# -*- coding: utf-8 -*-
"""
nk_facefix.py - 작은 얼굴 고치기

왜: 두 명 컷·넓은 컷에서 캐릭터 얼굴이 작으면(머리가 컷 높이의 30% 안팎) LoRA 무늬가 안 살아남음
    Qwen으로 한 캐릭터만 고치면 다른 캐릭터가 사라지거나 망가짐
    -> SDXL + 캐릭터 LoRA로 '머리만 잘라서 크게' 다시 그림 (ADetailer와 같은 방식). 다른 캐릭터는 마스크 밖이라 안 바뀜.
시험: 머리 512px 크롭 -> 1024 -> 머리 모양 마스크 안만 다시 그림
    denoise 0.45·0.60: 얼굴은 깔끔해지지만 얼굴 무늬가 안 생김 ✗ / 0.85: 시트 얼굴에 가까워짐 ✓
    주의: 0.85에서 목 장식이 마스크에 들어가면 색이 바뀔 수 있음 -> 마스크 아래 끝을 턱까지만 (목 아래는 원본 그대로)
머리 찾기: DWPose 어깨 두 점. 털 캐릭터는 코·눈 점이 한쪽 눈에 몰려서 못 믿고, 어깨는 잘 잡힘.
    목 = 어깨 가운데, s = 어깨 너비 -> 머리 상자 = 가로 목±1.0s, 세로 (목-2.3s) ~ (목-0.2s)  (고양이 귀 끝 ~ 턱)
두 명 컷은 그 사람 칸(span) 밖으로 안 나가게 자름
고칠지 (컷마다):
    1) 뒷모습(판별기 from_behind >= 0.5)이면 건너뜀 - 얼굴이 없음
    2) 머리가 크면(상자 높이 > 컷 높이의 45%) 건너뜀 - 클로즈업은 LoRA가 이미 잘 그림
없으면 검수 AI(qa_checklist region: face)
사람이 --use 로 바꿈
사용: nk ep facefix <ep> [컷 번호...] [--denoise 0.85] [--seed 41] [--tries 2] [--force] [--dry]
        컷 번호가 없으면: 그 캐릭터가 나오는 컷 전부 (위 1~3으로 걸러짐)
      nk ep facefix <ep> --use 4=42 20=0      (0 = 고치기 전 원본으로 되돌림)
결과: episodes/<ep>/cuts_facefix/cand/cutNN_s<시드>.png (컷 전체) + cutNN_s<시드>_head.png (원본 머리 | 고친 머리, 검수용)
      orig/cutNN.png (고치기 전 최종본), facefix.json
순서: 최종본 -> facefix -> backfix -> restyle -> letter
캐릭터 파일 (선택): facefix: {tags: "...", neg: "..."}  - 얼굴 크롭에만 붙이는 태그/부정 태그"""
import os, sys, json, shutil

DENOISE = 0.85
RES = 1024
BIG = 0.45          # 머리 상자 높이 / 컷 높이 가 이보다 크면 건너뜀 (클로즈업)
GATE_BACK = 0.5     # from_behind 문턱 (nk_backfix와 같음)
# 배경 흐림 검사: 마스크 안 바깥쪽(머리가 아닌 배경 자리)의 선명도를 원본과 비교. 작은 머리를 2배 넘게 키워 다시 그리면
BLUR_MIN = 0.8
# 눈으로 보면 멀쩡한 머리 - 합격선(facial_mark 0.6)을 못 넘어 '원본 그대로'가 됨 = 깨진 얼굴이 남음.
# -> 원본 무늬 점수가 RESCUE_ORIG_MAX 미만(깨짐 수준)이고 후보가 RESCUE_GAIN 이상 올랐으면, 배경 흐림·전후 비교 거부권을 통과한 것 중
#    점수 높은 후보를 씀. 합격은 아니므로 기록에 rescue 표시 -> review에 '확인 필요'로 뜸
RESCUE_ORIG_MAX, RESCUE_GAIN = 0.2, 0.25
# 흐림 원인 추정: 'portrait, face focus' 태그가 배경 흐림(피사계 심도)을 부름 + 작은 크롭을 키운 입력이 흐림.
SHARP_NEG = "blurry, blurry background, depth of field, bokeh"

# 얼굴 크롭에 가져갈 표정·시선 태그 (컷·역할 태그 중 이것만). 물건·동작 이름은 안 가져감 -> 머리 크롭에 물건을 그려 넣지 않게
EXPR = {"smile", "grin", "smirk", "open mouth", "closed mouth", "closed eyes", "one eye closed", "wink", "blush", "sweatdrop",
        "pout", "laughing", "happy", "sad", "crying", "tears", "surprised", "shocked", "wide-eyed", "angry", "frown",
        "determined", "worried", "embarrassed", "nervous", "excited", "sleepy", "fang", "fangs", "looking up", "looking down",
        "looking at viewer", "looking at another", "looking away", "looking to the side", "head tilt", "confused", "serious",
        "expressionless", "teeth", "clenched teeth", "tongue out", "half-closed eyes", "raised eyebrows", ":3", ":d", "^_^",
        "happy tears", "annoyed", "smug", "blank stare", "light smile", "big smile", "flustered"}


EXPR_WORDS = ("eye", "mouth", "smile", "grin", "blush", "tear", "cry", "sweat", "dizzy", "fang", "tongue", "frown", "pout",
              "@_@", "wink", "surpris", "shock", "scared", "nervous", "embarrass", "angry", "sad", "happy", "laugh",
              "sleepy", "drool", "sparkl", "expression", "looking ")
# 콘티 표정 -> 판별기(WD) 태그: 고친 얼굴에 그 표정이 있는지 확인 (없으면 그 후보는 불합격)
EXPR_TAGGER = {"spiral eyes": "@_@", "dizzy": "@_@", "closed eyes": "closed_eyes", "crying": "tears", "tears": "tears",
               "streaming tears": "tears", "open mouth": "open_mouth", "wink": "one_eye_closed", "one eye closed": "one_eye_closed"}


def _expr_tags(nk, cfg, cut, role):
    txt = ", ".join(str(x) for x in (nk.resolve_scene(cfg, cut.get("scene", "")) if cut.get("scene") else "",
                                     (role or {}).get("pos", "")) if x)
    out = []
    for t in [x.strip() for x in txt.split(",")]:
        k = t.lower().strip("() ").split(":")[0].strip()
        if k and (k in EXPR or any(w in k for w in EXPR_WORDS)) and k not in out:
            out.append(k)
    return out


def _expr_expect(tags):
    """표정 태그 중 판별기로 확인할 수 있는 것 -> 판별기 태그 목록"""
    out = []
    for t in tags:
        v = EXPR_TAGGER.get(t)
        if v and v not in out:
            out.append(v)
    return out


def _wear_tags(conti, cut, key):
    """콘티 world의 wear/state 중 이 컷·이 캐릭터 것 (모자·머리 위 잎 등). 머리를 다시 그릴 때 빠뜨리면 지워짐"""
    import nk_webtoon as W
    w = (conti or {}).get("world") or {}
    cid = int(cut["id"])
    tags, negs = [], []
    for k in ("wear", "state"):
        for e in w.get(k) or []:
            if str(e.get("who", "")) != str(key) or cid not in W._parse_range(e.get("cuts")):
                continue
            if e.get("tags"):
                tags.append(str(e["tags"]))
            if e.get("neg"):
                negs.append(str(e["neg"]))
    return ", ".join(tags), ", ".join(negs)


def _who(conti, cut, who):
    """(캐릭터 dict, 역할 dict 또는 None, 가로 칸 (a, b)) - 이 컷에 그 캐릭터가 없으면 None"""
    import nk_webtoon as W
    roles = cut.get("_roles") or []
    if roles:
        for r, ch in roles:
            if who in (str(r.get("char")), ch.get("_key"), ch.get("name"), ch.get("trigger")):
                span = tuple(r["span"]) if r.get("span") else W.SIDES[str(r.get("side", "left"))]
                return ch, r, span
        return None
    ch = cut.get("_char")
    if ch and who in (cut.get("_charkey"), ch.get("_key"), ch.get("name"), ch.get("trigger")):
        return ch, None, (0.0, 1.0)
    return None


def head_box(path, span):
    """DWPose 어깨 두 점으로 머리 상자 (x0, y0, x1, y1) (컷 픽셀 좌표). 못 찾으면 (None, 이유)"""
    import numpy as np, cv2, nk_pose
    img0 = cv2.imread(path)
    H, Wd = img0.shape[:2]
    a, b = span
    box = np.array([max(0, (a - 0.02) * Wd), 0, min(Wd, (b + 0.02) * Wd), H])
    best = None
    for g in (1.0, 0.6, 0.45):
        img = img0 if g == 1.0 else np.clip(255 * ((img0 / 255.0) ** g), 0, 255).astype(np.uint8)
        k, c = nk_pose.pose_one(img, box)
        sc = float(min(c[5], c[6]))
        if best is None or sc > best[0]:
            best = (sc, k, c)
        if sc >= 0.45:
            break
    sc, k, c = best
    if sc < 0.3:
        return None, "shoulders not found (conf %.2f)" % sc
    ls, rs = k[5], k[6]
    n = (ls + rs) / 2.0
    s = float(np.linalg.norm(ls - rs))
    if s < 0.03 * H:
        return None, "shoulders too close (%.0f px)" % s
    x0, x1 = n[0] - 1.0 * s, n[0] + 1.0 * s
    y0, y1 = n[1] - 2.3 * s, n[1] - 0.2 * s
    x0, x1 = max(x0, (a - 0.02) * Wd, 0), min(x1, (b + 0.02) * Wd, Wd)
    y0, y1 = max(0, y0), min(H, y1)
    if c[0] >= 0.3 and not (x0 - 0.1 * s <= k[0][0] <= x1 + 0.1 * s and y0 <= k[0][1] <= y1 + 0.3 * s):
        # 코 점이 머리 상자 밖 = 누운 자세·옆으로 기운 머리 등 '목 위에 머리'가 아닌 그림 -> 안 고침
        return None, "nose point outside the head box (head not above the neck?)"
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None, "head box too small"
    return (float(x0), float(y0), float(x1), float(y1)), "ok (shoulder conf %.2f, width %.0f px)" % (sc, s)


def _plan_add(plan, e, cuts_arg):
    hb, h0 = e["hb"], e["size"][1]
    if (hb[3] - hb[1]) / float(h0) > BIG and not cuts_arg:
        print("[skip] cut %d: head is big (%.0f%% of the panel height) - the LoRA already draws big faces well"
              % (e["cid"], 100.0 * (hb[3] - hb[1]) / h0)); return
    plan.append(e)


# 가장 많이 겹치는 것 = 그 캐릭터 머리. 몸 글자가 없는 캐릭터는 혼자 컷에서 가장 큰 머리
SAM_HEAD_MIN_OVERLAP = 0.3
SAM_FIRST = True


def _sam_heads(nk, kit, cfg, ep, pend, dry):
    import numpy as np
    from PIL import Image
    import nk_sam
    import nk_handfix
    items = []
    for e in pend:
        nm = "cut%02d" % e["cid"]
        items.append((nm, e["src"], "head:4"))
        body = nk_handfix._hands_cfg(e["ch"]).get("sam_body")
        if body:
            items.append((nm, e["src"], body))
    got = nk_sam.segment(nk, kit, cfg, ep, items, 0.3, run="facefix_sam", dry=dry, individual=True)
    out = {}
    for e in pend:
        nm = "cut%02d" % e["cid"]
        w, h = e["size"]
        heads = []
        for mp in got.get((nm, "head:4")) or []:
            m = np.asarray(Image.open(mp).convert("L").resize((w, h))) > 127
            if m.sum() > 0.002 * w * h:
                heads.append(m)
        body = nk_handfix._hands_cfg(e["ch"]).get("sam_body")
        bm = None
        if body and got.get((nm, body)):
            bm = np.zeros((h, w), bool)
            for mp in got[(nm, body)]:
                bm |= np.asarray(Image.open(mp).convert("L").resize((w, h))) > 127
        best = None
        for m in heads:
            ov = float((m & bm).sum()) / m.sum() if bm is not None else 1.0
            key = (round(ov, 2), int(m.sum()))
            if best is None or key > best[0]:
                best = (key, m)
        if best is None:
            out[e["cid"]] = (None, "SAM3 found no head"); continue
        if bm is not None and best[0][0] < SAM_HEAD_MIN_OVERLAP:
            out[e["cid"]] = (None, "SAM3 heads are not on this character (best overlap %.2f)" % best[0][0]); continue
        if bm is None and len(heads) > 1 and len(e["cut"].get("_roles") or []) > 1:
            out[e["cid"]] = (None, "two-character cut and no body prompt to tell the heads apart"); continue
        ys, xs = np.nonzero(best[1])
        out[e["cid"]] = ((float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)),
                         "SAM3 head (on the character %.2f)" % best[0][0])
    return out


def _save_boxes(W, kit, ep, plan):
    """--boxes: 찾은 머리 상자만 그려서 저장 (얼굴 고치기는 안 함)"""
    from PIL import Image, ImageDraw
    d = os.path.join(W.ep_dir(kit, ep), "cuts_facefix", "boxes")
    os.makedirs(d, exist_ok=True)
    for p in plan:
        im = Image.open(p["src"]).convert("RGB")
        dr = ImageDraw.Draw(im)
        dr.rectangle(p["hb"], outline=(255, 0, 255), width=max(3, im.width // 200))
        dr.text((p["hb"][0] + 6, p["hb"][1] + 6), p["why"], fill=(255, 0, 255))
        im.thumbnail((900, 900))
        im.save(os.path.join(d, "cut%02d.png" % p["cid"]))
        print("cut %d: head box %s (%s)" % (p["cid"], [int(v) for v in p["hb"]], p["why"]))
    print("look: %s" % d)


def _crop_and_mask(W_, H_, hb):
    """정사각형 크롭 (cx0, cy0, L) + 크롭 안 머리 마스크 (L x L, 0~255, 흐림).
    마스크 = 머리 상자에 맞춘 둥근 네모(|x|^4+|y|^4<=1): 타원이면 고양이 귀 끝(상자 위 모서리 근처)이 잘림"""
    import numpy as np, cv2
    x0, y0, x1, y1 = hb
    bw, bh = x1 - x0, y1 - y0
    L = int(min(max(bw, bh) * 1.25, W_, H_))
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    cx0 = int(min(max(0, cx - L / 2.0), W_ - L))
    cy0 = int(min(max(0, cy - L / 2.0), H_ - L))
    yy, xx = np.mgrid[0:L, 0:L].astype(float)
    u = (xx + cx0 - cx) / (bw / 2.0 * 1.06)
    v = (yy + cy0 - cy) / (bh / 2.0 * 1.04)
    m = ((np.abs(u) ** 4 + np.abs(v) ** 4) <= 1.0).astype(np.float32)
    m[(yy + cy0) > y1] = 0                                  # 턱 아래(목·몸)는 절대 안 건드림
    m[(xx + cx0) < x0 - 0.03 * bw] = 0                      # 칸(span)으로 자른 가장자리 밖도 (다른 캐릭터 보호)
    m[(xx + cx0) > x1 + 0.03 * bw] = 0
    sig = max(2.0, 0.025 * bh)
    m = cv2.GaussianBlur(m, (0, 0), sig)
    m[(yy + cy0) > y1] = 0                                  # 흐림이 턱 아래로 번진 것도 지움
    return cx0, cy0, L, (np.clip(m, 0, 1) * 255).astype(np.uint8)


def _graph(cfg, s, char, pos, neg, img_name, mask_name, seed, den, prefix):
    g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}}
    model, clip = ["4", 0], ["4", 1]
    if char.get("lora"):
        st = float(char.get("lora_strength", 1.0))
        g["20"] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip, "lora_name": char["lora"],
                                                           "strength_model": st, "strength_clip": st}}
        model, clip = ["20", 0], ["20", 1]
    g["1"] = {"class_type": "LoadImage", "inputs": {"image": img_name}}
    g["2"] = {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos", "width": RES,
                                                      "height": RES, "crop": "disabled"}}
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": clip}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": clip}}
    g["10"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["4", 2]}}
    g["11"] = {"class_type": "LoadImage", "inputs": {"image": mask_name}}
    g["12"] = {"class_type": "ImageToMask", "inputs": {"image": ["11", 0], "channel": "red"}}
    g["14"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["10", 0], "mask": ["12", 0]}}
    g["3"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                                    "sampler_name": s["sampler"], "scheduler": s["scheduler"],
                                                    "denoise": float(den), "model": model, "positive": ["6", 0],
                                                    "negative": ["7", 0], "latent_image": ["14", 0]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


def _face_items(char):
    return [it for it in (char.get("qa_checklist") or []) if str(it.get("region", "")) == "face" and it.get("options")]


def _face_check(nk, qa_cfg, char, img_path):
    """검수 AI에게 머리 크롭을 보여 주고 얼굴 항목(이마·눈·귀)을 물어봄. 돌려줌: (합격?, {id: 답}) / 검수 AI 없으면 (None, {})"""
    items = _face_items(char)
    if not items:
        return None, {}
    lines = ['  "%s": %s  Options: %s' % (it["id"], it["q"], " | ".join(it["options"])) for it in items]
    prompt = ("You are a strict quality inspector for a close-up of the head of " + char.get("qa_desc", "an anthropomorphic cat character")
              + " named %s.\nLook at the face carefully, especially small fur markings, and answer every question. "
              "For each question copy exactly one option text as the answer. If a part is not visible, pick the 'not visible' option.\n"
              "Questions:\n%s\nReply with a single JSON object whose keys are exactly the question ids and whose values are the "
              "chosen option text. No explanations.") % (char.get("name", "character"), "\n".join(lines))
    try:
        raw = nk.ollama_ask(qa_cfg, nk._img_b64(img_path, int(qa_cfg.get("max_side", 896))), prompt)
    except SystemExit:
        return None, {}
    ans = nk.parse_answers(raw, [it["id"] for it in items])
    ok, out = True, {}
    for it in items:
        v = ans.get(it["id"])
        j = nk._judge_option(v, it.get("options", []), it.get("expect", []))
        out[it["id"]] = v
        if it.get("must") and j is False:
            ok = False
    return ok, out


def _masked_head(src_img, cx0, cy0, L, mask, dst):
    """판별기용 머리 그림: 크롭에서 마스크 밖(다른 캐릭터·배경)을 회색으로 지움"""
    from PIL import Image
    crop = src_img.crop((cx0, cy0, cx0 + L, cy0 + L))
    bg = Image.new("RGB", (L, L), (128, 128, 128))
    m = Image.fromarray(mask).point(lambda v: 255 if v > 60 else 0)
    bg.paste(crop, (0, 0), m)
    bg.save(dst)
    return dst


def _bg_detail_ratio(old_crop, new_crop, mask):
    """마스크 안쪽이지만 가운데(머리)에서 먼 자리 = 대개 배경. 그 자리 선명도(라플라시안 평균) 새것/원본"""
    import numpy as np, cv2
    a = cv2.resize(np.asarray(old_crop.convert("L"), np.float32), (512, 512), interpolation=cv2.INTER_AREA)
    b = cv2.resize(np.asarray(new_crop.convert("L"), np.float32), (512, 512), interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (512, 512))
    yy, xx = np.mgrid[0:512, 0:512]
    sel = (m > 200) & (np.hypot(xx - 256, yy - 256) > 200)
    if sel.sum() < 200:
        return 1.0
    la = np.abs(cv2.Laplacian(a, cv2.CV_32F))[sel].mean()
    lb = np.abs(cv2.Laplacian(b, cv2.CV_32F))[sel].mean()
    return round(float(lb / max(1e-3, la)), 2)


def _tag_judge(nk, kit, ch, path, expect=None):
    """캐릭터 파일 facefix.good / facefix.bad 가 있을 때만.
    검수 AI(gemma)는 무늬가 틀린 그림도 '합격'으로 볼 때가 많음 (비슷한 색 부분을 무늬로 착각) -> 판별기를 먼저 씀"""
    ff = ch.get("facefix") or {}
    if not ff.get("good"):
        return None
    import nk_tagger
    ok, why = nk_tagger.available(kit)
    if not ok:
        return None
    t = nk_tagger.tags(kit, path) or {}
    good = {k: float(v) for k, v in dict(ff["good"]).items()}
    bad = [x.strip() for x in str(ff.get("bad", "")).split(",") if x.strip()]
    gs = {k: round(float(t.get(k, 0.0)), 2) for k in good}
    bs = {k: round(float(t.get(k, 0.0)), 2) for k in bad}
    worst = max(bs.values()) if bs else 0.0
    es = {k: round(float(t.get(k, 0.0)), 2) for k in (expect or [])}
    passed = all(gs[k] >= good[k] for k in good) and worst < float(ff.get("bad_max", 0.3)) \
        and all(v >= 0.25 for v in es.values())            # 콘티 표정(빙글빙글 눈 등)이 나와야 합격
    r = {"pass": passed, "score": round(sum(gs.values()) - worst + sum(es.values()), 2), "good": gs,
         "bad": {k: v for k, v in bs.items() if v >= 0.1}}
    if es:
        r["expr"] = es
    return r


def _good_sum(info):
    """판별기 기록에서 캐릭터 무늬 점수 합 (facial_mark 등). 판별기를 안 썼으면 None"""
    t = (info or {}).get("tagger")
    if not t:
        return None
    return float(sum((t.get("good") or {}).values()))


def _judge(nk, kit, qa_cfg, ch, path, expect=None):
    """(합격?, 점수, 기록) - 판별기 설정이 있으면 판별기, 없으면 검수 AI 얼굴 질문"""
    r = _tag_judge(nk, kit, ch, path, expect)
    if r is not None:
        return r["pass"], r["score"], {"tagger": r}
    ok, ans = _face_check(nk, qa_cfg, ch, path)
    return ok, (1.0 if ok else 0.0) if ok is not None else 0.0, {"vlm": ans}


def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _fdir(W, kit, ep):
    return os.path.join(W.ep_dir(kit, ep), "cuts_facefix")


def run_use(W, kit, args):
    d = _fdir(W, kit, args.ep)
    rec_p = os.path.join(d, "facefix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    for ch in args.use:
        try:
            cid, sd = [int(x) for x in ch.split("=")]
        except ValueError:
            print("[ERROR] --use needs cut=seed, e.g. 4=42"); sys.exit(1)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        f = W._final_file(kit, args.ep, cid)
        src = orig if sd == 0 else os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, sd))
        if sd != 0 and not os.path.exists(src):
            print("[ERROR] no candidate", src); sys.exit(1)
        if not os.path.exists(orig):
            if sd == 0:
                print("[ERROR] cut %d was never face-fixed (no %s)" % (cid, orig)); sys.exit(1)
            was = (rec.get(str(cid)) or {}).get("final_md5")
            if was and was != _md5(f):
                print("[ERROR] cut %d was redrawn after facefix ran - the candidates belong to the old picture. run facefix again"
                      % cid); sys.exit(1)
            os.makedirs(os.path.dirname(orig), exist_ok=True)
            shutil.copy(f, orig)
        shutil.copy(src, f)
        rec[str(cid)] = dict(rec.get(str(cid)) or {}, use=sd, manual=True, final_md5=_md5(W._final_file(kit, args.ep, cid)))
        print("cut %02d -> %s" % (cid, "original (before facefix)" if sd == 0 else "seed %d" % sd))
    with open(rec_p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print("then (again): nk ep backfix / restyle / letter %s" % args.ep)


def run(nk, kit, args):
    import argparse
    import nk_webtoon as W
    from PIL import Image
    import numpy as np
    if getattr(args, "use", None):
        return run_use(W, kit, args)
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    who = args.who or next((k for k, ch in (conti.get("_cast") or {}).items() if ch.get("lora")), None) \
        or (conti.get("_default_char") or {}).get("_key")
    if not who:
        print("[ERROR] which character? use --who"); sys.exit(1)
    wch = (conti.get("_cast") or {}).get(who) or {}
    if not wch and (conti.get("_default_char") or {}).get("_key") == who:     # 예전 콘티(chars 없음)
        wch = conti["_default_char"]
    if not args.who and not wch.get("lora"):
        print("nothing to do: no character with a LoRA in this episode (facefix redraws faces with the character LoRA). "
              "tag-only characters are skipped - use --who <name> to try anyway")
        return
    cuts_arg = [int(x) for x in args.cuts] if args.cuts else None
    boxes = {}
    for b in (getattr(args, "box", None) or []):
        try:
            k, v = b.split("=")
            x0, y0, x1, y1 = [float(t) for t in v.split(",")]
            assert x1 > x0 + 16 and y1 > y0 + 16
            boxes[int(k)] = (x0, y0, x1, y1)
        except Exception:
            print("[ERROR] --box needs cut=x0,y0,x1,y1, e.g. 5=830,0,1330,540"); sys.exit(1)
    if boxes:
        cuts_arg = sorted(set(cuts_arg or []) | set(boxes))
    den = float(args.denoise if args.denoise is not None else DENOISE)
    seed = args.seed if args.seed is not None else 41
    seeds = [seed + k for k in range(max(1, int(args.tries or 2)))]
    qa_cfg = cfg.get("qa", {})
    d = _fdir(W, kit, args.ep)
    rec_p = os.path.join(d, "facefix.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    work = os.path.join(d, "_work")
    os.makedirs(work, exist_ok=True)

    # 1) 대상 컷 + 머리 자리 (CPU: DWPose, 못 찾으면 SAM3)
    plan, pend = [], []
    for cut in conti["cuts"]:
        cid = int(cut["id"])
        if cuts_arg and cid not in cuts_arg:
            continue
        hit = _who(conti, cut, who)
        if not hit:
            if cuts_arg:
                print("[skip] cut %d: %s is not in this cut" % (cid, who))
            continue
        ch, role, span = hit
        f = W._final_file(kit, args.ep, cid)
        if not os.path.exists(f):
            print("[skip] cut %d: no final picture yet" % cid); continue
        pr = rec.get(str(cid)) or {}
        if not cuts_arg and not args.force and pr.get("final_md5") and pr.get("final_md5") == _md5(f):
            print("[skip] cut %d: unchanged since the last facefix (%s) - give the cut number to redo"
                  % (cid, "seed %s" % pr.get("use") if pr.get("use") else "original kept"))
            continue
        # 합치기(nk ep compose)로 만든 두 명 컷: 얼굴은 혼자 컷 최종본에서 옮겨 온 것 -> 기본은 안 고침.
        cp_ = os.path.join(W.ep_dir(kit, args.ep), "cuts_compose", "compose.json")
        if not cuts_arg and not args.force and os.path.exists(cp_):
            crec = (json.load(open(cp_, encoding="utf-8")).get(str(cid)) or {})
            if crec.get("final_md5") and crec.get("final_md5") == _md5(f):
                print("[skip] cut %d: made by compose (faces come from the solo pictures) - give the cut number to fix anyway" % cid)
                continue
        # 이미 고친 컷을 다시: '고치기 전 원본'에서 시작. 단 그 뒤에 컷을 새로 그렸으면(ep redo) 지금 최종본이 새 원본
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        prev = (rec.get(str(cid)) or {}).get("final_md5")
        if os.path.exists(orig) and _md5(f) in (prev, _md5(orig)):
            src = orig
        else:
            src = f
            if os.path.exists(orig):
                os.remove(orig)
        back = str(cut.get("angle", "")) == "back"
        if back and not args.force:
            print("[skip] cut %d: angle: back in the conti (--force to fix anyway)" % cid); continue
        try:
            import nk_backfix
            fb = nk_backfix._from_behind(nk, kit, src, cut, ch)
        except Exception as e:
            fb = None
            print("[WARN] cut %d: tagger gate failed (%s)" % (cid, e))
        if fb is not None and fb >= GATE_BACK:
            print("[skip] cut %d: %s faces away (from_behind %.2f)" % (cid, who, fb)); continue
        if back and fb is None:
            # 두 명 컷 angle: back 인데 판별기가 없음 -> 뒤통수에 얼굴을 그릴 위험 (검수 AI는 뒤통수를 '이마 무늬 없음'으로 불합격시킴)
            print("[skip] cut %d: angle: back and no tagger to check which way %s faces" % (cid, who)); continue
        wt, _ = _wear_tags(conti, cut, str(role.get("char")) if role else str(cut.get("_charkey") or who))
        if cid not in boxes and any(w in wt.lower() for w in ("hat", "headwear", "hood", "helmet", "cap")):
            print("[skip] cut %d: %s wears headwear here (%s) - facefix would cut through it" % (cid, who, wt)); continue
        w0, h0 = Image.open(src).size
        if cid in boxes:
            x0, y0, x1, y1 = boxes[cid]
            hb = (max(0.0, x0), max(0.0, y0), min(float(w0), x1), min(float(h0), y1))
            why = "manual box"
        elif SAM_FIRST or getattr(args, "sam", False):
            hb, why = None, "SAM3 first"
        else:
            hb, why = head_box(src, span)
        entry = {"cut": cut, "cid": cid, "ch": ch, "role": role, "src": src, "f": f, "orig": orig, "hb": hb,
                 "size": (w0, h0), "why": why, "span": span}
        if hb is None:
            pend.append(entry); continue       # SAM3 'head'로 찾음 (아래에서 한 번에)
        _plan_add(plan, entry, cuts_arg)
    if pend:
        found = _sam_heads(nk, kit, cfg, args.ep, pend, args.dry)
        for e in pend:
            hb, why = found.get(e["cid"], (None, "SAM3 not run (dry)"))
            if hb is None and not getattr(args, "sam", False):
                hb2, why2 = head_box(e["src"], e["span"])      # SAM3가 못 찾으면 예전 방식(DWPose 어깨)
                if hb2 is not None:
                    hb, why = hb2, "DWPose (SAM3: %s)" % why
            if hb is None:
                print("[skip] cut %d: %s" % (e["cid"], why)); continue
            e.update(hb=hb, why=why)
            _plan_add(plan, e, cuts_arg)
    if getattr(args, "boxes", False):
        _save_boxes(W, kit, args.ep, plan)
        return
    if not plan:
        print("[ERROR] nothing to do"); sys.exit(1)

    # 2) 원본 머리 검수 (이미 합격이면 안 고침)
    heads = {}
    for p in plan:
        cx0, cy0, L, m = _crop_and_mask(p["size"][0], p["size"][1], p["hb"])
        p.update(cx0=cx0, cy0=cy0, L=L, mask=m)
        hp = os.path.join(work, "cut%02d_head_orig.png" % p["cid"])
        im = Image.open(p["src"]).convert("RGB")
        im.crop((cx0, cy0, cx0 + L, cy0 + L)).save(hp)
        heads[p["cid"]] = hp
        p["judge_img"] = _masked_head(im, cx0, cy0, L, m, os.path.join(work, "cut%02d_head_orig_m.png" % p["cid"]))
    todo = []
    if not args.dry:
        for p in plan:
            p["expect"] = _expr_expect(_expr_tags(nk, cfg, p["cut"], p["role"]))
            ok, sc, info = _judge(nk, kit, qa_cfg, p["ch"], p["judge_img"], p["expect"])
            p["orig_judge"], p["orig_score"] = info, sc
            print("cut %d: original head %s %s" % (p["cid"], {True: "PASS", False: "FAIL", None: "(no check)"}[ok], info))
            if ok and not args.force:
                print("   -> already fine, not changed (--force to fix anyway)")
                rec[str(p["cid"])] = dict(rec.get(str(p["cid"])) or {}, skipped="original passes", orig_judge=info)
                continue
            todo.append(p)
        nk.ollama_unload(qa_cfg)
    else:
        todo = plan
    if not todo:
        with open(rec_p, "w", encoding="utf-8") as fo:
            json.dump(rec, fo, ensure_ascii=False, indent=1)
        print("nothing needs fixing"); return

    # 3) 머리만 다시 그리기 (ComfyUI)
    jobs = []
    for p in todo:
        cut, ch, cid = p["cut"], p["ch"], p["cid"]
        ns = argparse.Namespace(preset=cut.get("artist", conti.get("artist")), extra=None, neg=None, lora=None,
                                size=W._gen_size(cut["size"]), rating=None, cfg=cut.get("cfg"), steps=None, sampler=None,
                                scheduler=None, quality=None, year=None, artist=None, artist_weight=None, artist_position=None,
                                tags=None, strength=None, charlora=None, hires=0, hires_denoise=None, hires_steps=None,
                                hires_method=None, upscale_model=None)
        s = nk.build_settings(cfg, ns)
        ff = ch.get("facefix") or {}
        key = str(p["role"].get("char")) if p["role"] else str(cut.get("_charkey") or who)
        wt, wn = _wear_tags(conti, cut, key)
        et = _expr_tags(nk, cfg, cut, p["role"])
        if "@_@" in _expr_expect(et) and "@_@" not in et:
            et = et + ["(@_@:1.2)"]          # 빙글빙글 눈은 태그 사전 이름(@_@)을 같이 줘야 잘 나옴 (spiral eyes만으로는 LoRA 눈이 이김)
        scene = ", ".join(x for x in ["portrait, face focus", ", ".join(et), wt, ff.get("tags", "")] if x)
        pos, neg = nk.compose_prompt(s, ch, scene)
        if wn:
            neg = nk.clean_tags(neg + ", " + wn)
        if ff.get("drop"):
            dl = [x.strip().lower() for x in str(ff["drop"]).split(",") if x.strip()]
            pos = ", ".join(t for t in [x.strip() for x in pos.split(",")] if t and not any(w in t.lower() for w in dl))
        if ff.get("neg"):
            neg = nk.clean_tags(neg + ", " + ff["neg"])
        if getattr(args, "sharp", False):
            neg = nk.clean_tags(neg + ", " + SHARP_NEG)
        cp = os.path.join(work, "cut%02d_crop.png" % cid)
        mp = os.path.join(work, "cut%02d_mask.png" % cid)
        Image.open(heads[cid]).resize((RES, RES), Image.LANCZOS).save(cp)
        Image.fromarray(p["mask"]).resize((RES, RES), Image.BILINEAR).convert("RGB").save(mp)
        img = W._upload_input(nk, cfg, cp, "%s_cut%02d_ffcrop.png" % (args.ep, cid), args.dry)
        msk = W._upload_input(nk, cfg, mp, "%s_cut%02d_ffmask.png" % (args.ep, cid), args.dry)
        for sd in seeds:
            label = "cut%02d_s%d" % (cid, sd)
            g = _graph(cfg, s, ch, pos, neg, img, msk, sd, den, "nk/%s_facefix/%s" % (args.ep, label))
            jobs.append({"label": label, "graph": g, "positive": pos, "negative": neg, "seed": sd,
                         "settings": {"cfg": s["cfg"], "steps": s["steps"], "width": RES, "height": RES}})
        print("cut %d (%s): head box %s, crop %d px at (%d, %d) -> %d px, denoise %.2f | %s"
              % (cid, who, [int(v) for v in p["hb"]], p["L"], p["cx0"], p["cy0"], RES, den, p["why"]))
    print("facefix %s: %d cuts x %d seeds %s (~40 s each)" % (args.ep, len(todo), len(seeds), seeds))
    res = nk.run_jobs(cfg, jobs, "%s/facefix" % args.ep, args.dry)
    if args.dry:
        return
    try:
        nk.Comfy(cfg.get("server", "auto")).free()     # 검수 AI(VLM)가 GPU를 쓸 수 있게
    except Exception as e:
        print("[WARN] could not free ComfyUI models:", e)

    # 4) 붙이기 + 검수 + 고르기
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "facefix")
    os.makedirs(os.path.join(d, "cand"), exist_ok=True)
    os.makedirs(os.path.join(d, "orig"), exist_ok=True)
    by = {p["cid"]: p for p in todo}
    made = {}
    for r in res:
        cid = int(r["label"][3:5])
        p = by[cid]
        L = p["L"]
        new = Image.open(os.path.join(out_dir, r["file"])).convert("RGB").resize((L, L), Image.LANCZOS)
        base = Image.open(p["src"]).convert("RGB")
        old_crop = base.crop((p["cx0"], p["cy0"], p["cx0"] + L, p["cy0"] + L))
        base.paste(new, (p["cx0"], p["cy0"]), Image.fromarray(p["mask"]))
        blur = _bg_detail_ratio(old_crop, base.crop((p["cx0"], p["cy0"], p["cx0"] + L, p["cy0"] + L)), p["mask"])
        cpath = os.path.join(d, "cand", r["label"] + ".png")
        base.save(cpath)
        # 검수용: 원본 머리 | 고친 머리 (같은 크기)
        hd = Image.new("RGB", (2 * L + 8, L), "white")
        hd.paste(Image.open(heads[cid]), (0, 0))
        hd.paste(base.crop((p["cx0"], p["cy0"], p["cx0"] + L, p["cy0"] + L)), (L + 8, 0))
        hd.save(os.path.join(d, "cand", r["label"] + "_head.png"))
        hp = _masked_head(base, p["cx0"], p["cy0"], L, p["mask"], os.path.join(work, r["label"] + "_head_new_m.png"))
        made.setdefault(cid, []).append((r["seed"], hp, blur))
    for cid, lst in made.items():
        p = by[cid]
        checks = {}
        best = None
        for sd, hp, blur in lst:
            ok, sc, info = _judge(nk, kit, qa_cfg, p["ch"], hp, p.get("expect"))
            if blur < BLUR_MIN:
                ok = False
                info["blur"] = "background blurred (detail %.2f < %.2f)" % (blur, BLUR_MIN)
            if ok and PAIR_VETO:
                # 판별기 합격이어도 검수 AI에게 '고치기 전|후 비교'로 한 번 더 물음. 깨졌다고 하면 안 씀 (거부권만)
                try:
                    bad, ans = _pair_check(nk, qa_cfg, os.path.join(d, "cand", "cut%02d_s%d_head.png" % (cid, sd)))
                    info["pair"] = ans
                    if bad:
                        ok = False
                        info["pair_veto"] = "before|after check says the new face is broken"
                except Exception as e:
                    info["pair_err"] = str(e)
            checks[str(sd)] = {"pass": ok, "score": sc, "judge": info, "bg_detail": blur, "_good": _good_sum(info)}
            print("cut %d seed %d: %s score %.2f bg_detail %.2f %s" % (cid, sd, {True: "PASS", False: "FAIL", None: "(no check)"}[ok],
                                                                     sc, blur, info))
            if ok is not False and (best is None or sc > best[1]):
                best = (sd, sc)
        pick = best[0] if best else None
        rescue = None
        og = _good_sum(p.get("orig_judge") or {})
        if pick is None and og is not None and og < RESCUE_ORIG_MAX:
            for sd, hp, blur in lst:
                c = checks[str(sd)]
                g = c.get("_good")
                if g is None or g - og < RESCUE_GAIN or blur < BLUR_MIN or (c["judge"].get("tagger") or {}).get("bad"):
                    continue
                if PAIR_VETO and "pair" not in c["judge"]:
                    try:
                        bad, ans = _pair_check(nk, qa_cfg, os.path.join(d, "cand", "cut%02d_s%d_head.png" % (cid, sd)))
                        c["judge"]["pair"] = ans
                        if bad:
                            c["judge"]["pair_veto"] = "before|after check says the new face is broken"
                            continue
                    except Exception as e:
                        c["judge"]["pair_err"] = str(e)
                if rescue is None or g > rescue[1]:
                    rescue = (sd, g)
            if rescue:
                pick = rescue[0]
                print("cut %02d: no candidate reached the pass line, but the original face is broken (mark %.2f) and seed %d is "
                      "clearly better (mark %.2f) -> using it (rescue, check it)" % (cid, og, rescue[0], rescue[1]))
        for c in checks.values():
            c.pop("_good", None)
        entry = {"seeds": [x[0] for x in lst], "checks": checks, "denoise": den, "head_box": [int(v) for v in p["hb"]],
                 "orig_judge": p.get("orig_judge"), "orig_score": p.get("orig_score")}
        if rescue:
            entry["rescue"] = {"orig_mark": round(og, 2), "mark": round(rescue[1], 2)}
        if pick is None:
            entry.update(use=0, final_md5=_md5(p["f"]))
            print("[WARN] cut %02d: no candidate passed the face check - final left as it was. look at cuts_facefix/cand/"
                  "*_head.png and choose with --use" % cid)
        else:
            if not os.path.exists(p["orig"]):
                shutil.copy(p["f"], p["orig"])
            shutil.copy(os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, pick)), p["f"])
            entry.update(use=pick, final_md5=_md5(p["f"]))
            print("cut %02d: final <- seed %d. original kept in %s" % (cid, pick, p["orig"]))
        rec[str(cid)] = entry
    nk.ollama_unload(qa_cfg)
    with open(rec_p, "w", encoding="utf-8") as fo:
        json.dump(rec, fo, ensure_ascii=False, indent=1)
    print("look at %s (*_head.png = before | after), choose: nk ep facefix %s --use <cut>=<seed>  (0 = before facefix)."
          " then nk ep backfix / restyle / letter" % (os.path.join(d, "cand"), args.ep))


BROKEN_Q = ("This is a close-up of the head of a cartoon cat character. Judge ONLY the drawing quality, not the design. "
            "Answer with a JSON object with exactly these keys:\n"
            '  "eyes": one of "two normal eyes", "one eye closed (wink)", "eyes mismatched, melted or misplaced"\n'
            '  "face": one of "clean", "distorted, smeared or melted"\n'
            '  "ears": one of "clean ears", "extra, ghost or broken ears"\n'
            "No explanations.")


# 작은 VLM은 절대 판단보다 비교가 나을 수 있어서, 고치기 전(왼쪽)|후(오른쪽)를 같이 보여 주고 차이를 물음
PAIR_Q = ("Two pictures of the same cartoon cat head side by side: LEFT = before, RIGHT = after a repaint. "
          "Compare the RIGHT picture with the LEFT one and judge ONLY drawing mistakes, not style or expression. "
          "Answer with a JSON object with exactly these keys:\n"
          '  "eyes": one of "both eyes drawn well", "one eye bigger, melted or oddly shaped"\n'
          '  "smear": one of "no smears", "color smears or blobs on the face"\n'
          '  "ears": one of "normal ears", "extra, ghost or broken ear"\n'
          '  "cleaner": one of "right", "left"\n'
          "No explanations.")


PAIR_VETO = True


def _pair_check(nk, qa_cfg, head_png):
    q = dict(qa_cfg)
    q["num_ctx"] = 4096
    raw = nk.ollama_ask(q, nk._img_b64(head_png, 1024), PAIR_Q)
    ans = nk.parse_answers(raw, ["eyes", "smear", "ears", "cleaner"])
    first = lambda k: str(ans.get(k, "")).strip().lower().split(" ")[0]
    bad = first("eyes") == "one" or first("smear") == "color" or first("ears") == "extra" or first("cleaner") == "left"
    return bad, ans


def run_facecheck(nk, kit, args):
    import nk_webtoon as W
    from PIL import Image
    cfg = nk.load_presets()
    q = dict(cfg.get("qa", {}))
    q["num_ctx"] = 4096
    d = _fdir(W, kit, args.ep)
    files = args.files or sorted(f for f in os.listdir(os.path.join(d, "cand")) if f.endswith("_head.png"))
    tmp = os.path.join(d, "_work", "_fc.png")
    rows = []
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(d, "cand", f)
        if not os.path.exists(p):
            print("[skip] no", p); continue
        im = Image.open(p).convert("RGB")
        pair = getattr(args, "pair", False)
        if not args.whole and not pair:          # *_head.png = 고치기 전 | 후 -> 오른쪽(고친 뒤)만
            im = im.crop((im.width // 2 + 4, 0, im.width, im.height))
        im.save(tmp)
        if pair:
            raw = nk.ollama_ask(q, nk._img_b64(tmp, 1024), PAIR_Q)
            ans = nk.parse_answers(raw, ["eyes", "smear", "ears", "cleaner"])
            first = lambda k: str(ans.get(k, "")).strip().lower().split(" ")[0]
            bad = first("eyes") == "one" or first("smear") == "color" or first("ears") == "extra" or first("cleaner") == "left"
        else:
            raw = nk.ollama_ask(q, nk._img_b64(tmp, 768), BROKEN_Q)
            ans = nk.parse_answers(raw, ["eyes", "face", "ears"])
            bad = any(str(ans.get(k, "")).split(",")[0].split(" ")[0] in ("eyes", "distorted", "extra") for k in ("eyes", "face", "ears"))
        rows.append((f, "BROKEN" if bad else "ok", ans))
        print("%-26s %-6s %s" % (f, "BROKEN" if bad else "ok", ans))
    nk.ollama_unload(q)
    json.dump([{"file": f, "verdict": v, "answer": a} for f, v, a in rows],
              open(os.path.join(d, "facecheck.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
