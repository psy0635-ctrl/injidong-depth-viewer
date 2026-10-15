"""Runner unit tests with a FAKE checker/baseline, not device compatibility tests."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUNNER = Path(__file__).resolve().parents[1] / 'run_mobile_intake.py'
spec = importlib.util.spec_from_file_location('mobile_intake_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

FAKE_CHECKER = r'''
import argparse,hashlib,json,os,time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('session',type=Path)
p.add_argument('--contract-root')
p.add_argument('--report-dir',type=Path)
a=p.parse_args()
mode=Path(__file__).with_name('mode.txt').read_text()
if mode=='timeout':time.sleep(10)
if mode=='crash':
    print('simulated abnormal exit',flush=True)
    raise SystemExit(7)
if mode=='missing':
    raise SystemExit(0)
hashes={f.relative_to(a.session).as_posix():hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(a.session.rglob('*')) if f.is_file()}
if mode=='changed':(a.session/'payload.bin').write_bytes(b'changed')
if mode=='added':(a.session/'extra.txt').write_text('new')
if mode=='removed':(a.session/'payload.bin').unlink()
if mode=='changed_before_report':
    (a.session/'payload.bin').write_bytes(b'changed')
    hashes={f.relative_to(a.session).as_posix():hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(a.session.rglob('*')) if f.is_file()}
r={'status':'passed_mobile_file_checks','geometry_verified':False,'processing_ready':False,
   'rgb_depth_alignment_verified':False,'world_pose_verified':False,
   'environment':{'python':'fake','numpy':'fake','platform':'fake'},
   'input_sha256':hashes,'data_kind':'synthetic','core_loader_compatible':True,
   'server_uploaded':False,'counts':{'depth_frames':1,'phone_rgb_images':1,'imu_samples':1},
   'depth_frames':[{}],'imu_sensor_types':[],'warnings':[],'additional_files':[],
   'unreferenced_collection_files':[],'remaining':[], 'mobile_commit_reference':'b'*40}
if mode=='failed':
    r={'status':'failed_mobile_file_checks','error':'fixture rejected',
       'geometry_verified':False,'processing_ready':False,'rgb_depth_alignment_verified':False,
       'world_pose_verified':False,'environment':r['environment']}
if mode=='true':r.update(geometry_verified=True,processing_ready=True)
if mode=='bool_string':r['processing_ready']='false'
if mode=='bool_number':r['geometry_verified']=0
if mode=='hash_mismatch':r['input_sha256']['payload.bin']='0'*64
if mode=='hash_missing':del r['input_sha256']
if mode=='top_list':r=[]
path=a.report_dir/('mobile_check_'+'a'*32+'.json')
path.write_text('{' if mode=='corrupt' else json.dumps(r),encoding='utf-8')
if mode=='duplicate_key':path.write_text('{"status":1,"status":2}',encoding='utf-8')
if mode=='multiple':
    (a.report_dir/('mobile_check_'+'c'*32+'.json')).write_text(json.dumps(r))
print(str(Path(__file__).with_name('old_report.json')) if mode=='stale_path' else str(path))
raise SystemExit(1 if mode in ('failed','mismatch') else 0)
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mobile_runner_unit_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.session = self.root / 'input'
        self.session.mkdir()
        (self.session / 'payload.bin').write_bytes(b'original')
        self.base = self.root / 'baseline'
        (self.base / 'src').mkdir(parents=True)
        (self.base / 'schemas').mkdir()
        (self.base / 'src/contract.py').write_text('# fake baseline for unit tests\n')
        (self.base / 'src/session_boundary.py').write_text(
            'def guard_read(path):\n'
            '    from pathlib import Path\n'
            '    if (Path(path)/"reject_guard").exists():\n'
            '        raise ValueError("SESSION_UNCOMMITTED: fake guard rejection")\n')
        (self.base / 'schemas/frame.schema.json').write_text('{}')
        self.code = self.root / 'fake_checker'
        self.code.mkdir()
        self.checker = self.code / 'check_mobile_session.py'
        self.checker.write_text(FAKE_CHECKER, encoding='utf-8')
        expected = {name: runner.digest(self.base / name) for name in runner.BASELINE_FILES}
        (self.code / 'baseline_hashes.json').write_text(json.dumps(expected))
        self.output = self.root / 'results'

    def invoke(self, mode='passed', output=None, timeout=300):
        (self.code / 'mode.txt').write_text(mode)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = runner.main(['--python', sys.executable, '--checker', str(self.checker),
                                '--contract-root', str(self.base), '--session', str(self.session),
                                '--result-root', str(output if output is not None else self.output),
                                '--timeout-seconds', str(timeout)])
        self.stderr_output = stderr.getvalue()
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, result['exit_code'])
        self.assertIs(result['geometry_verified'], False)
        self.assertIs(result['processing_ready'], False)
        self.assertIs(result['viewer_launched'], False)
        if result['summary_path']:
            self.assertEqual(json.loads(Path(result['summary_path']).read_text(encoding='utf-8')), result)
        return code, result

    def test_pass_is_held_and_each_run_is_exclusive(self):
        code, first = self.invoke()
        self.assertEqual(code, 10)
        self.assertEqual(first['final_status'], 'processing_held')
        self.assertEqual(first['issues'], [])
        self.assertTrue(first['input_verification']['before_after']['matched'])
        self.assertTrue(first['input_verification']['checker_report_comparison']['matched'])
        report = Path(first['checker_report'])
        saved = report.read_bytes()
        _, second = self.invoke()
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(report.read_bytes(), saved)
        self.assertFalse(list(self.session.glob('.ade71*')))

    def test_checker_failure_preserves_reason_report_and_logs(self):
        code, result = self.invoke('failed')
        self.assertEqual(code, 20)
        self.assertEqual(result['reason'], 'fixture rejected')
        self.assertEqual(result['checker_exit_code'], 1)
        self.assertTrue(Path(result['checker_report']).is_file())
        self.assertEqual(result['input_verification']['checker_report_comparison'], 'not_available')
        self.assertTrue(result['input_verification']['before_after']['matched'])
        for path in result['logs'].values():
            self.assertTrue(Path(path).is_file())

    def test_input_content_change(self):
        code, result = self.invoke('changed')
        self.assertEqual(code, 21)
        self.assertEqual(result['input_verification']['before_after']['modified'], ['payload.bin'])

    def test_file_addition_and_deletion(self):
        code, result = self.invoke('added')
        self.assertEqual(code, 21)
        self.assertEqual(result['input_verification']['before_after']['added'], ['extra.txt'])
        code, result = self.invoke('removed')
        self.assertEqual(code, 21)
        self.assertEqual(result['input_verification']['before_after']['removed'], ['payload.bin'])

    def test_pre_inventory_detects_change_even_if_report_matches_current(self):
        code, result = self.invoke('changed_before_report')
        self.assertEqual(code, 21)
        self.assertTrue(result['input_verification']['checker_report_comparison']['matched'])

    def test_report_hash_mismatch(self):
        code, result = self.invoke('hash_mismatch')
        self.assertEqual(code, 21)
        self.assertTrue(result['input_verification']['before_after']['matched'])
        self.assertFalse(result['input_verification']['checker_report_comparison']['matched'])

    def test_missing_report(self):
        code, result = self.invoke('missing')
        self.assertEqual(code, 23)
        self.assertIn('missing', result['reason'])

    def test_corrupt_report(self):
        code, result = self.invoke('corrupt')
        self.assertEqual(code, 23)
        self.assertTrue(Path(result['checker_report']).is_file())

    def test_status_exit_disagreement(self):
        code, result = self.invoke('mismatch')
        self.assertEqual(code, 23)
        self.assertIn('disagree', result['reason'])

    def test_multiple_reports(self):
        code, result = self.invoke('multiple')
        self.assertEqual(code, 23)
        self.assertIn('multiple', result['reason'])

    def test_stale_stdout_path_is_not_used(self):
        (self.code / 'old_report.json').write_text('{}')
        code, result = self.invoke('stale_path')
        self.assertEqual(code, 23)
        self.assertIn('this invocation', result['reason'])

    def test_strict_report_types_and_required_hash_inventory(self):
        for mode in ('bool_string', 'bool_number', 'top_list', 'hash_missing', 'duplicate_key'):
            with self.subTest(mode=mode):
                code, result = self.invoke(mode)
                self.assertEqual(code, 23)

    def test_true_readiness_still_cannot_launch_processing(self):
        code, result = self.invoke('true')
        self.assertEqual(code, 10)
        self.assertIn('readiness=true', result['reason'])
        report = json.loads(Path(result['checker_report']).read_text(encoding='utf-8'))
        self.assertIs(report['geometry_verified'], True)
        self.assertIs(report['processing_ready'], True)

    def test_abnormal_exit(self):
        code, result = self.invoke('crash')
        self.assertEqual(code, 22)
        self.assertEqual(result['checker_exit_code'], 7)
        self.assertTrue(result['input_verification']['before_after']['matched'])

    def test_timeout_keeps_logs_and_rechecks_input(self):
        code, result = self.invoke('timeout', timeout=1)
        self.assertEqual(code, 22)
        self.assertIn('timeout', result['reason'])
        self.assertIsNone(result['checker_exit_code'])
        self.assertTrue(result['input_verification']['before_after']['matched'])

    def test_log_write_error_is_output_error(self):
        original_open = Path.open

        def fail_log(path, *args, **kwargs):
            if path.name == 'checker_stdout.txt':
                raise OSError('simulated log write failure')
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, 'open', new=fail_log):
            code, result = self.invoke()
        self.assertEqual(code, 25)
        self.assertIsNone(result['checker_exit_code'])
        self.assertTrue(result['input_verification']['before_after']['matched'])

    def test_log_close_failure_is_output_error(self):
        original_open = Path.open

        @contextmanager
        def failing_close(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as stream:
                yield stream
            raise OSError('simulated log close failure')

        def open_log(path, *args, **kwargs):
            if path.name == 'checker_stdout.txt':
                return failing_close(path, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, 'open', new=open_log):
            code, result = self.invoke()
        self.assertEqual(code, 25)
        self.assertEqual(result['checker_exit_code'], 0)
        self.assertIn('simulated log close failure', self.stderr_output)

    def test_storage_failure_remains_primary_when_input_changes(self):
        original_open = Path.open

        @contextmanager
        def failing_close(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as stream:
                yield stream
            raise OSError('simulated log close failure with input change')

        def open_log(path, *args, **kwargs):
            if path.name == 'checker_stdout.txt':
                return failing_close(path, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, 'open', new=open_log):
            code, result = self.invoke('changed')
        self.assertEqual(code, 25)
        self.assertEqual(result['input_verification']['status'], 'changed')
        self.assertIn('input change', self.stderr_output)

    def test_summary_write_failure_never_publishes_final(self):
        original_write = runner.write_new

        def fail_summary(path, value):
            original_write(path, value)
            if path.name.startswith('runner_summary'):
                raise OSError('simulated summary close failure')

        with mock.patch.object(runner, 'write_new', side_effect=fail_summary):
            code, result = self.invoke()
        self.assertEqual(code, 25)
        self.assertIsNone(result['summary_path'])
        self.assertFalse(list(self.output.rglob('runner_summary.json')))
        self.assertIn('simulated summary close failure', self.stderr_output)

    def test_summary_publication_failure_reports_stderr(self):
        original_rename = Path.rename

        def fail_publication(path, destination):
            if path.name == 'runner_summary.pending.json':
                raise OSError('simulated summary rename failure')
            return original_rename(path, destination)

        with mock.patch.object(Path, 'rename', new=fail_publication):
            code, result = self.invoke()
        self.assertEqual(code, 25)
        self.assertIsNone(result['summary_path'])
        self.assertFalse(list(self.output.rglob('runner_summary.json')))
        self.assertIn('simulated summary rename failure', self.stderr_output)

    def test_result_directory_failure_reports_stderr(self):
        original_mkdir = Path.mkdir

        def fail_result_root(path, *args, **kwargs):
            if path == self.output:
                raise OSError('simulated result directory failure')
            return original_mkdir(path, *args, **kwargs)

        with mock.patch.object(Path, 'mkdir', new=fail_result_root):
            code, result = self.invoke()
        self.assertEqual(code, 25)
        self.assertIsNone(result['summary_path'])
        self.assertFalse(self.output.exists())
        self.assertIn('simulated result directory failure', self.stderr_output)

    def test_reject_protected_output_equal_child_and_parent(self):
        for output in (self.session, self.session / 'new', self.base, self.base / 'new',
                       self.code / 'new', self.root):
            with self.subTest(output=str(output)):
                existed = output.exists()
                code, result = self.invoke(output=output)
                self.assertEqual(code, 24)
                self.assertIsNone(result['summary_path'])
                self.assertEqual(output.exists(), existed)
                self.assertFalse(list(self.root.rglob('run_*')))

    def test_baseline_mismatch_before_output_creation(self):
        (self.base / 'src/contract.py').write_text('# changed fake baseline')
        code, result = self.invoke()
        self.assertEqual(code, 24)
        self.assertIn('baseline mismatch', result['reason'])
        self.assertFalse(self.output.exists())

    def test_guard_rejection_before_output_creation(self):
        (self.session / 'reject_guard').touch()
        code, result = self.invoke()
        self.assertEqual(code, 24)
        self.assertIn('SESSION_UNCOMMITTED', result['reason'])
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows Junction test requires Windows')
    def test_windows_junction_output_alias(self):
        alias = self.root / 'input_alias'
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                  'New-Item -ItemType Junction -ErrorAction Stop -Path ' + quote(alias) +
                                  ' -Target ' + quote(self.session) + ' | Out-Null'], capture_output=True)
        if process.returncode != 0 or not alias.is_dir():
            self.skipTest('Junction creation unavailable: ' + process.stderr.decode(errors='replace'))
        # Remove only the link before TemporaryDirectory cleanup, never its target.
        self.addCleanup(lambda: os.rmdir(alias))
        code, result = self.invoke(output=alias / 'new_output')
        self.assertEqual(code, 24)
        self.assertFalse((self.session / 'new_output').exists())


if __name__ == '__main__':
    unittest.main()
