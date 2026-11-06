# -*- coding: utf-8 -*-
import os
import nk_pose3d_auto as P

HEATH = {"name": "testman", "height_cm": 180}
DON = {"name": "testknight", "height_cm": 158}


def duo(pos1, pos2, scene, shot="full", angle="eye"):
    return {"id": 4, "shot": shot, "angle": angle, "scene": scene,
            "_roles": [({"char": "man", "side": "right", "pos": pos1}, HEATH), ({"char": "don", "side": "left", "pos": pos2}, DON)]}


def test_plan_pose_mapping():
    """동작 태그 -> 혼자 자세, 가까운 구도는 잘라 씀"""
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "high", "scene": "solo, sitting, park bench", "_char": HEATH})[0] == "sit_bench"
    assert P.plan_pose({"id": 2, "shot": "full", "angle": "eye", "scene": "solo, standing, smile", "_char": DON})[0] == "stand_single"
    assert P.plan_pose({"id": 3, "shot": "waist", "angle": "side", "scene": "solo, smile", "_char": HEATH})[0] == "stand_single"
    assert P.plan_pose({"id": 3, "shot": "full", "angle": "side", "scene": "solo, running", "_char": HEATH})[0] == "s_run"
    assert P.plan_pose({"id": 3, "shot": "full", "angle": "eye", "scene": "solo, lying, on stomach, reading", "_char": HEATH})[0] == "s_lie_stomach"
    assert P.plan_pose({"id": 3, "shot": "eyes", "angle": "eye", "scene": "solo, shocked", "anima_act": "sweat running down", "_char": HEATH}) is None
    assert P.plan_pose({"id": 3, "shot": "hands", "angle": "eye", "scene": "solo, holding food", "_char": HEATH}) is None
    pp = P.plan_pose(duo("standing, hands in pockets", "sitting, smile", "park bench"))
    assert pp[0] == "stand_sit" and pp[1] is HEATH and pp[2] is DON and pp[3] is False
    pp = P.plan_pose(duo("sitting", "standing", "park bench"))
    assert pp[0] == "stand_sit" and pp[1] is DON and pp[3] is True
    assert P.plan_pose(duo("eating", "smile", "sitting, park bench, eating"))[0] == "sit_pair"
    assert P.plan_pose(duo("standing", "standing", "grass"))[0] == "stand_pair"
    assert P.plan_pose(duo("standing, looking down", "standing, looking up", "facing another, grass"))[0] == "face_pair"
    assert P.plan_pose(duo("lying, sleeping", "lying, smile", "on bed"))[0] == "p_lie_back_lie_back"
    assert P.plan_pose(duo("squatting, pointing", "kneeling", "grass"))[0] == "p_squat_kneel"
    assert P.plan_pose(duo("carrying", "sleepy", "piggyback"))[0] == "piggyback_h"


def test_depth_for_writes_cut_size(tmp_path, monkeypatch):
    import nk_webtoon as W
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    out = P.depth_for(".", "ep", duo("standing", "sitting", "park bench"), 320, 200)
    from PIL import Image
    im = Image.open(out)
    assert im.size == (320, 200) and os.path.basename(out) == "cut04_depth3d.png"
    assert Image.open(out.replace("_depth3d.png", "_line3d.png")).size == (320, 200)      # 인형 선화도
    assert os.path.exists(out.replace("_depth3d.png", "_mask_a.png")) and os.path.exists(out.replace("_depth3d.png", "_mask_b.png"))   # 사람별 틀
    c = dict(duo("lying", "lying", "on bed"), shot="knee")
    out2 = P.depth_for(".", "ep", c, 320, 200)                                        # 가까운 구도 = 잘라 씀 (크기는 컷 그대로)
    assert Image.open(out2).size == (320, 200)


def test_faceless_person_has_no_doll_head(tmp_path, monkeypatch):
    """얼굴이 칸 밖인 사람(roles pos 'head out of frame') = 인형 머리·목 없이, 목 자리에서 위로 기둥 (깊이에 머리가 보이면 얼굴이 그려짐)"""
    import sys
    import nk_webtoon as W
    sys.path.insert(0, os.path.join(P.KIT, "tools"))
    from pose3d import render as R
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    c = duo("standing, head out of frame", "standing, smile", "grass", shot="knee")
    assert P._faceless_of(c, HEATH) and not P._faceless_of(c, DON)
    out = P.depth_for(".", "ep", c, 320, 200)
    from PIL import Image
    assert Image.open(out).size == (320, 200)
    dolls = P.depth_for.last_res["res"]["dolls"]
    flags = [bool(d.b.get("no_head")) for d in dolls]
    assert sorted(flags) == [False, True]
    for d in dolls:
        names = [p[1] for p in R.doll_parts(d)]
        if d.b.get("no_head"):
            assert "head" not in names and "neck" not in names and "neck_up" in names and d.b.get("neck_up_len")
        else:
            assert "head" in names and "neck_up" not in names
    solo = {"id": 5, "shot": "full", "angle": "eye", "scene": "solo, standing, face out of frame", "_char": HEATH}
    assert P._faceless_of(solo, HEATH)
    P.depth_for(".", "ep", solo, 200, 320)
    assert all(d.b.get("no_head") for d in P.depth_for.last_res["res"]["dolls"])
