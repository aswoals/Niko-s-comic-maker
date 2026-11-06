# -*- coding: utf-8 -*-
"""글자·효과 v2: 손글씨 효과음, 외침·속삭임 풍선, 사람 피하는 효과선"""
from PIL import Image, ImageDraw
import nk_letter2 as L2
import nk_webtoon as W


def page_st():
    P = Image.new("RGB", (800, 800), "white")
    st = {"_occupied": [], "_heads": [], "_people": Image.new("L", (800, 800), 0),
          "_edges": Image.new("L", (800, 800), 0), "v2": True}
    return P, st


def test_sfx_style_not_all_hard():
    assert L2.sfx_style("첨벙첨벙!") != "hard"        # '!' 만으로 굵은 글꼴이 되지 않음 (lt01 첫 판: 전부 hard)
    assert L2.sfx_style("미끄윽!") != "hard"
    assert L2.sfx_style("쾅!") == "hard"


def test_sfx_auto_size_fits_panel():
    P, st = page_st()
    L2.draw_sfx(P, {"type": "sfx", "text": "첨벙첨벙!"}, (0, 0, 700, 700), st, 0)
    x, y, w, h = st["_occupied"][-1]
    assert w <= 700 * 0.6 and h <= 700 * 0.6, (w, h)       # 자동 크기 = 글줄이 칸 폭의 약 40% (흰 테두리·기울기·글자 흔들기로 조금 넘음)


def test_mask_people_clears_lines_on_people():
    PM = Image.new("L", (400, 400), 0)
    ImageDraw.Draw(PM).rectangle([150, 0, 250, 400], fill=255)
    Lr = Image.new("RGBA", (400, 400), (0, 0, 0, 200))
    out = L2.mask_people(Lr, (0, 0, 400, 400), PM)
    a = out.getchannel("A")
    assert a.getpixel((200, 200)) == 0 and a.getpixel((20, 200)) == 200
    assert L2.mask_people(Lr, (0, 0, 400, 400), None) is Lr     # 마스크 없으면 그대로


def test_bubble_kind_and_v1_fallback():
    assert L2.bubble_kind({"type": "speech", "text": "가라!!"}) == "shout"
    assert L2.bubble_kind({"type": "whisper", "text": "쉿"}) == "whisper"
    P, st = page_st()
    st["v2"] = False
    st.update(W._page_style({}) if hasattr(W, "_page_style") else {})
    d = ImageDraw.Draw(P)
    W._draw_item(P, d, {"type": "shout", "text": "와!"}, (0, 0, 700, 700), dict(st, v2=False), 0)    # v1 은 보통 말풍선으로 (오류 없이)


def test_missing_glyph_is_replaced():
    """gl01v 첫 판: BlackHanSans 에 '…' 가 없어 외침 풍선이 비어 보임 -> '...' 로"""
    from PIL import ImageFont
    f = ImageFont.truetype(L2.font_path("hard"), 40)
    assert L2.fit_text("가위바위…!", f) == "가위바위...!"
    b = ImageFont.truetype(L2.font_path("brush"), 40)            # EastSeaDokdo 에는 있음 -> 그대로
    assert L2.fit_text("맴맴…", b) == "맴맴…"


def test_shout_bubble_stays_in_panel():
    P, st = page_st()
    st.update({"font_size": 30, "line": 3, "bubble_ratio": 0.42, "font": None})
    d = ImageDraw.Draw(P)
    L2.draw_bubble(P, d, {"type": "shout", "text": "가위바위…!"}, (100, 100, 600, 600), st, 0, "shout")
    x, y, w, h = st["_occupied"][-1]
    assert x >= 100 and y >= 100 and x + w <= 700 and y + h <= 700, (x, y, w, h)


def test_face_center_protects_closeup_face():
    """gl02 컷 8: 얼굴 극근접은 뼈대가 얼굴을 못 찾아 집중선·효과음이 얼굴을 덮음 -> 칸 가운데를 사람으로"""
    PM = Image.new("L", (800, 800), 0)
    L2.face_center(PM, (100, 100, 700, 700))
    assert PM.getpixel((400, 400)) == 255 and PM.getpixel((110, 110)) == 0      # 가운데만, 모서리는 비움
    Lr = Image.new("RGBA", (600, 600), (0, 0, 0, 200))
    out = L2.mask_people(Lr, (100, 100, 700, 700), PM).getchannel("A")
    assert out.getpixel((300, 300)) == 0 and out.getpixel((5, 5)) == 200


def test_animeseg_mask_shape():
    """있으면 같은 크기 L 마스크, 없으면 None (조립은 계속)"""
    import nk_animeseg as S
    if not S.available():
        assert S.cached_mask(".", 1, __file__) is None
        return
    im = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(im).ellipse([100, 40, 200, 190], fill=(30, 30, 30))
    m = S.mask(im)
    assert m.size == (300, 200) and m.mode == "L"


def test_pop_out_pastes_character_above_border(monkeypatch, tmp_path):
    import nk_animeseg
    P = Image.new("RGB", (400, 400), "white")
    E = Image.new("RGB", (200, 240), (200, 0, 0))                      # 위로 40 더 잘라 둔 그림 (빨강)
    m = Image.new("L", (200, 240), 0)
    ImageDraw.Draw(m).rectangle([80, 0, 120, 239], fill=255)            # 가운데 기둥만 캐릭터
    monkeypatch.setattr(nk_animeseg, "cached_mask", lambda d, cid, f: m)
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    ct = {"id": 1, "rect": [100, 100, 300, 300], "_pop": (E, 40, "x.png", (200, 240))}
    W._pop_out(P, ".", "ep", ct, 4)
    assert P.getpixel((200, 70)) == (200, 0, 0)        # 캐릭터 = 테두리 위로 나옴
    assert P.getpixel((120, 70)) == (255, 255, 255)    # 캐릭터 아닌 곳 = 그대로
    assert "_pop" not in ct


def test_color_match_pulls_saturation_to_median():
    """배율은 한계 안"""
    m = Image.new("L", (100, 100), 255)
    vivid = Image.new("RGB", (100, 100), (250, 200, 0))
    dull = Image.new("RGB", (100, 100), (150, 140, 120))
    sv, sd_ = L2.char_stats(vivid, m), L2.char_stats(dull, m)
    tgt = L2.color_targets([sv, sd_, ((sv[0] + sd_[0]) / 2, (sv[1] + sd_[1]) / 2)])
    a = L2.char_stats(L2.match_color(vivid, sv, tgt), m)
    b = L2.char_stats(L2.match_color(dull, sd_, tgt), m)
    assert a[0] < sv[0] and b[0] > sd_[0]
    assert abs(a[1] - sv[1]) < 2 and abs(b[1] - sd_[1]) < 2          # 밝기는 그대로
    assert L2.match_color(vivid, None, tgt) is vivid
