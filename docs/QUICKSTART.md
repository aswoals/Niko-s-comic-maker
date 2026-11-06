# 처음 쓰는 사람용 설치·사용 가이드

ComfyUI 한 번도 안 깔아 본 사람 기준으로 씀. 순서대로 따라 하면 첫 만화까지 갈 수 있음.

미리 말하면 설치가 좀 귀찮음. 모델 파일만 7GB 넘게 받아야 하고, ComfyUI 첫 설치도 오래 걸림. 대신 한 번 깔아 두면 그다음부터는 작업실 화면에서 클릭 몇 번이면 됨.

> ⚠ 쓰기 전에 꼭 알아 둘 것 ([USE_POLICY.md](../USE_POLICY.md))
> - **전연령 그림만 됨. NSFW나 잔인한 그림은 금지.** 그런 단어를 넣어도 프로그램이 지움.
> - 불법적인 용도(남의 그림 도용, 실존 인물 사칭 등) 금지.
> - 비상업 전용. 팔거나 커미션 받거나 유료로 쓰는 거 안 됨.
> - **문제가 생기면 책임은 전부 쓰는 사람한테 있음.** 처음 켤 때 '동의'를 쳐야 켜짐.

---

## 0. 이게 뭐냐면

"여우랑 토끼가 눈싸움하는 만화 2쪽" 같은 요청 하나로 컬러 페이지 만화를 뽑아 주는 도구임.

- 이야기(글콘티)는 ChatGPT나 Gemini 같은 AI 채팅이 짜고, 그림은 내 PC의 ComfyUI가 그림.
- 말풍선, 효과음, 쪽 배치까지 알아서 해서 PNG랑 PDF로 나옴.

솔직히 아직 실험작이라 컷마다 잘 나오고 못 나오고가 갈림. 마음에 안 드는 컷은 다시 그리면 되는데, 그 기능은 5번에서 설명함.

## 1. 내 컴퓨터로 되나 확인

| 항목 | 기준 |
|---|---|
| 운영체제 | Windows 10 또는 11 |
| 그래픽카드 | NVIDIA, 그래픽 메모리 8GB 이상 (8GB에서 시험함) |
| 디스크 | 30GB 정도 비워 두면 넉넉함 (SSD 추천) |

그래픽 메모리 확인하는 법: `Ctrl + Shift + Esc`로 작업 관리자 열고 성능 탭 > GPU > '전용 GPU 메모리' 숫자 보면 됨.

AMD, 인텔 그래픽카드나 맥은 시험 안 해 봤음. 아마 안 될 거임.

## 2. 설치 (처음 한 번만)

순서가 중요함. 위에서부터 하나씩.

### 2-1. 파이썬 설치

1. [Python 3.11.9 설치 파일](https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe) 받기 (누르면 바로 받아짐).
   python.org 맨 위의 최신판(3.15 같은 거) 말고 3.11.9 추천함. 필요한 패키지가 다 깔리고, 나중에 LoRA 학습([TRAINING.md](TRAINING.md))을 할 때 쓰는 kohya_ss도 이 버전을 씀.
2. 설치 파일 실행하면 첫 화면 맨 아래에 `Add python.exe to PATH` 체크박스가 있음. **이거 꼭 체크하고** `Install Now` 누르기.
   이거 빼먹으면 나중에 명령어가 안 먹음. 여기서 제일 많이 막힘.

### 2-2. ComfyUI 설치

1. [comfy.org/download](https://www.comfy.org/download)에서 ComfyUI Desktop 받아서 실행.
2. 처음 뜨는 화면(How do you want to run Comfy?)에서 `Local` 고르고, `I agree to the EULA and Terms of Service`에 체크.
   사용 데이터 보내기나 베타 기능 체크는 원하는 대로 하면 됨.
3. `Express Install with recommended settings`에 체크하고 `Continue` 누르면 알아서 깔림.
   설치 위치를 직접 고를 거면 SSD로 하고, C 드라이브 바로 아래(`C:\`)는 피하라는 게 공식 안내임.
4. 기다리기. 처음엔 꽤 오래 걸림. 공식 안내로는 컴퓨터에 따라 1시간 넘게 걸릴 수도 있다고 함.
   템플릿 고르는 화면이 나오면 설치는 끝난 거임. 템플릿은 안 써도 됨.

### 2-3. 그림 모델 6개 받아서 넣기

먼저 모델 넣을 폴더를 염. ComfyUI 왼쪽 위 ☰ 메뉴 > `Desktop Settings` > `Storage` 탭 > `Shared Models`에 적힌 경로를 누르면 탐색기가 열림. 거기 `models` 폴더가 보이면 그 안으로 들어가면 됨.

그다음 아래 링크를 하나씩 눌러서 받고, 오른쪽에 적힌 폴더에 넣기. 링크 누르면 바로 다운로드됨.

| 파일 (누르면 받아짐) | 크기 | 넣을 폴더 |
|---|---|---|
| [anima-base-v1.0.safetensors](https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/diffusion_models/anima-base-v1.0.safetensors) | 4.2GB | `diffusion_models` |
| [qwen_3_06b_base.safetensors](https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/text_encoders/qwen_3_06b_base.safetensors) | 1.2GB | `text_encoders` |
| [qwen_image_vae.safetensors](https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/vae/qwen_image_vae.safetensors) | 254MB | `vae` |
| [sam3.1_multiplex_fp16.safetensors](https://huggingface.co/Comfy-Org/sam3.1/resolve/main/checkpoints/sam3.1_multiplex_fp16.safetensors) | 1.7GB | `checkpoints` |
| [anima-lllite-depth-1.safetensors](https://huggingface.co/Comfy-Org/Anima-LLLite/resolve/main/model_patches/anima-lllite-depth-1.safetensors) | 8MB | `model_patches` |
| [anima-lllite-any-test-like-v2.safetensors](https://huggingface.co/Comfy-Org/Anima-LLLite/resolve/main/model_patches/anima-lllite-any-test-like-v2.safetensors) | 16MB | `model_patches` |

- 폴더가 없으면 그 이름으로 새로 만들면 됨.
- 파일 이름 바꾸지 말 것. 프로그램이 이 이름 그대로 찾음.
- 다 넣었으면 ComfyUI 껐다 켜기.
- 이 모델들도 각자 라이선스가 있음 (Anima는 비상업 라이선스). 받는 페이지에서 한 번 확인해 두기.

### 2-4. 만화 제작기 받기

1. [저장소 페이지](https://github.com/mdyjsg09-crypto/Niko-s-comic-maker)에서 초록색 `Code` 버튼 > `Download ZIP`.
2. 압축 풀기. 위치는 `C:\nk`처럼 짧은 경로 추천. 바탕화면이나 OneDrive 폴더는 동기화 때문에 꼬일 수 있어서 피하는 게 나음.
3. 압축 푼 폴더를 열었을 때 `nk.bat`, `작업실.bat`이 바로 보여야 함. 폴더가 한 겹 더 있으면 그 안으로 들어가서 쓰면 됨.

### 2-5. 필요한 파이썬 패키지 깔기

1. 그 폴더 빈 곳에서 오른쪽 클릭 > `터미널에서 열기` (윈도우 10이면 폴더 주소창에 `powershell` 치고 Enter).
2. 파란 창이 뜨면 아래 줄을 복사해서 붙여 넣고 Enter.
   ```
   python -m pip install -r requirements.txt
   ```
3. 몇 분 기다리면 마지막에 `Successfully installed ...`가 뜸. 그럼 끝.

### 2-6. 처음 켜기

1. `작업실.bat` 더블클릭. 파일 출처 경고가 뜰 수도 있는데, 이 저장소에서 받은 거면 `실행` 누르면 됨.
2. 검은 창에 사용 정책이 나옴. 읽어 보고 `동의` 치고 Enter.
3. 브라우저에 작업실 화면(`http://127.0.0.1:8765`)이 자동으로 열림.

검은 창은 끄지 말 것. 그 창을 닫으면 작업실도 같이 꺼짐.

## 3. 캐릭터 만들기 (최소 1명)

저장소에는 캐릭터가 하나도 없음. 직접 만들어야 함. 둘 만들어 두면 이야기 짜기가 훨씬 편함.

### 3-1. AI로 만들기 (추천)

1. 만화 제작기 폴더에 있는 `AI_캐릭터_만들기.md`를 AI 채팅 새 대화에 첨부.
2. 캐릭터를 말로 설명하기. 참고 그림이 있으면 같이 올려도 됨.
   > 주황 털 여우 남자애, 초록 눈, 파란 후드티에 반바지, 장난꾸러기 성격
3. AI가 빠진 걸 몇 개 물어볼 수 있음. 대답하면 YAML을 줌.
4. 그 YAML을 메모장에 붙여 넣고 `characters` 폴더에 `fox.yaml`처럼 저장.
   저장할 때 '파일 형식'을 **모든 파일**로 바꿔야 함. 안 바꾸면 `fox.yaml.txt`로 저장돼서 프로그램이 못 읽음.

맘에 안 드는 데가 있으면 같은 대화에서 "눈을 파란색으로 바꿔 줘"처럼 말하면 고친 걸 다시 줌.

### 3-2. 직접 쓰기

1. `characters` 폴더의 `_template.yaml`을 복사해서 이름을 `fox.yaml`처럼 영어 소문자로 바꾸기.
2. 메모장으로 열어서 아래 칸만 고치면 됨.

| 칸 | 넣을 것 | 예시 |
|---|---|---|
| (맨 위) `ai_hide: true` | **이 줄은 지우기.** 안 지우면 캐릭터 목록에 안 나옴 | |
| `name`, `trigger` | 파일 이름이랑 똑같이 | `fox` |
| `name_ko` | 한국어 이름 | `여우` |
| `personality` | 성격이랑 말투 한 줄. 대사가 이 말투로 나옴 | `밝고 장난스러움. 짧은 반말.` |
| `tags_short`, `tags_full` | 생김새를 영어 태그로, 쉼표로 구분 | `1boy, furry, anthro, fox boy, orange fur` |
| `anima` | 생김새를 짧은 영어 문장으로 | `A small anthro fox boy with orange fur.` |
| `compose_name` | 겉모습으로 부르는 이름 | `orange fox boy` |

- 태그는 Danbooru나 e621에 실제로 있는 태그를 써야 잘 먹힘. 색은 꼭 붙이기 (`blue hoodie`처럼).
- `qa_`로 시작하는 아래쪽 칸은 안 건드려도 됨.
- 콜론(`:`) 뒤에는 한 칸 띄우고, 따옴표는 열었으면 닫기. 이거 틀리면 파일을 못 읽음.

남의 캐릭터나 실존 인물은 만들지 말 것. 자세한 칸 설명은 [ADDING.md](ADDING.md)에 있음.

## 4. 첫 만화 만들기

ComfyUI 켜 두고 작업실 화면에서 함.

1. 왼쪽 맨 아래 '새 만화' 칸에서 `글콘티용 첨부 파일 만들기` 누르기. 키트 폴더에 `AI_글콘티_만들기.md`가 생김.
   이 파일에는 내 캐릭터 목록이 들어가서, 캐릭터를 새로 만들거나 고쳤으면 이 버튼을 다시 눌러야 함.
2. ChatGPT, Gemini 같은 AI 채팅에서 새 대화를 열고 `AI_글콘티_만들기.md`를 첨부. 그리고 만들고 싶은 만화를 그냥 말로 쓰기.
   > 여우랑 토끼가 눈싸움하는 만화, 2쪽, 마지막에 눈사람이 무너지는 장면 꼭
   - 첨부가 안 되는 AI면 파일 내용을 통째로 복사해서 붙여 넣어도 됨 (1만 7천 자쯤).
   - 뭐라고 써야 할지 모르겠으면 작업실의 'AI 채팅에 보낼 요청 글 만들기'를 펼쳐서 칸만 채우면 요청 글을 대신 써 줌.
   - 줄거리부터 보고 싶으면 '줄거리 먼저'라고 쓰기. 마음에 들면 '좋아'라고 하면 계획표를 줌.
3. AI가 준 답을 처음부터 끝까지 전부 복사해서 작업실의 'AI 답 전체' 칸에 붙여 넣기.
4. '에피소드 이름'에 영어나 숫자로 이름 넣기 (예: `ep01`). 한글은 안 됨.
5. `글콘티 검사하기` 누르기.
   - 통과하면 바로 그리기 시작함.
   - 고칠 점이 있으면 창이 뜸. 창에 나온 글을 `복사`해서 AI 채팅 같은 대화에 붙여 넣고, 새로 받은 답으로 3번부터 다시.
6. 기다리기. 8GB 그래픽카드에서 2쪽에 15분쯤 걸림 (컴퓨터마다 다름). 그동안 게임처럼 그래픽카드 쓰는 건 끄는 게 좋음.
7. 다 되면 왼쪽 '만화 목록'에서 만화를 고르면 결과가 보임. 파일은 `episodes\ep01\out` 폴더에 `page_01.png` 같은 쪽 그림이랑 `book.pdf`로 생김.

## 5. 마음에 안 드는 컷 고치기

작업실에서 만화를 고르면 컷마다 버튼이 있음.

- `다시 그리기`: 같은 내용으로 새로 그림. 누를 때마다 다른 그림이 나옴.
- `후보 3장`: 3장 그려 놓고 그중에 고르기. 지금 그림은 고를 때까지 그대로 있음.
- `태그 고치기`: 태그를 더하거나 빼고 `고쳐서 다시 그리기`.

`수정하기`(말로 고치기)는 Ollama라는 로컬 AI가 있어야 돼서 처음엔 안 될 거임.

경험상 뒷모습, 누워 있는 전신, 둘이 꼭 붙어 있는 자세가 제일 잘 깨짐. 그런 컷은 그냥 몇 번 다시 그리는 게 빠름. 한 컷에 세 명 이상은 아예 안 됨.

## 6. 막혔을 때

| 이런 게 보이면 | 이렇게 |
|---|---|
| 명령어 쳤는데 `python`을 못 찾는다고 나오거나 Microsoft Store가 열림 | 파이썬 깔 때 `Add python.exe to PATH`를 체크 안 한 거임. 파이썬 다시 설치하면서 체크 |
| `ModuleNotFoundError: No module named ...` | 2-5 패키지 설치를 안 했거나 실패한 거임. 다시 하기 |
| `[ERROR] ComfyUI not reachable` | ComfyUI가 꺼져 있음. 켜고 화면이 다 뜰 때까지 기다린 다음 다시 |
| `[ERROR] 작업실이 이미 켜져 있음` | 작업실 검은 창이 이미 하나 떠 있음. 다른 창 다 닫고 다시 켜기 |
| `캐릭터 파일 없음` | AI가 목록에 없는 캐릭터를 씀. 캐릭터 파일을 만들고 `글콘티용 첨부 파일 만들기`를 다시 누른 다음, AI 채팅 새 대화에 다시 첨부 |
| `YAML을 못 찾음`, `'pages:' 가 없음` | AI 답을 일부만 복사했거나 줄거리만 받은 상태임. 전체 복사하기, 줄거리였으면 '좋아'라고 해서 계획표 받기 |
| 기록에 `Value not in list` | 모델 파일 이름이나 넣은 폴더가 틀림. 2-3 표랑 똑같은지 확인 |
| 기록에 `out of memory` | 그래픽 메모리 부족. 게임, 영상, 다른 AI 프로그램 끄고 다시 |
| 캐릭터가 안 닮음 | 캐릭터 파일의 태그랑 `anima` 문장을 더 자세히. 그래도 안 되면 LoRA 학습 ([TRAINING.md](TRAINING.md)) |

## 7. 더 해 볼 거

- 내 캐릭터 LoRA 학습하고 쓰기: [TRAINING.md](TRAINING.md). LoRA 캐릭터가 나오는 두 명 컷은 ComfyUI 확장 Impact Pack이 따로 필요함.
- 말로 컷 고치기, 자동 검수: [Ollama](https://ollama.com/) 깔고 `gemma4:e4b-it-qat` 모델 받기.
- 명령어로 쓰기: 키트 폴더 터미널에서 `.\nk.bat --help`. 자세한 건 [README](../README.md)랑 [nk_guide.md](../nk_guide.md).
