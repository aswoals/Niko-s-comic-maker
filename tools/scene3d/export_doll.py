# -*- coding: utf-8 -*-
"""캡슐 인형 장면 -> JSON (Blender 3D 장면 렌더러 tools/scene3d/render_scene.py 가 읽음)
좌표는 인형 그대로 (+y 위, +z 카메라 쪽, 큰 사람 키 ≈ 1.0). render_scene 이 Blender 좌표(+z 위, -y 앞)로 바꿈."""
import json
import re
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KIT); sys.path.insert(0, os.path.join(KIT, "tools"))


def doll_json(d):
    import numpy as np
    pos = {j: [float(v) for v in p] for j, p in d.pos.items() if not j.startswith("tail")}
    frames = {j: np.asarray(d.frame[j]).tolist() for j in ("pelvis", "chest", "head")}
    return {"pos": pos, "frame": frames, "height": float(d.b["thigh"] + d.b["shin"] + d.b["torso"] + d.b["neck"] + 2 * d.b["head_ry"]),
            "no_arms": bool(d.b.get("no_arms")), "extra": [[e[0], e[1], [float(v) for v in e[2]], [float(v) for v in e[3]], float(e[4])] for e in d.extra if e[0] == "cap"]}


def export(cut, w, h, chars, out_json):
    """cut: 콘티 컷 dict (_roles/_char 가 붙은 것), chars: 사람마다 VRM 경로 [a, b]"""
    import nk_pose3d_auto as P3
    P3.depth_for(KIT, "scene3d", cut, w, h, save=False)
    L = P3.depth_for.last_res
    cam = L["res"]["cam"]
    data = {"W": int(w), "H": int(L["H2"]), "crop_h": int(h), "mirror": bool(L["mirror"]), "pose": P3.depth_for.last_pose,
            "camera": {"pos": [float(v) for v in cam.pos], "target": [float(v) for v in cam.target], "fov": float(cam.fov)},
            "people": [dict(doll_json(d), vrm=chars[i] if i < len(chars) else chars[-1]) for i, d in enumerate(L["res"]["dolls"])]}
    json.dump(data, open(out_json, "w", encoding="utf-8"), indent=1)
    return data


# Blender 렌더러는 이 공개본에 들어 있지 않음 (bpy 스크립트는 Blender 의 GPL 조건을 따름).
# 직접 만든 렌더러가 있으면 NK_BLENDER = blender.exe 경로, NK_SCENE3D_RENDER = 렌더 스크립트 경로를 설정. 없으면 캡슐 인형 그대로.
BLENDER = os.environ.get("NK_BLENDER", "")
RENDER = os.environ.get("NK_SCENE3D_RENDER") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_scene.py")


def render(scene_json, out_dir, timeout=600):
    import subprocess
    if not (BLENDER and os.path.exists(BLENDER) and os.path.exists(RENDER)):
        return False                    # 렌더러 없음 -> 부르는 쪽이 캡슐 인형 그대로 씀
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", RENDER, "--", scene_json, out_dir],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    ok = "SCENE3D_DONE" in (r.stdout or "")
    if not ok:
        open(os.path.join(out_dir, "blender_log.txt"), "w", encoding="utf-8").write((r.stdout or "") + (r.stderr or ""))
    return ok


def finish(scene, out_dir, dest, parts=("depth", "line", "mask")):
    """Blender 출력 -> 캡슐 인형과 같은 파일 (dest = .../cutNN_depth3d.png): 가까운 구도는 위쪽만, 거울이면 뒤집기, 선은 흰 선·검정 바탕, 사람별 틀은 퍼뜨려 흐리게"""
    from PIL import Image, ImageOps, ImageFilter
    import numpy as np
    w, h = scene["W"], scene["crop_h"]
    def fit(im):
        im = im.crop((0, 0, w, h)) if im.height != h else im
        return im.transpose(Image.FLIP_LEFT_RIGHT) if scene["mirror"] else im
    dep = fit(Image.open(os.path.join(out_dir, "depth.png")).convert("RGB"))
    line = fit(ImageOps.invert(Image.open(os.path.join(out_dir, "line_bw.png")).convert("L")))
    m = np.asarray(fit(Image.open(os.path.join(out_dir, "mask.png")).convert("RGB")))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if "depth" in parts:
        dep.save(dest)
    if "line" in parts:
        Image.merge("RGB", [line] * 3).save(dest.replace("_depth3d.png", "_line3d.png"))
    for tag, ch in (("a", 0), ("b", 1)) if "mask" in parts else ():
        mk = Image.fromarray(((m[:, :, ch] > 128) & (m[:, :, 1 - ch] < 128)).astype("uint8") * 255)
        if mk.getbbox():
            mk.filter(ImageFilter.MaxFilter(25)).filter(ImageFilter.GaussianBlur(6)).convert("RGB").save(dest.replace("_depth3d.png", "_mask_%s.png" % tag))
    return dest


VRM_DIR = os.environ.get("NK_VRM_DIR", "")      # (선택) CC0 VRM 몸 모델 폴더


def vrm_for(ch):
    """캐릭터 파일 vrm (없으면 남/여 기본 CC0 몸)"""
    ch = ch or {}
    if ch.get("vrm"):
        return ch["vrm"]
    tg = str(ch.get("tags_full", "")).lower()
    male = "1boy" in tg or bool(re.search(r"(^|[ ,])male([ ,]|$)", tg))
    return os.path.join(VRM_DIR, "Base_Male.vrm" if male else "Base_Female.vrm").replace("\\", "/")


def outfit_for(ch):
    """캐릭터 -> 3D 옷 종류 (캐릭터 파일 outfit3d, 없으면 태그로)"""
    ch = ch or {}
    if ch.get("outfit3d"):
        return str(ch["outfit3d"])
    if is_furry(ch):
        return "fur"
    tg = (str(ch.get("tags_full", "")) + " " + str(ch.get("anima", ""))).lower()
    for key, kind in (("dress", "dress"), ("skirt", "tee_skirt"), ("coat", "coat"), ("jacket", "coat"), ("shorts", "tee_shorts")):
        if key in tg:
            return kind
    return "tee_pants"


def props_for(cut):
    """컷 태그 -> 3D 소품 목록 (태그 낱말 그대로)"""
    w = " " + " ".join(str(cut.get(k) or "") for k in ("scene", "anima_act")).lower() + " "
    has = lambda *ks: any(re.search(r"(^|[\s,.])" + re.escape(k) + r"($|[\s,.])", w) for k in ks)
    out = []
    for keys, name in ((("soccer ball", "ball"), "ball"), (("umbrella", "holding umbrella"), "umbrella"), (("table", "desk"), "table"), (("bed", "on bed"), "bed")):
        if has(*keys):
            out.append(name)
    return out


def is_furry(ch):
    ch = ch or {}
    if ch.get("body3d_kind"):
        return ch["body3d_kind"] == "furry"
    tg = str(ch.get("tags_full", "")).lower()
    return any(k in tg for k in ("furry", "anthro"))


def animal(ch):
    """캐릭터 -> 3D 동물 부위 {kind, ears, tail} (캐릭터 파일 ears3d/tail3d, 없으면 태그로: cat ears·rabbit ears·cat tail)"""
    ch = ch or {}
    tg = (str(ch.get("tags_full", "")) + " " + str(ch.get("anima", ""))).lower()
    ears = ch.get("ears3d") or ("cat" if ("cat ears" in tg or "felid" in tg or "domestic cat" in tg or " cat " in tg) else
                                "rabbit" if ("rabbit ears" in tg or "rabbit" in tg or "lagomorph" in tg) else "none")
    tail = ch.get("tail3d") or ("cat" if ("cat tail" in tg or "felid" in tg or "domestic cat" in tg) else "rabbit" if "rabbit" in tg else "none")
    return {"kind": "furry" if is_furry(ch) else "human", "ears": ears, "tail": tail}


def make_cut(kit, ep, cut, w, h, dest, parts=("depth", "line", "mask")):
    """nk_animacut 에서: depth_for 가 막 만든 인형 장면으로 3D 렌더 -> dest(cutNN_depth3d.png) 와 같은 이름들을 덮어씀. 성공하면 True"""
    import nk_pose3d_auto as P3
    right, left = getattr(P3.depth_for, "last", (None, None))
    chars = [vrm_for(right)] + ([vrm_for(left)] if left else [])
    work = os.path.join(os.path.dirname(dest), "scene3d_cut%02d" % int(cut["id"]))
    os.makedirs(work, exist_ok=True)
    sj = os.path.join(work, "scene.json")
    L = P3.depth_for.last_res
    cam = L["res"]["cam"]
    outfits = [outfit_for(c) for c in (right, left) if c]
    extras = [animal(c) for c in (right, left) if c]
    data = {"W": int(w), "H": int(L["H2"]), "crop_h": int(h), "mirror": bool(L["mirror"]), "pose": P3.depth_for.last_pose,
            "camera": {"pos": [float(v) for v in cam.pos], "target": [float(v) for v in cam.target], "fov": float(cam.fov)},
            "people": [dict(doll_json(d), vrm=chars[min(i, len(chars) - 1)], outfit=outfits[min(i, len(outfits) - 1)], **extras[min(i, len(extras) - 1)])
                       for i, d in enumerate(L["res"]["dolls"])],
            "props": props_for(cut)}
    json.dump(data, open(sj, "w", encoding="utf-8"), indent=1)
    if not render(sj, work):
        return False
    finish(data, work, dest, parts)
    print("[scene3d] cut %s: 3D 장면 (%s) -> %s" % (cut.get("id"), ", ".join(os.path.basename(c) for c in chars), dest))
    return True
