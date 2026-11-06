# -*- coding: utf-8 -*-
"""한 컷을 글로 고치기

    태그로 다시 그리기(fix)는 NoobAI가 그 단어를 약하게 알면 안 됨. Qwen 편집은 문장에 적힌 것을 그려 넣음 (propfix·restyle 에서 배움).
사용: nk ep edit <ep> <컷> "Make the cookies burnt black with smoke" [--seed 81] [--tries 2]
        -> 후보만 (최종본 그대로): episodes/<ep>/cuts_edit/cand/cutNN_sSEED.png + cutNN_cmp.png (전 | 후보들, 바뀐 정도)
      nk ep edit <ep> --use 9=81   (후보를 최종본으로, 원래 그림은 cuts_edit/orig/) / --use 9=0 (되돌림)
      그다음 nk ep auto <ep> --from restyle (바뀐 컷만 그림체·말풍선 다시)
문장 요령 (propfix·restyle 에서 배운 것): 바꿀 것만 구체적으로. 바꾸면 안 되는 것은 물건 이름 없이 '인물·구도·배경·빛은 그대로'."""
import os
import sys
import json

KEEP = " Keep the characters, the faces, the composition, the art style, the background and the lighting exactly the same."
KEEP_OBJ = " Keep the composition, the art style, the background and the lighting exactly the same. Do not add any people, animals or characters."
MAX_CHANGE = 35.0        # nk_propfix 와 같은 잼: 이보다 많이 바뀌면 '그림 전체를 새로 그림' 경고

# 어떻게: 태그 판별기로 고치기 전·후를 잼. 그 컷 캐릭터의 외형 태그(tags_full+short, 색 뗀 명사 포함)·소품 태그가
#     전 >= HAD 인데 후 < LOST = 'lost' / 캐릭터 금지 태그·인원 태그가 전 < 0.3 인데 후 >= GAIN = 'gained' -> 깨끗하지 않음.
HAD, LOST, GAIN = 0.5, 0.25, 0.5
PEOPLE_GAIN = {0: "1boy|1girl|2boys|multiple_boys|anthro|furry|male_focus",       # 사람 없는 컷에 사람이 생김
               1: "multiple_boys|multiple_girls|2boys|2girls|duo|group",          # 혼자 컷에 한 명 더
               2: "3boys|3girls|group"}


def _tag_names(text):
    """'(red plaid scarf:1.2), round glasses' -> ['red_plaid_scarf', 'scarf', 'round_glasses', 'glasses']"""
    import re
    import nk_plan
    out = []
    for t in str(text or "").replace("\n", " ").split(","):
        t = re.sub(r"[()]", "", t).split(":")[0].strip()
        if not t:
            continue
        for x in nk_plan._prop_qa_tag(t).split("|"):
            if x and x not in out:
                out.append(x)
    return out


def _cut_chars(ct):
    if ct is None:
        return []
    if ct.get("_roles"):
        return [ch for _, ch in ct["_roles"]]
    return [ct["_char"]] if ct.get("_char") else []


def design_check(kit, conti, ct, before, after, text=""):
    """-> {"lost": [...], "gained": [...], "scores": {tag: [전, 후]}} / 판별기가 없으면 None"""
    import re
    import nk_tagger
    ok, _ = nk_tagger.available(kit)
    if not ok or ct is None:
        return None
    tb, ta = nk_tagger.tags(kit, before) or {}, nk_tagger.tags(kit, after) or {}
    voc = nk_tagger.vocab(kit)
    chars = _cut_chars(ct)
    keep = []
    for ch in chars:
        for x in _tag_names(ch.get("tags_full")) + _tag_names(ch.get("tags_short")):
            if x not in keep:
                keep.append(x)
    words = set(re.findall(r"[a-z]+", str(text).lower()))
    words |= {w[:-1] for w in words if w.endswith("s")}
    pr = ((conti or {}).get("world") or {}).get("props") or {}
    props = ct.get("props") or []
    if isinstance(props, str):
        props = [x.strip() for x in props.split(",") if x.strip()]
    for p in props:
        for x in _tag_names((pr.get(p) or {}).get("tags")):
            if x not in keep and not (set(x.split("_")) & words):
                keep.append(x)
    if not chars:
        keep.append("no_humans")
    gain = []
    for ch in chars:
        gain += [x.strip().replace(" ", "_") for x in str(ch.get("forbid") or "").split(",") if x.strip()]
    gain += PEOPLE_GAIN[min(len(chars), 2)].split("|")
    if voc:
        keep = [x for x in keep if x in voc]
        gain = [x for x in gain if x in voc]
    res = {"lost": [], "gained": [], "scores": {}, "drops": []}
    for x in keep:
        b, a = tb.get(x, 0.0), ta.get(x, 0.0)
        if b - a >= 0.15:
            res["drops"].append([x, round(b, 2), round(a, 2)])
        if b >= HAD and a < LOST:
            res["lost"].append(x); res["scores"][x] = [round(b, 2), round(a, 2)]
    for x in dict.fromkeys(gain):
        b, a = tb.get(x, 0.0), ta.get(x, 0.0)
        if b < 0.3 and a >= GAIN:
            res["gained"].append(x); res["scores"][x] = [round(b, 2), round(a, 2)]
    return res


def _conti_cut(nk, kit, ep, cid):
    import nk_webtoon as W
    try:
        c = W.load_conti(nk, kit, ep)
    except SystemExit:
        return None, None
    return c, next((x for x in c["cuts"] if int(x["id"]) == int(cid)), None)


# 어떻게: 원본과 후보를 흐리게 줄여 비교 -> 차이 큰 곳(PASTE_THR)만 마스크 -> 점 지우기·키우기·구멍 메우기·흐리게 -> 그 부분만 후보, 나머지는 원본 픽셀.
#     고치는 글이 얼굴 얘기가 아니면(FACE_WORDS 없음) SAM3 'head:4' 머리 자리는 원본으로 되돌림.
#     바뀐 곳이 그림의 LOCAL_MAX 넘게 넓으면(비 지우기처럼 그림 전체를 바꾸는 고치기) 붙이지 않고 후보 그대로.
PASTE = True
PASTE_THR, LOCAL_MAX = 0.14, 0.7
FACE_WORDS = ("face", "eye", "eyes", "mouth", "expression", "smile", "smiles", "smiling", "cry", "crying", "tears", "blush", "blushing",
              "pale", "disgust", "disgusted", "angry", "surprised", "sleepy", "yawn", "yawning", "drool", "drooling", "head", "hair",
              "helmet", "hat", "ear", "ears", "glasses", "eyewear", "sweat", "sweatdrop", "looks", "happy", "sad", "grin", "frown", "wink")


def change_mask(src, cand, thr=PASTE_THR, work=512, grow=0.03, feather=0.012):
    """-> (원본 그림, 후보 그림(원본 크기), 흐린 마스크 L, 바뀐 면적 비율)"""
    import numpy as np
    from PIL import Image, ImageFilter
    A0 = Image.open(src).convert("RGB")
    B0 = Image.open(cand).convert("RGB").resize(A0.size, Image.LANCZOS)
    w, h = A0.size
    sc = work / max(w, h)
    ws, hs = max(8, int(w * sc)), max(8, int(h * sc))
    A = np.asarray(A0.resize((ws, hs), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.5)), float) / 255
    B = np.asarray(B0.resize((ws, hs), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.5)), float) / 255
    m = Image.fromarray(((np.abs(A - B).max(axis=2) > thr) * 255).astype("uint8"))
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    k = max(3, int(work * grow) // 2 * 2 + 1)
    m = m.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    area = float(np.asarray(m).mean() / 255)
    M = m.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(max(1, feather * max(w, h))))
    return A0, B0, M, area


def face_edit(text):
    import re
    return bool(set(re.findall(r"[a-z]+", str(text).lower())) & set(FACE_WORDS))


def local_paste(nk, kit, cfg, ep, src, cand, text, out=None):
    """후보를 '바뀐 곳만 + 얼굴은 원본'으로 합성해서 out(기본 = cand 덮어씀, 원래 후보는 _raw.png). -> 정보 dict"""
    import numpy as np
    from PIL import Image, ImageChops, ImageFilter
    A0, B0, M, area = change_mask(src, cand)
    info = {"area": round(area, 3), "faces_kept": 0, "mode": "local"}
    if area > LOCAL_MAX:
        info["mode"] = "global"
        return info
    if not face_edit(text):
        try:
            import nk_compose as C
            blobs = C.sam_blobs(nk, kit, cfg, ep, [src], "head:4", run="paste_heads", size=256).get(src) or []
        except Exception as e:
            print("   (head check failed: %s)" % e); blobs = []
        if blobs:
            hm = np.zeros((256, 256), bool)
            for b in blobs:
                hm |= b
            H = Image.fromarray((hm * 255).astype("uint8")).resize(A0.size, Image.BILINEAR)
            H = H.filter(ImageFilter.MaxFilter(max(3, int(0.02 * max(A0.size)) // 2 * 2 + 1))).filter(
                ImageFilter.GaussianBlur(max(1, 0.01 * max(A0.size))))
            M = ImageChops.multiply(M, ImageChops.invert(H))
            info["faces_kept"] = len(blobs)
    raw = os.path.splitext(cand)[0] + "_raw.png"
    if out is None:
        B0.save(raw); out = cand
    Image.composite(B0, A0, M).save(out)
    return info


def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _dir(W, kit, ep):
    return os.path.join(W.ep_dir(kit, ep), "cuts_edit")


def run_use(W, kit, ep, choices):
    import shutil
    d = _dir(W, kit, ep)
    rec_p = os.path.join(d, "edit.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    for chs in choices:
        cid, sd = [int(x) for x in chs.split("=")]
        f = W._final_file(kit, ep, cid)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        r = rec.get(str(cid)) or {}
        is_edit = bool(r.get("final_md5")) and r.get("final_md5") == _md5(f)
        if sd == 0:
            if not is_edit:
                print("cut %02d: the final is not an edit - nothing to undo" % cid); continue
            shutil.copy(orig, f)
            r.update(use=0, final_md5=None)
        else:
            p = os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, sd))
            if not os.path.exists(p):
                print("[ERROR] no candidate", p); sys.exit(1)
            if not is_edit:                   # 지금 최종본(고치기 전)을 보관
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                shutil.copy(f, orig)
            shutil.copy(p, f)
            r.update(use=sd, final_md5=_md5(f))
        rec[str(cid)] = r
        print("cut %02d -> %s" % (cid, "before the edit" if sd == 0 else "edit seed %d" % sd))
    os.makedirs(d, exist_ok=True)
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("then: nk ep auto %s --from restyle" % ep)


def make_candidates(nk, kit, cfg, ep, cid, text, seeds, dry=False):
    """후보만 만듦 -> [(seed, 경로, 바뀐 정도, 색 쏠림, 격자)] (dry면 []). 기록: cuts_edit/edit.json, 비교 그림 cutNN_cmp.png"""
    import nk_webtoon as W
    import nk_restyle as R
    import nk_backfix
    from PIL import Image, ImageDraw
    d = _dir(W, kit, ep)
    rec_p = os.path.join(d, "edit.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    f = W._final_file(kit, ep, cid)
    if not os.path.exists(f):
        print("[ERROR] no final picture:", f); sys.exit(1)
    orig = os.path.join(d, "orig", "cut%02d.png" % cid)
    r0 = rec.get(str(cid)) or {}
    src = orig if os.path.exists(orig) and r0.get("final_md5") == _md5(f) else f     # 고친 그림을 또 고치지 않게
    w0, h0 = Image.open(src).size
    w, h = R.fit_size(w0, h0)
    keep = KEEP
    conti, ct = _conti_cut(nk, kit, ep, cid)
    if ct is not None and str(ct.get("char", "")).lower() == "none":
        keep = KEEP_OBJ
    full = text.strip().rstrip(".") + "." + keep
    img = W._upload_input(nk, cfg, src, "%s_cut%02d_preedit.png" % (ep, cid), dry)
    jobs = []
    for sd in seeds:
        label = "cut%02d_s%d" % (cid, sd)
        jobs.append({"label": label, "graph": R.graph(img, full, sd, "nk/%s_edit/%s" % (ep, label), w, h, 1.0),
                     "positive": full, "negative": "", "seed": sd,
                     "settings": {"cfg": 1.0, "steps": 8, "width": w, "height": h, "model": R.QWEN["unet"]}})
    print("edit %s cut %d: %s\n  %d seeds (~90 s each), final not changed" % (ep, cid, full, len(seeds)))
    res = nk.run_jobs(cfg, jobs, "%s/edit" % ep, dry)
    if dry:
        return []
    src_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), ep, "edit")
    os.makedirs(os.path.join(d, "cand"), exist_ok=True)
    made, pastes = [], {}
    for r in res:
        im = Image.open(os.path.join(src_dir, r["file"])).convert("RGB").resize((w0, h0), Image.LANCZOS)
        p = os.path.join(d, "cand", r["label"] + ".png")
        im.save(p)
        pz = None
        if PASTE:
            try:
                pz = local_paste(nk, kit, cfg, ep, src, p, text)
                im = Image.open(p).convert("RGB")
                print("   seed %d: changed area %.0f%%%s" % (int(r["seed"]), 100 * pz["area"],
                      " (whole picture - kept as it is)" if pz["mode"] == "global" else
                      (", %d face(s) kept from the original" % pz["faces_kept"]) if pz["faces_kept"] else ""))
            except Exception as e:
                print("   (paste failed: %s)" % e)
        chg = nk_backfix._change(src, p)
        cast = None
        try:
            la, lb = R.lab_mean(Image.open(src)), R.lab_mean(im)
            cast = round(((lb[1] - la[1]) ** 2 + (lb[2] - la[2]) ** 2) ** 0.5, 1)
        except Exception:
            pass
        gs = round(R.grid_score(im), 1)
        try:
            dz = design_check(kit, conti, ct, src, p, text)
        except Exception as e:
            print("   (design check failed: %s)" % e); dz = None
        made.append((int(r["seed"]), p, chg, cast, gs, dz))
        pastes[int(r["seed"])] = pz
        print("[edit] cut %02d seed %d: change %.1f%s%s%s%s" % (cid, int(r["seed"]), chg, " (whole picture redrawn?)" if chg > MAX_CHANGE else "",
                                                              (" color shift %.0f" % cast) if cast is not None and cast >= R.CAST_ON else "",
                                                              (" GRID %.0f" % gs) if gs >= R.GRID_ON else "", _dz_text(dz)))
    rec[str(cid)] = dict(r0, text=text, seeds=[m[0] for m in made],
                         checks={str(m[0]): {"change": m[2], "color": m[3], "grid": m[4],
                                             "lost": (m[5] or {}).get("lost"), "gained": (m[5] or {}).get("gained"),
                                             "paste": pastes.get(m[0])} for m in made})
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    H = 560
    tiles = [("before", src)] + [("s%d (change %.0f)" % (m[0], m[2]), m[1]) for m in made]
    ims = [(lb, Image.open(q).convert("RGB")) for lb, q in tiles]
    ims = [(lb, im.resize((int(im.width * H / im.height), H))) for lb, im in ims]
    sheet = Image.new("RGB", (sum(i.width for _, i in ims) + 10 * (len(ims) - 1), H + 24), "white")
    dr = ImageDraw.Draw(sheet)
    x = 0
    for lb, im in ims:
        sheet.paste(im, (x, 24)); dr.text((x + 4, 6), lb, fill="black"); x += im.width + 10
    sheet.save(os.path.join(d, "cut%02d_cmp.png" % cid))
    return made


def _dz_text(dz):
    if not dz or not (dz["lost"] or dz["gained"]):
        return ""
    return "".join([" LOST %s" % ",".join("%s %.2f->%.2f" % (x, *dz["scores"][x]) for x in dz["lost"])] if dz["lost"] else []) + \
        "".join([" GAINED %s" % ",".join("%s %.2f->%.2f" % (x, *dz["scores"][x]) for x in dz["gained"])] if dz["gained"] else [])


def clean(made_item):
    """후보가 쓸 만한가 (바뀐 정도·색 쏠림·격자·디자인 지킴)"""
    import nk_restyle as R
    _, _, chg, cast, gs = made_item[:5]
    dz = made_item[5] if len(made_item) > 5 else None
    return (chg <= MAX_CHANGE and (cast is None or cast < R.CAST_ON) and gs < R.GRID_ON
            and not (dz and (dz["lost"] or dz["gained"])))


def run_recheck(nk, kit, ep, cuts=None):
    """이미 만든 후보(cuts_edit/cand/cutNN_s*.png)를 디자인 지킴 검사로 다시 잼 (검사 기준을 정할 때 쓰는 시험용, 최종본 안 바꿈)"""
    import glob
    import re
    import nk_webtoon as W
    import nk_backfix
    d = _dir(W, kit, ep)
    rec_p = os.path.join(d, "edit.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    conti = W.load_conti(nk, kit, ep)
    files = sorted(glob.glob(os.path.join(d, "cand", "cut*_s*.png")))
    byc = {}
    for p in files:
        m = re.match(r"cut(\d+)_s(\d+)\.png$", os.path.basename(p))
        if m:
            byc.setdefault(int(m.group(1)), []).append((int(m.group(2)), p))
    for cid in sorted(byc):
        if cuts and cid not in cuts:
            continue
        ct = next((x for x in conti["cuts"] if int(x["id"]) == cid), None)
        f = W._final_file(kit, ep, cid)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        r0 = rec.get(str(cid)) or {}
        src = orig if os.path.exists(orig) and r0.get("final_md5") == _md5(f) else f
        print("cut %02d (%s) text: %s" % (cid, "before = orig" if src == orig else "before = final", r0.get("text")))
        for sd, p in byc[cid]:
            dz = design_check(kit, conti, ct, src, p, r0.get("text", ""))
            print("   s%d change %.1f%s" % (sd, nk_backfix._change(src, p), (_dz_text(dz) or "  clean") if dz else "  (no tagger)"))
            if dz and dz["drops"]:
                print("        drops: %s" % ", ".join("%s %.2f->%.2f" % tuple(x) for x in sorted(dz["drops"], key=lambda y: y[2] - y[1])[:6]))


def run(nk, kit, args):
    import nk_webtoon as W
    if getattr(args, "use", None):
        return run_use(W, kit, args.ep, args.use)
    if getattr(args, "recheck", False):
        return run_recheck(nk, kit, args.ep, [int(args.cut)] if args.cut is not None else None)
    if args.cut is None or not (args.text or "").strip():
        print('[ERROR] nk ep edit <ep> <cut> "what to change"  (or --use 9=81)'); sys.exit(1)
    cfg = nk.load_presets()
    seed = args.seed if args.seed is not None else 81
    seeds = [seed + k for k in range(max(1, int(args.tries or 2)))]
    make_candidates(nk, kit, cfg, args.ep, int(args.cut), args.text, seeds, args.dry)
    if not args.dry:
        print("look: %s\\cut%02d_cmp.png  -> nk ep edit %s --use %d=<seed>" % (_dir(W, kit, args.ep), int(args.cut), args.ep, int(args.cut)))


def add_parser(esub, nk, kit):
    a = esub.add_parser("edit", help='fix one cut by sentence with Qwen-Image-Edit (candidates only), e.g. nk ep edit ep01 9 "Make the cookies burnt black"')
    a.add_argument("ep")
    a.add_argument("cut", nargs="?", type=int)
    a.add_argument("text", nargs="?", help="what to change, in English")
    a.add_argument("--seed", type=int)
    a.add_argument("--tries", type=int, help="candidates (default 2)")
    a.add_argument("--use", nargs="+", help="9=81 use that candidate / 9=0 back to the picture before the edit")
    a.add_argument("--recheck", action="store_true", help="measure existing candidates with the design check again (test, final not changed)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
