# -*- coding: utf-8 -*-
"""
nk_detail.py - Anima 손·발 다시 그리기 시험

가설: 손·발은 그림에서 작게(40~80px) 그려져 모델이 대충 그림 → 그 부분만 넓게 잘라(손 상자 x 1.8, 아카라이브 경험값 — nk_handfix)
      크게(768) 키워 같은 글로 약하게(denoise) 다시 그리고 붙이면 나아짐. 손을 찾는 건 DWPose 전신 133점(손 21점 x 2, 발 6점).
최종본은 안 바꿈: episodes/<편>/detail/cutNN_<부위><번호>_d<세기>.png (원본 | 다시 그린 것) + cutNN_d<세기>.png (붙인 그림)

사용: nk ep detail <편> <컷...> [--den 0.45,0.6] [--parts hands,feet] [--dry]"""
import json
import os
import time

CROP = 1.8           # 부위 상자 긴 변 x 1.8 = 자르는 정사각형
MIN_CROP = 112
SIDE = 768           # 다시 그리는 크기
THR = 0.35
HANDS = [(91, 112), (112, 133)]              # COCO-WholeBody 왼손 91~111, 오른손 112~132
FEET = [((15, 17, 18, 19), "l"), ((16, 20, 21, 22), "r")]   # 발목 + 엄지·새끼발가락·뒤꿈치
WORDS = {"hand": "detailed hands, five fingers, clean fingers, correct hand anatomy",
         "foot": "detailed feet, footwear, correct foot anatomy, both feet on the ground"}
PART_TEXT = {"hand": "close-up of hands only, detailed hands, five fingers on each hand, clean separated fingers, correct hand anatomy",
             "foot": "close-up of feet and shoes only, two feet, footwear, correct foot anatomy, standing on the ground"}
PART_NEG = "people, person, 1girl, 2girls, 1boy, face, head, eyes, hair, miniature, chibi, full body, multiple views, extra fingers, fused fingers, extra digits, extra legs"
CONTEXT = ("holding hands", "hug", "high five", "handshake", "fist bump", "headpat")      # 조각 글에 남길 닿는 동작


def find_parts(img, boxes, parts=("hands", "feet")):
    """BGR 그림 + 사람 칸들 -> [(부위, (x0,y0,x1,y1), 사람 번호)] — 믿을 만한 점이 4개 이상인 손, 발목이 보이는 발"""
    import numpy as np
    import nk_pose
    out = []
    for pi, bx in enumerate(boxes):
        kp, conf = nk_pose.pose_one(img, bx)
        if "hands" in parts:
            for a, b in HANDS:
                ok = conf[a:b] >= THR
                if ok.sum() >= 4:
                    pts = kp[a:b][ok]
                    out.append(("hand", tuple(pts.min(0)) + tuple(pts.max(0)), pi))
        if "feet" in parts:
            for ix, _side in FEET:
                ok = conf[list(ix)] >= THR
                if ok[0] and ok.sum() >= 2:
                    pts = kp[list(ix)][ok]
                    out.append(("foot", tuple(pts.min(0)) + tuple(pts.max(0)), pi))
    return _merge(out)


def _merge(parts):
    """겹치는 같은 부위 상자(맞잡은 두 손 등)는 하나로 — 한 번에 다시 그려야 손이 서로 맞음"""
    res = []
    for kind, b, pi in parts:
        for r in res:
            if r[0] == kind and not (b[2] < r[1][0] or b[0] > r[1][2] or b[3] < r[1][1] or b[1] > r[1][3]):
                r[1] = (min(r[1][0], b[0]), min(r[1][1], b[1]), max(r[1][2], b[2]), max(r[1][3], b[3]))
                break
        else:
            res.append([kind, b, pi])
    return [(k, tuple(b), pi) for k, b, pi in res]


def crop_box(b, W, H):
    """부위 상자 -> 자를 정사각형 (그림 안으로 밀어 넣음)"""
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    s = int(max(MIN_CROP, max(b[2] - b[0], b[3] - b[1]) * CROP))
    s = min(s, W, H)
    x0 = int(min(max(cx - s / 2, 0), W - s))
    y0 = int(min(max(cy - s / 2, 0), H - s))
    return x0, y0, x0 + s, y0 + s


def part_mask(b, cb, side=SIDE):
    """자른 그림 안에서 부위를 덮는 부드러운 타원 틀 (흰 = 다시 그림)"""
    from PIL import Image, ImageDraw, ImageFilter
    s = cb[2] - cb[0]
    k = side / float(s)
    pad = 0.35 * max(b[2] - b[0], b[3] - b[1])
    m = Image.new("L", (side, side), 0)
    ImageDraw.Draw(m).ellipse([(b[0] - pad - cb[0]) * k, (b[1] - pad - cb[1]) * k, (b[2] + pad - cb[0]) * k, (b[3] + pad - cb[1]) * k], fill=255)
    return m.filter(ImageFilter.GaussianBlur(side * 0.03))


def detail_graph(nk_animatest, v, text, neg, seed, prefix, crop_up, mask_up, den):
    """Anima 그림 그래프에서 '빈 화면' 대신 잘라 낸 그림 + 틀 (SetLatentNoiseMask) 로 약하게 다시 그림. 조종(인형·사람별 틀)은 안 씀"""
    v = {k: x for k, x in v.items() if k not in ("lllite", "lllite2", "_control_up", "_control_up2", "_regions", "_refs_up", "hires", "_rmask_l")}
    g = nk_animatest.graph(v, text, neg, SIDE, SIDE, seed, prefix)
    g.pop("7", None)
    g["70"] = {"class_type": "LoadImage", "inputs": {"image": crop_up}}
    g["71"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["70", 0], "vae": ["3", 0]}}
    g["72"] = {"class_type": "LoadImage", "inputs": {"image": mask_up}}
    g["73"] = {"class_type": "ImageToMask", "inputs": {"image": ["72", 0], "channel": "red"}}
    g["74"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["71", 0], "mask": ["73", 0]}}
    g["8"]["inputs"]["latent_image"] = ["74", 0]
    g["8"]["inputs"]["denoise"] = float(den)
    return g


def run(nk, kit, args):
    import cv2
    from PIL import Image
    import nk_webtoon as W
    import nk_animatest
    import nk_pose3d_auto as P3
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    rec = json.load(open(os.path.join(W.ep_dir(kit, args.ep), "animamake.json"), encoding="utf-8"))
    dens = [float(x) for x in str(args.den).split(",")]
    parts = tuple(str(args.parts).split(","))
    od = os.path.join(W.ep_dir(kit, args.ep), "detail" + ("" if args.prompt == "scene" else "_" + args.prompt))
    os.makedirs(od, exist_ok=True)
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    for cid in [int(x) for x in args.cuts]:
        cut = next(ct for ct in conti["cuts"] if int(ct["id"]) == cid)
        r = rec.get(str(cid))
        src = os.path.join(W.ep_dir(kit, args.ep), "cuts", "cut%02d.png" % cid)
        if not r or not os.path.exists(src):
            print("[skip] cut %d: 그림·기록 없음" % cid); continue
        img = cv2.imread(src)
        H, Wd = img.shape[:2]
        n = 2 if cut.get("_roles") else 1
        found = find_parts(img, P3._draft_boxes(img, n), parts)
        print("cut %d: %s" % (cid, ", ".join("%s(%d,%d,%d,%d)" % ((k,) + tuple(int(x) for x in b)) for k, b, _ in found) or "부위 못 찾음"))
        base = Image.open(src).convert("RGB")
        for den in dens:
            out = base.copy()
            for i, (kind, b, _pi) in enumerate(found):
                cb = crop_box(b, Wd, H)
                crop = base.crop(cb).resize((SIDE, SIDE), Image.LANCZOS)
                m = part_mask(b, cb)
                cp = os.path.join(od, "cut%02d_%s%d_crop.png" % (cid, kind, i))
                mp = os.path.join(od, "cut%02d_%s%d_mask.png" % (cid, kind, i))
                crop.save(cp); m.convert("RGB").save(mp)
                if args.prompt == "scene":
                    text, ng = r["text"].rstrip(". ") + ". " + WORDS[kind] + ".", r["negative"]
                else:
                    head = r["text"].split(". ")[0].split(", ")
                    keep = [x for x in head if x.startswith("@") or x in ("masterpiece", "best quality", "score_7", "safe", "anime coloring", "flat color", "lineart")]
                    ctx = [x for x in CONTEXT if x in r["text"]]
                    text = ", ".join(keep + ctx) + ". " + PART_TEXT[kind] + "."
                    ng = r["negative"] + ", " + PART_NEG
                cu = W._upload_input(nk, cfg, cp, "detail_%s_%02d_%s%d.png" % (args.ep, cid, kind, i), args.dry)
                mu = W._upload_input(nk, cfg, mp, "detail_%s_%02d_%s%d_m.png" % (args.ep, cid, kind, i), args.dry)
                g = detail_graph(nk_animatest, r["settings"], text, ng, int(r["seed"]) + 77, "nk/%s_detail/cut%02d" % (args.ep, cid), cu, mu, den)
                if args.dry:
                    print("  [dry] %s %d d%.2f crop %s" % (kind, i, den, cb)); continue
                t0 = time.time()
                ims = (c.wait(c.queue(g), "cut%02d_%s%d" % (cid, kind, i)).get("10") or {}).get("images") or []
                if not ims:
                    print("  [ERROR] %s %d: no image" % (kind, i)); continue
                rp = os.path.join(od, "cut%02d_%s%d_d%.2f_raw.png" % (cid, kind, i, den))
                c.fetch(ims[0], rp)
                new = Image.open(rp).convert("RGB").resize((cb[2] - cb[0], cb[3] - cb[1]), Image.LANCZOS)
                mm = m.resize(new.size, Image.LANCZOS)
                out.paste(new, cb[:2], mm)
                pair = Image.new("RGB", (SIDE * 2 + 8, SIDE), "white")
                pair.paste(crop, (0, 0)); pair.paste(Image.open(rp).convert("RGB"), (SIDE + 8, 0))
                pair.save(os.path.join(od, "cut%02d_%s%d_d%.2f.png" % (cid, kind, i, den)))
                print("  %s %d d%.2f (%.0f s)" % (kind, i, den, time.time() - t0))
            if not args.dry:
                out.save(os.path.join(od, "cut%02d_d%.2f.png" % (cid, den)))


def add_parser(esub, nk, kit):
    a = esub.add_parser("detail", help="Anima 손·발 다시 그리기 시험 — 최종본은 안 바꿈 (episodes/<ep>/detail/)")
    a.add_argument("ep"); a.add_argument("cuts", nargs="+")
    a.add_argument("--den", default="0.45,0.6")
    a.add_argument("--parts", default="hands,feet")
    a.add_argument("--prompt", default="part", choices=["part", "scene"], help="part = 부위만 설명 (기본) / scene = 컷 전체 글 (조각에 작은 사람이 생김)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
