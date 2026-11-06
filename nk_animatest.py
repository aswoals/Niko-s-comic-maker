# -*- coding: utf-8 -*-
"""Anima를 '제대로' 쓰면 어디까지 되나 — 설정 비교 시험

네가 보여 준 Anima 그림은 늘 같은 그림체에 AI 티가 난다
      — 'Anima는 보조'라는 전제에 묻혀 잊은 건 아닌가". 확인한 것 (확실):
  - 우리 Anima = turbo v1.1, CFG 1, 10단계 (nk_webtoon.ANIMA). README: turbo는 "강한 기본 그림체 + 다양성 줄어듦", 권장은 base/aesthetic 30~50단계 CFG 4~5
  - CFG 1 에서는 부정 프롬프트가 아무 일도 안 함 (CFG 식: 부정 쪽 예측이 빠짐)
  - 작가 태그를 Anima 문장에서 빼 왔음 (_anima_prompt 가 'by ...' 를 버림). Anima 작가 형식은 '@이름' (README) — 한 번도 안 써 봄

사용: nk ep animatest <spec.yaml> [--seeds 1] [--name ...] [--dry]
spec.yaml = {prompts: [{name, text, w, h}], variants
             quality: "...", negative: "..."}
결과: runs/animatest/<name>/<prompt>_<variant>_s<seed>.png + sheet.png (줄 = 글·시드, 칸 = 설정)"""
import os, sys, json

CLIP = "qwen_3_06b_base.safetensors"
VAE = "qwen_image_vae.safetensors"


def anima_speed():
    """presets.yaml 의 anima_speed (없으면 {} = 둘 다 꺼짐)"""
    try:
        import nk
        sp = nk.load_presets().get("anima_speed") or {}
        return sp if isinstance(sp, dict) else {}
    except Exception:
        return {}


def speed_patch(g, model, v):
    """설치·재시작 없음, 켜고 끄기 쉬움.
    v["ck_attention"] = True -> ModelAttentionBackend 'comfy kitchen attention' (INT8 어텐션, 보고 약 1.2~1.5배, 긴 글 노이즈 버그 보고 있음)
    v["easycache"] = True 또는 {reuse_threshold, start_percent, end_percent} -> EasyCache (비슷한 걸음 결과를 다시 씀, 디테일 조금 줄 수 있음)
    둘 다 없으면 그래프 그대로"""
    sp = anima_speed()                     # v 에 값이 있으면 그것 (시험·기준 그림이 끔), 없으면 presets.yaml anima_speed
    ck = v["ck_attention"] if "ck_attention" in v else sp.get("ck_attention")
    ec = v["easycache"] if "easycache" in v else sp.get("easycache")
    if ck:
        g["16"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": model, "attention": "comfy kitchen attention"}}
        model = ["16", 0]
    if ec:
        ec = ec if isinstance(ec, dict) else {}
        g["17"] = {"class_type": "EasyCache", "inputs": {"model": model, "reuse_threshold": float(ec.get("reuse_threshold", 0.2)),
                                                         "start_percent": float(ec.get("start_percent", 0.15)),
                                                         "end_percent": float(ec.get("end_percent", 0.95)), "verbose": False}}
        model = ["17", 0]
    return model


def graph(v, text, neg, w, h, seed, prefix):
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": v["unet"], "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "lumina2", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}}}
    model = ["1", 0]
    if v.get("shift"):
        g["4"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model, "shift": float(v["shift"])}}
        model = ["4", 0]
    if v.get("lora"):
        g["11"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": v["lora"],
                                                                   "strength_model": float(v.get("lora_strength", 1.0))}}
        model = ["11", 0]
    if v.get("lllite") and v.get("_control_up"):   # T4e: Anima LLLite 조종 (3D 인형 색 칸·깊이). 이미지는 run 이 ComfyUI에 올린 이름
        g["12"] = {"class_type": "ModelPatchLoader", "inputs": {"name": v["lllite"]}}
        g["13"] = {"class_type": "LoadImage", "inputs": {"image": v["_control_up"]}}
        g["14"] = {"class_type": "AnimaLLLiteApply", "inputs": {"model": model, "model_patch": ["12", 0], "image": ["13", 0],
                                                                "strength": float(v.get("lllite_strength", 0.6)), "start_percent": 0.0,
                                                                "end_percent": float(v.get("lllite_end", 1.0))}}
        model = ["14", 0]
    if v.get("lllite2") and v.get("_control_up2"):
        g["16a"] = {"class_type": "ModelPatchLoader", "inputs": {"name": v["lllite2"]}}
        g["16b"] = {"class_type": "LoadImage", "inputs": {"image": v["_control_up2"]}}
        g["16c"] = {"class_type": "AnimaLLLiteApply", "inputs": {"model": model, "model_patch": ["16a", 0], "image": ["16b", 0],
                                                                 "strength": float(v.get("lllite2_strength", 0.5)), "start_percent": 0.0,
                                                                 "end_percent": float(v.get("lllite2_end", 1.0))}}
        model = ["16c", 0]
    if v.get("_refs_up"):
        ic = v.get("incontext") or {}
        g["15"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": ic.get("lora", "anima-incontext-character.safetensors"),
                                                                   "strength_model": float(ic.get("lora_strength", 1.0))}}
        lat = None
        for k, up in enumerate(v["_refs_up"]):
            g["5%d" % k] = {"class_type": "LoadImage", "inputs": {"image": up}}
            g["6%d" % k] = {"class_type": "AnimaRefEncode", "inputs": {"vae": ["3", 0], "image": ["5%d" % k, 0], "target_width": int(w), "target_height": int(h)}}
            if lat is None:
                lat = ["6%d" % k, 0]
            else:
                g["7%d" % k] = {"class_type": "AnimaRefLatentBatch", "inputs": {"ref_latent_1": lat, "ref_latent_2": ["6%d" % k, 0], "fit_mode": "pad"}}
                lat = ["7%d" % k, 0]
        g["79"] = {"class_type": "AnimaInContextApply", "inputs": {"model": ["15", 0], "ref_latent": lat, "strength": float(ic.get("strength", 1.0)),
                                                                   "start_percent": 0.0, "end_percent": 1.0, "cond_only": True, "fit_mode": "pad",
                                                                   "ref_timestep": 0.0}}
        model = ["79", 0]
    model = speed_patch(g, model, v)
    g["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["2", 0]}}
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["2", 0]}}
    pos = ["5", 0]
    if v.get("_rmask_l"):
        rl = v["region_lora"]
        g["30"] = {"class_type": "CreateHookLoraModelOnly", "inputs": {"lora_name": rl["lora"], "strength_model": float(rl.get("strength", 1.0))}}
        g["31"] = {"class_type": "LoadImage", "inputs": {"image": v["_rmask_l"]}}
        g["32"] = {"class_type": "ImageToMask", "inputs": {"image": ["31", 0], "channel": "red"}}
        g["33"] = {"class_type": "LoadImage", "inputs": {"image": v["_rmask_r"]}}
        g["34"] = {"class_type": "ImageToMask", "inputs": {"image": ["33", 0], "channel": "red"}}
        lh, rh = (None, ["30", 0]) if rl.get("side", "right") == "right" else (["30", 0], None)
        g["35"] = {"class_type": "ConditioningSetProperties", "inputs": dict({"cond_NEW": ["5", 0], "strength": 1.0, "set_cond_area": "default", "mask": ["32", 0]}, **({"hooks": lh} if lh else {}))}
        g["36"] = {"class_type": "ConditioningSetPropertiesAndCombine", "inputs": dict({"cond": ["35", 0], "cond_NEW": ["5", 0], "strength": 1.0, "set_cond_area": "default",
                                                                                        "mask": ["34", 0]}, **({"hooks": rh} if rh else {}))}
        pos = ["36", 0]
    if v.get("_regions"):
        cur = pos
        for k, (up, rtext) in enumerate(v["_regions"]):
            g["90%d" % k] = {"class_type": "LoadImage", "inputs": {"image": up}}
            g["91%d" % k] = {"class_type": "ImageToMask", "inputs": {"image": ["90%d" % k, 0], "channel": "red"}}
            g["92%d" % k] = {"class_type": "CLIPTextEncode", "inputs": {"text": rtext, "clip": ["2", 0]}}
            g["93%d" % k] = {"class_type": "ConditioningSetMask", "inputs": {"conditioning": ["92%d" % k, 0], "mask": ["91%d" % k, 0],
                                                                         "strength": float(v.get("region_strength", 0.7)), "set_cond_area": "default"}}
            g["94%d" % k] = {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": cur, "conditioning_2": ["93%d" % k, 0]}}
            cur = ["94%d" % k, 0]
        pos = cur
    g["7"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": int(w), "height": int(h), "batch_size": 1}}
    g["8"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(v["steps"]), "cfg": float(v["cfg"]),
                                                   "sampler_name": v["sampler"], "scheduler": v.get("scheduler", "simple"),
                                                   "denoise": 1.0, "model": model, "positive": pos, "negative": ["6", 0],
                                                   "latent_image": ["7", 0]}}
    g["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}}
    last = ["9", 0]
    if v.get("hires"):
        hr = v["hires"]
        g["40"] = {"class_type": "ImageScaleBy", "inputs": {"image": last, "upscale_method": "lanczos", "scale_by": float(hr.get("scale", 1.5))}}
        g["41"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["40", 0], "vae": ["3", 0]}}
        g["42"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(hr.get("steps", v["steps"])), "cfg": float(v["cfg"]),
                                                        "sampler_name": v["sampler"], "scheduler": v.get("scheduler", "simple"),
                                                        "denoise": float(hr.get("denoise", 0.4)), "model": model, "positive": pos,
                                                        "negative": ["6", 0], "latent_image": ["41", 0]}}
        g["43"] = {"class_type": "VAEDecode", "inputs": {"samples": ["42", 0], "vae": ["3", 0]}}
        last = ["43", 0]
    g["10"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": last}}
    return g


def region_masks(nk, cfg, od, name, w, h, rl, dry):
    """왼쪽·오른쪽 틀 (흰 = 그 영역). split = 경계 위치(가로 비율), feather = 경계 부드러움(가로 비율)"""
    import numpy as np
    from PIL import Image
    x = np.linspace(0, 1, w)
    sp, fe = float(rl.get("split", 0.5)), max(1e-3, float(rl.get("feather", 0.1)))
    r = np.clip((x - (sp - fe / 2)) / fe, 0, 1)
    out = {}
    for side, arr in (("l", 1 - r), ("r", r)):
        f = os.path.join(od, "_rmask_%s_%dx%d_%.2f_%.2f.png" % (side, w, h, sp, fe))
        Image.fromarray((np.tile(arr, (h, 1)) * 255).astype(np.uint8)).convert("RGB").save(f)
        if dry:
            out["_rmask_" + side] = "(dry) " + f
        else:
            import nk_webtoon as W
            out["_rmask_" + side] = W._upload_input(nk, cfg, f, "animatest_%s_%s" % (name, os.path.basename(f)), False)
    return out


def full_text(spec, v, p):
    head = ", ".join(x for x in (spec.get("quality", ""), v.get("artist", "")) if x)
    return (head + ", " if head else "") + p["text"]


def run(nk, kit, args):
    import yaml
    spec = yaml.safe_load(open(args.spec, encoding="utf-8"))
    cfg = nk.load_presets()
    name = args.name or os.path.splitext(os.path.basename(args.spec))[0]
    od = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), "animatest", name)
    os.makedirs(od, exist_ok=True)
    seeds = [int(x) for x in str(args.seeds).split(",") if x.strip()]
    neg = spec.get("negative", "")
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    if c:
        have = c._get("/object_info/UNETLoader")["UNETLoader"]["input"]["required"]["unet_name"][0]
        miss = sorted(set(v["unet"] for v in spec["variants"]) - set(have))
        if miss:
            print("[ERROR] ComfyUI doesn't list %s (downloaded? restart needed?)" % miss); sys.exit(1)
    done = []
    resume = bool(spec.get("resume"))      # T6b: 긴 묶음(학습 재료 80장) — 이미 있는 그림은 건너뜀, 기록은 한 장마다 저장
    pseeds = lambda p: [int(p["seed"])] if p.get("seed") is not None else seeds      # 글마다 시드 (없으면 --seeds)
    for p in spec["prompts"]:
        for sd in pseeds(p):
            for v in spec["variants"]:
                label = "%s_%s_s%d" % (p["name"], v["name"], sd)
                text = full_text(spec, v, p)
                if v.get("lllite") and p.get("control", {}).get(v.get("control_kind", "")):
                    # 컷마다 조종 그림 (prompt.control = {regional: 파일, depth: 파일}) -> ComfyUI 입력으로 올림 (한 번만)
                    cp = os.path.join(kit, p["control"][v["control_kind"]])
                    if not args.dry:
                        import nk_webtoon as W
                        v = dict(v, _control_up=W._upload_input(nk, cfg, cp, "animatest_%s_%s_%s.png" % (name, p["name"], v["control_kind"]), False))
                    else:
                        v = dict(v, _control_up="(dry) " + cp)
                if v.get("lllite2") and p.get("control", {}).get(v.get("control_kind2", "")):
                    cp2 = os.path.join(kit, p["control"][v["control_kind2"]])
                    if not args.dry:
                        import nk_webtoon as W
                        v = dict(v, _control_up2=W._upload_input(nk, cfg, cp2, "animatest_%s_%s_%s.png" % (name, p["name"], v["control_kind2"]), False))
                    else:
                        v = dict(v, _control_up2="(dry) " + cp2)
                if v.get("incontext") and p.get("refs"):
                    rp = [os.path.join(kit, r) for r in p["refs"]]
                    if not args.dry:
                        import nk_webtoon as W
                        v = dict(v, _refs_up=[W._upload_input(nk, cfg, f, "animatest_%s_%s_ref%d.png" % (name, p["name"], k), False) for k, f in enumerate(rp)])
                    else:
                        v = dict(v, _refs_up=["(dry) " + f for f in rp])
                if v.get("region_lora"):
                    v = dict(v, **region_masks(nk, cfg, od, name, int(p.get("w", 1024)), int(p.get("h", 1024)), v["region_lora"], args.dry))
                dst = os.path.join(od, label + ".png")
                if resume and os.path.exists(dst) and not args.dry:
                    done.append({"prompt": p["name"], "variant": v["name"], "seed": sd, "file": dst, "secs": 0, "text": text})
                    print("[skip] %s exists" % label); continue
                nv = neg + (", " + v["negative_extra"] if v.get("negative_extra") else "")      # T6a: 변형마다 부정 더하기
                g = graph(v, text, nv, p.get("w", 1024), p.get("h", 1024), sd, "nk/animatest_%s/%s" % (name, label))
                if args.dry:
                    print("[dry] %s | %s %s steps cfg %s %s | %s" % (label, v["unet"], v["steps"], v["cfg"], v["sampler"], text[:160]))
                    continue
                import time
                t0 = time.time()
                outs = c.wait(c.queue(g), label)
                ims = (outs.get("10") or {}).get("images") or []
                if not ims:
                    print("[ERROR] %s: no image" % label); continue
                c.fetch(ims[0], dst)
                done.append({"prompt": p["name"], "variant": v["name"], "seed": sd, "file": dst, "secs": round(time.time() - t0, 1), "text": text})
                if resume:
                    json.dump({"spec": spec, "done": done}, open(os.path.join(od, "animatest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print("   saved %s (%.0f s)" % (dst, time.time() - t0))
    if args.dry or not done:
        return
    json.dump({"spec": spec, "done": done}, open(os.path.join(od, "animatest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from PIL import Image, ImageDraw
    H0 = 360
    rows = []
    if len(spec["variants"]) == 1 and len(done) > 12:      # 변형 하나 + 많은 글(학습 재료) = 8칸씩 줄
        tiles = []
        for d in done:
            im = Image.open(d["file"]).convert("RGB")
            im = im.resize((int(im.width * H0 / im.height), H0))
            t = Image.new("RGB", (im.width, H0 + 22), "white")
            t.paste(im, (0, 22)); ImageDraw.Draw(t).text((4, 4), d["prompt"], fill="black")
            tiles.append(t)
        for k in range(0, len(tiles), 8):
            r = Image.new("RGB", (sum(t.width for t in tiles[k:k + 8]) + 8 * 8, H0 + 22), "white")
            x = 0
            for t in tiles[k:k + 8]:
                r.paste(t, (x, 0)); x += t.width + 8
            rows.append(r)
    for p in ([] if rows else spec["prompts"]):
        for sd in pseeds(p):
            tiles = []
            for v in spec["variants"]:
                f = next((d["file"] for d in done if d["prompt"] == p["name"] and d["variant"] == v["name"] and d["seed"] == sd), None)
                if not f:
                    continue
                im = Image.open(f).convert("RGB")
                im = im.resize((int(im.width * H0 / im.height), H0))
                t = Image.new("RGB", (im.width, H0 + 22), "white")
                t.paste(im, (0, 22)); ImageDraw.Draw(t).text((4, 4), "%s s%d | %s" % (p["name"], sd, v["name"]), fill="black")
                tiles.append(t)
            if tiles:
                r = Image.new("RGB", (sum(t.width for t in tiles) + 8 * len(tiles), H0 + 22), "white")
                x = 0
                for t in tiles:
                    r.paste(t, (x, 0)); x += t.width + 8
                rows.append(r)
    if rows:
        W = max(r.width for r in rows)
        sheet = Image.new("RGB", (W, sum(r.height + 8 for r in rows)), "white")
        y = 0
        for r in rows:
            sheet.paste(r, (0, y)); y += r.height + 8
        sheet.save(os.path.join(od, "sheet.png"))
        print("look: %s" % os.path.join(od, "sheet.png"))


def add_parser(esub, nk, kit):
    a = esub.add_parser("animatest", help="TEST: Anima settings comparison (turbo vs base/aesthetic, @artist, CFG) with known characters")
    a.add_argument("spec"); a.add_argument("--seeds", default="1"); a.add_argument("--name"); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
