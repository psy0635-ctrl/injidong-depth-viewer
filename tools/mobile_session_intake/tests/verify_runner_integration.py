"""One real-checker CLI integration using the existing SYNTHETIC fixture builder.

This does not run the old test suite, capture hardware, or calculate point clouds.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('python', 'contract-root', 'verification-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    baseline = args.contract_root.resolve()
    root = args.verification_root.resolve()
    tools = Path(__file__).resolve().parents[1]
    for protected in (baseline, tools):
        if root.is_relative_to(protected) or protected.is_relative_to(root):
            parser.error('verification root must be disjoint from baseline and checker code')
    root.mkdir(parents=True, exist_ok=False)
    os.environ['MOBILE_CONTRACT_ROOT'] = str(baseline)
    sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location('existing_mobile_fixture', tools / 'tests/test_mobile_session.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    fixture = fixtures.MobileIntakeTests()
    fixture.setUp()
    try:
        # Reuse all fixture bytes unchanged; no injected real flags/calibration.
        shutil.copytree(fixture.session, root / 'synthetic_session')
    finally:
        fixture.tearDown()
    session = root / 'synthetic_session'
    before = fixtures.inventory(session)
    command = [str(args.python.resolve()), '-B', '-X', 'utf8', str(tools / 'run_mobile_intake.py'),
               '--python', str(args.python.resolve()), '--checker', str(tools / 'check_mobile_session.py'),
               '--contract-root', str(baseline), '--session', str(session),
               '--result-root', str(root / 'results')]
    process = subprocess.run(command, shell=False, capture_output=True)
    (root / 'integration_stdout.txt').write_bytes(process.stdout)
    (root / 'integration_stderr.txt').write_bytes(process.stderr)
    summary = json.loads(process.stdout.decode('utf-8'))
    report = json.loads(Path(summary['checker_report']).read_text(encoding='utf-8'))
    assert process.returncode == 10, summary
    assert summary['final_status'] == 'processing_held'
    assert summary['checker_exit_code'] == 0
    assert report['status'] == 'passed_mobile_file_checks' and report['data_kind'] == 'synthetic'
    assert report['input_sha256'] == before == fixtures.inventory(session)
    assert summary['input_verification']['before_after']['matched'] is True
    assert summary['input_verification']['checker_report_comparison']['matched'] is True
    assert all(summary[k] is False for k in ('geometry_verified', 'processing_ready', 'viewer_launched'))
    assert not list(session.rglob('.ade71*'))
    evidence = {'validation_kind': 'synthetic_real_checker_cli_integration', 'hardware_capture': False,
                'fixture_builder': str(tools / 'tests/test_mobile_session.py'),
                'fixture_reused_unchanged': True, 'command': command,
                'runner_exit_code': process.returncode, 'checker_exit_code': summary['checker_exit_code'],
                'runner_summary': summary['summary_path'], 'checker_report': summary['checker_report'],
                'original_synthetic_input_unchanged': True, 'status': 'passed'}
    (root / 'integration_verification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
