# 학교 이전·복원·동일성 기록의 사용 범위

10/16 집 복원,10/18 학교 이전,10/21 ROI 전달/복원,10/22 문서 동일성 확인은 과거 로컬 실행 기록이다. 이번 GitHub 게시에는 이전 ZIP·가상환경·raw 촬영본·개인 ROI·중복 배포물을 새로 넣지 않았다. 이미 추적되던 제출 자료는 삭제하지 않았다.

재현에는 소스 버전만 아니라 원본 입력 식별값·크기·SHA, 필요한 보정·참조 파일과 저장 결과 폴더 전체가 필요하다. 새 PC에서는 저장소를 새 폴더에 clone하고 Python3.11/3.12+Tk의 **새 환경**을 준비한다. 기존 정상 venv를 덮거나 다른 PC의 venv를 복사하지 않는다. 현재 동작 안내는 [앱 README](../apps/local_review/README.md)와 [독립 ADE95 안내](../README-viewer.md)다.

ZIP 내부 원본/생성 결과는 임의 변환하지 않는다. 특히 해시 보존이 필요한 JSON/MD/Python은 LF/CRLF를 구분한다. 이번 fresh clone의 초기 Windows CRLF 변환은 원본 해시 시험3건을 실패시켰다. 독립 clone만 Git blob 바이트로 복원하고 LF attributes를 명시했다. 원래 사용자 작업본은 그대로다.

과거 SHA256SUMS는 [이전 manifest](validation/20261024-publish/previous_SHA256SUMS.txt)에 보존하고 Git 이력의 기준 commit도 남긴다. 현재 SHA256SUMS는 이번에 변경된 README와 활성 core를 포함한 **현재 체크아웃의 기대값**이다. 현재 manifest 검사 성공을10/07 파일 전체가 변경되지 않았다는 과거 주장으로 해석하지 않는다. schema5개는 그대로다.

수동 ROI는 화면 개수만이 아니라 ZIP·session/frame·내부 파일 해시, 선택ID int64 값/순서/직렬화 해시, ROI 경계·basis를 검증해야 한다. 화면 샘플·시점·preview는 다를 수 있다. 다운로드 캐시는 임시이므로 종료 후 동일 ZIP을 다시 확보한 다음 저장 프레임과 ROI를 선택한다. 임시 절대경로를 재열기 입력으로 쓰지 않는다.
