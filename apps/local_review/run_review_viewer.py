"""Robot frame_001409: full-cloud rectangle ROI in saved fitted-support u/v."""
import sys,os,time,json,hashlib,argparse,traceback
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
import numpy as np
from review_data import load_review,select_display,zoom_limits,write,read,sha,load_contract,CODE,SESSION
from projection import painter_rows
from roi_core import NOTICE,normalize_roi,select_mask,id_hash,save_bundle,load_bundle

def create_window(data,run,max_points=50000,initial_roi=None,*,save_function=None,source_label='ROBOT frame_001409',initial_depth_range=(.07,.5)):
    import matplotlib
    matplotlib.rcParams['font.family']='Malgun Gothic'
    matplotlib.rcParams['axes.unicode_minus']=False
    from matplotlib.widgets import Button,RectangleSelector
    load_contract();sys.path.insert(0,str(CODE/'src'))
    from viewer import ViewerWindow
    from viewer_data import FrameView
    class SafeSelector(RectangleSelector):
        def _clean_event(self,event):
            if event.xdata is None and event.x is not None and event.y is not None:
                import copy
                event=copy.copy(event)
                event.xdata,event.ydata=self.ax.transData.inverted().transform((event.x,event.y))
            return super()._clean_event(event)
        def ignore(self,event):
            toolbar=getattr(self.ax.figure.canvas,'toolbar',None)
            if toolbar and toolbar.mode:return True
            return super().ignore(event)
    class Model:
        def __init__(self):
            self.current=FrameView(data.frame,data.cloud.points_m,data.cloud.points_m[:1])
            self.session=SESSION;self.index=0;self.frame_ids=[data.frame.metadata['frame_id']]
    class ROIWindow(ViewerWindow):
        def __init__(self):
            self.data=data;self.save_function=save_function
            self.roi=normalize_roi(initial_roi);self.limit=max_points;self.depth_range=initial_depth_range;self.overlay=False
            self.selector=None;self.drawn=False;self.current_run=run;self.sequence=0
            self.mask=select_mask(data.coordinates,self.roi);self.original_hash=self.array_hashes()
            super().__init__(Model(),run/'exports')
            for b in self.buttons:b.ax.remove()
            self.buttons=[]
            actions=[('전체 범위',.045,.10,lambda e:self.navigate(-1)),('근거리 범위',.155,.11,lambda e:self.navigate(1)),('표시점 수 변경',.275,.14,self.cycle_limit),('선택 해제',.425,.11,self.clear_roi),('저장 ROI + 전체점',.545,.20,lambda e:self.save()),('지지면 후보 표시',.755,.20,self.toggle_support)]
            for label,left,width,action in actions:
                ax=self.figure.add_axes([left,.052,width,.045]);b=Button(ax,label);b.on_clicked(action);self.buttons.append(b)
            self.figure.suptitle(source_label+' | 추정 지지면 후보 u/v 사각형 ROI 검토',fontsize=13)
            self.figure.text(.055,.28,'왼쪽 드래그: 생성 | 내부: 이동 | 핸들: 크기 수정 | Esc: 해제 | 오른쪽: 회전 / 휠 확대',fontsize=8.5)
            self.figure.text(.055,.135,NOTICE,fontsize=9,color='#7b263c')
            self.status.set_position((.055,.105));self.status.set_fontsize(8)
            self.figure.canvas.mpl_connect('scroll_event',self.scroll)
            self.figure.canvas.mpl_connect('button_release_event',self.mouse_release)
            self.record('initial');self.capture('initial')
        def array_hashes(self):
            return {k:hashlib.sha256(getattr(data.cloud,k).tobytes()).hexdigest() for k in ('points_m','pixel_id','rgb_u8','pixel_vu')}
        def record(self,event,extra=None):
            if self.array_hashes()!=self.original_hash:raise RuntimeError('original XYZ/RGB/pixel correspondence changed')
            item={'event':event,'pid':os.getpid(),'time_ns':str(time.time_ns()),'roi_uv_m':self.roi,'full_points':len(data.cloud.pixel_id),'selected_full':int(self.mask.sum()),'selected_display':int(self.mask[self.rows].sum()),'selected_ids_sha256':id_hash(data.cloud.pixel_id[self.mask]),'display_limit':self.limit,'display_count':len(self.rows),'depth_range':self.depth_range,'angles':[float(self.cloud_ax.elev),float(self.cloud_ax.azim),float(self.cloud_ax.roll)],'limits_3d':[list(self.cloud_ax.get_xlim()),list(self.cloud_ax.get_ylim()),list(self.cloud_ax.get_zlim())],'source_arrays_sha256':self.original_hash}
            if extra:item.update(extra)
            with (run/'gui_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n')
        def capture(self,name):
            with (run/(name+'_'+str(time.time_ns())+'.png')).open('xb') as f:self.figure.savefig(f,format='png')
        def draw(self):
            view=None
            if self.drawn:view=([self.cloud_ax.get_xlim(),self.cloud_ax.get_ylim(),self.cloud_ax.get_zlim()],(self.cloud_ax.elev,self.cloud_ax.azim,self.cloud_ax.roll),[self.depth_ax.get_xlim(),self.depth_ax.get_ylim()])
            if self.selector is not None:self.selector.disconnect_events()
            self.depth_ax.clear();self.cloud_ax.clear()
            self.highlight=None
            self.depth_ax.set_position([.075,.34,.36,.54]);self.cloud_ax.set_position([.52,.32,.44,.58])
            self.rows=select_display(data.cloud,self.limit,self.depth_range);self.model.current.display_points_m=data.cloud.points_m[self.rows]
            rows=self.rows;colored=data.cloud.color_candidate[rows];p=data.cloud.points_m
            self.cloud_ax.scatter(*p[rows[colored]].T,c=data.cloud.rgb_u8[rows[colored]]/255.,s=3,depthshade=False)
            self.cloud_ax.scatter(*p[rows[~colored]].T,c='#929292',s=4,marker='x',depthshade=False)
            self.cloud_ax.set(xlabel='camera X (m)',ylabel='camera Y (m)',zlabel='camera Z (m)',title=('단색 Depth 점군 / RGB 사용 안 함' if data.evidence.get('rgb_used') is False else '원본 RGB 후보')+' / 선택: 자홍색')
            self.cloud_ax.set_box_aspect((1,1,1))
            order=painter_rows(data.coordinates,data.cloud.pixel_id,rows);q=data.coordinates[order]
            colors=data.cloud.rgb_u8[order]/255.;colors[~data.cloud.color_candidate[order]]=[.57,.57,.57]
            self.depth_ax.scatter(q[:,0],q[:,1],c=colors,s=3,linewidths=0)
            if self.overlay:
                r=data.support_full_rows[::max(1,len(data.support_full_rows)//1000)];q=data.coordinates[r]
                self.depth_ax.scatter(q[:,0],q[:,1],s=9,facecolors='none',edgecolors='cyan',linewidths=.5)
            self.depth_ax.set(xlabel='plane u (m)',ylabel='plane v (m)',title='추정 지지면 정사영 (+u 오른쪽 / +v 위)')
            self.depth_ax.set_aspect('equal',adjustable='box');self.depth_ax.grid(alpha=.15)
            if view:
                lim,angles,uv=view;self.cloud_ax.view_init(*angles)
                for setter,b in zip((self.cloud_ax.set_xlim,self.cloud_ax.set_ylim,self.cloud_ax.set_zlim),lim):setter(*b)
                # A display range change must be visible in 2D; sampling-only redraw keeps zoom.
                if not getattr(self,'reset_plane_limits',False):self.depth_ax.set_xlim(*uv[0]);self.depth_ax.set_ylim(*uv[1])
            self.reset_plane_limits=False
            uv_limits=(self.depth_ax.get_xlim(),self.depth_ax.get_ylim())
            self.selector=SafeSelector(self.depth_ax,self.on_select,useblit=False,button=[1],minspanx=0,minspany=0,spancoords='data',interactive=True,drag_from_anywhere=True,ignore_event_outside=True,props={'facecolor':'magenta','edgecolor':'magenta','alpha':.12,'linewidth':1.5},handle_props={'markeredgecolor':'magenta','markerfacecolor':'white','markersize':6})
            self.depth_ax.set_xlim(*uv_limits[0]);self.depth_ax.set_ylim(*uv_limits[1])
            if self.roi is not None:self.selector.extents=self.roi;self.selector.set_visible(True)
            self.drawn=True;self.update_selection()
        def update_selection(self):
            self.mask=select_mask(data.coordinates,self.roi)
            if self.highlight is not None:self.highlight.remove()
            selected=self.rows[self.mask[self.rows]];p=data.cloud.points_m[selected]
            self.highlight=self.cloud_ax.scatter(*p.T,facecolors='none',edgecolors='magenta',s=12,linewidths=.6,depthshade=False)
            state='해제' if self.roi is None else 'ROI 존재'
            self.info.set_position((.055,.215));self.info.set_fontsize(9)
            self.info.set_text(f'전체 원본 {len(data.cloud.pixel_id):,}점 | 전체 선택 {int(self.mask.sum()):,}점 | 표시 선택 {len(selected):,} / 표시 {len(self.rows):,}점 | {state}\n표시 선택 수는 렌더러 제출점 수입니다(가림/화면 픽셀 수 아님).\n추정 평면 거리 ≠ 검증된 높이·두께. 중력 기준·물리 정확도·모바일 정렬 미검증.')
            self.figure.canvas.draw_idle()
        def on_select(self,press,release):
            try:
                proposed=normalize_roi(self.selector.extents)
                self.roi=proposed;self.update_selection();self.record('roi_edited')
            except ValueError as e:
                # A zero-area click keeps the previous committed selection and restores its shape.
                if self.roi is None:self.selector.set_visible(False)
                else:self.selector.extents=self.roi;self.selector.set_visible(True)
                self.status.set_text(str(e));self.record('invalid_roi_rejected');self.figure.canvas.draw_idle()
        def clear_roi(self,event=None):
            self.roi=None;self.selector.clear();self.update_selection();self.record('roi_cleared')
        def navigate(self,delta):
            self.depth_range=None if delta<0 else (.07,.5);self.reset_plane_limits=True;self.draw();self.record('range_changed')
        def cycle_limit(self,event=None):
            choices=[50000,10000,1000,len(data.cloud.pixel_id)];self.limit=choices[(choices.index(self.limit)+1)%len(choices)] if self.limit in choices else 50000
            self.draw();self.record('sample_changed')
        def toggle_support(self,event=None):
            self.overlay=not self.overlay;self.draw();self.record('support_overlay_changed')
        def scroll(self,event):
            if event.inaxes is self.cloud_ax:
                lim=zoom_limits([self.cloud_ax.get_xlim(),self.cloud_ax.get_ylim(),self.cloud_ax.get_zlim()],.8**float(event.step))
                for setter,b in zip((self.cloud_ax.set_xlim,self.cloud_ax.set_ylim,self.cloud_ax.set_zlim),lim):setter(*b)
            elif event.inaxes is self.depth_ax:
                lim=np.array([self.depth_ax.get_xlim(),self.depth_ax.get_ylim()]);mid=lim.mean(axis=1,keepdims=True);lim=mid+(lim-mid)*(.8**float(event.step));self.depth_ax.set_xlim(*lim[0]);self.depth_ax.set_ylim(*lim[1])
            else:return
            self.figure.canvas.draw_idle();self.record('wheel_zoom',{'panel':'3D' if event.inaxes is self.cloud_ax else '2D'})
        def mouse_release(self,event):
            if event.inaxes is self.cloud_ax:self.record('3d_mouse_release')
        def key(self,event):
            if event.key=='escape':self.clear_roi()
            elif event.key=='d':self.cycle_limit()
            else:super().key(event)
        def save(self):
            try:
                destination=self.output/('roi_'+str(time.time_ns()))
                bundle=(save_bundle(destination,data,self.roi,self.rows,self.figure) if self.save_function is None else self.save_function(destination,data,self.roi,self.rows,self.figure))
                self.status.set_text('저장: '+str(bundle));self.status.set_color('darkgreen');self.record('saved',{'bundle':str(bundle)});self.capture('saved');print('SAVED '+str(bundle),flush=True);self.figure.canvas.draw_idle()
            except Exception as e:self.report_error(e);traceback.print_exc()
        def show(self):
            import tkinter as tk
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg,NavigationToolbar2Tk
            class Toolbar(NavigationToolbar2Tk):
                toolitems=tuple(t for t in NavigationToolbar2Tk.toolitems if t[0]!='Save')
            root=tk.Tk();root.title('인지동 ROBOT 사각형 ROI 검토');canvas=FigureCanvasTkAgg(self.figure,master=root)
            bar=Toolbar(canvas,root,pack_toolbar=False);bar.pack(side=tk.BOTTOM,fill=tk.X);canvas.get_tk_widget().pack(side=tk.TOP,fill=tk.BOTH,expand=True)
            canvas.get_tk_widget().focus_set();canvas.draw();root.protocol('WM_DELETE_WINDOW',root.destroy);root.mainloop();self.close();return self.exit_code
    return ROIWindow()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--open-review',type=Path);p.add_argument('--verify-only',action='store_true');p.add_argument('--max-display-points',type=int,default=50000);p.add_argument('--output-dir',type=Path,default=ROOT.parent/'roi_review_outputs')
    p.add_argument('--mobile',action='store_true',help='모바일 ZIP 검사·Depth 단일 점군 모드')
    p.add_argument('--mobile-zip',type=Path,help='모바일 모드에서 처음 열 ZIP (생략 시 선택창 버튼)')
    args=p.parse_args()
    if args.max_display_points<1:p.error('positive display limit required')
    if args.mobile or args.mobile_zip:
        if args.open_review or args.verify_only:p.error('mobile mode cannot open a robot ROI bundle')
        from mobile_viewer import main as mobile_main
        return mobile_main(args.mobile_zip,display_limit=args.max_display_points)
    output=args.output_dir if args.output_dir.is_absolute() else ROOT/args.output_dir
    output=output.resolve()
    from paths import INPUT_ROOT
    for protected in (ROOT, *((INPUT_ROOT,) if INPUT_ROOT else ())):
        if output.is_relative_to(protected):p.error('output must be outside protected package data/code')
    output.mkdir(parents=True,exist_ok=True)
    run=output/('run_'+str(time.time_ns()));run.mkdir();os.environ['MPLCONFIGDIR']=str(run/'matplotlib_config')
    if args.open_review and not args.open_review.is_absolute():args.open_review=ROOT/args.open_review
    import matplotlib
    matplotlib.use('Agg' if args.verify_only else 'TkAgg')
    try:
        if args.open_review:data,label=load_bundle(args.open_review);initial=label['roi_uv_m']
        else:data=load_review();initial=None
    except (OSError,ValueError) as e:
        print('입력 검증 실패: '+str(e)+'; 명시한 외부 입력과 파일 무결성을 확인하세요.',file=sys.stderr)
        return 1
    write(run/'basis.json',data.basis);write(run/'input_evidence.json',data.evidence)
    result={'pid':os.getpid(),'full_points':len(data.cloud.pixel_id),'session_id':data.frame.metadata['session_id'],'frame_id':data.frame.metadata['frame_id'],'selected_count':int(select_mask(data.coordinates,initial).sum()),'selected_ids_sha256':id_hash(data.cloud.pixel_id[select_mask(data.coordinates,initial)]),'restored':bool(args.open_review),'saved_basis_reused':bool(args.open_review),'run':str(run)}
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if args.verify_only:
        with (run/'restored_selected_pixel_id.npy').open('xb') as f:np.save(f,data.cloud.pixel_id[select_mask(data.coordinates,initial)],allow_pickle=False)
        write(run/'verification.json',result);return 0
    window=create_window(data,run,args.max_display_points,initial);exit_code=window.show();write(run/'execution_finished.json',{**result,'exit_code':exit_code,'final_selected_count':int(window.mask.sum()),'final_ids_sha256':id_hash(data.cloud.pixel_id[window.mask])});return exit_code
if __name__=='__main__':raise SystemExit(main())
