"""Read-only mobile file intake; never authorizes geometry, cloud or inference."""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import platform
import re
import stat
import sys
import uuid
import zipfile

sys.dont_write_bytecode = True

import numpy as np
from PIL import Image

MOBILE_COMMIT = 'b9f370ac94901b1dfce2c4c64018380d5036e967'
RGB_INDEX_POLICY = 'mobile-rgb-index-compat-review-v1'
RGB_INDEX_NAMES = {'phone_rgb_index': 'rgb_index.jsonl', 'images_index': 'images.jsonl'}
COMMON_FILES = {'depth_index': 'frames.jsonl', 'phone_rgb_images': 'rgb/',
                'imu_samples': 'imu.jsonl', 'depth_arrays': '<frame_id>/arrays.npz',
                'raw_depth': 'raw/'}


class IntakeError(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def require(condition, message):
    if not condition:
        raise IntakeError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def parse(text):
    def invalid(value):
        raise IntakeError(f'nonfinite JSON token: {value}')
    return json.loads(text, object_pairs_hook=strict_pairs, parse_constant=invalid)


def read_json(path):
    return parse(path.read_text(encoding='utf-8'))


def rows(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield parse(line)


def require_unlinked(path):
    # lstat before resolve/exists: dangling links and Windows junctions count.
    for component in (Path(path).absolute(), *Path(path).absolute().parents):
        info = component.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                f'linked input not supported: {component.name}')


def inventory(root):
    require_unlinked(root)
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob('*')):
        require_unlinked(path)
        require(path.resolve().is_relative_to(root), 'input alias escapes session')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def load_contract(root):
    root = Path(root).resolve()
    expected = read_json(Path(__file__).with_name('baseline_hashes.json'))
    for name, value in expected.items():
        require(digest(root / name) == value, f'baseline mismatch: {name}')
    for name in ('contract', 'session_boundary'):
        if name in sys.modules:
            require(Path(sys.modules[name].__file__).resolve() == root / 'src' / f'{name}.py',
                    f'conflicting loaded module: {name}')
    sys.path.insert(0, str(root / 'src'))
    contract = importlib.import_module('contract')
    boundary = importlib.import_module('session_boundary')
    return contract, boundary


def stamp(value):
    require(isinstance(value, dict) and set(value) == {'ns', 'clock_domain', 'origin'}, 'invalid time object')
    if value['ns'] is None:
        require(all(v is None for v in value.values()), 'partly missing timestamp')
    else:
        require(isinstance(value['ns'], str) and re.fullmatch(r'[0-9]+', value['ns']), 'ns must be decimal string')
        require(isinstance(value['clock_domain'], str) and bool(value['clock_domain'].strip()), 'missing clock domain')
        require(value['origin'] in ('sensor', 'host_receive', 'synthetic', 'replay_host'), 'invalid time origin')


def vector(value, size):
    require(isinstance(value, list) and len(value) == size, 'wrong sensor vector length')
    require(all(type(v) in (int, float) and math.isfinite(v) for v in value), 'nonfinite/missing sensor value')


def collection_kind(name, session, frame_directories, rgb_index_name):
    """Recognize the pinned writer's collection files, not arbitrary sidecars."""
    path = Path(name)
    parts = tuple(part.lower() for part in path.parts)
    if parts[0] == 'rgb' and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'):
        return f'RGB image not referenced by {rgb_index_name}'
    if parts[0] == 'raw' and path.suffix.lower() == '.bin':
        return 'raw Depth buffer not referenced by any FramePacket'
    if parts[-1] in ('metadata.json', 'arrays.npz'):
        directory = (session / path).parent
        is_frame = directory in frame_directories or re.fullmatch(r'(frame|d405)_[0-9]+', directory.name.lower())
        if not is_frame:
            # A notes/metadata.json sidecar is not automatically a FramePacket.
            # For other names, recognize the packet shape without approving it.
            try:
                metadata = read_json(directory / 'metadata.json')
                is_frame = isinstance(metadata, dict) and {'schema_version', 'frame_id', 'depth', 'intrinsics', 'provenance'} <= set(metadata)
            except (ValueError, OSError, UnicodeError):
                is_frame = False
        if is_frame:
            return 'frame metadata/arrays not referenced by frames.jsonl/FramePacket storage'
    return None


def select_rgb_index(session, files, selection):
    require(type(files) is dict, 'session.json.files must be an object')
    keys = selection['candidate_keys']
    require(len(keys) == 1, 'exactly one RGB index key required')
    key = keys[0]
    declared = files[key]
    selection.update(selected_key=key, declared_path=declared if type(declared) is str else None,
                     declared_path_type=type(declared).__name__, status='declared')
    name = RGB_INDEX_NAMES[key]
    require(type(declared) is str and declared == name, 'RGB index key/path combination mismatch')
    require(files == {**COMMON_FILES, key: name}, 'unexpected mobile file layout')
    entries = selection['candidate_entries']
    require(len(entries) == 1 and entries[0]['name'] == name,
            'declared RGB index must be the only candidate entry')
    path = session / name
    require_unlinked(path)
    require(stat.S_ISREG(path.lstat().st_mode), 'RGB index must be a regular file')
    require(path.resolve().is_relative_to(session), 'RGB index path escapes session')
    selection.update(status='selected', used_relative_path=name)
    selection['sha256'] = digest(path)
    return path


def inspect_session(session, contract_root):
    selection = {'policy_id': RGB_INDEX_POLICY, 'status': 'not_selected',
                 'candidate_keys': [], 'candidate_entries': [], 'selected_key': None,
                 'declared_path': None, 'used_relative_path': None, 'sha256': None}
    try:
        session = Path(session)
        require_unlinked(session)
        for path in sorted(session.iterdir()):
            if path.name.casefold() in RGB_INDEX_NAMES.values():
                info = path.lstat()
                linked = stat.S_ISLNK(info.st_mode) or bool(
                    getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                kind = 'link_or_reparse' if linked else 'file' if stat.S_ISREG(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'special'
                selection['candidate_entries'].append({'name': path.name, 'kind': kind})
        return _inspect_session(session, contract_root, selection)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, EOFError, zipfile.BadZipFile) as error:
        selection['error'] = str(error)
        details = dict(error.details) if isinstance(error, IntakeError) else {}
        details['rgb_index'] = selection
        raise IntakeError(str(error), details) from error


def _inspect_session(session, contract_root, selection):
    contract, boundary = load_contract(contract_root)
    session = Path(session).resolve()
    require(session.is_dir(), 'session directory missing')
    before = None
    try:
        boundary.guard_read(session)
        summary = read_json(session / 'session.json')
        require(isinstance(summary, dict), 'session.json top-level must be a JSON object')
        files = summary.get('files', {})
        if type(files) is dict:
            selection['candidate_keys'] = [key for key in RGB_INDEX_NAMES if key in files]
        require(summary.get('manifest_version') == '1.0.0', 'unsupported mobile manifest')
        require(summary.get('status') == 'complete', 'session must be complete; failed/collecting not accepted')
        sid = summary.get('session_id')
        require(isinstance(sid, str) and bool(sid.strip()), 'missing session_id')
        require(summary.get('sources') == {'rgb': 'android_phone_back_camera', 'depth': 'intel_realsense_d405', 'imu': 'android_phone_sensors'}, 'unexpected source identity')
        require(summary.get('rgb_depth_alignment') == {'status': 'unverified', 'aligned_to_depth': False, 'evidence': None}, 'alignment contract changed; review required')
        transmission = summary.get('transmission', {})
        require(isinstance(transmission, dict), 'session.json.transmission must be a JSON object')
        require(transmission.get('status') == 'not_configured' and transmission.get('sent') is False, 'transport contract changed; review required')
        rgb_index = select_rgb_index(session, files, selection)
        before = inventory(session)
        require(before[rgb_index.name] == selection['sha256'], 'RGB index changed during selection')
        referenced = {}
        frame_directories = set()
        warnings = []

        def reference(path, owner):
            # Windows Path equality includes case aliases; resolve removes ./.
            require(path not in referenced,
                    f'duplicate collection path: {path.relative_to(session).as_posix()} '
                    f'({referenced.get(path)}; {owner})')
            referenced[path] = owner

        reference(rgb_index, 'RGB index')

        entries = list(rows(session / 'frames.jsonl'))
        require(bool(entries), 'no Depth frames')
        for entry in entries:
            require(isinstance(entry, dict) and set(entry) == {'frame_id', 'metadata_path'}, 'invalid frame index')
            metadata_path = boundary.relative_path(session, entry['metadata_path'])
            frame_directories.add(metadata_path.parent)
            reference(metadata_path, f"metadata for {entry['frame_id']}")
            metadata = read_json(metadata_path)
            arrays_path = boundary.relative_path(metadata_path.parent, metadata['storage']['file'])
            reference(arrays_path, f"arrays for {entry['frame_id']}")
        frames = list(contract.iter_frames(session))
        mapping = {}
        depth_details = []
        kinds = set()
        for frame in frames:
            m = frame.metadata
            require(m['session_id'] == sid and m['source_path'] == 'mobile_device', 'mobile frame identity mismatch')
            require(m['sync']['status'] == 'unverified' and m['pose'] is None and m['imu'] is None, 'pose/sync contract changed; review required')
            kind = m['provenance']['kind']
            require(m['capture_source'] == ('mobile_device' if kind == 'real' else 'synthetic'), 'capture source mismatch')
            camera = m['provenance']['camera']
            missing_camera = []
            if kind == 'real':
                require(camera['vendor'] == 'Intel' and camera['model'] == 'RealSense D405',
                        f"Depth camera identity differs from pinned app: {m['frame_id']}")
                require(camera['depth_profile_id'] == m['intrinsics']['calibration_id'],
                        f"Depth profile/calibration mismatch: {m['frame_id']}")
                missing_camera = [key for key in ('serial', 'firmware', 'sdk') if camera[key] is None]
                if missing_camera:
                    warnings.append({'code': 'DEPTH_CAMERA_INFORMATION_MISSING', 'frame_id': m['frame_id'],
                                     'fields': missing_camera, 'reason': 'App permits null; actual device information unconfirmed.'})
            kinds.add(kind)
            mapping[m['frame_id']] = frame
            raw = boundary.relative_path(session, m['provenance']['raw_file'])
            reference(raw, f"raw Depth for {m['frame_id']}")
            require(digest(raw) == m['provenance']['raw_sha256'], 'raw Z16 hash mismatch')
            require(m['provenance']['raw_unit'] == 'Z16', 'raw encoding mismatch')
            scale = m['provenance']['raw_scale_to_m']
            require(type(scale) in (int, float) and math.isfinite(scale) and scale > 0, 'missing SDK scale')
            # Metadata currently does not record source stride. Do not infer layout.
            size = raw.stat().st_size
            minimum = frame.depth_m.size * 2
            require(size >= minimum and size % 2 == 0, 'raw Z16 byte count impossible')
            raw_values = np.frombuffer(raw.read_bytes(), dtype='<u2')
            depth_details.append({'frame_id': m['frame_id'], 'shape': list(frame.depth_m.shape),
                                  'valid_depth_ratio': float(frame.valid_mask.mean()),
                                  'raw_bytes': size, 'minimum_packed_bytes': minimum,
                                  'raw_65535_word_count': int(np.count_nonzero(raw_values == 65535)),
                                  'camera': camera, 'missing_camera_information': missing_camera,
                                  'camera_information_scope': 'recorded_metadata_only' if kind == 'real' else 'synthetic_fixture',
                                  'geometry_verified': False})
        require(len(kinds) == 1, 'mixed real/synthetic frame provenance')
        rgb_count = 0
        seen_images = set()
        rgb_fields = set('frame_id session_id file sha256 width height encoding image_kind time pair_status pair_evidence aligned_to_depth alignment_method calibration_id provenance_kind'.split())
        for row in rows(rgb_index):
            require(isinstance(row, dict) and set(row) == rgb_fields, 'RGB fields mismatch')
            require(row['session_id'] == sid and row['frame_id'] in mapping, 'RGB references unknown frame')
            require(row['provenance_kind'] in kinds, 'RGB provenance mismatch')
            require(row['pair_status'] == 'unverified' and row['pair_evidence'] is None and row['aligned_to_depth'] is False and row['alignment_method'] is None, 'RGB claims verified alignment; review required')
            require(isinstance(row['calibration_id'], str) and row['calibration_id'].startswith('android_phone_back_intrinsics_unrecorded_'), 'unexpected phone calibration record')
            require(row['encoding'] == 'RGB8' and row['image_kind'] == 'original_rgb', 'unexpected RGB encoding/kind')
            stamp(row['time'])
            require(row['time']['ns'] is not None and row['time']['clock_domain'] == 'android_camera_sensor'
                    and row['time']['origin'] == 'sensor', 'unexpected/missing RGB time for pinned app')
            for key in ('width', 'height'):
                require(type(row[key]) is int and row[key] > 0, 'invalid RGB dimensions')
            image_path = boundary.relative_path(session, row['file'])
            require(image_path not in seen_images, 'duplicate RGB file')
            seen_images.add(image_path)
            reference(image_path, f"RGB for {row['frame_id']}")
            require(digest(image_path) == row['sha256'], 'RGB hash mismatch')
            with Image.open(image_path) as image:
                image.load()
                require(image.format == 'PNG' and image.mode == 'RGB' and image.size == (row['width'], row['height']), 'PNG must match RGB8 dimensions/mode; RGBA requires format review')
            rgb_count += 1
        imu_count = 0
        seen_samples = set()
        sensors = set()
        device_id = None
        sensor_times = {}
        imu_fields = set('schema_version session_id sample_id device_id source sensor_type frame time accel_m_s2 gyro_rad_s orientation_xyzw gravity_included provenance_kind'.split())
        sensor_map = {'TYPE_ACCELEROMETER': ('accel_m_s2', True), 'TYPE_LINEAR_ACCELERATION': ('accel_m_s2', False), 'TYPE_GYROSCOPE': ('gyro_rad_s', False), 'TYPE_ROTATION_VECTOR': ('orientation_xyzw', False)}
        for row in rows(session / 'imu.jsonl'):
            require(isinstance(row, dict) and set(row) == imu_fields, 'IMU fields mismatch')
            require(row['schema_version'] == '1.0.0' and row['session_id'] == sid and row['source'] == 'phone' and row['frame'] == 'android_phone_default_axes', 'IMU identity mismatch')
            require(row['provenance_kind'] in kinds, 'IMU provenance mismatch')
            sample = row['sample_id']
            require(isinstance(sample, str) and bool(sample) and sample not in seen_samples, 'invalid/duplicate IMU sample')
            require(re.fullmatch(re.escape(sid) + r'_[0-9]{8,}', sample), 'IMU sample session identity mismatch')
            seen_samples.add(sample)
            require(isinstance(row['device_id'], str) and bool(row['device_id']), 'missing IMU device identity')
            if device_id is None:
                device_id = row['device_id']
            require(row['device_id'] == device_id, f'IMU device identity mismatch: {sample}')
            sensor = row['sensor_type']
            require(sensor in sensor_map, 'unexpected IMU sensor')
            field, gravity = sensor_map[sensor]
            require(row['gravity_included'] is gravity, 'gravity flag mismatch')
            for name in ('accel_m_s2', 'gyro_rad_s', 'orientation_xyzw'):
                if name == field:
                    vector(row[name], 4 if name == 'orientation_xyzw' else 3)
                else:
                    require(row[name] is None, 'sensor row contains unrelated vector')
            if field == 'orientation_xyzw':
                require(abs(np.linalg.norm(row[field]) - 1) <= 1e-5, 'IMU quaternion not unit length')
            stamp(row['time'])
            require(row['time']['ns'] is not None and row['time']['clock_domain'] == 'android_elapsed_realtime' and row['time']['origin'] == 'sensor', 'unexpected IMU time domain')
            # One default sensor of each type is registered by this app. Compare
            # integer ns within that type only, never across sensor streams.
            current = int(row['time']['ns'])
            previous = sensor_times.get(sensor)
            if previous is not None:
                require(current >= previous, f'IMU time regression: {sensor}, {sample}, {previous} -> {current}')
                if current == previous:
                    warnings.append({'code': 'IMU_EQUAL_TIMESTAMP', 'sensor_type': sensor,
                                     'sample_id': sample, 'ns': row['time']['ns'],
                                     'reason': 'Equality retained; strict duplicate-time policy is unconfirmed.'})
            sensor_times[sensor] = current
            sensors.add(sensor)
            imu_count += 1
        counts = summary.get('counts', {})
        actual = {'depth_frames': len(frames), 'phone_rgb_images': rgb_count, 'imu_samples': imu_count}
        require(set(counts) == set(actual) and all(type(counts[k]) is int and counts[k] == actual[k] for k in actual), 'summary count differs from saved records')
        require(rgb_count > 0 and imu_count > 0, 'full mobile intake requires RGB and IMU samples')
        unreferenced = []
        additional = []
        for name in before:
            if (session / name).resolve() in referenced or name in ('session.json', 'frames.jsonl', 'imu.jsonl'):
                continue
            reason = collection_kind(name, session, frame_directories, rgb_index.name)
            if reason:
                unreferenced.append({'path': name, 'reason': reason})
            else:
                additional.append({'path': name, 'reason': 'Additional file outside recognized collection naming; not validated as capture data.'})
        if unreferenced:
            raise IntakeError('unreferenced collection files: ' + ', '.join(item['path'] for item in unreferenced),
                              {'unreferenced_collection_files': unreferenced, 'additional_files': additional,
                               'input_sha256': before})
        return {'status': 'passed_mobile_file_checks', 'data_kind': next(iter(kinds)),
                'rgb_index': selection, 'viewer_launched': False,
                'sdk_values_independently_verified': False, 'common_framepacket_fully_validated': False,
                'counts': actual, 'imu_sensor_types': sorted(sensors), 'depth_frames': depth_details,
                'warnings': warnings, 'additional_files': additional, 'unreferenced_collection_files': [],
                'core_loader_compatible': True, 'geometry_verified': False,
                'processing_ready': False, 'rgb_depth_alignment_verified': False,
                'world_pose_verified': False, 'server_uploaded': False,
                'mobile_commit_reference': MOBILE_COMMIT,
                'remaining': ['actual_device_capture_validation', 'raw_stride_and_distortion_evidence',
                              'frame_bound_full_precision_calibration_and_scale_evidence',
                              'raw_65535_meaning_policy', 'team_review_of_sidecar_and_loader_integration'],
                'input_sha256': before}
    finally:
        if before is not None:
            require(inventory(session) == before, 'input changed during check')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--contract-root', required=True, type=Path)
    parser.add_argument('--report-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    # Check output relation without loading or changing the contract.
    source, output = args.session.absolute(), args.report_dir.resolve()
    baseline = args.contract_root.resolve()
    for directory in (source.resolve(), baseline):
        require(not output.is_relative_to(directory) and not directory.is_relative_to(output), 'report directory must be disjoint from input and baseline')
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / ('mobile_check_' + uuid.uuid4().hex + '.json')
    try:
        report = inspect_session(source, baseline)
        exit_code = 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, EOFError, zipfile.BadZipFile) as error:
        report = {'status': 'failed_mobile_file_checks', 'error': str(error), 'processing_ready': False,
                  'geometry_verified': False, 'rgb_depth_alignment_verified': False, 'world_pose_verified': False,
                  'viewer_launched': False, 'sdk_values_independently_verified': False,
                  'common_framepacket_fully_validated': False}
        if isinstance(error, IntakeError):
            report.update(error.details)
        exit_code = 1
    report['environment'] = {'python': platform.python_version(), 'numpy': np.__version__, 'platform': platform.system()}
    with report_path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(str(report_path))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
