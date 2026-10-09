# ADE-95 저장 Depth·Point Cloud 독립 뷰어

카메라 없이 v1.0.0 저장 세션을 읽어 Depth와 카메라 좌표 3D 점군을 확인하는 PC 뷰어다. ADE-95 범위는 세션 로드, 프레임 이동, 정보 표시, 오류 안내, PNG·전체 점군 저장과 재현 방법이다. **실제 기기·부피·중량 검증, 팀장 승인 및 공식 통합은 미완료**다. USB·Android 기능은 포함하지 않는다.

## 기존 환경과 실행

현재 작업 폴더는 `C:\study\injidong_contract_v1`이다. 기존 `.venv\Scripts\python.exe`를 사용한다. 의존성은 `requirements-viewer.txt`의 NumPy 2.3.5와 Matplotlib 3.10.8이며, 설치 버전 목록은 `requirements-viewer.lock.txt`에 있다. Python 3.11/3.12 환경이 기준이다. 이번 보완에서 설치·업데이트·DLL 교체·venv 재생성을 수행하지 않는다.

```powershell
Set-Location -LiteralPath 'C:\study\injidong_contract_v1'
& .\.venv\Scripts\python.exe -X utf8 src/viewer.py examples/viewer_multiframe --output outputs/demo_gui
$LASTEXITCODE
```

ZIP을 별도 위치에 풀었을 때는 압축 해제된 `injidong_ade95` 폴더로 이동한다. ZIP에는 `.venv`가 없으므로 위 로컬 실행 파일을 절대 경로로 지정할 수 있다. 다른 PC의 새 환경 구축은 이번 보완에서 검증하지 않았다.

```powershell
Set-Location -LiteralPath '<압축 해제 위치>\injidong_ade95'
& 'C:\study\injidong_contract_v1\.venv\Scripts\python.exe' -X utf8 src/viewer.py examples/viewer_multiframe --output '<새 출력 폴더>'
$LASTEXITCODE
```

## 조작과 저장

- `Previous / Next`, ←/→ 또는 P/N으로 프레임을 이동한다.
- 3D 영역에서 왼쪽 드래그로 회전, 오른쪽 드래그로 확대·축소한다. 도구 모음의 Home으로 기본 시점에 돌아간다.
- S 또는 `Save PNG + full NPZ` 버튼으로 새 결과 폴더에 저장한다.
- PNG는 **기본 재현 시점**으로 저장된다. GUI에서 회전한 현재 시점 그대로를 저장하지 않는다.
- 표시 점 수를 제한해도 `points.npz`에는 전체 점군을 저장한다. 원본 입력과 기존 결과를 덮어쓰지 않는다.

## 좌표·단위 설명 5줄

1. `depth_m[v,u]`는 광축 Z 방향 거리이며 float32 H×W, 단위는 m이다.
2. 유효 값은 finite & >0이며 무효 Depth는 0, 같은 크기의 `valid_mask`는 bool이다.
3. 픽셀 u는 오른쪽, v는 아래쪽이고 정수 인덱스를 픽셀 중심으로 사용한다.
4. 카메라 X는 오른쪽, Y는 아래쪽, Z는 전방이며 `X=(u-cx)Z/fx`, `Y=(v-cy)Z/fy`, `Z=depth_m[v,u]`다.
5. 점군은 float32 N×3 `points_m`, m 단위·유효 픽셀 행 순서이며 검증된 pose·sync 없이 world·다중 시점 결과를 만들지 않는다.

## Depth·3D 화면 예제

기존에 저장한 세 번째 합성 프레임의 화면을 재사용한다. 실기기 정확도 결과가 아니다.

![세 번째 합성 프레임의 Depth와 카메라 좌표 3D 점군](outputs/ade95_final_user_saves/frame_000003_1791460557654228600/preview.png)

## 저장 결과 검증

결과 폴더만 지정하는 기존 명령은 파일 구조·해시 검사를 수행한다. **입력 좌표 비교는 미실행**이며 `coordinates_verified=false`, `input_coordinate_validation.status=not_run`으로 표시한다. 감사 기록의 과거 `input_session` 절대 경로를 자동으로 신뢰하거나 frame_id 문자열에서 좌표를 추정하지 않는다.

입력 좌표까지 검증하려면 `--session`을 명시한다. 실제 입력의 같은 frame_id를 찾아 기존 로더·검증기·`point_cloud_camera`로 계산하고, 전체 점군의 dtype·shape·점 개수·행 순서·좌표 및 전체 입력 metadata를 비교한다. 동일한 float32 기준 함수로 저장·재계산하므로 **`numpy.array_equal`, 허용 오차 0(`rtol=0`, `atol_m=0`)**을 사용한다.

```powershell
# 기본 합성 프레임의 전체 입력 대조
& .\.venv\Scripts\python.exe -X utf8 scripts/verify_viewer_outputs.py outputs/ade95_final_synthetic --session examples/synthetic
$LASTEXITCODE

# 실제 사용자 저장 세 번째 프레임 2건의 전체 입력 대조
& .\.venv\Scripts\python.exe -X utf8 scripts/verify_viewer_outputs.py outputs/ade95_final_user_saves/frame_000003_1791460557654228600 --session examples/viewer_multiframe
$LASTEXITCODE
& .\.venv\Scripts\python.exe -X utf8 scripts/verify_viewer_outputs.py outputs/ade95_final_user_saves/frame_000003_1791460742554215400 --session examples/viewer_multiframe
$LASTEXITCODE

# 파일 무결성만 검사: 좌표 검증 완료를 뜻하지 않음
& .\.venv\Scripts\python.exe -X utf8 scripts/verify_viewer_outputs.py outputs/ade95_final_synthetic
$LASTEXITCODE
```

ZIP에는 원래 `outputs/demo_gui` 대신 바이트 동일한 `outputs/ade95_final_user_saves` 복사본이 포함된다. 로컬 원래 결과를 검사할 때는 결과 경로만 `outputs/demo_gui/...`로 바꾸고 같은 `--session`을 사용한다.

명시한 입력이 없거나 frame_id가 없고, metadata·점군이 다르면 종료 1과 원인을 반환한다. `artifact_validation`은 파일 무결성, `input_coordinate_validation`은 실제 입력 대조 결과다. 전체 성공이어도 입력 미지정 시 좌표 검증 성공으로 해석하지 않는다. 인자 오류는 종료 2다. `--original-inventory`는 유지하며 원래 로컬 작업 폴더용이다. 새 ZIP만 풀었을 때는 제출물 밖 파일을 참조하는 목록을 지정하지 않는다.

## 배포 스키마와 기록 구분

버전 키는 `schema_version="1.0.0"`이다. 시간 객체는 필수이고 시각을 모르면 `{"ns":null,"clock_domain":null,"origin":null}`을 유지한다. `pose`·`imu`는 없으면 null이다. 원본 문서 요약의 `version`·`capture_time=null` 표현과 차이가 있지만 배포 스키마를 따르며 공통 규격을 변경하지 않았다.

이전 검토 증거는 새 검토 로그 폴더의 `previous_review`에 복사해 보존하고 이번 수정 후 실행과 구분한다. 과거 ADE-66·67 로그도 새 패키지에 포함한다. 기존 자동 GUI 검사와 사용자 실행·저장 기록은 과거 근거이며 이번 보완에서 GUI 코드는 변경하지 않는다. 사람의 직접 회전·확대·버튼·방향키 성공과 직접 종료 코드는 미확인이다.

자세한 오류 정책·결과 구조·1분 시연 대본은 [상세 사용·검증 문서](docs/ADE-95-독립뷰어-사용검증.md)를 참고한다.
