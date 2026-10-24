"""Stage-1 tests use temporary deliveries, never mutate the real D405 input."""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import ContractError, normalize_depth
from depth_preflight import (digest, frame_stats, new_run, read_scale, run_preflight,
                             verify_roundtrip, write_json_new)


class DepthPreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.zip = self.base / 'depth_original.zip'
        self.receipt = self.base / 'receipt.json'
        self.outputs = self.base / 'out'
        self.raw = np.array([[[0, 1, 65535], [1000, 2, 0]],
                             [[3, 0, 5], [7, 8, 9]]], dtype=np.uint16)

    def delivery(self, raw=None, key='depth_raw', metadata='SCALE 9.999999747378752e-05\n',
                 extra=None):
        buffer = io.BytesIO()
        np.savez(buffer, **{key: self.raw if raw is None else raw})
        # If the capture code were executed it would create a marker and fail.
        self.marker = self.base / 'executed.txt'
        capture = f'from pathlib import Path\nPath({str(self.marker)!r}).write_text("executed")\nraise RuntimeError("must not execute")\n'
        with zipfile.ZipFile(self.zip, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('depth10.npz', buffer.getvalue())
            archive.writestr('metadata.txt', metadata)
            archive.writestr('capture10.py', capture)
            if extra:
                archive.writestr(*extra)
        import hashlib
        with zipfile.ZipFile(self.zip) as archive:
            members = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
        receipt = {'delivery_id': 'temporary-test-only', 'zip_sha256': digest(self.zip),
                   'members': members,
                   'raw_array': {'file': 'depth10.npz', 'key': 'depth_raw',
                                 'dtype': 'uint16', 'shape': [2, 2, 3]},
                   'metadata_file': 'metadata.txt', 'capture_code_file': 'capture10.py'}
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')

    def run_check(self):
        return run_preflight(self.zip, self.receipt, self.outputs)

    def assert_error(self, code):
        run, report = self.run_check()
        self.assertEqual(report['status'], 'failure')
        self.assertIn(code, [e['code'] for e in report['errors']])
        self.assertTrue(report['originals_unchanged'])
        self.assertTrue((run / 'inspection_report.json').is_file())
        return run, report

    def test_real_arithmetic_roundtrip_preservation_and_65535_notice(self):
        self.delivery()
        before = digest(self.zip)
        run, report = self.run_check()
        self.assertEqual(report['status'], 'passed_array_preflight', report['errors'])
        self.assertEqual(report['completed_frames'], 2)
        self.assertEqual(report['zip_crc']['status'], 'passed')
        self.assertEqual(digest(self.zip), before)
        self.assertEqual(report['original_hashes_before'], report['original_hashes_after'])
        self.assertFalse(self.marker.exists())
        self.assertFalse(report['is_frame_packet'])
        self.assertFalse(report['common_session_approved'])
        self.assertFalse(list(run.rglob('metadata.json')))
        self.assertFalse(list(run.rglob('frames.jsonl')))
        self.assertEqual(report['frames'][0]['raw_65535_count'], 1)
        self.assertEqual(report['frames'][0]['valid_65535_count'], 1)
        self.assertIn('65535 의미 미확인', report['warnings'][0])
        for index, item in enumerate(report['frames']):
            expected_depth, expected_mask = normalize_depth(self.raw[index], 9.999999747378752e-05)
            with np.load(run / item['output_file'], allow_pickle=False) as arrays:
                self.assertEqual(arrays['depth_m'].dtype, np.float32)
                self.assertEqual(arrays['valid_mask'].dtype, np.bool_)
                self.assertEqual(arrays['depth_m'].shape, (2, 3))
                np.testing.assert_array_equal(arrays['depth_m'], expected_depth)
                np.testing.assert_array_equal(arrays['valid_mask'], expected_mask)
                self.assertTrue(np.all(arrays['depth_m'][~arrays['valid_mask']] == 0))
            self.assertEqual(digest(run / item['output_file']), item['output_sha256'])
            self.assertEqual(item['source_frame_index'], index)
            self.assertEqual(item['roundtrip']['status'], 'passed')

    def test_hash_mismatch_zip(self):
        self.delivery()
        receipt = json.loads(self.receipt.read_text())
        receipt['zip_sha256'] = '0' * 64
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        _, report = self.assert_error('CHECKSUM_MISMATCH')
        self.assertEqual(report['completed_frames'], 0)
        self.assertEqual(report['zip_crc']['status'], 'not_run')

    def test_hash_mismatch_member(self):
        self.delivery()
        receipt = json.loads(self.receipt.read_text())
        receipt['members']['metadata.txt'] = '0' * 64
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        self.assert_error('CHECKSUM_MISMATCH')

    def test_bad_npz_key_shape_dtype_and_pickle(self):
        for raw, key, code in [(self.raw, 'unexpected', 'NPZ_KEY_INVALID'),
                               (self.raw[:1], 'depth_raw', 'DEPTH_SHAPE_INVALID'),
                               (self.raw.astype(np.float32), 'depth_raw', 'DEPTH_DTYPE_INVALID'),
                               (self.raw.astype(object), 'depth_raw', 'INPUT_CORRUPT')]:
            with self.subTest(code=code, dtype=str(raw.dtype)):
                self.delivery(raw=raw, key=key)
                self.assert_error(code)

    def test_missing_ambiguous_and_invalid_scale_are_failures(self):
        for text in ['', 'INTRINSICS [SCALE 0.001]', 'SCALE 0.001\nSCALE 0.002',
                     'SCALE 0', 'SCALE -1', 'SCALE nan', 'SCALE inf', 'SCALE 1e999',
                     'SCALE text', 'SCALE 0.001 m', 'SCALE = 0.001']:
            with self.subTest(text=text):
                self.delivery(metadata=text)
                self.assert_error('UNIT_UNKNOWN')

    def test_scale_precision_is_read_without_substituting(self):
        scale, line = read_scale('SAVE OK (10, 480, 640)\nSCALE 9.999999747378752e-05\n')
        self.assertEqual(scale, 9.999999747378752e-05)
        self.assertEqual(line, 'SCALE 9.999999747378752e-05')

    def test_entirely_invalid_frame_fails_without_approval(self):
        self.delivery(raw=np.zeros_like(self.raw))
        _, report = self.assert_error('NO_VALID_DEPTH')
        self.assertEqual(report['frames'][0]['zero_count'], 6)
        self.assertEqual(report['frames'][0]['valid_count'], 0)
        self.assertEqual(report['completed_frames'], 0)

    def test_frame_statistics_denominator_and_center(self):
        stats = frame_stats(self.raw[0])
        self.assertEqual(stats['pixel_count'], 6)
        self.assertEqual(stats['zero_count'], 2)
        self.assertEqual(stats['positive_count'], 4)
        self.assertEqual(stats['positive_ratio_full_image'], 4 / 6)
        self.assertEqual(stats['center_pixel_v_u'], [1, 1])
        self.assertEqual(stats['center_raw'], 2)
        self.assertEqual((stats['raw_min'], stats['raw_max']), (0, 65535))

    def test_output_collision_retries_and_preserves_existing_files(self):
        self.outputs.mkdir()
        existing = self.outputs / ('run_' + '0' * 32)
        existing.mkdir()
        sentinel = existing / 'user.txt'
        sentinel.write_text('preserve', encoding='utf-8')
        with patch('depth_preflight.uuid.uuid4', side_effect=[uuid.UUID(int=0), uuid.UUID(int=1)]):
            result = new_run(self.outputs)
        self.assertNotEqual(result, existing)
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.delivery()
        first, _ = self.run_check()
        hashes = {p.relative_to(first): digest(p) for p in first.rglob('*') if p.is_file()}
        second, _ = self.run_check()
        self.assertNotEqual(first, second)
        self.assertEqual(hashes, {p.relative_to(first): digest(p) for p in first.rglob('*') if p.is_file()})

    def test_roundtrip_rejects_dtype_shape_values_and_mask_changes(self):
        depth, mask = normalize_depth(self.raw[0], .0001)
        saved = self.base / 'saved.npz'
        for key, value in [('depth_m', depth.astype(np.float64)),
                           ('depth_m', depth[:1]), ('depth_m', depth + np.float32(1)),
                           ('valid_mask', mask.astype(np.uint8)), ('valid_mask', ~mask),
                           ('valid_mask', mask[:1])]:
            with self.subTest(key=key, shape=value.shape, dtype=str(value.dtype)):
                arrays = {'depth_m': depth, 'valid_mask': mask}
                arrays[key] = value
                np.savez(saved, **arrays)
                with self.assertRaises(ContractError) as error:
                    verify_roundtrip(saved, depth, mask)
                self.assertEqual(error.exception.code, 'ROUNDTRIP_MISMATCH')

    def test_zip_unsafe_paths_and_symlink_rejected_before_extraction(self):
        for name in ['../escape.txt', '/escape.txt', 'C:/escape.txt', 'a\\..\\escape.txt',
                     'a/../../escape.txt', 'metadata.txt:alternate']:
            with self.subTest(name=name):
                self.delivery(extra=(name, 'unsafe'))
                run, _ = self.assert_error('PATH_INVALID')
                self.assertFalse((self.base / 'escape.txt').exists())
                self.assertFalse((run / 'originals/depth10.npz').exists())
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.delivery(extra=(info, '../outside'))
        self.assert_error('PATH_INVALID')

    def test_zip_crc_corruption_fails_even_with_matching_zip_hash(self):
        self.delivery()
        data = self.zip.read_bytes()
        offset = data.index(b'SCALE 9.999999747378752e-05')
        data = data[:offset] + b'X' + data[offset + 1:]
        self.zip.write_bytes(data)
        receipt = json.loads(self.receipt.read_text())
        receipt['zip_sha256'] = digest(self.zip)
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        _, report = self.assert_error('ZIP_CRC_INVALID')
        self.assertEqual(report['zip_crc']['status'], 'failed')

    def test_preserved_file_mutation_is_reported_as_failure(self):
        self.delivery()
        original = verify_roundtrip
        def changed(path, depth, mask):
            result = original(path, depth, mask)
            (path.parent.parent / 'originals/metadata.txt').write_text('changed', encoding='utf-8')
            return result
        with patch('depth_preflight.verify_roundtrip', side_effect=changed):
            _, report = self.run_check()
        self.assertEqual(report['status'], 'failure')
        self.assertFalse(report['originals_unchanged'])
        self.assertIn('PRESERVATION_MISMATCH', [e['code'] for e in report['errors']])

    def test_cli_exit_codes_and_persistent_failure_record(self):
        self.delivery()
        command = [sys.executable, '-X', 'utf8', str(ROOT / 'src/depth_preflight.py'),
                   str(self.zip), '--receipt', str(self.receipt), '--output-root', str(self.outputs)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.delivery(metadata='SCALE nan')
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 1)
        self.assertIn('UNIT_UNKNOWN', result.stderr)
        reports = [json.loads(p.read_text(encoding='utf-8')) for p in self.outputs.glob('*/inspection_report.json')]
        self.assertEqual(sorted(r['status'] for r in reports), ['failure', 'passed_array_preflight'])

    def test_json_utf8_nonfinite_and_overwrite_rejected(self):
        path = self.base / 'record.json'
        for value in [float('nan'), float('inf'), float('-inf')]:
            with self.assertRaises(ValueError):
                write_json_new(path, {'value': value})
            self.assertFalse(path.exists())
        write_json_new(path, {'notice': '배열 사전 검사'})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['notice'], '배열 사전 검사')
        with self.assertRaises(FileExistsError):
            write_json_new(path, {})


if __name__ == '__main__':
    unittest.main()
