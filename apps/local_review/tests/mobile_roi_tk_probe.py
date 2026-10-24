"""Separate real Tk process; Matplotlib events are automated, not OS mouse input."""
import argparse,hashlib,json,os,sys,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import tkinter as tk
from mobile_viewer import MobileWindow
from mobile_session import digest
from roi_core import id_hash,strict_read

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--bundle',type=Path)
    a=p.parse_args();a.root.mkdir(parents=True,exist_ok=True)
    original=digest(a.archive);errors=[];trace=[];result={};started=time.monotonic()
    root=tk.Tk();w=MobileWindow(root,a.root/'cache',1000,output_root=a.root/'labels')
    root.title('모바일 ROI 자동 시험 전용')
    def report(t,e,tb):errors.append(''.join(traceback.format_exception(t,e,tb)));traceback.print_exception(t,e,tb)
    root.report_callback_exception=report
    pending=[];destroy=root.destroy
    def final_destroy():
        destroy();pending.extend(str(i) for i in root.tk.splitlist(root.tk.call('after','info')))
    root.destroy=final_destroy
    phase='initial'
    def choose(index):
        w.frames.selection_clear(0,'end');w.frames.selection_set(index);w.select_frame();w.canvas.draw()
    def source_fingerprints():
        return [{'metadata':hashlib.sha256(json.dumps(f.metadata,sort_keys=True,allow_nan=False).encode()).hexdigest(),
            'depth_m':hashlib.sha256(f.depth_m.tobytes()).hexdigest(),'valid_mask':hashlib.sha256(f.valid_mask.tobytes()).hexdigest()} for f in w.controller.session.frames]
    def mouse(name,ax,point):
        from matplotlib.backend_bases import MouseEvent
        x,y=ax.transData.transform(point);e=MouseEvent(name,w.canvas,x,y,button=1)
        w.canvas.callbacks.process(name,e)
    def drag(ax,start,end):
        mouse('button_press_event',ax,start);mouse('motion_notify_event',ax,end);mouse('button_release_event',ax,end)
    def perform():
        nonlocal phase
        try:
            if time.monotonic()-started>35:raise TimeoutError('state did not complete: '+phase)
            if w.controller.status=='ready' and phase in ('initial','recovered'):
                assert w.frames.size()==4
                fingerprints=source_fingerprints()
                if a.bundle:
                    label=strict_read(a.bundle/'roi.json');index=w.controller.frame_ids.index(label['frame_id']);choose(index)
                    assert w.open_roi_path(a.bundle)
                    e=w.editor
                    np.testing.assert_array_equal(e.data.cloud.pixel_id[e.mask],label['selected_pixel_id'])
                    assert e.data.basis==label['basis']
                    result.update(bundle=str(a.bundle),selected_pixel_id=label['selected_pixel_id'],id_sha256=label['id_sha256'],basis=e.data.basis)
                    trace.append('restored exact IDs/order/hash/basis in another Tk process');w.close();return
                for index,count in enumerate((207104,210516,213661,172196)):
                    choose(index);assert len(w.controller.current.points_m)==count
                choose(0)
                assert w.controller.current.frame.metadata['support_plane'] is None
                w.enable_support_selection();assert w.support_selector is not None
                drag(w.depth_ax,(530,400),(610,450));assert w.editor is None
                assert '실패' in w.status.get()
                drag(w.depth_ax,(380,120),(430,190))
                assert w.editor is not None,w.status.get()
                e=w.editor;q=e.data.coordinates
                # Zoom to central data before interaction, without excluding full source rows.
                bounds=np.quantile(q[e.rows,:2],[.05,.95],axis=0)
                e.depth_ax.set_xlim(*bounds[:,0]);e.depth_ax.set_ylim(*bounds[:,1]);w.canvas.draw()
                mid=bounds.mean(axis=0);span=(bounds[1]-bounds[0])*.18
                drag(e.depth_ax,mid-span,mid+span);assert e.roi is not None and e.mask.sum()>0
                before=e.roi.copy();delta=span*.12
                drag(e.depth_ax,mid,mid+delta);assert e.roi!=before
                before=e.roi.copy();drag(e.depth_ax,(before[1],before[3]),(before[1]+delta[0],before[3]+delta[1]));assert e.roi[1]>before[1]
                ids=e.data.cloud.pixel_id[e.mask].copy();assert len(ids)>len(e.rows[e.mask[e.rows]])
                expected=id_hash(ids);e.cloud_ax.view_init(20,40,5)
                from types import SimpleNamespace
                e.scroll(SimpleNamespace(inaxes=e.cloud_ax,step=1))
                for action in (e.cycle_limit,e.toggle_support,lambda:e.navigate(-1),lambda:e.navigate(1)):
                    action();assert id_hash(e.data.cloud.pixel_id[e.mask])==expected
                    assert (e.cloud_ax.elev,e.cloud_ax.azim,e.cloud_ax.roll)==(20,40,5)
                saved_box=e.roi.copy();e.clear_roi();assert not e.mask.any()
                # Recreate through the real selector after clear (including visibility).
                w.canvas.draw()
                drag(e.depth_ax,(saved_box[1],saved_box[3]),(saved_box[0],saved_box[2]))
                assert e.roi is not None and e.mask.sum()>0 and e.selector.get_visible()
                ids=e.data.cloud.pixel_id[e.mask].copy();expected=id_hash(ids)
                e.save();assert e.exit_code==0
                bundle=w.last_saved;label=strict_read(bundle/'roi.json')
                np.testing.assert_array_equal(label['selected_pixel_id'],ids)
                result.update(bundle=str(bundle),selected_pixel_id=ids.tolist(),id_sha256=expected,basis=e.data.basis)
                assert fingerprints==source_fingerprints()
                result['input_fingerprints_before_after_equal']=True
                result['input_fingerprints']=fingerprints
                w.figure.savefig(a.root/'mobile_roi.png')
                choose(1);assert w.editor is None
                assert not w.open_roi_path(bundle);assert w.editor is None
                choose(0);assert w.open_roi_path(bundle)
                assert id_hash(w.editor.data.cloud.pixel_id[w.editor.mask])==expected
                trace.append('4 frames; Depth candidate fit; ROI create/move/resize/clear; rotation/zoom/display; save; wrong frame rejected; restore')
                old=w.controller.session.session_dir
                bad=a.root/'broken.zip';bad.write_bytes(b'bad ZIP')
                w.open_path(bad);assert w.editor is None and not old.exists();phase='bad'
            elif phase=='bad' and w.controller.status=='failed':
                assert w.editor is None and w.frames.size()==0
                w.open_path(a.archive);phase='recovering'
            elif phase=='recovering' and w.controller.status=='ready':
                choose(0);assert w.open_roi_path(Path(result['bundle']))
                trace.append('failed ZIP then reopen and restore; close with ROI idle draw pending')
                w.canvas.draw_idle();w.close();return
            root.after(30,perform)
        except Exception as exc:
            errors.append(traceback.format_exc());traceback.print_exc();w.close()
    w.open_path(a.archive);root.after(30,perform);root.mainloop()
    # Detect orphan Tcl timers after destruction, not just a successful mainloop return.
    root.tk.call('after',160,'set','::probe_done','1');root.tk.call('vwait','::probe_done')
    assert not errors,errors
    assert not pending,pending
    assert not any(t.is_alive() for t in w.workers)
    assert not any((a.root/'cache').iterdir())
    assert original==digest(a.archive)
    result.update(pid=os.getpid(),trace=trace,cache_clean=True,orphan_timers=pending,elapsed_s=time.monotonic()-started)
    (a.root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pid':os.getpid(),'result':str(a.root/'result.json'),'id_sha256':result['id_sha256'],'cache_clean':True}))
    return 0
if __name__=='__main__':raise SystemExit(main())
