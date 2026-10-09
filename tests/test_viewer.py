"""ADE-95: actual file input, display state, export, and CLI policies."""
import copy
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

import matplotlib
matplotlib.use('Agg')
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import ContractError, validate_json
from viewer_data import ViewerSession, depth_preview, export_frame
from viewer import ViewerWindow


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.session = self.base / 'session'
        shutil.copytree(ROOT / 'examples/synthetic', self.session)

    def error(self, code, fn):
        with self.assertRaises(ContractError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'src/viewer.py'),
                               str(self.session), *args], cwd=ROOT,
                              env={**os.environ, 'PYTHONUTF8': '1'},
                              capture_output=True, text=True, encoding='utf-8')

    def change(self, folder='frame_000001', arrays=None, mutate=None):
        path = self.session / folder
        meta = json.loads((path / 'metadata.json').read_text(encoding='utf-8'))
        if arrays is not None:
            np.savez(path / 'arrays.npz', **arrays)
            meta['storage']['sha256'] = hashlib.sha256((path / 'arrays.npz').read_bytes()).hexdigest()
        if mutate:
            mutate(meta)
        (path / 'metadata.json').write_text(json.dumps(meta, allow_nan=False), encoding='utf-8')

    def second(self):
        shutil.copytree(self.session / 'frame_000001', self.session / 'frame_000002')
        self.change('frame_000002', {'depth_m': np.array([[2,2],[2,0]], dtype=np.float32),
                                    'valid_mask': np.array([[1,1],[1,0]], dtype=bool)},
                    lambda m: m.update(frame_id='synthetic_000002'))
        with (self.session / 'frames.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'frame_id':'synthetic_000002', 'metadata_path':'frame_000002/metadata.json'})+'\n')

    def test_expected_cloud_ratio_sampling_and_array_preservation(self):
        model = ViewerSession(self.session, max_display_points=2)
        view = model.current
        original = (view.frame.depth_m.copy(), view.frame.valid_mask.copy(), copy.deepcopy(view.frame.metadata))
        self.assertEqual(view.valid_ratio, .75)
        self.assertEqual(len(view.points_m), 3)
        self.assertEqual(len(view.display_points_m), 2)
        np.testing.assert_allclose(view.points_m, [[0,0,1],[.01,0,1],[0,.01,1]], rtol=0, atol=1e-7)
        pixels, bounds = depth_preview(view.frame)
        self.assertTrue(pixels.mask[1,1])
        self.assertLess(bounds[0], 1)
        self.assertGreater(bounds[1], 1)
        window = ViewerWindow(model, self.base / 'out')
        window.figure.canvas.draw()
        np.testing.assert_array_equal(view.frame.depth_m, original[0])
        np.testing.assert_array_equal(view.frame.valid_mask, original[1])
        self.assertEqual(view.frame.metadata, original[2])
        window.close()

    def test_navigation_boundaries_and_joint_refresh(self):
        self.second()
        model = ViewerSession(self.session)
        window = ViewerWindow(model, self.base / 'out')
        window.navigate(-1)
        self.assertEqual(model.index, 0)
        window.navigate(1)
        self.assertEqual(model.index, 1)
        self.assertIn('synthetic_000002', window.info.get_text())
        self.assertEqual(float(window.depth_image.get_array()[0,0]), 2)
        self.assertEqual(float(model.current.points_m[0,2]), 2)
        window.navigate(1)
        self.assertEqual(model.index, 1)
        window.navigate(-1)
        self.assertEqual(model.index, 0)
        window.close()

    def test_move_failure_clears_old_screen_and_can_recover(self):
        self.second()
        model = ViewerSession(self.session)
        window = ViewerWindow(model, self.base / 'out')
        path = self.session / 'frame_000002/arrays.npz'
        original = path.read_bytes()
        path.write_bytes(b'corrupt')
        window.navigate(1)
        self.assertIsNone(model.current)
        self.assertIsNone(window.depth_image)
        self.assertEqual(len(window.cloud_ax.collections), 0)
        self.assertIn('INPUT_CORRUPT', window.info.get_text())
        window.save()
        self.assertFalse((self.base / 'out').exists())
        path.write_bytes(original)
        window.navigate(-1)
        self.assertEqual(model.current.frame.metadata['frame_id'], 'synthetic_000001')
        window.close()

    def test_export_full_cloud_hash_schema_metadata_and_no_overwrite(self):
        model = ViewerSession(self.session, max_display_points=1)
        before = {p.relative_to(self.session): p.read_bytes() for p in self.session.rglob('*') if p.is_file()}
        bundle = export_frame(model.current, self.session, self.base / 'export')
        result = json.loads((bundle / 'processing.json').read_text(encoding='utf-8'))
        validate_json(result, 'processing')
        self.assertEqual(result['stage'], 'point_cloud')
        self.assertIsNone(result['volume_m3'])
        pc = result['point_cloud']
        self.assertEqual((pc['key'],pc['unit'],pc['frame'],pc['point_count']), ('points_m','m','camera',3))
        with np.load(bundle / pc['file'], allow_pickle=False) as data:
            self.assertEqual(data['points_m'].dtype, np.float32)
            self.assertEqual(data['points_m'].shape, (3,3))
            np.testing.assert_array_equal(data['points_m'], model.current.points_m)
        self.assertEqual(pc['sha256'], hashlib.sha256((bundle / pc['file']).read_bytes()).hexdigest())
        record = json.loads((bundle / 'viewer_export.json').read_text(encoding='utf-8'))
        self.assertEqual(record['input_metadata'], model.current.frame.metadata)
        for name, digest in record['output_sha256'].items():
            self.assertEqual(digest, hashlib.sha256((bundle / name).read_bytes()).hexdigest())
        self.error('PATH_INVALID', lambda: export_frame(model.current, self.session, self.base / 'export'))
        self.assertEqual(before, {p.relative_to(self.session):p.read_bytes() for p in self.session.rglob('*') if p.is_file()})

    def test_input_output_paths_and_partial_save_cleanup(self):
        model = ViewerSession(self.session)
        self.error('PATH_INVALID', lambda: export_frame(model.current, self.session, self.session / 'new'))
        with patch('viewer_data.np.savez', side_effect=OSError('disk full')):
            self.error('RESULT_INVALID', lambda: export_frame(model.current, self.session, self.base / 'partial'))
        self.assertFalse((self.base / 'partial').exists())

    def test_cli_missing_empty_and_broken_json_fail(self):
        for kind in ('missing','empty','json'):
            with self.subTest(kind=kind):
                manifest = self.session / 'frames.jsonl'
                if kind=='missing': manifest.unlink()
                else: manifest.write_text('' if kind=='empty' else '{broken', encoding='utf-8')
                result = self.cli('--headless', '--output', str(self.base / kind))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('MANIFEST_INVALID' if kind=='empty' else 'INPUT_CORRUPT', result.stderr)
                self.assertFalse((self.base / kind).exists())

    def test_cli_npz_corruption_with_matching_hash_and_schema_failure(self):
        path = self.session / 'frame_000001/arrays.npz'
        path.write_bytes(b'bad zip')
        self.change(mutate=lambda m: m['storage'].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        result = self.cli('--headless', '--output', str(self.base / 'bad'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('INPUT_CORRUPT', result.stderr)
        self.change(mutate=lambda m: m.update(schema_version='1.0'))
        result = self.cli('--headless', '--output', str(self.base / 'schema'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('SCHEMA_INVALID', result.stderr)

    def test_cli_all_invalid_depth_rejected(self):
        self.change(arrays={'depth_m':np.zeros((2,2),np.float32), 'valid_mask':np.zeros((2,2),bool)})
        result = self.cli('--headless', '--output', str(self.base / 'invalid'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('NO_VALID_DEPTH', result.stderr)

    def test_frame_file_errors_and_bad_dtype_reach_cli(self):
        folder = self.session / 'frame_000001'
        original_metadata = (folder / 'metadata.json').read_bytes()
        original_arrays = (folder / 'arrays.npz').read_bytes()
        for kind, expected in [('metadata_json','INPUT_CORRUPT'), ('missing_npz','INPUT_CORRUPT'),
                               ('hash','INPUT_CORRUPT'), ('dtype','DEPTH_DTYPE_INVALID')]:
            with self.subTest(kind=kind):
                (folder / 'metadata.json').write_bytes(original_metadata)
                (folder / 'arrays.npz').write_bytes(original_arrays)
                if kind=='metadata_json':
                    (folder / 'metadata.json').write_text('{broken', encoding='utf-8')
                elif kind=='missing_npz':
                    (folder / 'arrays.npz').unlink()
                elif kind=='hash':
                    (folder / 'arrays.npz').write_bytes(b'changed')
                else:
                    self.change(arrays={'depth_m':np.array([[1,1],[1,0]],np.float64),
                                        'valid_mask':np.array([[1,1],[1,0]],bool)})
                result = self.cli('--headless','--output',str(self.base / kind))
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)

    def test_session_order_change_invalidates_current(self):
        self.second()
        model = ViewerSession(self.session)
        manifest = self.session / 'frames.jsonl'
        manifest.write_text('\n'.join(reversed(manifest.read_text(encoding='utf-8').splitlines()))+'\n',encoding='utf-8')
        self.error('MANIFEST_INVALID', lambda: model.select(1))
        self.assertIsNone(model.current)

    def test_manifest_relative_paths_unique_ids_and_nan(self):
        manifest = self.session / 'frames.jsonl'
        original = manifest.read_text(encoding='utf-8')
        cases = [(original*2,'MANIFEST_INVALID'),
                 (json.dumps({'frame_id':'synthetic_000001','metadata_path':'../outside.json'}),'PATH_INVALID'),
                 (json.dumps({'frame_id':'synthetic_000001','metadata_path':str(self.session/'frame_000001/metadata.json')}),'PATH_INVALID'),
                 ('{"frame_id":NaN,"metadata_path":"x"}','MANIFEST_INVALID'),
                 ('{"frame_id":[],"metadata_path":"x"}','MANIFEST_INVALID')]
        for text, code in cases:
            with self.subTest(code=code, text=text):
                manifest.write_text(text, encoding='utf-8')
                self.error(code, lambda: ViewerSession(self.session))

    def test_headless_cli_exports_and_existing_output_is_failure(self):
        output = self.base / 'cli'
        result = self.cli('--headless', '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output / 'preview.png').is_file())
        self.assertIn('synthetic', result.stdout)
        result = self.cli('--headless', '--output', str(output))
        self.assertEqual(result.returncode, 1)
        self.assertIn('PATH_INVALID', result.stderr)

    def test_save_error_keeps_valid_view_but_reports_failure(self):
        model = ViewerSession(self.session)
        output = self.base / 'existing'
        output.mkdir()
        window = ViewerWindow(model, output)
        with patch('viewer.export_frame', side_effect=ContractError('RESULT_INVALID','disk full')):
            window.save()
        self.assertIsNotNone(model.current)
        self.assertIn('RESULT_INVALID', window.status.get_text())
        self.assertEqual(window.exit_code, 1)
        window.close()

    def test_unexpected_error_propagates(self):
        with patch('viewer_data.iter_frames', side_effect=RuntimeError('unexpected')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                ViewerSession(self.session)

    def test_labels_are_ignored_and_zero_display_limit_is_usage_error(self):
        (self.session / 'labels.jsonl').write_text('this is not inference input', encoding='utf-8')
        self.assertEqual(len(ViewerSession(self.session).current.points_m), 3)
        result = self.cli('--max-display-points', '0')
        self.assertEqual(result.returncode, 2)

    def test_generator_creates_three_valid_distinct_frames_without_overwrite(self):
        output = self.base / 'generated'
        command = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/make_viewer_example.py'), '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        model = ViewerSession(output)
        self.assertEqual(len(model.frame_ids), 3)
        first = model.current.points_m.copy()
        model.select(1)
        self.assertFalse(np.array_equal(first, model.current.points_m))
        self.assertEqual(model.current.frame.metadata['capture_source'], 'synthetic')
        before = (output / 'frames.jsonl').read_bytes()
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (output / 'frames.jsonl').read_bytes())


if __name__ == '__main__':
    unittest.main()
