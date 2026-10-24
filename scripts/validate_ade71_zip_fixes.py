"""Independent minimum CLI/import/full-value validation; outputs in a fresh run.

Use --regressions on an extracted submission to run only the new four-finding
test module. Existing venv reuse is recorded, never a fresh-install claim.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true')
    parser.add_argument('--archive', type=Path,
                        help='optional external D405 original ZIP; omitted means real-input check is not run')
    parser.add_argument('--receipt', type=Path, default=ROOT / 'docs/inputs/ade71-d405-20261013.json')
    parser.add_argument('--basis', type=Path,
                        default=ROOT / 'examples/ade71_session_intake/d405_blocked/basis.json')
    args = parser.parse_args()
    run = args.output_root.resolve() / ('run_' + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failure', 'started_at': datetime.now(timezone(timedelta(hours=9))).isoformat(),
              'root': str(ROOT), 'run': str(run), 'errors': [], 'existing_venv_reused': True,
              'new_environment_installed': False, 'sdk_camera_android_executed': False,
              'environment': {'os': platform.platform(), 'python': sys.version, 'executable': sys.executable,
                              'numpy': np.__version__, 'numpy_import': np.__file__}}
    def command(label, arguments, expected):
        cmd = [sys.executable, '-B', '-X', 'utf8', *map(str, arguments)]
        env = dict(os.environ)
        for name in ('PYTHONPATH', 'PYTHONHOME'):
            env.pop(name, None)
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8')
        record = {'command': cmd, 'cwd': str(ROOT), 'expected_exit': expected, 'exit_code': result.returncode,
                  'stdout': result.stdout, 'stderr': result.stderr}
        with (run / (label + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        if result.returncode != expected:
            raise AssertionError(f'{label}: unexpected exit {result.returncode}: {result.stderr}')
        return result
    try:
        import contract, session_boundary, session_pipeline, session_auxiliary, depth_preflight, replay, viewer_data
        report['imports'] = {m.__name__: str(Path(m.__file__).resolve()) for m in
            (contract, session_boundary, session_pipeline, session_auxiliary, depth_preflight, replay, viewer_data)}
        assert all(Path(p).is_relative_to(ROOT) for p in report['imports'].values())
        import PIL
        report['environment']['pillow'] = PIL.__version__
        source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in (ROOT / 'src').glob('*.py')}
        basis_path = ROOT / 'examples/ade71_session_intake/synthetic/basis.json'
        expected_path = ROOT / 'examples/ade71_session_intake/synthetic/expected_points.json'
        command('synthetic_cli', [ROOT / 'src/session_pipeline.py', '--basis', basis_path,
            '--output-root', run / 'synthetic', '--repeat', '10', '--expected-points', expected_path], 0)
        synthetic, = (run / 'synthetic').glob('run_*')
        result = json.loads((synthetic / 'validation.json').read_text(encoding='utf-8'))
        assert result['status'] == 'passed_file_boundary_validation' and result['completed_repeats'] == 10
        assert result['originals_unchanged'] and result['session_unchanged']
        frame, = viewer_data.read_session(synthetic / 'session')
        basis = json.loads(basis_path.read_text(encoding='utf-8'))
        with np.load(basis_path.parent / basis['source']['file'], allow_pickle=False) as data:
            raw = data[basis['source']['key']][0]
        depth = (raw.astype(np.float64) * basis['conversion']['scale_to_m']).astype(np.float32)
        valid = np.isfinite(depth) & (depth > 0)
        for value in basis['conversion']['invalid_values']:
            valid &= raw != value
        depth[~valid] = 0
        assert frame.depth_m.dtype == np.float32 and frame.valid_mask.dtype == np.bool_
        assert np.array_equal(frame.depth_m, depth) and np.array_equal(frame.valid_mask, valid)
        v, u = np.nonzero(valid)
        i = frame.metadata['intrinsics']
        z = depth[v, u]
        points = np.column_stack(((u-i['cx'])*z/i['fx'], (v-i['cy'])*z/i['fy'], z)).astype(np.float32)
        np.testing.assert_array_equal(points, np.asarray([[0,0,1],[.01,0,1],[0,.01,1]], dtype=np.float32))
        processing = session_boundary.load_processing_result(synthetic / 'results/frame_000000/processing.json')
        cloud = synthetic / 'results/frame_000000/points.npz'
        with np.load(cloud, allow_pickle=False) as data:
            assert data.files == ['points_m'] and data['points_m'].dtype == np.float32
            np.testing.assert_array_equal(data['points_m'], points)
        assert processing['point_cloud']['point_count'] == 3 and processing['point_cloud']['unit'] == 'm'
        assert sha(cloud) == processing['point_cloud']['sha256'] and processing['volume_m3'] is None
        original_meta = basis['frames'][0]['metadata']
        for name in ('capture_time','host_receive_time','capture_source','provenance','replay_time'):
            assert frame.metadata[name] == original_meta[name]
        report['synthetic'] = {'status': result['status'], 'exit_code': 0, 'repeat': 10,
            'validation': str(synthetic / 'validation.json'), 'completion': str(synthetic / session_boundary.COMPLETION),
            'points_m': points.tolist(), 'point_count': 3, 'points_sha256': sha(cloud), 'whole_values_matched': True}
        report['d405'] = {'status': 'not_run', 'reason': 'external original ZIP not supplied'}
        if args.archive is not None:
            # The materializer deliberately refuses intake inside the package tree.
            with tempfile.TemporaryDirectory(prefix='ade71_d405_intake_') as intake_directory:
                prepared = command('prepare_d405', [ROOT / 'scripts/prepare_d405_intake.py',
                                    '--archive', args.archive, '--receipt', args.receipt, '--basis', args.basis,
                                    '--output-root', Path(intake_directory)], 0)
                intake = json.loads(prepared.stdout)
                assert intake['capture_code_executed'] is False and intake['originals_unchanged']
                blocked = command('d405_blocked_cli', [ROOT / 'src/session_pipeline.py', '--basis', intake['basis_path'],
                    '--output-root', run / 'blocked', '--repeat', '3'], 1)
                assert 'INTAKE_BLOCKED' in blocked.stderr and 'passed_file_boundary_validation' not in blocked.stdout
                blocked_run, = (run / 'blocked').glob('run_*')
                blocked_report = json.loads((blocked_run / 'validation.json').read_text(encoding='utf-8'))
                assert blocked_report['status'] == 'failure'
                assert any(e['code'] == 'INTAKE_BLOCKED' for e in blocked_report['errors'])
                assert not list(blocked_run.rglob('frames.jsonl')) and not list(blocked_run.rglob('points.npz'))
                report['d405'] = {'status': 'INTAKE_BLOCKED', 'exit_code': 1, 'normal_session': False,
                                  'point_cloud': False, 'validation': str(blocked_run / 'validation.json')}
        command('auxiliary_cli', [ROOT / 'scripts/verify_ade71_auxiliary.py',
            ROOT / 'examples/ade71_mobile_boundary_synthetic', '--report', run / 'auxiliary.json'], 0)
        if args.regressions:
            result = command('four_finding_regressions', ['-m', 'unittest', 'discover', '-s', 'tests',
                         '-p', 'test_session_zip_fixes.py', '-v'], 0)
            report['regressions'] = {'executed': True, 'log': str(run / 'four_finding_regressions.json'),
                                    'notice': 'Skip remains skip; unittest stdout/stderr are authoritative.'}
        assert source_hashes == {p.relative_to(ROOT).as_posix(): sha(p) for p in (ROOT / 'src').glob('*.py')}
        report['source_unchanged'] = True
        report['status'] = 'passed_minimum_cli_validation'
    except Exception as error:
        report['errors'].append({'type': type(error).__name__, 'message': str(error)})
    report['finished_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    with (run / 'validation.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': report['status'], 'report': str(run / 'validation.json'), 'errors': report['errors']}, ensure_ascii=False))
    return 0 if report['status'] == 'passed_minimum_cli_validation' else 1


if __name__ == '__main__':
    raise SystemExit(main())
