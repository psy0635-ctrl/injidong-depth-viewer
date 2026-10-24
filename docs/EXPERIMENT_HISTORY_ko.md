# 저장 입력·로봇·탐색 실험의 게시 범위

2026-10-24. 완료된 코드와 실행 근거를 구분한다. 이 문서는 원본 ZIP·개인 라벨·원본 RGB/Depth·실행 출력 전체를 복제하지 않는다.

| 경과 | 게시된 재현 수단 | 직접 검증의 한계 |
|---|---|---|
| ADE66/67 저장·재생 | src/contract.py, replay.py 및 tests | 합성 수학/배열 계약. 실제 중량 정확도 아님 |
| ADE71 D405 입력·완료 보호 | 활성 session_pipeline/depth_preflight/session_boundary 및 명시적 입력 CLI | 과거10프레임 인수 근거가 부족하면 INTAKE_BLOCKED. 현재 모바일4프레임 ZIP과 다른 입력 |
| 저장 Depth 독립 좌표 대조 | tools/stored_depth_analysis | 저장 float32와 카메라 좌표의 수학/원본 참조 대조. raw×scale의 모든 픽셀 일치는 왜곡 재매핑 입력에 강제하지 않음 |
| 0042와4프레임·10/20 GUI | 기존 뷰어·분석 도구 + 최신 모바일 ZIP 로더 | 0042 장면/4프레임 원본은 별도 인수 필요. 과거 정적 PNG와 OS GUI 조작을 구분 |
| 합성 부피 | experiments/synthetic_volume | 합성 생성 정답과 알고리즘 실험. 실물 부피/중량 검증 아님 |
| 로봇 원본 ZIP 접수 | 원본 식별·부분추출/검사 설명 및 명시적 외부 로봇 검토 묶음 | 원본 archive scan/extract의 특정PC·촬영묶음 고정 일회성 스크립트는 미게시. 원본·권한·추출manifest가 없으면 동일 접수 재현 불가 |
| 단일 로봇 컬러·후보 평면·ROI | apps/local_review/lib/color, plane_math, projection, roi_core 및 합성 수학 시험 | 저장된 SDK depth-grid align과 보정/frameset 증거에 조건부. PC가 새 정렬을 하지 않음. 실제 픽셀 정확도·바닥/중력은 미검증 |
| 두 시점 정합 | experiments/two_view/rigid_transform.py와 합성5시험 | source frame_001459→target frame_001409의 탐색 기록. 실제 prepare_inputs/run_registration/reapply_saved와 원본 묶음은 미게시. 작은 NN 오차는 물리 정답 아님 |

최신 모바일 기준 입력은 session d405_1792497323680, ZIP3354368bytes, SHA256 72f3ebaff4c6fcb57675e702aca0854eeec162ce0de4f86b4b80de381cd07dff다. [앱 안내](../apps/local_review/README.md)의 확보·검사 조건을 따른다. RGB4장·Depth4프레임·IMU1117건이며 RGB8/RGBA 경고4건을 유지한다. metadata의 pair/alignment는 unverified, pose/IMU geometry는 미적용이다.

로봇 컬러 경로는 기존 승인된 외부 검토 묶음의 path_map.json·session/metadata/arrays/aligned RGB/calibration·후보평면 근거를 필요로 한다. 프레임001409의 원본 점군190949점·비검정 색후보176747점이라는10/24 로컬 확인은 동일 원본이 있어야 재현된다. 검정색은 실제 검정/샘플없음이 구분되지 않아 표시 후보만 다르게 처리하며 Depth행·픽셀ID는 보존한다. 임의 RGB resize·같은픽셀 번호 색칠로 모바일 정렬 완료를 만들지 않는다.

원본 로봇 ZIP/카메라장착 보정·촬영소스·동일 물체/자세/시각·실측 비교 근거는 코드 게시와 별도로 확보해야 한다. 후보 평면과 정합 target 카메라 좌표를 실제 바닥/중력/world로 승격하지 않는다. volume/mass·모델 최종 인수는 여전히 미검증이다.
