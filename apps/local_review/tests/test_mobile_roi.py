"""Real sample integration; GUI subprocess tests are in test_mobile_roi_tk.py."""
import copy,hashlib,importlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from mobile_session import load_mobile_zip,digest
from roi_core import id_hash,select_mask,load_bundle
SAMPLE=Path(os.environ.get('MOBILE_TEST_ZIP',str(Path(__file__).with_name('external-sample-not-configured.zip'))))
BOUNDS=[380,120,430,190]  # Depth-only test candidates; physical floor identity NOT verified.

@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP'), 'external reference ZIP not supplied; real integration not run')
class MobileROITests(unittest.TestCase):
    def setUp(self):
        try:self.api=importlib.import_module('mobile_roi')
        except ModuleNotFoundError:self.fail('mobile depth-to-existing-ROI adapter is absent')
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.before=(SAMPLE.stat().st_size,digest(SAMPLE))
        self.s=load_mobile_zip(SAMPLE,self.root/'cache')
    def tearDown(self):
        self.s.close()
        self.assertFalse(any((self.root/'cache').iterdir()))
        self.assertEqual(self.before,(SAMPLE.stat().st_size,digest(SAMPLE)))
        self.temp.cleanup()
    def data(self):return self.api.prepare_review(self.s,0,BOUNDS)
    def test_real_frame_pixel_depth_and_unchanged_metadata(self):
        self.assertEqual(len(self.s.frames),4)
        for i,f in enumerate(self.s.frames):
            view=self.s.select(i,123);v,u=np.nonzero(f.valid_mask)
            np.testing.assert_array_equal(view.points_m[:,2],f.depth_m[v,u])
            self.assertIsNone(f.metadata['pose']);self.assertIsNone(f.metadata['support_plane'])
        d=self.data();v,u=d.cloud.pixel_vu.T
        np.testing.assert_array_equal(d.cloud.pixel_id,v*640+u)
        np.testing.assert_array_equal(d.cloud.points_m[:,2],d.frame.depth_m[v,u])
        self.assertFalse(d.cloud.color_candidate.any())
        self.assertFalse(d.evidence['physical_accuracy_verified'])
        self.assertEqual(d.basis['mobile_support']['candidate_bounds_depth_px'],BOUNDS)
    def test_missing_or_bad_basis_fails_without_fallback(self):
        for box in (None,[0,0,0,1],[-1,0,10,20],[0,0,700,500],[530,400,610,450]):
            with self.subTest(box=box),self.assertRaises(ValueError):self.api.prepare_review(self.s,0,box)
        b=copy.deepcopy(self.data().basis);b['mobile_support']['frame_id']=self.s.frame_ids[1]
        with self.assertRaises(ValueError):self.api.prepare_review(self.s,0,saved_basis=b)
    def test_save_close_separate_process_reopen_exact_contract(self):
        d=self.data();q=d.coordinates
        box=[float(x) for x in np.quantile(q[:,0],[.25,.75])]+[float(x) for x in np.quantile(q[:,1],[.25,.75])]
        rows=np.arange(0,len(q),40,dtype=np.int64)
        p=self.api.MobileROI(self.s,0).save(self.root/'bundle',d,box,rows)
        expected=d.cloud.pixel_id[select_mask(q,box)]
        label=json.loads((p/'roi.json').read_text(encoding='utf-8'))
        np.testing.assert_array_equal(label['selected_pixel_id'],expected)
        self.s.close()
        result=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(self.api.__file__).with_name('mobile_roi.py')),
            '--archive',str(SAMPLE),'--bundle',str(p),'--cache',str(self.root/'child_cache')],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertEqual(result.stderr,'')
        restored=json.loads(result.stdout)
        self.assertEqual(restored['id_sha256'],id_hash(expected));self.assertEqual(restored['selected_count'],len(expected))
        self.assertEqual(restored['basis'],d.basis);self.assertTrue(restored['cache_clean'])
        self.assertNotEqual(restored['pid'],os.getpid())
        self.assertEqual(label['id_serialization'],'signed int64 little-endian, C contiguous bytes, original full-cloud row order; no header')
    def test_wrong_frame_archive_and_corrupted_bundle_refused(self):
        d=self.data();adapter=self.api.MobileROI(self.s,0)
        from paths import PRIOR_REVIEW
        with self.subTest(case='robot_legacy_is_not_mobile'),self.assertRaises(ValueError):adapter.open(PRIOR_REVIEW)
        p=adapter.save(self.root/'bundle',d,None,np.arange(0,len(d.coordinates),100,dtype=np.int64))
        with self.assertRaises(ValueError):self.api.MobileROI(self.s,1).open(p)
        other=self.root/'other.zip';other.write_bytes(SAMPLE.read_bytes()+b'changed source')
        s2=load_mobile_zip(other,self.root/'cache')
        try:
            with self.assertRaises(ValueError):self.api.MobileROI(s2,0).open(p)
        finally:s2.close()
        # Ordinary robot opener must never silently interpret a mobile bundle.
        with self.assertRaises(ValueError):load_bundle(p)
        with (p/'review_arrays.npz').open('ab') as f:f.write(b'corruption')
        with self.assertRaises(ValueError):adapter.open(p)
    def test_output_guards_and_basis_restored_without_refit(self):
        from unittest.mock import patch
        d=self.data();a=self.api.MobileROI(self.s,0);rows=np.arange(0,len(d.coordinates),100,dtype=np.int64)
        p=a.save(self.root/'bundle',d,None,rows)
        with self.assertRaises(FileExistsError):a.save(p,d,None,rows)
        with self.assertRaises(ValueError):a.save(self.s.session_dir/'bad_output',d,None,rows)
        with self.subTest(case='loader_owner_root'),self.assertRaises(ValueError):a.save(Path(self.s.owner.name)/'bad_output',d,None,rows)
        with patch.object(self.api,'fit_robust',side_effect=AssertionError('must reuse saved axes')):
            restored,label=a.open(p)
        self.assertEqual(restored.basis,d.basis)
        np.testing.assert_array_equal(restored.coordinates,d.coordinates)

if __name__=='__main__':unittest.main()
