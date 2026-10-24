import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'lib/color'))
import copy,json,sys,unittest
from pathlib import Path
import numpy as np
from paths import load_contract,BASELINE
contract=load_contract()
from color_data import build_color_cloud,select_display,zoom_limits

class ColorTests(unittest.TestCase):
    def fixture(self):
        meta=json.loads((BASELINE/'examples/synthetic/frame_000001/metadata.json').read_text(encoding='utf-8'))
        meta['depth'].update(height=2,width=3)
        meta['intrinsics'].update(height=2,width=3,fx=100,fy=200,cx=1,cy=.5)
        depth=np.array([[1,0,2],[3,4,5]],dtype=np.float32)
        frame=contract.FramePacket(meta,depth,depth>0,None)
        rgb=np.array([[[255,0,0],[0,255,0],[0,0,255]],[[255,255,0],[0,255,255],[255,0,255]]],dtype=np.uint8)
        return frame,rgb

    def cloud(self):
        frame,rgb=self.fixture();value=build_color_cloud(frame,rgb)
        self.assertIsNotNone(value,'adapter must return a cloud with source pixel associations')
        return value

    def test_hand_calculated_XYZ_and_unique_RGB_after_invalid_removal(self):
        # Catches u/v swap, wrong intrinsics, row reordering, RGB/BGR swap.
        c=self.cloud()
        np.testing.assert_array_equal(c.pixel_id,[0,2,3,4,5])
        np.testing.assert_array_equal(c.pixel_vu,[[0,0],[0,2],[1,0],[1,1],[1,2]])
        np.testing.assert_allclose(c.points_m,[[-.01,-.0025,1],[.02,-.005,2],[-.03,.0075,3],[0,.01,4],[.05,.0125,5]],rtol=0,atol=1e-8)
        np.testing.assert_array_equal(c.rgb_u8,[[255,0,0],[0,0,255],[255,255,0],[0,255,255],[255,0,255]])

    def test_sampling_uses_identical_full_rows_for_every_attribute(self):
        # Catches separate color/point sampling or IDs reconstructed after sampling.
        c=self.cloud();d=select_display(c,3)
        self.assertIsNotNone(d)
        np.testing.assert_array_equal(d,[0,2,4])
        np.testing.assert_array_equal(c.pixel_id[d],[0,3,5])
        np.testing.assert_array_equal(c.rgb_u8[d],[[255,0,0],[255,255,0],[255,0,255]])
        np.testing.assert_allclose(c.points_m[d],[[-.01,-.0025,1],[-.03,.0075,3],[.05,.0125,5]],rtol=0,atol=1e-8)

    def test_display_only_depth_window_keeps_full_cloud_and_original_IDs(self):
        c=self.cloud();before=c.points_m.copy()
        d=select_display(c,2,(2,4));self.assertIsNotNone(d)
        np.testing.assert_array_equal(d,[1,3])
        np.testing.assert_array_equal(c.pixel_id[d],[2,4])
        np.testing.assert_array_equal(c.points_m,before)

    def test_black_is_ambiguous_not_removed_or_fabricated(self):
        frame,rgb=self.fixture();rgb[1,0]=0
        c=build_color_cloud(frame,rgb);self.assertIsNotNone(c)
        self.assertEqual(len(c.points_m),5)
        np.testing.assert_array_equal(c.color_candidate,[True,True,False,True,True])
        np.testing.assert_array_equal(c.rgb_u8[2],[0,0,0])
        self.assertEqual(c.pixel_id[2],3)

    def test_bad_RGB_shape_channels_dtype_and_bad_depth_calibration_rejected(self):
        frame,rgb=self.fixture()
        for bad in [rgb[:1],rgb[:,:,:2],rgb.astype(float),rgb.astype(np.int16)]:
            with self.subTest(shape=bad.shape,dtype=bad.dtype):
                with self.assertRaises(ValueError):build_color_cloud(frame,bad)
        for field,value in [('fx',0),('width',4)]:
            broken=copy.deepcopy(frame);broken.metadata['intrinsics'][field]=value
            with self.assertRaises(Exception):build_color_cloud(broken,rgb)

    def test_input_arrays_unchanged_and_invalid_sample_limits_rejected(self):
        frame,rgb=self.fixture();original=(frame.depth_m.copy(),frame.valid_mask.copy(),rgb.copy(),copy.deepcopy(frame.metadata))
        c=build_color_cloud(frame,rgb);self.assertIsNotNone(c)
        for bad in [0,-1,True,2.5]:
            with self.assertRaises(ValueError):select_display(c,bad)
        for bad in [(4,2),(float('nan'),4),(0,0)]:
            with self.assertRaises(ValueError):select_display(c,2,bad)
        np.testing.assert_array_equal(frame.depth_m,original[0]);np.testing.assert_array_equal(frame.valid_mask,original[1])
        np.testing.assert_array_equal(rgb,original[2]);self.assertEqual(frame.metadata,original[3])

    def test_wheel_zoom_keeps_centers_and_reversed_camera_Y(self):
        limits=((-1,1),(2,-2),(0,4))
        np.testing.assert_allclose(zoom_limits(limits,.5),[[-.5,.5],[1,-1],[1,3]],rtol=0,atol=0)
        with self.assertRaises(ValueError):zoom_limits(limits,0)

if __name__=='__main__':unittest.main()
