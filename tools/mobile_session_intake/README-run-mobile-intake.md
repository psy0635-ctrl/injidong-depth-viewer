# 독립 모바일 검사 연결 CLI

`run_mobile_intake.py`는 **검사 실행 → 이번 실행 보고서 확인 → 입력 재대조 → 실패 또는 처리 보류 출력**까지만 수행한다. Python 표준 라이브러리만 사용한다. 별도 프로세스의 기존 검사기는 NumPy/Pillow와 지정 ADE-71 baseline이 필요하다.

뷰어 실행·점군 계산·보정 검증·RGB 변환·부피/중량 계산 기능은 없다. 검사 보고서가 예상과 달리 readiness=true를 반환해도 자동 처리하지 않는다. 연결 요약의 `geometry_verified=false`, `processing_ready=false`, `viewer_launched=false`는 항상 유지한다. 기존 보고서 원본은 수정하지 않는다.

이 문서는 연결 CLI 전용 README다. 기존 [검사기 README](README.md), 검사기·기준 해시·기존 해시 목록은 변경하지 않았다. 새 파일은 기존 `FILE_SHA256SUMS.json`의 검사기 배포 목록에 포함되지 않으며 연결 실행 시 별도 SHA-256을 기록한다.

## 인자

| 인자 | 필수 | 의미 |
|---|---|---|
| `--python` | 예 | 검사기와 baseline 경계 사전 확인을 실행할 Python 파일 |
| `--checker` | 예 | 기존 `check_mobile_session.py` 파일. 같은 디렉터리의 `baseline_hashes.json` 필요 |
| `--contract-root` | 예 | 지정 ADE-71 ZIP의 별도 해제 루트. 저장소 기본 src를 자동 지정하지 않음 |
| `--session` | 예 | 입력 세션 디렉터리. 실제 수집 파일의 유효성은 기존 검사기가 판정 |
| `--result-root` | 예 | 실행마다 `run_<uuid>`를 새로 만드는 결과 부모 디렉터리 |
| `--timeout-seconds` | 아니요 | 검사기 제한 시간, 양의 정수 초. 기본 300초 |

학교 절대 경로를 코드 기본값으로 사용하지 않는다. 인자 경로는 resolve한 절대 경로로 실행·기록한다. 입력·baseline·검사기 코드 디렉터리·연결 CLI 코드 디렉터리와 결과 루트가 같거나 어느 방향으로든 중첩되면 거부한다. 기존 Windows Junction도 resolve하여 검사한다.

필수 실행 파일·baseline 3개 파일과 기준 해시를 확인하고 **선택한 Python에서 baseline의 `guard_read()`를 그대로 호출**한 뒤에만 결과 폴더를 만든다. 상위 ADE-71 관리 marker가 미완료/분리/pending 입력을 차단하면 `preflight_error`다. marker를 생성·삭제하거나 staging 우회 문맥을 사용하지 않는다. marker 없는 외부 세션은 기존 정책대로 읽을 수 있다. 입력 내부 파일 누락/손상은 검사기의 실패 보고서로 전달한다.

## 학교 PC 실행 예시

2026-10-15 이번 작업에서 재확인한 Python은 아래 `.venv` 경로다. `C:\study\injidong-depth-viewer.venv\Scripts\python.exe`는 존재하지 않았다. Python 3.11.9 / NumPy 2.3.5 / Pillow 12.3.0을 재확인했으며 설치·업그레이드는 하지 않았다.

아래 입력은 이번 연결 검증에서 기존 fixture builder로 만든 **합성 입력**이다. 실제 모바일 세션으로 검증한 이력은 아직 없다. 실제 수신 후에는 `$intakeSession`만 해당 세션 루트로 바꾼다. 다음 명령은 사용자가 필요할 때 실행하는 예시이며 반복 검증을 요구하지 않는다.

```powershell
$runnerPython = 'C:\study\injidong-depth-viewer\.venv\Scripts\python.exe'
$intakeTools = 'C:\study\injidong-mobile-path-review-20261015-3c906367\tools\mobile_session_intake'
$intakeBaseline = 'C:\study\injidong-baseline-review-20261015-3c906367'
$intakeSession = 'C:\study\injidong-runner-verification-20261015-5a0470d7\real_checker_synthetic\synthetic_session'
$intakeResults = 'C:\study\injidong-runner-results-20261015'

& $runnerPython -B -X utf8 "$intakeTools\run_mobile_intake.py" `
    --python $runnerPython `
    --checker "$intakeTools\check_mobile_session.py" `
    --contract-root $intakeBaseline `
    --session $intakeSession `
    --result-root $intakeResults
$intakeExit = $LASTEXITCODE
$intakeExit # 파일 검사 통과·처리 보류는 10. 실제 처리 허용이 아니다.
```

## 상태와 종료 코드

| 최종 상태 | 코드 | 의미 |
|---|---:|---|
| `processing_held` | 10 | 파일 검사 통과·입력 재대조 일치. 실제 처리는 보류하는 독립 상태이며 검사 실패가 아님 |
| `checker_failed` | 20 | 검사기 종료 1과 실패 보고서가 일치. 원본 error와 보고서 경로 전달 |
| `input_changed` | 21 | 검사 전후 파일 추가/삭제/내용 변경 또는 검사 보고서 목록과 재대조 불일치. 불일치만으로 정확한 변경 시점을 확정하지 않음 |
| `execution_error` | 22 | 검사기 실행 불가·0/1 이외 종료·timeout 또는 입력 재대조 불가 |
| `report_error` | 23 | 이번 보고서 누락·복수/예상 밖 파일·손상·stdout 경로 불일치·필수 필드/형식 오류·종료 코드와 판정 불일치 |
| `preflight_error` | 24 | 경로·baseline 해시·선택한 Python·baseline 공개 경계 사전 확인 실패. 결과 디렉터리 생성 전 중단 |
| `output_error` | 25 | 실행 디렉터리·로그/요약·해시 목록 저장 오류 |
| CLI 사용 오류 | 2 | argparse의 필수 인자 누락·잘못된 옵션/timeout 등. 요약 파일 없음 |

**검사 수행 경로에서는 종료 0을 반환하지 않는다.** `--help`만 일반 argparse 동작으로 0을 반환하며 검사를 실행하지 않는다. 원래 검사기의 종료 0은 파일 검사 성공일 뿐이고, 연결 CLI는 이를 처리 보류 10으로 구분한다. 외부 자동화는 단순 0/비0 대신 `final_status`와 코드를 함께 읽어야 한다. 어떤 코드도 실제 처리 허용을 뜻하지 않는다.

저장 실패는 종료 25를 우선 유지하며 함께 발견한 입력 변경/재대조 오류도 `input_verification`에 보존한다. 저장 실패가 없으면 입력 변경/불일치를 우선 표시하고 이전 검사·보고서 실패도 `checker_outcome`/`issues`에 보존한다. 입력을 재열거할 수 없으면 변경 없음으로 취급하지 않고 `execution_error`를 반환한다. 결과·로그·요약 저장 오류는 stderr의 원인으로 알리고, stdout JSON에도 `output_error`를 출력한다.

## 실행별 기록과 보고서 연결

```text
<result-root>/run_<uuid>/
  checker_reports/mobile_check_<checker-uuid>.json  # 기존 검사기의 원본
  checker_stdout.txt                             # 원본 stdout 바이트
  checker_stderr.txt                             # 원본 stderr 바이트
  input_before.json                              # 연결부의 검사 전 목록
  input_after.json                               # 연결부의 검사 후 목록
  runner_summary.json                            # 별도 연결 요약
```

요약은 `runner_summary.pending.json`에 쓰고 파일 닫기까지 성공한 후 최종 이름으로 rename한다. 쓰기/닫기/공개 실패 시 최종 요약을 게시하지 않으며 `summary_path=null`과 stderr 원인을 남긴다. 남은 pending 파일은 진단용 미완료 파일로, 최종 판정으로 읽지 않는다. 이 이름 공개 절차는 파일 시스템 완료 경계이며 전원 차단 시 내구성 보장이 아니다.

디렉터리는 UUID와 exclusive 생성으로 분리한다. 기존 결과를 덮어쓰거나 삭제하지 않는다. 검사기는 절대 경로의 인자 목록과 `shell=False`로 실행한다. 이번 전용 `checker_reports` 디렉터리에서 정확히 한 개의 규칙에 맞는 보고서가 생성됐는지 확인하고, 검사기가 stdout에 출력한 한 줄의 절대 경로와 일치해야 채택한다. 예전 결과 루트를 glob으로 검색해 대체하지 않는다. 비정상 종료/timeout에서는 보고서를 성공 결과로 채택하지 않고 로그와 재대조 결과를 남긴다.

요약은 stdout에도 JSON 한 객체로 출력한다. `summary_format=mobile-intake-runner-v1`은 **연결 CLI 전용 형식**이며 공통 FramePacket/ProcessingResult 스키마가 아니다. run ID·사용 경로·Python 버전/경로·runner/checker/Python/기준 파일의 해시·실행 인자·검사기 종료 코드·이번 보고서 경로/해시·입력 비교 범위/결과·최종 상태/사유·준비 상태·viewer 미실행을 기록한다. 사전 확인 실패 시에는 생성하지 않은 경로/보고서 값이 null일 수 있고 요약은 stdout에만 남는다.

JSON 최상위 객체·필수 필드·bool/int/목록/문자열·해시 목록·상태/종료 코드 대응을 확인한다. 문자열 `"false"`나 숫자 `0`을 bool로 변환하지 않는다. 중복 JSON key와 비유한 수를 거부한다. 실패 보고서는 원래 검사기에서 `input_sha256`이 생략될 수 있으므로, 그 경우 검사기 목록 비교는 `not_available`로 명시하고 연결부 전후 비교만 수행한다.

## 입력 변경 검사 범위

기준 검사기의 `inventory()`를 읽고 같은 규칙을 독립 구현했다. `input_sha256`은 참조된 수집 파일만이 아니라 **`session.rglob('*')`가 열거하는 모든 일반 파일**의 세션 상대 POSIX 경로 → 내용 바이트 SHA-256이다. 부가 메모·숨김 파일도 범위에 포함된다. symlink와 resolve 후 세션 밖으로 나가는 경로는 거부한다. 빈 디렉터리·mtime·권한 등 파일 메타데이터는 범위 밖이다.

연결부 목록은 `input_before.json`/`input_after.json`이라는 별도 기록이며 검사 보고서의 `input_sha256`을 수정하거나 다른 규칙으로 재사용하지 않는다. 파일 추가는 added, 삭제는 removed, 같은 경로의 내용 변경은 modified로 기록한다. 통과 보고서는 input_sha256을 필수로 확인하고 검사 후 목록과도 비교한다. 검사기 목록이 잘못되거나 낡았을 때도 불일치가 날 수 있으므로 전후 비교와 보고서 비교를 따로 남긴다.

이는 검사 전/검사기 내부/검사 후의 **해당 시점 비교**다. 비교 사이에 변경됐다가 복구된 내용이나 마지막 비교 이후의 변경을 모두 탐지한다는 보장은 없으며 파일 잠금이 아니다. 이후 처리 허용에는 별도 근거 검증과 사용 시점의 입력 결합이 필요하다.

## 새 검증만 실행하는 명령

```powershell
# 가짜 검사기/baseline으로 연결부만 검사. 기존 49개를 발견/실행하지 않는다.
& $runnerPython -B -X utf8 -m unittest discover `
    -s "$intakeTools\tests" -p 'test_run_mobile_intake.py' -v
$runnerUnitExit = $LASTEXITCODE
if ($runnerUnitExit -ne 0) { throw "연결부 테스트 실패: $runnerUnitExit" }

# 실제 검사기/baseline + 기존 합성 fixture builder. 기존 테스트 메서드는 실행하지 않는다.
# 필요할 때만 새 검증 경로로 1회 실행한다.
$newVerification = Join-Path 'C:\study' ('mobile-runner-synthetic-' + [guid]::NewGuid().ToString('N'))
& $runnerPython -B -X utf8 "$intakeTools\tests\verify_runner_integration.py" `
    --python $runnerPython --contract-root $intakeBaseline `
    --verification-root $newVerification
$integrationExit = $LASTEXITCODE
if ($integrationExit -ne 0) { throw "합성 연결 검증 실패: $integrationExit" }
```

통합 검증 helper는 기존 `MobileIntakeTests.setUp()`의 합성 파일을 변경 없이 별도 경로에 복사한다. 실측 출처/보정 플래그를 주입하지 않으며 `integration_verification.json`에 합성임을 명시한다. helper 자체 종료 0은 검증 assertion 통과이며, 그 안에서 실행한 연결 CLI 종료는 10이다.

Windows Junction 테스트는 실제 생성 가능할 때만 통과하며 불가능하면 unittest에 구체적인 skip 사유를 남긴다. 이 새 검증을 과거 49개·실제 모바일·GUI·100회 재생·기기/보정 검증과 합산하거나 동일시하지 않는다.

## 2026-10-15 학교 PC 최종 검토

기존 20개 테스트/합성 연결 기록이 수정 전 네 파일의 diff 및 runner 해시와 대응함을 확인했다. 최종 검토에서 요약 저장 실패의 stderr 안내 누락·미완료 최종 파일 노출과 로그 close 오류 분류를 보완했다. 요약은 pending 파일의 쓰기/닫기가 끝난 뒤 공개한다.

- 저장 실패와 입력 변경 동시 발생을 포함한 회귀 5개를 추가한 **최종 단위 테스트 25개 통과 / 실패 0 / skip 0**. Windows Junction 검사는 실제 실행했다. 가짜 검사기/baseline을 사용하는 연결부 검증이다.
- 최종 코드로 실제 기준 검사기·별도 ADE-71 baseline·기존 합성 fixture 연결을 확인했다. 검사기 종료 0, 연결 CLI 종료 10(`processing_held`), 입력 전후·보고서 해시 목록 일치, viewer 미실행이다.
- 기존 검사기·baseline·ZIP 등 보호 파일 160개의 해시를 대조했다. 검증 입력/상세 로그는 저장소 밖에 보관하며 이 변경에 포함하지 않는다.

이는 이번 학교 PC의 로컬 검증 기록이다. 과거 검사기 49개와 합산하지 않으며 실제 모바일 세션·장비·보정·정렬·점군 정확도·부피·중량 및 공용 0.2.0 통합 검증은 아니다. 개인 작업 브랜치 보관과 팀 공용 통합·승인은 별개다.
