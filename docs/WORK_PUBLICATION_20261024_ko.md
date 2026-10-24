# 전체 작업 게시 대조 · 2026-10-24

작업 통합 전에 작성한 로컬 대조표를 바탕으로 검증한 결과다. main 기준은 작업 시작 시 재조회한 `73a5ca5f60b4ec9a2f0ad2f9de82a89e4406b42d`다. 브랜치명/커밋 메시지만 보지 않고 실제 소스·시험·문서 내용을 비교했다.

전체 **28개 작업 단위**: **main 반영 완료7 / 원격 브랜치에만 게시0 / 이번 PR 반영19 / 로컬 보존 제외1 / 자료 부족1**. 작업 단위는 아래의 기능·근거 묶음이며 시험 개수나 공식 진척률이 아니다. ‘이번 PR 반영’에는 코드 통합 또는 명시한 후속 검증/재현 문서 요약이 포함된다. 최초 통합 전8/18 분류에서 원격 CI의 정적 PNG 글꼴 시험 후속 수정으로 해당 항목을 이번 PR로 옮겼다. 모든 원본과 일회성 스크립트가 업로드됐다는 뜻이 아니다.

| 작업명 | 로컬 근거 | GitHub main 반영 여부 | 다른 원격 브랜치 게시 여부 | 로컬 후속 변경 | 이번 조치 | 제외 또는 보류 이유 |
|---|---|---|---|---|---|---|
| ADE-66 저장·반복 재생 | injidong_contract_v1/src/replay.py, tests/test_replay.py | src/replay.py·테스트 내용 및 f9384e3 이력 일치 | 기존 브랜치→main 조상 | 완료 보호는 별도 항목7 | 1 main 반영 완료 | 동일 구현 중복 없음 |
| ADE-67 유효 Depth·단위·좌표 검증 | injidong_contract_v1/src/contract.py, tests/test_preprocessing_boundaries.py | 기본 수학·검사 main 존재 | 기존 브랜치→main 조상 | 파일 완료 가드는 항목7 | 1 main 반영 완료 | 기본 규격 유지 |
| ADE-71 D405 변환·저장·재로드 | home-restore/extracted/validation/baseline 및 ADE71 제출자료 | 제출기록 있으나 활성 파이프라인 후속 미통합 | 제출 브랜치는 main 조상 | 독립 세션 pipeline·boundary 검토 | 3 이번 PR에 반영 | 실장비 수집은 기존 보고와 구분 |
| ADE-95 독립 저장 뷰어 | src/viewer*.py·ADE95 사용검증 문서 | 시연 vendor viewer3파일 main과 동일 | 원격 관련 변경 main 포함 | 새 모바일 앱과 구분 | 1 main 반영 완료 | 코드 중복 복사하지 않음; 실행 안내 연결 |
| 모바일 접수·JSON 방어 검사 | 모바일세션 사전검사·tools/mobile_session_intake | 검사기 실제 내용 main 존재 | 591ca53→main 조상 | 후속 index변경 이미main | 1 main 반영 완료 | 개인 입력 제외 |
| RGB 인덱스 호환 | mobile-rgb-index-compat-review 및 test_rgb_index_compat.py | e5f7bf9와 main 검사기 내용 일치 | compat 브랜치 main 조상 | 새 앱은 같은 검사기 재사용 | 1 main 반영 완료 | 중복 구현 없음 |
| 원본 출처·해시·경로·scale·저장 완료 보호 | home-restore baseline/src/session_boundary.py 및 최신앱 vendor/baseline | 현재 main에 session_boundary 없음 | 관련 신규 후속 원격 미게시 | guard 및 pipeline/테스트 | 3 이번 PR에 반영 | schema 변경 없이 보조 완료 프로토콜 |
| 저장 Depth 점군 독립 대조·분석 | stored-depth-review/tools/stored_depth_analysis | main 실제 코드·테스트 존재 | bf20435→main 조상 | 기존 알고리즘 유지; Ubuntu 합성PNG 시험의 글꼴을 명시 | 3 이번 PR에 반영 | 기존 코드 중복 없음; CI 이식성 시험 최소 수정, 한글 가독성 검증 아님 |
| 정적 Depth 분석 시각화 | stored_depth_analysis/make_static_figures.py | main 실제 코드 존재 | stored-depth 브랜치 포함 | 실제 출력은 로컬 | 1 main 반영 완료 | 생성 PNG는 제외 |
| 합성 부피 실험 | experiments/synthetic_volume | main 코드/합성fixture/테스트 동일 | 5edb794→main 조상 | 실제부피 정확도로 확대금지 | 1 main 반영 완료 | 기존 합성 기능 중복 없음 |
| 실제 4프레임 대조와 0042 GUI 후속 | depth-session4·ade71-step1 REPORT | 후속 실행 기록 없음 | 미게시 | 선택 근거·재현·제약 요약 | 3 이번 PR에 반영 | 원본 세션·정적 출력 제외 |
| 로봇 원본 ZIP 접수/부분추출 조사 | robot-intake REPORT·scan/extract scripts | 없음 | 미게시 | 입력식별·부분추출 한계 기록 | 3 이번 PR에 반영 | 하드코딩된 추출일회성스크립트/원본은 로컬보존, 게시 요약에서 명시 |
| 로봇 단일 프레임 조건부 컬러 | robot-color + 최신앱 vendor/color | 없음 | 미게시 | 색 연결 알고리즘/증거 gate/테스트 | 3 이번 PR에 반영 | 실제 원본 RGB 제외, 모바일 정렬 완료 아님 |
| 후보 평면 독립 비교 | robot-floor plane_math.py·tests | 없음 | 미게시 | 순수 평면수학·검증 방법 | 3 이번 PR에 반영 | 실제바닥/중력 검증 아님 |
| 후보 평면 투영·로봇 ROI | support-view·robot-roi + 최신앱 projection/roi_core | 없음 | 미게시 | 공용 ROI·보조 저장/재열기 | 3 이번 PR에 반영 | 입력자료는 명시적 외부 경로 |
| 탐색 두 시점 정합 | two-view rigid_transform·tests·REPORT 및 registration-evidence | 없음 | 미게시 | 알고리즘·변환검사·제약 | 3 이번 PR에 반영 | 탐색/합성 검증 구분; 원본·밀도출력 제외 |
| 모바일 ZIP 안전 로더 | mobile-zip + 최신앱 mobile_session/safe_zip | 없음 | 미게시 | 최신 파일검사·소유캐시 수명 | 3 이번 PR에 반영 | 실제데이터 제외 |
| 외부 기대 ID/크기/SHA 검사 | verified-mobile-zip + 최신앱 verified_mobile_zip | 없음 | 미게시 | 독립 기대값 검증 wrapper·테스트 | 3 이번 PR에 반영 | ZIP 자체 계산값으로 기대값 대체금지 |
| 모바일 Depth·3D·수직뷰·ROI 편집/저장/재열기 | mobile-label + 최종앱 | 없음 | 미게시 | 최신앱·관련테스트 통합 | 3 이번 PR에 반영 | RGB 미사용 |
| HTTP 목록·페이지·다운로드·검증 | pc-http + 최종앱 pc_http/server_panel | 없음 | 미게시 | client·loopback 합성fixture·테스트 | 3 이번 PR에 반영 | 운영서버 구현 제외 |
| GUI 배치·스크롤·수동 결과 대조 | HTTP_GUI_LAYOUT_VERIFICATION·MANUAL_ADDENDUM | 없음 | 미게시 | mobile_layout·증거요약·최신테스트 | 3 이번 PR에 반영 | 개인 수동 ROI/스크린샷 전체 제외 |
| Tk 종료·재다운로드·재열기 | mobile-tk-close·HTTP probe | 없음 | 미게시 | 종료수명 테스트와 결과 구분 | 3 이번 PR에 반영 | 과거시험 수 합산금지 |
| 일반 실행 리허설 | demo-rehearsal REHEARSAL_RESULT | 없음 | 미게시 | 저장소상대경로 새 실행 안내 | 3 이번 PR에 반영 | 과거일반CLI근거 보존 |
| 10/24 우선 검토 | priority-20261024 PRIORITY_REVIEW | 없음 | 미게시 | 최신 상태·검증 한계 요약 | 3 이번 PR에 반영 | 156파일 무변경은 10/24 기존 직접검사 |
| API 협의·시연 안내 | api-agreement·pc-server-handoff·demo prep | 없음 | 미게시 | 임시호환 프로필·사용법 정리 | 3 이번 PR에 반영 | 담당 메시지초안/토큰/시험전용값 실서비스 요구로 전용금지 |
| 학교 이전·집 복원·문서/ZIP 동일성 | school-transfer·home-restore·document-identity·lf-integrity | 일부 이전 제출 문서만 있음 | 신규후속 미게시 | 이전/복원 재현·주의사항 요약 | 3 이번 PR에 반영 | 이전ZIP/중복 배포물 로컬보존 |
| 원본 촬영·개인 수동 ROI·이전ZIP/생성출력 | 기준 ZIP·최종 수동 ROI·각원본/exports | 이번 신규게시 제외 | 기존 추적데이터는 삭제안함 | 기준자료 불변보존 | 4 로컬 보존 대상으로 제외 | 원본·개인 편집·배포묶음 기본 제외 |
| 실제 서버·Android 완료·모바일 픽셀정렬 | 10/24 검토 및 API 인수 자료 | 완료근거 없음 | 확정 구현원본 미확보 | 구현으로 게시하지 않음 | 5 자료 부족으로 확인 불가 | 접속/보정/공동시험 자료 필요; 담당 구현 추정금지 |

## 비교·제외의 세부 범위

- 기존 원격 작업 브랜치6개는 모두 main의 조상이다. `merge-base --is-ancestor`가 모두0이고 synthetic-volume 브랜치와 main의 최종 tree diff는0이었다. 오래된 브랜치의 main 대비 삭제 diff를 새 변경으로 되돌리지 않았다. 일괄 merge/cherry-pick은 없다.
- 기존 ADE66/67·ADE95·모바일 접수·RGB 인덱스·저장 Depth·합성부피 구현은 재사용한다. ADE71의 제출 ZIP에만 있던 활성 소스와 가드를 명시적으로 꺼내 통합했다. [파이프라인 출처와 실행](validation/20261024-publish/PIPELINE_INTEGRATION_ko.md).
- 최신 모바일 앱은 `apps/local_review`에 두고 저장소의 core/viewer/intake를 사용한다. [앱 사용법](../apps/local_review/README.md). 기존 중간 public-review 사본은 경로 adapter/일부 순수 시험의 참고 출처로만 썼고 최신 HTTP/GUI를 과거 코드로 덮지 않았다.
- 로봇 원본 ZIP 접수의 scan/extract 일회성 도구, 후보 추출·독립실측이 없는 정합 실행 스크립트, 원본 경로에 묶인 prepare/reapply 스크립트는 그대로 게시하지 않았다. [실험·입력 제약](EXPERIMENT_HISTORY_ko.md), [두 시점 게시 범위](../experiments/two_view/README.md)에 구체적으로 남긴다. 순수 알고리즘과 작은 합성 검증을 게시해도 실제 입력 전체 재현 완료가 되지 않는다.
- 항목27: 원본 ZIP/RGB/Depth/IMU, 개인 수동 ROI, 이전·복원 ZIP/중복 배포물, 생성 이미지·NPZ·실행 로그, 비밀정보·개인 기록은 신규 게시 제외다. 기존에 추적되던 데이터·로그·제출 ZIP은 이번에 삭제하지 않았다.
- 항목28: 실제 서버·Android 구현 코드/완료 보고와 모바일 정렬 보정/대응 증거가 확보되지 않았다. 담당자의 목표 회신이나 timestamp 근접으로 완료를 추정하지 않는다. ‘서버 미구현’으로 단정하지 않는다.
- 실행/자료 단계별 시험 수는 중복될 수 있으므로 합산하지 않는다. 최신 코드 게시와 main 병합은 별개다.

정확한 로컬 원본 절대경로·원본/게시 파일별 SHA·수정 사유·실행 로그는 게시 작업의 별도 로컬 기록에 보존한다. 공개 문서에는 새 PC 실행에 필요한 저장소 상대경로와 입력 식별값·제약만 남긴다.
