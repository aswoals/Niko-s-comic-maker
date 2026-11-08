# -*- coding: utf-8 -*-
"""말풍선 배치: 한국식(왼→오) 읽기, 글자끼리 겹침 피하기, 작은 칸 글씨 조절, 같은 사람 대사 합치기, 캐릭터별 말풍선 색"""
from PIL import Image, ImageDraw
import nk_webtoon as W


def page_st(n_text=1, w=800, h=800):
    st = {"_occupied": [], "_heads": [], "_people": Image.new("L", (w, h), 0),
          "_edges": Image.new("L", (w, h), 0), "width": w, "height": h,
          "_cut": {"id": 1, "page": 1, "text": [{"type": "speech", "text": "x"}] * n_text}}
    return ImageDraw.Draw(Image.new("RGB", (w, h), "white")), st


def test_wrap_keeps_punctuation_on_previous_line():
    d, _ = page_st()
    font = W._font("", 30)
    for maxw in range(60, 260, 10):                     # 마침표·물음표만 다음 줄로 넘어가면 안 됨 ('뿐인걸요' / '.')
        lines = W._wrap(d, "소리의 반복일 뿐인걸요.", font, maxw)
        assert all(not l or l[0] not in W.WRAP_PUNCT for l in lines[1:]), lines


def test_mirror_for_left_to_right():
    assert W.MIRROR["tr"] == "tl" and W.MIRROR["bl"] == "br" and W.MIRROR["right"] == "left"


def test_text_boxes_do_not_overlap_when_there_is_room():
    d, st = page_st(n_text=2)
    a = W._smart_at(300, 120, (0, 0, 800, 800), "tl", st)
    b = W._smart_at(300, 120, (0, 0, 800, 800), "tl", st)
    (ax, ay), (bx, by) = a, b
    assert bx >= ax + 300 or ax >= bx + 300 or by >= ay + 120 or ay >= by + 120, (a, b)


def test_second_line_is_not_placed_before_the_first_ltr():
    d, st = page_st(n_text=2)
    st["_ltr"] = True
    st["_text_kn"] = (0, 2)
    a = W._smart_at(300, 120, (0, 0, 800, 800), "tl", st)
    st["_text_kn"] = (1, 2)
    b = W._smart_at(300, 120, (0, 0, 800, 800), "tl", st)   # 같은 자리를 원해도 뒤 대사는 아래쪽이나 오른쪽
    assert b[1] >= a[1] + 120 or (abs(b[1] - a[1]) < 120 and b[0] > a[0]), (a, b)


def test_fit_text_small_panel_uses_fewer_lines():
    d, st = page_st(n_text=2)
    text = "어머, 그것은 애교가 아니라 소리의 반복일 뿐인걸요."
    of = lambda s: W._font("", s)
    big = W._fit_text(d, text, (0, 0, 1400, 1400), st, 30, 0.3, of)
    small = W._fit_text(d, text, (0, 0, 360, 360), st, 30, 0.3, of)
    assert big[1] == 30                                  # 큰 칸은 그대로
    assert len(small[3]) <= 3 or small[1] < 30           # 작은 칸은 폭을 넓히거나 글씨를 줄여서 4줄 이상을 피함


def test_merge_same_speaker_only_in_small_panels():
    items = [{"type": "speech", "who": "a", "text": "하나"}, {"type": "speech", "who": "a", "text": "둘"},
             {"type": "speech", "who": "b", "text": "셋"}, {"type": "sfx", "text": "쾅"}]
    assert len(W._merge_same_speaker(items, False)) == 4
    m = W._merge_same_speaker(items, True)
    assert [x["text"] for x in m] == ["하나\n둘", "셋", "쾅"]


def test_ellipse_exit_is_on_the_border():
    x, y = W._ellipse_exit((50, 50), (200, 50), 50, 50, 40, 20)
    assert abs(x - 90) < 1e-6 and abs(y - 50) < 1e-6
    assert W._ellipse_exit((200, 50), (300, 50), 50, 50, 40, 20) == (200, 50)   # 이미 밖이면 그대로


def test_tail_reaches_toward_far_speaker():
    assert W._tail_len(48, 30, 120, 200, 80, True) == 48          # 가까우면 기본 길이
    assert W._tail_len(48, 30, 600, 200, 80, True) > 48           # 멀면 더 길게 (글자 4.5개 높이까지)
    assert W._tail_len(48, 30, 600, 200, 80, False) == 48         # 화면 밖 대사는 그대로


def test_bubble_colors_modes():
    st = {"_castmap": {"a": {"bubble": {"fill": "#FFF0F5", "line": "#D9578A"}}}, "_bubble_mode": "all"}
    assert W._bubble_colors({"who": "a"}, st) == ("#FFF0F5", "#D9578A")
    assert W._bubble_colors({"who": "b"}, st) == ("white", "black")          # 색이 없는 캐릭터
    st["_bubble_mode"], st["_offscreen"] = "offscreen", False
    assert W._bubble_colors({"who": "a"}, st) == ("white", "black")
    st["_offscreen"] = True
    assert W._bubble_colors({"who": "a"}, st) == ("#FFF0F5", "#D9578A")
    st["_bubble_mode"] = "off"
    assert W._bubble_colors({"who": "a"}, st) == ("white", "black")
