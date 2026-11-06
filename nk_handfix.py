# -*- coding: utf-8 -*-
"""손 다시 그리기 시험

왜: 얼굴·손·귀 깨짐이 가장 치명적인데 손은 자동으로 찾는 방법 자체가 없었음.
    아카라이브 aiart 경험값: 손 주변을 넓게(crop factor 1.8, 1.4 밑이면 망가짐 - 156612388) 잘라서 denoise 0.5 이상(127711152).
    인페인트 컨트롤넷은 설치가 필요 -> 먼저 설치 없이 얼굴 고치기와 같은 방식(잘라서 마스크 안만 다시 그리기)으로 되는지 봄.
아직 시험: 최종본은 안 바꿈. 결과 = episodes/<ep>/handtest/cutNN_hands.png (손마다 한 줄: 원본 | denoise별 후보)
'이 손이 깨졌나' 판단은 아직 없음 -> 찾은 손을 전부 다시 그려 보고 눈으로 비교.

사용: nk ep handtest <ep> <컷...> [--methods sd,dd,qwen] [--den 0.55,0.7] [--seed 61] [--threshold 0.3] [--dry]"""
import os
import sys
import json

CROP = 1.8           # 손 상자 긴 변 x 1.8 = 자르는 정사각형 (채널 경험값)
MIN_CROP = 256       # 작은 손도 주변이 보이게
AREA_MIN, AREA_MAX = 0.0004, 0.06     # 그림 넓이 대비 손 마스크 (먼지·팔 전체 거르기)
OWNER_MIN = 0.3


def _body_word(ch):
    """손 주인을 가릴 SAM3 몸 말: 캐릭터 파일 hands.sam_body > anima_find > sam_body (없으면 None)"""
    ch = ch or {}
    return (ch.get("hands") or {}).get("sam_body") or ch.get("anima_find") or ch.get("sam_body") or None


def _hand_desc(ch):
    """(손 태그, 손 설명): 캐릭터 파일 hands.tags · hands.desc (없으면 일반 손)"""
    h = (ch or {}).get("hands") or {}
    return str(h.get("tags") or ""), str(h.get("desc") or "cartoon hand")


#   sd   = 지금 얼굴 고치기와 같음 (SetLatentNoiseMask)
#   dd   = ComfyUI 기본 노드 DifferentialDiffusion + InpaintModelConditioning (마스크 가장자리를 점점 약하게 다시 그림)
#   qwen = Qwen-Image-Edit 2509로 '이 손을 고쳐 그려라' (색을 바꾸는 흠에 강할 것으로 추정 - 소품 넣기에서 주변 유지가 좋았음)
METHODS = {"sd": [0.55, 0.7], "dd": [0.85, 1.0], "qwen": [1.0]}


def _graph_dd(cfg, s, char, pos, neg, img_name, mask_name, seed, den, prefix, res):
    g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}}
    model, clip = ["4", 0], ["4", 1]
    if char.get("lora"):
        st = float(char.get("lora_strength", 1.0))
        g["20"] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip, "lora_name": char["lora"],
                                                           "strength_model": st, "strength_clip": st}}
        model, clip = ["20", 0], ["20", 1]
    g["16"] = {"class_type": "DifferentialDiffusion", "inputs": {"model": model, "strength": 1.0}}
    g["1"] = {"class_type": "LoadImage", "inputs": {"image": img_name}}
    g["2"] = {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos", "width": res,
                                                      "height": res, "crop": "disabled"}}
    g["11"] = {"class_type": "LoadImage", "inputs": {"image": mask_name}}
    g["12"] = {"class_type": "ImageToMask", "inputs": {"image": ["11", 0], "channel": "red"}}
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": clip}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": clip}}
    g["15"] = {"class_type": "InpaintModelConditioning", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "vae": ["4", 2],
                                                                     "pixels": ["2", 0], "mask": ["12", 0], "noise_mask": True}}
    g["3"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                                    "sampler_name": s["sampler"], "scheduler": s["scheduler"],
                                                    "denoise": float(den), "model": ["16", 0], "positive": ["15", 0],
                                                    "negative": ["15", 1], "latent_image": ["15", 2]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g
HAND_NEG = "bad hands, mutated hands, extra fingers, fused fingers, missing fingers, extra digits, fewer digits, extra hands"


def _cast(conti, cut):
    """이 컷의 캐릭터 [(키, 캐릭터 yaml)]"""
    cast = conti.get("_cast") or {}
    if cut.get("_roles"):
        out = []
        for r, ch in cut["_roles"]:
            out.append((str(r["char"]), ch))
        return out
    k = cut.get("_charkey")
    if k and k in cast:
        return [(k, cast[k])]
    return []


def _boxes(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def run(nk, kit, args):
    import argparse
    import numpy as np
    import cv2
    from PIL import Image, ImageDraw
    import nk_webtoon as W
    import nk_sam
    import nk_facefix as F
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    meths = [m.strip() for m in (getattr(args, "methods", None) or "sd").split(",") if m.strip() in METHODS]
    variants = []
    for m in meths:
        dl = [float(x) for x in args.den.split(",")] if (args.den and m != "qwen") else METHODS[m]
        variants += [(m, dn) for dn in dl]
    seed = args.seed if args.seed is not None else 61
    d = os.path.join(W.ep_dir(kit, args.ep), "handtest")
    work = os.path.join(d, "_work")
    os.makedirs(work, exist_ok=True)

    # 1) SAM3: 손(여러 개) + 캐릭터 몸
    items, plan = [], {}
    for cid in [int(x) for x in args.cuts]:
        cut = cuts.get(cid)
        f = W._final_file(kit, args.ep, cid)
        if not cut or not os.path.exists(f):
            print("[skip] cut %d: no final picture" % cid); continue
        cast = _cast(conti, cut)
        if not cast:
            print("[skip] cut %d: no character" % cid); continue
        nm = "cut%02d" % cid
        plan[cid] = {"cut": cut, "f": f, "cast": cast, "nm": nm}
        items.append((nm, f, "hand:6"))
        for k, ch in cast:
            body = _body_word(ch)
            if body:
                items.append((nm, f, body))
    if not plan:
        print("[ERROR] nothing to do"); sys.exit(1)
    got = nk_sam.segment(nk, kit, cfg, args.ep, items, args.threshold, run="handtest_sam", dry=args.dry, individual=True)
    if args.dry:
        print("(dry) SAM3 jobs only"); return

    # 2) 손마다 주인·자르기·마스크
    jobs, hands = [], []
    for cid, p in plan.items():
        im = Image.open(p["f"]).convert("RGB")
        Wd, Hd = im.size
        bodies = {}
        for k, ch in p["cast"]:
            body = _body_word(ch)
            if body and got.get((p["nm"], body)):
                bm = np.zeros((Hd, Wd), bool)
                for mp in got[(p["nm"], body)]:
                    bm |= np.asarray(Image.open(mp).convert("L").resize((Wd, Hd))) > 127
                k_ = max(3, int(0.03 * max(Wd, Hd)))
                bodies[k] = cv2.dilate(bm.astype(np.uint8), np.ones((k_, k_), np.uint8)) > 0
        masks = []
        for mp in got.get((p["nm"], "hand:6")) or []:
            m = np.asarray(Image.open(mp).convert("L").resize((Wd, Hd))) > 127
            a = m.mean()
            if a < AREA_MIN or a > AREA_MAX:
                continue
            masks.append(m)
        for j, m in enumerate(masks):
            owner = None
            for k, bm in bodies.items():
                if (m & bm).sum() / float(m.sum()) >= OWNER_MIN:
                    owner = k
            others = [k for k, _ in p["cast"] if k not in bodies]
            if owner is None and len(p["cast"]) == 1:
                k0 = p["cast"][0][0]
                bm = bodies.get(k0)
                if bm is None or (m & bm).sum() / float(m.sum()) >= 0.05:
                    owner = k0
            if owner is None:
                if len(others) == 1:
                    owner = others[0]
                else:
                    print("cut %d hand %d: not on a known character (snowman? background?) - skipped" % (cid, j)); continue
            ch = dict(p["cast"])[owner]
            x0, y0, x1, y1 = _boxes(m)
            L = int(min(max(max(x1 - x0, y1 - y0) * CROP, MIN_CROP), Wd, Hd))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            cx0 = int(min(max(0, cx - L / 2), Wd - L))
            cy0 = int(min(max(0, cy - L / 2), Hd - L))
            crop_m = m[cy0:cy0 + L, cx0:cx0 + L].astype(np.uint8)
            k_ = max(3, int(0.06 * L))
            mm = cv2.dilate(crop_m, np.ones((k_, k_), np.uint8)).astype(np.float32)
            mm = cv2.GaussianBlur(mm, (0, 0), max(2.0, 0.02 * L))
            mask = (np.clip(mm, 0, 1) * 255).astype(np.uint8)
            label0 = "cut%02d_h%d" % (cid, j)
            cp = os.path.join(work, label0 + "_crop.png")
            mpth = os.path.join(work, label0 + "_mask.png")
            im.crop((cx0, cy0, cx0 + L, cy0 + L)).resize((F.RES, F.RES), Image.LANCZOS).save(cp)
            Image.fromarray(mask).resize((F.RES, F.RES), Image.BILINEAR).convert("RGB").save(mpth)
            img = W._upload_input(nk, cfg, cp, "%s_%s_htcrop.png" % (args.ep, label0), False)
            msk = W._upload_input(nk, cfg, mpth, "%s_%s_htmask.png" % (args.ep, label0), False)
            cut = p["cut"]
            ns = argparse.Namespace(preset=cut.get("artist", conti.get("artist")), extra=None, neg=None, lora=None,
                                    size=W._gen_size(cut["size"]), rating=None, cfg=cut.get("cfg"), steps=None, sampler=None,
                                    scheduler=None, quality=None, year=None, artist=None, artist_weight=None,
                                    artist_position=None, tags=None, strength=None, charlora=None, hires=0, hires_denoise=None,
                                    hires_steps=None, hires_method=None, upscale_model=None)
            s = nk.build_settings(cfg, ns)
            hd = _hand_desc(ch)
            pos, neg = nk.compose_prompt(s, ch, "hand focus, close-up, detailed hands" + (", " + hd[0] if hd[0] else ""))
            neg = nk.clean_tags(neg + ", " + HAND_NEG)
            qtext = ("Fix the hand in the middle of this picture: redraw it as a clean, well-drawn %s with a natural shape and "
                     "the right number of fingers. Keep everything else exactly the same: the pose, the arm, the sleeve, the "
                     "colors, the background and the art style." % hd[1])
            h = {"cid": cid, "j": j, "owner": owner, "box": [int(x0), int(y0), int(x1), int(y1)], "crop": [cx0, cy0, L],
                 "mask": mask, "src": p["f"], "cands": {}}
            hands.append(h)
            for m_, dn in variants:
                label = "%s_%s%02d" % (label0, m_, int(round(dn * 100)))
                prefix = "nk/%s_handtest/%s" % (args.ep, label)
                if m_ == "sd":
                    g = F._graph(cfg, s, ch, pos, neg, img, msk, seed, dn, prefix)
                elif m_ == "dd":
                    g = _graph_dd(cfg, s, ch, pos, neg, img, msk, seed, dn, prefix, F.RES)
                else:
                    import nk_restyle as R
                    g = R.graph(img, qtext, seed, prefix, F.RES, F.RES, 1.0)
                jobs.append({"label": label, "graph": g, "positive": qtext if m_ == "qwen" else pos, "negative": neg,
                             "seed": seed, "settings": {"cfg": s["cfg"], "steps": s["steps"], "width": F.RES, "height": F.RES}})
            print("cut %d hand %d (%s): box %s, crop %d px" % (cid, j, owner, h["box"], L))
    if not jobs:
        print("[ERROR] no hands found"); sys.exit(1)
    print("handtest %s: %d hands x %d variants %s (~30 s each, qwen ~90 s)" % (args.ep, len(hands), len(variants), variants))
    jobs.sort(key=lambda j: "_qwen" in j["label"])       # 모델 바꿔 끼우기 줄이기: SDXL 먼저 다 하고 Qwen
    res = nk.run_jobs(cfg, jobs, "%s/handtest" % args.ep, False)

    # 3) 붙여서 비교 그림 (최종본은 안 바꿈)
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "handtest")
    byl = {r["label"]: os.path.join(out_dir, r["file"]) for r in res}
    rec = []
    for cid in sorted(set(h["cid"] for h in hands)):
        rows = []
        for h in [x for x in hands if x["cid"] == cid]:
            cx0, cy0, L = h["crop"]
            base = Image.open(h["src"]).convert("RGB")
            orig = base.crop((cx0, cy0, cx0 + L, cy0 + L))
            tiles = [("hand %d (%s) before" % (h["j"], h["owner"]), orig)]
            for m_, dn in variants:
                lp = byl.get("cut%02d_h%d_%s%02d" % (cid, h["j"], m_, int(round(dn * 100))))
                if not lp:
                    continue
                new = Image.open(lp).convert("RGB").resize((L, L), Image.LANCZOS)
                t = orig.copy()
                t.paste(new, (0, 0), Image.fromarray(h["mask"]))
                tiles.append(("%s %.2f" % (m_, dn) if m_ != "qwen" else "qwen edit", t))
            # 마스크 테두리 표시 (어디를 다시 그렸나)
            ol = orig.copy()
            edge = cv2.Canny((h["mask"] > 60).astype(np.uint8) * 255, 50, 150)
            arr = np.asarray(ol).copy()
            arr[edge > 0] = (255, 0, 255)
            tiles.insert(1, ("mask", Image.fromarray(arr)))
            rows.append(tiles)
            rec.append({k: v for k, v in h.items() if k not in ("mask", "src", "cands")})
        S = 320
        sheet = Image.new("RGB", (max(len(r) for r in rows) * (S + 8), len(rows) * (S + 22)), "white")
        dr = ImageDraw.Draw(sheet)
        for ri, r in enumerate(rows):
            for ti, (lb, t) in enumerate(r):
                x, y = ti * (S + 8), ri * (S + 22)
                sheet.paste(t.resize((S, S), Image.LANCZOS), (x, y + 20)); dr.text((x + 3, y + 4), lb, fill="black")
        sp = os.path.join(d, "cut%02d_hands.png" % cid)
        sheet.save(sp)
        print("sheet:", sp)
    json.dump(rec, open(os.path.join(d, "handtest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("look: %s\\cutNN_hands.png (nothing installed)" % d)


# 멀쩡한 손(22개)은 두 방법 다 모양·자세를 바꿔 버리는 일이 많음 -> '색이 캐릭터와 안 맞는 손'만 고침
# 색 검사 (손 24개로 잰 값, 캐릭터 파일 hands.expect):
FIX_METHODS = [("dd", 1.0), ("qwen", 1.0)]      # 흠 종류마다 고친 방법이 달랐음 -> 둘 다 만들고 색 검사로 고름
TEXT_MAX = 0.35


def hand_colors(rgb, mask):
    """rgb: HxWx3 uint8, mask: HxW bool -> {L, dark, bright, skin, pink}"""
    import numpy as np
    from PIL import Image
    if mask.sum() == 0:
        return None
    im = Image.fromarray(rgb)
    L = np.asarray(im.convert("L")).astype(float)[mask]
    hsv = np.asarray(im.convert("HSV")).astype(float)
    h = hsv[..., 0][mask] * 360 / 255
    s = hsv[..., 1][mask] / 255
    v = hsv[..., 2][mask] / 255
    return {"L": round(float(L.mean()), 1), "dark": round(float((L < 70).mean()), 3), "bright": round(float((L > 190).mean()), 3),
            "skin": round(float(((h >= 8) & (h <= 35) & (s > 0.18) & (s < 0.65) & (v > 0.45)).mean()), 3),
            "pink": round(float((((h >= 330) | (h < 8)) & (s > 0.25) & (v > 0.5)).mean()), 3),
            "v_med": round(float(np.median(v)), 2)}


def color_flaw(expect, c):
    if not c:
        return None
    if expect == "dark":
        if c["dark"] < 0.25 and (c["pink"] > 0.6 or c["skin"] > 0.4):
            hint = " - bright pink like the chest marking, probably NOT a hand" if c.get("v_med", 0) >= 0.9 else ""
            return "hand is not dark (pink %.2f, skin %.2f)%s" % (c["pink"], c["skin"], hint)
    elif expect == "bright":
        if c["dark"] > 0.6:
            return "hand is dark (%.2f) on a white character" % c["dark"]
    return None


def color_normal(expect, c):
    """    모의 시험: dd 후보 = 분홍 덩어리인데 어두움 0.45로 흠 규칙은 통과 -> 이 규칙으로 떨어뜨리고 qwen(어두움 0.86)을 고름"""
    if not c:
        return False
    if expect == "dark":
        return c["dark"] >= 0.5 and c["pink"] <= 0.45 and c["skin"] <= 0.2
    if expect == "bright":
        return c["bright"] >= 0.6 and c["dark"] <= 0.2
    return True


def _hands_cfg(ch):
    hc = dict(ch.get("hands") or {})
    tags, desc = _hand_desc(ch)
    hc.setdefault("tags", tags)
    hc.setdefault("desc", desc)
    hc.setdefault("expect", "")
    hc.setdefault("sam_body", _body_word(ch) or "")
    return hc


def run_fix(nk, kit, args):
    """nk ep handfix <ep> [컷...] [--apply]: 색이 캐릭터와 안 맞는 손만 dd·qwen으로 다시 그리고 색 검사로 고름"""
    import argparse
    import numpy as np
    import cv2
    from PIL import Image, ImageDraw
    import nk_webtoon as W
    import nk_sam
    import nk_facefix as F
    import nk_restyle as R
    import shutil
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    ids = [int(x) for x in args.cuts] if args.cuts else sorted(cuts)
    seed = args.seed if args.seed is not None else 61
    d = os.path.join(W.ep_dir(kit, args.ep), "cuts_handfix")
    work = os.path.join(d, "_work")
    for sub in ("_work", "cand", "orig"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    rec_p = os.path.join(d, "handfix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}

    # 1) SAM3
    items, plan = [], {}
    for cid in ids:
        cut = cuts.get(cid)
        f = W._final_file(kit, args.ep, cid)
        if not cut or not os.path.exists(f):
            continue
        cast = _cast(conti, cut)
        if not cast:
            continue
        pr = rec.get(str(cid)) or {}
        if not args.cuts and pr.get("final_md5") and pr["final_md5"] == F._md5(f):
            print("[skip] cut %d: unchanged since the last handfix" % cid); continue
        nm = "cut%02d" % cid
        plan[cid] = {"cut": cut, "f": f, "cast": cast, "nm": nm}
        items.append((nm, f, "hand:6"))
        for k, ch in cast:
            b = _hands_cfg(ch)["sam_body"]
            if b and (nm, f, b) not in items:
                items.append((nm, f, b))
    if not plan:
        print("nothing to check"); return {"fixed": {}, "flags": {}}
    got = nk_sam.segment(nk, kit, cfg, args.ep, items, args.threshold, run="handfix_sam", dry=args.dry, individual=True)
    if args.dry:
        print("(dry) SAM3 jobs only"); return {"fixed": {}, "flags": {}}

    # 2) 손마다 주인 + 색 검사 -> 흠 있는 손만 후보 작업
    jobs, bad = [], []
    for cid, p in plan.items():
        im = Image.open(p["f"]).convert("RGB")
        rgb = np.asarray(im)
        Wd, Hd = im.size
        bodies = {}
        for k, ch in p["cast"]:
            b = _hands_cfg(ch)["sam_body"]
            if b and got.get((p["nm"], b)):
                bm = np.zeros((Hd, Wd), bool)
                for mp in got[(p["nm"], b)]:
                    bm |= np.asarray(Image.open(mp).convert("L").resize((Wd, Hd))) > 127
                k_ = max(3, int(0.03 * max(Wd, Hd)))
                bodies[k] = cv2.dilate(bm.astype(np.uint8), np.ones((k_, k_), np.uint8)) > 0
        crec = {"hands": [], "final_md5": F._md5(p["f"])}
        j = -1
        for mp in got.get((p["nm"], "hand:6")) or []:
            m = np.asarray(Image.open(mp).convert("L").resize((Wd, Hd))) > 127
            if not (AREA_MIN <= m.mean() <= AREA_MAX):
                continue
            j += 1
            owner = None
            for k, bm in bodies.items():
                if (m & bm).sum() / float(m.sum()) >= OWNER_MIN:
                    owner = k
            others = [k for k, _ in p["cast"] if k not in bodies]
            if owner is None and len(p["cast"]) == 1:
                k0 = p["cast"][0][0]
                bm = bodies.get(k0)
                if bm is None or (m & bm).sum() / float(m.sum()) >= 0.05:
                    owner = k0
            if owner is None and len(others) == 1:
                owner = others[0]
            if owner is None:
                crec["hands"].append({"j": j, "owner": None}); continue
            ch = dict(p["cast"])[owner]
            hc = _hands_cfg(ch)
            c0 = hand_colors(rgb, m)
            why = color_flaw(hc["expect"], c0)
            x0, y0, x1, y1 = _boxes(m)
            hr = {"j": j, "owner": owner, "box": [int(x0), int(y0), int(x1), int(y1)], "colors": c0, "flaw": why}
            crec["hands"].append(hr)
            print("cut %d hand %d (%s): %s %s" % (cid, j, owner, "FLAW - " + why if why else "ok", c0))
            if not why:
                continue
            L = int(min(max(max(x1 - x0, y1 - y0) * CROP, MIN_CROP), Wd, Hd))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            cx0 = int(min(max(0, cx - L / 2), Wd - L))
            cy0 = int(min(max(0, cy - L / 2), Hd - L))
            k_ = max(3, int(0.06 * L))
            mm = cv2.dilate(m[cy0:cy0 + L, cx0:cx0 + L].astype(np.uint8), np.ones((k_, k_), np.uint8)).astype(np.float32)
            mm = cv2.GaussianBlur(mm, (0, 0), max(2.0, 0.02 * L))
            pmask = (np.clip(mm, 0, 1) * 255).astype(np.uint8)
            label0 = "cut%02d_h%d" % (cid, j)
            cp = os.path.join(work, label0 + "_crop.png")
            mpth = os.path.join(work, label0 + "_mask.png")
            im.crop((cx0, cy0, cx0 + L, cy0 + L)).resize((F.RES, F.RES), Image.LANCZOS).save(cp)
            Image.fromarray(pmask).resize((F.RES, F.RES), Image.BILINEAR).convert("RGB").save(mpth)
            img = W._upload_input(nk, cfg, cp, "%s_%s_hfcrop.png" % (args.ep, label0), False)
            msk = W._upload_input(nk, cfg, mpth, "%s_%s_hfmask.png" % (args.ep, label0), False)
            cut = p["cut"]
            ns = argparse.Namespace(preset=cut.get("artist", conti.get("artist")), extra=None, neg=None, lora=None,
                                    size=W._gen_size(cut["size"]), rating=None, cfg=cut.get("cfg"), steps=None, sampler=None,
                                    scheduler=None, quality=None, year=None, artist=None, artist_weight=None,
                                    artist_position=None, tags=None, strength=None, charlora=None, hires=0, hires_denoise=None,
                                    hires_steps=None, hires_method=None, upscale_model=None)
            s = nk.build_settings(cfg, ns)
            pos, neg = nk.compose_prompt(s, ch, "hand focus, close-up, detailed hands" + (", " + hc["tags"] if hc["tags"] else ""))
            neg = nk.clean_tags(neg + ", " + HAND_NEG + ", text, letters")
            qtext = ("Fix the hand in the middle of this picture: redraw it as a clean, well-drawn %s with a natural shape and "
                     "the right number of fingers. Keep everything else exactly the same: the pose, the arm, the sleeve, the "
                     "colors, the background and the art style. Do not add any text." % hc["desc"])
            bad.append({"cid": cid, "j": j, "owner": owner, "expect": hc["expect"], "m": m, "crop": [cx0, cy0, L],
                        "pmask": pmask, "f": p["f"], "rec": hr})
            for m_, dn in FIX_METHODS:
                label = "%s_%s" % (label0, m_)
                prefix = "nk/%s_handfix/%s" % (args.ep, label)
                g = _graph_dd(cfg, s, ch, pos, neg, img, msk, seed, dn, prefix, F.RES) if m_ == "dd" \
                    else R.graph(img, qtext, seed, prefix, F.RES, F.RES, 1.0)
                jobs.append({"label": label, "graph": g, "positive": qtext if m_ == "qwen" else pos, "negative": neg,
                             "seed": seed, "settings": {"cfg": s["cfg"], "steps": s["steps"], "width": F.RES, "height": F.RES}})
        rec[str(cid)] = crec
    out = {"fixed": {}, "flags": {}}
    if not jobs:
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        print("no hand with a wrong color - nothing to fix"); return out
    jobs.sort(key=lambda jb: "_qwen" in jb["label"])
    print("handfix %s: %d hands x %d methods (~30 s dd, ~90 s qwen)" % (args.ep, len(bad), len(FIX_METHODS)))
    res = nk.run_jobs(cfg, jobs, "%s/handfix" % args.ep, False)
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "handfix")
    byl = {r["label"]: os.path.join(out_dir, r["file"]) for r in res}

    import nk_tagger
    tag_ok = nk_tagger.available(kit)[0]
    newimg = {}
    for b in bad:
        cx0, cy0, L = b["crop"]
        base = newimg.get(b["cid"]) or Image.open(b["f"]).convert("RGB")
        orig_crop = base.crop((cx0, cy0, cx0 + L, cy0 + L))
        tiles = [("before", orig_crop)]
        pick = None
        b["rec"]["cands"] = {}
        for m_, _ in FIX_METHODS:
            lp = byl.get("cut%02d_h%d_%s" % (b["cid"], b["j"], m_))
            if not lp:
                continue
            new = Image.open(lp).convert("RGB").resize((L, L), Image.LANCZOS)
            t = orig_crop.copy()
            t.paste(new, (0, 0), Image.fromarray(b["pmask"]))
            cm = b["m"][cy0:cy0 + L, cx0:cx0 + L]
            c1 = hand_colors(np.asarray(t), cm)
            why = color_flaw(b["expect"], c1) or (None if color_normal(b["expect"], c1) else "color still not a normal hand")
            txt = 0.0
            if tag_ok:
                tp = os.path.join(work, "cut%02d_h%d_%s_t.png" % (b["cid"], b["j"], m_))
                t.save(tp)
                tg = nk_tagger.tags(kit, tp) or {}
                txt = max(float(tg.get(k, 0.0)) for k in ("text", "english_text", "signature", "watermark", "speech_bubble"))
            ok = (why is None) and txt < TEXT_MAX
            b["rec"]["cands"][m_] = {"colors": c1, "flaw": why, "text": round(txt, 2), "ok": ok}
            print("   cut %d hand %d %s: %s colors %s text %.2f" % (b["cid"], b["j"], m_, "OK" if ok else "no", c1, txt))
            tiles.append(("%s %s" % (m_, "OK" if ok else "x"), t))
            if ok and pick is None:
                pick = (m_, t)
        if pick:
            base.paste(pick[1], (cx0, cy0))
            newimg[b["cid"]] = base
            b["rec"]["use"] = pick[0]
            out["fixed"].setdefault(b["cid"], []).append("hand %d (%s) %s" % (b["j"], b["owner"], pick[0]))
        else:
            out["flags"].setdefault(b["cid"], []).append("hand %d (%s): %s - no candidate fixed it" % (b["j"], b["owner"], b["rec"]["flaw"]))
        S = 320
        sheet = Image.new("RGB", (len(tiles) * (S + 8), S + 22), "white")
        dr = ImageDraw.Draw(sheet)
        for ti, (lb, t) in enumerate(tiles):
            sheet.paste(t.resize((S, S), Image.LANCZOS), (ti * (S + 8), 22)); dr.text((ti * (S + 8) + 3, 5), lb, fill="black")
        sheet.save(os.path.join(d, "cand", "cut%02d_h%d.png" % (b["cid"], b["j"])))
    for cid, im2 in newimg.items():
        cpath = os.path.join(d, "cand", "cut%02d.png" % cid)
        im2.save(cpath)
        f = W._final_file(kit, args.ep, cid)
        if getattr(args, "apply", False):
            o = os.path.join(d, "orig", "cut%02d.png" % cid)
            if not os.path.exists(o):
                shutil.copy(f, o)
            shutil.copy(cpath, f)
            rec[str(cid)]["final_md5"] = F._md5(f)
            rec[str(cid)]["applied"] = True
            print("cut %02d: final <- hands fixed (%s). original kept in %s" % (cid, "; ".join(out["fixed"][cid]), o))
        else:
            print("cut %02d: fixed picture in %s (not installed - add --apply)" % (cid, cpath))
    for b in bad:
        b["rec"].pop("m", None)
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("look: %s\\cand\\cutNN_hN.png (before | dd | qwen)" % d)
    return out
