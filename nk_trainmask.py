# -*- coding: utf-8 -*-
"""학습 그림의 '가릴 부위' 찾기 — SAM3로 부위 틀

    Anima로 뽑은 재료 그림(T6b)도 v1이 그린 것이라 가슴·뒤통수·등 무늬는 믿을 수 없음 -> 그 부위는 학습에서 빼고(kohya --masked_loss,
    PNG 알파 = 0 인 곳은 배우지 않음) 몸 비율·자세·팔다리·꼬리만 배우게 함. 무늬 정답은 시트 그림만.
이 명령은 SAM3 틀만 만든다 (부위마다 흑백 png + 훑어보기 모음). 알파 그림 만들기는 틀을 보고 고른 뒤 tools/t6_dataset_v2.py.

사용: nk ep trainmask <그림 폴더> [--prompts "torso:1,head:1,cat:1"] [--threshold 0.4] [--name T6b_material] [--dry]
결과: runs/trainmask/<name>/<그림>__<부위>_00001_.png + masks.json({그림: {부위: 틀 파일}}) + sheet_<부위>.png"""
import os, sys, glob, json


def run(nk, kit, args):
    import nk_sam
    cfg = nk.load_presets()
    src = args.dir if os.path.isabs(args.dir) else os.path.join(kit, args.dir)
    files = sorted(f for f in glob.glob(os.path.join(src, "*.png")) if not os.path.basename(f).startswith("sheet"))
    if not files:
        print("[ERROR] no pictures in %s" % src); sys.exit(1)
    name = args.name or os.path.basename(os.path.normpath(src))
    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
    items = [(os.path.splitext(os.path.basename(f))[0], f, pr) for f in files for pr in prompts]
    print("trainmask %s: %d pictures x %d parts %s, threshold %.2f" % (name, len(files), len(prompts), prompts, args.threshold))
    got = nk_sam.segment(nk, kit, cfg, "trainmask", items, args.threshold, run=name, dry=args.dry)
    if args.dry:
        return
    out = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), "trainmask", name)
    rec = {}
    for (nm, pr), ps in got.items():
        rec.setdefault(nm, {})[pr.split(":")[0]] = sorted(ps)[0] if ps else None
    for nm, f in ((os.path.splitext(os.path.basename(f))[0], f) for f in files):
        rec.setdefault(nm, {})["_src"] = f
    json.dump(rec, open(os.path.join(out, "masks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sheets(rec, [p.split(":")[0] for p in prompts], out)
    print("look: %s" % out)


def sheets(rec, parts, out, H=300):
    """부위마다 모음 그림 (틀을 빨갛게 덮음, 8칸씩)"""
    from PIL import Image, ImageDraw
    import numpy as np
    for part in parts:
        tiles = []
        for nm in sorted(rec):
            im = Image.open(rec[nm]["_src"]).convert("RGB")
            im = im.resize((int(im.width * H / im.height), H))
            ov = np.asarray(im).copy()
            mp = rec[nm].get(part)
            cover = 0.0
            if mp and os.path.exists(mp):
                m = np.asarray(Image.open(mp).convert("L").resize(im.size)) > 127
                cover = float(m.mean())
                ov[m] = (ov[m] * 0.45 + np.array([255, 40, 40]) * 0.55).astype(np.uint8)
            t = Image.new("RGB", (im.width, H + 20), "white")
            t.paste(Image.fromarray(ov), (0, 20))
            ImageDraw.Draw(t).text((3, 3), "%s %.0f%%" % (nm[:28], cover * 100), fill="black")
            tiles.append(t)
        rows = []
        for k in range(0, len(tiles), 8):
            r = Image.new("RGB", (sum(t.width + 6 for t in tiles[k:k + 8]), H + 20), "white")
            x = 0
            for t in tiles[k:k + 8]:
                r.paste(t, (x, 0)); x += t.width + 6
            rows.append(r)
        W = max(r.width for r in rows)
        sh = Image.new("RGB", (W, sum(r.height + 6 for r in rows)), "white")
        y = 0
        for r in rows:
            sh.paste(r, (0, y)); y += r.height + 6
        sh.save(os.path.join(out, "sheet_%s.png" % part))


def add_parser(esub, nk, kit):
    a = esub.add_parser("trainmask", help="TEST: SAM3 part masks for training pictures (masked_loss)")
    a.add_argument("dir"); a.add_argument("--prompts", default="torso:1,head:1,cat:1")
    a.add_argument("--threshold", type=float, default=0.4); a.add_argument("--name"); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
