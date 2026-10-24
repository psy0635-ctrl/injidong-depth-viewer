"""Portable file/HTTP/ROI integration using generated synthetic input only."""
import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from make_synthetic_demo import create_archive,SID
from mobile_session import load_mobile_zip
from mobile_roi import MobileROI,prepare_review
from roi_core import id_hash,select_mask
from verified_mobile_zip import load_verified_mobile_zip,VerifiedZipError
from http_fixture import FixtureServer
from pc_http import ClientConfig,list_sessions,download_session,PCHttpError


class SyntheticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.archive=self.root/'synthetic.zip'
        self.expected=create_archive(self.archive)

    def test_explicit_expectations_and_frame_geometry(self):
        s=load_verified_mobile_zip(self.archive,SID,self.expected['zip_size_bytes'],self.expected['zip_sha256'],self.root/'cache')
        try:
            self.assertEqual(s.frame_ids,['synthetic_0001','synthetic_0002'])
            self.assertFalse(s.report['rgb_alignment_verified'])
            view=s.select(0,17);v,u=np.nonzero(view.frame.valid_mask)
            np.testing.assert_array_equal(view.points_m[:,2],view.frame.depth_m[v,u])
            self.assertEqual(len(view.display_points_m),17)
            self.assertEqual(view.frame.metadata['provenance']['kind'],'synthetic')
            self.assertEqual(view.frame.metadata['schema_version'],'1.0.0')
        finally:s.close()
        self.assertEqual(list((self.root/'cache').iterdir()),[])

    def test_wrong_expected_digest_rejected(self):
        with self.assertRaises(VerifiedZipError):
            load_verified_mobile_zip(self.archive,SID,self.expected['zip_size_bytes'],'0'*64,self.root/'cache')

    def test_new_archive_never_overwrites_input(self):
        before=self.archive.read_bytes()
        with self.assertRaises(FileExistsError):create_archive(self.archive)
        self.assertEqual(self.archive.read_bytes(),before)

    def test_roi_save_close_reopen_separate_process(self):
        s=load_mobile_zip(self.archive,self.root/'cache')
        try:
            data=prepare_review(s,0,[2,2,12,20]);box=[-.02,.02,-.015,.015]
            mask=select_mask(data.coordinates,box);rows=np.arange(0,len(mask),3,dtype=np.int64)
            adapter=MobileROI(s,0);p=adapter.save(self.root/'bundle',data,box,rows)
            restored,label=adapter.open(p)
            self.assertEqual(label['id_sha256'],id_hash(data.cloud.pixel_id[mask]))
            self.assertFalse(data.evidence['rgb_used']);self.assertFalse(data.cloud.color_candidate.any())
            self.assertEqual(label['schema_version'],'1.0.0')
            self.assertIn('검토',label['notice']);self.assertEqual(label['purpose'],'local review auxiliary only')
        finally:s.close()
        result=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve().parents[1]/'mobile_roi.py'),'--archive',str(self.archive),'--bundle',str(p),'--cache',str(self.root/'child')],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        answer=json.loads(result.stdout)
        self.assertEqual(answer['id_sha256'],label['id_sha256']);self.assertTrue(answer['cache_clean'])

    def test_loopback_list_page_download_validates_and_cleans(self):
        with FixtureServer(self.root/'server',self.archive,SID) as fixture:
            config=ClientConfig(fixture.base)
            page=list_sessions(config)
            self.assertEqual(page.items[0].session_id,SID)
            self.assertEqual(page.items[0].zip_size_bytes,self.expected['zip_size_bytes'])
            self.assertEqual(page.items[0].zip_sha256,self.expected['zip_sha256'])
            self.assertEqual(list_sessions(config,cursor=page.next_cursor).items,())
            session=download_session(config,page.items[0],self.root/'http')
            download=session.download_path
            try:self.assertEqual(session.frame_ids,['synthetic_0001','synthetic_0002'])
            finally:session.close()
            self.assertFalse(download.exists())
            fixture.mode('sha_header')
            with self.assertRaises(PCHttpError) as error:download_session(config,page.items[0],self.root/'bad_http')
            self.assertEqual(error.exception.code,'HEADER_MISMATCH')

    def test_imported_runtime_modules_stay_in_checkout(self):
        import mobile_session,paths,review_data
        paths.load_contract()
        checkout=Path(__file__).resolve().parents[3]
        for module in (mobile_session,paths,review_data,sys.modules['contract']):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(checkout),module.__file__)


if __name__=='__main__':unittest.main()
