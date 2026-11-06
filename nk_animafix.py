# -*- coding: utf-8 -*-
"""LoRA 캐릭터 자리만 다시 그리기: 두 명 컷을 LoRA 없이 그린 뒤, SAM3 로 LoRA 캐릭터 자리를 찾아 크게 잘라
Anima + LoRA + 그 캐릭터 설명으로 다시 그리고 붙임. 한 장 전체에 LoRA 를 걸면 상대에게도 번지기 때문(추정).
커뮤니티 방식(Anima 워크플로: 그린 뒤 SAM3 로 얼굴을 잘라 크게 다시 그림)과 같은 원리. 상대는 틀 밖이라 안 바뀜.

사용: nk ep animafix <ep> [컷...] [--who <cast 이름>] [--find "<찾을 말>"] [--denoise 0.55] [--seed 900] [--to m02f] [--dry]
결과: <to>/cuts/cutNN.png (고친 컷, --to 가 없으면 episodes/<ep>/cuts_animafix/), <ep>/cuts_animafix/cutNN_cmp.png (원본 자리 | 고친 자리),
      animafix.json"""
import os, sys, json, time, re, shutil

PAD = 0.14
SIDE = 1024         # 잘라서 키울 긴 변
GROW = 0.03


def box_from_mask(m, W, H):
    """틀(bool 배열) -> 여백 넣은 상자 (x0, y0, x1, y1), 그림 밖으로 안 나감"""
    import numpy as np
    ys, xs = np.where(m)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    L = max(x1 - x0, y1 - y0)
    p = int(L * PAD)
    return int(max(0, x0 - p)), int(max(0, y0 - p)), int(min(W, x1 + p)), int(min(H, y1 + p))


def crop_size(bw, bh):
    """상자 -> 키울 크기 (긴 변 SIDE, 16의 배수)"""
    s = SIDE / float(max(bw, bh))
    return max(16, int(round(bw * s / 16)) * 16), max(16, int(round(bh * s / 16)) * 16)


def paste_back(orig, fixed_crop, mask_crop, box):
    """고친 자리를 원본에 붙임: 틀(부드럽게)만큼만 섞음. orig·결과 = PIL RGB"""
    from PIL import Image, ImageFilter
    x0, y0, x1, y1 = [int(v) for v in box]
    fc = fixed_crop.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    mk = mask_crop.resize((x1 - x0, y1 - y0), Image.LANCZOS).filter(ImageFilter.GaussianBlur(int(max(2, (x1 - x0) // 150))))
    out = orig.copy()
    out.paste(fc, (x0, y0), mk)
    return out


def chest_mask(body, head, down=1.4, up=0.15):
    """가슴만 한 번 더: 몸 틀(body) 중 머리 틀(head) 바로 아래 띠만.
    띠 = 머리 아래 끝에서 머리 높이 x up 만큼 위(목 포함) ~ 머리 높이 x down 만큼 아래. 머리를 못 찾으면 None.
    얼굴은 틀 밖이라 안 바뀜"""
    import numpy as np
    ys = np.where(head.any(axis=1))[0]
    if len(ys) == 0:
        return None
    hh = ys.max() - ys.min() + 1
    y0, y1 = max(0, int(ys.max() - hh * up)), min(body.shape[0], int(ys.max() + hh * down))
    band = np.zeros_like(body, dtype=bool)
    band[y0:y1] = True
    return body & band & ~head


def desc_for(ch, cut, box, H, mode="auto"):
    """상자가 컷 높이의 60% 넘으면 전신 설명, 아니면 윗몸.
    mode=head (얼굴 한 번 더, 아카라이브 워크플로우의 face 크롭처럼) = anima_head"""
    import nk_animacut as A
    if mode == "chest":
        return ch.get("anima_chest") or ch.get("anima_upper"), "upper body, close-up"
    if mode == "head":
        if A.is_back(cut) and ch.get("anima_back"):
            return ch["anima_back"], "from behind, facing away, close-up"
        return ch.get("anima_face") or ch.get("anima_head") or ch.get("anima_upper"), "portrait, close-up"
    if A.is_back(cut) and ch.get("anima_back"):
        return ch["anima_back"], "from behind, facing away"
    if (box[3] - box[1]) > 0.6 * H:
        return ch.get("anima_lora_desc") or ch["anima"], "full body"
    return ch.get("anima_upper") or ch.get("anima_lora_desc"), "upper body"


def graph(v, text, neg, img, mask, seed, den, prefix):
    import nk_animatest
    g = nk_animatest.graph(dict(v, easycache=v.get("easycache", False)), text, neg, 64, 64, seed, prefix)
    g["20"] = {"class_type": "LoadImage", "inputs": {"image": img}}
    g["21"] = {"class_type": "LoadImage", "inputs": {"image": mask}}
    g["22"] = {"class_type": "ImageToMask", "inputs": {"image": ["21", 0], "channel": "red"}}
    g["23"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["3", 0]}}
    g["24"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["23", 0], "mask": ["22", 0]}}
    g["8"]["inputs"]["latent_image"] = ["24", 0]
    g["8"]["inputs"]["denoise"] = float(den)
    del g["7"]
    return g


def run(nk, kit, args):
    import numpy as np
    from PIL import Image, ImageFilter
    import nk_webtoon as W, nk_sam, nk_animacut as A
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    who = args.who or next((k for k, c in (conti.get("_cast") or {}).items() if c and c.get("anima_lora")), None)
    ch = (conti.get("_cast") or {}).get(who)                        # load_conti 가 채움 (_resolve_cast)
    if not ch or not ch.get("anima_lora"):
        print("[ERROR] %s: no such character or no anima_lora" % who); sys.exit(1)
    ids = [int(x) for x in args.cuts] or [int(c["id"]) for c in conti["cuts"]]
    has = lambda c: who in [str(r.get("char")) for r in c.get("cast") or []] + [str(c.get("_charkey"))]
    cuts = [c for c in conti["cuts"] if int(c["id"]) in ids and has(c)
            and (args.dry or os.path.exists(W._final_file(kit, args.ep, int(c["id"]))))]
    if args.desc == "chest":                  # 뒷모습은 가슴이 안 보임
        cuts = [c for c in cuts if not A.is_back(c)]
    epd = W.ep_dir(kit, args.ep)
    wd = os.path.join(epd, "cuts_animafix" + ("_chest" if args.desc == "chest" else "")); os.makedirs(wd, exist_ok=True)
    words = W.find_words(ch)
    head = args.desc == "head"
    find = args.find or (words[0] + " head" if head else words[0])
    items = []
    for c in cuts:
        src = W._final_file(kit, args.ep, int(c["id"]))
        items.append(("cut%02d" % int(c["id"]), src, find + ":1"))
    print("animafix %s: %d cuts, find '%s', denoise %s, LoRA %s" % (args.ep, len(items), find, args.denoise, ch["anima_lora"]))
    got = nk_sam.segment(nk, kit, cfg, args.ep, items, 0.4, run="animafix_sam", dry=args.dry)
    if not args.dry:
        lo = 0.002 if args.desc == "head" else 0.01
        falls = [w + " head" if head else w for w in words if (w + " head" if head else w) != find]

        def cover(nm, key):
            ps = got.get((nm, key))
            if not ps:
                return 0.0
            return float((np.asarray(Image.open(sorted(ps)[0]).convert("L")) > 127).mean())
        for nm, src, pr in items:
            if cover(nm, pr) >= lo:
                continue
            for fw in falls:
                g2 = nk_sam.segment(nk, kit, cfg, args.ep, [(nm, src, fw + ":1")], 0.4, run="animafix_sam")
                ps = g2.get((nm, fw + ":1"))
                if ps and (np.asarray(Image.open(sorted(ps)[0]).convert("L")) > 127).mean() >= lo:
                    got[(nm, pr)] = ps; print("   %s: found by '%s'" % (nm, fw)); break
    heads = {}
    if args.desc == "chest" and not args.dry:   # 가슴 띠를 정하려고 머리 틀도 (못 찾으면 다른 말로)
        for nm, src, _ in items:
            for hw in [w + " head" for w in words]:
                g3 = nk_sam.segment(nk, kit, cfg, args.ep, [(nm, src, hw + ":1")], 0.4, run="animafix_sam")
                ps = g3.get((nm, hw + ":1"))
                if ps and (np.asarray(Image.open(sorted(ps)[0]).convert("L")) > 127).mean() >= 0.002:
                    heads[nm] = sorted(ps)[0]; break
    v = {"unet": "anima-base-v1.0.safetensors", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple",
         "lora": ch["anima_lora"], "lora_strength": float(ch.get("anima_lora_strength", 1.0))}
    c_ = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    rec_p = os.path.join(wd, "animafix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    to = W.ep_dir(kit, args.to) if args.to else None
    if args.dry and to:
        print("[dry] would write %s/cuts" % to); to = None
    if to:
        os.makedirs(os.path.join(to, "cuts"), exist_ok=True)
        if not os.path.exists(os.path.join(to, "conti.yaml")):
            s = open(os.path.join(epd, "conti.yaml"), encoding="utf-8").read()
            open(os.path.join(to, "conti.yaml"), "w", encoding="utf-8").write(
                "# %s = %s 에서 LoRA 캐릭터 자리만 다시 그림 (nk ep animafix). 컷 메모는 원본 그대로\n" % (args.to, args.ep) + re.sub(r"^title: *\"?(.*?)\"?$", lambda m: "title: \"(다시 그림) " + m.group(1).replace('"', "") + "\"", s, count=1, flags=re.M))
    for c in cuts:
        cid = int(c["id"]); nm = "cut%02d" % cid
        src = W._final_file(kit, args.ep, cid)
        if not os.path.exists(src):
            print("[skip] %s: picture gone" % nm); continue
        orig = Image.open(src).convert("RGB")
        mps = got.get((nm, args.find + ":1"))
        if args.dry:
            print("[dry] %s: %s" % (nm, src)); continue
        if not mps:
            print("[skip] %s: SAM3 found no '%s'" % (nm, args.find)); continue
        m = np.asarray(Image.open(sorted(mps)[0]).convert("L").resize(orig.size)) > 127
        if args.desc == "chest":
            if nm not in heads:
                print("[skip] %s: SAM3 found no head (chest band needs it)" % nm); continue
            hm = np.asarray(Image.open(heads[nm]).convert("L").resize(orig.size)) > 127
            m = chest_mask(m, hm)
            if m is None:
                print("[skip] %s: no chest band" % nm); continue
        if m.mean() < (0.002 if args.desc in ("head", "chest") else 0.01):          # 얼굴 한 번 더: 전신 컷의 머리는 그림의 1% 안팎
            print("[skip] %s: mask too small (%.3f)" % (nm, m.mean())); continue
        k = max(3, int(max(orig.size) * (GROW / 2 if args.desc in ("head", "chest") else GROW))) | 1
        mg = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k))) > 127
        if args.desc == "chest":          # 넓힌 틀도 얼굴은 빼고, 자르는 상자는 머리까지 (모델이 윗몸 전체를 보고 가슴만 다시)
            mg = mg & ~hm
            box = box_from_mask(mg | hm, orig.width, orig.height)
        else:
            box = box_from_mask(mg, orig.width, orig.height)
        bw, bh = box[2] - box[0], box[3] - box[1]
        cw, chh = crop_size(bw, bh)
        crop = orig.crop(box).resize((cw, chh), Image.LANCZOS)
        mcrop = Image.fromarray((mg * 255).astype(np.uint8)).crop(box).resize((cw, chh), Image.LANCZOS)
        cp, mp = os.path.join(wd, nm + "_crop.png"), os.path.join(wd, nm + "_cropmask.png")
        crop.save(cp); mcrop.convert("RGB").save(mp)
        d, view = desc_for(ch, c, box, orig.height, args.desc)
        art = c.get("anima_artist", conti.get("artist", ""))
        head = ", ".join(x for x in ("masterpiece, best quality, score_7, safe", ("@" + art.lstrip("@")) if art else "",
                                     "1boy, solo, furry, anthro", view) if x)
        text = "%s. The character: %s." % (head, d)
        up_i = W._upload_input(nk, cfg, cp, "%s_animafix_%s.png" % (args.ep, nm), False)
        up_m = W._upload_input(nk, cfg, mp, "%s_animafix_%s_mask.png" % (args.ep, nm), False)
        neg = A.NEG + ((", " + ch["anima_face_neg"]) if args.desc == "head" and ch.get("anima_face_neg") else "")
        g = graph(v, text, neg, up_i, up_m, int(args.seed) + cid, args.denoise, "nk/%s_animafix/%s" % (args.ep, nm))
        t0 = time.time()
        outs = c_.wait(c_.queue(g), nm)
        ims = (outs.get("10") or {}).get("images") or []
        if not ims:
            print("[ERROR] %s: no image" % nm); continue
        fp = os.path.join(wd, nm + "_fixcrop.png")
        c_.fetch(ims[0], fp)
        fixed = Image.open(fp).convert("RGB")
        out = paste_back(orig, fixed, mcrop, box)
        dst = os.path.join(to, "cuts", nm + ".png") if to else os.path.join(wd, nm + ".png")
        if os.path.abspath(dst) == os.path.abspath(src):
            pre = os.path.join(epd, "_alt", "preface", nm + ".png")
            if not os.path.exists(pre):
                os.makedirs(os.path.dirname(pre), exist_ok=True)
                shutil.copy(src, pre)
        out.save(dst)
        H0 = 520                                                            # 검수용: 원본 자리 | 고친 자리
        a, b = orig.crop(box), out.crop(box)
        a = a.resize((int(a.width * H0 / a.height), H0)); b = b.resize((int(b.width * H0 / b.height), H0))
        cmp_ = Image.new("RGB", (a.width + b.width + 8, H0), "white"); cmp_.paste(a, (0, 0)); cmp_.paste(b, (a.width + 8, 0))
        cmp_.save(os.path.join(wd, nm + "_cmp.png"))
        rec[nm] = {"src": src, "box": list(map(int, box)), "mask_cover": round(float(m.mean()), 4), "text": text, "negative": neg, "denoise": float(args.denoise),
                   "seed": int(args.seed) + cid, "lora": v["lora"], "out": dst, "secs": round(time.time() - t0, 1), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("   %s box %s -> %s (%.0f s)" % (nm, box, dst, time.time() - t0))
        if getattr(args, "on_done", None):
            args.on_done(cid)


def add_parser(esub, nk, kit):
    a = esub.add_parser("animafix", help="TEST: repaint only the LoRA character's area (SAM3) larger with Anima + LoRA, paste back")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.add_argument("--who", help="cast name of the LoRA character (default: the one whose character file has anima_lora)")
    a.add_argument("--find", help="SAM3 word for that character (default: from the character file, else its species tag)")
    a.add_argument("--denoise", default="0.55"); a.add_argument("--seed", default="900")
    a.add_argument("--to", help="write fixed cuts to episodes/<to>/cuts (+ copy conti) so the label page shows them side by side")
    a.add_argument("--desc", default="auto", choices=["auto", "head", "chest"],
                   help="head = second pass on the face only (anima_face), use with --find '<word> head' / "
                        "chest = chest band only (body mask under the head, anima_chest, face kept)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
