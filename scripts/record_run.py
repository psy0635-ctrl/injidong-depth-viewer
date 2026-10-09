"""프로젝트 Python으로 명령을 실행하고 UTF-8 실행 근거를 새 파일로 저장한다."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not re.fullmatch(r'[a-zA-Z0-9_-]+', args.label):
        parser.error('명령과 영문/숫자/밑줄/하이픈 label이 필요합니다.')
    actual = [sys.executable, '-X', 'utf8', *command]
    started = datetime.now(KST).isoformat()
    result = subprocess.run(actual, cwd=ROOT, env={**os.environ, 'PYTHONUTF8': '1'},
                            capture_output=True, text=True, encoding='utf-8')
    record = {
        'source': '이번 에이전트 실행 / 사용자 전달 결과와 별개',
        'started_at': started, 'finished_at': datetime.now(KST).isoformat(),
        'timezone': 'Asia/Seoul', 'os': platform.platform(),
        'windows_version': platform.win32_ver(), 'python': sys.version,
        'executable': sys.executable, 'numpy': np.__version__, 'cwd': str(ROOT),
        'command': actual, 'exit_code': result.returncode,
        'stdout': result.stdout, 'stderr': result.stderr,
    }
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    path = logs / f'{time.time_ns()}_{args.label}.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    print(f'실행 기록: {path} (종료 코드 {result.returncode})')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
