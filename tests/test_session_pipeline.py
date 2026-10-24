"""Temporary files only: source/geometry failures, full storage and replay boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from contract import ContractError, volume_preflight
from depth_preflight import digest
from make_ade71_session_intake import create_synthetic
import session_pipeline as pipeline
from session_auxiliary import attach_target, check_auxiliary
from viewer_data import read_session


class SessionPipelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.intake = create_synthetic(self.base / 'intake')
        self.basis_path = self.intake / 'basis.json'
        self.basis = json.loads(self.basis_path.read_text(encoding='utf-8'))
        self.output = self.base / 'outputs'

    def save(self):
        self.basis_path.write_text(json.dumps(self.basis), encoding='utf-8')

    def run_it(self, expected=None):
        self.save()
        return pipeline.run_conversion(self.basis_path, self.output, 3, expected)

    def assert_failed(self, code):
        run, report = self.run_it()
        self.assertEqual(report['status'], 'failure')
        self.assertIn(code, [e['code'] for e in report['errors']], report)
        self.assertTrue(report['originals_unchanged'])
        self.assertTrue((run / 'validation.json').exists())
        return run, report

    def raw(self, data):
        raw = np.asarray(data, dtype=np.uint16)
        np.savez_compressed(self.intake / 'source.npz', depth_raw=raw)
        self.basis['source']['sha256'] = digest(self.intake / 'source.npz')
        self.basis['source']['shape'] = list(raw.shape)
        self.basis['frames'][0]['metadata']['provenance']['raw_sha256'] = self.basis['source']['sha256']

    def test_full_synthetic_roundtrip_row_major_cloud_time_and_hashes(self):
        expected = [[0, 0, 1], [.01, 0, 1], [0, .01, 1]]
        original = copy.deepcopy(self.basis['frames'][0]['metadata'])
        run, report = self.run_it(expected)
        self.assertEqual(report['status'], 'passed_file_boundary_validation', report['errors'])
        self.assertEqual(report['completed_repeats'], 3)
        self.assertTrue(report['expected_points_checked'])
        self.assertFalse(report['team_approval'])
        self.assertTrue(report['originals_unchanged'])
        frame = read_session(run / 'session')[0]
        self.assertEqual(frame.metadata['capture_time'], original['capture_time'])
        self.assertEqual(frame.metadata['capture_source'], 'synthetic')
        self.assertIsNone(frame.metadata['replay_time']['ns'])
        for iteration in report['iterations']:
            self.assertEqual(iteration['frames'][0]['capture_time'], original['capture_time'])
            self.assertEqual(iteration['frames'][0]['replay_time']['origin'], 'replay_host')
        np.testing.assert_array_equal(frame.depth_m, [[1, 1], [1, 0]])
        np.testing.assert_array_equal(frame.valid_mask, [[True, True], [True, False]])
        with np.load(run / 'results/frame_000000/points.npz', allow_pickle=False) as saved:
            self.assertEqual(saved['points_m'].dtype, np.float32)
            np.testing.assert_array_equal(saved['points_m'], np.asarray(expected, dtype=np.float32))
        result = report['frames'][0]
        self.assertEqual(result['point_cloud']['point_count'], 3)
        self.assertEqual(result['point_cloud']['unit'], 'm')
        self.assertEqual(result['point_cloud']['sha256'], digest(run / 'results/frame_000000/points.npz'))
        self.assertIsNone(result['volume_m3'])
        self.assertIn('TARGET_UNAVAILABLE', result['warnings'][0])

    def test_rerun_uses_new_folder_without_overwriting(self):
        first, _ = self.run_it()
        before = pipeline.file_hashes(first)
        second, _ = self.run_it()
        self.assertNotEqual(first, second)
        self.assertEqual(before, pipeline.file_hashes(first))

    def test_unknown_scale_semantics_and_all_invalid(self):
        for value in (None, 0, -1):
            with self.subTest(scale=value):
                self.basis['conversion']['scale_to_m'] = value
                self.assert_failed('UNIT_UNKNOWN')
        self.basis['conversion']['scale_to_m'] = .001
        self.basis['conversion']['semantics'] = 'ray_distance'
        self.assert_failed('SEMANTICS_UNSUPPORTED')
        self.basis['conversion']['semantics'] = 'optical_axis_z'
        self.raw([[[0, 0], [0, 0]]])
        self.assert_failed('NO_VALID_DEPTH')

    def test_unknown_65535_not_removed_or_approved(self):
        self.raw([[[65535, 1000], [1000, 0]]])
        run, _ = self.assert_failed('RAW_65535_UNCONFIRMED')
        self.assertFalse((run / 'session').exists())
        self.basis['conversion']['raw_65535_policy'] = 'invalid'
        self.basis['conversion']['invalid_values'] = [0, 65535]
        self.assert_failed('EVIDENCE_REQUIRED')

    def test_65535_explicit_profile_policy_and_hash_evidence(self):
        self.raw([[[65535, 1000], [1000, 0]]])
        evidence = self.intake / 'policy.txt'
        evidence.write_text('SYNTHETIC policy fixture: 65535 means invalid', encoding='utf-8')
        self.basis['evidence_files'] = {'policy': {'file': 'policy.txt', 'sha256': digest(evidence)}}
        self.basis['conversion'].update(raw_65535_policy='invalid', invalid_values=[0, 65535], raw_65535_evidence='policy')
        run, report = self.run_it()
        self.assertEqual(report['status'], 'passed_file_boundary_validation')
        frame = read_session(run / 'session')[0]
        self.assertFalse(frame.valid_mask[0, 0])
        self.assertEqual(frame.depth_m[0, 0], 0)

    def test_raw_hash_mismatch(self):
        self.basis['source']['sha256'] = '0' * 64
        self.assert_failed('CHECKSUM_MISMATCH')

    def test_duplicate_and_missing_mapping(self):
        self.basis['frames'][0]['source_frame_index'] = 1
        self.assert_failed('FRAME_MAPPING_INVALID')
        self.basis['frames'] = []
        self.assert_failed('FRAME_MAPPING_INVALID')

    def test_schema_and_dtype_shape_failures(self):
        m = self.basis['frames'][0]['metadata']
        m['imaginary_rgb'] = True
        self.assert_failed('SCHEMA_INVALID')
        del m['imaginary_rgb']
        m['intrinsics']['width'] = 3
        self.assert_failed('INTRINSICS_INVALID')

    def test_real_geometry_missing_rounded_or_misbound(self):
        m = self.basis['frames'][0]['metadata']
        m['capture_source'] = 'pc_camera'
        m['provenance'].update(kind='real', camera={'vendor': 'fixture', 'model': 'fixture',
            'serial': None, 'firmware': None, 'sdk': None, 'depth_profile_id': 'profile-test'},
            synthetic_seed=None, synthetic_config=None)
        self.basis['real_geometry'] = {}
        self.assert_failed('EVIDENCE_REQUIRED')
        evidence = self.intake / 'geometry.txt'
        evidence.write_text('mock claims; not an actual calibration or SDK result', encoding='utf-8')
        self.basis['evidence_files'] = {'g': {'file': evidence.name, 'sha256': digest(evidence)}}
        claims = {key: 'g' for key in ('scale', 'semantics', 'intrinsics', 'rectification', 'device_profile')}
        claims.update(intrinsics_precision='rounded', calibration_id=m['intrinsics']['calibration_id'],
                      depth_profile_id='profile-test', source_sha256=self.basis['source']['sha256'])
        self.basis['real_geometry'] = claims
        self.assert_failed('CALIBRATION_UNCONFIRMED')
        claims['intrinsics_precision'] = 'full_precision'
        claims['depth_profile_id'] = 'different'
        self.assert_failed('EVIDENCE_MISMATCH')

    def test_capture_absence_preserved_and_replay_fabrication_rejected(self):
        m = self.basis['frames'][0]['metadata']
        m['capture_time'] = {'ns': None, 'clock_domain': None, 'origin': None}
        run, report = self.run_it()
        self.assertEqual(report['status'], 'passed_file_boundary_validation')
        self.assertEqual(read_session(run / 'session')[0].metadata['capture_time'], m['capture_time'])
        m['replay_time'] = {'ns': '123', 'clock_domain': 'pc_unix_utc', 'origin': 'replay_host'}
        self.assert_failed('TIMESTAMP_INVALID')

    def test_array_save_and_reload_failures_not_success(self):
        with patch.object(pipeline.np, 'savez_compressed', side_effect=OSError('disk failure mock')):
            self.assert_failed('INPUT_CORRUPT')
        with patch.object(pipeline, 'read_session', side_effect=ContractError('INPUT_CORRUPT', 'reload mock')):
            self.assert_failed('INPUT_CORRUPT')

    def test_cloud_save_failure_and_report_write_failure_exit_one(self):
        with patch.object(pipeline, 'process_frame', side_effect=OSError('cloud disk failure mock')):
            self.assert_failed('INPUT_CORRUPT')
        self.save()
        original = pipeline.write_json_new
        def broken_report(path, value):
            if Path(path).name in ('validation.json', 'validation.pending.json'):
                raise OSError('report disk failure mock')
            return original(path, value)
        with patch.object(pipeline, 'write_json_new', side_effect=broken_report):
            self.assertEqual(pipeline.main(['--basis', str(self.basis_path), '--output-root', str(self.output)]), 1)

    def test_multiframe_source_mapping_and_session_id_guard(self):
        self.raw([[[1000, 1000], [1000, 0]], [[2000, 0], [2000, 2000]]])
        entry = copy.deepcopy(self.basis['frames'][0])
        entry['source_frame_index'] = 1
        entry['metadata']['frame_id'] = 'synthetic_000002'
        entry['metadata']['capture_time']['ns'] = '2000000000'
        self.basis['frames'].append(entry)
        run, report = self.run_it()
        self.assertEqual(report['status'], 'passed_file_boundary_validation')
        self.assertEqual(report['frame_count'], 2)
        self.assertEqual([e['source_frame_index'] for e in report['source_frame_mapping']], [0, 1])
        np.testing.assert_array_equal(read_session(run / 'session')[1].depth_m, [[2, 0], [2, 2]])
        entry['metadata']['session_id'] = 'wrong-session'
        self.assert_failed('FRAME_MAPPING_INVALID')

    def test_full_coordinate_difference_even_when_count_and_hash_match(self):
        run, _ = self.run_it()
        original = pipeline.point_cloud_camera
        def wrong(frame):
            values = original(frame)
            values[-1, 0] += .01
            return values
        with patch.object(pipeline, 'point_cloud_camera', side_effect=wrong):
            with self.assertRaises(ContractError):
                pipeline.verify_session(run / 'session', self.base / 'wrong_points', 2,
                                        [[0, 0, 1], [.01, 0, 1], [0, .01, 1]])

    def test_replay_saved_cloud_tamper_detected(self):
        run, _ = self.run_it()
        original = pipeline.read_session
        count = 0
        results = self.base / 'cloud_tamper'
        def mutate(path):
            nonlocal count
            count += 1
            if count == 2:
                with (results / 'frame_000000/points.npz').open('ab') as stream:
                    stream.write(b'changed')
            return original(path)
        with patch.object(pipeline, 'read_session', side_effect=mutate):
            with self.assertRaises(ContractError) as error:
                pipeline.verify_session(run / 'session', results, 2)
        self.assertEqual(error.exception.code, 'CHECKSUM_MISMATCH')

    def test_target_keeps_missing_pixels_and_volume_failure(self):
        run, _ = self.run_it()
        frame = read_session(run / 'session')[0]
        target = np.ones((2, 2), dtype=bool)
        attached = attach_target(frame, target, 'synthetic model fixture', 'model-v1')
        np.testing.assert_array_equal(attached.target_mask, target)
        np.testing.assert_array_equal(attached.valid_mask, frame.valid_mask)
        self.assertTrue(attached.target_mask[1, 1])
        with self.assertRaises(ContractError):
            attach_target(frame, target.astype(np.uint8), 'fixture', 'v1')
        with self.assertRaises(ContractError):
            volume_preflight(attached)

    def test_path_escape_and_output_inside_input_rejected(self):
        self.basis['source']['file'] = '../intake/source.npz'
        self.save()
        with self.assertRaises(ContractError):
            pipeline.run_conversion(self.basis_path, self.output)
        with self.assertRaises(ContractError):
            pipeline.run_conversion(self.basis_path, self.intake / 'out')

    def test_cli_success_and_blocked_failure_codes(self):
        common = [sys.executable, '-B', '-X', 'utf8', str(ROOT / 'src/session_pipeline.py'),
                  '--basis', str(self.basis_path), '--output-root', str(self.output)]
        result = subprocess.run(common, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.basis['blocked_requirements'] = [{'item': 'calibration missing', 'owner': 'fixture'}]
        self.save()
        result = subprocess.run(common, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1)
        self.assertIn('INTAKE_BLOCKED', result.stderr)


# Define a separate fixture class without inherited test methods.
class AuxiliaryBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        intake = create_synthetic(self.base / 'intake')
        run, _ = pipeline.run_conversion(intake / 'basis.json', self.base / 'out')
        self.session = run / 'session'
        self.frames = read_session(self.session)

    def annotation(self):
        target = np.ones((2, 2), dtype=bool)
        np.savez_compressed(self.session / 'model_mask.npz', target_mask=target)
        m = self.frames[0].metadata
        return {'schema_version': '1.0.0', 'session_id': m['session_id'], 'frame_id': m['frame_id'],
                'specimen_id': m['specimen_id'], 'mask_file': 'model_mask.npz', 'mask_key': 'target_mask',
                'sha256': digest(self.session / 'model_mask.npz'), 'width': 2, 'height': 2,
                'class_name': 'clay', 'source': 'synthetic model fixture', 'version': 'model-v1',
                'purpose': 'model_output', 'provenance_kind': 'synthetic'}

    def write(self, name, row):
        (self.session / name).write_text(json.dumps(row) + '\n', encoding='utf-8')

    def test_annotations_identity_hash_and_missing_depth(self):
        row = self.annotation()
        self.write('annotations.jsonl', row)
        report = check_auxiliary(self.session, self.frames)
        self.assertEqual(report['annotations'][0]['target_missing_depth_count'], 1)
        row['specimen_id'] = 'wrong-specimen'
        self.write('annotations.jsonl', row)
        with self.assertRaises(ContractError):
            check_auxiliary(self.session, self.frames)
        row['specimen_id'] = None
        row['sha256'] = '0' * 64
        self.write('annotations.jsonl', row)
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'CHECKSUM_MISMATCH')

    def image(self):
        from PIL import Image
        Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8)).save(self.session / 'rgb.png')
        m = self.frames[0].metadata
        return {'session_id': m['session_id'], 'frame_id': m['frame_id'], 'file': 'rgb.png',
                'sha256': digest(self.session / 'rgb.png'), 'width': 2, 'height': 2, 'encoding': 'RGB8',
                'image_kind': 'original_rgb', 'time': m['capture_time'], 'pair_status': 'unverified',
                'pair_evidence': None, 'aligned_to_depth': False, 'alignment_method': None,
                'calibration_id': None, 'provenance_kind': 'synthetic'}

    def test_equal_sized_rgb_not_alignment_and_resize_rejected(self):
        row = self.image()
        self.write('images.jsonl', row)
        report = check_auxiliary(self.session, self.frames)
        self.assertFalse(report['images'][0]['usable_for_depth_label_review'])
        row.update(aligned_to_depth=True, alignment_method='resize',
                   calibration_id=self.frames[0].metadata['intrinsics']['calibration_id'])
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'ALIGNMENT_UNCONFIRMED')

    def test_pair_verified_without_evidence_and_unknown_frame(self):
        row = self.image()
        row['pair_status'] = 'verified'
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError):
            check_auxiliary(self.session, self.frames)
        row['frame_id'] = 'unknown'
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'FRAME_MAPPING_INVALID')


if __name__ == '__main__':
    unittest.main()
