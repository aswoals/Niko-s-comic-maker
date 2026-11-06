# -*- coding: utf-8 -*-
"""
tools/pose3d/library_human.py - 사람 인형 자세 도서관

왜: 자동 인형(nk_pose3d_auto)이 아는 자세가 20개쯤이라, 목록에 없는 자세는 '서기'로 그려 다리·발이 뭉개짐.
    자세를 늘려 컷 태그(Danbooru 자세 태그)로 고르게 함. 그 밖의 자세는 '먼저 그리고 → DWPose 뼈대 → 인형 비율로 고쳐 → 약하게 다시'(lift2d).

등록 (자세 하나 = 함수 하나):
    def hands_on_hips(d, x=0.0):      # d = 사람 인형(Doll), x = 가로 자리. 바닥 = y 0, 정면 = +z, 인형 왼쪽 = d.left()
        ...
    def princess_carry(a, b):         # a = 오른쪽 사람(+x), b = 왼쪽 사람. first 가 있으면 그 낱말이 붙은 사람이 a
        ...
  - tags: 컷 태그 안에 이 말이 낱말 그대로 있으면 이 자세 (여러 개면 하나만 맞아도). 긴(구체적인) 태그가 이김.
    'a+b' = a 와 b 가 둘 다 있어야 (예: "sitting+leaning back").
  - base (혼자 자세만): 바탕 자세 — nk_pose3d_auto._kind 가 컷 태그에서 읽은 것(stand·sit_floor·kneel·squat·lie_back·lie_stomach·run·jump)과
    같을 때만 고름. 예: base="stand" 인 'arms behind head' 는 'lying, arms behind head' 컷에선 안 골림. None = 태그 자체가 바탕 자세(seiza, all fours ...).
  - arms: True = 팔 전체를 깊이·선화에 남김 (팔 모양이 자세의 핵심일 때만). False = 팔을 빼고 그림 모델에 맡김
.
  - 혼자 자세는 poses_human.SINGLE 에도 들어가서 's_<이름>'(혼자)·'p_<이름1>_<이름2>'(두 사람이 각자) 로 쓰임.
  - 두 사람 자세는 poses.POSES 에 'L_<이름>' 으로 들어감."""
import math
import re

import numpy as np

from .body import ry, standing_pelvis_height, unit

UP = np.array([0, 1.0, 0])
LIB = {}          # 이름 -> {"n": 1|2, "tags": [...], "ko": "...", "arms": bool, "first": str|None, "fn": f}


def single(name, tags, ko, arms=False, base="stand"):
    def deco(fn):
        assert name not in LIB, "자세 이름 겹침: " + name
        LIB[name] = {"n": 1, "tags": [t.lower() for t in tags], "ko": ko, "arms": bool(arms), "first": None, "base": base, "fn": fn}
        return fn
    return deco


def pair(name, tags, ko, arms=True, first=None, actor="a"):
    """actor = 그 동작을 '하는' 사람이 a(오른쪽 인형)인지 b(왼쪽 인형)인지. 컷 roles 에 자세 태그가 붙은 사람이 actor 자리로 감"""
    def deco(fn):
        assert name not in LIB, "자세 이름 겹침: " + name
        LIB[name] = {"n": 2, "tags": [t.lower() for t in tags], "ko": ko, "arms": bool(arms), "first": first, "actor": actor, "base": None, "fn": fn}
        return fn
    return deco


def _has(words, tag):
    return all(re.search(r"(^|[\s,.;:()])" + re.escape(x.strip()) + r"($|[\s,.;:()])", words) is not None for x in tag.split("+"))


def match(words, n=1, base=None):
    """컷 태그 낱말 -> 자세 이름 (n = 1 혼자 / 2 두 사람) 또는 None. 가장 긴 태그가 맞은 자세.
    base 를 주면 바탕 자세가 같은(또는 base 가 None 인) 혼자 자세만"""
    w = " " + str(words or "").lower() + " "
    best, best_len = None, 0
    for name, e in LIB.items():
        if e["n"] != n:
            continue
        if n == 1 and base is not None and e["base"] not in (None, base):
            continue
        for t in e["tags"]:
            if len(t) > best_len and _has(w, t):
                best, best_len = name, len(t)
    return best


def arms_kept(name):
    e = LIB.get(name)
    return bool(e and e["arms"])


# ------------------------------------------------------------------ 도우미 (자세 함수에서 씀)
def stand_legs(d, spread=0.0, bend=0.0, back=0.0):
    """두 다리로 서기: 발은 엉덩이 관절보다 조금 안쪽, bend = 무릎 굽혀 낮아지는 길이"""
    b = d.b
    L = b["thigh"] + b["shin"]
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        tgt = hip - UP * (L - bend) + d.left() * sx * (spread - b["hip_w"] * 0.4) - d.facing() * back
        tgt[1] = max(tgt[1], b["foot_r"] * 1.1)
        d.solve_limb(side + "_leg", tgt, d.facing())


def root_stand(d, x=0.0, z=0.0, yaw=0.0, drop=0.004):
    """서 있는 골반 높이에 인형을 둠 (drop = 무릎을 살짝 굽힌 만큼 낮춤)"""
    d.set_root([x, standing_pelvis_height(d.b) - drop, z], yaw=yaw)


def hang_arm(d, side, out=0.04):
    b = d.b
    sx = -1 if side == "r" else 1
    sh = d.pos[side + "_shoulder"]
    d.solve_limb(side + "_arm", sh - UP * (b["upper_arm"] + b["forearm"]) * 0.92 + d.left() * sx * out, -d.facing())


def arm_to(d, side, target, pole):
    """손목을 target 에, 팔꿈치는 pole 쪽으로"""
    return d.solve_limb(side + "_arm", np.asarray(target, float), np.asarray(pole, float))


def arm_reach(d, side, target, pole, k=0.985):
    """arm_to 와 같지만 팔이 닿는 거리(길이 x k) 밖이면 그 방향으로 닿는 데까지만 (키가 다른 사람끼리 손이 안 닿을 때 팔이 꼬이지 않게)"""
    S = d.pos[side + "_shoulder"]
    v = np.asarray(target, float) - S
    L = (d.b["upper_arm"] + d.b["forearm"]) * k
    n = float(np.linalg.norm(v))
    if n > L:
        target = S + v / n * L
    return arm_to(d, side, target, pole)


def leg_to(d, side, target, pole):
    t = np.asarray(target, float)
    t[1] = max(t[1], d.b["foot_r"] * 1.1)
    return d.solve_limb(side + "_leg", t, np.asarray(pole, float))


def head_top(d):
    return d.pos["head"] + UP * d.b["head_ry"]


def kscale(d):
    """다리 길이 / 기준(0.485): 키가 다른 사람(0.8~1.0)에게도 같은 모양이 되게 길이 숫자에 곱함"""
    return (d.b["thigh"] + d.b["shin"]) / 0.485


def aspan(d):
    """팔 길이 (위팔 + 아래팔)"""
    return d.b["upper_arm"] + d.b["forearm"]


def sgn(side):
    """오른쪽 = -1 (정면을 볼 때 -x), 왼쪽 = +1"""
    return -1 if side == "r" else 1


def hfacing(d):
    """인형이 보는 쪽 (수평) — 골반을 숙여도 땅과 나란한 방향"""
    f = d.facing().copy()
    f[1] = 0.0
    return unit(f)


def vec(d, side, out=0.0, up=0.0, fwd=0.0):
    """인형 기준 방향 (세계 좌표): out = 그 팔·다리의 바깥쪽, up = 세계 위, fwd = 인형이 보는 쪽 (수평)"""
    return d.left() * sgn(side) * out + UP * up + hfacing(d) * fwd


def via(d, limb, mid, end_dir):
    """팔꿈치·무릎을 mid 쪽으로, 끝은 거기서 end_dir 쪽으로 (poses._via)"""
    from .poses import _via
    return _via(d, limb, mid, end_dir)


def arm_via(d, side, elbow_dir, fore_dir):
    """위팔 방향(어깨에서 팔꿈치 쪽)과 아래팔 방향을 직접 줌 — 팔 모양이 핵심인 자세용"""
    sh = d.pos[side + "_shoulder"]
    return via(d, side + "_arm", sh + unit(elbow_dir), fore_dir)


def foot_low(d, side):
    """발(발목-발끝 캡슐)의 가장 낮은 점 높이"""
    b = d.b
    an = d.pos[side + "_ankle"]
    toe = an + d.frame[side + "_knee"] @ np.array([0, -b["foot_r"] * 0.3, b["foot"]])
    return min(an[1], toe[1]) - b["foot_r"]


def plant(d, side, target, pole, floor=0.0, tol=0.01):
    """발목을 target 에 두는 다리 IK. 발이 바닥(floor)보다 tol 넘게 밑으로 들어가면 발목을 조금씩 올려 가며 다시 풂
    (발끝이 아래로 기운 뒷발은 뒤꿈치가 뜸 — 무릎이 굽을수록 발끝이 더 기울어 한 번에 안 풀려서 훑어 찾음)"""
    t = np.asarray(target, float).copy()
    t[1] = max(t[1], d.b["foot_r"] * 1.1)
    y0 = t[1]
    for k in range(80):
        t[1] = y0 + 0.004 * k
        d.solve_limb(side + "_leg", t, pole)
        if foot_low(d, side) >= floor - tol:
            break
    return t


def foot_floor(d, side, prefer=None, tol=0.01):
    """발끝 방향을 정강이 둘레로 돌려 가며, 바닥 밑으로 안 들어가는(tol 안) 방향 중 prefer 에 가장 가까운 것을 고름"""
    k = side + "_knee"
    base = d.rot[k].copy()
    best = None
    for deg in range(0, 360, 10):
        d.rot[k] = base @ ry(deg)
        d.fk()
        low = foot_low(d, side)
        toe_dir = d.frame[k] @ np.array([0, 0, 1.0])
        sc = (low >= -tol, float(toe_dir @ prefer) if prefer is not None else 0.0, low)
        if best is None or sc > best[0]:
            best = (sc, deg)
    d.rot[k] = base @ ry(best[1])
    d.fk()


def vertical_shin_ahead(d, hip_y, y_ankle=None):
    """골반(엉덩이 관절) 높이가 hip_y 일 때, 정강이가 수직(발이 평평)이 되도록 발목이 엉덩이보다 앞에 있어야 하는 거리.
    (무릎이 살짝 굽은 서기에서 정강이가 기울면 발이 정강이에 수직이라 발끝이 바닥 밑으로 들어감 → 엉덩이를 발목 약간 뒤에 둠)"""
    b = d.b
    ya = b["foot_r"] * 1.1 if y_ankle is None else y_ankle
    rest = hip_y - ya - b["shin"]
    return math.sqrt(max(b["thigh"] ** 2 - rest * rest, 0.0)) if rest < b["thigh"] else 0.0


def legs_stand(d, spread=0.03, back=0.0, toe_out=6.0, flat=True):
    """두 발 평평하게 서기: 정강이를 수직으로(flat) 두어 발이 바닥에 평평, 발끝은 살짝 바깥 (toe_out 도).
    back = 발목을 엉덩이보다 더 뒤로 (몸이 앞으로 기운 자세에서 발 위로 무게를 모을 때)"""
    b = d.b
    for side in ("r", "l"):
        s = sgn(side)
        hip = d.pos[side + "_hip"]
        dz = (vertical_shin_ahead(d, float(hip[1])) if flat else 0.0) - back          # 발목이 엉덩이보다 앞으로 dz
        tgt = hip.copy()
        tgt[1] = b["foot_r"] * 1.1
        tgt = tgt + d.left() * s * (spread - b["hip_w"] * 0.4) + hfacing(d) * dz
        a = math.radians(toe_out)
        plant(d, side, tgt, hfacing(d) * math.cos(a) + d.left() * s * math.sin(a))


def stance(d, x, off_r=0.0, off_l=0.0, spread=0.03, z=0.0, yaw=0.0, pitch=0.0, straight=None, toe_out=6.0, outs=(0.0, 0.0), tol=0.01):
    """발을 앞뒤로 어긋나게 선 자세: off_r / off_l = 오른발·왼발 발목이 골반보다 앞(+)·뒤(-)로 얼마나, outs = 발끝 바깥 각도 (오른, 왼) 가산.
    골반 높이: 더 앞에 있는 발의 정강이가 수직(발이 평평)이 되는 높이 — 앞(+)이 클수록 무릎이 더 굽음.
    straight 를 주면 대신 '가장 멀리 뻗은 다리를 (길이 x straight) 로 편' 높이 (무릎 편 서기·인사: 발끝이 살짝 들림).
    뒤로 간 발은 발끝이 아래로 기울어 뒤꿈치가 뜸(plant)"""
    b = d.b
    L = b["thigh"] + b["shin"]
    lat = abs(spread - b["hip_w"] * 0.4)
    ya = b["foot_r"] * 1.1
    if straight is None:
        h = min(max(off_r, off_l, 0.0), b["thigh"] * 0.95)
        y = ya + b["shin"] + math.sqrt(b["thigh"] ** 2 - h * h)
    else:
        h = max(abs(off_r), abs(off_l))
        y = ya + math.sqrt(max((L * straight) ** 2 - h * h - lat * lat, 0.01))
    d.set_root([x, y, z], yaw=yaw, pitch=pitch)
    f = hfacing(d)
    for side, off, extra in (("r", off_r, outs[0]), ("l", off_l, outs[1])):
        sg = sgn(side)
        hip = d.pos[side + "_hip"]
        tgt = hip + d.left() * sg * (spread - b["hip_w"] * 0.4) + f * off
        tgt[1] = ya
        a = math.radians(toe_out + extra)
        plant(d, side, tgt, f * math.cos(a) + d.left() * sg * math.sin(a), tol=tol)


# ------------------------------------------------------------------ 예시 2개 (보조 작업이 이 모양을 따라 더 만듦)
@single("hands_on_hips", tags=["hands on own hips", "hands on hips"], ko="두 손 허리에 얹고 서기", arms=True)
def hands_on_hips(d, x=0.0):
    root_stand(d, x)
    stand_legs(d, spread=0.03)
    b = d.b
    for side, sx in (("r", -1), ("l", 1)):
        hip = d.pos[side + "_hip"]
        tgt = hip + UP * (b["torso"] * 0.22) + d.left() * sx * (b["hip_w"] * 0.9 + 0.03)
        arm_to(d, side, tgt, d.left() * sx * 1.0 - d.facing() * 0.3)      # 팔꿈치는 옆으로 벌어짐


@pair("princess_carry", tags=["princess carry"], ko="공주님 안기 (a 가 b 를 두 팔로 가로로 안아 듦: 오른팔은 b 등, 왼팔은 b 무릎 밑)", arms=True, first="carrying")
def princess_carry(a, b):
    ab, bb = a.b, b.b
    root_stand(a, 0.0, drop=0.02)
    legs_stand(a, spread=0.06, toe_out=8)
    a.set_joint("spine", pitch=-5)                                          # 짐을 안아 윗몸이 살짝 뒤로
    a.set_joint("neck", pitch=12, yaw=-20)                                  # b 를 내려다봄
    # b: 반듯이 누운 채 가로로 안김 (머리 = a 의 오른쪽 -x, 다리 = a 의 왼쪽 +x). 골반이 a 의 아랫가슴~윗배 높이, 몸은 a 앞
    by = a.pos["pelvis"][1] + 0.2
    b.set_root([0.06, by, ab["torso_rz"] + bb["hip_w"] + bb["thigh_r"] * 0.9 + 0.012], yaw=90, pitch=-90)
    b.set_joint("neck", pitch=-12, roll=6)                                   # 머리는 a 어깨 쪽으로 기울어 축 처짐
    # b 다리: 허벅지는 a 왼팔 위로 +x 쪽으로, 무릎에서 꺾여 정강이는 아래로 늘어짐
    for side in ("r", "l"):
        hip = b.pos[side + "_hip"]
        via(b, side + "_leg", hip + X3 * (bb["thigh"] * 0.98) - UP * 0.01, -UP + X3 * 0.15)
        foot_floor(b, side, Z3, tol=0.5)
    # b 팔: 왼팔(a 쪽)은 a 목 뒤를 감쌈, 오른팔은 배 위
    arm_to(b, "l", a.pos["r_shoulder"] + np.array([0.03, 0.03, ab["torso_rz"] * 0.9]), np.array([0.0, 1.0, 0.3]))
    mid = (b.pos["spine"] + b.pos["chest"]) / 2 + UP * (bb["torso_rz"] + bb["paw_r"] * 0.7)
    arm_to(b, "r", mid + Z3 * 0.03, UP + Z3 * 0.4)
    # a 팔: 오른팔 = b 등 (어깨뼈 밑), 왼팔 = b 허벅지 밑 (무릎 가까이)
    back_y = by - bb["torso_rz"] - ab["paw_r"] * 0.9
    chest_x = b.pos["chest"][0] * 0.55 + b.pos["spine"][0] * 0.45
    arm_to(a, "r", np.array([chest_x - 0.01, back_y, b.root_pos[2] + 0.01]), -UP + vec(a, "r", out=0.6, fwd=-0.2))
    knee_x = (b.pos["r_knee"][0] + b.pos["l_knee"][0]) / 2
    arm_to(a, "l", np.array([knee_x - 0.1, back_y - 0.015, b.root_pos[2] + 0.0]), -UP + vec(a, "l", out=0.6, fwd=-0.2))
    return [("a 오른손 - b 등(가슴)", (0, "r_wrist"), (1, "chest"), 0.2), ("a 왼손 - b 무릎", (0, "l_wrist"), (1, "l_knee"), 0.22)]


# ================================================================== 혼자 자세: 서서 팔로 하는 동작 (arms=True)
@single("hand_on_hip", tags=["hand on own hip"], ko="한 손 허리에 얹고 서기 (다른 팔은 내림)", arms=True)
def hand_on_hip(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.04)
    b = d.b
    tgt = d.pos["r_hip"] + UP * (b["torso"] * 0.22) - d.left() * (b["hip_w"] * 0.9 + 0.03)
    arm_to(d, "r", tgt, vec(d, "r", out=1.0, fwd=-0.3))                 # 팔꿈치는 옆으로 벌어짐
    hang_arm(d, "l")


@single("arms_up", tags=["arms up"], ko="두 팔을 머리 위로 쭉 (만세)", arms=True)
def arms_up(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.05)
    L = d.b["upper_arm"] + d.b["forearm"]
    for side in ("r", "l"):
        sh = d.pos[side + "_shoulder"]
        arm_to(d, side, sh + UP * L * 0.96 + vec(d, side, out=0.07), vec(d, side, out=1.0, fwd=-0.2))


@single("arm_up", tags=["arm up", "hand up"], ko="한 팔(오른팔)만 위로 번쩍", arms=True)
def arm_up(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.04)
    d.set_joint("spine", roll=-3)                                         # 올린 팔 반대쪽으로 윗몸이 살짝 기움
    L = d.b["upper_arm"] + d.b["forearm"]
    sh = d.pos["r_shoulder"]
    arm_to(d, "r", sh + UP * L * 0.94 + vec(d, "r", out=0.03), vec(d, "r", out=1.0, fwd=0.3))
    hang_arm(d, "l")


@single("waving", tags=["waving"], ko="손 흔들기 (오른손을 머리 옆에, 아래팔은 위로)", arms=True)
def waving(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.04)
    d.set_joint("spine", roll=-2)
    arm_via(d, "r", vec(d, "r", out=0.8, up=-0.15, fwd=0.3), vec(d, "r", out=-0.3, up=1.0, fwd=0.05))
    hang_arm(d, "l")


@single("pointing", tags=["pointing", "pointing forward", "pointing at viewer"], ko="오른팔을 앞(카메라 쪽)으로 쭉 뻗어 가리키기", arms=True)
def pointing(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.05)
    d.set_joint("spine", yaw=12, pitch=3)                                 # 오른 어깨가 앞으로
    d.set_joint("neck", yaw=-12)                                          # 얼굴은 정면
    L = d.b["upper_arm"] + d.b["forearm"]
    sh = d.pos["r_shoulder"]
    arm_to(d, "r", sh + d.facing() * L * 0.97 + UP * 0.015, -UP + vec(d, "r", out=0.4))
    hang_arm(d, "l")


@single("crossed_arms", tags=["crossed arms"], ko="팔짱 (두 아래팔이 가슴 앞에서 엇갈림)", arms=True)
def crossed_arms(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.05)
    b = d.b
    c = d.pos["chest"]
    for side in ("r", "l"):
        s = sgn(side)
        front = 0.03 if side == "r" else 0.0                              # 오른 아래팔이 왼 아래팔 앞
        tgt = c + d.facing() * (b["torso_rz"] + b["arm_r"] * 1.5 + front) - d.left() * s * b["shoulder_w"] * 0.7 \
            - UP * (b["torso"] * 0.3 + front * 0.6)
        arm_to(d, side, tgt, vec(d, side, out=0.4, up=-1.0, fwd=0.2))


@single("hand_on_chin", tags=["hand on own chin"], ko="턱에 손 대고 생각하기 (오른손 턱, 왼팔은 그 팔꿈치를 받침)", arms=True)
def hand_on_chin(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.04)
    b = d.b
    d.set_joint("neck", pitch=4, roll=-5)
    chin = d.pos["head"] + d.facing() * b["head_rz"] * 0.8 - UP * b["head_ry"] * 0.9
    arm_to(d, "r", chin + d.facing() * 0.035 - UP * 0.025 - d.left() * 0.015, vec(d, "r", out=0.5, up=-1.0, fwd=0.1))
    el = d.pos["r_elbow"]
    arm_to(d, "l", el - UP * (b["arm_r"] + b["paw_r"] * 0.6) + d.facing() * 0.01, vec(d, "l", out=0.3, up=-1.0, fwd=-0.2))


@single("salute", tags=["salute"], ko="경례 (오른손을 이마 옆에, 차렷)", arms=True)
def salute(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.0, toe_out=18)
    b = d.b
    brow = d.pos["head"] + d.facing() * b["head_rz"] * 0.8 + UP * b["head_ry"] * 0.3 - d.left() * b["head_rx"] * 0.8
    arm_to(d, "r", brow + d.facing() * 0.03 - d.left() * 0.03 - UP * 0.01, vec(d, "r", out=1.0, up=-0.15, fwd=-0.1))
    hang_arm(d, "l", out=0.01)


@single("stretching", tags=["stretching"], ko="기지개 (두 팔을 머리 위로 모으고 등을 살짝 젖힘)", arms=True)
def stretching(d, x=0.0):
    root_stand(d, x, z=0.0)
    legs_stand(d, spread=0.06)
    d.set_joint("spine", pitch=-9)
    d.set_joint("neck", pitch=-6)
    top = d.pos["chest"] + UP * aspan(d) * 0.84 - hfacing(d) * 0.02
    for side in ("r", "l"):
        arm_to(d, side, top + d.left() * sgn(side) * 0.025, vec(d, side, out=1.0, fwd=-0.3))


@single("outstretched_arms", tags=["outstretched arms", "spread arms"], ko="두 팔을 옆으로 쭉 벌리기", arms=True)
def outstretched_arms(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.07)
    d.set_joint("spine", pitch=-3)
    d.set_joint("neck", pitch=-2)
    L = d.b["upper_arm"] + d.b["forearm"]
    for side in ("r", "l"):
        arm_to(d, side, d.pos[side + "_shoulder"] + vec(d, side, out=L * 0.98, up=0.03), vec(d, side, up=-0.4, fwd=-0.6))


@single("reaching", tags=["reaching", "reaching towards viewer"], ko="한 팔(오른팔)을 앞 위로 뻗기 (윗몸을 살짝 기울이고 왼팔은 뒤로)", arms=True)
def reaching(d, x=0.0):
    stance(d, x, off_r=0.0, off_l=0.07, spread=0.04)
    d.set_joint("spine", yaw=12, pitch=11)
    d.set_joint("neck", yaw=-12, pitch=-10)
    L = d.b["upper_arm"] + d.b["forearm"]
    reach = unit(hfacing(d) * 0.93 + UP * 0.37)
    arm_to(d, "r", d.pos["r_shoulder"] + reach * L * 0.98, -UP * 0.6 + vec(d, "r", out=0.5))
    back = unit(vec(d, "l", out=0.25, up=-0.8, fwd=-0.5))
    arm_to(d, "l", d.pos["l_shoulder"] + back * L * 0.92, vec(d, "l", out=0.6, up=-0.2, fwd=-0.5))


@single("hands_in_pockets", tags=["hands in pockets"], ko="두 손을 바지 앞주머니에 넣고 서기", arms=True)
def hands_in_pockets(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.05)
    d.set_joint("spine", pitch=3)
    d.set_joint("neck", pitch=-3)
    b = d.b
    for side in ("r", "l"):
        pocket = d.pos["pelvis"] + d.left() * sgn(side) * (b["hip_w"] + 0.045) + hfacing(d) * (b["torso_rz"] + 0.005) - UP * 0.02
        arm_to(d, side, pocket, vec(d, side, out=0.7, up=-0.2, fwd=-0.7))          # 팔꿈치는 살짝 뒤·바깥


@single("arms_behind_back", tags=["arms behind back"], ko="두 손을 허리 뒤로 깍지", arms=True)
def arms_behind_back(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.05)
    d.set_joint("spine", pitch=-3)
    b = d.b
    for side in ("r", "l"):
        tgt = d.pos["pelvis"] + UP * (b["torso"] * 0.12) - hfacing(d) * (b["torso_rz"] + b["paw_r"] * 0.9) + d.left() * sgn(side) * 0.025
        arm_to(d, side, tgt, vec(d, side, out=0.8, up=-0.1, fwd=-0.6))


@single("arms_behind_head", tags=["arms behind head"], ko="두 손을 머리 뒤로, 팔꿈치는 옆으로 벌림", arms=True)
def arms_behind_head(d, x=0.0):
    root_stand(d, x)
    legs_stand(d, spread=0.06)
    d.set_joint("spine", pitch=-2)
    b = d.b
    for side in ("r", "l"):
        tgt = d.pos["head"] - hfacing(d) * (b["head_rz"] + 0.025) + d.left() * sgn(side) * 0.035 - UP * 0.005
        arm_to(d, side, tgt, vec(d, side, out=1.0, up=0.15, fwd=0.45))


@single("leaning_forward", tags=["leaning forward"], ko="윗몸을 앞으로 숙이기 (엉덩이는 뒤로, 무릎 살짝 굽힘)", arms=False)
def leaning_forward(d, x=0.0):
    stance(d, x, off_r=0.1, off_l=0.1, spread=0.05, pitch=13)
    d.set_joint("spine", pitch=15)
    d.set_joint("neck", pitch=-20)                                        # 고개는 들어 앞을 봄


@single("bowing", tags=["bowing"], ko="공손히 허리 숙여 인사 (약 40도)", arms=False)
def bowing(d, x=0.0):
    stance(d, x, off_r=0.08, off_l=0.08, spread=0.0, pitch=20, straight=0.995, toe_out=12)
    d.set_joint("spine", pitch=20)
    d.set_joint("neck", pitch=5)


# ================================================================== 혼자 자세: 서서 몸 전체로 하는 동작 (arms=False 는 팔을 뺌)
@single("contrapposto", tags=["contrapposto"], ko="한 다리에 체중을 싣고 서기 (골반 기울고 다른 무릎은 살짝 굽힘)", arms=False)
def contrapposto(d, x=0.0):
    b = d.b
    ya = b["foot_r"] * 1.1
    roll = -7.0                                                           # 오른 엉덩이가 올라감 (체중 다리)
    hc = b["hip_w"] * math.sin(math.radians(-roll))
    H = ya + b["shin"] + math.sqrt(b["thigh"] ** 2 - 0.03 ** 2)          # 오른다리(체중): 정강이 수직, 무릎은 거의 곧게
    d.set_root([x - 0.04, H - hc, 0.0], roll=roll)                        # 골반이 체중 발 쪽으로 쏠림
    d.set_joint("spine", roll=11)                                         # 어깨는 반대로 기울어 S 자
    d.set_joint("neck", roll=-4)
    X, F = np.array([1.0, 0, 0]), hfacing(d)
    t = d.pos["r_hip"].copy(); t[1] = ya
    plant(d, "r", t + X * 0.04 + F * 0.03, F)
    t = d.pos["l_hip"].copy(); t[1] = ya
    plant(d, "l", t + X * 0.12 + F * 0.03, F + X * 0.25, tol=0.03)         # 왼발은 옆·앞에 가볍게, 무릎 굽힘


@single("walking", tags=["walking"], ko="걷기 (한 걸음: 왼발이 앞 뒤꿈치 닿음, 오른발은 뒤에서 뒤꿈치 듦)", arms=False)
def walking(d, x=0.0):
    stance(d, x, off_r=-0.11, off_l=0.15, spread=0.02, straight=0.985, toe_out=3, tol=0.022)
    d.set_joint("spine", pitch=3, yaw=6)                                  # 다리와 어깨는 엇갈려 돎


@single("standing_on_one_leg", tags=["standing on one leg"], ko="한 다리로 서기 (왼 무릎을 앞으로 들어 올림)", arms=False)
def standing_on_one_leg(d, x=0.0):
    b = d.b
    ya = b["foot_r"] * 1.1
    H = ya + b["shin"] + math.sqrt(b["thigh"] ** 2 - 0.03 ** 2)
    d.set_root([x - 0.05, H, 0.0])
    d.set_joint("spine", pitch=-3)
    X, F = np.array([1.0, 0, 0]), hfacing(d)
    t = d.pos["r_hip"].copy(); t[1] = ya
    plant(d, "r", t + X * 0.065 + F * 0.03, F)                            # 서 있는 다리는 골반 아래로 살짝 모음
    hl = d.pos["l_hip"]
    via(d, "l_leg", hl + F * 0.22 + UP * 0.075, -UP - F * 0.2)            # 무릎은 엉덩이 높이 앞, 정강이는 아래로


@single("fighting_stance", tags=["fighting stance"], ko="싸움 자세 (복싱 가드: 왼발 앞, 몸을 비스듬히, 두 주먹을 턱 앞에, 뒤꿈치 듦)", arms=True)
def fighting_stance(d, x=0.0):
    stance(d, x, off_r=-0.08, off_l=0.11, spread=0.085, yaw=-32, toe_out=0.0, outs=(35.0, -5.0), tol=0.022)
    d.set_joint("spine", pitch=8, yaw=8)
    d.set_joint("neck", pitch=6, yaw=14)                                  # 턱을 당기고 정면(카메라 쪽)을 봄
    f = hfacing(d)
    head = d.pos["head"]
    arm_to(d, "l", head + f * 0.13 - UP * 0.05 + d.left() * 0.02, -UP + vec(d, "l", out=0.3))      # 앞손
    arm_to(d, "r", head + f * 0.075 - UP * 0.075 - d.left() * 0.015, -UP + vec(d, "r", out=0.2))   # 뒷손은 턱 옆


@single("kicking", tags=["kicking"], ko="앞차기 (오른발 지지, 왼다리를 허리 높이로 차올림, 윗몸은 살짝 뒤로)", arms=False)
def kicking(d, x=0.0):
    b = d.b
    ya = b["foot_r"] * 1.1
    H = ya + b["shin"] + math.sqrt(b["thigh"] ** 2 - 0.03 ** 2)
    d.set_root([x - 0.02, H, -0.03])
    d.set_joint("spine", pitch=-12)
    d.set_joint("neck", pitch=10)
    X, F = np.array([1.0, 0, 0]), hfacing(d)
    t = d.pos["r_hip"].copy(); t[1] = ya
    plant(d, "r", t + X * 0.03 + F * 0.03, F)                             # 지지 다리: 무릎 살짝 굽힘
    t = d.pos["l_hip"] + (F * 0.42 + UP * 0.12) * kscale(d)
    d.solve_limb("l_leg", t, UP + F * 0.2)                                # 차는 다리: 무릎이 위로 (거의 폄)


@single("dancing", tags=["dancing"], ko="춤 (왼다리에 체중, 오른발은 옆으로 내딛고, 오른팔 위로·왼손 허리, 몸이 기욺)", arms=True)
def dancing(d, x=0.0):
    b = d.b
    ya = b["foot_r"] * 1.1
    H = ya + b["shin"] + math.sqrt(b["thigh"] ** 2 - 0.045 ** 2)
    hc = b["hip_w"] * math.sin(math.radians(6))
    d.set_root([x + 0.045, H - hc, 0.0], roll=6.0)                        # 왼 엉덩이가 올라감 (체중 왼다리)
    d.set_joint("spine", roll=-14, yaw=-8)                                # 윗몸은 오른쪽으로 굽음
    d.set_joint("neck", roll=8, yaw=8)
    X, F = np.array([1.0, 0, 0]), hfacing(d)
    t = d.pos["l_hip"].copy(); t[1] = ya
    plant(d, "l", t - X * 0.035 + F * 0.045, F + X * 0.2)
    t = d.pos["r_hip"].copy(); t[1] = ya
    plant(d, "r", t - X * 0.17 + F * 0.03, F - X * 0.3)                   # 오른발은 옆으로 내딛어 발끝만 닿음
    arm_to(d, "r", d.pos["r_shoulder"] + unit(vec(d, "r", out=0.55, up=1.0, fwd=0.15)) * aspan(d) * 0.94, vec(d, "r", out=0.8, fwd=-0.3))
    tgt = d.pos["l_hip"] + UP * (b["torso"] * 0.2) + X * (b["hip_w"] * 0.9 + 0.03)
    arm_to(d, "l", tgt, X * 1.0 - F * 0.3)


@single("falling", tags=["falling"], ko="뒤로 넘어지며 떨어지는 중 (공중에서 팔다리를 벌림)", arms=False, base=None)
def falling(d, x=0.0):
    d.set_root([x, 0.7, -0.02], pitch=-54)                               # 몸이 뒤로 눕는 중 (머리가 뒤쪽)
    d.set_joint("spine", pitch=-6)
    d.set_joint("neck", pitch=-12)
    hr, hl = d.pos["r_hip"], d.pos["l_hip"]
    k = kscale(d)
    via(d, "r_leg", hr + np.array([-0.04, 0.12, 0.2]) * k, np.array([-0.2, -0.7, -0.3]))      # 오른다리: 무릎을 굽혀 공중에 흔들림
    d.solve_limb("l_leg", hl + np.array([0.1, 0.24, 0.4]) * k, np.array([0.0, 1.0, -0.3]))    # 왼다리: 앞위로 거의 쭉 (벌림)


# ================================================================== 혼자 자세: 바닥 (base=None 은 태그 자체가 바탕 자세)
X3 = np.array([1.0, 0, 0])
Z3 = np.array([0, 0, 1.0])


def foot_inward(d, side):
    """발을 바닥에 눕혀 안쪽으로 (정강이가 바닥에 깔린 자세에서 발이 땅 밑으로 안 들어가게)"""
    foot_floor(d, side, -X3 * sgn(side))


def seiza_legs(d, x, Hh=0.115):
    """정좌 다리 (골반 높이 Hh): 무릎은 바닥, 허벅지는 앞으로, 정강이는 바닥을 따라 뒤로 (발뒤꿈치 위에 앉음)"""
    b = d.b
    d.set_root([x, Hh, 0.0])
    ky = b["thigh_r"] * 0.95                                              # 무릎 높이 (허벅지가 바닥에 닿음)
    zk = math.sqrt(b["thigh"] ** 2 - (Hh - ky) ** 2)                      # 무릎은 바닥, 허벅지는 앞으로
    for side in ("r", "l"):
        sg = sgn(side)
        hip = d.pos[side + "_hip"]
        knee = hip + np.array([sg * 0.014, ky - Hh, zk])
        via(d, side + "_leg", knee, np.array([-sg * 0.14, -0.08, -1.0]))     # 정강이는 바닥을 따라 뒤로, 발목이 모임
        foot_floor(d, side, -X3 * sg)


@single("seiza", tags=["seiza"], ko="정좌 (무릎 꿇고 발뒤꿈치 위에 앉기, 등 곧게)", arms=False, base=None)
def seiza(d, x=0.0):
    seiza_legs(d, x)


@single("indian_style", tags=["indian style"], ko="책상다리 (바닥에 앉아 다리를 앞에서 엇갈림)", arms=False, base=None)
def indian_style(d, x=0.0):
    d.set_root([x, 0.078, 0.0], pitch=8)
    d.set_joint("spine", pitch=-4)
    for side, ank in (("r", np.array([0.03, 0.035, 0.13])), ("l", np.array([-0.03, 0.09, 0.20]))):    # 왼 정강이가 오른 정강이 위·앞
        sg = sgn(side)
        hip = d.pos[side + "_hip"]
        knee = hip + np.array([sg * 0.11, -0.025, 0.215])                 # 무릎은 옆·앞으로 벌림
        tgt = np.array([x + ank[0], ank[1], ank[2]])
        d.solve_limb(side + "_leg", tgt, knee - (hip + tgt) / 2)
        foot_floor(d, side, -Z3)


@single("wariza", tags=["wariza"], ko="와리자 (W 자 앉기: 무릎은 앞에 모으고 발은 엉덩이 양옆 바닥)", arms=False, base=None)
def wariza(d, x=0.0):
    b = d.b
    d.set_root([x, 0.072, 0.0])
    d.set_joint("spine", pitch=2)
    for side in ("r", "l"):
        sg = sgn(side)
        hip = d.pos[side + "_hip"]
        ank = np.array([x + sg * 0.165, b["foot_r"] * 1.1, 0.03])
        knee = hip + np.array([-sg * 0.014, -0.017, 0.243])
        d.solve_limb(side + "_leg", ank, knee - (hip + ank) / 2)
        foot_floor(d, side, X3 * (-sg) * 0.89 - Z3 * 0.44)               # 발끝은 안쪽 뒤 (바닥에 평평)


def _lie_side(d, x):
    """오른쪽 옆구리를 바닥에 대고 누움 (머리 = -x 쪽, 얼굴·배 = 카메라(+z) 쪽). 골반 = 오른 엉덩이가 바닥에 닿는 높이"""
    b = d.b
    d.set_root([x, b["hip_w"] + b["thigh_r"] + 0.0, 0.0], roll=90)


def _chest_down(d, roll, pitch=6):
    """옆으로 누운 윗몸: 가슴이 바닥 쪽으로 기울되(roll) 어깨 관절이 바닥 밑으로 안 들어가는 만큼만"""
    for r in range(int(roll), -1, -1):
        d.set_joint("spine", pitch=pitch, roll=r)
        if d.pos["r_shoulder"][1] >= d.b["arm_r"] * 0.9 and d.pos["chest"][1] >= d.b["arm_r"]:
            break


@single("on_side", tags=["on side"], ko="옆으로 누워 쉬기 (무릎을 살짝 굽히고 머리는 아랫팔 위)", arms=False, base=None)
def on_side(d, x=0.0):
    b = d.b
    _lie_side(d, x)
    _chest_down(d, 8)
    d.set_joint("neck", roll=-6)
    hr, hl = d.pos["r_hip"], d.pos["l_hip"]
    ya = b["foot_r"] * 1.1
    k = kscale(d)
    # 아래 다리 (오른쪽): 바닥에, 위 다리 (왼쪽): 아래 다리 위에 조금 더 굽혀 앞으로
    tr = np.array([hr[0] + 0.44 * k, ya, hr[2] - 0.03])
    d.solve_limb("r_leg", tr, Z3)
    tl = np.array([hl[0] + 0.39 * k, ya + 0.07, hl[2] + 0.02])
    d.solve_limb("l_leg", tl, Z3)
    for side in ("r", "l"):
        foot_floor(d, side, Z3)                                            # 발은 바닥과 나란히 눕힘 (발끝은 배 쪽)


@single("fetal_position", tags=["fetal position"], ko="태아 자세 (옆으로 누워 무릎을 가슴 쪽으로 당기고 몸을 동그랗게 말기)", arms=False, base=None)
def fetal_position(d, x=0.0):
    b = d.b
    _lie_side(d, x)
    _chest_down(d, 6, pitch=36)
    d.set_joint("neck", pitch=22, roll=-5)
    for side, dk, ds in (("r", np.array([-0.25, 0.0, 0.97]), np.array([0.55, 0.0, -0.65])),
                         ("l", np.array([-0.3, -0.12, 0.94]), np.array([0.5, -0.3, -0.6]))):
        hip = d.pos[side + "_hip"]
        via(d, side + "_leg", hip + unit(dk) * b["thigh"], ds)
        foot_floor(d, side, Z3)


@single("all_fours", tags=["all fours"], ko="네발로 엎드리기 (두 손과 두 무릎으로 몸을 받침, 고개는 앞)", arms=True, base=None)
def all_fours(d, x=0.0):
    b = d.b
    d.set_root([x, b["thigh"] + b["thigh_r"] * 0.95 + 0.0, 0.0], pitch=90)       # 엎드림: 머리가 +z (카메라 쪽)
    d.set_joint("spine", pitch=-10)
    d.set_joint("neck", pitch=-44)                                                  # 고개를 들어 앞을 봄
    ky = b["thigh_r"] * 0.95
    for side in ("r", "l"):
        sg = sgn(side)
        hip = d.pos[side + "_hip"]
        via(d, side + "_leg", np.array([hip[0] + sg * 0.018, ky, hip[2] + 0.02]), -Z3)   # 허벅지는 수직, 정강이는 바닥에 뒤로
        foot_floor(d, side, -X3 * sg)
    for side in ("r", "l"):
        sg = sgn(side)
        sh = d.pos[side + "_shoulder"]
        tgt = np.array([sh[0] + sg * 0.01, b["paw_r"] * 1.05, sh[2] + 0.05])
        d.solve_limb(side + "_arm", tgt, np.array([sg * 0.5, 0.3, -1.0]))             # 팔꿈치는 뒤·바깥으로 살짝 굽음


@single("on_one_knee", tags=["on one knee"], ko="한쪽 무릎 꿇기 (오른 무릎은 바닥, 왼발은 앞에 디딤, 윗몸 곧게)", arms=False, base=None)
def on_one_knee(d, x=0.0):
    b = d.b
    ky = b["thigh_r"] * 0.95
    back = 0.06                                                          # 오른 무릎은 엉덩이보다 살짝 뒤
    H = ky + math.sqrt(b["thigh"] ** 2 - back ** 2)
    d.set_root([x, H, 0.0])
    d.set_joint("spine", pitch=5)
    d.set_joint("neck", pitch=-4)
    hr, hl = d.pos["r_hip"], d.pos["l_hip"]
    via(d, "r_leg", np.array([hr[0] - 0.01, ky, hr[2] - back]), -Z3)     # 뒤 무릎은 바닥, 정강이는 바닥에 뒤로
    foot_floor(d, "r", X3)
    via(d, "l_leg", hl + Z3 * b["thigh"] - UP * 0.0, -UP)                # 앞 다리: 허벅지 수평, 정강이 수직
    foot_floor(d, "l", Z3, tol=0.012)


@single("sit_leaning_back", tags=["leaning back"], ko="바닥에 앉아 두 손을 뒤로 짚고 몸을 뒤로 기대기 (다리는 앞으로, 무릎 살짝 굽힘)", arms=True, base="sit_floor")
def sit_leaning_back(d, x=0.0):
    b = d.b
    d.set_root([x, 0.078, 0.0])
    d.set_joint("spine", pitch=-24)
    d.set_joint("neck", pitch=14)
    ya = b["foot_r"] * 1.1
    for side in ("r", "l"):
        sg = sgn(side)
        hip = d.pos[side + "_hip"]
        tgt = np.array([hip[0] + sg * 0.05, ya, hip[2] + 0.455 * kscale(d)])
        d.solve_limb(side + "_leg", tgt, UP + Z3 * 0.2)
        foot_floor(d, side, UP, tol=0.012)
    for side in ("r", "l"):
        sg = sgn(side)
        sh = d.pos[side + "_shoulder"]
        tgt = np.array([sh[0] + sg * 0.035, b["paw_r"] * 1.05, sh[2] - 0.045])
        d.solve_limb(side + "_arm", tgt, np.array([sg * 0.4, 0.0, -1.0]))     # 손은 엉덩이 뒤 옆 바닥, 팔꿈치는 거의 폄


@single("lie_arms_behind_head", tags=["arms behind head"], ko="반듯이 누워 두 손을 머리 뒤에 (한쪽 무릎 세움)", arms=True, base="lie_back")
def lie_arms_behind_head(d, x=0.0):
    b = d.b
    d.set_root([x, b["torso_rz"] + 0.01, 0.0], pitch=-90)                 # 반듯이 누움 (머리 -z, 발 +z = 카메라 쪽)
    d.set_joint("neck", pitch=18)                                         # 머리가 손 위에 얹혀 살짝 들림
    hr, hl = d.pos["r_hip"], d.pos["l_hip"]
    L = b["thigh"] + b["shin"]
    d.solve_limb("r_leg", hr + Z3 * L * 0.96 - X3 * 0.03, UP)             # 오른다리 곧게
    ya = b["foot_r"] * 1.1
    d.solve_limb("l_leg", np.array([hl[0] + 0.03, ya, hl[2] + 0.2]), UP + Z3 * 0.3)     # 왼 무릎 세우고 발은 바닥
    foot_floor(d, "r", Z3)
    foot_floor(d, "l", Z3, tol=0.012)
    head = d.pos["head"]
    for side in ("r", "l"):
        sg = sgn(side)
        tgt = np.array([head[0] + sg * 0.04, 0.04, head[2] - 0.055])
        d.solve_limb(side + "_arm", tgt, np.array([sg * 1.0, 0.1, 0.1]))   # 팔꿈치는 옆 바닥으로 벌어짐


# ================================================================== 두 사람 자세 (a = 오른쪽·큰 사람, b = 왼쪽·작은 사람)
@pair("headpat", tags=["headpat"], ko="머리 쓰다듬기 (a 가 오른손을 b 머리 위에 얹음, 서로 살짝 마주 봄)", arms=True)
def headpat(a, b):
    ab, bb = a.b, b.b
    root_stand(a, 0.2, yaw=-22)
    legs_stand(a, spread=0.05, toe_out=0)
    root_stand(b, -0.14, yaw=22)
    legs_stand(b, spread=0.04, toe_out=0)
    a.set_joint("spine", pitch=4, roll=4)
    a.set_joint("neck", pitch=14, yaw=10)                                   # 내려다봄
    b.set_joint("neck", pitch=-14, yaw=-10)                                 # 올려다봄
    top = b.pos["head"] + UP * (bb["head_ry"] + 0.025)
    arm_reach(a, "r", top + X3 * 0.045, vec(a, "r", out=0.6, up=-0.3, fwd=-0.5))                 # 손목은 머리 꼭대기 조금 a 쪽
    hang_arm(a, "l")
    hang_arm(b, "r")
    hang_arm(b, "l")
    return [("a 오른손 - b 머리", (0, "r_wrist"), (1, "head"), 0.2)]


@pair("arm_hug", tags=["arm hug"], ko="팔에 매달리기 (b 가 a 의 오른팔을 두 팔로 껴안고 어깨에 기댐)", arms=True, actor="b")
def arm_hug(a, b):
    ab, bb = a.b, b.b
    root_stand(a, 0.15, yaw=-6)
    legs_stand(a, spread=0.05, toe_out=0)
    root_stand(b, -0.14, yaw=8)
    legs_stand(b, spread=0.04, toe_out=0)
    a.set_joint("neck", roll=4)
    b.set_joint("spine", roll=-5)                                           # a 쪽으로 기댐
    b.set_joint("neck", roll=-12, pitch=2)
    # a 의 오른팔은 살짝 굽혀 안긴 채
    el = a.pos["r_shoulder"] + np.array([0.0, -ab["upper_arm"] * 0.97, 0.0]) + X3 * 0.012
    arm_to(a, "r", el + np.array([0.01, -ab["forearm"] * 0.9, 0.05]), np.array([0, -0.4, -1.0]))
    hang_arm(a, "l")
    # b 의 두 팔이 a 의 오른 위팔을 감쌈: 왼손은 뒤, 오른손은 앞으로 가슴 앞을 가로질러
    mid = (a.pos["r_shoulder"] + a.pos["r_elbow"]) / 2
    arm_to(b, "l", mid + np.array([0.0, -0.02, -0.045]), np.array([0.2, -1.0, -0.6]))
    arm_to(b, "r", mid + np.array([0.0, -0.05, 0.05]), np.array([-0.5, -1.0, 0.3]))
    return [("b 왼손 - a 오른 위팔", (1, "l_wrist"), (0, "r_elbow"), 0.17),
            ("b 오른손 - a 오른 위팔", (1, "r_wrist"), (0, "r_elbow"), 0.2)]


@pair("head_on_shoulder", tags=["head on another's shoulder"], ko="나란히 바닥에 앉아 b 가 a 어깨에 머리를 기댐", arms=True, actor="b")
def head_on_shoulder(a, b):
    ab, bb = a.b, b.b
    for d, x in ((a, 0.13), (b, -0.12)):
        d.set_root([x, 0.078, 0.0])
        d.set_joint("spine", pitch=-6)
    a.set_joint("neck", roll=-2, pitch=5, yaw=-22)                          # b 를 내려다봄 (머리는 b 쪽으로 기울이지 않음: 머리끼리 겹침 방지)
    # b 윗몸을 a 쪽으로 기울여 머리가 a 오른 어깨 바로 위(안쪽 조금)에 오게
    goal = a.pos["r_shoulder"] + X3 * 0.012 + UP * (ab["arm_r"] + bb["head_rx"] * 0.9)
    b.set_joint("neck", roll=-14, pitch=4)
    for roll in range(0, -34, -1):
        b.set_joint("spine", pitch=-6, roll=roll)
        if b.pos["head"][0] >= goal[0]:
            break
    for d in (a, b):
        for side in ("r", "l"):
            sg = sgn(side)
            hip = d.pos[side + "_hip"]
            tgt = np.array([hip[0] + sg * 0.03, d.b["foot_r"] * 1.1, hip[2] + 0.44 * (d.b["thigh"] / ab["thigh"])])
            d.solve_limb(side + "_leg", tgt, UP + Z3 * 0.2)
            foot_floor(d, side, UP, tol=0.012)
    # 손은 허벅지 위 (붙은 쪽 팔은 몸 옆으로)
    for d in (a, b):
        for side in ("r", "l"):
            thigh_mid = (d.pos[side + "_hip"] + d.pos[side + "_knee"]) / 2
            arm_to(d, side, thigh_mid + UP * (d.b["thigh_r"] + d.b["paw_r"] * 0.6), vec(d, side, out=0.5, up=-0.3, fwd=-0.6))
    return [("b 머리 - a 오른 어깨", (1, "head"), (0, "r_shoulder"), 0.14)]


@pair("hug_from_behind", tags=["hug from behind"], ko="뒤에서 안기 (a 가 b 뒤에서 두 팔로 가슴 아래를 감쌈, 둘 다 앞을 봄)", arms=True)
def hug_from_behind(a, b):
    ab, bb = a.b, b.b
    gap = ab["torso_rz"] + bb["torso_rz"] + 0.012
    root_stand(b, -0.03, z=0.0)
    legs_stand(b, spread=0.04)
    root_stand(a, 0.035, z=-gap)
    legs_stand(a, spread=0.04)
    a.set_joint("spine", pitch=5)
    a.set_joint("neck", pitch=-3, roll=9)                                    # 뺨을 b 머리 쪽으로
    b.set_joint("neck", roll=-4)
    # a 의 두 손: b 가슴 아래 앞에서 모음 (오른손이 위)
    front = b.pos["chest"] - UP * (bb["torso"] * 0.3)
    for side in ("r", "l"):
        sg = sgn(side)
        tgt = front + Z3 * (bb["torso_rz"] + ab["arm_r"] + 0.012) + X3 * sg * 0.06       # 손은 b 몸 앞 양옆 (팔꿈치가 b 팔과 안 겹치게 바깥으로)
        arm_to(a, side, tgt, vec(a, side, out=1.0, up=-0.2, fwd=0.2))
    # b 의 두 손: 같은 쪽 a 의 아래팔 위에 얹음
    for side in ("r", "l"):
        tgt = a.pos[side + "_wrist"] + UP * (ab["arm_r"] + bb["paw_r"] * 0.6) - X3 * sgn(side) * 0.02 + Z3 * 0.01
        arm_to(b, side, tgt, vec(b, side, out=0.9, up=-0.3, fwd=0.1))
    return [("a 오른손 - b 가슴", (0, "r_wrist"), (1, "chest"), 0.2), ("a 왼손 - b 가슴", (0, "l_wrist"), (1, "chest"), 0.2),
            ("a 오른손 - b 오른손", (0, "r_wrist"), (1, "r_wrist"), 0.15)]


def _hand_gap(d, side, target_y, target_z, k=0.9):
    """손목을 (x 0, target_y, target_z) 에 두려면 어깨가 수평으로 얼마나 떨어져야 하나 (팔 길이 x k 로 뻗을 때)"""
    sh = d.pos[side + "_shoulder"]
    L = (d.b["upper_arm"] + d.b["forearm"]) * k
    dy, dz = sh[1] - target_y, sh[2] - target_z
    return math.sqrt(max(L * L - dy * dy - dz * dz, 0.0004))


def _face_off(a, b, y_m, k, spread=0.05):
    """마주 서기: a 는 +x 에서 -x 를 보고(yaw -90), b 는 -x 에서 +x 를 봄. 두 오른손이 (0, y_m, 0) 근처에서 만나도록 간격을 정함"""
    for d, yaw in ((a, -90), (b, 90)):
        root_stand(d, 0.0, yaw=yaw)
    ga = _hand_gap(a, "r", y_m, 0.0, k)
    gb = _hand_gap(b, "r", y_m, 0.0, k)
    root_stand(a, ga, yaw=-90)
    root_stand(b, -gb, yaw=90)
    legs_stand(a, spread=spread, toe_out=4)
    legs_stand(b, spread=spread, toe_out=4)


@pair("handshake", tags=["handshake"], ko="악수 (마주 서서 오른손을 맞잡음, 옆에서 보기 좋음)", arms=True)
def handshake(a, b):
    _face_off(a, b, 0.62, 0.86)
    a.set_joint("neck", pitch=8)
    b.set_joint("neck", pitch=-10)
    ab, bb = a.b, b.b
    arm_to(a, "r", np.array([0.014, 0.62, 0.0]), vec(a, "r", out=0.4, up=-1.0))
    arm_to(b, "r", np.array([-0.014, 0.62, 0.0]), vec(b, "r", out=0.4, up=-1.0))
    hang_arm(a, "l")
    hang_arm(b, "l")
    return [("a 오른손 - b 오른손", (0, "r_wrist"), (1, "r_wrist"), 0.1)]


@pair("fist_bump", tags=["fist bump"], ko="주먹 인사 (마주 서서 오른 주먹을 앞으로 맞댐)", arms=True)
def fist_bump(a, b):
    _face_off(a, b, 0.66, 0.96)
    a.set_joint("neck", pitch=8)
    b.set_joint("neck", pitch=-10)
    arm_to(a, "r", np.array([0.046, 0.66, 0.0]), vec(a, "r", out=0.5, up=-1.0))
    arm_to(b, "r", np.array([-0.046, 0.66, 0.0]), vec(b, "r", out=0.5, up=-1.0))
    hang_arm(a, "l")
    hang_arm(b, "l")
    return [("a 오른주먹 - b 오른주먹", (0, "r_wrist"), (1, "r_wrist"), 0.13)]


@pair("arm_around_shoulder", tags=["arm around shoulder", "hand on another's shoulder"], ko="어깨동무 (a 가 오른팔을 b 어깨 너머로 두름, 나란히 앞을 봄)", arms=True)
def arm_around_shoulder(a, b):
    ab, bb = a.b, b.b
    root_stand(a, 0.125, yaw=-4)
    legs_stand(a, spread=0.05, toe_out=0)
    root_stand(b, -0.125, yaw=4)
    legs_stand(b, spread=0.04, toe_out=0)
    a.set_joint("spine", roll=3)                                            # 서로 쪽으로 살짝 기울임
    b.set_joint("spine", roll=-4)
    a.set_joint("neck", roll=4)
    b.set_joint("neck", roll=-6)
    tgt = b.pos["r_shoulder"] + UP * (bb["arm_r"] + ab["paw_r"] * 0.6) + Z3 * 0.0
    arm_to(a, "r", tgt, np.array([0.0, 0.5, -1.0]))                         # 팔꿈치는 b 목 뒤로
    hang_arm(a, "l")
    side = a.pos["pelvis"] - X3 * (ab["hip_w"] + 0.045) + UP * 0.03
    arm_to(b, "l", side, vec(b, "l", out=0.5, up=-1.0, fwd=-0.3))           # b 왼손은 a 허리 옆
    hang_arm(b, "r")
    return [("a 오른손 - b 오른 어깨", (0, "r_wrist"), (1, "r_shoulder"), 0.1), ("b 왼손 - a 허리", (1, "l_wrist"), (0, "pelvis"), 0.17)]


@pair("lap_pillow", tags=["lap pillow"], ko="무릎베개 (a 는 정좌로 앉고, b 는 반듯이 누워 머리를 a 허벅지에 얹음)", arms=True, first="sitting")
def lap_pillow(a, b):
    ab, bb = a.b, b.b
    ax = 0.12
    seiza_legs(a, ax)
    a.set_joint("spine", pitch=4)
    # b: 반듯이 누움, 머리가 +x 쪽 (yaw -90 + pitch -90), 몸은 -x 쪽으로 뻗음
    goal = np.array([ax - 0.04, 0.0, 0.14])
    goal[1] = a.pos["r_hip"][1] - 0.045 + ab["thigh_r"] + bb["head_rz"] * 0.9
    b.set_root([0.0, bb["torso_rz"] + 0.01, 0.0], yaw=-90, pitch=-90)
    for sp in range(0, 46, 1):
        b.set_joint("spine", pitch=sp * 0.6)
        b.set_joint("neck", pitch=sp * 0.45)
        if b.pos["head"][1] >= goal[1]:
            break
    off = goal - b.pos["head"]
    b.set_root([off[0], bb["torso_rz"] + 0.01, off[2]], yaw=-90, pitch=-90)
    hr, hl = b.pos["r_hip"], b.pos["l_hip"]
    L = bb["thigh"] + bb["shin"]
    b.solve_limb("r_leg", hr - X3 * L * 0.96, UP)
    b.solve_limb("l_leg", hl - X3 * L * 0.9 + Z3 * 0.02, UP + Z3 * 0.5)
    foot_floor(b, "r", Z3, tol=0.012)
    foot_floor(b, "l", Z3, tol=0.012)
    # b 손: 배 위에 포갬 (몸이 보는 쪽 = 위)
    up_b = b.frame["spine"] @ Z3
    mid = (b.pos["spine"] + b.pos["chest"]) / 2 + up_b * (bb["torso_rz"] + bb["paw_r"] * 0.7)
    arm_to(b, "r", mid + Z3 * 0.03, UP + Z3 * 0.5)
    arm_to(b, "l", mid - Z3 * 0.02 - X3 * 0.02, UP - Z3 * 0.5)
    # a: 오른손은 b 이마·머리카락 쪽, 왼손은 자기 허벅지, 고개를 숙여 b 를 봄
    a.set_joint("neck", pitch=28, yaw=-30)
    head = b.pos["head"]
    arm_to(a, "r", head + UP * (bb["head_rz"] + 0.012) + X3 * 0.03 - Z3 * 0.03, vec(a, "r", out=0.8, up=-0.5, fwd=0.3))
    thigh_mid = (a.pos["l_hip"] + a.pos["l_knee"]) / 2
    arm_to(a, "l", thigh_mid + UP * (ab["thigh_r"] + ab["paw_r"] * 0.6), vec(a, "l", out=0.5, up=-0.3, fwd=-0.6))
    return [("b 머리 - a 허벅지", (1, "head"), (0, "r_hip"), 0.2), ("a 오른손 - b 머리", (0, "r_wrist"), (1, "head"), 0.15)]


def _push_stance(d, x, yaw):
    """등 미는 사람(a) 자세: 앞발(왼) 앞, 뒷발(오른) 곧게 뒤로 뻗어 밀어냄, 윗몸이 앞으로 기욺"""
    stance(d, x, off_r=-0.2, off_l=0.1, spread=0.04, yaw=yaw, pitch=8, straight=0.98, toe_out=4, tol=0.022)
    d.set_joint("spine", pitch=14)
    d.set_joint("neck", pitch=-14)


@pair("pushing", tags=["pushing"], ko="등 밀기 (a 가 두 손으로 b 의 등을 밀며 둘 다 앞으로 기울어 -x 쪽으로 걸음)", arms=True)
def pushing(a, b):
    ab, bb = a.b, b.b
    # b: 앞으로 걸어감 (-x 를 봄), 윗몸을 살짝 숙임
    stance(b, 0.0, off_r=-0.06, off_l=0.11, spread=0.03, yaw=-90, straight=0.985, toe_out=3, tol=0.022)
    b.set_joint("spine", pitch=9)
    b.set_joint("neck", pitch=-7)
    bf = b.frame["spine"] @ Z3
    back = b.pos["spine"] + (b.pos["chest"] - b.pos["spine"]) * 0.62 - bf * (bb["torso_rz"] + 0.012)
    # a: 두 손을 b 등에 대는 거리에 서기 (두 번 풀어 어깨 위치를 알아냄)
    _push_stance(a, 0.6, -90)
    sh = {s_: a.pos[s_ + "_shoulder"] for s_ in ("r", "l")}
    L = (ab["upper_arm"] + ab["forearm"]) * 0.9
    tz = {"r": back[2] - 0.07, "l": back[2] + 0.07}
    gap = min(math.sqrt(max(L * L - (sh[s_][1] - back[1]) ** 2 - (sh[s_][2] - tz[s_]) ** 2, 0.0004)) for s_ in ("r", "l"))
    xs = a.pos["r_shoulder"][0] - a.root_pos[0]
    _push_stance(a, back[0] + gap - xs, -90)
    for s_ in ("r", "l"):
        arm_to(a, s_, np.array([back[0], back[1], tz[s_]]), vec(a, s_, out=0.5, up=-0.8))
    # b 의 팔: 걸음에 맞춰 엇갈려 흔듦 (왼다리 앞이면 오른팔 앞)
    arm_via(b, "r", vec(b, "r", out=0.15, up=-0.6, fwd=0.5), vec(b, "r", up=-0.55, fwd=0.7))
    arm_via(b, "l", vec(b, "l", out=0.2, up=-0.7, fwd=-0.45), vec(b, "l", up=-0.9, fwd=-0.25))
    return [("a 오른손 - b 등", (0, "r_wrist"), (1, "chest"), 0.2), ("a 왼손 - b 등", (0, "l_wrist"), (1, "chest"), 0.2)]


def _run_pose(d, x, lead="l", yaw=-90, high=0.0):
    """달리기 한 걸음 (공중): lead 쪽 다리가 앞으로 올라오고 반대 다리는 뒤로 뻗어 정강이를 접어 올림. 팔은 엇갈려 90도로 굽혀 흔듦"""
    b = d.b
    rear = "r" if lead == "l" else "l"
    d.set_root([x, standing_pelvis_height(b) - 0.03 + high, 0.0], yaw=yaw)
    d.set_joint("spine", pitch=12)
    d.set_joint("neck", pitch=-9)
    f = hfacing(d)
    via(d, lead + "_leg", d.pos[lead + "_hip"] + f * 0.15 - UP * 0.19, -f * 0.5 - UP * 1.0)       # 앞 다리: 허벅지 앞으로, 정강이는 아래·뒤로
    via(d, rear + "_leg", d.pos[rear + "_hip"] - f * 0.07 - UP * 0.225, -f * 1.0 + UP * 0.55)     # 뒷 다리: 뒤로 뻗고 정강이는 접어 올림
    for side in (lead, rear):
        foot_floor(d, side, f, tol=0.5)
    fa, ba = rear, lead                                             # 앞다리와 반대쪽 팔이 앞
    arm_via(d, fa, vec(d, fa, out=0.2, up=-0.45, fwd=0.8), vec(d, fa, up=0.45, fwd=0.9))
    arm_via(d, ba, vec(d, ba, out=0.25, up=-0.55, fwd=-0.8), vec(d, ba, up=-0.85, fwd=-0.25))


@pair("chasing", tags=["chasing"], ko="쫓아가기 (둘 다 -x 쪽으로 달림, a 가 b 뒤에서 앞 팔을 뻗음, b 는 어깨 너머로 돌아봄)", arms=True)
def chasing(a, b):
    ab, bb = a.b, b.b
    _run_pose(b, -0.1, lead="r", high=0.0)
    _run_pose(a, 0.5, lead="l", high=0.01)
    b.set_joint("spine", pitch=12)
    b.set_joint("neck", pitch=-6)
    # a 의 앞 팔(오른팔)은 b 쪽으로 쭉 뻗음
    L = ab["upper_arm"] + ab["forearm"]
    arm_to(a, "r", a.pos["r_shoulder"] + unit(vec(a, "r", fwd=1.0, up=0.12, out=-0.05)) * L * 0.97, -UP + vec(a, "r", out=0.4))
    a.set_joint("neck", pitch=-12)
    return []


@pair("forehead_to_forehead", tags=["forehead-to-forehead", "forehead to forehead"], ko="이마 맞대기 (마주 서서 서로 쪽으로 기울여 이마를 맞대고, 손은 상대 어깨·허리)", arms=True)
def forehead_to_forehead(a, b):
    ab, bb = a.b, b.b
    for d, x, yaw in ((a, 0.13, -90), (b, -0.13, 90)):
        stance(d, x, off_r=-0.005, off_l=-0.005, spread=0.05, yaw=yaw, straight=0.995, toe_out=30)
        d.set_joint("spine", pitch=9)
    gap_h = max(float(a.pos["head"][1] - b.pos["head"][1]), 0.0)                # 키 차이가 크면 큰 쪽이 더 숙임
    a.set_joint("spine", pitch=9 + gap_h * 90)

    def fh(d):
        return d._head_surface([0.0, 0.5, 0.86])

    best = None
    for pa in range(0, 56, 3):
        for pb in range(-45, 1, 3):
            a.set_joint("neck", pitch=pa)
            b.set_joint("neck", pitch=pb)
            dy = abs(float(fh(a)[1] - fh(b)[1])) + 0.0006 * (abs(pa) + abs(pb))
            if best is None or dy < best[0]:
                best = (dy, pa, pb)
    a.set_joint("neck", pitch=best[1])
    b.set_joint("neck", pitch=best[2])
    dx = float(fh(a)[0] - fh(b)[0]) - 0.004                                  # 이마 면이 맞닿게 b 를 옮김
    stance(b, -0.13 + dx, off_r=-0.005, off_l=-0.005, spread=0.05, yaw=90, straight=0.995, toe_out=30)
    # 손: a 는 b 어깨 위, b 는 a 허리 옆 (서로 같은 쪽 z)
    for sa, sb in (("r", "l"), ("l", "r")):
        arm_reach(a, sa, b.pos[sb + "_shoulder"] + UP * (bb["arm_r"] + ab["paw_r"] * 0.5), vec(a, sa, out=0.8, up=-0.4))
        arm_reach(b, sb, a.pos["chest"] - UP * 0.17 + Z3 * (0.115 if sb == "r" else -0.115), vec(b, sb, out=0.6, up=-0.6))
    return [("a 이마 - b 이마", (0, "head"), (1, "head"), 0.18)]


@pair("shoulder_carry", tags=["shoulder carry"], ko="목마 (b 가 a 어깨 위에 앉아 다리를 가슴 앞으로 늘어뜨리고, a 가 b 정강이를 잡음)", arms=True, first="carrying")
def shoulder_carry(a, b):
    ab, bb = a.b, b.b
    root_stand(a, 0.0)
    legs_stand(a, spread=0.07, toe_out=8)
    a.set_joint("neck", pitch=-4)
    # b: 골반은 a 목 뒤 어깨 위 (a 머리 바로 뒤), 윗몸은 곧게
    sh_top = a.pos["chest"][1] + ab["arm_r"] * 0.5
    pelvis = np.array([0.0, sh_top + bb["thigh_r"] * 1.3 + 0.02, -(ab["head_rz"] + bb["torso_rz"] * 0.9)])
    b.set_root(pelvis)
    b.set_joint("spine", pitch=-4)
    b.set_joint("neck", pitch=4)
    # b 다리: 허벅지는 a 머리 양옆을 지나 앞으로, 정강이는 a 가슴 앞으로 늘어뜨림
    for side in ("r", "l"):
        sg = sgn(side)
        hip = b.pos[side + "_hip"]
        knee = hip + np.array([sg * 0.05, -0.045, 0.215])
        via(b, side + "_leg", knee, np.array([sg * 0.05, -1.0, -0.2]))
    # a 손: b 정강이를 잡음, b 손: a 머리 위
    for side in ("r", "l"):
        sg = sgn(side)
        shin_mid = (b.pos[side + "_knee"] + b.pos[side + "_ankle"]) / 2
        arm_to(a, side, shin_mid + Z3 * (bb["shin_r"] + 0.0) + UP * 0.02, vec(a, side, out=0.6, up=-1.0, fwd=-0.2))
        arm_to(b, side, a.pos["head"] + UP * (ab["head_ry"] * 0.7) + X3 * sg * 0.035 + Z3 * 0.01, vec(b, side, out=0.9, up=-0.2, fwd=0.4))
    return [("a 오른손 - b 오른 정강이", (0, "r_wrist"), (1, "r_ankle"), 0.16), ("a 왼손 - b 왼 정강이", (0, "l_wrist"), (1, "l_ankle"), 0.16),
            ("b 엉덩이 - a 어깨", (1, "pelvis"), (0, "chest"), 0.16)]


@pair("carrying_over_shoulder", tags=["carrying over shoulder"], ko="어깨에 둘러메기 (a 가 b 를 오른쪽 어깨에 자루처럼 걸침: b 의 배가 어깨 위, 다리는 앞, 머리·윗몸은 뒤로 늘어짐)", arms=True, first="carrying")
def carrying_over_shoulder(a, b):
    ab, bb = a.b, b.b
    root_stand(a, 0.0)
    legs_stand(a, spread=0.07, toe_out=8)
    a.set_joint("spine", pitch=5, roll=-4)                                  # 짐 반대쪽으로 살짝 기울여 균형
    a.set_joint("neck", pitch=-4)
    S = a.pos["r_shoulder"]
    # b: 엎드린 채 머리가 뒤(-z) — yaw 180 + pitch 80, 허리를 굽혀 윗몸이 등 쪽으로 늘어짐
    b.set_root([S[0], S[1] + 0.1, S[2] + 0.12], yaw=180, pitch=78)
    b.set_joint("spine", pitch=62)
    b.set_joint("neck", pitch=8)
    mid = b.pos["spine"] + (b.pos["chest"] - b.pos["spine"]) * 0.28                # 배(허리쯤)가 어깨 위
    goal = S + UP * (bb["torso_rz"] * 1.0 + ab["arm_r"] + 0.012) - X3 * 0.055 + Z3 * 0.02          # 오른 어깨 위, 바깥쪽으로 조금 (다리가 가슴·목을 안 파고듦)
    b.set_root(b.root_pos + (goal - mid), yaw=180, pitch=78)
    # b 다리: 엉덩이에서 앞 아래로 늘어짐 (무릎 살짝 굽힘)
    for side in ("r", "l"):
        hip = b.pos[side + "_hip"]
        via(b, side + "_leg", hip + np.array([0.0, -0.17, 0.16]), np.array([0.0, -1.0, -0.15]))
        foot_floor(b, side, Z3, tol=0.5)
    # b 팔: 등 쪽으로 축 늘어짐
    for side in ("r", "l"):
        sh = b.pos[side + "_shoulder"]
        arm_to(b, side, sh + np.array([0.0, -0.28, -0.03]), np.array([0.0, 0.0, 1.0]))
    # a: 오른손은 b 허벅지 뒤를 잡고, 왼팔은 편히
    thigh = (b.pos["r_hip"] + b.pos["l_hip"]) / 2 + (b.pos["r_knee"] + b.pos["l_knee"] - b.pos["r_hip"] - b.pos["l_hip"]) / 4
    arm_to(a, "r", thigh + Z3 * (bb["thigh_r"] + 0.0) + UP * 0.0, vec(a, "r", out=0.5, up=-1.0, fwd=-0.3))
    hang_arm(a, "l")
    return [("a 오른어깨 - b 배", (0, "r_shoulder"), (1, "spine"), 0.2), ("a 오른손 - b 허벅지", (0, "r_wrist"), (1, "r_knee"), 0.2)]


@pair("pull_by_wrist", tags=["pulling"], ko="손목 잡아끌기 (a 가 서서 몸을 뒤로 젖히며, 바닥에 앉아 버티는 b 의 손목을 끌어당김)", arms=True)
def pull_by_wrist(a, b):
    ab, bb = a.b, b.b
    # b: 바닥에 앉아 무릎을 세우고 a 쪽(+x)을 봄 (poses_human.b_sit_floor 를 a 쪽으로 돌린 것)
    b.set_root([-0.16, bb["thigh_r"] + 0.01, 0.0], yaw=60)
    b.set_joint("spine", pitch=-6)                              # 끌려가지 않으려고 살짝 뒤로
    f = b.facing()
    for side in ("r", "l"):
        hip = b.pos[side + "_hip"]
        ank = hip + f * (bb["thigh"] + bb["shin"]) * 0.55 + b.left() * sgn(side) * 0.03
        ank[1] = bb["foot_r"] * 1.1
        b.solve_limb(side + "_leg", ank, UP + f * 0.3)
    # a: b 쪽(-x)을 보고 서서 몸을 뒤로 젖힘, 발은 앞으로 버팀
    root_stand(a, 0.2, yaw=-100, drop=0.02)
    a.set_joint("spine", pitch=-14)
    legs_stand(a, spread=0.06, back=-0.05, toe_out=4)
    # 잡는 손: a 의 b 쪽 팔과 b 의 a 쪽 팔이 두 사람 사이에서 만남
    sa = min(("r", "l"), key=lambda s: float(np.linalg.norm(a.pos[s + "_shoulder"] - b.pos["chest"])))
    sb = min(("r", "l"), key=lambda s: float(np.linalg.norm(b.pos[s + "_shoulder"] - a.pos["chest"])))
    meet = (a.pos[sa + "_shoulder"] * 0.55 + b.pos[sb + "_shoulder"] * 0.45) - UP * 0.06
    arm_reach(a, sa, meet, vec(a, sa, out=0.6, up=-0.6, fwd=-0.2))
    arm_reach(b, sb, meet + (a.pos[sa + "_wrist"] - meet) * 0.0 - (meet - b.pos[sb + "_shoulder"]) * 0.0, vec(b, sb, out=0.5, up=-0.6))
    hang_arm(a, "l" if sa == "r" else "r")
    hang_arm(b, "l" if sb == "r" else "r")
    return [("a 손 - b 손목", (0, sa + "_wrist"), (1, sb + "_wrist"), 0.09)]


# ------------------------------------------------------------------ 연결 (poses_human.SINGLE / poses.POSES)
def install():
    """도서관 자세를 인형 자세 표에 넣음 (여러 번 불러도 같음)"""
    from . import poses as P, poses_human as PH
    for name, e in LIB.items():
        if e["n"] == 1:
            PH.SINGLE.setdefault(name, e["fn"])
            for key, f in (("s_" + name, PH.single_pose(name)),):
                P.POSES.setdefault(key, f)
                P.KOREAN.setdefault(key, e["ko"] + " (사람)")
                P.EXAMPLE_CAMERAS.setdefault(key, [("eye", 20, 6), ("high", 25, 50)])
        else:
            def mk(fn):
                def f(settings, swap=False):
                    a, b = PH._pair(settings)
                    if swap:
                        a, b = b, a
                    contacts = fn(a, b) or []
                    return [a, b], contacts
                return f
            key = "L_" + name
            P.POSES.setdefault(key, mk(e["fn"]))
            P.KOREAN.setdefault(key, e["ko"] + " (사람 둘)")
            P.EXAMPLE_CAMERAS.setdefault(key, [("eye", 20, 6), ("high", 25, 50)])
