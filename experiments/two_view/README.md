# 두 시점 강체 정합의 수치 실험 코어

인접한 로봇 촬영 두 시점을 탐색할 때 사용한 NumPy 강체 변환/ICP 코어와 합성 회귀시험이다. 실제 촬영 자료 없이 알려진 회전·이동의 추정, 적용·역변환, 잘못된 행렬/JSON 거부와 작은 합성 ICP를 재현한다. 기존 코어 계약이나 원본 `pose=null`·검증 상태를 바꾸지 않는다.

저장소 루트에서 Python 3.11 이상과 NumPy를 설치한 환경으로 실행한다. 기존 `requirements-viewer.txt` 환경의 NumPy로도 실행할 수 있다.

```powershell
python -B -m unittest discover -s experiments/two_view -p test_rigid_transform.py -v
```

시험 5개는 알려진 강체 변환과 역변환, 반사/축척/비유한/잘못된 마지막 행 거부, 잘못된 점/퇴화 fit 거부, JSON 중복키·방향/단위 오류 거부, exact nearest neighbour와 합성 ICP를 확인한다. 임시 JSON은 OS 임시폴더에만 작성한다. 이는 수학적 계산의 회귀시험이며 센서·로봇의 물리 정확도 검증이 아니다.

## 좌표와 알고리즘

- 변환 방향은 `p_target = R @ p_source + t`, 입력/이동 단위는 m다. Nx3 행 배열에는 `points @ R.T + t`를 적용한다.
- 4×4 행렬의 유한값·동차 마지막 행·정규직교 회전·determinant +1을 확인한다. 역변환과 가중 SVD rigid fit을 제공한다.
- ICP는 그룹별 exact Euclidean 최근접점, 대응 거리 제한, 그룹별 trim, 그룹 총 가중치 균등의 point-to-point rigid fit을 사용한다. 초기값과 그룹 구성을 호출자가 제공한다.
- `load_transform`의 형식 `injidong_local_two_view_exploration`은 실험 보조 형식이다. 코어 frame schema나 검증된 robot/world pose 형식으로 사용하지 않는다.

## 실제 촬영 실험과 게시 범위

당시 로컬 실험은 각 view의 기존 물체 라벨과 주변 평면 가설로 영역을 나눴다. 4mm voxel hash로 먼저 fit/eval을 분리하고 평면 normal/물체 fit 중심으로 초기화했다. 기본 대응 8mm 외에 yaw/이동 교란·대응 4/12mm·바닥만의 대조를 포함한 고정 6조건을 비교했다. RGB는 정합 비용에 사용하지 않았다. 동일 pixel_id는 view 사이의 동일 물리점 대응을 뜻하지 않는다.

실제 원본 ZIP·Depth/RGB·라벨·개인 ROI·저장 변환/NPZ/그림·실행로그는 포함하지 않는다. 원래 실데이터 실행 스크립트 `prepare_inputs.py`, `run_registration.py`, `reapply_saved.py`도 게시하지 않는다. 이들은 특정 로컬 입력·인수기록·실험 bundle의 배치와 해시에 의존한다. 이 공개 폴더만으로 당시 실제 촬영의 행렬·지표·bitwise 출력까지 재현할 수 없다. 실제 실험 재현에는 선택 원본 프레임, 두 view의 원래 라벨, 보정/인덱스, 입력 해시와 전체 파라미터가 별도로 필요하다.

## 한계

평면 normal과 중심 초기화는 평면 내 이동·yaw의 정답을 보장하지 않는다. ICP는 초기값·대칭·가림·결측·표본 밀도에 민감하다. fit/eval 표본 분리는 같은 센서/장면의 상관을 없애지 않으며 최근접 거리 감소는 독립 실측 오차의 정답이 아니다. 3/5/10mm 이내 비율은 탐색 보고값이며 팀 합격 기준이 아니다.

후속 근거 조사에서 현재 저장 변환을 독립 평가할 명시적 고정 기준점 대응이나 검증된 camera–robot/world pose를 확보하지 못했다. 사용자 제공 시편 치수만으로 두 촬영의 상대 pose를 정할 수 없다. 넓게 분포한 식별 가능한 비일직선 기준 대응 또는 검증된 카메라 pose가 추가로 필요하며 비공면 타깃만 가능한 것은 아니다. 완전 3D 복원·부피·중량·물리 정합 승인으로 확대하지 않는다.

`nearest`는 작은 탐색 표본을 대상으로 query 128행씩 reference 전체와 비교한다. 대규모 점군용 성능을 보장하지 않는다. 코어의 축/법선·ICP 반복/trim 설정 검사는 제한적이다. 호출자는 유한한 비영 축/법선, 양의 정수 반복 수, `0 < trim_fraction <= 1`, 같은 그룹 이름과 충분한 점 수를 제공해야 한다. 이 폴더는 범용 자동 정합 CLI가 아니다.
