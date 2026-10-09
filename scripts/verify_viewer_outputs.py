"""저장 파일 무결성과 명시한 입력의 전체 점군·메타데이터를 분리 검증한다."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import ContractError, fail, iter_frames, point_cloud_camera, validate_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, code, message):
    if not condition:
        fail(code, message)


def bundle_file(bundle, name):
    """출력에 기록된 파일은 결과 폴더 안의 상대 경로여야 한다."""
    require(isinstance(name, str) and bool(name), 'RESULT_INVALID', '결과 파일 경로가 비어 있습니다.')
    path = Path(name)
    require(not (path.is_absolute() or path.drive or path.root), 'PATH_INVALID', '결과 파일은 상대 경로여야 합니다.')
    candidate = (bundle / path).resolve()
    require(candidate.is_relative_to(bundle), 'PATH_INVALID', '결과 파일 경로가 결과 폴더를 벗어납니다.')
    return candidate


def verify_artifacts(bundle):
    result = json.loads((bundle / 'processing.json').read_text(encoding='utf-8'))
    validate_json(result, 'processing')
    require(result['status'] == 'success' and result['stage'] == 'point_cloud',
            'RESULT_INVALID', '성공한 뷰어 point_cloud 결과가 필요합니다.')
    audit = json.loads((bundle / 'viewer_export.json').read_text(encoding='utf-8'))
    validate_json(audit['input_metadata'], 'frame')
    cloud = result['point_cloud']
    require(cloud['frame'] == 'camera' and cloud['unit'] == 'm' and cloud['key'] == 'points_m',
            'RESULT_INVALID', 'points_m, m 단위, camera 좌표가 필요합니다.')
    require(result['volume_m3'] is None and result['volume_method'] is None,
            'RESULT_INVALID', '뷰어 결과의 미계산 부피는 null이어야 합니다.')
    cloud_path = bundle_file(bundle, cloud['file'])
    preview_path = bundle_file(bundle, audit['preview'])
    hashes = audit['output_sha256']
    require(isinstance(hashes, dict) and set(hashes) == {cloud['file'], audit['preview'], 'processing.json'},
            'RESULT_INVALID', 'PNG·NPZ·processing.json 해시가 모두 필요합니다.')
    for name, expected in hashes.items():
        require(digest(bundle_file(bundle, name)) == expected, 'CHECKSUM_MISMATCH', f'{name}: 파일 해시가 다릅니다.')
    require(digest(cloud_path) == cloud['sha256'], 'CHECKSUM_MISMATCH', 'ProcessingResult의 점군 해시가 다릅니다.')
    # 이미지 내용의 시각적 판독은 별도이며 여기서는 파일·해시를 검사한다.
    require(preview_path.is_file(), 'RESULT_INVALID', '미리보기 파일이 없습니다.')
    with np.load(cloud_path, allow_pickle=False) as data:
        require(data.files == ['points_m'], 'RESULT_INVALID', 'NPZ에는 points_m 배열 하나가 필요합니다.')
        points = data['points_m'].copy()
    require(points.dtype == np.float32, 'POINT_CLOUD_DTYPE_INVALID', '저장 점군은 float32여야 합니다.')
    require(points.shape == (cloud['point_count'], 3), 'POINT_CLOUD_SHAPE_INVALID', '점군 shape와 point_count가 다릅니다.')
    require(bool(np.isfinite(points).all()), 'POINT_CLOUD_VALUES_INVALID', '점군에 유한하지 않은 좌표가 있습니다.')
    require(audit['full_point_count'] == len(points), 'RESULT_INVALID', '감사 기록의 전체 점 개수가 다릅니다.')
    require(audit['input_metadata']['frame_id'] == result['frame_id'],
            'METADATA_MISMATCH', '결과와 감사 기록의 frame_id가 다릅니다.')
    return result, audit, points


def compare_input(result, audit, points, session):
    """frame_id는 조회 키일 뿐이며 좌표는 실제 배열·내참수로 계산한다."""
    matches = [frame for frame in iter_frames(session) if frame.metadata['frame_id'] == result['frame_id']]
    require(len(matches) == 1, 'FRAME_NOT_FOUND', f"입력 세션에 결과 frame_id={result['frame_id']}가 없습니다.")
    frame = matches[0]
    require(audit['input_metadata'] == frame.metadata, 'METADATA_MISMATCH', '저장된 입력 metadata가 실제 입력과 다릅니다.')
    expected = point_cloud_camera(frame)
    require(points.dtype == expected.dtype and points.shape == expected.shape,
            'POINT_CLOUD_SHAPE_INVALID', '입력에서 계산한 전체 점군의 dtype·shape·점 개수가 다릅니다.')
    require(bool(np.array_equal(points, expected)), 'POINT_CLOUD_MISMATCH', '입력 전체 점군과 저장 좌표 또는 행 순서가 다릅니다.')
    ratio = float(np.count_nonzero(frame.valid_mask) / frame.valid_mask.size)
    require(result['point_cloud']['point_count'] == len(expected), 'RESULT_INVALID', '입력 점 개수가 결과와 다릅니다.')
    require(result['valid_depth_ratio'] == ratio and result['provenance_kind'] == frame.metadata['provenance']['kind'],
            'METADATA_MISMATCH', '처리 결과의 유효 비율 또는 출처가 입력과 다릅니다.')
    return {'status': 'matched', 'session': str(session), 'frame_id': result['frame_id'],
            'metadata_matched': True, 'dtype': str(points.dtype), 'shape': list(points.shape),
            'point_count': len(points), 'row_order_matched': True,
            'comparison': 'numpy.array_equal', 'atol_m': 0, 'rtol': 0,
            'reason': '동일한 float32 기준 함수로 저장·재계산하므로 허용 오차 없이 전체 배열을 비교합니다.'}


def verify_preservation(original_inventory):
    deployed = 0
    for line in (ROOT / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        expected, name = line.split('  ', 1)
        require(digest(ROOT / name) == expected, 'PRESERVATION_MISMATCH', f'배포 원본 변경: {name}')
        deployed += 1
    preserved = None
    if original_inventory:
        initial = json.loads(original_inventory.read_text(encoding='utf-8'))
        for name, expected in initial['files'].items():
            require(digest(ROOT / name) == expected, 'PRESERVATION_MISMATCH', f'착수 파일 변경: {name}')
        preserved = len(initial['files'])
    schema_match = {}
    doc = ROOT / '인지동_최신기준_규격v1.0.0_20261008.md'
    if doc.exists():
        text = doc.read_text(encoding='utf-8')
        for schema in sorted((ROOT / 'schemas').glob('*.schema.json')):
            pattern = r'### injidong_contract_v1/schemas/' + re.escape(schema.name) + r'\s*\x60{3}json\s*(.*?)\s*\x60{3}'
            match = re.search(pattern, text, re.S)
            require(match is not None, 'SCHEMA_INVALID', f'기준 문서에 스키마가 없습니다: {schema.name}')
            schema_match[schema.name] = json.loads(match.group(1)) == json.loads(schema.read_text(encoding='utf-8'))
            require(schema_match[schema.name], 'SCHEMA_INVALID', f'문서·배포 스키마 불일치: {schema.name}')
    return deployed, preserved, schema_match


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, help='points.npz / processing.json / viewer_export.json / preview.png 결과 폴더')
    parser.add_argument('--session', type=Path, help='좌표·metadata를 대조할 실제 입력 세션. 생략하면 파일 무결성만 검사')
    parser.add_argument('--original-inventory', type=Path, help='로컬 착수 파일 보존 검사. 제출 ZIP 밖 파일 포함 가능')
    args = parser.parse_args(argv)
    report = {'status': 'failure', 'bundle': str(args.bundle.resolve()),
              'artifact_validation': {'status': 'not_run'},
              'input_coordinate_validation': {'status': 'not_run', 'reason': '--session 미지정: 입력 좌표 비교를 실행하지 않았습니다.'},
              'coordinates_verified': False, 'errors': []}
    stage = 'artifact_validation'
    try:
        result, audit, points = verify_artifacts(args.bundle.resolve())
        report['artifact_validation'] = {'status': 'passed', 'schema_checked': True, 'output_hashes_matched': True,
                                         'dtype': str(points.dtype), 'shape': list(points.shape), 'point_count': len(points)}
        report['output_hashes_matched'] = True
        if args.session is not None:
            stage = 'input_coordinate_validation'
            report[stage] = {'status': 'running', 'session': str(args.session.resolve())}
            report[stage] = compare_input(result, audit, points, args.session.resolve())
            report['coordinates_verified'] = True
        stage = 'preservation_validation'
        deployed, preserved, schema_match = verify_preservation(args.original_inventory)
        report.update(deployment_hashes_preserved=deployed, initial_files_preserved=preserved,
                      local_summary_schemas_match=schema_match, status='success')
        report['summary'] = ('파일 무결성과 명시한 입력의 전체 좌표·metadata 대조에 성공했습니다.'
                             if report['coordinates_verified'] else '파일 무결성 검사에 성공했습니다. 입력 좌표 비교는 미실행입니다.')
    except (ContractError, OSError, UnicodeError, ValueError, KeyError, TypeError, zipfile.BadZipFile, EOFError) as error:
        code = error.code if isinstance(error, ContractError) else 'INPUT_CORRUPT'
        report[stage] = {'status': 'failed', 'code': code, 'message': str(error)}
        report['errors'].append({'code': code, 'message': str(error)})
        print(f'검증 실패: {code}: {error}', file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())

