# -*- coding: utf-8 -*-
"""콘티의 모든 컷을 Anima가 한 번에 그림 — T3 '천장 만화'

왜: 두 명 닿는 컷은 두 캐릭터를 다 아는 모델이 한 장에 한 번에 그리면 됨 (hands_h Anima 4/4, T1 5/5),
    예전 A 방식과 다름 — Anima 그림이 그대로 최종 컷.

사용: nk ep animamake <ep> [컷...] [--unet anima-base-v1.0.safetensors] [--steps 30] [--cfg 4.5] [--sampler er_sde]
 [--seed 500] [--force] [--dry]
      → episodes/<ep>/cuts/cutNN.png (있으면 건너뜀, --force면 _alt/ 에 남기고 다시) + episodes/<ep>/animamake.json
      글자·페이지는 그다음 `nk ep auto <ep> --from letter` (그리기 단계 건너뜀)"""
import os
import re, sys, json, time, shutil

DEFAULT = {"unet": "anima-base-v1.0.safetensors", "steps": "30", "cfg": "4.5", "sampler": "er_sde"}

NEG = ("worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, "   # Anima README 권장
       "text, speech bubble, watermark, signature, comic, 2koma, split screen, multiple views, panel border, border, "
       "nsfw, explicit, sensitive")


#   -> 다시 그린 횟수를 episodes/<ep>/reseed.json 에 적고, 그 컷 시드를 1000씩 옮김 (태그를 바꾼 다시 그리기는 시드 그대로 = 바뀐 것만 바뀜)
RESEED = "reseed.json"


def _reseed_path(ep):
    import nk_webtoon as W
    return os.path.join(W.ep_dir(os.path.dirname(os.path.abspath(__file__)), ep), RESEED)


def reseed_count(ep, cid):
    try:
        return int(json.load(open(_reseed_path(ep), encoding="utf-8")).get(str(int(cid)), 0))
    except Exception:
        return 0


def bump_reseed(ep, cid):
    """'다시 그리기' 한 번 -> 그 컷 시드 +1000. 새 횟수를 돌려줌"""
    p = _reseed_path(ep)
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        d = {}
    d[str(int(cid))] = int(d.get(str(int(cid)), 0)) + 1
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p, "w", encoding="utf-8"), indent=1)
    return d[str(int(cid))]


def cut_seed(ep, cut, base):
    cid = int(cut["id"])
    return int(cut.get("seed") or (int(base) + cid)) + 1000 * reseed_count(ep, cid)


def cut_chars(W, cut):
    """이 컷에 나오는 캐릭터 파일들 (두 명 = _roles, 혼자 = _cut_char)"""
    if cut.get("_roles"):
        return [ch for _, ch in cut["_roles"] if ch]
    ch = W._cut_char(None, cut)
    return [ch] if ch else []


def cut_lora(W, cut):
    """컷에 Anima LoRA 가 있는 캐릭터(캐릭터 파일 anima_lora)가 나오면 (파일, 세기). 한 컷에 LoRA 하나만 (둘이면 첫 것 + 경고)"""
    ls = [(ch["anima_lora"], float(ch.get("anima_lora_strength", 1.0))) for ch in cut_chars(W, cut) if ch.get("anima_lora")]
    if len(ls) > 1:
        print("[warn] cut %s: two Anima LoRA characters - only %s used" % (cut.get("id"), ls[0][0]))
    return ls[0] if ls else (None, None)


def is_back(cut):
    """뒷모습 컷인가.
    장면·동작 글에 from behind / facing away 가 있고 looking back(뒤돌아보기 = 얼굴 보임)이 없으면 뒷모습"""
    t = " ".join(str(cut.get(k) or "") for k in ("scene", "anima_act")).lower()
    return ("from behind" in t or "facing away" in t or str(cut.get("angle") or "") == "back") and "looking back" not in t


def shot_desc(ch, shot, back=False):
    """    컷 거리마다 캐릭터 설명을 고름 (업힌 쪽은 머리·얼굴만 보이는 것과 같은 원리). face·detail = anima_head / waist = anima_upper / 그 밖 = LoRA 캐릭터는 anima_lora_desc.
    뒷모습(back) = anima_back 먼저. 칸이 없으면 다음 것으로 (없으면 None = 그대로)"""
    if back and ch.get("anima_back"):
        return ch["anima_back"]
    #   손 극근접에 머리·눈 설명이 들어가 얼굴이 나오고 칸 안에 칸이 생김 (3/3) -> 손·소매만 (anima_hands, 없으면 짧은 기본 문장)
    face_order = ("anima_upper", "anima_head", "anima_lora_desc") if not ch.get("anima_lora") else ("anima_head", "anima_upper", "anima_lora_desc")
    order = {"face": face_order, "detail": ("anima_head", "anima_upper", "anima_lora_desc"),
             "eyes": ("anima_head", "anima_upper", "anima_lora_desc"), "hands": ("anima_hands",),
             "waist": ("anima_upper", "anima_lora_desc")}.get(str(shot or ""), ("anima_lora_desc",))
    if not ch.get("anima_lora"):
        order = tuple(k for k in order if k != "anima_lora_desc")
    got = next((ch[k] for k in order if ch.get(k)), None)
    if got is None and str(shot or "") == "hands":
        sex = "man's" if "1boy" in str(ch.get("tags_full", "")) else "woman's"
        got = "close-up of a %s hands only, the face is outside the frame" % sex
    return got


def drop_eyes(ch, desc, tags):
    """자는·눈 감은 컷이면 설명에서 눈 말(캐릭터 파일 anima_eyes, 예: 'big green eyes')을 뺌."""
    eyes = ch.get("anima_eyes")
    t = str(tags).lower()
    if not eyes or not ("closed eyes" in t or "sleeping" in t):
        return desc
    for pat in (", " + eyes, " and " + eyes, eyes + ", ", eyes):
        if pat in desc:
            return desc.replace(pat, "", 1)
    return desc


def cut_text(nk, W, cfg, conti, cut, artist):
    """nk_pose._cut_prompt (두 명 = _anima_prompt 동작 문장, 혼자·사물 = _anima_solo) + 작가 '@이름'.
    LoRA 캐릭터는 설명 문장(anima)을 anima_lora_desc(트리거 + 짧은 태그)로 바꿈 — LoRA 가 모습을 맡음"""
    import nk_pose
    s, text, _ = nk_pose._cut_prompt(nk, W, cfg, conti, cut)
    back = is_back(cut)
    pairs = [(r, ch) for r, ch in cut["_roles"] if ch] if cut.get("_roles") else [(None, ch) for ch in cut_chars(W, cut)]
    for r, ch in pairs:
        if ch.get("anima"):
            d = shot_desc(ch, cut.get("shot"), back) or ch["anima"]
            d = drop_eyes(ch, d, str(r.get("pos", "")) if r else str(cut.get("scene", "")))
            if d != ch["anima"]:
                text = text.replace(ch["anima"], d)
    shot = str(cut.get("shot") or "")
    if char_tags_on(conti) and pairs and shot != "hands":
        tags = [str(ch.get("trigger") or "").strip() for _, ch in pairs if ch and not ch.get("anima_lora")]
        if len(pairs) == 1 and pairs[0][1] and not pairs[0][1].get("anima_lora") and shot not in ("eyes", "face", "detail"):   # 혼자 컷은 핵심 태그(tags_full)까지 글에, 두 명 컷은 이름 태그만 (핵심 태그는 사람별 틀 글에). LoRA 캐릭터는 LoRA 가 모습을 맡음
            tags.append(str(pairs[0][1].get("tags_full") or ""))
        tg = _dedupe_tags(text, ", ".join(x for x in tags if x))
        if tg:
            text = text.replace("safe, ", "safe, %s, " % tg, 1) if "safe, " in text else "%s, %s" % (tg, text)
    if gaze_on(conti, cut):
        text = text.replace("safe, ", "safe, looking at another, ", 1) if "safe, " in text else "looking at another, " + text
        if gaze_mode(conti) != "v2":
            text = text.rstrip() + " They look at each other, not at the viewer."
    if gaze_mode(conti) == "v2" and cut.get("_roles"):
        gp = gaze_people(dict(conti, gaze="auto"), cut)
        (r1, c1), (r2, c2) = cut["_roles"]
        nm = lambda c: str((c or {}).get("compose_name") or "other character").replace("the ", "", 1)
        sents = []
        if gp[0]:
            sents.append("The %s turns her head and looks directly at the %s, not at the viewer." % (nm(c1), nm(c2)))
        if gp[1]:
            sents.append("The %s turns her head and looks directly at the %s, not at the viewer." % (nm(c2), nm(c1)))
        if sents:
            text = text.rstrip() + " " + " ".join(sents)
    if cut.get("anima_act"):          # 동작 문장 목록에 없는 동작을 컷에 직접 적음
        text = text.rstrip() + " " + cut["anima_act"].strip()
    if conti.get("collarbone", True) and str(cut.get("shot")) in ("knee", "waist", "face") and pairs and             all(not (ch or {}).get("anima_lora") and "furry" not in str((ch or {}).get("tags_full", "")).lower() for _, ch in pairs):
        text = text.replace("safe, ", "safe, collarbone, ", 1) if "safe, " in text else "collarbone, " + text
        text = text.rstrip() + " The collarbones are clearly visible at the neckline."
    if conti.get("anima_tags"):
        tg = str(conti["anima_tags"]).strip().strip(",")
        text = text.replace("safe, ", "safe, %s, " % tg, 1) if "safe, " in text else "%s, %s" % (tg, text)
    artist = cut.get("anima_artist", artist)      # 컷마다 작가 (그림 시험 묶음). 없으면 콘티 작가
    if artist:
        a = "@" + artist.lstrip("@")
        text = text.replace("safe, ", "safe, %s, " % a, 1) if "safe, " in text else "%s, %s" % (a, text)
    return s, text


def char_tags_on(conti):
    """콘티 char_tags: false 면 끔"""
    return str(conti.get("char_tags", True)).lower() not in ("false", "off", "none", "0")


GAZE_WORDS = ("looking", "closed eyes", "eyes closed", "sleeping", "wink")         # 이미 시선이 정해진 사람 ('half-closed eyes' 는 시선 아님)
GAZE_BLOCK = ("from behind", "back-to-back", "facing away")                        # 서로 볼 수 없는 컷


def _gaze_word(words):
    w = re.sub(r"half-closed eyes", "", str(words or "").lower())
    return any(g in w for g in GAZE_WORDS)


def gaze_mode(conti):
    return str(conti.get("gaze", "v2") or "off").lower()


def duo_strength(conti, cut):
    """키·다리가 인형대로, 원근 안 망가짐 (같은 시드 3컷).
    혼자 컷은 아직 시험 안 함 -> 약하게 그대로. 콘티 pose3d_strength 가 있으면 그것 (모든 컷), duo_strength: off 면 끔"""
    if conti.get("pose3d_strength"):
        return [float(x) for x in re.split(r"[/,]", str(conti["pose3d_strength"]))]
    if len(cut.get("_roles") or []) == 2 and str(conti.get("duo_strength", "on")).lower() not in ("off", "false", "0"):
        return [0.45, 0.45, 0.3, 0.7]
    return None


def gaze_people(conti, cut):
    """시선 말이 있는 사람·등 맞대기는 안 붙임"""
    roles = cut.get("_roles") or []
    if gaze_mode(conti) not in ("auto", "v2") or len(roles) != 2:
        return [False, False]
    scene = " ".join([str(cut.get("scene") or ""), str(cut.get("sentence") or ""), str(cut.get("anima_act") or "")]).lower()
    if any(b in scene for b in GAZE_BLOCK) or str(cut.get("angle") or "") == "back":
        return [False, False]
    if any(k in scene for k in ("piggyback", "carrying", "princess carry", "shoulder carry", "chasing")):
        return [False, False]
    return [not _gaze_word(str(r.get("pos") or "")) for r, _ in roles]


def gaze_on(conti, cut):
    """두 사람 다 시선 말이 없을 때 (컷 전체 글에 '서로 봄')"""
    g = gaze_people(conti, cut)
    return all(g) and not _gaze_word(str(cut.get("scene") or ""))


def char_negs(conti, cut, W=None):
    """다른 캐릭터의 긍정 말(trigger·tags_full·anima)에
    들어 있는 말은 뺌. 'furry'·'anthro'·색 낱말은 그림 규칙대로 뺌"""
    if str(conti.get("char_neg") or "").lower() not in ("true", "1", "on"):
        return ""
    if cut.get("_roles"):
        chars = [ch for _, ch in cut["_roles"] if ch]
    else:
        chars = [cut.get("_char")] if cut.get("_char") else []
    chars = [c for c in chars if c]
    out = []
    for c in chars:
        others = " ".join(str(o.get(k) or "") for o in chars if o is not c for k in ("trigger", "tags_full", "anima")).lower()
        mine = " ".join(str(c.get(k) or "") for k in ("trigger", "tags_full", "anima")).lower()
        for x in str(c.get("negative_extra") or "").split(","):
            x = x.strip()
            if not x or x.lower() in ("furry", "anthro", "mammal", "feral") or x.lower() in others or x.lower() in mine:
                continue
            if x.lower() not in [o.lower() for o in out]:
                out.append(x)
    return ", ".join(out)


def _dedupe_tags(text, tags):
    """이미 글에 있는 태그는 빼고 쉼표 목록으로"""
    have = set(x.strip().lower() for x in re.split(r"[,.]", text))
    out = []
    for x in str(tags or "").split(","):
        x = x.strip()
        if x and x.lower() not in have and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return ", ".join(out)


def hand_refine(nk, kit, args, cid, dst):
    import argparse, nk_webtoon as W, nk_detail
    try:
        nk_detail.run(nk, kit, argparse.Namespace(ep=args.ep, cuts=[str(cid)], den="0.6", parts="hands", prompt="part", dry=False))
        out = os.path.join(W.ep_dir(kit, args.ep), "detail_part", "cut%02d_d0.60.png" % cid)
        if os.path.exists(out):
            alt = os.path.join(W.ep_dir(kit, args.ep), "_alt")
            os.makedirs(alt, exist_ok=True)
            shutil.copy(dst, os.path.join(alt, "cut%02d_before_hands.png" % cid))
            shutil.copy(out, dst)
            print("   [hands] cut %d: 손 다시 그림 붙임 (원본 _alt)" % cid)
    except Exception as e:
        print("   [hands] cut %d 실패: %s" % (cid, e))


def body_flags(kit, ep, cut, img):
    """검사기 v1 의 몸 검사(몸 방향·큰 자세·다리 빠짐)만 — 믿을 수 있는 부분 (헛걸림 0)"""
    try:
        import nk_inspect as I
        r = I.inspect_cut(kit, ep, cut, img)
        if not r:
            return []
        return [f for v in I.judge([r]) for f in v["flags"] if f[0] in ("facing", "pose", "legs")]
    except Exception as e:
        print("   [inspect] 실패 (%s) -> 다시 그리기 안 함" % e)
        return []


def auto_retry(nk, kit, args, conti, cut, c, vc, text, neg, w, h, label, dst, retry_n, rec, rec_p):
    """그린 컷을 검사기로 보고, 걸리면 새 시드(+1000)로 최대 retry_n 번 다시 그려 걸림이 가장 적은 것을 최종으로. 다른 판은 _alt/cutNN_tryK.png"""
    import nk_webtoon as W, nk_animatest
    cid = int(cut["id"])
    alt = os.path.join(W.ep_dir(kit, args.ep), "_alt")
    os.makedirs(alt, exist_ok=True)
    best = (len(body_flags(kit, args.ep, cut, dst)), dst, rec.get(str(cid)))
    print("   [retry] cut %d: 검사 걸림 %d" % (cid, best[0]))
    k = 0
    while best[0] > 0 and k < retry_n:
        k += 1
        bump_reseed(args.ep, cid)
        seed = cut_seed(args.ep, cut, args.seed)
        g = nk_animatest.graph(vc, text, neg, w, h, seed, "nk/%s_animamake/%s_try%d" % (args.ep, label, k))
        ims = (c.wait(c.queue(g), label + " try%d" % k).get("10") or {}).get("images") or []
        if not ims:
            continue
        tp = os.path.join(alt, "cut%02d_try%d.png" % (cid, k))
        c.fetch(ims[0], tp)
        n = len(body_flags(kit, args.ep, cut, tp))
        print("   [retry] cut %d 시도 %d (시드 %d): 걸림 %d" % (cid, k, seed, n))
        if n < best[0]:
            best = (n, tp, dict(best[2] or {}, seed=seed, retry=k))
    if best[1] != dst:
        shutil.copy(dst, os.path.join(alt, "cut%02d_try0.png" % cid))
        shutil.copy(best[1], dst)
        rec[str(cid)] = best[2]
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("   [retry] cut %d: 시도 %s 판을 최종으로 (걸림 %d)" % (cid, best[2].get("retry"), best[0]))


def neg_for(conti):
    """기본 부정 + 만화 전체 부정어 (plan anima_neg, 예: 배경 흐림 빼기 depth of field, blurry background, bokeh)"""
    return NEG + ((", " + str(conti["anima_neg"]).strip().strip(",")) if conti.get("anima_neg") else "")


def run(nk, kit, args):
    import nk_webtoon as W, nk_animatest
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    artist = args.artist if args.artist is not None else conti.get("artist", "")
    v = {"unet": args.unet, "steps": int(args.steps), "cfg": float(args.cfg), "sampler": args.sampler, "scheduler": "simple",
         "shift": float(args.shift) if args.shift else None}
    ids = [int(x) for x in args.cuts] or [int(c["id"]) for c in conti["cuts"]]
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    rec_p = os.path.join(W.ep_dir(kit, args.ep), "animamake.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    W.tag_report(kit, conti, [c for c in conti["cuts"] if int(c["id"]) in ids])
    print("animamake %s: %d cuts | %s %s steps cfg %s %s | artist @%s" % (args.ep, len(ids), v["unet"], v["steps"], v["cfg"],
                                                                        v["sampler"], artist))
    made = 0
    for cut in conti["cuts"]:
        cid = int(cut["id"])
        if cid not in ids:
            continue
        dst = W._final_file(kit, args.ep, cid)
        if os.path.exists(dst) and not args.force:
            print("[skip] cut %d: %s exists (--force to redraw)" % (cid, dst)); continue
        s, text = cut_text(nk, W, cfg, conti, cut, artist)
        w, h = [int(x) for x in s["size"].split("x")] if isinstance(s.get("size"), str) else (int(s["width"]), int(s["height"]))
        seed = cut_seed(args.ep, cut, args.seed)
        label = "cut%02d" % cid
        lora, lst = (None, None) if getattr(args, "nolora", False) else cut_lora(W, cut)
        vc = dict(v, lora=lora, lora_strength=lst) if lora else v
        neg = neg_for(conti) + ((", " + args.neg_extra) if getattr(args, "neg_extra", None) else "")
        if any(gaze_people(conti, cut)) and "looking at viewer" not in str(cut.get("scene") or "").lower():
            neg += ", looking at viewer"
        if str(cut.get("shot")) == "hands":
            neg += ", self grab, holding own wrist"
            neg += ", face, head, eyes, hair, split screen, multiple views, 2koma"
        if re.search(r"(^|[ ,])pulling([ ,]|$)", " ".join(str(cut.get(k) or "") for k in ("scene", "anima_act")) + " " + " ".join(str(r.get("pos") or "") for r, _ in (cut.get("_roles") or []))):
            neg += ", tail pull, holding another's tail"
        cn = char_negs(conti, cut, W)
        if cn:
            neg += ", " + cn
        if str(conti.get("pose3d") or "").lower() in ("auto", "scene3d", "capsule"):
            import nk_pose3d_auto as P3
            if str(conti.get("pose3d_arms") or "") == "all":
                cut["_arms_all"] = True
            if gaze_mode(conti) == "v2":
                cut["_gaze"] = gaze_people(conti, cut)
            hy = conti.get("hug_yaw", 35)
            if hy not in (None, "", "off", False):
                cut["_hug_yaw"] = float(hy)
            pp3 = P3.plan_pose(cut)
            if pp3 and pp3[0] == "dw":
                draft = os.path.join(W.ep_dir(kit, args.ep), "poses", "cut%02d_draft.png" % cid)
                if not os.path.exists(draft) and not args.dry:
                    c = c or nk.Comfy(cfg.get("server", "auto"))
                    gd = nk_animatest.graph(dict(vc, steps=min(int(v["steps"]), 20)), text, neg, w, h, seed, "nk/%s_animamake/%s_draft" % (args.ep, label))
                    t1 = time.time()
                    di = (c.wait(c.queue(gd), label + "_draft").get("10") or {}).get("images") or []
                    if di:
                        os.makedirs(os.path.dirname(draft), exist_ok=True)
                        c.fetch(di[0], draft)
                        print("   draft %s (%.0f s)" % (draft, time.time() - t1))
                dp = P3.depth_from_draft(kit, args.ep, cut, w, h, draft) if os.path.exists(draft) else None
                if dp and str(conti.get("pose3d")).lower() == "scene3d" and not args.dry:
                    sys.path.insert(0, os.path.join(kit, "tools"))
                    from scene3d import export_doll as S3
                    S3.make_cut(kit, args.ep, cut, w, h, dp)
            else:
                dp = P3.depth_for(kit, args.ep, cut, w, h)
                if dp and str(conti.get("pose3d")).lower() == "scene3d" and not args.dry:
                    sys.path.insert(0, os.path.join(kit, "tools"))
                    from scene3d import export_doll as S3
                    parts = tuple(str(conti.get("scene3d_parts") or "depth,line,mask").split(","))
                    if not S3.make_cut(kit, args.ep, cut, w, h, dp, parts):
                        print("[scene3d] cut %d: Blender 실패 -> 캡슐 인형 그대로" % cid)
            if dp:
                up = W._upload_input(nk, cfg, dp, "pose3d_%s_cut%02d.png" % (args.ep, cid), args.dry)
                up2 = W._upload_input(nk, cfg, dp.replace("_depth3d.png", "_line3d.png"), "pose3d_%s_cut%02d_line.png" % (args.ep, cid), args.dry)
                regs = []
                for tag, chx in zip("ab", getattr(P3.depth_for, "last", (None, None))):
                    mp = dp.replace("_depth3d.png", "_mask_%s.png" % tag)
                    if chx and cut.get("_roles") and os.path.exists(mp):      # 두 명 컷만: 사람별 틀마다 그 캐릭터 글
                        rpos = next((str(r.get("pos") or "") for r, c2 in cut["_roles"] if c2 is chx), "")
                        sex = "1boy" if "1boy" in str(chx.get("tags_full", "")) else "1girl"
                        art = cut.get("anima_artist", artist)
                        ctag = (", ".join(x for x in (str(chx.get("trigger") or "").strip() if not chx.get("anima_lora") else "",
                                                      str(chx.get("tags_full") or "").strip()) if x) if (char_tags_on(conti) and not chx.get("anima_lora")) else "")
                        gp = gaze_people(conti, cut)
                        look = "looking at another" if gp[[c2 for _, c2 in cut["_roles"]].index(chx)] else ""
                        head = ", ".join(x for x in ("masterpiece, best quality, score_7, safe", ("@" + art.lstrip("@")) if art else "",
                                                     str(conti.get("anima_tags") or ""), sex, "solo", ctag, look, rpos) if x)
                        rtext = head + ". " + str(chx.get("anima") or chx.get("anima_upper") or "")
                        regs.append((W._upload_input(nk, cfg, mp, "pose3d_%s_cut%02d_mask_%s.png" % (args.ep, cid, tag), args.dry), rtext))
                if len(regs) == 2:
                    vc = dict(vc, _regions=regs)
                    for tag, (_u, rt) in zip("ab", regs):
                        print("  [region %s] %s" % (tag, rt[:260]))
                    if conti.get("region_strength") not in (None, ""):
                        vc = dict(vc, region_strength=float(conti["region_strength"]))
                st = duo_strength(conti, cut) or [P3.STRENGTH, P3.END, P3.STRENGTH2, P3.END2]
                vc = dict(vc, lllite=P3.LLLITE, control_kind="depth", lllite_strength=st[0], lllite_end=st[1], _control_up=up,
                          lllite2=P3.LLLITE2, lllite2_strength=st[2], lllite2_end=st[3], _control_up2=up2)
        g = nk_animatest.graph(vc, text, neg, w, h, seed, "nk/%s_animamake/%s" % (args.ep, label))
        print("\n== cut %d %dx%d seed %d\n  %s" % (cid, w, h, seed, text))
        if args.dry:
            continue
        t0 = time.time()
        outs = c.wait(c.queue(g), label)
        ims = (outs.get("10") or {}).get("images") or []
        if not ims:
            print("[ERROR] cut %d: no image" % cid); continue
        if os.path.exists(dst):
            alt = os.path.join(W.ep_dir(kit, args.ep), "_alt")
            os.makedirs(alt, exist_ok=True)
            shutil.copy(dst, os.path.join(alt, "cut%02d_%s.png" % (cid, time.strftime("%m%d_%H%M"))))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        c.fetch(ims[0], dst)
        rec[str(cid)] = {"text": text, "negative": neg, "seed": seed, "size": [w, h], "settings": vc, "artist": artist,
                         "secs": round(time.time() - t0, 1), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        made += 1
        print("   saved %s (%.0f s)" % (dst, time.time() - t0))
        if str(conti.get("hand_refine") or "").lower() in ("true", "1", "on"):
            hand_refine(nk, kit, args, cid, dst)
        retry_n = int(conti.get("auto_retry") or 0)
        if retry_n > 0:
            auto_retry(nk, kit, args, conti, cut, c, vc, text, neg, w, h, label, dst, retry_n, rec, rec_p)
    print("\nanimamake %s: %d cuts drawn. next: nk ep auto %s --from letter" % (args.ep, made, args.ep))


def add_parser(esub, nk, kit):
    a = esub.add_parser("animamake", help="TEST: draw every cut of the conti with Anima (both characters in one pass)")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.add_argument("--unet", default=DEFAULT["unet"])
    a.add_argument("--steps", default=DEFAULT["steps"]); a.add_argument("--cfg", default=DEFAULT["cfg"])
    a.add_argument("--sampler", default=DEFAULT["sampler"])
    a.add_argument("--shift", help="ModelSamplingAuraFlow shift (turbo 3.0; empty = model default)")
    a.add_argument("--artist", help="artist name for '@name' (default: conti artist; '' = none)")
    a.add_argument("--seed", default="500"); a.add_argument("--force", action="store_true"); a.add_argument("--dry", action="store_true")
    a.add_argument("--neg-extra", dest="neg_extra", help="add to the negative prompt")
    a.add_argument("--nolora", action="store_true", help="draw without any character LoRA (first pass of two-pass; nk ep animafix adds the LoRA only in the character area)")
    a.set_defaults(func=lambda x: run(nk, kit, x))
