# -*- coding: utf-8 -*-
"""캐릭터 + 소품 컷에 빠진 소품 그려 넣기

왜: 소품만 있는 컷에서는 소품이 잘 나오는데, 캐릭터가 같이 나오는 컷에서는 소품이 자주 빠짐.
    캐릭터 LoRA + 동작 + 소품을 한 번에 그리면 소품이 밀려남 (두 명 컷과 같은 '한 번에 다 그리기' 문제).
어떻게: 두 명 컷(nk_compose)과 같은 원리 - 잘 나온 것은 그대로 두고, Qwen-Image-Edit-2509로 소품만 그려 넣음.
    그림체 입히기(nk_restyle)에서 배운 것: Qwen은 문장에 적힌 물건을 그려 넣음 -> 여기서는 그 성질을 씀.
    바꾸면 안 되는 것은 물건 이름 없이 '인물·자세·배경·빛은 그대로'만 말함.
사용: nk ep propfix <ep> [컷...]   (컷을 안 주면: 사람 + props가 있는 혼자 컷 중 최종본에 소품이 안 보이는 컷)
      -> 후보 2장, 판별기로 소품이 보이고 캐릭터에 없던 것(forbid)이 안 생긴 것을 골라 최종본으로 (원래 최종본은 cuts_propfix/orig/)
      nk ep propfix <ep> --use 6=72 / 6=0 (되돌림)   |  --dry"""
import os
import sys
import json

PROP_MIN = 0.35          # 소품이 '보인다' = 판별기 점수 이 이상 (콘티 qa min과 같음)
#   소품만 들어간 후보 15.1(컷 6)·21.5(컷 9) / 그림 전체를 새로 그린 후보(배경이 단색, 구도 바뀜) 57.7·100.4
#   -> 두 후보 모두 소품 점수 0.99라 점수로는 못 가름. 35 넘으면 불합격, 합격 중에서는 덜 바뀐 쪽
MAX_CHANGE = 35.0
BAD_MIN = 0.35

# 동작 태그 -> 소품과의 관계 문장 (없으면 '옆에')
REL = [("pushing", "that he is pushing with both hands"), ("rolling", "that he is rolling"),
       ("holding", "that he is holding"), ("carrying", "that he is carrying"), ("hugging", "that he is hugging"),
       ("eating", "that he is eating"), ("drinking", "that he is drinking"), ("throwing", "that he is throwing"),
       ("pointing", "that he is pointing at"), ("looking", "that he is looking at"), ("sitting", "next to where he sits")]


def _prop_tags(conti, pn):
    pv = ((conti.get("world") or {}).get("props") or {}).get(pn) or {}
    return pv.get("tags", pn) if isinstance(pv, dict) else str(pv or pn)


def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def prop_score(kit, conti, cut, path):
    """{소품 이름: 판별기 점수} (그림 전체)"""
    import nk_tagger
    ok, _ = nk_tagger.available(kit)
    if not ok:
        return None
    t = nk_tagger.tags(kit, path) or {}
    out = {}
    for pn in cut.get("props") or []:
        tg = "|".join(x.strip() for x in str(_prop_tags(conti, pn)).split(",") if x.strip())
        out[pn] = round(nk_tagger.score(t, tg), 3)
    return out


def targets(W, kit, conti, cuts_arg=None):
    """[(cut, 빠진 소품 이름 목록)] - 사람이 나오는 혼자 컷 + props, 최종본에서 소품 점수 < PROP_MIN"""
    ep = conti["_ep"]
    out = []
    for cut in conti["cuts"]:
        cid = int(cut["id"])
        if cuts_arg and cid not in cuts_arg:
            continue
        if cut.get("_roles") or not cut.get("_char") or not cut.get("props"):
            continue
        f = W._final_file(kit, ep, cid)
        if not os.path.exists(f):
            continue
        sc = prop_score(kit, conti, cut, f)
        if sc is None:
            if cuts_arg:
                out.append((cut, list(cut["props"])))
            continue
        miss = [pn for pn, v in sc.items() if v < PROP_MIN]
        if miss:
            print("cut %d: missing %s (tagger %s)" % (cid, ", ".join(miss), sc))
            out.append((cut, miss))
        elif cuts_arg:
            print("[skip] cut %d: props already visible %s" % (cid, sc))
    return out


def build_prompt(cut, ch, miss, conti):
    name = "the " + (ch.get("compose_name") or "character")
    act = str(cut.get("scene", ""))
    rel = next((r for k, r in REL if k in act), "next to him")
    things = " and ".join("a %s %s" % (_prop_tags(conti, pn).split(",")[0].strip(), rel) for pn in miss)
    return ("Add to this picture %s, clearly visible and in proportion to %s. %s: %s. "
            "Keep the character, the face, the pose, the colors, the art style, the background and the lighting exactly the same."
            % (things, name, name[0].upper() + name[1:], act.replace("solo, ", "")))


def run_use(W, kit, ep, choices):
    import shutil
    d = os.path.join(W.ep_dir(kit, ep), "cuts_propfix")
    rec_p = os.path.join(d, "propfix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    for chs in choices:
        cid, sd = [int(x) for x in chs.split("=")]
        f = W._final_file(kit, ep, cid)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        if sd == 0:
            if not os.path.exists(orig):
                print("[ERROR] no original kept for cut %d" % cid); sys.exit(1)
            shutil.copy(orig, f)
        else:
            p = os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, sd))
            if not os.path.exists(p):
                print("[ERROR] no candidate", p); sys.exit(1)
            if not os.path.exists(orig):
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                shutil.copy(f, orig)
            shutil.copy(p, f)
        r = rec.get(str(cid)) or {}
        r.update(use=sd, manual=True, final_md5=_md5(f))
        rec[str(cid)] = r
        print("cut %02d -> %s" % (cid, "original" if sd == 0 else "propfix seed %d" % sd))
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def run(nk, kit, args):
    import nk_webtoon as W
    import nk_restyle as R
    import nk_tagger
    import shutil
    from PIL import Image, ImageDraw
    if getattr(args, "use", None):
        return run_use(W, kit, args.ep, args.use)
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts_arg = [int(x) for x in args.cuts] if args.cuts else None
    todo = targets(W, kit, conti, cuts_arg)
    if not todo:
        print("nothing to do: every character cut with props shows them (tagger >= %.2f)" % PROP_MIN)
        return
    seed = args.seed if args.seed is not None else 71
    seeds = [seed + k for k in range(max(1, int(args.tries or 2)))]
    d = os.path.join(W.ep_dir(kit, args.ep), "cuts_propfix")
    rec_p = os.path.join(d, "propfix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    jobs, info = [], {}
    for cut, miss in todo:
        cid = int(cut["id"])
        f = W._final_file(kit, args.ep, cid)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        # 이미 소품을 넣은 컷을 다시: 넣기 전 원본에서 시작 (넣은 그림에 또 넣지 않게)
        src = orig if os.path.exists(orig) and (rec.get(str(cid)) or {}).get("final_md5") == _md5(f) else f
        w0, h0 = Image.open(src).size
        w, h = R.fit_size(w0, h0)
        text = build_prompt(cut, cut["_char"], miss, conti)
        img = W._upload_input(nk, cfg, src, "%s_cut%02d_prepropfix.png" % (args.ep, cid), args.dry)
        info[cid] = {"src": src, "final": f, "orig": orig, "miss": miss, "prompt": text, "size": [w0, h0]}
        print("cut %d: %s" % (cid, text))
        for sd in seeds:
            label = "cut%02d_s%d" % (cid, sd)
            jobs.append({"label": label, "graph": R.graph(img, text, sd, "nk/%s_propfix/%s" % (args.ep, label), w, h, 1.0),
                         "positive": text, "negative": "", "seed": sd,
                         "settings": {"cfg": 1.0, "steps": 8, "width": w, "height": h, "model": R.QWEN["unet"]}})
    print("propfix %s: %d cuts x %d seeds (~90 s each)" % (args.ep, len(info), len(seeds)))
    res = nk.run_jobs(cfg, jobs, "%s/propfix" % args.ep, args.dry)
    if args.dry:
        return
    src_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "propfix")
    os.makedirs(os.path.join(d, "cand"), exist_ok=True)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    made = {}
    for r in res:
        cid = int(r["label"][3:5])
        w0, h0 = info[cid]["size"]
        im = Image.open(os.path.join(src_dir, r["file"])).convert("RGB").resize((w0, h0), Image.LANCZOS)
        p = os.path.join(d, "cand", r["label"] + ".png")
        im.save(p)
        try:
            import nk_edit
            if nk_edit.PASTE:
                pz = nk_edit.local_paste(nk, kit, cfg, args.ep, info[cid]["src"], p, "")    # 소품 넣기는 얼굴을 고치는 일이 아님
                print("   cut %02d seed %d: changed area %.0f%%%s" % (cid, int(r["seed"]), 100 * pz["area"],
                      " (whole picture changed)" if pz["mode"] == "global" else ", %d face(s) kept" % pz["faces_kept"]))
        except Exception as e:
            print("   (paste failed: %s)" % e)
        made.setdefault(cid, []).append((int(r["seed"]), p))
    for cid, lst in made.items():
        cut, ch = cuts[cid], cuts[cid]["_char"]
        forbid = [x.strip() for x in str(ch.get("forbid") or "").split(",") if x.strip()]
        judged = []
        checks = {}
        for sd, p in lst:
            ps = prop_score(kit, conti, cut, p) or {}
            t = nk_tagger.tags(kit, p) or {}
            bad = {tg: round(nk_tagger.score(t, tg), 2) for tg in forbid if nk_tagger.score(t, tg) >= BAD_MIN}
            mosaic = R.mosaic_score(Image.open(p))
            import nk_backfix
            chg = nk_backfix._change(info[cid]["src"], p)
            ok = all(v >= PROP_MIN for k, v in ps.items() if k in info[cid]["miss"]) and not bad and mosaic < R.MOSAIC_ON \
                and chg <= MAX_CHANGE
            checks[str(sd)] = {"props": ps, "bad": bad, "mosaic": round(mosaic, 2), "change": chg, "pass": ok}
            print("[judge] cut %02d seed %d: %s props %s bad %s mosaic %.1f change %.1f%s"
                  % (cid, sd, "PASS" if ok else "FAIL", ps, bad or "-", mosaic, chg,
                     " (whole picture redrawn)" if chg > MAX_CHANGE else ""))
            judged.append((not ok, chg, sd, p))
        judged.sort()
        entry = {"miss": info[cid]["miss"], "prompt": info[cid]["prompt"], "checks": checks, "seeds": [s for s, _ in lst]}
        fail, _, sd, p = judged[0]
        if fail:
            entry.update(use=0, final_md5=_md5(info[cid]["final"]))
            print("[WARN] cut %02d: no candidate shows the prop cleanly - final left as it was. look at %s\\cand" % (cid, d))
        else:
            if not os.path.exists(info[cid]["orig"]):
                os.makedirs(os.path.dirname(info[cid]["orig"]), exist_ok=True)
                shutil.copy(info[cid]["final"], info[cid]["orig"])
            shutil.copy(p, info[cid]["final"])
            entry.update(use=sd, final_md5=_md5(info[cid]["final"]))
            print("cut %02d: final <- seed %d (original kept in cuts_propfix/orig)" % (cid, sd))
        rec[str(cid)] = entry
        # 비교 한 장: 원본 | 후보들
        H = 560
        # '전' = 넣기 전 그림 (최종본은 이미 바뀌었을 수 있음 -> orig/ 또는 src). 첫 시험에서 바뀐 최종본을 '전'으로 보여 준 실수
        before = info[cid]["orig"] if os.path.exists(info[cid]["orig"]) else info[cid]["src"]
        tiles = [("before", before)] + [("s%d (change %.0f)" % (s, checks[str(s)]["change"]), q) for s, q in lst]
        ims = [(lb, Image.open(q).convert("RGB")) for lb, q in tiles]
        ims = [(lb, im.resize((int(im.width * H / im.height), H))) for lb, im in ims]
        sheet = Image.new("RGB", (sum(i.width for _, i in ims) + 10 * (len(ims) - 1), H + 24), "white")
        dr = ImageDraw.Draw(sheet)
        x = 0
        for lb, im in ims:
            sheet.paste(im, (x, 24)); dr.text((x + 4, 6), lb, fill="black"); x += im.width + 10
        sheet.save(os.path.join(d, "cut%02d_cmp.png" % cid))
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("look: %s\\cutNN_cmp.png  (choose: nk ep propfix %s --use 6=72 / 6=0 = back)" % (d, args.ep))
