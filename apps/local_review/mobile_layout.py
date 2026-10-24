"""Tk-only presentation for the existing ROI editor; selection/export are unchanged."""
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from roi_core import NOTICE


class EmbeddedROIControls:
    def __init__(self, window, editor, host):
        self.window = window
        self.editor = editor
        self.host = host
        self.last_text = None
        self.frame = ttk.LabelFrame(host, text='ROI 선택 · 조작 · 검증 상태', padding=5)
        self.frame.pack(fill='x')
        self.counts = ttk.Label(self.frame, anchor='w', justify='left')
        self.counts.pack(fill='x')
        self.details = ScrolledText(self.frame, height=4, wrap='word', font=('Malgun Gothic', 9),
                                   takefocus=True, relief='flat', background='#f5f5f5')
        self.details.pack(fill='x', pady=(3, 4))
        self.details.configure(state='disabled')
        actions = [
            ('전체 범위', lambda: editor.navigate(-1)),
            ('근거리 범위', lambda: editor.navigate(1)),
            ('표시점 수 변경', editor.cycle_limit),
            ('선택 해제', editor.clear_roi),
            ('저장 ROI + 전체점', editor.save),
            ('지지면 후보 표시', editor.toggle_support),
        ]
        row = ttk.Frame(self.frame)
        row.pack(fill='x')
        self.buttons = {}
        for i, (label, action) in enumerate(actions):
            button = ttk.Button(row, text=label, command=action)
            button.grid(row=0, column=i, sticky='ew', padx=2, pady=2)
            self.buttons[label] = button
        for i in range(6): row.columnconfigure(i, weight=1, uniform='roi')
        # Move all explanations into the readable Tk area, including errors and
        # save paths. The underlying artists remain the editor's state source.
        self.text_artists = list(editor.figure.texts)
        for text in self.text_artists: text.set_visible(False)
        for button in editor.buttons: button.ax.set_visible(False)
        self.cid = window.canvas.mpl_connect('draw_event', self.sync)
        self.sync()

    def sync(self, event=None):
        editor = self.editor
        counts = (f'전체 원본 {len(editor.data.cloud.pixel_id):,}점  |  전체 선택 {int(editor.mask.sum()):,}점\n'
                  f'표시 {len(editor.rows):,}점  |  표시 선택 {int(editor.mask[editor.rows].sum()):,}점 (렌더러 제출점 수)')
        self.counts.configure(text=counts, wraplength=max(200, self.host.winfo_width()-30))
        text = ('왼쪽 정사영: 드래그 생성 · 내부 이동 · 핸들 크기 변경 · Esc 해제 · S 저장\n'
                '오른쪽 3D: 왼쪽 버튼 드래그 회전 · 휠 확대/축소. 도구 모음 이동/확대는 ROI 편집 전 해제.\n'
                'RGB 미사용. 후보 평면의 실제 바닥 여부·중력·거리/형상/부피/중량 정확도는 미검증.\n'
                + NOTICE + '\n표시 선택 수는 가림/화면 픽셀 수가 아닙니다. 추정 평면 거리 ≠ 검증된 높이·두께.'
                + ('\n' + editor.status.get_text() if editor.status.get_text() else ''))
        if text != self.last_text:
            self.details.configure(state='normal')
            self.details.delete('1.0', 'end')
            self.details.insert('1.0', text)
            self.details.configure(state='disabled')
            # A newly saved path/error is visible, with all notices scrollable.
            self.details.see('end' if editor.status.get_text() else '1.0')
            self.last_text = text
        changed = False
        height=max(150,self.window.canvas.get_tk_widget().winfo_height())
        bottom=60/height
        plot_height=max(30,height-110)/height
        for ax, box, title in (
            (editor.depth_ax, [.08,bottom,.36,plot_height], '추정 후보 평면 정사영\n(+u 오른쪽 / +v 위)'),
            (editor.cloud_ax, [.55,bottom,.40,plot_height], '단색 Depth · RGB 미사용\n선택: 자홍색')):
            if any(abs(a-b)>1e-6 for a,b in zip(ax.get_position(original=True).bounds,box)):
                ax.set_position(box);changed = True
            if ax.get_title() != title:
                ax.set_title(title, fontsize=10);changed = True
            ax.tick_params(labelsize=8)
            ax.xaxis.label.set_fontsize(8)
            ax.yaxis.label.set_fontsize(8)
        editor.cloud_ax.zaxis.label.set_fontsize(8)
        if changed: self.window.canvas.draw_idle()

    def close(self):
        self.window.canvas.mpl_disconnect(self.cid)
        self.frame.destroy()
