"""Read-only auxiliary intake validator. Report must be new and outside input."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import fail
from depth_preflight import write_json_new
from replay import file_hashes
from session_pipeline import ERRORS
from session_auxiliary import check_auxiliary
from viewer_data import read_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    record = {'status': 'failure', 'errors': [], 'team_approval': False}
    try:
        if args.report.resolve().is_relative_to(args.session.resolve()):
            fail('PATH_INVALID', 'report must be outside session')
        before = file_hashes(args.session)
        record.update(check_auxiliary(args.session, read_session(args.session)))
        after = file_hashes(args.session)
        record['input_hashes'] = after
        record['originals_unchanged'] = before == after
        if before != after:
            fail('PRESERVATION_MISMATCH', 'session changed during checks')
        record['status'] = 'passed_auxiliary_file_checks'
    except ERRORS as error:
        record['errors'].append({'code': getattr(error, 'code', 'INPUT_CORRUPT'), 'message': str(error)})
    try:
        if args.report.resolve().is_relative_to(args.session.resolve()):
            fail('PATH_INVALID', 'report must be outside session')
        args.report.parent.mkdir(parents=True, exist_ok=True)
        write_json_new(args.report, record)
    except ERRORS as error:
        print(f'failure: {error}', file=sys.stderr)
        return 1
    print(f'{record["status"]}: {args.report}')
    return 0 if not record['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
