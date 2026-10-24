# 게시 작업본 직접 검증 · 2026-10-24

기준은 작업 시작 시 GitHub에서 재조회한 main `73a5ca5f60b4ec9a2f0ad2f9de82a89e4406b42d`이며, 고유한 별도 clone에서 검사했다. 기존 사용자 저장소의 미추적 출력·HEAD/브랜치·원본 앱/수동 ROI를 바꾸지 않았다.

## 환경과 실행

Windows11 Home build26200, PowerShell7.6.5, Python3.11.9, NumPy2.3.5, Matplotlib3.10.8, Pillow12.3.0, Tk8.6의 기존 정상 환경을 재사용했다. 설치/업그레이드하지 않았다. 명령은 README가 있는 새 checkout에서 실행했다. 아래 `python`은 선택한3.11/3.12 환경의 실행 파일을 뜻한다.

```powershell
python -B -X utf8 scripts/run_checks.py
```

이 명령은 각 단계를 새 인터프리터로 실행하고 PYTHONPATH와 실입력/GUI opt-in을 제거한다. 단계별 결과는 아래와 같으며 **서로/과거 결과와 합산하지 않는다.**

| 이번 직접 실행 단계 | 결과 |
|---|---|
| core·저장/재생·완료보호·뷰어 기존시험 | 135개,133통과·2skip·실패0,종료0 |
| 모바일 접수·JSON/인덱스·runner | 109개,103통과·6skip·실패0,종료0 |
| 저장 Depth 수학·배열 분석 | 10개 통과,종료0 |
| 합성 부피 | 11개 통과,종료0 |
| 앱 기본 portable | 134개,71통과·63skip·실패0,종료0 |
| 두 시점 순수 코어·합성 | 5개 통과,종료0 |

skip은 장비/외부 원본·GUI opt-in 또는 현재 OS에서 지원되지 않은 링크 생성 등 명시된 제약이다. skip을 검증 성공으로 계산하지 않는다. 일부 환경에서 실제 심볼릭 링크를 만들 수 없을 때도 해당 시험이 이유를 남긴다.

## 명시적 외부 입력과 GUI

기준 ZIP의3354368bytes 및 SHA256 72f3ebaff4c6fcb57675e702aca0854eeec162ce0de4f86b4b80de381cd07dff를 대조한 후 MOBILE_TEST_ZIP, 승인된 외부 로봇 검토 묶음의 INJIDONG_ROBOT_REVIEW_ROOT, INJIDONG_TEST_GUI=1을 자식 시험 프로세스에만 지정했다. 앱 디렉터리에서 `python -B -X utf8 -m unittest discover -s tests -v`를 실행해 **134개 전부 통과/종료0**했다. HTTP 목록/페이지·다운로드·부정헤더·크기/SHA·실제 ZIP 로더·ROI 및 취소·종료/재열기 수명 경로를 포함한다. 이는 loopback fixture 성공이며 실제 서버 종단 성공이 아니다.

별도 일반 `apps/local_review/run_review_viewer.py --mobile-zip <기준 ZIP>` 프로세스도 실행했다. OS UI 조작으로0017 선택→제품 폴더 대화상자의 기존 수동ROI 선택→42897점 표시→3D회전→표시50000/선택11336에서10000/2271로 변경→새 저장→이번GUI만Alt+F4 정상종료0을 확인했다. GUI stderr0bytes다. 그 새 저장본을 **게시 코드 mobile_roi.py**로 다른 프로세스에서 다시 열어 종료0·전체42897점·동일 선택ID SHA438fd2c375357d322f09d79ea2d517e0ad2493329a7a8aba37aff148c750b736·원본ID/ROI/basis/sources/schema 동일성과 새 cache 정리를 확인했다. 일반GUI에서 HTTP 재다운로드를 다시 수행했다고 주장하지 않는다. 그 흐름은 위 자동 수명시험과 기존10/23리허설의 별도 근거다.

원본 없는 사용자는 make_synthetic_demo.py가 생성한32×24 두 프레임 ZIP으로 별도6개 합성 통합시험을 실행한다. 기대ID/크기/SHA·픽셀/점군Z·목록/다음페이지·다운로드·오류헤더거부·ROI저장/다른프로세스재열기·importcheckout경계가 포함된다. 실제 장비 정확도나 모바일RGB 정렬의 증거는 아니다.

## 원인 확인과 최소 통합 수정

- 최초 fresh Windows clone의 기존68시험 중3건은 README 해시의 CRLF변환으로 실패했다. 독립 clone만 Git blob 바이트로 복원하고 LF attributes를 명시했다. 과거 SHA manifest는 previous_SHA256SUMS.txt로 그대로 보존했다. 현재 SHA256SUMS는 의도적으로 바뀐 README/VALIDATION/활성 contract의 현재 기대값이며21개 모두 엄격히 검사한다. 저장 배열·좌표·메타데이터 검증을 완화하지 않았다.
- 공유 core/viewer 경로로 옮긴 뒤 새 합성시험에서 viewer_data import 누락을 발견했다. 앱의 명시적 저장소 src 경로로만 수정하고 같은 시험6개를 통과시켰다. 새 시험의 예외형 이름 오타도 실제 API 이름 VerifiedZipError로 정정했다.
- 최초 조사 명령의 일부 존재하지 않는 후보 파일 조회 및 작성 도구 문자열 문법 오류는 제품 실행 실패와 분리했다. 존재하지 않는 자료를 구현 근거로 쓰지 않았다.
- 실제입력 전용 기존 시험은 원본 수치/해시를 유지하면서 명시적 환경 선택과 absent skip만 추가했다. 임의로 합성 입력을 기존 실입력 기대값으로 바꾸지 않았다.

원본 앱·ROI·ZIP·10/24 기존 근거는 읽기 전용으로 보존한다. 생성 출력·캐시·실행 로그·화면·전체 파일별 출처/해시/명령/종료코드는 별도 로컬 게시 감사 폴더에 남기고 새 Git 파일에서는 제외한다. 정적 파일·import·내부링크·개인경로/비밀정보·바이너리 선정·diff 검사는 commit 전에 별도로 수행한다.

## 원격 CI와 남은 제약

기존 main에는 CI workflow가 없었다. 이번 PR은 Linux Python3.11의 portable-checks workflow를 추가한다. 최초 HEAD c3682f8의 원격 CI는 기존 정적 PNG 시험이 Windows의 Malgun Gothic 글꼴을 요구해 실패했다. 같은 합성 PNG 시험에서 Matplotlib에 포함된 DejaVu Sans를 명시하도록 수정했다. 제품 기본 글꼴·엄격한 font lookup·배열/점군/PNG 검사 자체는 유지한다. 이 시험은 파일/PNG 생성 프로토콜 검증이며 한글 glyph 가독성 승인이 아니다. 해당10개 관련 검사를 수정 후 다시 실행하고 새 PR HEAD의 CI를 확인한다.

위 표는 **로컬 Windows 실행**이며 원격 Linux CI 결과는 PR의 해당 HEAD Checks에서 별도로 확인한다. workflow 추가·대기·미실행을 성공으로 간주하지 않는다. 병합은 이번 범위가 아니다.

실제 서버/Android 공동 연결·모바일 RGB 픽셀정렬/실제컬러·물리바닥/중력·실제 다중시점/부피/중량 정확도·학습팀최종인수는 미검증이다. [현재 상태](../../STATUS_20261024_ko.md)와 [전체28작업 대조](../../WORK_PUBLICATION_20261024_ko.md)를 따른다.
