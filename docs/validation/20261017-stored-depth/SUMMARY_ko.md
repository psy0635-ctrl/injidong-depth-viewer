# 저장 Depth 점군 대조·정적 시각화 코드 이동 검증

기준 커밋: e5f7bf9c54d751a03e8acb272aaf1ba05391eb9b. RGB 인덱스 호환의 개인 검토 커밋 위에 별도 로컬 브랜치로 코드를 정리했다. 팀 승인/공용 통합은 별도 미완료다.

## 원본에서 가져온 코드와 수정

| 원본 역할/파일 | 저장소 대상 | 변경 이유 |
|---|---|---|
| 점군 대조 작업/compare_stored_depth.py | tools/stored_depth_analysis/compare_stored_depth.py | start.json·고정 프레임/개수 의존 제거, 명시적 CLI, 수치 계산은 유지 |
| 점군 대조 작업/tests/test_stored_array_comparison.py | tools/stored_depth_analysis/tests/test_stored_array_comparison.py | 원래3개 수치 사례 유지, 코드 밖 출력·명시적 baseline·경계 사례 추가 |
| 정적 작업/make_static_figures.py | tools/stored_depth_analysis/make_static_figures.py | 원래 렌더링 코드 재사용, 기존 NPZ/보고서/세션 명시, frame/해상도별 표시값 정리 |
| 두 도구의 경로·읽기·baseline 경계 | tools/stored_depth_analysis/_common.py | 중복 경계 한곳으로 정리, 기존 baseline 해시 재사용 |

README/requirements는 새 공개용 문서다. 합성 테스트는 알려진 비대칭 내참수·invalid 픽셀·synthetic Z16/sidecar를 실행 출력 폴더에서 생성한다. 실제 입력을 저장소로 반입하지 않는다. 사용법은 [도구 README](../../../tools/stored_depth_analysis/README.md)를 따른다.

## 이번 이동 후 검증

- 환경: Python3.11.9 / NumPy2.3.5 / Matplotlib3.10.8 / Pillow12.3.0 / Windows / Agg.
- 최종 전용 테스트10개: pass10, failure0, error0, skip0. 기존 전체 프로젝트 테스트·모바일 검사·runner/raw 검사는 재실행하지 않았다.
- 초기 전용 테스트는 pass8/failure1/error1이었다. 시각화 함수 분리 후 남아 있던 지역변수 참조를 수정했다. 해시 불일치 테스트는 새 출력이 잘못된 NPZ의 부모에 중첩돼 경계에서 먼저 거부되었으므로 시험 데이터 폴더를 분리했다. 실패 로그는 비공개 외부 작업 경로에 보존했다.
- 실제0042 이동 후 대조1회·종료0. 실제 정적 시각화1회·종료0. 과거 원본 실행 횟수와 별개다. 실제 실행 재시도는 없다.
- 독립 기대값/좌표 대조/NPZ 왕복 함수3개의 AST가 원본과 동일함을 확인했다. 반올림 허용치나 기존 기대 수치를 완화하지 않았다.

| 항목 | 이동 후 결과 |
|---|---:|
| 전체 점 | 255,349 |
| points_m/pixel_vu | 이전 결과와 dtype/shape/전체 배열 정확 일치 |
| X/Y/Z 최대 절대 오차(m) | 2.1852288867307834e-7 / 1.4836207729018724e-7 / 0 |
| 고정 절반 float32 ULP 초과 성분 | 0 |
| 독립 float64 기대값의 최종 float32 캐스트 | 전체 정확 일치 |
| raw65535 대응 | 119개 전체 픽셀/행 대응 및 valid 보존 |
| 정적 표시 점 | 50,098(대응119개 전부 포함) |
| Depth 기본 색상 범위(m) | 0.2655999958515167~6.553499698638916 |
| 보조 색상 범위(m) | 0.2655999958515167~2.200899839401245 |

시각화는 이전 결과와 색상 범위·표시 수·raw 표시·전체 bbox/축 범위·정사영/시점·단위 축척을 대조했다. PNG 해시 동일성만을 성공 기준으로 삼지 않았다. 저장 PNG3개를 디코딩한 뒤 직접 열어 한글·축·범례·색상바·미검증 문구를 확인했다. 동적 해상도용 픽셀 눈금 정수 배치 때문에 과거 고정 눈금과 일부 숫자가 다를 수 있으나 좌표 범위/표시 데이터는 같다.

## 공개 포함/제외

포함: 새 도구 코드3개, 원래 사례를 유지한 테스트1개, README/requirements, 이 수치 요약. 실제 촬영본을 사용하지 않는 합성 생성 예제는 테스트 안에 있다.

제외: 실제 입력/원본 raw/RGB/Depth/전체 점군 NPZ, 실제 파생 PNG3개와 상세 JSON, 전체 실행 로그·개인 경로·카메라 식별정보·샘플별 대응, ZIP/bundle/baseline/venv/cache, 합성 부피 코드. 실제 파생 이미지의 사람/화면/식별정보 공개 가능성을 확정할 수 없어 images 폴더에 넣지 않았다. 원본 이미지를 수정하거나 삭제하지 않았다. 공개용 요약은 수치와 코드 범위만 옮겼다.

geometry_verified / processing_ready / viewer_launched / sdk_values_independently_verified / common_framepacket_fully_validated는 모두 false다. 계산 일치는 SDK/왜곡 보정/65535의 물리 의미/거리 정확도/팀 정책 승인과 다르다. 정적 PNG는 GUI 뷰어 실행이 아니다.

이번 변경은 commit/push/PR/merge 전 로컬 검토 상태다. 실제 데이터 공개에 대한 판단이나 원격 CI 성공은 주장하지 않는다.
