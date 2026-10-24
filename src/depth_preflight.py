"""ADE-71 stage 1: raw delivery integrity and array round trip; not a FramePacket."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import shutil
import stat
import sys
import uuid
import zipfile

import numpy as np

from contract import ROOT, ContractError, fail, normalize_depth

KST = timezone(timedelta(hours=9))
MISSING = [
    {'item': 'full_precision_depth_intrinsics_fx_fy_cx_cy', 'owner': '도형준 제공 / 강석현 검토'},
    {'item': 'Brown_Conrady_to_rectified_pinhole_evidence', 'owner': '강석현 SDK·보정 검토 / 도형준 원본 제공'},
    {'item': 'device_profile_calibration_identity_evidence', 'owner': '도형준 제공 / 강석현 검토'},
    {'item': 'per_frame_capture_and_host_receive_timestamps', 'owner': '강석현 SDK backend / 도형준 수집'},
    {'item': 'specimen_id_capture_conditions_three_conditions', 'owner': '도형준 제공 / 강석현 기준 확인'},
    {'item': 'raw_65535_semantics', 'owner': '강석현 SDK backend / 도형준 장비 근거 제공'},
]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_json(path):
    def invalid(value):
        raise ValueError(f'nonfinite JSON token: {value}')
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)


def write_json_new(path, value):
    # Serialize first: NaN/Infinity cannot leave a partially serialized record.
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(text)


def check_hash(actual, expected, name):
    if actual != expected:
        fail('CHECKSUM_MISMATCH', f'{name}: expected {expected}, got {actual}')


def member_path(base, info):
    name = info.filename
    posix, windows = PurePosixPath(name), PureWindowsPath(name)
    if (not name or '\\' in name or ':' in name or posix.is_absolute()
            or windows.drive or windows.root or '..' in posix.parts
            or stat.S_ISLNK(info.external_attr >> 16)):
        fail('PATH_INVALID', f'unsafe ZIP member: {name}')
    candidate = (base / name).resolve()
    if not candidate.is_relative_to(base.resolve()):
        fail('PATH_INVALID', f'ZIP member escapes archive directory: {name}')
    return candidate


def read_scale(text):
    # Exact SDK console field, not the approximate intrinsics string or dtype.
    lines = [line.strip() for line in text.splitlines()
             if re.match(r'^\s*SCALE\b', line)]
    if len(lines) != 1:
        fail('UNIT_UNKNOWN', 'metadata.txt requires exactly one unambiguous SCALE field')
    match = re.fullmatch(r'SCALE\s+([^\s]+)', lines[0])
    if match is None:
        fail('UNIT_UNKNOWN', 'malformed SCALE field; no inferred fallback')
    try:
        scale = float(match[1])
    except ValueError:
        fail('UNIT_UNKNOWN', 'SCALE must be a positive finite numeric value')
    if not math.isfinite(scale) or scale <= 0:
        fail('UNIT_UNKNOWN', 'SCALE must be a positive finite numeric value')
    return scale, lines[0]


def load_raw(path, spec):
    with np.load(path, allow_pickle=False) as arrays:
        keys = arrays.files
        if keys != [spec['key']]:
            fail('NPZ_KEY_INVALID', f'expected only {spec["key"]}, got {keys}')
        raw = arrays[spec['key']].copy()
    if raw.dtype != np.dtype(spec['dtype']):
        fail('DEPTH_DTYPE_INVALID', f'expected {spec["dtype"]}, got {raw.dtype}')
    if raw.shape != tuple(spec['shape']):
        fail('DEPTH_SHAPE_INVALID', f'expected {spec["shape"]}, got {raw.shape}')
    return raw, {'keys': keys, 'shape': list(raw.shape), 'dtype': str(raw.dtype)}


def frame_stats(raw):
    row, column = raw.shape[0] // 2, raw.shape[1] // 2
    positive = int(np.count_nonzero(raw > 0))
    return {'pixel_count': int(raw.size), 'zero_count': int(np.count_nonzero(raw == 0)),
            'positive_count': positive, 'raw_65535_count': int(np.count_nonzero(raw == 65535)),
            'positive_ratio_full_image': positive / raw.size,
            'center_pixel_v_u': [row, column], 'center_raw': int(raw[row, column]),
            'raw_min': int(raw.min()), 'raw_max': int(raw.max())}


def verify_roundtrip(path, depth, mask):
    with np.load(path, allow_pickle=False) as arrays:
        if set(arrays.files) != {'depth_m', 'valid_mask'}:
            fail('ROUNDTRIP_MISMATCH', 'unexpected saved NPZ keys')
        for key, reference in [('depth_m', depth), ('valid_mask', mask)]:
            current = arrays[key]
            if (current.dtype != reference.dtype or current.shape != reference.shape
                    or not np.array_equal(current, reference)):
                fail('ROUNDTRIP_MISMATCH', f'{key}: dtype/shape/full values differ')
    return {'status': 'passed', 'comparison': 'dtype + shape + numpy.array_equal',
            'rtol': 0, 'atol': 0, 'depth_m_dtype': str(depth.dtype),
            'valid_mask_dtype': str(mask.dtype), 'shape': list(depth.shape)}


def new_run(output_root):
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        path = output_root / ('run_' + uuid.uuid4().hex)
        try:
            path.mkdir(exist_ok=False)
            return path
        except FileExistsError:
            continue
    fail('OUTPUT_COLLISION', 'could not reserve a new output directory')


def validate_receipt(receipt):
    for name, value in {'ZIP': receipt['zip_sha256'], **receipt['members']}.items():
        if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
            fail('RECEIPT_INVALID', f'{name}: SHA-256 must be 64 lowercase hex characters')
    # This CLI handles a raw depth stack, not arbitrary session/schema promotion.
    spec = receipt['raw_array']
    if (spec['dtype'] != 'uint16' or len(spec['shape']) != 3
            or any(type(n) is not int or n <= 0 for n in spec['shape'])):
        fail('RECEIPT_INVALID', 'requires uint16 stack with positive N,H,W dimensions')
    for name in (spec['file'], receipt['metadata_file'], receipt['capture_code_file']):
        if name not in receipt['members']:
            fail('RECEIPT_INVALID', f'missing required member in receipt: {name}')


def run_preflight(zip_path, receipt_path, output_root):
    zip_path, receipt_path = Path(zip_path).resolve(), Path(receipt_path).resolve()
    receipt = strict_json(receipt_path)
    validate_receipt(receipt)
    run = new_run(output_root)
    raw_dir, arrays_dir = run / 'originals', run / 'arrays'
    raw_dir.mkdir(); arrays_dir.mkdir()
    report = {
        'schema_version': '1.0.0', 'artifact_type': 'array_preflight_report',
        'tool_version': 'ade71-stage1-v1', 'delivery_id': receipt['delivery_id'],
        'status': 'failure', 'scope': 'array conversion and file integrity only',
        'is_frame_packet': False, 'common_session_approved': False,
        'accuracy_verified': False, 'geometry_semantics_approved': False,
        'processing_started_at': datetime.now(KST).isoformat(),
        'processing_time_notice': 'conversion time only; never a capture timestamp',
        'environment': {'python': sys.version, 'executable': sys.executable,
                        'numpy': np.__version__, 'os': platform.platform()},
        'source_zip': str(zip_path), 'receipt_path': str(receipt_path),
        'receipt_sha256': digest(receipt_path), 'expected_zip_sha256': receipt['zip_sha256'],
        'zip_crc': {'status': 'not_run'}, 'zip_sha256_before': None,
        'zip_sha256_after': None, 'original_hashes_before': {}, 'original_hashes_after': {},
        'originals_unchanged': None, 'frames': [], 'completed_frames': 0,
        'missing_information': MISSING,
        'warnings': ['65535 의미 미확인; 기존 finite·양수 기준에서 포함될 수 있음',
                     '유효 비율은 전체 영상 기준; 대상 물체 관측률·정확도가 아님',
                     '내참수 출력 문자열은 승인된 보정값으로 사용하지 않음'],
        'errors': [],
    }
    preserved_zip = raw_dir / 'depth_original.zip'
    try:
        report['zip_sha256_before'] = digest(zip_path)
        check_hash(report['zip_sha256_before'], receipt['zip_sha256'], 'source ZIP')
        with zip_path.open('rb') as source, preserved_zip.open('xb') as dest:
            shutil.copyfileobj(source, dest)
        report['original_hashes_before']['originals/depth_original.zip'] = digest(preserved_zip)
        check_hash(report['original_hashes_before']['originals/depth_original.zip'],
                   receipt['zip_sha256'], 'preserved ZIP')
        with zipfile.ZipFile(preserved_zip) as archive:
            members = archive.infolist()
            destinations = [member_path(raw_dir, info) for info in members]
            names = [info.filename for info in members]
            if len(names) != len(set(names)) or set(names) != set(receipt['members']):
                fail('ZIP_MEMBERS_INVALID', f'unexpected/missing/duplicate members: {names}')
            bad = archive.testzip()
            report['zip_crc'] = {'status': 'passed' if bad is None else 'failed', 'bad_member': bad}
            if bad is not None:
                fail('ZIP_CRC_INVALID', f'CRC mismatch: {bad}')
            for info, destination in zip(members, destinations):
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open('xb') as dest:
                    shutil.copyfileobj(source, dest)
                name = destination.relative_to(run).as_posix()
                report['original_hashes_before'][name] = digest(destination)
                check_hash(report['original_hashes_before'][name],
                           receipt['members'][info.filename], info.filename)
        # Read code as inert text: never import, exec or start its SDK pipeline.
        capture = (raw_dir / receipt['capture_code_file']).read_text(encoding='utf-8')
        report['capture_code'] = {'read_only': True, 'executed': False, 'character_count': len(capture)}
        scale, line = read_scale((raw_dir / receipt['metadata_file']).read_text(encoding='utf-8'))
        report['conversion'] = {
            'scale_to_m': scale, 'scale_source_member': receipt['metadata_file'], 'scale_source_line': line,
            'calculation': 'contract.normalize_depth: float64 multiplication, then float32',
            'invalid_raw_values': [0], 'mask_policy': 'finite & >0; invalid depth_m=0',
            'raw_65535_policy': 'included if finite and positive; meaning unconfirmed',
            'semantics_notice': 'normalize_depth default arithmetic reused; optical_axis_z approval not established',
        }
        spec = receipt['raw_array']
        raw, report['npz_observed'] = load_raw(raw_dir / spec['file'], spec)
        report['expected_frames'] = len(raw)
        for index, frame in enumerate(raw):
            item = {'source_member': spec['file'], 'source_member_sha256': receipt['members'][spec['file']],
                    'source_key': spec['key'], 'source_frame_index': index, **frame_stats(frame)}
            report['frames'].append(item)
            depth, mask = normalize_depth(frame, scale)
            item.update(valid_count=int(mask.sum()), valid_ratio_full_image=float(mask.mean()),
                        valid_65535_count=int(np.count_nonzero(mask & (frame == 65535))),
                        center_depth_m=float(depth[tuple(item['center_pixel_v_u'])]),
                        depth_m_min=float(depth.min()), depth_m_max=float(depth.max()))
            if not mask.any():
                fail('NO_VALID_DEPTH', f'raw frame {index} is entirely invalid; not approved')
            saved = arrays_dir / f'frame_{index:06d}.npz'
            with saved.open('xb') as stream:
                np.savez_compressed(stream, depth_m=depth, valid_mask=mask)
            item['output_file'] = saved.relative_to(run).as_posix()
            item['output_sha256'] = digest(saved)
            item['roundtrip'] = verify_roundtrip(saved, depth, mask)
            report['completed_frames'] += 1
    except (ContractError, OSError, UnicodeError, ValueError, KeyError, TypeError,
            zipfile.BadZipFile, EOFError) as error:
        report['errors'].append({'code': getattr(error, 'code', 'INPUT_CORRUPT'),
                                 'exception_type': type(error).__name__, 'message': str(error)})
    finally:
        try:
            report['zip_sha256_after'] = digest(zip_path)
            for name in report['original_hashes_before']:
                report['original_hashes_after'][name] = digest(run / name)
            report['originals_unchanged'] = (
                report['zip_sha256_before'] is not None
                and report['zip_sha256_before'] == report['zip_sha256_after']
                and report['original_hashes_before'] == report['original_hashes_after'])
            if not report['originals_unchanged']:
                fail('PRESERVATION_MISMATCH', 'source ZIP or preserved originals changed during inspection')
        except (ContractError, OSError) as error:
            report['errors'].append({'code': getattr(error, 'code', 'INPUT_CORRUPT'), 'message': str(error)})
        report['processing_finished_at'] = datetime.now(KST).isoformat()
    if not report['errors'] and report['completed_frames'] == report.get('expected_frames'):
        report['status'] = 'passed_array_preflight'
    write_json_new(run / 'inspection_report.json', report)
    return run, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', type=Path)
    parser.add_argument('--receipt', type=Path, required=True, help='delivery-specific expected hashes/spec')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'outputs/ade71_preflight')
    args = parser.parse_args(argv)
    try:
        run, report = run_preflight(args.zip, args.receipt, args.output_root)
    except (ContractError, OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        print(f'failure: {error}', file=sys.stderr)
        return 1
    print(f'{report["status"]}: {report["completed_frames"]} frame(s)')
    print(f'report: {run / "inspection_report.json"}')
    print('Array preflight only; 65535 meaning unconfirmed; no common session or accuracy approval.')
    for error in report['errors']:
        print(f'{error["code"]}: {error["message"]}', file=sys.stderr)
    return 0 if report['status'] == 'passed_array_preflight' else 1


if __name__ == '__main__':
    raise SystemExit(main())
