"""Mobile mode: background file checks, explicit frame selection, saved Depth only."""
from pathlib import Path
import queue
import threading
from mobile_session import NOTICE, load_contract, load_mobile_zip


class MobileController:
    """Only an accepted current generation can expose frames or a current view."""
    def __init__(self):
        self.generation=0;self.session=None;self.current=None;self.status='empty';self.error=''

    @property
    def frame_ids(self):return self.session.frame_ids if self.session is not None else []

    def clear(self):
        self.current=None
        if self.session is not None:self.session.close()
        self.session=None

    def begin_load(self):
        self.clear();self.generation+=1;self.status='checking';self.error=''
        return self.generation

    def accept(self,token,session):
        if token!=self.generation:
            session.close();return False
        self.clear();self.session=session;self.status='ready';return True

    def fail(self,token,error):
        if token==self.generation:
            self.clear();self.status='failed';self.error=str(error)

    def select(self,index,display_limit=50000):
        self.current=None
        if self.session is None:raise ValueError('검사를 통과한 세션이 없습니다.')
        self.current=self.session.select(index,display_limit)
        return self.current


class MobileWindow:
    def __init__(self,root,cache_root,display_limit=50000,output_root=None):
        import tkinter as tk
        from tkinter import ttk
        import matplotlib
        matplotlib.rcParams['font.family']='Malgun Gothic'
        matplotlib.rcParams['axes.unicode_minus']=False
        load_contract()
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg,NavigationToolbar2Tk
        self.root=root;self.cache_root=Path(cache_root);self.display_limit=display_limit
        self.controller=MobileController();self.events=queue.Queue();self.closed=threading.Event();self.workers=[]
        self._poll_after=None;self._open_after=None
        from paths import ROOT
        self.output_root=Path(output_root or ROOT.parent/'mobile_roi_outputs')
        self.editor=None;self.support_selector=None;self.last_saved=None;self.depth_ax=None;self.roi_controls=None
        root.title('인지동 모바일 ZIP · 저장 Depth 검토');root.geometry('1260x860')
        root.minsize(900,720)
        self.status=tk.StringVar(value='모바일 ZIP을 선택하세요.')
        self.session_text=tk.StringVar(value='세션: 없음')
        self.frame_text=tk.StringVar(value='프레임: 없음')
        top=ttk.Frame(root,padding=8);top.pack(fill='x')
        self.open_button=ttk.Button(top,text='모바일 ZIP 열기',command=self.choose_zip);self.open_button.pack(side='left')
        ttk.Button(top,text='Depth 지지면 후보 지정',command=self.enable_support_selection).pack(side='left',padx=3)
        ttk.Button(top,text='현재 프레임 ROI 재열기',command=self.choose_roi).pack(side='left',padx=3)
        ttk.Label(root,textvariable=self.session_text,padding=(8,0),wraplength=850).pack(fill='x')
        self.progress=ttk.Progressbar(top,mode='indeterminate',length=150);self.progress.pack(side='right')
        ttk.Label(root,textvariable=self.status,wraplength=1200,padding=8).pack(fill='x')
        from server_panel import ServerPanel
        self.server=ServerPanel(self)
        bottom=ttk.Frame(root);bottom.pack(side='bottom',fill='x')
        ttk.Label(bottom,textvariable=self.frame_text,padding=5,wraplength=850).pack(fill='x')
        ttk.Label(bottom,text=NOTICE,padding=5,foreground='#7b263c',wraplength=850).pack(fill='x')
        self.roi_host=ttk.Frame(root);self.roi_host.pack(side='bottom',fill='x',padx=8)
        middle=ttk.Frame(root);middle.pack(fill='both',expand=True)
        left=ttk.Frame(middle,padding=8);left.pack(side='left',fill='y')
        ttk.Label(left,text='프레임 목록 (선택하여 표시)').pack(anchor='w')
        self.frames=tk.Listbox(left,width=25,height=12,exportselection=False)
        self.frames.pack(fill='y',expand=True);self.frames.bind('<<ListboxSelect>>',self.select_frame)
        plot=ttk.Frame(middle);plot.pack(side='left',fill='both',expand=True)
        self.figure=Figure(figsize=(10,6),dpi=100)
        self.canvas=FigureCanvasTkAgg(self.figure,master=plot)
        self.toolbar=NavigationToolbar2Tk(self.canvas,plot,pack_toolbar=False)
        self.toolbar.pack(side='bottom',fill='x');self.canvas.get_tk_widget().pack(fill='both',expand=True)
        self.blank('모바일 ZIP 선택 → 파일 검사 → 프레임 선택')
        root.protocol('WM_DELETE_WINDOW',self.close);self._poll_after=root.after(60,self.poll)

    def blank(self,message):
        self.clear_editor()
        self.figure.clear();self.figure.text(.1,.5,message,fontsize=13)
        self.canvas.draw_idle();self.toolbar.update()

    def choose_zip(self):
        from tkinter import filedialog
        filename=filedialog.askopenfilename(parent=self.root,title='모바일 세션 원본 ZIP 선택',
                                           filetypes=[('세션 ZIP','*.zip')])
        if filename:self.open_path(filename)

    def open_path(self,filename):
        if self.closed.is_set():return
        self.server.cancel(silent=True)
        token=self.controller.begin_load()
        self.frames.delete(0,'end');self.session_text.set('세션: 검사 중')
        self.frame_text.set('프레임: 없음');self.status.set('원본을 보존하며 ZIP을 검사하고 있습니다.')
        self.blank('파일 검사 중…');self.open_button.configure(state='disabled');self.progress.start(15)
        def worker():
            session=None
            try:
                def progress(message):
                    if self.closed.is_set():
                        from safe_zip import MobileInputError
                        raise MobileInputError('CANCELLED','창을 닫아 검사를 중단했습니다.')
                    self.events.put(('progress',token,message))
                session=load_mobile_zip(filename,self.cache_root,progress=progress)
                if self.closed.is_set():session.close()
                else:self.events.put(('ready',token,session))
            except Exception as exc:self.events.put(('failed',token,str(exc)))
        thread=threading.Thread(target=worker,daemon=False)
        self.workers.append(thread);thread.start()

    def poll(self):
        # Also keep one reservation when a caller explicitly polls the queue.
        if self._poll_after is not None:
            self.root.after_cancel(self._poll_after);self._poll_after=None
        if self.closed.is_set():return
        while True:
            try:kind,token,value=self.events.get_nowait()
            except queue.Empty:break
            if self.server.handle(kind,token,value):continue
            if token!=self.controller.generation:
                if kind=='ready':value.close()
                continue
            if kind=='progress':
                if token==self.controller.generation:self.status.set(value)
                continue
            self.progress.stop();self.open_button.configure(state='normal')
            if kind=='ready':
                self.accept_loaded_session(value)
            elif kind=='failed':
                self.controller.fail(token,value);self.frames.delete(0,'end')
                self.session_text.set('세션: 없음');self.frame_text.set('프레임: 없음')
                self.status.set('불러오기 실패 · '+value);self.blank('입력 실패 — 이전 세션을 표시하지 않습니다.')
        self._poll_after=self.root.after(60,self.poll)

    def accept_loaded_session(self,session):
        """GUI-thread commit point, reached by network only after all checks pass."""
        self.clear_editor()
        self.controller.accept(self.controller.generation,session)
        self.frames.delete(0,'end');self.frame_text.set('프레임: 없음')
        self.session_text.set(f'세션: {session.session_id}')
        for fid in session.frame_ids:self.frames.insert('end',fid)
        warning=len(session.report['rgb_format_warnings'])
        self.status.set(f'파일 검사 완료 · Depth {len(session.frames)}프레임. 목록에서 프레임을 선택하세요.'
                        + (f' RGB8/RGBA 불일치 {warning}건은 별도 경고이며 RGB는 사용하지 않습니다.' if warning else ''))
        self.blank('검사 완료 — 왼쪽 목록에서 프레임을 선택하세요.')

    def select_frame(self,event=None):
        if self.closed.is_set():return
        selection=self.frames.curselection()
        if not selection:return
        self.frame_text.set('프레임: 검사 중');self.blank('선택 프레임 준비 중…')
        try:
            view=self.controller.select(int(selection[0]),self.display_limit)
            from viewer_render import draw_view,info_text
            self.figure.clear()
            depth_ax=self.figure.add_axes([.07,.20,.36,.65])
            self.depth_ax=depth_ax
            cloud_ax=self.figure.add_axes([.55,.20,.40,.65],projection='3d')
            draw_view(self.figure,depth_ax,cloud_ax,view)
            self.figure.suptitle(view.frame.metadata['frame_id'])
            self.frame_text.set(info_text(view))
            self.canvas.draw_idle();self.toolbar.update()
        except Exception as exc:
            self.controller.current=None;self.frame_text.set('프레임: 없음')
            self.status.set('프레임 표시 실패 · '+str(exc));self.blank('프레임을 표시할 수 없습니다.')

    def clear_editor(self):
        if self.roi_controls is not None:
            self.roi_controls.close();self.roi_controls=None
        if self.support_selector is not None:
            self.support_selector.disconnect_events();self.support_selector=None
        if self.editor is not None:
            editor=self.editor
            editor.selector.disconnect_events()
            # Retire window-level weak methods before the dynamic ROI class and
            # its button closures become cyclic garbage (Python 3.11 teardown).
            registry=editor.figure.canvas.callbacks
            for callbacks in list(registry.callbacks.values()):
                for cid,proxy in list(callbacks.items()):
                    if getattr(proxy(),'__self__',None) is editor:registry.disconnect(cid)
            for button in editor.buttons:
                button.disconnect_events()
                # Button.disconnect is public; the registry provides owned IDs.
                for cid in list(button._observers.callbacks.get('clicked',{})):button.disconnect(cid)
            self.editor=None
        self.depth_ax=None

    def enable_support_selection(self):
        if self.closed.is_set():return
        if self.controller.current is None:
            self.status.set('먼저 검사된 Depth 프레임을 선택하세요.');return
        # Return to actual Depth pixels; never select candidates in RGB or a prior frame.
        self.select_frame()
        if self.depth_ax is None:return
        from matplotlib.widgets import RectangleSelector
        self.support_selector=RectangleSelector(self.depth_ax,self.support_selected,button=[1],useblit=False,
            interactive=False,minspanx=1,minspany=1,spancoords='data')
        self.status.set('Depth 화면에서 지지면 후보를 드래그하세요. 후보 표면의 바닥 여부·중력·정확도는 미검증입니다. 기존 ROI는 프레임 전환/재지정 시 해제됩니다.')

    def support_selected(self,press,release):
        if self.closed.is_set():return
        if self.toolbar.mode:
            self.status.set('도구 모음의 이동/확대를 해제한 뒤 후보를 지정하세요.');return
        import math
        x0,x1,y0,y1=self.support_selector.extents
        bounds=[math.floor(x0),math.floor(y0),math.ceil(x1),math.ceil(y1)]
        try:
            from mobile_roi import prepare_review
            index=int(self.frames.curselection()[0])
            data=prepare_review(self.controller.session,index,bounds)
            self.mount_editor(data)
        except (ValueError,OSError) as exc:
            self.status.set('지지면 후보 준비 실패 · '+str(exc))

    def mount_editor(self,data,initial_roi=None):
        import time
        from mobile_roi import MobileROI
        from run_review_viewer import create_window
        from paths import ROOT
        index=int(self.frames.curselection()[0]);adapter=MobileROI(self.controller.session,index)
        output=self.output_root.resolve()
        if output.is_relative_to(ROOT) or output.is_relative_to(self.cache_root.resolve()):raise ValueError('ROI output must be outside app and loader cache')
        output.mkdir(parents=True,exist_ok=True)
        run=output/('run_'+str(time.time_ns()));run.mkdir()
        self.clear_editor()
        def save(destination,data,box,rows,figure):
            saved=adapter.save(destination,data,box,rows,figure);self.last_saved=saved;return saved
        editor=create_window(data,run,self.display_limit,initial_roi,save_function=save,
            source_label='MOBILE '+data.frame.metadata['frame_id']+' | 단색 Depth / RGB 미사용',initial_depth_range=(.07,.5))
        # Reuse the existing ROI controls in this Tk canvas; no second app/window.
        self.editor=editor;self.figure=editor.figure;self.canvas.figure=self.figure;self.figure.set_canvas(self.canvas)
        from mobile_layout import EmbeddedROIControls
        self.roi_controls=EmbeddedROIControls(self,editor,self.roi_host)
        self.root.update_idletasks()
        widget=self.canvas.get_tk_widget()
        self.figure.set_size_inches(max(1,widget.winfo_width())/self.figure.dpi,
                                    max(1,widget.winfo_height())/self.figure.dpi,forward=False)
        self.toolbar.update();self.canvas.draw();self.canvas.get_tk_widget().focus_set()
        self.status.set('지지면 후보 추정 기준 정사영 · 중력/공식 바닥 미검증. ROI: 생성·내부 이동·핸들 수정·Esc 해제·S 저장. RGB 미사용.')
        self.frame_text.set('프레임: '+data.frame.metadata['frame_id']+' · 원본 전체 픽셀 ID로 선택 · '+str(len(data.cloud.pixel_id))+'점')

    def choose_roi(self):
        if self.closed.is_set():return
        from tkinter import filedialog
        path=filedialog.askdirectory(parent=self.root,title='현재 모바일 ZIP/프레임의 보조 ROI 폴더 선택')
        if path:self.open_roi_path(path)

    def open_roi_path(self,path):
        if self.closed.is_set():return False
        try:
            if self.controller.current is None:raise ValueError('먼저 ZIP과 저장 당시 Depth 프레임을 선택하세요.')
            from mobile_roi import MobileROI
            index=int(self.frames.curselection()[0])
            data,label=MobileROI(self.controller.session,index).open(path)
            self.mount_editor(data,label['roi_uv_m']);return True
        except (ValueError,OSError) as exc:
            self.status.set('ROI 재열기 거부 · '+str(exc));return False

    def close(self):
        if self.closed.is_set():return
        self.closed.set()
        self.server.cancel(silent=True)
        for name in ('_poll_after','_open_after'):
            after_id=getattr(self,name)
            if after_id is not None:
                self.root.after_cancel(after_id);setattr(self,name,None)
        # ttk owns an internal Tcl timer; stop it while its widget still exists.
        self.progress.stop()
        self.controller.begin_load()
        self.open_button.configure(state='disabled');self.frames.delete(0,'end')
        self.session_text.set('세션: 없음');self.frame_text.set('프레임: 없음')
        self.status.set('검사를 중단하고 임시 파일을 정리하는 중입니다.')
        self.blank('임시 파일 정리 중…');self.root.after(20,self.finish_close)

    def finish_close(self):
        if any(thread.is_alive() for thread in self.workers):
            self.root.after(20,self.finish_close);return
        while True:
            try:kind,token,value=self.events.get_nowait()
            except queue.Empty:break
            if kind in ('ready','net_ready'):value.close()
        # Embedded TkAgg has no FigureManager to cancel its pending idle draw.
        if self.canvas._idle_draw_id is not None:
            self.canvas.get_tk_widget().after_cancel(self.canvas._idle_draw_id)
            self.canvas._idle_draw_id=None
        self.root.destroy()


def main(archive=None,cache_root=None,display_limit=50000):
    import tkinter as tk
    import matplotlib
    matplotlib.use('TkAgg');matplotlib.rcParams['font.family']='Malgun Gothic'
    matplotlib.rcParams['axes.unicode_minus']=False
    from paths import ROOT
    root=tk.Tk();window=MobileWindow(root,cache_root or ROOT.parent/'runtime',display_limit)
    if archive:window._open_after=root.after(100,lambda:window.open_path(archive))
    root.mainloop()
    return 0
