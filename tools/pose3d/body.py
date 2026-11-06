# -*- coding: utf-8 -*-
"""
tools/pose3d/body.py - 인형 한 개: 체형(비율) + 관절 뼈대 + 앞으로 운동학(FK) + 팔다리 IK + OpenPose 18점 + 입체 조각

말 풀이 (처음 보는 사람용)
- 앞으로 운동학(FK, forward kinematics): 관절마다 '얼마나 돌렸나(각도)'를 주면, 뿌리(골반)부터 차례로 따라가서
  손끝·발끝이 어디에 있는지 계산하는 것. 비유: 팔을 어깨에서 30도, 팔꿈치에서 90도 굽히면 손이 어디 가나.
- IK(inverse kinematics): 반대로 '손을 여기에 두고 싶다'를 주면 어깨·팔꿈치 각도를 거꾸로 구하는 것.
  여기서는 IK로 각도를 구한 뒤 다시 FK로 위치를 계산해서, 뼈 길이가 늘 체형 설정과 같게 한다.
- 좌표: y = 위, 서 있는 인형은 +z 쪽을 봄, +x = 인형의 왼쪽. 바닥은 y = 0. 길이 단위 = 캐릭터 키 1.0.

에러가 나면: 대부분 settings.yaml 값 오타 (숫자 대신 글자 등). `python -m tools.pose3d check` 로 설정만 읽어 볼 수 있음."""
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# settings.yaml 이 없거나 PyYAML 이 없을 때 쓰는 기본값 (settings.yaml 과 같은 값)
DEFAULT_BODY = dict(
    head_rx=0.125, head_ry=0.115, head_rz=0.115, neck=0.06, torso=0.30, torso_rx=0.10, torso_rz=0.085,
    shoulder_w=0.10, shoulder_drop=0.03, upper_arm=0.14, forearm=0.13, arm_r=0.035, paw_r=0.05,
    hip_w=0.07, thigh=0.17, shin=0.16, thigh_r=0.06, shin_r=0.045, foot=0.08, foot_r=0.035,
    ear_len=0.10, ear_r=0.045, muzzle=0.035, tail_seg=0.11, tail_r=0.045)
DEFAULT_SETTINGS = dict(
    body=DEFAULT_BODY,
    people=dict(a=dict(scale=1.0), b=dict(scale=1.0)),
    camera=dict(yaw=20.0, pitch=8.0, dist=None, fov=35.0, margin=1.12),
    image=dict(width=512, height=640, depth_far=40, line_px=2,
               person_colors=[[255, 80, 80], [80, 140, 255]]))


def load_settings(path=None):
    """settings.yaml 읽기. 없는 값은 기본값으로 채움 (돌려줌: 새 dict)"""
    import copy
    s = copy.deepcopy(DEFAULT_SETTINGS)
    path = path or os.path.join(HERE, "settings.yaml")
    if not os.path.exists(path):
        return s
    try:
        import yaml
    except ImportError:              # PyYAML 없으면 기본값 (nk 파이썬에는 PyYAML 6 있음)
        return s
    with open(path, encoding="utf-8") as f:
        user = yaml.safe_load(f) or {}
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    for k, v in s["body"].items():
        s["body"][k] = float(v)
    return s


# ------------------------------------------------------------------ 회전 도우미
def rx(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def ry(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)


def rz(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def euler(yaw=0.0, pitch=0.0, roll=0.0):
    """yaw: 위를 축으로 돌기(+ = 왼쪽으로 돎, 90이면 +x를 봄) / pitch: + = 앞으로 숙임(머리면 아래를 봄) / roll: + = 오른쪽으로 기울임"""
    return ry(yaw) @ rx(pitch) @ rz(roll)


def unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v * 0.0


# ------------------------------------------------------------------ 뼈대 (관절 이름, 부모)
JOINTS = [
    ("pelvis", None), ("spine", "pelvis"), ("chest", "spine"), ("neck", "chest"), ("head", "neck"),
    ("r_shoulder", "chest"), ("r_elbow", "r_shoulder"), ("r_wrist", "r_elbow"),
    ("l_shoulder", "chest"), ("l_elbow", "l_shoulder"), ("l_wrist", "l_elbow"),
    ("r_hip", "pelvis"), ("r_knee", "r_hip"), ("r_ankle", "r_knee"),
    ("l_hip", "pelvis"), ("l_knee", "l_hip"), ("l_ankle", "l_knee"),
    ("tail1", "pelvis"), ("tail2", "tail1"), ("tail3", "tail2"), ("tail4", "tail3"), ("tail5", "tail4"),
]
PARENT = dict(JOINTS)
ORDER = [j for j, _ in JOINTS]

# 팔다리 (뿌리, 가운데, 끝, 가운데 관절이 튀어나가는 기본 방향: 팔꿈치 = 뒤, 무릎 = 앞)
LIMBS = {"r_arm": ("r_shoulder", "r_elbow", "r_wrist"), "l_arm": ("l_shoulder", "l_elbow", "l_wrist"),
         "r_leg": ("r_hip", "r_knee", "r_ankle"), "l_leg": ("l_hip", "l_knee", "l_ankle")}

# OpenPose 18점 순서 (nk_pose.py 와 같은 순서·같은 색 규칙)
OP_NAMES = ["nose", "neck", "r_shoulder", "r_elbow", "r_wrist", "l_shoulder", "l_elbow", "l_wrist",
            "r_hip", "r_knee", "r_ankle", "l_hip", "l_knee", "l_ankle", "r_eye", "l_eye", "r_ear", "l_ear"]


def rest_offsets(b):
    """관절마다 부모 좌표계 안에서의 위치 (가만히 선 자세, 팔은 아래로)"""
    return {
        "pelvis": np.zeros(3), "spine": np.zeros(3),
        "chest": np.array([0, b["torso"], 0.0]),
        "neck": np.zeros(3),
        "head": np.array([0, b["neck"] + b["head_ry"], 0.0]),
        "r_shoulder": np.array([-b["shoulder_w"], -b["shoulder_drop"], 0.0]),
        "l_shoulder": np.array([b["shoulder_w"], -b["shoulder_drop"], 0.0]),
        "r_elbow": np.array([0, -b["upper_arm"], 0.0]), "l_elbow": np.array([0, -b["upper_arm"], 0.0]),
        "r_wrist": np.array([0, -b["forearm"], 0.0]), "l_wrist": np.array([0, -b["forearm"], 0.0]),
        "r_hip": np.array([-b["hip_w"], 0, 0.0]), "l_hip": np.array([b["hip_w"], 0, 0.0]),
        "r_knee": np.array([0, -b["thigh"], 0.0]), "l_knee": np.array([0, -b["thigh"], 0.0]),
        "r_ankle": np.array([0, -b["shin"], 0.0]), "l_ankle": np.array([0, -b["shin"], 0.0]),
        "tail1": np.array([0, 0.02, -b["torso_rz"] * 0.9]),
        "tail2": np.array([0, 0, -b["tail_seg"]]), "tail3": np.array([0, 0, -b["tail_seg"]]),
        "tail4": np.array([0, 0, -b["tail_seg"]]), "tail5": np.array([0, 0, -b["tail_seg"]]),
    }


def scaled_body(settings, who):
    """사람(a/b) 체형 = body 비율 × 키 배율"""
    pe = (settings.get("people") or {}).get(who, {})
    k = float(pe.get("scale", 1.0))
    shape = pe.get("shape") or {}
    out = {n: (v * k * float(shape.get(n, 1.0)) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
           for n, v in settings["body"].items()}   # human: true 같은 표시는 그대로
    out.update({n: v for n, v in shape.items() if isinstance(v, bool)})      # 표시 (no_arms 등) 는 그대로 넣음
    return out


def standing_pelvis_height(b):
    """다리를 곧게 폈을 때 골반(엉덩이 관절) 높이 = 허벅지 + 정강이 + 발목 높이"""
    return b["thigh"] + b["shin"] + b["foot_r"] * 1.1


class Doll:
    """인형 한 개. rot[j] = 관절 j 의 '자기 좌표계 회전'(부모 기준). FK 로 pos/frame(세계 좌표)을 계산"""

    def __init__(self, body, name="a"):
        self.b = dict(body)
        self.name = name
        self.off = rest_offsets(self.b)
        self.root_pos = np.array([0.0, standing_pelvis_height(self.b), 0.0])
        self.rot = {j: np.eye(3) for j in ORDER}
        self.reach_err = {}           # IK 로 못 닿은 거리 (팔다리 이름 -> 남은 거리)
        self.extra = []
        self.fk()

    # ---- FK
    def fk(self):
        pos, frm = {}, {}
        for j in ORDER:
            p = PARENT[j]
            if p is None:
                frm[j] = self.rot[j].copy()
                pos[j] = self.root_pos.copy()
            else:
                frm[j] = frm[p] @ self.rot[j]
                pos[j] = pos[p] + frm[p] @ self.off[j]
        self.pos, self.frame = pos, frm
        return pos

    def facing(self):
        """몸통(골반)이 보는 방향 (세계 좌표)"""
        return self.frame["pelvis"] @ np.array([0, 0, 1.0])

    def left(self):
        return self.frame["pelvis"] @ np.array([1.0, 0, 0])

    # ---- 자세 정하기 (모두 각도, 도)
    def set_root(self, pos=None, yaw=0.0, pitch=0.0, roll=0.0):
        if pos is not None:
            self.root_pos = np.asarray(pos, float)
        self.rot["pelvis"] = euler(yaw, pitch, roll)
        self.fk()

    def set_joint(self, j, yaw=0.0, pitch=0.0, roll=0.0):
        self.rot[j] = euler(yaw, pitch, roll)
        self.fk()

    def curl_tail(self, pitch=20.0, yaw=0.0, first=(0.0, 0.0)):
        """꼬리: 첫 마디 방향(first = (pitch, yaw)) + 마디마다 같은 만큼 휨.
        pitch + = 위로 말림, - = 아래로 처짐 / yaw + = 인형의 오른쪽(-x)으로 휨 (뒤를 향한 꼬리 기준)"""
        self.rot["tail1"] = euler(first[1], first[0], 0)
        for j in ("tail2", "tail3", "tail4", "tail5"):
            self.rot[j] = euler(yaw, pitch, 0)
        self.fk()

    def solve_limb(self, limb, target, pole=None):
        """두 마디 IK: 끝(손목·발목)을 target 에 두고, 가운데 관절(팔꿈치·무릎)은 pole 방향으로 굽힘.
        결과는 관절 각도(rot)로 저장 → FK 로 위치 계산 (뼈 길이 불변). 못 닿으면 가장 가까운 곳 + reach_err 에 기록"""
        a, m, e = LIMBS[limb]
        self.fk()
        S = self.pos[a]
        l1 = float(np.linalg.norm(self.off[m]))
        l2 = float(np.linalg.norm(self.off[e]))
        T = np.asarray(target, float)
        d_raw = float(np.linalg.norm(T - S))
        d = min(max(d_raw, abs(l1 - l2) + 1e-4), l1 + l2 - 1e-4)
        u = unit(T - S) if d_raw > 1e-9 else self.frame[a] @ np.array([0, -1.0, 0])
        if pole is None:        # 기본: 팔꿈치는 몸 뒤쪽, 무릎은 몸 앞쪽
            pole = -self.facing() if "arm" in limb else self.facing()
        p = np.asarray(pole, float)
        v = p - np.dot(p, u) * u
        if np.linalg.norm(v) < 1e-6:            # pole 이 팔 방향과 나란하면 아무 수직 방향
            v = np.cross(u, [0, 0, 1.0]) if abs(u[2]) < 0.9 else np.cross(u, [1.0, 0, 0])
        v = unit(v)
        cos_a = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
        ang = math.acos(max(-1.0, min(1.0, cos_a)))
        M = S + l1 * (math.cos(ang) * u + math.sin(ang) * v)
        E = S + d * u
        d1 = unit(M - S)
        d2 = unit(E - M)
        n = unit(np.cross(v, u))                 # 굽힘 축 (가운데 관절이 도는 축)
        # 뿌리 관절의 세계 회전: 자기 -y = 첫 뼈 방향, 자기 x = 굽힘 축
        yw = -d1
        xw = unit(n - np.dot(n, yw) * yw)
        zw = np.cross(xw, yw)
        Rw = np.stack([xw, yw, zw], axis=1)
        parent = PARENT[a]
        self.rot[a] = self.frame[parent].T @ Rw
        # 가운데 관절: 자기 x 축으로 theta 만큼 (첫 뼈 좌표계에서 둘째 뼈 방향으로)
        dl = Rw.T @ d2
        theta = math.degrees(math.atan2(-dl[2], -dl[1]))
        self.rot[m] = rx(theta)
        self.fk()
        self.reach_err[limb] = float(np.linalg.norm(self.pos[e] - T))
        return self.reach_err[limb]

    def bone_lengths(self):
        return {j: float(np.linalg.norm(self.pos[j] - self.pos[PARENT[j]])) for j in ORDER if PARENT[j]}

    # ---- 머리 위 점 (OpenPose 코·눈·귀)
    def _head_surface(self, d):
        """머리 타원체 표면에서 머리 좌표 방향 d 인 점"""
        b = self.b
        d = unit(d)
        radii = np.array([b["head_rx"], b["head_ry"], b["head_rz"]])
        k = 1.0 / math.sqrt(float(np.sum((d / radii) ** 2)))
        return self.pos["head"] + self.frame["head"] @ (d * k)

    def muzzle_center(self):
        b = self.b
        return self.pos["head"] + self.frame["head"] @ np.array([0, -0.35 * b["head_ry"], 0.92 * b["head_rz"]])

    def keypoints(self):
        """OpenPose 18점 (세계 좌표, 18x3). 목 = 두 어깨 가운데 (DWPose→OpenPose 변환과 같은 규칙, nk_pose.to_openpose)"""
        b, P, F = self.b, self.pos, self.frame
        nose = self.muzzle_center() + F["head"] @ np.array([0, 0.1 * b["muzzle"], b["muzzle"] * 1.1])
        pts = {
            "nose": nose, "neck": (P["r_shoulder"] + P["l_shoulder"]) / 2,
            "r_eye": self._head_surface([-0.36, 0.12, 0.92]), "l_eye": self._head_surface([0.36, 0.12, 0.92]),
            "r_ear": self._head_surface([-0.97, 0.05, -0.12]), "l_ear": self._head_surface([0.97, 0.05, -0.12]),
        }
        for n in OP_NAMES:
            if n not in pts:
                pts[n] = P[n]
        return np.array([pts[n] for n in OP_NAMES])

    # ---- 입체 조각 (그리기용): ('cap', 부위, a, b, 반지름) 또는 ('ell', 부위, 중심, 3x3 회전, (rx, ry, rz))
    def primitives(self):
        b, P, F = self.b, self.pos, self.frame
        out = []
        tc = (P["pelvis"] + P["chest"]) / 2
        out.append(("ell", "torso", tc, F["spine"], (b["torso_rx"], b["torso"] / 2 + 0.04, b["torso_rz"])))
        out.append(("ell", "hips", P["pelvis"] + F["pelvis"] @ np.array([0, -0.01, -0.01]), F["pelvis"],
                    (b["hip_w"] + b["thigh_r"] * 0.9, b["thigh_r"] * 1.3, b["torso_rz"] * 1.05)))
        if b.get("human"):
            out.append(("ell", "belly", P["pelvis"] + F["spine"] @ np.array([0, b["torso"] * 0.16, b["torso_rz"] * 0.12]), F["spine"],
                        (b["hip_w"] + b["thigh_r"] * 0.55, b["torso"] * 0.2, b["torso_rz"] * 0.95)))
        out.append(("cap", "neck", P["chest"], P["chest"] + F["neck"] @ np.array([0, b["neck"] + 0.02, 0]), b["arm_r"] * 1.2))
        out.append(("ell", "head", P["head"], F["head"], (b["head_rx"], b["head_ry"], b["head_rz"])))
        human = bool(b.get("human"))
        if not human:
            out.append(("ell", "muzzle", self.muzzle_center(), F["head"], (b["muzzle"] * 1.3, b["muzzle"], b["muzzle"] * 1.1)))
        else:
            out.append(("ell", "nose", P["head"] + F["head"] @ np.array([0, -0.15 * b["head_ry"], 0.93 * b["head_rz"]]), F["head"],
                        (b["head_rx"] * 0.22, b["head_ry"] * 0.28, b["head_rz"] * 0.35)))
        for sx, side in ((-1, "r"), (1, "l")):
            # 고양이 귀: 납작한 타원체 (귀 뿌리는 머리 위 양옆, 바깥으로 약 25도)
            ed = unit([sx * 0.45, 1.0, 0.04])
            ex = unit(np.cross(ed, [0, 0, 1.0])) * -sx if abs(ed[2]) < 0.99 else np.array([1.0, 0, 0])
            ez = np.cross(ex, ed)
            eR = F["head"] @ np.stack([ex, ed, ez], axis=1)
            base = P["head"] + F["head"] @ np.array([sx * 0.55 * b["head_rx"], 0.78 * b["head_ry"], 0.0])
            if not human:
                out.append(("ell", "ear_" + side, base + F["head"] @ ed * (b["ear_len"] * 0.38), eR,
                            (b["ear_r"], b["ear_len"] * 0.55, b["ear_r"] * 0.4)))
            if not b.get("no_arms"):
                out.append(("cap", "uarm_" + side, P[side + "_shoulder"], P[side + "_elbow"], b["arm_r"]))
            if not b.get("upper_arms_only") and not b.get("no_arms"):
                out.append(("cap", "farm_" + side, P[side + "_elbow"], P[side + "_wrist"], b["arm_r"]))
                fdir = unit(P[side + "_wrist"] - P[side + "_elbow"])
                out.append(("cap", "hand_" + side, P[side + "_wrist"] + fdir * b["paw_r"] * 0.2,
                            P[side + "_wrist"] + fdir * b["paw_r"] * 0.7, b["paw_r"]))
            out.append(("cap", "thigh_" + side, P[side + "_hip"], P[side + "_knee"], b["thigh_r"]))
            out.append(("cap", "shin_" + side, P[side + "_knee"], P[side + "_ankle"], b["shin_r"]))
            if human and b.get("kneecap", True):
                mid = (P[side + "_hip"] + P[side + "_ankle"]) / 2
                kd = P[side + "_knee"] - mid
                kd = unit(kd) if float(np.linalg.norm(kd)) > 0.01 else self.facing()
                out.append(("ell", "kneecap_" + side, P[side + "_knee"] + kd * b["thigh_r"] * 0.75, F["pelvis"],
                            (b["thigh_r"] * 0.55, b["thigh_r"] * 0.6, b["thigh_r"] * 0.45)))
            toe = P[side + "_ankle"] + F[side + "_knee"] @ np.array([0, -b["foot_r"] * 0.3, b["foot"]])
            out.append(("cap", "foot_" + side, P[side + "_ankle"], toe, b["foot_r"]))
        tail = ["tail1", "tail2", "tail3", "tail4", "tail5"]
        if not human:
            for i in range(len(tail) - 1):
                out.append(("cap", "tail", P[tail[i]], P[tail[i + 1]], b["tail_r"] * (1.0 - 0.08 * i)))
        return out + list(self.extra)

    # OpenPose 점을 감싸는 '둥근 덩어리'(타원체) 부위의 두께 허용치.
    #   - 자기 몸통·골반·머리(타원체)면 → 아래 두께만큼은 허용 (정면에서 보면 어깨·엉덩이 점은 몸통 속에 조금 묻혀 있음)
    #   - 그 밖(다른 사람, 자기 다른 부위) → 조금이라도 앞이면 가려짐
    def owners(self):
        b = self.b
        eps = 0.012
        torso = {"torso": b["torso_rz"] + eps}
        hips = {"hips": b["torso_rz"] * 1.05 + eps, "torso": b["torso_rz"] + eps}
        head = {"head": eps, "muzzle": eps}
        return [dict(head), dict(torso), dict(torso), {}, {}, dict(torso), {}, {},
                dict(hips), {}, {}, dict(hips), {}, {}, dict(head), dict(head), dict(head), dict(head)]
