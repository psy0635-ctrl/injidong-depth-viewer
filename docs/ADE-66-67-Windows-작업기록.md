# ADE-66·ADE-67 Windows 로컬 구현·검증 기록

작성일: 2026-10-07 / 시간대: Asia/Seoul (UTC+09:00)

## A. 결론과 범위

저장 프레임의 반복 재생 CLI, 기존 전처리의 미검증 경계 확인, Windows 실행 로그와 인수인계 문서를 완료했다. 기존 기준 코드의 오류는 이번 검증에서 재현되지 않았으므로 `src/contract.py`를 수정하지 않았다. 제공 합성 세션을 **총 100회 새로 읽어** 배열·원본 메타데이터·카메라 좌표 Point Cloud의 동일성과 파일 보존을 확인했다.

이는 로컬 합성 데이터에 대한 ADE-66·67 작업 결과다. 팀장 검토·공식 저장소 통합·실기기 승인은 아직 완료되지 않았다. ADE-54·55 전체 완료나 최종 부피·중량 추정 완료를 의미하지 않는다. 100회는 이번 요청의 재현성 점검 조건이며 팀 공식 성능 기준이 아니다.

카메라 SDK·실제 캡처·휴대폰 USB·로봇팔 제어·실제 부피 계산·중량 학습 모델·실측 정확도 평가·공통 스키마 변경·Android 앱/서버/UI는 후속 범위다.

## B. 실제 환경과 설치 상태

| 항목 | 이번 실행에서 확인한 값 |
|---|---|
| OS | Windows, `platform.platform() = Windows-10-10.0.26200-SP0` |
| Python | 3.11.9, MSC v.1938 64 bit (AMD64) |
| 실행 파일 | `C:\study\injidong_contract_v1\.venv\Scripts\python.exe` |
| NumPy | 2.3.5 |
| 작업 폴더 | `C:\study\injidong_contract_v1` |
| 설치 목록 | numpy 2.3.5 / pip 24.0 / setuptools 65.5.0 |
| Git / AGENTS.md | Git 미설정 / 적용되는 AGENTS.md 없음 |

OS 문자열은 Python의 실제 보고값을 그대로 기록했다. 이를 제품명이나 Windows 에디션으로 추정하지 않는다. 기존 `.venv`를 그대로 사용했고, 생성·삭제·재설치·pip 업데이트·추가 라이브러리 설치는 하지 않았다. `requirements.txt`는 `numpy==2.3.5`이며 확인한 설치 상태와 일치한다. pip의 업데이트 안내는 출력 기록일 뿐 실제 업데이트를 수행한 것이 아니다.

이 PC에서는 새 설치 없이 아래 실행 명령을 사용하면 된다. 별도 PC의 최초 설치가 필요할 때만 **Python 3.11/3.12로 새 가상환경을 만들고 그 가상환경 Python으로** `-m pip install -r requirements.txt`를 수행한다. 별도 PC의 설치·실행은 이번에 검증하지 않았다. 기본 등록 Python 3.14에 의존하지 않는다.

### 기존 기록과 이번 실행의 구분

- 사용자 전달 기록: 가상환경 생성·requirements 설치 성공, 제공 unittest 28개 통과, 합성 예제 1 frame·3 point 성공. 직접 재실행한 결과와 구분하여 `logs/original_inventory.json`의 `user_report`에 보존했다.
- 배포본 `VALIDATION.md`: Linux / Python 3.12.14 검증 기록이다. 해당 파일을 수정하거나 Windows 결과로 덮어쓰지 않았다.
- 이번 에이전트 실행: Windows / Python 3.11.9 / NumPy 2.3.5에서 실제 실행한 명령·출력·종료 코드가 아래 로그에 있다.

## C. 제공 코드 분석과 변경 파일

요청된 README, VALIDATION, requirements, contract와 기존 테스트, 스키마 5개, 합성 manifest/metadata, 기대 좌표, SHA256SUMS를 읽었다. 스키마는 입력·처리 결과·특징·예측·실측 라벨을 분리한다. 기존 구조 검사는 배포본에서 사용하는 JSON Schema 키워드만 지원하며 일반적인 모든 JSON Schema 기능을 지원하는 검사기는 아니다.

### 재사용한 함수

| 기존 함수 | 코드에서 확인한 역할 / 이번 활용 |
|---|---|
| `normalize_depth` | 명시적 양의 유한 scale, optical_axis_z, H×W 숫자 배열 확인; float32 m 변환; 무효 픽셀 0·mask=false. 경계 테스트에서 직접 재사용 |
| `load_frame` | metadata 스키마, NPZ 경로 제한·SHA-256·배열 key·pickle 금지, validate_frame 호출. iter_frames를 통해 매회 실행 |
| `iter_frames` | frames.jsonl의 두 필드, ID 중복·manifest/metadata ID 일치·세션 내부 경로 검증. 매회 새로 호출 |
| `validate_frame` | depth/mask dtype·shape·값·유효 Depth 존재·Depth 내참수·시간·출처·target_mask 등 의미 검증. 기존 로더와 Point Cloud 경로에서 재사용 |
| `point_cloud_camera` | validate_frame 후 유효 픽셀을 행 우선 순서로 카메라 N×3 float32 좌표로 변환 |
| `_inside` | 기준 코드의 경로 제한을 파일 해시 검사에서도 재사용 |

기존 로드·정규화·NPZ 검증·좌표 계산을 복제하지 않았다. 기존 테스트 28개도 내용 변경 없이 유지했다.

| 추가 파일 | 내용과 목적 |
|---|---|
| `src/replay.py` | 세션/횟수 인자, 반복 직접 비교, 선택 기대 좌표 검사, 전후 SHA-256, 별도 재생 시각, 한국어 출력, 실패 종료 코드, 기존 파일 덮어쓰기 방지 |
| `tests/test_replay.py` | 추가 10개: CLI 성공/실패, target_mask·여러 frame, 배열·출처·좌표 변경, 수/순서 변경, 파일 변경, 기록 보존, 인자 검사, 예상 밖 예외 전파 |
| `tests/test_preprocessing_boundaries.py` | 추가 4개: Infinity·overflow·sentinel, 잘못된 scale, 원본 배열 경계, 전부 무효인 정규화와 프레임 거부 구분 |
| `scripts/record_run.py` | 같은 프로젝트 Python으로 명령 실행; 환경·명령·stdout·stderr·종료 코드를 새 UTF-8 JSON으로 저장 |
| 이 문서 | 결과·재현 명령·인수인계·미검증 범위 |
| `logs/`의 새 JSON | 이번 실행과 원본 보존의 근거 |

README·VALIDATION·기준 contract·기존 테스트·requirements·스키마·examples·SHA256SUMS는 모두 변경하지 않았다.

## D. 검증 결과

### 테스트와 실행

| 검증 | 실제 결과 |
|---|---|
| 수정 전 제공 테스트 | 28개 통과 / 실패 0 / 종료 코드 0 |
| 제공 예제 | frame_id=synthetic_000001 / provenance_kind=synthetic / point_count=3 / 종료 코드 0 |
| 최종 전체 테스트 | 기존 28 + 추가 14 = **42개 통과** / 실패 0 / 종료 코드 0 |
| 추가 테스트 구성 | 재생 10 + 전처리 경계 4; subTest 반복을 별도 unittest 개수로 세지 않음 |
| 합성 세션 반복 재생 | **100/100회 성공**, 매회 1 frame, 총 100번 세션 재독 / 종료 코드 0 |
| 기대 좌표 | 3개 일치; 최대 절대 오차 `2.2351741811588166e-10 m` |
| 원본 시각·출처 | capture_time, capture_source, provenance 모두 기준 반복과 일치 |
| 합성 세션 원본 | frames.jsonl·metadata.json·arrays.npz 3개 전후 SHA-256 동일 |
| 배포 체크섬 | 작업 시작 시 SHA256SUMS의 21/21개 항목 일치 |
| 작업 전체 원본 | 시작 시 목록의 **22/22개 파일 그대로 유지** (SHA256SUMS 파일 자체 포함) |
| 실패 CLI 실행 | 임시 복사본에서 14개 시나리오 모두 기대 오류·종료 코드·원본 보존 확인 |
| git diff --check | 해당 없음: Git 저장소가 아님 |

100회 재생 기록의 시각: `2026-10-07T18:22:27.857537+09:00` ~ `2026-10-07T18:22:28.026225+09:00`. 이 시각 차이는 이번 소형 합성 샘플 실행 기록이며 성능 보장이나 공식 벤치마크가 아니다.

배열과 반복 Point Cloud는 `dtype/shape 일치 + numpy.array_equal`로 **허용 오차 없이 실제 값**을 비교한다. 기준 반복은 첫 번째 읽기다. 이후 99회와 비교하여 전체 읽기 횟수가 100회가 되도록 했다. frame 수와 ID 순서가 다르면 실패한다. target_mask는 양쪽 없음/존재 여부와 실제 배열 값을 모두 검사한다. target_mask·여러 frame 시나리오는 임시 복사본으로 검증했다. 제공 원본에는 target_mask가 없다.

기대 좌표 비교만 `numpy.allclose(actual, expected, rtol=0, atol=1e-7)`를 적용했다. float32의 0.01 표현 오차를 허용하는 명시적 절대 오차이며 단위는 m다. 반복 간 차이를 이 허용 오차로 숨기지 않는다.

### 전처리와 실패 사례

| 사례 | 검증 결과 / 실제 오류 코드 |
|---|---|
| 1000mm × 0.001 | 1m, float32 / 기존 테스트 통과 |
| 0·음수·NaN·±Infinity, 유효/무효 혼합 | 무효 0·bool false; 유효값만 유지 / 기존+추가 테스트 통과 |
| float32 범위를 초과하는 변환 | 무효 0·false로 정규화 / 추가 테스트 통과 |
| 원본 sentinel 65535 지정 | invalid_values에 명시한 값은 무효 / 추가 테스트 통과 |
| 모든 픽셀 무효 | normalize_depth는 0·false 반환, validate_frame은 `NO_VALID_DEPTH` / 추가 테스트 및 CLI 종료 1 |
| 변환 계수 None | `UNIT_UNKNOWN` / 기존 테스트 통과 |
| 변환 계수 0·음수·NaN·±Infinity·bool·문자열 | `UNIT_UNKNOWN` / 추가 테스트 통과 |
| 빈 배열·1차원·3차원·문자열·bool 원본 | `DEPTH_SHAPE_INVALID` / 추가 테스트 통과 |
| 정규화된 depth/mask 크기 불일치 | `DEPTH_SHAPE_INVALID` / 기존 테스트 및 CLI 종료 1 |
| depth float64 또는 valid_mask uint8 | `DEPTH_DTYPE_INVALID` / 테스트 및 CLI 종료 1 |
| 무효 mask 위치의 depth가 양수 | `DEPTH_VALUES_INVALID` / 기존 테스트 및 CLI 종료 1 |
| Depth profile과 내참수 크기 불일치 | `INTRINSICS_INVALID` / 기존 테스트 및 CLI 종료 1 |
| ray distance를 Z로 선언 | `SEMANTICS_UNSUPPORTED` / 기존 테스트 통과 |
| NPZ checksum 불일치 | `INPUT_CORRUPT` / 기존 테스트 및 CLI 종료 1 |
| 세션 밖 metadata 경로 | `PATH_INVALID` / 기존 테스트 및 CLI 종료 1 |
| 빈 세션 또는 ID 중복 | `MANIFEST_INVALID` / CLI 종료 1 |
| 기대 Point Cloud 불일치 | `RESULT_INVALID` / 추가 테스트 및 CLI 종료 1 |
| 반복 수 0·음수·비정수 | argparse 사용 오류 / 종료 2 |
| 깨진 JSON / 배열 파일 없음 | 원래 `JSONDecodeError` / `FileNotFoundError` 타입 유지 / 종료 1 |
| 예상하지 못한 RuntimeError | 성공·0 값으로 바꾸지 않고 전파 / 추가 테스트 통과 |

계약 오류는 기존 ContractError의 code를 그대로 기록한다. 기준 로더가 ContractError로 분류하지 않는 I/O/JSON 오류는 `code=null`, `exception_type`에 실제 타입을 기록한다. 원인과 다른 계약 코드로 바꾸지 않는다. 예상 밖 예외는 traceback과 비정상 종료로 드러나며 이 경우 구조화 replay 보고서는 불완전할 수 있다. 바깥 `record_run.py`의 stdout/stderr/종료 코드 로그를 확인한다.

SDK/profile에서 확인한 변환 계수를 **명시적 함수 인자**로 전달한다. dtype으로 단위를 추정하지 않는다. mm raw를 이미 m인 저장 배열에 재적용하지 않는다. 무효 픽셀을 정규화하는 단계와 잘못된 정규화 입력을 거부하는 단계를 구분했다.

내참수는 Depth profile의 값으로 사용한다. RGB 보정값과 실제 Depth 보정값의 장비별 일치 여부는 소프트웨어의 크기 검증만으로 증명할 수 없으며 실제 장비 확인이 남아 있다.

## E. PowerShell 사용 방법

아래 명령은 프로젝트 Python과 UTF-8 옵션을 명시한다. 실제 검증에서 실행한 명령이다. 로그 이름은 자동 생성하므로 다시 실행해도 기존 로그를 덮어쓰지 않는다.

```powershell
Set-Location -LiteralPath 'C:\study\injidong_contract_v1'

# 설치 상태 확인 (설치나 업데이트를 수행하지 않음)
& .\.venv\Scripts\python.exe -X utf8 scripts/record_run.py --label installed_packages -- -m pip list

# 제공 예제 실행
& .\.venv\Scripts\python.exe -X utf8 scripts/record_run.py --label baseline_example -- src/contract.py examples/synthetic

# 기존+추가 총 42개 테스트 실행
& .\.venv\Scripts\python.exe -X utf8 scripts/record_run.py --label final_tests -- -m unittest discover -s tests -v

# 합성 세션 100회 재독, 기대 좌표 검증, stdout/stderr/환경 및 상세 재생 기록 저장
& .\.venv\Scripts\python.exe -X utf8 scripts/record_run.py --label replay_100 -- src/replay.py examples/synthetic --repeat 100 --expected-points examples/results/expected_points.json
```

최초 baseline은 새 테스트를 추가하기 전에 `discover -s tests -v`로 실행하여 당시 제공 테스트 28개만 수행했다. 현재 위 전체 테스트 명령은 기존 28개와 추가 14개를 함께 수행한다. 최초 baseline의 실제 명령과 결과는 baseline_tests 로그에 보존했다.

입력 예시:

```text
examples/synthetic/frames.jsonl
  {"frame_id":"synthetic_000001","metadata_path":"frame_000001/metadata.json"}
examples/synthetic/frame_000001/metadata.json
examples/synthetic/frame_000001/arrays.npz
```

정상 출력 예시 (이번 실제 출력):

```text
성공: 100회 / 매회 1 frame / ['synthetic_000001']
합성 데이터 포함; 실측/중량 정확도 결과가 아닙니다.
synthetic_000001: point_count=3, points_m=[[0.0, 0.0, 1.0], [0.009999999776482582, 0.0, 1.0], [0.0, 0.009999999776482582, 1.0]]
배열·메타데이터·Point Cloud 동일, 원본 시각·출처 보존, 전후 SHA-256 동일
기대 좌표 일치: numpy.allclose(rtol=0, atol=1e-7 m)
```

기록의 핵심 필드:

```json
{
  "status": "success",
  "requested_repeats": 100,
  "completed_repeats": 100,
  "frame_count": 1,
  "frame_ids": ["synthetic_000001"],
  "original_files_unchanged": true
}
```

각 `iterations[].frames[].replay_time`에는 실행 시각을 ns **문자열**, `clock_domain=pc_unix_utc`, `origin=replay_host`로 기록한다. 원본 capture_time은 `ns=1000000000`, `clock_domain=synthetic_reference`, `origin=synthetic` 그대로다. 입력 metadata에 실행 replay_time을 대입하지 않는다. 기존 metadata의 replay_time도 전체 메타데이터 비교에 포함하여 보존한다.

`pc_unix_utc`는 재생 PC의 시스템 벽시계에서 `time.time_ns()`로 얻은 **Unix epoch (1970-01-01T00:00:00Z) 이후 ns**를 의미한다. 센서 시계나 monotonic 시계가 아니다. `origin=replay_host`는 재생 호스트에서 기록했다는 출처다. 시스템 시계는 조정될 수 있으므로 ns 표현을 단조 증가 또는 ns 정확도 보장으로 해석하지 않는다. 이번 환경의 `time.get_clock_info('time')` 보고값은 implementation=`GetSystemTimeAsFileTime()`, monotonic=false, adjustable=true, resolution=0.015625초다. capture_time·host_receive_time은 원래 필드로 유지하고 실행 재생 시각으로 대체하지 않는다.

입력 동일성 비교에 사용하는 프레임에는 **이번 실행에서 생성한 replay_time을 넣지 않는다**. 따라서 별도 실행 기록의 시각 100개는 동일성 비교 대상에서 제외된다. 원본 파일에 이미 저장된 replay_time은 원본 메타데이터 보존 확인 대상으로 유지한다.

원하는 별도 기록 경로는 CLI의 `--report`로 지정할 수 있다. 경로는 입력 세션 밖의 **새 파일**이어야 한다. 기존 파일이 있으면 실패하여 사용자 기록을 보존한다. `--expected-points`는 단일 frame에만 사용한다. 일반 다중 frame 세션의 반복 검증에는 이 옵션을 생략한다.

## F. 이슈별 판단과 남은 제약

### ADE-66

저장 입력 공통 로드, 횟수 지정 재독, 수·순서 확인, depth/valid/target 직접 비교, 계산 결과 비교, 원본 시각·출처 보존, 별도 재생 시각 기록, 성공/실패 출력·종료 코드, 원본 SHA-256 전후 확인을 충족했다. 합성 입력 100회와 임시 다중 frame/target_mask 시나리오를 검증했다.

실제 카메라 세션과 팀 통합 환경의 재현성 검증은 미검증이다. 기준 반복의 전체 프레임과 좌표를 메모리에 유지하고 파일 해시는 파일 내용을 읽어 계산하므로 대형 실측 세션의 메모리·속도 평가는 남아 있다. 전후 해시는 두 시점의 보존 증거이며 실행 중 다른 프로세스가 파일을 바꿨다가 동일하게 복구하는 상황을 감시하는 잠금 기능은 아니다.

### ADE-67

기존 normalize_depth·validate_frame·load_frame를 재사용하여 단위 변환, 유효/무효 규칙, optical-axis-Z 제한, shape/dtype/profile/scale/checksum/경로 실패를 검증했다. 전처리 계산 자체의 신규 복제나 raw SDK 어댑터 구현은 하지 않았다. 저장 배열은 이미 정규화된 m 입력으로 사용한다.

실제 SDK/profile의 단위 계수·Depth 내참수·왜곡 보정·거리 의미 확인, 실제 데이터 전처리 승인, 팀장 통합 검토는 남았다.

### ADE-54·55와 구분

이번 결과는 저장 입력 재생·전처리 검증 범위다. 실제 부피·중량 학습/추론·모바일 USB·로봇 동작을 포함하는 ADE-54·55 전체 완료로 보고하지 않는다. Point Cloud는 반복 계산 동일성의 근거일 뿐 부피 계산 결과가 아니다.

examples/results의 feature 부피·prediction 성공·label 중량은 인터페이스 fixture다. 실제 측정·학습 결과나 정확도 근거로 취급하지 않았다. labels.jsonl·실측 g를 프레임/추론 입력으로 결합하지 않는다. 세션 내 파일의 보존 해시에 labels.jsonl이 포함될 수 있으나 내용 파싱이나 계산 입력 사용은 하지 않는다.

### 팀장 검토 항목

1. 이 재생 CLI와 실행 기록 형식을 공식 저장소에 이관할 위치 및 통합 기준.
2. 실제 카메라 세션의 출처, SDK/profile, 단위 계수, Depth 내참수·보정 승인.
3. 실제 세션의 반복 검증 횟수와 성능·메모리 기준. 이번 100회를 공식 기준으로 자동 채택하지 않음.
4. 스키마 변경 없이 추가한 실행 보고서의 팀 공용 형식 채택 여부.

## G. Git·외부 작업·원본 보존

`git rev-parse --show-toplevel`, `git status --short --branch`, `git remote -v`에서 Git 저장소가 아님을 확인했다. 따라서 저장소 루트·브랜치·remote·Git working tree는 해당 없음이다. git init·브랜치 생성·commit·push·PR·병합을 하지 않았다. 개인 백업 저장소를 공식 저장소로 지정하지 않았다. 외부 Linear·Notion 페이지 수정 및 팀원 메시지 전송도 하지 않았다.

Git 미설정이므로 .gitignore를 임의 생성하지 않았다. 제출할 산출물은 추가 src/tests/scripts/docs와 logs 및 필요한 기존 기준본이다. **`.venv/`, `__pycache__/`, `*.pyc`는 제출에서 제외**한다. 로컬 실행에 필요한 가상환경과 캐시는 그대로 두었다. 합성 입력·스키마·해시·검증 로그는 검증 근거로 보존한다.

오류 입력은 임시 복사본 또는 메모리 객체를 사용했다. 배포 원본 22개 파일의 시작/종료 해시는 `original_inventory.json`과 `final_preservation.json`에서 비교할 수 있다. 기존 SHA256SUMS를 신규 산출물용으로 덮어쓰지 않았다.

## 실행 로그 안내

각 실행 JSON에는 Asia/Seoul 일시, OS, Python 버전·실행 경로, NumPy, cwd, 실제 명령 배열, 종료 코드, stdout, stderr가 있다. UTF-8로 직접 저장하고 다시 읽었다. PowerShell 기본 리디렉션 인코딩에 의존하지 않는다.

| 로그 | 근거 |
|---|---|
| `logs/original_inventory.json` | 작업 시작 전체 원본 해시, 배포 21개 체크섬, 별도로 표시한 사용자 전달 기록 |
| `logs/1791364711363884400_baseline_tests.json` | 제공 테스트 28개 실제 실행 |
| `logs/1791364713525193600_baseline_example.json` | 제공 예제 실제 좌표 출력 |
| `logs/1791364714113016200_installed_packages.json` | 설치 상태 확인 |
| `logs/1791364812642280400_replay_red.json` | 새 도구 구현 전 테스트 실패 기록. replay.py 미존재로 인한 개발 단계의 의도된 실패이며 최종 실패와 구분 |
| `logs/1791364812985283600_preprocessing_boundaries.json` | 기존 코드의 추가 전처리 경계 4개 통과 |
| `logs/1791364905228668800_replay_green.json` | 최초 재생 테스트 8개 구현 후 통과. 이후 2개 추가하여 최종 10개 |
| `logs/1791364945665668600_final_tests.json` | 최종 기존 28 + 추가 14 = 42개 통과 |
| `logs/1791364948072227200_replay_100.json` | 100회 실행 환경·명령·표준출력·종료 0 |
| `logs/replay_1791364947856535500.json` | 반복 100개 각각의 replay_time, 기준 좌표·출처·시각·전후 파일 해시 |
| `logs/1791365008651846000_failure_cli_cases.json` | 임시 입력 14개 시나리오의 실제 subprocess 명령·stdout·stderr·오류 코드·종료 코드·보존 확인. 재현 코드도 command에 포함 |
| `logs/final_preservation.json` | 원본 22개 최종 SHA-256 비교 |
| `logs/1791365010714202200_preservation.json` | 최종 보존 검사 실행 기록 |
| `logs/1791365185262843900_artifact_review.json` | 로그 UTF-8 재읽기, 문서에 기재한 로그 존재, Python 구문·공백 확인, .venv·캐시를 제외한 새 산출물 목록 |
| `logs/v1_0_0_compliance_1791365313123131000.json` | 추가 v1.0.0 조건 점검: 기존 코드·스키마·배포 체크섬 보존, 함수 시그니처·FramePacket 필드, 재생 시각 100개 형식·프레임 계약 검증, 시계 기준, 전부 무효 처리 단계, 원본 샘플 해시, 추가 코드의 별도 해시 |
| `logs/1791365313171471900_v1_0_0_compliance.json` | 위 준수 점검의 환경·실제 명령·출력·종료 코드 0 |

최종 검사 완료 후 같은 테스트를 불필요하게 다시 실행하지 않았다.

### 추가 지시의 규격 v1.0.0 준수 판단

기존 FramePacket 필드, 함수 시그니처, 스키마와 m·광축 Z·카메라 좌표 의미를 그대로 유지했다. 기존 계약 변경은 필요하지 않았다. 추가 재생·실행 기록 기능은 별도 도구이며 원본 계약을 대체하지 않는다.

배포 SHA256SUMS 21개 항목의 **변경 전 검사 결과는 모두 일치, 불일치 목록은 빈 목록**으로 저장돼 있다. SHA256SUMS.txt 자체도 배포 기준 그대로다. 원본 합성 샘플 3개는 배포 검사와 별도로 100회 재생 전후 및 이번 준수 점검 시점에 동일한 해시임을 확인했다. 새 코드의 해시는 준수 점검 JSON의 `new_code_sha256`에 따로 기록했으며 배포 체크섬이나 샘플 훼손 판정과 혼합하지 않았다. 이후 코드 수정으로 해시가 달라지면 수정 내역으로 기록하고 원본 샘플 보존은 별도로 판단한다.

전부 무효인 입력은 normalize_depth에서 예외 없이 0·false로 정리하고 validate_frame에서 NO_VALID_DEPTH로 거부되는 것을 이번 준수 점검에서도 직접 확인했다. 저장된 depth_m에는 raw 변환 계수를 재적용하지 않는다.

추가 조건 확인을 위해 기존 42개 전체 테스트와 100회 세션 재생을 다시 반복하지 않았다. 기존 로그를 검토하고 시각 100개의 형식을 기존 validate_frame으로 확인하는 점검을 수행했다. 신규 unittest 추가는 없으며 **기존 제공 28개 / 앞선 작업 추가 14개**라는 구분은 그대로다.

ADE-66·67의 이번 로컬 기준은 충족했다. 100회는 로컬 검증 조건이며 공식 성능 기준이 아니다. 실제 카메라 샘플 검증·팀장 검토·승인·통합은 여전히 미완료다.

## H. 가장 먼저 할 다음 작업

**실제 카메라의 SDK/profile·단위 계수·Depth 내참수가 기록된 정규화 세션을 확보하고, 팀장 승인 후 같은 재생 CLI로 검증한다.** 장비 모델·공식 저장소·실측 결과는 확인되기 전 추정하지 않는다.
