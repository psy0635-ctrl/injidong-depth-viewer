"""Run repository checks in separate interpreters; optional real input stays opt-in."""
import os,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    stages=[
        ('core and pipeline',ROOT,['-m','unittest','discover','-s','tests','-v']),
        ('mobile intake',ROOT,['-m','unittest','discover','-s','tools/mobile_session_intake/tests','-v']),
        ('stored Depth',ROOT,['tools/stored_depth_analysis/tests/test_stored_array_comparison.py','--baseline',str(ROOT)]),
        ('synthetic volume',ROOT,['experiments/synthetic_volume/tests/test_synthetic_volume.py','--baseline',str(ROOT)]),
        ('local review portable',ROOT/'apps/local_review',['-m','unittest','discover','-s','tests','-v']),
        ('two view synthetic',ROOT,['-m','unittest','discover','-s','experiments/two_view','-p','test_*.py','-v']),
    ]
    with tempfile.TemporaryDirectory(prefix='injidong-checks-') as tmp:
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['MPLCONFIGDIR']=str(Path(tmp)/'mpl');env['MOBILE_CONTRACT_ROOT']=str(ROOT)
        for key in ('PYTHONPATH','MOBILE_TEST_ZIP','INJIDONG_ROBOT_REVIEW_ROOT','INJIDONG_TEST_GUI'):env.pop(key,None)
        for name,cwd,args in stages:
            if name in ('stored Depth','synthetic volume'):
                args=[*args,'--output-root',str(Path(tmp)/name.replace(' ','-'))]
            print('\nCHECK '+name,flush=True)
            result=subprocess.run([sys.executable,'-B','-X','utf8',*args],cwd=cwd,env=env)
            print('EXIT '+str(result.returncode)+' '+name,flush=True)
            if result.returncode:return result.returncode
    return 0


if __name__=='__main__':raise SystemExit(main())
