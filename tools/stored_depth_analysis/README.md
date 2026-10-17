# 저장 Depth 배열 점군 대조와 정적 시각화

이 도구는 외부 ADE-71 baseline의 로더·검증·카메라 점군 함수를 재사용하여, 저장된 depth/mask/기록 내참수의 수학적 일치를 검사한다. 시각화는 성공한 대조 결과의 **기존 NPZ**를 읽어 PNG만 저장한다. 실제 처리 승인이나 SDK 보정·물리 정확도 검증이 아니다. SDK·왜곡 보정·65535 의미/정책·RGB 정렬·팀 승인은 미확인이다.

## 파일과 의존성

- [compare_stored_depth.py](compare_stored_depth.py): frame ID 선택, 독립 float64 기대값, 전체 float32 좌표/행/픽셀 대조, raw 대응 보존, NPZ 왕복.
- [make_static_figures.py](make_static_figures.py): 기존 points_m/pixel_vu와 Depth/raw를 읽는 Agg 정적 PNG 생성. 점군 계산/GUI 실행 없음.
- [_common.py](_common.py): 고정 baseline 해시, import 경로, 입력 읽기 기록과 출력 경계.
- [tests/test_stored_array_comparison.py](tests/test_stored_array_comparison.py): 촬영본 없는 합성 및 경계 테스트.
- [requirements.txt](requirements.txt): 직접 사용하는 NumPy, Matplotlib, Pillow만 선언. Python 3.11 이상. 검증 환경은 Python 3.11.9 / NumPy 2.3.5 / Matplotlib 3.10.8 / Pillow 12.3.0, Windows, Agg다. 기존 루트 requirements/lock은 변경하지 않았다. 이번 작업에서 설치·업그레이드는 하지 않았다.

## 외부 ADE-71 baseline

저장소 기본 src를 baseline으로 자동 사용하지 않는다. 팀에서 기준 배포본 `ADE-71_session_fixed_20261014_6fe5b71e259e.zip`을 별도로 확보한다. ZIP SHA-256은 `31547e5128b78d0becce9c3414fff9f3e27211dac72d318badaf0a3686a3dddd`다. 압축 경로/출처를 확인한 뒤 저장소와 입력 밖의 새 폴더에 해제하고 src/, schemas/, examples/가 바로 있는 루트를 명시한다. 이 도구는 ZIP을 다운로드·해제·탐색하지 않는다. 다른 baseline으로 자동 fallback하지 않는다.

기존 [baseline_hashes.json](../mobile_session_intake/baseline_hashes.json)의 3항목을 그대로 사용한다.

| 파일 | SHA-256 |
|---|---|
| src/contract.py | c013de55d34120076fd899c8797ffaa38675201c011e16ab2c39dfd0f6c6897e |
| src/session_boundary.py | b52fed283cf78f33f0e8192ff270dcd90050083a1fc83dc99bfd3e7b9f4662d4 |
| schemas/frame.schema.json | b277100a2d5a8ac6052a3dcbb8e6bcdc56da9e23a656c2aa50e5d91475b190ea |

통과시키려고 목록·외부 코드·스키마를 바꾸면 안 된다. 실제 import된 contract/session_boundary 경로를 대조 JSON에 기록한다. 이미 로드된 같은 이름 모듈이 다른 경로면 거부한다. bytecode 캐시 대신 지정한 원본 소스를 __file__/ROOT가 유지된 모듈 spec에 로드하며 기존 함수를 교체하지 않는다. 공통 스키마 검사는 해당 배포본의 제한 검사기 범위다.

## 합성 테스트만 실행

아래 예시는 **저장소 루트**에서 PowerShell로 실행한다. 실제 촬영본이 필요 없다. 출력은 기존에 없는 경로여야 하고 입력·baseline·저장소와 양방향으로 겹치면 안 된다.

```powershell
$python = Read-Host '기존 Python 실행 파일 경로'
$baseline = (Resolve-Path (Read-Host '외부 ADE-71 baseline 루트')).Path
$testOutput = Read-Host '입력·baseline·저장소 밖의 새 테스트 출력 경로'
& $python -B -X utf8 tools/stored_depth_analysis/tests/test_stored_array_comparison.py --baseline $baseline --output-root $testOutput
if ($LASTEXITCODE -ne 0) { throw '합성 검증 실패: 출력 로그 확인' }
```

이 명령은 비대칭 내참수·invalid 픽셀의 알려진 좌표, 좌표/행 변조 검출, NPZ 왕복을 검사한다. 추가로 합성 raw/metadata 세션을 출력 폴더에 만들고 두 CLI를 실행해 해시·import 충돌·기존/중첩 출력·Windows junction 별칭·실패 보고 경계를 확인한다. 기존 전체 프로젝트 테스트나 모바일 검사기를 발견/실행하지 않는다. Windows junction 생성이 불가능한 환경은 해당 검사를 skip으로 구분한다. 정적 합성 PNG 검사에는 설치된 한글 글꼴이 필요하다(아래 글꼴 설명 참조).

## 저장된 세션 대조

필수 인자: `--baseline`, `--session`, `--frame-id`, `--expected-valid-count`, `--expected-raw65535-count`, `--output`. 외부 start.json이나 특정 PC 폴더는 필요 없다. 기대 개수는 독립된 기존 근거에서 정해 명시하며 실행 후 실패를 통과시키려고 바꾸지 않는다.

```powershell
$session = (Resolve-Path (Read-Host 'frames.jsonl이 바로 있는 세션 루트')).Path
$frameId = Read-Host 'manifest에서 선택할 frame ID'
$expectedValid = [int](Read-Host '사전에 확인한 유효점 수')
$expectedRaw65535 = [int](Read-Host '사전에 확인한 raw 65535 수')
$comparisonOutput = Read-Host '입력·baseline·저장소 밖의 새 대조 출력 경로'
& $python -B -X utf8 tools/stored_depth_analysis/compare_stored_depth.py --baseline $baseline --session $session --frame-id $frameId --expected-valid-count $expectedValid --expected-raw65535-count $expectedRaw65535 --output $comparisonOutput
if ($LASTEXITCODE -ne 0) { throw '대조 실패: 성공으로 취급하지 말 것' }
```

선택은 frames.jsonl의 유일한 frame_id와 metadata의 frame_id로 한다. 현재 지원하는 입력은 m 단위 optical_axis_z float32 depth, bool valid_mask, rectified_pinhole 기록과 프레임별 raw_capture.json/원본 Z16이다. raw는 sidecar의 little-endian uint16·stride·해시로 읽는다. raw×기록 scale과 저장 배열의 같은 인덱스 관계를 대조할 수 있어야 하며 remapping/역왜곡을 수행하지 않는다. 다른 raw 배치나 보정 결과 매핑은 조용히 근사하지 않는다.

독립 기대값은 원래 구현의 v-다음-u 이중 순회와 float64 뺄셈→곱셈→나눗셈 그대로다. `rtol=0`, 좌표별 `0.5*abs(spacing(reference64.astype(float32)).astype(float64))` 이내를 요구한다. 이는 기존 float64 중간값의 마지막 float32 반올림 기준이다. 최종 float32 기대 배열과의 **정확 일치** 및 원본 픽셀/행 순서/Z 일치도 별도로 필수 검사한다. 허용 오차 확대나 거리 필터는 없다.

출력은 `analysis_points.npz`(float32 Nx3 points_m, int64 Nx2 pixel_vu=[v,u])와 `stored_array_comparison.json`이다. NPZ는 allow_pickle=False로 재로딩하고 전체 배열/해시를 대조한다. 65535 샘플을 제거·클리핑·무효화하지 않는다. 실패는 별도 analysis_status와 errors로 남기며 성공 보고를 게시하지 않는다. 출력 경계 거부처럼 폴더 예약 전 실패는 보고서 없이 비0으로 종료할 수 있다. 상세 JSON에는 로컬 경로·입력 metadata·raw 대응 정보가 있으므로 자동 공개하면 안 된다.

## 기존 점군의 정적 PNG

필수 인자: `--session`, `--frame-id`, `--pointcloud`, `--comparison-report`, `--output`. 선택 인자: `--max-display-points`(기본50000), `--font-family`(기본 Malgun Gothic). 지정한 pointcloud 바이트 SHA-256과 입력 파일들이 성공한 대조 보고서에 결합돼 있는지 확인한다. 원본의 위치를 자동 탐색하거나 다른 결과로 대체하지 않는다.

```powershell
$figureOutput = Read-Host '입력·baseline·코드·점군/보고서 폴더와 분리된 새 PNG 출력 경로'
& $python -B -X utf8 tools/stored_depth_analysis/make_static_figures.py --session $session --frame-id $frameId --pointcloud (Join-Path $comparisonOutput 'analysis_points.npz') --comparison-report (Join-Path $comparisonOutput 'stored_array_comparison.json') --output $figureOutput --max-display-points 50000 --font-family 'Malgun Gothic'
if ($LASTEXITCODE -ne 0) { throw '정적 시각화 실패: 출력 로그 확인' }
```

설치된 한글 글꼴만 사용한다. 글꼴을 찾지 못하면 실패하며 다운로드나 다른 글꼴로 숨겨서 대체하지 않는다. 다른 OS에서는 해당 환경에 이미 설치된 한글 글꼴명을 --font-family로 지정한다. 현재 합성 테스트의 렌더링 사례는 기본 Malgun Gothic을 사용하므로 그 글꼴이 없는 환경에서는 렌더링 검증이 실패할 수 있다. Matplotlib 설정/글꼴 캐시는 새 PNG 출력의 .matplotlib_cache 안에만 생성한다.

생성물은 depth.png, raw65535_locations.png, pointcloud.png, visualization_results.json이다.

- Depth는 유효값 전체 색상 범위와 회색 invalid를 표시한다. 보조 패널은 상위98백분위까지 색상만 표시하며 배열 클리핑/제거가 아니다. 상수 깊이 합성 입력은 색상바의 특이 구간 방지를 위해 표시 상한만 작은 폭으로 넓히고 그 범위를 기록한다.
- raw 65535는 정확한 raw 값에서 찾은 위치를 자홍색으로 표시하고 의미 미확정을 명시한다. 대응 샘플은 전부 포함한다.
- 점군은 기존 저장 points_m을 사용한다. 행 번호 linspace(0,N-1,min(표시상한,N))와 raw 대응 행 전체의 합집합을 정렬해 결정적으로 표시한다. 따라서 표시 수가 기본 상한보다 조금 많을 수 있다. 원본 데이터/valid_mask는 변경하지 않는다.
- 카메라 X 오른쪽·Y 아래·Z 전방, m 단위다. 화면에는 X/깊이 Z/수직 Y를 배치하고 Y축 눈금만 뒤집는다. 전체 점 bbox+5% 여백, 정사영, elevation18°/azimuth-68°/roll0°, 범위 비례 box aspect로1m 단위 축척을 맞춘다. 가림/투영 축 단축/표본 생략으로 세부 형상을 확정할 수 없다. Z 색상이며 RGB 색상이나 정렬 결과가 아니다.

## 보호·공개·한계

출력은 입력·baseline·코드·기존 점군/보고서 폴더와 분리된 **새 경로**다. 같은 경로/양방향 중첩/기존 엔트리를 거부하며 Path.resolve로 기존 junction/symlink 상위 별칭을 확인한다. 기존 출력을 덮어쓰지 않는다. 읽은 프로젝트 파일의 시작/종료 SHA-256을 보고한다. 이는 시점별 대조이며 파일 잠금이 아니다.

원래 계산·시각화 스크립트에서 이동한 범위와 검증 결과는 [수치 요약](../../docs/validation/20261017-stored-depth/SUMMARY_ko.md)에 있다. 공개용 변경에는 코드·합성 fixture 생성 로직·의존성·수치 요약만 포함한다. 실제 raw/RGB/Depth 세션/전체 점군 NPZ/원본 로그/실제 파생 PNG와 상세 JSON은 공개 가능성을 확정할 수 없어 제외했다. 원본은 삭제/수정하지 않았다. 원본 보고서의 개인 절대 경로·카메라 식별정보·샘플별 상세 대응은 공개 요약에 옮기지 않았다. 이는 원본에 비밀이 있었다는 판정이 아니며 공개 데이터 범위를 제한한 것이다.

geometry_verified / processing_ready / viewer_launched / sdk_values_independently_verified / common_framepacket_fully_validated는 항상 false다. 정적 PNG는 GUI 뷰어 실행이 아니다. 이번 도구는 기존 runner의 실제 처리 차단이나 팀 정책을 해제하지 않는다. 물리 거리·보정·RGB 정렬·합성 부피·중량 정확도를 검증하지 않는다.
