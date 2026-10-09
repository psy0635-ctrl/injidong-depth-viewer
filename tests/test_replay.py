"""재생 CLI의 실제 파일 입력·종료 코드·기록·보존 동작을 검증한다."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import iter_frames


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.session = self.base / 'session'
        shutil.copytree(ROOT / 'examples/synthetic', self.session)
        self.report = self.base / 'report.json'

    def cli(self, *extra):
        return subprocess.run(
            [sys.executable, '-X', 'utf8', str(ROOT / 'src/replay.py'),
             str(self.session), '--report', str(self.report), *extra],
            env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True,
            text=True, encoding='utf-8', cwd=ROOT)

    def test_cli_reopens_session_and_records_original_metadata(self):
        before = {p.name: p.read_bytes() for p in self.session.rglob('*') if p.is_file()}
        result = self.cli('--repeat', '3', '--expected-points',
                          str(ROOT / 'examples/results/expected_points.json'))
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'success')
        self.assertEqual(record['completed_repeats'], 3)
        self.assertEqual(record['frame_ids'], ['synthetic_000001'])
        self.assertEqual(len(record['iterations']), 3)
        self.assertEqual(record['frames'][0]['capture_time'],
                         {'ns': '1000000000', 'clock_domain': 'synthetic_reference', 'origin': 'synthetic'})
        self.assertEqual(record['frames'][0]['capture_source'], 'synthetic')
        self.assertEqual(record['frames'][0]['provenance']['raw_scale_to_m'], .001)
        np.testing.assert_allclose(record['frames'][0]['points_m'],
                                   [[0, 0, 1], [.01, 0, 1], [0, .01, 1]], rtol=0, atol=1e-7)
        self.assertEqual(record['hashes_before'], record['hashes_after'])
        for iteration in record['iterations']:
            self.assertEqual(iteration['frames'][0]['replay_time']['origin'], 'replay_host')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.session.rglob('*') if p.is_file()})

    def test_target_mask_and_multiple_frame_order(self):
        first = self.session / 'frame_000001'
        meta = json.loads((first / 'metadata.json').read_text(encoding='utf-8'))
        with np.load(first / 'arrays.npz') as data:
            depth, mask = data['depth_m'], data['valid_mask']
        np.savez(first / 'arrays.npz', depth_m=depth, valid_mask=mask, target_mask=mask)
        meta['storage']['target_mask_key'] = 'target_mask'
        meta['storage']['sha256'] = hashlib.sha256((first / 'arrays.npz').read_bytes()).hexdigest()
        meta['target_mask_info'] = {'source': '임시 합성 테스트', 'version': '1'}
        (first / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')
        second = self.session / 'frame_000002'
        shutil.copytree(first, second)
        meta['frame_id'] = 'synthetic_000002'
        (second / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')
        with (self.session / 'frames.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'frame_id': 'synthetic_000002', 'metadata_path': 'frame_000002/metadata.json'}) + '\n')
        result = self.cli('--repeat', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(record['frame_ids'], ['synthetic_000001', 'synthetic_000002'])
        self.assertTrue(all(frame['has_target_mask'] for frame in record['frames']))

    def test_cli_propagates_contract_codes_for_bad_inputs(self):
        # 기존 로더 검사를 복제하지 않고 새 CLI의 실패 경계와 기록을 확인한다.
        for kind, expected in [('checksum', 'INPUT_CORRUPT'), ('escape', 'PATH_INVALID'),
                               ('empty', 'MANIFEST_INVALID')]:
            with self.subTest(kind=kind):
                manifest = self.session / 'frames.jsonl'
                original = manifest.read_bytes()
                arrays = self.session / 'frame_000001/arrays.npz'
                arrays_original = arrays.read_bytes()
                if kind == 'checksum':
                    arrays.write_bytes(b'corrupt')
                elif kind == 'escape':
                    manifest.write_text(json.dumps({'frame_id': 'x', 'metadata_path': '../outside.json'}), encoding='utf-8')
                else:
                    manifest.write_text('', encoding='utf-8')
                result = self.cli('--repeat', '2')
                self.assertEqual(result.returncode, 1, result.stderr)
                record = json.loads(self.report.read_text(encoding='utf-8'))
                self.assertEqual(record['errors'][0]['code'], expected)
                self.assertEqual(record['status'], 'failure')
                self.assertEqual(record['hashes_before'], record['hashes_after'])
                manifest.write_bytes(original)
                arrays.write_bytes(arrays_original)
                self.report.unlink()

    def test_expected_points_mismatch_is_failure(self):
        expected = self.base / 'expected.json'
        expected.write_text('[[0,0,2],[0.01,0,1],[0,0.01,1]]', encoding='utf-8')
        result = self.cli('--expected-points', str(expected))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(self.report.read_text(encoding='utf-8'))['errors'][0]['code'], 'RESULT_INVALID')

    def test_report_cannot_overwrite_input_or_existing_record(self):
        metadata = self.session / 'frame_000001/metadata.json'
        original = metadata.read_bytes()
        result = self.cli('--report', str(metadata))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PATH_INVALID', result.stderr)
        self.assertEqual(metadata.read_bytes(), original)
        self.report.write_text('사용자 기록', encoding='utf-8')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.report.read_text(encoding='utf-8'), '사용자 기록')

    def test_invalid_repeat_is_usage_failure(self):
        for count in ['0', '-1', 'x']:
            with self.subTest(count=count):
                result = self.cli('--repeat', count)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.report.exists())

    def test_detects_loaded_value_metadata_point_and_order_differences(self):
        import replay
        # 메모리 반환을 바꾸어 해시만 비교하는 구현을 잡는다. 실제 로더로 매회 재독한다.
        mutations = {
            'depth': lambda f: f.depth_m.__setitem__((0, 0), 2),
            'valid_mask': lambda f: f.valid_mask.__setitem__((0, 0), False),
            'target_mask': lambda f: f.target_mask.__setitem__((0, 0), False),
            'capture_time': lambda f: f.metadata['capture_time'].__setitem__('ns', '1000000001'),
            'provenance': lambda f: f.metadata['provenance'].__setitem__('synthetic_seed', 1),
            'capture_source': lambda f: f.metadata.__setitem__('capture_source', 'pc_camera'),
            'frame_id': lambda f: f.metadata.__setitem__('frame_id', 'changed'),
        }
        for kind, mutate in mutations.items():
            reads = 0
            def changed(session):
                nonlocal reads
                frames = list(iter_frames(session))
                if kind == 'target_mask':
                    frames[0].metadata['storage']['target_mask_key'] = 'target_mask'
                    frames[0].metadata['target_mask_info'] = {'source': '임시 합성', 'version': '1'}
                    frames[0].target_mask = frames[0].valid_mask.copy()
                reads += 1
                if reads == 2:
                    mutate(frames[0])
                return iter(frames)
            with self.subTest(kind=kind), patch.object(replay, 'iter_frames', changed):
                record = replay.verify_replay(self.session, 2)
                self.assertEqual(record['status'], 'failure')
                self.assertIn(kind, record['errors'][0]['message'])
                self.assertEqual(reads, 2)
        calls = 0
        original_cloud = replay.point_cloud_camera
        def changed_cloud(frame):
            nonlocal calls
            calls += 1
            points = original_cloud(frame)
            if calls == 2:
                points[0, 0] = .1
            return points
        with patch.object(replay, 'point_cloud_camera', changed_cloud):
            record = replay.verify_replay(self.session, 2)
        self.assertEqual(record['status'], 'failure')
        self.assertIn('points_m', record['errors'][0]['message'])

    def test_detects_file_change_even_when_frame_values_are_identical(self):
        import replay
        reads = 0
        def changed(session):
            nonlocal reads
            frames = list(iter_frames(session))
            reads += 1
            if reads == 2:
                with (self.session / 'frames.jsonl').open('a', encoding='utf-8') as f:
                    f.write('\n')
            return iter(frames)
        with patch.object(replay, 'iter_frames', changed):
            record = replay.verify_replay(self.session, 2)
        self.assertEqual(record['status'], 'failure')
        self.assertFalse(record['original_files_unchanged'])
        self.assertIn('frames.jsonl', record['errors'][-1]['message'])

    def test_count_and_order_changes_fail(self):
        import copy
        import replay
        for kind in ['count', 'order']:
            reads = 0
            def changed(session):
                nonlocal reads
                first = list(iter_frames(session))[0]
                second = copy.deepcopy(first)
                second.metadata['frame_id'] = 'synthetic_000002'
                reads += 1
                frames = [first, second]
                if reads == 2:
                    frames = [first] if kind == 'count' else [second, first]
                return iter(frames)
            with self.subTest(kind=kind), patch.object(replay, 'iter_frames', changed):
                record = replay.verify_replay(self.session, 2)
                self.assertEqual(record['status'], 'failure')
                self.assertEqual(record['errors'][0]['code'], 'MANIFEST_INVALID')

    def test_unexpected_exception_is_not_hidden(self):
        import replay
        with patch.object(replay, 'iter_frames', side_effect=RuntimeError('예상하지 못한 오류')):
            with self.assertRaisesRegex(RuntimeError, '예상하지 못한 오류'):
                replay.verify_replay(self.session, 2)


if __name__ == '__main__':
    unittest.main()
