# Niko's Comic Maker (nk 만화 제작기)

**한국어** · [English](#english)

> ## ⚠ 먼저 읽기: 사용 정책 ([USE_POLICY.md](USE_POLICY.md))
> - **전연령(safe) 그림만 만든다. NSFW, 성인물, 선정적이거나 잔혹한 그림에는 쓰지 않는다.** 미성년자를 성적으로 다루는 건 어떤 경우에도 안 된다.
> - 불법적인 용도에 쓰지 않는다. 저작권이나 초상권 침해, 실존 인물 사칭, 괴롭힘, 사기 같은 것들이다.
> - 비상업 용도로만 쓸 수 있다 ([PolyForm Noncommercial 1.0.0](LICENSE)). 판매, 유료 서비스, 커미션처럼 돈 버는 일에는 쓰지 않는다.
> - **책임은 전부 사용자에게 있다.** 이 프로그램은 있는 그대로 제공하고, 프로그램이나 그 결과물 때문에 생긴 문제는 원작자가 책임지지 않는다.
> - 처음 실행할 때 이 내용에 동의해야 쓸 수 있다.

"○○와 ○○가 나오는, ○○ 작가 그림체의, ○쪽짜리, ○○한 내용의 만화를 만들어 줘."
이렇게 한 번 요청해서 일본식 컬러 페이지 만화를 받는 게 목표인 개인 프로젝트다. 그림은 내 PC의 [ComfyUI](https://www.comfy.org/)가 그리고, 이야기 계획은 AI 채팅(ChatGPT, Gemini 등 아무거나)이나 로컬 AI가 쓴다.

원작자는 니코다. 취미 겸 공부로 만든 실험적인 프로그램이라 설치가 쉽지 않고, 그림 품질은 모델과 캐릭터, 그림체에 따라 많이 달라진다.

## 흐름

```
요청(한국어 자유 문장) ─► AI 채팅이 계획표 plan.yaml ─► nk가 콘티 conti.yaml로 (연출 규칙은 코드가 붙임)
   ─► ComfyUI로 컷 그리기 (혼자 컷 / 두 명 컷 / 풍경) ─► 자동 검수·고치기 후보 ─► 말풍선·효과음·쪽 조립 ─► PNG·PDF
```

## 필요한 것

PC는 Windows 10이나 11, NVIDIA 그래픽카드(8GB에서 시험했다), 디스크 여유 공간 수십 GB가 필요하다.

**필수**
| 무엇 | 쓰는 곳 |
|---|---|
| Python 3.10 이상과 `requirements.txt` | nk 명령 |
| [ComfyUI](https://www.comfy.org/) 최신판 (Desktop이든 일반 설치든) | 그림 그리기. nk가 8000, 8188~8191 포트에서 찾는다. 아래 Anima-LLLite와 SAM3 노드는 ComfyUI에 기본으로 들어 있어서 따로 깔지 않아도 된다 |
| Anima 그림 모델 3개 ([circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima)의 `split_files` 폴더): `anima-base-v1.0.safetensors` → `models/diffusion_models`, `qwen_3_06b_base.safetensors` → `models/text_encoders`, `qwen_image_vae.safetensors` → `models/vae` | 기본 그리기 (`nk ep auto`) |
| Anima-LLLite 2개 ([Comfy-Org/Anima-LLLite](https://huggingface.co/Comfy-Org/Anima-LLLite)의 `model_patches` 폴더): `anima-lllite-depth-1.safetensors`, `anima-lllite-any-test-like-v2.safetensors` → `models/model_patches` | 3D 인형으로 자세 잡기. 기본으로 켜져 있다 |
| SAM 3.1 ([Comfy-Org/sam3.1](https://huggingface.co/Comfy-Org/sam3.1)): `checkpoints/sam3.1_multiplex_fp16.safetensors` → `models/checkpoints` | 캐릭터 자리 찾기 |
| AI 채팅 아무거나 (ChatGPT, Gemini 등. 무료판도 된다) | 캐릭터 만들기와 계획표(글콘티) 쓰기. `AI_캐릭터_만들기.md`, `AI_글콘티_만들기.md`를 첨부해서 쓴다 |
| 캐릭터 파일 1개 이상 (`characters/`) | 등장인물 ([docs/ADDING.md](docs/ADDING.md)) |

필수 모델 파일은 합쳐서 7.4GB쯤 된다.

**선택** (없으면 그 기능만 안 된다)
| 무엇 | 쓰는 곳 |
|---|---|
| ComfyUI 확장 [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) (RegionalSampler 등) | LoRA 캐릭터가 나오는 두 명 컷 |
| [Ollama](https://ollama.com/)와 `gemma4:e4b-it-qat` 같은 작은 비전 모델 | 자동 검수, 한국어 고치기 요청 해석, 로컬 계획 쓰기 |
| NoobAI-XL V-Pred 1.0 ([Laxhar/noobai-XL-Vpred-1.0](https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0)) | 예전 흐름 `--render noob`, `nk gen` |
| Qwen-Image-Edit 2509 (fp8)와 `qwen_2.5_vl_7b_fp8_scaled` | 문장으로 컷 고치기, 소품 넣기, 두 명 합치기 |
| [comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes) | 두 명 컷 시험 방식 일부 |
| 판별기 `models/wd-eva02-large-tagger-v3/` (ONNX), DWPose `models/dwpose/dw-ll_ucoco_384.onnx`, anime-seg `models/animeseg/isnetis.onnx` | 태그 판별 검사, 뼈대, 캐릭터 잘라내기 |
| [kohya_ss](https://github.com/bmaltais/kohya_ss) (sd-scripts 포함, 기본 위치 `C:\kohya_ss`, 다른 곳이면 환경 변수 `NK_KOHYA`) | 내 캐릭터 LoRA 학습 ([docs/TRAINING.md](docs/TRAINING.md)) |
| 태그 사전 `tags/danbooru.csv`, `tags/e621.csv` ([a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)) | 태그 검사, 캐릭터 찾기 ([docs/ADDING.md](docs/ADDING.md) 4절) |

- 설치된 ComfyUI 노드 목록은 `nk ep nodes`로 볼 수 있다. 보기만 하고 아무것도 바꾸지 않는다.
- 모델 파일은 이 저장소에 없다. 모델마다 라이선스(비상업 조건 등)가 따로 있으니 직접 확인하고 지켜야 한다.

## 설치

처음이라면 [처음 쓰는 사람용 가이드](docs/QUICKSTART.md)를 따라 하는 게 편하다.

1. 이 저장소를 내려받는다 (Code → Download ZIP, 또는 `git clone`).
2. 파이썬 패키지를 설치한다: `python -m pip install -r requirements.txt`
   - `nk.bat`은 환경 변수 `NK_PYTHON`에 적힌 python.exe, 이 패키지가 깔린 PATH의 `python`, `C:\kohya_ss\venv` 순서로 파이썬을 찾는다.
3. ComfyUI를 설치하고 위 모델을 넣은 다음 켜 둔다. LoRA 캐릭터를 쓰려면 Impact Pack도 깐다.
4. 처음 한 번은 PowerShell 창에서 아무 명령이나 실행해서 사용 정책에 동의한다 (예: `.\nk.bat list`). `작업실.bat`을 더블클릭해도 같은 동의 화면이 나온다.
5. 캐릭터를 추가한다. 저장소에는 캐릭터 파일 없이 양식(`characters/_template.yaml`)만 있다. `AI_캐릭터_만들기.md`를 AI 채팅에 첨부하고 캐릭터를 설명하면 캐릭터 파일을 대신 써 준다. 직접 쓰는 방법은 [docs/ADDING.md](docs/ADDING.md)에 있다.

## 쓰는 법

- 작업실(화면): `작업실.bat`을 더블클릭하면 브라우저에 `http://127.0.0.1:8765`가 열린다. 새 만화, 이어서 만들기, 컷 다시 그리기, 결과 보기를 여기서 한다. 이 PC에서만 열린다.
- 메뉴: `만화만들기.bat`을 켜고 번호를 고른다. 1 글콘티용 첨부 파일 만들기 / 2 AI 답 붙여 넣기 / 3 만들기 / 4 컷 고치기 / 5 대사만 / 6 결과 / 7 캐릭터 추가
- 명령:
  ```
  .\nk.bat ep aifile          # AI_글콘티_만들기.md 만들기 -> AI 채팅 새 대화에 첨부하고 만들고 싶은 만화를 한국어로 요청
  .\nk.bat ep paste ep01        # 복사해 둔 AI 답을 episodes/ep01/plan.yaml 로 저장 + 검사
  .\nk.bat ep auto ep01         # 처음부터 끝까지: 콘티 -> 그리기 -> 고치기 -> 말풍선 -> 검토
  .\nk.bat ep fix ep01 3 --add "smile"   # 3번 컷 태그를 고쳐서 그 컷만 다시
  ```
  완성본은 `episodes/<화>/out*/page_*.png`와 `book.pdf`로 나오고, 한 장짜리 검토 그림은 `episodes/<화>/auto/review.png`에 생긴다.
- 다른 명령은 `.\nk.bat --help`, `.\nk.bat ep`, [nk_guide.md](nk_guide.md)에 있다. 계획표 형식은 [docs/prompt_plan.md](docs/prompt_plan.md), 콘티 규칙은 [docs/conti_rules.md](docs/conti_rules.md)를 보면 된다.

## 폴더

```
nk.bat / nk*.py      명령 (nk ep ...)
presets.yaml         기본값, 작가(직접 추가), 장면
characters/          캐릭터 파일 (직접 추가, _template.yaml 이 양식)
docs/                계획표 규칙(prompt_plan.md), 콘티 규칙, 추가 방법(ADDING.md), 계획표 예시
fonts/               말풍선·효과음 글꼴 (SIL OFL 1.1, fonts/FONTS.md)
tools/pose3d/        3D 인형 자세 그림
tests/               시험 (가짜 ComfyUI, 가짜 검수 AI, 시험용 가짜 캐릭터)
episodes/ runs/      내가 만든 만화와 그림 (저장소에 올리지 않음)
```

## 시험 (GPU 안 씀)
```
python -m pip install pytest
python -m pytest tests/unit -q          # 단위 시험
python tests/run_selftest.py            # 가짜 ComfyUI와 가짜 검수 AI로 nk ep auto 전체 흐름
```

## 알려진 한계
- LoRA 캐릭터는 한 만화에 하나만 쓸 수 있고, 한 컷에 세 명 이상은 못 그린다. 뒷모습, 누운 전신, 몸이 많이 겹치는 자세는 아직 잘 안 나온다.
- 자동 검수(작은 비전 모델)는 자주 틀린다. 마지막엔 원본 크기로 직접 봐야 한다.
- 3D 장면 렌더러(Blender 스크립트)는 공개본에서 뺐다. 그래서 3D 자세 조종은 캡슐 인형으로만 된다.
- 화면과 안내문은 한국어뿐이다.

## 라이선스
- 코드와 문서: PolyForm Noncommercial License 1.0.0 ([LICENSE](LICENSE)). 비상업 용도로만 쓸 수 있다. Required Notice: Copyright (c) 2026 니코 (Niko)
- 글꼴: SIL Open Font License 1.1 ([fonts/FONTS.md](fonts/FONTS.md))
- 모델, 도구, 태그 목록은 이 저장소에 없고, 각각 자기 라이선스를 따른다.

---

## English

> ### ⚠ Read first — Use Policy ([USE_POLICY.md](USE_POLICY.md))
> - **All-ages (safe) images only.** Do not use this for NSFW, adult, sexually suggestive, or gory content. Any sexual depiction of minors is absolutely forbidden.
> - **No illegal use.** No copyright or likeness infringement, impersonation of real people, harassment, fraud, and so on.
> - **Non-commercial only.** [PolyForm Noncommercial 1.0.0](LICENSE). Do not use it to make money (selling, paid services, commissions, etc.).
> - **You are solely responsible.** The software is provided "as is". The author accepts no liability for any problem arising from the software or anything made with it.
> - You must **agree** to this policy on first run.

A personal project that aims to make a **colored, Japanese-style page comic** from a single request such as "make a ○-page comic starring ○○ and ○○, in ○○'s art style, about ○○".
Images are drawn by [ComfyUI](https://www.comfy.org/) on your own PC; the story plan is written by a free AI chat (ChatGPT, Gemini — any LLM works) or a local AI.

- Author: **Niko**
- Status: an **experimental** program made as a personal hobby and study project. Setup is not easy, and image quality varies a lot by model, character and art style.
- The UI, messages and most docs are in **Korean** only.

### Flow

```
Request (free-form sentence) ─► an AI chat (any LLM) writes plan.yaml ─► nk turns it into the storyboard conti.yaml (directing rules are added by code)
   ─► ComfyUI draws each cut (solo / two characters / scenery) ─► automatic checks and fix candidates ─► speech balloons, sound effects, page layout ─► PNG / PDF
```

### Requirements

**PC**: Windows 10/11, NVIDIA GPU (tested with 8 GB+), tens of GB of free disk space.

**Required**
| What | Used for |
|---|---|
| Python 3.10+ and `requirements.txt` | nk commands |
| [ComfyUI](https://www.comfy.org/), latest version (Desktop or standard) | drawing. nk looks for it on ports 8000 and 8188–8191. The Anima-LLLite and SAM3 nodes below are built into ComfyUI — nothing extra to install |
| Anima image model, 3 files — in `split_files` of [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima): `anima-base-v1.0.safetensors` → `models/diffusion_models`, `qwen_3_06b_base.safetensors` → `models/text_encoders`, `qwen_image_vae.safetensors` → `models/vae` | default drawing (`nk ep auto`) |
| Anima-LLLite, 2 files — in `model_patches` of [Comfy-Org/Anima-LLLite](https://huggingface.co/Comfy-Org/Anima-LLLite): `anima-lllite-depth-1.safetensors`, `anima-lllite-any-test-like-v2.safetensors` → `models/model_patches` | posing with a 3D doll (on by default in plans) |
| SAM 3.1 — `checkpoints/sam3.1_multiplex_fp16.safetensors` from [Comfy-Org/sam3.1](https://huggingface.co/Comfy-Org/sam3.1) → `models/checkpoints` | finding where each character is |
| Any AI chat such as ChatGPT or Gemini (free tier is fine) | making characters and writing the plan (attach `AI_캐릭터_만들기.md`, `AI_글콘티_만들기.md`) |
| At least one character file (`characters/`) | the cast ([docs/ADDING.md](docs/ADDING.md)) |

The required model files total about 7.4 GB.

**Optional** (without it, only that feature is unavailable)
| What | Used for |
|---|---|
| ComfyUI extension [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) (RegionalSampler, etc.) | two-character cuts with a LoRA character |
| [Ollama](https://ollama.com/) + a small vision model such as `gemma4:e4b-it-qat` | automatic checks, reading Korean edit requests, writing plans locally |
| NoobAI-XL V-Pred 1.0 ([Laxhar/noobai-XL-Vpred-1.0](https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0)) | legacy flow `--render noob`, `nk gen` |
| Qwen-Image-Edit 2509 (fp8) + `qwen_2.5_vl_7b_fp8_scaled` | editing a cut with a sentence, adding props, merging two characters |
| [comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes) | some experimental two-character modes |
| Tagger `models/wd-eva02-large-tagger-v3/` (ONNX), DWPose `models/dwpose/dw-ll_ucoco_384.onnx`, anime-seg `models/animeseg/isnetis.onnx` | tag checks, skeletons, cutting out characters |
| [kohya_ss](https://github.com/bmaltais/kohya_ss) with sd-scripts (default location `C:\kohya_ss`, otherwise set the `NK_KOHYA` environment variable) | training a LoRA of your own character ([docs/TRAINING.md](docs/TRAINING.md), Korean) |
| Tag lists `tags/danbooru.csv`, `tags/e621.csv` ([a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)) | tag checks, character lookup ([docs/ADDING.md](docs/ADDING.md) section 4) |

- To list the installed ComfyUI nodes: `nk ep nodes` (read-only)
- **No model files are included in this repository.** Check and follow each model's own license (non-commercial terms, etc.).

### Install

1. Download this repository (Code → Download ZIP, or `git clone`).
2. Python packages: `python -m pip install -r requirements.txt`
   - `nk.bat` looks for Python in this order: the `NK_PYTHON` environment variable (path to python.exe) → `python` on PATH if these packages are installed there → `C:\kohya_ss\venv`.
3. Install ComfyUI and add the models above (plus Impact Pack if you use a LoRA character). Keep ComfyUI running.
   A step-by-step beginner guide (Korean only): [docs/QUICKSTART.md](docs/QUICKSTART.md).
4. Run any command once in a terminal (PowerShell) and **accept the use policy** (type `agree`): `.\nk.bat list`
5. Add your characters. No character files are included; `characters/_template.yaml` is the template. Attach `AI_캐릭터_만들기.md` to an AI chat and describe your character, and it writes the character file for you. To write one by hand, see [docs/ADDING.md](docs/ADDING.md) (Korean).

### Usage

Korean file names: `작업실.bat` = Workshop, `만화만들기.bat` = Make a comic, `AI_캐릭터_만들기.md` = character request file, `AI_글콘티_만들기.md` = storyboard request file (both are attached to an AI chat).

- **Workshop (web UI)**: double-click `작업실.bat` → open `http://127.0.0.1:8765` in a browser — new comic, continue, redraw a cut, view results. It only opens on this PC.
- **Menu**: `만화만들기.bat` — 1 make the storyboard attachment / 2 paste the AI's answer / 3 make / 4 fix a cut / 5 dialogue only / 6 results / 7 add a character
- **Commands**:
  ```
  .\nk.bat ep aifile          # make AI_글콘티_만들기.md -> attach it to a new AI chat and describe the comic you want
  .\nk.bat ep paste ep01        # save the copied AI answer as episodes/ep01/plan.yaml + check it
  .\nk.bat ep auto ep01         # start to finish: storyboard -> draw -> fix -> balloons -> review
  .\nk.bat ep fix ep01 3 --add "smile"   # change cut 3's tags and redraw only that cut
  ```
  Output: `episodes/<episode>/out*/page_*.png`, `book.pdf`, one-sheet review `episodes/<episode>/auto/review.png`
- More commands: `.\nk.bat --help`, `.\nk.bat ep`, [nk_guide.md](nk_guide.md). Plan format: [docs/prompt_plan.md](docs/prompt_plan.md), storyboard rules: [docs/conti_rules.md](docs/conti_rules.md) (all Korean)

### Folders

```
nk.bat / nk*.py      commands (nk ep ...)
presets.yaml         defaults, artists (add your own), scenes
characters/          character files (add your own; _template.yaml is the template)
docs/                plan rules (prompt_plan.md), storyboard rules, how to add things (ADDING.md), plan example
fonts/               balloon and sound-effect fonts (SIL OFL 1.1, fonts/FONTS.md)
tools/pose3d/        3D doll pose images
tests/               tests (fake ComfyUI, fake checking AI, fake test characters)
episodes/ runs/      comics and images you make (not uploaded to the repository)
```

### Tests (no GPU)
```
python -m pip install pytest
python -m pytest tests/unit -q          # unit tests
python tests/run_selftest.py            # whole nk ep auto flow with a fake ComfyUI and a fake checking AI
```

### Known limitations
- Only one LoRA character per comic, and no more than two characters per cut. Back views, lying full-body shots and heavily overlapping poses are still weak.
- The automatic checks (a small vision model) are often wrong. A person makes the final call by looking at full-resolution images.
- The 3D scene renderer (Blender scripts) is not included in this release → 3D pose control works only with the capsule doll.
- The UI and messages are in Korean.

### License
- Code and docs: **PolyForm Noncommercial License 1.0.0** ([LICENSE](LICENSE)) — non-commercial use only. Required Notice: Copyright (c) 2026 니코 (Niko)
- Fonts: SIL Open Font License 1.1 ([fonts/FONTS.md](fonts/FONTS.md))
- Other models, tools and tag lists follow their own licenses (none are included in this repository).
