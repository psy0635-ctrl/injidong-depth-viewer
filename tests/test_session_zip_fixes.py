"""Regressions for the four independently reproduced ZIP findings.

All hardware declarations here are synthetic mocks; no real calibration tested.
"""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
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
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'src')]
import test_session_pipeline as fixtures
import contract
import session_pipeline as pipeline
from session_boundary import COMPLETION, load_processing_result
from viewer_data import read_session
from replay import verify_replay
from depth_preflight import digest


class ZipFixTests(unittest.TestCase):
    setUp = fixtures.SessionPipelineTests.setUp
    save = fixtures.SessionPipelineTests.save
    run_it = fixtures.SessionPipelineTests.run_it

    def mock_real(self):
        m = self.basis['frames'][0]['metadata']
        m['capture_source'] = 'pc_camera'
        m['provenance'].update(kind='real', camera={'vendor': 'FIXTURE_ONLY', 'model': 'MOCK',
            'serial': None, 'firmware': None, 'sdk': 'NOT_ACTUAL_SDK', 'depth_profile_id': 'mock'},
            synthetic_seed=None, synthetic_config=None)
        evidence = self.intake / 'mock_geometry.txt'
        evidence.write_text('SYNTHETIC mock; not real geometry evidence', encoding='utf-8')
        self.basis['evidence_files'] = {'mock': {'file': evidence.name, 'sha256': digest(evidence)}}
        self.basis['real_geometry'] = {k: 'mock' for k in ('scale', 'semantics', 'intrinsics', 'rectification', 'device_profile')}
        self.basis['real_geometry'].update(intrinsics_precision='full_precision',
            calibration_id=m['intrinsics']['calibration_id'], depth_profile_id='mock',
            source_sha256=self.basis['source']['sha256'])
        self.save()
        with np.load(self.intake / 'source.npz', allow_pickle=False) as arrays:
            d, v = contract.normalize_depth(arrays['depth_raw'][0], .001)
        return contract.FramePacket(copy.deepcopy(m), d, v)

    def cli(self, output=None):
        return subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / 'src/session_pipeline.py'),
            '--basis', str(self.basis_path), '--output-root', str(output or self.output), '--repeat', '1'],
            capture_output=True, text=True, encoding='utf-8')

    def rejection(self, function, code):
        with self.assertRaises(contract.ContractError) as ctx:
            function()
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))

    def inconsistent(self, key, wrong):
        frame = self.mock_real()
        frame.metadata['provenance'][key] = wrong
        self.basis['frames'][0]['metadata']['provenance'][key] = wrong
        self.save()
        destination = self.base / ('direct_' + key)
        self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': self.basis_path,
                       'output_dir': destination}), 'EVIDENCE_MISMATCH')
        self.assertFalse(destination.exists())
        result = self.cli()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('EVIDENCE_MISMATCH', result.stderr)
        self.assertNotIn('passed_file_boundary_validation', result.stdout)
        self.assertFalse(list(self.output.rglob('frames.jsonl')))
        self.assertFalse(list(self.output.rglob('points.npz')))

    def test_f1_scale_direct_and_cli(self):
        self.inconsistent('raw_scale_to_m', .1)

    def test_f1_hash_direct_and_cli(self):
        self.inconsistent('raw_sha256', '1' * 64)

    def test_f1_raw_path_direct_and_cli(self):
        self.inconsistent('raw_file', 'raw/nonexistent.npz')

    def test_f1_source_hash_mismatch(self):
        frame = self.mock_real()
        self.basis['source']['sha256'] = '2' * 64
        self.save()
        self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': self.basis_path,
                       'output_dir': self.base / 'bad_hash'}), 'CHECKSUM_MISMATCH')
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn('CHECKSUM_MISMATCH', result.stderr)

    def test_f1_unknown_scale_direct_and_cli(self):
        frame = self.mock_real()
        self.basis['conversion']['scale_to_m'] = None
        self.save()
        self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': self.basis_path,
                       'output_dir': self.base / 'bad_scale'}), 'UNIT_UNKNOWN')
        self.assertEqual(self.cli().returncode, 1)

    def test_f1_normal_mock_real_direct_and_cli(self):
        frame = self.mock_real()
        result = pipeline.process_frame(frame, {'basis_path': self.basis_path, 'output_dir': self.base / 'direct'})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['point_cloud']['point_count'], 3)
        self.assertIsNone(result['volume_m3'])
        self.assertEqual(self.cli().returncode, 0)

    def test_f2_report_and_quarantine_double_failure_blocks_every_supported_reader(self):
        self.save()
        original_rename = pipeline.rename_new
        original_process = pipeline.process_frame
        cached = []
        def capture(frame, config):
            cached.append(frame)
            return original_process(frame, config)
        def double_failure(source, destination, run):
            if destination.name == 'validation.json':
                raise OSError('injected final report publication failure')
            if source.name == 'frames.jsonl':
                raise OSError('injected quarantine rename failure')
            return original_rename(source, destination, run)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(pipeline, 'rename_new', side_effect=double_failure), \
                patch.object(pipeline, 'process_frame', side_effect=capture), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = pipeline.main(['--basis', str(self.basis_path), '--output-root', str(self.output)])
        self.assertEqual(code, 1)
        self.assertNotIn('passed_file_boundary_validation', stdout.getvalue())
        self.assertIn('quarantine rename failure', stderr.getvalue())
        run = next(self.output.glob('run_*'))
        self.assertTrue((run / 'session/frames.jsonl').exists())  # Same residual files as the original repro.
        result_path = run / 'results/frame_000000/processing.json'
        self.assertTrue(result_path.exists())
        self.assertFalse((run / COMPLETION).exists())
        for read in (lambda: list(contract.iter_frames(run / 'session')),
                     lambda: contract.load_frame(run / 'session/frame_000000/metadata.json'),
                     lambda: read_session(run / 'session'),
                     lambda: load_processing_result(result_path),
                     lambda: pipeline.verify_session(run / 'session', self.base / 'reverify', 1),
                     lambda: original_process(cached[0], {'output_dir': self.base / 'reprocess'}),
                     lambda: contract.point_cloud_camera(cached[0])):
            with self.subTest(reader=read):
                self.rejection(read, 'SESSION_UNCOMMITTED')
        replay = verify_replay(run / 'session', 1)
        self.assertEqual(replay['status'], 'failure')
        self.assertEqual(replay['completed_repeats'], 0)
        self.assertEqual(replay['errors'][0]['code'], 'SESSION_UNCOMMITTED')
        self.assertFalse((self.base / 'reprocess').exists())
        # Also prove the actual child process exit code, not only main's return.
        injected_cli = """
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import session_pipeline as pipeline
original = pipeline.rename_new
def broken(source, destination, run):
    if destination.name == 'validation.json':
        raise OSError('child final report publication failure')
    if source.name == 'frames.jsonl':
        raise OSError('child quarantine rename failure')
    return original(source, destination, run)
with patch.object(pipeline, 'rename_new', side_effect=broken):
    code = pipeline.main(sys.argv[2:])
raise SystemExit(code)
"""
        child_output = self.base / 'child_double_failure'
        child = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', injected_cli, str(ROOT / 'src'),
            '--basis', str(self.basis_path), '--output-root', str(child_output)],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(child.returncode, 1)
        self.assertIn('child quarantine rename failure', child.stderr)
        self.assertNotIn('passed_file_boundary_validation', child.stdout)
        child_run = next(child_output.glob('run_*'))
        self.assertTrue((child_run / 'session/frames.jsonl').exists())
        self.rejection(lambda: read_session(child_run / 'session'), 'SESSION_UNCOMMITTED')
        self.rejection(lambda: load_processing_result(child_run / 'results/frame_000000/processing.json'),
                       'SESSION_UNCOMMITTED')

    def test_f2_completion_write_failure_is_not_published(self):
        self.save()
        original = pipeline.write_json_new
        def fail_record(path, value):
            if path.name == '.ade71-complete.pending.json':
                path.write_text('{partial', encoding='utf-8')
                raise OSError('injected partial completion write')
            return original(path, value)
        with patch.object(pipeline, 'write_json_new', side_effect=fail_record):
            run, report = pipeline.run_conversion(self.basis_path, self.output)
        self.assertEqual(report['status'], 'failure')
        self.assertFalse((run / COMPLETION).exists())
        self.rejection(lambda: read_session(run / 'session'), 'SESSION_UNCOMMITTED')

    def test_f2_missing_or_tampered_completion_rejects_cached_packet(self):
        run, report = self.run_it()
        self.assertEqual(report['status'], 'passed_file_boundary_validation')
        frame = read_session(run / 'session')[0]
        record = run / COMPLETION
        value = record.read_bytes()
        record.write_text('{}', encoding='utf-8')
        self.rejection(lambda: pipeline.process_frame(frame, {'output_dir': self.base / 'tampered'}), 'SESSION_UNCOMMITTED')
        record.write_bytes(value)
        record.unlink()
        self.rejection(lambda: contract.load_frame(run / 'session/frame_000000/metadata.json'), 'SESSION_UNCOMMITTED')

    def test_f2_detached_managed_session_cannot_be_read_as_legacy(self):
        run, _ = self.run_it()
        detached = self.base / 'detached'
        shutil.copytree(run / 'session', detached)
        self.rejection(lambda: read_session(detached), 'SESSION_UNCOMMITTED')

    def test_f3_same_child_and_ancestor_direct_and_cli(self):
        frame = self.mock_real()
        before = pipeline.file_hashes(self.intake)
        for output in (self.intake, self.intake / 'new_result', self.intake.parent):
            with self.subTest(output=output):
                self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': self.basis_path,
                               'output_dir': output}), 'PATH_INVALID')
                result = self.cli(output)
                self.assertEqual(result.returncode, 1)
                self.assertIn('PATH_INVALID', result.stderr)
        self.assertEqual(before, pipeline.file_hashes(self.intake))

    def test_f3_loaded_synthetic_input_context_enforced(self):
        run, _ = self.run_it()
        frame = read_session(run / 'session')[0]
        for output in (run / 'session', run / 'session/new_result', run):
            self.rejection(lambda: pipeline.process_frame(frame, {'output_dir': output}), 'PATH_INVALID')

    def test_f3_symlink_alias_if_permitted(self):
        frame = self.mock_real()
        alias = self.base / 'intake_alias'
        try:
            os.symlink(self.intake, alias, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'No directory symlink privilege: {error}')
        self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': self.basis_path,
                       'output_dir': alias / 'result'}), 'PATH_INVALID')
        self.assertEqual(self.cli(alias / 'result').returncode, 1)

    def test_f3_windows_junction_alias(self):
        if os.name != 'nt':
            self.skipTest('Windows junction-specific test')
        frame = self.mock_real()
        alias = self.base / 'intake_junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.intake)], capture_output=True)
        if result.returncode:
            self.skipTest(f'Junction creation unavailable, exit {result.returncode}')
        # Remove the junction itself before TemporaryDirectory cleans the actual input.
        self.addCleanup(lambda: os.rmdir(alias) if alias.exists() else None)
        self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': self.basis_path,
                       'output_dir': alias / 'result'}), 'PATH_INVALID')
        self.rejection(lambda: pipeline.process_frame(frame, {'basis_path': alias / 'basis.json',
                       'output_dir': self.intake / 'result'}), 'PATH_INVALID')
        self.assertEqual(self.cli(alias / 'result').returncode, 1)

    def legacy(self):
        path = self.base / 'legacy'
        shutil.copytree(ROOT / 'examples/synthetic', path)
        return path

    def test_f4_internal_absolute_and_escape_rejected_by_both_loaders(self):
        session = self.legacy()
        manifest = session / 'frames.jsonl'
        entry = json.loads(manifest.read_text(encoding='utf-8'))
        relative = entry['metadata_path']
        bad_paths = [str((session / relative).resolve()), '../outside.json',
                     'C:/absolute/metadata.json', '//server/share/metadata.json', 'C:drive-relative.json']
        for name in bad_paths:
            entry['metadata_path'] = name
            manifest.write_text(json.dumps(entry) + '\n', encoding='utf-8')
            for read in (lambda: list(contract.iter_frames(session)), lambda: read_session(session)):
                self.rejection(read, 'PATH_INVALID')

    def test_f4_relative_legacy_and_normal_synthetic_cloud(self):
        session = self.legacy()
        self.assertEqual(len(list(contract.iter_frames(session))), 1)
        self.assertEqual(len(read_session(session)), 1)
        frame = read_session(session)[0]
        result = pipeline.process_frame(frame, {'output_dir': self.base / 'legacy_cloud'})
        self.assertEqual(result['status'], 'success')
        run, report = self.run_it([[0, 0, 1], [.01, 0, 1], [0, .01, 1]])
        self.assertEqual(report['status'], 'passed_file_boundary_validation')
        self.assertTrue((run / COMPLETION).is_file())
        self.assertEqual(load_processing_result(run / 'results/frame_000000/processing.json')['status'], 'success')


if __name__ == '__main__':
    unittest.main()
