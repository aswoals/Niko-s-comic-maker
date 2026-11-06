# -*- coding: utf-8 -*-
"""표지 (nk_cover): 제목 정리, 설정 합치기, 그림 없을 때 글자만 표지, 직접 넣은 art.png 안 덮어쓰기, page_00 끼우기, book.pdf 첫 쪽.
ComfyUI·GPU 없음: 그리기(자식 프로세스)는 _stream 을 바꿔 끼워서 흉내 냄"""
import argparse, io, json, os, re, types

import pytest
from PIL import Image

import nk
import nk_cover as C
import nk_plan

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WH = (300, 420)                                        # 시험용 작은 쪽 크기


def fake_nk():
    return types.SimpleNamespace(load_yaml=nk.load_yaml, load_presets=lambda: {"manga": {"width": WH[0], "ratio": WH[1] / WH[0]}})


def conti(**kw):
    c = {"title": "숲속 모험 — 첫째 날 (시험 v3)", "format": "page", "chars": {"hero": "testcat", "buddy": "testgoat"},
         "char": "hero", "artist": "",
         "world": {"locations": {"park": {"tags": "park, grass, blue sky, outdoors, day"}}},
         "cuts": [{"id": 1, "_charkey": "hero"}, {"id": 2, "_charkey": "buddy"},
                  {"id": 3, "cast": [{"char": "hero"}, {"char": "buddy"}]}, {"id": 4, "char": "none", "_charkey": None}]}
    c.update(kw)
    return c


@pytest.fixture
def home(tmp_path, monkeypatch):
    """NK_HOME = 임시 폴더 (episodes/ep1/out 에 흰 쪽 두 장). 키트 폴더 = 임시 kit (cover.yaml 없음 = 기본값)"""
    monkeypatch.setenv("NK_HOME", str(tmp_path / "home"))
    out = tmp_path / "home" / "episodes" / "ep1" / "out"
    out.mkdir(parents=True)
    for i in (1, 2):
        Image.new("RGB", WH, "white").save(out / ("page_%02d.png" % i))
    (tmp_path / "kit").mkdir()
    return types.SimpleNamespace(kit=str(tmp_path / "kit"), out=str(out), ep=tmp_path / "home" / "episodes" / "ep1")


def no_draw(*a, **k):
    raise AssertionError("그리면 안 되는데 그리기를 부름")


def fake_draw(color=(200, 30, 30), rc=0):
    """가짜 그리기: cover/_home/episodes/cv/cuts/cut01.png 를 만듦 (rc != 0 이면 안 만들고 실패 글만)"""
    calls = []

    def _s(cmd, env, cwd, timeout, log, prefix=""):
        calls.append(cmd)
        if rc:
            open(log, "w", encoding="utf-8").write("ComfyUI not running")
            return rc, "ComfyUI not running"
        d = os.path.join(env["NK_HOME"], "episodes", C.CV_EP, "cuts")
        os.makedirs(d, exist_ok=True)
        Image.new("RGB", (64, 96), color).save(os.path.join(d, "cut01.png"))
        return 0, "done"
    return _s, calls


def pdf_images(path):
    """book.pdf 안의 쪽 그림 (Pillow 는 RGB 쪽을 JPEG 로 넣음) -> 순서대로 PIL 그림. 새 패키지 없이 바이트에서 꺼냄"""
    raw = open(path, "rb").read()
    ims = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            ims.append(Image.open(io.BytesIO(m.group(1))).convert("RGB"))
        except Exception:
            pass
    return raw, ims


def mean(im):
    from PIL import ImageStat
    return ImageStat.Stat(im.convert("L")).mean[0]


# ------------------------------------------------------------------ 제목·설정
def test_split_title_strips_notes_and_splits_subtitle():
    assert C.split_title("숲속 모험 — 첫째 날 (시험 v3)") == ("숲속 모험", "첫째 날")
    assert C.split_title("바다 이야기 (초안) [메모]") == ("바다 이야기", "")
    assert C.split_title("우주 – 별 하나") == ("우주", "별 하나")
    assert C.split_title("X-Men 같은 제목") == ("X-Men 같은 제목", "")          # 띄어쓰기 없는 '-' 는 안 나눔
    assert C.split_title("(메모만)", "ep01") == ("ep01", "")                       # 다 빠지면 만화 이름
    assert C.split_title(None, "ep02") == ("ep02", "")


def test_config_merge_kit_then_episode(home, capsys):
    open(os.path.join(home.kit, "cover.yaml"), "w", encoding="utf-8").write(
        'author: "작가 - 가"\nvariant: 2\nshade: 0.3\nwhat: 1\n')
    (home.ep / "cover.yaml").write_text('author: "작가 - 나"\nenabled: "off"\n', encoding="utf-8")
    cfg = C.load_cfg(fake_nk(), home.kit, "ep1")
    assert cfg["author"] == "작가 - 나" and cfg["variant"] == 2 and cfg["shade"] == 0.3   # 만화 쪽이 우선, 나머지는 키트
    assert cfg["enabled"] is False and "what" not in cfg
    assert "모르는 칸" in capsys.readouterr().out
    (home.ep / "cover.yaml").write_text("enabled: true\nvariant: abc\n", encoding="utf-8")
    cfg = C.load_cfg(fake_nk(), home.kit, "ep1")
    assert cfg["enabled"] is True and cfg["variant"] == 0                               # 이상한 숫자는 0


def test_repo_cover_yaml_matches_defaults():
    y = nk.load_yaml(os.path.join(KIT, "cover.yaml"))
    assert set(y) <= set(C.DEFAULT), set(y) - set(C.DEFAULT)
    assert y["enabled"] is True and y["author"] == "" and C.DEFAULT["author"] == ""     # 작가 줄은 기본으로 비어 있음
    assert str(y["ai_notice"]).strip() and str(C.DEFAULT["ai_notice"]).strip()          # 'AI로 제작' 문구는 기본으로 켬


# ------------------------------------------------------------------ 표지 그림 계획
def test_pick_chars_and_plan_compiles_and_is_safe():
    c = conti()
    assert C.pick_chars(c, {"chars": []}) == [("hero", "testcat"), ("buddy", "testgoat")]   # 같은 횟수 -> 주인공이 앞
    assert C.pick_chars(c, {"chars": ["buddy"]}) == [("buddy", "testgoat")]
    solo = conti(chars={"hero": "testcat"}, cuts=[{"id": 1, "_charkey": "hero"}])
    p1 = C.build_plan(solo, dict(C.DEFAULT), "숲속 모험")
    assert p1["pages"][0]["cuts"][0]["who"] == ["hero"] and p1["locations"]["cover"].startswith("park")
    p2 = C.build_plan(c, dict(C.DEFAULT), "숲속 모험")
    cut = p2["pages"][0]["cuts"][0]
    assert cut["who"] == ["hero", "buddy"] and set(cut["roles"]) == {"hero", "buddy"}
    for t in (cut["action"], cut["scene"]) + tuple(cut["roles"].values()):            # 전연령 안전장치가 지울 말이 없음
        assert nk.safe_text(t) == t
    for p in (p1, p2):                                                                    # 공개판 계획표 컴파일러가 그대로 받음
        cc, _ = nk_plan.compile_plan(p)
        assert len(cc["pages"]) == 1 and len(cc["pages"][0]["cuts"]) == 1
    assert C.build_plan(conti(chars={}, char="none"), dict(C.DEFAULT), "x") is None


# ------------------------------------------------------------------ 그리기·캐시·직접 넣은 그림
def test_draw_once_then_cached_and_variant_redraws(home, monkeypatch):
    s, calls = fake_draw()
    monkeypatch.setattr(C, "_stream", s)
    ap = C.ensure_art(fake_nk(), home.kit, "ep1", conti())
    assert ap and os.path.exists(ap) and len(calls) == 1
    cmd = calls[0]
    assert cmd[-6:] == ["auto", C.CV_EP, "--from", "compile", "--to", "make"]
    rec = json.load(open(home.ep / "cover" / "art.json", encoding="utf-8"))
    assert rec["md5"] == C._md5(ap) and rec["source"] == "draw"
    assert C.ensure_art(fake_nk(), home.kit, "ep1", conti()) == ap and len(calls) == 1    # 두 번째는 안 그림
    (home.ep / "cover.yaml").write_text("variant: 1\n", encoding="utf-8")
    C.ensure_art(fake_nk(), home.kit, "ep1", conti())
    assert len(calls) == 2 and os.listdir(home.ep / "cover" / "_old")                     # 옛 그림은 _old 로 (안 지움)
    rs = json.load(open(home.ep / "cover" / "_home" / "episodes" / C.CV_EP / "reseed.json", encoding="utf-8"))
    assert rs == {"1": 1}                                                                 # 시드 + 1000 x variant


def test_user_art_is_never_overwritten(home, monkeypatch):
    cdir = home.ep / "cover"
    cdir.mkdir()
    Image.new("RGB", (50, 70), (0, 128, 255)).save(cdir / "art.png")
    before = C._md5(str(cdir / "art.png"))
    monkeypatch.setattr(C, "_stream", no_draw)
    for redo in (False, True):
        assert C.ensure_art(fake_nk(), home.kit, "ep1", conti(), redo=redo) == str(cdir / "art.png")
    assert C._md5(str(cdir / "art.png")) == before and not (cdir / "_old").exists()
    # 그린 그림 기록(art.json)이 있어도 그림이 바뀌었으면 (= 직접 바꿔 넣음) 그대로
    (cdir / "art.json").write_text(json.dumps({"stamp": "x", "md5": "다른 그림"}), encoding="utf-8")
    assert C.is_user_art(home.kit, "ep1")
    assert C.ensure_art(fake_nk(), home.kit, "ep1", conti(), redo=True) == str(cdir / "art.png")
    assert C._md5(str(cdir / "art.png")) == before


# ------------------------------------------------------------------ 글자만 표지 (그리기 실패)
def test_draw_failure_gives_text_only_cover_and_log(home, monkeypatch):
    s, calls = fake_draw(rc=1)
    monkeypatch.setattr(C, "_stream", s)
    page1 = C._md5(os.path.join(home.out, "page_01.png"))
    C.attach(fake_nk(), home.kit, "ep1", conti(), home.out, *WH)
    assert len(calls) == 1
    log = (home.ep / "cover" / "draw.log").read_text(encoding="utf-8")
    assert "ComfyUI not running" in log and "못 그림" in log
    assert os.path.exists(os.path.join(home.out, "page_00.png")) and (home.ep / "cover" / "cover.png").exists()
    assert not (home.ep / "cover" / "art.png").exists()
    assert C._md5(os.path.join(home.out, "page_01.png")) == page1                         # 페이지는 안 건드림


def test_attach_survives_errors_in_art_step(home, monkeypatch):
    def boom(*a, **k):
        raise SystemExit(1)
    monkeypatch.setattr(C, "ensure_art", boom)
    C.attach(fake_nk(), home.kit, "ep1", conti(), home.out, *WH)
    assert os.path.exists(os.path.join(home.out, "page_00.png"))
    assert "그림 단계 오류" in (home.ep / "cover" / "draw.log").read_text(encoding="utf-8")


def test_disabled_and_art_none(home, monkeypatch):
    monkeypatch.setattr(C, "_stream", no_draw)
    (home.ep / "cover.yaml").write_text("art: none\n", encoding="utf-8")
    assert C.ensure_art(fake_nk(), home.kit, "ep1", conti()) is None
    (home.ep / "cover.yaml").write_text("enabled: false\n", encoding="utf-8")
    assert C.attach(fake_nk(), home.kit, "ep1", conti(), home.out, *WH) is None
    assert not os.path.exists(os.path.join(home.out, "page_00.png"))


# ------------------------------------------------------------------ page_00 · book.pdf
def test_page00_inserted_and_pdf_first_page_is_cover(home):
    (home.ep / "cover.yaml").write_text('author: "작가 - 이름"\n', encoding="utf-8")
    cv = C.add_to_out(fake_nk(), home.kit, "ep1", conti(), home.out, *WH, None)
    with Image.open(os.path.join(home.out, "page_00.png")) as p0:      # 닫아 둬야 윈도우에서 다시 만들 때 바꿔 끼울 수 있음
        assert p0.size == WH and cv.size == WH
    raw, ims = pdf_images(os.path.join(home.out, "book.pdf"))
    assert len(re.findall(rb"/Type\s*/Page\b(?!s)", raw)) == 3                           # 표지 + 두 쪽
    assert len(ims) == 3 and ims[0].size == WH
    assert mean(ims[0]) < 128 and mean(ims[1]) > 240 and mean(ims[2]) > 240              # 첫 쪽 = 어두운 표지, 뒤 = 흰 쪽
    C.add_to_out(fake_nk(), home.kit, "ep1", conti(), home.out, *WH, None)               # 다시 해도 표지는 한 장
    raw, ims = pdf_images(os.path.join(home.out, "book.pdf"))
    assert len(ims) == 3


def test_cover_with_art_uses_picture(home):
    art = home.ep / "a.png"
    Image.new("RGB", (200, 300), (250, 250, 250)).save(art)
    cv = C.add_to_out(fake_nk(), home.kit, "ep1", conti(), None, *WH, str(art))
    assert cv.getpixel((WH[0] // 2, WH[1] // 2))[0] > 200                                 # 가운데 = 그림 (밝은 그림)
    assert not os.path.exists(os.path.join(home.out, "page_00.png"))                      # out 없이 = cover.png 만


def test_ep_cover_command_refreshes_only_cover(home, monkeypatch):
    (home.ep / "conti.yaml").write_text(
        "title: 시험\nformat: page\nchars: {hero: testcat}\nchar: hero\n"
        "pages:\n- page: 1\n  rows: [{h: 1.0, cuts: [1]}]\n  cuts: [{id: 1, scene: 'solo, smile'}]\n", encoding="utf-8")
    (home.ep / "cover.yaml").write_text("art: none\n", encoding="utf-8")
    monkeypatch.setattr(C, "_stream", no_draw)
    monkeypatch.setattr(nk, "load_presets", lambda: {"manga": {"width": WH[0], "ratio": WH[1] / WH[0]}})
    page1 = C._md5(os.path.join(home.out, "page_01.png"))
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers()
    C.add_parser(sub, nk, home.kit)
    args = ap.parse_args(["cover", "ep1", "--redo"])
    assert args.redo is True
    args.func(args)
    assert os.path.exists(os.path.join(home.out, "page_00.png"))
    assert len(pdf_images(os.path.join(home.out, "book.pdf"))[1]) == 3
    assert C._md5(os.path.join(home.out, "page_01.png")) == page1
