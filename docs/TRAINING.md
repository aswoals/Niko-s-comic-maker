# 내 캐릭터 LoRA 학습 가이드

모델이 모르는 내 OC를 더 닮게 그리고 싶을 때 하는 거임. 캐릭터 파일의 태그만으로도 그리긴 하는데, 무늬나 옷 같은 디테일은 자주 틀림. LoRA를 학습해서 캐릭터 파일에 넣으면 훨씬 비슷하게 나옴.

대신 준비할 게 많고 학습도 시간이 걸림. 처음엔 학습 없이 써 보고, 부족하다 싶을 때 하는 걸 추천함.

> ⚠ 학습 그림은 **직접 그렸거나 쓸 권리가 있는 그림만** 쓸 것. 남의 그림이나 남의 캐릭터로 만든 LoRA를 퍼뜨리는 것도 안 됨 ([USE_POLICY.md](../USE_POLICY.md)).
> 만든 LoRA는 Anima 모델 라이선스 조건도 따라야 함. 받는 페이지에서 한 번 확인해 두기.

전체 순서: kohya_ss 설치 > 학습 그림 모으기 > 캡션 달기 > 설정 파일 만들기 > 학습 > 캐릭터 파일에 넣기

---

## 1. 준비물

| 항목 | 내용 |
|---|---|
| 그래픽카드 | NVIDIA, 8GB 이상 (만든 사람은 8GB로 학습함) |
| kohya_ss | 학습 프로그램. 2번에서 설치 |
| 학습 그림 | 캐릭터 혼자 나온 그림 여러 장. 보통 수십 장으로 시작함 |
| 만화 제작기 | [QUICKSTART](QUICKSTART.md)대로 설치가 끝나 있어야 함 (모델 파일 포함) |

## 2. kohya_ss 설치 (처음 한 번)

kohya_ss 공식 안내(pip 방식) 기준임.

1. 필요한 프로그램 깔기. 이미 있는 건 건너뜀.
   - Python 3.11.9: QUICKSTART 2-1에서 깐 거면 됨
   - [Git](https://git-scm.com/download/win)
   - [CUDA Toolkit 12.8](https://developer.nvidia.com/cuda-12-8-0-download-archive?target_os=Windows&target_arch=x86_64)
   - [Visual Studio 재배포 패키지](https://aka.ms/vs/17/release/vc_redist.x64.exe)
2. 터미널(PowerShell)을 열고 한 줄씩 실행.
   ```
   git clone --recursive https://github.com/bmaltais/kohya_ss.git C:\kohya_ss
   cd C:\kohya_ss
   .\setup.bat
   ```
3. 메뉴가 뜨면 `Install kohya_ss GUI`를 고름. 설치 중에 accelerate 설정을 물어보면 전부 기본값으로 Enter.
4. 끝나면 메뉴에서 나가면 됨. kohya_ss 화면(GUI)은 안 켜도 됨. 만화 제작기가 kohya_ss 안의 학습 스크립트를 직접 부름.

`C:\kohya_ss` 말고 다른 데 깔았으면 환경 변수 `NK_KOHYA`에 그 폴더를 적어야 함. ComfyUI 모델 폴더가 Desktop 기본 위치가 아니면 `NK_COMFY_MODELS`에 `models` 폴더 경로를 적음. (환경 변수는 시작 메뉴에서 '환경 변수'로 검색 > 계정의 환경 변수 편집 > 새로 만들기)

## 3. 학습 그림 모으기

1. 만화 제작기 폴더 안에 `training\data\fox`처럼 영어 이름으로 폴더를 만들고 그림을 넣음.
2. 그림 이름을 `01.png`, `02.png`…처럼 번호로 바꿈. 캡션 파일이랑 이름을 맞추려고 그러는 거임.

좋은 학습 그림:
- 캐릭터 혼자 나온 그림. 다른 캐릭터가 같이 있으면 섞여서 배움.
- 앞, 옆, 뒤, 전신, 상반신, 얼굴처럼 각도랑 거리가 골고루 있으면 좋음.
- 배경은 단순할수록 좋음.
- 틀린 데가 있는 그림은 빼기. 틀린 것도 같이 배움.

직접 그린 그림이 적으면, 만화 제작기로 이 캐릭터를 여러 장 뽑아서 잘 나온 것만 골라 보태는 방법도 있음. 만든 사람도 이렇게 해서 늘렸음.

## 4. 캡션 달기

그림마다 같은 이름의 `.txt` 파일에 태그 한 줄을 써 둬야 함 (`01.png` 옆에 `01.txt`). 손으로 쓰면 오래 걸리니까 AI한테 시키는 게 편함.

1. 만화 제작기 폴더의 `AI_캡션_만들기.md`를 AI 채팅 새 대화에 첨부. 캐릭터 파일(`characters\fox.yaml`)도 같이 첨부하면 좋음.
2. 학습 그림을 번호 순서대로 올림. 한 번에 다 안 올라가면 나눠서 올려도 됨.
3. AI 답을 전부 복사하고, 만화 제작기 폴더의 터미널에서:
   ```
   .\nk.bat ep captions training/data/fox --trigger fox
   ```
   그림마다 캡션 파일이 생김. 먼저 보기만 하고 싶으면 끝에 `--dry`를 붙임.
4. 생긴 캡션을 한 번 훑어보기. 틀린 태그가 있으면 메모장으로 고치면 됨.

캡션 규칙은 세 가지만 기억하면 됨. 자세한 건 `AI_캡션_만들기.md`에 있음.
- 맨 앞은 트리거 단어 (캐릭터 파일의 `name`).
- 그림마다 바뀌는 것(자세, 구도, 표정, 배경, 그림체)은 전부 태그로 적음. 적은 건 '바꿀 수 있는 것'으로 배우고, 안 적은 건 캐릭터 자체로 굳음.
- 늘 같은 특징은 핵심 5~8개만.

## 5. 설정 파일 만들기

예시 두 개를 복사해서 고치면 됨.

1. `training\example_anima.yaml`을 복사해서 `training\fox.yaml`로 저장하고 아래 두 줄을 고침.
   ```yaml
   output_name: fox_anima_v1
   dataset_config: training/fox_dataset.toml
   ```
2. `training\example_dataset.toml`을 복사해서 `training\fox_dataset.toml`로 저장하고, `image_dir`를 내 그림 폴더의 **전체 경로**로 바꿈. 역슬래시(`\`) 대신 슬래시(`/`)를 씀.
   ```toml
   image_dir = 'C:/nk/training/data/fox'
   ```
   - 이 파일에는 한글을 쓰지 말 것. 윈도우에서 학습 프로그램이 한글을 못 읽을 수 있음.
   - 캐릭터 무늬가 한쪽에만 있으면 `flip_aug = false`로 바꿈. 안 그러면 좌우 뒤집은 그림도 같이 배워서 무늬 방향이 섞임.

## 6. 학습 돌리기

ComfyUI는 켜 둔 채로 해도 됨. 학습 전에 ComfyUI가 잡고 있던 그래픽 메모리를 비움.

1. 확인부터:
   ```
   .\nk.bat ep trainanima training/fox.yaml --dry
   ```
   모델 파일, 설정 파일, kohya_ss를 다 찾는지 봄. `[ERROR]`가 안 나오면 됨.
2. 속도 재기 (선택). 30걸음만 돌려 봄:
   ```
   .\nk.bat ep trainanima training/fox.yaml --bench 30
   ```
3. 진짜 학습:
   ```
   .\nk.bat ep trainanima training/fox.yaml --stop-comfy
   ```
   `--stop-comfy`는 학습하는 동안 ComfyUI를 껐다가 끝나면 다시 켜는 옵션임. 켜 둔 채로 하는 것보다 훨씬 빠름.

걸리는 시간은 걸음 수에 달림. 걸음 수는 그림 수 × `num_repeats` × 에포크 수임. 만든 사람 PC(8GB, ComfyUI 끈 상태)에서 한 걸음에 1.5초쯤 걸렸음. 예를 들어 그림 40장을 10에포크 돌리면 400걸음이니까 10분 정도.

학습하는 동안은 만화 그리기를 하지 말 것. 중간에 멈추려면 창에 나온 `taskkill /PID ... /T /F` 줄을 실행하면 됨.

## 7. 써 보기

학습이 끝나면 `training\output`에 `fox_anima_v1-000002.safetensors`, `-000004`…처럼 에포크별 파일이 생기고, ComfyUI의 `models\loras`로 알아서 복사됨.

캐릭터 파일(`characters\fox.yaml`)에 아래를 넣음:
```yaml
anima_lora: fox_anima_v1-000006.safetensors
anima_lora_strength: 1.0
anima_lora_desc: "a small anthro fox boy, orange fur, blue hoodie"
anima_find: orange fox
```

에포크 번호를 바꿔 끼워 가면서 몇 컷씩 그려 보고 제일 나은 걸 고르면 됨. 너무 오래 배운 건 캐릭터는 닮아도 자세가 굳거나 그림체가 잘 안 바뀌는 경우가 있음.

- LoRA 캐릭터가 나오는 두 명 컷은 ComfyUI 확장 [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack)이 있어야 함.
- LoRA 캐릭터는 한 만화에 하나만 쓸 수 있음.

## 8. 막혔을 때

| 이런 게 보이면 | 이렇게 |
|---|---|
| `[ERROR] missing: ...` | 그 경로에 파일이 없음. 모델 파일 이름, `dataset_config` 경로를 확인. ComfyUI 모델이 기본 위치가 아니면 `NK_COMFY_MODELS` |
| `image_dir not found` | 데이터 설정(`.toml`)의 그림 폴더 경로가 틀림. 전체 경로로, 슬래시(`/`)로 썼는지 확인 |
| `kohya_ss python not found` | kohya_ss가 `C:\kohya_ss`에 없거나 설치가 덜 됨. 2번을 다시 하거나 `NK_KOHYA` 설정 |
| `anima_train_network.py not found` | kohya_ss가 옛날 판임. `C:\kohya_ss`에서 `git pull`, `git submodule update --init --recursive` 한 다음 `.\setup.bat` 다시 |
| `out of memory` | 그래픽 메모리 부족. `--stop-comfy`를 붙이거나, 설정의 `blocks_to_swap`을 올림 |
| 데이터 설정을 읽다가 `UnicodeDecodeError` | `.toml` 파일에 한글이 들어감. 영어만 남기기 |
| `ep captions`에서 `캡션이 없는 그림`, `폴더에 그림이 없음` | 그림 이름이랑 AI 답의 `=== 01.png` 이름이 다름. 그림 이름을 번호로 맞추고 다시 |
| 만화 제작기가 `ModuleNotFoundError`를 냄 | 만화 제작기용 패키지가 안 깔린 파이썬이 잡힌 거임. 만화 제작기 폴더에서 `python -m pip install -r requirements.txt` 다시 |
