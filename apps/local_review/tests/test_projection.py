import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'lib/color'))
import tempfile,unittest
from pathlib import Path
import numpy as np
from projection import plane_basis,to_plane,from_plane,painter_rows,save_review_arrays

class ProjectionTests(unittest.TestCase):
    def test_horizontal_known_coordinates_and_signed_distance(self):
        b=plane_basis([0,0,-1,2])
        np.testing.assert_allclose(b['origin_m'],[0,0,2])
        np.testing.assert_allclose(to_plane(np.array([[1,3,1],[0,0,3.]]),b),[[1,-3,1],[0,0,-1]])

    def test_tilted_plane_hand_computed_projection(self):
        b=plane_basis([0,-1,-1,2])
        np.testing.assert_allclose(to_plane(np.array([[2,0,2],[2,0,1.]]),b),[[2,np.sqrt(2),0],[2,1/np.sqrt(2),1/np.sqrt(2)]],atol=1e-14)

    def test_unit_orthogonal_right_handed_axes(self):
        b=plane_basis([.2,-.4,-.8,.1])
        u,v,n=[np.array(b[k]) for k in ('u_axis','v_axis','normal')]
        np.testing.assert_allclose(np.stack((u,v,n))@np.stack((u,v,n)).T,np.eye(3),atol=1e-14)
        np.testing.assert_allclose(np.cross(u,v),n,atol=1e-14)
        self.assertGreater(np.dot(n,-np.array(b['origin_m'])),0)

    def test_reconstruction_preserves_known_XYZ(self):
        b=plane_basis([0,0,-1,2])
        np.testing.assert_allclose(from_plane(np.array([[1,-3,1],[0,0,-1.]]),b),[[1,3,1],[0,0,3]])
        p=np.array([[.01,-.03,.1],[-.04,.1,.25],[2,3,6.55]])
        b=plane_basis([.2,-.4,-.8,.1])
        np.testing.assert_allclose(from_plane(to_plane(p,b),b),p,atol=1e-14)

    def test_plane_sign_flip_does_not_change_camera_facing_basis(self):
        a=plane_basis([0,-1,-1,2]);b=plane_basis([0,1,1,-2])
        for k in ('origin_m','u_axis','v_axis','normal'):np.testing.assert_array_equal(a[k],b[k])

    def test_parallel_camera_X_uses_camera_Y_fallback(self):
        b=plane_basis([1,0,0,-1])
        np.testing.assert_allclose(b['origin_m'],[1,0,0]);np.testing.assert_allclose(b['u_axis'],[0,1,0]);np.testing.assert_allclose(b['v_axis'],[0,0,-1])
        b=plane_basis([1,1e-12,0,-1]);self.assertEqual(b['reference_axis'],'camera_Y')
        b=plane_basis([1,0,0,0]);self.assertFalse(b['camera_side_resolved'])

    def test_invalid_planes_points_and_basis_rejected(self):
        for bad in ([0,0,0,1],[0,np.nan,1,2],[0,1,2]):
            with self.assertRaises(ValueError):plane_basis(bad)
        b=plane_basis([0,0,1,-2])
        for bad in (np.zeros((2,2)),np.array([[0,0,np.inf]])):
            with self.assertRaises(ValueError):to_plane(bad,b)
        b['u_axis']=[0,0,0]
        with self.assertRaises(ValueError):to_plane(np.zeros((2,3)),b)

    def test_painter_order_retains_point_ID_tie_break(self):
        coords=np.array([[0,0,3],[0,0,1],[0,0,3.]])
        np.testing.assert_array_equal(painter_rows(coords,np.array([10,11,12]),np.array([2,0,1])),[1,0,2])

    def test_saved_full_correspondence_and_bad_shapes(self):
        payload=dict(points_m=np.array([[1,3,1],[0,0,3],[2,0,2]],dtype=np.float32),
            pixel_id=np.array([4,9,11],dtype=np.int64),pixel_vu=np.array([[0,4],[1,3],[1,5]],dtype=np.int64),
            rgb_u8=np.array([[1,2,3],[0,0,0],[50,60,70]],dtype=np.uint8),color_candidate=np.array([True,False,True]),
            plane_coordinates_m=np.array([[1,-3,1],[0,0,-1],[2,0,0]],dtype=np.float64),
            display_full_rows=np.array([0,2],dtype=np.int64),draw_order_full_rows=np.array([2,0],dtype=np.int64))
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'review.npz';save_review_arrays(p,**payload)
            with np.load(p,allow_pickle=False) as z:
                self.assertEqual(set(z.files),set(payload))
                for k,v in payload.items():np.testing.assert_array_equal(z[k],v)
            bad={**payload,'rgb_u8':np.zeros((2,3),dtype=np.uint8)}
            with self.assertRaises(ValueError):save_review_arrays(Path(directory)/'bad.npz',**bad)
            with self.assertRaises(FileExistsError):save_review_arrays(p,**payload)

if __name__=='__main__':unittest.main()
