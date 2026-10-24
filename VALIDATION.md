# 검증 기록 — 2026-10-07

> 이 문서는10/07 당시 결과를 보존한다. Windows3.11 및10/24 게시 작업본 검증은 [후속 기록](docs/STATUS_20261024_ko.md)에 구분한다. 아래의 ‘Windows 미검증’은 당시 범위다.

- 실행 환경: Python 3.12.14 / NumPy 2.3.5 / Linux PC.
- `python -m unittest discover -s tests -v`: **28개 통과**, 실패 0.
- `python src/contract.py examples/synthetic`: frame 1개, 유효 point 3개. `(0,0,1)`, `(.01,0,1)`, `(0,.01,1)` m와 float32 허용 오차 내 일치.
- 검사 범위: 단위 변환, NaN/음수/0 처리, shape/dtype/내참수, 빈 Depth, checksum/파일 경로, nullable 자세·시각, quaternion, 동기화 근거와 허용 오차, 대상 mask, 지지면/basis/누락 Depth, 라벨 유출 방지, 모델 미준비·성공·품질 미정 상태, fixture 구조, JSONL 반복 재생.
- Point Cloud success fixture는 제공한 합성 입력으로 실제 계산한 결과다. Prediction success와 label fixture는 화면·규격 예제이며 학습 모델/실측 결과가 아니다.
- 실제 카메라 캡처·모바일 USB·로봇 동작·실측 중량·부피 정확도·10% 중량 목표는 이번 검증에 포함하지 않았다. ADE-69 및 담당 구현 이슈에서 검증한다.
- 원본 파일을 유지한 상태로 오류 입력 복사본/메모리 객체로 실패 테스트를 진행했다.
- Python 3.11과 Windows에서의 실행은 아직 검증하지 않았다. 해당 환경 담당자는 동일 재현 명령과 실제 SDK 설치 로그를 기록한다.
