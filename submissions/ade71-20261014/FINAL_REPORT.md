# ADE-71 결함4건 수정·새 제출본 검증 — 2026-10-14

4건의 수정과 검증, 새 ZIP 생성 및 실제 별도 해제본 실행을 완료했다. **PC 파일 처리·합성 검증·실제 입력 차단 범위의 팀장 검토 자료로 제출 가능**하다. 공용 보호 코드의 활성 변경 사본과 sidecar 프로토콜 통합은 강석현 검토가 필요하다. 실제 D405 세션/Point Cloud·Android/SDK·부피/중량·팀장 승인 완료는 아니다.

## 결함별 원인과 수정 전후

| 결함 | 원인 / 수정 전 | 변경 파일·함수 / 수정 후 |
|---|---|---|
| P1 F1 직접 API provenance 불일치 | 직접 경로는 metadata끼리 일치만 검사. raw hash/path/scale을 같은 오답으로 맞추면 success·3점; CLI는 거부 | `src/session_pipeline.py`의 `prepare_frames`, `require_processing_basis`, `convert_frames`가 쓰기 없는 full raw/hash/frame/conversion/geometry/target 검사를 공유. 직접 ContractError / 실제 CLI 종료1, 정상 출력 없음 |
| P1 F2 공개·격리 연속 실패 | final validation 공개 후 첫 manifest 격리가 실패하면 readable frames와 success processing 잔존 | `src/session_boundary.py`, 활성 `contract.py`, `viewer_data.py`, `session_pipeline.run_conversion`에 최종 완료 sidecar gate. 동일 잔존 조건에서 지원 로더·재생·직접 처리·cached packet/cloud·processing reader 모두 거부. main 반환1과 실제 child process 종료1을 각각 확인 |
| P2 F3 경로 충돌 | 직접 output_dir는 basis/input 내부를 허용 | `disjoint_output`, `packet_input_dirs`, pipeline `input_directories`를 공통 사용. 동일·입력 안·입력을 포함하는 출력 ancestor 모두 거부. resolve된 Windows junction 별칭도 직접 확인 |
| P2 F4 절대 manifest 경로 | contract._inside는 resolve containment만 검사 | `session_boundary.relative_path`를 contract._inside와 pipeline 참조에 공통 적용. 내부 absolute도 거부, relative 정상 허용, ../drive/UNC/ADS 거부 |

수정 전 원래 재현 코드는 새 경로에서 다시 실행했다. `before_reproduction/boundary_probe_results.json`은 실제 변경 전 관찰이며 수정 후 시험과 구분한다. SDK 선언은 합성 mock이고 실물 calibration 근거가 아니다. 새 회귀는 `tests/test_session_zip_fixes.py`에 고정했다. 상세 설계·호환 영향은 [수정 문서](C:/study/injidong-ade71-stage1-20261013/docs/ADE-71-zip-fixes-20261014.md), 변경 diff는 이 폴더의 `diffs/`다.

최종 `.ade71-complete.json`은 report·manifest·processing 해시를 연결하는 별도 완료 기록이다. core metadata/frames나 스키마에 임의 키를 추가하지 않는다. completion.pending은 닫은 후 final 이름으로 공개한다. 파일이 남더라도 final completion이 없으면 정상 입력으로 승인하지 않는다. 격리 성공을 보장의 전제로 삼지 않는다. 외부 legacy core 세션은 호환을 유지한다. 고의적 sidecar 삭제/원본 JSON 재구성에 대한 인증 보안이나 전원 차단 durability를 보장하는 구현으로 주장하지 않는다.

## 테스트·환경

기존 Windows venv `C:\study\injidong-depth-viewer\.venv\Scripts\python.exe`, Python3.11.9, NumPy2.3.5, Pillow12.3.0 사용. 새 설치 검증이 아니다. 공용 loader 영향으로 contract28 / pipeline21 / 이전회귀15 / replay10 / viewer16 / 새회귀16의 **106개 실행, 104 pass·0 failure·2 skip**을 확인했다. child CLI를 추가한 F2 선택1 재확인은 중복 합산하지 않는다.

source 회귀 skip2는 기존 annotations.jsonl **파일 symlink**와 새 **디렉터리 symlink 별칭** 생성의 WinError1314다. 권한 변경을 하지 않았다. Windows **junction** 별칭 시험은 실제 생성·거부 통과했다. ZIP 해제본에서는 새회귀16만 재실행하여 **15 pass·0 failure·1 skip**이며, 이전 파일 symlink 시험을 새로 통과한 것으로 표시하지 않는다. 전체 모음을 패키징 이유로 반복하지 않았다. 과거67/68·구현63·이전14+9도 합산하지 않는다.

최초 source 회귀2개 failure는 viewer 검사 순서와 replay 반환 API의 잘못된 시험 기대를 수정한 뒤 관련 시험을 다시 실행했다. 첫 minimum supervisor는 prepare helper가 금지하는 내부 intake 경로를 지정한 실행 오류로 실패했으며 외부 intake로 수정했다. 실패 기록을 정상 example 경로에 넣지 않았다. 패키징 첫 시도는 blocked evidence의 원본3개 중복을 검사에서 잡아 **ZIP 생성 전에 중단**했다. 그 새 폴더는 FAILED_PACKAGING.json으로 표시해 보존했다. 두 번째 ZIP의 CLI/회귀는 이미 통과했으나 최종 verifier가 짧은 Windows 사용자 경로와 긴 경로를 문자열로 비교한 오류가 있었다. 양쪽을 resolve하여 실제 import containment를 확인하고 static 검증만 마무리했다. 추가 소스 수정·불필요한 테스트 재실행은 없었다.

합성 raw=`[[1000,1000],[1000,0]]`, scale=.001, fx=fy=100,cx=cy=0에서 float32 전체 points=`[[0,0,1],[.01,0,1],[0,.01,1]]` m, 행 우선3점과 NPZ/key/count/unit/hash를 독립 재계산해 비교했다. 저장·공용 재로드·반복10회·capture/provenance 유지·replay 분리 성공, CLI 종료0이다. points hash=`ac26008fba6d8b9accc1afed052f82e47d7355babfacff44a6b6557e326c3cc6`.

실제 D405 원본은 SDK capture 코드 실행 없이 hash를 대조해 새 외부 intake로 준비했다. 정식 CLI는 **INTAKE_BLOCKED·종료1**, 정상 frames/points 없음이다. 현재 실제 보정/정밀값 부족이 유지되므로 합성 성공을 실제 입력 완료로 확대하지 않았다. SDK·카메라·USB/Android·GUI 수동 시연·학습·부피 적분·중량 정확도·물리 디스크 고장은 수행하지 않았다.

## 새 ZIP 실물

| 항목 | 직접 검증 결과 |
|---|---|
| ZIP 절대 경로 | `C:\study\injidong-ade71-stage1-20261013\submissions\ade71_session_fixed_20261014_6fe5b71e259e\ADE-71_session_fixed_20261014_6fe5b71e259e.zip` |
| 크기 | **2,528,277 bytes** |
| SHA-256 | **31547e5128b78d0becce9c3414fff9f3e27211dac72d318badaf0a3686a3dddd** |
| 파일/디렉터리 항목 | **154 / 0** |
| 파일별 목록 | 153개 hash 전체 일치, FILE_SHA256SUMS.txt 자신만 제외 |
| CRC·중복·안전한 경로·링크 | 전체 통과, unsafe/duplicate 항목 없음 |
| 원본 ZIP | depth_original.zip 한 개, 내부 CRC/hash 동일, 내부 원본 파일 별도 중복 없음 |
| 보호 원본 | checksum/map 기준21개 일치, active contract 변경1개 명시 |
| 필수 파일·UTF-8 JSON | 의존 code5스키마/예제/문서/회귀/로그 포함, NaN/Infinity 토큰 없음 |
| venv/cache/Git/키 등 | 파일명 및 대표 비밀값 패턴 검사에서 발견 없음; 완전한 비밀값 부재 보장은 아님 |
| 실제 ZIP 해제본 실행 | minimum supervisor0, 합성0/10회/전체좌표, D405차단1, 새회귀15pass/1skip |

원본 파일을 복사해 둔 blocked output evidence3개는 ZIP에서 제외하고 `ORIGINAL_MEMBER_MAP.json`으로 단일 원본 ZIP의 member/hash에 연결했다. 실패 binary output을 정상 예제로 넣지 않았다. 원본 depth_original.zip SHA=`c7db1884aa5a78fd4fd634153e9575912d762000a7aa0aa1ad7acee66889e6e2`, raw depth10.npz SHA=`61de8af2f76ff04e4bac639b7f1fe4f4a07b638534dec2ac8866deb657ad29f0` 유지.

실제 별도 해제 경로:

`C:\Users\AISW-510-131\AppData\Local\Temp\ade71_fixed_zip_validation__asult6t\extracted`

contract/session_boundary/pipeline/auxiliary/preflight/replay/viewer_data **7개 실제 import 모두 resolve한 이 해제 경로 아래**임을 확인했다. dependency는 기존 venv다. 해제154개 hash를 실행 후 대조하여 파일 추가/변경이 없었다. 실행 명령·stdout/stderr·회귀 skip은 ZIP 옆 `EXTRACTED_EXECUTION.json`, 상세 실행 report와 `PACKAGING_VERIFICATION.json`에 남겼다. 외부 ZIP hash를 ZIP 안에 넣는 순환을 만들지 않았다.

```powershell
$adePython = 'C:\study\injidong-depth-viewer\.venv\Scripts\python.exe'
$adeExtracted = 'C:\Users\AISW-510-131\AppData\Local\Temp\ade71_fixed_zip_validation__asult6t\extracted'
Set-Location -LiteralPath $adeExtracted
& $adePython -B -X utf8 scripts\validate_ade71_zip_fixes.py `
  --output-root 'C:\Users\AISW-510-131\AppData\Local\Temp\ade71_fixed_zip_validation__asult6t\minimum_runs' `
  --regressions
$LASTEXITCODE # 확인된 supervisor0; 내부 합성0 / 실제 INTAKE_BLOCKED1
```

## 보호·Git·남은 실제 자료

활성 `src/contract.py`는 보호 기준에 대해 **변경된 사본**이다. 원본은 `protected_reference/src/contract.py`에 동일 hash로 보존했다. 원래 SHA256SUMS.txt는 수정하지 않았고 active 사본에는 의도된 mismatch1개가 생긴다. 이를 PROTECTED_FILE_MAP으로 보존 원본 검사와 분리했다. 보호5스키마 및 다른 원본20개는 그대로다. 기능 서명과 core 필드는 유지하지만 invalid 절대 경로와 미완료 managed 세션은 새롭게 거부한다. 공용 backend0.2.0과의 sidecar/loader 통합 검토는 강석현이 확인해야 한다.

이번 시작 **447개** 중 **441개 그대로 / 허용 수정6개 / 누락0 / 예상 밖 변경0**이며 원본21개 checksum 보존을 직접 확인했다. 변경6개는 활성 src4개와 정정 문서2개다. 과거504개 보존은 기준/후 목록이 없어 확인하지 못했으며 정정했다. 예전 제출 ZIP의 hash는 기존 `2ff18dedf6bd15ade9b36b9feb3bac769398b1e155d73e7c8422096801a04d4c` 그대로다. branch `codex/ade-71-stage1-20261013`, HEAD `a6180a6aca48de5c98b3a4d81619f64cea573118`는 기존 문서 커밋이다. 이번 코드 커밋이 아니며 작업은 미커밋 상태다.

실제 D405 세션/Point Cloud에는 **현재 raw/index0..9/profile에 연결된** 정밀 내참수·보정/rectified_pinhole 경로·장비/profile/calibration 출처·scale/Z 근거·65535 의미/정책·프레임 대응이 필요하다. 도형준은 실제 원본/측정·촬영 자료, 강석현은 해당 근거·공용 변경 사본/0.2.0·small_v1 제작/실측 기준 검토, 이가영은 Galaxy S23 FE 정확한 모델/OS/SDK/USB·RGB/Depth/정렬·mask 인수 근거를 제공해야 한다. timestamp는 미저장본 all-null을 유지하며 시각·pose 없음만으로 단일 camera 처리를 전부 금지하지 않는다. 부피는 support/basis/footprint/coverage/방법 가정, 중량 정확도는 모델·실측g·물리 specimen 독립 split이 추가 조건이다. 전체 요청표는 새 ZIP 루트 REQUESTS.md다. 실제 메시지는 발송하지 않았다.

commit/push/reset/clean·Linear 변경·메시지 발송·원본 정리/삭제·옛 ZIP 덮어쓰기는 하지 않았다. 확인 범위에서 제출 검증을 통과했으며 모든 가능한 오류나 실제 장비 적합성을 보장하는 판정은 아니다.
