# nk 만화 제작기 LoRA 학습 캡션 만들기 (AI 채팅에 첨부하는 파일)

> 사용자용 안내 (자세한 건 docs/TRAINING.md)
> 1. 학습 그림 이름을 `01.png`, `02.png`처럼 번호로 바꿔 둔다.
> 2. 이 파일을 AI 채팅 새 대화에 첨부한다. 캐릭터 파일(`characters/fox.yaml` 같은 것)도 같이 첨부하면 좋다.
> 3. 학습 그림을 번호 순서대로 올린다. 한 번에 다 안 올라가면 몇 장씩 나눠 올려도 된다.
> 4. AI 답을 전부 복사한 다음, 만화 제작기 폴더의 터미널에서:
>    `.\nk.bat ep captions training/data/fox --trigger fox`
>    그림마다 `01.txt` 같은 캡션 파일이 생긴다.
>
> 아래부터는 AI에게 하는 말이다.

---

## 네가 할 일

사용자가 올린 학습 그림마다 LoRA 학습용 캡션(태그 한 줄)을 써 준다. 이 캡션으로 캐릭터 하나를 그림 모델(Anima)에 가르친다.

1. 시작하기 전에 두 가지를 확인한다. 모르면 사용자에게 묻는다.
   - **트리거 단어**: 캐릭터 파일의 `name` (예: `fox`). 모든 캡션의 맨 앞에 온다.
   - **늘 같은 특징**: 이 캐릭터를 알아보게 하는 생김새. 캐릭터 파일이 있으면 `tags_short`에서 가져온다.
2. 그림을 올라온 순서대로 보고, 그림마다 아래 형식으로 캡션을 쓴다.
3. 사용자가 그림을 나눠 올리면 번호를 이어서 붙인다. 마지막에 "전부 모아 줘"라고 하면 지금까지의 캡션을 코드 블록 하나로 다시 준다.

## 캡션 규칙

형식: `트리거, 늘 같은 특징 5~8개, 이 그림에서만 다른 것들`

1. **맨 앞은 무조건 트리거 단어.** 학습 설정상 첫 자리는 섞이지 않고 고정된다.
2. **그림마다 바뀌는 건 전부 태그로 적는다.** 자세, 구도(`front view`, `side view`, `from behind`, `close-up`, `upper body`, `full body`), 표정, 행동, 들고 있는 물건, 배경(`simple background`, `white background`, `outdoors` 등), 그림체(`sketch`, `flat colors`, `chibi` 등).
   태그로 적은 건 '바꿀 수 있는 것'으로 배우고, 안 적은 건 캐릭터 자체로 굳는다.
3. **늘 같은 특징은 핵심 5~8개만.** 다 적으면 트리거가 배울 게 없어진다. 종, 털과 눈 색, 꼭 있는 무늬나 소품 정도.
4. 옷을 그림마다 갈아입으면 옷도 태그로 적는다. 늘 같은 옷이면 3번의 특징에 넣는다.
5. 캐릭터 시트(앞, 옆, 뒤를 늘어놓은 그림)는 `reference sheet`를 붙인다. 머리가 큰 아기 비율로 그렸으면 `chibi`도 붙인다. 안 붙이면 그 비율이 캐릭터로 굳는다.
6. 태그는 Danbooru나 e621에 실제로 있는 것만, 소문자로, 밑줄 대신 띄어쓰기로, 쉼표로 구분해서 한 줄로 쓴다.
7. 실제 작가 이름은 쓰지 않는다.

## 꼭 지킬 것

- 전연령 그림만 다룬다. 성적이거나 선정적인 그림, 노출, 잔혹한 그림이 올라오면 그 그림은 캡션을 쓰지 않고 "이 그림은 학습에 쓸 수 없다"고만 말한다.
- 실존 인물 사진은 다루지 않는다.
- 그림 속 사람이 학습할 캐릭터 말고 또 있으면 그 사실을 알려 준다. 학습 그림에는 캐릭터 혼자 나오는 게 좋다.

## 출력 형식

캡션 전체를 코드 블록 하나에 넣는다. 그림마다 `=== 그림 이름` 줄 다음 줄에 캡션 한 줄. 그림 이름을 모르면 올라온 순서대로 `01.png`, `02.png`…로 붙이고, 그렇게 했다고 한 줄 알려 준다.

```
=== 01.png
fox, 1boy, furry, anthro, fox boy, orange fur, white muzzle, green eyes, reference sheet, front view, full body, standing, simple background, white background
=== 02.png
fox, 1boy, furry, anthro, fox boy, orange fur, white muzzle, green eyes, blue hoodie, sitting, cafe, holding cup, smile, three-quarter view, upper body
=== 03.png
fox, 1boy, furry, anthro, fox boy, orange fur, white muzzle, green eyes, from behind, fluffy tail, outdoors, park, walking, full body
```

코드 블록 뒤에는 이 한 줄만 덧붙인다:
"답을 전부 복사한 다음 만화 제작기 폴더의 터미널에서 `.\nk.bat ep captions <그림 폴더> --trigger <트리거>`를 실행하면 캡션 파일이 생깁니다."
