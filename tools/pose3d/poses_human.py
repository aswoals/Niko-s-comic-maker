# -*- coding: utf-8 -*-
"""
tools/pose3d/poses_human.py - 사람(성인) 인형 자세
settings_human.yaml 과 같이 씀 (a = 큰 사람, b = 작은 사람 — 키 배율은 settings 의 people).

  sit_bench   벤치에 앉기 (a 혼자)
  stand_sit   a 는 서고 b 는 벤치에 앉기
  face_pair   마주 보고 서기 (b 가 올려다봄)
  sit_pair    벤치에 나란히 앉기

벤치 = 앉은 사람의 소품 조각(extra) — 깊이 그림에 같이 들어가 앉는 높이를 그림 모델에 알려 줌.
좌표: +y 위, +z 카메라 쪽(정면), a 는 화면 오른쪽(+x)."""
import numpy as np

from .body import Doll, scaled_body, standing_pelvis_height, unit

UP = np.array([0, 1.0, 0])
SEAT_H = 0.24          # 벤치 앉는 면 높이 (큰 사람 키 1.0 기준 — 188cm 에서 약 45cm)
SEAT_D = 0.20          # 앉는 면 깊이


def _pair(settings):
    return Doll(scaled_body(settings, "a"), "a"), Doll(scaled_body(settings, "b"), "b")


def _bench(x0, x1, z_front=0.08):
    """벤치 조각: 앉는 면(앞·뒤 막대) + 등받이 + 다리 4개 (캡슐)"""
    r = 0.022
    zb = z_front - SEAT_D
    y = SEAT_H - r
    out = [("cap", "bench", np.array([x0, y, z_front]), np.array([x1, y, z_front]), r),
           ("cap", "bench", np.array([x0, y, (z_front + zb) / 2]), np.array([x1, y, (z_front + zb) / 2]), r),
           ("cap", "bench", np.array([x0, y, zb]), np.array([x1, y, zb]), r),
           ("cap", "bench", np.array([x0, SEAT_H + 0.17, zb - 0.02]), np.array([x1, SEAT_H + 0.17, zb - 0.02]), r * 1.3)]
    for x in (x0, x1):
        for z in (z_front, zb):
            out.append(("cap", "bench", np.array([x, 0.0, z]), np.array([x, y, z]), r * 0.7))
    return out


def _stand(d, x, yaw=0.0, spread=0.0):
    d.set_root([x, standing_pelvis_height(d.b) - 0.004, 0.0], yaw=yaw)
    b = d.b
    L = b["thigh"] + b["shin"]
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        tgt = hip + UP * -L + d.left() * sx * (spread - b["hip_w"] * 0.4)
        tgt[1] = max(tgt[1], b["foot_r"] * 1.1)
        d.solve_limb(side + "_leg", tgt, d.facing())
    for side, sx in (("r", -1), ("l", 1)):           # 팔은 옆에 (주머니 근처)
        sh = d.pos[side + "_shoulder"]
        d.solve_limb(side + "_arm", sh + UP * -(b["upper_arm"] + b["forearm"]) * 0.92 + d.left() * sx * 0.04, -d.facing())


def _sit(d, x, z=-0.03, yaw=0.0, hands_on_knees=True, swing=0.0):
    """벤치에 앉기: 엉덩이 관절 = 앉는 면 + 허벅지 두께, 허벅지는 앞으로 수평, 정강이는 아래로 (짧으면 발이 뜸 = 다리 흔들기)"""
    b = d.b
    d.set_root([x, SEAT_H + b["thigh_r"] * 0.9, z], yaw=yaw)
    d.set_joint("spine", pitch=-4)                  # 등을 살짝 뒤로 (등받이)
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        knee = hip + d.facing() * b["thigh"] * 0.97 + d.left() * sx * 0.01 - UP * 0.045
        ank = knee - UP * b["shin"] * 0.98 + d.facing() * (0.03 + swing * (1 if side == "r" else -0.5))
        ank[1] = max(ank[1], b["foot_r"] * 1.1)
        d.solve_limb(side + "_leg", ank, d.facing() + UP * 0.5)
    for side, sx in (("r", -1), ("l", 1)):
        if hands_on_knees:
            tgt = d.pos[side + "_knee"] + UP * (b["thigh_r"] + b["paw_r"] * 0.5) - d.facing() * 0.03
        else:                                       # 손은 허벅지 옆 벤치 위
            tgt = d.pos[side + "_hip"] + d.left() * sx * (b["hip_w"] + 0.06) + d.facing() * 0.04
            tgt[1] = SEAT_H + b["paw_r"]
        d.solve_limb(side + "_arm", tgt, -d.facing() * 0.4 + d.left() * sx - UP * 0.2)


def _cross_right_leg(d):
    """앉은 자세에서 오른다리를 왼무릎 위로 꼼"""
    b = d.b
    lk = d.pos["l_knee"]
    knee = lk + UP * (b["thigh_r"] * 2.0) + d.left() * (b["thigh_r"] * 0.6) + d.facing() * 0.02
    d.solve_limb("r_leg", d.pos["r_hip"] + 0.0, None)          # 리셋 없이 바로 IK
    ank = knee - UP * b["shin"] * 0.9 + d.left() * 0.06 + d.facing() * 0.05
    d.solve_limb("r_leg", ank, unit(knee - d.pos["r_hip"]) + UP * 0.3)


def sit_cross(settings, swap=False):
    """벤치에 다리 꼬고 앉기 (작은 사람 체형 b)"""
    a, b = _pair(settings)
    _sit(b, 0.0, hands_on_knees=False)
    _cross_right_leg(b)
    b.extra = _bench(-0.26, 0.26)
    return [b], []


def walk_pair(settings, swap=False):
    """나란히 걸어 카메라 쪽으로 옴 (a 오른쪽, b 왼쪽) — 다리 한쪽 앞, 한쪽 뒤"""
    a, b = _pair(settings)
    for d, x, ph in ((a, 0.2, 1), (b, -0.2, -1)):
        d.set_root([x, standing_pelvis_height(d.b) - 0.025, 0.0], yaw=0)       # 걸으면 골반이 조금 내려감
        bb = d.b
        L = bb["thigh"] + bb["shin"]
        for side, sgn in (("r", ph), ("l", -ph)):
            hip = d.pos[side + "_hip"]
            inward = d.left() * (1 if side == "r" else -1) * bb["hip_w"] * 0.3
            if sgn > 0:
                ank = hip - UP * L * 0.95 + d.facing() * 0.19 + inward
            else:
                ank = hip - UP * L * 0.86 - d.facing() * 0.16 + inward
            ank[1] = max(ank[1], bb["foot_r"] * 1.1)
            d.solve_limb(side + "_leg", ank, d.facing())
        for side, sx in (("r", -1), ("l", 1)):
            sh = d.pos[side + "_shoulder"]
            d.solve_limb(side + "_arm", sh + UP * -(bb["upper_arm"] + bb["forearm"]) * 0.92 + d.left() * sx * 0.04, -d.facing())
    return [a, b], []


def look_back(settings, swap=False):
    """뒤돌아보기: 등을 카메라 쪽(뒤에서 찍는 카메라 yaw 180 기준)으로 두고 윗몸을 틀어 어깨 너머로 봄"""
    a, b = _pair(settings)
    _stand(b, 0.0)
    b.set_joint("spine", yaw=-22)
    b.set_joint("neck", yaw=-55, pitch=-4)
    return [b], []


def piggyback_h(settings, swap=False):
    """사람 업기: a = 업는 사람(앞), b = 업힌 사람(등 뒤) — 케모노 piggyback 의 사람 체형판"""
    from .poses import piggyback
    return piggyback(settings, swap)


def _from_kemono(name):
    """케모노 두 명 자세(poses.py)를 사람 체형으로 그대로 씀 (설정 단위가 같음: 큰 사람 키 = 1.0)"""
    def f(settings, swap=False):
        from . import poses as _p
        return getattr(_p, name)(settings, swap)
    return f


hug_h, high_five_h, holding_hands_h, back_to_back_h = (_from_kemono(n) for n in ("hug", "high_five", "holding_hands", "back_to_back"))


def sit_bench(settings, swap=False):
    a, b = _pair(settings)
    _sit(a, 0.0)
    a.extra = _bench(-0.26, 0.26)                   # 혼자면 짧은 벤치 (길면 자동 카메라가 멀어져 사람이 작게 찍힘)
    return [a], []


def stand_sit(settings, swap=False):
    """a(큰 사람)는 벤치 오른쪽 옆에 서고, b(작은 사람)는 벤치에 앉아 다리를 흔듦"""
    a, b = _pair(settings)
    _sit(b, -0.12, swing=0.05)
    b.extra = _bench(-0.5, 0.18)
    _stand(a, 0.42, yaw=-15)
    b.set_joint("neck", yaw=12, pitch=8)             # 올려다봄
    a.set_joint("neck", yaw=-15, pitch=-10)          # 내려다봄
    return [a, b], []


def face_pair(settings, swap=False):
    """마주 보고 서기: a(큰 사람) 오른쪽에서 왼쪽을, b(작은 사람) 왼쪽에서 오른쪽을 봄. b 는 고개를 들어 올려다봄"""
    a, b = _pair(settings)
    gap = 0.17
    _stand(a, gap + a.b["torso_rz"], yaw=-90)
    _stand(b, -(gap + b.b["torso_rz"]), yaw=90)
    b.set_joint("neck", pitch=18)
    a.set_joint("neck", pitch=-16)
    return [a, b], []


def sit_pair(settings, swap=False):
    """벤치에 나란히 앉기 (a 오른쪽, b 왼쪽). 손은 무릎 위 (음식을 든 손은 그림 글이 맡음)"""
    a, b = _pair(settings)
    _sit(a, 0.2)
    _sit(b, -0.18, swing=0.03)
    a.extra = _bench(-0.5, 0.5)
    return [a, b], []


def stand_single(settings, swap=False):
    """혼자 서기, 손은 허리"""
    a, b = _pair(settings)
    _stand(b, 0.0, spread=0.05)
    return [b], []


def stand_pair(settings, swap=False):
    """나란히 서서 앞(카메라)을 봄 — a 오른쪽, b 왼쪽 (서로 쪽으로 조금 돌림)"""
    a, b = _pair(settings)
    _stand(a, 0.2, yaw=-10)
    _stand(b, -0.2, yaw=10)
    return [a, b], []


POSES = {"sit_bench": sit_bench, "stand_sit": stand_sit, "face_pair": face_pair, "sit_pair": sit_pair, "stand_single": stand_single,
         "stand_pair": stand_pair, "sit_cross": sit_cross, "walk_pair": walk_pair,
         "look_back": look_back, "piggyback_h": piggyback_h, "hug_h": hug_h, "high_five_h": high_five_h,
         "holding_hands_h": holding_hands_h, "back_to_back_h": back_to_back_h}
KOREAN = {"sit_bench": "벤치에 앉기 (사람)", "stand_sit": "한 명 서고 한 명 앉기 (사람)", "face_pair": "마주 보고 서기 (사람)",
          "sit_pair": "벤치에 나란히 앉기 (사람)", "stand_single": "혼자 서기, 손은 허리 (사람, 작은 체형)",
          "stand_pair": "나란히 서기 (사람)", "sit_cross": "다리 꼬고 앉기 (사람)", "walk_pair": "나란히 걷기 (사람)",
          "look_back": "뒤돌아보기 (사람)", "piggyback_h": "업기 (사람)", "hug_h": "안기 (사람)", "high_five_h": "하이파이브 (사람)",
          "holding_hands_h": "손잡고 서기·걷기 (사람)", "back_to_back_h": "등 맞대고 앉기 (사람)"}


#   pitch +90 = 엎드림(머리 +z), -90 = 반듯이 누움(머리 -z) — body.euler 규칙
def _legs(d, targets_poles):
    for side in ("r", "l"):
        t, pole = targets_poles[side]
        t = np.asarray(t, float)
        t[1] = max(t[1], d.b["foot_r"] * 1.1)
        d.solve_limb(side + "_leg", t, pole)


def b_stand(d, x=0.0):
    _stand(d, x)


def b_run(d, x=0.0):
    b = d.b
    L = b["thigh"] + b["shin"]
    d.set_root([x, standing_pelvis_height(b) - 0.035, 0.0])
    d.set_joint("spine", pitch=10)
    f, u = d.facing(), UP
    hr, hl = d.pos["r_hip"], d.pos["l_hip"]
    inr, inl = d.left() * (b["hip_w"] * 0.35), -d.left() * (b["hip_w"] * 0.35)
    _legs(d, {"r": (hr + f * 0.13 - u * L * 0.66 + inr, f), "l": (hl - f * 0.2 - u * L * 0.78 + inl, f)})


def b_jump(d, x=0.0):
    b = d.b
    d.set_root([x, standing_pelvis_height(b) + 0.06, 0.0])
    f, u = d.facing(), UP
    for side in ("r", "l"):
        hip = d.pos[side + "_hip"]
        d.solve_limb(side + "_leg", hip - u * (b["thigh"] + b["shin"]) * 0.62 - f * 0.06, f)


def b_sit_floor(d, x=0.0):
    """바닥에 앉아 무릎을 세워 안음"""
    b = d.b
    d.set_root([x, b["thigh_r"] + 0.01, 0.0])
    d.set_joint("spine", pitch=16)
    f = d.facing()
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        ank = hip + f * (b["thigh"] + b["shin"]) * 0.5 + d.left() * sx * 0.02
        ank[1] = b["foot_r"] * 1.1
        d.solve_limb(side + "_leg", ank, UP + f * 0.3)


def b_kneel(d, x=0.0):
    b = d.b
    d.set_root([x, b["thigh"] + b["shin_r"] + 0.01, 0.0])
    f = d.facing()
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        knee = hip - UP * b["thigh"] + f * 0.04 + d.left() * sx * 0.01
        knee[1] = b["shin_r"]
        from .poses import _via
        _via(d, side + "_leg", knee, -f + UP * 0.05)


def b_squat(d, x=0.0):
    b = d.b
    d.set_root([x, b["shin"] * 0.62, 0.0])
    d.set_joint("spine", pitch=22)
    f = d.facing()
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        ank = hip + f * 0.02 + d.left() * sx * 0.06
        ank[1] = b["foot_r"] * 1.1
        d.solve_limb(side + "_leg", ank, f + UP * 0.4)


def b_lie_back(d, x=0.0):
    b = d.b
    d.set_root([x, b["torso_rz"] + 0.01, 0.0], pitch=-90)
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        d.solve_limb(side + "_leg", hip + np.array([0, 0, 1.0]) * (b["thigh"] + b["shin"]) * 0.97 + d.left() * sx * 0.03, UP)


def b_lie_stomach(d, x=0.0):
    """엎드려 팔꿈치로 윗몸을 받치고 발을 듦 (책 읽기)"""
    b = d.b
    d.set_root([x, b["torso_rz"] + 0.01, 0.0], pitch=90)
    d.set_joint("spine", pitch=-18)
    d.set_joint("neck", pitch=-12)
    back = np.array([0, 0, -1.0])
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        d.solve_limb(side + "_leg", hip + back * b["thigh"] + UP * b["shin"] * 0.8 + d.left() * sx * 0.03, back)
    #   (엎드린 사람의 핵심 표시 = 바닥을 짚은 팔꿈치·앞으로 뻗은 아래팔. nk_pose3d_auto 가 이 자세는 팔을 남김)
    from .poses import _via
    fwd = np.array([0, 0, 1.0])
    cx = d.pos["chest"][0]
    for side in ("r", "l"):
        sh = d.pos[side + "_shoulder"]
        elbow = np.array([sh[0] + (cx - sh[0]) * 0.15, b["arm_r"] * 1.3, sh[2] + 0.04])
        inward = np.array([np.sign(cx - sh[0]) or 1.0, 0, 0])
        _via(d, side + "_arm", elbow, fwd + inward * 0.45 + UP * 0.05)


SINGLE = {"stand": b_stand, "run": b_run, "jump": b_jump, "sit_floor": b_sit_floor, "kneel": b_kneel, "squat": b_squat,
          "lie_back": b_lie_back, "lie_stomach": b_lie_stomach}


def single_pose(kind):
    def f(settings, swap=False):
        a, b = _pair(settings)
        SINGLE[kind](a)
        return [a], []
    return f


def pair_pose(ka, kb, gap=0.24):
    """두 사람이 각자 혼자 자세 (닿지 않음) — a 오른쪽, b 왼쪽"""
    def f(settings, swap=False):
        a, b = _pair(settings)
        g = gap * (1.6 if ka.startswith("lie") or kb.startswith("lie") else 1.0)
        SINGLE[ka](a, g)
        SINGLE[kb](b, -g)
        return [a, b], []
    return f


for _k in SINGLE:
    POSES["s_" + _k] = single_pose(_k)
    KOREAN["s_" + _k] = "혼자 %s (사람)" % _k
