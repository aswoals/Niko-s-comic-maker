# -*- coding: utf-8 -*-
"""SAM 3.1 (Meta Segment Anything 3.1) - 글자로 부위를 찾아 마스크로

왜: 얼굴 고치기가 머리를 'DWPose 어깨 두 점 + 짐작'으로 찾음 -> 쪼그린 자세·얼굴 클로즈업에서 실패.
    손 깨짐은 자동으로 찾는 방법 자체가 없음 (표 qa-08: 얼굴·손·귀 깨짐이 가장 치명적).
    SAM3는 "face", "hand" 같은 짧은 명사로 그 부위 모양을 직접 찾음 (Ultralytics 문서: 짧은 명사에 강함, 드문 개념엔 약함).
    ComfyUI 자체 노드라 새로 설치할 노드 없음. 모델 = checkpoints/sam3.1_multiplex_fp16.safetensors
    (1,745,546,848 바이트, nk ep fetch로 받음).
아직 시험 단계: 수인 캐릭터에서도 얼굴·손을 찾는지 먼저 잼 (nk ep samtest).

주의: 글자 뒤 ':N' = 최대 N개 (없으면 1개뿐 -> run_test가 ':4'를 붙임). 결과: 두 명 컷 8장 모두 얼굴·머리 둘 다, 손 대부분.
사용: nk ep samtest <ep> <그림...> [--prompts "face,hand:6,head"] [--threshold 0.3] [--individual]
      그림 = episodes/<ep>/cuts/cutNN.png 이름(cut08) 또는 경로. 결과 = runs/<ep>/samtest/*.png + episodes/<ep>/samtest/<그림>_sheet.png"""
import os
import sys
import json

MODEL = "sam3.1_multiplex_fp16.safetensors"


def graph(img, prompt, threshold, prefix, individual=False):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MODEL}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": prompt}},
        "3": {"class_type": "LoadImage", "inputs": {"image": img}},
        "4": {"class_type": "SAM3_Detect", "inputs": {"model": ["1", 0], "image": ["3", 0], "conditioning": ["2", 0],
                                                      "threshold": float(threshold), "refine_iterations": 2,
                                                      "individual_masks": bool(individual)}},
        "5": {"class_type": "MaskToImage", "inputs": {"mask": ["4", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["5", 0]}},
    }


def _resolve(W, kit, ep, name):
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for p in (os.path.join(W.ep_dir(kit, ep), "cuts", name if name.endswith(".png") else name + ".png"),
              os.path.join(W.ep_dir(kit, ep), name)):
        if os.path.exists(p):
            return p
    return None


def segment(nk, kit, cfg, ep, items, threshold=0.4, run="samtest", dry=False, individual=False):
    """items: [(이름, 그림 경로, 프롬프트)] -> {(이름, 프롬프트): [마스크 png 경로...]} (individual이면 찾은 것마다 한 장)"""
    import nk_webtoon as W
    jobs, keys = [], {}
    up = {}
    for name, path, prompt in items:
        if path not in up:
            up[path] = W._upload_input(nk, cfg, path, "%s_sam_%s.png" % (ep, name), dry)
        label = "%s__%s" % (name, prompt.replace(" ", "_").replace(":", "-").replace(",", "+"))
        keys[label] = (name, prompt)
        jobs.append({"label": label, "graph": graph(up[path], prompt, threshold, "nk/%s_%s/%s" % (ep, run, label), individual),
                     "positive": prompt, "negative": "", "seed": 0,
                     "settings": {"cfg": 0, "steps": 0, "width": 0, "height": 0, "model": MODEL}})
    res = nk.run_jobs(cfg, jobs, "%s/%s" % (ep, run), dry)
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), ep, run)
    out = {}
    for r in res:
        out.setdefault(keys[r["label"]], []).append(os.path.join(out_dir, r["file"]))
    return out


def run_test(nk, kit, args):
    import nk_webtoon as W
    from PIL import Image, ImageDraw
    import numpy as np
    cfg = nk.load_presets()
    prompts = [p.strip() for p in (args.prompts or "face,hand,head").split(",") if p.strip()]
    # ComfyUI SAM3는 ':N'이 없으면 글자마다 1개만 찾음 (comfy/text_encoders/sam3_clip.py _parse_prompts 기본 1).
    prompts = [p if ":" in p else p + ":4" for p in prompts]
    items = []
    for n in args.files:
        p = _resolve(W, kit, args.ep, n)
        if not p:
            print("[skip] not found:", n); continue
        nm = os.path.splitext(os.path.basename(p))[0]
        for pr in prompts:
            items.append((nm, p, pr))
    if not items:
        print("[ERROR] no pictures"); sys.exit(1)
    print("SAM3 test: %d pictures x %d prompts %s, threshold %.2f" % (len(items) // len(prompts), len(prompts), prompts,
                                                                       args.threshold))
    ind = bool(getattr(args, "individual", False))
    got = segment(nk, kit, cfg, args.ep, items, args.threshold, dry=args.dry, individual=ind)
    if args.dry:
        return
    d = os.path.join(W.ep_dir(kit, args.ep), "samtest")
    os.makedirs(d, exist_ok=True)
    rep = {}
    cols = {0: (255, 60, 60), 1: (60, 200, 60), 2: (60, 120, 255), 3: (255, 200, 0), 4: (220, 0, 220)}
    for nm in sorted(set(i[0] for i in items)):
        src = next(i[1] for i in items if i[0] == nm)
        im = Image.open(src).convert("RGB")
        H = 420
        base = im.resize((int(im.width * H / im.height), H))
        tiles = [("picture", base)]
        rep[nm] = {}
        for k, pr in enumerate(prompts):
            mps = got.get((nm, pr))
            if not mps:
                rep[nm][pr] = None; continue
            ov = np.asarray(base).copy()
            covers = []
            # individual: 찾은 것마다 다른 색 (한 장에 여러 개 = 두 명 컷에서 머리 둘을 따로 찾는지)
            for j, mp in enumerate(sorted(mps)):
                m = np.asarray(Image.open(mp).convert("L").resize(base.size)) > 127
                if not m.any():
                    continue
                covers.append(round(float(m.mean()), 4))
                c = np.array(cols[(k + j) % 5])
                ov[m] = (ov[m] * 0.45 + c * 0.55).astype(np.uint8)
            rep[nm][pr] = covers if ind else (covers[0] if covers else 0.0)
            lab = ("%s x%d (%s)" % (pr, len(covers), ", ".join("%.1f%%" % (c * 100) for c in covers))) if ind \
                else "%s (%.1f%%)" % (pr, (covers[0] if covers else 0.0) * 100)
            tiles.append((lab, Image.fromarray(ov)))
        sheet = Image.new("RGB", (sum(t.width for _, t in tiles) + 8 * (len(tiles) - 1), H + 22), "white")
        dr = ImageDraw.Draw(sheet)
        x = 0
        for lb, t in tiles:
            sheet.paste(t, (x, 22)); dr.text((x + 4, 4), lb, fill="black"); x += t.width + 8
        sheet.save(os.path.join(d, "%s_sheet.png" % nm))
        print("%-12s %s" % (nm, "  ".join("%s %s" % (pr, "-" if v is None else
                                                          (("x%d" % len(v)) if isinstance(v, list) else "%.1f%%" % (v * 100)))
                                          for pr, v in rep[nm].items())))
    jp = os.path.join(d, "samtest.json")
    allrep = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {}
    allrep["%s|%s|t%.2f" % (",".join(prompts), "ind" if ind else "one", args.threshold)] = rep   # 시험마다 따로 남김 (덮어쓰지 않게)
    json.dump(allrep, open(jp, "w", encoding="utf-8"), indent=1)
    print("look: %s\\*_sheet.png" % d)
