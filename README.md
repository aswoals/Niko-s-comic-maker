# Niko's Comic Maker (nk 만화 제작기)

**한국어** · [English](#english)

> ## ⚠ 먼저 읽기 — 사용 정책 ([USE_POLICY.md](USE_POLICY.md))
> - **전연령(safe) 그림만.** NSFW·성인·선정적·잔혹한 그림에 쓰지 않는다. 미성년자를 성적으로 다루는 것은 절대 금지.
> - **불법적인 용도 금지.** 저작권·초상권 침해, 실존 인물 사칭, 괴롭힘, 사기 등에 쓰지 않는다.
> - **비상업 전용.** [PolyForm Noncommercial 1.0.0](LICENSE). 판매·유료 서비스·의뢰 등 돈을 버는 일에 쓰지 않는다.
> - **모든 책임은 사용자에게 있다.** 이 프로그램은 "있는 그대로" 제공되며, 이 프로그램과 그 결과물로 생기는 어떤 문제에 대해서도 원작자는 책임지지 않는다.
> - 처음 실행할 때 이 내용에 **동의해야** 쓸 수 있다.
>
> **All-ages only · No NSFW · No illegal use · Non-commercial only · Use at your own risk — the author accepts no liability.** See [USE_POLICY.md](USE_POLICY.md).

"○○와 ○○가 나오는, ○○ 작가 그림체의, ○쪽짜리, ○○한 내용의 만화를 만들어 줘" — 이런 요청 한 번으로 **일본식 페이지 만화(컬러)** 를 만드는 것을 목표로 하는 개인 프로젝트다.
내 PC 의 [ComfyUI](https://www.comfy.org/) 로 그림을 그리고, 이야기 계획은 무료 웹 AI(Grok 등)나 로컬 AI 가 쓴다.

- 원작자: **니코**
- 상태: 개인 취미·공부용으로 만든 **실험적인 프로그램**. 설치가 쉽지 않고, 그림 품질은 모델·캐릭터·작가에 따라 크게 다르다.
- 캐릭터 기본값은 퍼리(수인) 캐릭터에 맞춰져 있다.

## 흐름

```
요청(한국어 자유 문장) ─► 웹 AI(Grok 등)가 계획표 plan.yaml ─► nk 가 콘티 conti.yaml 로 (연출 규칙은 코드가 붙임)
   ─► ComfyUI 로 컷 그리기 (혼자 컷 / 두 명 컷 / 풍경) ─► 자동 검수·고치기 후보 ─► 말풍선·효과음·쪽 조립 ─► PNG·PDF
```

## 필요한 것

**PC**: Windows 10/11, NVIDIA 그래픽카드 (8GB 이상에서 시험), 디스크 여유 수십 GB.

**필수**
| 무엇 | 쓰는 곳 |
|---|---|
| Python 3.10+ 과 `requirements.txt` | nk 명령 |
| [ComfyUI](https://www.comfy.org/) (Desktop 또는 일반) | 그림 그리기. nk 가 8000·8188~8191 포트에서 찾음 |
| Anima 그림 모델 — `anima-base-v1.0.safetensors` (diffusion_models), `qwen_3_06b_base.safetensors` (text_encoders), `qwen_image_vae.safetensors` (vae) — [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima) | 기본 그리기 (`nk ep auto`) |
| ComfyUI 확장 [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) (RegionalSampler 등) | LoRA 캐릭터 두 명 컷 |
| ComfyUI 의 `SAM3_Detect` 노드 + `sam3.1_multiplex_fp16.safetensors` | 캐릭터 자리 찾기 |

**선택** (없으면 그 기능만 안 됨)
| 무엇 | 쓰는 곳 |
|---|---|
| [Ollama](https://ollama.com/) + `gemma4:e4b-it-qat` 같은 작은 비전 모델 | 자동 검수, 한국어 고치기 요청 해석, 로컬 계획 쓰기 |
| Grok·Gemini·ChatGPT 같은 웹 AI (무료판) | 계획표 쓰기 (`Grok_첨부용.md` 를 첨부) |
| NoobAI-XL V-Pred 1.0 ([Laxhar/noobai-XL-Vpred-1.0](https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0)) | 예전 흐름 `--render noob`, `nk gen` |
| Qwen-Image-Edit 2509 (fp8) + `qwen_2.5_vl_7b_fp8_scaled` | 문장으로 컷 고치기, 소품 넣기, 두 명 합치기 |
| [ComfyUI-Anima-LLLite](https://github.com/kohya-ss/ComfyUI-Anima-LLLite) + LLLite 모델 | 3D 인형으로 자세 조종 (`pose3d`) |
| [comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes) | 두 명 컷 시험 방식 일부 |
| 판별기 `models/wd-eva02-large-tagger-v3/` (ONNX), DWPose `models/dwpose/dw-ll_ucoco_384.onnx`, anime-seg `models/animeseg/isnetis.onnx` | 태그 판별 검사, 뼈대, 캐릭터 잘라내기 |
| [kohya-ss sd-scripts](https://github.com/kohya-ss/sd-scripts) (기본 위치 `C:\kohya_ss`, 다르면 환경 변수 `NK_KOHYA`) | 내 캐릭터 LoRA 학습 |
| 태그 사전 `tags/danbooru.csv`, `tags/e621.csv` ([a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)) | 태그 검사·캐릭터 찾기 ([docs/ADDING.md](docs/ADDING.md) 4절) |

- 설치된 ComfyUI 노드 목록 보기: `nk ep nodes` (읽기만 함)
- **모델 파일은 이 저장소에 없다.** 각 모델의 라이선스(비상업 조건 등)를 직접 확인하고 지킨다.

## 설치

1. 이 저장소를 내려받는다 (Code → Download ZIP 또는 `git clone`).
2. 파이썬 패키지: `python -m pip install -r requirements.txt`
   - `nk.bat` 은 환경 변수 `NK_PYTHON`(python.exe 경로) → `C:\kohya_ss\venv` → PATH 의 `python` 순서로 파이썬을 찾는다.
3. ComfyUI 를 설치하고 위 모델·확장을 넣는다. ComfyUI 를 켜 둔다.
4. 처음 한 번 창(PowerShell)에서 아무 명령이나 실행해 **사용 정책에 동의**한다: `.\nk.bat list`
5. 캐릭터를 추가한다 → [docs/ADDING.md](docs/ADDING.md). (저장소에는 캐릭터 파일이 없다. `characters/_template.yaml` 이 양식)

## 쓰는 법

- **작업실 (화면)**: `작업실.bat` 더블클릭 → 브라우저 `http://127.0.0.1:8765` — 새 만화, 이어서 만들기, 컷 다시 그리기, 결과 보기. 이 PC 안에서만 열린다.
- **메뉴**: `만화만들기.bat` — 1 Grok 첨부 파일 만들기 / 2 Grok 답 붙여 넣기 / 3 만들기 / 4 컷 고치기 / 5 대사만 / 6 결과 / 7 캐릭터 추가
- **명령**:
  ```
  .\nk.bat ep grokfile          # Grok_첨부용.md 만들기 -> Grok 새 대화에 첨부하고 만들고 싶은 만화를 한국어로 요청
  .\nk.bat ep paste ep01        # 복사해 둔 Grok 답을 episodes/ep01/plan.yaml 로 저장 + 검사
  .\nk.bat ep auto ep01         # 처음부터 끝까지: 콘티 -> 그리기 -> 고치기 -> 말풍선 -> 검토
  .\nk.bat ep fix ep01 3 --add "smile"   # 3번 컷 태그를 고쳐서 그 컷만 다시
  ```
  결과: `episodes/<화>/out*/page_*.png`, `book.pdf`, 검토 한 장 `episodes/<화>/auto/review.png`
- 더 자세한 명령: `.\nk.bat --help`, `.\nk.bat ep`, [nk_guide.md](nk_guide.md). 계획표 형식: [docs/prompt_plan.md](docs/prompt_plan.md), 콘티 규칙: [docs/conti_rules.md](docs/conti_rules.md)

## 폴더

```
nk.bat / nk*.py      명령 (nk ep ...)
presets.yaml         기본값·작가(직접 추가)·장면
characters/          캐릭터 파일 (직접 추가, _template.yaml 이 양식)
docs/                계획표 규칙(prompt_plan.md), 콘티 규칙, 추가 방법(ADDING.md), Grok 예시
fonts/               말풍선·효과음 글꼴 (SIL OFL 1.1, fonts/FONTS.md)
tools/pose3d/        3D 인형 자세 그림
tests/               시험 (가짜 ComfyUI·가짜 검수 AI·시험용 가짜 캐릭터)
episodes/ runs/      내가 만든 만화·그림 (저장소에 올리지 않음)
```

## 시험 (GPU 안 씀)
```
python -m pip install pytest
python -m pytest tests/unit -q          # 단위 시험
python tests/run_selftest.py            # 가짜 ComfyUI·가짜 검수 AI 로 nk ep auto 전체 흐름
```

## 알려진 한계
- 한 만화에 LoRA 캐릭터는 하나만. 한 컷에 세 명 이상은 안 됨. 뒷모습·누운 전신·몸이 많이 겹치는 자세는 아직 약함.
- 자동 검수(작은 비전 모델)는 틀릴 때가 많다. 최종 판단은 사람이 원본 해상도로 본다.
- 3D 장면 렌더러(Blender 스크립트)는 이 공개본에 들어 있지 않다 → 3D 자세 조종은 캡슐 인형으로만 된다.
- 화면·안내문은 한국어.

## 라이선스
- 코드·문서: **PolyForm Noncommercial License 1.0.0** ([LICENSE](LICENSE)) — 비상업 용도로만. Required Notice: Copyright (c) 2026 니코 (Niko)
- 글꼴: SIL Open Font License 1.1 ([fonts/FONTS.md](fonts/FONTS.md))
- 그 밖의 모델·도구·태그 목록은 각자의 라이선스를 따른다 (이 저장소에 들어 있지 않음).

---

## English

> ### ⚠ Read first — Use Policy ([USE_POLICY.md](USE_POLICY.md))
> - **All-ages (safe) images only.** Do not use this for NSFW, adult, sexually suggestive, or gory content. Any sexual depiction of minors is absolutely forbidden.
> - **No illegal use.** No copyright or likeness infringement, impersonation of real people, harassment, fraud, and so on.
> - **Non-commercial only.** [PolyForm Noncommercial 1.0.0](LICENSE). Do not use it to make money (selling, paid services, commissions, etc.).
> - **You are solely responsible.** The software is provided "as is". The author accepts no liability for any problem arising from the software or anything made with it.
> - You must **agree** to this policy on first run.

A personal project that aims to make a **colored, Japanese-style page comic** from a single request such as "make a ○-page comic starring ○○ and ○○, in ○○'s art style, about ○○".
Images are drawn by [ComfyUI](https://www.comfy.org/) on your own PC; the story plan is written by a free web AI (Grok, etc.) or a local AI.

- Author: **Niko**
- Status: an **experimental** program made as a personal hobby and study project. Setup is not easy, and image quality varies a lot by model, character and art style.
- Character defaults are tuned for furry (anthro) characters.
- The UI, messages and most docs are in **Korean** only.

### Flow

```
Request (free-form sentence) ─► web AI (Grok, etc.) writes plan.yaml ─► nk turns it into the storyboard conti.yaml (directing rules are added by code)
   ─► ComfyUI draws each cut (solo / two characters / scenery) ─► automatic checks and fix candidates ─► speech balloons, sound effects, page layout ─► PNG / PDF
```

### Requirements

**PC**: Windows 10/11, NVIDIA GPU (tested with 8 GB+), tens of GB of free disk space.

**Required**
| What | Used for |
|---|---|
| Python 3.10+ and `requirements.txt` | nk commands |
| [ComfyUI](https://www.comfy.org/) (Desktop or standard) | drawing. nk looks for it on ports 8000 and 8188–8191 |
| Anima image model — `anima-base-v1.0.safetensors` (diffusion_models), `qwen_3_06b_base.safetensors` (text_encoders), `qwen_image_vae.safetensors` (vae) — [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima) | default drawing (`nk ep auto`) |
| ComfyUI extension [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) (RegionalSampler, etc.) | two-character cuts with a LoRA character |
| ComfyUI `SAM3_Detect` node + `sam3.1_multiplex_fp16.safetensors` | finding where each character is |

**Optional** (without it, only that feature is unavailable)
| What | Used for |
|---|---|
| [Ollama](https://ollama.com/) + a small vision model such as `gemma4:e4b-it-qat` | automatic checks, reading Korean edit requests, writing plans locally |
| A web AI such as Grok, Gemini or ChatGPT (free tier) | writing the plan (attach `Grok_첨부용.md`) |
| NoobAI-XL V-Pred 1.0 ([Laxhar/noobai-XL-Vpred-1.0](https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0)) | legacy flow `--render noob`, `nk gen` |
| Qwen-Image-Edit 2509 (fp8) + `qwen_2.5_vl_7b_fp8_scaled` | editing a cut with a sentence, adding props, merging two characters |
| [ComfyUI-Anima-LLLite](https://github.com/kohya-ss/ComfyUI-Anima-LLLite) + an LLLite model | pose control with a 3D doll (`pose3d`) |
| [comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes) | some experimental two-character modes |
| Tagger `models/wd-eva02-large-tagger-v3/` (ONNX), DWPose `models/dwpose/dw-ll_ucoco_384.onnx`, anime-seg `models/animeseg/isnetis.onnx` | tag checks, skeletons, cutting out characters |
| [kohya-ss sd-scripts](https://github.com/kohya-ss/sd-scripts) (default location `C:\kohya_ss`, otherwise set the `NK_KOHYA` environment variable) | training a LoRA of your own character |
| Tag lists `tags/danbooru.csv`, `tags/e621.csv` ([a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)) | tag checks, character lookup ([docs/ADDING.md](docs/ADDING.md) section 4) |

- To list the installed ComfyUI nodes: `nk ep nodes` (read-only)
- **No model files are included in this repository.** Check and follow each model's own license (non-commercial terms, etc.).

### Install

1. Download this repository (Code → Download ZIP, or `git clone`).
2. Python packages: `python -m pip install -r requirements.txt`
   - `nk.bat` looks for Python in this order: the `NK_PYTHON` environment variable (path to python.exe) → `C:\kohya_ss\venv` → `python` on PATH.
3. Install ComfyUI and add the models and extensions above. Keep ComfyUI running.
4. Run any command once in a terminal (PowerShell) and **accept the use policy** (type `agree`): `.\nk.bat list`
5. Add your characters → [docs/ADDING.md](docs/ADDING.md) (Korean). No character files are included; `characters/_template.yaml` is the template.

### Usage

Korean file names: `작업실.bat` = Workshop, `만화만들기.bat` = Make a comic, `Grok_첨부용.md` = file to attach to Grok.

- **Workshop (web UI)**: double-click `작업실.bat` → open `http://127.0.0.1:8765` in a browser — new comic, continue, redraw a cut, view results. It only opens on this PC.
- **Menu**: `만화만들기.bat` — 1 make the Grok attachment / 2 paste Grok's answer / 3 make / 4 fix a cut / 5 dialogue only / 6 results / 7 add a character
- **Commands**:
  ```
  .\nk.bat ep grokfile          # make Grok_첨부용.md -> attach it to a new Grok chat and describe the comic you want
  .\nk.bat ep paste ep01        # save the copied Grok answer as episodes/ep01/plan.yaml + check it
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
docs/                plan rules (prompt_plan.md), storyboard rules, how to add things (ADDING.md), Grok example
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
