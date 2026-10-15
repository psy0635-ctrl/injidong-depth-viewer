"""Run file intake and recheck input; this CLI never authorizes processing."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import uuid

VERSION = 'mobile-intake-runner-v1'
CODES = {'processing_held': 10, 'checker_failed': 20, 'input_changed': 21,
         'execution_error': 22, 'report_error': 23, 'preflight_error': 24,
         'output_error': 25}
BASELINE_FILES = {'src/contract.py', 'src/session_boundary.py', 'schemas/frame.schema.json'}
FLAGS = ('geometry_verified', 'processing_ready', 'rgb_depth_alignment_verified',
         'world_pose_verified')
SCOPE = ('Same rules as pinned checker inventory(): all recursively enumerated regular '
         'files, including auxiliary/hidden files; session-relative POSIX paths and '
         'SHA-256 of bytes. Reject symlinks and resolved escapes. Empty directories '
         'and file metadata are excluded. Point-in-time comparisons, not a lock.')


class RunnerError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RunnerError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result

    def constant(value):
        raise RunnerError(f'nonfinite JSON token: {value}')

    def number(value):
        result = float(value)
        require(math.isfinite(result), 'nonfinite JSON number')
        return result

    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=constant, parse_float=number)


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def inventory(root):
    """Keep the pinned checker's file/path/content scope, without importing it."""
    result = {}
    require(root.is_dir(), 'input directory no longer exists')
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), f'symlink input not supported: {path.name}')
        require(path.resolve().is_relative_to(root), 'input alias escapes session')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def difference(before, after):
    return {'matched': before == after, 'added': sorted(after.keys() - before.keys()),
            'removed': sorted(before.keys() - after.keys()),
            'modified': sorted(k for k in before.keys() & after.keys() if before[k] != after[k])}


def validate_hashes(value):
    require(type(value) is dict, 'input_sha256 must be an object')
    for name, hashed in value.items():
        require(type(name) is str and bool(name) and '\\' not in name and ':' not in name,
                'invalid input_sha256 relative path')
        path = Path(name)
        require(bool(path.parts) and not path.is_absolute() and not PureWindowsPath(name).drive
                and '..' not in path.parts and path.as_posix() == name,
                'noncanonical input_sha256 path')
        require(type(hashed) is str and re.fullmatch('[0-9a-f]{64}', hashed) is not None,
                'invalid input_sha256 digest')


def disjoint(output, protected):
    for source in protected:
        require(not output.is_relative_to(source) and not source.is_relative_to(output),
                f'result root overlaps protected directory: {source}')


# The selected baseline's guard enforces its own publication policy, including
# ancestor markers. No guard is copied, bypassed, or called in staging context.
GUARD_SCRIPT = '''import json,sys
sys.path.insert(0, sys.argv[1])
try:
    from session_boundary import guard_read
    guard_read(sys.argv[2])
except Exception as error:
    print(json.dumps({'error': str(error)}))
    raise SystemExit(1)
print(json.dumps({'python': sys.version, 'executable': sys.executable}))
'''


def preflight(args, summary):
    paths = {name: getattr(args, name).resolve() for name in
             ('python', 'checker', 'contract_root', 'session', 'result_root')}
    summary['paths'] = {k: str(v) for k, v in paths.items()}
    for name in ('python', 'checker'):
        require(paths[name].is_file(), f'{name} file missing: {paths[name]}')
    for name in ('contract_root', 'session'):
        require(paths[name].is_dir(), f'{name} directory missing: {paths[name]}')
    protected = [paths['session'], paths['contract_root'], paths['checker'].parent,
                 Path(__file__).resolve().parent]
    disjoint(paths['result_root'], protected)
    require(not paths['result_root'].exists() or paths['result_root'].is_dir(),
            'result root is not a directory')
    manifest = paths['checker'].with_name('baseline_hashes.json')
    expected = read_json(manifest)
    require(type(expected) is dict and set(expected) == BASELINE_FILES,
            'unsupported baseline_hashes.json file inventory')
    actual = {}
    for name in sorted(BASELINE_FILES):
        file = paths['contract_root'] / name
        require(file.is_file() and file.resolve().is_relative_to(paths['contract_root']),
                f'baseline file missing or escapes root: {name}')
        actual[name] = digest(file)
        require(actual[name] == expected[name], f'baseline mismatch: {name}')
    summary['tools'] = {'runner_version': VERSION, 'runner_sha256': digest(__file__),
                        'checker_sha256': digest(paths['checker']),
                        'python_sha256': digest(paths['python']),
                        'baseline_hashes_sha256': digest(manifest),
                        'baseline_files_sha256': actual}
    guard = subprocess.run([str(paths['python']), '-B', '-X', 'utf8', '-c', GUARD_SCRIPT,
                            str(paths['contract_root'] / 'src'), str(paths['session'])],
                           shell=False, capture_output=True, timeout=30)
    require(guard.returncode == 0,
            'baseline publication guard failed: ' +
            (guard.stdout + guard.stderr).decode('utf-8', errors='replace').strip())
    environment = json.loads(guard.stdout.decode('utf-8'))
    require(type(environment) is dict and all(type(environment.get(k)) is str
            for k in ('python', 'executable')), 'invalid Python preflight response')
    summary['selected_python'] = environment
    return paths, protected


def validate_report(report, returncode):
    require(type(report) is dict, 'checker report must be a JSON object')
    status = report.get('status')
    require(status in ('passed_mobile_file_checks', 'failed_mobile_file_checks'),
            'unknown checker report status')
    require(returncode == (0 if status == 'passed_mobile_file_checks' else 1),
            'checker exit code and report status disagree')
    for flag in FLAGS:
        require(type(report.get(flag)) is bool, f'{flag} must be a JSON boolean')
    env = report.get('environment')
    require(type(env) is dict and all(type(env.get(k)) is str for k in
            ('python', 'numpy', 'platform')), 'invalid checker environment')
    if 'input_sha256' in report:
        validate_hashes(report['input_sha256'])
    if status == 'failed_mobile_file_checks':
        require(type(report.get('error')) is str and bool(report['error'].strip()),
                'failed checker report requires an error string')
        return
    require(type(report.get('input_sha256')) is dict, 'passed report requires input_sha256')
    require(report.get('data_kind') in ('real', 'synthetic'), 'invalid data_kind')
    require(report.get('core_loader_compatible') is True, 'passed report requires loader compatibility')
    require(type(report.get('server_uploaded')) is bool, 'server_uploaded must be boolean')
    counts = report.get('counts')
    require(type(counts) is dict and set(counts) ==
            {'depth_frames', 'phone_rgb_images', 'imu_samples'} and
            all(type(v) is int and v > 0 for v in counts.values()), 'invalid checker counts')
    for key in ('depth_frames', 'imu_sensor_types', 'warnings', 'additional_files',
                'unreferenced_collection_files', 'remaining'):
        require(type(report.get(key)) is list, f'{key} must be an array')
    require(len(report['depth_frames']) == counts['depth_frames'] and
            all(type(row) is dict for row in report['depth_frames']), 'invalid depth frame details')
    require(not report['unreferenced_collection_files'], 'passed report has unreferenced collection files')
    require(type(report.get('mobile_commit_reference')) is str and
            re.fullmatch('[0-9a-f]{40}', report['mobile_commit_reference']) is not None,
            'invalid mobile commit reference')


def read_current_report(directory, stdout_path, summary):
    # This directory was exclusively created for this invocation. Never search
    # old result roots or use a glob to substitute a report for checker stdout.
    files = list(directory.iterdir())
    require(files, 'checker report missing')
    require(len(files) == 1, 'multiple or unexpected checker report candidates')
    path = files[0]
    require(not path.is_symlink() and path.is_file() and path.resolve().parent == directory
            and re.fullmatch(r'mobile_check_[0-9a-f]{32}\.json', path.name) is not None,
            'unexpected checker report path or filename')
    summary['checker_report'] = str(path)
    summary['checker_report_sha256'] = digest(path)
    lines = [line for line in stdout_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    require(len(lines) == 1, 'checker stdout must contain exactly one report path')
    emitted = Path(lines[0])
    require(emitted.is_absolute() and emitted.resolve() == path.resolve(),
            'checker stdout does not identify this invocation report')
    return read_json(path)


def finish(summary, state, reason, run=None):
    summary.update(final_status=state, reason=reason, exit_code=CODES[state],
                   finished_at_utc=datetime.now(timezone.utc).isoformat())
    if run is not None:
        try:
            destination = run / 'runner_summary.json'
            summary['summary_path'] = str(destination)
            pending = run / 'runner_summary.pending.json'
            # Publish only after writing AND closing succeeded. A failed write
            # leaves diagnostic pending bytes, never a completed final summary.
            write_new(pending, summary)
            require(not destination.exists(), 'runner summary already exists')
            pending.rename(destination)
        except (OSError, ValueError) as error:
            summary.update(final_status='output_error', reason=f'cannot save runner summary: {error}',
                           exit_code=CODES['output_error'], summary_path=None)
    if summary['final_status'] == 'output_error':
        print(f"output_error: {summary['reason']}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    return summary['exit_code']


def run_intake(args):
    summary = {'summary_format': VERSION, 'run_id': uuid.uuid4().hex,
               'started_at_utc': datetime.now(timezone.utc).isoformat(),
               'paths': {}, 'tools': {}, 'checker_exit_code': None, 'checker_report': None,
               'summary_path': None, 'geometry_verified': False, 'processing_ready': False,
               'viewer_launched': False, 'issues': [],
               'input_verification': {'scope': SCOPE, 'status': 'not_run',
                                      'checker_report_comparison': 'not_available'}}
    try:
        paths, protected = preflight(args, summary)
        before = inventory(paths['session'])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        return finish(summary, 'preflight_error', str(error))
    run = None
    owns_run = False
    try:
        paths['result_root'].mkdir(parents=True, exist_ok=True)
        disjoint(paths['result_root'].resolve(), protected)
        run = paths['result_root'] / ('run_' + summary['run_id'])
        run.mkdir(exist_ok=False)
        owns_run = True
        reports = run / 'checker_reports'
        reports.mkdir()
        write_new(run / 'input_before.json', before)
    except (OSError, ValueError) as error:
        return finish(summary, 'output_error', str(error), run if owns_run else None)
    command = [str(paths['python']), '-B', '-X', 'utf8', str(paths['checker']),
               str(paths['session']), '--contract-root', str(paths['contract_root']),
               '--report-dir', str(reports)]
    summary['checker_command'] = command
    summary['logs'] = {name: str(run / f'checker_{name}.txt') for name in ('stdout', 'stderr')}
    state, reason = 'execution_error', 'checker did not finish'
    try:
        state = 'output_error'
        with (run / 'checker_stdout.txt').open('xb') as stdout, (run / 'checker_stderr.txt').open('xb') as stderr:
            state = 'execution_error'
            process = subprocess.run(command, shell=False, stdout=stdout, stderr=stderr,
                                     timeout=args.timeout_seconds)
            summary['checker_exit_code'] = process.returncode
            state = 'output_error'  # Includes buffered log flush/close failures.
        state = 'execution_error'
        if process.returncode not in (0, 1):
            reason = f'abnormal checker exit: {process.returncode}'
        else:
            state = 'report_error'
            report = read_current_report(reports, run / 'checker_stdout.txt', summary)
            validate_report(report, process.returncode)
            summary['checker_status'] = report['status']
            if 'input_sha256' in report:
                summary['input_verification']['checker_report_comparison'] = 'pending'
            if report['status'] == 'failed_mobile_file_checks':
                state, reason = 'checker_failed', report['error']
            else:
                state, reason = 'processing_held', 'File checks passed; processing is withheld by runner policy.'
                if report['geometry_verified'] or report['processing_ready']:
                    reason += ' Checker readiness=true does not authorize any processing.'
    except subprocess.TimeoutExpired:
        state, reason = 'execution_error', f'checker timeout after {args.timeout_seconds} seconds'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        reason = f'{type(error).__name__}: {error}'
    summary['checker_outcome'] = {'status': state, 'reason': reason}
    if state != 'processing_held':
        summary['issues'].append(summary['checker_outcome'])
    try:
        root_missing = not paths['session'].is_dir()
        after = {} if root_missing else inventory(paths['session'])
        verification = summary['input_verification']
        verification['root_missing'] = root_missing
        verification['before_after'] = difference(before, after)
        verification['snapshots'] = {'before': str(run / 'input_before.json'),
                                     'after': str(run / 'input_after.json')}
        verification['status'] = 'matched' if before == after and not root_missing else 'changed'
        if verification['checker_report_comparison'] == 'pending':
            verification['checker_report_comparison'] = difference(report['input_sha256'], after)
        mismatch = (root_missing or before != after or (type(verification['checker_report_comparison']) is dict
                    and not verification['checker_report_comparison']['matched']))
        if mismatch and state != 'output_error':
            state, reason = 'input_changed', 'Input path/content inventory differs before/after checking or from the checker report.'
        try:
            write_new(run / 'input_after.json', after)
        except OSError as error:
            state, reason = 'output_error', f'cannot save input recheck snapshot: {error}'
    except (OSError, ValueError, RuntimeError) as error:
        summary['input_verification'].update(status='unavailable', error=str(error))
        if state != 'output_error':
            state, reason = 'execution_error', f'input recheck could not complete: {error}'
    return finish(summary, state, reason, run)


def positive_seconds(text):
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('timeout must be positive integer seconds')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('python', 'checker', 'contract-root', 'session', 'result-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=positive_seconds, default=300)
    return run_intake(parser.parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
