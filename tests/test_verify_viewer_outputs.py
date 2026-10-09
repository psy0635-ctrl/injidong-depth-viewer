"""저장 결과 검증 CLI의 실제 입력 대조와 거짓 성공 방지 회귀 검사."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class VerifyViewerOutputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.session = self.base / 'session'
        self.bundle = self.base / 'bundle'
        shutil.copytree(ROOT / 'examples/viewer_multiframe', self.session)
        shutil.copytree(ROOT / 'outputs/ade95_final_user_saves/frame_000003_1791460557654228600', self.bundle)

    def read(self, name):
        return json.loads((self.bundle / name).read_text(encoding='utf-8'))

    def write(self, name, value):
        (self.bundle / name).write_text(json.dumps(value, allow_nan=False), encoding='utf-8')

    def refresh_hashes(self):
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        result = self.read('processing.json')
        result['point_cloud']['sha256'] = digest(self.bundle / 'points.npz')
        self.write('processing.json', result)
        audit = self.read('viewer_export.json')
        for name in audit['output_sha256']:
            audit['output_sha256'][name] = digest(self.bundle / name)
        self.write('viewer_export.json', audit)

    def cli(self, session=True):
        command = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/verify_viewer_outputs.py'), str(self.bundle)]
        if session:
            command.extend(['--session', str(self.session)])
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'})

    def assert_failure(self, code):
        result = self.cli()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'failure')
        self.assertFalse(report['coordinates_verified'])
        self.assertEqual(report['errors'][0]['code'], code)
        self.assertIn(code, result.stderr)

    def test_basic_synthetic_frame_matches_explicit_input(self):
        shutil.copytree(ROOT / 'examples/synthetic', self.base / 'basic_session')
        shutil.copytree(ROOT / 'outputs/ade95_final_synthetic', self.base / 'basic_bundle')
        self.session, self.bundle = self.base / 'basic_session', self.base / 'basic_bundle'
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['coordinates_verified'])
        self.assertEqual(report['input_coordinate_validation']['frame_id'], 'synthetic_000001')

    def test_third_frame_matches_explicit_multiframe_input(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['artifact_validation']['status'], 'passed')
        self.assertEqual(report['input_coordinate_validation']['status'], 'matched')
        self.assertTrue(report['coordinates_verified'])
        self.assertEqual(report['input_coordinate_validation']['frame_id'], 'ade95_synthetic_000003')
        self.assertEqual(report['input_coordinate_validation']['point_count'], 3)

    def test_hash_consistent_zero_third_cloud_is_rejected(self):
        np.savez(self.bundle / 'points.npz', points_m=np.zeros((3, 3), dtype=np.float32))
        self.refresh_hashes()
        self.assert_failure('POINT_CLOUD_MISMATCH')

    def test_input_metadata_mismatch_is_rejected(self):
        audit = self.read('viewer_export.json')
        audit['input_metadata']['capture_conditions']['notes'] = '입력과 다른 임시 메모'
        self.write('viewer_export.json', audit)
        self.assert_failure('METADATA_MISMATCH')

    def test_result_frame_absent_from_input_is_rejected(self):
        result = self.read('processing.json')
        result['frame_id'] = 'absent_frame'
        self.write('processing.json', result)
        audit = self.read('viewer_export.json')
        audit['input_metadata']['frame_id'] = 'absent_frame'
        self.write('viewer_export.json', audit)
        self.refresh_hashes()
        self.assert_failure('FRAME_NOT_FOUND')

    def test_no_input_reports_coordinates_not_verified_even_for_basic_id(self):
        shutil.copytree(ROOT / 'outputs/ade95_final_synthetic', self.base / 'basic_bundle')
        self.bundle = self.base / 'basic_bundle'
        result = self.cli(session=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['artifact_validation']['status'], 'passed')
        self.assertEqual(report['input_coordinate_validation']['status'], 'not_run')
        self.assertFalse(report['coordinates_verified'])
        self.assertNotIn('expected_coordinates', report)

    def test_missing_input_session_is_rejected(self):
        self.session = self.base / 'missing'
        self.assert_failure('INPUT_CORRUPT')

    def test_hash_consistent_reordered_points_are_rejected(self):
        with np.load(self.bundle / 'points.npz', allow_pickle=False) as data:
            points = data['points_m'][::-1].copy()
        np.savez(self.bundle / 'points.npz', points_m=points)
        self.refresh_hashes()
        self.assert_failure('POINT_CLOUD_MISMATCH')

    def test_hash_consistent_wrong_dtype_is_rejected(self):
        with np.load(self.bundle / 'points.npz', allow_pickle=False) as data:
            points = data['points_m'].astype(np.float64)
        np.savez(self.bundle / 'points.npz', points_m=points)
        self.refresh_hashes()
        self.assert_failure('POINT_CLOUD_DTYPE_INVALID')

    def test_declared_point_count_mismatch_is_rejected(self):
        result = self.read('processing.json')
        result['point_cloud']['point_count'] = 2
        self.write('processing.json', result)
        self.refresh_hashes()
        self.assert_failure('POINT_CLOUD_SHAPE_INVALID')


if __name__ == '__main__':
    unittest.main()
