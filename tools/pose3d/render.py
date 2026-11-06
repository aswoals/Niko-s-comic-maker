# -*- coding: utf-8 -*-
"""
tools/pose3d/render.py - 인형 장면을 카메라로 찍어서 조종 그림 4가지를 만든다 (GPU 없이 numpy 로 광선 쏘기)

만드는 그림
  ① 깊이(depth): 가까울수록 밝게, 배경은 검정 (ControlNet 깊이 그림과 같은 규칙)
  ② 사람별 모양 틀(label): 픽셀마다 '맨 앞에 보이는 사람'. 겹친 곳은 앞사람 것 → 한 픽셀 = 한 사람
  ③ OpenPose 18점: 조종용(가려진 점 뺌 = 뼈대 찾기 AI가 내는 모양) / 확인용(가려진 점을 속 빈 동그라미로)
  ④ 선화(lineart): 사람 경계 + 앞뒤로 떨어진 곳(깊이가 뚝 끊기는 곳)만 흰 선

말 풀이
- 광선 쏘기(ray casting): 화면 픽셀마다 카메라에서 선을 하나 쏴서 처음 부딪히는 물체를 찾는 것. 비유: 레이저 포인터로 하나씩 찍어 보기.
- 카메라 yaw/pitch: yaw 는 장면 둘레를 도는 각도(0 = 정면), pitch 는 올려 찍는 높이 각도(+ = 위에서 내려다봄).

에러가 나면: 그림 크기(--size)를 너무 크게 주면 느려짐 (512x640 기준 한 장 1~3초, 2048 이면 수십 초)."""
import math

import numpy as np

from .body import OP_NAMES, unit

# nk_pose.py 와 같은 OpenPose 선 연결·색 (점 번호 1부터)
OP_LIMBS = [[2, 3], [2, 6], [3, 4], [4, 5], [6, 7], [7, 8], [2, 9], [9, 10], [10, 11], [2, 12], [12, 13], [13, 14],
            [2, 1], [1, 15], [15, 17], [1, 16], [16, 18]]
OP_COLORS = [[255, 0, 0], [255, 85, 0], [255, 170, 0], [255, 255, 0], [170, 255, 0], [85, 255, 0], [0, 255, 0],
             [0, 255, 85], [0, 255, 170], [0, 255, 255], [0, 170, 255], [0, 85, 255], [0, 0, 255], [85, 0, 255],
             [170, 0, 255], [255, 0, 255], [255, 0, 170], [255, 0, 85]]


class Camera:
    """target 을 바라보는 핀홀 카메라. yaw: 장면 둘레 각도(0 = +z 쪽 정면, 90 = +x 쪽) / pitch: 올려 찍는 각도"""

    def __init__(self, target, yaw=0.0, pitch=0.0, dist=3.0, fov=35.0, width=512, height=640):
        self.target = np.asarray(target, float)
        self.yaw, self.pitch, self.dist, self.fov = float(yaw), float(pitch), float(dist), float(fov)
        self.W, self.H = int(width), int(height)
        a, e = math.radians(yaw), math.radians(pitch)
        self.pos = self.target + dist * np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])
        f = unit(self.target - self.pos)
        up = np.array([0, 1.0, 0])
        if abs(np.dot(f, up)) > 0.999:          # 바로 위에서 찍으면 위쪽 방향을 -z 로
            up = np.array([0, 0, -1.0])
        r = unit(np.cross(f, up))
        self.f, self.r, self.u = f, r, np.cross(r, f)
        self.tanh = math.tan(math.radians(fov) / 2)

    def rays(self):
        """픽셀마다 광선 방향 (H x W x 3, 길이 1)"""
        H, W = self.H, self.W
        ys = (H / 2.0 - (np.arange(H) + 0.5)) / (H / 2.0) * self.tanh
        xs = ((np.arange(W) + 0.5) - W / 2.0) / (H / 2.0) * self.tanh
        d = self.f[None, None, :] + xs[None, :, None] * self.r[None, None, :] + ys[:, None, None] * self.u[None, None, :]
        return d / np.linalg.norm(d, axis=2, keepdims=True)

    def project(self, P):
        """세계 점 (N x 3) -> 픽셀 (N x 2: x, y), 카메라 앞 거리 (N)"""
        P = np.atleast_2d(np.asarray(P, float))
        v = P - self.pos
        z = v @ self.f
        zs = np.where(np.abs(z) < 1e-9, 1e-9, z)
        x = (v @ self.r) / zs / self.tanh * (self.H / 2.0) + self.W / 2.0
        y = self.H / 2.0 - (v @ self.u) / zs / self.tanh * (self.H / 2.0)
        return np.stack([x, y], axis=1), z


def auto_camera(dolls, yaw, pitch, fov, width, height, dist=None, margin=1.12):
    """dist 가 없으면 두 인형(조각 전체)이 화면에 다 들어오는 거리로"""
    pts = []
    six = np.vstack([np.eye(3), -np.eye(3)])
    for d in dolls:
        for p in d.primitives():
            if p[0] == "cap":
                pts += list(p[2] + six * p[4]) + list(p[3] + six * p[4])
            else:
                R, rad = p[3], p[4]
                for ax in range(3):
                    for sg in (-1, 1):
                        e = np.zeros(3); e[ax] = sg * rad[ax]
                        pts.append(p[2] + R @ e)
    pts = np.array(pts)
    center = (pts.min(0) + pts.max(0)) / 2
    if dist is not None:
        return Camera(center, yaw, pitch, dist, fov, width, height)
    dist = 2.0
    for _ in range(30):                          # 화면 밖으로 나가는 점이 없을 때까지 거리 조절
        cam = Camera(center, yaw, pitch, dist, fov, width, height)
        uv, z = cam.project(pts)
        nx = np.abs(uv[:, 0] - width / 2) / (width / 2)
        ny = np.abs(uv[:, 1] - height / 2) / (height / 2)
        need = float(max(nx.max(), ny.max())) * margin
        if z.min() <= 0.05:
            dist *= 1.5
            continue
        if abs(need - 1.0) < 0.01:
            break
        dist *= need ** 0.9
    return Camera(center, yaw, pitch, dist, fov, width, height)


# ------------------------------------------------------------------ 광선 - 조각 부딪힘 (길이 1인 광선 d, 시작점 o 는 모두 같음)
def hit_capsule(o, d, a, b, r):
    """캡슐(양 끝이 둥근 원기둥) — Inigo Quilez 식. 돌려줌: 거리 t (안 맞으면 inf)"""
    ba = b - a
    oa = o - a
    baba = float(ba @ ba)
    baoa = float(ba @ oa)
    oaoa = float(oa @ oa)
    bard = d @ ba
    rdoa = d @ oa
    A = baba - bard * bard
    B = baba * rdoa - baoa * bard
    C = baba * oaoa - baoa * baoa - r * r * baba
    h = B * B - A * C
    t = np.full(d.shape[0], np.inf)
    ok = (h >= 0) & (A > 1e-12)
    with np.errstate(invalid="ignore", divide="ignore"):
        tb = (-B - np.sqrt(np.where(ok, h, 0))) / np.where(ok, A, 1)
    y = baoa + tb * bard
    body = ok & (y > 0) & (y < baba) & (tb > 0)
    t[body] = tb[body]
    # 둥근 끝 (몸통에 안 맞았거나 광선이 축과 나란할 때)
    for c in (a, b):
        oc = o - c
        bb = d @ oc
        cc = float(oc @ oc) - r * r
        hh = bb * bb - cc
        m = (hh >= 0) & ~body
        tc = -bb - np.sqrt(np.where(m, hh, 0))
        m &= tc > 0
        t[m] = np.minimum(t[m], tc[m])
    return t


def hit_ellipsoid(o, d, c, R, radii):
    """타원체 — 타원체 좌표로 옮겨 단위 구와 부딪힘"""
    inv = 1.0 / np.asarray(radii, float)
    oo = (R.T @ (o - c)) * inv
    dd = (d @ R) * inv[None, :]
    A = np.einsum("ij,ij->i", dd, dd)
    B = dd @ oo
    C = float(oo @ oo) - 1.0
    h = B * B - A * C
    t = np.full(d.shape[0], np.inf)
    m = h >= 0
    tt = (-B[m] - np.sqrt(h[m])) / A[m]
    good = tt > 0
    idx = np.where(m)[0][good]
    t[idx] = tt[good]
    return t


def _bound(p):
    """조각을 감싸는 공 (중심, 반지름) — 화면에서 계산할 픽셀 범위를 줄이는 데 씀"""
    if p[0] == "cap":
        return (p[2] + p[3]) / 2, float(np.linalg.norm(p[3] - p[2])) / 2 + p[4]
    return p[2], float(max(p[4]))


def scene_parts(dolls):
    """[(사람 번호, 부위 이름, 조각)]"""
    return [(i, p[1], p) for i, dl in enumerate(dolls) for p in dl.primitives()]


def raycast(cam, parts, rays=None, pix=None):
    """rays: (N x 3) 광선. 돌려줌: 거리 t (N), 사람 번호 (N, 없으면 -1), 조각 번호 (N, 없으면 -1).
    pix 를 주면 (N x 2 정수 픽셀) 조각을 감싸는 공이 닿는 픽셀만 계산 (빠르게)"""
    N = rays.shape[0]
    tb = np.full(N, np.inf)
    who = np.full(N, -1, int)
    part = np.full(N, -1, int)
    for k, (i, name, p) in enumerate(parts):
        if pix is not None:
            c, rad = _bound(p)
            uv, z = cam.project(c[None])
            if z[0] <= rad:                      # 카메라가 조각 안/바로 앞 → 전체 계산
                sel = np.arange(N)
            else:
                rpx = rad / max(z[0] - rad, 1e-6) / cam.tanh * (cam.H / 2.0) + 2
                sel = np.where((np.abs(pix[:, 0] - uv[0, 0]) <= rpx) & (np.abs(pix[:, 1] - uv[0, 1]) <= rpx))[0]
            if sel.size == 0:
                continue
        else:
            sel = np.arange(N)
        d = rays[sel]
        t = hit_capsule(cam.pos, d, p[2], p[3], p[4]) if p[0] == "cap" else hit_ellipsoid(cam.pos, d, p[2], p[3], p[4])
        better = t < tb[sel]
        s = sel[better]
        tb[s] = t[better]
        who[s] = i
        part[s] = k
    return tb, who, part


def render(dolls, cam):
    """장면 한 번 찍기 → dict: t(거리), z(카메라 깊이), who(사람 번호 -1=배경), part(조각 번호), parts(조각 목록)"""
    parts = scene_parts(dolls)
    H, W = cam.H, cam.W
    rays = cam.rays().reshape(-1, 3)
    yy, xx = np.mgrid[0:H, 0:W]
    pix = np.stack([xx.ravel() + 0.5, yy.ravel() + 0.5], axis=1)
    t, who, part = raycast(cam, parts, rays, pix)
    z = t * (rays @ cam.f)
    return {"t": t.reshape(H, W), "z": z.reshape(H, W), "who": who.reshape(H, W), "part": part.reshape(H, W),
            "parts": parts, "cam": cam}


# ------------------------------------------------------------------ OpenPose 점: 화면 위치 + 보임/가려짐
def _seg_dist(P, a, b):
    ab = b - a
    t = float(np.clip(np.dot(P - a, ab) / max(float(ab @ ab), 1e-12), 0, 1))
    return float(np.linalg.norm(P - (a + t * ab)))


def keypoints_2d(dolls, cam, parts=None):
    """사람마다 (18x2 픽셀, 18 보임 1/0, 18 화면 안 1/0, 18 가린 사람 번호(-1 = 안 가려짐)).
점보다 앞에서 부딪힌 것 중 가장 가까운 것이 가린 것.
    단 그 점을 품은 자기 팔다리 캡슐은 무시하고, 자기 몸통·골반·머리는 두께만큼 허용 (body.Doll.owners)"""
    parts = parts if parts is not None else scene_parts(dolls)
    out = []
    for i, dl in enumerate(dolls):
        K = dl.keypoints()
        uv, z = cam.project(K)
        inside = (uv[:, 0] >= 0) & (uv[:, 0] < cam.W) & (uv[:, 1] >= 0) & (uv[:, 1] < cam.H) & (z > 0)
        own = dl.owners()
        vis = np.zeros(len(K), int)
        by = np.full(len(K), -1, int)
        for j in range(len(K)):
            if not inside[j]:
                continue
            tj = float(np.linalg.norm(K[j] - cam.pos))
            d = unit(K[j] - cam.pos)[None]
            best = np.inf
            for k, (pi, name, p) in enumerate(parts):
                t = hit_capsule(cam.pos, d, p[2], p[3], p[4]) if p[0] == "cap" else hit_ellipsoid(cam.pos, d, p[2], p[3], p[4])
                t = float(t[0])
                if not np.isfinite(t) or t >= best:
                    continue
                if pi == i and p[0] == "cap" and _seg_dist(K[j], p[2], p[3]) <= p[4] * 1.05 + 1e-6:
                    continue                      # 점을 품은 자기 팔다리 → 가림 아님
                tol = own[j].get(name, 0.012) if pi == i else 0.0
                if t < tj - tol - 1e-6:
                    best, by[j] = t, pi
            vis[j] = 1 if by[j] < 0 else 0
        out.append((uv, vis, inside.astype(int), by))
    return out


# ------------------------------------------------------------------ 그림 만들기 (numpy 배열, RGB uint8)
def depth_range(R):
    m = R["who"] >= 0
    return (float(R["z"][m].min()), float(R["z"][m].max())) if m.any() else (0.0, 1.0)


def depth_image(R, far_value=40, zrange=None):
    """가까울수록 밝게 (몸이 있는 픽셀만 0~255 로 늘림, 배경 0). zrange 를 주면 그 범위로 (혼자 그림을 두 사람 그림과 같은 밝기로)"""
    z = R["z"]
    m = R["who"] >= 0
    img = np.zeros(z.shape, np.uint8)
    if m.any():
        zn, zf = zrange or depth_range(R)
        span = max(zf - zn, 1e-6)
        v = 255.0 - (z - zn) / span * (255.0 - far_value)
        img[m] = np.clip(v[m], 1, 255).astype(np.uint8)      # 몸은 0(배경)이 되지 않게
    return np.repeat(img[:, :, None], 3, axis=2)


def label_image(R, colors):
    """사람별 모양 틀을 색으로 (a = 빨강, b = 파랑, 배경 검정)"""
    who = R["who"]
    img = np.zeros(who.shape + (3,), np.uint8)
    for i, c in enumerate(colors):
        img[who == i] = c
    return img


def person_masks(R, n):
    """사람마다 흑백 틀 (255 = 그 사람, 0 = 아님). 한 픽셀은 많아야 한 사람"""
    return [np.where(R["who"] == i, 255, 0).astype(np.uint8) for i in range(n)]


def _dilate(m, px):
    out = m.copy()
    for dy in range(-px, px + 1):
        for dx in range(-px, px + 1):
            if dx * dx + dy * dy > px * px:
                continue
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def line_image(R, line_px=2, jump=0.05):
    """선화: 사람이 바뀌는 곳(배경 포함) + 깊이가 jump 넘게 끊기는 곳. 흰 선, 검정 바탕 (선화 ControlNet 입력 모양)"""
    who, z = R["who"], np.where(R["who"] >= 0, R["z"], 1e9)
    e = np.zeros(who.shape, bool)
    for ax in (0, 1):
        w2 = np.roll(who, -1, ax)
        z2 = np.roll(z, -1, ax)
        diff = (who != w2) | (np.abs(z - z2) > jump)
        if ax == 0:
            diff[-1, :] = False
        else:
            diff[:, -1] = False
        e |= diff
    e = _dilate(e, max(0, int(line_px) // 2))
    img = np.zeros(who.shape + (3,), np.uint8)
    img[e] = 255
    return img


def _ellipse_poly(cx, cy, a, b, ang_deg, n=24):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    ca, sa = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))
    x = cx + a * np.cos(t) * ca - b * np.sin(t) * sa
    y = cy + a * np.cos(t) * sa + b * np.sin(t) * ca
    return list(zip(x.tolist(), y.tolist()))


FACE_IDX = [0, 14, 15, 16, 17]      # 코·눈·귀 (nk_pose.FACE 와 같음)


def control_mask(kps, i, solo=False):
    """조종 그림에 그릴 점 (사람 i). 규칙
    - 화면 밖 → 안 그림
    - 자기 머리에 가린 얼굴 점(뒷모습의 코·눈 등) → 안 그림 (nk_pose.pose_image back=True 와 같은 뜻)
    - 자기 몸에 가린 몸 점(옆모습의 먼 쪽 어깨·엉덩이·목) → 그림 (뼈대가 끊기면 ControlNet이 몸을 못 이음)
    - 상대에 가린 점 → 두 사람 그림(solo=False)에선 안 그림, 혼자 층(solo=True)에선 그림 (혼자 층은 가려진 몸도 그려야 함)"""
    uv, vis, inside, by = kps[i]
    face = np.zeros(len(by), bool)
    face[FACE_IDX] = True
    use = inside.astype(bool) & ~((by == i) & face)
    if not solo:
        use &= ~((by >= 0) & (by != i))
    return use


def openpose_image(W, H, kps, mode="control", stick=4, radius=4, only=None):
    """OpenPose 표준 모양 (nk_pose.draw 와 같은 색·굵기).
    mode: control = 조종용 (control_mask 규칙) / solo = 혼자 층용 (only 사람만, 상대에 가린 점도 그림) /
          all = 화면 안 점 전부 / check = 전부 + 진짜로 가려진 점(vis 0)은 속 빈 동그라미·어두운 선 (눈으로 확인용)"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    for i, (uv, vis, inside, by) in enumerate(kps):
        if only is not None and i != only:
            continue
        if mode in ("all", "check"):
            use = inside.astype(bool)
        else:
            use = control_mask(kps, i, solo=(mode == "solo"))
        for li, (a, b) in enumerate(OP_LIMBS):
            a -= 1; b -= 1
            if not (use[a] and use[b]):
                continue
            (x1, y1), (x2, y2) = uv[a], uv[b]
            L = math.hypot(x2 - x1, y2 - y1)
            ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
            col = tuple(int(v * 0.6) for v in OP_COLORS[li])
            if mode == "check" and not (vis[a] and vis[b]):
                col = tuple(int(v * 0.25) for v in OP_COLORS[li])
            dr.polygon(_ellipse_poly((x1 + x2) / 2, (y1 + y2) / 2, L / 2, stick, ang), fill=col)
        for k in range(18):
            if not use[k]:
                continue
            x, y = uv[k]
            if mode == "check" and not vis[k]:
                dr.ellipse([x - radius - 1, y - radius - 1, x + radius + 1, y + radius + 1], outline=(255, 255, 255), width=1)
                dr.ellipse([x - 1, y - 1, x + 1, y + 1], fill=tuple(OP_COLORS[k]))
            else:
                dr.ellipse([x - radius, y - radius, x + radius, y + radius], fill=tuple(OP_COLORS[k]))
    return np.asarray(img)


def kp_json(kps, W, H, spans=None):
    """nk_pose.save_kp 와 같은 모양 (+ vis·hidden_by). nk 가 쓰는 c (문턱 0.3) = 혼자 층용 규칙 (control_mask solo=True):
    c = 1.0 → 그릴 점 (상대에 가린 점 포함 — 혼자 층을 그릴 땐 그 부분도 그려야 하므로)
    c = 0.0 → 화면 밖이거나 자기 머리에 가린 얼굴 점
    vis = 두 사람을 같이 볼 때 진짜로 보이는지, hidden_by = 가린 사람 번호(-1 없음). spans 를 주면 그대로 씀 (콘티 cast 칸과 맞추기)"""
    people, sp = [], []
    for i, (uv, vis, inside, by) in enumerate(kps):
        c = control_mask(kps, i, solo=True).astype(float)
        people.append({"k": [[float(x), float(y)] for x, y in uv], "c": c.tolist(),
                       "vis": vis.tolist(), "hidden_by": by.tolist(), "inside": inside.tolist(), "names": OP_NAMES})
        xs = uv[inside.astype(bool), 0]
        sp.append([float(max(0, xs.min()) / W), float(min(W, xs.max()) / W)] if xs.size else [0.0, 0.0])
    return {"W": int(W), "H": int(H), "spans": [list(x) for x in spans] if spans else sp, "people": people}
