"""Detect uncancelled viewer timers, Tk/Python errors, hangs, and cleanup leaks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SAMPLE = Path(os.environ.get('MOBILE_TEST_ZIP',str(Path(__file__).with_name('external-sample-not-configured.zip'))))
PROBE = Path(__file__).with_name('tk_close_probe.py')

@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP') and os.environ.get('INJIDONG_TEST_GUI')=='1', 'explicit reference ZIP and GUI opt-in required')
class ShutdownTests(unittest.TestCase):
    def check_case(self, case):
        for drain in (False, True):
            with self.subTest(drain=drain):
                self.run_case(case,drain)

    def run_case(self, case, drain):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', MPLCONFIGDIR=str(Path(tmp)/'mpl'))
            command = [sys.executable,'-B','-X','utf8',str(PROBE),'--case',case,
                '--archive',str(SAMPLE),'--cache',str(Path(tmp)/'cache')]
            if not drain: command.append('--no-drain')
            result = subprocess.run(command,
                capture_output=True,text=True,encoding='utf-8',env=env,timeout=25)
            evidence = os.environ.get('MOBILE_CLOSE_EVIDENCE')
            if evidence:
                out = Path(evidence);out.mkdir(parents=True,exist_ok=True)
                name=case+('.drain' if drain else '.native')
                (out/(name+'.stdout.json')).write_text(result.stdout,encoding='utf-8')
                (out/(name+'.stderr.txt')).write_text(result.stderr,encoding='utf-8')
                (out/(name+'.exit.txt')).write_text(str(result.returncode),encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertEqual(result.stderr,'',result.stderr)
            data=json.loads(result.stdout)
            self.assertTrue(data['assertions_passed'])
            self.assertEqual(data['orphan_timers'],[],data['orphan_timers'])
            self.assertTrue(data['cache_clean'] and data['zip_preserved'])

    def test_close_before_input(self): self.check_case('empty')
    def test_close_before_initial_archive_callback(self): self.check_case('startup')
    def test_close_with_canvas_redraw_pending(self): self.check_case('idle_pending')
    def test_close_while_real_extraction_is_paused(self): self.check_case('checking')
    def test_close_after_validation_before_worker_returns(self): self.check_case('completed_pending')
    def test_close_with_ready_session_queued(self): self.check_case('queued_ready')
    def test_close_after_result_is_accepted(self): self.check_case('ready')
    def test_close_after_frame_switch(self): self.check_case('frame')
    def test_failure_then_reopen_and_close(self): self.check_case('recover')

if __name__ == '__main__': unittest.main()
