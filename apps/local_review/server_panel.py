"""Small optional server controls; Tk access stays on the GUI thread.

Requests have independent generations. Failed/cancelled work never clears the
currently accepted local/network session or its unsaved ROI.
"""
import os,threading
import pc_http

class ServerPanel:
    def __init__(self,window):
        import tkinter as tk
        from tkinter import ttk
        self.window=window;self.generation=0;self.cancel_event=threading.Event();self.busy=False
        self.records=();self.next_cursor=None;self.page_config=None;self.last_error_code=None
        self.address=tk.StringVar(value='');self.token=tk.StringVar(value='');self.allow_http=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='서버 선택 사항 · 로컬 ZIP은 서버 없이 사용할 수 있습니다.')
        frame=ttk.LabelFrame(window.root,text='PC 세션 목록·원본 ZIP 다운로드',padding=5);frame.pack(fill='x',padx=8)
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Label(row,text='서버 주소').pack(side='left')
        ttk.Entry(row,textvariable=self.address,width=36).pack(side='left',padx=4)
        ttk.Label(row,text='선택적 Bearer (미확정)').pack(side='left')
        ttk.Entry(row,textvariable=self.token,show='●',width=17).pack(side='left',padx=4)
        ttk.Checkbutton(row,text='개발 HTTP 명시 허용',variable=self.allow_http).pack(side='left')
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=2)
        ttk.Button(actions,text='목록 조회',command=self.fetch_page).pack(side='left',padx=3)
        self.next_button=ttk.Button(actions,text='다음 페이지',command=lambda:self.fetch_page(next_page=True),state='disabled');self.next_button.pack(side='left')
        ttk.Button(actions,text='선택 ZIP 검증 후 열기',command=self.download_selected).pack(side='left',padx=3)
        ttk.Button(actions,text='요청 취소',command=self.cancel).pack(side='left')
        table=ttk.Frame(frame);table.pack(fill='x',pady=3)
        columns=('id','size','stored_at','warnings')
        self.sessions=ttk.Treeview(table,columns=columns,show='headings',height=2,selectmode='browse')
        for key,title,width in zip(columns,('session_id · stored만 선택','ZIP bytes','최초 stored_at UTC','서버 경고 (품질 승인 아님)'),(260,120,220,420)):
            self.sessions.heading(key,text=title);self.sessions.column(key,width=width)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.sessions.yview);self.sessions.configure(yscrollcommand=scroll.set)
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.sessions.xview)
        self.sessions.configure(xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom',fill='x')
        scroll.pack(side='right',fill='y');self.sessions.pack(side='left',fill='x',expand=True)
        status=ttk.Label(frame,textvariable=self.status,wraplength=850);status.pack(fill='x')
        frame.bind('<Configure>',lambda event:status.configure(wraplength=max(200,event.width-20)))

    def _config(self):
        try:
            values={}
            for env,key,cast in (('INJIDONG_HTTP_IO_TIMEOUT_S','io_timeout_s',float),('INJIDONG_HTTP_TOTAL_TIMEOUT_S','total_timeout_s',float),
                ('INJIDONG_HTTP_MAX_JSON_BYTES','max_json_bytes',int),('INJIDONG_HTTP_MAX_ARCHIVE_BYTES','max_archive_bytes',int)):
                if env in os.environ:values[key]=cast(os.environ[env])
            return pc_http.ClientConfig(self.address.get(),bearer_token=self.token.get() or None,allow_dev_http=self.allow_http.get(),**values)
        except (ValueError,TypeError):raise pc_http.PCHttpError('CONFIG') from None

    def cancel(self,*,silent=False):
        self.cancel_event.set();self.generation+=1;self.busy=False
        if not silent:
            self.last_error_code='CANCELLED';self.status.set('취소 요청 · 현재 세션/미저장 ROI는 유지합니다. 작업 파일은 worker가 정리합니다.')

    def _start(self,kind,operation):
        if self.window.closed.is_set():return
        self.cancel(silent=True);token=self.generation;cancel=threading.Event();self.cancel_event=cancel
        events=self.window.events;self.busy=True;self.last_error_code=None
        def worker():
            try:
                def progress(message):
                    if cancel.is_set():raise pc_http.PCHttpError('CANCELLED')
                    events.put(('net_progress',token,message))
                value=operation(cancel,progress)
                if cancel.is_set():
                    if kind=='net_ready':value.close()
                    raise pc_http.PCHttpError('CANCELLED')
                events.put((kind,token,value))
            except pc_http.PCHttpError as error:events.put(('net_failed',token,error))
            except Exception:
                # An unexpected error stays distinguishable; never echo credentials/body.
                events.put(('net_failed',token,pc_http.PCHttpError('INTERNAL_ERROR')))
        thread=threading.Thread(target=worker,name='PC session request',daemon=False)
        self.window.workers.append(thread);thread.start()

    def fetch_page(self,*,next_page=False):
        if self.window.closed.is_set():return
        self.cancel(silent=True)
        try:
            config=self._config()
            if next_page and (self.next_cursor is None or config!=self.page_config):raise pc_http.PCHttpError('CONFIG')
            cursor=self.next_cursor if next_page else None
            self.status.set('목록 조회 중 · 완료된 stored 세션만 받습니다. 현재 라벨은 유지합니다.')
            self._start('net_list',lambda cancel,progress:(pc_http.list_sessions(config,cursor=cursor,cancel=cancel),config))
        except pc_http.PCHttpError as exc:self.last_error_code=exc.code;self.status.set(str(exc))

    def download_selected(self):
        if self.window.closed.is_set():return
        self.cancel(silent=True)
        try:
            config=self._config();chosen=self.sessions.selection()
            if config!=self.page_config or len(chosen)!=1:raise pc_http.PCHttpError('CONFIG')
            record=self.records[int(chosen[0][3:])]
            # Invalidate a pending local load WITHOUT clearing an accepted session.
            self.window.controller.generation+=1
            self.window.controller.status='ready' if self.window.controller.session is not None else 'empty'
            self.window.progress.stop();self.window.open_button.configure(state='normal')
            self.status.set('다운로드/검증 중 · 실패·취소 시 현재 ROI 유지, 성공하면 현재 화면/미저장 ROI를 교체합니다.')
            scratch=self.window.cache_root
            self._start('net_ready',lambda cancel,progress:pc_http.download_session(config,record,scratch,cancel=cancel,progress=progress))
        except (pc_http.PCHttpError,IndexError,ValueError) as exc:
            error=exc if isinstance(exc,pc_http.PCHttpError) else pc_http.PCHttpError('CONFIG')
            self.last_error_code=error.code;self.status.set(str(error))

    def handle(self,kind,token,value):
        if not kind.startswith('net_'):return False
        if token!=self.generation or self.window.closed.is_set():
            if kind=='net_ready':value.close()
            return True
        if kind=='net_progress':self.status.set(value);return True
        self.busy=False
        if kind=='net_list':
            page,config=value;self.records=page.items;self.next_cursor=page.next_cursor;self.page_config=config
            self.sessions.delete(*self.sessions.get_children())
            for i,r in enumerate(self.records):
                warning=', '.join(code+(f' ({count})' if count is not None else '') for code,count in r.warnings)
                self.sessions.insert('', 'end',iid='row'+str(i),values=(r.session_id,r.zip_size_bytes,r.stored_at,warning))
            self.next_button.configure(state='normal' if self.next_cursor is not None else 'disabled')
            self.status.set(f'목록 {len(self.records)}개 · 다음 페이지 '+('있음' if self.next_cursor is not None else '없음')+' · 자동 전체 조회 없음')
        elif kind=='net_ready':
            self.window.accept_loaded_session(value)
            self.status.set('외부 목록 기대 ID·크기·SHA 및 기존 ZIP 검사 통과 · 다운로드 사본은 이 세션을 닫을 때 삭제됩니다.')
        elif kind=='net_failed':
            self.last_error_code=value.code;self.status.set(str(value)+' 현재 정상 세션/미저장 ROI는 유지합니다.')
        return True
