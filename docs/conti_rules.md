# 콘티 작성 규칙서 (conti_rules.md)

> 시험 만화를 그리면서 실제로 틀린 것을 모아 만든 규칙. 지킬 수 있는 건 코드가 검사한다: `.\nk ep check <에피소드>`
> 보통은 계획표(plan.yaml)만 쓰면 되고(`docs/prompt_plan.md`), 콘티(conti.yaml)는 프로그램이 만든다.
> 이 문서는 콘티를 직접 고칠 때 참고용이다.

---

## 0. 작업 순서

1. **이야기** — 기승전결을 한 줄씩. 페이지당 한 단계.
2. **페이지 나누기** — 페이지마다 줄(rows)과 컷 크기. 가장 중요한 순간이 가장 큰 컷.
3. **컷 카드 쓰기** — 아래 1번 형식대로.
4. **검사** — `.\nk ep check ep01` → 경고 0개가 될 때까지 고침 (몇 초, 그림 안 그림).
5. **모의 실행** — `.\nk ep redo ep01 --all --dry` 로 실제 들어갈 프롬프트 확인.
6. **그리기** — `.\nk ep redo ep01 --all` (또는 문제 컷만).
7. **검수** — 원본 해상도로 보고 → 문제 컷만 다시.

---

## 1. 컷 카드 형식

```yaml
      - id: 7
        scene: "solo, blank stare, empty eyes, sweatdrop"   # 인물 수 + 동작 1개 + 표정. 카메라·장소 태그 넣지 않음
        shot: face          # 필수: wide / full / knee / waist / face / detail
        angle: high         # 필수: eye / high / low / side / back / tilt / pov
        loc: kitchen        # 캐릭터 컷은 필수: world.locations 키
        props: [yarn]       # 등장 소품: world.props 키
        text:
          - {type: speech, text: "…딸기가 없어.", at: top}
        # 선택: n(후보 수) / qa(컷 전용 검수) / neg / extra / flip / crop / char: none(사물 컷)
        #       seed(미리 시험해서 좋았던 시드) / char_drop(이 컷만 캐릭터 태그 빼기)
        #       keep_order: true(scene 의 카메라 태그를 일부러 둠 — 검사 경고 끔)
```
- 장소에 `same_as: garden` → 태그만 조금 다른 같은 장소. "첫 등장" 검사는 원래 장소 기준.

### 두 캐릭터 에피소드
```yaml
chars: {hero: mychar, buddy: buddy}      # 짧은 이름 -> characters/<파일>.yaml
char: hero                               # 컷 기본 캐릭터. 컷에서 char: buddy / char: none

      - id: 4                            # 두 명 컷
        scene: "duo, 2boys"              # 두 사람 공통만 (인원수 + 같이 하는 것). 사람별 동작은 cast에
        shot: knee
        angle: eye
        loc: lawn
        cast:
          - {char: buddy, side: right, pos: "standing, worried", neg: "..."}   # 먼저 말하는 사람 = right
          - {char: hero, side: left, pos: "sitting, embarrassed"}
        text:
          - {type: speech, who: buddy, text: "괜찮아?!"}   # who: 꼬리가 그 사람 쪽. 컷에 없는 사람이면 화면 밖 대사
```
- world의 wear/state에 `who: buddy` → 그 캐릭터 컷에만, 두 명 컷에서는 그 사람 자리에만 붙음
- 검수: 두 명 컷은 **사람마다 자기 자리를 잘라 자기 체크리스트** + 그림 전체로 "몇 명인가"(2명 아니면 불합격)
- 코드 강조선: 컷에 `fx: focus`(집중선, `fx_center: [0.5, 0.4]`) / `fx: speed`(가로 속도선) / `fx: speed_v`(세로)
- 효과음 크기: text 항목에 `size: 56`
- 아직 안 되는 것: 두 캐릭터 **모두** LoRA인 컷 / 3명 이상 / 위아래 배치(자리는 좌우 반씩만)
- LoRA 캐릭터가 나오는 두 명 컷은 프로그램이 나눠 그린다 (LoRA 없이 전체 → LoRA 캐릭터 자리만 LoRA로 다시, `nk ep regionlora`).
- LoRA 없는 두 명 컷도 나눠 그린다 (전체 → SAM3로 두 사람 자리 → 사람마다 자기 글로만 다시, `nk_duosplit`). Impact Pack이 없으면 예전처럼 한 번에. 끄기 = `duosplit_settings.yaml`의 `enabled: false` 또는 계획표에 `duo_split: off`.

**scene에 쓰지 않는 것** (다른 칸이 대신 붙임):
- 카메라(upper body, from above …) → `shot`·`angle`
- 장소(kitchen, window …) → `loc`
- 소품·옷·상태(red yarn ball, pink apron, cream on face) → `props`·`wear`·`state`
- 두 곳에 쓰면 태그가 두 번 붙어서 과해짐. 검사기가 잡음.

---

## 2. scene 쓰는 법 — "그릴 수 있는 말"만

| 규칙 | 이유 |
|---|---|
| **태그 사전에 있는 말만** (`ep check`가 검사) | 문장으로 쓴 동작(오븐에 넣기, 냉장고 들여다보기)은 거의 안 그려짐 |
| **한 컷 = 동작 1개 + 명사 몇 개** | 여러 동작·관계를 한 컷에 넣으면 물건이 섞이고 엉뚱한 도구를 듦 |
| **관계·동작이 안 되면 연출을 바꿈** | 오븐에 넣기 → 오븐 앞에 쪼그려 앉기 / 주걱으로 바르기 → 손으로 올리기 |
| **태그 뜻 = 사전 뜻** (아래 목록) | spatula→뒤집개, marker→마커 든 손, circle→둥근 화면 |
| **강조 괄호 `(x:1.2)` 금지** | 색 강조가 털·배경까지 물들임 |
| **괄호 자체 금지** | ComfyUI에서 ( )는 강조 문법. `calendar (object)` → `calendar` |
| **부정 태그에 색+물건 조심** | `red couch`를 부정하면 "red"가 약해져 다른 빨간 것까지 흐려질 수 있음 |
| **사물 컷엔 빛 태그 필수** (sunlight, light rays, lamp, fire …) | 빛 태그가 없으면 새까만 방이 나옴 |
| **어둠을 세게 금지하지 않음** | dark·night를 부정하면 백지가 나옴 |
| **못 그리는 것은 쓰지 않음** (5번 목록) | 몇 번을 다시 그려도 실패 |

### 알게 된 태그 뜻 (사전 뜻 ≠ 영어 뜻)
- `spatula` = 뒤집개 (케이크 주걱은 태그 없음)
- `cake pan` = 태그 없음 → 프라이팬
- `burnt cake` = 초코케이크 → `burnt food, burnt, smoke` + 부정 `chocolate cake`
- `marker` = 마커를 든 손 / `circle` = 둥근 구도(비네팅)
- `pov` = 보는 사람의 손이 화면 앞에 같이 그려질 때가 많음 → 필요하면 부정 `pov hands`
- `strawberry shortcake` = 대부분 조각 케이크 → 통케이크는 `cake, holding plate` + 부정 `cake slice`
- `over the shoulder` (e621) = `looking back`의 별칭 (어깨 너머 구도가 아님)
- `flower pot` = 거의 늘 꽃이 핀 화분. 빈 화분은 `from above, flower pot, soil, dirt` + 부정 `potted plant, plant, petals`
- `hat over eyes` + 캐릭터의 안경 태그 = 안경 속 눈이 그려짐 → 그 컷만 `char_drop`으로 안경 태그 빼기
- `dirty face` = 흰 털에는 거의 안 보임. 이야기에 꼭 필요하면 쓰지 말 것

### 영어 장면 문장 — 보이는 사람 한 명당 한 문장
> plan.yaml 의 `scene`(예전 이름 `sentence`)은 콘티의 `anima_act` 로 들어가 Anima 글 끝에 붙는다. 콘티를 직접 고칠 때도 같은 규칙.
> 예전 규칙 '장면 문장 2~3개 (한 문장이면 동작이 빠짐)'를 대체한다. 한 사람을 여러 문장에 나눠 쓰고 문장마다 그 사람의 겉모습 낱말을 되풀이하면
> 모델이 그 사람을 둘로 읽어 한 컷에 같은 캐릭터가 두 명 그려졌다.

- **한 사람 = 한 문장.** 혼자 컷 1문장, 두 명 컷 2문장 (사람마다 하나), 사람이 없는 풍경·소품 컷 1문장. 같은 사람을 두 문장 이상에 나눠 쓰지 않는다.
- 한 문장 안에 그 사람의 **동작·시선·표정**을 다 담는다. 쉼표·대시(—)·분사(`looking …`)·`with`·`and` 로 잇는다. 길이 제한은 없다.
- 문장은 그 사람의 **겉모습 낱말**로 시작한다 (`the fox boy …`, `the rabbit girl …`). 캐릭터 이름·옷 설명은 쓰지 않는다.
- **두 명 컷**: 문장마다 그 사람 **자신의** 동작·시선·표정만 쓴다. 상대는 겉모습 낱말로만 가리키고 `he`·`his`·`her`·`him` 으로 상대를 가리키지 않는다. 상대의 동작을 내 문장에 넣지 않는다.
- 두 문장은 **같은 한 순간**을 보여 준다. 한 사람은 가만히 있고 다른 사람에게만 사건이 일어나면 칸이 두 장면으로 갈라진다.
- **얼굴이 칸 밖인 사람**은 그 문장에 동작 + `his face is out of frame` (또는 `her face is out of frame`) 만 쓴다.
  그 사람의 태그(두 명 컷 = cast 의 `pos`, plan 의 roles / 혼자 컷 = 컷 `scene`, plan 의 action)에 `head out of frame` 을 넣으면
  프로그램이 그 사람의 머리 묘사 태그·서로 보기 문장·3D 인형 머리를 빼고, 캐릭터 파일에 `anima_body`(머리 없는 몸 설명)가 있으면 그것을 쓴다.

| | 예 |
|---|---|
| 좋음 (혼자) | `The fox boy kneels by the puddle, poking the water with one finger and staring at the ripples with wide, curious eyes.` |
| 나쁨 (혼자) | `The fox boy kneels by the puddle. The fox boy pokes the water with one finger. He looks curious.` (한 사람이 세 문장 → 두 명으로 그려짐) |
| 좋음 (두 명) | `The rabbit girl holds out a red apple with both hands, smiling at the fox boy. The fox boy reaches for the apple with his right hand, his eyes sparkling.` |
| 나쁨 (두 명) | `The rabbit girl holds out an apple and he takes it happily.` (상대를 he 로, 상대의 동작이 내 문장에) |

---

## 3. 연출 규칙

### 거리 (shot)
| 값 | 태그 | 쓰는 곳 |
|---|---|---|
| wide | wide shot, full body (+ 인물 없는 컷만 scenery) | **장소 첫 등장**. 인물이 작음 → 표정 컷 아님 |
| full | full body | 큰 동작·이동 |
| knee | cowboy shot | 몸짓 + 표정 (반응, 결심) |
| waist | upper body | 대화 |
| face | portrait, close-up | 감정이 핵심인 순간 |
| detail | close-up | 사물·손 (char: none) |

### 각도 (angle) — 감정에 맞춰
| 값 | 태그 | 느낌 |
|---|---|---|
| eye | (없음) | 중립, 대화 |
| high | from above | 작고 약해 보임 → 좌절·슬픔·당황 |
| low | from below | 크고 결연해 보임 → 결심·박력 |
| side | from side | 이동·동작, 무언가를 들여다봄 |
| back | from behind | 떠나는 뒷모습 (아직 약함 — 아껴 쓸 것). 등 무늬는 그린 뒤 `nk ep backfix`로 고침 → **인물을 크게(knee~full)** |
| tilt | dutch angle | 혼란·놀람 |
| pov | pov | 화면 밖 인물의 눈으로 봄 |

### 검사기가 잡는 규칙
1. 모든 컷에 shot·angle (사물 컷은 detail 기본값)
2. **장소가 처음 나오는 캐릭터 컷은 wide 또는 full** — 전경이 없으면 독자가 어디인지 매 컷 새로 추측함
3. **같은 거리·각도 3연속 금지**
4. **정면(eye) 상반신·얼굴 3연속 금지** + 전체의 절반 이하
5. **큰 동작 컷은 페이지당 1~2개** (역동 포즈 과잉 금지)
6. 강조 괄호 금지 / 사물 컷 빛 태그

### 사람이 지킬 규칙 (검사기가 못 봄)
- **장소 소개 → 인물 → 표정 → 디테일** 순서로 좁혀 들어가기
- **이동 방향은 페이지 내내 한쪽으로**: 오른→왼 만화에서 전진 = 왼쪽. 태그로 방향을 못 정하니 결과를 보고 `flip: true`
- **시선은 다음 컷 쪽**: 오른→왼이면 인물이 왼쪽을 보면 눈이 다음 컷으로 흐름
- **큰 컷 = 중요한 순간**: 페이지마다 제일 큰 컷에 그 페이지의 핵심
- **사물 컷은 페이지당 1개 이하**: 캐릭터가 없어서 그림체가 흔들리기 쉬움
- **두 명 컷·넓은 컷의 얼굴은 작아서 무늬가 빠지기 쉬움**: 다 그린 뒤 `nk ep facefix <ep>`가 머리만 잘라 다시 그림. 얼굴이 중요한 대사 컷은 처음부터 knee~waist로 크게
- **옷 부피가 큰 캐릭터(모자·로브)**: 두 명 컷 영역을 캐릭터 파일 mask_grow·mask_cap으로 크게
- **색이 이어져야 하는 소품은 색까지 태그로**: "checkered"만 쓰면 컷마다 색이 바뀜 → "red checkered picnic blanket"

---

## 4. 검수 질문 쓰는 법 (캐릭터 파일 qa_checklist)

| 규칙 | 이유 |
|---|---|
| **있나?가 아니라 무슨 값인가?** | "모자 있나?"는 색이 틀려도 통과함 → "모자 색은?" |
| **틀리기 쉬운 답을 보기에 넣기** | "손에 든 건? 딸기 / 뒤집개 / 주걱" 처럼 실제로 자주 나오는 틀린 답을 보기로 |
| **맞는 그림이 떨어질 경우를 생각하기** | 목도리가 브로치를 가리면 정답 그림이 탈락할 수 있음 → 보기에 "가려져 안 보임" |
| **사물 컷에도 질문 달기** | 질문이 없으면 검수를 건너뜀 |
| **검수 AI를 믿지 말 것** | 백지·검은 그림에도 그럴듯하게 답함 → 백지·검정은 픽셀 검사로 먼저 거름 |
| **태그로 확인할 수 있는 건 판별기로** (`{tag: flower, max: 0.8, must: true}`) | 판별기가 "있다/없다"는 더 정확함. 단 "어디에"는 모름 → 컷마다 문턱을 정함 |
| 두 명 컷 "몇 명인가"는 판별기가 자동으로 봄 (2boys 등 0.45 이상) | 검수 AI는 인물 0명 그림도 "두 명"이라고 답할 때가 있음 |
| **"없음·가려짐"과 작은 얼룩은 검수 AI가 못 봄 → must로 쓰지 않기** | |
| **"크기"로 가르지 말고 "종류"로 가르기** | "새싹 / 큰 꽃"이면 작은 꽃을 "새싹"이라고 답함 → "꽃잎 없음 / 꽃잎 있음" |

---

## 5. 지금 이 모델로 안 되는 것 (피해서 연출)

- 물건이 몸에 감긴 상태 → 옆에 굴러다니는 물건 + 뒤 컷에 가닥
- A를 B에 넣기·올리기·바르기 같은 두 물체 관계 → 전·후 상태 컷으로 나눔
- **인물 컷에 scenery 태그 금지**: 인물이 사라지거나 배경에 묻힘. 코드가 shot: wide 인물 컷에서 자동으로 뺌
- **캐릭터가 드는 물건 색은 틀릴 수 있음**: 캐릭터의 색 태그가 물건에 번짐
  → 물건 색·종류 태그를 같이 쓰고(green hat, wizard hat) 판별기 검사 `{tag: green_headwear, min: 0.5, must: true}`
  → 손에 든 물건·일부만 보이는 물건은 판별기 점수가 낮게 나옴 → 문턱을 낮게(0.3)
- 뒷모습·누운 전신은 아직 약함
- 작은 인물의 얼굴: wide 컷에서 얼굴이 뭉개질 수 있음 → wide 컷엔 표정 대사를 싣지 않음

---

## 6. 명령 넣기 전 체크리스트

- [ ] 어려운 컷(모델이 잘 안 그리는 사물·상태)은 **먼저 같은 시드로 몇 장 시험** → 잘 된 시드를 `seed:`로 고정
- [ ] `.\nk ep check <ep>` — 연출 경고 0, 태그 경고는 전부 이유가 있는 것만
- [ ] 캐릭터 태그(characters/*.yaml)를 바꿨으면 → 전체 재생성 (일부만 다시 그리면 옛 컷과 어긋남)
- [ ] `--dry`로 프롬프트 한 번 읽어보기 (태그가 두 번 붙거나 엉뚱한 게 붙지 않았나)

## 참고 자료
- 컷 종류와 용도: [Clip Studio — Comic & Manga Layouts, Paneling, Flow](https://www.clipstudio.net/how-to-draw/archives/160963)
- 전경→인물→표정→디테일, 각도별 느낌: [Gootaku — Manga Panel Composition Rules](https://gootaku.com/blog/manga-panel-composition-rules)
- 화면 방향 규칙: [Wikipedia — Screen direction](https://en.wikipedia.org/wiki/Screen_direction)
- 태그 사전: [a1111-sd-webui-tagcomplete tags](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)
