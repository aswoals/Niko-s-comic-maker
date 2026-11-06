# -*- coding: utf-8 -*-
"""LoRA 없는 두 명 컷 '나눠 그리기'

왜: 두 사람을 글 하나로 한 번에 그리면 두 캐릭터의 생김새·옷이 서로 섞인다 (한 사람 옷 색이 상대에게 번지는 등).
    LoRA 캐릭터가 나오는 두 명 컷은 이미 나눠 그렸지만(nk_regionlora --split), LoRA 없는 두 사람은 한 번에 그렸다.
    이 파일이 그 틈을 메운다: 두 명 컷은 어떤 조합이든 나눠 그린다.

하는 일 (컷 하나):
  ① 기준 그림: 지금 글 그대로, LoRA 없음 (euler / sgm_uniform = 다음 단계 RegionalSampler 의 처음 걸음과 같은 샘플러·시드)
  ② SAM3 로 두 사람 자리를 찾음 (콘티의 left/right 쪽에 중심이 있는 조각)
  ③ 구역 틀: 한 사람 조각에서 상대 조각을 빼고 3% 넓힌 뒤 상대 조각을 다시 뺌. 두 틀이 겹친 곳은 양쪽에서 뺌
  ④ Impact Pack RegionalSampler: 처음 base_only 걸음 = 전체 글(구도·누가 무엇을 하나), 그 뒤 = 사람마다 자기 틀 안에서 자기 글만
  콘티가 3D 인형 자세(pose3d)를 쓰면 기준 그림과 ④ 둘 다 같은 인형 조종을 받음 (nk_regionlora 와 같음).
결과: episodes/<편>/cuts/cutNN.png (최종), cuts_base/cutNN.png (기준 그림), duosplit.json (기록),
      regionlora.json 의 그 컷 spans (말풍선 꼬리가 가리킬 실제 좌우 자리 — 글자 단계가 읽음)
나누기가 안 되면 (SAM3 가 두 사람을 못 찾음 / 한 사람 구역이 너무 작음 / 나눠 그리기 작업 실패)
  -> 기준 그림을 최종으로 쓰고 duosplit.json 에 ok:false 와 이유를 적고 화면에 [WARN].

사용: 따로 부를 일 없음. nk ep auto (작업실의 만들기·컷 다시 그리기·후보 그리기 포함)가 LoRA 없는 두 명 컷을 그릴 때 부른다.
  직접 부르기: nk ep duosplit <편> [컷...] [--force] [--dry]   (--dry = 그리지 않고 기준 글·구역 글만 보여 줌)
  끄기: duosplit_settings.yaml 의 enabled: false, 또는 계획표(plan.yaml)·콘티(conti.yaml)에 duo_split: off -> 예전처럼 한 번에 그림
  Impact Pack(RegionalSampler 등)이 ComfyUI 에 없으면 경고 한 줄을 내고 그 컷들은 예전처럼 한 번에 그림 (멈추지 않음).

설정 파일: duosplit_settings.yaml (presets.yaml 옆) — enabled, min_region, steps, base_only, cfg, overlap.
  코드를 몰라도 숫자만 고치면 됨. 파일이 없거나 틀리면 [WARN] 을 내고 처음 값으로 그림.

에러가 나면:
  [WARN] ComfyUI 에 나눠 그리기 노드(...)가 없음 -> 오류가 아님. 두 명 컷을 예전처럼 한 번에 그렸음.
                                              나눠 그리려면 ComfyUI-Impact-Pack 을 깔고 ComfyUI 를 다시 켠 뒤 그 컷을 다시 그리기.
                                              (SAM3_Detect 만 없다고 나오면 ComfyUI 를 최신판으로)
  [WARN] cutNN: 나누기 실패 ...              -> 오류가 아님. 그 컷은 기준 그림(한 번에 그린 그림)이 최종.
                                              '다시 그리기'를 누르면 새 시드로 다시 나눠 봄.
                                              ('region too small' = 한 사람 구역이 min_region 보다 작음 — 일부러 그런 것)
  [WARN] duosplit_settings.yaml 를 못 읽음   -> 숫자·글자가 틀림. 처음 값으로 그렸음. 줄 앞 공백·콜론·숫자 범위를 확인.
  [ERROR] cutNN: no base image               -> ComfyUI 가 그림을 못 냈음. ComfyUI 창의 빨간 글을 확인.
                                              연달아 3번이면 멈춤 (고친 뒤 다시 하면 이어서 함)."""
import os
import re
import sys
import json
import time
import shutil

SETTINGS_FILE = "duosplit_settings.yaml"
DEFAULTS = {"enabled": True, "min_region": 0.08, "steps": 25, "base_only": 12, "cfg": 5.0, "overlap": 10}
DROP_TAGS = {"duo", "solo", "1boy", "1girl", "2boys", "2girls", "furry", "anthro"}   # nk_regionlora.lora_region_text 와 같은 목록
IMPACT_NODES = ("RegionalSampler", "CombineRegionalPrompts", "RegionalPrompt", "KSamplerAdvancedProvider", "ToBasicPipe")
NEED_NODES = IMPACT_NODES + ("SAM3_Detect",)
SWALLOWED = 0.5       # 상대 조각이 이 사람 조각의 이만큼 이상을 품는데, 그 조각 자신은 이 사람 조각 안에 거의 다 들지 않으면
#                       (covered < COVERED_WARN) = 두 사람을 한 덩어리로 잡은 것 -> 상대가 아님, 버리고 다음 조각·말로
OFF_WORDS = ("false", "0", "off", "no", "none")
WARN_NO_IMPACT = ("[WARN] ComfyUI 에 나눠 그리기 노드(%s)가 없음 -> LoRA 없는 두 명 컷 %s 은 예전처럼 한 번에 그림 "
                  "(나눠 그리려면 ComfyUI-Impact-Pack 을 깔고 ComfyUI 를 다시 켠 뒤 그 컷을 다시 그리기)")


# ---------------------------------------------------------------- 설정 (duosplit_settings.yaml)
def load_settings(kit, log=print):
    """-> {enabled, min_region, steps, base_only, cfg, overlap}. 파일이 없거나 틀리면 DEFAULTS (틀리면 [WARN])"""
    S = dict(DEFAULTS)
    pth = os.path.join(kit, SETTINGS_FILE)
    if not os.path.isfile(pth):
        return S
    try:
        import yaml
        d = yaml.safe_load(open(pth, encoding="utf-8")) or {}
        if not isinstance(d, dict):
            raise ValueError("이름: 값 꼴이 아님")

        def num(k, lo, hi, kind):
            if d.get(k) is None:
                return
            v = kind(d[k])
            if isinstance(d[k], bool) or not lo <= v <= hi or (kind is int and float(d[k]) != v):
                raise ValueError("%s 는 %s ~ %s 사이 %s (지금 %r)" % (k, lo, hi, "정수" if kind is int else "숫자", d[k]))
            S[k] = v
        if d.get("enabled") is not None:
            S["enabled"] = str(d["enabled"]).strip().lower() not in OFF_WORDS
        num("min_region", 0.0, 0.5, float)
        num("steps", 4, 100, int)
        num("base_only", 1, 99, int)
        num("cfg", 1.0, 15.0, float)
        num("overlap", 0, 64, int)
    except Exception as e:
        log("[WARN] %s 를 못 읽음 (%s) - 처음 값으로 그림" % (SETTINGS_FILE, str(e)[:160]))
        return dict(DEFAULTS)
    return S


def enabled(kit, conti=None, plan_path=None, log=print):
    """두 명 컷을 나눠 그리나 -> (True/False, 이유). 설정 파일 enabled + 만화마다 duo_split (콘티 > 계획표)"""
    if not load_settings(kit, log)["enabled"]:
        return False, "%s enabled: false" % SETTINGS_FILE
    v = (conti or {}).get("duo_split")
    if v is None and plan_path and os.path.isfile(plan_path):
        try:
            import yaml
            v = (yaml.safe_load(open(plan_path, encoding="utf-8")) or {}).get("duo_split")
        except Exception:
            v = None
    if v is not None and str(v).strip().lower() in OFF_WORDS:
        return False, "duo_split: off (plan/conti)"
    return True, ""


def missing_nodes(c_, names=NEED_NODES):
    """ComfyUI(nk.Comfy) 에 없는 노드 이름 목록 (object_info 로 확인, 확인이 안 되면 없는 것으로 봄)"""
    miss = []
    for n in names:
        try:
            if n not in (c_._get("/object_info/" + n) or {}):
                miss.append(n)
        except Exception:
            miss.append(n)
    return miss


# ---------------------------------------------------------------- 컷 고르기
def cut_chars(cut):
    return [ch for _, ch in (cut.get("_roles") or []) if ch]


def is_duo(cut):
    """캐릭터 파일이 있는 사람이 꼭 두 명인 컷"""
    return len(cut_chars(cut)) == 2


def has_lora(cut):
    return any(ch.get("anima_lora") for ch in cut_chars(cut))


# ---------------------------------------------------------------- 글
def _dedupe(parts):
    """쉼표 목록 여러 개 -> 겹치는 태그를 뺀 쉼표 목록 하나 (앞에 나온 것을 남김)"""
    out, seen = [], set()
    for p in parts:
        for t in str(p or "").split(","):
            t = t.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return ", ".join(out)


def region_text(A, W, conti, cut, ch, role, artist, look=False):
    """구역 글 = 머리말(품질·safe·작가·인원·종) + 캐릭터 태그 + 행위 태그 + 그 사람의 pos + 컷 거리에 맞는 캐릭터 설명.
    행위 문장(anima_act)은 안 넣음 — 구도·누가 무엇을 하나는 처음 base_only 걸음의 전체 글이 정함 (LoRA 쪽 나눠 그리기와 같음).
    A = nk_animacut, W = nk_webtoon 모듈. look = 이 사람이 상대를 보는 컷 (nk_animacut.gaze_people)"""
    pos = str(role.get("pos", "")).strip()
    d = A.shot_desc(ch, cut.get("shot"), A.is_back(cut)) or ch.get("anima") or ch.get("anima_upper") or ""
    d = A.drop_eyes(ch, d, pos).strip().rstrip(".")
    act = [t.strip() for t in str(cut.get("scene", "")).split(",") if t.strip() and t.strip().lower() not in DROP_TAGS]
    ctag = ""
    if A.char_tags_on(conti) and not ch.get("anima_lora"):          # 두 명 컷의 핵심 태그는 사람별 글에 (nk_animacut.cut_text 와 같은 규칙)
        ctag = ", ".join(x for x in (str(ch.get("trigger") or "").strip(), str(ch.get("tags_full") or "").strip()) if x)
    tags = _dedupe(["masterpiece, best quality, score_7, safe", ("@" + artist.lstrip("@")) if artist else "",
                    str(conti.get("anima_tags") or ""), W.head_tags(ch), ctag, "looking at another" if look else "",
                    ", ".join(act), pos])
    return "%s. %s." % (tags, d) if d else tags + "."


def cut_neg(A, conti, cut, s=None):
    """부정어 = 한 번에 그릴 때(nk_animacut.run)와 같은 규칙: 기본 + 만화 전체 + 컷·장소 neg + 시선·손 극근접·당기기·캐릭터 부정어"""
    neg = A.cut_neg(s, conti) if (s is not None and hasattr(A, "cut_neg")) else A.neg_for(conti)
    if any(A.gaze_people(conti, cut)) and "looking at viewer" not in str(cut.get("scene") or "").lower():
        neg += ", looking at viewer"
    if str(cut.get("shot")) == "hands":
        neg += ", self grab, holding own wrist"
        neg += ", face, head, eyes, hair, split screen, multiple views, 2koma"
    words = " ".join(str(cut.get(k) or "") for k in ("scene", "anima_act")) + " " + " ".join(str(r.get("pos") or "") for r, _ in (cut.get("_roles") or []))
    if re.search(r"(^|[ ,])pulling([ ,]|$)", words):
        neg += ", tail pull, holding another's tail"
    cn = A.char_negs(conti, cut)
    if cn:
        neg += ", " + cn
    return neg


def pose_flags(A, conti, cut):
    """3D 인형 자세를 한 번에 그릴 때(nk_animacut.run)와 똑같이 잡으려고 같은 표시를 컷에 붙임"""
    if str(conti.get("pose3d_arms") or "") == "all":
        cut["_arms_all"] = True
    if A.gaze_mode(conti) == "v2":
        cut["_gaze"] = A.gaze_people(conti, cut)
    hy = conti.get("hug_yaw", 35)
    if hy not in (None, "", "off", False):
        cut["_hug_yaw"] = float(hy)


# ---------------------------------------------------------------- ComfyUI 그림 틀 (nk_regionlora.split_graph 에서 LoRA 를 뺀 것)
def duo_graph(T, p, base_text, text_a, text_b, neg, mask_a_img, mask_b_img, w, h, seed, sampler, sched, prefix="nk/duo_split"):
    """p = {unet, steps, cfg, base_only, overlap}. T = nk_animatest 모듈(CLIP·VAE 이름). 결과 이미지는 노드 '10'.
    부정어(노드 6)는 ToBasicPipe 의 negative 로 연결됨 -> nk.safe_graph 가 부정어로 알아봄"""
    def prov(pipe):
        return {"class_type": "KSamplerAdvancedProvider", "inputs": {"cfg": float(p["cfg"]), "sampler_name": sampler, "scheduler": sched,
                                                                      "sigma_factor": 1.0, "basic_pipe": [pipe, 0]}}

    def pipe(pos):
        return {"class_type": "ToBasicPipe", "inputs": {"model": ["1", 0], "clip": ["2", 0], "vae": ["3", 0], "positive": [pos, 0], "negative": ["6", 0]}}
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": T.CLIP, "type": "lumina2", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": T.VAE}},
         "5": {"class_type": "CLIPTextEncode", "inputs": {"text": base_text, "clip": ["2", 0]}},
         "6": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["2", 0]}},
         "7": {"class_type": "CLIPTextEncode", "inputs": {"text": text_a, "clip": ["2", 0]}},
         "12": {"class_type": "CLIPTextEncode", "inputs": {"text": text_b, "clip": ["2", 0]}},
         "40": pipe("5"), "41": pipe("7"), "50": pipe("12"),
         "42": prov("40"), "43": prov("41"), "51": prov("50"),
         "44": {"class_type": "LoadImage", "inputs": {"image": mask_a_img}},
         "45": {"class_type": "ImageToMask", "inputs": {"image": ["44", 0], "channel": "red"}},
         "46": {"class_type": "RegionalPrompt", "inputs": {"mask": ["45", 0], "advanced_sampler": ["43", 0]}},
         "52": {"class_type": "LoadImage", "inputs": {"image": mask_b_img}},
         "53": {"class_type": "ImageToMask", "inputs": {"image": ["52", 0], "channel": "red"}},
         "54": {"class_type": "RegionalPrompt", "inputs": {"mask": ["53", 0], "advanced_sampler": ["51", 0]}},
         "47": {"class_type": "CombineRegionalPrompts", "inputs": {"regional_prompts1": ["46", 0], "regional_prompts2": ["54", 0]}},
         "48": {"class_type": "EmptySD3LatentImage", "inputs": {"width": int(w), "height": int(h), "batch_size": 1}},
         "49": {"class_type": "RegionalSampler", "inputs": {"seed": int(seed), "seed_2nd": 0, "seed_2nd_mode": "ignore", "steps": int(p["steps"]),
                                                          "base_only_steps": int(p["base_only"]), "denoise": 1.0, "samples": ["48", 0],
                                                          "base_sampler": ["42", 0], "regional_prompts": ["47", 0], "overlap_factor": int(p["overlap"]),
                                                          "restore_latent": True, "additional_mode": "DISABLE", "additional_sampler": "AUTO",
                                                          "additional_sigma_ratio": 0.3}},
         "9": {"class_type": "VAEDecode", "inputs": {"samples": ["49", 0], "vae": ["3", 0]}},
         "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["9", 0]}}}
    return g


# ---------------------------------------------------------------- 조각 고르기 (SAM3 결과 -> 두 사람 조각). get_pieces 를 넘겨받아 SAM3 없이도 시험 가능
def overlap_stats(RL, mine, part):
    """nk_regionlora.overlap_stats + swallow (이 사람 조각 중 상대 조각 안에 든 몫)"""
    st = dict(RL.overlap_stats(mine, part))
    ms = int(mine.sum())
    st["swallow"] = round(int((mine & part).sum()) / ms, 4) if ms else None
    return st


def pick_side_piece(pieces, side):
    """SAM3 조각들 중 콘티의 side(left/right) 쪽에 중심이 있는 가장 큰 조각 (넓이 2~60% 만).
    SAM 의 첫 조각이 상대인 일이 있어서 순서 대신 자리로 고름.
    -> (조각, {side, n, index, cover, cx}) 또는 (None, {side, n, why})"""
    import numpy as np
    info = {"side": side, "n": len(pieces)}
    if side not in ("left", "right"):
        return None, dict(info, why="no side")
    best = None
    for i, pm in enumerate(pieces):
        cov = float(pm.mean())
        if not (0.02 <= cov <= 0.6) or not pm.any():
            continue
        cx = float(np.nonzero(pm)[1].mean()) / pm.shape[1]
        if (cx >= 0.5) != (side == "right"):
            continue
        if best is None or cov > best[1]:
            best = (i, cov, cx)
    if best is None:
        return None, dict(info, why="no piece on that side")
    return pieces[best[0]], dict(info, index=best[0], cover=round(best[1], 4), cx=round(best[2], 3))


def _pick(get_pieces, words, side, avoid, RL, log):
    """한 사람의 조각: 말 순서대로 SAM3 조각을 받아, (상대 조각이 있으면) 상대와 같은 사람·상대를 품은 덩어리는 거르고,
    pick_side_piece 로 고름. -> (조각, 정보) 또는 (None, {'why': ...})"""
    why = []
    for fw in words:
        pcs = get_pieces(fw)
        keep = []
        for k, pm in enumerate(pcs):
            if avoid is not None:
                st = overlap_stats(RL, avoid, pm)
                if st["iou"] >= RL.SAME_AS_LORA:
                    why.append("'%s' piece %d = same figure as the other (iou %.2f)" % (fw, k, st["iou"]))
                    continue
                if (st.get("swallow") or 0) >= SWALLOWED and (st["covered"] or 0) < RL.COVERED_WARN:
                    why.append("'%s' piece %d holds the other figure (swallow %.2f)" % (fw, k, st["swallow"]))
                    continue
            keep.append(pm)
        pm, info = pick_side_piece(keep, side)
        if pm is not None:
            return pm, dict(info, word=fw)
        why.append("'%s': %s (%d pieces, %s side)" % (fw, info.get("why"), len(pcs), side))
        log("      %s" % why[-1])
    return None, {"why": "; ".join(why) or "no words"}


def find_two(get_pieces, words_a, words_b, side_a, side_b, RL, log=print):
    """-> (조각 A, 조각 B, 정보). 못 찾으면 (None, None, {'ok': False, 'why': ...})"""
    ma, ia = _pick(get_pieces, words_a, side_a, None, RL, log)
    if ma is None:
        return None, None, {"ok": False, "why": "A not found: " + ia["why"]}
    mb, ib = _pick(get_pieces, words_b, side_b, ma, RL, log)
    if mb is None:
        return None, None, {"ok": False, "why": "B not found: " + ib["why"], "A": ia}
    st = overlap_stats(RL, ma, mb)
    return ma, mb, {"ok": True, "A": ia, "B": ib, "iou": st["iou"], "B_inside_A": st["covered"], "A_inside_B": st["swallow"]}


def region_masks(ma, mb, grow_frac, min_region=None):
    """-> (틀 A, 틀 B, 정보) bool 배열. 한 사람 조각에서 상대 조각을 빼고 넓힌 뒤 상대 조각을 다시 빼고, 두 틀이 겹친 곳은 양쪽에서 뺌.
    min_region = 구역 최소 크기 (그림 대비 비율, 없으면 설정 파일의 처음 값). 둘 중 하나라도 작으면 info['ok'] = False"""
    import numpy as np
    from PIL import Image, ImageFilter
    min_region = DEFAULTS["min_region"] if min_region is None else float(min_region)
    h, w = ma.shape
    k = max(3, int(max(h, w) * grow_frac)) | 1

    def grow(m):
        return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(k))) > 127
    ga = grow(ma & ~mb) & ~mb
    gb = grow(mb & ~ma) & ~ma
    ov = ga & gb
    ga, gb = ga & ~ov, gb & ~ov
    tot = float(h * w)
    info = {"cover_A": round(float(ga.sum()) / tot, 4), "cover_B": round(float(gb.sum()) / tot, 4), "overlap_removed": round(float(ov.sum()) / tot, 4)}
    info["ok"] = bool(info["cover_A"] >= min_region and info["cover_B"] >= min_region)
    if not info["ok"]:
        info["why"] = "region too small (A %.2f%%, B %.2f%%, min %.1f%%)" % (100 * info["cover_A"], 100 * info["cover_B"], 100 * min_region)
    return ga, gb, info


def span(m):
    """조각 틀 -> 그림 너비 대비 [왼, 오른] (가로 10~90 백분위). 말풍선 꼬리 자리용 (nk_regionlora.mask_spans 와 같은 방식)"""
    import numpy as np
    m = np.asarray(m)
    cols = np.nonzero(m)[1]
    if len(cols) == 0:
        return None
    w = float(m.shape[1])
    return [round(float(np.percentile(cols, 10)) / w, 3), round(float(np.percentile(cols, 90)) / w, 3)]


def png_ok(p):
    try:
        from PIL import Image
        with Image.open(p) as im:
            im.verify()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 컷 하나
def _base_sig(text, neg, w, h, seed, p, ctl):
    """기준 그림을 다시 써도 되는지 보는 표 (글·부정어·크기·시드·모델·걸음·인형 조종이 같아야 재사용)"""
    return {"text": text, "negative": neg, "size": [int(w), int(h)], "seed": int(seed), "unet": p["unet"], "steps": int(p["steps"]),
            "cfg": float(p["cfg"]), "control": {k: v for k, v in sorted((ctl or {}).items())}}


def _base_reusable(bp, sig):
    try:
        return png_ok(bp) and json.load(open(bp[:-4] + ".json", encoding="utf-8")) == json.loads(json.dumps(sig))
    except Exception:
        return False


def split_one(env, cut, text, neg, w, h, seed, tag, outdir, to, p, artist, ctl=None, log=print, label=None):
    """env = {nk, kit, cfg, conti, c_(nk.Comfy), W, A, T, RL, SAM, S(설정)}. ctl = 3D 인형 조종 (nk_regionlora.pose_control, 없으면 {}).
    -> dict: ok(나눠 그렸나), why, base(기준 그림 경로), final(나눈 그림 경로 | None), 정보들.
    기준 그림이 안 나오면 base 없이 돌려줌 (부르는 쪽이 오류로 셈). 그 뒤 단계가 실패하면 ok False + why (기준 그림은 살림)"""
    import numpy as np
    from PIL import Image
    nk, kit, cfg, c_, conti = env["nk"], env["kit"], env["cfg"], env["c_"], env.get("conti") or {}
    W, A, T, RL, SAM = env["W"], env["A"], env["T"], env["RL"], env["SAM"]
    S = env.get("S") or DEFAULTS
    ctl = ctl or {}
    os.makedirs(outdir, exist_ok=True)
    lb = label or tag                          # 작업실 진행 표시가 읽는 이름 (cut07 꼴)
    res = {"tag": tag, "seed": int(seed), "ok": False, "base": None, "final": None}
    t0 = time.time()
    # 1) 기준 그림 (같은 글·시드로 이미 그렸으면 다시 씀 — 끊긴 뒤 이어 할 때)
    bp = os.path.join(outdir, tag + "_base.png")
    sig = _base_sig(text, neg, w, h, seed, p, ctl)
    if not _base_reusable(bp, sig):
        v = {"unet": p["unet"], "steps": p["steps"], "cfg": p["cfg"], "sampler": RL.SAMPLER, "scheduler": RL.SCHED, "easycache": False}
        v.update(ctl)
        g = T.graph(v, text, neg, w, h, seed, "nk/%s_duosplit/%s_base" % (to, tag))
        outs = c_.wait(c_.queue(g), lb + " base")
        ims = (outs.get("10") or {}).get("images") or []
        if not ims:
            res["why"] = "no base image"
            return res
        c_.fetch(ims[0], bp)
        json.dump(sig, open(bp[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False)
    res["base"] = bp
    res["secs_base"] = round(time.time() - t0, 1)
    roles = [(r, ch) for r, ch in (cut.get("_roles") or []) if ch]
    if len(roles) != 2:
        res["why"] = "나누기 실패: 두 명 컷이 아님 (roles %d)" % len(roles)
        return res
    (ra, cha), (rb, chb) = roles
    res["chars"] = [str(ra.get("char")), str(rb.get("char"))]
    try:
        size = Image.open(bp).size
        # 2) SAM3 조각 (말마다 한 번만 부름)
        memo = {}

        def get_pieces(word):
            if word not in memo:
                got = SAM.segment(nk, kit, cfg, to, [(tag, bp, word + ":3")], 0.4, run="duo_sam", individual=True)
                memo[word] = [np.asarray(Image.open(pp).convert("L").resize(size)) > 127 for pp in sorted(got.get((tag, word + ":3")) or [])]
            return memo[word]
        ma, mb, fi = find_two(get_pieces, RL.partner_words(cha), RL.partner_words(chb), str(ra.get("side")), str(rb.get("side")), RL, log)
        res["find"] = fi
        if not fi["ok"]:
            res["why"] = "나누기 실패: " + fi["why"]
            return res
        res["spans"] = {k: v for k, v in ((str(ra.get("char")), span(ma)), (str(rb.get("char")), span(mb))) if v}   # 말풍선 꼬리용 실제 자리
        log("%s: mask by '%s' + '%s' (%s side + %s side)" % (lb, fi["A"].get("word"), fi["B"].get("word"), ra.get("side"), rb.get("side")))
        # 3) 구역 틀
        ga, gb, mi = region_masks(ma, mb, RL.GROW, S.get("min_region"))
        res["masks"] = mi
        if not mi["ok"]:
            res["why"] = "나누기 실패: " + mi["why"]
            return res
        mpa, mpb = os.path.join(outdir, tag + "_maskA.png"), os.path.join(outdir, tag + "_maskB.png")
        Image.fromarray((ga * 255).astype(np.uint8)).convert("RGB").save(mpa)
        Image.fromarray((gb * 255).astype(np.uint8)).convert("RGB").save(mpb)
        ua = W._upload_input(nk, cfg, mpa, "%s_duo_%s_maskA.png" % (to, tag), False)
        ub = W._upload_input(nk, cfg, mpb, "%s_duo_%s_maskB.png" % (to, tag), False)
        # 4) 구역별 다시 그리기
        look = A.gaze_people(conti, cut)
        ta = region_text(A, W, conti, cut, cha, ra, artist, bool(look[0]))
        tb = region_text(A, W, conti, cut, chb, rb, artist, bool(look[1]))
        res["texts"] = {"A": ta, "B": tb}
        g = duo_graph(T, p, text, ta, tb, neg, ua, ub, w, h, seed, RL.SAMPLER, RL.SCHED, "nk/%s_duosplit/%s" % (to, tag))
        g = RL.speed_region(RL.apply_control(g, ctl))
        t1 = time.time()
        outs = c_.wait(c_.queue(g), lb)
        ims = (outs.get("10") or {}).get("images") or []
        if not ims:
            res["why"] = "나누기 실패: no split image"
            return res
        fp = os.path.join(outdir, tag + "_split.png")
        c_.fetch(ims[0], fp)
        res.update(ok=True, final=fp, secs_regional=round(time.time() - t1, 1))
    except SystemExit:
        res["why"] = "나누기 실패: ComfyUI 작업 실패 (위 [ERROR] 줄 참고)"
    except Exception as e:
        res["why"] = "나누기 실패: 오류 %s" % str(e)[:300]
    finally:
        res["secs"] = round(time.time() - t0, 1)
    return res


def save_result(ed, cid, dst, r, rec, rl, extra=None):
    """컷 하나의 결과를 제자리에: 최종본(나눈 그림, 실패면 기준 그림), cuts_base/cutNN.png, duosplit.json·regionlora.json 기록(rec·rl 사전).
    옛 최종본은 _alt/ 에 남김. 나누기에 실패하면 regionlora.json 의 그 컷 기록(옛 그림의 자리)을 지움 -> 글자 단계는 콘티의 left/right 를 씀.
    -> 나눠 그렸나 (True/False)"""
    nm = "cut%02d" % int(cid)
    split_ok = bool(r.get("ok") and r.get("final") and png_ok(r["final"]))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.makedirs(os.path.join(ed, "cuts_base"), exist_ok=True)
    shutil.copy(r["base"], os.path.join(ed, "cuts_base", nm + ".png"))
    if os.path.exists(dst):
        alt = os.path.join(ed, "_alt")
        os.makedirs(alt, exist_ok=True)
        shutil.copy(dst, os.path.join(alt, "cut%02d_%s.png" % (int(cid), time.strftime("%m%d_%H%M"))))
    shutil.copy(r["final"] if split_ok else r["base"], dst)
    rec[str(int(cid))] = dict({k: v for k, v in r.items() if k not in ("base", "final")}, split_ok=split_ok, **(extra or {}))
    if split_ok and r.get("spans"):
        rl[nm] = {"spans": r["spans"], "duosplit": True, "time": time.strftime("%Y-%m-%d %H:%M:%S")}   # 말풍선 꼬리 자리 (nk_webtoon._real_spans 가 읽음)
    else:
        rl.pop(nm, None)
    return split_ok


# ---------------------------------------------------------------- 콘티의 LoRA 없는 두 명 컷을 나눠 그림 (nk_auto 가 부름)
def run(nk, kit, args):
    """args: ep, cuts(문자열 번호들, 비면 LoRA 없는 두 명 컷 전부), seed, force, dry (+ 고르기: unet, steps, cfg, base_only, overlap — 없으면 설정 파일).
    nk_animacut.run(animamake) 과 같은 규칙: 이미 있는 컷은 건너뜀(force 면 _alt 에 남기고 다시), 시드 = 컷 시드 + 다시 그리기 횟수 x 1000.
    -> {'made': 그린 컷 수, 'split': 나눠 그린 컷 수, 'base_kept': 기준 그림을 최종으로 쓴 컷 번호들, 'one_pass': 한 번에 그린 컷 번호들}"""
    import argparse
    import nk_webtoon as W
    import nk_animacut as A
    import nk_animatest as T
    import nk_regionlora as RL
    import nk_sam as SAM
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    artist = conti.get("artist", "")
    ids = [int(x) for x in (args.cuts or [])] or [int(c["id"]) for c in conti["cuts"]]
    cuts = []
    for c in conti["cuts"]:
        if int(c["id"]) not in ids or not is_duo(c):
            continue
        if has_lora(c):
            print("[skip] cut %d: LoRA character - drawn by nk ep regionlora --split" % int(c["id"])); continue
        cuts.append(c)
    ed = W.ep_dir(kit, args.ep)
    S = load_settings(kit)
    pick = lambda k: getattr(args, k, None) if getattr(args, k, None) not in (None, "") else S[k]
    p = {"unet": getattr(args, "unet", None) or A.DEFAULT["unet"], "steps": int(pick("steps")), "cfg": float(pick("cfg")),
         "base_only": int(pick("base_only")), "overlap": int(pick("overlap")), "min_region": float(S["min_region"])}
    if p["base_only"] >= p["steps"]:
        print("[WARN] base_only %d 가 전체 걸음 %d 이상 - %d 로 줄여서 그림" % (p["base_only"], p["steps"], max(1, p["steps"] - 1)))
        p["base_only"] = max(1, p["steps"] - 1)
    out ={"made": 0, "split": 0, "base_kept": [], "one_pass": []}
    # 작업실 진행 표시(nk_web)는 'regionlora <편> -> <편>: N cuts' 줄을 두 명 컷 단계의 시작으로 읽음 -> 같은 꼴로 씀
    print("regionlora %s -> %s: %d cuts | %s %s steps %d cfg %.1f base_only %d overlap %d | no LoRA (duo split, nk_duosplit)"
          % (args.ep, args.ep, len(cuts), RL.SAMPLER, RL.SCHED, p["steps"], p["cfg"], p["base_only"], p["overlap"]))
    print("duosplit settings (%s): min_region %.1f%% | base_only %d / %d steps" % (SETTINGS_FILE, 100 * p["min_region"], p["base_only"], p["steps"]))
    if not cuts:
        return out
    c_ = None
    if not args.dry:
        c_ = nk.Comfy(cfg.get("server", "auto"))
        miss = missing_nodes(c_)
        if miss:                                # Impact Pack 이 없음 -> 멈추지 않고 그 컷들을 예전처럼 한 번에 그림
            todo = [int(c["id"]) for c in cuts]
            print(WARN_NO_IMPACT % (", ".join(miss), todo))
            d = A.DEFAULT
            A.run(nk, kit, argparse.Namespace(ep=args.ep, cuts=[str(i) for i in todo], unet=d["unet"], steps=d["steps"], cfg=d["cfg"],
                                              sampler=d["sampler"], shift=None, artist=None, seed=str(getattr(args, "seed", None) or "500"),
                                              force=bool(getattr(args, "force", False)), nolora=False, dry=False))
            out["one_pass"] = todo
            return out
    W.tag_report(kit, conti, cuts)
    rec_p, rl_p = os.path.join(ed, "duosplit.json"), os.path.join(ed, "regionlora.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    rl = json.load(open(rl_p, encoding="utf-8")) if os.path.exists(rl_p) else {}
    env = {"nk": nk, "kit": kit, "cfg": cfg, "conti": conti, "c_": c_, "W": W, "A": A, "T": T, "RL": RL, "SAM": SAM, "S": S}
    work = os.path.join(ed, "duosplit")
    fails = 0
    for cut in cuts:
        cid = int(cut["id"]); nm = "cut%02d" % cid
        dst = W._final_file(kit, args.ep, cid)
        if os.path.exists(dst) and not getattr(args, "force", False):
            print("[skip] cut %d: %s exists (--force to redraw)" % (cid, dst)); continue
        art = cut.get("anima_artist", artist)
        s, text = A.cut_text(nk, W, cfg, conti, cut, artist)
        w, h = [int(x) for x in s["size"].split("x")] if isinstance(s.get("size"), str) else (int(s["width"]), int(s["height"]))
        seed = A.cut_seed(args.ep, cut, getattr(args, "seed", None) or "500")
        neg = cut_neg(A, conti, cut, s)
        if args.dry:
            (ra, cha), (rb, chb) = [(r, ch) for r, ch in cut["_roles"] if ch]
            look = A.gaze_people(conti, cut)
            print("\n== duo-split cut %d %dx%d seed %d\n  [base] %s\n  [A %s] %s\n  [B %s] %s\n  [neg] %s" % (
                cid, w, h, seed, text, ra.get("char"), region_text(A, W, conti, cut, cha, ra, art, bool(look[0])),
                rb.get("char"), region_text(A, W, conti, cut, chb, rb, art, bool(look[1])), neg))
            continue
        ctl = {}
        if str(conti.get("pose3d") or "").lower() in ("auto", "scene3d", "capsule"):
            try:
                pose_flags(A, conti, cut)
                ctl = RL.pose_control(nk, kit, cfg, conti, args.ep, cut, w, h)
            except (Exception, SystemExit) as e:
                print("   [note] %s: 3D 인형 조종 실패 (%s) - 조종 없이 그림" % (nm, str(e)[:120]))
                ctl = {}
        tag = "%s_s%d" % (nm, seed)
        t0 = time.time()
        try:
            r = split_one(env, cut, text, neg, w, h, seed, tag, work, args.ep, p, art, ctl, log=print, label=nm)
        except SystemExit:
            r = {"ok": False, "why": "ComfyUI 작업 실패", "error": True}
        except Exception as e:
            r = {"ok": False, "why": "오류: %s" % str(e)[:300], "error": True}
        if r.get("error") or not r.get("base") or not png_ok(r["base"]):
            fails += 1
            print("[ERROR] %s: %s (연달아 %d번)" % (nm, r.get("why") or "no base image", fails))
            if fails >= 3:
                print("[ERROR] 연달아 3번 실패 - 멈춤 (다시 하면 이어서 함)")
                sys.exit(1)
            continue
        fails = 0
        secs = round(time.time() - t0, 1)
        split_ok = save_result(ed, cid, dst, r, rec, rl, dict(text=text, negative=neg, size=[w, h], settings=p, artist=art, secs=secs,
                                                             control=bool(ctl), time=time.strftime("%Y-%m-%d %H:%M:%S")))
        json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(rl, open(rl_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        out["made"] += 1
        if split_ok:
            out["split"] += 1
        else:
            out["base_kept"].append(cid)
            print("[WARN] %s: 나누기 실패 -> 기준 그림(한 번에 그린 그림)을 최종으로 씀: %s" % (nm, str(r.get("why"))[:200]))
        print("%s -> %s (%.0f s, %s)" % (nm, dst, secs, "duo split" if split_ok else "split FAILED, base kept"))
    print("\nduosplit %s: %d cuts drawn, %d split, %d with the base picture (see duosplit.json)"
          % (args.ep, out["made"], out["split"], len(out["base_kept"])))
    return out


def add_parser(esub, nk, kit):
    a = esub.add_parser("duosplit", help="two-character cut without a LoRA character: base picture -> SAM3 finds both -> each person redrawn "
                                         "with only their own text (Impact RegionalSampler). settings: duosplit_settings.yaml")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.add_argument("--unet"); a.add_argument("--steps"); a.add_argument("--cfg")
    a.add_argument("--base-only", dest="base_only"); a.add_argument("--overlap")
    a.add_argument("--seed", default="500")
    a.add_argument("--force", action="store_true", help="redraw cuts that already have a final picture (old one kept in _alt/)")
    a.add_argument("--dry", action="store_true", help="print the base and per-person texts only")
    a.set_defaults(func=lambda x: run(nk, kit, x))
