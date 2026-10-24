# 모바일 ZIP · PC 검토 앱

기존 ADE-95 `src/viewer.py`와 별도 진입점이다. 저장소의 core/viewer/접수 검사기를 재사용한다. Python **3.11 또는 3.12**, NumPy2.3.5, Matplotlib3.10.8, Pillow12.3.0, Tcl/Tk가 필요하다. SDK/Open3D/서버 설치는 필요 없다.

아래 명령은 Python의 `>>>`가 아닌 **Windows PowerShell**에 입력한다. 저장소를 연 뒤 README.md가 있는 루트를 현재 폴더로 삼는다. `.venv`가 이미 정상이라면 재생성·재설치하지 않는다. 새 PC에서는 기존 ADE-95 [설치 안내](../../README-viewer.md)를 따라 Python3.11/3.12+Tk로 `.venv`를 만든 뒤 다음 의존성을 설치한다.

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r 'apps/local_review/requirements.txt'
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -B -X utf8 'apps/local_review/run_review_viewer.py' --mobile
```

설치 명령은 새 환경 준비용이다. 이 게시 작업에서는 기존 정상 환경을 재사용했다. Linux/macOS에서는 대응하는 환경의 `python`을 사용하며 GUI에는 표시 서버/Tk가 필요하다.

## 원본 없이 확인: 합성 ZIP

```powershell
$reviewRun = Join-Path (Get-Location) ('../review-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $reviewRun -ErrorAction Stop | Out-Null
$reviewZip = Join-Path $reviewRun 'synthetic-mobile.zip'
& '.\.venv\Scripts\python.exe' -B -X utf8 'apps/local_review/make_synthetic_demo.py' --output $reviewZip
# 출력의 session_id / zip_size_bytes / zip_sha256은 생성한 합성 입력의 식별값이다.
& '.\.venv\Scripts\python.exe' -B -X utf8 'apps/local_review/run_review_viewer.py' --mobile-zip $reviewZip
```

합성 세션은 32×24 두 프레임의 기울어진 표면이다. 프레임 선택→`Depth 지지면 후보 지정`→Depth에서 넓은 평면 후보 사각형 지정→검토 ROI 생성/이동/핸들 수정→저장으로 조작할 수 있다. 이 입력은 파일·HTTP·GUI·저장 프로토콜 시험용이며 실제 거리/부피/중량·물리 바닥·RGB 정렬을 검증하지 않는다. RGB는 점군에 입히지 않는다.

## 승인된 실제 ZIP

`--mobile-zip`에 별도 전달받은 ZIP 경로를 지정한다. 파일 대화상자로 열 수도 있다. 원본 촬영 ZIP은 이 저장소에 새로 게시하지 않았다. 10/24 로컬 검토의 기준은 다음과 같다.

| 항목 | 기준 |
|---|---|
| 이름 | 0.5.0data_sample (1).zip |
| session_id | d405_1792497323680 |
| ZIP bytes | 3354368 |
| SHA-256 | 72f3ebaff4c6fcb57675e702aca0854eeec162ce0de4f86b4b80de381cd07dff |
| 대표 프레임 | d405_0000000017 |
| 기준 수동 ROI 전체 선택 | 42897점, 선택ID SHA438fd2c375357d322f09d79ea2d517e0ad2493329a7a8aba37aff148c750b736 |

원본과 개인 수동 ROI는 보유자에게 별도로 받아야 한다. 같은 개수만으로 같은 ROI라고 판정하지 않는다. ZIP 크기와 SHA는 `Get-Item -LiteralPath $reviewZip` / `Get-FileHash -LiteralPath $reviewZip -Algorithm SHA256`으로 확인할 수 있다. 외부 기대값을 검증하는 Python API는 `verified_mobile_zip.load_verified_mobile_zip(path, expected_session_id, expected_size_bytes, expected_sha256, cache_root)`이며, 성공 반환 세션은 반드시 `close()`한다. 기대값은 수신 파일에서 다시 계산해 대체하지 않는다. HTTP에서는 독립 목록 레코드가 기대값을 제공한다.

## ROI·화면·원본 참조

- 기본 프레임 화면의 viridis 색은 **Depth Z 가짜 색**이다. ROI 화면은 회색 단색·선택 자홍색이다. 모바일 실제 RGB 색/픽셀 정렬이 아니다.
- 후보 평면 정사영은 검증된 바닥/중력/세계 좌표가 아니다. 사각형은 주변 바닥을 포함할 수 있는 **검토 범위**이며 찰흙 정답 마스크·부피 footprint가 아니다.
- 왼쪽 드래그는 ROI 생성, 내부 드래그는 이동, 핸들은 크기 변경, Esc는 해제다. 오른쪽 3D는 왼쪽 버튼 드래그로 회전한다. 휠 확대·표시점 수는 전체 선택을 바꾸지 않는다. 도구모음 pan/zoom을 해제한 뒤 ROI를 편집한다.
- 전체 원본/전체 선택과 표시점/표시 선택을 구분한다. 표시 Z 범위가 바뀌면 표시 선택 수도 달라질 수 있다.
- 새 저장은 `apps/mobile_roi_outputs/run_*/exports/roi_*` 아래 고유 폴더를 만든다. 폴더 전체를 보존한다. 모바일 CLI의 `--output-dir`는 모바일 경로 설정이 아니므로 사용하지 않는다.
- 재열기는 같은 바이트 ZIP을 먼저 열고 같은 프레임을 선택한 뒤 `현재 프레임 ROI 재열기`에서 실제 `roi_*` 폴더를 선택한다. 저장 basis·원본 ZIP 및 내부 파일 해시·선택 ID를 다시 검증하며 새 후보 fit으로 대체하지 않는다.
- schema_version="1.0.0", 원본 ID·단위·좌표·보정·시각 출처는 유지된다. pose/sync·측정값이 없으면 성공값을 생성하지 않는다.

## 시험용 HTTP 서버와 클라이언트

실제 서버 인수 자료는 미확보다. 다음 서버는 **loopback 시험 fixture**이며 업로드/저장 서버 구현이 아니다. 첫 PowerShell에서 위 합성 ZIP 생성 후 실행한다.

```powershell
$fixtureState = Join-Path $reviewRun 'fixture'
New-Item -ItemType Directory -Path $fixtureState -ErrorAction Stop | Out-Null
Set-Content -LiteralPath (Join-Path $fixtureState 'mode.json') -Value '{"mode":"good"}' -Encoding ascii
& '.\.venv\Scripts\python.exe' -B -X utf8 'apps/local_review/tests/http_fixture.py' `
  --serve $fixtureState --archive $reviewZip --session-id synthetic_mobile_demo
# 시연 종료 시 이 서버 프로세스의 입력에만 Enter. 다른 서버는 종료하지 않는다.
```

별도 PowerShell에서 `Get-Content -LiteralPath '<이번 fixture 폴더>/ready.json'`의 실제 base_url을 읽고 앱의 서버 주소에 입력한다. 과거 포트를 추측하지 않는다. 합성 fixture의 Bearer는 공란, 개발 HTTP 체크는 해제 상태다. `목록 조회`→행 선택→`선택 ZIP 검증 후 열기`로 ID/크기/SHA와 로더가 연결된다. `다음 페이지`는 opaque cursor를 한 번 전달한다.

다운로드와 로더 임시 사본은 성공 세션 소유이며, 세션 교체/앱 종료 시 정리된다. ROI는 영구 출력이므로 따로 유지된다. 종료 후 다시 열려면 동일 ZIP 재다운로드 또는 따로 보관한 동일 원본 ZIP이 필요하다. 실패/취소는 정상 세션·미저장 ROI를 유지하고, 성공 새 로드는 기존 편집을 교체하므로 먼저 저장한다.

실서버의 origin·접속 네트워크·실제 JSON/OpenAPI·인증 전달 방법·적용 한도·시험 ZIP·공동 시각을 확보해야 한다. [임시 API 프로필](../../docs/PC_HTTP_PROFILE_ko.md)은 실제 서버 계약 일치 검증이 아니다. 시험 전용 X-Test-Fixture/TEST_HTTP_ERROR는 실제 서비스 요구사항이 아니다. 토큰은 GUI 메모리에만 입력하며 코드/URL/문서/명령/로그에 쓰지 않는다.

## 기존 로봇 저장 RGB 경로

로봇 단일 프레임은 저장된 depth-grid 정렬 RGB·보정/frameset 증거를 검사한 뒤 연결하는 별도 조건부 경로다. 원본을 포함하지 않으므로 `INJIDONG_ROBOT_REVIEW_ROOT`에 승인된 외부 검토 묶음(path_map.json 포함)을 명시해야 한다. 알려진 PC 폴더로 fallback하지 않는다. 앱은 RGB resize/새 정렬/새 보정값 생성을 하지 않는다. 정렬 물리 정확도는 별도 미검증이다.

## 검증

```powershell
# 저장소 루트. 각 suite는 새 Python 프로세스에서 실행된다.
& '.\.venv\Scripts\python.exe' -B -X utf8 'scripts/run_checks.py'

# 승인된 기준 ZIP이 있는 경우에만 별도 실입력 검사 활성화
$referenceZip = Read-Host '크기/SHA를 대조한 실제 기준 ZIP의 경로'
$env:MOBILE_TEST_ZIP = $referenceZip
$env:INJIDONG_TEST_GUI = '1'       # 표시 가능한 Windows GUI 시험 명시 활성화
Push-Location 'apps/local_review'
& '..\..\.venv\Scripts\python.exe' -B -X utf8 -m unittest discover -s tests -v
Pop-Location
```

기준 ZIP용 기존 시험은 정확한 기존 크기/해시/프레임 수치를 유지한다. 합성 ZIP을 MOBILE_TEST_ZIP에 넣어 이 시험의 기대값을 바꾸지 않는다. 외부 입력/GUI가 없으면 해당 시험을 명시적으로 skip하며 성공으로 세지 않는다. 합성 흐름은 별도 test_synthetic_workflow.py로 항상 실행한다. [최신 상태와 근거](../../docs/STATUS_20261024_ko.md), [전체 게시 대조표](../../docs/WORK_PUBLICATION_20261024_ko.md)를 함께 읽는다.
