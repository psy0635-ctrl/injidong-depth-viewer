"""Real Tk widgets/canvas callbacks; separate from OS mouse/keyboard verification."""
from pathlib import Path
from contextlib import contextmanager
import json
import os
import tempfile
import time
import traceback
import unittest
from mobile_viewer import MobileWindow
from test_mobile_session import SAMPLE


@unittest.skipUnless(os.environ.get('MOBILE_TEST_ZIP') and os.environ.get('INJIDONG_TEST_GUI')=='1', 'explicit reference ZIP and GUI opt-in required')
class MobileTkTests(unittest.TestCase):
    @contextmanager
    def window_context(self,display_limit=50000):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as tmp:
            root=tk.Tk();window=MobileWindow(root,Path(tmp)/'cache',display_limit)
            root.title('종료 회귀 시험 전용 · 기존 모바일 GUI')
            destroyed=False
            pending_after=[]
            scheduling=[]
            canvas_widget=window.canvas.get_tk_widget()
            original_idle=canvas_widget.after_idle
            def after_idle(func,*args):
                ident=original_idle(func,*args)
                scheduling.append(dict(id=ident,callback=getattr(func,'__qualname__',str(func)),
                                       stack=traceback.format_stack(limit=5)))
                return ident
            canvas_widget.after_idle=after_idle
            original_destroy=root.destroy
            def destroy():
                nonlocal destroyed,pending_after
                pending_before=[dict(id=str(i),info=[str(v) for v in root.tk.call('after','info',i)])
                                for i in root.tk.splitlist(root.tk.call('after','info'))]
                original_destroy();destroyed=True
                pending_after=[dict(id=str(i),info=[str(v) for v in root.tk.call('after','info',i)])
                               for i in root.tk.splitlist(root.tk.call('after','info'))]
                out=os.environ.get('MOBILE_CLOSE_EVIDENCE')
                if out:
                    target=Path(out);target.mkdir(parents=True,exist_ok=True)
                    (target/(self.id()+'.json')).write_text(json.dumps(dict(
                        pending_before=pending_before,pending_after=pending_after,
                        canvas_idle_id=window.canvas._idle_draw_id,scheduling=scheduling),indent=2),encoding='utf-8')
            root.destroy=destroy
            def shutdown():
                if destroyed:return
                window.close()
                deadline=time.monotonic()+20
                while not destroyed and time.monotonic()<deadline:
                    root.update();time.sleep(.005)
                self.assertTrue(destroyed,'close did not finish within 20s')
                self.assertFalse(any(t.is_alive() for t in window.workers))
                self.assertFalse(window.cache_root.exists() and any(window.cache_root.iterdir()))
                self.assertEqual(pending_after,[],'Tk destroyed with orphaned canvas callbacks')
            try:yield root,window,Path(tmp),shutdown
            finally:shutdown()  # finish worker/session lifetimes before TemporaryDirectory exits

    def test_stale_failure_cannot_clear_newer_session_widgets(self):
        with self.window_context(100) as (root,window,tmp,shutdown):
            old=window.controller.begin_load();new=window.controller.begin_load()
            from mobile_session import load_mobile_zip
            session=load_mobile_zip(SAMPLE,Path(tmp)/'cache')
            window.events.put(('ready',new,session));window.poll()
            current_status=window.status.get()
            window.events.put(('failed',old,'late old failure'));window.poll()
            self.assertEqual(window.frames.size(),4)
            self.assertEqual(window.status.get(),current_status)
            self.assertEqual(window.controller.status,'ready')

    def test_close_during_load_finishes_owned_temp_cleanup(self):
        with self.window_context() as (root,window,tmp,shutdown):
            # Quick-close only; test_mobile_shutdown controls real in-flight work.
            cache=tmp/'cache';window.open_path(SAMPLE);shutdown()
            # Cleanup must finish before Tk/process shutdown, not eventually at interpreter exit.
            self.assertFalse(cache.exists() and any(cache.iterdir()),'closing leaked owned ZIP/session files')

    def test_open_switch_fail_clear_and_recover_in_real_tk(self):
        with self.window_context(1000) as (root,window,tmp,shutdown):
            def wait():
                until=time.monotonic()+20
                while window.controller.status=='checking' and time.monotonic()<until:
                    root.update();time.sleep(.02)
                root.update()
                self.assertNotEqual(window.controller.status,'checking','background validation stalled')
            window.open_path(SAMPLE);wait()
            self.assertEqual(window.controller.status,'ready')
            self.assertEqual(window.frames.size(),4)
            for index,expected in ((0,207104),(3,172196)):
                window.frames.selection_clear(0,'end');window.frames.selection_set(index)
                window.frames.event_generate('<<ListboxSelect>>');root.update()
                self.assertEqual(len(window.controller.current.points_m),expected)
                self.assertEqual(len(window.controller.current.display_points_m),1000)
                self.assertIn(window.controller.frame_ids[index],window.frame_text.get())
                self.assertEqual(len(window.figure.axes),3) # Depth, 3D, one colorbar; no old frame remains.
            previous=window.controller.session
            broken=Path(tmp)/'broken.zip';broken.write_bytes(b'not a ZIP')
            window.open_path(broken)
            self.assertEqual(window.frames.size(),0);self.assertIsNone(window.controller.current)
            self.assertFalse(previous.session_dir.exists())
            wait();self.assertEqual(window.controller.status,'failed')
            self.assertEqual(len(window.figure.axes),0);self.assertEqual(window.frames.size(),0)
            self.assertIn('실패',window.status.get())
            window.open_path(SAMPLE);wait();self.assertEqual(window.controller.status,'ready')
            self.assertEqual(window.frames.size(),4)
            self.assertIsNone(window.controller.current)


if __name__=='__main__':unittest.main()
