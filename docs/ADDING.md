# 캐릭터와 작가(그림체) 직접 추가하기

이 저장소에는 캐릭터 파일도, 작가 목록도 없다. 쓰고 싶은 캐릭터와 그림체는 직접 넣어야 한다.

> ⚠ 꼭 지킬 것 (자세한 건 [USE_POLICY.md](../USE_POLICY.md))
> - 전연령(safe) 그림만 만든다. 성인물이나 선정적이거나 잔혹한 묘사는 캐릭터 파일에 넣지 않는다.
> - 실존 인물을 캐릭터로 만들지 않는다.
> - 남의 캐릭터나 작가 그림체는 개인적인 비상업 용도로만, 권리자가 정한 규칙(2차 창작 가이드라인 등) 안에서 쓴다.
>   만든 그림을 공개하거나 퍼뜨리는 책임은 전부 사용자에게 있다.
> - 살아 있는 작가 중엔 AI가 자기 그림체를 흉내 내는 걸 원하지 않는 사람이 많다. 작가의 뜻을 존중한다.

---

## 1. 캐릭터 추가

캐릭터 하나에 `characters/<영어이름>.yaml` 파일 하나다. 계획표와 콘티에서는 `cast: {짧은이름: 파일이름}` 식으로 부른다.

### 방법 A: 양식을 복사해서 직접 쓰기 (내 OC)
직접 쓰기 귀찮으면 키트 폴더의 `AI_캐릭터_만들기.md`를 AI 채팅에 첨부하고 캐릭터를 설명하면 된다. 이 양식대로 파일을 써 준다.

1. `characters/_template.yaml`을 복사해서 `characters/mychar.yaml`처럼 저장한다.
2. 맨 위 `ai_hide: true` 줄을 지운다. 양식에만 있는 줄이고, 남겨 두면 캐릭터 목록에 안 나온다.
3. 꼭 채울 칸은 `name`, `trigger`, `name_ko`, `personality`, `tags_short`, `tags_full`, `anima`, `compose_name`이다.
   - 태그는 Danbooru나 e621에 실제로 있는 것만 쓴다 (밑줄 대신 띄어쓰기). 문장은 `anima` 칸에 짧은 영어로 쓴다.
   - 옷이나 무늬처럼 그 캐릭터를 알아보게 하는 건 `tags_full`과 `anima`에 넣는다. 색은 꼭 붙인다 (`blue hoodie`처럼).
4. `nk list`에 이름이 나오는지 보고, `nk gen --char mychar --scene white --n 2 --dry`로 프롬프트가 제대로 나오는지 확인한다.

### 방법 B: 그림 모델이 이미 아는 캐릭터 (태그가 있는 캐릭터)
```
nk ep charfind <영어 이름> <작품 이름>      # 태그 사전에서 캐릭터 태그 찾기 (한국어 이름이면 로컬 AI 에게 물어봄)
nk ep charadd <캐릭터_태그> --ko "한국어 이름"   # 시험 그림 몇 장 -> 판별기로 공통 외형 태그 -> 초안 (runs/ 에)
nk ep charadd <캐릭터_태그> --ko "한국어 이름" --save   # 초안이 괜찮으면 characters/ 에 저장
```
- `만화만들기.bat` 메뉴 7번(캐릭터 추가)도 같은 일을 한다.
- 태그 사전(4절)이 있어야 찾을 수 있다. 사전에 없으면 모델이 모르는 캐릭터라서, 방법 A로 만들고 LoRA를 써야 한다.

### 방법 C: LoRA 캐릭터 (직접 학습한 LoRA)
- 모델이 모르는 OC는 LoRA를 학습시키면 훨씬 비슷하게 나온다. LoRA 파일을 ComfyUI의 `models/loras`에 넣고 캐릭터 파일에 적는다:
  ```yaml
  anima_lora: mychar_anima_v1.safetensors   # Anima 흐름 (기본)
  anima_lora_strength: 1.0
  anima_lora_desc: "a small anthro fox boy, orange fur, blue hoodie"
  anima_find: orange fox                    # 두 명 컷에서 이 캐릭터 자리를 찾을 짧은 말 (SAM3)
  ```
- `anima_lora`가 있는 캐릭터가 두 명 컷에 나오면 프로그램이 나눠 그린다. 먼저 LoRA 없이 전체를 그리고, 그 캐릭터 자리만 LoRA로 다시 그린다. 상대 캐릭터에 LoRA가 번지지 않게 하려고 이렇게 한다.
  이 컷에는 ComfyUI 확장 [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack)이 있어야 한다. LoRA 캐릭터는 한 만화에 하나만 쓸 수 있다 (둘 이상이면 첫 캐릭터만).
- 학습은 `nk ep trainanima training/<설정>.yaml`로 돌린다. kohya_ss 설치, 학습 그림 준비, 캡션(`AI_캡션_만들기.md`), 예시 설정(`training/example_anima.yaml`)까지 [TRAINING.md](TRAINING.md)에 순서대로 적어 두었다.
  학습 그림은 직접 그렸거나 권리가 있는 그림만 쓴다.

### 자주 쓰는 선택 칸
| 칸 | 하는 일 |
|---|---|
| `anima_upper`, `anima_head`, `anima_face`, `anima_back` | 컷 거리나 방향마다 다른 짧은 설명 (없으면 `anima`를 씀) |
| `negative_extra` | 이 캐릭터일 때만 더하는 부정 태그 (색 낱말, furry, anthro는 넣지 않기) |
| `duo_exclusive` | 두 명 컷에서 상대에게 옮겨 붙으면 안 되는 이 캐릭터만의 것 |
| `mask_grow`, `mask_cap` | 옷 부피가 큰 캐릭터라면 두 명 컷 영역을 크게 |
| `height_cm` | 두 명 컷 키 차이 (3D 인형) |
| `hands: {tags, desc, expect}` | 손 색 검사 (`expect: dark` 또는 `bright`) |
| `qa_checklist` | 자동 검수 질문. "있나?"가 아니라 "무슨 값인가?"로 묻는다 ([conti_rules.md](conti_rules.md) 4절) |
| `ai_note`, `ai_hide` | 글콘티용 첨부 파일의 캐릭터 목록에 붙는 메모, 목록에서 숨기기 |

캐릭터를 추가하거나 고친 뒤에는 글콘티용 첨부 파일을 다시 만든다 (`nk ep aifile`, 또는 메뉴 1번).

---

## 2. 작가(그림체) 추가

작가는 Danbooru나 e621의 작가 태그 이름으로 적는다. Anima에서는 `@작가이름`, NoobAI 흐름에서는 `by 작가이름` 꼴로 들어가는데, 앞에 붙는 말은 프로그램이 붙인다.

`presets.yaml`에서:
```yaml
main_artists: [artist name one, artist name two]    # 글콘티용 첨부 파일의 '쓸 작가' 목록. 첫 작가가 기본
presets:
  mystyle: {artist: "artist name one", artist_weight: 1.0}   # nk gen --preset mystyle
```
- `main_artists`에 있는 이름은 계획표 검사가 태그 사전 없이도 받아 준다. 거기 없는 이름은 태그 사전(4절)에서 게시물 수를 확인한다.
- 작가를 하나도 안 적으면 작가 태그 없이 그린다. 그러면 그림체가 컷마다 흔들릴 수 있다.
- `artist_note:`에 AI에게 줄 작가 안내 글을 직접 써도 된다.

---

## 3. 그림체 입히기(restyle)와 내 워크플로
- 마지막에 그림체를 입히려면 콘티나 계획표에 `restyle: picturebook`처럼 적는다 (`nk ep restyle`). 쓸 수 있는 이름은 `nk_restyle.py`의 STYLES와 `presets.yaml`의 `restyle:`에 있다.
- 혼자 컷을 내 ComfyUI 워크플로로 그리려면, ComfyUI 메뉴 File → Export Workflow (API)로 저장한 json을 `workflows/<이름>.json`에 넣고 계획표에 `flow: <이름>`을 적는다.
  지금 nk의 기본 그리기를 워크플로 파일로 꺼내려면 `nk ep flow export`.

---

## 4. 태그 사전 (없어도 되지만 있으면 좋다)
태그 검사, 캐릭터 찾기, 작가 확인에 쓴다. 저장소에는 없으니 직접 받아서 `tags/` 폴더에 넣는다.
- `tags/danbooru.csv`, `tags/e621.csv`: [a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete) 저장소의 `tags/` 폴더에 있다 (그 저장소 라이선스를 따른다).
- 없으면 태그 검사만 건너뛰고 나머지는 그대로 돈다.
