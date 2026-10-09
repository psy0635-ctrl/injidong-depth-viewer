"""실제 Tk 창에서 자동 Matplotlib 이벤트를 검증한다. 사람의 직접 조작 검증은 아니다."""
import argparse
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest.mock import patch

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backend_bases import MouseEvent, KeyEvent

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from viewer_data import ViewerSession
from viewer import ViewerWindow, main as viewer_main


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, default=ROOT/'examples/viewer_multiframe')
    parser.add_argument('--output', type=Path, required=True, help='새 검증 폴더')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    window = ViewerWindow(ViewerSession(args.session), output/'exports')
    result = {'method':'real Tk window; programmatic Matplotlib canvas events',
              'manual_user_interaction_verified':False, 'status':'failure', 'checks':{}}
    real_tk = tk.Tk

    def create_root():
        root = real_tk()
        def exercise():
            try:
                canvas = window.figure.canvas
                root.update_idletasks()
                result['checks']['window_viewable'] = bool(root.winfo_viewable())
                assert result['checks']['window_viewable']
                def click(button):
                    x,y = button.ax.transAxes.transform((.5,.5))
                    for name in ('button_press_event','button_release_event'):
                        canvas.callbacks.process(name, MouseEvent(name,canvas,x,y,button=1))
                    canvas.draw()
                click(window.buttons[1])
                assert window.model.index==1
                assert 'ade95_synthetic_000002' in window.info.get_text()
                assert float(window.depth_image.get_array()[0,0])==1.5
                result['checks']['next_button_joint_refresh'] = True
                ax = window.cloud_ax
                before = (ax.elev,ax.azim)
                x,y = ax.transAxes.transform((.5,.5))
                canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',canvas,x,y,button=1))
                canvas.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',canvas,x+45,y+25,button=1))
                canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',canvas,x+45,y+25,button=1))
                assert before!=(ax.elev,ax.azim)
                result['checks']['rotation_changed'] = {'before':before,'after':[ax.elev,ax.azim]}
                before_limits = list(ax.get_xlim())
                canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',canvas,x,y,button=3))
                canvas.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',canvas,x+25,y+20,button=3))
                canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',canvas,x+25,y+20,button=3))
                assert before_limits!=list(ax.get_xlim())
                result['checks']['zoom_changed'] = {'before':before_limits,'after':list(ax.get_xlim())}
                click(window.buttons[2])
                bundles = list((output/'exports').glob('frame_*'))
                assert len(bundles)==1 and (bundles[0]/'points.npz').is_file()
                result['checks']['save_button_bundle'] = str(bundles[0])
                canvas.callbacks.process('key_press_event',KeyEvent('key_press_event',canvas,key='right'))
                assert window.model.index==2
                click(window.buttons[1])
                assert window.model.index==2
                click(window.buttons[0])
                assert window.model.index==1
                result['checks']['keys_previous_last_boundary'] = True
                canvas.draw()
                window.figure.savefig(output/'tk_canvas.png')
                result['status']='success'
            except Exception as error:
                result['error'] = f'{type(error).__name__}: {error}'
            finally:
                root.after(100,root.destroy)
        root.after(650,exercise)
        # Watchdog for test failures or backend deadlock.
        root.after(15000,root.destroy)
        return root

    with patch('tkinter.Tk', side_effect=create_root):
        code = window.show()
    result['checks']['normal_close_exit_code'] = code
    def close_cli_root():
        root = real_tk()
        root.after(500, root.destroy)
        return root
    with patch('tkinter.Tk', side_effect=close_cli_root):
        cli_code = viewer_main([str(args.session), '--output', str(output/'cli_exports')])
    result['checks']['gui_cli_main_normal_close_exit_code'] = cli_code
    result['finished_ns'] = str(time.time_ns())
    with (output/'gui_check.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0 if result['status']=='success' and code==0 and cli_code==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
