# -*- coding: utf-8 -*-
"""두 명 컷 '따로 그려서 합치기' 시험

왜: 한 장에 두 캐릭터를 같이 그리면(MB·N·A 방식) 그리는 도중 두 캐릭터 특징이 섞임 (의미 누출, Bounded Attention 논문)
검은 머리 0.49~0.69.
    부정 태그로 못 막음.
어떻게: 혼자 컷은 디자인이 잘 나옴 -> 같은 에피소드의 각 캐릭터 혼자 컷 최종본을 Qwen-Image-Edit-2509에
    그림 1·2로 주고 "두 캐릭터를 한 장면에" 새로 그리게 함 (모델 카드: 입력 1~3장, 'person + person' 조합 지원).
    그림체 입히기(nk_restyle)에 쓰는 모델 그대로 -> 새로 설치하는 것 없음.

사용: nk ep compose <ep> <컷...> [--seed 51] [--tries 2] [--dry]   (비교만, 최종본 안 바꿈)
      nk ep compose <ep> <컷...> --apply   (판별기로 가장 나은 후보를 골라 최종본으로. 원래 최종본은 cuts_compose/orig/)
      nk ep compose <ep> --use 8=52        (사람이 고름 / 8=0 = 합치기 전으로 되돌림)
      nk ep auto 는 두 명 컷을 기본으로 이 방식으로 만듦 (--duo draw = 예전 MB 방식)
결과: episodes/<ep>/cuts_compose/cand/cutNN_s<seed>.png + cutNN_cmp.png (재료 | 지금 최종본 | 후보들) + compose.json
1차는 소품(눈사람)이 빠짐 ->
      소품을 따로 한 문장 + 서 있는 전신 재료 우선으로 고친 2차는 2장 모두 눈사람·자세 맞음."""
import os
import sys
import json

SHOT = {"wide": "a wide shot showing the whole place, both characters small and full body",
        "full": "full body, both characters shown from head to feet",
        "knee": "shown from the knees up", "waist": "shown from the waist up", "face": "close-up of both faces",
        "eyes": "close-up of both faces", "hands": "close-up of their hands"}
ANGLE = {"eye": "camera at eye level", "low": "camera slightly below, looking up", "high": "camera slightly above, looking down",
         "side": "seen from the side", "back": "seen from behind", "tilt": "tilted camera", "pov": "first-person view"}


def _who(conti, cut):
    """이 컷에 보이는 캐릭터 짧은 이름 목록"""
    if cut.get("_roles"):
        return [str(r["char"]) for r, _ in cut["_roles"]]
    return [cut["_charkey"]] if cut.get("_charkey") else []


def pick_sources(W, kit, conti, cut, override=None):
    """두 명 컷의 사람마다 재료로 쓸 혼자 컷 하나: 같은 장소 +2, 전신(full) +1.5 / 무릎(knee) +1, 얼굴·소품 컷 제외,
    같으면 번호가 가까운 컷"""
    ep = conti["_ep"]
    cid = int(cut["id"])
    out = {}
    for r, ch in cut["_roles"]:
        key = str(r["char"])
        if override and key in override:
            out[key] = int(override[key]); continue
        best = None
        for c2 in conti["cuts"]:
            if c2.get("_roles") or c2.get("_charkey") != key:
                continue
            if str(c2.get("shot", "")) in ("face", "detail", "eyes", "hands"):
                continue
            f = W._final_file(kit, ep, int(c2["id"]))
            if not os.path.exists(f):
                continue
            whole = str(cut.get("shot")) in ("full", "wide")      # 전신 두 명 컷이면 무늬(다리·꼬리)가 다 보이는 전신 재료가 중요
            sc = (2 if c2.get("loc") == cut.get("loc") else 0) + {"full": 2.0 if whole else 1.5, "knee": 1.0}.get(str(c2.get("shot")), 0)
            sc2 = str(c2.get("scene", ""))
            sc += 0.5 if "standing" in sc2 else 0
            sc -= 1.5 if any(w in sc2 for w in ("sitting", "crouching", "kneeling", "squatting", "lying")) else 0
            # 이번엔 컷 10이 앞모습으로 그려져서 괜찮았지만, 제대로 뒷모습이면 얼굴 없는 재료가 됨 -> 크게 뺌
            sc -= 5 if str(c2.get("angle", "")) == "back" else 0
            key2 = (sc, -abs(int(c2["id"]) - cid))
            if best is None or key2 > best[0]:
                best = (key2, int(c2["id"]))
        if best is None:
            raise LookupError("cut %d: no solo picture of '%s' in %s to use (give one: --src %s=<cut>)" % (cid, key, ep, key))
        out[key] = best[1]
    return out


#   ② "Draw a new anime illustration ... Clean line art" -> 깨끗한 셀화로 끌림
#   keepstyle = 이름 빼고, 재료 두 장과 같은 그림체(선·명암·색)로 그리라고 함
#   예전 문장 = --prompt classic (비교용)
DEFAULT_PROMPT = "keepstyle"
PROMPT_VARIANT = DEFAULT_PROMPT


def _strip_names(desc):
    """a small robot boy ...' -> 'a small robot boy ...'"""
    import re
    return re.sub(r"^[^,]{1,60}\bfrom\b[^,]{1,60},\s*", "", str(desc or "")).strip()


def build_prompt(conti, cut):
    keep = PROMPT_VARIANT == "keepstyle"
    roles = sorted(cut["_roles"], key=lambda rc: 0 if rc[0].get("side") == "left" else 1)   # 그림 1 = 왼쪽 사람
    names = []
    lines = []
    for i, (r, ch) in enumerate(roles, 1):
        nm = "the %s" % (ch.get("compose_name") or "character")
        if ch.get("compose_name") is None:
            nm = "the character from picture %d" % i
        names.append(nm)
        desc = ch.get("anima") or ch.get("name", "")
        if keep:
            desc = _strip_names(desc)
        lines.append("Picture %d: %s (%s)." % (i, nm, desc))
    loc = ((conti.get("world") or {}).get("locations") or {}).get(cut.get("loc")) or {}
    loc_tags = loc.get("tags", "") if isinstance(loc, dict) else str(loc)
    acts = []
    for (r, ch), nm in zip(roles, names):
        if r.get("pos"):
            acts.append("%s: %s" % (nm[0].upper() + nm[1:], r["pos"]))
    # 다른 캐릭터 전용 소품(안경·망토 등)은 그 캐릭터만 (두 명 컷 번짐의 대표 증상)
    only = []
    for (r, ch), nm in zip(roles, names):
        if ch.get("duo_exclusive"):
            only.append("Only %s wears %s." % (nm, ch["duo_exclusive"]))
    common = ", ".join(t.strip() for t in str(cut.get("scene", "")).split(",")
                       if t.strip() and t.strip() not in ("duo", "2boys", "solo"))
    wprops = (conti.get("world") or {}).get("props") or {}
    props = []
    for pn in cut.get("props") or []:
        pv = wprops.get(pn) or {}
        props.append(pv.get("tags", pn) if isinstance(pv, dict) else str(pv))
    prop_txt = (" Clearly show %s in the scene, between or next to the two characters." % " and ".join(props)) if props else ""
    stand = " Both characters are standing." if "standing" in common else ""
    if keep:
        head = (" Draw a new illustration with both characters together in one scene, in exactly the same drawing style as the "
                "two pictures (same line weight, same soft shading, same coloring and the same proportions for both): "
                "%s on the left and %s on the right, side by side, not touching, not overlapping.")
        tail = " One single panel."
    else:
        head = (" Draw a new anime illustration with both characters together in one scene: %s on the left and %s on the right, "
                "side by side, not touching, not overlapping.")
        tail = " Clean line art, one single panel."
    txt = " ".join(lines) + (
        head + "%s%s %s, %s. %s. Setting: %s. %s "
        "Keep each character's body shape, fur colors, markings and accessories exactly as in their picture. "
        "Do not add clothes, hair or glasses that are not in their picture." + tail
        ) % (names[0], names[1], stand, prop_txt, SHOT.get(str(cut.get("shot")), "full body"), ANGLE.get(str(cut.get("angle", "eye")), ""),
             ". ".join(acts) + (". " + common if common else ""), loc_tags, " ".join(only))
    return " ".join(txt.split()), [str(r["char"]) for r, _ in roles]


SUB, RUN = "", "compose"


def graph(img1, img2, prompt, seed, prefix, w, h):
    import nk_restyle as R
    Q = R.QWEN
    g = {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": Q["unet"], "weight_dtype": "default"}},
        "89": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["37", 0], "strength_model": 1.0, "lora_name": Q["lightning"]}},
        "66": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["89", 0], "shift": 3.0}},
        "75": {"class_type": "CFGNorm", "inputs": {"model": ["66", 0], "strength": 1.0}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": Q["clip"], "type": "qwen_image", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": Q["vae"]}},
        "78": {"class_type": "LoadImage", "inputs": {"image": img1}},
        "79": {"class_type": "LoadImage", "inputs": {"image": img2}},
        "80": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["78", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                                                 "resolution_steps": 16}},
        "81": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["79", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                                                 "resolution_steps": 16}},
        "111": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["38", 0], "vae": ["39", 0],
                                                                       "image1": ["80", 0], "image2": ["81", 0], "prompt": prompt}},
        "110": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["38", 0], "vae": ["39", 0],
                                                                       "image1": ["80", 0], "image2": ["81", 0], "prompt": ""}},
        "90": {"class_type": "EmptySD3LatentImage", "inputs": {"width": int(w), "height": int(h), "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": 8, "cfg": 1.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": 1.0, "model": ["75", 0],
                                                   "positive": ["111", 0], "negative": ["110", 0], "latent_image": ["90", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }
    return R.add_ref_method(g)


def can_compose(conti, cut):
    """두 명 컷의 사람마다 재료가 될 혼자 컷(얼굴·소품 클로즈업 아닌 것)이 콘티에 있나 (아직 안 그렸어도 됨)"""
    if not cut.get("_roles"):
        return False
    for r, _ in cut["_roles"]:
        key = str(r["char"])
        if not any((not c2.get("_roles")) and c2.get("_charkey") == key and str(c2.get("shot", "")) not in ("face", "detail", "eyes", "hands")
                   for c2 in conti["cuts"]):
            return False
    return True


def _base_size(cut):
    try:
        w, h = [int(x) for x in str(cut.get("size", "")).split("x")]
        return w, h
    except ValueError:
        return 896, 1152


def _jobs(nk, kit, cfg, conti, ids, override, seeds, dry):
    import nk_webtoon as W
    import nk_restyle as R
    from PIL import Image
    ep = conti["_ep"]
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    jobs, info, errors = [], {}, {}
    for cid in ids:
        cut = cuts.get(cid)
        if not cut or not cut.get("_roles"):
            print("[skip] cut %d is not a two-character cut" % cid); continue
        try:
            src = pick_sources(W, kit, conti, cut, override)
        except LookupError as e:
            print("[ERROR]", e); errors[cid] = str(e); continue
        text, order = build_prompt(conti, cut)
        final = W._final_file(kit, ep, cid)
        if os.path.exists(final):
            w0, h0 = Image.open(final).size
        else:                                   # 다른 컷 최종본과 같은 크기 (그리기 크기 x final_hires)
            bw, bh = _base_size(cut)
            fh = float((cfg.get("defaults") or {}).get("final_hires") or 1.5)
            w0, h0 = int(round(bw * fh)), int(round(bh * fh))
        w, h = R.fit_size(w0, h0)
        up = []
        for key in order:
            p = W._final_file(kit, ep, src[key])
            up.append(W._upload_input(nk, cfg, p, "%s_compose_src_cut%02d.png" % (ep, src[key]), dry))
        info[cid] = {"src": {k: src[k] for k in order}, "order": order, "size": [w0, h0], "prompt": text}
        print("cut %d: %s  (%dx%d)\n  %s" % (cid, ", ".join("%s <- cut %d" % (k, src[k]) for k in order), w, h, text))
        for sd in seeds:
            label = "cut%02d_s%d" % (cid, sd)
            jobs.append({"label": label, "graph": graph(up[0], up[1], text, sd, "nk/%s_%s/%s" % (ep, RUN, label), w, h),
                         "positive": text, "negative": "", "seed": sd,
                         "settings": {"cfg": 1.0, "steps": 8, "width": w, "height": h, "model": R.QWEN["unet"]}})
    return jobs, info, errors


def _collect(nk, kit, cfg, conti, res, info):
    import nk_webtoon as W
    from PIL import Image, ImageDraw
    ep = conti["_ep"]
    d = os.path.join(W.ep_dir(kit, ep), "cuts_compose", SUB) if SUB else os.path.join(W.ep_dir(kit, ep), "cuts_compose")
    src_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), ep, RUN)
    os.makedirs(os.path.join(d, "cand"), exist_ok=True)
    made = {}
    for r in res:
        cid = int(r["label"][3:5])
        w0, h0 = info[cid]["size"]
        im = Image.open(os.path.join(src_dir, r["file"])).convert("RGB").resize((w0, h0), Image.LANCZOS)
        p = os.path.join(d, "cand", r["label"] + ".png")
        im.save(p)
        made.setdefault(cid, []).append((int(r["seed"]), p))
    # 비교 한 장: 재료 1 | 재료 2 | 지금 최종본 | 합친 후보들
    H = 640
    for cid, cands in made.items():
        tiles = [("src %s (cut %d)" % (k, info[cid]["src"][k]), W._final_file(kit, ep, info[cid]["src"][k]))
                 for k in info[cid]["order"]]
        if os.path.exists(W._final_file(kit, ep, cid)):
            tiles.append(("now", W._final_file(kit, ep, cid)))
        tiles += [(os.path.basename(p)[:-4], p) for _, p in sorted(cands)]
        ims = []
        for lb, p in tiles:
            im = Image.open(p).convert("RGB")
            ims.append((lb, im.resize((int(im.width * H / im.height), H))))
        sheet = Image.new("RGB", (sum(i.width for _, i in ims) + 10 * (len(ims) - 1), H + 24), "white")
        dr = ImageDraw.Draw(sheet)
        x = 0
        for lb, im in ims:
            sheet.paste(im, (x, 24)); dr.text((x + 4, 6), lb, fill="black"); x += im.width + 10
        sheet.save(os.path.join(d, "cut%02d_cmp.png" % cid))
        info[cid]["cands"] = [os.path.basename(p) for _, p in sorted(cands)]
    return made


# / 1차 컷 10 눈사람 0.00~0.01 (빠짐). 문턱 0.35 = 태그 판별 기본값 (소품 qa min과 같음)
BAD_MIN, PROP_MIN = 0.35, 0.35

#   ① 눈 색: 자기 눈 색(캐릭터 파일의 '<색> eyes') 점수 0.3 미만 + 다른 색 0.4 이상 -> 흠.
#   ② 자세: 콘티 scene·roles의 자세 태그(sitting 등)가 그림 전체에서 0.3 미만 -> 흠.
EYE_COLORS = ["blue", "yellow", "orange", "red", "pink", "green", "brown", "purple", "aqua", "grey", "black", "white"]
EYE_NEAR = {"pink": ["red", "purple"], "red": ["pink", "orange"], "yellow": ["orange"], "orange": ["yellow", "red"],
            "blue": ["aqua"], "aqua": ["blue", "green"], "green": ["aqua"], "purple": ["pink"]}
POSE = ["sitting", "walking", "running", "lying", "on back", "on stomach", "kneeling", "squatting",
        "crouching", "jumping", "eating", "sleeping"]
EYE_OK_MIN, EYE_BAD_MIN, HETERO_MIN, POSE_MIN = 0.3, 0.4, 0.5, 0.3
SEVERE = (" has ", " eyes look ", "heterochromia", "pose: ", "heads", "new figure", "figures:", "grid pattern")     # 순위: 이런 흠이 적은 후보가 먼저
EXTRA_ROUND = True     # 후보가 전부 심한 흠이면 시드 2개 더 (한 번만, 컷당 약 5분)
HEAD_CHECK = True
FIG_CHECK = True
FIG_MIN = 0.002        # 이보다 작은 덩어리는 안 셈 (그림의 0.2%; 작은 주황 생물 0.44%)


def _char_text(ch):
    return ", ".join(str(ch.get(k) or "") for k in ("tags_full", "tags_short")).replace("\n", " ").lower()


def eye_colors(ch):
    """캐릭터 파일 태그의 '<색> eyes' -> ['blue'] (sclera 는 뺌)"""
    out = set()
    for t in _char_text(ch).split(","):
        w = t.strip().strip("()").split(":")[0].split()
        if len(w) == 2 and w[1] == "eyes" and w[0] in EYE_COLORS:
            out.add(w[0])
    return sorted(out)


def eye_flags(t, key, ch):
    """판별기 결과 t(자기 쪽 절반) -> (flags, 감점, detail)"""
    exp = eye_colors(ch)
    flags, pen, det = [], 0.0, {}
    if exp:
        okc = set(exp) | {n for e in exp for n in EYE_NEAR.get(e, [])}
        own = max(t.get(c + "_eyes", 0.0) for c in okc)
        other = max(((t.get(c + "_eyes", 0.0), c) for c in EYE_COLORS if c not in okc), default=(0.0, ""))
        det["%s:eyes_own" % key] = round(own, 2)
        det["%s:eyes_other" % key] = "%s %.2f" % (other[1], other[0])
        if own < EYE_OK_MIN and other[0] >= EYE_BAD_MIN:
            flags.append("%s eyes look %s (%.2f), not %s" % (key, other[1], other[0], "/".join(exp)))
            pen += other[0]
    het = t.get("heterochromia", 0.0)
    if het >= HETERO_MIN and "heterochromia" not in _char_text(ch):
        flags.append("%s heterochromia (%.2f)" % (key, het))
        pen += het
    return flags, pen, det


def pose_flags(ta, cut):
    """콘티 scene + 사람별 roles 의 자세 태그가 그림 전체에 있나"""
    words = [str(cut.get("scene", ""))] + [str(r.get("pos", "")) for r, _ in (cut.get("_roles") or [])]
    have = {x.strip().lower() for w in words for x in w.split(",") if x.strip()}
    flags, pen, det = [], 0.0, {}
    for p in POSE:
        if p in have:
            v = ta.get(p.replace(" ", "_"), 0.0)
            det["pose:" + p] = round(v, 2)
            if v < POSE_MIN:
                flags.append("pose: no %s (%.2f)" % (p, v))
                pen += 0.5
    return flags, pen, det


def judge(kit, conti, cut, path):
    import nk_tagger
    from PIL import Image
    ok, why = nk_tagger.available(kit)
    if not ok:
        return 0.0, [], {"note": "no tagger: " + why}
    im = Image.open(path).convert("RGB")
    w, h = im.size
    base = os.path.splitext(path)[0]
    if os.path.basename(os.path.dirname(path)).lower() == "cuts":
        jd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), "_judge")
        os.makedirs(jd, exist_ok=True)
        base = os.path.join(jd, os.path.basename(base))
    flags, sc, det = [], 0.0, {}
    for r, ch in cut["_roles"]:
        key = str(r["char"])
        side = str(r.get("side", "left"))
        tmp = "%s__%s.png" % (base, key)                 # 후보·사람마다 다른 파일 (판별기 캐시가 경로+시각 기준)
        im.crop((0, 0, w // 2, h) if side == "left" else (w // 2, 0, w, h)).save(tmp)
        t = nk_tagger.tags(kit, tmp) or {}
        own = set(x.strip() for x in str(ch.get("tags_full") or ch.get("tags_short") or "").split(","))
        bad = [x.strip() for x in str(ch.get("forbid") or "").split(",") if x.strip()]
        for r2, c2 in cut["_roles"]:
            if r2 is not r:
                bad += [x.strip() for x in str(c2.get("duo_exclusive") or "").split(",") if x.strip() and x.strip() not in own]
        for tg in sorted(set(bad)):
            v = nk_tagger.score(t, tg)
            det["%s:%s" % (key, tg)] = round(v, 2)
            if v >= BAD_MIN:
                flags.append("%s has %s (%.2f)" % (key, tg, v)); sc -= v
        fl2, pen, d2 = eye_flags(t, key, ch)
        flags += fl2; sc -= pen; det.update(d2)
    ta = nk_tagger.tags(kit, path) or {}
    fl3, pen, d3 = pose_flags(ta, cut)
    flags += fl3; sc -= pen; det.update(d3)
    wprops = (conti.get("world") or {}).get("props") or {}
    for pn in cut.get("props") or []:
        pv = wprops.get(pn) or {}
        tg = "|".join(x.strip() for x in str(pv.get("tags", pn) if isinstance(pv, dict) else pv).split(",") if x.strip())
        v = nk_tagger.score(ta, tg)
        det["prop:" + pn] = round(v, 2)
        if v < PROP_MIN:
            flags.append("no %s (%.2f)" % (pn, v)); sc -= 0.5
        else:
            sc += v
    return round(sc, 3), flags, det


#    -> 머리 비슷한 소품(눈사람·인형·가면 ...)이 콘티에 있으면 하나당 2개까지 봐 줌. 면적 0.4% 미만은 버림 (잡티)
HEAD_PROMPT, HEAD_TH, HEAD_MIN_AREA, HEAD_MERGE = "head:4", 0.3, 0.004, 0.5
HEADLIKE = ("snowman", "doll", "plush", "stuffed", "teddy", "statue", "mask", "scarecrow", "figurine", "mannequin",
            "puppet", "skull", "portrait", "painting", "poster", "mirror", "reflection", "crowd", "photo")
_HEADS = {}


HEAD_FLOOR = 0.0002        # 이보다 작은 SAM 조각은 버림 (잡음). 작은 머리 비교(unify)는 min_area를 낮춰서 셈


def head_counts(nk, kit, cfg, ep, paths, run="compose_heads", min_area=None):
    """SAM3로 그림마다 머리 개수 (면적 min_area(기본 HEAD_MIN_AREA) 이상). 같은 파일·시각이면 다시 안 잼. -> {경로: (개수, [면적])}"""
    min_area = HEAD_MIN_AREA if min_area is None else float(min_area)
    import nk_sam
    from PIL import Image
    import numpy as np
    todo = [p for p in paths if (p, os.path.getmtime(p)) not in _HEADS]
    if todo:
        items = [("h%03d_%s" % (i, os.path.splitext(os.path.basename(p))[0][:24]), p, HEAD_PROMPT) for i, p in enumerate(todo)]
        try:
            got = nk_sam.segment(nk, kit, cfg, ep, items, HEAD_TH, run=run, individual=True)
        except SystemExit:
            print("[heads] SAM3 failed -> head count skipped"); got = {}
        for name, p, pr in items:
            ms = []
            for mp in got.get((name, pr), []):
                m = np.asarray(Image.open(mp).convert("L")) > 127
                if float(m.mean()) >= HEAD_FLOOR:
                    ms.append(m)
            grp = list(range(len(ms)))
            def root(i):
                while grp[i] != i:
                    i = grp[i]
                return i
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    inter = float((ms[i] & ms[j]).sum())
                    if inter / max(1.0, min(ms[i].sum(), ms[j].sum())) >= HEAD_MERGE:
                        grp[root(j)] = root(i)
            blobs = {}
            for i, m in enumerate(ms):
                r = root(i)
                blobs[r] = (blobs[r] | m) if r in blobs else m
            areas = sorted((round(float(m.mean()), 5) for m in blobs.values()), reverse=True)
            _HEADS[(p, os.path.getmtime(p))] = areas if (name, pr) in got else None

    def cnt(v):
        if v is None:
            return (None, [])
        a = [round(x, 4) for x in v if x >= min_area]
        return (len(a), a)
    return {p: cnt(_HEADS.get((p, os.path.getmtime(p)))) for p in paths}


FIG_PROMPT = "animal:6"
_BLOBS = {}


def sam_blobs(nk, kit, cfg, ep, paths, prompt=FIG_PROMPT, run="figs", size=160, threshold=None):
    """-> {경로: [bool 마스크 size x size] 또는 None}. prompt 는 글 하나 또는 여러 개(마스크를 모두 모음).
    겹친 것(작은 쪽의 50%)은 합침, HEAD_FLOOR 미만은 버림"""
    import nk_sam
    from PIL import Image
    import numpy as np
    prompts = [prompt] if isinstance(prompt, str) else list(prompt)
    th = HEAD_TH if threshold is None else float(threshold)
    key = lambda p: (p, os.path.getmtime(p), tuple(prompts), th)
    todo = [p for p in paths if key(p) not in _BLOBS]
    if todo:
        names = [("b%03d_%s" % (i, os.path.splitext(os.path.basename(p))[0][:24]), p) for i, p in enumerate(todo)]
        items = [(nm, p, pr) for nm, p in names for pr in prompts]
        try:
            got = nk_sam.segment(nk, kit, cfg, ep, items, th, run=run, individual=True)
        except SystemExit:
            print("[figures] SAM3 failed -> skipped"); got = {}
        for name, p in names:
            if not any((name, pr) in got for pr in prompts):
                _BLOBS[key(p)] = None; continue
            ms = []
            for mp in [m for pr in prompts for m in got.get((name, pr), [])]:
                m = np.asarray(Image.open(mp).convert("L").resize((size, size))) > 127
                if float(m.mean()) >= HEAD_FLOOR:
                    ms.append(m)
            grp = list(range(len(ms)))

            def root(i):
                while grp[i] != i:
                    i = grp[i]
                return i
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    if float((ms[i] & ms[j]).sum()) / max(1.0, min(ms[i].sum(), ms[j].sum())) >= HEAD_MERGE:
                        grp[root(j)] = root(i)
            blobs = {}
            for i, m in enumerate(ms):
                r = root(i)
                blobs[r] = (blobs[r] | m) if r in blobs else m
            _BLOBS[key(p)] = list(blobs.values())
    return {p: _BLOBS.get(key(p)) for p in paths}


def _R():
    import nk_restyle
    return nk_restyle


def _grid(p):
    try:
        from PIL import Image
        return _R().grid_score(Image.open(p))
    except Exception:
        return None


def fig_flags(blobs, allowed):
    """sam_blobs 한 장 결과 -> 몸 덩어리가 허용(사람 수 + 2x 머리 비슷한 소품)보다 많으면 ['figures: ...']"""
    if blobs is None:
        return []
    a = sorted((round(float(m.mean()), 4) for m in blobs if float(m.mean()) >= FIG_MIN), reverse=True)
    if len(a) <= allowed:
        return []
    return ["figures: %d found, %d expected (%s) - extra little figure?" % (len(a), allowed, ", ".join("%.1f%%" % (x * 100) for x in a))]


def new_figures(src, cand, min_area=0.001, max_in=0.3, grow=3):
    """src·cand = sam_blobs 결과. cand 덩어리 중 원래 그림(src) 덩어리 자리(조금 넓힘) 안에 30%도 안 들어가는 것 -> [면적]"""
    import numpy as np
    if src is None or not cand:
        return []
    U = np.zeros_like(cand[0])
    for m in src:
        U = U | m
    for _ in range(grow):                     # 몇 칸 넓힘 (살짝 움직인 캐릭터는 같은 자리로)
        V = U.copy()
        V[1:, :] |= U[:-1, :]; V[:-1, :] |= U[1:, :]; V[:, 1:] |= U[:, :-1]; V[:, :-1] |= U[:, 1:]
        U = V
    out = []
    for b in cand:
        a = float(b.mean())
        if a >= min_area and float((b & U).sum()) / max(1.0, float(b.sum())) < max_in:
            out.append(round(a, 4))
    return out


def head_allowed(conti, cut):
    words = " ".join([str(cut.get("scene", "")), " ".join(str(x) for x in (cut.get("props") or [])), str(cut.get("loc", ""))]
                     + [str(r.get("pos", "")) for r, _ in (cut.get("_roles") or [])]).lower()
    n_like = sum(words.count(w) for w in HEADLIKE)
    return len(cut.get("_roles") or []) + 2 * n_like, n_like


def head_flags(n, areas, allowed):
    if n is None or n <= allowed:
        return [], 0.0
    return ["heads: %d found, %d expected (%s)" % (n, allowed, ", ".join("%.1f%%" % (a * 100) for a in areas))], 1.0


def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _install(kit, conti, cid, src_path):
    """후보를 최종본(cuts/cutNN.png)으로. 원래 최종본은 cuts_compose/orig/에 한 번만 보관"""
    import nk_webtoon as W
    import shutil
    ep = conti["_ep"]
    d = os.path.join(W.ep_dir(kit, ep), "cuts_compose")
    f = W._final_file(kit, ep, cid)
    orig = os.path.join(d, "orig", "cut%02d.png" % cid)
    if os.path.exists(f) and not os.path.exists(orig):
        os.makedirs(os.path.dirname(orig), exist_ok=True)
        shutil.copy(f, orig)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    shutil.copy(src_path, f)
    return _md5(f)


def auto(nk, kit, conti, ids, seeds=None, dry=False, override=None):
    """두 명 컷 합치기 + 판별기로 고르기 + 최종본으로. -> {"used": {cid: seed}, "failed": {cid: 이유}, "flags": {cid: [...]}}"""
    import nk_webtoon as W
    cfg = nk.load_presets()
    seeds = seeds or [51, 52]
    jobs, info, errors = _jobs(nk, kit, cfg, conti, ids, override or {}, seeds, dry)
    out = {"used": {}, "failed": dict(errors), "flags": {}}
    if not jobs or dry:
        if dry and jobs:
            nk.run_jobs(cfg, jobs, "%s/compose" % conti["_ep"], True)
        return out
    print("compose %s: %d cuts x %d seeds (~2-4 min each)" % (conti["_ep"], len(info), len(seeds)))
    res = nk.run_jobs(cfg, jobs, "%s/compose" % conti["_ep"], False)
    made = _collect(nk, kit, cfg, conti, res, info)
    cuts = {int(c["id"]): c for c in conti["cuts"]}

    def judge_all():
        out_j = {}
        heads, figs = {}, {}
        allp = [p for cid in info if cid in made for _, p in made[cid]]
        if HEAD_CHECK:                                   # ③ 머리 수 (SAM3, 후보 전부 한 번에)
            heads = head_counts(nk, kit, cfg, conti["_ep"], allp)
        if FIG_CHECK:                                    # ④ 몸 덩어리 수
            figs = sam_blobs(nk, kit, cfg, conti["_ep"], allp, run="compose_figs")
        for cid in info:
            if cid not in made:
                continue
            judged = []
            allowed, _ = head_allowed(conti, cuts[cid])
            for sd, p in made[cid]:
                sc, fl, det = judge(kit, conti, cuts[cid], p)
                hn, ha = heads.get(p, (None, []))
                hf, hp = head_flags(hn, ha, allowed)
                fl = fl + hf; sc = round(sc - hp, 3)
                if hn is not None:
                    det["heads"] = hn
                ff = fig_flags(figs.get(p), allowed)
                if ff:
                    fl = fl + ff; sc = round(sc - 1.0, 3)
                gs = _grid(p)
                if gs is not None:
                    det["grid"] = round(gs, 1)
                    if gs >= _R().GRID_ON:
                        fl = fl + ["grid pattern over the picture (%.0f)" % gs]; sc = round(sc - 2.0, 3)
                if figs.get(p) is not None:
                    det["figures"] = len([m for m in figs[p] if float(m.mean()) >= FIG_MIN])
                info[cid].setdefault("judge", {})[str(sd)] = {"score": sc, "flags": fl, "detail": det}
                print("[judge] cut %02d seed %d: score %.2f %s" % (cid, sd, sc, "; ".join(fl) or "ok"))
                # 심한 흠(디자인 번짐·눈 색·자세)이 적은 것 > 흠 개수 > 점수
                judged.append((sum(1 for x in fl if any(s in x for s in SEVERE)), len(fl), -sc, sd, p, fl))
            judged.sort()
            out_j[cid] = judged
        return out_j

    judged_by = judge_all()
    retry = [cid for cid, j in judged_by.items() if j and j[0][0] > 0]
    if retry and EXTRA_ROUND:
        more = [s + len(seeds) for s in seeds]
        print("\ncompose: cut %s - every candidate has a serious flaw -> %d more seeds %s"
              % (", ".join(str(c) for c in retry), len(more), more))
        jobs2, _, _ = _jobs(nk, kit, cfg, conti, retry, override or {}, more, dry)
        res2 = nk.run_jobs(cfg, jobs2, "%s/compose" % conti["_ep"], False) or []
        made = _collect(nk, kit, cfg, conti, list(res) + list(res2), info)
        judged_by = judge_all()
    for cid in info:
        if cid not in made:
            out["failed"][cid] = "no picture came back"; continue
        _, _, _, sd, p, fl = judged_by[cid][0]
        info[cid]["use"] = sd
        info[cid]["final_md5"] = _install(kit, conti, cid, p)
        out["used"][cid] = sd
        if fl:
            out["flags"][cid] = fl
            info[cid]["flags"] = fl
        print("   -> cut %02d uses seed %d%s" % (cid, sd, (" (check: %s)" % "; ".join(fl)) if fl else ""))
    d = os.path.join(W.ep_dir(kit, conti["_ep"]), "cuts_compose")
    rec_p = os.path.join(d, "compose.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    rec.update({str(k): v for k, v in info.items()})
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def run_use(nk, kit, conti, choices):
    """--use 8=52 : 그 후보를 최종본으로 / 8=0 : 합치기 전 원래 최종본으로 되돌림"""
    import nk_webtoon as W
    import shutil
    d = os.path.join(W.ep_dir(kit, conti["_ep"]), "cuts_compose")
    rec_p = os.path.join(d, "compose.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    for ch in choices:
        cid, sd = [int(x) for x in ch.split("=")]
        if sd == 0:
            orig = os.path.join(d, "orig", "cut%02d.png" % cid)
            if not os.path.exists(orig):
                print("[ERROR] no original kept for cut %d" % cid); sys.exit(1)
            shutil.copy(orig, W._final_file(kit, conti["_ep"], cid))
        else:
            p = os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, sd))
            if not os.path.exists(p):
                print("[ERROR] no candidate", p); sys.exit(1)
            _install(kit, conti, cid, p)
        r = rec.get(str(cid)) or {}
        r.update(use=sd, manual=True, final_md5=_md5(W._final_file(kit, conti["_ep"], cid)))
        rec[str(cid)] = r
        print("cut %02d -> %s" % (cid, "original (before compose)" if sd == 0 else "compose seed %d" % sd))
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("then: nk ep facefix / restyle / letter %s" % conti["_ep"])


def run(nk, kit, args):
    import nk_webtoon as W
    import nk_restyle as R
    conti = W.load_conti(nk, kit, args.ep)
    if getattr(args, "use", None):
        return run_use(nk, kit, conti, args.use)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    ids = [int(x) for x in args.cuts] if args.cuts else [i for i, c in cuts.items() if c.get("_roles")]
    override = {}
    for part in (args.src or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            override[k.strip()] = int(v)
    seed = args.seed if args.seed is not None else 51
    seeds = [seed + k for k in range(max(1, int(args.tries or 2)))]
    global SUB, RUN, PROMPT_VARIANT
    if getattr(args, "prompt", None) and str(args.prompt) != DEFAULT_PROMPT:
        PROMPT_VARIANT = str(args.prompt)
        SUB, RUN = "p_" + PROMPT_VARIANT, "compose_" + PROMPT_VARIANT
        if getattr(args, "apply", False):
            print("[ERROR] --prompt %s is a comparison test only (no --apply yet)" % PROMPT_VARIANT); sys.exit(1)
    if getattr(args, "qwen", None) and str(args.qwen) != R.qwen_ver():
        ver = R.use_qwen(args.qwen)
        if getattr(args, "apply", False):
            print("[ERROR] --qwen %s is a comparison test only (no --apply yet)" % ver); sys.exit(1)
        SUB, RUN = "q" + ver, "compose" + ver
    if getattr(args, "apply", False):
        out = auto(nk, kit, conti, ids, seeds, args.dry, override)
        print("used:", out["used"], "| failed:", out["failed"], "| check:", out["flags"])
        return
    cfg = nk.load_presets()
    jobs, info, errors = _jobs(nk, kit, cfg, conti, ids, override, seeds, args.dry)
    if not jobs:
        print("[ERROR] nothing to do"); sys.exit(1)
    print("compose %s: %d cuts x %d seeds (~2-4 min each) - test only, cuts/ not changed (--apply to use the best)"
          % (args.ep, len(info), len(seeds)))
    res = nk.run_jobs(cfg, jobs, "%s/%s" % (args.ep, RUN), args.dry)
    if args.dry:
        return
    made = _collect(nk, kit, cfg, conti, res, info)
    for cid, cands in made.items():
        for sd, p in cands:
            sc, fl, det = judge(kit, conti, cuts[cid], p)
            info[cid].setdefault("judge", {})[str(sd)] = {"score": sc, "flags": fl, "detail": det}
            print("[judge] cut %02d seed %d: score %.2f %s" % (cid, sd, sc, "; ".join(fl) or "ok"))
    d = os.path.join(W.ep_dir(kit, args.ep), "cuts_compose", SUB) if SUB else os.path.join(W.ep_dir(kit, args.ep), "cuts_compose")
    rec_p = os.path.join(d, "compose.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    for v in info.values():
        v["qwen"] = R.qwen_ver()
    rec.update({str(k): v for k, v in info.items()})
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if SUB:
        print("look: %s\\cutNN_cmp.png  ('now' = current final; comparison only, nothing installed)" % d)
    else:
        print("look: %s\\cutNN_cmp.png  (choose: nk ep compose %s --use 8=52)" % (d, args.ep))
