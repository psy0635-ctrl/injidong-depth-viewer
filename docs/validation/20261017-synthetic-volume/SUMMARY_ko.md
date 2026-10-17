# 합성 높이 적분 실험 이동 검증

기준 커밋은 bf204354a6eccf515e1ee25bcadd00cdf680358c다. 기존 점군 분석/RGB 호환/공통 src·스키마·사전조건·결과 계약은 변경하지 않았다. 별도 폴더에서 작성한 synthetic 전용 적분기·fixture·테스트·저장형 검증을 [실험 도구](../../../experiments/synthetic_volume/README.md)로 정리했다. 이 문서는 공개 후보 정리 당시의 검증 이력이며, 그 단계에서는 stage/commit/push/PR/병합을 수행하지 않았다. 아래 수치·실행 횟수는 당시 기록이며 후속 작업의 재실행 결과가 아니다.

후속 보관·검토 상태: 합성 실험은 [6908d763 커밋](https://github.com/psy0635-ctrl/injidong-depth-viewer/commit/6908d7636a6c95501a9bd0dd130e2a81b5c91bea)에 보관됐고 [Draft PR #3](https://github.com/psy0635-ctrl/injidong-depth-viewer/pull/3)에 runner·RGB 호환·점군 도구와 함께 포함된다. 개인 원격 보관·Draft 검토는 main 병합·팀 승인·공용 통합·실제 정확도 검증 완료를 뜻하지 않는다.

## 코드 출처와 변경

| 원본 역할 | 공개 후보 파일 | 이동 변경 |
|---|---|---|
| synthetic_volume.py | experiments/synthetic_volume/synthetic_volume.py | analyze와 개발 정책/수치 허용치 유지; baseline 로더만 공통 경계 재사용 |
| synthetic_fixtures.py | experiments/synthetic_volume/synthetic_fixtures.py | start.json 의존 제거, 명시적으로 로드한 contract.ROOT의 합성 template 사용 |
| tests/test_synthetic_volume.py | experiments/synthetic_volume/tests/test_synthetic_volume.py | 원래6개 유지, baseline/output CLI와 이동 경계 회귀5개 추가 |
| run_synthetic_validation.py | experiments/synthetic_volume/run_synthetic_validation.py | 새 출력 아래 생성/저장/로딩/결과 검증, 전후 해시, 실행 환경과 실제 import 경로 기록 |
| 기존 도구의 공통 경계 | experiments/synthetic_volume/_boundary.py | 원래 저장소 helper를 경로로 재사용, processing 스키마/합성 template 두 핀 추가 |

README/requirements와 이 요약은 새 문서다. baseline 원본이나 과거 상세 로그/저장 입력은 반입하지 않았다. analyze·POLICY/허용치 및 원래6개 test 메서드의 AST를 원본과 대조했다. 적분 알고리즘이나 승인 조건을 완화하지 않았다.

## 새 위치에서 실행한 검증

Python3.11.9 / NumPy2.3.5 / Windows의 기존 환경을 사용했다. 설치·업그레이드는 없었다.

- 전용 테스트1회: **11 pass, failure0, error0, skip0, 종료0**. 원래6개와 회귀5개다. 출력 중첩/기존 경로/실제 Windows junction 별칭, baseline 핀 변조, 충돌 import, CLI 필수 인자/실패 보고, 저장형8사례·단위·null, synthetic packet의 real 표시 거부를 포함한다.
- 독립 저장형 CLI1회: **8사례 기대 일치, 종료0**. 회귀 테스트 내부에서도 저장형8사례를1회 실행했다. 테스트11개와 저장형8사례를 고유19개라고 합산하지 않는다.
- 전용 테스트와 저장형 CLI의 초기 실패나 재시도는 없었다. 이전 원본의 테스트/CLI 수정 이력과 이번 실행을 구분했다.
- 정상/실패 입력의 배열·표본·가정을 저장 후 pickle 없이 재로딩하고 dtype/shape/전체 값을 대조했다. 정상은 baseline load_frame, 잘못된 plane은 예상 로더 거부 기록 후 저장된 음성 FramePacket의 preflight 실패를 확인했다. 결과 JSON도 재로딩해 기존 ProcessingResult 계약 및 부피/null·상태·단위를 확인했다.

정답은 독립 치수 곱 0.02m×0.03m×0.01m = 0.000006m³ = 6cm³다. float64 치수 곱의 표현은 5.999999999999999e-6m³다. 절대 허용치는1e-15m³, 상대0으로 실행 전에 고정했다.

| 저장형 사례 | 결과 | 부피(m³) 또는 오류 |
|---|---|---|
| A_known_cuboid | success | 6.000000000000006e-6 |
| B_duplicates_reordered | success | A와 정확히 같음 |
| C_missing_cell | failure, volume/method null | COVERAGE_INSUFFICIENT |
| C_invalid_target | failure, volume/method null | COVERAGE_INSUFFICIENT |
| D_bad_plane | failure, volume/method null | PLANE_INVALID |
| D_bad_basis | failure, volume/method null | PLANE_BASIS_INVALID |
| D_unconfirmed | failure, volume/method null | VOLUME_ASSUMPTION_REQUIRED |
| E_cell_boundary_unsupported | failure, volume/method null | CONFIG_INVALID |

정상 두 사례의 절대 오차는6.776263578034403e-21m³다. 6표본을11표본으로 중복/재정렬해도6셀과 부피가 그대로다. 누락·invalid를 높이0으로 채우지 않았다.

기존 원본의 최종6개 테스트 통과·저장형8사례 통과 기록은 이전 구현의 근거로만 읽었다. 위 수치와 실행 횟수는 새 위치의 실행 기록에 근거한다. 실제 세션·모바일 검사·raw 검사·runner·실제 점군/렌더링/뷰어·전체 프로젝트 테스트는 이번에 실행하지 않았다.

## 가정·한계·공개 범위

직사각형 footprint·정수 개의 정사각 셀·셀 중심 표본·coverage100%·셀별 최대 normal 높이×셀 면적 합만 지원하는 개발 정책이다. 양의 높이·알려진 지지면/basis·단일값의 꽉 찬 기둥·공동/오버행 없음·전체 윗면 관측을 합성 가정으로 요구한다. 임의 다각형/부분 셀/비중심 표본/가림을 근사하지 않는다. 거리 m, 면적 m², 부피 m³다. 실패 부피는 null이며0으로 대체하지 않는다.

팀 정책 승인·실제 카메라/찰흙/중량 정확도 검증이 아니다. SDK 보정·65535 의미/정책·RGB 정렬·실측 오차·현장 footprint/coverage/격자 pitch/최대값 편향은 미확인이다. 기존 pipeline의 VOLUME_NOT_IMPLEMENTED를 교체하거나 실제 처리 차단을 해제하지 않았다.

geometry_verified / processing_ready / viewer_launched / sdk_values_independently_verified / common_framepacket_fully_validated는 모두 false다. 합성 fixture의 assumptions_confirmed는 이상적 합성 조건의 입력이며 실제 세션 승격이 아니다.

공개 후보는 소스/결정적 생성기/합성 테스트/README/NumPy 의존성/이 요약8파일이다. 실제 촬영본·raw/RGB/점군/PNG·전송 ZIP/bundle·baseline/venv/cache·인증정보·개인 PC 경로와 상세 로그를 포함하지 않는다. 새 실행 로그·합성 저장 입력·결과는 저장소 밖 작업 폴더에만 남겼다. 원본 보존 범위는 실제 읽은19개 참조 파일의 전후 해시와 기준 저장소 Git 상태이며, 과거18/31/759파일 전체 검사를 재실행한 것은 아니다.
