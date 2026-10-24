import os
import unittest,tempfile,copy,json
from pathlib import Path
import numpy as np
import roi_core as roi
from projection import plane_basis,to_plane
class SelectionTests(unittest.TestCase):
    def test_direction_and_inclusive_boundary(self):
        coords=np.array([[0,0,8],[1,1,-5],[.5,.5,0],[1.01,.5,0],[-.01,0,0.]])
        for box in ([0,1,0,1],[1,0,1,0]):
            np.testing.assert_array_equal(roi.select_mask(coords,box),[1,1,1,0,0])
    def test_clear_empty_and_invalid(self):
        q=np.array([[0,0,1.]])
        self.assertFalse(roi.select_mask(q,None).any())
        self.assertFalse(roi.select_mask(q,[2,3,2,3]).any())
        for b in ([0,0,0,1],[0,1,2,2],[0,np.nan,0,1],[0,1,0,np.inf],[0,1,2]):
            with self.assertRaises(ValueError):roi.select_mask(q,b)
    def test_nonfinite_uv_excluded_height_ignored(self):
        q=np.array([[0,0,-200],[0,0,200],[np.nan,0,0],[0,np.inf,1.]])
        np.testing.assert_array_equal(roi.select_mask(q,[-1,1,-1,1]),[1,1,0,0])
    def test_serialization_is_signed_int64_little_endian(self):
        ids=np.array([0,257,65536],dtype=np.int64)
        import hashlib
        self.assertEqual(roi.id_hash(ids),hashlib.sha256(b'\x00'*8+b'\x01\x01'+b'\x00'*6+b'\x00\x00\x01'+b'\x00'*5).hexdigest())
        with self.assertRaises(ValueError):roi.id_hash(np.array([1.]))
    def test_basis_consistency(self):
        b=plane_basis([0,0,-1,2]);roi.validate_basis(b)
        for k,v in [('u_axis',[0,0,0]),('origin_m',[0,0,3]),('normal',[0,0,np.nan]),('oriented_plane_n_d_m',[0,0,-1,9])]:
            broken=copy.deepcopy(b);broken[k]=v
            with self.assertRaises(ValueError):roi.validate_basis(broken)

@unittest.skipUnless(os.environ.get('INJIDONG_ROBOT_REVIEW_ROOT'),'explicit external robot review bundle required')
class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from review_data import load_review
        cls.data=load_review()
    def test_real_source_correspondence_and_display_independence(self):
        from review_data import select_display
        d=self.data;c=d.cloud;v,u=c.pixel_vu.T
        np.testing.assert_array_equal(c.pixel_id,v*640+u)
        np.testing.assert_array_equal(c.points_m[:,2],d.frame.depth_m[v,u])
        box=[-.04,.04,-.02,.12];mask=roi.select_mask(d.coordinates,box);expected=c.pixel_id[mask].copy()
        hashes=[a.tobytes() for a in (c.points_m,c.rgb_u8,c.pixel_id)]
        counts=[]
        for limit,depth in ((50000,(.07,.5)),(257,None),(190949,None)):
            rows=select_display(c,limit,depth);counts.append(int(mask[rows].sum()))
            np.testing.assert_array_equal(c.pixel_id[roi.select_mask(d.coordinates,box)],expected)
        self.assertGreater(mask.sum(),counts[0]);self.assertNotEqual(counts[0],counts[1])
        self.assertEqual(hashes,[a.tobytes() for a in (c.points_m,c.rgb_u8,c.pixel_id)])
    def save(self,p,box=None):
        return roi.save_bundle(p,self.data,box,np.arange(0,len(self.data.cloud.pixel_id),20,dtype=np.int64))
    def test_restore_clear_empty_and_selected(self):
        for box in (None,[50,51,50,51],[-.04,.04,-.02,.12]):
            with self.subTest(box=box),tempfile.TemporaryDirectory() as t:
                p=Path(t)/'bundle';self.save(p,box);d,label=roi.load_bundle(p)
                self.assertEqual(label['roi_uv_m'],box);self.assertEqual(d.basis,self.data.basis)
                np.testing.assert_array_equal(label['selected_pixel_id'],self.data.cloud.pixel_id[roi.select_mask(self.data.coordinates,box)])
                for name in ('points_m','rgb_u8','pixel_id'):np.testing.assert_array_equal(getattr(d.cloud,name),getattr(self.data.cloud,name))
    def test_no_overwrite_and_incomplete_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bundle';self.save(p)
            with self.assertRaises((FileExistsError,ValueError)):self.save(p)
            (p/'COMPLETE.json').unlink()
            with self.assertRaises((ValueError,OSError)):roi.load_bundle(p)
    def test_outside_display_range_selected_points_are_retained(self):
        from review_data import select_display
        d=self.data;q=d.coordinates
        box=[float(q[:,0].min()-1),float(q[:,0].max()+1),float(q[:,1].min()-1),float(q[:,1].max()+1)]
        mask=roi.select_mask(q,box);self.assertTrue(mask.all())
        near=select_display(d.cloud,len(q),(.07,.5));hidden=np.setdiff1d(np.arange(len(q)),near)
        self.assertGreater(len(hidden),0);self.assertTrue(mask[hidden].all())
        np.testing.assert_array_equal(d.cloud.pixel_id[mask],d.cloud.pixel_id)
    def reseal(self,p):
        from review_data import sha
        files={f.name:sha(f) for f in p.iterdir() if f.is_file() and f.name not in ('COMPLETE.json','manifest.json')}
        (p/'manifest.json').write_text(json.dumps(files),encoding='utf-8')
        (p/'COMPLETE.json').write_text(json.dumps({'format':roi.FORMAT,'manifest_sha256':sha(p/'manifest.json')}),encoding='utf-8')
    def test_tampered_inputs_ids_axes_count_and_roi_rejected(self):
        mutations=[lambda a:a['sources'][0].update(sha256='0'*64),lambda a:a.update(selected_pixel_id=[True]),lambda a:a.update(selected_pixel_id=[99999999]),lambda a:a.update(selected_pixel_id=a['selected_pixel_id']*2),lambda a:a['basis'].update(u_axis=[0,0,0]),lambda a:a['basis'].update(origin_m=[0,0,0]),lambda a:a.update(full_point_count=1),lambda a:a.update(selected_count=1),lambda a:a.update(roi_uv_m=[1,2,3,4]),lambda a:a.update(frame_id='other'),lambda a:a.update(id_sha256='0'*64)]
        for mutate in mutations:
            with self.subTest(mutate=mutations.index(mutate)),tempfile.TemporaryDirectory() as t:
                p=Path(t)/'bundle';self.save(p,[-.04,.04,-.02,.12]);a=json.loads((p/'roi.json').read_text(encoding='utf-8'));mutate(a)
                (p/'roi.json').write_text(json.dumps(a),encoding='utf-8');self.reseal(p)
                with self.assertRaises((ValueError,OSError)):roi.load_bundle(p)
    def test_corrupt_file_rejected_without_reseal(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bundle';self.save(p);(p/'review_arrays.npz').write_bytes(b'broken')
            with self.assertRaises(ValueError):roi.load_bundle(p)
    def test_previous_review_bundle_can_be_reopened_read_only(self):
        from paths import PRIOR_REVIEW
        p=PRIOR_REVIEW
        d,a=roi.load_bundle(p)
        self.assertTrue(a['legacy_review_import']);self.assertIsNone(a['roi_uv_m'])
        for name in ('pixel_id','points_m','rgb_u8'):np.testing.assert_array_equal(getattr(d.cloud,name),getattr(self.data.cloud,name))
if __name__=='__main__':unittest.main()
