"""ADE-66: 저장 세션을 매회 새로 읽어 값·계산·출처·원본 보존을 검증한다."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from contract import ROOT, ContractError, _inside, fail, iter_frames, point_cloud_camera

KST = timezone(timedelta(hours=9))
EXPECTED_ATOL_M = 1e-7


def file_hashes(session):
    """내용 변경과 파일 추가/삭제 확인용. 라벨을 해시해도 추론 입력으로 읽지는 않는다."""
    return {
        path.relative_to(session).as_posix(): hashlib.sha256(
            _inside(session, path.relative_to(session)).read_bytes()).hexdigest()
        for path in sorted(session.rglob('*')) if path.is_file()
    }


def compare_frame(reference, current):
    frame_id = reference.metadata['frame_id']
    for name in ('depth_m', 'valid_mask', 'target_mask'):
        left, right = getattr(reference, name), getattr(current, name)
        if left is None and right is None:
            continue
        if (left is None or right is None or left.shape != right.shape
                or left.dtype != right.dtype or not np.array_equal(left, right)):
            fail('INPUT_CORRUPT', f'{frame_id}: {name} 반복 간 불일치')
    # 별도 생성한 재생 시각은 이 metadata에 넣지 않는다. 원본의 모든 필드 비교.
    for name in reference.metadata.keys() | current.metadata.keys():
        if reference.metadata.get(name) != current.metadata.get(name):
            fail('INPUT_CORRUPT', f'{frame_id}: metadata.{name} 반복 간 불일치')


def verify_replay(session_dir, repeats, expected_points=None):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('반복 횟수는 양의 정수여야 합니다.')
    session = Path(session_dir).resolve()
    record = {
        'tool_version': 'ade-66-replay-v1', 'session': str(session),
        'started_at': datetime.now(KST).isoformat(), 'timezone': 'Asia/Seoul',
        'requested_repeats': repeats, 'completed_repeats': 0, 'status': 'failure',
        'frame_count': 0, 'frame_ids': [], 'frames': [], 'iterations': [],
        'array_comparison': 'dtype/shape 일치 및 numpy.array_equal; 허용 오차 0',
        'point_cloud_replay_comparison': 'numpy.array_equal; 허용 오차 0',
        'metadata_comparison': '원본 metadata 전체 동등 비교; 실행 replay_time은 별도 기록',
        'expected_points_comparison': {'method': 'numpy.allclose', 'rtol': 0,
                                       'atol_m': EXPECTED_ATOL_M,
                                       'checked': False, 'matched': None},
        'hashes_before': {}, 'hashes_after': {}, 'original_files_unchanged': None,
        'errors': [],
    }
    baseline = None
    baseline_clouds = None
    snapshot_taken = False
    try:
        record['hashes_before'] = file_hashes(session)
        snapshot_taken = True
        for repeat in range(1, repeats + 1):
            iteration = {'repeat': repeat, 'frames': []}
            current = []
            # iter_frames -> load_frame의 checksum/schema/shape/dtype 검증 재사용.
            for frame in iter_frames(session):
                current.append(frame)
                iteration['frames'].append({
                    'frame_id': frame.metadata['frame_id'],
                    'replay_time': {'ns': str(time.time_ns()), 'clock_domain': 'pc_unix_utc',
                                    'origin': 'replay_host'},
                })
            record['iterations'].append(iteration)
            if not current:
                fail('MANIFEST_INVALID', 'frames.jsonl에 재생할 frame이 없습니다.')
            if baseline is not None:
                ids = [f.metadata['frame_id'] for f in current]
                if ids != record['frame_ids']:
                    fail('MANIFEST_INVALID', f'반복 {repeat}: frame_count/frame_id 순서 불일치: {ids}')
                for reference, frame in zip(baseline, current):
                    compare_frame(reference, frame)
            clouds = [point_cloud_camera(frame) for frame in current]
            if baseline is None:
                baseline, baseline_clouds = current, clouds
                record['frame_ids'] = [f.metadata['frame_id'] for f in baseline]
                record['frame_count'] = len(baseline)
                record['provenance_kinds'] = sorted({f.metadata['provenance']['kind'] for f in baseline})
                record['synthetic_notice'] = ('합성 데이터 포함; 실측/중량 정확도 결과가 아닙니다.'
                                              if 'synthetic' in record['provenance_kinds']
                                              else '입력은 real로 표기됨; 장비/실측 승인 여부는 별도 확인 필요.')
                for frame, points in zip(baseline, clouds):
                    record['frames'].append({
                        'frame_id': frame.metadata['frame_id'],
                        'capture_time': frame.metadata['capture_time'],
                        'capture_source': frame.metadata['capture_source'],
                        'provenance': frame.metadata['provenance'],
                        'original_replay_time': frame.metadata['replay_time'],
                        'depth_shape': list(frame.depth_m.shape), 'depth_dtype': str(frame.depth_m.dtype),
                        'valid_mask_dtype': str(frame.valid_mask.dtype),
                        'has_target_mask': frame.target_mask is not None,
                        'point_count': len(points), 'points_m': points.tolist(),
                    })
                if expected_points is not None:
                    expected = np.asarray(expected_points, dtype=np.float64)
                    if len(clouds) != 1 or expected.shape != clouds[0].shape or not np.isfinite(expected).all():
                        fail('RESULT_INVALID', '기대 좌표는 단일 frame의 유한한 N×3 좌표와 크기가 같아야 합니다.')
                    comparison = record['expected_points_comparison']
                    comparison['checked'] = True
                    comparison['matched'] = bool(np.allclose(clouds[0], expected, rtol=0, atol=EXPECTED_ATOL_M))
                    comparison['max_abs_error_m'] = float(np.max(np.abs(clouds[0] - expected)))
                    if not comparison['matched']:
                        fail('RESULT_INVALID', 'Point Cloud 기대 좌표 불일치 (rtol=0, atol=1e-7 m)')
            else:
                for frame, left, right in zip(current, baseline_clouds, clouds):
                    if left.dtype != right.dtype or left.shape != right.shape or not np.array_equal(left, right):
                        fail('RESULT_INVALID', f'{frame.metadata["frame_id"]}: points_m 반복 간 불일치')
            record['completed_repeats'] += 1
    except ContractError as error:
        record['errors'].append({'code': error.code, 'message': str(error)})
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        # 기존 로더가 ContractError로 분류하지 않은 I/O/JSON 오류의 실제 타입을 보존.
        record['errors'].append({'code': None, 'exception_type': type(error).__name__, 'message': str(error)})
    finally:
        if snapshot_taken:
            try:
                record['hashes_after'] = file_hashes(session)
                record['original_files_unchanged'] = record['hashes_before'] == record['hashes_after']
                if not record['original_files_unchanged']:
                    changed = sorted(name for name in record['hashes_before'].keys() | record['hashes_after'].keys()
                                     if record['hashes_before'].get(name) != record['hashes_after'].get(name))
                    record['errors'].append({'code': 'INPUT_CORRUPT',
                                             'message': f'검증 전후 파일 SHA-256 불일치: {changed}'})
            except (ContractError, OSError) as error:
                record['errors'].append({'code': getattr(error, 'code', None),
                                         'exception_type': type(error).__name__, 'message': str(error)})
        record['finished_at'] = datetime.now(KST).isoformat()
    if not record['errors'] and record['completed_repeats'] == repeats:
        record['status'] = 'success'
    return record


def positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('반복 횟수는 양의 정수여야 합니다.') from error
    if number < 1:
        raise argparse.ArgumentTypeError('반복 횟수는 양의 정수여야 합니다.')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--repeat', type=positive_int, default=1, help='세션 재독 횟수; 첫 회가 기준 반복')
    parser.add_argument('--expected-points', type=Path, help='단일 frame 기대 좌표 JSON; rtol=0, atol=1e-7 m')
    parser.add_argument('--report', type=Path, help='새 UTF-8 기록 파일; 생략 시 logs에 자동 생성')
    args = parser.parse_args(argv)
    report_path = (args.report or ROOT / 'logs' / f'replay_{time.time_ns()}.json').resolve()
    try:
        if report_path.is_relative_to(args.session.resolve()):
            fail('PATH_INVALID', '실행 기록 경로는 입력 세션 밖이어야 합니다.')
        expected = None
        if args.expected_points:
            expected = json.loads(args.expected_points.read_text(encoding='utf-8'))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        # 이미 있는 사용자 파일은 절대 덮어쓰지 않는다.
        with report_path.open('x', encoding='utf-8') as stream:
            record = verify_replay(args.session, args.repeat, expected)
            record['expected_points_file'] = str(args.expected_points.resolve()) if args.expected_points else None
            json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except (ContractError, OSError, json.JSONDecodeError, UnicodeError) as error:
        print(f'실패: {type(error).__name__}: {error}', file=sys.stderr)
        return 1
    if record['status'] == 'success':
        print(f'성공: {record["completed_repeats"]}회 / 매회 {record["frame_count"]} frame / {record["frame_ids"]}')
        print(record['synthetic_notice'])
        for frame in record['frames']:
            print(f'{frame["frame_id"]}: point_count={frame["point_count"]}, points_m={frame["points_m"]}')
        print('배열·메타데이터·Point Cloud 동일, 원본 시각·출처 보존, 전후 SHA-256 동일')
        if record['expected_points_comparison']['checked']:
            print('기대 좌표 일치: numpy.allclose(rtol=0, atol=1e-7 m)')
    else:
        for error in record['errors']:
            print(f'실패: {error["code"] or error.get("exception_type")}: {error["message"]}', file=sys.stderr)
    print(f'실행 기록: {report_path}')
    return 0 if record['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
