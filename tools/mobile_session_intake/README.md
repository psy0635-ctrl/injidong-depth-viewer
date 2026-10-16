# 모바일 세션 파일 사전 검사

## 2026-10-16 RGB 인덱스 호환 개인 검토본

정책 식별자는 `mobile-rgb-index-compat-review-v1`이다. 이 변경은 개인 검토 브랜치의 모바일 인수 검사기 정책이며 **팀 공식 승인·공용 통합은 미완료**다. 공통 FramePacket v1.0.0 스키마를 변경하지 않는다. 이번 구현·검증 결과는 [별도 후속 문서](../../docs/mobile-rgb-index-compat-review-20261016.md)에 기록하며 과거 실패·검증 기록은 보존한다.

허용 조합은 아래 둘 중 정확히 하나다. 나머지 `files` 항목의 엄격한 검증과 RGB 행 검증은 두 형식에 동일하게 적용한다.

| session.json 키 | 정확한 세션 상대 파일명 |
|---|---|
| `files.phone_rgb_index` | `rgb_index.jsonl` |
| `files.images_index` | `images.jsonl` |

두 키가 함께 있거나 두 파일명에 해당하는 루트 엔트리가 함께 있으면 내용이 같아도 거부한다. 선언하지 않은 다른 인덱스 엔트리도 거부한다. 디렉터리·끊어진 링크·symlink·Windows junction/reparse point를 엔트리 부재로 취급하지 않는다. 선택 파일은 링크 없는 일반 파일이어야 한다. 선언 파일 누락·읽기 실패·손상 시 **자동 fallback을 하지 않으며 입력의 이름이나 내용을 변경하지 않는다**.

보고서의 추가 `rgb_index` 객체는 정책 ID, 관찰 후보 키/엔트리, 선택 키, 선언 경로, 사용한 세션 상대 경로, 실제 SHA-256을 기록한다. 선택 전 실패는 후보와 이유를, 선택 후 실패는 확보한 선택 정보와 이유를 보존한다. 확보하지 못한 경로/해시는 null이며 해시를 추정하지 않는다. 이 객체는 검사 보고서 필드이며 FramePacket 필드가 아니다. 기존 보고 필드와 종료 코드(파일 검사 0/1, 연결 CLI 통과·처리 보류 10/검사 실패 20)를 유지한다.

파일 검사 성공은 RGB·Depth 짝맞춤·정렬·시간 동기화, 물리적 거리 정확도, SDK 값의 독립 검증이나 처리 허용을 뜻하지 않는다. geometry_verified, processing_ready, viewer_launched, sdk_values_independently_verified, common_framepacket_fully_validated는 false를 유지한다.

아래의 ‘실제 모바일 자료 미수신’, ‘최신 49개와 동일’ 설명은 **2026-10-14 보관 당시 이력**이다. 새 검토본 결과와 합산하거나 현재 코드가 과거 코드와 같다는 의미로 사용하지 않는다.

## 2026-10-14 보관 이력과 기본 실행 안내

이가영 앱이 저장한 RGB·Depth·IMU 세션의 파일 무결성·형식을 확인하는 추가 도구다. 기준 앱 커밋은 `b9f370ac94901b1dfce2c4c64018380d5036e967`이다. 실제 모바일 자료는 아직 받지 못했다. 통과 상태는 `passed_mobile_file_checks`이며 `geometry_verified=false`, `processing_ready=false`, RGB–Depth 정렬·world pose 미검증을 유지한다.

이 폴더의 실행 코드·테스트·baseline_hashes.json은 최신 49개 검증본과 바이트가 같다. 기능·검사 조건·import 경로는 변경하지 않았다. 검증 결과와 근거의 범위는 [검증 요약](../../docs/mobile-session-intake-validation-20261014.md)에 있다.

## 별도로 준비할 기준 코드

이 도구는 지정 baseline이 필요한 추가 도구이며 단독 실행 패키지가 아니다. **저장소의 기존 src/contract.py를 지정 baseline으로 가정하지 않는다.** 현재 Git 시작본에는 src/session_boundary.py도 없다. 아래 기준 ZIP을 별도 폴더에 해제하고 src/, schemas/, examples/가 바로 있는 루트를 지정한다.

- 파일명: `ADE-71_session_fixed_20261014_6fe5b71e259e.zip`
- SHA-256: `31547e5128b78d0becce9c3414fff9f3e27211dac72d318badaf0a3686a3dddd`

`baseline_hashes.json`은 src/contract.py, src/session_boundary.py, schemas/frame.schema.json의 기준 해시를 확인한다. 다른 버전을 통과시키려고 이 목록을 바꾸지 않는다. 기준 코드·공통 스키마는 이 변경안에서 수정하지 않았다.

## 사용자가 경로를 지정하는 실행 방법

저장소 루트에서 PowerShell로 실행한다. 기존 NumPy와 Pillow가 있는 Python 환경을 사용한다. 기존 Windows 검증 환경은 Python 3.11.9 / NumPy 2.3.5 / Pillow 12.3.0이다. 아래 명령은 사용 예시이며 이번 Git 변경안 준비에서 도구를 재실행한 명령이 아니다. 학교 PC나 임시 해제 경로를 실행 필수 경로로 고정하지 않는다.

```powershell
$python = Read-Host '사용할 Python 실행 파일 경로'
$baseline = (Resolve-Path (Read-Host '기준 ADE-71 ZIP을 별도 해제한 루트 경로')).Path
$session = (Resolve-Path (Read-Host '실제 수신 세션 루트 경로')).Path
$reports = Read-Host '입력과 baseline 밖의 보고서 출력 경로'
$mobileTools = (Resolve-Path '.\tools\mobile_session_intake').Path

& $python -B -X utf8 "$mobileTools\check_mobile_session.py" `
    "$session" --contract-root "$baseline" --report-dir "$reports"
$LASTEXITCODE
```

세션 루트에는 session.json과 frames.jsonl이 바로 있어야 한다. 상위 sessions/ 폴더나 개별 파일을 지정하지 않는다. 위 정책으로 선택한 RGB 인덱스, imu.jsonl, rgb/, raw/와 프레임별 metadata.json·arrays.npz도 필요하다. 보고서 폴더는 입력 세션·baseline과 겹치거나 이들을 포함하는 상위 폴더여서는 안 된다. 입력 원본을 덮어쓰지 않는다.

정상 입력은 종료 0과 `passed_mobile_file_checks`를 남긴다. 지원하는 입력 검사 오류는 종료 1과 stdout의 실패 JSON 보고서 경로로 확인한다. session.json 최상위 또는 transmission이 []/null인 경우도 해당 파일/필드를 밝힌 `failed_mobile_file_checks` 보고서를 남긴 것이 기존 검증에서 확인됐다. CLI 인자·출력 경로 오류처럼 검사 시작 전 오류는 보고서 생성 전에 종료할 수 있다.

필요할 때 사용자가 수행할 기존 테스트 명령:

```powershell
$env:MOBILE_CONTRACT_ROOT = $baseline
& $python -B -X utf8 -m unittest discover -s "$mobileTools\tests" -v
$LASTEXITCODE
```

테스트는 합성 fixture이며 실제 촬영·SDK 실측 증거가 아니다. 일부 카메라 검사는 real 분기를 검사하도록 합성 메타데이터의 출처 필드를 의도적으로 주입하고 SYNTHETIC_NOTICE 및 메모로 구분한다. 실제 serial·보정 기록을 생성하지 않는다. baseline의 examples/synthetic도 테스트에 필요하다.

## 현재 검사 조건과 한계

- 완료 상태·manifest·FramePacket·NPZ·raw Z16·RGB PNG의 경로·자료형·해시 및 개수를 검사한다. 미완료 managed 세션을 차단하고 외부 세션에 ADE-71 완료 기록을 만들지 않는다. RGBA를 RGB8로 조용히 처리하지 않는다.
- RGB 시간은 10진 ns, android_camera_sensor, sensor 표기를 확인한다. RGB–Depth 시간을 직접 빼서 동기화 판정을 하지 않는다.
- real FramePacket의 Intel/RealSense D405와 profile/calibration 식별자의 대응을 확인한다. serial·firmware·SDK null은 허용하고 누락 정보로 보고한다. 문자열 일치는 물리 보정 증거가 아니다.
- IMU session/device/sample 출처·센서별 벡터·시간을 확인한다. 같은 센서 종류에서의 시간 역행은 오류이며 같은 시각은 경고로 허용한다. 전역 시간 증가를 강제하거나 IMU로 world pose를 확보했다고 판단하지 않는다.
- 중복 수집 경로와 인식 가능한 목록 밖 수집 파일을 보고한다. README·로그·메모 등 부가 파일을 구분하여 허용하며 다른 이름으로 숨긴 자료까지 수집 파일이라고 확정하지 않는다. 첫 오류에서 종료하므로 전체 오류를 한 번에 수집하는 도구는 아니다.

raw stride·왜곡 계수·65535의 의미·정밀 보정·scale·RGB–Depth 정렬·camera↔IMU 외참수·pose·실제 Point Cloud 정확도·실기기 동작·팀장 승인은 미검증이다. 다음 단계는 실제 정상 종료 세션의 인수 검사다.

## 파일 해시와 보관 범위

새 검토본의 `FILE_SHA256SUMS.json`은 이 폴더의 README.md, check_mobile_session.py, baseline_hashes.json, tests/test_mobile_session.py, tests/test_rgb_index_compat.py 다섯 파일의 상대 경로→실제 바이트 SHA-256이다. 목록 자신은 제외한다. 기존 ZIP과 Windows 실행 복사본의 목록은 변경하지 않는다. 저장소 루트 `.gitattributes`는 이 다섯 파일과 목록 자체에만 `text eol=lf`를 명시해 작업 파일과 Git blob의 바이트를 맞춘다. 실제 작업 파일과 staged blob을 각각 해시하여 대조하며 저장소 전체를 정규화하지 않는다. 연결 CLI 파일은 이전과 같이 이 목록 범위 밖이다.

대량 검증 로그·과거 TEST_LOG.txt·ZIP·환경·캐시·개인 설정·실제 수집 입력은 넣지 않았다. 최초 17개, 이전 45개, 최신 49개 검증 결과는 포함 관계이므로 합산하지 않는다. 필요 시 원본 검토 ZIP과 별도 감사 기록에서 상세 로그를 확인한다.
