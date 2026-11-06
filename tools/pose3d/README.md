# tools/pose3d — 3D 인형으로 자세를 잡아 조종 그림 만들기 (시제품)

**한 줄**: 머리 큰 인형 두 개를 3D로 세우고(업기·목마·안기·손 맞잡고 들기·등 맞대고 앉기), 카메라를 아무 각도에 두고 찍어서
ControlNet(그림 조종 장치)에 줄 그림 네 가지를 만든다. GPU·ComfyUI 없이 몇 초. **파이프라인에는 아직 안 붙였어 (제안만).**

| 그림 | 파일 | 뜻 |
|---|---|---|
| ① 깊이 | `depth.png` | 가까울수록 밝게. 누가 앞인지·몸의 두께가 들어 있음 |
| ② 사람별 모양 틀 | `label.png`(색), `mask_a.png`, `mask_b.png` | 픽셀마다 '맨 앞에 보이는 사람'. 겹친 곳은 앞사람 것 → **한 픽셀 = 한 사람** |
| ③ OpenPose 18점 | `openpose.png`(조종용), `openpose_all.png`(전부), `openpose_check.png`(진짜로 가려진 점 = 속 빈 동그라미) | 우리 `nk_pose.py`와 같은 색·순서. 조종용 규칙: 뒷모습의 코·눈과 상대에 가린 점은 뺌, 옆모습의 먼 쪽 어깨처럼 자기 몸에 가린 몸 점은 그림 (뼈대가 끊기지 않게) |
| ④ 선화 | `lineart.png` | 사람 경계 + 앞뒤로 떨어진 곳만 흰 선 |
| 누끼 레이어용 | `depth_a.png`·`depth_b.png`(사람마다 혼자 깊이), `openpose_a.png`·`openpose_b.png`(혼자 층 뼈대: 상대에 가린 점도 그림), `behind_a.png`·`behind_b.png`(상대에 가린 곳 = 겹친 곳) | 따로 그리는 층이 가려진 몸까지 그리게 |
| 기록 | `kp.json`(nk_pose `_kp.json`과 같은 모양 + `vis`·`hidden_by`), `scene.json`(카메라·닿는 곳 거리·관절 좌표), `sheet.png`(네 그림 나란히) | `--name cut09 --spans 0.5-1.0,0.0-0.5` 를 주면 `cut09.png`·`cut09_kp.json`(nk poses 폴더 모양)도 |

## 쓰는 법 (PC, 키트 폴더에서 — 붙여 넣기용)
```
python tools\pose3d\run.py list
python tools\pose3d\run.py render --pose piggyback --yaw 20 --pitch 50 --size 832x1216 --out runs\pose3d\pig_high
python tools\pose3d\run.py examples --out runs\pose3d\examples
```
- `--yaw` 장면 둘레 각도 (0 = 정면, 90 = 옆, 180 = 뒤) / `--pitch` 올려 찍는 각도 (0 = 눈높이, 50 = 위에서 내려다봄, 음수 = 아래에서)
- `--dist` 카메라 거리 (비우면 두 사람이 다 들어오게 자동) / `--fov` 화각 / `--swap` a·b 역할 바꾸기 (업는 사람을 상대로)
- 체형·기본 카메라·틀 색은 **`settings.yaml` 하나만** 고치면 됨 (머리 큰 케모노 체형을 눈대중으로 넣어 둠).
- 자세 틀: 과제 5개(piggyback 업기·shoulder 목마·hug 서서 안기·hands_up 두 손 맞잡고 높이 들기·back_to_back 등 맞대고 앉기) + 덤 2개(holding_hands·high_five)
- 시험: `python -m pytest tests\unit\test_pose3d.py` (pytest 필요)

## 에러가 나면
- `No module named numpy` / `PIL` → nk 파이썬(위 경로)으로 돌렸는지 확인.
- `모르는 자세` → `run.py list`에 나온 이름으로.
- 그림이 잘리거나 비었으면 → `--dist`를 빼서 자동 거리로.

## 한계 (확실)
- 몸은 캡슐·타원체 덩어리라 옷·털·손가락이 없음 → 깊이·선화 ControlNet은 **약하게** 걸어야 할 것 (추정, PC 시험 전).
- 자세 틀 5개는 손으로 짠 것. 닿는 곳은 IK(손을 여기에 → 팔 각도 계산)로 맞추고, 시험(`test_every_template_keeps_its_contacts`)이 거리를 확인.
- 몸끼리 살짝 파고드는 곳이 있음(안기의 배, 등 맞대기의 뒤통수) — 틀은 앞사람 것으로 정해지므로 조종 그림에는 문제없음.
- 꼬리는 틀·깊이·선화에는 들어가지만 OpenPose에는 꼬리 점이 없음 (OpenPose 규칙).
