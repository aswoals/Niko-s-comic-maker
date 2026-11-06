# -*- coding: utf-8 -*-
"""영역 LoRA: 두 명 컷에서 캐릭터 LoRA 를 그 캐릭터 자리에만 건다 (상대 캐릭터에 LoRA 가 번지지 않게).

방식 = Civitai 32568 'Anima crossover couple generation using regional sampler':
  ① LoRA 없는 전체 글로 기준 그림 ② SAM3 로 LoRA 캐릭터 자리 찾기
  ③ RegionalSampler: 같은 시드로 처음 base_only_steps(6~16) 는 LoRA 없는 전체 글로 = 기준 구도 그대로, 나머지 걸음은
     LoRA 캐릭터 자리만 LoRA + 캐릭터 설명으로. LoRA 는 RegionalPrompt 쪽에만 연결(기본 모델을 '오염'시키지 않음)
  Civitai 권장: 32~33걸음, CFG 5, sgm_uniform, base_only_steps 6(작은 틀일수록 크게), overlap_factor 10(이음새 보이면 16~24), LoRA 0.8~1.0
LoRA 캐릭터 = 콘티 cast 중 캐릭터 파일에 anima_lora 가 있는 캐릭터 (--who 로 직접 고를 수도 있음).

사용: nk ep regionlora <ep> [컷...] [--to <ep>] [--base-only 8] [--steps 32] [--cfg 5] [--overlap 10] [--who <cast 이름>] [--find "<찾을 말>"] [--dry]
결과: episodes/<to>/cuts/cutNN.png (+ 콘티 복사), episodes/<to>/cuts_base/cutNN.png (LoRA 없는 기준), regionlora.json"""
import os, sys, json, time, re, shutil

SAMPLER, SCHED = "euler", "sgm_uniform"
GROW = 0.03


def region_graph(p, base_text, lora_text, neg, mask_img, w, h, seed, invert=False):
    """p = {unet, lora, lora_strength, steps, cfg, base_only, overlap}
    invert: base_sampler = LoRA 모델 + 전체 글, 영역 = LoRA 없는 모델 + 전체 글
상대에게 번진 무늬·수인화만 LoRA 없는 모델이 다시 그림"""
    import nk_animatest as T
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": T.CLIP, "type": "lumina2", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": T.VAE}},
         "11": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": p["lora"], "strength_model": float(p["lora_strength"])}},
         "5": {"class_type": "CLIPTextEncode", "inputs": {"text": base_text, "clip": ["2", 0]}},
         "6": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["2", 0]}},
         "7": {"class_type": "CLIPTextEncode", "inputs": {"text": lora_text, "clip": ["2", 0]}},
         "40": {"class_type": "ToBasicPipe", "inputs": {"model": ["1", 0], "clip": ["2", 0], "vae": ["3", 0], "positive": ["5", 0], "negative": ["6", 0]}},
         "41": {"class_type": "ToBasicPipe", "inputs": {"model": ["11", 0], "clip": ["2", 0], "vae": ["3", 0], "positive": ["7", 0], "negative": ["6", 0]}},
         "42": {"class_type": "KSamplerAdvancedProvider", "inputs": {"cfg": float(p["cfg"]), "sampler_name": SAMPLER, "scheduler": SCHED, "sigma_factor": 1.0, "basic_pipe": ["40", 0]}},
         "43": {"class_type": "KSamplerAdvancedProvider", "inputs": {"cfg": float(p["cfg"]), "sampler_name": SAMPLER, "scheduler": SCHED, "sigma_factor": 1.0, "basic_pipe": ["41", 0]}},
         "44": {"class_type": "LoadImage", "inputs": {"image": mask_img}},
         "45": {"class_type": "ImageToMask", "inputs": {"image": ["44", 0], "channel": "red"}},
         "46": {"class_type": "RegionalPrompt", "inputs": {"mask": ["45", 0], "advanced_sampler": ["43", 0]}},
         "47": {"class_type": "CombineRegionalPrompts", "inputs": {"regional_prompts1": ["46", 0]}},
         "48": {"class_type": "EmptySD3LatentImage", "inputs": {"width": int(w), "height": int(h), "batch_size": 1}},
         "49": {"class_type": "RegionalSampler", "inputs": {"seed": int(seed), "seed_2nd": 0, "seed_2nd_mode": "ignore", "steps": int(p["steps"]),
                                                          "base_only_steps": int(p["base_only"]), "denoise": 1.0, "samples": ["48", 0],
                                                          "base_sampler": ["42", 0], "regional_prompts": ["47", 0], "overlap_factor": int(p["overlap"]),
                                                          "restore_latent": True, "additional_mode": "DISABLE", "additional_sampler": "AUTO",
                                                          "additional_sigma_ratio": 0.3}},
         "9": {"class_type": "VAEDecode", "inputs": {"samples": ["49", 0], "vae": ["3", 0]}},
         "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "nk/regionlora", "images": ["9", 0]}}}
    if invert:
        g["40"]["inputs"].update({"model": ["11", 0], "positive": ["5", 0]})      # 바깥 = LoRA
        g["41"]["inputs"].update({"model": ["1", 0], "positive": ["5", 0]})       # 영역 = LoRA 없음, 전체 글
    return g


def apply_control(g, ctl):
    """그 모델을 쓰던 곳(기본 pipe·LoRA)을 모두 조종된 모델로 바꿈"""
    if not ctl or not ctl.get("_control_up"):
        return g
    g["12c"] = {"class_type": "ModelPatchLoader", "inputs": {"name": ctl["lllite"]}}
    g["13c"] = {"class_type": "LoadImage", "inputs": {"image": ctl["_control_up"]}}
    g["14c"] = {"class_type": "AnimaLLLiteApply", "inputs": {"model": ["1", 0], "model_patch": ["12c", 0], "image": ["13c", 0],
                                                            "strength": float(ctl["lllite_strength"]), "start_percent": 0.0, "end_percent": float(ctl["lllite_end"])}}
    last = ["14c", 0]
    if ctl.get("_control_up2"):
        g["16x"] = {"class_type": "ModelPatchLoader", "inputs": {"name": ctl["lllite2"]}}
        g["16y"] = {"class_type": "LoadImage", "inputs": {"image": ctl["_control_up2"]}}
        g["16z"] = {"class_type": "AnimaLLLiteApply", "inputs": {"model": last, "model_patch": ["16x", 0], "image": ["16y", 0],
                                                                "strength": float(ctl["lllite2_strength"]), "start_percent": 0.0, "end_percent": float(ctl["lllite2_end"])}}
        last = ["16z", 0]
    for k, n in g.items():
        if k in ("14c",):
            continue
        if n.get("inputs", {}).get("model") == ["1", 0]:
            n["inputs"]["model"] = last
    return g


def pose_control(nk, kit, cfg, conti, ep, cut, w, h):
    """콘티 pose3d (auto·scene3d) 면 nk_animacut 과 같은 3D 인형 조종 값 (없으면 {})"""
    import nk_webtoon as W, nk_animacut as A
    mode = str(conti.get("pose3d") or "").lower()
    if mode not in ("auto", "scene3d", "capsule"):
        return {}
    import nk_pose3d_auto as P3
    if not P3.plan_pose(cut) or P3.plan_pose(cut)[0] == "dw":
        return {}
    dp = P3.depth_for(kit, ep, cut, w, h)
    if not dp:
        return {}
    if mode == "scene3d":
        sys.path.insert(0, os.path.join(kit, "tools"))
        from scene3d import export_doll as S3
        S3.make_cut(kit, ep, cut, w, h, dp)
    cid = int(cut["id"])
    up = W._upload_input(nk, cfg, dp, "pose3d_%s_cut%02d.png" % (ep, cid), False)
    up2 = W._upload_input(nk, cfg, dp.replace("_depth3d.png", "_line3d.png"), "pose3d_%s_cut%02d_line.png" % (ep, cid), False)
    st = A.duo_strength(conti, cut) or [P3.STRENGTH, P3.END, P3.STRENGTH2, P3.END2]
    print("   cut %d: 3D 인형 조종 (%s) %s" % (cid, mode, st))
    return dict(lllite=P3.LLLITE, control_kind="depth", lllite_strength=st[0], lllite_end=st[1], _control_up=up,
                lllite2=P3.LLLITE2, lllite2_strength=st[2], lllite2_end=st[3], _control_up2=up2)


def split_graph(p, base_text, lora_rtext, partner_text, neg, lora_mask, other_mask, w, h, seed):
    """나눠 그리기(--split): LoRA 캐릭터 자리 = LoRA + 그 캐릭터 설명만, 상대 자리 = LoRA 없음 + 상대 설명 (사람 상대는 furry·anthro 뺌).
      처음 base_only 걸음 = LoRA + 전체 글"""
    g = region_graph(p, base_text, lora_rtext, neg, lora_mask, w, h, seed, invert=False)
    g["40"]["inputs"].update({"model": ["11", 0], "positive": ["5", 0]})             # 바깥(처음 걸음) = LoRA + 전체 글
    g["12"] = {"class_type": "CLIPTextEncode", "inputs": {"text": partner_text, "clip": ["2", 0]}}
    g["50"] = {"class_type": "ToBasicPipe", "inputs": {"model": ["1", 0], "clip": ["2", 0], "vae": ["3", 0], "positive": ["12", 0], "negative": ["6", 0]}}
    g["51"] = {"class_type": "KSamplerAdvancedProvider", "inputs": {"cfg": float(p["cfg"]), "sampler_name": SAMPLER, "scheduler": SCHED, "sigma_factor": 1.0, "basic_pipe": ["50", 0]}}
    g["52"] = {"class_type": "LoadImage", "inputs": {"image": other_mask}}
    g["53"] = {"class_type": "ImageToMask", "inputs": {"image": ["52", 0], "channel": "red"}}
    g["54"] = {"class_type": "RegionalPrompt", "inputs": {"mask": ["53", 0], "advanced_sampler": ["51", 0]}}
    g["47"]["inputs"]["regional_prompts2"] = ["54", 0]
    return g


def speed_region(g):
    """    EasyCache 는 안 씀 — RegionalSampler 는 걸음마다 영역별로 따로 그려서 캐시가 영역끼리 섞일 수 있음 (시험 전)"""
    import nk_animatest as T
    if not T.anima_speed().get("ck_attention"):
        return g
    g["18"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": ["1", 0], "attention": "comfy kitchen attention"}}
    for k, n in g.items():
        if k != "18" and n.get("inputs", {}).get("model") == ["1", 0]:
            n["inputs"]["model"] = ["18", 0]
    return g


def lora_region_text(ch, cut, artist):
    drop = {"duo", "solo", "1boy", "1girl", "2boys", "2girls", "furry", "anthro"}
    act = [t.strip() for t in str(cut.get("scene", "")).split(",") if t.strip() and t.strip().lower() not in drop]
    pos = next((str(r.get("pos", "")) for r, c2 in (cut.get("_roles") or []) if c2 and c2.get("anima_lora")), "")
    t = lora_text(ch, cut, artist)
    head, desc = t.split(". ", 1)
    extra = ", ".join(x for x in (", ".join(act), pos) if x)
    return "%s%s. %s" % (head, (", " + extra) if extra else "", desc)


def partner_text(text, cut, conti):
    """상대가 사람(캐릭터 파일 태그에 furry·anthro 없음)이면 머리말의 'furry, anthro, ' 뺌"""
    others = [ch for r, ch in (cut.get("_roles") or []) if ch and not ch.get("anima_lora")]
    human = others and all(not any(w in str(ch.get(k, "")) for w in ("furry", "anthro") for k in ("tags_short", "tags_full")) for ch in others)
    return text.replace("furry, anthro, ", "", 1) if human else text


def lora_text(ch, cut, artist):
    """영역 글 = 캐릭터 특징만 (구도·각도 말은 기준 글이 맡음, Civitai 32568). 뒷모습이면 anima_back, 가까운 컷이면 윗몸 설명"""
    import nk_animacut as A, nk_webtoon as W
    if A.is_back(cut) and ch.get("anima_back"):
        d = ch["anima_back"]
    elif str(cut.get("shot")) in ("face", "detail", "waist", "eyes", "hands"):
        d = ch.get("anima_upper") or ch.get("anima_lora_desc")
    else:
        d = ch.get("anima_lora_desc") or ch["anima"]
    head = ", ".join(x for x in ("masterpiece, best quality, score_7, safe", ("@" + artist.lstrip("@")) if artist else "", W.head_tags(ch)) if x)
    return "%s. %s." % (head, d)


SAME_AS_LORA = 0.6
COVERED_WARN = 0.8


def partner_words(ch):
    """상대를 SAM3 로 찾을 짧은 명사: 캐릭터 파일 sam_find > 태그 1girl/1boy > 동물 종 > furry > person"""
    out = [str(ch["sam_find"])] if ch.get("sam_find") else []
    tags = [t.strip().lower() for t in str(ch.get("tags_short", "")).split(",")]
    out += [w for t, w in (("1girl", "girl"), ("1boy", "boy")) if t in tags]
    out += [t for t in ("goat", "dog", "wolf", "fox", "rabbit", "bear", "cat", "dragon", "bird", "lizard") if t in tags]
    out += ["furry creature"] if "furry" in tags else []
    return list(dict.fromkeys(out + ["person"]))


def overlap_stats(lmask, part):
    ps, inter = int(part.sum()), int((lmask & part).sum())
    union = int((lmask | part).sum())
    return {"cover": round(float(part.mean()), 4), "iou": round(inter / union, 4) if union else 0.0,
            "covered": round(inter / ps, 4) if ps else None}


def pick_partner(lmask, parts):
    best = None
    for i, pm in enumerate(parts):
        st = overlap_stats(lmask, pm)
        if st["cover"] < 0.01 or st["iou"] >= SAME_AS_LORA:
            continue
        if best is None or st["cover"] > best[1]["cover"]:
            best = (i, st)
    return best


def find_partner(nk, kit, cfg, to, nm, bp, lmask, partner_ch, run="regionlora_partner"):
    """-> (상대 틀 bool, 말, 통계) 또는 (None, None, None)"""
    import numpy as np, nk_sam
    from PIL import Image
    for fw in partner_words(partner_ch):
        got = nk_sam.segment(nk, kit, cfg, to, [(nm, bp, fw + ":3")], 0.4, run=run, individual=True)
        parts = [np.asarray(Image.open(p).convert("L").resize((lmask.shape[1], lmask.shape[0]))) > 127
                 for p in sorted(got.get((nm, fw + ":3")) or [])]
        b = pick_partner(lmask, parts)
        if b:
            return parts[b[0]], fw, b[1]
    return None, None, None


def mask_check(nk, kit, args):
    """    결과: episodes/<ep>/maskcheck.json"""
    import numpy as np
    from PIL import Image
    import nk_webtoon as W, nk_sam
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    ed = W.ep_dir(kit, args.ep)
    ids = [int(x) for x in args.cuts] or [int(c["id"]) for c in conti["cuts"]]
    od = os.path.join(os.environ.get("NK_HOME") or kit, "runs", "regtest", "maskcheck")
    os.makedirs(od, exist_ok=True)
    out = {}
    for c in [c for c in conti["cuts"] if int(c["id"]) in ids and c.get("_roles")]:
        nm = "cut%02d" % int(c["id"])
        bp, mp = os.path.join(ed, "cuts_base", nm + ".png"), os.path.join(ed, "cuts_base", nm + "_mask.png")
        others = [ch for r, ch in c["_roles"] if str(r.get("char")) != args.who]
        if not (os.path.exists(bp) and os.path.exists(mp) and others):
            print("[skip] %s: no base/mask/partner" % nm); continue
        base = Image.open(bp).convert("RGB")
        lmask = np.asarray(Image.open(mp).convert("L").resize(base.size)) > 127
        rows = []
        for fw in partner_words(others[0]):
            if args.dry:
                print("[dry] %s partner %s word '%s:3'" % (nm, others[0].get("_key"), fw)); continue
            got = nk_sam.segment(nk, kit, cfg, args.ep, [(nm, bp, fw + ":3")], 0.4, run="maskcheck", individual=True)
            for i, p in enumerate(sorted(got.get((nm, fw + ":3")) or [])):
                pm = np.asarray(Image.open(p).convert("L").resize(base.size)) > 127
                rows.append(dict(overlap_stats(lmask, pm), word=fw, i=i, file=p))
        if args.dry:
            continue
        pick = None
        for fw in partner_words(others[0]):                 # 실제 흐름과 같은 고르기: 말 순서대로, 첫 번째로 상대를 찾은 말
            cand = [r for r in rows if r["word"] == fw and r["cover"] >= 0.01 and r["iou"] < SAME_AS_LORA]
            if cand:
                pick = max(cand, key=lambda r: r["cover"]); break
        out[nm] = {"partner": others[0].get("_key"), "lora_cover": round(float(lmask.mean()), 4), "rows": rows, "pick": pick,
                   "warn": bool(pick and pick["covered"] is not None and pick["covered"] >= COVERED_WARN)}
        a = np.asarray(base).astype(np.float32) * 0.55
        a[lmask] += np.array([110, 0, 0], np.float32)
        if pick:
            pm = np.asarray(Image.open(pick["file"]).convert("L").resize(base.size)) > 127
            a[pm] += np.array([0, 0, 110], np.float32)
            a[pm & lmask] += np.array([90, 150, 0], np.float32)
        Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(os.path.join(od, "%s_%s.jpg" % (args.ep, nm)), quality=88)
        print("   %s %-9s lora %.2f | pick %s | covered %s %s" % (nm, others[0].get("_key"), lmask.mean(),
              (pick or {}).get("word"), (pick or {}).get("covered"), "WARN" if out[nm]["warn"] else ""))
    if not args.dry:
        json.dump(out, open(os.path.join(ed, "maskcheck.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("maskcheck -> %s" % os.path.join(ed, "maskcheck.json"))


def mask_spans(lmask, who, others):
    """저장한 LoRA 캐릭터 마스크에서 실제 좌우 자리 (말풍선 꼬리용: 글자 단계는 콘티가 정한 좌우를 가리키는데
    Anima 는 자리를 마음대로 정함)"""
    import numpy as np
    xs = np.nonzero(np.asarray(lmask).any(axis=0))[0]
    if len(xs) == 0:
        return {}
    w = float(np.asarray(lmask).shape[1])
    cols = np.nonzero(np.asarray(lmask))[1]
    a, b = float(np.percentile(cols, 10)) / w, float(np.percentile(cols, 90)) / w
    out = {who: [round(a, 3), round(b, 3)]}
    if others:
        cx = (a + b) / 2
        pa, pb = (b, 1.0) if cx < 0.5 else (0.0, a)
        if pb - pa < 0.12:
            pa, pb = (0.8, 1.0) if cx < 0.5 else (0.0, 0.2)
        out[str(others[0])] = [round(pa, 3), round(pb, 3)]
    return out


def spans_only(kit, args):
    import numpy as np
    from PIL import Image
    import nk_webtoon as W
    ed = W.ep_dir(kit, args.ep)
    rec_p = os.path.join(ed, "regionlora.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    conti = yaml_load(os.path.join(ed, "conti.yaml"))
    for c in _all_cuts(conti):
        roles = [str(r.get("char")) for r in c.get("cast") or []]
        nm = "cut%02d" % int(c["id"])
        mp = os.path.join(ed, "cuts_base", nm + "_mask.png")
        if args.who not in roles or not os.path.exists(mp):
            continue
        sp = mask_spans(np.asarray(Image.open(mp).convert("L")) > 127, args.who, [r for r in roles if r != args.who])
        rec.setdefault(nm, {})["spans"] = sp
        print("   %s spans %s" % (nm, sp))
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def yaml_load(p):
    import yaml
    return yaml.safe_load(open(p, encoding="utf-8"))


def _all_cuts(conti):
    return list(conti.get("cuts") or []) + [c for pg in conti.get("pages") or [] for c in pg.get("cuts") or [] if isinstance(c, dict)]


def run(nk, kit, args):
    import numpy as np
    from PIL import Image, ImageFilter
    import nk_webtoon as W, nk_animacut as A, nk_animatest as T, nk_sam
    if not getattr(args, "who", None):
        cast = W.load_conti(nk, kit, args.ep).get("_cast") or {}
        args.who = next((k for k, c in cast.items() if c and c.get("anima_lora")), None)
        if not args.who:
            print("[ERROR] no cast member with anima_lora in its character file (or pass --who)"); sys.exit(1)
    if getattr(args, "mask_check", False):          # nk_auto 는 자기 인자 묶음(_ns)으로 부름 — 새 인자는 getattr 로
        return mask_check(nk, kit, args)
    if getattr(args, "spans_only", False):
        return spans_only(kit, args)
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    ch = (conti.get("_cast") or {}).get(args.who)
    if not ch or not ch.get("anima_lora"):
        print("[ERROR] %s: no such character or no anima_lora" % args.who); sys.exit(1)
    ids = [int(x) for x in args.cuts] or [int(c["id"]) for c in conti["cuts"]]
    has = lambda c: args.who in [str(r.get("char")) for r in c.get("cast") or []] + [str(c.get("_charkey"))]
    cuts = [c for c in conti["cuts"] if int(c["id"]) in ids and has(c)]
    to = args.to or (args.ep + "r")
    tod = W.ep_dir(kit, to)
    if not args.dry:
        os.makedirs(os.path.join(tod, "cuts"), exist_ok=True); os.makedirs(os.path.join(tod, "cuts_base"), exist_ok=True)
    if not args.dry and not os.path.exists(os.path.join(tod, "conti.yaml")):
        s = open(os.path.join(W.ep_dir(kit, args.ep), "conti.yaml"), encoding="utf-8").read()
        open(os.path.join(tod, "conti.yaml"), "w", encoding="utf-8").write(
            "# %s = %s 를 영역 LoRA 로 (nk ep regionlora): LoRA 는 그 캐릭터 자리에만\n" % (to, args.ep) + re.sub(r"^title: *\"?(.*?)\"?$", lambda m: "title: \"(영역 LoRA) " + m.group(1).replace('"', "") + "\"", s, count=1, flags=re.M))
    p = {"unet": args.unet, "lora": ch["anima_lora"], "lora_strength": float(args.lora_strength or ch.get("anima_lora_strength", 1.0)),
         "steps": int(args.steps), "cfg": float(args.cfg), "base_only": int(args.base_only), "overlap": int(args.overlap)}
    c_ = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    rec_p = os.path.join(tod, "regionlora.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    W.tag_report(kit, conti, [c for c in conti["cuts"] if int(c["id"]) in ids])
    print("regionlora %s -> %s: %d cuts | %s %s steps %d cfg %.1f base_only %d overlap %d | LoRA %s %.2f"
          % (args.ep, to, len(cuts), SAMPLER, SCHED, p["steps"], p["cfg"], p["base_only"], p["overlap"], p["lora"], p["lora_strength"]))
    for c in cuts:
        cid = int(c["id"]); nm = "cut%02d" % cid
        dst = os.path.join(tod, "cuts", nm + ".png")
        if os.path.exists(dst) and not args.redo:
            print("[skip] %s exists" % dst); continue
        s, text = A.cut_text(nk, W, cfg, conti, c, conti.get("artist", ""))
        w, h = [int(x) for x in s["size"].split("x")] if isinstance(s.get("size"), str) else (int(s["width"]), int(s["height"]))
        seed = A.cut_seed(args.ep, c, args.seed)
        ntext = lora_text(ch, c, c.get("anima_artist", conti.get("artist", "")))
        if args.dry:
            print("[dry] %s %dx%d seed %d\n  base: %s\n  lora: %s" % (nm, w, h, seed, text[:200], ntext[:200])); continue
        # ① 기준 그림 (LoRA 없음, RegionalSampler 의 base 와 같은 샘플러·시드)
        bp = os.path.join(tod, "cuts_base", nm + ".png")
        old = rec.get(nm) or {}
        if os.path.exists(bp) and (old.get("text") not in (None, text) or old.get("seed") not in (None, seed)):
            os.remove(bp)
        ctl = pose_control(nk, kit, cfg, conti, to, c, w, h)
        if not os.path.exists(bp):
            v = {"unet": p["unet"], "steps": p["steps"], "cfg": p["cfg"], "sampler": SAMPLER, "scheduler": SCHED,
                 "easycache": False}
            v.update(ctl)
            if args.invert or args.split:           # 거꾸로·나눔: 기준 = LoRA 전체 (RegionalSampler 의 base 와 같은 모델·샘플러·시드)
                v.update(lora=p["lora"], lora_strength=p["lora_strength"])
            g = T.graph(v, text, A.neg_for(conti), w, h, seed, "nk/%s_regionlora/%s_base" % (to, nm))
            outs = c_.wait(c_.queue(g), nm + " base")
            ims = (outs.get("10") or {}).get("images") or []
            if not ims:
                print("[ERROR] %s: no base image" % nm); continue
            c_.fetch(ims[0], bp)
        base = Image.open(bp).convert("RGB")
        m = None
        for fw in list(dict.fromkeys(([args.find] if args.find else []) + W.find_words(ch))):
            got = nk_sam.segment(nk, kit, cfg, to, [(nm, bp, fw + ":1")], 0.4, run="regionlora_sam")
            mps = got.get((nm, fw + ":1"))
            if mps:
                mm = np.asarray(Image.open(sorted(mps)[0]).convert("L").resize(base.size)) > 127
                if 0.02 <= mm.mean() <= 0.6:          # 너무 작으면 못 찾은 것, 너무 크면 둘 다 잡은 것
                    m = mm; print("   %s: mask by '%s' %.1f%%" % (nm, fw, m.mean() * 100)); break
                print("   %s: '%s' mask %.1f%% - try next" % (nm, fw, mm.mean() * 100))
        if m is None:
            print("[skip] %s: no usable character mask" % nm); continue
        k = max(3, int(max(base.size) * GROW)) | 1
        mg = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k))
        ov, fix = None, getattr(args, "overlap_fix", None) or "warn"
        others = [ch2 for r, ch2 in (c.get("_roles") or []) if str(r.get("char")) != args.who]
        if args.split and others and fix != "off":
            try:
                pm, pw, ov = find_partner(nk, kit, cfg, to, nm, bp, np.asarray(mg) > 127, others[0])
            except SystemExit:
                pm, pw, ov = None, None, None; print("[warn] %s: partner SAM failed - no overlap check" % nm)
            if ov:
                thr = COVERED_WARN if getattr(args, "covered_warn", None) is None else float(args.covered_warn)
                ov = dict(ov, word=pw, warn=bool(ov["covered"] is not None and ov["covered"] >= thr))
                print("   %s: partner '%s' %.1f%%, %.0f%% of it inside the %s mask%s" % (nm, pw, ov["cover"] * 100, (ov["covered"] or 0) * 100,
                      args.who, "  [WARN overlap - fix: %s]" % fix if ov["warn"] else ""))
                if ov["warn"] and fix == "subtract":
                    m = m & ~pm
                    mg = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k))
                    mg = Image.fromarray(np.where(pm, 0, np.asarray(mg)).astype(np.uint8))
                elif ov["warn"] and fix == "base":           # 나눠 그리기를 안 함 = LoRA 전체 기준 그림 그대로 (B 방식)
                    shutil.copyfile(bp, dst)
                    rec[nm] = {"base": bp, "mask_cover": round(float(m.mean()), 4), "overlap": ov, "overlap_fix": "base", "text": text,
                               "seed": seed, "settings": p, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
                    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    print("   %s -> %s (overlap: kept the LoRA-everywhere base)" % (nm, dst)); continue
        if args.split:
            mo = Image.fromarray(255 - np.asarray(mg))
            mop = os.path.join(tod, "cuts_base", nm + "_mask_other.png"); mo.convert("RGB").save(mop)
            up_o = W._upload_input(nk, cfg, mop, "%s_regionlora_%s_mask_other.png" % (to, nm), False)
        if args.invert:
            mg = Image.fromarray(255 - np.asarray(mg))
        mp = os.path.join(tod, "cuts_base", nm + "_mask.png")
        mg.convert("RGB").save(mp)
        up = W._upload_input(nk, cfg, mp, "%s_regionlora_%s_mask.png" % (to, nm), False)
        # ③ 영역 LoRA
        if args.split:
            art = c.get("anima_artist", conti.get("artist", ""))
            g = apply_control(split_graph(p, text, lora_region_text(ch, c, art), partner_text(text, c, conti), A.NEG, up, up_o, w, h, seed), ctl)
        else:
            g = apply_control(region_graph(p, text, ntext, A.NEG, up, w, h, seed, args.invert), ctl)
        g = speed_region(g)
        t0 = time.time()
        outs = c_.wait(c_.queue(g), nm)
        ims = (outs.get("10") or {}).get("images") or []
        if not ims:
            print("[ERROR] %s: no image" % nm); continue
        c_.fetch(ims[0], dst)
        rec[nm] = {"base": bp, "mask": mp, "mask_cover": round(float(m.mean()), 4), "overlap": ov,
                   "overlap_fix": fix if ov and ov.get("warn") else None, "text": text, "lora_text": ntext, "seed": seed,
                   "settings": p, "sampler": SAMPLER, "scheduler": SCHED, "secs": round(time.time() - t0, 1), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "spans": mask_spans(m, args.who, [str(r.get("char")) for r, _ in (c.get("_roles") or []) if str(r.get("char")) != args.who])}
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("   %s -> %s (%.0f s, mask %.1f%%)" % (nm, dst, time.time() - t0, m.mean() * 100))


def add_parser(esub, nk, kit):
    a = esub.add_parser("regionlora", help="two-character cut: character LoRA only inside that character's area (Impact RegionalSampler)")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.add_argument("--who", help="cast name of the LoRA character (default: the one whose character file has anima_lora)")
    a.add_argument("--find", help="SAM3 word for that character's body (default: anima_find/sam_body in the character file, else its species tag)")
    a.add_argument("--to")
    a.add_argument("--unet", default="anima-base-v1.0.safetensors")
    a.add_argument("--steps", default="32"); a.add_argument("--cfg", default="5.0"); a.add_argument("--base-only", dest="base_only", default="8")
    a.add_argument("--overlap", default="10"); a.add_argument("--lora-strength", dest="lora_strength")
    a.add_argument("--seed", default="500"); a.add_argument("--redo", action="store_true"); a.add_argument("--dry", action="store_true")
    a.add_argument("--split", action="store_true", help="like --invert, but the character area keeps its LoRA with ONLY its own description (no partner clothes words) and the partner area drops furry/anthro for human partners")
    a.add_argument("--invert", action="store_true", help="LoRA everywhere first, then redraw everything OUTSIDE the character without LoRA (keeps the LoRA character, cleans the partner)")
    a.add_argument("--overlap-fix", dest="overlap_fix", choices=["warn", "subtract", "base", "off"], default="warn",
                   help="when the character mask covers the partner (piggyback-like): warn only (default) / subtract the partner from the mask / keep the LoRA-everywhere base / no check")
    a.add_argument("--covered-warn", dest="covered_warn", type=float, default=None,
                   help="overlap threshold instead of COVERED_WARN (0.8); 0 = apply --overlap-fix to every two-person cut (e.g. subtract the partner's body, incl. a held hand, from the character mask)")
    a.add_argument("--spans-only", dest="spans_only", action="store_true",
                   help="no drawing - write each character's real left/right place (from the saved mask) to regionlora.json for speech bubble tails")
    a.add_argument("--mask-check", dest="mask_check", action="store_true", help="no drawing - find the partner with SAM on existing cuts_base and measure how much of the partner the character mask covers")
    a.set_defaults(func=lambda x: run(nk, kit, x))
