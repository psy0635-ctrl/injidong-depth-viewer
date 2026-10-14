# 모바일 세션 파일 검사 검증 요약 — 2026-10-14

목적은 이가영 앱의 저장 세션에 대한 파일 무결성·형식 검사다. [추가 도구와 실행 안내](../tools/mobile_session_intake/README.md)는 별도 ADE-71 baseline을 지정해 사용한다. 저장소의 기존 contract.py·schemas·뷰어를 변경하거나 baseline으로 자동 지정하지 않는다.

## 확인된 결과와 근거 구분

| 결과 | 근거·범위 |
|---|---|
| Windows 전체 49개 통과, 실패 0, error 0, skip 0, 종료 0 | 기존 최신 Windows 로그 04_full_tests.txt와 05_test_summary.json 확인. Python 3.11.9 / NumPy 2.3.5 / Pillow 12.3.0. 이번 Git 반영안에서 재실행하지 않음. |
| JSON 객체형 오류 4종과 정상 입력 대상 테스트 5개 통과 | ChatGPT Linux 독립 검증에 대한 사용자 전달 결과. 이번 로컬 작업에서 Linux를 실행하거나 Linux 원본 로그를 확보한 것은 아님. |
| 객체형 오류에서도 실패 JSON 보고서 생성 | 기존 Windows 03_cli_after.jsonl 및 실제 보존 JSON 사본 확인. session.json 최상위 []/null, transmission []/null은 종료 1·failed_mobile_file_checks, 정상 객체는 종료 0·passed_mobile_file_checks. |
| 반영본의 코드·테스트·기준 해시 동일 | 원본 세 파일과 바이트·SHA-256 대조. 상대 baseline_hashes.json 참조와 tests의 상위 도구 폴더 참조 유지. |

최초 17개가 이전 45개에, 이전 45개가 최신 49개에 포함된다. Windows 49개와 Linux 대상 5개도 같은 회귀를 포함하므로 54개로 합산하지 않는다. 이번에 새 기능·테스트·ZIP을 만들거나 테스트·CLI를 다시 실행하지 않았다.

최신 검토 ZIP 식별 정보(파일 자체는 이 변경안에 추가하지 않음):

- `injidong_mobile_session_json_guard_review_20261014_3efda29bb39e42aa8d2517f8be2cab1c.zip`
- SHA-256: `e2e331aaf3708a4f36a344244a83823f7f92b0a8433be3dab61fc060fd0e2ac0`

현재 저장소는 과거 ADE-71 기준 ZIP 하나를 추적하지만 .gitignore는 일반 ZIP을 제외한다. 최신 검토 ZIP을 소스와 함께 보관하려면 바이너리 중복·용량·버전 추적 필요성을 별도로 결정해야 한다. 이번 제안은 소스와 간결한 문서만 보관한다.

## 완료 범위와 다음 단계

파일 검사 성공은 `passed_mobile_file_checks`이다. `geometry_verified=false`, `processing_ready=false`를 유지하며 RGB–Depth 정렬·world pose도 미검증이다. 실제 모바일 자료는 아직 받지 못했다. 휴대폰·D405·USB·SDK 동작, CameraX 시간 의미, raw stride·왜곡·65535 정책, 정밀 보정·내참수·scale·정렬·pose·실제 Point Cloud 정확도 및 팀장 승인 완료로 확대하지 않는다.

다음 단계는 앱에서 정상 종료한 실제 RGB·Depth·IMU 세션 전체를 인수해 원본을 보존하고 파일 검사부터 수행하는 것이다. 원본 세션 루트와 지정 baseline 및 분리된 보고서 경로를 사용한다. 실제 장비·기하 검증은 그 후 별도 근거로 진행한다.

이 자료는 개인 저장소 `psy0635-ctrl/injidong-depth-viewer`의 `codex/mobile-session-json-guard-review-20261014` 작업 브랜치에 보관하는 검토본이다. 팀 공용 통합이나 공식 승인 완료를 뜻하지 않는다. 공식 통합 저장소·대상 브랜치·검토 절차는 별도 확인이 필요하다. main 병합, PR 생성, Linear/Notion 변경, 팀원 메시지 발송은 이번 보관 작업에 포함하지 않는다.
