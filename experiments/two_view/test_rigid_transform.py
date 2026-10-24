import unittest,tempfile,json
from pathlib import Path
import numpy as np
from rigid_transform import *

class TransformTests(unittest.TestCase):
    def test_known_rigid_fit_application_and_inverse(self):
        p=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1],[.3,.4,.2]])
        t=np.eye(4);t[:3,:3]=axis_rotation([1,2,3],.4);t[:3,3]=[.1,-.2,.3]
        original=p.copy();q=apply_transform(p,t);found=weighted_rigid(p,q,np.ones(len(p)))
        np.testing.assert_allclose(found,t,atol=1e-12);np.testing.assert_array_equal(p,original)
        np.testing.assert_allclose(apply_transform(q,inverse_transform(t)),p,atol=1e-12)
        n1=np.array([.1,.3,-.95],dtype=np.float32);n2=np.array([.13,.31,-.94],dtype=np.float32)
        normal_transform=np.eye(4);normal_transform[:3,:3]=align_normals(n1,n2);validate_transform(normal_transform)
    def test_bad_matrices_rejected(self):
        bad=[]
        for kind in ('nonfinite','reflection','scale','lastrow'):
            t=np.eye(4)
            if kind=='nonfinite':t[0,3]=np.nan
            if kind=='reflection':t[0,0]=-1
            if kind=='scale':t[0,0]=2
            if kind=='lastrow':t[3,0]=1
            bad.append(t)
        for t in bad:
            with self.subTest(t=t),self.assertRaises(ValueError):validate_transform(t)
        with self.assertRaises(ValueError):validate_transform(np.eye(3))
    def test_bad_points_and_degenerate_fit_rejected(self):
        for p in (np.array([1,2,3]),np.array([[1,np.inf,3]]),np.array([['a','b','c']])):
            with self.assertRaises(ValueError):apply_transform(p,np.eye(4))
        with self.assertRaises(ValueError):weighted_rigid(np.zeros((3,3)),np.zeros((3,3)),np.ones(3))
    def test_direction_unit_and_json_corruption_rejected(self):
        d={'format':'injidong_local_two_view_exploration','format_version':'1.0.0','schema_version':'1.0.0','direction':'p_target = R @ p_source + t','unit':'m','matrix_source_to_target':np.eye(4).tolist()}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'transform.json';p.write_text(json.dumps(d),encoding='utf-8');load_transform(p)
            for key,value in [('unit','mm'),('direction','reversed'),('schema_version','2')]:
                bad=d.copy();bad[key]=value;p.write_text(json.dumps(bad),encoding='utf-8')
                with self.assertRaises(ValueError):load_transform(p)
            p.write_text('{"unit":"m","unit":"mm"}',encoding='utf-8')
            with self.assertRaises(ValueError):load_transform(p)
    def test_nearest_and_synthetic_icp(self):
        rng=np.random.default_rng(23);p=rng.normal(size=(80,3))*.03
        t=np.eye(4);t[:3,:3]=axis_rotation([0,0,1],.02);t[:3,3]=[.001,-.002,.0005];q=apply_transform(p,t)
        found,_,_=icp({'object':p},{'object':q},np.eye(4),.01)
        np.testing.assert_allclose(found,t,atol=1e-10)
        d,k=nearest(q,q);np.testing.assert_array_equal(k,np.arange(80));np.testing.assert_array_equal(d,np.zeros(80))
        with self.assertRaises(ValueError):nearest(p,np.empty((0,3)))

if __name__=='__main__':unittest.main(verbosity=2)
