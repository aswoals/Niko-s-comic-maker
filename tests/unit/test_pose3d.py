# -*- coding: utf-8 -*-
"""tools/pose3d (3D 인형 조종 그림 시제품, 클라우드 작업 8) 시험 — GPU·ComfyUI 없음.
보는 것: 한 픽셀 = 한 사람(틀이 안 겹침), 카메라를 돌리면 좌우가 바뀜
가까울수록 밝은 깊이, 뼈 길이 불변(FK/IK), 자세 틀마다 닿는 곳, 출력 파일 모양, nk_pose 와 같은 OpenPose 색."""
import json
import os
import sys

import numpy as np
import pytest

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(KIT, "tools"))      # 'pose3d' 로 가져옴 (다른 tools 패키지와 안 겹치게)

from pose3d import render as R  # noqa: E402
from pose3d.__main__ import build, main  # noqa: E402
from pose3d.body import DEFAULT_BODY, OP_NAMES, Doll, load_settings, scaled_body, standing_pelvis_height  # noqa: E402
from pose3d.poses import EXAMPLE_CAMERAS, EXAMPLE_POSES, POSES as _ALL_POSES, contact_report, make  # noqa: E402
from pose3d import poses_human as PH  # noqa: E402
POSES = {k: v for k, v in _ALL_POSES.items() if k not in PH.POSES}

OP = {n: i for i, n in enumerate(OP_NAMES)}


@pytest.fixture(scope="module")
def S():
    return load_settings()


def _standing(S, who="a", x=0.0, z=0.0, yaw=0.0, scale=None):
    b = scaled_body(S, who)
    if scale:
        b = {k: v * scale for k, v in b.items()}
    d = Doll(b, who)
    d.set_root([x, standing_pelvis_height(b), z], yaw=yaw)
    return d


def _shoot(dolls, yaw, pitch, W=160, H=200, dist=None):
    cam = R.auto_camera(dolls, yaw, pitch, 35.0, W, H, dist=dist)
    rr = R.render(dolls, cam)
    return cam, rr, R.keypoints_2d(dolls, cam, rr["parts"])


# ------------------------------------------------------------------ 설정·뼈대
def test_settings_file_has_all_body_keys(S):
    assert set(S["body"]) == set(DEFAULT_BODY)
    assert all(isinstance(v, float) for v in S["body"].values())
    assert len(S["image"]["person_colors"]) >= 2


@pytest.mark.parametrize("pose", sorted(POSES))
def test_bone_lengths_never_change(S, pose):
    """IK 로 자세를 잡아도 뼈 길이는 체형 설정 그대로 (FK 로 위치를 다시 계산하므로)"""
    dolls, _ = make(pose, S)
    for d in dolls:
        rest = Doll(d.b)
        for j, L in d.bone_lengths().items():
            assert abs(L - rest.bone_lengths()[j]) < 1e-9, (pose, d.name, j)


def test_ik_reaches_and_clamps(S):
    d = _standing(S)
    sh = d.pos["r_shoulder"]
    reach = d.b["upper_arm"] + d.b["forearm"]
    tgt = sh + np.array([0.0, 0.05, 0.6 * reach])
    assert d.solve_limb("r_arm", tgt) < 1e-9                   # 닿는 곳은 정확히
    far = sh + np.array([0.0, 0.0, 2.0 * reach])
    err = d.solve_limb("r_arm", far)                            # 못 닿으면 쭉 뻗은 만큼만
    assert err == pytest.approx(2.0 * reach - reach, abs=1e-3)
    assert d.reach_err["r_arm"] == err


@pytest.mark.parametrize("pose", sorted(POSES))
def test_every_template_keeps_its_contacts(S, pose):
    dolls, contacts = make(pose, S)
    rep = contact_report(dolls, contacts)
    assert rep and all(ok for _, _, _, ok in rep), rep
    for d in dolls:
        assert all(e < 0.01 for e in d.reach_err.values()), (pose, d.name, d.reach_err)


# ------------------------------------------------------------------ 한 픽셀 = 한 사람
@pytest.mark.parametrize("pose", sorted(POSES))
def test_masks_never_overlap_and_cover_bodies(S, pose):
    dolls, _ = make(pose, S)
    for _, yaw, pitch in EXAMPLE_CAMERAS[pose]:
        cam, rr, _ = _shoot(dolls, yaw, pitch)
        masks = R.person_masks(rr, 2)
        stack = np.stack([m > 0 for m in masks])
        assert stack.sum(0).max() <= 1                          # 겹치는 픽셀 0
        assert np.array_equal(stack.any(0), rr["who"] >= 0)     # 몸이 있는 픽셀은 모두 누군가의 것
        for i in range(2):
            assert stack[i].sum() > 150, (pose, yaw, pitch, i)  # 두 사람 다 보임


# ------------------------------------------------------------------ 가려짐
def test_person_in_front_hides_person_behind(S):
    a = _standing(S, "a", z=0.0)
    b = _standing(S, "b", z=-0.6)                               # 카메라(정면) 쪽에서 a 뒤에 b
    cam, rr, kps = _shoot([a, b], yaw=0, pitch=0, dist=4.0)
    va, vb = kps[0][1], kps[1][1]
    for n in ("neck", "r_hip", "l_hip", "nose", "r_knee"):
        assert va[OP[n]] == 1, n
        assert vb[OP[n]] == 0, n
    # 틀: a 몸통 가운데 픽셀은 a
    uv, _ = cam.project(((a.pos["pelvis"] + a.pos["chest"]) / 2)[None])
    x, y = int(uv[0, 0]), int(uv[0, 1])
    assert rr["who"][y, x] == 0


def test_own_head_hides_face_from_behind(S):
    d = _standing(S)
    _, _, front = _shoot([d], yaw=0, pitch=0)
    _, _, back = _shoot([d], yaw=180, pitch=0)
    for n in ("nose", "r_eye", "l_eye"):
        assert front[0][1][OP[n]] == 1, n
        assert back[0][1][OP[n]] == 0, n
    assert back[0][1][OP["neck"]] == 1                        # 목·어깨는 뒤에서도 보임
    assert back[0][1][OP["r_shoulder"]] == 1


def test_torso_thickness_rule_both_ways(S):
    """몸통 두께 허용치가 너무 크지도(옆모습 먼 어깨가 보인다고 함) 작지도(정면 엉덩이가 가려졌다고 함) 않은지.
    팔·목을 아주 가늘게 해서 몸통만 가리게 함 (보통 인형은 옆모습에서 가까운 팔이 먼저 가려서 몸통 규칙을 못 봄)"""
    d = _standing(S)
    d.b.update(arm_r=0.002, paw_r=0.002)
    _, _, side = _shoot([d], yaw=90, pitch=10, dist=3.0)        # +x = 인형의 왼쪽에서, 살짝 위에서
    assert side[0][1][OP["l_shoulder"]] == 1
    assert side[0][1][OP["r_shoulder"]] == 0
    _, _, front = _shoot([d], yaw=0, pitch=0, dist=3.0)
    for n in ("r_shoulder", "l_shoulder", "r_hip", "l_hip", "neck"):
        assert front[0][1][OP[n]] == 1, n
    # 보통 인형 옆모습: 먼 쪽 어깨·엉덩이는 가려짐
    _, _, kps = _shoot([_standing(S)], yaw=90, pitch=0)
    v = kps[0][1]
    assert v[OP["l_shoulder"]] == 1 and v[OP["l_hip"]] == 1
    assert v[OP["r_shoulder"]] == 0 and v[OP["r_hip"]] == 0


def test_top_view_big_head_hides_feet(S):
    d = _standing(S)
    _, _, kps = _shoot([d], yaw=0, pitch=89)
    v = kps[0][1]
    assert v[OP["r_ankle"]] == 0 and v[OP["l_ankle"]] == 0     # 머리 큰 체형: 바로 위에서는 발이 안 보임
    assert v[OP["nose"]] == 1


def test_arm_pointing_at_camera_stays_visible(S):
    """팔을 카메라 쪽으로 뻗으면 팔꿈치가 자기 팔 캡슐 속 — 자기 팔에 가려졌다고 하면 안 됨"""
    d = _standing(S)
    d.solve_limb("r_arm", d.pos["r_shoulder"] + np.array([0, 0, 0.25]))
    _, _, kps = _shoot([d], yaw=0, pitch=0, dist=3.0)
    assert kps[0][1][OP["r_wrist"]] == 1
    assert kps[0][1][OP["r_elbow"]] == 1 or kps[0][2][OP["r_elbow"]] == 1


# ------------------------------------------------------------------ 카메라·깊이
def test_camera_turn_swaps_left_and_right(S):
    dolls, _ = make("hands_up", S)                              # a 는 +x (정면에서 화면 오른쪽)
    for yaw, a_right in ((0, True), (180, False)):
        _, rr, _ = _shoot(dolls, yaw=yaw, pitch=5)
        xa = np.nonzero(rr["who"] == 0)[1].mean()
        xb = np.nonzero(rr["who"] == 1)[1].mean()
        assert (xa > xb) == a_right, yaw
    d = _standing(S)                                            # 정면: 오른 어깨는 화면 왼쪽 (OpenPose 규칙)
    _, _, f = _shoot([d], yaw=0, pitch=0)
    _, _, b = _shoot([d], yaw=180, pitch=0)
    assert f[0][0][OP["r_shoulder"], 0] < f[0][0][OP["l_shoulder"], 0]
    assert b[0][0][OP["r_shoulder"], 0] > b[0][0][OP["l_shoulder"], 0]


def test_nearer_is_brighter(S):
    a = _standing(S, "a", x=0.35, z=0.0)
    b = _standing(S, "b", x=-0.35, z=-0.8)
    cam, rr, _ = _shoot([a, b], yaw=0, pitch=0, dist=4.0)
    dep = R.depth_image(rr)[:, :, 0].astype(int)
    assert dep[rr["who"] < 0].max() == 0                         # 배경 검정
    va = np.median(dep[rr["who"] == 0])
    vb = np.median(dep[rr["who"] == 1])
    assert va > vb + 60


def test_high_angle_shows_more_top_of_head(S):
    d = _standing(S)
    _, lo, _ = _shoot([d], yaw=0, pitch=0)
    _, hi, _ = _shoot([d], yaw=0, pitch=60)
    head = [k for k, (_, name, _) in enumerate(lo["parts"]) if name == "head"][0]
    body = [k for k, (_, name, _) in enumerate(lo["parts"]) if name in ("torso", "hips")]
    ratio = lambda rr: (rr["part"] == head).sum() / max(1, np.isin(rr["part"], body).sum())
    assert ratio(hi) > ratio(lo) * 1.5


# ------------------------------------------------------------------ 출력 모양
def test_build_outputs_have_requested_size(S):
    res = build("piggyback", S, 20, 6, None, 35, 200, 300)
    for n in ("depth", "label", "openpose", "openpose_all", "openpose_check", "lineart"):
        assert res[n].shape == (300, 200, 3), n
        assert res[n].dtype == np.uint8
    kp = res["kp"]
    assert kp["W"] == 200 and kp["H"] == 300 and len(kp["people"]) == 2 and len(kp["spans"]) == 2
    for p in kp["people"]:
        assert len(p["k"]) == 18 and set(p["c"]) <= {0.0, 1.0}
    assert (res["lineart"] > 0).any()
    # 조종용(가려진 점 뺌)은 전부 그린 것보다 칠한 픽셀이 적거나 같음
    assert (res["openpose"] > 0).sum() <= (res["openpose_all"] > 0).sum()


def test_openpose_colors_match_nk_pose():
    import nk_pose
    assert R.OP_LIMBS == nk_pose.LIMBS
    assert R.OP_COLORS == nk_pose.COLORS


def test_cli_render_and_examples(tmp_path):
    from PIL import Image
    out = tmp_path / "r"
    assert main(["render", "--pose", "hug", "--size", "160x200", "--out", str(out)]) == 0
    ma = np.array(Image.open(out / "mask_a.png")) > 0
    mb = np.array(Image.open(out / "mask_b.png")) > 0
    assert ma.any() and mb.any() and not (ma & mb).any()
    sc = json.load(open(out / "scene.json", encoding="utf-8"))
    assert all(c["ok"] for c in sc["contacts"])
    ex = tmp_path / "ex"
    assert main(["examples", "--out", str(ex), "--size", "128x160", "--panel", "96"]) == 0
    assert len(list(ex.glob("*.png"))) == 2 * len(EXAMPLE_POSES) == 10


# ------------------------------------------------------------------ 누끼 레이어용 (사람마다 혼자 그림)
def test_solo_layers_and_behind_masks(S):
    res = build("piggyback", S, 20, 6, None, 35, 200, 250)
    who = res["render"]["who"]
    for i, t in enumerate("ab"):
        behind = res["behind_" + t] > 0
        assert behind.any(), t                                   # 업기: 두 사람 다 어딘가 가려짐
        assert not (behind & (who == i)).any()                   # 가린 곳은 그 사람이 안 보이는 곳
        assert (who[behind] == 1 - i).all()                      # 거기 보이는 건 상대
        solo_body = res["depth_" + t][:, :, 0] > 0
        assert np.array_equal(solo_body, (who == i) | behind)   # 혼자 몸 = 보이는 곳 + 상대에 가린 곳
    assert (res["openpose_a"] > 0).any() and (res["openpose_b"] > 0).any()


def test_kp_c_keeps_points_hidden_by_partner_only(S):
    a = _standing(S, "a", z=0.0)
    b = _standing(S, "b", z=-0.6)
    cam, rr, kps = _shoot([a, b], yaw=0, pitch=0, dist=4.0)
    kp = R.kp_json(kps, cam.W, cam.H)
    pb = kp["people"][1]
    assert pb["vis"][OP["neck"]] == 0 and pb["hidden_by"][OP["neck"]] == 0
    assert pb["c"][OP["neck"]] == 1.0                            # 상대(a)에 가린 점은 혼자 층에서 그려야 함
    _, _, back = _shoot([a], yaw=180, pitch=0)
    kb = R.kp_json(back, 160, 200)["people"][0]
    assert kb["c"][OP["nose"]] == 0.0 and kb["hidden_by"][OP["nose"]] == 0   # 자기 머리에 가린 코는 뺌 (뒷모습)


def test_cli_exports_nk_pose_files(tmp_path):
    out = tmp_path / "p"
    assert main(["render", "--pose", "back_to_back", "--size", "224x160", "--spans", "0.5-1.0,0.0-0.5",
                 "--name", "cut10", "--out", str(out)]) == 0
    kp = json.load(open(out / "cut10_kp.json", encoding="utf-8"))
    assert kp["W"] == 224 and kp["H"] == 160 and kp["spans"] == [[0.5, 1.0], [0.0, 0.5]]
    assert all(len(p["k"]) == 18 and len(p["c"]) == 18 for p in kp["people"])
    assert (out / "cut10.png").exists()


def test_control_skeleton_keeps_self_hidden_body_points(S):
    """옆모습: 먼 쪽 어깨·엉덩이·목은 진짜로는 가려졌어도(vis 0) 조종 뼈대엔 그림 (몸통 선이 끊기지 않게).
    뒷모습의 얼굴 점, 상대에 가린 점은 조종 뼈대에서 뺌"""
    d = _standing(S)
    _, _, kps = _shoot([d], yaw=90, pitch=0)
    use = R.control_mask(kps, 0)
    for n in ("r_shoulder", "r_hip"):
        assert kps[0][1][OP[n]] == 0 and use[OP[n]], n
    _, _, back = _shoot([d], yaw=180, pitch=0)
    assert not R.control_mask(back, 0)[OP["nose"]]
    a = _standing(S, "a", z=0.0)
    b = _standing(S, "b", z=-0.6)
    _, _, two = _shoot([a, b], yaw=0, pitch=0, dist=4.0)
    assert not R.control_mask(two, 1)[OP["neck"]]                     # 두 사람 그림: 상대(a)에 가린 목은 뺌
    assert R.control_mask(two, 1, solo=True)[OP["neck"]]              # 혼자 층: 그림



@pytest.fixture(scope="module")
def SH():
    return load_settings(os.path.join(KIT, "tools", "pose3d", "settings_human.yaml"))


@pytest.mark.parametrize("pose", sorted(PH.POSES))
def test_human_poses_render(SH, pose):
    res = build(pose, SH, 15, 40, None, 35, 160, 200)
    assert res["depth"].shape[:2] == (200, 160) and res["depth"].max() > 0
    assert all(not any(k.startswith("ear") or k == "tail" or k == "muzzle" for _, k, _ in R.scene_parts(res["dolls"])) for _ in [0])


def test_human_heights(SH):
    """서고 앉기: 앉은 작은 사람(b) 머리 꼭대기가 선 큰 사람(a) 골반보다 높고 어깨보다 낮음 / 나란히 앉기: 엉덩이 높이 같음(같은 벤치)"""
    dolls, _ = make("stand_sit", SH)
    a, b = dolls
    top_b = b.pos["head"][1] + b.b["head_ry"]
    assert a.pos["pelvis"][1] < top_b < a.pos["r_shoulder"][1]
    dolls, _ = make("sit_pair", SH)
    a, b = dolls
    assert abs((a.pos["pelvis"][1] - a.b["thigh_r"] * 0.9) - (b.pos["pelvis"][1] - b.b["thigh_r"] * 0.9)) < 1e-6
