# -*- coding: utf-8 -*-
"""
nk_inspect.py - 컷 자동 검사기 v1

생각: 3D 인형이 이미 '정답 뼈대'를 안다 → 그린 그림에서 DWPose 로 뼈대를 뽑아 인형 뼈대와 비교하면 어떤 자세든 같은 방법으로 검사됨.
검사 (사람 컷마다, GPU 안 씀):
  1. 몸 방향 (facing): 인형과 그림의 어깨 좌우 순서가 반대인가 — 엎드림↔누움, 뒷모습↔앞모습 (파이널 1차 컷 1·14)
  2. 자세 (pose): 몸통·허벅지·정강이(+팔이 핵심인 자세는 팔) 방향 각도 차이 — 다리는 좌우 바꿔 맞춰 봄 (DWPose 좌우 헷갈림)
  3. 다리 빠짐 (legs): 인형은 다리가 보이는데 그림에서 다리를 하나도 못 찾음 — 뭉개짐·가림
  4. 사람 바뀜·옷/머리 바뀜 (identity): 사람 자리의 머리색(위쪽)·윗옷색을 그 캐릭터의 다른 컷 색(가운데 값)과 비교 — 두 명 컷은 상대 색에 더 가까우면 '바뀜'
결과: episodes/<ep>/inspect.json (컷마다 점수·걸린 항목) + inspect.png (그림 위에 인형 뼈대(파랑)·그림 뼈대(빨강))
문턱은 정답 절반으로 정하고 나머지 절반으로 잰다 — runs/inspect_eval.py

사용: nk ep inspect <ep> [컷...]"""
import json
import math
import os

import numpy as np

THR = 0.3
#   몸 (facing·pose·legs): pose 60, facing 0.2 → 두 겹 합쳐 맞게 걸림 5 / 놓침 3 / 헛걸림 0 (사람 컷 66) — 쓸 수 있음
#   팔 (닿는 자세): 끌기 3/3 잡지만 팔짱은 못 가름 → 기본 꺼짐 (999, 실험용)
#   색 (머리·윗옷·바뀜): 맞는 컷·틀린 컷 값이 겹쳐 못 가름 → 기본 꺼짐 (999) — 다른 방법 필요
TH = {"pose": 60.0, "facing": 0.2, "arm": 999.0, "id_hair": 999.0, "id_shirt": 999.0, "swap": 999.0}
SEGS = [("neck", "mid_hip", "torso"), ("r_hip", "r_knee", "r_thigh"), ("r_knee", "r_ankle", "r_shin"),
        ("l_hip", "l_knee", "l_thigh"), ("l_knee", "l_ankle", "l_shin")]
ARM_SEGS = [("r_shoulder", "r_elbow", "r_upper"), ("r_elbow", "r_wrist", "r_fore"),
            ("l_shoulder", "l_elbow", "l_upper"), ("l_elbow", "l_wrist", "l_fore")]


def _pts(names, k, ok):
    d = {n: (np.array(p, float) if o else None) for n, p, o in zip(names, k, ok)}
    if d.get("r_hip") is not None and d.get("l_hip") is not None:
        d["mid_hip"] = (d["r_hip"] + d["l_hip"]) / 2
    else:
        d["mid_hip"] = None
    return d


def _ang(v):
    return math.degrees(math.atan2(v[1], v[0]))


def _adiff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def seg_errors(doll, draw, segs):
    """같은 이름 뼈마다 방향 각도 차 {이름: 도}. 다리는 (오른-오른, 왼-왼) 과 (오른-왼, 왼-오른) 중 작은 쪽"""
    def one(dmap, gmap, swap=False):
        out = {}
        for a, b, nm in segs:
            ga, gb = a, b
            if swap and nm != "torso":
                sw = lambda n: n.replace("r_", "l_", 1) if n.startswith("r_") else n.replace("l_", "r_", 1)
                ga, gb = sw(a), sw(b)
            pa, pb, qa, qb = dmap.get(a), dmap.get(b), gmap.get(ga), gmap.get(gb)
            if pa is None or pb is None or qa is None or qb is None:
                continue
            if np.linalg.norm(pb - pa) < 4 or np.linalg.norm(qb - qa) < 4:
                continue
            out[nm] = _adiff(_ang(pb - pa), _ang(qb - qa))
        return out
    e1, e2 = one(doll, draw), one(doll, draw, swap=True)
    s1 = sum(e1.values()) / max(1, len(e1))
    s2 = sum(e2.values()) / max(1, len(e2))
    return e1 if (s1 <= s2 or len(e1) > len(e2)) else e2


def facing_score(doll, draw):
    """+ = 같은 쪽, - = 반대. 어깨 좌우 폭을 몸통 길이로 나눈 값 (옆모습이면 0 근처 → 판단 안 함)"""
    def side(d):
        if d.get("r_shoulder") is None or d.get("l_shoulder") is None or d.get("neck") is None or d.get("mid_hip") is None:
            return None
        torso = np.linalg.norm(d["neck"] - d["mid_hip"]) + 1e-6
        return float((d["l_shoulder"][0] - d["r_shoulder"][0]) / torso)
    a, b = side(doll), side(draw)
    if a is None or b is None:
        return None, a, b
    return a * b, a, b


def _robust(errs):
    """뼈 하나의 DWPose 잡음에 흔들리지 않게: 3개 이상이면 두 번째로 큰 차이, 아니면 가장 큰 차이"""
    if not errs:
        return None
    v = sorted(errs.values(), reverse=True)
    return round(v[1] if len(v) >= 3 else v[0], 1)


LYING = ("lie", "on_side", "fetal", "all_fours", "falling", "handstand", "dw")     # 눕기·엎드리기 등: 위아래 띠 색·다리 찾기가 안 맞음
FOLDED = ("sit", "head_on_shoulder", "kneel", "seiza", "indian", "wariza", "squat", "lap_pillow", "pull_by_wrist", "stand_sit", "on_one_knee")


def detect(img_bgr, box):
    """DWPose 한 사람 -> (OpenPose 18 이름 dict 점, 133 점 conf)"""
    import nk_pose
    from pose3d.body import OP_NAMES
    kp, conf = nk_pose.pose_one(img_bgr, box)
    k18, c18 = nk_pose.to_openpose(kp, conf)
    return _pts(OP_NAMES, k18.tolist(), [int(c >= THR) for c in c18]), kp, conf


def _grow(box, W, H, k=0.18):
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * k, (y1 - y0) * k
    return (max(0, int(x0 - dx)), max(0, int(y0 - dy)), min(W, int(x1 + dx)), min(H, int(y1 + dy)))


def region_colors(img_rgb, seg, box, shot):
    """사람 자리(인형 틀 상자 ∩ 실루엣)의 머리색(위 15%)·윗옷색(구도에 따라 띠) — Lab 가운데 값"""
    from PIL import Image
    x0, y0, x1, y1 = box
    m = seg[y0:y1, x0:x1]
    if m.sum() < 400:
        return None
    ys = np.where(m.any(1))[0]
    top, bot = ys.min(), ys.max()
    hgt = bot - top + 1
    band = {"face": (0.7, 1.0), "eyes": None, "waist": (0.45, 0.8), "knee": (0.3, 0.55)}.get(shot, (0.22, 0.42))
    import cv2
    lab = cv2.cvtColor(np.ascontiguousarray(img_rgb[y0:y1, x0:x1][:, :, ::-1]), cv2.COLOR_BGR2LAB).astype(float)   # PIL LAB 는 a·b 가 부호 바이트라 값이 튐
    def med(r0, r1):
        sl = np.zeros_like(m)
        sl[int(top + hgt * r0):int(top + hgt * r1) + 1] = True
        sel = m & sl
        if sel.sum() < 80:
            return None
        return np.median(lab[sel], axis=0).tolist()
    return {"hair": med(0.0, 0.15), "shirt": med(*band) if band else None}


def _de(a, b):
    if a is None or b is None:
        return None
    return float(np.linalg.norm(np.array(a) - np.array(b)))


def inspect_cut(kit, ep, cut, img_path):
    """컷 하나 -> {people: [...], flags: [...]} (인형이 없는 컷은 None)"""
    import cv2
    import nk_pose3d_auto as P3
    import nk_animeseg
    import nk_webtoon as W
    img = cv2.imread(img_path)
    H, Wd = img.shape[:2]
    if not P3.plan_pose(cut):
        return None
    P3.depth_for(kit, ep, cut, Wd, H, save=False)
    dolls = getattr(P3.depth_for, "last_kps", None) or []
    chars = getattr(P3.depth_for, "last", (None, None))
    pose = getattr(P3.depth_for, "last_pose", "")
    arms_keep = P3._arms_for(pose)
    seg_img = nk_animeseg.cached_mask(os.path.join(W.ep_dir(kit, ep), "poses"), int(cut["id"]), img_path)
    seg = (np.asarray(seg_img.resize((Wd, H))) > 128) if seg_img is not None else np.ones((H, Wd), bool)
    rgb = img[:, :, ::-1].copy()
    people = []
    for i, d in enumerate(dolls):
        if not d.get("box"):
            continue
        dmap = _pts(d["names"], d["k"], d["ok"])
        box = _grow(d["box"], Wd, H)
        gmap, _kp, conf = detect(img, box)
        folded = any(k in pose for k in FOLDED)
        errs = seg_errors(dmap, gmap, SEGS[:1] if folded else SEGS)          # 몸통·다리 (앉기·꿇기는 몸통만)
        aerr = seg_errors(dmap, gmap, ARM_SEGS) if arms_keep[min(i, 1)] else {}   # 팔: 인형이 팔을 남긴 자세만
        fs, fa, fb = facing_score(dmap, gmap)
        doll_legs = sum(1 for a, b, nm in SEGS[1:] if dmap.get(a) is not None and dmap.get(b) is not None)
        draw_legs = sum(1 for a, b, nm in SEGS[1:] if gmap.get(a) is not None and gmap.get(b) is not None)
        ch = chars[i] if i < len(chars) else None
        people.append({"char": (ch or {}).get("name"), "box": box, "seg_err": {k: round(v, 1) for k, v in errs.items()},
                       "pose_err": _robust(errs), "facing": None if fs is None else round(fs, 3),
                       "arm_err": round(max(aerr.values()), 1) if aerr else None, "arm_seg_err": {k: round(v, 1) for k, v in aerr.items()},
                       "facing_doll": fa, "facing_draw": fb, "doll_legs": doll_legs, "draw_legs": draw_legs,
                       "colors": region_colors(rgb, seg, box, str(cut.get("shot") or "")),
                       "draw_kp": {n: (None if p is None else [round(float(p[0]), 1), round(float(p[1]), 1)]) for n, p in gmap.items()},
                       "doll_kp": {n: (None if p is None else [round(float(p[0]), 1), round(float(p[1]), 1)]) for n, p in dmap.items()}})
    return {"id": int(cut["id"]), "shot": cut.get("shot"), "angle": cut.get("angle"), "pose": pose, "people": people,
            "duo_touch": bool(len(people) == 2 and (pose.startswith("L_") or pose.split("__")[0] in P3.TOUCH))}


def judge(cuts, th=None):
    """컷 결과 목록 -> 컷마다 flags (색은 캐릭터별 가운데 값과 비교 — 한 편 안 일관성)"""
    th = dict(TH, **(th or {}))
    ref = {}
    for c in cuts:
        if any(k in str((c or {}).get("pose") or "") for k in LYING):
            continue
        for p in (c or {}).get("people", []):
            if p.get("char") and p.get("colors"):
                ref.setdefault(p["char"], {"hair": [], "shirt": []})
                for k in ("hair", "shirt"):
                    if p["colors"].get(k):
                        ref[p["char"]][k].append(p["colors"][k])
    med = {ch: {k: (np.median(np.array(v), axis=0).tolist() if len(v) >= 2 else None) for k, v in d.items()} for ch, d in ref.items()}
    out = []
    for c in cuts:
        if not c:
            continue
        flags = []
        for i, p in enumerate(c["people"]):
            tag = p.get("char") or "?"
            lying = any(k in str(c.get("pose") or "") for k in LYING)
            if p.get("facing") is not None and p["facing"] < -th["facing"]:
                flags.append(("facing", tag, p["facing"]))
            if p.get("pose_err") is not None and p["pose_err"] > th["pose"]:
                flags.append(("pose", tag, p["pose_err"]))
            if c.get("duo_touch") and p.get("arm_err") is not None and p["arm_err"] > th["arm"]:     # 닿는 두 명 자세: 팔이 곧 역할
                flags.append(("arm", tag, p["arm_err"]))
            folded = any(k in str(c.get("pose") or "") for k in FOLDED)
            if p.get("doll_legs", 0) >= 2 and p.get("draw_legs", 0) == 0 and not lying and not folded:
                flags.append(("legs", tag, 0))
            col = (p.get("colors") or {}) if not lying else {}
            mine = med.get(p.get("char")) or {}
            for k in ("hair", "shirt"):
                de = _de(col.get(k), mine.get(k))
                if de is not None and de > th["id_" + k]:
                    flags.append(("id_" + k, tag, round(de, 1)))
            others = [q for q in c["people"] if q is not p and q.get("char") and q.get("char") != p.get("char")]
            for q in others:                                   # 두 명 컷: 내 자리 색이 상대 캐릭터 색에 더 가까우면 '바뀜'
                theirs = med.get(q["char"]) or {}
                d_me = [_de(col.get(k), mine.get(k)) for k in ("hair", "shirt")]
                d_th = [_de(col.get(k), theirs.get(k)) for k in ("hair", "shirt")]
                pairs = [(a, b) for a, b in zip(d_me, d_th) if a is not None and b is not None]
                if pairs and sum(a for a, b in pairs) > sum(b for a, b in pairs) + th["swap"]:
                    flags.append(("swap", tag, round(sum(a - b for a, b in pairs), 1)))
        out.append({"id": c["id"], "flags": flags})
    return out


def overlay(img_path, res, out_path):
    from PIL import Image, ImageDraw
    im = Image.open(img_path).convert("RGB")
    d = ImageDraw.Draw(im)
    for p in res.get("people", []):
        for mp, col in ((p["doll_kp"], (40, 120, 255)), (p["draw_kp"], (255, 40, 40))):
            for a, b, _ in SEGS + ARM_SEGS:
                if mp.get(a) and mp.get(b):
                    d.line([tuple(mp[a]), tuple(mp[b])], fill=col, width=4)
        d.rectangle(p["box"], outline=(0, 200, 0), width=2)
    im.save(out_path)


def run(nk, kit, args):
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    ids = [int(x) for x in args.cuts] or [int(c["id"]) for c in conti["cuts"]]
    od = os.path.join(W.ep_dir(kit, args.ep), "inspect")
    os.makedirs(od, exist_ok=True)
    res = []
    for cut in conti["cuts"]:
        if int(cut["id"]) not in ids:
            continue
        f = os.path.join(W.ep_dir(kit, args.ep), "cuts", "cut%02d.png" % int(cut["id"]))
        if not os.path.exists(f):
            continue
        r = inspect_cut(kit, args.ep, cut, f)
        if r:
            overlay(f, r, os.path.join(od, "cut%02d.png" % int(cut["id"])))
            res.append(r)
    verdict = judge(res)
    json.dump({"ep": args.ep, "cuts": res, "verdict": verdict}, open(os.path.join(W.ep_dir(kit, args.ep), "inspect.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for v in verdict:
        print("cut %2d: %s" % (v["id"], ", ".join("%s(%s %s)" % f for f in v["flags"]) or "OK"))


def add_parser(esub, nk, kit):
    a = esub.add_parser("inspect", help="컷 자동 검사기: 인형 뼈대 vs 그림 뼈대(DWPose), 몸 방향, 사람·옷 색 (GPU 안 씀)")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.set_defaults(func=lambda x: run(nk, kit, x))
