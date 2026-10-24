# 게시 코드의 출처와 변경 경계

2026-10-24. 최신 시연본 `injidong-pc-http-layout-20261023-195646-23d94910/app`의 실행 경로와 시험을 선정했다. 이전 `injidong-public-review-20261021-a14e4eb9`의 외부 입력 adapter·ZIP순수시험·경로시험은 출처를 별도로 대조해 참고했다. 이전 앱 전체로 최신 HTTP/GUI를 덮지 않았다.

| 게시 구성 | 출처와 최소 변경 |
|---|---|
| mobile_session/mobile_viewer/mobile_roi/mobile_layout | 최신 시연본. 저장소 src/intake를 명시적으로 참조. 데이터·실측값·RGB 미사용 정책 유지 |
| pc_http/server_panel/verified_mobile_zip/safe_zip | 최신 시연본. 프로토콜·기대값·검증·수명 정책 유지 |
| roi_core/projection/plane_math/run_review_viewer/review_data | 최신 검증본. 외부 로봇 입력 선택·공유core 경로·누락파일 안내만 최소 조정 |
| lib/color | 기존 저장정렬RGB 조건부 gate/픽셀 연결. 새 정렬 구현 아님 |
| paths | 승인된 외부 로봇 묶음만 명시 선택. 과거 PC 경로 fallback·원본 데이터의 숨은 코드 의존성 제거 |
| 기존 tests·probe·http_fixture | 최신 검증본. 실제 원본은 환경으로 선택하고 없으면 명시skip, fixture에 별도 합성 identity 지원. 실제기준 SHA/크기 검사 유지 |
| 색·평면·투영 순수시험 | 이전 robot-color/floor/support-view의 누락 시험4파일. 합성입력·저장소 경로만 사용 |
| make_synthetic_demo·test_synthetic_workflow | 이번 새 checkout 재현용 작은 합성 생성/실제제품 경로 통합시험. 실제장비 근거 아님 |

이미 main에 게시된 core/viewer/intake를 vendor에 중복 복사하지 않았다. 공유 core의 신규 완료/경로 가드 출처는 [파이프라인 통합](../../docs/validation/20261024-publish/PIPELINE_INTEGRATION_ko.md)이다. 개인 입력·수동ROI·배포ZIP·실행출력·연결된 팀 메신저 원문은 게시하지 않았다. 정확한 로컬원본/게시경로·원본SHA/게시SHA·변경사유는 별도 로컬 APP_FILE_MAP/PIPELINE_FILE_MAP/EXPERIMENTS_FILE_MAP 기록에 있다.
