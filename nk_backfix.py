# -*- coding: utf-8 -*-
"""
nk_backfix.py - 뒷모습 컷의 등 무늬를 캐릭터 시트 뒷모습대로 고치기

왜: LoRA 학습 그림에 뒷모습이 적으면 등 무늬가 틀리기 쉬움 -> 학습 대신 '다 그린 컷을 고치기'.
방법: Qwen-Image-Edit 2509에 그림 2장 - 1) 완성 컷 2) 시트 뒷모습(캐릭터 파일 back_ref, 머리~허리만 잘라 크게) +
      캐릭터 파일의 back_desc(뒷모습 무늬를 색·모양으로 적은 문장). 컷의 구도·자세·배경·그림체는 그대로.
시험에서 배운 것
  - 막연한 문장("그림 2처럼 등 무늬를 맞춰")은 시트의 엉뚱한 부분까지 등에 그림 ✗ -> back_desc 에 색·모양을 구체적으로 ✓
  주의: 이름을 말하면 그림. back_desc에는 '그려야 할 것'만, 색·모양을 붙여서.
  - 앞을 보는 그림에 쓰면 그림 전체가 시트 뒷모습으로 바뀜 ✗ -> 판별기 from_behind 문(0.5)
  - 인물이 작은 넓은 뒷모습 컷도 그림 전체가 시트로 바뀜 ✗ -> 원본과의 변화량 검사(MAX_CHANGE), 넘으면 최종본을 안 바꿈
    -> 두 명 컷은 기본으로 건너뜀 (--any로만). 다른 캐릭터가 망가질 수 있음
사용: nk ep backfix <ep> [컷 번호...] [--seed 31] [--tries 3] [--any] [--dry]
        컷 번호가 없으면: angle: back 이고 back_desc가 있는 캐릭터가 나오는 컷 전부. 원본에서 뒤돌아 있지 않으면 건너뜀(--any = 그래도)
      nk ep backfix <ep> --use 7=32 21=0   (후보 고르기 / 0 = 고치기 전 원본으로 되돌림)
      결과: episodes/<ep>/cuts_backfix/cand/cutNN_s<시드>.png (후보), orig/cutNN.png (고치기 전 최종본),
            episodes/<ep>/cuts/cutNN.png 는 첫 시드 후보로 바뀜 (그림체 입히기 restyle은 이 그림으로 함)
순서: 최종본 -> backfix -> restyle -> letter"""
import os, sys, json, shutil

PROMPT = ("Picture 2 is the official back view reference of this %(kind)scharacter. Redraw %(name)s in picture 1 with the back markings "
          "of picture 2: %(desc)s Keep the pose, the arms, the legs, the tail, the background and the art style of picture 1 "
          "exactly the same.")


def _targets(conti, cuts_arg):
    """[(cut, 캐릭터 dict)] - 뒷모습 무늬(back_desc)가 있는 캐릭터가 나오는 컷"""
    out = []
    for cut in conti["cuts"]:
        cid = int(cut["id"])
        if cuts_arg and cid not in cuts_arg:
            continue
        chars = [ch for _, ch in (cut.get("_roles") or [])] or ([cut["_char"]] if cut.get("_char") else [])
        chars = [ch for ch in chars if ch.get("back_desc")]
        if not chars:
            if cuts_arg:
                print("[skip] cut %d: no character with back_desc" % cid)
            continue
        if not cuts_arg and str(cut.get("angle", "")) != "back":
            continue
        if len(cut.get("_roles") or []) >= 2 and not getattr(_targets, "any", False):
            print("[skip] cut %d: two-character panel - backfix removes/overwrites the other character. --any to force" % cid)
            continue
        out.append((cut, chars[0]))
    return out


GATE = 0.5
# 사고 검사: 원본과 64x64 흑백으로 비교한 평균 차이. 등 무늬만 바뀌면 작고, 그림 전체가 시트로 바뀌면 큼.
MAX_CHANGE = 25


def _change(a, b):
    import numpy as np
    from PIL import Image
    A = np.asarray(Image.open(a).convert("L").resize((64, 64)), float)
    B = np.asarray(Image.open(b).convert("L").resize((64, 64)), float)
    return round(float(np.abs(A - B).mean()), 1)


def _from_behind(nk, kit, path, cut, ch):
    """이 캐릭터 자리(두 명 컷은 cast side 절반, 혼자 컷은 전체)의 from_behind 점수. 판별기가 없으면 None"""
    import nk_tagger
    from PIL import Image
    ok, why = nk_tagger.available(kit)
    if not ok:
        return None
    im = Image.open(path).convert("RGB")
    w, h = im.size
    for r, c in (cut.get("_roles") or []):
        if c is ch:
            im = im.crop((0, 0, w // 2, h) if r.get("side") == "left" else (w // 2, 0, w, h))
            break
    tmp = os.path.join(os.path.dirname(path), "_bf_gate.png")
    im.save(tmp)
    try:
        t = nk_tagger.tags(kit, tmp) or {}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return float(t.get("from_behind", 0.0))


def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _bdir(W, kit, ep):
    return os.path.join(W.ep_dir(kit, ep), "cuts_backfix")


def run_use(W, kit, args):
    d = _bdir(W, kit, args.ep)
    rec_p = os.path.join(d, "backfix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    for ch in args.use:
        try:
            cid, sd = [int(x) for x in ch.split("=")]
        except ValueError:
            print("[ERROR] --use needs cut=seed, e.g. 7=32"); sys.exit(1)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        if not os.path.exists(orig):
            print("[ERROR] cut %d was never backfixed (no %s)" % (cid, orig)); sys.exit(1)
        src = orig if sd == 0 else os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, sd))
        if not os.path.exists(src):
            print("[ERROR] no candidate", src); sys.exit(1)
        shutil.copy(src, W._final_file(kit, args.ep, cid))
        rec[str(cid)] = dict(rec.get(str(cid)) or {}, use=sd, final_md5=_md5(W._final_file(kit, args.ep, cid)))
        print("cut %02d -> %s" % (cid, "original (before backfix)" if sd == 0 else "seed %d" % sd))
    with open(rec_p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print("then (again): nk ep restyle %s <cuts>" % args.ep)


def run(nk, kit, args):
    import nk_webtoon as W
    import nk_restyle as R
    from PIL import Image
    if getattr(args, "use", None):
        return run_use(W, kit, args)
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts_arg = [int(x) for x in args.cuts] if args.cuts else None
    _targets.any = bool(getattr(args, "any", False))
    todo = _targets(conti, cuts_arg)
    if not todo:
        print("[ERROR] no back-view cut with a back_desc character (angle: back, or give cut numbers)"); sys.exit(1)
    seed = args.seed if args.seed is not None else 31
    tries = max(1, int(args.tries or 3))
    seeds = [seed + k for k in range(tries)]
    d = _bdir(W, kit, args.ep)
    rec_p = os.path.join(d, "backfix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    jobs, info = [], {}
    for cut, ch in todo:
        cid = int(cut["id"])
        f = W._final_file(kit, args.ep, cid)
        if not os.path.exists(f):
            print("[skip] cut %d: no final picture yet" % cid); continue
        pr = rec.get(str(cid)) or {}
        if not cuts_arg and pr.get("final_md5") and pr.get("final_md5") == _md5(f):
            print("[skip] cut %d: unchanged since the last backfix - give the cut number to redo" % cid)
            continue
        # 이미 고친 컷을 다시 고칠 때는 '고치기 전 원본'에서 시작 (고친 그림을 또 고치지 않게).
        # 단 그 뒤에 컷을 새로 그렸으면(ep redo) 지금 최종본이 새 원본
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        prev = (rec.get(str(cid)) or {}).get("final_md5")
        if os.path.exists(orig) and _md5(f) in (prev, _md5(orig)):
            src = orig
        else:
            src = f
            if os.path.exists(orig):
                os.remove(orig)
        # 문: 원본에서 이 캐릭터가 정말 뒤돌아 있나 (판별기 from_behind). 앞을 보는 그림에 쓰면 Qwen이 그림 전체를
        fb = _from_behind(nk, kit, src, cut, ch)
        if fb is not None and fb < GATE and not getattr(args, "any", False):
            print("[skip] cut %d: %s does not face away in the picture (from_behind %.2f < %.2f) - backfix would redraw "
                  "the whole panel. (--any to force)" % (cid, ch.get("name"), fb, GATE))
            continue
        ref = os.path.join(kit, ch["back_ref"])
        if not os.path.exists(ref):
            print("[ERROR] %s: back_ref not found: %s" % (ch.get("name"), ref)); sys.exit(1)
        text = PROMPT % {"name": ch.get("back_name") or ("the " + ch.get("name", "character")),
                         "kind": (str(ch["back_kind"]).strip() + " ") if ch.get("back_kind") else "",
                         "desc": " ".join(str(ch["back_desc"]).split())}
        w0, h0 = Image.open(src).size
        w, h = R.fit_size(w0, h0)
        img = W._upload_input(nk, cfg, src, "%s_cut%02d_prebackfix.png" % (args.ep, cid), args.dry)
        rimg = W._upload_input(nk, cfg, ref, "%s_back_ref.png" % ch.get("name", "char"), args.dry)
        info[cid] = (src, f, orig)
        for sd in seeds:
            label = "cut%02d_s%d" % (cid, sd)
            g = R.graph(img, text, sd, "nk/%s_backfix/%s" % (args.ep, label), w, h, 1.0, ref=rimg)
            jobs.append({"label": label, "graph": g, "positive": text, "negative": "", "seed": sd,
                         "settings": {"cfg": 1.0, "steps": 8, "width": w, "height": h, "model": R.QWEN["unet"]}})
        print("cut %d (%s): %s" % (cid, ch.get("name"), text))
    if not jobs:
        print("[ERROR] nothing to do"); sys.exit(1)
    print("backfix %s: %d cuts x %d seeds %s (~130 s each)" % (args.ep, len(info), tries, seeds))
    res = nk.run_jobs(cfg, jobs, "%s/backfix" % args.ep, args.dry)
    if args.dry:
        return
    src_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "backfix")
    os.makedirs(os.path.join(d, "cand"), exist_ok=True)
    os.makedirs(os.path.join(d, "orig"), exist_ok=True)
    made = {}
    diffs = {}
    for r in res:
        cid = int(r["label"][3:5])
        src, f, orig = info[cid]
        w, h = Image.open(src).size
        im = Image.open(os.path.join(src_dir, r["file"])).convert("RGB").resize((w, h), Image.LANCZOS)
        cp = os.path.join(d, "cand", r["label"] + ".png")
        im.save(cp)
        diffs[r["label"]] = _change(src, cp)
        made.setdefault(cid, []).append(r["seed"])
    for cid, sds in made.items():
        src, f, orig = info[cid]
        ok = [sd for sd in sds if diffs["cut%02d_s%d" % (cid, sd)] <= MAX_CHANGE]
        rec[str(cid)] = {"seeds": sds, "change": {str(sd): diffs["cut%02d_s%d" % (cid, sd)] for sd in sds}}
        if not ok:
            rec[str(cid)].update(use=0, final_md5=_md5(f))
            print("[WARN] cut %02d: every candidate changed the whole panel (change %s > %d) - final left as it was"
                  % (cid, [diffs["cut%02d_s%d" % (cid, sd)] for sd in sds], MAX_CHANGE))
            continue
        if not os.path.exists(orig):
            shutil.copy(f, orig)                      # 고치기 전 최종본 보관
        shutil.copy(os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, ok[0])), f)
        rec[str(cid)].update(use=ok[0], final_md5=_md5(f))
        print("cut %02d: final <- seed %d (change %.1f; all: %s). original kept in %s"
              % (cid, ok[0], diffs["cut%02d_s%d" % (cid, ok[0])], rec[str(cid)]["change"], orig))
    with open(rec_p, "w", encoding="utf-8") as fo:
        json.dump(rec, fo, ensure_ascii=False, indent=1)
    print("look at %s, choose: nk ep backfix %s --use <cut>=<seed>  (0 = before backfix). then nk ep restyle"
          % (os.path.join(d, "cand"), args.ep))
