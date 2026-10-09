"""ADE-95: 저장 Depth·카메라 좌표 Point Cloud 독립 PC 뷰어."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

from contract import ROOT, ContractError
from viewer_data import ViewerSession, export_frame
from viewer_render import draw_view, info_text, make_figure


class ViewerWindow:
    def __init__(self, model, output):
        from matplotlib.widgets import Button
        self.model, self.output = model, Path(output).resolve()
        self.figure, self.depth_ax, self.cloud_ax = make_figure()
        self.figure.suptitle('ADE-95 Stored Depth / Camera Point Cloud', fontsize=15)
        self.info = self.figure.text(.07,.15,'',fontsize=10, va='bottom')
        self.status = self.figure.text(.07,.10,'',fontsize=9, va='bottom')
        self.bar, self.depth_image = None, None
        self.exit_code = 0
        self.buttons = []
        for name, left, callback in [('Previous',.07,lambda e:self.navigate(-1)),
                                     ('Next',.21,lambda e:self.navigate(1)),
                                     ('Save PNG + full NPZ',.37,lambda e:self.save())]:
            ax = self.figure.add_axes([left,.025,.13 if left<.3 else .25,.05])
            button = Button(ax,name)
            button.on_clicked(callback)
            self.buttons.append(button)
        self.figure.canvas.mpl_connect('key_press_event', self.key)
        self.draw()

    def clear(self):
        if self.bar is not None:
            self.bar.remove()
            self.bar = None
        # colorbar.remove restores parent position; set explicit layout on every frame.
        self.depth_ax.set_position([.07,.31,.34,.58])
        self.depth_ax.clear()
        self.cloud_ax.clear()
        self.depth_image = None

    def draw(self):
        self.clear()
        if self.model.current is not None:
            self.depth_image, self.bar = draw_view(self.figure, self.depth_ax, self.cloud_ax, self.model.current)
            self.info.set_text(f'{self.model.index+1} / {len(self.model.frame_ids)}   '+info_text(self.model.current))
        self.figure.canvas.draw_idle()

    def report_error(self, error, clear=False):
        self.exit_code = 1
        message = f'{type(error).__name__}: {error}'
        if clear:
            self.clear()
            self.info.set_text(f'Frame {self.model.index+1} FAILED - no current result\n{message}')
        self.status.set_text(message)
        self.status.set_color('firebrick')
        print(message, file=sys.stderr)
        self.figure.canvas.draw_idle()

    def navigate(self, delta):
        try:
            self.model.select(self.model.index+delta)
            self.status.set_text('')
            self.draw()
        except ContractError as error:
            self.report_error(error, clear=True)
        except Exception as error:
            self.model.current = None
            self.report_error(error, clear=True)
            traceback.print_exc()

    def save(self):
        try:
            # Each click produces a separate bundle; --output is the GUI export parent.
            destination = self.output / f'frame_{self.model.index+1:06d}_{time.time_ns()}'
            bundle = export_frame(self.model.current, self.model.session, destination)
            self.status.set_text(f'Saved: {bundle}')
            self.status.set_color('darkgreen')
            print(f'Saved: {bundle}')
            self.figure.canvas.draw_idle()
        except ContractError as error:
            self.report_error(error)
        except Exception as error:
            self.report_error(error)
            traceback.print_exc()

    def key(self, event):
        if event.key in ('right','n'):
            self.navigate(1)
        elif event.key in ('left','p'):
            self.navigate(-1)
        elif event.key == 's':
            self.save()

    def close(self):
        from matplotlib import pyplot as plt
        plt.close(self.figure)

    def show(self):
        import tkinter as tk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        class ViewerToolbar(NavigationToolbar2Tk):
            # Route saving through our guarded export, including PNG. Standard Save
            # would let the file dialog overwrite arbitrary input/user files.
            toolitems = tuple(item for item in NavigationToolbar2Tk.toolitems if item[0] != 'Save')
        root = tk.Tk()
        root.title('ADE-95 Stored Depth / Camera Point Cloud')
        canvas = FigureCanvasTkAgg(self.figure, master=root)
        toolbar = ViewerToolbar(canvas, root, pack_toolbar=False)
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        canvas.get_tk_widget().focus_set()
        canvas.draw()
        root.protocol('WM_DELETE_WINDOW', root.destroy)
        root.mainloop()
        self.close()
        return self.exit_code


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('positive integer required')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog='GUI: Previous/Next 또는 ←/→, 저장 S. Headless: PNG/NPZ/JSON 새 결과 폴더 생성.')
    parser.add_argument('session', type=Path, help='v1.0.0 세션 폴더 (frames.jsonl 포함); 예: examples/synthetic')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/ade95',
                        help='입력 밖 출력 경로: GUI는 결과 부모 폴더, --headless는 새 결과 폴더 자체')
    parser.add_argument('--headless', action='store_true', help='창 없이 지정 프레임 PNG와 전체 points_m NPZ 저장 후 종료')
    parser.add_argument('--frame', type=positive_int, default=1, help='처음 표시/저장할 프레임 번호 (1부터)')
    parser.add_argument('--max-display-points', type=positive_int, default=50000,
                        help='표시 점 개수 상한; 저장 NPZ는 항상 전체 점군')
    args = parser.parse_args(argv)
    try:
        import matplotlib
        matplotlib.use('Agg' if args.headless else 'TkAgg')
        model = ViewerSession(args.session, args.max_display_points)
        if args.frame > len(model.frame_ids):
            parser.error('--frame exceeds session frame count')
        if args.frame != 1:
            model.select(args.frame-1)
        print(info_text(model.current))
        if args.headless:
            print(f'Saved: {export_frame(model.current, model.session, args.output)}')
            return 0
        return ViewerWindow(model, args.output).show()
    except ContractError as error:
        print(f'실패: {error}', file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
