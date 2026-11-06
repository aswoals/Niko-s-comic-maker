# -*- coding: utf-8 -*-
"""nk_regionlora 틀 겹침 검사: 상대 찾는 말, 겹침 숫자, 상대 조각 고르기"""
import numpy as np
import nk_regionlora as R


def _box(x0, y0, x1, y1, n=100):
    a = np.zeros((n, n), bool)
    a[y0:y1, x0:x1] = True
    return a


def test_partner_words_from_tags():
    assert R.partner_words({"tags_short": "1boy, helmet"}) == ["boy", "person"]
    assert R.partner_words({"tags_short": "1girl"}) == ["girl", "person"]
    assert R.partner_words({"tags_short": "male, goat, caprine"}) == ["goat", "person"]
    assert R.partner_words({"tags_short": "furry, animal ears"}) == ["furry creature", "person"]
    assert R.partner_words({"sam_find": "robot boy", "tags_short": "1boy"}) == ["robot boy", "boy", "person"]


def test_overlap_stats():
    hero, part = _box(0, 0, 50, 100), _box(40, 0, 60, 100)
    st = R.overlap_stats(hero, part)
    assert st["cover"] == 0.2 and st["covered"] == 0.5 and st["iou"] == round(1000 / 6000, 4)
    assert R.overlap_stats(hero, np.zeros((100, 100), bool))["covered"] is None


def test_pick_partner_skips_lora_itself_and_flags_piggyback():
    hero = _box(0, 0, 50, 100)
    side_by_side = [_box(0, 0, 50, 100), _box(55, 0, 95, 100)]
    i, st = R.pick_partner(hero, side_by_side)
    assert i == 1 and st["covered"] == 0.0
    lora_big = _box(0, 0, 70, 100)
    i, st = R.pick_partner(lora_big, [_box(10, 20, 60, 90)])
    assert i == 0 and st["covered"] >= R.COVERED_WARN
    assert R.pick_partner(hero, [_box(0, 0, 50, 100)]) is None


def test_covered_warn_threshold_t20a():
    """m05 컷13 = 0.5339"""
    assert 1.0 >= R.COVERED_WARN > 0.5339


def test_mask_spans_left_lora_partner_right():
    sp = R.mask_spans(_box(10, 0, 40, 100), "hero", ["don"])
    assert sp["hero"][0] < 0.2 and 0.3 < sp["hero"][1] < 0.45 and sp["don"][1] == 1.0 and sp["don"][0] == sp["hero"][1]
    sp = R.mask_spans(_box(60, 0, 95, 100), "hero", ["don"])
    assert sp["don"][0] == 0.0 and sp["don"][1] == sp["hero"][0]
    sp = R.mask_spans(_box(0, 0, 100, 100), "hero", ["don"])
    assert sp["don"][1] - sp["don"][0] >= 0.19
    assert R.mask_spans(np.zeros((10, 10), bool), "hero", ["don"]) == {}
