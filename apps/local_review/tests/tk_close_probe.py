"""Real Tk subprocess probe. Gates pause real loader work, never fake a session.

The Tcl interpreter is briefly pumped AFTER Tk destruction to expose orphaned
timers (as in a subsequent Tk test); this is reported separately from mainloop.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import tkinter as tk
import mobile_session
if os.environ.get('MOBILE_VIEWER_SOURCE'):
    spec=importlib.util.spec_from_file_location('mobile_viewer',os.environ['MOBILE_VIEWER_SOURCE'])
    mobile_viewer=importlib.util.module_from_spec(spec)
    sys.modules['mobile_viewer']=mobile_viewer
    spec.loader.exec_module(mobile_viewer)
else:
    import mobile_viewer


def run_startup(archive, cache, drain):
    """Exercise the real main(archive) startup reservation and its WM close path."""
    windows = []
    pending_timers = []
    trace = []
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    base = mobile_viewer.MobileWindow
    class StartupWindow(base):
        def __init__(self,root,*args,**kwargs):
            super().__init__(root,*args,**kwargs)
            windows.append(self)
            root.title('종료 회귀 시험 전용 · startup')
            original_destroy = root.destroy
            def destroy():
                original_destroy()
                for ident in root.tk.splitlist(root.tk.call('after','info')):
                    pending_timers.append(dict(id=str(ident),info=[str(v) for v in root.tk.call('after','info',ident)]))
            root.destroy = destroy
            root.after(0,self.close)
    mobile_viewer.MobileWindow = StartupWindow
    assert mobile_viewer.main(archive,cache,1000) == 0
    window = windows[0]
    if drain:
        window.root.tk.call('after',150,'set','::startup_probe_done','1')
        window.root.tk.call('vwait','::startup_probe_done')
    assert not window.workers, 'ZIP opened despite close before startup callback'
    assert window.closed.is_set()
    assert not (cache.exists() and any(cache.iterdir()))
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    print(json.dumps(dict(case='startup',drain=drain,pid=os.getpid(),assertions_passed=True,
                          orphan_timers=pending_timers,cache_clean=True,zip_preserved=True,trace=trace)))


def run(case, archive, cache, drain=True):
    trace = []
    def record(event, **values):
        trace.append(dict(event=event, thread=threading.current_thread().name,
                          at=round(time.monotonic()-started, 4), **values))
    started = time.monotonic()
    before_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    entered = threading.Event()
    release = threading.Event()
    gate_used = threading.Event()
    loaded_sessions = []
    real_load = mobile_viewer.load_mobile_zip
    real_close = mobile_session.LoadedMobileSession.close
    def session_close(session):
        record('session.close', path=str(session.session_dir), exists=session.session_dir.exists())
        real_close(session)
        record('session.cleaned', exists=session.session_dir.exists())
    mobile_session.LoadedMobileSession.close = session_close

    def controlled_load(filename, cache_root, progress):
        def controlled_progress(message):
            # First progress is emitted after an actual ZIP member was extracted.
            if case == 'checking' and not gate_used.is_set():
                gate_used.set()
                record('loader.paused', message=message,
                       files=[str(p) for p in cache.rglob('*') if p.is_file()])
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test did not release extraction gate')
                record('loader.released', files_exist=any(cache.rglob('input.zip')))
            progress(message)
        session = real_load(filename, cache_root, progress=controlled_progress)
        loaded_sessions.append(session)
        record('loader.validated', frames=len(session.frames), path=str(session.session_dir))
        if case == 'completed_pending':
            entered.set()
            if not release.wait(10):
                raise TimeoutError('test did not release completed gate')
            record('loader.return_after_close', path_exists=session.session_dir.exists())
        return session
    mobile_viewer.load_mobile_zip = controlled_load

    root = tk.Tk()
    root.title('종료 회귀 시험 전용 · '+case)
    record('environment', python=sys.version, tk=root.tk.call('info','patchlevel'))
    callback_errors = []
    original_report = root.report_callback_exception
    def report(exc, value, tb):
        callback_errors.append(''.join(traceback.format_exception(exc, value, tb)))
        original_report(exc, value, tb)
    root.report_callback_exception = report
    window = mobile_viewer.MobileWindow(root, cache, display_limit=1000)
    root.title('종료 회귀 시험 전용 · '+case)
    destroyed = False
    close_started = False
    pending_after_destroy = []
    real_destroy = root.destroy
    def pending():
        return [{'id': str(ident), 'info': [str(v) for v in root.tk.call('after','info',ident)]}
                for ident in root.tk.splitlist(root.tk.call('after','info'))]
    def destroy():
        nonlocal destroyed, pending_after_destroy
        record('root.destroy.before', pending=pending(),
               workers_alive=[t.name for t in window.workers if t.is_alive()],
               queued=[item[0] for item in list(window.events.queue)])
        real_destroy()
        destroyed = True
        pending_after_destroy = pending()
        record('root.destroy.after', pending=pending_after_destroy)
    root.destroy = destroy
    real_accept = window.controller.accept
    def accept(token, session):
        record('controller.accept', closed=window.closed.is_set())
        assert not window.closed.is_set(), 'result applied after close'
        return real_accept(token, session)
    window.controller.accept = accept
    if case == 'idle_pending':
        original_finish = window.finish_close
        def finish_with_pending_redraw():
            if not any(t.is_alive() for t in window.workers):
                # Model an invalidation queued immediately before final destruction.
                # This schedules a REAL TkAgg idle callback; no warning is fabricated.
                window.canvas.draw_idle()
                assert window.canvas._idle_draw_id is not None
                record('canvas.redraw_pending',id=window.canvas._idle_draw_id)
            original_finish()
        window.finish_close=finish_with_pending_redraw
    if case == 'queued_ready':
        class HeldReadyQueue(queue.Queue):
            def put(self, item, *args, **kwargs):
                super().put(item,*args,**kwargs)
                if item[0] == 'ready':
                    record('ready.queued')
                    entered.set()
            def get_nowait(self):
                # Hold only delivery, not ZIP validation or session creation.
                if not window.closed.is_set():
                    with self.mutex:
                        if self.queue and self.queue[0][0] == 'ready':
                            raise queue.Empty
                return super().get_nowait()
        window.events = HeldReadyQueue()

    original_after = tk.Misc.after
    original_cancel = tk.Misc.after_cancel
    def traced_after(widget, ms, func=None, *args):
        ident = original_after(widget, ms, func, *args)
        name = getattr(func, '__qualname__', str(func))
        if func is not drive:
            record('after.schedule', id=ident, ms=ms, callback=name,
                   stack=traceback.format_stack(limit=4))
        return ident
    def traced_cancel(widget, ident):
        record('after.cancel', id=ident)
        return original_cancel(widget, ident)

    def begin_close():
        nonlocal close_started
        close_started = True
        record('close.request', status=window.controller.status,
               worker_alive=any(t.is_alive() for t in window.workers),
               gate_entered=entered.is_set(), pending=pending())
        window.close()
        window.close()  # repeated WM close is harmless
        window.open_path(archive)  # late open must not touch a closing UI
        if case in ('checking', 'completed_pending'):
            assert any(t.is_alive() for t in window.workers)
            assert any(cache.rglob('input.zip')), 'live loader files deleted too soon'
            # Release from GUI callback proves close() did not block on join().
            root.after(25, release.set)

    phase = 'loading'
    def drive():
        nonlocal phase
        if destroyed or close_started:
            return
        if time.monotonic()-started > 18:
            raise TimeoutError('GUI state never reached: '+case+' '+window.controller.status)
        if case in ('empty','idle_pending'):
            begin_close(); return
        if case == 'queued_ready' and entered.is_set():
            assert window.controller.status == 'checking'
            assert any(item[0] == 'ready' for item in list(window.events.queue))
            begin_close(); return
        if case in ('checking','completed_pending') and entered.is_set():
            assert window.controller.status == 'checking'
            assert any(t.is_alive() for t in window.workers)
            begin_close(); return
        if case in ('ready','frame') and window.controller.status == 'ready':
            assert window.frames.size() == 4
            if case == 'frame':
                for index, count in ((0,207104),(3,172196)):
                    window.frames.selection_clear(0,'end')
                    window.frames.selection_set(index)
                    window.select_frame()
                    assert len(window.controller.current.points_m) == count
                record('frame.displayed', frame=window.controller.current.frame.metadata['frame_id'])
            begin_close(); return
        if case == 'recover':
            if phase == 'loading' and window.controller.status == 'ready':
                previous = window.controller.session.session_dir
                bad = cache.parent/'broken.zip'
                bad.write_bytes(b'not a zip')
                window.open_path(bad)
                assert not previous.exists()
                assert window.frames.size() == 0
                phase = 'bad'
            elif phase == 'bad' and window.controller.status == 'failed':
                assert window.controller.current is None and window.frames.size() == 0
                assert len(window.figure.axes) == 0
                record('failed.cleared')
                window.open_path(archive)
                phase = 'reopen'
            elif phase == 'reopen' and window.controller.status == 'ready':
                assert window.frames.size() == 4
                window.frames.selection_set(0)
                window.select_frame()
                assert len(window.controller.current.points_m) == 207104
                record('reopen.ready')
                begin_close(); return
        root.after(5, drive)

    tk.Misc.after = traced_after
    tk.Misc.after_cancel = traced_cancel
    if case not in ('empty','idle_pending'):
        window.open_path(archive)
    root.after(0, drive)
    root.mainloop()
    record('mainloop.return')
    assert destroyed and close_started, 'mainloop exited without controlled close'
    # No widget calls after destroy. Tcl survives Tk and can reveal dangling scripts.
    if drain:
        root.tk.call('after', 150, 'set', '::close_probe_done', '1')
        root.tk.call('vwait', '::close_probe_done')
        record('post_destroy_tcl_drain.complete', pending=pending())
    assert not callback_errors, callback_errors
    assert not any(t.is_alive() for t in window.workers), 'worker survived destroy'
    assert not (cache.exists() and any(cache.iterdir())), 'owned extraction leaked'
    assert all(not s.session_dir.exists() for s in loaded_sessions), 'session.close missing'
    assert window.controller.session is None and window.controller.current is None
    assert before_hash == hashlib.sha256(archive.read_bytes()).hexdigest(), 'original ZIP changed'
    assert len(threading.enumerate()) == 1, 'extra thread remains'
    result = dict(case=case, drain=drain, pid=os.getpid(), assertions_passed=True,
                  orphan_timers=pending_after_destroy, callback_errors=callback_errors,
                  cache_clean=True, zip_preserved=True, trace=trace)
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--no-drain',action='store_true')
    args = parser.parse_args()
    if args.case == 'startup':
        run_startup(args.archive,args.cache,not args.no_drain)
    else:
        run(args.case,args.archive,args.cache,not args.no_drain)
