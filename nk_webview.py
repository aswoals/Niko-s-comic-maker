# -*- coding: utf-8 -*-
"""웹툰판 — 페이지형 만화를 폰에서 세로로 내려 보는 한 장짜리 HTML 로도 내보냄

무엇을 하나
  - '말풍선 조립(letter)'이 끝날 때마다 쪽 만화(out/page_NN.png · book.pdf) 옆에 웹툰판을 만듦:
      episodes/<만화>/out/webtoon/index.html     컷 하나가 화면 폭을 꽉 채우고 세로로 이어짐 (본문 폭 최대 760px)
      episodes/<만화>/out/webtoon/img/cutNN.jpg  컷 그림 (가로 1080px 넘으면 줄임, JPEG) + 표지가 있으면 img/cover.jpg
      episodes/<만화>/out/webtoon/font.ttf · sfx.ttf   글꼴 (fonts/ 의 Jua · Black Han Sans, SIL OFL - fonts/FONTS.md)
    index.html 은 바깥 주소(http/https)를 하나도 안 쓰고 자바스크립트도 없음 -> webtoon 폴더째 옮기거나 올리면 그대로 보임.
  - 대사는 그림에 굽지 않고 HTML 글자로 그림 위에 올림 -> 폰에서도 컷과 글씨가 크게 보임 (쪽 만화는 한 쪽을 통째로 줄여 보게 됨).

어떻게
  - 컷 그림은 쪽 조립(nk_webtoon.page_letter)과 같은 파일 (_cut_image: 완성 컷, 없으면 초안, --style 이면 cuts_<style>).
    flip: true 는 쪽과 같게 뒤집음. 자르지는 않음 (쪽은 칸 모양에 맞춰 잘라 내지만 웹툰판은 그림 전체를 보여 줌).
    그림이 없는 컷은 'cut N: no image', 열 수 없는(깨진) 그림은 'cut N: broken image' 자리 표시만 넣고 계속함.
    웹툰판에 없는 것: 쪽 조립이 코드로 그리는 집중선·속도선(fx), 컷끼리 색 맞추기(color_match). 그림 파일을 그대로 보여 줌.
  - 순서 = 읽는 순서: 쪽 번호 순, 쪽 안에서는 tree(칸 v2)가 있으면 나무의 잎 순서, 없으면 rows 의 줄 순서.
  - 글자 자리 = 컷의 네 귀퉁이 tl/tr/bl/br 가운데 하나. 한 귀퉁이에 여럿이면 적힌 순서대로 위에서 아래로 쌓음.
      at 을 적힌 그대로 씀: tl tr bl br 는 그대로 / t·top -> tl / b·bottom -> bl / l·left -> tl / r·right -> tr / 그 밖(없음·c·center …) -> tr
      narration(네모 해설)은 왼쪽에만: 위쪽 귀퉁이면 tl, 아래쪽이면 bl / sfx = 큰 흰 글씨 / 나머지 = 말풍선
      말풍선 종류는 콘티에 적힌 그대로. letter: v2 콘티에서는 쪽 조립과 같게 느낌표가 둘 이상인 speech 를 외침(shout)으로 (nk_letter2.bubble_kind).
    같은 줄의 두 귀퉁이(tl·tr, bl·br)는 한 줄(.row)에 나란히 놓음 -> 둘의 폭을 더해 컷 폭을 넘으면 겹치지 않고 둘 다 줄어들어 줄바꿈됨.
    띄어쓰기 없는 긴 낱말은 상자 폭에 맞춰 낱말 안에서 줄바꿈됨 (보통 대사는 띄어쓰기에서만).
  - read: ltr 이어도 좌우를 뒤집지 않음 (쪽 조립은 MIRROR 로 뒤집음). 세로로 내려 보는 화면에서는 위->아래가 읽는 순서를 정하고,
    해설은 원래 안 뒤집기 때문에 대사만 뒤집으면 해설과 같은 귀퉁이에 몰림.
  - 말풍선 꼬리는 없음 -> 캐릭터 말풍선 색(캐릭터 파일 bubble: {fill, line})이 '누가 말하는지'의 유일한 단서.
  - web_at = 웹툰판에서만 글자 자리를 옮기는 칸. 글자 한 줄에 web_at: tl|tr|bl|br 를 적으면 웹툰판은 그 귀퉁이를 그대로 씀
    (해설도 오른쪽으로 갈 수 있음, 모르는 값은 무시). 쪽 만화는 web_at 을 안 봄 = at 과 쪽 결과는 그대로.
    어디에 적나 (대사 고치기 nk_lines.py 와 같은 원칙):
      episodes/<만화>/plan.yaml 의 lines    원본 계획표. 여기에 적고 콘티를 다시 만들어야(nk ep compile <만화>) 콘티로 넘어옴 -> nk ep webview <만화>
      episodes/<만화>/conti.yaml 의 text   웹툰판이 읽는 글. 계획표 없이 손으로 쓴 콘티면 여기에 적음 -> nk ep webview <만화>
      계획표가 있는데 conti.yaml 만 고치면 지금 웹툰판에는 반영되지만, 계획표로 콘티를 다시 만들 때(nk ep compile · nk ep fix · 메뉴 '대사만') 사라짐.
    쓸 때: 글자가 얼굴(눈·입)이나 손에 든 물건을 가릴 때. 거의 다 '오른쪽 위(tr) 말풍선이 오른쪽에 선 인물의 얼굴을 덮는' 경우라 아래로 옮기면 풀림.
    아래로 옮길 때, 그 컷의 나중 대사가 이미 bl 에 있으면 br 이 아니라 bl 에 쌓을 것 (한 귀퉁이 안에서는 적힌 순서대로 위->아래라 순서가 안 뒤집힘).
  - 검수 (39편 1,811컷, 폰 폭 412px): 글자가 컷 밖으로 잘린 컷 0. 글자끼리 겹친 컷은 5 (모두 '왼쪽 위 해설 + 오른쪽 위 넓은 말풍선')였고,
    같은 줄을 한 줄(.row)로 놓은 뒤 브라우저로 다시 재니 0 (컷 폭 360·397·412·760px 에서 잘림·겹침 0).
    글자가 얼굴·손에 든 물건을 가린 컷은 약 34 (1.9%) — 자리를 그림을 안 보고 정하므로 생김. 모두 web_at 으로 글자 하나를 옮겨 풀렸음.

설정: presets.yaml manga: webview: false = 쪽을 조립할 때 웹툰판을 안 만듦 (기본 true)

사용 (선택): nk ep webview <만화> [--style S]
  쪽을 다시 조립하지 않고 웹툰판만 다시 만듦 (대사·자리만 고쳤을 때 빠름). 위 설정이 꺼져 있어도 만듦.

에러가 나면
  - 웹툰판을 못 만들어도 말풍선 조립은 그대로 끝남 ('[note] webtoon view skipped (...)' 한 줄만 나옴). 쪽·PDF 는 그대로.
  - 컷 그림 하나가 깨져 있으면 그 컷만 자리 표시로 넣고 끝까지 만듦 ('[note] cut N: broken image ...'). 표지가 깨졌으면 표지만 뺌.
  - 옛 그림(img/*.jpg)은 새 index.html 을 다 쓴 뒤에, 이번에 안 쓴 것만 지움 -> 만들다 멈춰도 전에 만든 화면은 그대로 보임.
"""
import os, re, html, shutil

OFF = ("false", "0", "off", "no", "none", "")
MAX_W = 1080                                 # 컷 그림 가로 최대 px (넘으면 줄임)
JPEG_Q = 86
# (웹툰 폴더 안 이름, fonts/ 안 파일, CSS 글꼴 이름). 둘 다 SIL OFL 1.1 (fonts/FONTS.md)
FONT_FILES = (("font.ttf", "Jua-Regular.ttf", "Talk"), ("sfx.ttf", "BlackHanSans-Regular.ttf", "Sfx"))
KINDS = ("speech", "shout", "whisper", "thought", "aside", "tremble")       # 말풍선 종류 = CSS 클래스. 모르는 종류는 speech
# at -> 귀퉁이. nk 가 쓰는 이름(nk_webtoon.ANCHOR: tl tr bl br top bottom left right)과 짧은 이름(t b l r). 여기 없으면 tr
CORNER = {"tl": "tl", "tr": "tr", "bl": "bl", "br": "br", "t": "tl", "top": "tl", "b": "bl", "bottom": "bl",
          "l": "tl", "left": "tl", "r": "tr", "right": "tr"}
# 효과음 size s/m/l/xl (v2 칸 비율 0.10/0.15/0.21/0.29) -> 기본 크기 대비 배율. 0.7~1.4 안에 순서대로 눌러 담음
SFX_SIZE = {"s": 0.8, "m": 1.0, "l": 1.2, "xl": 1.4}
SCALE_MIN, SCALE_MAX = 0.7, 1.4

# 글꼴 파일이 없으면 @font-face 를 안 넣음 -> 아래 font-family 의 시스템 글꼴로 보임
# .row = 컷 폭의 94% (좌우 3%씩). .stack 최대 폭 65.96% = 컷 폭의 62% (62 / 94) — 혼자 있는 귀퉁이의 줄바꿈은 줄(.row)이 없던 때와 같음
CSS = """
:root{--bg:#f4f1ec;--ink:#1d1b19;--muted:#7a746c}
@media (prefers-color-scheme:dark){:root{--bg:#141312;--ink:#f2efe9;--muted:#a49d93}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Talk,"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif}
header{max-width:760px;margin:0 auto;padding:28px 16px 8px}
header h1{font-size:26px;margin:0 0 4px;font-weight:400}
header p{margin:0;color:var(--muted);font-size:14px}
.cover{max-width:760px;margin:12px auto 0}
.cover img{display:block;width:100%;height:auto}
main{max-width:760px;margin:0 auto;padding:8px 0 80px}
.page{margin:28px 16px 6px;color:var(--muted);font-size:13px;letter-spacing:.08em}
.cut{position:relative;margin:0 0 14px;overflow:hidden;background:#000;border-top:3px solid #111;border-bottom:3px solid #111}
.cut img{display:block;width:100%;height:auto}
.cut.none{aspect-ratio:3/2;background:#2b2826}
.noimg{position:absolute;top:0;right:0;bottom:0;left:0;display:flex;align-items:center;justify-content:center;color:#f08a8a;font-size:14px}
.row{position:absolute;left:3%;right:3%;display:flex;justify-content:space-between;gap:8px;pointer-events:none}
.row.top{top:4%;align-items:flex-start}.row.bottom{bottom:4%;align-items:flex-end}
.stack{display:flex;flex-direction:column;gap:8px;flex:0 1 auto;max-width:65.96%}
.tl,.bl{align-items:flex-start}.tr,.br{align-items:flex-end;margin-left:auto}
.b{background:#fff;color:#111;border:2.5px solid #111;border-radius:999px;padding:.5em 1em;font-size:calc(clamp(14px,3.6vw,20px)*var(--s,1));line-height:1.35;text-align:center;word-break:keep-all;overflow-wrap:anywhere}
.b.shout{border-width:4px;font-size:calc(clamp(16px,4.4vw,25px)*var(--s,1));border-radius:14px;transform:rotate(-1.5deg)}
.b.whisper{border-style:dashed}
.b.thought{border-style:dotted;border-radius:40%}
.b.aside{border:none;background:rgba(255,255,255,.85);font-size:calc(clamp(12px,3vw,16px)*var(--s,1));color:#444;border-radius:8px}
.b.tremble{animation:tremble .18s linear infinite}
@keyframes tremble{0%{transform:translate(0)}50%{transform:translate(1px,-1px)}100%{transform:translate(-1px,1px)}}
.n{background:#fff;color:#111;border:2px solid #111;padding:.45em .8em;font-size:calc(clamp(13px,3.3vw,18px)*var(--s,1));line-height:1.4;word-break:keep-all;overflow-wrap:anywhere}
.sfx{font-family:Sfx,Talk,"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;font-size:calc(clamp(26px,8vw,48px)*var(--s,1));color:#fff;-webkit-text-stroke:2px #111;paint-order:stroke fill;transform:rotate(-6deg);text-shadow:3px 3px 0 #111}
@media (prefers-reduced-motion:reduce){.b.tremble{animation:none}}
"""

PAGE = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><style>%s</style></head><body><header><h1>%s</h1><p>%s</p></header>%s'
        '<main>%s</main></body></html>')

_COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,30}|(rgb|rgba|hsl|hsla)\([0-9., %]+\)")      # fullmatch 로만 씀


def enabled(st):
    """presets.yaml manga: webview (키가 없으면 켜짐). st = nk_webtoon._page_style 이 돌려준 것 (manga 설정이 그대로 들어 있음)"""
    return str((st or {}).get("webview", True)).strip().lower() not in OFF


# ------------------------------------------------------------------ 순서
def _leaves(t):
    """칸 나무(nk_layout2)의 잎 = 컷 번호, 읽는 순서대로"""
    if "cut" in t:
        return [int(t["cut"])]
    return [x for k in (t.get("kids") or []) for x in _leaves(k)]


def ordered_cuts(c):
    """컷을 읽는 순서대로 -> [(쪽 번호, 컷)]. 쪽이 없는 콘티(세로 스트립)는 쪽 번호 None.
    load_conti 가 펴 준 c["cuts"] 를 씀 (기본값이 채워져 있고, rows 쪽은 줄 순서 = 읽는 순서).
    tree 쪽은 _flatten_pages 가 cuts 목록 순서로 펴 두기 때문에 나무의 잎 순서로 다시 줄 세움"""
    cuts = list(c.get("cuts") or [])
    if not cuts or any(ct.get("page") is None for ct in cuts):
        return [(None, ct) for ct in cuts]
    trees = {}
    for pg in c.get("pages") or []:
        if pg.get("tree"):
            trees.setdefault(int(pg["page"]), []).extend(_leaves(pg["tree"]))
    out = []
    for pn in sorted({int(ct["page"]) for ct in cuts}):
        mine = [ct for ct in cuts if int(ct["page"]) == pn]
        order = trees.get(pn)
        if order:
            mine.sort(key=lambda ct: order.index(int(ct["id"])) if int(ct["id"]) in order else len(order))
        out += [(pn, ct) for ct in mine]
    return out


# ------------------------------------------------------------------ 글자
def corner(item):
    """글자 하나 -> 귀퉁이 (tl/tr/bl/br).
    web_at(웹툰판 전용 자리)이 아는 이름이면 그 귀퉁이를 그대로 씀 (해설도 오른쪽으로 갈 수 있음). 모르는 값이면 무시.
    없으면 at 을 적힌 그대로 씀 — read: ltr 이어도 좌우를 뒤집지 않음 (이유는 맨 위 설명).
    해설(narration)은 왼쪽에만: 위쪽 귀퉁이면 tl, 아래쪽이면 bl"""
    w = CORNER.get(str(item.get("web_at") or "").strip().lower())
    if w:
        return w
    k = CORNER.get(str(item.get("at") or "").strip().lower(), "tr")
    if str(item.get("type") or "speech") == "narration":
        return "tl" if k in ("tl", "tr") else "bl"
    return k


def _scale(item, kind, fs0):
    """size(글씨 크기 조절) -> 기본 크기 대비 배율 (0.7~1.4 로 제한). 없거나 모르는 값이면 1.0
    숫자 = 쪽 만화의 글자 크기 px (기본은 manga.font_size, 효과음은 그 1.6배) / 효과음의 s·m·l·xl = SFX_SIZE"""
    v = item.get("size")
    if v is None or isinstance(v, bool):
        return 1.0
    if kind == "sfx" and str(v).strip().lower() in SFX_SIZE:
        return SFX_SIZE[str(v).strip().lower()]
    try:
        r = float(v) / (float(fs0) * (1.6 if kind == "sfx" else 1.0))
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0
    return min(SCALE_MAX, max(SCALE_MIN, r))


def _color_off(c):
    """콘티 bubble_color: off 인가 (YAML 은 off 를 false 로 읽음 — page_letter 와 같은 판단)"""
    bm = c.get("bubble_color", "all")
    return bm is False or str(bm).lower() in ("false", "off", "no", "none", "0")


def _bubble_style(item, c):
    """말풍선 색 (style 조각, 없으면 ""). 캐릭터 파일 bubble: {fill, line} — nk_webtoon._bubble_colors 를 그대로 씀.
    웹툰판에는 말풍선 꼬리가 없어서 색이 '누가 말하는지'의 유일한 단서 -> 콘티가 bubble_color: offscreen(쪽에서는 화면 밖
    대사만 색)이어도 그 캐릭터의 말풍선 전부에 색을 입힘. off 일 때만 안 입힘"""
    import nk_webtoon as W
    if _color_off(c) or not item.get("who"):
        return ""
    fill, line = W._bubble_colors(item, {"_castmap": c.get("_cast") or {}, "_bubble_mode": "all"})
    if (fill, line) == ("white", "black") or not (_COLOR_RX.fullmatch(fill) and _COLOR_RX.fullmatch(line)):
        return ""
    return "background:%s;border-color:%s" % (fill, line)


def _kind(item, v2):
    """글자 종류. letter: v2 콘티에서는 쪽 조립(nk_webtoon._draw_item)과 같은 함수로 정함: nk_letter2.bubble_kind =
    콘티가 정한 종류 그대로, speech 인데 '!' 가 둘 이상이면 shout. v1 콘티는 적힌 그대로"""
    if v2:
        import nk_letter2
        return str(nk_letter2.bubble_kind(item))
    return str(item.get("type") or "speech")


def overlay(texts, c, fs0=30):
    """컷의 글자들 -> 그림 위에 올릴 HTML: 귀퉁이마다 <div class="stack tl|tr|bl|br">, 그 안에 적힌 순서대로 위에서 아래로
    .n(해설) / .sfx(효과음) / .b + 종류(말풍선). 글자 내용은 모두 html.escape, 줄바꿈은 <br>.
    위쪽 두 귀퉁이는 <div class="row top">, 아래쪽 두 귀퉁이는 <div class="row bottom"> 이 감쌈 (글자가 없는 줄은 안 넣음).
    줄 이름을 t / b 로 줄이지 않는 까닭: b 는 말풍선 클래스(.b)와 겹침"""
    stacks = {"tl": [], "tr": [], "bl": [], "br": []}
    v2 = str((c or {}).get("letter") or "").lower() == "v2"          # page_letter 와 같은 판단
    for t in texts or []:
        if not isinstance(t, dict):
            continue
        kind = _kind(t, v2)
        raw = "" if t.get("text") is None else str(t.get("text"))
        txt = html.escape(raw.replace("\r\n", "\n").replace("\r", "\n")).replace("\n", "<br>")
        sc = _scale(t, kind, fs0)
        styles = ["--s:%.2f" % sc] if abs(sc - 1.0) > 0.004 else []
        if kind == "narration":
            cls = "n"
        elif kind == "sfx":
            cls = "sfx"
        else:
            cls = "b %s" % (kind if kind in KINDS else "speech")
            col = _bubble_style(t, c)
            styles = ([col] if col else []) + styles
        stacks[corner(t)].append('<div class="%s"%s>%s</div>' % (cls, ' style="%s"' % ";".join(styles) if styles else "", txt))
    out = ""
    for row, keys in (("top", ("tl", "tr")), ("bottom", ("bl", "br"))):
        inner = "".join('<div class="stack %s">%s</div>' % (k, "".join(stacks[k])) for k in keys if stacks[k])
        if inner:
            out += '<div class="row %s">%s</div>' % (row, inner)
    return out


# ------------------------------------------------------------------ 그림·글꼴
def _save_jpg(src, dst, flip=False):
    """그림 파일 -> JPEG (가로 MAX_W 넘으면 줄임, 자르지 않음). 돌려줌: (가로, 세로)"""
    from PIL import Image
    with Image.open(src) as im0:
        im = im0.convert("RGB")
    if flip:                                   # page_letter 와 같게 (오른->왼으로 읽는 만화의 전진 방향)
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if im.width > MAX_W:
        im = im.resize((MAX_W, max(1, int(round(im.height * MAX_W / float(im.width))))), Image.LANCZOS)
    im.save(dst, format="JPEG", quality=JPEG_Q)
    return im.size


def _why(e):
    return ("%s: %s" % (type(e).__name__, " ".join(str(e).split())))[:160]


def _copy_fonts(kit, wdir):
    """키트 fonts/ 의 글꼴을 웹툰 폴더로 복사. 돌려줌: 복사한 글꼴의 @font-face CSS (파일이 없으면 건너뜀 = 시스템 글꼴)"""
    css = ""
    for name, src, family in FONT_FILES:
        p = os.path.join(kit, "fonts", src)
        if not os.path.exists(p):
            continue
        shutil.copyfile(p, os.path.join(wdir, name))
        css += "@font-face{font-family:%s;src:url(%s);font-display:swap}\n" % (family, name)
    return css


# ------------------------------------------------------------------ 만들기
def build(nk, kit, ep, c, out, style=None):
    """<out>/webtoon/ 을 새로 만듦 (index.html + img/ + 글꼴). c = nk_webtoon.load_conti 가 돌려준 콘티,
    out = 쪽이 들어 있는 폴더 (episodes/<만화>/out 또는 out_<style>). 돌려줌: index.html 경로"""
    import nk_webtoon as W
    cfg = nk.load_presets()
    fs0 = W._page_style(cfg).get("font_size") or 30
    picks = W.load_picks(kit, ep)
    wdir = os.path.join(out, "webtoon")
    idir = os.path.join(wdir, "img")
    os.makedirs(idir, exist_ok=True)
    faces = _copy_fonts(kit, wdir)
    used = set()                                          # 이번에 쓴 img/ 파일 이름 (나머지 옛 jpg 는 맨 끝에 지움)
    cover = ""
    cv = os.path.join(out, "page_00.png")                 # 표지 (nk_cover 가 쪽 조립 끝에 만든 것)가 있으면 맨 위에 한 장
    if os.path.exists(cv):
        try:
            w, h = _save_jpg(cv, os.path.join(idir, "cover.jpg"))
            used.add("cover.jpg")
            cover = '<div class="cover"><img src="img/cover.jpg" alt="" width="%d" height="%d"></div>' % (w, h)
        except Exception as e:                            # 표지가 깨졌으면 표지만 빼고 계속
            print("[note] webtoon: cover left out, page_00.png cannot be read (%s)" % _why(e))
    body, last, n = [], None, 0
    for pn, ct in ordered_cuts(c):
        cid = int(ct["id"])
        if pn is not None and pn != last:
            body.append('<div class="page">%d쪽</div>' % pn)
            last = pn
        n += 1
        over = overlay(ct.get("text") or [], c, fs0)
        f = W._cut_image(nk, cfg, kit, ep, cid, picks, style)
        why = "no image"
        if f and os.path.exists(f):
            name = "cut%02d.jpg" % cid
            try:
                w, h = _save_jpg(f, os.path.join(idir, name), flip=bool(ct.get("flip")))
                used.add(name)
                body.append('<div class="cut"><img src="img/%s" alt="" width="%d" height="%d" loading="lazy">%s</div>' % (name, w, h, over))
                continue
            except Exception as e:                        # 열 수 없는 그림: 그 컷만 자리 표시로 넣고 계속
                why = "broken image"
                print("[note] cut %d: broken image, placeholder used (%s)" % (cid, _why(e)))
        body.append('<div class="cut none"><div class="noimg">cut %d: %s</div>%s</div>' % (cid, why, over))
    title = html.escape(str(c.get("title") or ep))
    p = os.path.join(wdir, "index.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(PAGE % (title, faces + CSS, title, "웹툰판 · 전체 %d컷" % n, cover, "\n".join(body)))
    for fn in os.listdir(idir):                           # 옛 그림 정리: 새 index.html 을 쓴 뒤에, 이번에 안 쓴 jpg 만 (없어진 컷·꺼진 표지).
        if fn.lower().endswith(".jpg") and fn not in used:   # 도중에 멈춰도 옛 화면이 안 깨짐. glob 은 경로의 [ ] 를 무늬로 읽어서 안 씀
            try:
                os.remove(os.path.join(idir, fn))
            except OSError:
                pass
    print("webtoon -> %s  (%d cuts)" % (p, n))
    return p


def attach(nk, kit, ep, conti, out, st=None, style=None):
    """말풍선 조립(page_letter) 끝에 부름. presets.yaml manga: webview: false 면 안 만듦"""
    if not enabled(st):
        old = os.path.join(out, "webtoon")
        print("[webtoon] 웹툰판 꺼짐 (presets.yaml manga: webview: false)%s"
              % (" - 전에 만든 %s 폴더는 그대로 둠 (지금 쪽과 다를 수 있음)" % old if os.path.isdir(old) else ""))
        return None
    return build(nk, kit, ep, conti, out, style)


# ------------------------------------------------------------------ nk ep webview <만화> [--style S]
def run(nk, kit, args):
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    style = getattr(args, "style", None)
    out = os.path.join(W.ep_dir(kit, args.ep), "out_" + style if style else "out")      # letter / page_letter 와 같은 폴더
    return build(nk, kit, args.ep, conti, out, style)


def add_parser(esub, nk, kit):
    a = esub.add_parser("webview", help="make only the webtoon view again (out/webtoon/index.html: one cut per screen width, "
                                        "text as HTML over the pictures), e.g. nk ep webview ep01")
    a.add_argument("ep")
    a.add_argument("--style", help="use episodes/<ep>/cuts_<style>/ (from nk ep restyle) and write out_<style>/webtoon/")
    a.set_defaults(func=lambda x: run(nk, kit, x))
