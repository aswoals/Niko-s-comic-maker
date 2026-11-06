# -*- coding: utf-8 -*-
"""모든 자세가 그려지고, 땅 밑으로 안 들어가고, 뼈 길이가 그대로"""
import os
import sys

import numpy as np
import pytest

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(KIT, "tools"))
sys.path.insert(0, KIT)

from pose3d import library_human as LH  # noqa: E402
from pose3d import library_sheet as LS  # noqa: E402
from pose3d.__main__ import build  # noqa: E402
from pose3d.body import Doll, scaled_body  # noqa: E402
import nk_pose3d_auto as P  # noqa: E402

LH.install()
H = {"name": "testman", "height_cm": 180}
D = {"name": "testknight", "height_cm": 158}


@pytest.mark.parametrize("name", sorted(LH.LIB))
def test_library_pose_renders_and_passes_checks(name):
    """정면·위에서 그려지고, 점검(땅 밑·팔다리 못 닿음·닿을 곳 멂·두 사람 겹침)에 안 걸림"""
    s = LS.settings_for(name)
    for yaw, pitch in ((15, 6), (25, 50)):
        res = build(LS.pose_key(name), s, yaw, pitch, None, 35, 120, 150)
        assert res["depth"].max() > 0
    assert LS.check(name, res) == [], LS.check(name, res)


@pytest.mark.parametrize("name", sorted(LH.LIB))
def test_library_pose_keeps_bone_lengths(name):
    s = LS.settings_for(name)
    res = build(LS.pose_key(name), s, 15, 6, None, 35, 80, 100)
    for i, d in enumerate(res["dolls"]):
        fresh = Doll(scaled_body(s, "ab"[i]))
        for j in ("r_elbow", "r_wrist", "l_elbow", "l_wrist", "r_knee", "r_ankle", "l_knee", "l_ankle", "head"):
            assert abs(np.linalg.norm(d.pos[j] - d.pos[_parent(j)]) - np.linalg.norm(fresh.pos[j] - fresh.pos[_parent(j)])) < 1e-6


def _parent(j):
    from pose3d.body import PARENT
    return PARENT[j]


def test_library_entries_are_well_formed():
    assert len(LH.LIB) >= 2
    for name, e in LH.LIB.items():
        assert e["n"] in (1, 2) and e["tags"] and e["ko"] and callable(e["fn"])
        assert all(t == t.lower().strip() and t for t in e["tags"]), name
        if e["n"] == 1:
            assert e["base"] in (None, "stand", "sit_floor", "kneel", "squat", "lie_back", "lie_stomach", "run", "jump"), name


def test_match_rules():
    assert LH.match("solo, standing, hands on hips", 1) == "hands_on_hips" and LH.match("standing, hands on own hips", 1) == "hands_on_hips"
    assert LH.match("solo, lying, hands on hips", 1, base="lie_back") is None        # 바탕 자세가 다르면 안 골림
    assert LH.match("hands on hipsx", 1) is None                                       # 낱말 그대로만
    assert LH.match("princess carry, park", 2) == "L_princess_carry"[2:]
    assert LH.match("princess carry", 1) is None
    assert LH._has(" sitting, leaning back ", "sitting+leaning back") and not LH._has(" sitting ", "sitting+leaning back")


def test_plan_pose_uses_library():
    pp = P.plan_pose({"id": 1, "shot": "full", "angle": "eye", "scene": "solo, standing, hands on hips", "_char": H})
    assert pp[0] == "s_hands_on_hips"
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "eye", "scene": "solo, lying, hands on hips", "_char": H})[0] == "s_lie_back"
    duo = lambda p1, p2, sc: {"id": 4, "shot": "full", "angle": "eye", "scene": sc, "_roles": [({"pos": p1}, H), ({"pos": p2}, D)]}
    pp = P.plan_pose(duo("smile", "carrying", "princess carry, park"))
    assert pp[0] == "L_princess_carry" and pp[1] is D and pp[2] is H                  # 'carrying' 이 붙은 사람이 안는 쪽 (a)
    assert P.plan_pose(duo("hands on hips", "kneeling", "grass"))[0] == "p_hands_on_hips_kneel"
    assert P._arms_for("p_hands_on_hips_kneel") == (True, False)
    assert P._arms_for("s_run") == (False, False) and P._arms_for("hug_h") == (True, True)
    assert P._split_pair("p_sit_floor_lie_back") == ("sit_floor", "lie_back")
    assert P.plan_pose(duo("smile", "smile", "hug from behind, park"))[0] == "L_hug_from_behind"     # 'hug' 글자 포함으로 옛 안기에 가지 않음
    assert P.plan_pose(duo("standing", "arm hug, smile", "arm hug, walking"))[0] == "L_arm_hug"
    assert P.plan_pose(duo("smile", "smile", "hug, park"))[0] == "hug_h"
    pp = P.plan_pose(duo("walking, sleepy", "walking, arm hug, smile", "arm hug, walking"))
    assert pp[0] == "L_arm_hug" and pp[2] is D and pp[1] is H and pp[3] is False      # 바꾸지 않음 = 뒤집지 않음
    pp = P.plan_pose(duo("walking, arm hug, smile", "walking, sleepy", "arm hug, walking"))     # 오른쪽(H)이 껴안음 -> b 자리로 바꿈 -> 좌우 뒤집기
    assert pp[2] is H and pp[1] is D and pp[3] is True
    pp = P.plan_pose(duo("closed eyes, happy", "standing, headpat", "headpat"))                  # 쓰다듬는 사람(D) = a
    assert pp[0] == "L_headpat" and pp[1] is D


def test_depth_for_library_pose_keeps_arms(tmp_path, monkeypatch):
    import nk_webtoon as W
    from PIL import Image
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    out = P.depth_for(".", "ep", {"id": 2, "shot": "full", "angle": "eye", "scene": "solo, standing, hands on hips", "_char": H}, 200, 260)
    assert Image.open(out).size == (200, 260)
