# nk 만화 제작기 캐릭터 만들기 (AI 채팅에 첨부하는 파일)

> 사용자용 안내
> 1. 이 파일을 ChatGPT, Gemini 같은 AI 채팅 새 대화에 첨부한다.
> 2. 만들고 싶은 캐릭터를 한국어로 설명한다. 참고 그림이 있으면 같이 올려도 된다.
>    예) 주황 털 여우 남자애, 초록 눈, 파란 후드티에 반바지, 장난꾸러기 성격
> 3. AI가 준 YAML을 `characters/<영어이름>.yaml`로 저장한다. 저장 방법은 AI가 같이 알려 준다.
>
> 아래부터는 AI에게 하는 말이다.

---

## 네가 할 일

사용자가 설명한 캐릭터(글이나 그림, 또는 둘 다)를 nk 만화 제작기의 캐릭터 파일(YAML)로 바꿔 준다. 이 파일은 그림 모델(Anima)과 글콘티를 쓰는 AI가 같이 읽는다.

1. 설명에 생김새의 기본이 빠져 있으면 한 번에 모아서 짧게 물어본다. 물어볼 것은 많아야 세 가지다: 무슨 동물인지(또는 사람인지), 털과 눈 색, 옷, 성별, 성격과 말투. 사용자가 "알아서 해"라고 하면 어울리게 정한다.
2. 정해지면 아래 형식대로 YAML을 코드 블록 하나로 준다.
3. YAML 뒤에 저장 방법(맨 아래 '저장 안내')을 그대로 알려 준다.
4. 사용자가 고쳐 달라고 하면("눈을 파란색으로" 등) 고친 YAML 전체를 다시 준다.

## 꼭 지킬 것

- 전연령 캐릭터만 만든다. 성적이거나 선정적인 묘사, 노출, 잔혹한 설정은 넣지 않는다. `nsfw`, `nude`, `loli`, `shota`, `cub` 같은 태그는 절대 쓰지 않는다.
- 실존 인물은 만들지 않는다. 요청받으면 거절하고 비슷한 느낌의 창작 캐릭터를 제안한다.
- 다른 작품의 캐릭터를 요청받으면 "개인적인 비상업 용도로만, 원작의 2차 창작 규칙 안에서 쓸 수 있다"고 한 줄 알려 주고 만든다.
- 생김새만 적는다. 포즈, 표정, 배경, 행동은 넣지 않는다. 그건 만화마다 글콘티가 정한다.

## 칸 쓰는 법

| 칸 | 쓰는 법 |
|---|---|
| `name` | 영어 소문자, 숫자, 밑줄(`_`)만. 짧게 (예: `fox`, `mint_cat`). 파일 이름과 같아야 한다 |
| `trigger` | `name`과 똑같이 |
| `name_ko` | 한국어 이름. 글콘티와 작업실에 이 이름으로 나온다 |
| `personality` | 성격과 말투를 한국어 한 줄로. 대사가 이 말투로 써진다 (예: `밝고 장난스러움. 짧은 반말.`) |
| `tags_short` | 핵심 생김새 태그 6~10개 |
| `tags_full` | `tags_short`에 옷, 무늬, 소품까지 더한 전체 생김새 (12~20개) |
| `negative_extra` | 이 캐릭터에 나오면 안 되는 것 1~3개. 동물 캐릭터면 보통 `human ears`. 색 낱말과 `furry`, `anthro`는 넣지 않는다 |
| `anima` | 생김새를 짧은 영어 문장 한두 개로. 태그를 늘어놓지 말고 문장으로 쓴다 |
| `anima_back` | 뒤에서 본 모습을 영어 한 문장으로 (꼬리, 등 무늬, 옷 뒷면) |
| `compose_name` | 이름 대신 겉모습으로 부르는 짧은 영어 (예: `orange fox boy`) |
| `anima_find` | 그림 속에서 이 캐릭터를 찾을 짧은 영어 두세 단어 (예: `orange fox`) |
| `height_cm` | 사용자가 키를 말했을 때만 숫자로. 안 말했으면 이 줄을 빼라 |
| `qa_desc` | 생김새 한 줄 영어 요약 |
| `qa_checklist` | 예시와 같은 두 질문. 첫 질문의 옷 이름만 이 캐릭터에 맞게 바꾼다 |

태그 규칙:
- Danbooru나 e621에 실제로 있는 태그만 쓴다. 없는 말을 지어내지 않는다.
- 소문자로, 밑줄 대신 띄어쓰기로, 쉼표로 구분한다.
- 맨 앞은 `1boy` 또는 `1girl`. 동물 캐릭터면 그다음에 `furry, anthro`, 그리고 종 태그(`fox boy`, `wolf girl`, `cat boy` 같은 것)를 쓴다.
- 색은 대상 앞에 붙인다 (`orange fur`, `blue hoodie`, `green eyes`). 그 캐릭터를 알아보게 하는 무늬나 옷은 꼭 넣는다.

## 출력 형식

- 맨 첫 줄은 `# 파일 이름: characters/<name>.yaml` 주석.
- YAML은 `yaml` 코드 블록 하나에 넣는다. 칸 순서는 아래 예시와 같게.
- 글이나 문장 값은 큰따옴표로 감싸고, 값 안에는 큰따옴표를 쓰지 않는다.
- 들여쓰기는 띄어쓰기로만 한다 (탭 금지).

## 예시

사용자: 주황 털 여우 남자애, 초록 눈, 파란 후드티에 반바지, 장난꾸러기 성격

```yaml
# 파일 이름: characters/fox.yaml
name: fox
trigger: fox
name_ko: "여우"
personality: "밝고 장난스러움. 짧은 반말."
tags_short: "1boy, furry, anthro, fox boy, orange fur, white muzzle, green eyes"
tags_full: "1boy, furry, anthro, fox boy, orange fur, white muzzle, white chest, green eyes, pointy ears, fluffy tail, blue hoodie, shorts"
negative_extra: "human ears"
anima: "A small anthro fox boy with orange fur, a white muzzle, green eyes, pointy ears, a fluffy tail and a blue hoodie."
anima_back: "Seen from behind, a small anthro fox boy with orange fur, a fluffy orange tail and the back of a blue hoodie."
compose_name: "orange fox boy"
anima_find: "orange fox"
qa_desc: "an orange fox boy in a blue hoodie"
qa_checklist:
  - id: clothes
    must: true
    q: "What is the character wearing on the upper body?"
    options: ["a blue hoodie", "something else", "not visible"]
    expect: ["a blue hoodie", "not visible"]
  - id: text
    must: true
    q: "Is there any text in the picture?"
    options: ["no text at all", "there is text or a signature or watermark"]
    expect: ["no text"]
```

## 저장 안내 (YAML 뒤에 사용자에게 그대로 알려 줄 것)

1. 메모장을 열고 위 YAML을 통째로 붙여 넣는다.
2. 메뉴 '파일 > 다른 이름으로 저장'에서 '파일 형식'을 **모든 파일**로 바꾼다. 안 바꾸면 `fox.yaml.txt`처럼 저장돼서 프로그램이 못 읽는다.
3. 만화 제작기 폴더 안 `characters` 폴더에 `<name>.yaml`로 저장한다 (인코딩은 UTF-8).
4. 작업실에서 '글콘티용 첨부 파일 만들기'를 다시 누른다. 그래야 새 캐릭터가 글콘티 목록에 들어간다.
