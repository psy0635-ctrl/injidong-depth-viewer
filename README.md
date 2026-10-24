# 인지동 공통 데이터·인터페이스 규격 v1.0.0

> **2026-10-24 현재:** 저장·재생/독립 ADE95 뷰어에 더해 PC 모바일 ZIP·외부 기대값·HTTP 목록/다운로드·Depth/3D·후보 평면 ROI 저장/재열기를 별도 앱으로 통합했다. [최신 상태](docs/STATUS_20261024_ko.md), [앱 실행](apps/local_review/README.md), [전체 작업 게시 대조28개](docs/WORK_PUBLICATION_20261024_ko.md)를 먼저 읽는다. 실제 서버·Android 공동 연결, 모바일 RGB 픽셀 정렬·실제 컬러, 물리 바닥/중력·부피/중량 정확도는 미검증이다. 아래10/07 담당·착수 설명은 당시 기록이다. 코어 schema_version은1.0.0을 유지한다.

**확정일: 2026-10-07 / 적용: ADE-51, 로봇팔·모바일 Depth 기반 중량 추정**

강석현의 “내 테스크를 진행하고 규격부터 정해 달라”는 요청을 근거로 확정한 개발 기준이다. 박수용의 `common-contract-proposal.md` draft-1을 검토해 입력 분리·단위·좌표·보정·실패 처리를 채택하고, 저장 파일·타임스탬프 표현·실측 라벨 분리·출력 필드를 확정했다. 실기기 연결 및 중량 정확도 검증 완료를 의미하지 않는다.

## 1. 이번 주 착수 기준

| 담당 | 바로 구현할 범위 | 전달할 결과 |
|---|---|---|
| 도형준 | 확보한 카메라의 모델·펌웨어·SDK·Depth profile 기록, PC 캡처 어댑터 | 원본 10프레임 이상 + 정규화 세션 + 실행 방법 |
| 박수용 | 저장 프레임 로더/재생, 유효 Depth·단위 전처리, 카메라 좌표 Point Cloud | 동일 입력의 반복 재생 결과, 기대 좌표/실패 사례 테스트 |
| 이가영 | FeaturePacket → PredictionResult, 모델 없는 상태와 화면 연결 | `not_ready`/실패/합성 성공 fixture를 구분한 출력·UI |
| 강석현 | 본 규격 기준 통합 검토, 카메라별 실측 샘플 승인, 공식 저장소 확정 | 실제 샘플 비교·PR 검토 및 병합 승인 |

기본 환경은 **PC의 Python venv**다. Android 에뮬레이터나 OS 가상머신을 의미하지 않는다. Python **3.11 또는 3.12**, 공용 필수 의존성 **NumPy 2.3.5**. 이 배포본은 Python 3.12.14에서 검증했다. OpenCV/Open3D/YOLO/카메라 SDK는 담당 모듈에서 필요할 때만 추가하고 실제 설치 버전을 기록한다. Android 구현 시 Kotlin 어댑터가 같은 필드·단위로 변환한다. PC 재생 성공과 휴대폰 USB 실연결 성공은 각각 기록한다.

## 2. 단위·좌표계

| 항목 | 확정 규격 |
|---|---|
| Depth | `depth_m`: H×W, float32, **m**, 광축 방향 Z 거리 |
| 유효성 | `valid_mask`: 같은 H×W bool. 유효=finite & >0, 무효 Depth는 **0** |
| 대상 분리 | `target_mask`: 선택 H×W bool, Depth 좌표에 정렬. 출처·버전 필수 |
| 픽셀 | `depth[v,u]`: u=오른쪽, v=아래, 정수 인덱스를 픽셀 중심으로 사용 |
| 카메라 좌표 | X 오른쪽, Y 아래, Z 전방; **m** |
| 내참수 | 실제 Depth profile의 width/height/fx/fy/cx/cy. 픽셀 단위, rectified pinhole |
| 자세 | `p_to = R(quaternion_xyzw) × p_from + translation_m`; 단위 quaternion, m |
| IMU | 각속도 rad/s, 가속도 m/s². IMU 축·카메라 외참수는 별도 기록 |
| 부피 | `volume_m3`: **m³**. cm³ 변환은 ×1,000,000 |
| 중량 | 실측 `ground_truth_weight_g`, 예측 `predicted_weight_g`: **g** |
| 시각 | ns를 **10진 문자열**로 저장. clock_domain/origin과 함께 해석 |

Point Cloud 변환: `X=(u-cx)*Z/fx`, `Y=(v-cy)*Z/fy`, `Z=depth_m[v,u]`. dtype만 보고 mm로 추정하지 않는다. 어댑터는 SDK/profile에서 확인한 `raw_scale_to_m`으로 변환한다. 광선 방향 거리인 입력은 내참수·보정으로 Z 거리로 변환한 뒤 넘긴다. RGB 내참수를 Depth에 사용하거나 미보정 영상을 pinhole로 선언하지 않는다. 미지원 왜곡/보정은 실패로 반환한다.

## 3. FramePacket: 필드와 빈 값

정확한 필드·자료형·필수/nullable 규칙은 `schemas/frame.schema.json`이 기준이다. 모든 키를 보존하며 모르는 값은 null로 채운다. JSON의 NaN/Infinity는 금지한다.

| 그룹 | 내용 |
|---|---|
| 식별 | schema_version, frame_id, session_id, specimen_id(미확보 시 null) |
| 경로 | source_path=`robot`/`mobile_pc_replay`/`mobile_device` |
| 원본 출처 | capture_source=`robot`/`mobile_device`/`pc_camera`/`synthetic`; 재생 시 원본 출처 유지 |
| provenance | real/synthetic, camera(vendor/model/serial/firmware/sdk/profile), raw 파일·SHA-256·단위·변환 계수, 합성 seed/config |
| storage/depth | NPZ 참조와 SHA-256, 배열 key/shape/dtype/unit/semantics |
| intrinsics | Depth 보정값 + calibration_id |
| 시간 | capture_time, host_receive_time, replay_time를 별도 유지 |
| pose/imu | 없으면 null. pose는 camera→world 등 실제 변환. IMU orientation만으로 위치를 생성하지 않음 |
| sync | missing/unverified/verified, residual offset/uncertainty/tolerance/evidence |
| capture_conditions | 카메라 거리, 조명, 재료, 메모. 모르면 null |
| 대상/부피 | target_mask_info, support_plane, volume_request. 미확보 시 null |

`frame_id`는 session 내 유일해야 한다. 예: `cam01_000001`. specimen_id는 동일 물리적 시료의 모든 촬영에서 같아야 한다. 로봇과 모바일이 다른 시료를 같은 ID로 쓰지 않도록 session 생성 시 팀 공용 시료 목록과 연결한다.

### 시간·자세 처리

timestamp 객체는 `{ns, clock_domain, origin}`을 모두 채우거나 모두 null로 둔다. 센서 시각이 없으면 capture_time=null, PC 수신 시각은 host_receive_time에 기록한다. 재생 시 원본 capture_time을 현재 시각으로 바꾸지 않는다. ns 문자열을 JavaScript Number로 변환하지 않는다(BigInt/문자열 사용).

pose.time은 실제 자세 측정 시각이며, 카메라와 다른 시계는 측정한 매핑으로 비교한다. sync.offset_ns는 시계 매핑·보간 후 남은 pose_time−capture_time 오차, uncertainty_ns는 매핑 불확실성 상한이다. verified는 `abs(offset)+uncertainty ≤ tolerance`와 매핑/보간 방법·교정 ID 등의 evidence가 있을 때만 사용한다. 허용치는 실험 요구에 따라 기록하며 임의로 전부 동기화된 것으로 처리하지 않는다.

pose가 없거나 동기화가 미검증이면 **카메라 좌표 단일 프레임 처리**를 진행한다. world 좌표 융합·다중 시점 합성·자세 의존 예측에는 실제 camera→world 보정, capture/pose 시각 및 검증된 sync가 필요하다. 단위행렬 자세·0 위치·가짜 timestamp로 채우지 않는다. IMU camera_to_imu는 별도 외참수이며 IMU 좌표를 카메라 좌표라고 가정하지 않는다.

## 4. 저장 파일

```text
session/
  frames.jsonl
  labels.jsonl              # 실측 확보 후 생성, 추론 로더에서는 읽지 않음
  frame_000001/
    metadata.json
    arrays.npz             # depth_m, valid_mask, 선택 target_mask
  raw/                     # 원본 확보 시 보존, metadata에 경로와 SHA-256
  results/                 # ProcessingResult, FeaturePacket, PredictionResult
```

frames.jsonl의 한 줄: `{"frame_id":"cam01_000001","metadata_path":"frame_000001/metadata.json"}`. metadata_path는 session 상대 경로이며 외부로 벗어날 수 없다. 각 metadata의 arrays.npz는 해당 frame 디렉터리에 둔다. NPZ는 pickle을 사용하지 않고 정해진 배열만 저장한다. 모든 JSON/JSONL은 UTF-8.

원본은 최초 저장하고 덮어쓰지 않는다. 전처리·모델 실행 결과는 config_version/model_id를 포함하여 별도 저장한다. labels.jsonl은 `schemas/label.schema.json`에 따른 시료별 측정값·측정 기기·분해능·방법·근거를 저장한다. ground truth는 학습·평가에서 specimen_id로 결합하며 FeaturePacket/추론 입력에 넣지 않는다. 아직 측정하지 않은 중량을 0으로 입력하지 않는다. 0g은 실제 측정값일 때만 유효하다.

## 5. 공통 인터페이스

카메라 SDK는 어댑터에만 의존한다. 전처리·부피·예측 모듈은 Orbbec/RealSense 객체를 받지 않는다.

| 경계 | 함수/데이터 계약 | 담당 |
|---|---|---|
| 카메라 어댑터 | SDK 원본 → `FramePacket(metadata, depth_m, valid_mask, target_mask=None)` | 도형준, 모바일 어댑터 박수용 |
| 저장/재생 | `load_frame(metadata_path) -> FramePacket`; `iter_frames(session_dir)` | 박수용 |
| 검증 | `validate_frame(frame, require_world_pose=False)` | 공용 기준; reference 제공 |
| 처리 | `process_frame(frame, config) -> ProcessingResult` | 박수용 |
| 특징 | 성공한 부피 결과 → FeaturePacket; feature_version 명시 | 박수용·이가영 |
| 예측 | `predict_weight(features, model) -> PredictionResult` | 이가영 |
| 화면 | PredictionResult 상태별 표시; g 표시는 success일 때만 | 이가영 |

`process_frame`과 `predict_weight`는 구현 담당자의 작업이다. 배포 코드에는 로드·재생·검증·카메라 Point Cloud 기준 계산·부피 사전조건 확인·모델 미준비 결과 생성만 포함한다. 실제 부피/학습 모델을 구현한 것으로 취급하지 않는다.

ProcessingResult 필드: version/frame_id/status/stage/point_cloud/volume_m3/volume_method/assumptions/valid_depth_ratio/provenance_kind/config_version/errors/warnings. Point Cloud 파일은 float32 N×3 `points_m` 배열을 NPZ에 저장하고 파일·key·SHA-256·단위·좌표 frame·point_count를 출력한다. 부피 미계산/실패는 null이며 0을 성공값으로 쓰지 않는다.

FeaturePacket 필드: version/frame_id/specimen_id/volume_m3/volume_method/material/provenance_kind/pose_features/feature_version. 최초 버전 `volume_only_v1`은 양의 부피만으로 학습 가능한 기준 입력이다. 재료를 사용하면 `volume_material_v1`(material 필수), 자세를 사용하면 `volume_pose_v1`(유효 자세로 계산한 tilt_rad 필수)로 명시한다. 근거 없는 pose feature를 채우지 않는다. 각 model_id는 학습 시 사용한 feature_version과 결합한다.

PredictionResult 필드: version/frame_id/status/predicted_weight_g/model_id/feature_version/provenance_kind/quality/quality_policy_id/errors/warnings. success는 nonnegative weight + model_id와 빈 errors가 필요하다. failure/not_ready는 weight=null와 오류 이유를 반환한다. 모델 파일/지원 feature가 없으면 MODEL_NOT_READY/MODEL_INCOMPATIBLE. 품질 판정 기준이 정해지기 전에는 quality=unknown, policy=null. 중량 예측 자체의 성공을 품질 합격으로 해석하지 않는다.

라이브러리 로더의 실패는 ContractError(code,message), 파이프라인 경계에서는 이를 failure 결과로 변환한다. 대표 코드: SCHEMA_INVALID, INPUT_CORRUPT, DEPTH_SHAPE_INVALID, DEPTH_DTYPE_INVALID, DEPTH_VALUES_INVALID, UNIT_UNKNOWN, SEMANTICS_UNSUPPORTED, INTRINSICS_INVALID, NO_VALID_DEPTH, TIMESTAMP_REQUIRED, POSE_REQUIRED, SYNC_UNVERIFIED, TARGET_UNAVAILABLE, SUPPORT_PLANE_REQUIRED, VOLUME_ASSUMPTION_REQUIRED, PLANE_BASIS_INVALID, COVERAGE_INSUFFICIENT, MODEL_NOT_READY, MODEL_INCOMPATIBLE. 상세 메시지는 실제 원인으로 작성한다.

## 6. 부피 계산의 유효 조건

우선 방법은 draft-1의 **높이 적분**이다. Support plane은 카메라 좌표의 `normal·p + offset_m=0`, normal 길이=1. normal은 지지면에서 물체 쪽을 향한다. plane_basis의 u/v는 직교 단위벡터, `u×v=normal`, origin은 지지면 위에 있어야 한다. footprint_polygon_uv_m는 이 basis의 알려진 바닥 영역, grid_pitch_m는 실제 적분 격자 크기다.

알려진 footprint와 전체 윗면 관측, 내부 공동·오버행 등 방법의 제한을 확인한 경우에만 assumptions_confirmed=true로 설정하고 evidence를 기록한다. 대상 mask만의 외접 사각형을 임의 footprint로 쓰지 않는다. 높이는 plane 기준으로 계산하고 셀별 관측 커버리지를 확인한다. 빈 셀·가림·대상 안 invalid depth를 0 높이로 채워 부피를 축소하지 않는다. point count를 부피로 쓰지 않는다. 조건이 맞지 않으면 실패로 반환하거나 별도 방법/버전으로 평가한다. reference의 volume_preflight 통과는 실제 격자 커버리지나 부피 정확도를 검증한 것이 아니다.

## 7. 예제 실행과 검증

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python src/contract.py examples/synthetic
```

합성 입력 raw_mm=`[[1000,1000],[1000,0]]`, scale=.001, fx=fy=100, cx=cy=0. Point Cloud 기대값은 `[[0,0,1],[.01,0,1],[0,.01,1]]` m, 순서는 유효 픽셀의 행 우선 순서다. 대상 mask와 지지면이 없으므로 부피를 산출할 수 없다. 결과 예제의 `features_synthetic.json` 부피는 인터페이스 fixture이고 카메라 입력에서 계산한 실측 부피가 아니다. synthetic 데이터는 UI/연결 테스트에만 사용한다.

`schemas/*.schema.json`은 Draft 2020-12 JSON Schema이다. src/contract.py의 구조 검사기는 **이 배포 스키마에서 사용하는 키워드만** 지원하며 일반 JSON Schema 라이브러리가 아니다. 배열 dtype/shape/finite, 보정·시간·상태의 의미 조건은 추가 검증한다. 테스트 결과는 VALIDATION.md에 기록한다.

## 8. 평가·통합·PR

목표 중량 오차 10%는 실제 실측 g가 있는 real 시료로 평가한다. 양의 실측값에 대해 `APE=abs(pred-true)/true*100`, `MAPE=평균 APE`. MAPE·MAE(g)·RMSE(g)·APE≤10% 비율·전체/성공/실패 시료 수를 함께 보고한다. 0g 시료는 상대오차 제외·MAE/RMSE 포함 여부를 별도 명시한다. synthetic·모델 미준비 결과는 정확도 집계에서 제외한다. 동일 물리 시료의 프레임이 train/test에 섞이지 않도록 specimen_id 기준으로 분리한다. 데이터셋과 평가 split 버전을 보존한다.

공식 저장소 URL은 아직 확정되지 않았다. 개인 백업 저장소를 공식 저장소로 지정하지 않는다. 공식 저장소가 준비되기 전에도 이 문서·ZIP 기준으로 로컬 구현을 시작할 수 있다. 저장소가 확정되면 `docs/contract/`, `src/ingest/`, `src/processing/`, `src/prediction/`, `tests/`로 이관한다.

팀 기준 브랜치: `main`=검토 완료 기준본, `develop`=통합, `feature/ade-번호-설명`=개별 작업. PR 대상 develop, 최종 발표 기준본은 강석현 승인 후 main 반영. 공유 브랜치 직접 push 금지. 모든 통합 PR은 강석현 검토를 거친다. PR에는 이슈, 입력/출력 예제, 재현 명령, 실제/합성 구분, 단위·빈 값·실패 테스트, SDK/환경 버전을 넣는다. 필드/단위/의미 변경은 기존 v1 데이터를 깨지 않도록 새 버전과 migration을 먼저 검토한다.

## 9. 남아 있는 확인

- ADE-63: 공식 저장소 소유자·URL·실제 브랜치 설정, 카메라 현물 모델/펌웨어/SDK/profile 확인.
- ADE-69: 카메라별 실제 샘플 단위·내참수·재생값 승인. synthetic 테스트로 대체하지 않는다.
- 실제 휴대폰 OTG/전력/SDK 지원·USB 입력, 로봇 외참수/실동작, 로드셀 측정은 장비 확보 이후 각 이슈에서 검증.
- Astra Mini·Mini Pro는 최신 이슈의 사용자 전달 장비명이다. 제조사 공용 어댑터 계약만 확정하고 firmware에 맞는 SDK를 선택한다. Orbbec SDK v1/v2의 지원 기기/프로토콜 표를 확인하고 펌웨어를 임의 변경하지 않는다.

## 근거 문서

- [박수용 draft-1 제안](https://github.com/psy0635-ctrl/injidong-depth-review/blob/codex/ade-54-ade-55-migration-review/docs/reviews/common-contract-proposal.md) — 검토한 파일 SHA: `90c9f9e5f67602062b6fa4ea5ce975fce3951e4e`.
- [Orbbec SDK v1](https://github.com/orbbec/OrbbecSDK), [SDK v2](https://github.com/orbbec/OrbbecSDK_v2), [Python wrapper 릴리스](https://github.com/orbbec/pyorbbecsdk/releases), [OpenNI SDK](https://www.orbbec.com/developers/openni-sdk/) — 장비별 실제 지원 확인에 사용.
