import os
"""Matplotlib callback tests on actual robot cloud; these are NOT OS mouse actions."""
import unittest,tempfile
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib.backend_bases import MouseEvent
from review_data import load_review
from run_review_viewer import create_window
from roi_core import id_hash
@unittest.skipUnless(os.environ.get('INJIDONG_ROBOT_REVIEW_ROOT'),'explicit external robot review bundle required')
class CallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=load_review()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.window=create_window(self.data,Path(self.temp.name));self.window.figure.canvas.draw()
    def tearDown(self):self.window.close();self.temp.cleanup()
    def event(self,name,u,v):
        x,y=self.window.depth_ax.transData.transform((u,v));e=MouseEvent(name,self.window.figure.canvas,x,y,button=1);self.window.figure.canvas.callbacks.process(name,e)
    def drag(self,a,b):
        self.event('button_press_event',*a);self.event('motion_notify_event',*b);self.event('button_release_event',*b)
    def test_initial_selector_does_not_expand_data_view(self):
        self.assertLess(self.window.depth_ax.get_ylim()[1],.5)
    def test_drag_move_resize_clear_and_outside_release(self):
        self.drag((-.04,.02),(.04,.10));self.assertGreater(self.window.mask.sum(),0)
        first=self.window.roi.copy();self.drag((0,.06),(.01,.07));self.assertFalse(np.array_equal(first,self.window.roi))
        b=self.window.roi.copy();self.drag((b[1],b[3]),(b[1]+.01,b[3]+.01));self.assertGreater(self.window.roi[1],b[1])
        self.window.clear_roi();self.assertIsNone(self.window.roi)
        self.drag((.04,.1),(-.04,.02));self.assertGreater(self.window.mask.sum(),0)
        self.window.clear_roi();self.drag((0,.05),(.5,.5));self.assertIsNotNone(self.window.roi)
    def test_view_changes_preserve_selection_angles_and_zoom(self):
        w=self.window;self.drag((-.04,.02),(.04,.10));expected=id_hash(self.data.cloud.pixel_id[w.mask]);w.cloud_ax.view_init(20,40,5);w.cloud_ax.set_xlim(-.02,.02)
        for action in (lambda:w.navigate(-1),lambda:w.navigate(1),w.cycle_limit,w.toggle_support):
            action();self.assertEqual(expected,id_hash(self.data.cloud.pixel_id[w.mask]));self.assertEqual((w.cloud_ax.elev,w.cloud_ax.azim,w.cloud_ax.roll),(20,40,5));np.testing.assert_allclose(w.cloud_ax.get_xlim(),[-.02,.02])
    def test_toolbar_blocks_roi_and_zero_click_keeps_selection(self):
        w=self.window;self.drag((-.04,.02),(.04,.10));old=w.roi.copy()
        from matplotlib.backend_bases import NavigationToolbar2
        toolbar=NavigationToolbar2(w.figure.canvas);toolbar.pan()
        self.drag((0,.04),(.02,.06));self.assertEqual(w.roi,old)
        toolbar.pan();w.figure.canvas.toolbar=None
        self.drag((.12,.18),(.12,.18));self.assertEqual(w.roi,old)
if __name__=='__main__':unittest.main()
