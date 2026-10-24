# ADE71 저장 Depth 파이프라인 활성 통합

2026-10-24. 10/14 제출 ZIP에만 들어 있던 PC 파일 처리 구현을 활성 `src/`와 `tests/`에 통합했다. 원본은 기존 게시 자료 `submissions/ade71-20261014/ADE-71_session_fixed_20261014_6fe5b71e259e.zip`의 정확한 `src/` 파일이다. `protected_reference/src/contract.py`는 과거 보호 원본이며 활성 구현과 구분한다.

`session_pipeline`, `session_boundary`, `session_auxiliary`, `depth_preflight`와 관련 회귀를 활성화했다. `contract.py`와 `viewer_data.py`는 기존 수학을 유지하면서 로더·캐시packet·재생의 완료/경로 검사를 연결했다. schema5개와 depth단위(m)/광축Z/좌표수학은 바뀌지 않았다.

기존 `tools/mobile_session_intake/baseline_hashes.json`의 세 파일 hash는 이 활성 contract/boundary/frame.schema와 같으므로 그대로 유지한다. 모바일 검사 도구의 처리 보류는 이 통합으로 해제되지 않는다.

## 실행

현재 저장소 루트에서 Python 3.11/3.12의 기존 환경을 사용한다. `python`은 선택한 환경의 실행 파일로 바꿀 수 있다. 기본 파이프라인에는 NumPy, 보조 PNG 검사에는 Pillow가 필요하다.

```powershell
# 기존 합성 예제로 변환·전체 저장값 대조·재독 10회
python -B -X utf8 src/session_pipeline.py `
  --basis examples/ade71_session_intake/synthetic/basis.json `
  --output-root ../pipeline-results --repeat 10 `
  --expected-points examples/ade71_session_intake/synthetic/expected_points.json

# 독립 검증: 합성 전체 점군·module import·RGB/annotation 파일 연결
python -B -X utf8 scripts/validate_ade71_zip_fixes.py `
  --output-root ../pipeline-verification --regressions

# 새 합성 intake 생성. 기존 경로에는 덮어쓰지 않는다.
python -B -X utf8 scripts/make_ade71_session_intake.py --output ../new-synthetic-intake
```

검증 스크립트에 `--archive`를 주지 않으면 실제 D405 확인은 `d405.status=not_run`이다. 합성 성공을 실제 입력 통과로 집계하지 않는다. output은 입력/코드와 분리한 새 경로를 사용한다.

## 외부 원본 D405를 확인하는 경우

과거10프레임 D405 원본 ZIP을 별도 전달받아야 한다. 이 통합에는 raw ZIP/실촬영 배열을 중복 추가하지 않았다. 명시한 원본은 receipt의 ZIP/member hash와 맞아야 하며 capture 코드를 실행하지 않는다.

```powershell
python -B -X utf8 scripts/validate_ade71_zip_fixes.py `
  --output-root ../pipeline-verification-real `
  --archive ../received/depth_original.zip `
  --receipt docs/inputs/ade71-d405-20261013.json `
  --basis examples/ade71_session_intake/d405_blocked/basis.json
```

기존 receipt/basis는 과거10프레임 촬영본의 것이다. 다른 촬영은 hash·frame대응·profile·scale·보정 근거가 연결된 새 인수 자료를 사용한다. 기존 blocked basis로는 준비 후 정식 변환이 `INTAKE_BLOCKED`/종료1이고 정상 manifest/점군이 없어야 한다. 이 예상 차단을 감독하는 검증 스크립트 자체는 종료0이 될 수 있으므로 내부 `d405` 결과를 함께 읽는다.

65535의 의미, 정밀 Depth내참수, rectification, 장비/profile/calibration·단위 근거가 없으면 이를 생성하거나 승인하지 않는다. 촬영/수신시각·specimen/pose의nullable은 그대로 유지한다.

## 완료 기록과 보호 경계

새 managed run은 최종 `.ade71-complete.json`이 validation/manifest/processing 해시와 연결된 뒤 공개로 읽힌다. `validation.json`이나 `processing.json`의 성공문자열만으로 완료로 판정하지 않는다. 지원 loader는 완료 전·실패한 공개 파일, 캐시된packet, pending결과를 거부한다. 외부 legacy core세션은 producer의marker를 강제로 요구하지 않는다.

원본hash/scale/path에 대해 직접 API와 CLI가 같은 검사 함수를 사용한다. 입력·출력의동일/자식/부모방향 겹침, 절대/drive/UNC/ADS/상위경로를 거부한다. 이는 파일완료·출처연결 검사이며 물리보정승인·인증/서명·전원차단durability보장이 아니다.

## 이번에 바꾼 실행 경로

- 합성생성CLI는 `--output`필수다. 과거 실행 폴더에 고정된D405원본복사함수는 제거하고 실제준비는 `prepare_d405_intake.py --archive`로 분리했다.
- 원본준비CLI는 `--archive`필수다. receipt/basis는 명시해 바꿀 수 있고 임의Downloads검색을 하지 않는다.
- 검증CLI는 `--archive/--receipt/--basis`로 외부입력을 받는다. 원본미제공은 명시적으로미실행이며, 임의사용자경로fallback이 없다.
- 10/20 이후 GUI/모바일/바닥·ROI·서버기능과실제승인판정은 각자료의 별도범위다. 이 문서의파이프라인활성화를 프로젝트전체완료로해석하지 않는다.
