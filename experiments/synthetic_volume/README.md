# 합성 높이 적분 실험

알려진 직육면체의 결정적 합성 셀 중심 표본으로 높이 적분 산술과 실패 처리를 검증한다. 실제 촬영본·카메라 점군·찰흙 부피·중량 정확도 검증이나 팀 승인 정책이 아니다. 실제 촬영 입력을 받는 CLI는 없으며 API도 provenance/capture_source가 synthetic인 FramePacket만 허용한다.

## 파일과 의존성

- [synthetic_volume.py](synthetic_volume.py): 기존 적분 함수 `analyze`와 개발 가정·허용치를 유지한 synthetic 전용 API.
- [synthetic_fixtures.py](synthetic_fixtures.py): 기준 template에서 3×2 합성 frame, 알려진 셀 중심 좌표, 가정 생성.
- [run_synthetic_validation.py](run_synthetic_validation.py): 생성→저장→로딩→계산→결과 JSON 재로딩·검증의 8사례 CLI.
- [_boundary.py](_boundary.py): 저장소의 기존 [공통 경계](../../tools/stored_depth_analysis/_common.py)·[baseline 해시](../../tools/mobile_session_intake/baseline_hashes.json)를 정확한 파일 경로로 재사용한다. 이 저장소 구조가 필요하며 실험 폴더 단독 복사본은 지원하지 않는다.
- [tests/test_synthetic_volume.py](tests/test_synthetic_volume.py): 원래 6개 수치/실패 테스트와 이동 후 경계 회귀 테스트5개. 저장형 8사례는 테스트와 겹치므로 고유 사례 수로 합산하지 않는다.
- [requirements.txt](requirements.txt): 직접 의존성 NumPy2.3.5. Python3.11 이상, 검증 환경 Python3.11.9/Windows/NumPy2.3.5. 표준 라이브러리 외 다른 패키지·GUI는 필요하지 않다. 이번 작업에서는 설치하지 않았다.

외부 ADE-71 기준 배포본 `ADE-71_session_fixed_20261014_6fe5b71e259e.zip`은 팀 기준 경로에서 별도로 확보한다. ZIP SHA-256은 `31547e5128b78d0becce9c3414fff9f3e27211dac72d318badaf0a3686a3dddd`다. 출처·압축 경로를 확인하고 코드/출력 밖에 해제한 src/, schemas/, examples/가 바로 있는 루트를 --baseline으로 지정한다. 자동 다운로드/탐색/fallback은 없다. baseline 파일을 실험 폴더에 포함하지 않는다.

기존 manifest의 contract.py/session_boundary.py/frame.schema.json 세 핀을 바꾸지 않는다. 추가로 processing.schema.json=`b5090a9f3a2f294836ca0a318b24fdf4ba2c695045e3f5c531564f5b9bd9e4ae`, 합성 template metadata.json=`806e0df67e2489612be6aabe9af80b3dc84ad08ff62b6804ec59d2ead0ee0bf7`를 검증한다. 실제 contract/session_boundary/공통 경계 모듈 경로를 요약에 기록하며 다른 출처로 이미 로드된 contract/session_boundary는 거부한다. 저장소 src로 fallback하지 않는다. baseline의 제한된 JSON 스키마 검사 범위만 재사용하며 일반 스키마 검증기라고 주장하지 않는다.

## 지원하는 개발 가정과 입력

먼저 API `load_contract(baseline)`을 명시적으로 호출한 뒤 `analyze(frame, points_m, pixel_vu, synthetic_assumptions)`를 사용한다. frame은 기준 `FramePacket`이며 depth_m은 m 단위 float32, valid/target mask는 depth-aligned bool이다. points_m은 별도로 생성한 유한 float64 Nx3 카메라 좌표(m), pixel_vu는 int64 Nx2 [v,u]다. 이 표본은 카메라 역투영 결과가 아니라 치수로 정의한 분석용 좌표다. depth와 표본을 임의 실촬영 입력에 결합하는 adapter는 제공하지 않는다.

지지면 normal/offset, plane basis origin/u/v, footprint, grid_pitch_m은 FramePacket metadata의 support_plane/volume_request에 명시한다. 기존 `volume_preflight`를 먼저 통과해야 한다. 합성 fixture의 assumptions_confirmed/evidence는 알려진 합성 조건의 증거이며 실제 세션의 검증 상태나 팀 승인이 아니다. 별도 known_footprint/entire_top_observed/solid_single_valued_columns/no_cavities_or_overhangs가 모두 bool true여야 한다.

- footprint는 plane u/v에 정렬된 네 꼭짓점 직사각형만 지원한다. 좌하단→우하단→우상단→좌상단 CCW, 닫는 점 반복 없음.
- 명시적인 양의 정사각 셀 pitch, 변마다 정수 개의 셀, 최대10000셀. 정수 비율 허용치1e-10. 부분 셀이나 임의 다각형을 근사하지 않는다.
- 단위 normal과 오른손 직교 basis, plane 위 origin을 추가 절대1e-12(거리 m 또는 무차원)·상대0으로 검사한다.
- footprint/셀은 반열림 [min,max), floor 인덱스다. 셀 중심에서1e-12m 이내 표본만 지원한다. 셀 경계/footprint 경계/외부/비중심을 조용히 이동·삭제하지 않는다.
- 높이는 plane normal 방향의 양의 유한 높이다. 셀별 최대 높이×pitch²를 고정 셀 순서로 math.fsum한다. 점 수를 부피로 환산하지 않는다.
- 모든 셀과 모든 대상 픽셀을 표본이 대표해야 한다. coverage100%만 지원하며 누락·대상 invalid를 높이0으로 채우거나 보간하지 않는다.

기준은 0.02m×0.03m×0.01m = 0.000006m³ = 6cm³, pitch0.01m, 6셀이다. 기대값은 계산기와 독립인 치수 곱이다. 절대 허용치1e-15m³·상대0을 실행 전에 고정하며 자동 확대하지 않는다. float64 투영·높이 차·곱셈·fsum의 반올림을 허용하되 한 셀 누락1e-6m³보다 훨씬 작다. 중복/순서 변경은 부피를 정확히 유지해야 한다. normal 높이를 쓰는 회전·이동 시험도 합성 산술 시험이며 실제 pose/world 변환 검증이 아니다.

누락/invalid는 COVERAGE_INSUFFICIENT, 잘못된 plane/basis는 PLANE_INVALID/PLANE_BASIS_INVALID, 가정 미확인은 VOLUME_ASSUMPTION_REQUIRED로 실패한다. 기타 미지원 조건은 기존 오류 코드를 재사용한다. 실패의 volume_m3/volume_method는 null이며 0을 대체값으로 쓰지 않는다.

## 검증된 실행 명령

저장소 루트의 PowerShell에서 기존 Python과 외부 baseline을 지정한다. 두 출력은 서로 분리된, 아직 존재하지 않는 경로여야 한다. 개인 PC 고정 경로나 외부 start.json이 필요하지 않다.

```powershell
$python = Read-Host '기존 Python 실행 파일 경로'
$baseline = (Resolve-Path (Read-Host '외부 ADE-71 baseline 루트')).Path
$testOutput = Read-Host '코드·baseline 밖의 새 테스트 출력 경로'
& $python -B -X utf8 experiments/synthetic_volume/tests/test_synthetic_volume.py --baseline $baseline --output-root $testOutput
if ($LASTEXITCODE -ne 0) { throw '합성 전용 테스트 실패: 로그 확인' }

$validationOutput = Read-Host '코드·baseline 밖의 새 저장형 검증 출력 경로'
& $python -B -X utf8 experiments/synthetic_volume/run_synthetic_validation.py --baseline $baseline --output-root $validationOutput
if ($LASTEXITCODE -ne 0) { throw '저장형 합성 검증 실패: validation_summary.json 확인' }
```

테스트는 CLI가 생성한 8사례를 내부에서도 실행한다. 위 두 명령 실행 시 저장형 검증은 회귀 내부1회와 독립 CLI1회다. Windows junction 생성 권한이 없으면 해당 회귀 테스트의 skip을 별도로 확인한다. 다른 OS에서도 junction 시험을 제외한 동일 경계를 사용한다. 전체 프로젝트 테스트나 모바일/runner/점군/뷰어를 탐색·실행하지 않는다.

## 저장 형식과 실패

저장형 출력 아래 inputs/사례명/에는 arrays.npz(depth_m float32 H×W, valid_mask/target_mask bool), metadata.json, analytic_top_samples.npz(points_m float64 N×3, pixel_vu int64 N×2), synthetic_assumptions.json을 만든다. pickle 없이 저장/재로딩하며 배열 dtype·shape·전체 값을 정확히 확인한다. 정상 입력은 baseline `load_frame`의 hash/schema/FramePacket 검사를 받는다. 잘못된 plane 사례는 예상한 PLANE_INVALID 로더 거부를 기록하고, 디스크의 실패 fixture를 FramePacket으로 재구성해 원래 `analyze`/`volume_preflight`의 실패·null을 확인한다. 로더 검증을 완화하지 않으며 예상 밖 로더 오류는 검증 실패다.

각 사례 JSON에는 기존 ProcessingResult 계약을 검증한 processing_result와 별도 개발 artifact의 units(distance=m, area=m^2, volume=m^3), diagnostics, 미승인 정책을 담는다. 저장한 결과 JSON을 다시 읽고 기준 `validate_json(...,'processing')`를 수행한다. 정상2사례·음성6사례의 기대 상태/부피 또는 null/오류가 일치하면 validation_summary.json의 validation_status가 passed_synthetic_height_integration_validation이다. 음성 사례의 예상 거부를 성공한 부피 계산으로 표현하지 않는다. 처리 중 예외/보존 불일치는 failed·errors·비0 종료로 남는다. 폴더 예약 전 경계 실패/필수 인자 누락은 JSON 없이 비0으로 종료할 수 있다.

출력은 코드/입력/baseline과 양방향 중첩되지 않는 신규 폴더만 받는다. 기존 엔트리 및 기존 junction/symlink 상위 별칭을 resolve해 거부하며 개별 파일도 exclusive 모드로 쓴다. 기존 결과를 덮어쓰지 않는다. 이 CLI의 입력은 지정 baseline과 생성된 합성 파일뿐이다. 읽은 baseline/코드/생성 입력/사례 결과의 전후 해시는 시점별 비교이며 파일 잠금이 아니다. 상세 JSON과 회귀 로그는 로컬 절대 경로를 포함하므로 공개 후보에 넣지 않는다.

## 한계와 공개 범위

실제 데이터 연결에는 footprint/coverage/격자 pitch/셀 최대값의 잡음 편향·가림·공동/오버행·지지면 근거·실측 허용치를 별도로 결정해야 한다. SDK 보정·65535 정책·RGB 정렬은 미확인이다. 기존 공통 코드·스키마·volume_preflight·ProcessingResult·기존 pipeline의 VOLUME_NOT_IMPLEMENTED는 변경하거나 교체하지 않는다.

geometry_verified / processing_ready / viewer_launched / sdk_values_independently_verified / common_framepacket_fully_validated는 모두 false다. 별도 합성 fixture의 알려진 가정을 실제 세션 준비 상태로 승격하지 않는다.

공개 후보에는 소스/결정적 생성기/테스트/의존성/이 README와 [검증 요약](../../docs/validation/20261017-synthetic-volume/SUMMARY_ko.md)만 포함한다. 실제 입력/raw/RGB/점군/PNG/전송 ZIP/bundle/baseline/venv/cache/인증정보/개인 경로가 담긴 상세 로그는 포함하지 않는다.
