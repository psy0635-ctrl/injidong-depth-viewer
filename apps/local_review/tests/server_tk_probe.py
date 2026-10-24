"""Real Tk subprocess and a separate loopback fixture process. Automated events."""
import argparse,hashlib,json,os,queue,subprocess,sys,threading,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import tkinter as tk
from http_fixture import FixtureServer,SAMPLE,SHA
from mobile_viewer import MobileWindow
from mobile_session import digest
from mobile_roi import prepare_review
from roi_core import id_hash

def run(case,work):
    work.mkdir(parents=True,exist_ok=True);before=digest(SAMPLE)
    errors=[];trace=[];result={};pending=[];entered=threading.Event();release=threading.Event();queued=threading.Event()
    with FixtureServer(work/'fixture') as fixture:
        root=tk.Tk();w=MobileWindow(root,work/'cache',1000,output_root=work/'labels');root.title('PC HTTP 자동 Tk 시험 전용 · '+case)
        assert hasattr(w,'server'),'server controls are not connected to the existing MobileWindow'
        import pc_http
        panel=w.server;panel.address.set(fixture.base)
        original_destroy=root.destroy
        def destroy():
            original_destroy();pending.extend(str(x) for x in root.tk.splitlist(root.tk.call('after','info')))
        root.destroy=destroy
        def report(t,e,tb):errors.append(''.join(traceback.format_exception(t,e,tb)));traceback.print_exception(t,e,tb)
        root.report_callback_exception=report
        if case in ('cancel_loading','close_loading'):
            original=pc_http.load_verified_mobile_zip
            def controlled(*args,**kwargs):
                progress=kwargs['progress']
                def gate(message):
                    if not entered.is_set():
                        trace.append({'event':'actual_loader_progress_gated','files_exist':any((work/'cache').rglob('input.zip'))})
                        entered.set()
                        if not release.wait(12):raise TimeoutError('loader gate not released')
                    progress(message)
                return original(*args,**{**kwargs,'progress':gate})
            pc_http.load_verified_mobile_zip=controlled
        if case in ('stale_result','queued_close'):
            class HoldReady(queue.Queue):
                def put(self,item,*args,**kwargs):
                    super().put(item,*args,**kwargs)
                    if item[0]=='net_ready':queued.set()
                def get_nowait(self):
                    with self.mutex:
                        if self.queue and self.queue[0][0]=='net_ready' and not release.is_set():raise queue.Empty
                    return super().get_nowait()
            w.events=HoldReady()
        old_editor=None;old_path=None;old_hash=None;old_registry=None;phase='local';started=time.monotonic();beats=0
        def choose(index):
            w.frames.selection_clear(0,'end');w.frames.selection_set(index);w.select_frame();w.canvas.draw()
        def roi():
            choose(0);data=prepare_review(w.controller.session,0,[380,120,430,190]);w.mount_editor(data)
            q=data.coordinates[w.editor.rows];b=np.quantile(q[:,:2],[.25,.75],axis=0)
            w.editor.selector.extents=[b[0,0],b[1,0],b[0,1],b[1,1]];w.editor.on_select(None,None)
            assert w.editor.mask.any()
        def preserved():
            assert w.editor is old_editor and old_path.exists()
            assert id_hash(w.editor.data.cloud.pixel_id[w.editor.mask])==old_hash
        def select_record():panel.sessions.selection_set('row0')
        def close():
            # Record owned callbacks still present before their teardown.
            if w.editor is not None:
                owned=[]
                for signal,callbacks in w.figure.canvas.callbacks.callbacks.items():
                    for cid,proxy in callbacks.items():
                        method=proxy()
                        if getattr(method,'__self__',None) is w.editor:owned.append({'signal':signal,'cid':cid,'method':method.__name__})
                trace.append({'event':'roi_owned_callbacks_before_close','callbacks':owned})
            t=time.monotonic();w.close();assert time.monotonic()-t<.5
            release.set();fixture.release()
        def drive():
            nonlocal phase,old_editor,old_path,old_hash,old_registry,beats
            beats+=1
            try:
                if time.monotonic()-started>32:raise TimeoutError('unreached phase '+phase+' '+panel.status.get())
                if phase=='local' and w.controller.status=='ready':
                    roi();old_editor=w.editor;old_path=w.controller.session.session_dir
                    old_registry=w.figure.canvas.callbacks
                    old_hash=id_hash(w.editor.data.cloud.pixel_id[w.editor.mask]);panel.fetch_page();phase='list'
                elif phase=='list' and not panel.busy:
                    assert len(panel.records)==1 and panel.next_cursor is not None
                    if case=='workflow':panel.fetch_page(next_page=True);phase='next'
                    else:
                        if case in ('cancel_download','close_download'):fixture.mode('gate_body')
                        select_record();panel.download_selected();phase='download'
                elif phase=='next' and not panel.busy:
                    assert not panel.records and panel.next_cursor is None
                    panel.fetch_page();phase='listed_again'
                elif phase=='listed_again' and not panel.busy:
                    select_record();fixture.mode('body_hash');panel.download_selected();phase='bad_download'
                elif phase=='bad_download' and not panel.busy:
                    assert panel.last_error_code=='HASH_MISMATCH';preserved()
                    fixture.mode('good');panel.download_selected();phase='good_download'
                elif phase=='good_download' and not panel.busy:
                    assert panel.last_error_code is None
                    assert w.controller.session.session_id=='d405_1792497323680' and w.frames.size()==4
                    assert not old_path.exists() and w.editor is None
                    assert not any(getattr(proxy(),'__self__',None) is old_editor for cbs in old_registry.callbacks.values() for proxy in cbs.values()),'retired ROI window callbacks remained'
                    assert w.controller.session.download_path.is_file()
                    assert not Path(w.controller.session.report['archive_path']).exists()
                    for index,count in enumerate((207104,210516,213661,172196)):
                        choose(index);assert len(w.controller.current.points_m)==count
                    roi();w.editor.save();assert w.editor.exit_code==0
                    bundle=w.last_saved;expected=id_hash(w.editor.data.cloud.pixel_id[w.editor.mask])
                    choose(1);assert not w.open_roi_path(bundle)
                    choose(0);assert w.open_roi_path(bundle)
                    assert expected==id_hash(w.editor.data.cloud.pixel_id[w.editor.mask])
                    result.update(bundle=str(bundle),id_sha256=expected,selected_count=int(w.editor.mask.sum()),download_path=str(w.controller.session.download_path))
                    w.figure.savefig(work/'network_label.png')
                    trace.append({'event':'download_verified_4_frames_roi_saved_restored','external_expected_sha256':SHA})
                    close();return
                elif phase=='download':
                    gate=any(x['event']=='gate' and x.get('phase')=='body' for x in fixture.events()) if case in ('cancel_download','close_download') else entered.is_set() if case in ('cancel_loading','close_loading') else queued.is_set()
                    if gate:
                        assert any(t.is_alive() for t in w.workers) or queued.is_set()
                        preserved();trace.append({'event':'controlled_live_boundary','case':case,'beats':beats})
                        if case in ('close_download','close_loading','queued_close'):close();return
                        if case=='stale_result':
                            assert any(item[0]=='net_ready' for item in list(w.events.queue));panel.fetch_page()
                        else:panel.cancel()
                        release.set();fixture.release();phase='cancelled'
                elif phase=='cancelled' and not any(t.is_alive() for t in w.workers) and w.events.empty():
                    preserved();assert not list((work/'cache').glob('http_download_*'))
                    assert not list((work/'cache').glob('verified_zip_*'))
                    trace.append({'event':'old_session_unsaved_roi_preserved_stale_result_cleaned'})
                    close();return
                root.after(15,drive)
            except Exception:
                errors.append(traceback.format_exc());traceback.print_exc();close()
        w.open_path(SAMPLE);root.after(15,drive);root.mainloop()
        root.tk.call('after',160,'set','::drained','1');root.tk.call('vwait','::drained')
        assert not errors,errors
        assert not pending,pending
        assert not any(t.is_alive() for t in w.workers)
        assert not any(t.name=='PC HTTP deadline' and t.is_alive() for t in threading.enumerate())
        assert not any((work/'cache').iterdir())
        if case=='workflow':
            assert not Path(result['download_path']).exists()
            command=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve().parents[1]/'mobile_roi.py'),'--archive',str(SAMPLE),'--bundle',result['bundle'],'--cache',str(work/'reopen_cache')]
            r=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=20)
            (work/'reopen.stdout.json').write_text(r.stdout,encoding='utf-8');(work/'reopen.stderr.txt').write_text(r.stderr,encoding='utf-8');(work/'reopen.exit.txt').write_text(str(r.returncode))
            assert r.returncode==0 and not r.stderr
            assert json.loads(r.stdout)['id_sha256']==result['id_sha256']
        assert digest(SAMPLE)==before
        result.update(pid=os.getpid(),fixture_pid=fixture.info['pid'],case=case,elapsed_s=time.monotonic()-started,cache_clean=True,orphan_timers=pending,trace=trace,assertions_passed=True)
        (work/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'case':case,'pid':os.getpid(),'cache_clean':True,'assertions_passed':True}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();run(a.case,a.work)
