"""ADE-71 file intake, exclusive FramePacket session and full cloud verification.

The intake basis is a LOCAL sidecar, not a new core/team schema or SDK backend.
Evidence references bind supplied claims to hashed files; physical approval is external.
"""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import sys
import time
import zipfile

import numpy as np

import contract
from contract import (FramePacket, ContractError, fail, normalize_depth,
                      point_cloud_camera, validate_frame, validate_json, volume_preflight)
from depth_preflight import (KST, check_hash, digest, load_raw, new_run, strict_json,
                             write_json_new)
from replay import compare_frame, file_hashes, positive_int
from viewer_data import read_session
from session_boundary import (relative_path, disjoint_output, packet_input_dirs,
                              RUN_MARKER, SESSION_MARKER, COMPLETION, FORMAT, _staging,
                              load_processing_result)

ERRORS = (ContractError, OSError, ValueError, KeyError, TypeError, UnicodeError,
          zipfile.BadZipFile, EOFError)


def relative_file(base, value):
    return relative_path(base, value)


def equal_array(actual, expected, name):
    if (actual.dtype != expected.dtype or actual.shape != expected.shape
            or not np.array_equal(actual, expected)):
        fail('ROUNDTRIP_MISMATCH', f'{name}: dtype/shape/full values differ')


def load_evidence(basis, base):
    files = basis['evidence_files']
    if not isinstance(files, dict):
        fail('EVIDENCE_REQUIRED', 'evidence_files must be a mapping')
    paths = {}
    for key, item in files.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            fail('EVIDENCE_REQUIRED', 'safe evidence identifier required')
        path = relative_file(base, item['file'])
        check_hash(digest(path), item['sha256'], key)
        paths[key] = path
    return paths


def evidence_ref(value, paths, field):
    if not isinstance(value, str) or value not in paths:
        fail('EVIDENCE_REQUIRED', f'{field}: hashed evidence file required')


def geometry_guard(metadata, basis, paths):
    if metadata['intrinsics']['model'] != 'rectified_pinhole':
        fail('CALIBRATION_UNCONFIRMED', 'rectified pinhole required; Brown Conrady not assumed compatible')
    if metadata['provenance']['kind'] == 'real':
        claims = basis.get('real_geometry')
        if not isinstance(claims, dict):
            fail('EVIDENCE_REQUIRED', 'real_geometry claims not received')
        for field in ('scale', 'semantics', 'intrinsics', 'rectification', 'device_profile'):
            evidence_ref(claims.get(field), paths, field)
        if claims['intrinsics_precision'] != 'full_precision':
            fail('CALIBRATION_UNCONFIRMED', 'rounded intrinsics cannot be promoted')
        if (claims['calibration_id'] != metadata['intrinsics']['calibration_id']
                or claims['depth_profile_id'] != metadata['provenance']['camera']['depth_profile_id']
                or claims['source_sha256'] != basis['source']['sha256']):
            fail('EVIDENCE_MISMATCH', 'geometry claims must bind calibration/profile/raw hash')


def raw_input(basis, base):
    if basis.get('blocked_requirements'):
        fail('INTAKE_BLOCKED', json.dumps(basis['blocked_requirements'], ensure_ascii=False))
    source = basis['source']
    if (source['dtype'] != 'uint16' or len(source['shape']) != 3
            or any(type(n) is not int or n <= 0 for n in source['shape'])):
        fail('DEPTH_SHAPE_INVALID', 'positive NxHxW uint16 raw stack required')
    raw_path = relative_file(base, source['file'])
    check_hash(digest(raw_path), source['sha256'], 'raw source')
    raw, _ = load_raw(raw_path, source)
    paths = load_evidence(basis, base)
    conversion = basis['conversion']
    # Validate even when the stack has no frames; no dtype/unit fallback.
    normalize_depth(raw[0], conversion['scale_to_m'], conversion['semantics'])
    invalid = conversion['invalid_values']
    if (not isinstance(invalid, list) or 0 not in invalid
            or any(type(v) is not int or not 0 <= v <= 65535 for v in invalid)):
        fail('INVALID_POLICY', 'explicit uint16 invalid values including 0 required')
    policy = conversion['raw_65535_policy']
    if policy not in ('unconfirmed', 'invalid', 'valid_distance'):
        fail('INVALID_POLICY', 'unknown 65535 policy')
    if (policy == 'invalid') != (65535 in invalid):
        fail('INVALID_POLICY', '65535 invalid list and policy disagree')
    if np.any(raw == 65535):
        if policy == 'unconfirmed':
            fail('RAW_65535_UNCONFIRMED', '65535 present without profile-specific meaning')
        evidence_ref(conversion['raw_65535_evidence'], paths, 'raw_65535')
    return raw, raw_path, paths


def require_processing_basis(frame, basis_path):
    """A saved core packet alone cannot establish real calibration/invalid policy."""
    if basis_path is None:
        if frame.metadata['provenance']['kind'] == 'real':
            fail('EVIDENCE_REQUIRED', 'real processing requires the original conversion basis')
        return []
    basis_path = Path(basis_path).resolve()
    basis = strict_json(basis_path)
    prepared, _, paths = prepare_frames(basis, basis_path.parent)
    matches = [reference for reference in prepared
               if reference.metadata['frame_id'] == frame.metadata['frame_id']
               and reference.metadata['session_id'] == frame.metadata['session_id']]
    if len(matches) != 1:
        fail('FRAME_MAPPING_INVALID', 'real packet not uniquely bound to supplied basis')
    original = matches[0]
    reference = copy.deepcopy(original.metadata)
    current = copy.deepcopy(frame.metadata)
    reference['storage']['sha256'] = current['storage']['sha256']
    if reference != current:
        fail('EVIDENCE_MISMATCH', 'real packet metadata differs from its conversion basis')
    equal_array(frame.depth_m, original.depth_m, 'source depth_m')
    equal_array(frame.valid_mask, original.valid_mask, 'source valid_mask')
    target = original.target_mask
    if (target is None) != (frame.target_mask is None):
        fail('TARGET_INVALID', 'real target array missing from conversion basis')
    if target is not None:
        equal_array(frame.target_mask, target, 'real source target_mask')
    return input_directories(basis_path, basis, paths)


def input_directories(basis_path, basis, paths):
    """Every received directory, including resolved referenced-file aliases."""
    base = Path(basis_path).resolve().parent
    folders = [base, relative_file(base, basis['source']['file']).parent]
    folders += [path.parent for path in paths.values()]
    folders += [relative_file(base, entry['target']['file']).parent
                for entry in basis['frames'] if entry.get('target')]
    return folders


def target_input(entry, metadata, base, paths):
    spec = entry.get('target')
    if spec is None:
        return None
    for field in ('frame_id', 'session_id', 'specimen_id'):
        if field not in spec or spec[field] != metadata[field]:
            fail('TARGET_INVALID', f'target {field} does not match packet')
    if metadata['target_mask_info'] != {'source': spec.get('source'), 'version': spec.get('version')}:
        fail('TARGET_INVALID', 'target source/version does not match core metadata')
    path = relative_file(base, spec['file'])
    check_hash(digest(path), spec['sha256'], 'target')
    with np.load(path, allow_pickle=False) as arrays:
        if arrays.files != ['target_mask']:
            fail('TARGET_INVALID', 'only target_mask key permitted')
        target = arrays['target_mask'].copy()
    evidence_ref(spec['depth_alignment_evidence'], paths, 'target depth alignment')
    return target


def prepare_frames(basis, base):
    """Shared, write-free full source/frame/conversion checks for CLI and API."""
    raw, raw_path, paths = raw_input(basis, base)
    source, conversion = basis['source'], basis['conversion']
    entries = basis['frames']
    if (len(entries) != len(raw) or any(type(e['source_frame_index']) is not int for e in entries)
            or [e['source_frame_index'] for e in entries] != list(range(len(raw)))):
        fail('FRAME_MAPPING_INVALID', 'every source frame must map once, in source order')
    prepared = []
    ids = set()
    session_ids = set()
    for entry in entries:
        m = copy.deepcopy(entry['metadata'])
        validate_json(m, 'frame')
        geometry_guard(m, basis, paths)
        if m['frame_id'] in ids:
            fail('FRAME_MAPPING_INVALID', 'duplicate frame_id')
        ids.add(m['frame_id']); session_ids.add(m['session_id'])
        if m['replay_time'] != {'ns': None, 'clock_domain': None, 'origin': None}:
            fail('TIMESTAMP_INVALID', 'conversion must not fabricate replay time')
        p = m['provenance']
        if p['raw_scale_to_m'] != conversion['scale_to_m'] or m['depth']['semantics'] != conversion['semantics']:
            fail('EVIDENCE_MISMATCH', 'metadata scale/semantics disagree with explicit conversion')
        if p['raw_sha256'] != source['sha256'] or p['raw_file'] != 'raw/source.npz':
            fail('EVIDENCE_MISMATCH', 'metadata must reference preserved raw/source.npz and original hash')
        depth, mask = normalize_depth(raw[entry['source_frame_index']], conversion['scale_to_m'],
                                     conversion['semantics'], conversion['invalid_values'])
        target = target_input(entry, m, base, paths)
        frame = FramePacket(m, depth, mask, target)
        validate_frame(frame)
        prepared.append(frame)
    if len(session_ids) != 1:
        fail('FRAME_MAPPING_INVALID', 'one session_id required')
    return prepared, raw_path, paths


def convert_frames(basis, base, session):
    prepared, raw_path, paths = prepare_frames(basis, base)
    session = Path(session).resolve()
    if not (session.parent / RUN_MARKER).is_file():
        fail('SESSION_UNCOMMITTED', 'conversion is a staging helper for a managed run')
    # All preconditions checked before creating the session. Partial I/O remains a failure.
    session.mkdir(exist_ok=False)
    write_json_new(session / SESSION_MARKER, {'format': FORMAT, 'completion_required': True})
    (session / 'raw').mkdir()
    with raw_path.open('rb') as src, (session / 'raw/source.npz').open('xb') as dest:
        shutil.copyfileobj(src, dest)
    check_hash(digest(session / 'raw/source.npz'), basis['source']['sha256'], 'preserved raw')
    manifest = []
    for index, frame in enumerate(prepared):
        folder = session / f'frame_{index:06d}'
        folder.mkdir()
        payload = {'depth_m': frame.depth_m, 'valid_mask': frame.valid_mask}
        if frame.target_mask is not None:
            payload['target_mask'] = frame.target_mask
        with (folder / 'arrays.npz').open('xb') as stream:
            np.savez_compressed(stream, **payload)
        frame.metadata['storage']['sha256'] = digest(folder / 'arrays.npz')
        write_json_new(folder / 'metadata.json', frame.metadata)
        manifest.append({'frame_id': frame.metadata['frame_id'],
                         'metadata_path': f'{folder.name}/metadata.json'})
    with (session / 'frames.jsonl').open('x', encoding='utf-8') as stream:
        for entry in manifest:
            stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + '\n')
    reloaded = read_session(session)
    if [f.metadata['frame_id'] for f in reloaded] != [f.metadata['frame_id'] for f in prepared]:
        fail('FRAME_MAPPING_INVALID', 'initial reload lost/reordered source frames')
    for original, current in zip(prepared, reloaded):
        compare_frame(original, current)
    return prepared, raw_path, paths


def process_frame(frame, config):
    """SDK-free camera-coordinate cloud; volume remains null with an actual reason."""
    validate_frame(frame)
    inputs = require_processing_basis(frame, config.get('basis_path')) + packet_input_dirs(frame)
    if config.get('input_dir') is not None:
        inputs.append(config['input_dir'])
    destination = disjoint_output(config['output_dir'], inputs)
    config_version = config.get('config_version', 'ade71-file-v1')
    if not isinstance(config_version, str) or not config_version:
        fail('CONFIG_INVALID', 'nonempty config_version required')
    points = point_cloud_camera(frame)
    if points.dtype != np.float32 or points.shape != (int(frame.valid_mask.sum()), 3) or not np.isfinite(points).all():
        fail('RESULT_INVALID', 'finite float32 Nx3 cloud required')
    destination.mkdir(exist_ok=False)
    path = destination / 'points.npz'
    with path.open('xb') as stream:
        np.savez_compressed(stream, points_m=points)
    expected_hash = digest(path)
    with np.load(path, allow_pickle=False) as arrays:
        if arrays.files != ['points_m']:
            fail('RESULT_INVALID', 'unexpected cloud keys')
        equal_array(arrays['points_m'], points, 'points_m')
    check_hash(digest(path), expected_hash, 'reloaded cloud')
    try:
        volume_preflight(frame)
        reason = 'VOLUME_NOT_IMPLEMENTED: grid/coverage/method validation and integration pending'
    except ContractError as error:
        reason = str(error)
    result = {'schema_version': '1.0.0', 'frame_id': frame.metadata['frame_id'],
              'status': 'success', 'stage': 'point_cloud',
              'point_cloud': {'file': 'points.npz', 'key': 'points_m', 'sha256': expected_hash,
                              'unit': 'm', 'frame': 'camera', 'point_count': len(points)},
              'volume_m3': None, 'volume_method': None, 'assumptions': [],
              'valid_depth_ratio': float(frame.valid_mask.mean()),
              'provenance_kind': frame.metadata['provenance']['kind'],
              'config_version': config_version, 'errors': [], 'warnings': [reason]}
    validate_json(result, 'processing')
    name = 'processing.pending.json' if config.get('publication_pending') else 'processing.json'
    write_json_new(destination / name, result)
    return result


def verify_session(session, results, repeats, expected_points=None, *, basis_path=None):
    if type(repeats) is not int or repeats < 1:
        fail('REPLAY_INVALID', 'positive repeat count required')
    session, results = Path(session).resolve(), Path(results).resolve()
    disjoint_output(results, [session])
    before = file_hashes(session)
    baseline = read_session(session)
    from session_auxiliary import check_auxiliary
    auxiliary = check_auxiliary(session, baseline)
    if len({f.metadata['session_id'] for f in baseline}) != 1:
        fail('FRAME_MAPPING_INVALID', 'mixed session IDs')
    for frame in baseline:
        disjoint_output(results, require_processing_basis(frame, basis_path))
    results.mkdir(exist_ok=False)
    saved = [(point_cloud_camera(f), process_frame(f, {'output_dir': results / f'frame_{i:06d}',
              'basis_path': basis_path, 'publication_pending': True}))
             for i, f in enumerate(baseline)]
    if expected_points is not None:
        expected = np.asarray(expected_points, dtype=np.float64)
        if (len(saved) != 1 or expected.shape != saved[0][0].shape or not np.isfinite(expected).all()
                or not np.allclose(saved[0][0], expected, rtol=0, atol=1e-7)):
            fail('RESULT_INVALID', 'synthetic expected full coordinates differ (atol=1e-7 m)')
    iterations = []
    for repeat in range(repeats):
        current = read_session(session)
        if [f.metadata['frame_id'] for f in baseline] != [f.metadata['frame_id'] for f in current]:
            fail('FRAME_MAPPING_INVALID', 'replay frame ordering changed')
        row = []
        for index, (left, right) in enumerate(zip(baseline, current)):
            compare_frame(left, right)
            points, result = saved[index]
            equal_array(point_cloud_camera(right), points, 'recomputed full points_m')
            path = results / f'frame_{index:06d}' / result['point_cloud']['file']
            check_hash(digest(path), result['point_cloud']['sha256'], 'saved cloud during replay')
            with np.load(path, allow_pickle=False) as arrays:
                equal_array(arrays['points_m'], points, 'reloaded full points_m')
            raw_file = right.metadata['provenance']['raw_file']
            if raw_file is not None:
                check_hash(digest(relative_file(session, raw_file)),
                           right.metadata['provenance']['raw_sha256'], 'session raw')
            row.append({'frame_id': right.metadata['frame_id'], 'capture_time': right.metadata['capture_time'],
                        'replay_time': {'ns': str(time.time_ns()), 'clock_domain': 'pc_unix_utc', 'origin': 'replay_host'}})
        iterations.append({'repeat': repeat + 1, 'frames': row})
    after = file_hashes(session)
    if before != after:
        fail('PRESERVATION_MISMATCH', 'session files changed during replay')
    return {'completed_repeats': repeats, 'frame_count': len(baseline), 'iterations': iterations,
            'auxiliary': auxiliary,
            'session_hashes': after, 'session_unchanged': True,
            'array_comparison': 'dtype/shape/full numpy.array_equal, zero tolerance',
            'point_comparison': 'full float32 Nx3 values, count, file SHA-256; camera coordinates in m',
            'expected_points_checked': expected_points is not None,
            'frames': [result for _, result in saved]}


def run_conversion(basis_path, output_root, repeats=3, expected_points=None):
    if type(repeats) is not int or repeats < 1:
        fail('REPLAY_INVALID', 'positive repeat count required')
    basis_path = Path(basis_path).resolve()
    # Output must be separate from intake directory; never add records to raw inputs.
    output_root = Path(output_root).resolve()
    disjoint_output(output_root, [basis_path.parent])
    basis = strict_json(basis_path)
    sources = [basis_path, relative_file(basis_path.parent, basis['source']['file'])]
    paths = load_evidence(basis, basis_path.parent)
    sources += list(paths.values())
    for entry in basis['frames']:
        if entry.get('target'):
            sources.append(relative_file(basis_path.parent, entry['target']['file']))
    disjoint_output(output_root, input_directories(basis_path, basis, paths))
    hashes = {str(p): digest(p) for p in sources}
    run = new_run(output_root)
    report = {'artifact_type': 'session_boundary_validation', 'status': 'failure',
              'started_at': datetime.now(KST).isoformat(), 'basis_path': str(basis_path),
              'environment': {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__,
                              'numpy_import': np.__file__, 'contract_import': contract.__file__,
                              'venv_prefix': sys.prefix, 'os': platform.platform()},
              'team_approval': False, 'physical_evidence_verified': False, 'accuracy_verified': False,
              'source_hashes_before': hashes, 'errors': [], 'requested_repeats': repeats}
    try:
        write_json_new(run / RUN_MARKER, {'format': FORMAT, 'completion_required': True})
        # Preserve supplied basis/evidence for review outside core metadata.
        evidence_dir = run / 'evidence'
        evidence_dir.mkdir()
        with basis_path.open('rb') as src, (evidence_dir / 'basis.json').open('xb') as dest:
            shutil.copyfileobj(src, dest)
        for key, path in paths.items():
            with path.open('rb') as src, (evidence_dir / (key + path.suffix)).open('xb') as dest:
                shutil.copyfileobj(src, dest)
            check_hash(digest(evidence_dir / (key + path.suffix)), digest(path), key)
        with _staging(run):
            prepared, _, _ = convert_frames(basis, basis_path.parent, run / 'pending_session')
            report['source_frame_mapping'] = [
                {'source_file': basis['source']['file'], 'source_sha256': basis['source']['sha256'],
                 'source_key': basis['source']['key'], 'source_frame_index': entry['source_frame_index'],
                 'frame_id': frame.metadata['frame_id'], 'session_id': frame.metadata['session_id'],
                 'capture_time': frame.metadata['capture_time'], 'capture_source': frame.metadata['capture_source']}
                for entry, frame in zip(basis['frames'], prepared)]
            report.update(verify_session(run / 'pending_session', run / 'pending_results', repeats,
                                        expected_points, basis_path=basis_path))
    except Exception as error:
        report['errors'].append({'code': getattr(error, 'code', 'INPUT_CORRUPT' if isinstance(error, ERRORS) else 'INTERNAL_ERROR'),
                                 'exception_type': type(error).__name__, 'message': str(error)})
    finally:
        try:
            report['source_hashes_after'] = {p: digest(p) for p in hashes}
            report['originals_unchanged'] = hashes == report['source_hashes_after']
            if not report['originals_unchanged']:
                fail('PRESERVATION_MISMATCH', 'intake source changed')
        except ERRORS as error:
            report['errors'].append({'code': getattr(error, 'code', 'INPUT_CORRUPT'), 'message': str(error)})
        report['finished_at'] = datetime.now(KST).isoformat()
    try:
        if not report['errors'] and report.get('completed_repeats') == repeats:
            # Prepare durable report before publishing. validation.json is the final commit record.
            report['status'] = 'passed_file_boundary_validation'
            write_json_new(run / 'validation.pending.json', report)
            rename_new(run / 'pending_session', run / 'session', run)
            rename_new(run / 'pending_results', run / 'results', run)
            for path in (run / 'results').glob('frame_*/processing.pending.json'):
                rename_new(path, path.with_name('processing.json'), run)
            rename_new(run / 'validation.pending.json', run / 'validation.json', run)
            # Last record only after every publication operation. Missing record
            # blocks public readers even if all subsequent quarantine I/O fails.
            write_json_new(run / '.ade71-complete.pending.json', {
                'format': FORMAT, 'validation_sha256': digest(run / 'validation.json'),
                'manifest_sha256': digest(run / 'session/frames.jsonl'),
                'processing_sha256': {p.relative_to(run).as_posix(): digest(p)
                                      for p in sorted((run / 'results').glob('frame_*/processing.json'))}})
            rename_new(run / '.ade71-complete.pending.json', run / COMPLETION, run)
        else:
            quarantine(run)
            write_json_new(run / 'validation.json', report)
    except Exception as error:
        report['status'] = 'failure'
        report['errors'].append({'code': getattr(error, 'code', 'OUTPUT_COMMIT_FAILED'), 'message': str(error)})
        quarantine(run)
        # A pending success record is an abandoned attempt, never the final validation.json.
        write_json_new(run / 'validation.json', report)
    return run, report


def rename_new(source, destination, run):
    """Only move this newly reserved run's own artifacts, with no replacement."""
    source, destination, run = source.resolve(), destination.resolve(), run.resolve()
    if source == run or not source.is_relative_to(run) or not destination.is_relative_to(run):
        fail('PATH_INVALID', 'publication paths must stay inside the new run')
    if destination.exists():
        fail('OUTPUT_COLLISION', f'will not replace {destination}')
    source.rename(destination)


def quarantine(run):
    """Retain incomplete output but remove canonical session/result entry points."""
    # A failed run must not retain its commit record. No failed path after a
    # completed commit is supported; this also covers a partial record write.
    completion = run / COMPLETION
    if completion.exists():
        completion.unlink()
    for folder in ('pending_session', 'session'):
        path = run / folder / 'frames.jsonl'
        if path.exists():
            rename_new(path, path.with_name('frames.failed.jsonl'), run)
    for folder in ('pending_results', 'results'):
        for path in (run / folder).glob('frame_*/processing.json'):
            rename_new(path, path.with_name('processing.uncommitted.json'), run)
    path = run / 'validation.pending.json'
    if path.exists():
        rename_new(path, run / 'validation.uncommitted.json', run)
    path = run / 'validation.json'
    if path.exists():
        rename_new(path, run / 'validation.final.uncommitted.json', run)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--repeat', type=positive_int, default=3)
    parser.add_argument('--expected-points', type=Path)
    args = parser.parse_args(argv)
    try:
        expected = strict_json(args.expected_points) if args.expected_points else None
        run, report = run_conversion(args.basis, args.output_root, args.repeat, expected)
    except ERRORS as error:
        print(f'failure: {type(error).__name__}: {error}', file=sys.stderr)
        return 1
    print(f'{report["status"]}: {run / "validation.json"}')
    for error in report['errors']:
        print(f'{error["code"]}: {error["message"]}', file=sys.stderr)
    return 0 if report['status'] == 'passed_file_boundary_validation' else 1


if __name__ == '__main__':
    raise SystemExit(main())
