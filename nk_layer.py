# -*- coding: utf-8 -*-
"""누끼 레이어 두 명 컷

nk ep auto <편> --duo layer   두 명 컷을 이 방식으로
nk ep layer <편> [컷...]      두 명 컷만 이 방식으로 (다시) 그림
nk ep layer <편> --use 5=A_SF 합치기 후보 바꾸기 (5=0 = 누끼 레이어 전 최종본으로)

_S 점 지우기, _F 얼굴 지키기, _SF 둘 다 (composite)
결과: episodes/<편>/cuts_layer/cutNN/ (층 L1·plate·R·틀, comp/ 후보 8장, sheet.png), cuts_layer/layer.json,
      최종본 cuts/cutNN.png (그 전 최종본은 cuts_layer/orig/cutNN.png)"""
import os, sys, json, time, glob
import numpy as np

LAYER_FRONT = "B"
LAYER_FIX = "SF"
LAYER_K = 3                # ① 후보 수 (duo1: 꼬리가 상대 자리를 덮는 비율 0.28->0.12 등)
VARIANTS = ["A", "B", "A_S", "B_S", "A_F", "B_F", "A_SF", "B_SF"]
NEED = ["L1", "R", "A", "B", "m1", "mR", "h1", "hR", "n1", "nR"]


# ------------------------------------------------------------------ 합치기 (GPU 없음)
def load(p, gray=False):
    from PIL import Image
    return np.asarray(Image.open(p).convert("L" if gray else "RGB"), np.float32) / 255.0


def grow(m, n):
    """ComfyUI GrowMask(tapered_corners=True): 십자 모양 칸으로 n번 넓힘 (음수 = 줄임)"""
    from scipy import ndimage
    fp = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    for _ in range(abs(int(n))):
        m = ndimage.grey_dilation(m, footprint=fp) if n > 0 else ndimage.grey_erosion(m, footprint=fp)
    return m


def blur(m, radius, sigma):
    """ComfyUI ImageBlur: 칸 크기 2r+1, 칸 좌표를 -1~1로 둔 가우스, 가장자리 reflect"""
    if radius <= 0:
        return m
    from scipy import ndimage
    ax = np.linspace(-1, 1, 2 * radius + 1)
    xx, yy = np.meshgrid(ax, ax, indexing="ij")
    g = np.exp(-(xx * xx + yy * yy) / (2.0 * sigma * sigma))
    return ndimage.convolve(m, g / g.sum(), mode="reflect")


def feather(m, g=3, b=2):
    """nk_regional._mask_feather(g, b) 와 같은 계산: 넓힘 g -> 흐림 반지름 max(1,b), 시그마 max(0.5, b/2)"""
    return np.clip(blur(grow(m, g), max(1, int(b)), max(0.5, b / 2.0)), 0, 1)


def keep_big(m, keep):
    """조각 나눔(8방향) -> 가장 큰 조각의 keep 배 이상인 조각만 남김. (남긴 틀, 버린 조각 수, 버린 넓이 비율)"""
    from scipy import ndimage
    b = m > 0.5
    lab, n = ndimage.label(b, structure=np.ones((3, 3), bool))
    if n <= 1:
        return m, 0, 0.0
    areas = ndimage.sum(b, lab, index=np.arange(1, n + 1))
    ok = np.zeros(n + 1, bool)
    ok[1:] = areas >= keep * areas.max()
    return np.where(ok[lab], m, 0.0).astype(np.float32), int((~ok[1:]).sum()), float(areas[~ok[1:]].sum() / max(1.0, b.sum()))


def comp(top, bottom, mask):
    """ComfyUI ImageCompositeMasked: 틀*위 + (1-틀)*아래"""
    return mask[..., None] * top + (1.0 - mask[..., None]) * bottom


def save(a, p):
    from PIL import Image
    Image.fromarray(np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)).save(p)


def diff_frac(a, b, th=16 / 255.0):
    return float((np.abs(a - b).max(2) > th).mean())


def composite(d, grow_n=3, keep=0.05, sheet=True, front3d=None):
    """층 폴더 d (L1 R A B m1 mR h1 hR n1 nR .png) -> d/comp/ 후보 8장 + (sheet) d/sheet.png. 돌려줌: 기록 dict (없으면 None)"""
    miss = [x for x in NEED if not os.path.exists(os.path.join(d, x + ".png"))]
    if miss:
        print("[layer] %s: missing layers %s" % (d, miss))
        return None
    L1, R, A, B = (load(os.path.join(d, x + ".png")) for x in ("L1", "R", "A", "B"))
    m1, mR, h1, hR, n1, nR = (load(os.path.join(d, x + ".png"), True) for x in ("m1", "mR", "h1", "hR", "n1", "nR"))
    rep = {}
    # 이 계산이 ComfyUI 와 같게 합치나: 저장된 틀(n1·nR)로 다시 합친 것 vs 그때 결과, 내 넓힘·흐림 vs 저장된 틀
    rep["check"] = {"A0_vs_A": round(diff_frac(comp(L1, R, n1), A), 5), "B0_vs_B": round(diff_frac(comp(R, A, nR), B), 5),
                    "my_feather_vs_n1": round(float(np.abs(feather(m1, 3, 2) - n1).mean()), 5),
                    "my_feather_vs_nR": round(float(np.abs(feather(mR, 3, 2) - nR).mean()), 5)}
    m1s, k1, a1 = keep_big(m1, keep)
    mRs, kR, aR = keep_big(mR, keep)
    rep["specks_removed"] = {"lora": [k1, round(a1, 4)], "partner": [kR, round(aR, 4)]}
    A_S = comp(L1, R, feather(m1s, grow_n, 2))
    B_S = comp(R, A_S, feather(mRs, grow_n, 2))
    hb1 = feather(np.minimum(h1, grow((m1 > 0.5).astype(np.float32), 24)), grow_n, 2)
    hbR = feather(np.minimum(hR, grow((mR > 0.5).astype(np.float32), 24)), grow_n, 2)
    rep["head_area"] = {"lora": round(float((hb1 > 0.5).mean()), 4), "partner": round(float((hbR > 0.5).mean()), 4)}

    def faces(x, front):
        for src, hm in ([(R, hbR), (L1, hb1)] if front == "lora" else [(L1, hb1), (R, hbR)]):
            x = comp(src, x, hm)
        return x
    out = {"A": A, "B": B, "A_S": A_S, "B_S": B_S, "A_F": faces(A, "lora"), "B_F": faces(B, "partner"),
           "A_SF": faces(A_S, "lora"), "B_SF": faces(B_S, "partner")}
    names = list(VARIANTS)
    if front3d:
        from PIL import Image
        a3 = np.asarray(Image.open(front3d[0]).convert("L").resize((L1.shape[1], L1.shape[0]), Image.NEAREST), np.float32) / 255.0
        zf = feather(np.minimum(m1s, grow((a3 > 0.5).astype(np.float32), 8)), grow_n, 2)
        out["Z"] = faces(comp(L1, B_S, zf), "partner")
        rep["front3d_area"] = round(float((zf > 0.5).mean()), 4)
        names.append("Z")
    cd = os.path.join(d, "comp")
    os.makedirs(cd, exist_ok=True)
    rep["changed_vs_base"] = {}
    for k in names:
        save(out[k], os.path.join(cd, k + ".png"))
        rep["changed_vs_base"][k] = round(diff_frac(out[k], A if k.startswith("A") else B), 5)
    if sheet:
        _sheet(d, out, rep)
    return rep


def _sheet(d, out, rep, H=360):
    from PIL import Image, ImageDraw
    names = {"A": "LoRA 캐릭터 앞", "A_S": "점 지우기", "A_F": "얼굴 지키기", "A_SF": "둘 다",
             "B": "상대 앞", "B_S": "점 지우기", "B_F": "얼굴 지키기", "B_SF": "둘 다"}
    h0, w0 = out["A"].shape[:2]
    w = int(w0 * H / h0)
    sh = Image.new("RGB", (4 * w + 24, 2 * (H + 26)), "white")
    dr = ImageDraw.Draw(sh)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 16)
    except Exception:
        font = None
    for r, row in enumerate((["A", "A_S", "A_F", "A_SF"], ["B", "B_S", "B_F", "B_SF"])):
        for c, k in enumerate(row):
            im = Image.fromarray(np.clip(out[k] * 255 + 0.5, 0, 255).astype(np.uint8)).resize((w, H), Image.LANCZOS)
            x, y = c * (w + 8), r * (H + 26)
            sh.paste(im, (x, y + 24))
            ch = "" if k in ("A", "B") else " (바뀐 곳 %.1f%%)" % (100 * rep["changed_vs_base"][k])
            dr.text((x + 2, y + 2), names[k] + ch, fill="black", font=font)
    sh.save(os.path.join(d, "sheet.png"))


# ------------------------------------------------------------------ 그리기 (GPU)
def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _gray(f):
    from PIL import Image
    a = np.asarray(Image.open(f).convert("RGB"))
    return bool((a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all())


def draw(nk, kit, conti, ids, seed=71, K=LAYER_K, pick=None, dry=False, pose3d=None):
    """두 명 컷 ids 를 누끼 레이어로 -> {"used": {cid: 후보}, "flags": {cid: [...]}, "failed": {cid: 이유}}"""
    import shutil
    import nk_webtoon as W
    import nk_regional as R
    cfg = nk.load_presets()
    ep = conti["_ep"]
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    dflt = cfg.get("defaults") or {}
    hires = {"scale": float(dflt.get("final_hires", 1.5)), "denoise": float(dflt.get("hires_denoise", 0.35)),
             "steps": int(dflt.get("hires_steps", 20))}
    d = conti.get("duo") or {}
    pst, pen = float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5))
    pick = pick or (LAYER_FRONT + ("_" + LAYER_FIX if LAYER_FIX else ""))
    root = os.path.join(W.ep_dir(kit, ep), "cuts_layer")
    rec_p = os.path.join(root, "layer.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    run_root = "%s/layer" % ep
    run_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), run_root)
    out = {"used": {}, "flags": {}, "failed": {}}
    c = None if dry else nk.Comfy(cfg.get("server", "auto"))
    print("layer %s: cuts %s, seed %d, stage-1 candidates %d, pick %s (A LoRA character front / B partner front)" % (ep, ids, seed, K, pick))
    for cid in ids:
        cut = cuts.get(cid)
        if not cut or not cut.get("_roles"):
            out["failed"][cid] = "not a two-character cut"; continue
        if not os.path.exists(W._pose_file(kit, ep, cid)):
            out["failed"][cid] = "no pose (layout step makes episodes/%s/poses/cut%02d.png)" % (ep, cid); continue
        try:
            s = R._settings(nk, W, cfg, conti, cut)
            bp, bn, regions = W._duo_parts(nk, cfg, conti, cut, s)
            fi = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
            back = [r for i, r in enumerate(regions) if i != fi][0]
            cd = os.path.join(root, "cut%02d" % cid)
            os.makedirs(cd, exist_ok=True)
            p3 = os.path.join(pose3d, "cut%02d" % cid) if pose3d else None
            partner_up, front3d = None, None
            if p3 and os.path.isdir(p3):
                me, other = ("a", "b") if fi == 0 else ("b", "a")
                sf, sb = os.path.join(p3, "openpose_%s.png" % me), os.path.join(p3, "openpose_%s.png" % other)
                import cv2
                Wf = int(round(int(s["width"]) * hires["scale"] / 8)) * 8
                Hf = int(round(int(s["height"]) * hires["scale"] / 8)) * 8
                pm = cv2.imread(os.path.join(p3, "mask_%s.png" % other), cv2.IMREAD_GRAYSCALE)
                pm = cv2.resize(pm, (Wf, Hf), interpolation=cv2.INTER_NEAREST)
                pm = cv2.dilate(pm, np.ones((33, 33), np.uint8))              # 그림 몸이 인형보다 조금 클 수 있어 +16px
                cv2.imwrite(os.path.join(cd, "partner3d.png"), cv2.merge([pm] * 3))
                partner_up = W._upload_input(nk, cfg, os.path.join(cd, "partner3d.png"), "%s_cut%02d_partner3d.png" % (ep, cid), dry)
                front3d = (os.path.join(p3, "mask_%s.png" % me), os.path.join(p3, "mask_%s.png" % other))
                print("cut %d: 3D doll from %s (partner region = 3D mask +16px, solo poses = openpose_%s/%s)" % (cid, p3, me, other))
            else:
                sf = R._solo_pose(W, kit, ep, cid, regions[fi]["span"], cd)
                sb = R._solo_pose(W, kit, ep, cid, back["span"], os.path.join(cd, "back"))
            if not sf or not sb:
                out["failed"][cid] = "no keypoints json next to the pose (nk ep pose makes it)"; continue
            pose_up = W._pose_upload(nk, cfg, kit, ep, cid, dry)
            sf_up = W._upload_input(nk, cfg, sf, "%s_cut%02d_layer_front.png" % (ep, cid), dry)
            sb_up = W._upload_input(nk, cfg, sb, "%s_cut%02d_layer_back.png" % (ep, cid), dry)
            jobs = []
            for k in range(K):
                label = "cut%02d_s%d_c%d" % (cid, seed, k)
                g = R._lf_graph(W, cfg, s, bp, bn, regions, seed + 1000 * k, "nk/%s_layer/%s" % (ep, label), 1.0, hires,
                                stage1_only=True)
                W._pose_cn(g, s, pose_up, pst, pen)
                g["705"] = {"class_type": "LoadImage", "inputs": {"image": sf_up}}
                g["706"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["705", 0]))
                for n2 in g.values():
                    if n2["class_type"] == "ControlNetApplyAdvanced":
                        n2["inputs"]["image"] = ["706", 0]
                jobs.append({"label": label, "graph": g, "positive": bp, "negative": bn, "settings": s, "seed": seed + 1000 * k})
            res = nk.run_jobs(cfg, jobs, run_root, dry) or []
            if dry:
                g2 = R._lc_layers_graph(W, cfg, s, bp, bn, regions, seed, "nk/%s_layer/cut%02d" % (ep, cid), hires, "dry.png", sb_up, pst, pen,
                                        partner_mask=partner_up)
                print("[dry] cut %d: %d stage-1 graphs (%d nodes) + layers graph (%d nodes)" % (cid, len(jobs), len(jobs[0]["graph"]), len(g2)))
                continue
            got = {}
            for r in res:
                got.setdefault(r["label"], []).append(os.path.join(run_dir, r["file"]))
            cands = []
            for k in range(K):
                fs = sorted(got.get("cut%02d_s%d_c%d" % (cid, seed, k), []))
                pic = next((f for f in fs if not _gray(f)), None)
                msk = next((f for f in fs if f != pic and _gray(f)), None)
                if pic and msk:
                    cands.append((pic, msk))
            if not cands:
                out["failed"][cid] = "no stage-1 candidate came back"; continue
            Wd = int(round(int(s["width"]) * hires["scale"] / 8)) * 8
            H = int(round(int(s["height"]) * hires["scale"] / 8)) * 8
            best, rows = R._lf_pick(W, kit, ep, cid, regions, cands, Wd, H)
            print("cut %d: partner-zone overlap %s -> candidate %d" % (cid, " / ".join("c%d %.3f" % (k, o) for k, o, _ in rows), best[0]))
            up1 = W._upload_input(nk, cfg, best[2], "%s_cut%02d_layer_s1.png" % (ep, cid))
            # ②③ 배경판·상대 + 층 저장
            g2 = R._lc_layers_graph(W, cfg, s, bp, bn, regions, seed, "nk/%s_layer/cut%02d" % (ep, cid), hires, up1, sb_up, pst, pen,
                                    partner_mask=partner_up)
            outs = c.wait(c.queue(g2), "cut%02d layers" % cid)
            for nid, (lay, _) in list(R.LAYER_SAVES.items()) + list(R.LAYER_MASKS.items()):
                ims = (outs.get(nid) or {}).get("images") or []
                if ims:
                    c.fetch(ims[0], os.path.join(cd, lay + ".png"))
            rep = composite(cd, front3d=front3d)
            if not rep:
                out["failed"][cid] = "layers missing after drawing"; continue
            want = "Z" if (front3d and pick == LAYER_FRONT + ("_" + LAYER_FIX if LAYER_FIX else "")) else pick
            use = want if os.path.exists(os.path.join(cd, "comp", want + ".png")) else "B"
            f = W._final_file(kit, ep, cid)
            r0 = rec.get(str(cid)) or {}
            if os.path.exists(f) and _md5(f) != r0.get("final_md5"):       # 누끼 레이어가 만든 것이 아닌 최종본 -> 보관
                os.makedirs(os.path.join(root, "orig"), exist_ok=True)
                shutil.copy(f, os.path.join(root, "orig", "cut%02d.png" % cid))
            os.makedirs(os.path.dirname(f), exist_ok=True)
            shutil.copy(os.path.join(cd, "comp", use + ".png"), f)
            rec[str(cid)] = {"use": use, "seed": seed, "stage1": best[0], "overlap": {str(k): round(o, 4) for k, o, _ in rows},
                             "final_md5": _md5(f), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "check": rep["check"], "specks_removed": rep["specks_removed"], "changed_vs_base": rep["changed_vs_base"]}
            json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            out["used"][cid] = use
            print("   -> cut %02d uses %s (other candidates: %s)" % (cid, use, os.path.join(cd, "comp")))
        except SystemExit as e:
            out["failed"][cid] = "stopped (exit %s) - look at the log above" % e.code
    return out


# 누끼 레이어는 두 캐릭터를 따로 그려서 손이 맞닿지 않음 (duo1 닿는 컷 0/3). Krita 문서 팁: 한 캐릭터만 다시 그리면 상호작용이 사라짐 ->
# 두 사람이 겹치는 곳을 같이 덮어 한 번에.
TOUCH_GROW = 24
TOUCH_MIN = 0.0005     # 이보다 좁으면 닿는 곳 없음 (그림의 0.05%)


def touch_region(d, grow_n=TOUCH_GROW, margin=96):
    """층 폴더 -> (닿는 곳 틀 H x W float, 자를 상자 x0,y0,x1,y1) 또는 (None, None). 얼굴(머리 틀)은 뺌"""
    m1, mR, h1, hR = (load(os.path.join(d, x + ".png"), True) for x in ("m1", "mR", "h1", "hR"))
    a = grow((m1 > 0.5).astype(np.float32), grow_n) > 0.5
    b = grow((mR > 0.5).astype(np.float32), grow_n) > 0.5
    heads = grow(((h1 > 0.5) | (hR > 0.5)).astype(np.float32), 8) > 0.5
    t = a & b & ~heads
    if t.mean() < TOUCH_MIN:
        return None, None
    ys, xs = np.nonzero(t)
    H, W = t.shape
    x0, x1 = max(0, int(xs.min()) - margin), min(W, int(xs.max()) + margin)
    y0, y1 = max(0, int(ys.min()) - margin), min(H, int(ys.max()) + margin)
    return np.clip(blur(t.astype(np.float32), 8, 4.0), 0, 1), (x0, y0, x1, y1)


def _touch_graph(W, cfg, s, bp, bn, regions, seed, prefix, img, mask, m_first, m_other, cw, ch, denoise, lora):
    """자른 그림(img)의 닿는 곳(mask)만 다시 칠함: 장면 글 + 두 캐릭터 영역(ETN, 자기 틀 모양), DifferentialDiffusion, 세기 denoise"""
    import nk_regional as R
    fi = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
    order = [regions[fi]] + [r for i, r in enumerate(regions) if i != fi]
    g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}}
    model, clip = ["4", 0], ["4", 1]
    ch0 = regions[fi]["char"] or {}
    if lora and ch0.get("lora"):
        st = float(ch0.get("lora_strength", 1.0))
        g["90"] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip, "lora_name": ch0["lora"],
                                                           "strength_model": st, "strength_clip": st}}
        model, clip = ["90", 0], ["90", 1]
    g["10"] = {"class_type": "LoadImage", "inputs": {"image": img}}
    g["11"] = {"class_type": "LoadImageMask", "inputs": {"image": mask, "channel": "red"}}
    g["12"] = {"class_type": "LoadImageMask", "inputs": {"image": m_first, "channel": "red"}}
    g["13"] = {"class_type": "LoadImageMask", "inputs": {"image": m_other, "channel": "red"}}
    g["14"] = {"class_type": "ImageScale", "inputs": {"image": ["10", 0], "upscale_method": "lanczos", "width": cw, "height": ch, "crop": "disabled"}}
    g["40"] = {"class_type": "CLIPTextEncode", "inputs": {"text": bp, "clip": clip}}
    negs, seen = [], set()
    for t in ", ".join([bn] + [r["neg"] for r in regions]).split(","):
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower()); negs.append(t)
    g["41"] = {"class_type": "CLIPTextEncode", "inputs": {"text": ", ".join(negs), "clip": clip}}
    g["70"] = {"class_type": "ETN_BackgroundRegion", "inputs": {"conditioning": ["40", 0]}}
    prev = ["70", 0]
    for i, (r, mnode) in enumerate(zip(order, ("12", "13"))):
        b = 100 + i * 10
        g[str(b)] = {"class_type": "CLIPTextEncode", "inputs": {"text": R._region_text(W, bp, r["pos1"], False), "clip": clip}}
        g[str(b + 7)] = {"class_type": "ETN_DefineRegion", "inputs": {"regions": prev, "mask": [mnode, 0], "conditioning": [str(b), 0]}}
        prev = [str(b + 7), 0]
    g["80"] = {"class_type": "ETN_AttentionMask", "inputs": {"model": model, "regions": prev}}
    g["81"] = {"class_type": "DifferentialDiffusion", "inputs": {"model": ["80", 0], "strength": 1.0}}
    g["82"] = {"class_type": "InpaintModelConditioning", "inputs": {"positive": ["40", 0], "negative": ["41", 0], "vae": ["4", 2],
                                                                     "pixels": ["14", 0], "mask": ["11", 0], "noise_mask": True}}
    g["3"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                                   "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(denoise),
                                                   "model": ["81", 0], "positive": ["82", 0], "negative": ["82", 1], "latent_image": ["82", 2]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


def touch_fix(nk, kit, conti, cid, d, base="B", denoise=0.5, seed=71, lora=False, dry=False):
    """층 폴더 d 의 합친 그림 comp/<base>.png 에서 닿는 곳만 다시 칠함 -> comp/<base>_T<세기>[L].png. 돌려줌: 결과 경로 또는 None"""
    from PIL import Image
    import nk_webtoon as W
    import nk_regional as R
    cfg = nk.load_presets()
    ep = conti["_ep"]
    cut = {int(c["id"]): c for c in conti["cuts"]}[int(cid)]
    src = os.path.join(d, "comp", base + ".png")
    if not os.path.exists(src) and all(os.path.exists(os.path.join(d, x + ".png")) for x in NEED):
        composite(d)
    if not os.path.exists(src):
        print("[touch] no %s" % src); return None
    t, box = touch_region(d)
    if t is None:
        print("[touch] cut %d: the two characters do not come close (no contact region)" % cid); return None
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    k = 1024.0 / max(bw, bh)
    cw, ch = int(round(bw * k / 8)) * 8, int(round(bh * k / 8)) * 8
    tag = "%s_T%s%s" % (base, ("%g" % denoise).replace(".", ""), "L" if lora else "")
    tmp = os.path.join(d, "touch")
    os.makedirs(tmp, exist_ok=True)
    im = Image.open(src).convert("RGB")
    im.crop(box).save(os.path.join(tmp, tag + "_crop.png"))
    m1, mR = (load(os.path.join(d, x + ".png"), True) for x in ("m1", "mR"))

    def msave(a, name):
        p = os.path.join(tmp, name)
        Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).resize((cw, ch), Image.BILINEAR).convert("RGB").save(p)
        return p
    pm = msave(t[y0:y1, x0:x1], tag + "_mask.png")
    p1 = msave(grow((m1 > 0.5).astype(np.float32), 12)[y0:y1, x0:x1], tag + "_m1.png")
    pR = msave(grow((mR > 0.5).astype(np.float32), 12)[y0:y1, x0:x1], tag + "_mR.png")
    s = R._settings(nk, W, cfg, conti, cut)
    bp, bn, regions = W._duo_parts(nk, cfg, conti, cut, s)
    up = lambda p: W._upload_input(nk, cfg, p, "%s_cut%02d_%s" % (ep, cid, os.path.basename(p)), dry)
    g = _touch_graph(W, cfg, s, bp, bn, regions, seed, "nk/%s_touch/cut%02d_%s" % (ep, cid, tag),
                     up(os.path.join(tmp, tag + "_crop.png")), up(pm), up(p1), up(pR), cw, ch, denoise, lora)
    print("[touch] cut %d %s: contact %.2f%% of the picture, box %s -> %dx%d, denoise %g, LoRA %s"
          % (cid, base, 100 * float((t > 0.5).mean()), box, cw, ch, denoise, "on" if lora else "off"))
    if dry:
        print("[dry] touch graph %d nodes" % len(g)); return None
    c = nk.Comfy(cfg.get("server", "auto"))
    outs = c.wait(c.queue(g), "cut%02d touch" % cid)
    ims = (outs.get("9") or {}).get("images") or []
    if not ims:
        print("[touch] no picture came back"); return None
    rp = os.path.join(tmp, tag + "_raw.png")
    c.fetch(ims[0], rp)
    new = np.asarray(Image.open(rp).convert("RGB").resize((bw, bh), Image.LANCZOS), np.float32) / 255.0
    out = load(src)
    out[y0:y1, x0:x1] = comp(new, out[y0:y1, x0:x1], t[y0:y1, x0:x1])
    dst = os.path.join(d, "comp", tag + ".png")
    save(out, dst)
    print("[touch] -> %s" % dst)
    return dst


def run_touch(nk, kit, args):
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    d = args.layers or os.path.join(W.ep_dir(kit, args.ep), "cuts_layer", "cut%02d" % int(args.cut))
    for dn in [float(x) for x in args.denoise.split(",")]:
        touch_fix(nk, kit, conti, int(args.cut), d, args.base, dn, int(args.seed), args.lora, args.dry)


def run(nk, kit, args):
    import shutil
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    root = os.path.join(W.ep_dir(kit, args.ep), "cuts_layer")
    rec_p = os.path.join(root, "layer.json")
    if args.use:
        rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
        for ch in args.use:
            cid, v = ch.split("=")
            cid = int(cid)
            f = W._final_file(kit, args.ep, cid)
            src = os.path.join(root, "orig", "cut%02d.png" % cid) if v == "0" else os.path.join(root, "cut%02d" % cid, "comp", v + ".png")
            if not os.path.exists(src):
                print("[ERROR] not found:", src, "(candidates: %s)" % " ".join(VARIANTS)); sys.exit(1)
            shutil.copy(src, f)
            r = rec.setdefault(str(cid), {})
            r.update(use=v, manual=True, final_md5=_md5(f) if v != "0" else None)
            print("cut %02d -> %s" % (cid, "the picture before layer" if v == "0" else v))
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    ids = [int(x) for x in args.cuts] or [int(c["id"]) for c in conti["cuts"] if c.get("_roles")]
    out = draw(nk, kit, conti, ids, int(args.seed), int(args.k), args.pick, args.dry, getattr(args, "pose3d", None))
    if out["failed"]:
        print("failed:", out["failed"])
        sys.exit(1)


def add_parser(esub, nk, kit):
    a = esub.add_parser("layer", help="two-character cuts by layers: LoRA character + background -> clean plate -> partner alone -> cut out and stack")
    a.add_argument("ep")
    a.add_argument("cuts", nargs="*")
    a.add_argument("--seed", default="71")
    a.add_argument("--k", default=str(LAYER_K), help="stage-1 candidates (LoRA character + background) to pick from")
    a.add_argument("--pick", choices=VARIANTS + ["Z"], help="which composite becomes the final (default %s)" % LAYER_FRONT)
    a.add_argument("--pose3d", help="TEST: folder with 3D doll renders <dir>/cutNN (tools/pose3d) -> partner region + solo poses + Z order")
    a.add_argument("--use", nargs="*", help="5=A_SF use that candidate / 5=0 back to the picture before layer")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
    a = esub.add_parser("touchfix", help="TEST (research T5): repaint only where the two characters touch, both characters together")
    a.add_argument("ep")
    a.add_argument("cut")
    a.add_argument("--layers", help="layer folder (default episodes/<ep>/cuts_layer/cutNN; regtest: runs/regtest/<name>/cutNN_s71)")
    a.add_argument("--base", default="B", choices=VARIANTS, help="which composite to start from")
    a.add_argument("--denoise", default="0.5", help="one or more, e.g. 0.4,0.5,0.6")
    a.add_argument("--seed", default="71")
    a.add_argument("--lora", action="store_true", help="character LoRA on the whole repaint")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run_touch(nk, kit, x))
