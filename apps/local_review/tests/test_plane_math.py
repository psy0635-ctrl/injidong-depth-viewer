import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'lib/color'))
import unittest
import numpy as np
from plane_math import normalize_plane,fit_robust,compare_planes,ray_intersections,residual_stats

class PlaneTests(unittest.TestCase):
    # Catches choosing a vertical OLS equation or forgetting metric normal normalization.
    def test_known_tilt_and_distance(self):
        x,y=np.meshgrid(np.linspace(-.12,.12,17),np.linspace(-.1,.1,15))
        p=np.column_stack((x.ravel(),y.ravel(),(.2+.25*x-.1*y).ravel()))
        model=fit_robust(p,threshold_m=.0001,seed=71,trials=100)
        want=np.array([.25,-.1,-1.,.2])/np.sqrt(1.0725)
        np.testing.assert_allclose(model['plane'],want,atol=1e-10)
        self.assertEqual(model['inlier_count'],255)

    # Catches replacing robust consensus with a fit to all points, including contamination.
    def test_seeded_fit_rejects_outliers(self):
        x,y=np.meshgrid(np.linspace(-.1,.1,21),np.linspace(-.1,.1,21))
        good=np.column_stack((x.ravel(),y.ravel(),(.2+.1*x).ravel()))
        rng=np.random.default_rng(27)
        noise=rng.uniform([-.1,-.1,.3],[.1,.1,.5],(100,3))
        model=fit_robust(np.vstack((good,noise)),threshold_m=.0005,seed=71,trials=200)
        np.testing.assert_allclose(model['plane'],np.array([.1,0,-1,.2])/np.sqrt(1.01),atol=1e-10)
        self.assertEqual(model['inlier_count'],441)

    # Catches normalizing n without d, or treating a sign flip as 180 degrees.
    def test_opposite_signs_are_same_geometry(self):
        np.testing.assert_array_equal(normalize_plane([0,0,2,-4]),[0,0,-1,2])
        result=compare_planes([0,0,-1,2],[0,0,3,-6])
        self.assertAlmostEqual(result['normal_angle_deg'],0,places=8)
        self.assertAlmostEqual(result['d_delta_m'],0,places=8)

    # Catches accepting a line/too few/nonfinite points as a unique support plane.
    def test_degenerate_inputs_rejected(self):
        for p in (np.zeros((2,3)),np.zeros((20,3)),np.column_stack((np.arange(10),np.arange(10),np.arange(10))),
                  np.array([[0,0,0],[1,0,0],[0,1,np.nan],[1,1,0],[2,0,0],[0,2,0]]),np.zeros((10,2))):
            with self.subTest(shape=p.shape),self.assertRaises(ValueError):
                fit_robust(p,threshold_m=.001,seed=71,trials=20)
        for p in ([0,0,0,1],[0,0,np.inf,1]):
            with self.assertRaises(ValueError):normalize_plane(p)

    # Catches radians/degrees mistakes and describing d change as a uniform height gap.
    def test_known_angle_and_offset_comparison(self):
        result=compare_planes([0,0,-1,.2],[0,.5,-np.sqrt(3)/2,.203])
        self.assertAlmostEqual(result['normal_angle_deg'],30.,places=10)
        self.assertAlmostEqual(result['d_delta_m'],.003,places=12)
        # With parallel unit normals, the coefficient difference is the actual separation.
        parallel=compare_planes([0,0,-1,.2],[0,0,2,-.410])
        self.assertAlmostEqual(parallel['normal_angle_deg'],0.,places=10)
        self.assertAlmostEqual(parallel['d_delta_m'],.005,places=12)

    # Catches bad signed ray equations or inventing a solution for a parallel ray.
    def test_plane_ray_intersection(self):
        p=ray_intersections([0,0,-1,.2],np.array([[0,0,1],[.1,.2,1]]))
        np.testing.assert_allclose(p,[[0,0,.2],[.02,.04,.2]])
        with self.assertRaises(ValueError):ray_intersections([1,0,0,-1],np.array([[0,0,1]]))

    # Catches reporting signed median as absolute error or RMSE after silently trimming.
    def test_residual_stats_include_all_points(self):
        s=residual_stats(np.array([-.003,0,.004]),.002)
        self.assertAlmostEqual(s['signed_median_m'],0.)
        self.assertAlmostEqual(s['absolute_median_m'],.003)
        self.assertAlmostEqual(s['rmse_m'],.005/np.sqrt(3))
        self.assertEqual(s['inlier_count'],1)

    def test_bad_fit_settings_rejected(self):
        x,y=np.meshgrid(np.arange(3),np.arange(3));p=np.column_stack((x.ravel(),y.ravel(),np.ones(9)))
        for threshold,trials in ((0,10),(-1,10),(np.inf,10),(.001,0)):
            with self.assertRaises(ValueError):fit_robust(p,threshold_m=threshold,seed=71,trials=trials)

if __name__=='__main__':unittest.main()
