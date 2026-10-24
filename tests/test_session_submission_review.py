"""Only newly found publication/evidence/auxiliary regressions, temporary files."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'src')]
import test_session_pipeline as fixtures
from contract import ContractError, FramePacket
from depth_preflight import digest
import session_pipeline as pipeline
from session_auxiliary import attach_target, check_auxiliary
from viewer_data import read_session


class PublicationReviewTests(unittest.TestCase):
    setUp = fixtures.SessionPipelineTests.setUp
    save = fixtures.SessionPipelineTests.save
    raw = fixtures.SessionPipelineTests.raw
    run_it = fixtures.SessionPipelineTests.run_it

    def not_published(self, run):
        self.assertFalse((run / 'session/frames.jsonl').exists())
        self.assertFalse(list(run.rglob('processing.json')))
        for manifest in run.rglob('frames.jsonl'):
            self.fail(f'failed canonical manifest left: {manifest}')
        for folder in ('session', 'pending_session'):
            if (run / folder).exists():
                with self.assertRaises(ContractError):
                    read_session(run / folder)

    def test_expected_full_cloud_failure_quarantines_session_and_results(self):
        run, report = self.run_it([[9, 9, 9]] * 3)
        self.assertEqual(report['status'], 'failure')
        self.assertIn('RESULT_INVALID', [e['code'] for e in report['errors']])
        self.not_published(run)
        self.assertTrue((run / 'pending_session/frames.failed.jsonl').exists())
        self.assertTrue(list(run.rglob('processing.pending.json')))

    def test_report_write_failure_exit_one_without_success_or_readable_session(self):
        self.save()
        original = pipeline.write_json_new
        def fail_report(path, value):
            if path.name in ('validation.json', 'validation.pending.json'):
                raise OSError('mock report disk failure')
            return original(path, value)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(pipeline, 'write_json_new', side_effect=fail_report), redirect_stdout(stdout), redirect_stderr(stderr):
            code = pipeline.main(['--basis', str(self.basis_path), '--output-root', str(self.output)])
        self.assertEqual(code, 1)
        self.assertNotIn('passed_file_boundary_validation', stdout.getvalue())
        self.assertIn('mock report disk failure', stderr.getvalue())
        self.not_published(next(self.output.glob('run_*')))

    def test_final_report_publication_failure_revokes_canonical_entrypoints(self):
        original = pipeline.rename_new
        def fail_commit(source, destination, run):
            if destination.name == 'validation.json':
                raise OSError('mock final report rename failure')
            return original(source, destination, run)
        with patch.object(pipeline, 'rename_new', side_effect=fail_commit):
            run, report = self.run_it()
        self.assertEqual(report['status'], 'failure')
        self.not_published(run)
        self.assertTrue((run / 'validation.uncommitted.json').exists())
        self.assertEqual(json.loads((run / 'validation.json').read_text(encoding='utf-8'))['status'], 'failure')

    def test_initial_metadata_save_failure_never_publishes_manifest(self):
        original = pipeline.write_json_new
        def broken_metadata(path, value):
            if path.name == 'metadata.json':
                raise OSError('mock mid frame save failure')
            return original(path, value)
        with patch.object(pipeline, 'write_json_new', side_effect=broken_metadata):
            run, report = self.run_it()
        self.assertEqual(report['status'], 'failure')
        self.not_published(run)
        self.assertTrue(report['originals_unchanged'])

    def test_unexpected_replay_error_is_failure_and_standalone_results_stay_pending(self):
        with patch.object(pipeline, 'verify_session', side_effect=RuntimeError('mock unexpected failure')):
            run, report = self.run_it()
        self.assertEqual(report['status'], 'failure')
        self.assertEqual(report['errors'][0]['code'], 'INTERNAL_ERROR')
        self.not_published(run)
        run, _ = self.run_it()
        original_hashes = pipeline.file_hashes(run / 'session')
        results = self.base / 'standalone_failed_results'
        with self.assertRaises(ContractError):
            pipeline.verify_session(run / 'session', results, 1, [[9, 9, 9]] * 3)
        self.assertFalse(list(results.rglob('processing.json')))
        self.assertEqual(original_hashes, pipeline.file_hashes(run / 'session'))

    def test_shortened_initial_reload_rejected_before_cloud_generation(self):
        self.raw([[[1000, 1000], [1000, 0]], [[2000, 0], [2000, 2000]]])
        entry = copy.deepcopy(self.basis['frames'][0])
        entry['source_frame_index'] = 1
        entry['metadata']['frame_id'] = 'second'
        self.basis['frames'].append(entry)
        original = pipeline.read_session
        with patch.object(pipeline, 'read_session', side_effect=lambda path: original(path)[:1]):
            run, report = self.run_it()
        self.assertEqual(report['status'], 'failure')
        self.assertIn('FRAME_MAPPING_INVALID', [e['code'] for e in report['errors']])
        self.not_published(run)
        self.assertFalse(list(run.rglob('points.npz')))

    def mock_real(self):
        run, _ = self.run_it()
        frame = read_session(run / 'session')[0]
        metadata = copy.deepcopy(frame.metadata)
        metadata['capture_source'] = 'pc_camera'
        metadata['provenance'].update(kind='real', camera={'vendor': 'mock', 'model': 'mock', 'serial': None,
            'firmware': None, 'sdk': None, 'depth_profile_id': 'mock'}, synthetic_seed=None, synthetic_config=None)
        return FramePacket(metadata, frame.depth_m, frame.valid_mask)

    def test_public_real_processing_and_mask_attachment_require_evidence(self):
        frame = self.mock_real()
        destination = self.base / 'no_evidence_points'
        with self.assertRaises(ContractError) as error:
            pipeline.process_frame(frame, {'output_dir': destination})
        self.assertEqual(error.exception.code, 'EVIDENCE_REQUIRED')
        self.assertFalse(destination.exists())
        with self.assertRaises(ContractError):
            attach_target(frame, np.ones((2, 2), dtype=bool), 'mock', 'mock-v1')

    def test_mock_real_basis_binds_complete_depth_and_target_arrays(self):
        # Explicit SDK mock fixture, NOT real calibration or hardware evidence.
        m = self.basis['frames'][0]['metadata']
        m['capture_source'] = 'pc_camera'
        m['provenance'].update(kind='real', camera={'vendor': 'mock', 'model': 'mock', 'serial': None,
            'firmware': None, 'sdk': 'mock', 'depth_profile_id': 'mock'}, synthetic_seed=None, synthetic_config=None)
        evidence = self.intake / 'mock_geometry.txt'
        evidence.write_text('mock-only declarations for file-boundary tests', encoding='utf-8')
        self.basis['evidence_files'] = {'mock': {'file': evidence.name, 'sha256': digest(evidence)}}
        claims = {field: 'mock' for field in ('scale', 'semantics', 'intrinsics', 'rectification', 'device_profile')}
        claims.update(intrinsics_precision='full_precision', calibration_id=m['intrinsics']['calibration_id'],
                      depth_profile_id='mock', source_sha256=self.basis['source']['sha256'])
        self.basis['real_geometry'] = claims
        target = np.ones((2, 2), dtype=bool)
        np.savez_compressed(self.intake / 'target.npz', target_mask=target)
        m['storage']['target_mask_key'] = 'target_mask'
        m['target_mask_info'] = {'source': 'mock', 'version': 'v1'}
        spec = {field: m[field] for field in ('frame_id', 'session_id', 'specimen_id')}
        spec.update(file='target.npz', sha256=digest(self.intake / 'target.npz'), source='mock', version='v1',
                    depth_alignment_evidence='mock')
        self.basis['frames'][0]['target'] = spec
        run, report = self.run_it()
        self.assertEqual(report['status'], 'passed_file_boundary_validation', report['errors'])
        self.assertFalse(report['physical_evidence_verified'])
        frame = read_session(run / 'session')[0]
        frame.target_mask[0, 0] = False
        with self.assertRaises(ContractError) as error:
            pipeline.process_frame(frame, {'output_dir': self.base / 'changed_target', 'basis_path': self.basis_path})
        self.assertEqual(error.exception.code, 'ROUNDTRIP_MISMATCH')
        self.assertFalse((self.base / 'changed_target').exists())

    def test_target_receipt_identity_and_source_version(self):
        target = np.ones((2, 2), dtype=bool)
        np.savez_compressed(self.intake / 'target.npz', target_mask=target)
        evidence = self.intake / 'alignment.txt'
        evidence.write_text('synthetic depth coordinate fixture', encoding='utf-8')
        self.basis['evidence_files'] = {'alignment': {'file': evidence.name, 'sha256': digest(evidence)}}
        metadata = self.basis['frames'][0]['metadata']
        metadata['storage']['target_mask_key'] = 'target_mask'
        metadata['target_mask_info'] = {'source': 'fixture', 'version': 'v1'}
        receipt = {key: metadata[key] for key in ('frame_id', 'session_id', 'specimen_id')}
        receipt.update(file='target.npz', sha256=digest(self.intake / 'target.npz'),
                       source='fixture', version='v1', depth_alignment_evidence='alignment')
        self.basis['frames'][0]['target'] = receipt
        for key, wrong in [('frame_id', 'wrong'), ('session_id', 'wrong'), ('specimen_id', 'wrong'),
                           ('source', 'wrong'), ('version', 'wrong')]:
            original = receipt[key]
            receipt[key] = wrong
            run, report = self.run_it()
            self.assertEqual(report['status'], 'failure')
            self.not_published(run)
            receipt[key] = original
        run, report = self.run_it()
        self.assertEqual(report['status'], 'passed_file_boundary_validation')
        np.testing.assert_array_equal(read_session(run / 'session')[0].target_mask, target)

    def test_exclusive_publication_paths_do_not_replace_files(self):
        folder = self.base / 'owned_run'
        folder.mkdir()
        source, destination = folder / 'source', folder / 'destination'
        source.write_text('new')
        destination.write_text('existing')
        with self.assertRaises(ContractError):
            pipeline.rename_new(source, destination, folder)
        self.assertEqual(destination.read_text(), 'existing')
        with self.assertRaises(ContractError):
            pipeline.rename_new(source, self.base / 'outside', folder)


class AuxiliaryReviewTests(unittest.TestCase):
    setUp = fixtures.AuxiliaryBoundaryTests.setUp
    annotation = fixtures.AuxiliaryBoundaryTests.annotation
    image = fixtures.AuxiliaryBoundaryTests.image
    write = fixtures.AuxiliaryBoundaryTests.write

    def test_matching_core_annotation_requires_full_mask_equality(self):
        row = self.annotation()
        self.frames[0] = attach_target(self.frames[0], np.zeros((2, 2), dtype=bool), row['source'], row['version'])
        self.write('annotations.jsonl', row)
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'TARGET_INVALID')

    def test_annotation_dtype_shape_whitespace_and_path_escape(self):
        row = self.annotation()
        for array in (np.ones((2, 2), dtype=np.uint8), np.ones((1, 2), dtype=bool)):
            np.savez_compressed(self.session / 'model_mask.npz', target_mask=array)
            row['sha256'] = digest(self.session / 'model_mask.npz')
            self.write('annotations.jsonl', row)
            with self.assertRaises(ContractError):
                check_auxiliary(self.session, self.frames)
        row = self.annotation()
        row['source'] = ' '
        self.write('annotations.jsonl', row)
        with self.assertRaises(ContractError):
            check_auxiliary(self.session, self.frames)
        row['source'] = 'fixture'
        row['mask_file'] = '../escape.npz'
        self.write('annotations.jsonl', row)
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'PATH_INVALID')

    def test_verified_rgb_requires_times_and_typed_evidence(self):
        row = self.image()
        row.update(pair_status='verified', pair_evidence=True, aligned_to_depth=True,
                   alignment_method='synthetic mapping', calibration_id=self.frames[0].metadata['intrinsics']['calibration_id'])
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError):
            check_auxiliary(self.session, self.frames)
        row['pair_evidence'] = 'explicit synthetic same-frame fixture'
        row['time'] = {'ns': None, 'clock_domain': None, 'origin': None}
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError):
            check_auxiliary(self.session, self.frames)

    def test_auxiliary_jsonl_symlink_escape(self):
        outside = self.base / 'outside.jsonl'
        outside.write_text('')
        try:
            os.symlink(outside, self.session / 'annotations.jsonl')
        except OSError as error:
            self.skipTest(f'Windows symlink capability unavailable: {error}')
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'PATH_INVALID')

    def test_malformed_alignment_method_and_ids_are_contract_failures(self):
        row = self.image()
        row.update(aligned_to_depth=True, alignment_method=123,
                   calibration_id=self.frames[0].metadata['intrinsics']['calibration_id'])
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError):
            check_auxiliary(self.session, self.frames)
        row['session_id'] = []
        self.write('images.jsonl', row)
        with self.assertRaises(ContractError) as error:
            check_auxiliary(self.session, self.frames)
        self.assertEqual(error.exception.code, 'FRAME_MAPPING_INVALID')


if __name__ == '__main__':
    unittest.main()
