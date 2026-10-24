"""Materialize an explicitly supplied original ZIP into a new external intake; never run capture code."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import fail
from depth_preflight import (check_hash, digest, member_path, new_run, strict_json,
                             validate_receipt, write_json_new)
from session_pipeline import ERRORS


def prepare(archive_path, receipt_path, basis_path, output_root):
    archive_path, receipt_path, basis_path = [Path(p).resolve() for p in (archive_path, receipt_path, basis_path)]
    output_root = Path(output_root).resolve()
    if output_root.is_relative_to(ROOT) or any(output_root.is_relative_to(p.parent) for p in (archive_path, receipt_path, basis_path)):
        fail('PATH_INVALID', 'intake must be new and outside the immutable package/input directories')
    receipt = strict_json(receipt_path)
    validate_receipt(receipt)
    basis = strict_json(basis_path)
    if not basis.get('blocked_requirements') or basis['source']['sha256'] != receipt['members'][receipt['raw_array']['file']]:
        fail('EVIDENCE_MISMATCH', 'packaged blocked basis/receipt mismatch')
    before = {str(p): digest(p) for p in (archive_path, receipt_path, basis_path)}
    check_hash(before[str(archive_path)], receipt['zip_sha256'], 'original archive')
    run = new_run(output_root)
    record = {'status': 'failure', 'archive': str(archive_path), 'archive_sha256': before[str(archive_path)],
              'capture_code_executed': False, 'not_a_frame_packet': True, 'errors': []}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(set(n.casefold() for n in names)) != len(names) or set(names) != set(receipt['members']):
                fail('ZIP_MEMBERS_INVALID', 'unexpected/duplicate original members')
            destinations = [member_path(run, i) for i in infos]
            if archive.testzip() is not None:
                fail('ZIP_CRC_INVALID', 'original CRC mismatch')
            for info, destination in zip(infos, destinations):
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, destination.open('xb') as dest:
                    shutil.copyfileobj(src, dest)
                check_hash(digest(destination), receipt['members'][info.filename], info.filename)
        with basis_path.open('rb') as src, (run / 'basis.json').open('xb') as dest:
            shutil.copyfileobj(src, dest)
        after = {p: digest(p) for p in before}
        if before != after:
            fail('PRESERVATION_MISMATCH', 'packaged inputs changed')
        record.update(status='prepared_blocked_intake', basis_path=str(run / 'basis.json'),
                      originals_unchanged=True, member_hashes=receipt['members'])
    except ERRORS as error:
        record['errors'].append({'code': getattr(error, 'code', 'INPUT_CORRUPT'), 'message': str(error)})
    write_json_new(run / 'preparation.json', record)
    if record['errors']:
        fail('INTAKE_PREPARATION_FAILED', json.dumps(record['errors'], ensure_ascii=False))
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'docs/inputs/ade71-d405-20261013.json')
    parser.add_argument('--basis', type=Path, default=ROOT / 'examples/ade71_session_intake/d405_blocked/basis.json')
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.archive, args.receipt, args.basis, args.output_root)
    except ERRORS as error:
        print(f'failure: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
