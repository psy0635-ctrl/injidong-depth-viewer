"""Synthetic file fixtures, never hardware evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_mobile_session import inspect_session, digest, inventory, load_contract

BASE = Path(os.environ['MOBILE_CONTRACT_ROOT']).resolve()
CONTRACT, BOUNDARY = load_contract(BASE)


def put(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')


class MobileIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = self.root / 'session'
        self.session.mkdir()
        frame = self.session / 'frame_000001'
        frame.mkdir()
        (self.session / 'raw').mkdir()
        (self.session / 'rgb').mkdir()
        raw = np.array([[1000, 1000], [1000, 0]], dtype='<u2')
        raw_path = self.session / 'raw/frame_000001_depth_z16.bin'
        raw_path.write_bytes(raw.tobytes())
        depth, valid = CONTRACT.normalize_depth(raw, .001)
        np.savez(frame / 'arrays.npz', depth_m=depth, valid_mask=valid)
        m = json.loads((BASE / 'examples/synthetic/frame_000001/metadata.json').read_text())
        m.update(session_id='synthetic_mobile', frame_id='frame_000001', source_path='mobile_device')
        m['sync'] = {'status': 'unverified', 'offset_ns': None, 'uncertainty_ns': None, 'tolerance_ns': None, 'evidence': None}
        m['provenance'].update(raw_file='raw/frame_000001_depth_z16.bin', raw_sha256=digest(raw_path), raw_unit='Z16', raw_scale_to_m=.001)
        m['storage']['sha256'] = digest(frame / 'arrays.npz')
        self.meta_path = frame / 'metadata.json'
        put(self.meta_path, m)
        self.meta = m
        put(self.session / 'frames.jsonl', {'frame_id': m['frame_id'], 'metadata_path': 'frame_000001/metadata.json'})
        image_path = self.session / 'rgb/phone_rgb_000001.png'
        Image.new('RGB', (3, 2), (20, 30, 40)).save(image_path)
        self.rgb = {'frame_id': m['frame_id'], 'session_id': m['session_id'], 'file': 'rgb/phone_rgb_000001.png', 'sha256': digest(image_path), 'width': 3, 'height': 2, 'encoding': 'RGB8', 'image_kind': 'original_rgb', 'time': {'ns': '12345', 'clock_domain': 'android_camera_sensor', 'origin': 'sensor'}, 'pair_status': 'unverified', 'pair_evidence': None, 'aligned_to_depth': False, 'alignment_method': None, 'calibration_id': 'android_phone_back_intrinsics_unrecorded_3x2', 'provenance_kind': 'synthetic'}
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.imu = {'schema_version': '1.0.0', 'session_id': m['session_id'], 'sample_id': 'synthetic_mobile_00000001', 'device_id': 'synthetic_fixture', 'source': 'phone', 'sensor_type': 'TYPE_GYROSCOPE', 'frame': 'android_phone_default_axes', 'time': {'ns': '12345', 'clock_domain': 'android_elapsed_realtime', 'origin': 'sensor'}, 'accel_m_s2': None, 'gyro_rad_s': [0, 0, 0], 'orientation_xyzw': None, 'gravity_included': False, 'provenance_kind': 'synthetic'}
        put(self.session / 'imu.jsonl', self.imu)
        self.summary = {'manifest_version': '1.0.0', 'session_id': m['session_id'], 'status': 'complete', 'sources': {'rgb': 'android_phone_back_camera', 'depth': 'intel_realsense_d405', 'imu': 'android_phone_sensors'}, 'counts': {'depth_frames': 1, 'phone_rgb_images': 1, 'imu_samples': 1}, 'files': {'depth_index': 'frames.jsonl', 'phone_rgb_index': 'rgb_index.jsonl', 'phone_rgb_images': 'rgb/', 'imu_samples': 'imu.jsonl', 'depth_arrays': '<frame_id>/arrays.npz', 'raw_depth': 'raw/'}, 'rgb_depth_alignment': {'status': 'unverified', 'aligned_to_depth': False, 'evidence': None}, 'transmission': {'status': 'not_configured', 'sent': False, 'reason': 'fixture'}}
        put(self.session / 'session.json', self.summary)

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self):
        before = inventory(self.session)
        try:
            return inspect_session(self.session, BASE)
        finally:
            after = inventory(self.session)
            self.assertEqual(after, before)
            # Optional persistent evidence lives outside each temporary input.
            audit = os.environ.get('MOBILE_TEST_AUDIT')
            if audit:
                with Path(audit).open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'test': self.id(), 'input_kind': 'synthetic_fixture',
                                             'before': before, 'after': after,
                                             'unchanged': before == after}) + '\n')

    def write_imu_rows(self, records):
        (self.session / 'imu.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in records), encoding='utf-8')
        self.summary['counts']['imu_samples'] = len(records)
        put(self.session / 'session.json', self.summary)

    def next_imu(self, ns='12346', sensor='TYPE_GYROSCOPE'):
        row = copy.deepcopy(self.imu)
        row['sample_id'] = 'synthetic_mobile_00000002'
        row['time']['ns'] = ns
        row['sensor_type'] = sensor
        if sensor == 'TYPE_LINEAR_ACCELERATION':
            row.update(gyro_rad_s=None, accel_m_s2=[0, 0, 0])
        return row

    def app_metadata_shape(self):
        # Deliberately injected real-valued flags exercise the app's validation
        # branch. These bytes and labels are synthetic, NEVER capture evidence.
        put(self.session / 'SYNTHETIC_NOTICE.json', {
            'data_kind': 'synthetic_test_fixture', 'hardware_capture': False,
            'reason': 'Injected app-shaped metadata to test the real-input guard.'})
        self.meta['capture_conditions']['notes'] = 'SYNTHETIC TEST ONLY; no device capture or calibration.'
        self.meta['capture_source'] = 'mobile_device'
        self.meta['provenance'].update(kind='real', synthetic_seed=None, synthetic_config=None,
                                      camera={'vendor': 'Intel', 'model': 'RealSense D405',
                                              'serial': None, 'firmware': None, 'sdk': None,
                                              'depth_profile_id': 'synthetic-pinhole-v1'})
        put(self.meta_path, self.meta)
        self.rgb['provenance_kind'] = 'real'
        self.imu['provenance_kind'] = 'real'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        put(self.session / 'imu.jsonl', self.imu)

    def append_depth_frame(self, shared_raw=False, shared_arrays=False):
        m = copy.deepcopy(self.meta)
        m['frame_id'] = 'frame_000002'
        directory = self.meta_path.parent if shared_arrays else self.session / 'frame_000002'
        directory.mkdir(exist_ok=True)
        if not shared_arrays:
            (directory / 'arrays.npz').write_bytes((self.meta_path.parent / 'arrays.npz').read_bytes())
        if not shared_raw:
            name = 'raw/frame_000002_depth_z16.bin'
            (self.session / name).write_bytes((self.session / m['provenance']['raw_file']).read_bytes())
            m['provenance']['raw_file'] = name
        path = directory / ('metadata_second.json' if shared_arrays else 'metadata.json')
        put(path, m)
        with (self.session / 'frames.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('\n' + json.dumps({'frame_id': m['frame_id'], 'metadata_path': path.relative_to(self.session).as_posix()}))
        self.summary['counts']['depth_frames'] = 2
        put(self.session / 'session.json', self.summary)
        return path, m

    def reject(self, text=None):
        before = inventory(self.session)
        with self.assertRaises((ValueError, OSError, KeyError, TypeError)) as caught:
            self.run_check()
        if text:
            self.assertIn(text, str(caught.exception))
        self.assertEqual(inventory(self.session), before)

    def assert_cli_report(self, exit_code, error_field=None):
        before = inventory(self.session)
        reports = self.root / 'reports'
        existing = set(reports.glob('*.json'))
        cmd = [sys.executable, '-B', '-X', 'utf8',
               str(Path(__file__).resolve().parents[1] / 'check_mobile_session.py'),
               str(self.session), '--contract-root', str(BASE), '--report-dir', str(reports)]
        process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        after = inventory(self.session)
        generated = set(reports.glob('*.json')) - existing
        audit = os.environ.get('MOBILE_CLI_AUDIT')
        if audit:
            audit_path = Path(audit)
            saved_reports = []
            for path in sorted(generated):
                saved = audit_path.parent / (audit_path.stem + '_reports') / path.name
                saved.parent.mkdir(exist_ok=True)
                saved.write_bytes(path.read_bytes())
                saved_reports.append(str(saved))
            with audit_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'test': self.id(), 'input_kind': 'synthetic_fixture',
                                         'command': cmd, 'exit_code': process.returncode,
                                         'stdout': process.stdout, 'stderr': process.stderr,
                                         'report_count': len(generated), 'saved_reports': saved_reports,
                                         'before_sha256': before, 'after_sha256': after,
                                         'input_unchanged': before == after}, allow_nan=False) + '\n')
        self.assertEqual(after, before)
        self.assertEqual(process.returncode, exit_code, process.stderr)
        self.assertEqual(process.stderr, '')
        self.assertEqual(len(generated), 1)
        self.assertEqual(len(process.stdout.strip().splitlines()), 1)
        report_path = Path(process.stdout.strip())
        self.assertIn(report_path, generated)

        def reject_nonfinite(value):
            raise AssertionError('nonfinite JSON token in CLI report: ' + value)

        report = json.loads(report_path.read_text(encoding='utf-8'), parse_constant=reject_nonfinite)
        self.assertEqual(report['status'], 'passed_mobile_file_checks' if exit_code == 0 else 'failed_mobile_file_checks')
        for name in ('geometry_verified', 'processing_ready', 'rgb_depth_alignment_verified', 'world_pose_verified'):
            self.assertIs(report[name], False)
        if exit_code:
            self.assertIsInstance(report['error'], str)
            self.assertTrue(report['error'].strip())
        if error_field:
            self.assertIn(error_field, report['error'])
        return report

    def test_synthetic_mobile_files_load_without_claiming_geometry(self):
        before = inventory(self.session)
        report = self.run_check()
        self.assertEqual(report['status'], 'passed_mobile_file_checks')
        self.assertEqual(report['data_kind'], 'synthetic')
        self.assertFalse(report['processing_ready'])
        self.assertFalse(report['geometry_verified'])
        self.assertEqual(inventory(self.session), before)
        f = next(CONTRACT.iter_frames(self.session))
        np.testing.assert_array_equal(CONTRACT.point_cloud_camera(f), np.array([[0, 0, 1], [.01, 0, 1], [0, .01, 1]], dtype=np.float32))

    def test_collecting_session_rejected(self):
        self.summary['status'] = 'collecting'
        put(self.session / 'session.json', self.summary)
        self.reject('session must be complete')

    def test_raw_hash_corruption(self):
        (self.session / self.meta['provenance']['raw_file']).write_bytes(b'12345678')
        self.reject('raw Z16 hash mismatch')

    def test_npz_hash_corruption(self):
        (self.meta_path.parent / 'arrays.npz').write_bytes(b'broken')
        self.reject('checksum mismatch')

    def test_absolute_metadata_path(self):
        put(self.session / 'frames.jsonl', {'frame_id': self.meta['frame_id'], 'metadata_path': str(self.meta_path)})
        self.reject('PATH_INVALID')

    def test_rgb_parent_traversal(self):
        self.rgb['file'] = '../escaped.png'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('PATH_INVALID')

    def test_rgb_unknown_frame(self):
        self.rgb['frame_id'] = 'unknown'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('unknown frame')

    def test_rgb_verified_claim_rejected(self):
        self.rgb['pair_status'] = 'verified'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('claims verified alignment')

    def test_rgb_missing_time_rejected(self):
        self.rgb['time'] = dict.fromkeys(('ns', 'clock_domain', 'origin'))
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('RGB time')

    def test_rgb_wrong_clock_domain_rejected(self):
        self.rgb['time']['clock_domain'] = 'android_elapsed_realtime'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('RGB time')

    def test_rgb_wrong_origin_rejected(self):
        self.rgb['time']['origin'] = 'host_receive'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('RGB time')

    def test_rgb_nondecimal_timestamp_rejected(self):
        self.rgb['time']['ns'] = '1.25'
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('decimal string')

    def test_app_shaped_fixture_camera_vendor_rejected(self):
        self.app_metadata_shape()
        self.meta['provenance']['camera']['vendor'] = 'Synthetic wrong vendor'
        put(self.meta_path, self.meta)
        self.reject('Depth camera identity')

    def test_app_shaped_fixture_camera_model_checked_on_each_frame(self):
        self.app_metadata_shape()
        path, m = self.append_depth_frame()
        m['provenance']['camera']['model'] = 'Synthetic wrong model'
        put(path, m)
        self.reject('Depth camera identity')

    def test_app_shaped_fixture_profile_mismatch_rejected(self):
        self.app_metadata_shape()
        self.meta['provenance']['camera']['depth_profile_id'] = 'synthetic-wrong-profile'
        put(self.meta_path, self.meta)
        self.reject('Depth profile/calibration')

    def test_app_shaped_fixture_null_device_details_allowed_and_reported(self):
        self.app_metadata_shape()
        report = self.run_check()
        self.assertEqual(report['status'], 'passed_mobile_file_checks')
        self.assertEqual(report['depth_frames'][0]['missing_camera_information'], ['serial', 'firmware', 'sdk'])
        self.assertFalse(report['geometry_verified'])
        self.assertFalse(report['processing_ready'])

    def test_capture_source_mismatch_already_rejected(self):
        self.meta['capture_source'] = 'mobile_device'
        put(self.meta_path, self.meta)
        self.reject()

    def test_imu_time_regression_within_sensor_rejected(self):
        self.write_imu_rows([self.imu, self.next_imu('12344')])
        self.reject('IMU time regression')

    def test_imu_large_integer_time_regression_rejected(self):
        self.imu['time']['ns'] = '9007199254740993'
        self.write_imu_rows([self.imu, self.next_imu('9007199254740992')])
        self.reject('IMU time regression')

    def test_imu_interleaved_sensor_times_allowed(self):
        last = self.next_imu('12346')
        last['sample_id'] = 'synthetic_mobile_00000003'
        self.write_imu_rows([self.imu, self.next_imu('100', 'TYPE_LINEAR_ACCELERATION'), last])
        report = self.run_check()
        self.assertEqual(report['counts']['imu_samples'], 3)
        self.assertFalse(report['world_pose_verified'])

    def test_imu_equal_times_allowed_with_warning(self):
        self.write_imu_rows([self.imu, self.next_imu('12345')])
        report = self.run_check()
        self.assertEqual(report['status'], 'passed_mobile_file_checks')
        warning = next(w for w in report['warnings'] if w['code'] == 'IMU_EQUAL_TIMESTAMP')
        self.assertEqual(warning['sample_id'], 'synthetic_mobile_00000002')

    def test_imu_mixed_device_rejected(self):
        other = self.next_imu()
        other['device_id'] = 'synthetic_other_device'
        self.write_imu_rows([self.imu, other])
        self.reject('IMU device identity mismatch')

    def test_imu_foreign_session_already_rejected(self):
        self.imu['session_id'] = 'synthetic_other_session'
        put(self.session / 'imu.jsonl', self.imu)
        self.reject('IMU identity mismatch')

    def test_imu_foreign_sample_id_rejected(self):
        self.imu['sample_id'] = 'synthetic_other_session_00000001'
        put(self.session / 'imu.jsonl', self.imu)
        self.reject('IMU sample session identity')

    def test_imu_unrelated_sensor_vector_already_rejected(self):
        self.imu['accel_m_s2'] = [1, 2, 3]
        put(self.session / 'imu.jsonl', self.imu)
        self.reject('unrelated vector')

    def test_imu_wrong_gravity_flag_already_rejected(self):
        self.imu['gravity_included'] = True
        put(self.session / 'imu.jsonl', self.imu)
        self.reject('gravity flag')

    def test_unreferenced_collection_files_report_all_paths(self):
        extras = {'rgb/phone_rgb_000002.png': self.session / self.rgb['file'],
                  'raw/frame_000002_depth_z16.bin': self.session / self.meta['provenance']['raw_file'],
                  'frame_000002/metadata.json': self.meta_path,
                  'frame_000002/arrays.npz': self.meta_path.parent / 'arrays.npz'}
        (self.session / 'frame_000002').mkdir()
        for name, source in extras.items():
            (self.session / name).write_bytes(source.read_bytes())
        before = inventory(self.session)
        with self.assertRaises(ValueError) as caught:
            self.run_check()
        details = caught.exception.details['unreferenced_collection_files']
        self.assertEqual({item['path'] for item in details}, set(extras))
        self.assertTrue(all(item['reason'] for item in details))
        self.assertEqual(before, inventory(self.session))

    def test_auxiliary_files_allowed_and_distinguished(self):
        names = ['README.md', 'capture.log', 'notes.json', 'rgb/note.txt', 'raw/capture.log']
        for name in names:
            (self.session / name).write_text('Synthetic auxiliary note', encoding='utf-8')
        report = self.run_check()
        self.assertEqual(report['status'], 'passed_mobile_file_checks')
        self.assertEqual({item['path'] for item in report['additional_files']}, set(names))

    def test_auxiliary_metadata_named_file_is_not_frame_packet(self):
        (self.session / 'notes').mkdir()
        put(self.session / 'notes/metadata.json', {'purpose': 'Synthetic collection notes only'})
        report = self.run_check()
        self.assertEqual(report['status'], 'passed_mobile_file_checks')
        self.assertEqual(report['additional_files'][0]['path'], 'notes/metadata.json')

    def test_two_synthetic_frames_with_distinct_paths_allowed(self):
        self.append_depth_frame()
        report = self.run_check()
        self.assertEqual(report['counts']['depth_frames'], 2)
        self.assertEqual(report['data_kind'], 'synthetic')
        self.assertFalse(report['geometry_verified'])

    def test_shared_raw_path_between_frames_rejected(self):
        self.append_depth_frame(shared_raw=True)
        self.reject('duplicate collection path')

    def test_shared_arrays_path_between_frames_rejected(self):
        self.append_depth_frame(shared_arrays=True)
        self.reject('duplicate collection path')

    def test_duplicate_metadata_reference_already_rejected(self):
        with (self.session / 'frames.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('\n' + json.dumps({'frame_id': 'frame_000002', 'metadata_path': 'frame_000001/metadata.json'}))
        self.reject()

    def test_duplicate_rgb_path_alias_already_rejected(self):
        other = copy.deepcopy(self.rgb)
        other['file'] = 'rgb/./phone_rgb_000001.png'
        (self.session / 'rgb_index.jsonl').write_text(json.dumps(self.rgb) + '\n' + json.dumps(other), encoding='utf-8')
        self.reject('duplicate RGB file')

    def test_missing_depth_collection_files_already_rejected(self):
        for name in ('frame_000001/metadata.json', 'frame_000001/arrays.npz', 'raw/frame_000001_depth_z16.bin'):
            with self.subTest(path=name):
                path = self.session / name
                contents = path.read_bytes()
                path.unlink()
                try:
                    self.reject()
                finally:
                    path.write_bytes(contents)

    def test_cli_unreferenced_files_preserve_structured_report(self):
        (self.session / 'raw/leftover.bin').write_bytes(b'\x00\x00')
        before = inventory(self.session)
        cmd = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'check_mobile_session.py'),
               str(self.session), '--contract-root', str(BASE), '--report-dir', str(self.root / 'reports')]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(Path(result.stdout.strip()).read_text(encoding='utf-8'))
        self.assertEqual(report['unreferenced_collection_files'][0]['path'], 'raw/leftover.bin')
        self.assertFalse(report['geometry_verified'])
        self.assertFalse(report['processing_ready'])
        self.assertEqual(inventory(self.session), before)

    def test_summary_counts_must_match(self):
        self.summary['counts']['imu_samples'] = 2
        put(self.session / 'session.json', self.summary)
        self.reject('summary count differs')

    def test_duplicate_imu_samples(self):
        path = self.session / 'imu.jsonl'
        path.write_text(json.dumps(self.imu) + '\n' + json.dumps(self.imu) + '\n')
        self.reject('duplicate IMU sample')

    def test_bad_imu_quaternion(self):
        self.imu.update(sensor_type='TYPE_ROTATION_VECTOR', gyro_rad_s=None, orientation_xyzw=[0, 0, 0, 0])
        put(self.session / 'imu.jsonl', self.imu)
        self.reject('quaternion not unit length')

    def test_missing_rgb_file(self):
        (self.session / self.rgb['file']).unlink()
        self.reject()

    def test_managed_incomplete_gate_preserved(self):
        put(self.session / '.ade71-session.json', {'format': 'ade71-publication-v1', 'completion_required': True})
        self.reject('SESSION_UNCOMMITTED')

    def test_rgba_not_mislabeled_rgb8(self):
        path = self.session / self.rgb['file']
        Image.new('RGBA', (3, 2)).save(path)
        self.rgb['sha256'] = digest(path)
        put(self.session / 'rgb_index.jsonl', self.rgb)
        self.reject('RGBA requires format review')

    def test_duplicate_json_keys(self):
        (self.session / 'session.json').write_text('{"status":"complete","status":"failed"}')
        self.reject('duplicate JSON key')

    def test_cli_summary_array_failure_report(self):
        put(self.session / 'session.json', [])
        self.assert_cli_report(1, 'session.json top-level')

    def test_cli_summary_null_failure_report(self):
        put(self.session / 'session.json', None)
        self.assert_cli_report(1, 'session.json top-level')

    def test_cli_transmission_array_failure_report(self):
        self.summary['transmission'] = []
        put(self.session / 'session.json', self.summary)
        self.assert_cli_report(1, 'session.json.transmission')

    def test_cli_transmission_null_failure_report(self):
        self.summary['transmission'] = None
        put(self.session / 'session.json', self.summary)
        self.assert_cli_report(1, 'session.json.transmission')

    def test_cli_success_and_failure_exit_reports(self):
        report = self.assert_cli_report(0)
        self.assertEqual(report['data_kind'], 'synthetic')
        self.summary['counts']['imu_samples'] = 99
        put(self.session / 'session.json', self.summary)
        self.assert_cli_report(1, 'summary count differs')

    def test_cli_refuses_report_inside_input(self):
        before = inventory(self.session)
        cmd = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'check_mobile_session.py'), str(self.session), '--contract-root', str(BASE), '--report-dir', str(self.session / 'reports')]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(inventory(self.session), before)


if __name__ == '__main__':
    unittest.main()
