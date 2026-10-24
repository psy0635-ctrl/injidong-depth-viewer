import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP') and os.environ.get('INJIDONG_TEST_GUI')=='1', 'explicit reference ZIP and GUI opt-in required')
class ServerTkTests(unittest.TestCase):
    def check(self,case):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(os.environ.get('PC_HTTP_EVIDENCE',tmp))/case
            command=[sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('server_tk_probe.py')),'--case',case,'--work',str(root)]
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',MPLCONFIGDIR=str(root/'mpl'))
            r=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            root.mkdir(parents=True,exist_ok=True)
            for suffix,value in (('stdout.txt',r.stdout),('stderr.txt',r.stderr),('exit.txt',str(r.returncode))):(root/('child.'+suffix)).write_text(value,encoding='utf-8')
            self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(r.stderr,'')
            data=json.loads((root/'result.json').read_text(encoding='utf-8'))
            self.assertTrue(data['assertions_passed'] and data['cache_clean']);self.assertEqual(data['orphan_timers'],[])
            self.assertNotEqual(data['pid'],data['fixture_pid'])
    def test_list_download_real_frames_roi_and_reopen(self):self.check('workflow')
    def test_cancel_during_body_keeps_current_roi(self):self.check('cancel_download')
    def test_close_during_body(self):self.check('close_download')
    def test_cancel_during_actual_loader_keeps_current_roi(self):self.check('cancel_loading')
    def test_close_during_actual_loader(self):self.check('close_loading')
    def test_new_request_rejects_old_queued_result(self):self.check('stale_result')
    def test_close_with_validated_network_session_queued(self):self.check('queued_close')
if __name__=='__main__':unittest.main()
