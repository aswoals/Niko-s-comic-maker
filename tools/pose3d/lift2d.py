# -*- coding: utf-8 -*-
"""
tools/pose3d/lift2d.py - 그림에서 뽑은 2D 뼈대(DWPose) -> 캐릭터 몸 비율 인형

흐름 (자세 도서관에 없는 자세): 먼저 조종 없이 한 장 그림 → DWPose 로 관절 2D 위치 → 이 파일이 관절 '방향'만 따르고
뼈 길이·골반 폭·키는 캐릭터 인형(settings_human + 캐릭터 height_cm·체형)으로 바꿔 3D 인형을 세움 → 깊이·선화·사람별 틀을 찍어
→ 같은 시드로 '인형 약하게' 다시 그림. 그림 모델이 잘못 그린 몸 비율(다리 길이·골반·두 사람 키)을 인형이 바로잡게 함.

카메라 공간에서 세움: 화면 오른쪽 = +x, 위 = +y, 카메라 쪽 = +z (그림을 찍은 각도는 이미 2D 에 들어 있음 → 거의 정사영 카메라로 정면에서 찍음).
깊이(z)는 2D 에서 짧아진 만큼 피타고라스로 (부호는 규칙: 무릎·팔은 몸이 보는 쪽으로) — 정답이 아니라 '약한 조종'용 어림.
COCO-WholeBody 133점 중 몸 17점만 씀: 0 코, 1·2 눈(왼·오), 3·4 귀, 5·6 어깨, 7·8 팔꿈치, 9·10 손목, 11·12 엉덩이, 13·14 무릎, 15·16 발목 (사람 기준 왼·오)."""
import math

import numpy as np

from .body import Doll, unit

THR = 0.3
FOV = 4.0                       # 거의 정사영 (원근 왜곡 없이 2D 위치 그대로)
NOSE, LEYE, REYE, LEAR, REAR, LSH, RSH, LEL, REL, LWR, RWR, LHIP, RHIP, LKN, RKN, LAN, RAN = range(17)


def _ok(conf, *ix):
    return all(conf[i] >= THR for i in ix)


def to_world(p, W, H, s):
    """그림 픽셀 (u, v) -> 카메라 공간 (x, y) 단위 (s = 단위당 픽셀)"""
    return np.array([(p[0] - W / 2.0) / s, (H / 2.0 - p[1]) / s])


def estimate_scale(kp, conf, b):
    """단위당 픽셀: 잘 보이는 뼈의 (2D 길이 / 인형 길이) 중 큰 쪽 (짧아 보이는 건 앞뒤로 기울어서일 수 있으니 80% 분위)"""
    pairs = [(LSH, LEL, b["upper_arm"]), (RSH, REL, b["upper_arm"]), (LEL, LWR, b["forearm"]), (REL, RWR, b["forearm"]),
             (LHIP, LKN, b["thigh"]), (RHIP, RKN, b["thigh"]), (LKN, LAN, b["shin"]), (RKN, RAN, b["shin"])]
    r = [np.linalg.norm(kp[i] - kp[j]) / L for i, j, L in pairs if _ok(conf, i, j) and L > 0]
    if _ok(conf, LSH, RSH, LHIP, RHIP):
        t2 = np.linalg.norm((kp[LSH] + kp[RSH]) / 2 - (kp[LHIP] + kp[RHIP]) / 2)
        r.append(t2 / max(b["torso"] - b["shoulder_drop"], 1e-6))
    if not r:
        return None
    return float(np.percentile(r, 80))


def _z_from(l2, L, sign):
    """2D 길이 l2, 실제 길이 L -> 깊이 성분 (짧아진 만큼)"""
    return sign * math.sqrt(max(0.0, L * L - l2 * l2))


def torso_frame(kp, conf, W, H, s, b, lean_sign=1.0, face_hint=None, s_pos=None):
    """(골반 위치 3D, 회전 3x3 [왼쪽, 위, 앞], 보는 쪽 부호 +1 = 카메라 쪽) 또는 None.
    face_hint: 컷 태그로 아는 몸 방향 (-1 = 등이 보임: from behind·뒤에서 찍음) — 뒤돌아보기는 얼굴이 보여 앞으로 읽히던 것"""
    if not _ok(conf, LSH, RSH) or not (_ok(conf, LHIP, RHIP) or _ok(conf, LHIP) or _ok(conf, RHIP)):
        return None
    S2 = to_world((kp[LSH] + kp[RSH]) / 2, W, H, s)
    if _ok(conf, LHIP, RHIP):
        H2 = to_world((kp[LHIP] + kp[RHIP]) / 2, W, H, s)
    else:
        H2 = to_world(kp[LHIP] if _ok(conf, LHIP) else kp[RHIP], W, H, s)
    up2 = S2 - H2
    root2 = H2 * (s / s_pos) if s_pos else H2                # 자리는 공통 배율(s_pos), 방향·기울기는 이 사람 배율(s)
    t_len = b["torso"] - b["shoulder_drop"]
    l2 = float(np.linalg.norm(up2))
    if l2 < 1e-6:
        return None
    up3 = unit(np.array([up2[0], up2[1], _z_from(min(l2, t_len), t_len, lean_sign)]))
    u2 = up2 / l2
    left2 = np.array([u2[1], -u2[0]])                       # 화면 안에서 위 방향을 시계 방향 90도 = 정면일 때 사람의 왼쪽
    sh = to_world(kp[LSH], W, H, s) - to_world(kp[RSH], W, H, s)
    face = 1.0 if float(np.dot(sh, left2)) >= 0 else -1.0   # 사람 왼어깨가 화면에서 '왼쪽 방향'에 있으면 카메라를 봄
    if not _ok(conf, NOSE) and not _ok(conf, LEYE) and not _ok(conf, REYE):
        face = -1.0                                         # 얼굴이 안 보이면 등
    if face_hint is not None:
        face = float(face_hint)
    c = min(1.0, float(np.linalg.norm(sh)) / (2 * b["shoulder_w"]))
    th = math.acos(c)
    turn = 0.0
    if face > 0 and _ok(conf, NOSE):
        turn = float(np.dot(to_world(kp[NOSE], W, H, s) - S2, left2))
    sgn = 1.0 if turn >= 0 else -1.0
    f3 = np.array([0, 0, face]) * math.cos(th) + np.array([left2[0], left2[1], 0]) * math.sin(th) * sgn
    f3 = f3 - np.dot(f3, up3) * up3
    if np.linalg.norm(f3) < 1e-6:
        f3 = np.array([0, 0, face]) - np.dot([0, 0, face], up3) * up3
    f3 = unit(f3)
    left3 = np.cross(up3, f3)
    R = np.stack([left3, up3, f3], axis=1)
    return np.array([root2[0], root2[1], 0.0]), R, face


def _limb(d, side, kp, conf, W, H, s, root_i, mid_i, end_i, L1, L2, sign1, sign2, limb):
    """뿌리(인형) 에서 2D 방향대로 인형 뼈 길이만큼 -> 가운데·끝 3D -> IK"""
    if not _ok(conf, root_i, mid_i):
        return False
    a = d.pos[{"arm": side + "_shoulder", "leg": side + "_hip"}[limb]]
    v1 = to_world(kp[mid_i], W, H, s) - to_world(kp[root_i], W, H, s)
    l1 = float(np.linalg.norm(v1))
    v1 = v1 * (min(l1, L1 * 0.999) / l1) if l1 > 1e-9 else np.array([0.0, -L1 * 0.999])
    M = a + unit(np.array([v1[0], v1[1], _z_from(np.linalg.norm(v1), L1, sign1)])) * L1
    if _ok(conf, end_i):
        v2 = to_world(kp[end_i], W, H, s) - to_world(kp[mid_i], W, H, s)
        l2 = float(np.linalg.norm(v2))
        v2 = v2 * (min(l2, L2 * 0.999) / l2) if l2 > 1e-9 else np.array([0.0, -L2 * 0.999])
        E = M + unit(np.array([v2[0], v2[1], _z_from(np.linalg.norm(v2), L2, sign2)])) * L2
    else:
        E = M + unit(M - a) * L2                               # 끝이 안 보이면 곧게
    pole = M - (a + E) / 2
    if np.linalg.norm(pole) < 1e-6:
        pole = d.facing() if limb == "leg" else -d.facing()
    d.solve_limb(side + "_" + limb, E, pole)
    return True


def build_doll(kp, conf, body, W, H, s, name="a", lean_sign=1.0, face_hint=None, s_pos=None):
    """한 사람 2D 뼈대 -> 인형 (Doll) 또는 None. s = 이 사람 그림의 단위당 픽셀(방향·기울기 읽기), s_pos = 화면 자리 배율(두 사람 공통)"""
    tf = torso_frame(kp, conf, W, H, s, body, lean_sign, face_hint, s_pos)
    if tf is None:
        return None
    root, R, face = tf
    d = Doll(body, name)
    d.root_pos = root
    d.rot["pelvis"] = R
    d.fk()
    b = d.b
    for side, (sh, el, wr, hp, kn, an) in (("l", (LSH, LEL, LWR, LHIP, LKN, LAN)), ("r", (RSH, REL, RWR, RHIP, RKN, RAN))):
        if not _limb(d, side, kp, conf, W, H, s, hp, kn, an, b["thigh"], b["shin"], face, -face, "leg"):
            d.solve_limb(side + "_leg", d.pos[side + "_hip"] + R @ np.array([0, -(b["thigh"] + b["shin"]) * 0.98, 0]), d.facing())
        if not _limb(d, side, kp, conf, W, H, s, sh, el, wr, b["upper_arm"], b["forearm"], face, face, "arm"):
            d.solve_limb(side + "_arm", d.pos[side + "_shoulder"] + R @ np.array([0, -(b["upper_arm"] + b["forearm"]) * 0.95, 0]), -d.facing())
    if _ok(conf, NOSE) and _ok(conf, LSH, RSH):                 # 고개: 코가 어깨 가운데에서 옆으로 간 만큼 돌림 (어림)
        S2 = to_world((kp[LSH] + kp[RSH]) / 2, W, H, s)
        off = float(np.dot(to_world(kp[NOSE], W, H, s) - S2, R[:2, 0])) / max(b["shoulder_w"], 1e-6)
        d.set_joint("neck", yaw=max(-50.0, min(50.0, off * 35.0 * face)))
    return d


def anchor_feet(d, kp, conf, W, H, s):
    """인형을 위아래로 옮겨 낮은 발목을 그림의 낮은 발목 높이에 맞춤 (서 있는 사람이 둥 뜨지 않게). 발목이 안 보이면 그대로"""
    ys = [to_world(kp[i], W, H, s)[1] for i in (LAN, RAN) if conf[i] >= THR]
    if not ys:
        return
    target = min(ys)
    cur = min(d.pos["l_ankle"][1], d.pos["r_ankle"][1])
    d.root_pos = d.root_pos + np.array([0, target - cur, 0])
    d.fk()


def camera_for(W, H, s):
    """단위당 s 픽셀로 찍히는 거의 정사영 카메라 (정면, 화면 가운데 = 원점)"""
    from .render import Camera
    dist = H / (2.0 * s * math.tan(math.radians(FOV) / 2))
    return Camera(np.zeros(3), 0.0, 0.0, dist, FOV, W, H)


def lift(people, bodies, W, H, lean_sign=1.0, anchor=True, face_hint=None):
    """people: [(kp 133x2 또는 17x2, conf)] (a 먼저), bodies: 사람마다 인형 체형 dict -> (인형 목록, 카메라) 또는 (None, None).
    방향·기울기는 사람마다 자기 그림 배율로 읽고(작게 그린 사람의 다리를 '앞으로 기운 다리'로 읽지 않게),
    화면 배율은 두 사람 평균 -> 키 관계는 인형 키 배율이 정함"""
    ss = [estimate_scale(np.asarray(k)[:17], np.asarray(c)[:17], b) for (k, c), b in zip(people, bodies)]
    good = [x for x in ss if x]
    if not good:
        return None, None
    s = float(np.mean(good))
    dolls = []
    for i, ((k, c), b) in enumerate(zip(people, bodies)):
        if not ss[i]:
            continue
        d = build_doll(np.asarray(k)[:17], np.asarray(c)[:17], b, W, H, ss[i], "ab"[i], lean_sign, face_hint, s_pos=s)
        if d is None:
            continue
        if anchor:
            anchor_feet(d, np.asarray(k)[:17], np.asarray(c)[:17], W, H, s)
        dolls.append(d)
    if not dolls:
        return None, None
    return dolls, camera_for(W, H, s)
