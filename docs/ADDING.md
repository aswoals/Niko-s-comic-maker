# 캐릭터·작가(그림체) 직접 추가하기

이 저장소에는 **캐릭터 파일과 작가 목록이 들어 있지 않다.** 쓰고 싶은 캐릭터와 그림체는 사용자가 직접 추가한다.

> ⚠ **꼭 지킬 것** (자세히는 [USE_POLICY.md](../USE_POLICY.md))
> - 전연령(safe) 그림만. 성인·선정적·잔혹한 묘사를 캐릭터 파일에 넣지 않는다.
> - 실존 인물을 캐릭터로 만들지 않는다.
> - 남의 저작권 캐릭터·작가 그림체는 **개인적인 비상업 용도**로만, 그 권리자의 규칙(2차 창작 가이드라인 등)을 지키는 범위에서 쓴다.
>   만든 그림을 공개하거나 퍼뜨릴 때의 책임은 전부 사용자에게 있다.
> - 살아 있는 작가 중에는 AI로 자기 그림체를 흉내 내는 것을 원하지 않는 사람이 많다. 작가의 뜻을 존중한다.

---

## 1. 캐릭터 추가

캐릭터 하나 = `characters/<영어이름>.yaml` 파일 하나. 계획표·콘티에서는 `cast: {짧은이름: 파일이름}` 으로 부른다.

### 방법 A — 양식을 복사해서 직접 쓰기 (내 OC, 처음부터)
1. `characters/_template.yaml` 을 복사해 `characters/mychar.yaml` 처럼 저장한다.
2. 맨 위 `grok_hide: true` 줄을 지운다 (양식 전용 줄).
3. 꼭 채울 것: `name`, `trigger`, `name_ko`, `personality`, `tags_short`, `tags_full`, `anima`, `compose_name`.
   - 태그는 **Danbooru/e621 에 실제로 있는 태그**만 (밑줄은 띄어쓰기). 문장은 `anima` 칸에 짧은 영어로.
   - 옷·무늬처럼 그 캐릭터를 알아보게 하는 것을 `tags_full`·`anima` 에 넣는다. 색은 꼭 붙인다 (`blue hoodie`).
4. 확인: `nk list` 에 이름이 나오는지, `nk gen --char mychar --scene white --n 2 --dry` 로 프롬프트가 맞는지 본다.

### 방법 B — 그림 모델이 이미 아는 캐릭터 (태그가 있는 캐릭터)
```
nk ep charfind <영어 이름> <작품 이름>      # 태그 사전에서 캐릭터 태그 찾기 (한국어 이름이면 로컬 AI 에게 물어봄)
nk ep charadd <캐릭터_태그> --ko "한국어 이름"   # 시험 그림 몇 장 -> 판별기로 공통 외형 태그 -> 초안 (runs/ 에)
nk ep charadd <캐릭터_태그> --ko "한국어 이름" --save   # 초안이 괜찮으면 characters/ 에 저장
```
- `만화만들기.bat` 메뉴 7번(캐릭터 추가)도 같은 일을 한다.
- 태그 사전(아래 4절)이 있어야 찾을 수 있다. 사전에 없으면 모델이 모르는 캐릭터 → 방법 A + LoRA.

### 방법 C — LoRA 캐릭터 (직접 학습한 LoRA)
- 모델이 모르는 OC 는 LoRA 를 학습하면 훨씬 비슷하게 나온다. LoRA 파일을 ComfyUI `models/loras` 에 넣고 캐릭터 파일에 적는다:
  ```yaml
  anima_lora: mychar_anima_v1.safetensors   # Anima 흐름 (기본)
  anima_lora_strength: 1.0
  anima_lora_desc: "a small anthro fox boy, orange fur, blue hoodie"
  anima_find: orange fox                    # 두 명 컷에서 이 캐릭터 자리를 찾을 짧은 말 (SAM3)
  ```
- `anima_lora` 가 있는 캐릭터가 나오는 두 명 컷은 프로그램이 **나눠 그린다**: LoRA 없이 전체 → 그 캐릭터 자리만 LoRA 로 다시 (상대에게 LoRA 가 번지지 않게).
  한 만화에 LoRA 캐릭터는 하나만 (둘 이상이면 첫 캐릭터).
- 학습 도우미: `nk ep trainanima training/<설정>.yaml` (kohya sd-scripts 필요, 설치 폴더가 `C:\kohya_ss` 가 아니면 환경 변수 `NK_KOHYA`).
  학습 그림은 **직접 그렸거나 권리가 있는 그림만** 쓴다.

### 자주 쓰는 선택 칸
| 칸 | 하는 일 |
|---|---|
| `anima_upper` · `anima_head` · `anima_face` · `anima_back` | 컷 거리·방향마다 다른 짧은 설명 (없으면 `anima`) |
| `negative_extra` | 이 캐릭터일 때만 더하는 부정 태그 (색 낱말·furry·anthro 는 넣지 않기) |
| `duo_exclusive` | 두 명 컷에서 상대에게 옮겨 붙으면 안 되는 이 캐릭터만의 것 |
| `mask_grow` · `mask_cap` | 옷 부피가 큰 캐릭터: 두 명 컷 영역을 크게 |
| `height_cm` | 두 명 컷 키 차이 (3D 인형) |
| `hands: {tags, desc, expect}` | 손 색 검사 (`expect: dark` / `bright`) |
| `qa_checklist` | 자동 검수 질문 — "있나?"가 아니라 "무슨 값인가?"로 ([conti_rules.md](conti_rules.md) 4절) |
| `grok_note` · `grok_hide` | Grok 첨부 파일의 캐릭터 목록 메모 · 목록에서 숨기기 |

캐릭터를 추가·수정한 뒤에는 Grok 첨부 파일을 다시 만든다: `nk ep grokfile` (또는 메뉴 1번).

---

## 2. 작가(그림체) 추가

작가 = Danbooru/e621 의 **작가 태그 이름**. 그림 모델(Anima)은 `@작가이름`, NoobAI 흐름은 `by 작가이름` 으로 쓴다 (프로그램이 붙임).

`presets.yaml` 에서:
```yaml
main_artists: [artist name one, artist name two]    # Grok 첨부 파일의 '쓸 작가' 목록. 첫 작가가 기본
presets:
  mystyle: {artist: "artist name one", artist_weight: 1.0}   # nk gen --preset mystyle
```
- `main_artists` 에 있는 이름은 계획표 검사가 태그 사전 없이도 받아 준다. 없는 이름은 태그 사전(4절)에서 게시물 수를 확인한다.
- 작가를 하나도 안 적으면 작가 태그 없이 그린다 (그림체가 컷마다 흔들릴 수 있음).
- (선택) `artist_note:` 에 Grok 에게 줄 작가 안내 글을 직접 쓸 수 있다.

---

## 3. 그림체 입히기(restyle)·내 워크플로
- 마지막에 그림체 입히기: 콘티/계획표 `restyle: picturebook` 등 (`nk ep restyle`). 이름 목록은 `nk_restyle.py` 의 STYLES 와 `presets.yaml` 의 `restyle:`.
- 혼자 컷을 내 ComfyUI 워크플로로: ComfyUI 메뉴 File → Export Workflow (API) 로 저장한 json 을 `workflows/<이름>.json` 에 넣고 계획표에 `flow: <이름>`.
  지금 nk 의 기본 그리기를 워크플로 파일로 꺼내기: `nk ep flow export`.

---

## 4. 태그 사전 (선택이지만 권장)
태그 검사·캐릭터 찾기·작가 확인에 쓴다. 저장소에는 들어 있지 않으니 직접 받아 `tags/` 폴더에 넣는다:
- `tags/danbooru.csv`, `tags/e621.csv` — [a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete) 의 `tags/` 폴더에 있는 목록 (그 저장소의 라이선스를 따른다)
- 없으면 태그 검사만 건너뛰고 나머지는 그대로 돈다.
