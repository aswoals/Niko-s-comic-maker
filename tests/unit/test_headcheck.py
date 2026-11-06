# -*- coding: utf-8 -*-
"""nk_headcheck: 컷마다 기대 머리 수, 흠 표시"""
import nk_headcheck as H


def test_expected_heads():
    duo = {"_roles": [({"char": "a", "pos": "smile"}, {}), ({"char": "b", "pos": ""}, {})], "scene": "duo", "_char": {}}
    assert H.expected_heads(duo)[0] == 2
    assert H.expected_heads({"scene": "solo, smile", "_char": {}})[0] == 1
    assert H.expected_heads({"scene": "tree, leaf", "_char": None})[0] == 0
    assert H.expected_heads({"scene": "solo, snowman", "_char": {}})[0] == 3          # 눈사람 = 머리 2개까지 봐 줌


def test_flag_of():
    assert H.flag_of(2, 1).startswith("머리 많음")
    assert H.flag_of(1, 1) is None and H.flag_of(0, 0) is None and H.flag_of(3, 0) is None     # 사람 없는 컷은 안 봄
    assert H.flag_of(0, 1).startswith("머리 없음") and H.flag_of(None, 1) == "SAM 실패"


def test_count_heads_relative_t28():
    """귀·장식 조각 (0.11~0.34) 은 안 셈"""
    assert H.count_heads([0.2646, 0.2566]) == 2
    assert H.count_heads([0.4018, 0.0732]) == 1
    assert H.count_heads([0.1192, 0.0801, 0.0405]) == 2
    assert H.count_heads([]) == 0
