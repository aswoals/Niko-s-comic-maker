# -*- coding: utf-8 -*-
"""웹툰판 (nk_webview): 컷 순서(tree 잎·rows 줄·쪽 없는 스트립), 글자 귀퉁이, 해설은 왼쪽만, read: ltr 이어도 안 뒤집음,
같은 줄의 두 귀퉁이를 한 줄(.row)로, 긴 낱말 줄바꿈, 웹툰판 전용 자리 web_at (계획표 -> 콘티 -> 웹툰판, 쪽 만화는 그대로),
v2 콘티의 외침, 글자 escape, 그림 없는 컷·깨진 그림, 옛 그림 정리(다 만든 뒤에만), 바깥 주소 없음, 말풍선 색, 끄는 스위치,
쪽 조립(page_letter) 끝에 붙기, nk ep webview.
ComfyUI·GPU 없음: 작은 PNG 컷과 임시 conti.yaml 만 씀"""
import argparse, json, os, re, shutil, types

import pytest
import yaml
from PIL import Image

import nk
import nk_plan
import nk_webtoon as W
import nk_webview as V

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WH = (300, 420)                                        # 시험용 작은 쪽 크기

# 1쪽 = tree (잎 순서 2, 1, 3 — cuts 목록 순서와 다름), 2쪽 = rows (줄 순서 5, 4, 6 — cuts 목록 순서와 다름)
CONTI = """
title: 웹툰판 시험
format: page
read: ltr
char: none
chars: {talker: talker, plain: plain}
pages:
- page: 1
  tree: {split: h, r: [0.5, 0.5], kids: [{cut: 2}, {split: v, r: [0.5, 0.5], kids: [{cut: 1}, {cut: 3}]}]}
  cuts:
  - {id: 1, scene: a, text: [{type: speech, who: talker, text: "안녕", at: tr}, {type: narration, text: "아침.", at: tr}]}
  - {id: 2, scene: b, text: [{type: sfx, text: "쾅", at: bl}]}
  - {id: 3, scene: c}
- page: 2
  rows: [{h: 0.5, cuts: [5, 4]}, {h: 0.5, cuts: [6]}]
  cuts:
  - {id: 4, scene: d, text: [{type: shout, who: plain, text: "뭐라고", at: tl}]}
  - {id: 5, scene: e}
  - {id: 6, scene: f, text: [{type: thought, text: "음", at: br}]}
"""

# 계획표 (plan.yaml) — web_at 이 계획표에서 콘티로 넘어가는지 보는 데만 씀. 캐릭터는 tests/fixtures 의 testcat
PLAN = """
title: 계획표 시험
cast: {hero: testcat}
main: hero
locations: {park: "park, grass, outdoors, day"}
pages:
  - cuts:
      - who: []
        shot: wide
        loc: park
        action: "tree, sunlight"
        lines:
          - {kind: narration, text: "해설 한 줄"}
      - who: [hero]
        shot: knee
        loc: park
        action: "standing, smile"
        lines:
          - {who: hero, text: "먼저 하는 말"}
          - {who: hero, text: "나중 말", at: bl}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """NK_HOME = 임시 폴더 (episodes/ep1 에 conti.yaml + 컷 그림 6장). 키트 폴더 = 임시 kit (fonts 없음).
    캐릭터 = 임시 폴더: talker (말풍선 색 있음), plain (없음)"""
    monkeypatch.setenv("NK_HOME", str(tmp_path / "home"))
    chars = tmp_path / "chars"
    chars.mkdir()
    (chars / "talker.yaml").write_text('name: talker\ntags_short: "1girl"\nbubble: {fill: "#FFF0F5", line: "#D9578A"}\n', encoding="utf-8")
    (chars / "plain.yaml").write_text('name: plain\ntags_short: "1boy"\n', encoding="utf-8")
    monkeypatch.setenv("NK_CHARS", str(chars))
    monkeypatch.setattr(nk, "load_presets", lambda: {"manga": {"width": WH[0], "ratio": WH[1] / WH[0]}})
    ep = tmp_path / "home" / "episodes" / "ep1"
    (ep / "cuts").mkdir(parents=True)
    (ep / "conti.yaml").write_text(CONTI, encoding="utf-8")
    for i in range(1, 7):
        Image.new("RGB", (120, 80), (40 * i, 100, 100)).save(ep / "cuts" / ("cut%02d.png" % i))
    (tmp_path / "kit").mkdir()
    return types.SimpleNamespace(kit=str(tmp_path / "kit"), ep=ep, out=str(ep / "out"), web=ep / "out" / "webtoon")


def load(home):
    return W.load_conti(nk, home.kit, "ep1")


def cut(c, cid):
    return next(ct for ct in c["cuts"] if int(ct["id"]) == cid)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def build(home, c, kit=None):
    return read(V.build(nk, kit or home.kit, "ep1", c, home.out))


def main_lines(page):
    return re.search(r"<main>(.*)</main>", page, re.S).group(1).split("\n")


def css_rules(page):
    """<style> 안의 규칙 -> {선택자: {속성: 값}}. 공백·줄바꿈이 달라져도 같은 결과 (글자 그대로 견주지 않으려고)"""
    css = page.split("<style>")[1].split("</style>")[0]
    out = {}
    for sel, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        decl = dict((k.strip(), v.strip()) for k, v in (d.split(":", 1) for d in body.split(";") if ":" in d))
        for s in sel.split(","):
            out.setdefault(s.strip(), {}).update(decl)
    return out


def pct(v):
    assert v.endswith("%"), v
    return float(v[:-1])


def no_draw(*a, **k):
    raise AssertionError("그리면 안 되는데 그리기를 부름")


ROW_TR = '<div class="row top"><div class="stack tr">%s</div></div>'          # 글자 하나가 오른쪽 위에 있을 때의 모양


# ------------------------------------------------------------------ 순서·구조
def test_reading_order_is_tree_leaves_and_rows(home):
    c = load(home)
    assert [int(ct["id"]) for ct in c["cuts"]] == [1, 2, 3, 5, 4, 6]            # load_conti 가 펴 준 순서: tree 쪽은 cuts 목록 순서
    assert [(pn, int(ct["id"])) for pn, ct in V.ordered_cuts(c)] == [(1, 2), (1, 1), (1, 3), (2, 5), (2, 4), (2, 6)]
    strip = {"cuts": [{"id": 3}, {"id": 1}]}                                    # 쪽이 없는 콘티(세로 스트립)는 적힌 순서
    assert [(pn, ct["id"]) for pn, ct in V.ordered_cuts(strip)] == [(None, 3), (None, 1)]
    assert V.ordered_cuts({}) == []


def test_build_writes_one_html_with_cuts_in_order(home, capsys):
    p = V.build(nk, home.kit, "ep1", load(home), home.out)
    assert p == str(home.web / "index.html") and os.path.exists(p)
    assert "webtoon -> %s  (6 cuts)" % p in capsys.readouterr().out
    page = read(p)
    lines = main_lines(page)
    kinds = ["page" if l.startswith('<div class="page">') else "cut" if l.startswith('<div class="cut') else "?" for l in lines]
    assert kinds == ["page", "cut", "cut", "cut", "page", "cut", "cut", "cut"]     # <main> 안은 한 줄에 하나씩
    assert lines[0] == '<div class="page">1쪽</div>' and lines[4] == '<div class="page">2쪽</div>'
    assert re.findall(r'src="img/cut(\d+)\.jpg"', page) == ["02", "01", "03", "05", "04", "06"]
    assert sorted(os.listdir(home.web / "img")) == ["cut%02d.jpg" % i for i in range(1, 7)]
    assert lines[3] == '<div class="cut"><img src="img/cut03.jpg" alt="" width="120" height="80" loading="lazy"></div>'
    assert lines[1] == ('<div class="cut"><img src="img/cut02.jpg" alt="" width="120" height="80" loading="lazy">'
                        '<div class="row bottom"><div class="stack bl"><div class="sfx">쾅</div></div></div></div>')
    assert "<h1>웹툰판 시험</h1><p>웹툰판 · 전체 6컷</p>" in page
    assert page.count("<div") == page.count("</div>")


def test_strip_conti_without_pages_builds_too(home):
    (home.ep / "conti.yaml").write_text(
        'title: 세로 스트립\nchar: none\ncuts:\n'
        '  - {id: 2, scene: a, text: [{type: speech, text: "둘 먼저", at: tl}]}\n'
        '  - {id: 1, scene: b}\n', encoding="utf-8")
    c = load(home)
    assert c.get("format") != "page" and all("page" not in ct for ct in c["cuts"])
    page = build(home, c)
    lines = main_lines(page)
    assert len(lines) == 2 and all(l.startswith('<div class="cut">') for l in lines)       # 쪽 구분 줄 없음
    assert re.findall(r'src="img/cut(\d+)\.jpg"', page) == ["02", "01"]                   # 적힌 순서
    assert '<div class="stack tl"><div class="b speech">둘 먼저</div></div>' in lines[0] and "전체 2컷" in page
    assert sorted(os.listdir(home.web / "img")) == ["cut01.jpg", "cut02.jpg"]


def test_pictures_are_shrunk_and_flipped_but_not_cropped(home):
    im = Image.new("RGB", (2160, 1000), (255, 0, 0))
    im.paste((0, 0, 255), (1080, 0, 2160, 1000))                                # 왼쪽 빨강, 오른쪽 파랑
    im.save(home.ep / "cuts" / "cut01.png")
    shutil.copyfile(home.ep / "cuts" / "cut01.png", home.ep / "cuts" / "cut02.png")
    c = load(home)
    cut(c, 1)["flip"] = True
    page = build(home, c)
    assert '<img src="img/cut01.jpg" alt="" width="1080" height="500" loading="lazy">' in page
    with Image.open(home.web / "img" / "cut01.jpg") as a, Image.open(home.web / "img" / "cut02.jpg") as b:
        assert a.size == (1080, 500) and b.size == (1080, 500)                  # 줄이기만 (비율 그대로 = 안 자름)
        la, lb = a.convert("RGB").getpixel((100, 250)), b.convert("RGB").getpixel((100, 250))
    assert la[2] > 180 and la[0] < 80                                           # flip: 왼쪽이 파랑
    assert lb[0] > 180 and lb[2] < 80                                           # 안 뒤집은 컷은 그대로 빨강


# ------------------------------------------------------------------ 글자 자리
def test_at_to_corner_table():
    table = {"tl": "tl", "tr": "tr", "bl": "bl", "br": "br", "t": "tl", "top": "tl", "b": "bl", "bottom": "bl",
             "l": "tl", "left": "tl", "r": "tr", "right": "tr", "c": "tr", "center": "tr", "": "tr", None: "tr",
             "TL": "tl", " br ": "br", "어딘가": "tr"}
    for at, want in table.items():
        assert V.corner({"type": "speech", "at": at}) == want, at
        assert V.corner({"type": "sfx", "at": at}) == want, at
    assert V.corner({"type": "speech"}) == "tr" and V.corner({}) == "tr"
    for at in W.ANCHOR:                                                         # nk 가 쓰는 자리 이름은 모두 표에 있음
        assert at in V.CORNER, at


def test_narration_stays_left_and_a_corner_stacks_in_written_order():
    for at, want in {"tl": "tl", "tr": "tl", "top": "tl", "right": "tl", None: "tl", "bl": "bl", "br": "bl", "bottom": "bl"}.items():
        assert V.corner({"type": "narration", "at": at}) == want, at
    texts = [{"type": "speech", "text": "가", "at": "tr"}, {"type": "narration", "text": "나", "at": "tr"},
             {"type": "sfx", "text": "쾅", "at": "bl"}, {"type": "whisper", "text": "다", "at": "tr"}]
    assert V.overlay(texts, {}) == (
        '<div class="row top"><div class="stack tl"><div class="n">나</div></div>'
        '<div class="stack tr"><div class="b speech">가</div><div class="b whisper">다</div></div></div>'       # 한 귀퉁이에 여럿 = 적힌 순서로 쌓음
        '<div class="row bottom"><div class="stack bl"><div class="sfx">쾅</div></div></div>')


def test_ltr_conti_is_not_mirrored_in_the_built_page(home):
    """read: ltr 콘티: 쪽 조립은 대사 자리를 좌우로 뒤집지만(W.MIRROR) 웹툰판은 적힌 그대로 — 읽는 방향을 바꿔도 결과가 같음"""
    c = load(home)
    assert c["read"] == "ltr" and W.MIRROR["tr"] == "tl" and W.MIRROR["tl"] == "tr" and W.MIRROR["br"] == "bl"
    ltr = build(home, c)
    lines = main_lines(ltr)
    assert ('<div class="row top"><div class="stack tl"><div class="n">아침.</div></div>'        # 1번 컷: 대사 at tr -> tr (뒤집으면 해설과 같은 tl 에 몰림)
            '<div class="stack tr"><div class="b speech" style="background:#FFF0F5;border-color:#D9578A">안녕</div></div></div>') in lines[2]
    assert '<div class="row top"><div class="stack tl"><div class="b shout">뭐라고</div></div></div>' in lines[6]       # 4번 컷: at tl -> tl
    assert '<div class="row bottom"><div class="stack br"><div class="b thought">음</div></div></div>' in lines[7]      # 6번 컷: at br -> br
    c2 = load(home)
    c2["read"] = "rtl"
    assert main_lines(build(home, c2)) == lines


def test_rows_hold_the_two_corners_of_a_line(home):
    one = lambda at: {"type": "speech", "text": at, "at": at}
    both = V.overlay([one("tl"), one("tr"), one("bl"), one("br")], {})
    assert both == ('<div class="row top"><div class="stack tl"><div class="b speech">tl</div></div>'
                    '<div class="stack tr"><div class="b speech">tr</div></div></div>'
                    '<div class="row bottom"><div class="stack bl"><div class="b speech">bl</div></div>'
                    '<div class="stack br"><div class="b speech">br</div></div></div>')
    assert V.overlay([one("br")], {}) == '<div class="row bottom"><div class="stack br"><div class="b speech">br</div></div></div>'   # 글자가 없는 줄은 안 넣음
    assert V.overlay([one("tl")], {}) == '<div class="row top"><div class="stack tl"><div class="b speech">tl</div></div></div>'
    page = build(home, load(home))
    assert set(re.findall(r'class="(row[^"]*)"', page)) == {"row top", "row bottom"}      # 줄 이름이 말풍선 클래스(.b)와 겹치면 안 됨
    for line in main_lines(page):                                                         # 스택은 모두 줄 안에, 위 줄에는 tl·tr 만, 아래 줄에는 bl·br 만
        rest = re.sub(r'<div class="row top">(<div class="stack t[lr]">(<div class="(b \w+|n|sfx)"[^>]*>[^<]*</div>)+</div>){1,2}</div>', "", line)
        rest = re.sub(r'<div class="row bottom">(<div class="stack b[lr]">(<div class="(b \w+|n|sfx)"[^>]*>[^<]*</div>)+</div>){1,2}</div>', "", rest)
        assert "stack" not in rest and "row" not in rest, line
    css = css_rules(page)
    row, stack = css[".row"], css[".stack"]
    assert row["position"] == "absolute" and row["display"] == "flex"                    # 줄이 컷 위에 뜨고, 스택 둘이 그 안에서 폭을 나눔
    assert "top" in css[".row.top"] and "bottom" in css[".row.bottom"]
    assert "position" not in stack and stack["flex"].split()[1] != "0"                   # 스택은 줄 안의 칸 (넘치면 줄어듦)
    assert css[".tr"]["margin-left"] == "auto" and css[".br"]["margin-left"] == "auto"   # 오른쪽 스택은 혼자 있어도 오른쪽에
    row_w = 100 - pct(row["left"]) - pct(row["right"])                                   # 줄 폭 = 컷 폭의 몇 %
    assert abs(row_w * pct(stack["max-width"]) / 100 - 62) < 0.05                        # 스택 최대 폭 = 컷 폭의 62% (혼자 있는 귀퉁이의 줄바꿈 기준)


def test_long_words_without_spaces_can_wrap(home):
    css = css_rules(build(home, load(home)))
    for sel in (".b", ".n"):                                                    # 보통 대사는 띄어쓰기에서만 (keep-all), 상자보다 긴 낱말만 낱말 안에서
        assert css[sel]["word-break"] == "keep-all" and css[sel]["overflow-wrap"] == "anywhere", sel


# ------------------------------------------------------------------ web_at (웹툰판에서만 자리 옮기기)
def test_web_at_moves_text_in_the_webtoon_view_only():
    for at in (None, "tl", "tr", "bl", "br", "top"):
        for web_at, want in {"tl": "tl", "tr": "tr", "bl": "bl", "br": "br", "BL": "bl", " br ": "br", "bottom": "bl", "top": "tl"}.items():
            assert V.corner({"type": "speech", "at": at, "web_at": web_at}) == want, (at, web_at)       # web_at 이 at 보다 우선
    assert V.corner({"type": "narration", "at": "tl", "web_at": "tr"}) == "tr"                          # 해설도 오른쪽으로 갈 수 있음
    assert V.corner({"type": "narration", "at": "tl", "web_at": "br"}) == "br"
    assert V.corner({"type": "sfx", "at": "bl", "web_at": "tr"}) == "tr"
    for bad in ("", None, "center", "어딘가", 3, False, ["bl"]):                                         # 모르는 값은 무시 = at 규칙 그대로
        assert V.corner({"type": "speech", "at": "bl", "web_at": bad}) == "bl", bad
        assert V.corner({"type": "narration", "at": "tr", "web_at": bad}) == "tl", bad
        assert V.corner({"type": "speech", "web_at": bad}) == "tr", bad
    texts = [{"type": "speech", "text": "먼저", "at": "tr", "web_at": "bl"}, {"type": "speech", "text": "나중", "at": "bl"}]
    assert V.overlay(texts, {}) == ('<div class="row bottom"><div class="stack bl"><div class="b speech">먼저</div>'
                                    '<div class="b speech">나중</div></div></div>')                    # 옮겨 간 귀퉁이에서도 적힌 순서대로 쌓음


def test_web_at_goes_from_plan_to_conti():
    def texts_of(plan):
        conti, _ = nk_plan.compile_plan(plan, None, KIT)
        return {t["text"]: t for pg in conti["pages"] for ct in pg["cuts"] for t in ct.get("text") or []}
    base = texts_of(yaml.safe_load(PLAN))
    assert set(base) == {"해설 한 줄", "먼저 하는 말", "나중 말"} and not any("web_at" in t for t in base.values())   # 안 적으면 칸이 안 생김
    plan = yaml.safe_load(PLAN)
    plan["pages"][0]["cuts"][0]["lines"][0]["web_at"] = "tr"                    # 해설
    plan["pages"][0]["cuts"][1]["lines"][0]["web_at"] = "bl"                    # 대사
    got = texts_of(plan)
    assert got["해설 한 줄"]["web_at"] == "tr" and got["먼저 하는 말"]["web_at"] == "bl" and "web_at" not in got["나중 말"]
    for k, t in got.items():                                                    # at 을 비롯한 나머지 칸은 그대로
        assert {a: b for a, b in t.items() if a != "web_at"} == base[k], k
    assert V.corner(got["해설 한 줄"]) == "tr" and V.corner(got["먼저 하는 말"]) == "bl" and V.corner(got["나중 말"]) == "bl"


def test_web_at_belongs_in_the_plan_when_there_is_one(tmp_path, monkeypatch):
    """계획표가 있는 만화: web_at 은 plan.yaml 에 적고 콘티를 다시 만들어야(nk ep compile) 콘티로 넘어옴.
    conti.yaml 만 고친 것은 웹툰판에는 바로 보이지만, 계획표로 콘티를 다시 만들면 사라짐 (대사 고치기와 같은 원칙)"""
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    ep = tmp_path / "episodes" / "ep1"
    ep.mkdir(parents=True)
    (ep / "plan.yaml").write_text(PLAN, encoding="utf-8")

    def recompile():
        nk_plan.run_compile(nk, KIT, argparse.Namespace(ep="ep1", dry=False, plan=None))

    def web_ats():                                                              # 웹툰판이 읽는 콘티에서 글자마다 web_at
        return {t["text"]: t.get("web_at") for ct in W.load_conti(nk, KIT, "ep1")["cuts"] for t in ct.get("text") or []}
    recompile()
    assert web_ats() == {"해설 한 줄": None, "먼저 하는 말": None, "나중 말": None}
    doc = yaml.safe_load((ep / "conti.yaml").read_text(encoding="utf-8"))       # conti.yaml 만 고침
    for pg in doc["pages"]:
        for ct in pg["cuts"]:
            for t in ct.get("text") or []:
                if t["text"] == "나중 말":
                    t["web_at"] = "br"
    (ep / "conti.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert web_ats()["나중 말"] == "br"                                          # 지금 웹툰판에는 반영됨
    recompile()
    assert web_ats()["나중 말"] is None                                          # 계획표로 콘티를 다시 만들면 사라짐
    (ep / "plan.yaml").write_text(PLAN.replace('text: "나중 말", at: bl}', 'text: "나중 말", at: bl, web_at: br}'), encoding="utf-8")
    assert web_ats()["나중 말"] is None                                          # plan.yaml 에만 적으면 다시 만들기 전에는 콘티에 없음
    recompile()
    recompile()
    assert web_ats() == {"해설 한 줄": None, "먼저 하는 말": None, "나중 말": "br"}        # 다시 만들 때마다 넘어옴


def test_page_comic_does_not_look_at_web_at(home):
    """conti.yaml 의 글자에 web_at 을 적어도 쪽 만화(page_NN.png)는 한 점도 안 바뀌고, 웹툰판에서만 자리가 바뀜"""
    def pages_and_view():
        W.page_letter(nk, home.kit, argparse.Namespace(ep="ep1", style=None), load(home))
        px = []
        for f in ("page_01.png", "page_02.png"):
            with Image.open(os.path.join(home.out, f)) as im:
                px.append((im.size, im.convert("RGB").tobytes()))
        return px, read(home.web / "index.html")
    (home.ep / "cover.yaml").write_text("enabled: false\n", encoding="utf-8")
    before, view0 = pages_and_view()
    src = (home.ep / "conti.yaml").read_text(encoding="utf-8")
    moved = src.replace('{type: speech, who: talker, text: "안녕", at: tr}', '{type: speech, who: talker, text: "안녕", at: tr, web_at: bl}')
    moved = moved.replace('{type: narration, text: "아침.", at: tr}', '{type: narration, text: "아침.", at: tr, web_at: tr}')
    assert moved.count("web_at") == 2
    (home.ep / "conti.yaml").write_text(moved, encoding="utf-8")
    assert [t.get("web_at") for t in cut(load(home), 1)["text"]] == ["bl", "tr"]        # load_conti 가 모르는 칸을 버리지 않음
    after, view1 = pages_and_view()
    assert after == before                                                      # 쪽 만화는 그대로
    bubble = '<div class="b speech" style="background:#FFF0F5;border-color:#D9578A">안녕</div>'
    assert ('<div class="row top"><div class="stack tl"><div class="n">아침.</div></div><div class="stack tr">%s</div></div>' % bubble) in view0
    assert ('<div class="row top"><div class="stack tr"><div class="n">아침.</div></div></div>'
            '<div class="row bottom"><div class="stack bl">%s</div></div>' % bubble) in view1
    assert "web_at" not in view1
    (home.ep / "conti.yaml").write_text(src.replace('text: "안녕", at: tr}', 'text: "안녕", at: bl}'), encoding="utf-8")
    assert pages_and_view()[0] != before                                        # (견줌이 뜻이 있는지: at 을 바꾸면 쪽 만화는 바뀜)


# ------------------------------------------------------------------ 말풍선 종류·크기
def test_bubble_kinds_and_unknown_kind():
    for k in ("speech", "shout", "whisper", "thought", "aside", "tremble"):
        assert V.overlay([{"type": k, "text": "x"}], {}) == ROW_TR % ('<div class="b %s">x</div>' % k)
    for k in ("offscreen", "이상한 종류", None, 'a" onclick="x'):
        assert V.overlay([{"type": k, "text": "x"}], {}) == ROW_TR % '<div class="b speech">x</div>', k
    assert V.overlay([{"text": "x"}, "글자가 아닌 것", None], {}) == ROW_TR % '<div class="b speech">x</div>'
    assert V.overlay([], {}) == "" and V.overlay(None, {}) == ""


def test_v2_conti_uses_the_page_comic_rule_for_shouts(home):
    """letter: v2 콘티는 쪽 조립과 같은 함수(nk_letter2.bubble_kind)로 종류를 정함: 느낌표가 둘 이상인 speech = 외침"""
    import nk_letter2
    texts = [{"type": "speech", "text": "뭐라고!!", "at": "tl"}, {"type": "speech", "text": "응!", "at": "tl"},
             {"type": "whisper", "text": "쉿!!", "at": "tl"}, {"type": "narration", "text": "쾅!! 하는 소리.", "at": "tl"},
             {"type": "offscreen", "text": "거기 서!!", "at": "tr"}, {"type": "sfx", "text": "쾅!!", "at": "bl"}]
    classes = lambda c: re.findall(r'<div class="(b \w+|n|sfx)"', V.overlay(texts, c))
    assert classes({"letter": "v2"}) == ["b shout", "b speech", "b whisper", "n", "b speech", "sfx"]
    assert classes({"letter": "V2"}) == classes({"letter": "v2"})
    assert classes({}) == ["b speech", "b speech", "b whisper", "n", "b speech", "sfx"]             # v1 콘티는 적힌 그대로
    assert classes({"letter": "v1"}) == classes({})
    assert [nk_letter2.bubble_kind(t) for t in texts[:3]] == ["shout", "speech", "whisper"]        # 쪽 조립이 쓰는 판단과 같음
    c = load(home)
    cut(c, 1)["text"] = texts[:1]
    assert '<div class="b speech">뭐라고!!</div>' in build(home, c)
    c["letter"] = "v2"
    assert '<div class="b shout">뭐라고!!</div>' in build(home, c)


def test_size_becomes_a_bounded_scale():
    one = lambda t: V.overlay([dict(t, text="x")], {}, 30)
    assert 'class="b speech" style="--s:0.80"' in one({"type": "speech", "size": 24})       # 쪽 글자 30px 기준 24px
    assert "--s:1.40" in one({"type": "speech", "size": 90}) and "--s:0.70" in one({"type": "narration", "size": 5})
    for t in ({"type": "speech"}, {"type": "speech", "size": 30}, {"type": "speech", "size": "big"}, {"type": "speech", "size": "s"},
              {"type": "sfx", "size": "m"}, {"type": "sfx", "size": 48}, {"type": "sfx", "size": True}):
        assert "style" not in one(t), t
    assert 'class="sfx" style="--s:0.80"' in one({"type": "sfx", "size": "s"})
    assert "--s:1.20" in one({"type": "sfx", "size": "l"}) and "--s:1.40" in one({"type": "sfx", "size": "xl"})
    assert all(V.SCALE_MIN <= v <= V.SCALE_MAX for v in V.SFX_SIZE.values())


# ------------------------------------------------------------------ escape
def test_text_and_title_are_escaped(home):
    c = load(home)
    c["title"] = '<script>alert(1)</script> & "제목"'
    cut(c, 1)["text"] = [{"type": "speech", "text": '<b>굵게</b> & "따옴표"\n둘째 줄', "at": "tl"},
                         {"type": "narration", "text": "a < b", "at": "tl"}, {"type": "sfx", "text": "<쾅>&", "at": "br"}]
    page = build(home, c)
    assert "<script" not in page and "<b>" not in page
    assert '<div class="b speech">&lt;b&gt;굵게&lt;/b&gt; &amp; &quot;따옴표&quot;<br>둘째 줄</div>' in page
    assert '<div class="n">a &lt; b</div>' in page and '<div class="sfx">&lt;쾅&gt;&amp;</div>' in page
    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;제목&quot;</title>" in page
    assert page.count("<div") == page.count("</div>") and len(main_lines(page)) == 8      # 줄 구조가 안 깨짐


# ------------------------------------------------------------------ 그림 없는 컷·깨진 그림·초안·옛 그림 정리
def test_cut_without_picture_gets_a_placeholder(home):
    os.remove(home.ep / "cuts" / "cut03.png")
    c = load(home)
    cut(c, 3)["text"] = [{"type": "speech", "text": "그림은 아직", "at": "bl"}]
    page = build(home, c)
    assert ('<div class="cut none"><div class="noimg">cut 3: no image</div>'
            '<div class="row bottom"><div class="stack bl"><div class="b speech">그림은 아직</div></div></div></div>') in main_lines(page)
    assert not (home.web / "img" / "cut03.jpg").exists() and (home.web / "img" / "cut06.jpg").exists()
    assert "웹툰판 · 전체 6컷" in page and len(main_lines(page)) == 8
    shutil.rmtree(home.ep / "cuts")                                             # 그림이 하나도 없어도 끝까지
    page = build(home, load(home))
    assert page.count('class="cut none"') == 6 and os.listdir(home.web / "img") == []


def test_broken_pictures_do_not_stop_the_build(home, capsys):
    build(home, load(home))                                                     # 먼저 멀쩡하게 한 번 (cut03.jpg 가 생김)
    (home.ep / "cuts" / "cut03.png").write_bytes(b"not a png at all")           # 열 수 없는 컷 그림
    with open(os.path.join(home.out, "page_00.png"), "wb") as f:                # 열 수 없는 표지
        f.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 20)
    c = load(home)
    cut(c, 3)["text"] = [{"type": "speech", "text": "그림이 깨짐", "at": "tr"}]
    capsys.readouterr()
    page = build(home, c)
    out = capsys.readouterr().out
    assert ('<div class="cut none"><div class="noimg">cut 3: broken image</div>'                  # 그 컷만 자리 표시 (그림 없음과 구분됨), 글자는 그대로
            '<div class="row top"><div class="stack tr"><div class="b speech">그림이 깨짐</div></div></div></div>') in main_lines(page)
    assert "[note] cut 3: broken image" in out and "cover left out" in out and "(6 cuts)" in out
    assert 'class="cover"' not in page and "cover.jpg" not in page                                # 표지만 빠짐
    assert re.findall(r'src="img/cut(\d+)\.jpg"', page) == ["02", "01", "05", "04", "06"]         # 나머지 컷은 끝까지
    assert sorted(os.listdir(home.web / "img")) == ["cut01.jpg", "cut02.jpg", "cut04.jpg", "cut05.jpg", "cut06.jpg"]


def test_draft_is_used_when_there_is_no_final(home):
    os.remove(home.ep / "cuts" / "cut03.png")
    d = os.path.join(home.kit, "runs", "ep1", "cut03")                          # 후보 폴더 (output_root 기본 = 키트 runs)
    os.makedirs(d)
    Image.new("RGB", (64, 96), (0, 200, 0)).save(os.path.join(d, "001_seed.png"))
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": "001_seed.png"}], f)
    page = build(home, load(home))
    assert '<img src="img/cut03.jpg" alt="" width="64" height="96" loading="lazy">' in page


def test_old_pictures_are_removed_only_after_the_new_page_is_written(home, monkeypatch):
    os.makedirs(home.out)
    Image.new("RGB", WH, (20, 20, 60)).save(os.path.join(home.out, "page_00.png"))      # 표지 (nk_cover 가 만든 것)
    c = load(home)
    page0 = build(home, c)
    img = home.web / "img"
    assert page0.index('<div class="cover"><img src="img/cover.jpg" alt="" width="%d" height="%d"></div>' % WH) < page0.index("<main>")
    assert sorted(os.listdir(img)) == ["cover.jpg"] + ["cut%02d.jpg" % i for i in range(1, 7)]
    (img / "memo.txt").write_text("jpg 가 아닌 파일", encoding="utf-8")
    os.remove(os.path.join(home.out, "page_00.png"))                            # 표지가 꺼지고
    c["cuts"] = [ct for ct in c["cuts"] if int(ct["id"]) != 6]                  # 6번 컷이 없어짐
    real, calls = V.overlay, []

    def stops_midway(texts, conti, fs0=30):
        calls.append(1)
        if len(calls) == 4:
            raise RuntimeError("만들다가 멈춤")
        return real(texts, conti, fs0)
    monkeypatch.setattr(V, "overlay", stops_midway)
    with pytest.raises(RuntimeError):
        V.build(nk, home.kit, "ep1", c, home.out)
    assert read(home.web / "index.html") == page0                               # 도중에 멈추면: 옛 화면 그대로,
    assert (img / "cover.jpg").exists() and (img / "cut06.jpg").exists()        # 옛 화면이 쓰는 그림도 그대로
    monkeypatch.setattr(V, "overlay", real)
    page = build(home, c)                                                       # 끝까지 만들면: 이번에 안 쓴 jpg 만 지움
    assert sorted(os.listdir(img)) == ["cut%02d.jpg" % i for i in range(1, 6)] + ["memo.txt"]
    assert 'class="cover"' not in page and "cut06" not in page and "전체 5컷" in page


def test_old_pictures_are_removed_when_the_path_has_brackets(home, tmp_path, monkeypatch):
    root = tmp_path / "만화 [1]"                                                 # glob 은 [1] 을 무늬로 읽음 -> 정리가 조용히 안 되던 경로
    shutil.copytree(home.ep, root / "episodes" / "ep1")
    monkeypatch.setenv("NK_HOME", str(root))
    out = root / "episodes" / "ep1" / "out"
    img = out / "webtoon" / "img"
    img.mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(img / "cut99.jpg")                            # 없어진 컷의 옛 그림
    V.build(nk, home.kit, "ep1", W.load_conti(nk, home.kit, "ep1"), str(out))
    assert sorted(os.listdir(img)) == ["cut%02d.jpg" % i for i in range(1, 7)]


# ------------------------------------------------------------------ 바깥 주소·글꼴
def test_no_outside_addresses_and_fonts_from_the_kit(home):
    page = build(home, load(home), kit=KIT)                                     # 진짜 키트의 fonts/
    assert "http://" not in page and "https://" not in page and "//" not in page.replace("</", "")
    assert "<script" not in page.lower()
    assert re.findall(r"url\(([^)]*)\)", page) == ["font.ttf", "sfx.ttf"]
    assert all(s.startswith("img/") for s in re.findall(r'src="([^"]*)"', page))
    for name, src, _ in V.FONT_FILES:
        assert os.path.getsize(home.web / name) == os.path.getsize(os.path.join(KIT, "fonts", src))
    assert '<html lang="ko">' in page and re.search(r'<meta name="viewport" content="width=device-width', page)
    assert re.search(r"prefers-color-scheme\s*:\s*dark", page) and re.search(r"prefers-reduced-motion\s*:\s*reduce", page)
    assert css_rules(page)["main"]["max-width"] == "760px"


def test_missing_fonts_fall_back_to_system_fonts(home):
    page = build(home, load(home))                                              # 임시 kit 에는 fonts/ 가 없음
    assert "@font-face" not in page and "url(" not in page
    names = [x.strip().strip('"') for x in css_rules(page)["body"]["font-family"].split(",")]
    assert names[1:] == ["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", "sans-serif"]
    assert sorted(os.listdir(home.web)) == ["img", "index.html"]


# ------------------------------------------------------------------ 말풍선 색
def test_bubble_color_from_character_file_and_off(home):
    c = load(home)
    cut(c, 1)["text"] = [{"type": "speech", "who": "talker", "text": "색", "at": "tr"}, {"type": "shout", "who": "plain", "text": "흰", "at": "bl"},
                         {"type": "speech", "text": "누구", "at": "bl"}, {"type": "narration", "who": "talker", "text": "해설", "at": "tl"}]
    colored = '<div class="b speech" style="background:#FFF0F5;border-color:#D9578A">색</div>'
    page = build(home, c)
    assert colored in page and '<div class="b shout">흰</div>' in page and '<div class="b speech">누구</div>' in page
    assert '<div class="n">해설</div>' in page                                   # 해설·효과음에는 색 없음
    c["bubble_color"] = "offscreen"                                             # 쪽에서는 화면 밖 대사만 색 / 웹툰판은 꼬리가 없어서 전부
    assert colored in build(home, c)
    for off in (False, "off", "none"):                                          # YAML 은 off 를 false 로 읽음
        c["bubble_color"] = off
        page = build(home, c)
        assert '<div class="b speech">색</div>' in page and "#FFF0F5" not in page, off
    c["bubble_color"] = "all"
    for bad in ('red;"><i>', "#fff\n", "#fff;color:red", "url(x)"):             # 색처럼 안 생긴 값은 안 넣음 (끝에 줄바꿈이 붙은 것도)
        c["_cast"]["talker"]["bubble"] = {"fill": bad, "line": "#000"}
        page = build(home, c)
        assert '<div class="b speech">색</div>' in page and "<i>" not in page, bad
    c["_cast"]["talker"]["bubble"] = {"fill": "rgb(255, 240, 245)", "line": "hotpink"}
    assert '<div class="b speech" style="background:rgb(255, 240, 245);border-color:hotpink">색</div>' in build(home, c)


# ------------------------------------------------------------------ 스위치·쪽 조립에 붙기
def test_switch_is_on_by_default_and_off_skips(home, capsys):
    assert V.enabled(W._page_style({})) and V.enabled(W._page_style(None)) and V.enabled(None)      # 키가 없으면 켜짐
    assert V.enabled(W._page_style({"manga": {"webview": True}})) and V.enabled({"webview": "on"})
    for off in (False, "false", "off", "no", 0):
        assert not V.enabled(W._page_style({"manga": {"webview": off}})), off
    c = load(home)
    assert V.attach(nk, home.kit, "ep1", c, home.out, {"webview": False}) is None
    out = capsys.readouterr().out
    assert not home.web.exists() and "웹툰판 꺼짐" in out and "그대로 둠" not in out
    assert V.attach(nk, home.kit, "ep1", c, home.out, {"font_size": 30}) == str(home.web / "index.html")
    before = read(home.web / "index.html")
    capsys.readouterr()
    assert V.attach(nk, home.kit, "ep1", c, home.out, {"webview": "off"}) is None                   # 끄면: 전에 만든 폴더는 안 지우고 알려 줌
    out = capsys.readouterr().out
    assert "웹툰판 꺼짐" in out and "그대로 둠" in out and str(home.web) in out
    assert read(home.web / "index.html") == before


def test_page_letter_makes_the_webtoon_view_unless_switched_off(home, monkeypatch):
    import nk_cover
    monkeypatch.setattr(nk_cover, "_stream", no_draw)
    (home.ep / "cover.yaml").write_text("art: none\n", encoding="utf-8")        # 표지는 글자만 (그리기 없음)
    args = argparse.Namespace(ep="ep1", style=None)
    W.page_letter(nk, home.kit, args, load(home))
    for f in ("page_00.png", "page_01.png", "page_02.png", "book.pdf"):
        assert os.path.exists(os.path.join(home.out, f)), f
    page = read(home.web / "index.html")
    assert '<div class="cover"><img src="img/cover.jpg"' in page and (home.web / "img" / "cover.jpg").exists()   # 표지 다음에 만들어짐
    assert re.findall(r'src="img/cut(\d+)\.jpg"', page) == ["02", "01", "03", "05", "04", "06"]
    shutil.rmtree(home.web)
    monkeypatch.setattr(nk, "load_presets", lambda: {"manga": {"width": WH[0], "ratio": WH[1] / WH[0], "webview": False}})
    W.page_letter(nk, home.kit, args, load(home))
    assert os.path.exists(os.path.join(home.out, "page_01.png")) and os.path.exists(os.path.join(home.out, "book.pdf"))
    assert not home.web.exists()                                                # 꺼 두면 안 만듦


def test_page_letter_with_style_writes_the_view_next_to_those_pages(home):
    sd = home.ep / "cuts_soft"                                                  # nk ep restyle 결과 흉내: 1번 컷만 초록
    sd.mkdir()
    Image.new("RGB", (120, 80), (0, 220, 0)).save(sd / "cut01.png")
    t = os.path.getmtime(home.ep / "cuts" / "cut01.png") + 10
    os.utime(sd / "cut01.png", (t, t))
    (home.ep / "cover.yaml").write_text("enabled: false\n", encoding="utf-8")
    W.page_letter(nk, home.kit, argparse.Namespace(ep="ep1", style="soft"), load(home))
    out2 = home.ep / "out_soft"
    assert (out2 / "page_01.png").exists() and (out2 / "webtoon" / "index.html").exists() and not os.path.exists(home.out)
    with Image.open(out2 / "webtoon" / "img" / "cut01.jpg") as a, Image.open(out2 / "webtoon" / "img" / "cut02.jpg") as b:
        ga, gb = a.convert("RGB").getpixel((60, 40)), b.convert("RGB").getpixel((60, 40))
    assert ga[1] > 180 and ga[0] < 60 and not (gb[1] > 180 and gb[0] < 60)      # 그림체판 그림 (없는 컷은 원래 그림)


def test_page_letter_survives_webtoon_view_errors(home, monkeypatch, capsys):
    def boom(*a, **k):
        raise SystemExit(1)
    monkeypatch.setattr(V, "build", boom)
    (home.ep / "cover.yaml").write_text("enabled: false\n", encoding="utf-8")
    W.page_letter(nk, home.kit, argparse.Namespace(ep="ep1", style=None), load(home))
    assert "[note] webtoon view skipped" in capsys.readouterr().out
    assert os.path.exists(os.path.join(home.out, "page_02.png")) and os.path.exists(os.path.join(home.out, "book.pdf"))


# ------------------------------------------------------------------ nk ep webview <만화> [--style S]
def test_ep_webview_command_makes_only_the_webtoon_view(home):
    sd = home.ep / "cuts_soft"                                                  # nk ep restyle 결과 흉내: 1번 컷만 초록
    sd.mkdir()
    Image.new("RGB", (120, 80), (0, 220, 0)).save(sd / "cut01.png")
    t = os.path.getmtime(home.ep / "cuts" / "cut01.png") + 10
    os.utime(sd / "cut01.png", (t, t))
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers()
    V.add_parser(sub, nk, home.kit)
    args = ap.parse_args(["webview", "ep1"])
    args.func(args)
    assert (home.web / "index.html").exists() and os.listdir(home.out) == ["webtoon"]     # 쪽은 안 만듦
    args = ap.parse_args(["webview", "ep1", "--style", "soft"])
    args.func(args)
    web2 = home.ep / "out_soft" / "webtoon"
    assert (web2 / "index.html").exists()
    with Image.open(web2 / "img" / "cut01.jpg") as a, Image.open(home.web / "img" / "cut01.jpg") as b:
        ga, gb = a.convert("RGB").getpixel((60, 40)), b.convert("RGB").getpixel((60, 40))
    assert ga[1] > 180 and ga[0] < 60 and not (gb[1] > 180 and gb[0] < 60)      # --style 은 cuts_soft 의 그림


def test_webview_is_registered_under_nk_ep():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    W.add_parser(sub, nk, KIT)
    args = ap.parse_args(["ep", "webview", "ep1", "--style", "soft"])
    assert args.ep_cmd == "webview" and args.ep == "ep1" and args.style == "soft" and callable(args.func)
