# -*- coding: utf-8 -*-
import os
import sys

import numpy as np

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(KIT, "tools"))
sys.path.insert(0, KIT)

from pose3d import lift2d as L  # noqa: E402
from pose3d.body import Doll, load_settings, scaled_body  # noqa: E402
import nk_pose3d_auto as P  # noqa: E402

S = load_settings(os.path.join(KIT, "tools", "pose3d", "settings_human.yaml"))
COCO = {L.NOSE: "head", L.LSH: "l_shoulder", L.RSH: "r_shoulder", L.LEL: "l_elbow", L.REL: "r_elbow", L.LWR: "l_wrist", L.RWR: "r_wrist",
        L.LHIP: "l_hip", L.RHIP: "r_hip", L.LKN: "l_knee", L.RKN: "r_knee", L.LAN: "l_ankle", L.RAN: "r_ankle"}


def body(scale=1.0):
    s = dict(S)
    s["people"] = {"a": {"scale": scale, "shape": {"no_arms": False}}}
    return scaled_body(s, "a")


def project(d, cam):
    """인형 관절 -> COCO 17점 2D (코는 머리 앞쪽, 눈은 코 옆)"""
    kp = np.zeros((17, 2)); conf = np.zeros(17)
    for i, j in COCO.items():
        p = d.pos[j] + (d.frame["head"] @ np.array([0, 0, d.b["head_rz"]]) if j == "head" else 0)
        kp[i] = cam.project(p[None])[0][0]; conf[i] = 0.9
    for i, dx in ((L.LEYE, 0.03), (L.REYE, -0.03)):
        kp[i] = cam.project((d.pos["head"] + d.frame["head"] @ np.array([dx, 0.02, d.b["head_rz"] * 0.9]))[None])[0][0]; conf[i] = 0.9
    return kp, conf


def test_lift_recovers_known_pose_in_2d():
    """알고 있는 인형(한 손 들고 한 무릎 굽힘)을 정면에서 찍은 2D 뼈대 -> 다시 세운 인형의 손목·발목·무릎이 같은 2D 자리 (뼈 길이가 같으니)"""
    b = body()
    d = Doll(b, "a")
    d.set_root([0, 0.5, 0], yaw=20)
    d.solve_limb("r_arm", d.pos["r_shoulder"] + np.array([-0.1, 0.25, 0.05]), np.array([0, 0, -1.0]))
    d.solve_limb("l_leg", d.pos["l_hip"] + np.array([0.05, -0.3, 0.15]), np.array([0, 0, 1.0]))
    W, H, s = 400, 500, 300.0
    cam = L.camera_for(W, H, s)
    kp, conf = project(d, cam)
    dolls, cam2 = L.lift([(kp, conf)], [b], W, H, anchor=False)
    assert dolls and len(dolls) == 1
    kp2, _ = project(dolls[0], cam2)
    for i in (L.LWR, L.RWR, L.LKN, L.RKN, L.LAN, L.RAN, L.LEL, L.REL):
        assert np.linalg.norm(kp2[i] - kp[i]) < 18, (i, kp[i], kp2[i])     # 18px 안 (어깨 위치 어림 차이)
    assert dolls[0].facing()[2] > 0                                              # 카메라 쪽을 봄


def test_lift_fixes_wrong_proportions_and_heights():
    """그림이 b 를 아이처럼 작게(키 0.7) 그렸어도, 인형 키 배율(0.91)로 세우면 b 가 커짐"""
    a_b, b_b = body(1.0), body(0.91)
    W, H, s = 600, 500, 300.0
    cam = L.camera_for(W, H, s)
    da = Doll(body(1.0)); da.set_root([0.3, 0.45, 0])
    db = Doll(body(0.7)); db.set_root([-0.3, 0.45 * 0.7, 0])
    pa, pb = project(da, cam), project(db, cam)
    dolls, cam2 = L.lift([pa, pb], [a_b, b_b], W, H)
    ha = dolls[0].pos["head"][1] - min(dolls[0].pos["l_ankle"][1], dolls[0].pos["r_ankle"][1])
    hb = dolls[1].pos["head"][1] - min(dolls[1].pos["l_ankle"][1], dolls[1].pos["r_ankle"][1])
    assert 0.86 < hb / ha < 0.96


def test_face_hint_turns_body_away():
    b = body()
    d = Doll(b); d.set_root([0, 0.5, 0])
    W, H, s = 300, 400, 250.0
    kp, conf = project(d, L.camera_for(W, H, s))
    dolls, _ = L.lift([(kp, conf)], [b], W, H, face_hint=-1)
    assert dolls[0].facing()[2] < 0


def test_plan_pose_unknown_goes_to_draft():
    H_ = {"name": "h", "height_cm": 160}
    D_ = {"name": "d", "height_cm": 157}
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "eye", "scene": "solo, handstand", "_char": H_})[0] == "dw"
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "eye", "scene": "solo, flying, arms up", "_char": H_})[0] == "dw"   # 'flying' 은 눕기가 아님
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "eye", "scene": "solo, jumping, midair", "_char": H_})[0] == "s_jump"  # 아는 바탕 자세가 먼저
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "low", "scene": "solo, kicking, high kick", "_char": H_})[0] == "s_kicking"   # 도서관 먼저
    assert P.plan_pose({"id": 1, "shot": "full", "angle": "low", "scene": "solo, all fours, crawling", "_char": H_})[0] == "s_all_fours"
    duo = lambda p1, p2, sc: {"id": 4, "shot": "full", "angle": "eye", "scene": sc, "_roles": [({"pos": p1}, H_), ({"pos": p2}, D_)]}
    assert P.plan_pose(duo("bent over", "standing", "park"))[0] == "dw"
    assert P.plan_pose(duo("smile", "smile", "hug, floating"))[0] == "hug_h"


def test_depth_from_draft_writes_files(tmp_path, monkeypatch):
    """먼저 그린 그림 -> (가짜 DWPose) -> 깊이·선화·사람별 틀이 컷 크기로"""
    import nk_webtoon as W
    import nk_pose
    from PIL import Image
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    b = body()
    d = Doll(b); d.set_root([0, 0.4, 0])
    kp, conf = project(d, L.camera_for(320, 400, 300.0))
    monkeypatch.setattr(nk_pose, "pose_one", lambda img, box: (kp, conf))
    monkeypatch.setattr(P, "_draft_boxes", lambda img, n: [(0, 0, 320, 400)] * n)
    draft = str(tmp_path / "draft.png")
    Image.new("RGB", (320, 400), "white").save(draft)
    cut = {"id": 3, "shot": "full", "angle": "eye", "scene": "solo, handstand", "_char": {"name": "h", "height_cm": 160}}
    out = P.depth_from_draft(".", "ep", cut, 320, 400, draft)
    assert out and Image.open(out).size == (320, 400)
    assert Image.open(out.replace("_depth3d.png", "_line3d.png")).size == (320, 400)
    assert os.path.exists(out.replace("_depth3d.png", "_mask_a.png"))
