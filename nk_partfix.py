# -*- coding: utf-8 -*-
"""한 캐릭터의 한 부위만 다시 그리기
왜: 컷 전체를 다시 그리면 마음에 들던 곳까지 바뀜. 얼굴 한 번 더(nk_animafix)와 같은 방식 — 그 자리만 SAM3 로 찾아 크게 잘라
    Anima(+ 그 캐릭터 LoRA 가 있으면 LoRA)로 다시 그리고 붙임 — 을 손·가슴/배·꼬리·귀·발과 LoRA 없는 캐릭터로 넓힘.
    최종본은 그대로 두고 episodes/<ep>/cands/cutNN/pNN.png 로 후보를 남김 -> 작업실 '이걸로' (nk ep usecand) 가 최종본으로 바꾸고 말풍선을 다시 넣음.
    품질(특히 손)은 아직 시험 전 — 그래서 자동 적용이 아니라 후보 + 고르기."""
import os, sys, json, time, shutil

PART_WORD = {"head": "head", "hand": "hand", "tail": "tail", "ear": "ear", "foot": "foot"}        # chest = 몸 틀에서 머리 아래 띠 (animafix.chest_mask)
PART_VIEW = {"head": "portrait, close-up", "hand": "close-up, hand focus", "chest": "upper body, close-up",
             "tail": "close-up, tail focus", "ear": "close-up", "foot": "close-up, foot focus"}
PART_MAX = {"head": 1, "hand": 2, "chest": 1, "tail": 1, "ear": 2, "foot": 2}                    # 한 컷에서 고칠 조각 수
PART_DENOISE = {"head": 0.6, "hand": 0.6, "chest": 0.55, "tail": 0.55, "ear": 0.55, "foot": 0.6}
PAD_SMALL = 0.5          # 손·귀·발·꼬리: 상자를 넉넉히 (팔·머리가 같이 보여야 모양을 맞춤)


def find_words(ch):
    """그 캐릭터를 SAM3 로 찾을 말들 (캐릭터 파일 anima_find·sam_body > 종 태그, LoRA 없는 상대는 regionlora.partner_words)"""
    import nk_regionlora as R, nk_webtoon as W
    if ch.get("anima_find"):
        return [str(ch["anima_find"])]
    if ch.get("anima_lora"):
        return W.find_words(ch)
    return R.partner_words(ch)


def desc_for(ch, part):
    if part == "head":
        return ch.get("anima_face") or ch.get("anima_head") or ch.get("anima_upper") or ch.get("anima_lora_desc") or ch.get("anima") or ""
    if part == "chest":
        return ch.get("anima_chest") or ch.get("anima_upper") or ch.get("anima_lora_desc") or ch.get("anima") or ""
    return ch.get("anima_upper") or ch.get("anima_lora_desc") or ch.get("anima") or ""


def part_text(ch, part, artist):
    tags = [t.strip().lower() for t in str(ch.get("tags_short", "")).split(",")]
    head = ["masterpiece, best quality, score_7, safe"]
    if artist:
        head.append("@" + str(artist).lstrip("@"))
    head.append("solo")
    if ch.get("anima_lora") or "furry" in tags:
        head.append("furry, anthro")
    head.append(PART_VIEW[part])
    return "%s. The character: %s." % (", ".join(head), desc_for(ch, part))


def keep_in_body(masks, body, min_in=0.5):
    """찾은 조각(bool 배열) 중 그 캐릭터 몸 틀(넓힌 것) 안에 절반 넘게 든 것만, 큰 순서"""
    out = []
    for m in masks:
        a = int(m.sum())
        if a == 0:
            continue
        if body is None or (m & body).sum() / float(a) >= min_in:
            out.append((a, m))
    out.sort(key=lambda x: -x[0])
    return [m for _, m in out]


def next_name(cd):
    k = 1
    while os.path.exists(os.path.join(cd, "p%02d.png" % k)):
        k += 1
    return "p%02d.png" % k


def run(nk, kit, args):
    import numpy as np
    from PIL import Image, ImageFilter
    import nk_webtoon as W, nk_sam, nk_animacut as A, nk_animafix as F, nk_regionlora as R
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cid, who, part = int(args.cut), args.who, args.part
    cut = next((c for c in conti["cuts"] if int(c["id"]) == cid), None)
    ch = (conti.get("_cast") or {}).get(who)
    if cut is None or not ch:
        print("[ERROR] cut %d or character '%s' not in this episode" % (cid, who)); sys.exit(1)
    in_cut = [str(r.get("char")) for r in cut.get("cast") or []] + [str(cut.get("_charkey"))]
    if who not in in_cut:
        print("[ERROR] '%s' is not in cut %d" % (who, cid)); sys.exit(1)
    if part not in PART_VIEW:
        print("[ERROR] part must be one of %s" % ", ".join(PART_VIEW)); sys.exit(1)
    src = W._final_file(kit, args.ep, cid)
    nm = "cut%02d" % cid
    artist = cut.get("anima_artist", conti.get("artist", ""))
    text = part_text(ch, part, artist)
    den = float(args.denoise) if args.denoise else PART_DENOISE[part]
    print("partfix %s %s: %s %s | denoise %.2f | %d candidates%s" % (args.ep, nm, who, part, den, int(args.n),
                                                                  (" | LoRA " + ch["anima_lora"]) if ch.get("anima_lora") else ""))
    print("  " + text[:300])
    if args.dry:
        print("[dry] find words %s, part word %s" % (find_words(ch), PART_WORD.get(part, "(chest band)"))); return
    if not os.path.exists(src):
        print("[ERROR] no picture for cut %d" % cid); sys.exit(1)
    epd = W.ep_dir(kit, args.ep)
    orig = Image.open(src).convert("RGB")
    Wd, Hd = orig.size

    def sam(word, n=1, individual=False):
        key = "%s:%d" % (word, n)
        got = nk_sam.segment(nk, kit, cfg, args.ep, [(nm, src, key)], 0.4, run="partfix_sam", individual=individual)
        return [np.asarray(Image.open(p).convert("L").resize((Wd, Hd))) > 127 for p in sorted(got.get((nm, key)) or [])]

    # 1) 그 캐릭터 몸 틀
    body, fw_used = None, None
    others = [c2 for r, c2 in (cut.get("_roles") or []) if str(r.get("char")) != who and c2]
    lora_other = next((c2 for c2 in others if c2.get("anima_lora")), None)
    if not ch.get("anima_lora") and lora_other is not None:
        nmask = None
        for fw in find_words(lora_other):
            ms = sam(fw, 1)
            if ms and 0.02 <= ms[0].mean() <= 0.6:
                nmask = ms[0]; break
        if nmask is not None:
            body, fw_used, _ = R.find_partner(nk, kit, cfg, args.ep, nm, src, nmask, ch, run="partfix_sam")
    if body is None:
        for fw in find_words(ch):
            ms = sam(fw, 3, individual=True) if not ch.get("anima_lora") else sam(fw, 1)
            ms = [m for m in ms if 0.01 <= m.mean() <= 0.7]
            if ms:
                body, fw_used = max(ms, key=lambda m: m.sum()), fw; break
    if body is None:
        print("[ERROR] %s: SAM3 found no '%s'" % (nm, "/".join(find_words(ch)))); sys.exit(1)
    k = max(3, int(max(Wd, Hd) * 0.03)) | 1
    body_g = np.asarray(Image.fromarray((body * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k))) > 127
    print("   %s: body by '%s' %.1f%%" % (nm, fw_used, body.mean() * 100))

    # 2) 부위 틀
    parts = []
    if part == "chest":
        hm = None
        for hw in ("%s head" % fw_used, "head"):
            ms = keep_in_body(sam(hw, 2, individual=True), body_g)
            if ms:
                hm = ms[0]; break
        cm = F.chest_mask(body, hm) if hm is not None else None
        if cm is not None and cm.mean() >= 0.002:
            parts = [cm]
    else:
        pw = PART_WORD[part]
        for word in ("%s %s" % (fw_used, pw), pw):
            ms = keep_in_body(sam(word, 4, individual=True), body_g)
            ms = [m for m in ms if m.mean() >= 0.0005 and (part == "head" or m.sum() < 0.6 * body.sum())]
            if ms:
                parts = ms[:PART_MAX[part]]; break
    if not parts:
        print("[ERROR] %s: SAM3 found no %s of '%s' (그 부위가 그림에 안 보이거나 너무 작음)" % (nm, part, fw_used)); sys.exit(1)
    print("   %s: %d %s piece(s) %s" % (nm, len(parts), part, ", ".join("%.2f%%" % (m.mean() * 100) for m in parts)))

    # 3) 후보마다: 조각을 차례로 크게 잘라 다시 그려 붙임 (최종본은 그대로)
    v = {"unet": "anima-base-v1.0.safetensors", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple"}
    if ch.get("anima_lora"):
        v.update(lora=ch["anima_lora"], lora_strength=float(ch.get("anima_lora_strength", 1.0)))
    neg = A.NEG + ((", " + ch["anima_face_neg"]) if part == "head" and ch.get("anima_face_neg") else "")
    c_ = nk.Comfy(cfg.get("server", "auto"))
    cd = os.path.join(epd, "cands", nm)
    wd = os.path.join(epd, "cuts_partfix")
    os.makedirs(cd, exist_ok=True); os.makedirs(wd, exist_ok=True)
    rl = None
    try:
        rl = json.load(open(os.path.join(epd, "regionlora.json"), encoding="utf-8")).get(nm)
    except Exception:
        pass
    made = []
    for n in range(int(args.n)):
        img = orig.copy()
        t0 = time.time()
        for j, m in enumerate(parts):
            kg = max(3, int(max(Wd, Hd) * (0.015 if part in ("head", "chest") else 0.01))) | 1
            mg = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(kg))) > 127
            ys, xs = np.where(mg)
            L = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
            pad = int(L * (F.PAD if part in ("head", "chest") else PAD_SMALL))
            box = (int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)), int(min(Wd, xs.max() + 1 + pad)), int(min(Hd, ys.max() + 1 + pad)))
            cw, chh = F.crop_size(box[2] - box[0], box[3] - box[1])
            crop = img.crop(box).resize((cw, chh), Image.LANCZOS)
            mcrop = Image.fromarray((mg * 255).astype(np.uint8)).crop(box).resize((cw, chh), Image.LANCZOS)
            cp, mp = os.path.join(wd, "%s_%d_crop.png" % (nm, j)), os.path.join(wd, "%s_%d_mask.png" % (nm, j))
            crop.save(cp); mcrop.convert("RGB").save(mp)
            up_i = W._upload_input(nk, cfg, cp, "%s_partfix_%s_%d.png" % (args.ep, nm, j), False)
            up_m = W._upload_input(nk, cfg, mp, "%s_partfix_%s_%d_mask.png" % (args.ep, nm, j), False)
            seed = int(args.seed) + cid + 10 * (n + 1) + j + int(time.time()) % 1000 * 100      # 누를 때마다 다른 후보
            g = F.graph(v, text, neg, up_i, up_m, seed, den, "nk/%s_partfix/%s_%d" % (args.ep, nm, j))
            outs = c_.wait(c_.queue(g), "%s %s %d/%d" % (nm, part, n + 1, int(args.n)))
            ims = (outs.get("10") or {}).get("images") or []
            if not ims:
                print("[ERROR] %s: no image" % nm); continue
            fp = os.path.join(wd, "%s_%d_fix.png" % (nm, j))
            c_.fetch(ims[0], fp)
            img = F.paste_back(img, Image.open(fp).convert("RGB"), mcrop, box)
        name = next_name(cd)
        img.save(os.path.join(cd, name))
        if rl is not None:                                  # 말풍선 꼬리 자리 = 지금 그림 그대로 (부위만 바뀜)
            json.dump(rl, open(os.path.join(cd, name[:-4] + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        made.append(name)
        print("   %s candidate %s (%.0f s)" % (nm, name, time.time() - t0))
    json.dump({"cut": cid, "who": who, "part": part, "text": text, "denoise": den, "made": made, "time": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(os.path.join(wd, nm + "_partfix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n후보 %d장 -> %s (작업실 그 컷에서 '이걸로'. 지금 그림은 그대로)" % (len(made), cd))


def add_parser(esub, nk, kit):
    a = esub.add_parser("partfix", help="repaint one body part of one character (SAM3 + Anima inpaint) as candidates; pick with nk ep usecand")
    a.add_argument("ep"); a.add_argument("cut", type=int)
    a.add_argument("--who", required=True); a.add_argument("--part", required=True, choices=sorted(PART_VIEW))
    a.add_argument("--n", default="2"); a.add_argument("--denoise"); a.add_argument("--seed", default="950")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
