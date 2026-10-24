import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
SAMPLE=Path(os.environ.get('MOBILE_TEST_ZIP',str(Path(__file__).with_name('external-sample-not-configured.zip'))))
@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP') and os.environ.get('INJIDONG_TEST_GUI')=='1', 'explicit reference ZIP and GUI opt-in required')
class MobileROITkTests(unittest.TestCase):
    def test_actual_tk_workflow_then_second_process_restore(self):
        evidence=os.environ.get('MOBILE_ROI_EVIDENCE')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(evidence) if evidence else Path(tmp)
            root.mkdir(exist_ok=True,parents=True)
            results=[];bundle=None
            for name in ('workflow','reopen'):
                cmd=[sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('mobile_roi_tk_probe.py')),'--archive',str(SAMPLE),'--root',str(root/name)]
                if bundle:cmd+=['--bundle',str(bundle)]
                r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=50)
                for suffix,value in (('stdout.txt',r.stdout),('stderr.txt',r.stderr),('exit.txt',str(r.returncode))):(root/(name+'.'+suffix)).write_text(value,encoding='utf-8')
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(r.stderr,'')
                data=json.loads((root/name/'result.json').read_text(encoding='utf-8'));results.append(data);bundle=Path(data['bundle'])
                self.assertTrue(data['cache_clean']);self.assertEqual(data['orphan_timers'],[])
            self.assertNotEqual(results[0]['pid'],results[1]['pid'])
            for key in ('selected_pixel_id','id_sha256','basis'):self.assertEqual(results[0][key],results[1][key])
if __name__=='__main__':unittest.main()
