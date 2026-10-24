import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'lib/color'))
import copy,sys,unittest
from pathlib import Path
from color_evidence import validate_color_record

class EvidenceTests(unittest.TestCase):
    def fixture(self):
        meta={'frame_id':'one','session_id':'real','depth':{'unit':'m','semantics':'optical_axis_z','height':2,'width':3},
              'intrinsics':{'width':3,'height':2,'fx':100,'fy':200,'cx':1,'cy':.5,'model':'rectified_pinhole','calibration_id':'depth_profile'},
              'capture_time':{'ns':'1000000000','clock_domain':'sensor_clock','origin':'sensor'},'provenance':{'raw_scale_to_m':.001}}
        cal={'depth':{'width':3,'height':2,'fx':100,'fy':200,'ppx':1,'ppy':.5,'distortion':'distortion.brown_conrady','coeffs':[0]*5},
             'color':{'width':3,'height':2,'fx':50,'fy':60},'depth_scale_to_m':.001,
             'depth_to_color':{'rotation':[1,0,0,0,1,0,0,0,1],'translation_m':[.01,0,0]}}
        row={'frame_id':'one','session_id':'real','file':'one/aligned.png','width':3,'height':2,'encoding':'RGB8','image_kind':'aligned_rgb',
             'aligned_to_depth':True,'alignment_method':'pyrealsense2.align(stream.depth)','calibration_id':'depth_profile',
             'pair_status':'verified','pair_evidence':'fixture frameset','time':{'ns':'1000303900','clock_domain':'sensor_clock','origin':'sensor'}}
        return meta,cal,row

    def test_uses_depth_grid_and_same_clock_delta(self):
        m,c,r=self.fixture();v=validate_color_record(m,c,r)
        self.assertEqual(v.get('grid'),'depth')
        self.assertEqual(v.get('delta_ns'),'303900')

    def test_wrong_frame_original_RGB_or_missing_alignment_rejected(self):
        m,c,row=self.fixture()
        for key,value in [('frame_id','other'),('session_id','other'),('image_kind','original_rgb'),('aligned_to_depth',False),
                          ('alignment_method',None),('calibration_id','unknown')]:
            r=copy.deepcopy(row);r[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):validate_color_record(m,c,r)

    def test_cross_clock_or_unverified_pairing_rejected(self):
        m,c,r=self.fixture()
        r['time']['clock_domain']='other_clock'
        with self.assertRaises(ValueError):validate_color_record(m,c,r)
        m,c,r=self.fixture();r['pair_status']='unverified'
        with self.assertRaises(ValueError):validate_color_record(m,c,r)
        m,c,r=self.fixture();r['time']['ns']='2000000000'
        with self.assertRaises(ValueError):validate_color_record(m,c,r)

    def test_calibration_grid_or_undocumented_distortion_rejected(self):
        m,c,r=self.fixture();c['depth']['fx']=50
        with self.assertRaises(ValueError):validate_color_record(m,c,r)
        m,c,r=self.fixture();c['depth']['coeffs'][0]=.01
        with self.assertRaises(ValueError):validate_color_record(m,c,r)

if __name__=='__main__':unittest.main()
