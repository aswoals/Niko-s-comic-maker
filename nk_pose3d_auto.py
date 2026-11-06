# -*- coding: utf-8 -*-
"""3D 인형 깊이 조종 자동 연결
콘티(conti) 에 pose3d: auto 가 있을 때만. 컷의 자세 태그(sitting/standing)·구도(shot/angle)·
캐릭터 키(캐릭터 파일 height_cm)로 사람 인형(tools/pose3d, settings_human.yaml)을 세우고 같은 카메라로 깊이 그림을 찍어
Anima LLLite 깊이 조종에 줌 → 앉기·하이앵글에서 상체·하체 각도가 따로 노는 것, 다리 길이, 두 사람 키 관계를 맞춤.
지금 되는 자세: 혼자 벤치·의자 앉기(sit_bench), 혼자 서 있는 전신(stand_single), 두 명 나란히 앉기(sit_pair), 한 명 서고 한 명 앉기(stand_sit).
안 하는 컷: 1인칭(pov)·기울임(tilt)·가까운 구도(waist·face·eyes·hands·detail), 그 밖의 동작(달리기 등) — 인형이 틀린 자세를 강요하지 않게.
결과: episodes/<편>/poses/cutNN_depth3d.png (컷 크기)"""
import os
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(KIT, "tools", "pose3d", "settings_human.yaml")
LLLITE = "anima-lllite-depth-1.safetensors"
STRENGTH, END = 0.3, 0.7
LLLITE2, STRENGTH2, END2 = "anima-lllite-any-test-like-v2.safetensors", 0.3, 0.7
FACING = ("facing another", "face-to-face", "looking at another")
CAM = {"eye": (0, 4), "high": (20, 50), "low": (0, -18), "side": (55, 8), "back": (180, 8), "pov": (0, 25), "tilt": (10, 6)}
SIT = ("sitting",)
SEAT = ("bench", "chair", "park bench", "sofa", "couch", "stool")
STAND = ("standing",)
BUSY = ("running", "jumping", "falling", "lying", "kneeling", "squatting", "fighting", "dancing",
        "pointing", "arms up", "outstretched arms", "waving", "fighting stance", "dynamic pose")


def _words(*xs):
    return " ".join(str(x or "") for x in xs).lower()


def _w(words, *tags):
    """낱말 그대로 있나"""
    import re
    w = " " + str(words or "").lower() + " "
    return any(re.search(r"(^|[\s,.;:()])" + re.escape(t) + r"($|[\s,.;:()])", w) for t in tags)


def _kind(words, seat_ok=True):
    """동작 낱말 -> 혼자 자세 이름 (tools/pose3d/poses_human.SINGLE)"""
    w = words
    if _w(w, "lying", "on back", "on stomach"):
        return "lie_stomach" if _w(w, "on stomach", "reading") else "lie_back"
    if _w(w, "running"):
        return "run"
    if _w(w, "jumping"):
        return "jump"
    if _w(w, "squatting"):
        return "squat"
    if _w(w, "kneeling", "seiza"):
        return "kneel"
    if _w(w, *SIT):
        return "sit_floor"
    return "stand"


TOUCH = ("hug_h", "high_five_h", "holding_hands_h")       # 닿는 자세는 팔이 핵심 -> 팔 전체를 남김
UNKNOWN = ("bent over", "arched back", "leaning to the side", "handstand", "upside-down", "cartwheel", "split", "climbing", "swimming",
           "flying", "floating", "crawling", "tripping", "punching", "throwing", "dodging", "leg up", "legs up", "spinning", "reclining",
           "yoga", "twisted torso", "midair", "sliding", "skipping", "tiptoes", "leg lift", "high kick", "lunge")


WHOLE_BODY = ("handstand", "upside-down", "cartwheel", "split", "climbing", "swimming", "flying", "floating", "reclining", "yoga")   # 몸 전체가 다른 자세 -> 도서관에 비슷한 태그가 있어도 dw


def _to_draft(words):
    """목록 밖 자세로 갈지: 몸 전체 자세 태그가 있거나, 모르는 태그가 있고 도서관에 맞는 게 없을 때"""
    if not _unknown(words) or _kind(words) != "stand":
        return False
    return _w(words, *WHOLE_BODY) or not _lib().match(words, 1)


def _unknown(words):
    import re
    w = " " + str(words or "").lower() + " "
    return any(re.search(r"(^|[\s,.;:()])" + re.escape(t) + r"($|[\s,.;:()])", w) for t in UNKNOWN)


def _lib():
    """자세 도서관 — 인형 자세 표에 넣은 뒤 돌려줌"""
    p = os.path.join(KIT, "tools")
    if p not in sys.path:
        sys.path.insert(0, p)
    from pose3d import library_human as LH
    LH.install()
    return LH


def _single(words, more=""):
    """한 사람 자세 이름: 바탕 자세(_kind)를 읽고, 도서관에 그 바탕 자세의 더 구체적인 자세(손 허리·팔 들기·정좌 ...)가 있으면 그것.
    words = 그 사람에게 붙은 말 (먼저 봄), more = 컷 전체 태그"""
    k = _kind(_words(words, more))
    LH = _lib()
    return LH.match(words, 1, base=k) or (LH.match(more, 1, base=k) if more else None) or k


def _split_pair(pose):
    """'p_<이름1>_<이름2>' -> (이름1, 이름2) — 이름에 '_' 가 든 자세(sit_floor, hands_on_hips ...) 도 바르게"""
    from pose3d import poses_human as _PH
    _lib()
    body = pose[2:]
    for kk in sorted(_PH.SINGLE, key=len, reverse=True):
        if body.startswith(kk + "_") and body[len(kk) + 1:] in _PH.SINGLE:
            return kk, body[len(kk) + 1:]
    return tuple(body.rsplit("_", 1))


SIDE_YAW = {"L_pull_by_wrist": 12}
ARMS_SINGLE = ("lie_stomach",)


def _arms_for(pose):
    """(오른쪽 사람 a 팔 남김, 왼쪽 사람 b 팔 남김) — 팔이 자세의 핵심인 것만 남김"""
    if pose in TOUCH:
        return True, True
    base = pose.split("__")[0]
    if base.startswith("s_") and base[2:] in ARMS_SINGLE:
        return True, True
    LH = _lib()
    if pose.startswith("L_") or pose.startswith("s_"):
        k = LH.arms_kept(pose[2:])
        return k, k
    if pose.startswith("p_"):
        ka, kb = _split_pair(pose)
        return LH.arms_kept(ka) or ka in ARMS_SINGLE, LH.arms_kept(kb) or kb in ARMS_SINGLE
    return False, False


def plan_pose(cut):
    """컷 -> (자세 이름, 오른쪽 사람 char, 왼쪽 사람 char, 거울) 또는 None.
    가까운 구도(knee·waist·face·eyes)는 몸 전체 인형을 찍어 위쪽만 잘라 씀 (depth_for)"""
    shot = str(cut.get("shot") or "")
    if shot in ("hands", "detail", "wide") and not (cut.get("_roles") or cut.get("_char")):
        return None
    if shot in ("hands", "eyes"):
        return None
    roles = cut.get("_roles") or []
    allw = _words(cut.get("scene"), cut.get("anima_act"))
    tw = _words(cut.get("scene"))                         # 자세 고르기는 태그만 (문장의 'sweat running down' 이 달리기로 읽히던 것 — gl03 컷 5)
    if len(roles) == 2:
        (r1, c1), (r2, c2) = roles                       # r1 = 오른쪽, r2 = 왼쪽 (nk_plan)
        p1, p2 = _words(r1.get("pos")), _words(r2.get("pos"))
        w1, w2 = _words(p1, allw), _words(p2, allw)
        common_sit = any(k in allw for k in SIT)
        s1 = any(k in p1 for k in SIT) or (common_sit and not any(k in p1 for k in STAND))
        s2 = any(k in p2 for k in SIT) or (common_sit and not any(k in p2 for k in STAND))
        m = _lib().match(allw, 2)
        if m:
            e = _lib().LIB[m]
            f = e["first"]
            first, second = (c2, c1) if (f and f in p2 and f not in p1) else (c1, c2)
            if not f:
                h1, h2 = (any(_w(p, tg) for tg in e["tags"]) for p in (p1, p2))
                if h1 != h2:
                    doer, other = (c1, c2) if h1 else (c2, c1)
                    first, second = (doer, other) if e.get("actor", "a") == "a" else (other, doer)
            #   -> 바꿨으면 인형을 좌우로 뒤집어(mirror) a 가 글의 그 사람 자리(왼쪽)에 오게 함 (팔짱 역할이 3판 모두 바뀐 원인)
            return ("L_" + m, first, second, first is not c1)
        for tag, pose in (("hug", "hug_h"), ("high five", "high_five_h"), ("holding hands", "holding_hands_h"), ("back-to-back", "back_to_back_h")):
            if _w(allw, tag):                               # 두 명이 닿는 자세 (케모노 자세의 사람 체형판) — 낱말 그대로
                return (pose, c1, c2, False)
        if "piggyback" in allw or "carrying" in w1 + " " + w2:      # 업기: 'carrying' 이 붙은 사람이 업는 쪽 (a)
            carrier, carried = (c1, c2) if "carrying" in p1 else (c2, c1)
            return ("piggyback_h", carrier, carried, False)
        if any(_to_draft(_words(p, tw)) for p in (p1, p2)):
            return ("dw", c1, c2, False)                    # 목록 밖 자세: 먼저 그린 그림의 뼈대로 (depth_from_draft)
        k1, k2 = _single(p1, tw), _single(p2, tw)
        if (s1 and s2) and any(k in allw for k in SEAT):
            return ("sit_pair", c1, c2, False)
        if s1 != s2 and any(k in allw for k in SEAT):
            stand, sit = (c1, c2) if s2 else (c2, c1)
            return ("stand_sit", stand, sit, not s2)
        if "walking" in allw and k1 == "stand" and k2 == "stand":
            return ("walk_pair", c1, c2, False)
        if k1 == "stand" and k2 == "stand":
            return ("face_pair" if any(k in w1 + " " + w2 for k in FACING) else "stand_pair", c1, c2, False)
        return ("p_%s_%s" % (k1, k2), c1, c2, False)    # 그 밖 = 각자 혼자 자세로 나란히
    if roles:
        return None
    ch = cut.get("_char") or {}
    if not ch:
        return None
    angle = str(cut.get("angle") or "eye")
    if "looking back" in allw and angle == "back":
        return ("look_back", ch, None, False)
    if any(k in allw for k in SIT) and any(k in allw for k in SEAT):
        return ("sit_cross" if "crossed legs" in allw else "sit_bench", ch, None, False)
    if _to_draft(tw):
        return ("dw", ch, None, False)                      # 목록 밖 자세: 먼저 그린 그림의 뼈대로 (depth_from_draft)
    k = _single(tw)
    return ("stand_single" if k == "stand" else "s_" + k, ch, None, False)


CROP = {"knee": 0.74, "waist": 0.56, "face": 0.3, "eyes": 0.26}       # 가까운 구도 = 몸 전체 인형의 위쪽 몇 할


def _height(ch):
    try:
        return float(ch.get("height_cm") or 170)
    except Exception:
        return 170.0


SHAPES = {
    "male": {"hip_w": 1.2, "thigh_r": 1.08},
    "female": {"hip_w": 1.35, "torso_rx": 0.88, "shoulder_w": 0.86, "thigh_r": 1.1, "torso_rz": 0.95},
}


def _shape(ch):
    ch = ch or {}
    if isinstance(ch.get("body3d"), dict):
        return ch["body3d"]
    t = " ".join(str(ch.get(k) or "") for k in ("tags_full", "tags_short", "anima")).lower()
    return SHAPES["female"] if ("1girl" in t or " woman" in t or " girl" in t) else SHAPES["male"]


def _faceless_of(cut, ch):
    """이 사람(캐릭터)의 얼굴이 칸 밖인가 — 두 명 컷은 roles 의 그 사람 pos, 혼자 컷은 컷 태그(scene)에 'head out of frame' / 'face out of frame'.
    인형 머리가 깊이 그림에 보이면 얼굴이 그려짐 -> 그 사람 인형은 머리 없이 (shape no_head, tools/pose3d/render.doll_parts)."""
    import re
    pat = r"(head|face) out of frame"
    roles = cut.get("_roles") or []
    if roles:
        return any(c is ch and re.search(pat, str(r.get("pos") or "").lower()) for r, c in roles)
    return re.search(pat, str(cut.get("scene") or "").lower()) is not None


def _neck_vs_head(res, fl, H2):
    """(머리 없는 사람 목의 세로 위치(가장 위), 머리 보이는 사람 머리 꼭대기 세로 위치(가장 위)) — 몸 전체를 찍은 그림 기준. 못 구하면 None"""
    import numpy as np
    try:
        necks = [float(np.asarray(res["kps"][i][0], float)[1][1]) for i, f in enumerate(fl) if f]
        tops = []
        for j, f in enumerate(fl):
            if f:
                continue
            m = np.asarray(res["masks"][j])
            ys = np.where(m.reshape(m.shape[0], -1).any(axis=1))[0]
            if len(ys):
                tops.append(float(ys.min()))
        if necks and tops:
            return min(necks), min(tops)
    except Exception as e:
        print("[pose3d] 머리 없는 사람 높이 비교 실패 (%s) — 건너뜀" % e)
    return None


def _look_at(d, target, limit=60.0):
    """인형 고개(neck)를 target 쪽으로 돌림 (골반 기준 좌우 각도, ±limit 도)"""
    import math
    import numpy as np
    v = np.asarray(target, float) - d.pos["neck"]
    loc = d.frame["chest"].T @ v
    yaw = math.degrees(math.atan2(loc[0], loc[2]))
    d.set_joint("neck", yaw=max(-limit, min(limit, yaw)))


def depth_for(kit, ep, cut, w, h, save=True):
    """컷 크기 깊이 그림 경로 (만들 수 없으면 None). save=False 면 파일을 안 쓰고 depth_for.last_kps(인형 2D 관절)만 채움 (nk_inspect 검사기용)"""
    pp = plan_pose(cut)
    if not pp:
        return None
    pose, right, left, mirror = pp
    sys.path.insert(0, os.path.join(KIT, "tools"))
    from pose3d.body import load_settings
    from pose3d.__main__ import build
    from PIL import Image
    s = load_settings(SETTINGS)
    keep_a, keep_b = (True, True) if cut.get("_arms_all") else _arms_for(pose)
    stand_a, stand_b = not keep_a, not keep_b
    if left:                                               # 두 명: 키 비율 (큰 사람 = 1.0)
        ha, hb = _height(right), _height(left)
        top = max(ha, hb)
        s["people"] = {"a": {"scale": ha / top, "shape": dict(_shape(right), no_arms=stand_a, no_head=_faceless_of(cut, right))},
                       "b": {"scale": hb / top, "shape": dict(_shape(left), no_arms=stand_b, no_head=_faceless_of(cut, left))}}
    else:
        s["people"] = {"a": {"scale": 1.0, "shape": dict(_shape(right), no_arms=stand_a, no_head=_faceless_of(cut, right))},
                       "b": {"scale": 1.0, "shape": dict(_shape(right), no_arms=stand_b, no_head=_faceless_of(cut, right))}}
    s["camera"]["margin"] = 1.0
    s["body"]["upper_arms_only"] = False                   # 팔은 사람마다 no_arms 로 (남기면 손까지 전체, 빼면 전부)
    yaw, pitch = CAM[str(cut.get("angle") or "eye")]
    if str(cut.get("angle") or "") == "side" and pose.split("__")[0] in SIDE_YAW:   # 마주 선 두 사람은 정면 카메라가 곧 옆모습 (55도면 앞사람이 뒷사람을 가림)
        yaw = SIDE_YAW[pose.split("__")[0]]
    if "lie" in pose and str(cut.get("angle")) == "high":   # 누운 사람을 위에서 = 거의 바로 위
        yaw, pitch = 10, 80
        if "lie_stomach" in pose:
            yaw, pitch = 30, 55
    if pose == "hug_h" and cut.get("_hug_yaw") is not None and str(cut.get("angle") or "eye") == "eye":
        yaw = float(cut["_hug_yaw"])
    depth_for.last = (right, left)                          # 사람별 틀 a = right, b = left (nk_animacut 영역 글)
    if pose.startswith("p_"):
        from pose3d import poses as _P, poses_human as _PH
        ka, kb = _split_pair(pose)
        _P.POSES[pose] = _PH.pair_pose(ka, kb)
    if cut.get("_gaze") and any(cut["_gaze"]) and left:
        from pose3d import poses as _P
        base_fn = _P.POSES[pose]
        flags = list(cut["_gaze"])
        def _look(settings, swap=False, _f=base_fn, _g=flags):
            dolls, contacts = _f(settings, swap)
            if len(dolls) == 2:
                for i, d in enumerate(dolls):
                    if _g[i]:
                        _look_at(d, dolls[1 - i].pos["head"])
            return dolls, contacts
        pose_key = pose + "__look"
        _P.POSES[pose_key] = _look
        pose = pose_key
    frac = CROP.get(str(cut.get("shot") or ""), 1.0)
    H2 = int(int(h) / frac)
    res = build(pose, s, yaw, pitch, None, 35, int(w), H2)
    y0 = 0
    if left and H2 != int(h):
        # 가까운 두 명 컷에서 얼굴이 칸 밖인 사람만 머리가 없으면, 목 위 기둥이 칸 맨 위까지 이어져 몸통이 끝없이 길어 보임
        fl = [bool(s["people"]["a"]["shape"].get("no_head")), bool(s["people"]["b"]["shape"].get("no_head"))]
        if any(fl) and not all(fl):
            nv = _neck_vs_head(res, fl, H2)
            if nv and nv[0] > nv[1] - 0.04 * H2:      # 가) 머리 없는 사람의 목이 상대 머리 꼭대기보다 아래 = 키가 비슷해 머리만 칸 밖으로 못 보냄 -> 그 사람을 크게(앞에 선 것처럼), 상대를 작게 다시
                for i, f in enumerate(fl):
                    sc = s["people"]["ab"[i]]
                    sc["scale"] = float(sc["scale"]) * (1.12 if f else 0.92)
                res = build(pose, s, yaw, pitch, None, 35, int(w), H2)
                nv = _neck_vs_head(res, fl, H2)
            if nv and nv[0] < nv[1] - 0.04 * H2:      # 나) 머리 없는 사람의 목이 상대 머리보다 한참 위 = 칸 맨 위(목·머리 자리)가 기둥뿐 -> 칸을 아래로 내려 자름
                y0 = int(min(max(nv[1] - 0.08 * H2, 0), H2 - int(h)))
    def _fit(a):                                       # 가까운 구도: 위쪽 h 만 (몸 전체를 찍은 그림에서). y0 > 0 이면 그만큼 내려서
        return Image.fromarray(a).crop((0, y0, int(w), y0 + int(h))) if H2 != int(h) else Image.fromarray(a)
    if y0:
        import numpy as _np
        res = dict(res, kps=[(_np.asarray(uv, float) - _np.array([0.0, float(y0)]), vis, inside, by) for (uv, vis, inside, by) in res["kps"]])
    im, ln = _fit(res["depth"]), _fit(res["lineart"])
    masks = [_fit(m) for m in res["masks"]]
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT); ln = ln.transpose(Image.FLIP_LEFT_RIGHT)
        masks = [m.transpose(Image.FLIP_LEFT_RIGHT) for m in masks]
    depth_for.last_res = dict(res=res, w=int(w), h=int(h), H2=H2, mirror=mirror, yaw=yaw, pitch=pitch, y0=y0)
    depth_for.last_kps = _doll_kps(res, int(w), int(h), mirror, masks)
    depth_for.last_pose = pose
    import nk_webtoon as W
    out = os.path.join(W.ep_dir(kit, ep), "poses", "cut%02d_depth3d.png" % int(cut["id"]))
    if not save:
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    import json as _json
    _json.dump({"pose": pose, "people": depth_for.last_kps}, open(out.replace("_depth3d.png", "_doll_kp.json"), "w", encoding="utf-8"))
    ln.save(out.replace("_depth3d.png", "_line3d.png"))           # 인형 선화 (any-test 조종 — 몸 방향)
    from PIL import ImageFilter
    for tag, m in zip("ab", masks):
        if m.getbbox():
            m.filter(ImageFilter.MaxFilter(25)).filter(ImageFilter.GaussianBlur(6)).save(out.replace("_depth3d.png", "_mask_%s.png" % tag))
    print("[pose3d] cut %s: %s (yaw %s, pitch %s%s%s) -> %s" % (cut.get("id"), pose, yaw, pitch, ", mirrored" if mirror else "",
                                                         (", 칸 %d px 아래로 (머리 없는 사람 목 위 기둥 줄임)" % y0) if y0 else "", out))
    return out


def _doll_kps(res, w, h, mirror, masks):
    """build 결과 -> 사람마다 {names, k: [[x,y]...], ok: [1/0] (화면 안 + 안 가려짐), box: [x0,y0,x1,y1] (인형 틀 테두리)}.
    가까운 구도는 위쪽 h 만 화면 안. 거울(mirror)이면 x 를 뒤집고 왼·오른 이름을 바꿈 (그림 속 사람에게 보이는 대로)"""
    from pose3d.body import OP_NAMES
    swap = {n: (n.replace("r_", "l_", 1) if n.startswith("r_") else n.replace("l_", "r_", 1) if n.startswith("l_") else n) for n in OP_NAMES}
    out = []
    for i, (uv, vis, inside, by) in enumerate(res["kps"]):
        k = [[float(x), float(y)] for x, y in uv]
        # 자기 몸 조각(무릎뼈·아랫배·큰 발)에 가린 관절도 '있음' (검사는 위치·방향만 봄) — 다른 사람에게 가린 것만 뺌
        ok = [int(bool(inside[j]) and int(by[j]) in (-1, i) and 0 <= k[j][1] < h) for j in range(len(k))]     # 0 이상: 칸을 아래로 내려 자른 컷(y0)은 위쪽이 칸 밖
        names = list(OP_NAMES)
        if mirror:
            k = [[w - 1 - x, y] for x, y in k]
            idx = {n: j for j, n in enumerate(OP_NAMES)}
            k = [k[idx[swap[n]]] for n in OP_NAMES]
            ok = [ok[idx[swap[n]]] for n in OP_NAMES]
        bb = masks[i].getbbox() if i < len(masks) else None
        out.append({"names": names, "k": k, "ok": ok, "box": list(bb) if bb else None})
    return out


def _draft_boxes(img, n):
    """먼저 그린 그림에서 사람 칸: 혼자 = anime-seg 실루엣 테두리 (없으면 그림 전체), 둘 = 오른쪽 60% (a) / 왼쪽 60% (b) — 손이 가운데를 넘어도 잡히게"""
    H, W = img.shape[:2]
    if n == 2:
        return [(int(W * 0.4), 0, W, H), (0, 0, int(W * 0.6), H)]
    try:
        import numpy as np
        from PIL import Image
        import nk_animeseg
        m = np.array(nk_animeseg.mask(Image.fromarray(img[:, :, ::-1]))) > 128
        ys, xs = np.where(m)
        if len(xs) > 100:
            return [(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))]
    except Exception as e:
        print("[pose3d] anime-seg 없음/실패 (%s): 그림 전체로 뼈대 찾기" % e)
    return [(0, 0, W, H)]


def depth_from_draft(kit, ep, cut, w, h, draft):
    """목록 밖 자세 (plan_pose 가 'dw'): 먼저 그린 그림 draft -> DWPose 뼈대 -> 캐릭터 몸 비율 인형(키·골반·팔다리 길이) -> 깊이·선화·사람별 틀.
    결과 파일은 depth_for 와 같음 (cutNN_depth3d.png ...). 뼈대를 못 찾으면 None (그러면 조종 없이 그림)"""
    import cv2
    import numpy as np
    pp = plan_pose(cut)
    if not pp:
        return None
    _, right, left, _m = pp
    p = os.path.join(KIT, "tools")
    if p not in sys.path:
        sys.path.insert(0, p)
    from pose3d.body import load_settings, scaled_body
    from pose3d import lift2d as L2, render as R
    import nk_pose
    from PIL import Image, ImageFilter
    img = cv2.imread(draft)
    if img is None:
        return None
    img = cv2.resize(img, (int(w), int(h))) if img.shape[1] != int(w) or img.shape[0] != int(h) else img
    chars = [c for c in (right, left) if c]
    people = [nk_pose.pose_one(img, bx) for bx in _draft_boxes(img, len(chars))]
    if sum(int((c[:17] >= 0.3).sum()) for _, c in people) < 8 * len(chars):
        H0, W0 = img.shape[:2]
        flipped = cv2.rotate(img, cv2.ROTATE_180)
        alt = []
        for bx in _draft_boxes(flipped, len(chars)):
            k, c = nk_pose.pose_one(flipped, bx)
            alt.append((np.stack([W0 - 1 - k[:, 0], H0 - 1 - k[:, 1]], 1), c))
        if sum(int((c[:17] >= 0.3).sum()) for _, c in alt) > sum(int((c[:17] >= 0.3).sum()) for _, c in people):
            people = alt
            print("[pose3d] cut %s: 거꾸로 선 사람: 그림을 돌려 뼈대를 찾음" % cut.get("id"))
    s = load_settings(SETTINGS)
    top = max(_height(c) for c in chars)
    bodies = []
    for c in chars:
        s["people"] = {"a": {"scale": _height(c) / top, "shape": dict(_shape(c), no_arms=False, upper_arms_only=False)}}
        bodies.append(scaled_body(s, "a"))
    words = _words(cut.get("scene"))
    hint = -1 if (str(cut.get("angle")) == "back" or "from behind" in words) else None
    dolls, cam = L2.lift(people, bodies, int(w), int(h), lean_sign=-1.0 if str(cut.get("angle")) == "low" else 1.0, face_hint=hint)
    if not dolls:
        print("[pose3d] cut %s: 먼저 그린 그림에서 뼈대를 못 찾음 -> 조종 없이" % cut.get("id"))
        return None
    rr = R.render(dolls, cam)
    import nk_webtoon as W
    out = os.path.join(W.ep_dir(kit, ep), "poses", "cut%02d_depth3d.png" % int(cut["id"]))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    Image.fromarray(R.depth_image(rr)).save(out)
    Image.fromarray(R.line_image(rr)).save(out.replace("_depth3d.png", "_line3d.png"))
    for tag, m in zip("ab", R.person_masks(rr, len(dolls))):
        m = Image.fromarray(m)
        if m.getbbox():
            m.filter(ImageFilter.MaxFilter(25)).filter(ImageFilter.GaussianBlur(6)).save(out.replace("_depth3d.png", "_mask_%s.png" % tag))
    depth_for.last = (right, left)
    depth_for.last_res = dict(res={"cam": cam, "dolls": dolls}, w=int(w), h=int(h), H2=int(h), mirror=False, yaw=0, pitch=0)
    depth_for.last_pose = "dw"
    print("[pose3d] cut %s: dw (먼저 그린 그림의 뼈대 %d명 -> 인형 비율) -> %s" % (cut.get("id"), len(dolls), out))
    return out
