# -*- coding: utf-8 -*-
"""닿는 두 명 컷: '닿는 곳은 한 번에 같이, 누가 누군지는 나중에 영역별로' 시험

왜: 누끼 레이어는 나중에 그리는 캐릭터가 먼저 그린 캐릭터 옆 '굳은 빈자리'에 끼워 그려져서 닿는 손이 깨짐
 / 업기는 작은 칸에 작게 그려져 망침 (G2 컷9).
    그래서 두 사람을 한 장에 같이 그린 그림(Anima + 3D 인형, 3번 시험 layout3d)을 '모양'의 원본으로 삼고,
    NoobAI가 그 선·깊이를 따라 두 사람을 한 번에 다시 그림 = 닿는 곳이 한 번에 그려짐.
    틀(누가 어느 픽셀)은 3D 인형 mask_a/b (SAM3 노이즈 없음, 가려진 곳까지 앎).

사용: nk ep joint <ep> <컷...> --src <layout3d 폴더 이름, 예: depth_06> --pose3d runs/pose3d/duo1p [--pick 1] [--seed 71]
      [--line 0.45] [--line-end 0.6] [--depth 0.6] [--depth-end 0.8] [--dn 0.9] [--name ...] [--tagfix ...] [--dry]
결과: runs/<ep>/joint/<name>/cutNN_s<seed>_{mb,ld}.png + sheet.png (같이 그린 그림 | 선 | MB 그대로 | MB + 선·깊이)
      바뀐 것 = 선·깊이 조종만 (같은 시드·같은 3D 뼈대·같은 3D 틀)."""
import os, sys, json

LINE_CN = "noob_lineart_anime_fp16.safetensors"      # models/controlnet (확인: ComfyUI-Shared/models/controlnet 목록)
DEPTH_CN = "noob_depth_midas_v11_fp16.safetensors"


def line_image(src, out, lo=60, hi=160):
    """같이 그린 그림 -> 흰 선 / 검은 바탕 (애니 선화 ControlNet 입력 형식). 애니 선화 전처리기 대신 Canny (추정: 비슷하게 먹힘)"""
    import cv2
    g = cv2.cvtColor(cv2.imread(src), cv2.COLOR_BGR2GRAY)
    e = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), lo, hi)
    cv2.imwrite(out, e)
    return out


def masks_3d(p3, W, H, out_dir, grow_region=16, grow_repaint=10):
    """3D 인형 사람 틀 (보이는 픽셀만, 서로 안 겹침) -> [(region 파일, repaint 파일)] 사람 순서 a, b.
    region = 1단계 영역 글 자리 (넓게) / repaint = 2단계 LoRA 다시 그리기 자리 (조금 넓게, 상대가 보이는 곳은 뺌)"""
    import cv2, numpy as np
    ms = []
    for k in ("a", "b"):
        m = cv2.imread(os.path.join(p3, "mask_%s.png" % k), cv2.IMREAD_GRAYSCALE)
        ms.append(cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST) > 127)
    out = []
    for i, m in enumerate(ms):
        other = ms[1 - i]
        reg = cv2.dilate(m.astype(np.uint8) * 255, np.ones((2 * grow_region + 1,) * 2, np.uint8))
        rep = cv2.dilate(m.astype(np.uint8) * 255, np.ones((2 * grow_repaint + 1,) * 2, np.uint8))
        rep[other] = 0
        fr, fp = os.path.join(out_dir, "mask_region_%d.png" % i), os.path.join(out_dir, "mask_repaint_%d.png" % i)
        cv2.imwrite(fr, cv2.merge([reg] * 3)); cv2.imwrite(fp, cv2.merge([rep] * 3))
        out.append((fr, fp))
    return out


def add_cn(g, s, cn_name, image, st, en, base):
    """그래프의 그리기 단계(고해상도 400번대 제외)에 ControlNet 하나를 사슬로 더 걺. 노드 번호 base+0.. (_pose_cn 과 같은 방식)"""
    W, H = int(s["width"]), int(s["height"])
    g[str(base)] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": cn_name}}
    g[str(base + 1)] = {"class_type": "LoadImage", "inputs": {"image": image}}
    g[str(base + 2)] = {"class_type": "ImageScale", "inputs": {"image": [str(base + 1), 0], "upscale_method": "lanczos",
                                                               "width": W, "height": H, "crop": "center"}}
    for k in [n for n, v in list(g.items()) if v["class_type"] == "KSampler" and not (400 <= int(n) < 500)]:
        ks = g[k]["inputs"]
        cn = str(base + 10 + int(k))
        g[cn] = {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ks["positive"], "negative": ks["negative"],
                 "control_net": [str(base), 0], "image": [str(base + 2), 0], "strength": float(st), "start_percent": 0.0,
                 "end_percent": float(en)}}
        ks["positive"] = [cn, 0]
        ks["negative"] = [cn, 1]
    return g


def _pick_src(root, cid, pick):
    """layout3d 폴더에서 조종을 건 그림 (cutNN_s<pick>_<control>.png, none 아닌 것)"""
    if not os.path.isdir(root):
        return None
    fs = sorted(f for f in os.listdir(root) if f.startswith("cut%02d_s%d_" % (cid, pick)) and f.endswith(".png")
                and not f.endswith("_none.png") and not f.endswith("_in.png"))
    return os.path.join(root, fs[0]) if fs else None


def run(nk, kit, args):
    import cv2, numpy as np
    import nk_webtoon as W, nk_regional as R
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    d = conti.get("duo") or {}
    out_root = cfg.get("output_root", os.path.join(kit, "runs"))
    name = args.name or "%s_l%s_d%s" % (args.src, str(args.line).replace(".", ""), str(args.depth).replace(".", ""))
    od = os.path.join(out_root, args.ep, "joint", name)
    os.makedirs(od, exist_ok=True)
    src_root = os.path.join(out_root, args.ep, "layout3d", args.src)
    hires = {"scale": float(args.hires), "denoise": float((cfg.get("defaults") or {}).get("hires_denoise", 0.35)),
             "steps": int((cfg.get("defaults") or {}).get("hires_steps", 20))} if float(args.hires) > 1.0 else None
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    rows, rep = [], {}
    for cid in [int(x) for x in args.cuts]:
        cut = cuts.get(cid)
        p3 = os.path.join(args.pose3d, "cut%02d" % cid)
        src = _pick_src(src_root, cid, int(args.pick))
        if not cut or not cut.get("_roles") or not os.path.isdir(p3) or not src:
            print("[skip] cut %d: two-character cut? %s / 3D folder %s / picture %s" % (cid, bool(cut and cut.get("_roles")), p3, src))
            continue
        s = R._settings(nk, W, cfg, conti, cut)
        bp, bn, regions = W._duo_parts(nk, cfg, conti, cut, s)
        R._tagfix(regions, getattr(args, "tagfix", None))
        Wd, H = int(s["width"]), int(s["height"])
        cd = os.path.join(od, "cut%02d" % cid)
        os.makedirs(cd, exist_ok=True)
        line = line_image(src, os.path.join(cd, "line.png"))
        mf = masks_3d(p3, Wd, H, cd)
        up = lambda p, tag: W._upload_input(nk, cfg, p, "%s_cut%02d_joint_%s.png" % (args.ep, cid, tag), args.dry)
        masks = {"region": [up(a, "reg%d" % i) for i, (a, _) in enumerate(mf)],
                 "repaint": [up(b, "rep%d" % i) for i, (_, b) in enumerate(mf)]}
        pose = up(os.path.join(p3, "openpose.png"), "pose")
        up_line, up_depth = up(line, "line"), up(os.path.join(p3, "depth.png"), "depth")
        mode = "MB%s" % args.dn
        print("\n== cut %d %sx%s %s | source %s" % (cid, Wd, H, " / ".join(r["key"] for r in regions), src))
        for var in ("mb", "ld"):
            label = "cut%02d_s%d_%s" % (cid, int(args.seed), var)
            g, used = W._duo_graph(cfg, s, bp, bn, regions, int(args.seed), "nk/%s_joint/%s" % (args.ep, label), mode, conti,
                                   hires=hires, pose=pose, masks=masks)
            if var == "ld":
                if float(args.line) > 0:
                    add_cn(g, s, LINE_CN, up_line, args.line, args.line_end, 8100)
                if float(args.depth) > 0:
                    add_cn(g, s, DEPTH_CN, up_depth, args.depth, args.depth_end, 8200)
            ks = [(n, v["inputs"]["denoise"]) for n, v in g.items() if v["class_type"] == "KSampler"]
            cns = [v["inputs"]["control_net_name"] for v in g.values() if v["class_type"] == "ControlNetLoader"]
            print("  %s: mode %s | KSampler %s | ControlNet %s | %d nodes" % (label, used, ks, cns, len(g)))
            if args.dry:
                continue
            outs = c.wait(c.queue(g), label)
            ims = (outs.get("9") or {}).get("images") or []
            if not ims:
                print("[ERROR] %s: no image" % label); continue
            dst = os.path.join(od, label + ".png")
            c.fetch(ims[0], dst)
            rows.append((cid, var, dst, src, line))
            print("   saved", dst)
        rep[cid] = {"source": src, "mode": mode, "line": [float(args.line), float(args.line_end)],
                    "depth": [float(args.depth), float(args.depth_end)], "seed": int(args.seed)}
    if args.dry or not rows:
        return
    json.dump(rep, open(os.path.join(od, "joint.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    H0 = 360
    tiles = []
    for cid in sorted(set(r[0] for r in rows)):
        rr = {r[1]: r for r in rows if r[0] == cid}
        if "mb" not in rr or "ld" not in rr:
            continue
        ims = [cv2.imread(rr["ld"][3]), cv2.imread(rr["ld"][4]), cv2.imread(rr["mb"][2]), cv2.imread(rr["ld"][2])]
        ims = [cv2.resize(i, (int(i.shape[1] * H0 / i.shape[0]), H0)) for i in ims]
        tiles.append(np.hstack([np.hstack([i, np.full((H0, 8, 3), 255, np.uint8)]) for i in ims]))
    if tiles:
        Wm = max(t.shape[1] for t in tiles)
        sheet = np.vstack([np.hstack([t, np.full((H0, Wm - t.shape[1], 3), 255, np.uint8)]) for t in tiles])
        cv2.imwrite(os.path.join(od, "sheet.png"), sheet)
        print("look: %s (each row: together picture | line | MB only | MB + line/depth)" % os.path.join(od, "sheet.png"))


def add_parser(esub, nk, kit):
    a = esub.add_parser("joint", help="TEST: draw both together from a joint picture's line/depth (MB + ControlNets), 3D masks")
    a.add_argument("ep"); a.add_argument("cuts", nargs="+")
    a.add_argument("--src", required=True, help="layout3d folder name under runs/<ep>/layout3d/ (e.g. depth_06)")
    a.add_argument("--pose3d", required=True, help="3D doll folder <dir>/cutNN (tools/pose3d)")
    a.add_argument("--pick", default="1", help="which layout3d seed picture (cutNN_s<pick>_<control>.png)")
    a.add_argument("--seed", default="71")
    a.add_argument("--line", default="0.45"); a.add_argument("--line-end", dest="line_end", default="0.6")
    a.add_argument("--depth", default="0.6"); a.add_argument("--depth-end", dest="depth_end", default="0.8")
    a.add_argument("--dn", default="0.9", help="stage-2 LoRA repaint denoise inside the LoRA character's 3D mask (MB)")
    a.add_argument("--hires", default="1.5")
    a.add_argument("--tagfix"); a.add_argument("--name"); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
