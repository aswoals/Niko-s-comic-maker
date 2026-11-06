# -*- coding: utf-8 -*-
"""
tools/pose3d/poses.py - 두 인형 자세 틀 5개

  piggyback     업기           a 가 b 를 등에 업음
  shoulder      목마           a 가 b 를 어깨에 태움
  hug           서서 안기       마주 보고 안음 (a 는 허리를, b 는 어깨를)
  hands_up      두 손 맞잡고 높이 들기
  back_to_back  등 맞대고 앉기   바닥에 앉아 등을 맞댐
  (덤) holding_hands 손잡고 서기 / high_five 하이파이브 — 예시 그림 10장에는 안 넣음

틀은 '손을 상대 어디에 둔다' 같은 닿는 곳을 먼저 정하고 IK 로 팔다리 각도를 구한다 → 체형(settings.yaml)을 바꿔도 닿는 곳이 유지됨.
팔이 짧아 못 닿으면 가장 가까운 곳까지만 가고 doll.reach_err 에 남은 거리가 적힘 (시험이 이걸 봄).
정면 카메라(yaw 0)에서 a 는 화면 오른쪽, b 는 왼쪽.

에러가 나면: 새 틀을 만들다 팔이 꼬이면 pole(팔꿈치·무릎이 향하는 방향)을 반대로 줘 볼 것."""
import numpy as np

from .body import Doll, scaled_body, standing_pelvis_height, unit

UP = np.array([0, 1.0, 0])


def _pair(settings, swap=False):
    a = Doll(scaled_body(settings, "a"), "a")
    b = Doll(scaled_body(settings, "b"), "b")
    return (b, a) if swap else (a, b)


def _via(doll, limb, mid, end_dir):
    """가운데 관절(팔꿈치·무릎)을 mid 쪽으로, 끝은 거기서 end_dir 방향으로 뻗게 (두 마디 길이 그대로)"""
    from .body import LIMBS
    a, m, e = LIMBS[limb]
    S = doll.pos[a]
    l1 = float(np.linalg.norm(doll.off[m]))
    l2 = float(np.linalg.norm(doll.off[e]))
    M = S + l1 * unit(np.asarray(mid, float) - S)
    E = M + l2 * unit(end_dir)
    pole = M - (S + E) / 2
    return doll.solve_limb(limb, E, pole)


def _stand_legs(doll, bend=0.0, spread=0.0, back=0.0):
    """서기: 발목을 엉덩이 관절 바로 아래(조금 벌림/뒤로)에. bend = 무릎 굽힘으로 낮아지는 길이"""
    b = doll.b
    L = b["thigh"] + b["shin"]
    for side, sx in (("r", -1), ("l", 1)):
        hip = doll.pos[side + "_hip"]
        tgt = hip + UP * -(L - bend) + doll.left() * sx * spread - doll.facing() * back
        tgt[1] = max(tgt[1], b["foot_r"] * 1.1)
        doll.solve_limb(side + "_leg", tgt, doll.facing())


def _hang_arms(doll, out=0.03):
    b = doll.b
    for side, sx in (("r", -1), ("l", 1)):
        sh = doll.pos[side + "_shoulder"]
        doll.solve_limb(side + "_arm", sh + UP * -(b["upper_arm"] + b["forearm"]) * 0.97 + doll.left() * sx * out,
                        -doll.facing())


def _torso_center(doll):
    return (doll.pos["pelvis"] + doll.pos["chest"]) / 2


# ------------------------------------------------------------------ 1) 업기
def piggyback(settings, swap=False):
    a, b = _pair(settings, swap)              # a = 업는 사람, b = 업히는 사람
    ab = a.b
    a.set_root([0.0, standing_pelvis_height(ab) - 0.02, 0.0], yaw=0)
    a.set_joint("spine", pitch=18)
    a.set_joint("neck", pitch=-12)            # 숙인 몸에서 얼굴은 앞(카메라)을 봄
    _stand_legs(a, bend=0.02, spread=0.01)
    # b: a 의 등 뒤, 허리 높이에 엉덩이
    back = -a.facing()
    b_pelvis = a.pos["pelvis"] + UP * 0.13 + back * (ab["torso_rz"] + b.b["torso_rz"] + 0.03)
    b.set_root(b_pelvis, yaw=0)
    b.set_joint("spine", pitch=22)
    b.set_joint("neck", pitch=-15, roll=-18)   # 머리를 a 어깨 옆(b 의 왼쪽 = 화면 오른쪽)으로 내밀어 둘 다 얼굴이 보이게
    # b 의 무릎은 a 의 허리 양옆, 정강이는 아래로
    for side, sx in (("r", -1), ("l", 1)):
        knee = a.pos["pelvis"] + UP * 0.10 + a.left() * sx * (ab["torso_rx"] + b.b["thigh_r"] + 0.01) + a.facing() * 0.02
        _via(b, side + "_leg", knee, -UP + a.facing() * 0.25)
    # a 의 손: b 의 무릎 바로 아래 (받쳐 듦)
    for side, sx in (("r", -1), ("l", 1)):
        tgt = b.pos[side + "_knee"] - UP * (b.b["thigh_r"] + ab["paw_r"] * 0.3) - a.facing() * 0.01
        a.solve_limb(side + "_arm", tgt, back + a.left() * sx * 0.8)
    for side, sx in (("r", -1), ("l", 1)):
        if b.b.get("human"):                 # 사람 체형만 (케모노 짧은 팔은 쇄골 앞까지 안 닿음 -> 예전처럼 어깨 위)
            col = (a.pos["neck"] + a.pos[side + "_shoulder"]) / 2
            tgt = col + a.facing() * (ab["torso_rz"] + b.b["paw_r"] * 0.8) - UP * (ab["arm_r"] * 0.8)
        else:
            tgt = a.pos[side + "_shoulder"] + UP * (ab["arm_r"] + b.b["paw_r"] * 0.6) + a.facing() * 0.03
        b.solve_limb(side + "_arm", tgt, b.left() * sx + UP * 0.3)
    a.curl_tail(pitch=-6, first=(-55, -35))    # a 꼬리: b 다리 아래로 처짐
    b.curl_tail(pitch=-12, first=(-40, 20))
    contacts = [
        ("a 오른손 - b 오른 무릎", (0, "r_wrist"), (1, "r_knee"), 0.14),
        ("a 왼손 - b 왼 무릎", (0, "l_wrist"), (1, "l_knee"), 0.14),
        ("b 오른손 - a 어깨·쇄골", (1, "r_wrist"), (0, "r_shoulder"), 0.16),
        ("b 왼손 - a 어깨·쇄골", (1, "l_wrist"), (0, "l_shoulder"), 0.16),
    ]
    return [a, b], contacts


# ------------------------------------------------------------------ 2) 목마
def shoulder(settings, swap=False):
    a, b = _pair(settings, swap)              # a = 태우는 사람, b = 어깨에 탄 사람
    ab = a.b
    a.set_root([0.0, standing_pelvis_height(ab), 0.0], yaw=0)
    _stand_legs(a, spread=0.02)
    a.set_joint("neck", pitch=6)
    b_pelvis = a.pos["chest"] + UP * (b.b["thigh_r"] * 0.9 + 0.02) - a.facing() * (ab["head_rz"] * 0.55)
    b.set_root(b_pelvis, yaw=0)
    b.set_joint("spine", pitch=6)
    # b 허벅지는 a 머리 양옆으로, 정강이는 a 가슴 앞으로 늘어뜨림
    for side, sx in (("r", -1), ("l", 1)):
        knee = a.pos["head"] + a.left() * sx * (ab["head_rx"] + b.b["thigh_r"] + 0.01) - UP * 0.06 + a.facing() * 0.03
        _via(b, side + "_leg", knee, -UP + a.facing() * 0.2)
    # a 의 손: b 의 발목을 잡음
    for side, sx in (("r", -1), ("l", 1)):
        tgt = b.pos[side + "_ankle"] + a.facing() * (b.b["shin_r"] + ab["paw_r"] * 0.4)
        a.solve_limb(side + "_arm", tgt, -a.facing() + a.left() * sx)
    # b 의 손: a 머리 위 (귀 사이)
    for side, sx in (("r", -1), ("l", 1)):
        tgt = a.pos["head"] + UP * (ab["head_ry"] + b.b["paw_r"] * 0.5) + a.left() * sx * 0.035 + a.facing() * 0.02
        b.solve_limb(side + "_arm", tgt, b.left() * sx + UP * 0.2)
    a.curl_tail(pitch=-5, first=(-45, 25))
    b.curl_tail(pitch=-8, first=(-75, 0))
    contacts = [
        ("a 오른손 - b 오른 발목", (0, "r_wrist"), (1, "r_ankle"), 0.14),
        ("a 왼손 - b 왼 발목", (0, "l_wrist"), (1, "l_ankle"), 0.14),
        ("b 손 - a 머리 위", (1, "r_wrist"), (0, "head"), 0.25),
        ("b 엉덩이 - a 목 밑", (1, "pelvis"), (0, "chest"), 0.16),
    ]
    return [a, b], contacts


# ------------------------------------------------------------------ 3) 서서 안기
def hug(settings, swap=False):
    a, b = _pair(settings, swap)
    ab, bb = a.b, b.b
    gap = ab["torso_rz"] + bb["torso_rz"] - 0.01
    a.set_root([gap / 2, standing_pelvis_height(ab), 0.0], yaw=-90)     # a: 오른쪽, 왼쪽(-x)을 봄
    b.set_root([-gap / 2, standing_pelvis_height(bb), 0.0], yaw=90)
    for d in (a, b):
        d.set_joint("spine", pitch=6)
        d.set_joint("neck", roll=-24, pitch=4)                         # 서로 어깨에 얼굴을 기댐 (반대쪽으로)
        _stand_legs(d, spread=0.015, back=0.03)
    # a 의 팔: b 허리를 감쌈 / b 의 팔: a 어깨·등 위쪽을 감쌈 (위아래로 엇갈려 팔이 부딪히지 않게)
    for side, sx in (("r", -1), ("l", 1)):
        c = _torso_center(b) - UP * 0.05
        tgt = c + b.left() * (-sx) * bb["torso_rx"] * 0.75 - b.facing() * (bb["torso_rz"] * 0.8)
        a.solve_limb(side + "_arm", tgt, -UP * 0.6 + a.left() * sx)
    for side, sx in (("r", -1), ("l", 1)):
        c = a.pos["chest"] - UP * 0.05
        tgt = c + a.left() * (-sx) * ab["torso_rx"] * 0.7 - a.facing() * (ab["torso_rz"] * 0.9)
        b.solve_limb(side + "_arm", tgt, UP * 0.5 + b.left() * sx)
    a.curl_tail(pitch=-6, first=(-62, 15))                  # 꼬리는 각자 뒤로 늘어뜨림
    b.curl_tail(pitch=-6, first=(-62, -15))
    contacts = [
        ("a 오른손 - b 몸통", (0, "r_wrist"), (1, "spine"), 0.2),
        ("a 왼손 - b 몸통", (0, "l_wrist"), (1, "spine"), 0.2),
        ("b 오른손 - a 가슴", (1, "r_wrist"), (0, "chest"), 0.2),
        ("b 왼손 - a 가슴", (1, "l_wrist"), (0, "chest"), 0.2),
    ]
    return [a, b], contacts


# ------------------------------------------------------------------ 4) 두 손 맞잡고 높이 들기
def hands_up(settings, swap=False, elev=55.0):
    import math
    a, b = _pair(settings, swap)
    ab, bb = a.b, b.b
    La = (ab["upper_arm"] + ab["forearm"]) * 0.96
    Lb = (bb["upper_arm"] + bb["forearm"]) * 0.96
    e = math.radians(elev)
    grip = (ab["paw_r"] + bb["paw_r"]) * 0.55                           # 두 손목 사이 (발바닥 손이 맞붙음)
    xa = grip / 2 + La * math.cos(e)
    xb = -(grip / 2 + Lb * math.cos(e))
    a.set_root([xa, standing_pelvis_height(ab), 0.0], yaw=-90)
    b.set_root([xb, standing_pelvis_height(bb), 0.0], yaw=90)
    for d in (a, b):
        d.set_joint("spine", pitch=-4)
        d.set_joint("neck", pitch=-14)                                  # 올린 손을 올려다봄
        _stand_legs(d, spread=0.03)
    # 두 사람 어깨 높이 가운데에서 elev 각도만큼 위
    y = (a.pos["r_shoulder"][1] + b.pos["l_shoulder"][1]) / 2 + min(La, Lb) * math.sin(e)
    for sa, sb in (("r", "l"), ("l", "r")):                            # a 오른손 = b 왼손, a 왼손 = b 오른손
        za = a.pos[sa + "_shoulder"][2]
        zb = b.pos[sb + "_shoulder"][2]
        z = (za + zb) / 2 * 1.2
        a.solve_limb(sa + "_arm", [grip / 2, y, z], -UP + a.left() * (1 if sa == "l" else -1))
        b.solve_limb(sb + "_arm", [-grip / 2, y, z], -UP + b.left() * (1 if sb == "l" else -1))
    a.curl_tail(pitch=14, first=(25, 15))
    b.curl_tail(pitch=14, first=(25, -15))
    contacts = [
        ("a 오른손 - b 왼손", (0, "r_wrist"), (1, "l_wrist"), 0.12),
        ("a 왼손 - b 오른손", (0, "l_wrist"), (1, "r_wrist"), 0.12),
    ]
    return [a, b], contacts


# ------------------------------------------------------------------ 5) 등 맞대고 앉기
def back_to_back(settings, swap=False):
    a, b = _pair(settings, swap)
    ab, bb = a.b, b.b
    xa = max(ab["torso_rz"] * 1.1, ab["head_rz"] * 0.92)
    xb = max(bb["torso_rz"] * 1.1, bb["head_rz"] * 0.92)
    a.set_root([xa, ab["thigh_r"] + 0.01, 0.0], yaw=90)                 # a: 오른쪽, 오른쪽(+x)을 봄
    b.set_root([-xb, bb["thigh_r"] + 0.01, 0.0], yaw=-90)
    for d in (a, b):
        d.set_joint("spine", pitch=-3)
        d.set_joint("neck", roll=16, pitch=-6)                          # 머리를 옆으로 살짝 → 뒤통수끼리 기댐
        dd = d.b
        for side, sx in (("r", -1), ("l", 1)):                         # 무릎 세우고 발은 앞 바닥에
            hip = d.pos[side + "_hip"]
            ank = hip + d.facing() * (dd["thigh"] + dd["shin"]) * 0.62 + d.left() * sx * 0.02
            ank[1] = dd["foot_r"] * 1.1
            d.solve_limb(side + "_leg", ank, UP + d.facing() * 0.3)
        for side, sx in (("r", -1), ("l", 1)):                         # 손은 무릎 위
            tgt = d.pos[side + "_knee"] + UP * (dd["thigh_r"] + dd["paw_r"] * 0.4) + d.left() * sx * 0.01
            d.solve_limb(side + "_arm", tgt, -d.facing() * 0.3 + d.left() * sx - UP * 0.3)
    # 꼬리는 바닥을 따라 옆으로, 둘 다 카메라 반대쪽(-z)으로 (a 는 자기 왼쪽, b 는 자기 오른쪽이 -z)
    a.curl_tail(pitch=-4, yaw=-18, first=(-30, -70))
    b.curl_tail(pitch=-4, yaw=18, first=(-30, 70))
    contacts = [
        ("a 뒤통수 - b 뒤통수", (0, "head"), (1, "head"), (ab["head_rz"] + bb["head_rz"]) * 1.25),
        ("a 등 - b 등", (0, "chest"), (1, "chest"), (ab["torso_rz"] + bb["torso_rz"]) * 2.6),
    ]
    return [a, b], contacts


# ------------------------------------------------------------------ (덤) duo1 컷3·4 시험용: 손잡고 서기 / 하이파이브
def holding_hands(settings, swap=False, arm_down=50.0):
    """나란히 서서 카메라(+z)를 봄. a(오른쪽)의 오른손 = b(왼쪽)의 왼손"""
    import math
    a, b = _pair(settings, swap)
    ab, bb = a.b, b.b
    La = (ab["upper_arm"] + ab["forearm"]) * 0.95
    Lb = (bb["upper_arm"] + bb["forearm"]) * 0.95
    e = math.radians(arm_down)
    grip = (ab["paw_r"] + bb["paw_r"]) * 0.5
    xa = ab["shoulder_w"] + La * math.cos(e) + grip / 2
    xb = -(bb["shoulder_w"] + Lb * math.cos(e) + grip / 2)
    a.set_root([xa, standing_pelvis_height(ab), 0.0], yaw=-8)
    b.set_root([xb, standing_pelvis_height(bb), 0.0], yaw=8)
    for d in (a, b):
        _stand_legs(d, spread=0.02)
    a.set_joint("neck", roll=6)
    b.set_joint("neck", roll=-6)                                       # 서로 쪽으로 고개를 살짝
    y = (a.pos["r_shoulder"][1] + b.pos["l_shoulder"][1]) / 2 - min(La, Lb) * math.sin(e)
    z = 0.03
    a.solve_limb("r_arm", [grip / 2, y, z], -a.facing() - UP * 0.2)
    b.solve_limb("l_arm", [-grip / 2, y, z], -b.facing() - UP * 0.2)
    _hang_arms_one(a, "l")
    _hang_arms_one(b, "r")
    a.curl_tail(pitch=6, first=(-20, -30))
    b.curl_tail(pitch=6, first=(-20, 30))
    return [a, b], [("a 오른손 - b 왼손", (0, "r_wrist"), (1, "l_wrist"), 0.12)]


def high_five(settings, swap=False):
    """마주 보고 오른손끼리 머리 높이에서 맞댐"""
    import math
    a, b = _pair(settings, swap)
    ab, bb = a.b, b.b
    La = (ab["upper_arm"] + ab["forearm"]) * 0.95
    grip = (ab["paw_r"] + bb["paw_r"]) * 0.55
    rise = 0.2
    dz = ab["shoulder_w"]
    dx = math.sqrt(max(La * La - dz * dz - rise * rise, 0.01 ** 2))
    xa = grip / 2 + dx
    a.set_root([xa, standing_pelvis_height(ab), 0.0], yaw=-90)
    b.set_root([-xa, standing_pelvis_height(bb), 0.0], yaw=90)
    for d in (a, b):
        d.set_joint("spine", pitch=-3)
        _stand_legs(d, spread=0.03, back=0.02)
    y = (a.pos["r_shoulder"][1] + b.pos["r_shoulder"][1]) / 2 + rise
    a.solve_limb("r_arm", [grip / 2, y, 0.0], -UP + a.left() * -1)
    b.solve_limb("r_arm", [-grip / 2, y, 0.0], -UP + b.left() * -1)
    _hang_arms_one(a, "l")
    _hang_arms_one(b, "l")
    a.curl_tail(pitch=16, first=(20, 10))
    b.curl_tail(pitch=16, first=(20, -10))
    return [a, b], [("a 오른손 - b 오른손", (0, "r_wrist"), (1, "r_wrist"), 0.12)]


def _hang_arms_one(doll, side, out=0.03):
    b = doll.b
    sx = -1 if side == "r" else 1
    sh = doll.pos[side + "_shoulder"]
    doll.solve_limb(side + "_arm", sh + UP * -(b["upper_arm"] + b["forearm"]) * 0.97 + doll.left() * sx * out, -doll.facing())


POSES = {"piggyback": piggyback, "shoulder": shoulder, "hug": hug, "hands_up": hands_up, "back_to_back": back_to_back,
         "holding_hands": holding_hands, "high_five": high_five}
EXAMPLE_POSES = ["piggyback", "shoulder", "hug", "hands_up", "back_to_back"]      # 과제의 자세 틀 5개 (예시 그림 10장)
KOREAN = {"piggyback": "업기", "shoulder": "목마", "hug": "서서 안기", "hands_up": "두 손 맞잡고 높이 들기",
          "back_to_back": "등 맞대고 앉기", "holding_hands": "손잡고 서기", "high_five": "하이파이브"}
# 예시 그림용 카메라 두 개 (yaw, pitch): 보통 눈높이 + 위에서 내려다보는 앵글
EXAMPLE_CAMERAS = {
    "piggyback": [("eye", 20, 6), ("high", -35, 50)],
    "shoulder": [("eye", 18, 4), ("high", -35, 55)],
    "hug": [("eye", 28, 6), ("high", 40, 55)],
    "hands_up": [("eye", 8, 4), ("high", -30, 50)],
    "back_to_back": [("eye", 10, 8), ("high", 35, 55)],
    "holding_hands": [("eye", 0, 5), ("high", 25, 50)],
    "high_five": [("eye", 15, 5), ("high", -30, 50)],
}


def make(name, settings, swap=False):
    if name not in POSES:
        raise KeyError("모르는 자세 '%s' (있는 것: %s)" % (name, ", ".join(POSES)))
    dolls, contacts = POSES[name](settings, swap)
    for d in dolls:
        d.fk()
    return dolls, contacts


def contact_report(dolls, contacts):
    """[(설명, 거리, 허용, 통과)] — 닿아야 할 곳이 실제로 가까운지 (3D 거리)"""
    out = []
    for desc, (i, p), (j, q), tol in contacts:
        dist = float(np.linalg.norm(dolls[i].pos[p] - dolls[j].pos[q]))
        out.append((desc, dist, float(tol), dist <= tol))
    return out


from . import poses_human as _ph          # noqa: E402
POSES.update(_ph.POSES)
KOREAN.update(_ph.KOREAN)
