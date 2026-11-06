# -*- coding: utf-8 -*-
"""
nk_pose.py - 두 명 컷 O 방식 준비: Anima로 배치 그림 뽑기 + 뼈대(OpenPose) 뽑기

    Anima는 '두 사람을 어디에 어떤 자세로' 는 잘 잡음 -> 그림에서 뼈대만 뽑아 OpenPose ControlNet으로 넘기면
    색·무늬·그림체는 전혀 안 넘어가고 자세·자리만 넘어감. (시험: ComfyUI output/layout_test, docs/conti_rules.md O 방식)

명령:
+ layout.png(한눈에 보기)
     뼈대는 콘티 cast의 side/span 칸마다 한 명씩 찾음 (사람 찾기 AI는 털 캐릭터를 사람으로 못 봐서 칸으로 대신)

뼈대 찾기 모델: DWPose (yzd-v/DWPose, Apache-2.0) models/dwpose/dw-ll_ucoco_384.onnx
  (없으면 이 명령만 안 되고, 뼈대 그림을 직접 만들어 episodes/<ep>/poses/ 에 넣어도 됨)"""
import os, sys, json, math, time

KIT = os.path.dirname(os.path.abspath(__file__))
DW = os.path.join(KIT, "models", "dwpose", "dw-ll_ucoco_384.onnx")


# ------------------------------------------------------------------ 1) Anima 배치 그림
_ANIMA_ARTIST_NOTED = set()


def _cut_prompt(nk, W, cfg, conti, cut):
    import argparse
    wt, wn, _ = W._world_for(conti, cut)
    wt = W._joined(W._camera_tags(cut), wt)
    art = cut.get("artist", conti.get("artist"))
    #   build_settings 가 'unknown preset' 으로 멈춤. Anima 그림엔 설정표의 작가가 안 쓰이고 cut_text 가 '@이름'을 글에 넣음 -> 없으면 설정표 없이
    if art and not nk.artist_known(cfg, art):
        if art not in _ANIMA_ARTIST_NOTED:
            _ANIMA_ARTIST_NOTED.add(art)
            print("[note] 작가 '%s' 는 옛 설정표·태그 사전에 없음 - Anima 는 '@%s' 로 그대로 씀" % (art, art))
        art = None
    ns = argparse.Namespace(preset=art, extra=W._joined(cut.get("extra"), wt),
                            neg=W._joined(cut.get("neg"), wn), lora=None, size=W._gen_size(cut["size"]), rating=None,
                            cfg=None, steps=None, sampler=None, scheduler=None, quality=None, year=None, artist=None,
                            artist_weight=None, artist_position=None, tags=None, strength=None, charlora=None, hires=0,
                            hires_denoise=None, hires_steps=None, hires_method=None, upscale_model=None)
    s = nk.build_settings(cfg, ns)
    if W._is_duo(cut):
        bp, bn, regs = W._duo_parts(nk, cfg, conti, cut, s)
        return s, W._anima_prompt(s, bp, regs, interact="D1" in (conti.get("rules_off") or [])), regs
    char = W._cut_char(None, cut)                 # load_conti가 컷마다 _char를 정해 둠
    an = W._anima_solo(conti, dict(cut, anima=True), char, wt)
    return s, an["text"], None


def _anima_graph(W, s, text, seed, prefix):
    g = {}
    W_, H_ = int(s["width"]), int(s["height"])
    A = W.ANIMA
    g["600"] = {"class_type": "UNETLoader", "inputs": {"unet_name": A["unet"], "weight_dtype": "default"}}
    g["601"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": A["clip"], "type": "lumina2", "device": "default"}}
    g["602"] = {"class_type": "VAELoader", "inputs": {"vae_name": A["vae"]}}
    g["603"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["600", 0], "shift": A["shift"]}}
    g["604"] = {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["601", 0]}}
    g["605"] = {"class_type": "CLIPTextEncode", "inputs": {"text": W.ANIMA_NEG, "clip": ["601", 0]}}
    g["606"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": W_, "height": H_, "batch_size": 1}}
    g["607"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": A["steps"], "cfg": 1.0,
                                                     "sampler_name": A["sampler"], "scheduler": A["scheduler"], "denoise": 1.0,
                                                     "model": ["603", 0], "positive": ["604", 0], "negative": ["605", 0],
                                                     "latent_image": ["606", 0]}}
    g["608"] = {"class_type": "VAEDecode", "inputs": {"samples": ["607", 0], "vae": ["602", 0]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["608", 0]}}
    return g


def layout(nk, kit, args):
    import nk_webtoon as W
    from PIL import Image, ImageDraw
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    out = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "layout")
    os.makedirs(out, exist_ok=True)
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    made = []
    for cid in args.cuts:
        if cid not in cuts:
            print("[ERROR] no cut", cid); sys.exit(1)
        s, text, regs = _cut_prompt(nk, W, cfg, conti, cuts[cid])
        print("\n== cut %d layout (%sx%s)\n  %s" % (cid, s["width"], s["height"], text))
        for k in range(1, int(args.seeds) + 1):
            name = "cut%02d_s%d.png" % (cid, k)
            if args.dry:
                continue
            g = _anima_graph(W, s, text, 1000 * cid + k, "nk/%s_layout/%s" % (args.ep, name[:-4]))
            res = c.wait(c.queue(g), name)
            img = [i for o in res.values() for i in o.get("images", [])][0]
            c.fetch(img, os.path.join(out, name))
            made.append((cid, name))
            print("   saved", os.path.join(out, name))
    if made:
        ims = [Image.open(os.path.join(out, n)).convert("RGB") for _, n in made]
        th = 360
        tiles = [im.resize((int(im.width * th / im.height), th)) for im in ims]
        wsum = max(sum(t.width for t in tiles[i:i + int(args.seeds)]) for i in range(0, len(tiles), int(args.seeds)))
        rows = math.ceil(len(tiles) / int(args.seeds))
        sheet = Image.new("RGB", (wsum, rows * (th + 24)), "white")
        d = ImageDraw.Draw(sheet)
        for i, (t, (cid, n)) in enumerate(zip(tiles, made)):
            r, k = divmod(i, int(args.seeds))
            x = sum(tt.width for tt in tiles[r * int(args.seeds): i])
            sheet.paste(t, (x, r * (th + 24) + 24)); d.text((x + 4, r * (th + 24) + 4), n, fill="black")
        sheet.save(os.path.join(out, "layout.png"))
        print("\nlook: %s  -> pick one per cut, then: nk ep pose %s <cut> <name>" % (os.path.join(out, "layout.png"), args.ep))


ANIMA_LLLITE = {"depth": "anima-lllite-depth-1.safetensors", "regional": "anima-lllite-regional-exp-v3.safetensors",
                "lineart": "anima-lllite-any-test-like-v2.safetensors"}


def _lllite(g, patch, image, strength, end):
    """_anima_graph 그래프의 Anima 모델(603)과 그리기(607) 사이에 AnimaLLLiteApply"""
    g["610"] = {"class_type": "ModelPatchLoader", "inputs": {"name": patch}}
    g["611"] = {"class_type": "LoadImage", "inputs": {"image": image}}
    g["612"] = {"class_type": "AnimaLLLiteApply", "inputs": {"model": ["603", 0], "model_patch": ["610", 0], "image": ["611", 0],
                                                             "strength": float(strength), "start_percent": 0.0, "end_percent": float(end)}}
    g["607"]["inputs"]["model"] = ["612", 0]
    return g


def _control_image(p3, kind, out):
    """3D 폴더 -> 조종 그림 파일 (depth = 그대로, regional = 흰 바탕 + 사람별 색 칸, lineart = 흰 바탕 검은 선)"""
    import numpy as np, cv2
    if kind == "depth":
        return os.path.join(p3, "depth.png")
    if kind == "regional":
        a = cv2.imread(os.path.join(p3, "mask_a.png"), cv2.IMREAD_GRAYSCALE) > 127
        b = cv2.imread(os.path.join(p3, "mask_b.png"), cv2.IMREAD_GRAYSCALE) > 127
        img = np.full(a.shape + (3,), 255, np.uint8)
        img[a] = (60, 60, 230)          # BGR: a = 빨강 계열
        img[b] = (230, 90, 40)          # b = 파랑 계열
        cv2.imwrite(out, img)
        return out
    li = cv2.imread(os.path.join(p3, "lineart.png"), cv2.IMREAD_GRAYSCALE)
    cv2.imwrite(out, 255 - li)
    return out


def layout3d(nk, kit, args):
    """nk ep layout3d <ep> <컷...> --pose3d <dir> --control depth|regional|lineart [--strength 0.6] [--end 1.0] [--seeds 2]
    3D 인형 조종 그림을 붙인 Anima 자리 잡기 그림 + 조종 없는 같은 시드 그림을 나란히 (runs/<ep>/layout3d/<name>/)"""
    import numpy as np, cv2
    import nk_webtoon as W
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    name = args.name or "%s_%s" % (args.control, str(args.strength).replace(".", ""))
    out = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "layout3d", name)
    os.makedirs(out, exist_ok=True)
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    rows = []
    for cid in [int(x) for x in args.cuts]:
        p3 = os.path.join(args.pose3d, "cut%02d" % cid)
        if cid not in cuts or not os.path.isdir(p3):
            print("[skip] cut %d: no cut or no 3D folder %s" % (cid, p3)); continue
        s, text, _ = _cut_prompt(nk, W, cfg, conti, cuts[cid])
        ctrl = _control_image(p3, args.control, os.path.join(out, "cut%02d_%s_in.png" % (cid, args.control)))
        up = W._upload_input(nk, cfg, ctrl, "%s_cut%02d_l3d_%s.png" % (args.ep, cid, args.control), args.dry)
        print("\n== cut %d layout3d %s (strength %s, end %s)\n  %s" % (cid, args.control, args.strength, args.end, text))
        for k in range(1, int(args.seeds) + 1):
            for with_ctrl in (False, True):
                g = _anima_graph(W, s, text, 1000 * cid + k, "nk/%s_layout3d/%s_cut%02d_s%d_%s" % (args.ep, name, cid, k, "c" if with_ctrl else "n"))
                if with_ctrl:
                    _lllite(g, ANIMA_LLLITE[args.control], up, args.strength, args.end)
                fn = "cut%02d_s%d_%s.png" % (cid, k, args.control if with_ctrl else "none")
                if args.dry:
                    print("[dry] %s %d nodes" % (fn, len(g))); continue
                res = c.wait(c.queue(g), fn)
                img = [i for o in res.values() for i in o.get("images", [])][0]
                c.fetch(img, os.path.join(out, fn))
                rows.append((cid, k, with_ctrl, os.path.join(out, fn), ctrl))
    if args.dry or not rows:
        return
    # 한눈에: 컷·시드마다 [조종 그림 | 조종 없음 | 조종 있음]
    H0 = 300
    tiles = []
    for cid, k, wc, p, ctrl in rows:
        if not wc:
            continue
        none = next(r[3] for r in rows if r[0] == cid and r[1] == k and not r[2])
        ims = [cv2.imread(ctrl), cv2.imread(none), cv2.imread(p)]
        ims = [cv2.resize(i, (int(i.shape[1] * H0 / i.shape[0]), H0)) for i in ims]
        tiles.append(np.hstack([np.hstack([i, np.full((H0, 8, 3), 255, np.uint8)]) for i in ims]))
    Wm = max(t.shape[1] for t in tiles)
    sheet = np.vstack([np.hstack([t, np.full((H0, Wm - t.shape[1], 3), 255, np.uint8)]) for t in tiles])
    cv2.imwrite(os.path.join(out, "sheet.png"), sheet)
    print("look: %s (each row: control | no control | with control)" % os.path.join(out, "sheet.png"))


# ------------------------------------------------------------------ 2) 뼈대 (DWPose, CPU)
_SESS = None


DW_MD5 = "5963bb23b9dbeaa037cbd1231dc48426"


def _join_parts():
    """모델이 조각(parts/*.part*)으로 나뉘어 있으면 처음 쓸 때 합침"""
    import hashlib, glob
    parts = sorted(glob.glob(os.path.join(os.path.dirname(DW), "parts", os.path.basename(DW) + ".part*")))
    if os.path.exists(DW) or not parts:
        return
    h = hashlib.md5()
    tmp = DW + ".tmp"
    with open(tmp, "wb") as f:
        for p in parts:
            b = open(p, "rb").read()
            h.update(b); f.write(b)
    if h.hexdigest() != DW_MD5:
        os.remove(tmp)
        print("[ERROR] DWPose parts are broken (md5 %s)" % h.hexdigest()); sys.exit(1)
    os.replace(tmp, DW)
    print("DWPose model assembled from %d parts -> %s" % (len(parts), DW))


def _pose_sess():
    global _SESS
    _join_parts()
    if _SESS is None:
        import onnxruntime as ort
        _SESS = ort.InferenceSession(DW, providers=["CPUExecutionProvider"])
    return _SESS


def pose_one(img, box):
    """img: BGR numpy, box: x0,y0,x1,y1 -> (keypoints 133x2, conf 133)"""
    import numpy as np, cv2
    sess = _pose_sess()
    Wn, Hn = 288, 384
    x0, y0, x1, y1 = box
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    sc = np.array([x1 - x0, y1 - y0]) * 1.25
    ar = Wn / Hn
    sc = np.array([sc[0], sc[0] / ar]) if sc[0] > sc[1] * ar else np.array([sc[1] * ar, sc[1]])
    src = np.float32([c, c + [0, -sc[1] / 2], c + [-sc[0] / 2, -sc[1] / 2]])
    dst = np.float32([[Wn / 2, Hn / 2], [Wn / 2, 0], [0, 0]])
    crop = cv2.warpAffine(img, cv2.getAffineTransform(src, dst), (Wn, Hn), flags=cv2.INTER_LINEAR)
    x = ((crop[:, :, ::-1].astype(np.float32) - [123.675, 116.28, 103.53]) / [58.395, 57.12, 57.375])
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    sx, sy = sess.run(None, {sess.get_inputs()[0].name: x})
    kp = np.stack([sx[0].argmax(1) / 2.0, sy[0].argmax(1) / 2.0], 1)
    conf = np.minimum(sx[0].max(1), sy[0].max(1))
    return kp / [Wn, Hn] * sc + c - sc / 2, conf


_MM = [17, 6, 8, 10, 7, 9, 12, 14, 16, 13, 15, 2, 1, 4, 3]
_OP = [1, 2, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17]
LIMBS = [[2, 3], [2, 6], [3, 4], [4, 5], [6, 7], [7, 8], [2, 9], [9, 10], [10, 11], [2, 12], [12, 13], [13, 14],
         [2, 1], [1, 15], [15, 17], [1, 16], [16, 18]]
COLORS = [[255, 0, 0], [255, 85, 0], [255, 170, 0], [255, 255, 0], [170, 255, 0], [85, 255, 0], [0, 255, 0],
          [0, 255, 85], [0, 255, 170], [0, 255, 255], [0, 170, 255], [0, 85, 255], [0, 0, 255], [85, 0, 255],
          [170, 0, 255], [255, 0, 255], [255, 0, 170], [255, 0, 85]]


def to_openpose(kp, conf):
    import numpy as np
    kp, conf = kp[:17], conf[:17]
    k = np.vstack([kp, kp[[5, 6]].mean(0)]); c = np.append(conf, min(conf[5], conf[6]))
    o, oc = k.copy(), c.copy()
    o[_OP] = k[_MM]; oc[_OP] = c[_MM]
    return o, oc


def draw(h, w, people, thr=0.3, stick=4):
    """OpenPose 표준 그림 (RGB). people: [(18x2, 18)]"""
    import numpy as np, cv2
    cv = np.zeros((h, w, 3), np.uint8)
    for k, c in people:
        for i, (a, b) in enumerate(LIMBS):
            a -= 1; b -= 1
            if c[a] < thr or c[b] < thr:
                continue
            X = [k[a][1], k[b][1]]; Y = [k[a][0], k[b][0]]
            L = math.hypot(X[0] - X[1], Y[0] - Y[1])
            ang = math.degrees(math.atan2(X[0] - X[1], Y[0] - Y[1]))
            poly = cv2.ellipse2Poly((int(sum(Y) / 2), int(sum(X) / 2)), (int(L / 2), stick), int(ang), 0, 360, 1)
            cv2.fillConvexPoly(cv, poly, [int(v * 0.6) for v in COLORS[i]])
        for i in range(18):
            if c[i] >= thr:
                cv2.circle(cv, (int(k[i][0]), int(k[i][1])), 4, COLORS[i], -1)
    return cv


FACE = [0, 14, 15, 16, 17]      # 코·눈·귀 (OpenPose 18점)


def pose_image(path, spans, thr=0.3, back=False):
    """spans: [(a, b)] 가로 비율 칸마다 한 명. 돌려줌: (뼈대 RGB, 겹쳐보기 BGR, 사람별 믿을만한 점 수, people [(18x2, 18)])
    back=True(뒷모습 컷): 코·눈·귀 점을 뺌"""
    import numpy as np, cv2
    img0 = cv2.imread(path)
    H, Wd = img0.shape[:2]
    people = []
    for a, b in spans:
        box = np.array([max(0, (a - 0.02) * Wd), 0, min(Wd, (b + 0.02) * Wd), H])
        best = None
        for g in (1.0, 0.6, 0.45):
            img = img0 if g == 1.0 else np.clip(255 * ((img0 / 255.0) ** g), 0, 255).astype(np.uint8)
            k, c = to_openpose(*pose_one(img, box))
            n = int((c >= thr).sum())
            if best is None or n > best[0]:
                best = (n, k, c)
            if n >= 8:
                break
        k, c = best[1], best[2].copy()
        if back:
            c[FACE] = 0
        people.append((k, c))
    pose = draw(H, Wd, people, thr)
    ov = cv2.addWeighted(img0, 0.45, pose[:, :, ::-1], 1.0, 0)
    return pose, ov, [int((c >= thr).sum()) for _, c in people], people


#   SAM3 사람별 틀의 상자 + 상대만 보이는 곳을 흰색으로 가린 그림으로 DWPose. 클라우드 시험(예시 20장·40명, M3):
#   자기 몸 위 점 226 -> 304 (+35%), 남의 몸에 붙은 점 53 -> 18 (-66%). 단 머리 큰·동물형 체형은 어떤 방법이든 약함 (13/40)
SAM_WORDS = {}   # 캐릭터 파일 이름 -> SAM3 말 (비면 캐릭터 파일의 anima_find·sam_body, 없으면 종 태그). 짧은 명사가 SAM3에 잘 먹힘


def pose_image_masked(img0, spans, masks, thr=0.3, back=False, pad=0.03):
    """masks: [H x W bool 또는 None] spans 순서와 같은 사람 순서. 틀이 없거나 너무 작으면 그 사람만 예전 칸 방식.
    돌려줌: (뼈대 RGB, 사람별 믿을 만한 점 수, people)"""
    import numpy as np
    H, Wd = img0.shape[:2]
    people = []
    for i, (a, b) in enumerate(spans):
        m = masks[i] if i < len(masks) else None
        if m is None or m.sum() < 0.002 * H * Wd:
            box, src = np.array([max(0, (a - 0.02) * Wd), 0, min(Wd, (b + 0.02) * Wd), H]), img0
        else:
            ys, xs = np.nonzero(m)
            box = np.array([max(0, xs.min() - pad * Wd), max(0, ys.min() - pad * H),
                            min(Wd, xs.max() + pad * Wd), min(H, ys.max() + pad * H)])
            other = np.zeros_like(m)
            for j, mj in enumerate(masks):
                if j != i and mj is not None:
                    other |= mj
            src = img0.copy()
            src[other & ~m] = 255                     # 상대만 보이는 곳은 흰색 (겹친 곳은 그대로)
        best = None
        for g in (1.0, 0.6, 0.45):
            im = src if g == 1.0 else np.clip(255 * ((src / 255.0) ** g), 0, 255).astype(np.uint8)
            k, c = to_openpose(*pose_one(im, box))
            n = int((c >= thr).sum())
            if best is None or n > best[0]:
                best = (n, k, c)
            if n >= 8:
                break
        k, c = best[1], best[2].copy()
        if back:
            c[FACE] = 0
        people.append((k, c))
    return draw(H, Wd, people, thr), [int((c >= thr).sum()) for _, c in people], people


def _own_other(people, masks, thr=0.3, grow_px=12):
    """사람마다 (자기 틀 위 점 수, 상대 틀 위 점 수) — 클라우드 시험과 같은 셈 (틀을 조금 넓혀 봄)"""
    import numpy as np, cv2
    ker = np.ones((2 * grow_px + 1, 2 * grow_px + 1), np.uint8)
    gm = [cv2.dilate(m.astype(np.uint8), ker) > 0 if m is not None else None for m in masks]
    out = []
    for i, (k, c) in enumerate(people):
        own = oth = 0
        for (x, y), cc in zip(k, c):
            if cc < thr:
                continue
            xi, yi = int(round(x)), int(round(y))
            for j, m in enumerate(gm):
                if m is None or not (0 <= yi < m.shape[0] and 0 <= xi < m.shape[1]) or not m[yi, xi]:
                    continue
                if j == i:
                    own += 1
                else:
                    oth += 1
        out.append((own, oth))
    return out


def posemask(nk, kit, args):
    """nk ep posemask <ep> <컷...> [--out <새 편>]: 자리 잡기 그림(auto layout 이 고른 것)에서 지금 방식(칸)과 C1(틀)을
    같이 돌려 비교 그림·숫자를 남김. --out 이면 C1 뼈대를 그 편(콘티 복사)의 poses/ 에 저장 = 같은 시드로 다시 그려 볼 때"""
    import numpy as np, cv2, shutil
    from PIL import Image
    import nk_webtoon as W, nk_sam
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    words = dict(SAM_WORDS)
    for part in [x for x in (args.words or "").split(";") if x.strip()]:
        k, _, v = part.partition(":")
        words[k.strip()] = v.strip()
    st = os.path.join(W.ep_dir(kit, args.ep), "auto", "state.json")
    picks = ((json.load(open(st, encoding="utf-8")).get("layout") or {}).get("picks") or {}) if os.path.exists(st) else {}
    lay = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "layout")
    todo, items = [], []
    for cid in [int(x) for x in args.cuts]:
        ct = cuts.get(cid)
        if not ct or not W._is_duo(ct):
            print("[skip] cut %d: not a two-character cut" % cid); continue
        name = (picks.get(str(cid)) or {}).get("image")
        src = os.path.join(lay, name) if name else None
        if not src or not os.path.exists(src):
            print("[skip] cut %d: no layout picture (auto layout picks)" % cid); continue
        roles = [(r, ch) for r, ch in ct["_roles"]]
        spans = [tuple(r["span"]) if r.get("span") else W.SIDES[str(r.get("side", "left"))] for r, _ in roles]
        ws = [words.get(ch.get("name")) or W.find_word(ch) for _, ch in roles]
        todo.append((cid, ct, src, spans, ws))
        for w in ws:
            items.append(("cut%02d_%s" % (cid, w.replace(" ", "_")), src, w))
    if not todo:
        print("[ERROR] nothing to do"); sys.exit(1)
    print("posemask %s: cuts %s, SAM3 words %s" % (args.ep, [t[0] for t in todo], sorted(set(i[2] for i in items))))
    got = nk_sam.segment(nk, kit, cfg, args.ep, items, float(args.threshold), run="posemask", dry=args.dry)
    if args.dry:
        return
    od = os.path.join(W.ep_dir(kit, args.ep), "posemask")
    os.makedirs(od, exist_ok=True)
    rep = {}
    for cid, ct, src, spans, ws in todo:
        img0 = cv2.imread(src)
        H, Wd = img0.shape[:2]
        masks = []
        for w in ws:
            mp = (got.get(("cut%02d_%s" % (cid, w.replace(" ", "_")), w)) or [None])[0]
            masks.append(np.asarray(Image.open(mp).convert("L").resize((Wd, H))) > 127 if mp else None)
        back = str(ct.get("angle", "")) == "back"
        _, _, n_old, p_old = pose_image(src, spans, back=back)
        pz, n_new, p_new = pose_image_masked(img0, spans, masks, back=back)
        oo_old, oo_new = _own_other(p_old, masks), _own_other(p_new, masks)
        rep[cid] = {"words": ws, "mask_area": [round(float(m.mean()), 4) if m is not None else None for m in masks],
                    "points_old": n_old, "points_new": n_new, "own_other_old": oo_old, "own_other_new": oo_new, "layout": src}
        print("cut %d: points %s -> %s | (own, other) %s -> %s | mask %s" % (cid, n_old, n_new, oo_old, oo_new, rep[cid]["mask_area"]))
        # 비교 그림: 틀 색칠 + 예전 뼈대 | 틀 색칠 + C1 뼈대
        base = img0.copy()
        for m, col in zip(masks, ((60, 60, 255), (60, 200, 60))):
            if m is not None:
                base[m] = (base[m] * 0.6 + np.array(col) * 0.4).astype(np.uint8)
        tiles = [cv2.addWeighted(base, 0.55, draw(H, Wd, pp)[:, :, ::-1], 1.0, 0) for pp in (p_old, p_new)]
        for t, lb in zip(tiles, ("now (half boxes) %s" % n_old, "C1 (SAM masks) %s" % n_new)):
            cv2.putText(t, lb, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
        cv2.imwrite(os.path.join(od, "cut%02d_compare.png" % cid), np.hstack([tiles[0], np.full((H, 12, 3), 255, np.uint8), tiles[1]]))
        if args.out:
            dd = os.path.join(W.ep_dir(kit, args.out))
            os.makedirs(os.path.join(dd, "poses"), exist_ok=True)
            for f in ("plan.yaml", "conti.yaml"):
                if not os.path.exists(os.path.join(dd, f)) and os.path.exists(os.path.join(W.ep_dir(kit, args.ep), f)):
                    shutil.copy(os.path.join(W.ep_dir(kit, args.ep), f), os.path.join(dd, f))
            dst = W._pose_file(kit, args.out, cid)
            cv2.imwrite(dst, pz[:, :, ::-1])
            save_kp(dst, Wd, H, spans, p_new)
    json.dump(rep, open(os.path.join(od, "posemask.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("look: %s\\cutNN_compare.png" % od)


def save_kp(dst, W_, H_, spans, people):
    """뼈대 점 좌표를 사람별로 저장 (poses/cutNN_kp.json) -> body_masks가 두 사람 뼈대가 닿아 있어도 사람별로 나눔"""
    import json
    with open(dst[:-4] + "_kp.json", "w", encoding="utf-8") as f:
        json.dump({"W": int(W_), "H": int(H_), "spans": [list(x) for x in spans],
                   "people": [{"k": [[float(a), float(b)] for a, b in k], "c": [float(x) for x in c]} for k, c in people]}, f)


# 점을 확대해서 머리 위(귀 여유)~엉덩이(waist)/무릎(knee)이 컷 높이를 채우게 함. 컷 밖으로 나간 점도 그대로 둠 (팔다리가 컷 밖으로 이어짐)
SHOT_BOTTOM = {"waist": (8, 11), "knee": (9, 12)}     # 이 점들(엉덩이 / 무릎) 중 가장 낮은 것 = 컷 아래 끝


def frame_to_shot(d, shot, thr=0.3, pad=0.04, min_zoom=1.1):
    """save_kp 형식 dict -> (확대한 dict, 배율). 배율이 min_zoom 보다 작으면(이미 맞음) 그대로 (배율 1.0).
    위 끝 = 가장 높은 (눈·귀 - 목~눈 길이 = 귀 끝, 추정) 또는 든 손 - 여유 pad, 아래 끝 = 가장 낮은 엉덩이(무릎), 가로 = 두 사람 가운데"""
    import numpy as np
    W_, H_ = float(d["W"]), float(d["H"])
    tops, bottoms, xs = [], [], []
    for pp in d["people"]:
        k, c = np.array(pp["k"], float), np.array(pp["c"], float)
        ok = c >= thr
        if not ok.any():
            continue
        xs += list(k[ok, 0])
        face = [i for i in (0, 14, 15, 16, 17) if ok[i]]
        if face:
            fy = min(k[i][1] for i in face)
            tops.append(fy - (max(0.0, k[1][1] - fy) if ok[1] else 0.1 * H_))
        tops += [k[i][1] for i in (4, 7) if ok[i]]
        bs = [k[i][1] for i in SHOT_BOTTOM[shot] if ok[i]]
        if bs:
            bottoms.append(max(bs))
    if not tops or not bottoms:
        return d, 1.0
    y0 = max(0.0, min(tops) - pad * H_)
    y1 = min(H_, max(bottoms))
    z = H_ / max(1.0, y1 - y0)
    if z < min_zoom:
        return d, 1.0
    ww = W_ / z
    x0 = min(max(0.0, (min(xs) + max(xs)) / 2.0 - ww / 2.0), W_ - ww)
    out = dict(d, people=[{"k": ((np.array(pp["k"], float) - [x0, y0]) * z).tolist(), "c": list(pp["c"])} for pp in d["people"]])
    out["framed"] = {"shot": shot, "zoom": round(z, 3), "window_xywh": [round(x0, 1), round(y0, 1), round(ww, 1), round(y1 - y0, 1)]}
    return out, z


def frame_pose_file(dst, shot):
    """poses/cutNN.png + cutNN_kp.json 을 frame_to_shot 으로 확대해 덮어씀 (원본은 cutNN_unframed.png / _kp.json 으로 남김).
돌려줌: 배율 (1.0 = 안 바꿈)"""
    import numpy as np, cv2, shutil
    kpf = dst[:-4] + "_kp.json"
    if not os.path.exists(kpf):
        return 1.0
    d = json.load(open(kpf, encoding="utf-8"))
    if d.get("framed"):
        return float(d["framed"].get("zoom", 1.0))
    d2, z = frame_to_shot(d, shot)
    if z == 1.0:
        return 1.0
    shutil.copy(dst, dst[:-4] + "_unframed.png")
    shutil.copy(kpf, dst[:-4] + "_unframed_kp.json")
    W_, H_ = int(d["W"]), int(d["H"])
    ppl = [(np.array(p["k"]), np.array(p["c"])) for p in d2["people"]]
    cv2.imwrite(dst, draw(H_, W_, ppl)[:, :, ::-1])
    save_kp(dst, W_, H_, d2["spans"], ppl)
    j = json.load(open(kpf, encoding="utf-8"))
    j["framed"] = d2["framed"]
    json.dump(j, open(kpf, "w", encoding="utf-8"))
    return z


def span_overflow(d, thr=0.3, overlap=0.06):
    """사람마다 믿을 만한 점의 가로 범위가 자기 칸(span ± overlap) 밖으로 나간 비율 -> [(사람, 왼쪽, 오른쪽)] (0 = 안 나감)"""
    out = []
    for i, (pp, (a, b)) in enumerate(zip(d["people"], d["spans"])):
        xs = [p[0] / float(d["W"]) for p, c in zip(pp["k"], pp["c"]) if c >= thr]
        if xs:
            out.append((i, round(max(0.0, (a - overlap) - min(xs)), 3), round(max(0.0, max(xs) - (b + overlap)), 3)))
    return out


def pose(nk, kit, args):
    import nk_webtoon as W
    _join_parts()
    if not os.path.exists(DW):
        print("[ERROR] no DWPose model: %s\n  (or make the pose image yourself and put it in episodes/%s/poses/cut%02d.png)"
              % (DW, args.ep, args.cut))
        sys.exit(1)
    import cv2
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cut = next((c for c in conti["cuts"] if int(c["id"]) == args.cut), None)
    if cut is None:
        print("[ERROR] no cut", args.cut); sys.exit(1)
    lay = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "layout")
    src = args.image if os.path.exists(args.image) else os.path.join(lay, args.image if args.image.endswith(".png") else args.image + ".png")
    if not os.path.exists(src):
        print("[ERROR] no image", src); sys.exit(1)
    if W._is_duo(cut):
        spans = [tuple(r["span"]) if r.get("span") else W.SIDES[str(r.get("side", "left"))] for r, _ in cut["_roles"]]
    else:
        spans = [(0.0, 1.0)]
    back = str(cut.get("angle", "")) == "back"
    pz, ov, npts, people = pose_image(src, spans, back=back)
    dst = W._pose_file(kit, args.ep, args.cut)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    cv2.imwrite(dst, pz[:, :, ::-1])
    save_kp(dst, pz.shape[1], pz.shape[0], spans, people)
    if back:
        print("back view: nose/eye/ear points removed (no face = seen from behind)")
    chk = os.path.join(lay, "cut%02d_pose_check.png" % args.cut)
    os.makedirs(lay, exist_ok=True)
    cv2.imwrite(chk, ov)
    print("pose saved:", dst)
    print("check (pose over the layout picture):", chk)
    print("points found per person (of 18):", npts)
    if min(npts) < 8:
        print("[WARN] a person has fewer than 8 points - that person's pose will be loose. look at the check picture")


# 원인(추정): 2단계가 '반쪽 직사각형 전체'를 다른 모델로 70~75% 다시 그림 -> 그 직사각형 안 배경까지 바뀌어 세로 경계가 생김.
# 대책: 다시 그리는 곳을 뼈대로 만든 '몸 모양'으로 줄임 -> 배경은 1단계 한 장 그대로.
def person_mask(k, c, h, w, thr=0.3, grow=1.0):
    """OpenPose 18점 -> 몸 모양 마스크 (0~255, 가장자리 부드럽게). 몸통 길이(목~엉덩이)를 기준 크기로 씀"""
    import numpy as np, cv2
    ok = c >= thr
    pts = {i: (float(k[i][0]), float(k[i][1])) for i in range(18) if ok[i]}
    m = np.zeros((h, w), np.uint8)
    if len(pts) < 4:
        return m
    hips = [pts[i] for i in (8, 11) if i in pts]
    neck = pts.get(1)
    if neck and hips:
        mh = np.mean(hips, 0)
        s = float(np.hypot(neck[0] - mh[0], neck[1] - mh[1]))
    else:
        xs = [p[0] for p in pts.values()]; ys = [p[1] for p in pts.values()]
        s = max(max(xs) - min(xs), max(ys) - min(ys)) / 3.0
    s = max(s, 20.0) * grow
    for a, b in LIMBS:
        a -= 1; b -= 1
        if a in pts and b in pts:
            cv2.line(m, tuple(map(int, pts[a])), tuple(map(int, pts[b])), 255, int(max(6, 0.42 * s)))
    body = [pts[i] for i in (1, 2, 5, 8, 11) if i in pts]
    if len(body) >= 3:
        cv2.fillConvexPoly(m, cv2.convexHull(np.array(body, np.int32)), 255)
    head = pts.get(0) or neck
    if head is not None:
        # 고양이 귀까지: 머리 원 + 위쪽으로 늘린 타원
        cx, cy = int(head[0]), int(head[1])
        cv2.ellipse(m, (cx, int(cy - 0.25 * s)), (int(0.55 * s), int(0.8 * s)), 0, 0, 360, 255, -1)
    for i in (4, 7, 10, 13):                     # 손·발 끝은 조금 더 크게
        if i in pts:
            cv2.circle(m, tuple(map(int, pts[i])), int(0.28 * s), 255, -1)
    kd = int(max(3, 0.18 * s)) | 1
    m = cv2.dilate(m, np.ones((kd, kd), np.uint8))
    m = cv2.GaussianBlur(m, (0, 0), max(2.0, 0.08 * s))
    return m


def body_masks(pose_path, spans, W, H, grow=0.055, blur=0.012, cap=1.0, solid=False):
    """spans: [(a, b)] 사람별 가로 비율. 돌려줌: [H x W uint8 마스크] (사람 순서), [사람별 뼈대 픽셀 수]
    뼈대 픽셀 덩어리를 가장 가까운 사람 칸(가운데 x)에 붙이고, 컷 높이의 grow 만큼 부풀린 뒤 흐림"""
    import numpy as np, cv2
    img = cv2.imread(pose_path)
    if img is None:
        raise FileNotFoundError(pose_path)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_NEAREST)
    centers = [(a + b) / 2.0 * W for a, b in spans]
    masks = [np.zeros((H, W), np.uint8) for _ in spans]
    counts = [0] * len(spans)
    kp = pose_path[:-4] + "_kp.json"
    if os.path.exists(kp):
        # 사람별 점 좌표가 있으면 사람마다 따로 그려서 나눔 (뼈대가 서로 닿아도 안 섞임)
        import json
        d = json.load(open(kp, encoding="utf-8"))
        sx, sy = W / float(d["W"]), H / float(d["H"])
        for pp in d["people"]:
            k = np.array(pp["k"], float) * [sx, sy]
            c = np.array(pp["c"], float)
            one = draw(H, W, [(k, c)])
            sk1 = (one.astype(np.int32).sum(2) > 60)
            if not sk1.any():
                continue
            xs = np.nonzero(sk1)[1]
            j = int(np.argmin([abs(xs.mean() - cc) for cc in centers]))
            masks[j][sk1] = 255
            counts[j] += int(sk1.sum())
    else:
        sk = (img.astype(np.int32).sum(2) > 60).astype(np.uint8)
        joined = cv2.dilate(sk, np.ones((7, 7), np.uint8))          # 머리 점·손끝 점을 몸에 이어 붙임
        n, lab, stats, cents = cv2.connectedComponentsWithStats(joined, 8)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < 30:
                continue
            k = int(np.argmin([abs(cents[i][0] - c) for c in centers]))
            part = (lab == i) & (sk > 0)
            masks[k][part] = 255
            counts[k] += int(part.sum())
    grows = list(grow) if isinstance(grow, (list, tuple)) else [grow] * len(masks)
    caps = list(cap) if isinstance(cap, (list, tuple)) else [cap] * len(masks)
    blurs = list(blur) if isinstance(blur, (list, tuple)) else [blur] * len(masks)
    for k, m in enumerate(masks):
        _head_cap(img, m, caps[k])
    solids = list(solid) if isinstance(solid, (list, tuple)) else [solid] * len(masks)
    out = []
    for k, m in enumerate(masks):
        sig = max(2.0, blurs[k] * H)
        r = max(8, int(round(grows[k] * H)))
        if solids[k]:
            # 흐린 가장자리가 안쪽(귀 끝·손끝)을 반투명하게 만들지 않게: 흐림 폭(2σ)만큼 더 넓힌 뒤 흐림 -> 원래 범위는 끝까지 1
            r += int(2 * sig)
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        m = cv2.dilate(m, ker)
        out.append(cv2.GaussianBlur(m, (0, 0), sig))
    return out, counts


def _kp_center(img, part, rgb, tol=40):
    """뼈대 그림에서 점 색(OpenPose 표준 색, 원은 100% 색 / 막대는 60%)으로 그 사람의 점 위치 찾기"""
    import numpy as np
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    hit = part & (abs(r - rgb[0]) < tol) & (abs(g - rgb[1]) < tol) & (abs(b - rgb[2]) < tol)
    ys, xs = np.nonzero(hit)
    if len(xs) < 5:
        return None
    return float(xs.mean()), float(ys.mean())


def _head_cap(img, m, cap):
    """    마스크 밖(배경 프롬프트만 받는 곳)으로 나감 -> 모자가 안 그려질 위험. 목->머리 방향(몸통 방향)으로 몸통 길이 비례 원을 더함.
    얼굴 점을 뺀 뒷모습 뼈대에도 되게 목·엉덩이 점만 씀. cap=0이면 끔"""
    import numpy as np, cv2
    if not cap:
        return
    part = m > 0
    if not part.any():
        return
    part = cv2.dilate(m, np.ones((9, 9), np.uint8)) > 0       # 점 원이 막대 끝에 붙어 있어서 조금 넓혀서 찾음
    neck = _kp_center(img, part, COLORS[1])
    hips = [h for h in (_kp_center(img, part, COLORS[8]), _kp_center(img, part, COLORS[11])) if h]
    if not neck or not hips:
        return
    hx, hy = np.mean([h[0] for h in hips]), np.mean([h[1] for h in hips])
    dx, dy = neck[0] - hx, neck[1] - hy
    T = float(np.hypot(dx, dy))
    if T < 10:
        return
    ux, uy = dx / T, dy / T
    cx, cy = neck[0] + ux * 0.55 * T * cap, neck[1] + uy * 0.55 * T * cap
    rad = int(0.42 * T * cap)
    cv2.circle(m, (int(cx), int(cy)), rad, 255, -1)
    # 귀가 2단계 마스크 가장자리에 걸림) -> 얼굴 점(코·눈·귀)이 있으면 그 점들 둘레에도 원 (귀 끝까지: 목-코 거리 비례)
    face = [q for q in (_kp_center(img, part, COLORS[k]) for k in (0, 14, 15, 16, 17)) if q]
    if face:
        nose = _kp_center(img, part, COLORS[0]) or face[0]
        d = max(float(np.hypot(nose[0] - neck[0], nose[1] - neck[1])), 0.18 * T)
        for k2, (fx, fy) in enumerate(face):
            cv2.circle(m, (int(fx), int(fy)), int(0.95 * d * cap), 255, -1)
        for k in (16, 17):
            q = _kp_center(img, part, COLORS[k])
            if q:
                cv2.circle(m, (int(q[0]), int(q[1])), int(1.35 * d * cap), 255, -1)
