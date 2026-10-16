"""Synthetic RGB index compatibility regressions; no geometry or device calls."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import test_mobile_session as fixtures
import check_mobile_session as checker
import run_mobile_intake as runner


class RGBIndexCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MobileIntakeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.session = self.fixture.session

    def use_new_format(self):
        (self.session / 'rgb_index.jsonl').rename(self.session / 'images.jsonl')
        files = self.fixture.summary['files']
        del files['phone_rgb_index']
        files['images_index'] = 'images.jsonl'
        self.write_summary()

    def write_summary(self):
        fixtures.put(self.session / 'session.json', self.fixture.summary)

    def cli(self, expected, reason=None):
        # Link fixtures deliberately cannot be enumerated with inventory().
        cmd = [sys.executable, '-B', '-X', 'utf8', str(Path(checker.__file__)),
               str(self.session), '--contract-root', str(fixtures.BASE),
               '--report-dir', str(self.fixture.root / 'reports')]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(result.stderr, '')
        report = json.loads(Path(result.stdout.strip()).read_text(encoding='utf-8'))
        runner.validate_report(report, expected)
        for key in ('geometry_verified', 'processing_ready', 'viewer_launched',
                    'sdk_values_independently_verified', 'common_framepacket_fully_validated'):
            self.assertIs(report[key], False)
        if reason:
            self.assertIn(reason, report['error'])
            self.assertEqual(report['error'], report['rgb_index']['error'])
        return report

    def test_legacy_format_reports_selection_and_runner_accepts_it(self):
        report = self.cli(0)
        selected = report['rgb_index']
        self.assertEqual(selected['policy_id'], 'mobile-rgb-index-compat-review-v1')
        self.assertEqual(selected['selected_key'], 'phone_rgb_index')
        self.assertEqual(selected['declared_path'], 'rgb_index.jsonl')
        self.assertEqual(selected['used_relative_path'], 'rgb_index.jsonl')
        self.assertEqual(selected['sha256'], checker.digest(self.session / 'rgb_index.jsonl'))
        self.assertEqual(report['counts'], self.fixture.summary['counts'])

    def test_new_format_reports_selection_and_is_not_an_auxiliary_file(self):
        self.use_new_format()
        report = self.cli(0)
        selected = report['rgb_index']
        self.assertEqual(selected['selected_key'], 'images_index')
        self.assertEqual(selected['declared_path'], 'images.jsonl')
        self.assertEqual(selected['used_relative_path'], 'images.jsonl')
        self.assertEqual(selected['sha256'], checker.digest(self.session / 'images.jsonl'))
        self.assertEqual(report['additional_files'], [])
        self.assertEqual(report['input_sha256']['images.jsonl'], selected['sha256'])

    def test_both_keys_rejected_even_if_paths_are_identical(self):
        for path in ('rgb_index.jsonl', 'images.jsonl'):
            with self.subTest(second_path=path):
                self.fixture.summary['files']['images_index'] = path
                self.write_summary()
                report = self.cli(1, 'exactly one RGB index key')
                self.assertEqual(set(report['rgb_index']['candidate_keys']),
                                 {'phone_rgb_index', 'images_index'})
                self.assertIsNone(report['rgb_index']['selected_key'])
                self.assertIsNone(report['rgb_index']['sha256'])

    def test_both_files_rejected_even_when_identical(self):
        (self.session / 'images.jsonl').write_bytes((self.session / 'rgb_index.jsonl').read_bytes())
        report = self.cli(1, 'only candidate entry')
        self.assertEqual(len(report['rgb_index']['candidate_entries']), 2)

    def test_both_files_rejected_when_different(self):
        (self.session / 'images.jsonl').write_text('broken alternate index', encoding='utf-8')
        self.cli(1, 'only candidate entry')

    def test_undeclared_other_index_without_selected_file_is_rejected(self):
        (self.session / 'rgb_index.jsonl').rename(self.session / 'images.jsonl')
        self.cli(1, 'only candidate entry')

    def test_no_key_is_rejected_with_observed_entry(self):
        del self.fixture.summary['files']['phone_rgb_index']
        self.write_summary()
        report = self.cli(1, 'exactly one RGB index key')
        self.assertEqual(report['rgb_index']['candidate_keys'], [])
        self.assertEqual(report['rgb_index']['candidate_entries'],
                         [{'name': 'rgb_index.jsonl', 'kind': 'file'}])

    def test_missing_declared_file_does_not_invent_a_hash(self):
        (self.session / 'rgb_index.jsonl').unlink()
        report = self.cli(1, 'only candidate entry')
        self.assertEqual(report['rgb_index']['selected_key'], 'phone_rgb_index')
        self.assertIsNone(report['rgb_index']['sha256'])

    def test_crossed_key_path_combinations_are_rejected(self):
        for key, name in [('phone_rgb_index', 'images.jsonl'), ('images_index', 'rgb_index.jsonl')]:
            with self.subTest(key=key):
                self.fixture.summary['files'].pop('phone_rgb_index', None)
                self.fixture.summary['files'].pop('images_index', None)
                self.fixture.summary['files'][key] = name
                self.write_summary()
                self.cli(1, 'key/path combination mismatch')

    def test_other_files_fields_remain_strict(self):
        for key, value in [('depth_index', 'other.jsonl'), ('unexpected', 'notes.json')]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.fixture.summary['files'])
                self.fixture.summary['files'][key] = value
                self.write_summary()
                self.cli(1, 'unexpected mobile file layout')
                self.fixture.summary['files'] = original

    def test_corrupt_selected_index_retains_selection_and_actual_hash(self):
        self.use_new_format()
        (self.session / 'images.jsonl').write_text('{broken', encoding='utf-8')
        report = self.cli(1)
        selected = report['rgb_index']
        self.assertEqual(selected['selected_key'], 'images_index')
        self.assertEqual(selected['used_relative_path'], 'images.jsonl')
        self.assertEqual(selected['sha256'], checker.digest(self.session / 'images.jsonl'))
        self.assertIn('error', selected)

    def test_corrupt_selected_index_with_healthy_alternate_never_falls_back(self):
        (self.session / 'images.jsonl').write_bytes((self.session / 'rgb_index.jsonl').read_bytes())
        (self.session / 'rgb_index.jsonl').write_text('{broken', encoding='utf-8')
        self.cli(1, 'only candidate entry')

    def test_selected_directory_rejected(self):
        (self.session / 'rgb_index.jsonl').unlink()
        (self.session / 'rgb_index.jsonl').mkdir()
        report = self.cli(1, 'regular file')
        self.assertEqual(report['rgb_index']['candidate_entries'][0]['kind'], 'directory')

    def test_alternate_directory_counts_as_a_conflict(self):
        (self.session / 'images.jsonl').mkdir()
        self.cli(1, 'only candidate entry')

    def test_new_format_keeps_rgb_row_error_detection(self):
        self.use_new_format()
        cases = [('frame_id', 'unknown', 'unknown frame'),
                 ('sha256', '0' * 64, 'RGB hash mismatch'),
                 ('file', 'rgb/missing.png', 'No such file'),
                 ('pair_status', 'verified', 'claims verified alignment'),
                 ('time', {'ns': '1.5', 'clock_domain': 'android_camera_sensor', 'origin': 'sensor'}, 'decimal string')]
        for key, value, reason in cases:
            with self.subTest(field=key):
                row = copy.deepcopy(self.fixture.rgb)
                row[key] = value
                fixtures.put(self.session / 'images.jsonl', row)
                # Missing-file wording varies by operating system.
                self.cli(1, None if key == 'file' else reason)

    def test_both_formats_reject_unsafe_image_paths(self):
        for new in (False, True):
            if new:
                self.use_new_format()
            name = 'images.jsonl' if new else 'rgb_index.jsonl'
            for path in ('../escape.png', '/absolute.png', 'C:/escape.png', '//server/share/escape.png'):
                with self.subTest(new_format=new, path=path):
                    row = copy.deepcopy(self.fixture.rgb)
                    row['file'] = path
                    fixtures.put(self.session / name, row)
                    self.cli(1, 'PATH_INVALID')

    def test_declared_paths_are_not_general_path_aliases(self):
        for path in ('../rgb_index.jsonl', '/rgb_index.jsonl', 'C:/rgb_index.jsonl',
                     '//server/share/rgb_index.jsonl', './rgb_index.jsonl'):
            with self.subTest(path=path):
                self.fixture.summary['files']['phone_rgb_index'] = path
                self.write_summary()
                self.cli(1, 'key/path combination mismatch')

    def test_new_format_duplicate_rgb_reference_rejected(self):
        self.use_new_format()
        row = json.dumps(self.fixture.rgb)
        (self.session / 'images.jsonl').write_text(row + '\n' + row, encoding='utf-8')
        self.cli(1, 'duplicate RGB file')

    def test_new_format_missing_image_is_rejected(self):
        self.use_new_format()
        (self.session / self.fixture.rgb['file']).unlink()
        self.cli(1)

    def test_new_format_rgba_is_not_silently_accepted(self):
        self.use_new_format()
        path = self.session / self.fixture.rgb['file']
        fixtures.Image.new('RGBA', (3, 2)).save(path)
        row = copy.deepcopy(self.fixture.rgb)
        row['sha256'] = checker.digest(path)
        fixtures.put(self.session / 'images.jsonl', row)
        self.cli(1, 'RGBA requires format review')

    def test_hash_failure_preserves_selection_without_fake_hash(self):
        real_digest = checker.digest
        index = self.session / 'rgb_index.jsonl'

        def deny_index(path):
            if Path(path).resolve() == index.resolve():
                raise PermissionError('mock index hash read denied')
            return real_digest(path)

        with mock.patch.object(checker, 'digest', side_effect=deny_index):
            with self.assertRaises(checker.IntakeError) as caught:
                checker.inspect_session(self.session, fixtures.BASE)
        selected = caught.exception.details['rgb_index']
        self.assertEqual(selected['used_relative_path'], 'rgb_index.jsonl')
        self.assertIsNone(selected['sha256'])
        self.assertIn('mock index hash read denied', selected['error'])

    def test_read_failure_after_hash_preserves_selection(self):
        real_rows = checker.rows

        def deny_index(path):
            if Path(path).name == 'rgb_index.jsonl':
                raise OSError('mock index parse read denied')
            return real_rows(path)

        with mock.patch.object(checker, 'rows', side_effect=deny_index):
            with self.assertRaises(checker.IntakeError) as caught:
                checker.inspect_session(self.session, fixtures.BASE)
        selected = caught.exception.details['rgb_index']
        self.assertEqual(selected['sha256'], checker.digest(self.session / 'rgb_index.jsonl'))
        self.assertIn('mock index parse read denied', selected['error'])

    def make_symlink(self, link, target):
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f'Actual symlink creation unavailable: {type(error).__name__}: {error}')

    def test_actual_selected_file_symlink_rejected(self):
        index = self.session / 'rgb_index.jsonl'
        target = self.fixture.root / 'index_target.jsonl'
        index.rename(target)
        self.make_symlink(index, target)
        self.cli(1, 'linked input')

    def test_actual_dangling_alternate_symlink_counts_as_conflict(self):
        self.make_symlink(self.session / 'images.jsonl', self.fixture.root / 'missing_target')
        report = self.cli(1, 'only candidate entry')
        self.assertEqual(len(report['rgb_index']['candidate_entries']), 2)

    def test_actual_dangling_selected_symlink_rejected(self):
        index = self.session / 'rgb_index.jsonl'
        index.unlink()
        self.make_symlink(index, self.fixture.root / 'missing_target')
        self.cli(1, 'linked input')

    def make_junction(self, name):
        if os.name != 'nt':
            self.skipTest('Actual Windows junction test requires Windows')
        link = self.session / name
        target = self.fixture.root / 'junction_target'
        target.mkdir()
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if result.returncode:
            self.skipTest('Actual junction creation unavailable: ' +
                          (result.stdout + result.stderr).decode(errors='replace'))
        self.addCleanup(lambda: os.rmdir(link) if os.path.lexists(link) else None)
        return link

    def test_actual_selected_windows_junction_rejected(self):
        (self.session / 'rgb_index.jsonl').unlink()
        self.make_junction('rgb_index.jsonl')
        self.cli(1, 'linked input')

    def test_actual_alternate_windows_junction_counts_as_conflict(self):
        self.make_junction('images.jsonl')
        self.cli(1, 'only candidate entry')


if __name__ == '__main__':
    unittest.main()
