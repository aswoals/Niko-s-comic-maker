# nk 명령 사용법 (P1 — ComfyUI를 명령 한 줄로 돌리기)

ComfyUI 켜 둔 상태에서 PowerShell:
```
cd <키트 폴더>
.\nk.bat list                                   # 프리셋·장면·캐릭터 목록
.\nk.bat gen --preset mystyle --scene cafe --n 5 # mystyle 프리셋 그림체, 카페 장면 5장
.\nk.bat gen --preset mystyle,hq --scene bench --n 3
.\nk.bat gen --scene "solo, sitting, rooftop, night" --artist "artist name" --cfg 4 --n 4
.\nk.bat style --artist "artist a,artist b" --cfg 3.5,4.5 --quality on,off --seed 42
.\nk.bat free                                   # VRAM 비우기 (VLM QA 전에)
```
아무 명령에 `--dry` 붙이면 프롬프트만 출력하고 생성은 안 함 (확인용, ComfyUI 없어도 됨).

## 결과 위치
`runs\<실행이름>\` — 이미지 + `meta.json`(장마다 프롬프트·시드·설정 기록 → 나중에 QA·재현용).
`style`은 `grid.png` 비교표까지 자동 생성.

## 자주 쓰는 옵션
| 옵션 | 뜻 | 예 |
|---|---|---|
| `--preset` | presets.yaml의 프리셋. 쉼표로 겹치기 | `--preset mystyle,hq` |
| `--scene` | presets.yaml의 장면 이름 또는 태그 직접 | `--scene cafe` / `--scene "solo, running"` |
| `--n` | 장수 | `--n 10` |
| `--seed` | 시드 고정 (같은 시드 = 같은 구도) | `--seed 42` |
| `--artist` `--artist_weight` | 작가 태그 직접 | `--artist "artist name" --artist_weight 1.3` |
| `--cfg` `--steps` `--size` | 샘플러 값 | `--cfg 3.5 --size 1024x1024` |
| `--quality on/off` | 품질 태그 넣기/빼기 | `--quality off` |
| `--rating safe/nsfw/explicit` | 등급 | `--rating explicit` |
| `--year` | 연도 태그 | `--year 2023` |
| `--tags short/full` | 캐릭터 외형 태그 전부 넣기 | `--tags full` |
| `--lora 파일:강도` | LoRA 추가 (반복 가능) | `--lora my_style.safetensors:0.7` |
| `--extra` `--neg` | 긍정/부정 태그 추가 | `--extra "wink"` |
| `--char` | 다른 캐릭터 / `none` = 캐릭터 없이 | `--char none` |
| `--name` | 결과 폴더 이름 | `--name test_v3` |

## 값을 영구적으로 바꾸려면
- 기본값·프리셋·장면 → `presets.yaml`
- 캐릭터 LoRA 파일·강도·태그·QA 체크리스트 → `characters\<이름>.yaml` (docs/ADDING.md)
- 새 캐릭터 → `characters\_template.yaml` 복사해서 이름 바꾸고 내용 수정 → `--char 새이름`

## 원리 (공부용)
ComfyUI는 화면에 노드를 그리는 프로그램이지만, 뒤에서는 `http://127.0.0.1:8000/prompt` 주소로 JSON을 받는 서버임.
nk.py는 워크플로 JSON(체크포인트 → LoRA → 프롬프트 → KSampler → 저장)을 코드로 조립해서 그 주소로 보내고, 끝나면 `/history`에서 결과 파일명을 받아 `runs\`로 복사함. 즉 "노드를 마우스로 만지는 대신 글자로 만지는 것".

---
# nk qa / nk run (P3·P5 — 디테일 QA와 원버튼)

## 준비 (한 번만, 학습 끝난 뒤)
이미 Ollama + gemma4(12b-it-qat / e4b-it-qat)가 설치돼 있음 → 기본 모델 `gemma4:12b-it-qat`. 바꾸려면 presets.yaml `qa: model:` 또는 명령에 `--model 이름`.
학습 중에는 반드시 `--cpu` (GPU 잡으면 학습 느려짐).

## 사용
```
.\nk.bat free                              # ComfyUI가 잡은 VRAM 비우기 (8GB라 둘 동시에 못 올림)
.\nk.bat qa --run gen_0922_011353          # runs\ 안의 실행 폴더 검사
.\nk.bat qa --dir "D:\pictures\test"   # 아무 폴더나
.\nk.bat run --preset mystyle --scene cafe --n 10    # 생성 10장 → VRAM 비움 → QA → pass\ 에 합격만 복사
```
결과: 폴더 안에 `qa.json`(항목별 답), `qa_report.md`(표 + 가장 많이 틀린 항목), `pass\`(합격 이미지).

## 원리
`characters\<이름>.yaml`의 `qa_checklist` 질문들을 이미지와 함께 VLM(그림을 보는 언어모델)에 보내고, JSON으로 true/false를 받아 `must: true` 항목이 하나라도 false면 불합격.
질문을 고치거나 추가하려면 yaml만 수정. `only_when: rating != safe` 항목은 성인용일 때만 물어봄.
VLM 판정은 100%가 아님 — 특히 작은 무늬(얼굴 무늬, 꼬리 끝)는 오판 있음. 그래서 "탈락 후보 걸러내기"용이고 최종 선택은 사람이 함. 정확도가 낮은 항목은 `must: false`로 내려서 참고용으로만.

---
# nk ep (웹툰 한 화 만들기)

글콘티(`episodes\<화>\conti.yaml`)만 고치고, 명령은 사실상 **make 하나**.
```
.\nk.bat ep new ep01          # 글콘티 견본 생성 (처음 한 번)
.\nk.bat ep make ep01         # 원버튼: 후보 3장씩 → VLM이 자동으로 골라 → 고화질 → 말풍선 스트립
.\nk.bat ep redo ep01 3       # 컷3만 새로 그리기 (자동 선택·고화질·스트립까지). 여러 개: redo ep01 3 5
.\nk.bat ep pick ep01 3=2     # 자동 선택이 틀렸을 때만: 컷3을 후보2로 바꿈 (고화질·스트립 자동)
.\nk.bat ep letter ep01       # 대사·말풍선 위치만 고쳤을 때 (몇 초)
```
- 결과: `episodes\ep01\out\strip.png` (전체) + 업로드용 조각. 후보 전체는 `runs\ep01\board.png` (선택된 후보는 초록 테두리).
- make는 **완성 그림이 없는 컷만** 그림 → 콘티에 컷을 추가하고 make 다시 치면 새 컷만 그림. 이미 그려 둔 후보가 있으면 다시 안 그리고 고르기만 함.
- 컷의 scene을 고쳤으면 그 컷은 `redo`.
- 옵션: `--n 5`(후보 수), `--noqa`(VLM 없이 후보1로, 빠름).
- 스트립 폭·여백·폰트·글자 크기 → presets.yaml `webtoon:`.
- conti.yaml 컷 항목: `size`(wide/tall/square/banner/long), `scene`(태그), `text`(대사 목록), 선택: `artist`(프리셋), `extra`, `neg`, `cfg`, `gap_after`.

---
# 일본식 페이지 만화 — 같은 nk ep 명령, conti.yaml 에 `format: page`
```
.\nk.bat ep make ep01          # 전 컷 후보 → 자동 선택 → 고화질 → 페이지 조립 (episodes\ep01\out\)
.\nk.bat ep redo ep01 12 19    # 12·19번 컷만 다시
.\nk.bat ep pick ep01 12=3     # 12번 컷을 후보 3으로
.\nk.bat ep letter ep01        # 대사·말풍선만 다시 (그림 재생성 없음)
.\nk.bat ep webview ep01       # 웹툰판만 다시: out\webtoon\index.html (컷을 세로로 이어 보는 HTML. letter 때도 같이 만들어짐, 끄기 = presets.yaml manga: webview: false)
```
- 결과: `out\page_01.png ~` (1600×2259, B5 비율) / `spread_01.png ~` (펼침면, 오른쪽이 홀수 페이지) / `book.pdf`
- 컷 배치: conti.yaml 의 rows (h = 줄 높이 비율, cuts = 오른쪽부터, w = 폭 비율). 컷 크기에 맞는 비율로 생성 후 잘라 넣음.
- `char: none` = 사물 컷 (LoRA·자동검수 안 함) / `n: 5` = 후보 수 / `place: left|right` = 잘라낼 때 남길 쪽
- 대사 type: speech / thought / narration / sfx / offscreen(화면 밖 인물, 꼬리가 컷 밖으로). ※ `off` 는 yaml 이 false 로 읽으니 쓰지 말 것
- 웹툰판에서만 글자 자리 옮기기: 글자 줄에 `web_at: tl|tr|bl|br` (글자가 얼굴을 가릴 때. 쪽 만화의 `at` 과 말풍선은 그대로).
  plan.yaml 의 `lines` 에 적고 `nk ep compile` (콘티로 넘어옴) → `nk ep webview`. 계획표 없이 손으로 쓴 콘티면 conti.yaml 의 `text` 에 적고 `nk ep webview`.
  계획표가 있는데 conti.yaml 만 고치면 계획표로 콘티를 다시 만들 때(`ep compile` · `ep fix` · 메뉴 '대사만') 사라짐
- 페이지 모양 → presets.yaml `manga:`
