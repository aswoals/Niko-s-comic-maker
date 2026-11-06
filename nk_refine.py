# -*- coding: utf-8 -*-
"""그림 다듬기 시험
다 그린 그림을 NoobAI-XL(v-pred, Illustrious 계열)로 약하게 다시 그림 (img2img). 구도·색은 남기고 몸 모양만 바로잡기를 노림.
사용: nk ep refine <spec.yaml> [--name 이름] [--dry]
  spec.yaml = {items: [{name, image(키트 기준 경로), pos(NoobAI 태그)}], variants: [{name, denoise, steps, cfg, sampler, scheduler}],
               negative: "..."}
결과: runs/refine/<이름>/<item>_<variant>.png + sheet.png (원본 | 변형들)
설정: NoobAI 체크포인트 = presets.yaml checkpoint, euler/normal (v-pred 라 karras 금지)"""
import json, os, sys, time


def graph(cfg, v, img_name, pos, neg, seed, prefix):
    g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": v.get("ckpt") or cfg["checkpoint"]}}}
    g["1"] = {"class_type": "LoadImage", "inputs": {"image": img_name}}
    g["10"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["4", 2]}}
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["4", 1]}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["4", 1]}}
    g["3"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(v.get("steps", 30)), "cfg": float(v.get("cfg", 4.5)),
                                                    "sampler_name": v.get("sampler", "euler"), "scheduler": v.get("scheduler", "normal"),
                                                    "denoise": float(v["denoise"]), "model": ["4", 0], "positive": ["6", 0],
                                                    "negative": ["7", 0], "latent_image": ["10", 0]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


def run(nk, kit, args):
    import yaml
    import nk_webtoon as W
    spec = yaml.safe_load(open(args.spec, encoding="utf-8"))
    cfg = nk.load_presets()
    name = args.name or os.path.splitext(os.path.basename(args.spec))[0]
    od = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), "refine", name)
    os.makedirs(od, exist_ok=True)
    neg = spec.get("negative", "")
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    done = []
    for it in spec["items"]:
        src = os.path.join(kit, it["image"])
        if not os.path.exists(src):
            print("[ERROR] %s: no image %s" % (it["name"], src)); continue
        up = W._upload_input(nk, cfg, src, "refine_%s_%s.png" % (name, it["name"]), args.dry)
        for v in spec["variants"]:
            label = "%s_%s" % (it["name"], v["name"])
            dst = os.path.join(od, label + ".png")
            if os.path.exists(dst) and not args.dry:
                done.append({"item": it["name"], "variant": v["name"], "file": dst, "src": src}); print("[skip] %s" % label); continue
            g = graph(cfg, v, up, it["pos"], neg, int(it.get("seed", 7)), "nk/refine_%s/%s" % (name, label))
            if args.dry:
                print("[dry] %s | denoise %s | %s" % (label, v["denoise"], it["pos"][:150])); continue
            t0 = time.time()
            outs = c.wait(c.queue(g), label)
            ims = (outs.get("9") or {}).get("images") or []
            if not ims:
                print("[ERROR] %s: no image" % label); continue
            c.fetch(ims[0], dst)
            done.append({"item": it["name"], "variant": v["name"], "file": dst, "src": src, "secs": round(time.time() - t0, 1)})
            json.dump({"spec": spec, "done": done}, open(os.path.join(od, "refine.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("   saved %s (%.0f s)" % (dst, time.time() - t0))
    if args.dry or not done:
        return
    from PIL import Image, ImageDraw
    H0, rows = 360, []
    for it in spec["items"]:
        fs = [("original", next((d["src"] for d in done if d["item"] == it["name"]), None))] + \
             [(v["name"], next((d["file"] for d in done if d["item"] == it["name"] and d["variant"] == v["name"]), None)) for v in spec["variants"]]
        tiles = []
        for lab, f in fs:
            if not f:
                continue
            im = Image.open(f).convert("RGB")
            im = im.resize((int(im.width * H0 / im.height), H0))
            t = Image.new("RGB", (im.width, H0 + 22), "white")
            t.paste(im, (0, 22)); ImageDraw.Draw(t).text((4, 4), "%s | %s" % (it["name"], lab), fill="black")
            tiles.append(t)
        if tiles:
            r = Image.new("RGB", (sum(t.width for t in tiles) + 8 * len(tiles), H0 + 22), "white")
            x = 0
            for t in tiles:
                r.paste(t, (x, 0)); x += t.width + 8
            rows.append(r)
    if rows:
        sh = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 8 for r in rows)), "white")
        y = 0
        for r in rows:
            sh.paste(r, (0, y)); y += r.height + 8
        sh.save(os.path.join(od, "sheet.png"))
        print("look: %s" % os.path.join(od, "sheet.png"))


def add_parser(esub, nk, kit):
    a = esub.add_parser("refine", help="TEST: refine finished pictures with NoobAI img2img (anatomy) — runs/refine/<name>")
    a.add_argument("spec"); a.add_argument("--name"); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
