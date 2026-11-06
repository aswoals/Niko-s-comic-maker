# -*- coding: utf-8 -*-
"""두 명 컷 '리저널(영역) 프롬프트' 비교 시험

왜: 지금 두 명 컷 기본(compose)은 Qwen이 혼자 컷 두 장을 보고 '새로' 그림 -> 그림체·조명·비율이 흔들림
. NoobAI 한 모델이 한 장에 두 사람을 그리면 그림체·조명은

nk ep regtest <ep> <컷...> [--variants P,PT0.2,AM] [--seeds 71,72] [--name 이름]
  P      = 지금 코드의 P 방식 (ComfyUI 기본 ConditioningSetMask: 영역마다 따로 예측해 섞음 = 잠재 단계)
  PT0.2  = P + 단계 나누기 (ConditioningSetTimestepRange): 처음 20%는 장면 프롬프트만(구도), 나머지는 영역 프롬프트
           (아카라이브 aiart 161686015 '로컬 comfyui 찍먹 - 리저널': 글로벌 0~0.2 / 리저널 0.2~1.0)
  AM     = 어텐션 단계 영역 (Acly comfyui-tooling-nodes: ETN_BackgroundRegion/DefineRegion/AttentionMask,
           크로스 어텐션만 영역별, 계산 1번) - 노드가 설치돼 있어야 함 (없으면 이 방식만 건너뜀)
결과: runs/regtest/<이름>/cutNN_sheet.png (재료 혼자 컷 | 지금 최종본 | 방식·시드별) + judge.json
최종본은 바꾸지 않음 (비교만)."""
import os, sys, json, time, argparse

AM_NODES = ["ETN_BackgroundRegion", "ETN_DefineRegion", "ETN_AttentionMask"]


def _settings(nk, W, cfg, conti, cut):
    """nk_webtoon._draft_cut 과 같은 설정 (장소·소품·카메라 태그, 그림 크기, 작가) -> s"""
    wt, wn, _ = W._world_for(conti, cut)
    wt = W._joined(W._camera_tags(cut), wt)
    ns = argparse.Namespace(preset=cut.get("artist", conti.get("artist")),
                            extra=W._joined(cut.get("extra"), wt), neg=W._joined(cut.get("neg"), wn),
                            lora=None, size=W._gen_size(cut["size"]), rating=None,
                            cfg=cut.get("cfg"), steps=None, sampler=None, scheduler=None, quality=None,
                            year=None, artist=None, artist_weight=None, artist_position=None, tags=None,
                            strength=cut.get("strength"), charlora=cut.get("lora"), hires=0, hires_denoise=None,
                            hires_steps=None, hires_method=None, upscale_model=None)
    s = nk.build_settings(cfg, ns)
    s.update(__import__("nk_styleref").cut_settings(conti, cut))
    return s


def _timestep(g, s_end):
    """P 그래프(build_duo2_graph pass1_only)에 단계 나누기: 장면(40) 0~x, 영역 조건(b+2) x~1"""
    g["45"] = {"class_type": "ConditioningSetTimestepRange", "inputs": {"conditioning": ["40", 0], "start": 0.0, "end": s_end}}
    g["104"]["inputs"]["conditioning_1"] = ["45", 0]
    i = 0
    while str(100 + i * 10) in g:
        b = 100 + i * 10
        g[str(b + 6)] = {"class_type": "ConditioningSetTimestepRange",
                         "inputs": {"conditioning": [str(b + 2), 0], "start": s_end, "end": 1.0}}
        g[str(b + 4)]["inputs"]["conditioning_2"] = [str(b + 6), 0]
        i += 1
    return g


def _masks_at(g, Wd, H, regions, base, overlap=0.06):
    """W._region_masks 와 같은 반쪽 마스크를 다른 번호(base..)·다른 크기로 (고해상도 단계용) -> [노드 참조]"""
    g[str(base)] = {"class_type": "SolidMask", "inputs": {"value": 0.0, "width": Wd, "height": H}}
    out = []
    for i, r in enumerate(regions):
        a, b = r["span"]
        x0 = max(0, int(Wd * (a - overlap))); x1 = min(Wd, int(Wd * (b + overlap)))
        g[str(base + 1 + 2 * i)] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": max(8, x1 - x0), "height": H}}
        g[str(base + 2 + 2 * i)] = {"class_type": "MaskComposite",
                                    "inputs": {"destination": [str(base), 0], "source": [str(base + 1 + 2 * i), 0],
                                               "x": x0, "y": 0, "operation": "add"}}
        out.append([str(base + 2 + 2 * i), 0])
    return out


def _am_hires(g, s, regions, seed, hires):
    """AM 최종본: 초안을 1.5배로 키워 같은 어텐션 영역(그 크기 마스크)으로 살짝(0.35) 다시 그림.
    ETN 마스크는 잠재 크기에 맞춰 줄이므로 고해상도용 마스크를 따로 만듦. 번호 450번대 = 뼈대 ControlNet 안 붙음(_pose_cn 규칙)"""
    sc = float(hires.get("scale", 1.5))
    Wd, H = int(s["width"]), int(s["height"])
    W2, H2 = int(round(Wd * sc / 8)) * 8, int(round(H * sc / 8)) * 8
    hm = _masks_at(g, W2, H2, regions, 850)
    g["870"] = {"class_type": "ETN_BackgroundRegion", "inputs": {"conditioning": ["40", 0]}}
    prev = ["870", 0]
    for i, r in enumerate(regions):
        g[str(871 + i)] = {"class_type": "ETN_DefineRegion",
                           "inputs": {"regions": prev, "mask": hm[i], "conditioning": [str(100 + i * 10), 0]}}
        prev = [str(871 + i), 0]
    g["880"] = {"class_type": "ETN_AttentionMask", "inputs": {"model": ["4", 0], "regions": prev}}
    g["450"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["451"] = {"class_type": "ImageScale", "inputs": {"image": ["450", 0], "upscale_method": "lanczos",
                                                        "width": W2, "height": H2, "crop": "disabled"}}
    g["452"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["451", 0], "vae": ["4", 2]}}
    g["453"] = {"class_type": "KSampler",
                "inputs": {"seed": int(seed), "steps": int(hires.get("steps", 20)), "cfg": float(s["cfg"]),
                           "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(hires.get("denoise", 0.35)),
                           "model": ["880", 0], "positive": ["40", 0], "negative": ["41", 0], "latent_image": ["452", 0]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["453", 0], "vae": ["4", 2]}}
    return g


REGION_SOLO = True


def _region_text(W, base_pos, tail, solo):
    return ("%s, solo, %s" % (W._strip_counts(base_pos), tail)) if solo else ("%s, %s" % (base_pos, tail))


def _am_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, hires=None, init=None, solo=REGION_SOLO):
    """어텐션 단계 영역 (Acly tooling-nodes region.py: attn2 패치). 영역 글 = 장면 + 그 사람 태그 (Forge Couple 식 공통 앞붙이기)"""
    g = {}
    Wd, H = int(s["width"]), int(s["height"])
    g["4"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}
    masks = W._region_masks(g, Wd, H, {str(i): r["span"] for i, r in enumerate(regions)})
    g["40"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_pos, "clip": ["4", 1]}}
    g["41"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_neg, "clip": ["4", 1]}}
    g["70"] = {"class_type": "ETN_BackgroundRegion", "inputs": {"conditioning": ["40", 0]}}
    prev = ["70", 0]
    for i, r in enumerate(regions):
        b = 100 + i * 10
        g[str(b)] = {"class_type": "CLIPTextEncode", "inputs": {"text": _region_text(W, base_pos, r["pos1"], solo), "clip": ["4", 1]}}
        g[str(b + 7)] = {"class_type": "ETN_DefineRegion",
                         "inputs": {"regions": prev, "mask": masks[str(i)], "conditioning": [str(b), 0]}}
        prev = [str(b + 7), 0]
    # 영역마다 부정 태그는 못 나눔 -> 두 사람 부정을 합침 (P 방식은 영역별)
    negs = [base_neg] + [r["neg"] for r in regions]
    seen, parts = set(), []
    for t in ", ".join(negs).split(","):
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower()); parts.append(t)
    g["41"]["inputs"]["text"] = ", ".join(parts)
    g["80"] = {"class_type": "ETN_AttentionMask", "inputs": {"model": ["4", 0], "regions": prev}}
    g["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": Wd, "height": H, "batch_size": 1}}
    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]), "sampler_name": s["sampler"],
                         "scheduler": s["scheduler"], "denoise": 1.0, "model": ["80", 0], "positive": ["40", 0],
                         "negative": ["41", 0], "latent_image": ["5", 0]}}
    if init:                       # AMI: 지금 최종본(합친 그림)에서 시작 -> 구도·색은 두고 NoobAI 한 모델로 다시 칠함
        g["6"] = {"class_type": "LoadImage", "inputs": {"image": init["image"]}}
        g["7"] = {"class_type": "ImageScale", "inputs": {"image": ["6", 0], "upscale_method": "lanczos",
                                                          "width": Wd, "height": H, "crop": "disabled"}}
        g["5"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["4", 2]}}
        g["3"]["inputs"]["denoise"] = float(init["denoise"])
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    if hires and float(hires.get("scale", 0) or 0) > 1.0:
        _am_hires(g, s, regions, seed, hires)
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


UNIFY_FIG_PROMPTS, UNIFY_FIG_TH = ("animal:6", "character:6"), 0.2
SMALL_HEAD = 0.001


def _amb_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, dn, hires=None, init=None, solo=REGION_SOLO):
    """AMB = 어텐션 영역으로 LoRA 없이 한 장(그림체·조명 하나) -> LoRA 캐릭터 자리만 SAM3 몸 마스크 ∩ 자기 반쪽으로
    그 LoRA 다시 그리기 (DifferentialDiffusion + InpaintModelConditioning = 가장자리를 점점 약하게, nk_handfix dd 와 같은 부품).
    예전 MB(뼈대 모양 마스크 + SetLatentNoiseMask)의 경계 테두리(턱·목·허벅지 색 테두리)를 줄이려는 개선판 (추정 - 시험)"""
    import nk_sam
    g = _am_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, hires, init, solo)
    del g["9"]
    hi = "850" in g
    Wd, H = int(s["width"]), int(s["height"])
    last_img = ["8", 0]
    made = False
    for i, r in enumerate(regions):
        ch = r["char"]
        if not (ch and ch.get("lora")):
            continue
        b = 300 + i * 20
        body = W.find_word(ch)
        g[str(b)] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": nk_sam.MODEL}}
        g[str(b + 1)] = {"class_type": "CLIPTextEncode", "inputs": {"clip": [str(b), 1], "text": body}}
        g[str(b + 2)] = {"class_type": "SAM3_Detect", "inputs": {"model": [str(b), 0], "image": last_img, "conditioning": [str(b + 1), 0],
                                                                "threshold": 0.3, "refine_iterations": 2, "individual_masks": False}}
        # 자기 반쪽(영역 마스크)과 겹치는 곳만 -> 조금 키우고 흐리게 (DifferentialDiffusion 이 흐린 정도만큼 약하게 다시 그림)
        g[str(b + 3)] = {"class_type": "MaskComposite", "inputs": {"destination": [str(b + 2), 0], "source": ["%d" % ((852 if hi else 52) + 2 * i), 0],
                                                                  "x": 0, "y": 0, "operation": "multiply"}}
        g[str(b + 4)] = {"class_type": "GrowMask", "inputs": {"mask": [str(b + 3), 0], "expand": 16, "tapered_corners": True}}
        g[str(b + 5)] = {"class_type": "MaskToImage", "inputs": {"mask": [str(b + 4), 0]}}
        g[str(b + 6)] = {"class_type": "ImageBlur", "inputs": {"image": [str(b + 5), 0], "blur_radius": 12, "sigma": 6.0}}
        g[str(b + 7)] = {"class_type": "ImageToMask", "inputs": {"image": [str(b + 6), 0], "channel": "red"}}
        st = float(ch.get("lora_strength", 1.0))
        g[str(b + 8)] = {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": ch["lora"],
                                                               "strength_model": st, "strength_clip": st}}
        g[str(b + 9)] = {"class_type": "DifferentialDiffusion", "inputs": {"model": [str(b + 8), 0], "strength": 1.0}}
        g[str(b + 10)] = {"class_type": "CLIPTextEncode",
                          "inputs": {"text": ("solo, " + W._strip_counts(r["pos"])) if solo else r["pos"], "clip": [str(b + 8), 1]}}
        g[str(b + 11)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"], "clip": [str(b + 8), 1]}}
        g[str(b + 12)] = {"class_type": "InpaintModelConditioning",
                          "inputs": {"positive": [str(b + 10), 0], "negative": [str(b + 11), 0], "vae": ["4", 2],
                                     "pixels": last_img, "mask": [str(b + 7), 0], "noise_mask": True}}
        g[str(b + 13)] = {"class_type": "KSampler",
                          "inputs": {"seed": int(seed), "steps": int((hires or {}).get("steps", 20) if hi else s["steps"]), "cfg": float(s["cfg"]),
                                     "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(dn),
                                     "model": [str(b + 9), 0], "positive": [str(b + 12), 0], "negative": [str(b + 12), 1],
                                     "latent_image": [str(b + 12), 2]}}
        g[str(b + 14)] = {"class_type": "VAEDecode", "inputs": {"samples": [str(b + 13), 0], "vae": ["4", 2]}}
        last_img = [str(b + 14), 0]
        made = True
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": last_img}}
    if not made:
        print("[AMB] LoRA 캐릭터가 없는 컷 -> AM 과 같음")
    return g


LF_RE = __import__("re").compile(r"LF(\d*\.?\d+)?(?:g(\d+))?(?:b(\d+))?(?:r(\d*\.?\d+))?(?:m([BCH]))?(s)?(?:k(\d))?(d)?(w)?")
LF_BODY_WORDS = {"B": "furry character", "C": "animal", "H": "character"}


def _solo_pose(W, kit, ep, cid, span, out_dir):
    """없으면 None"""
    import json, cv2, nk_pose
    kpf = W._pose_file(kit, ep, cid)[:-4] + "_kp.json"
    if not os.path.exists(kpf):
        return None
    d = json.load(open(kpf, encoding="utf-8"))
    i = min(range(len(d["spans"])), key=lambda j: abs(d["spans"][j][0] - span[0]) + abs(d["spans"][j][1] - span[1]))
    pp = d["people"][i]
    img = nk_pose.draw(int(d["H"]), int(d["W"]), [(pp["k"], pp["c"])])
    os.makedirs(out_dir, exist_ok=True)
    f = os.path.join(out_dir, "pose_solo_cut%02d.png" % cid)
    cv2.imwrite(f, img[:, :, ::-1])
    return f


def _front_mask(W, kit, ep, cid, regions, fi, Wd, H, out_dir):
    """LP: 앞 캐릭터를 덮어 그릴 자리 = 뼈대 몸 모양 - 상대 자리는 안 뺌
    (앞 캐릭터가 이기는 게 규칙: 어깨에 올린 손은 상대 위). 최종 크기로 만들어 올림"""
    import nk_pose, cv2
    spans = [tuple(r["span"]) for r in regions]
    ch = regions[fi]["char"] or {}
    ms, cnt = nk_pose.body_masks(W._pose_file(kit, ep, cid), spans, Wd, H,
                                 grow=0.055 * float(ch.get("repaint_grow", 2.2)), cap=float(ch.get("repaint_cap", 1.2)),
                                 blur=float(ch.get("repaint_blur", 0.035)), solid=True)
    os.makedirs(out_dir, exist_ok=True)
    f = os.path.join(out_dir, "front_mask_cut%02d.png" % cid)
    cv2.imwrite(f, cv2.merge([ms[fi]] * 3))
    return f, cnt[fi]


def _lp_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, front_mask, hires=None, solo=REGION_SOLO):
    """LP = 뒤→앞 순서로 그려 넣기
    1단계 뒤 캐릭터 + 배경을 한 장 (어텐션 영역, 뒤 캐릭터 뼈대만 - run()에서 바꿈)
    2단계 앞 캐릭터를 몸 모양 자리(front_mask)에 덮어 그림 (LoRA 캐릭터면 LoRA 1.0, 세기 1.0, 두 사람 뼈대).
    앞 = LoRA 캐릭터 (없으면 영역 0). 윤곽을 오려 내지 않음 - 겹친 곳은 나중에 그린 앞 캐릭터가 덮음"""
    fi = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
    fr = regions[fi]
    back = [r for i, r in enumerate(regions) if i != fi]
    g = _am_graph(W, cfg, s, W._strip_counts(base_pos), base_neg, back, seed, prefix, hires, None, solo)
    del g["9"]
    ch = fr["char"] or {}
    model, clip = ["4", 0], ["4", 1]
    if ch.get("lora"):
        st = float(ch.get("lora_strength", 1.0))
        g["640"] = {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": ch["lora"],
                                                           "strength_model": st, "strength_clip": st}}
        model, clip = ["640", 0], ["640", 1]
    g["641"] = {"class_type": "DifferentialDiffusion", "inputs": {"model": model, "strength": 1.0}}
    g["642"] = {"class_type": "LoadImageMask", "inputs": {"image": front_mask, "channel": "red"}}
    g["643"] = {"class_type": "CLIPTextEncode", "inputs": {"text": _region_text(W, base_pos, fr["pos1"], solo), "clip": clip}}
    g["644"] = {"class_type": "CLIPTextEncode", "inputs": {"text": W._joined(base_neg, fr["neg"]), "clip": clip}}
    g["645"] = {"class_type": "InpaintModelConditioning",
                "inputs": {"positive": ["643", 0], "negative": ["644", 0], "vae": ["4", 2],
                           "pixels": ["8", 0], "mask": ["642", 0], "noise_mask": True}}
    g["646"] = {"class_type": "KSampler",
                "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                           "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": 1.0,
                           "model": ["641", 0], "positive": ["645", 0], "negative": ["645", 1], "latent_image": ["645", 2]}}
    g["647"] = {"class_type": "VAEDecode", "inputs": {"samples": ["646", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["647", 0]}}
    return g


def _tagfix(regions, spec):
    """    -태그 = 그 사람 글에서 뺌 / +태그 = 더함 / !태그 = 그 사람 부정 글에 더함 / ~태그 = 그 사람 부정 글에서 뺌"""
    if not spec:
        return
    for part in [x.strip() for x in spec.split(";") if x.strip()]:
        key, _, ed = part.partition(":")
        op, tag = ed[:1], ed[1:].strip()
        for r in regions:
            if r["key"] != key.strip():
                continue
            if op == "-":
                r["pos1"] = ", ".join(t for t in [x.strip() for x in r["pos1"].split(",")] if t and t != tag)
            elif op == "+":
                r["pos1"] = r["pos1"] + ", " + tag
            elif op == "!":
                r["neg"] = (r["neg"] + ", " + tag) if r.get("neg") else tag
            elif op == "~":
                r["neg"] = ", ".join(t for t in [x.strip() for x in r.get("neg", "").split(",")] if t and t != tag)
            print("[tagfix] %s %s%s" % (r["key"], op, tag))


def _lf_pick(W, kit, ep, cid, regions, cand_files, Wd, H):
    """k 방식: ① 후보마다 (그림, SAM 몸 마스크) -> 먼저 그린 사람 몸이 상대 뼈대 몸 자리에 들어간 비율 -> 가장 적은 후보."""
    import numpy as np, cv2, nk_pose
    first = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
    spans = [tuple(r["span"]) for r in regions]
    ms, _ = nk_pose.body_masks(W._pose_file(kit, ep, cid), spans, Wd, H)
    zone = np.zeros((H, Wd), bool)
    for i, m in enumerate(ms):
        if i != first:
            zone |= m > 128
    rows = []
    for k, (pic, msk) in enumerate(cand_files):
        m = cv2.imread(msk, cv2.IMREAD_GRAYSCALE)
        if m is None:
            rows.append((k, 1.0, pic)); continue
        m = cv2.resize(m, (Wd, H), interpolation=cv2.INTER_NEAREST) > 128
        rows.append((k, float((m & zone).sum()) / max(1, int(zone.sum())), pic))
    best = min(rows, key=lambda x: x[1])
    return best, rows


def _mask_feather(g, base, src, grow, blur):
    """마스크 src -> grow px 넓히고 blur px 흐리게 (base, base+1.. 번호) -> [노드]"""
    g[str(base)] = {"class_type": "GrowMask", "inputs": {"mask": src, "expand": int(grow), "tapered_corners": True}}
    g[str(base + 1)] = {"class_type": "MaskToImage", "inputs": {"mask": [str(base), 0]}}
    g[str(base + 2)] = {"class_type": "ImageBlur", "inputs": {"image": [str(base + 1), 0], "blur_radius": max(1, int(blur)),
                                                             "sigma": max(0.5, blur / 2.0)}}
    g[str(base + 3)] = {"class_type": "ImageToMask", "inputs": {"image": [str(base + 2), 0], "channel": "red"}}
    return [str(base + 3), 0]


LC_K_RE = __import__("re").compile(r"LCk(\d)")
LCK_BACK_AT = 0.15


def _lc_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, hires=None, solo=REGION_SOLO, back=False, init_img=None,
              partner_mask=None):
    """누끼 따서 레이어로 합치기'.
    ③ 상대: 배경판의 자기 칸에 혼자 그림 (LoRA 없음, 상대 뼈대만) -> 상대 층
back=True면 그 위에 상대 누끼(SAM 'character')를 다시 붙임.
    LP와 다른 점: 앞 캐릭터를 '칸'이 아니라 '누끼(실제 모양)'로 붙여서 뒤 캐릭터 머리를 삼키지 않음"""
    g = _lf_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, 1.0, hires, solo, stage1_only=True, init_img=init_img)
    for k in ("9", "680", "681"):
        g.pop(k, None)
    first = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
    others = [r for i, r in enumerate(regions) if i != first]
    sc = float((hires or {}).get("scale", 0) or 0)
    Wd, H = int(s["width"]), int(s["height"])
    if sc > 1.0:
        Wd, H = int(round(Wd * sc / 8)) * 8, int(round(H * sc / 8)) * 8
    img1 = ["8", 0]
    # ② 배경판 (480번대 = 뼈대 ControlNet 안 붙음)
    pm = _mask_feather(g, 480, ["602", 0], 20, 8)
    g["484"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "no humans, scenery, " + W._strip_counts(base_pos), "clip": ["4", 1]}}
    g["485"] = {"class_type": "CLIPTextEncode", "inputs": {"text": W._joined(base_neg, "1boy, 1girl, anthro, animal, character, person"), "clip": ["4", 1]}}
    g["486"] = {"class_type": "InpaintModelConditioning", "inputs": {"positive": ["484", 0], "negative": ["485", 0], "vae": ["4", 2],
                                                                      "pixels": img1, "mask": pm, "noise_mask": True}}
    g["487"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                                     "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": 1.0,
                                                     "model": ["604", 0], "positive": ["486", 0], "negative": ["486", 1],
                                                     "latent_image": ["486", 2]}}
    g["488"] = {"class_type": "VAEDecode", "inputs": {"samples": ["487", 0], "vae": ["4", 2]}}
    plate = ["488", 0]
    # ③ 상대를 배경판 자기 칸에
    r = others[0]
    if partner_mask:
        g["957"] = {"class_type": "LoadImageMask", "inputs": {"image": partner_mask, "channel": "red"}}
        rmask = [["957", 0]]
    else:
        rmask = _masks_at(g, Wd, H, others, 950)
    rm = _mask_feather(g, 1100, rmask[0], 0, 16)
    g["1104"] = {"class_type": "CLIPTextEncode", "inputs": {"text": _region_text(W, base_pos, r["pos1"], solo), "clip": ["4", 1]}}
    g["1105"] = {"class_type": "CLIPTextEncode", "inputs": {"text": W._joined(base_neg, r["neg"]), "clip": ["4", 1]}}
    g["1106"] = {"class_type": "InpaintModelConditioning", "inputs": {"positive": ["1104", 0], "negative": ["1105", 0], "vae": ["4", 2],
                                                                       "pixels": plate, "mask": rm, "noise_mask": True}}
    g["1107"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                                      "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": 1.0,
                                                      "model": ["604", 0], "positive": ["1106", 0], "negative": ["1106", 1],
                                                      "latent_image": ["1106", 2]}}
    g["1108"] = {"class_type": "VAEDecode", "inputs": {"samples": ["1107", 0], "vae": ["4", 2]}}
    R = ["1108", 0]
    # ④ 누끼 합치기
    nm = _mask_feather(g, 1112, ["602", 0], 3, 2)
    g["1116"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": R, "source": img1, "x": 0, "y": 0,
                                                                   "resize_source": False, "mask": nm}}
    out = ["1116", 0]
    if back:
        g["1110"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["600", 1], "text": "character"}}
        g["1111"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["600", 0], "image": R, "conditioning": ["1110", 0],
                                                            "threshold": 0.3, "refine_iterations": 2, "individual_masks": False}}
        om = _mask_feather(g, 1120, ["1111", 0], 3, 2)
        g["1124"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": out, "source": R, "x": 0, "y": 0,
                                                                       "resize_source": False, "mask": om}}
        out = ["1124", 0]
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": out}}
    return g


def _lf_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, dn=1.0, hires=None, solo=REGION_SOLO,
              grow=24, blur=16, band=0.0, word=None, debug=False, stage1_only=False, init_img=None, wide=False):
    """LF = LoRA 캐릭터 먼저. AMB의 반대 순서
    ① 그림 전체에 LoRA 캐릭터 혼자 (LoRA 1.0, 어텐션 영역으로 자기 반쪽에) - 상대 반쪽은 배경만 = 혼자 컷 처음 그리기와 같은 조건
    ② 상대 반쪽만 NoobAI(LoRA 없음)로 새로 그림 (DifferentialDiffusion + InpaintModelConditioning, 세기 dn),
    LoRA 캐릭터가 없으면(태그 캐릭터 둘) 영역 0을 먼저"""
    import nk_sam
    first = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
    fr = regions[first]
    others = [r for i, r in enumerate(regions) if i != first]
    # ① 먼저 그릴 사람만 영역으로, 장면 글에서는 인원수 태그를 뺌 (상대 반쪽 = 배경 영역)
    ch = fr["char"] or {}
    if init_img:
        # k 방식 2단계: 고른 ① 그림(최종 크기)을 불러와서 ②만
        g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}},
             "8": {"class_type": "LoadImage", "inputs": {"image": init_img}}}
    else:
        g = _am_graph(W, cfg, s, W._strip_counts(base_pos), base_neg, [fr], seed, prefix, hires, None, solo)
        del g["9"]
    if ch.get("lora") and not init_img:
        st = float(ch.get("lora_strength", 1.0))
        g["90"] = {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": ch["lora"],
                                                           "strength_model": st, "strength_clip": st}}
        for n in list(g.values()):
            if n["class_type"] == "ETN_AttentionMask":
                n["inputs"]["model"] = ["90", 0]
            if n["class_type"] == "CLIPTextEncode" and n["inputs"].get("clip") == ["4", 1]:
                n["inputs"]["clip"] = ["90", 1]
    img = ["8", 0]
    sc = float((hires or {}).get("scale", 0) or 0)
    Wd, H = int(s["width"]), int(s["height"])
    if sc > 1.0:
        Wd, H = int(round(Wd * sc / 8)) * 8, int(round(H * sc / 8)) * 8
    # ② 상대마다: 자기 반쪽 - (먼저 그린 사람 몸 SAM3 + 여유) -> 흐린 가장자리 -> LoRA 없이 새로 그림
    body = W.find_word(ch)
    if word:
        body = LF_BODY_WORDS[word]
    g["600"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": nk_sam.MODEL}}
    g["601"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["600", 1], "text": body}}
    g["602"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["600", 0], "image": img, "conditioning": ["601", 0],
                                                       "threshold": 0.3, "refine_iterations": 2, "individual_masks": False}}
    g["603"] = {"class_type": "GrowMask", "inputs": {"mask": ["602", 0], "expand": int(grow), "tapered_corners": True}}
    g["604"] = {"class_type": "DifferentialDiffusion", "inputs": {"model": ["4", 0], "strength": 1.0}}
    if stage1_only:
        # k 방식 1단계: ① 그림 + 먼저 그린 사람 몸(SAM, 여유 없음) 마스크 두 장을 저장하고 끝
        g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": img}}
        g["680"] = {"class_type": "MaskToImage", "inputs": {"mask": ["602", 0]}}
        g["681"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix + "_mask", "images": ["680", 0]}}
        return g
    if debug:
        # d = 확인용: ① 그림 위에 지키는 영역(SAM+여유)을 반투명 빨강으로 칠해 저장하고 끝 (상대는 안 그림)
        g["690"] = {"class_type": "SolidMask", "inputs": {"value": 0.55, "width": Wd, "height": H}}
        g["691"] = {"class_type": "MaskComposite", "inputs": {"destination": ["603", 0], "source": ["690", 0],
                                                             "x": 0, "y": 0, "operation": "multiply"}}
        g["692"] = {"class_type": "EmptyImage", "inputs": {"width": Wd, "height": H, "batch_size": 1, "color": 0xFF0000}}
        g["693"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": img, "source": ["692", 0], "x": 0, "y": 0,
                                                                    "resize_source": False, "mask": ["691", 0]}}
        g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["693", 0]}}
        return g
    rmask = _masks_at(g, Wd, H, others, 950)
    if wide:
        #   상대 손이 칸 벽에 막혀 뭉개지는지 확인 (그 자리 다시 그리기 세기 1.0 = 배경과 섞인 게 아님, 04:5x 계산)
        g["958"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": Wd, "height": H}}
        rmask = [["958", 0] for _ in others]
    for i, r in enumerate(others):
        b = 610 + i * 20
        g[str(b)] = {"class_type": "MaskComposite", "inputs": {"destination": rmask[i], "source": ["603", 0],
                                                              "x": 0, "y": 0, "operation": "subtract"}}
        g[str(b + 1)] = {"class_type": "MaskToImage", "inputs": {"mask": [str(b), 0]}}
        g[str(b + 2)] = {"class_type": "ImageBlur", "inputs": {"image": [str(b + 1), 0], "blur_radius": max(1, int(blur)),
                                                                "sigma": max(0.5, blur / 2.0)}}
        g[str(b + 3)] = {"class_type": "ImageToMask", "inputs": {"image": [str(b + 2), 0], "channel": "red"}}
        g[str(b + 4)] = {"class_type": "CLIPTextEncode", "inputs": {"text": _region_text(W, base_pos, r["pos1"], solo), "clip": ["4", 1]}}
        g[str(b + 5)] = {"class_type": "CLIPTextEncode", "inputs": {"text": W._joined(base_neg, r["neg"]), "clip": ["4", 1]}}
        g[str(b + 6)] = {"class_type": "InpaintModelConditioning",
                         "inputs": {"positive": [str(b + 4), 0], "negative": [str(b + 5), 0], "vae": ["4", 2],
                                    "pixels": img, "mask": [str(b + 3), 0], "noise_mask": True}}
        g[str(b + 7)] = {"class_type": "KSampler",
                         "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                    "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(dn),
                                    "model": ["604", 0], "positive": [str(b + 6), 0], "negative": [str(b + 6), 1],
                                    "latent_image": [str(b + 6), 2]}}
        g[str(b + 8)] = {"class_type": "VAEDecode", "inputs": {"samples": [str(b + 7), 0], "vae": ["4", 2]}}
        img = [str(b + 8), 0]
    if band > 0 and others:
        #    상대 반쪽(+64px) 안쪽만 -> 장면 글로 세기 band 다시 칠함 (LoRA 없음). 얼굴 등 몸 안쪽은 안 건드림
        g["660"] = {"class_type": "GrowMask", "inputs": {"mask": ["602", 0], "expand": int(grow) + 24, "tapered_corners": True}}
        g["661"] = {"class_type": "GrowMask", "inputs": {"mask": ["602", 0], "expand": -8, "tapered_corners": True}}
        g["662"] = {"class_type": "MaskComposite", "inputs": {"destination": ["660", 0], "source": ["661", 0],
                                                             "x": 0, "y": 0, "operation": "subtract"}}
        g["663"] = {"class_type": "GrowMask", "inputs": {"mask": rmask[0], "expand": 64, "tapered_corners": True}}
        g["664"] = {"class_type": "MaskComposite", "inputs": {"destination": ["662", 0], "source": ["663", 0],
                                                             "x": 0, "y": 0, "operation": "multiply"}}
        g["665"] = {"class_type": "MaskToImage", "inputs": {"mask": ["664", 0]}}
        g["666"] = {"class_type": "ImageBlur", "inputs": {"image": ["665", 0], "blur_radius": 8, "sigma": 4.0}}
        g["667"] = {"class_type": "ImageToMask", "inputs": {"image": ["666", 0], "channel": "red"}}
        g["668"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_pos, "clip": ["4", 1]}}
        g["669"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_neg, "clip": ["4", 1]}}
        g["670"] = {"class_type": "InpaintModelConditioning",
                    "inputs": {"positive": ["668", 0], "negative": ["669", 0], "vae": ["4", 2],
                               "pixels": img, "mask": ["667", 0], "noise_mask": True}}
        g["671"] = {"class_type": "KSampler",
                    "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                               "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(band),
                               "model": ["604", 0], "positive": ["670", 0], "negative": ["670", 1],
                               "latent_image": ["670", 2]}}
        g["672"] = {"class_type": "VAEDecode", "inputs": {"samples": ["671", 0], "vae": ["4", 2]}}
        img = ["672", 0]
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": img}}
    return g


UNIFY_LORA_ALL = 0.5


def _lora_all(g, regions, st):
    """_am_graph 결과에 LoRA 캐릭터의 LoRA를 그림 전체 모델·글에 한 번 (따로 칠하기 대신)"""
    ch = next((r["char"] for r in regions if r["char"] and r["char"].get("lora")), None)
    if not ch:
        return g
    g["90"] = {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": ch["lora"],
                                                       "strength_model": float(st), "strength_clip": float(st)}}
    g["80"]["inputs"]["model"] = ["90", 0]
    for n in g.values():
        if n["class_type"] == "CLIPTextEncode" and n["inputs"].get("clip") == ["4", 1]:
            n["inputs"]["clip"] = ["90", 1]
    return g


def _graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, v, hires=None, init=None):
    if v.startswith("AMIB"):
        rest = v[4:]
        lora = rest.startswith("L")
        dn, _, sg = (rest[1:] if lora else rest).partition("s")
        sg = min(10.0, float(sg or 8))
        s2 = dict(s, width=init["w"], height=init["h"])
        g = _am_graph(W, cfg, s2, base_pos, base_neg, regions, seed, prefix, None, dict(init, denoise=float(dn or 0.75)), REGION_SOLO)
        g["7b"] = {"class_type": "ImageBlur", "inputs": {"image": ["7", 0], "blur_radius": min(31, int(sg * 3)), "sigma": sg}}
        g["5"]["inputs"]["pixels"] = ["7b", 0]
        return _lora_all(g, regions, UNIFY_LORA_ALL) if lora else g
    if v.startswith("AMI"):       # 합친 그림 위에 어텐션 영역 img2img (+ LoRA 캐릭터는 SAM 몸 마스크로 LoRA 0.6)
        mode = v[3] if len(v) > 3 and v[3] in "CNL" else ""     # AMIC = 예전 영역 글(duo·2boys) / AMIN·AMIL = 따로 칠하기 없음
        solo = mode != "C"
        ini = dict(init, denoise=float(v[3 + bool(mode):] or 0.5))
        s2 = dict(s, width=init["w"], height=init["h"])
        has_lora = any(r["char"] and r["char"].get("lora") for r in regions)
        if has_lora and mode in ("", "C"):
            return _amb_graph(W, cfg, s2, base_pos, base_neg, regions, seed, prefix, 0.6, None, ini, solo)
        g = _am_graph(W, cfg, s2, base_pos, base_neg, regions, seed, prefix, None, ini, solo)
        return _lora_all(g, regions, UNIFY_LORA_ALL) if has_lora and mode == "L" else g
    if v == "P":
        return W.build_duo2_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, pass1_only=True, hires=hires)
    if v.startswith("PT"):
        g = W.build_duo2_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, pass1_only=True, hires=hires)
        return _timestep(g, float(v[2:] or 0.2))
    if v == "AM":
        return _am_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, hires)
    if v.startswith("AMB"):
        return _amb_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, float(v[3:] or 0.7), hires)
    if v in ("LC", "LCb"):
        return _lc_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, hires, back=(v == "LCb"))
    if v == "LP":
        return _lp_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, (init or {})["front_mask"], hires)
    if v.startswith("LF"):
        m = LF_RE.fullmatch(v)
        return _lf_graph(W, cfg, s, base_pos, base_neg, regions, seed, prefix, float(m.group(1) or 1.0), hires,
                         grow=int(m.group(2) or 24), blur=int(m.group(3) or 16), band=float(m.group(4) or 0),
                         word=m.group(5), debug=bool(m.group(8)), wide=bool(m.group(9)))
    raise ValueError(v)


def _sheet(rows, dest, H=420):
    """rows: -> 한 줄 비교 그림"""
    from PIL import Image, ImageDraw
    ims = []
    for lb, p, note in rows:
        if not p or not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB")
        ims.append((lb, note, im.resize((max(1, int(im.width * H / im.height)), H))))
    if not ims:
        return None
    sheet = Image.new("RGB", (sum(i.width for _, _, i in ims) + 8 * (len(ims) - 1), H + 44), "white")
    dr = ImageDraw.Draw(sheet)
    x = 0
    for lb, note, im in ims:
        sheet.paste(im, (x, 22))
        dr.text((x + 3, 4), lb, fill="black")
        dr.text((x + 3, H + 26), (note or "")[:int(im.width / 6)], fill=(170, 0, 0) if note and note != "ok" else (0, 110, 0))
        x += im.width + 8
    sheet.save(dest)
    return dest


def run(nk, kit, args):
    import nk_webtoon as W
    import nk_compose as C
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    ids = [int(x) for x in args.cuts] or [cid for cid, c in cuts.items() if c.get("_roles")]
    variants = [v.strip() for v in (args.variants or "P,PT0.2,AM").split(",") if v.strip()]
    seeds = [int(x) for x in (args.seeds or "71,72").split(",") if x.strip()]
    name = args.name or "%s_%s" % (args.ep, time.strftime("%m%d_%H%M"))
    run_root = "regtest/%s" % name
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), run_root)
    for v0 in variants:
        v = v0[:-2] if v0.endswith("+O") else v0          # +O = OpenPose 뼈대(episodes/<ep>/poses/cutNN.png)로 자리·자세 고정
        if not (v == "P" or v == "AM" or (v.startswith("PT") and v[2:].replace(".", "", 1).isdigit())
                or (v.startswith("AMB") and (v[3:] == "" or v[3:].replace(".", "", 1).isdigit()))
                or (v.startswith("AMI") and (v[3:] == "" or v[3:].replace(".", "", 1).isdigit()))
                or (v[:4] in ("AMIC", "AMIN", "AMIL") and (v[4:] == "" or v[4:].replace(".", "", 1).isdigit()))
                or __import__("re").fullmatch(r"AMIBL?(\d*\.?\d+)?(s\d+(\.\d+)?)?", v)
                or LF_RE.fullmatch(v) or v in ("LP", "LC", "LCb") or LC_K_RE.fullmatch(v)):
            print("[ERROR] unknown variant %s (P / PT0.2 / AM / AMB0.7 / AMI0.5 / AMIN0.4 / AMIL0.4 / AMIB0.75s8 / LF, +O = with pose)" % v0); sys.exit(1)
    if any(v.startswith(("AM", "LF", "LP")) for v in variants) and not args.dry:
        c = nk.Comfy(cfg.get("server", "auto"))
        missing = [n for n in AM_NODES if n not in c._get("/object_info/" + n)]
        if missing:
            print("[skip AM] ComfyUI에 %s 노드가 없음 (Acly comfyui-tooling-nodes 설치 필요)" % ", ".join(missing))
            variants = [v for v in variants if not v.startswith(("AM", "LF", "LP"))]
    plan = {}
    for cid in ids:
        cut = cuts.get(cid)
        if not cut or not cut.get("_roles"):
            print("[skip] cut %d is not a two-character cut" % cid); continue
        if any(ch.get("lora") for _, ch in cut["_roles"]) and any(v[:3] not in ("AMB", "AMI") for v in variants):
            print("[note] cut %d: LoRA 캐릭터가 있음 -> P·PT·AM 은 LoRA 없이 1단계만 (AMB·AMI 는 LoRA 캐릭터 자리를 LoRA로 다시 그림)" % cid)
        s = _settings(nk, W, cfg, conti, cut)
        base_pos, base_neg, regions = W._duo_parts(nk, cfg, conti, cut, s)
        _tagfix(regions, getattr(args, "tagfix", None))
        plan[cid] = (cut, s, base_pos, base_neg, regions)
        print("\n== cut %d %sx%s  %s" % (cid, s["width"], s["height"], " / ".join(r["key"] for r in regions)))
        print("  BASE: " + base_pos)
        for r in regions:
            print("  %s %s: %s" % (r["key"], r["span"], r["pos1"]))
    poses = {}
    if any(v.endswith("+O") for v in variants):
        for cid in plan:
            if os.path.exists(W._pose_file(kit, args.ep, cid)):
                poses[cid] = W._pose_upload(nk, cfg, kit, args.ep, cid, args.dry)
            else:
                print("[skip +O] cut %d: no pose %s (nk ep pose %s %d <picture>)" % (cid, W._pose_file(kit, args.ep, cid), args.ep, cid))
    solo, solo_back, fronts = {}, {}, {}
    if any(v == "LP+O" for v in variants):
        sc0 = float(args.hires) if getattr(args, "hires", None) else 1.0
        for cid, (cut, s, bp, bn, regions) in plan.items():
            if cid not in poses:
                continue
            fi = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
            Wd, H = int(s["width"]), int(s["height"])
            if sc0 > 1.0:
                Wd, H = int(round(Wd * sc0 / 8)) * 8, int(round(H * sc0 / 8)) * 8
            f, n = _front_mask(W, kit, args.ep, cid, regions, fi, Wd, H, out_dir)
            fronts[cid] = W._upload_input(nk, cfg, f, "%s_cut%02d_front.png" % (args.ep, cid), args.dry)
            bk = [r for i, r in enumerate(regions) if i != fi][0]
            fb = _solo_pose(W, kit, args.ep, cid, bk["span"], os.path.join(out_dir, "back"))
            if fb:
                solo_back[cid] = W._upload_input(nk, cfg, fb, "%s_cut%02d_backsolo.png" % (args.ep, cid), args.dry)
            print("cut %d LP: back = %s first (pose %s), front = %s over body mask (%d skeleton px) %s"
                  % (cid, bk["key"], "only" if fb else "BOTH", regions[fi]["key"], n, f))
    if any(v in ("LC+O", "LCb+O") or (v.endswith("+O") and LC_K_RE.fullmatch(v[:-2])) for v in variants):
        for cid, (cut, s, bp, bn, regions) in plan.items():
            if cid not in poses:
                continue
            fi = next((i for i, r in enumerate(regions) if r["char"] and r["char"].get("lora")), 0)
            bk = [r for i, r in enumerate(regions) if i != fi][0]
            fb = _solo_pose(W, kit, args.ep, cid, bk["span"], os.path.join(out_dir, "back"))
            if fb and cid not in solo_back:
                solo_back[cid] = W._upload_input(nk, cfg, fb, "%s_cut%02d_backsolo.png" % (args.ep, cid), args.dry)
    if any((v.endswith("+O") and v.startswith("LF") and LF_RE.fullmatch(v[:-2]).group(6)) or v in ("LC+O", "LCb+O")
           or (v.endswith("+O") and LC_K_RE.fullmatch(v[:-2])) for v in variants):
        for cid, (cut, s, bp, bn, regions) in plan.items():
            if cid not in poses:
                continue
            fr = next((r for r in regions if r["char"] and r["char"].get("lora")), regions[0])
            f = _solo_pose(W, kit, args.ep, cid, fr["span"], out_dir)
            if f:
                solo[cid] = W._upload_input(nk, cfg, f, "%s_cut%02d_solo.png" % (args.ep, cid), args.dry)
                print("cut %d: stage 1 pose = %s only (%s)" % (cid, fr["key"], f))
            else:
                print("[skip s] cut %d: no keypoints json" % cid)
    inits = {}
    if any(v.startswith("AMI") for v in variants):
        from PIL import Image
        for cid in plan:
            f = W._final_file(kit, args.ep, cid)
            if getattr(args, "init", None) == "orig":        # 합친 그림(unify 전)에서 시작 - unify 방식끼리 공정 비교
                o = os.path.join(W.ep_dir(kit, args.ep), "cuts_unify", "orig", "cut%02d.png" % cid)
                f = o if os.path.exists(o) else f
                print("cut %d init: %s" % (cid, f))
            if os.path.exists(f):
                w0, h0 = Image.open(f).size
                inits[cid] = {"image": W._upload_input(nk, cfg, f, "%s_regtest_init_cut%02d.png" % (args.ep, cid), args.dry),
                              "w": int(w0) // 8 * 8, "h": int(h0) // 8 * 8}
            else:
                print("[skip AMI] cut %d: no final picture" % cid)
    d = conti.get("duo") or {}
    dflt = cfg.get("defaults") or {}
    hires = {"scale": float(args.hires), "denoise": float(dflt.get("hires_denoise", 0.35)),
             "steps": int(dflt.get("hires_steps", 20))} if getattr(args, "hires", None) else None
    times, res_all = {}, {}
    picks = {}
    for v in variants:
        jobs = []
        vb = v[:-2] if v.endswith("+O") else v
        tag = v.replace(".", "").replace("+", "")
        mk = LF_RE.fullmatch(vb) if vb.startswith("LF") else None
        mck = LC_K_RE.fullmatch(vb)
        if (mk and mk.group(7)) or mck:
            # k 방식: ① 후보 K장 (시드 sd, sd+1000, ...) -> 상대 자리 침범이 가장 적은 것 -> ②
            K = int(mk.group(7)) if mk else int(mck.group(1))
            kw = dict(grow=int(mk.group(2) or 24), blur=int(mk.group(3) or 16), band=float(mk.group(4) or 0), word=mk.group(5),
                      wide=bool(mk.group(9))) if mk else {}
            dn1 = float(mk.group(1) or 1.0) if mk else 1.0
            use_solo = bool(mk.group(6)) if mk else True
            sc0 = float(hires["scale"]) if hires else 1.0
            jobs1 = []
            for cid, (cut, s, bp, bn, regions) in plan.items():
                if v.endswith("+O") and cid not in poses:
                    continue
                for sd in seeds:
                    for k in range(K):
                        label = "cut%02d_%s_s%d_c%d" % (cid, tag, sd, k)
                        g = _lf_graph(W, cfg, s, bp, bn, regions, sd + 1000 * k, "nk/regtest_%s/%s" % (name, label),
                                      dn1, hires, stage1_only=True, **kw)
                        if v.endswith("+O"):
                            W._pose_cn(g, s, poses[cid], float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5)))
                            if use_solo and cid in solo:
                                g["705"] = {"class_type": "LoadImage", "inputs": {"image": solo[cid]}}
                                g["706"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["705", 0]))
                                for k2, n2 in g.items():
                                    if n2["class_type"] == "ControlNetApplyAdvanced":
                                        n2["inputs"]["image"] = ["706", 0]
                        jobs1.append({"label": label, "graph": g, "positive": bp, "negative": bn, "settings": s,
                                      "seed": sd + 1000 * k, "meta": {"regtest": {"variant": v, "cut": cid, "stage": 1}}})
            if args.dry:
                for j in jobs1:
                    print("[dry] %s nodes=%d saves=%s" % (j["label"], len(j["graph"]),
                          [n["inputs"]["filename_prefix"].split("/")[-1] for n in j["graph"].values() if n["class_type"] == "SaveImage"]))
                continue
            t0 = time.time()
            r1 = nk.run_jobs(cfg, jobs1, run_root + "/" + tag + "_cand", False) or []
            t1 = time.time() - t0
            cdir = os.path.join(out_dir, tag + "_cand")
            got = {}
            for r in r1:
                got.setdefault(r["label"], []).append(os.path.join(cdir, r["file"]))
            jobs = []
            for cid, (cut, s, bp, bn, regions) in plan.items():
                if v.endswith("+O") and cid not in poses:
                    continue
                Wd, H = int(s["width"]), int(s["height"])
                if sc0 > 1.0:
                    Wd, H = int(round(Wd * sc0 / 8)) * 8, int(round(H * sc0 / 8)) * 8
                for sd in seeds:
                    cands = []
                    for k in range(K):
                        fs = sorted(got.get("cut%02d_%s_s%d_c%d" % (cid, tag, sd, k), []))
                        import numpy as np
                        from PIL import Image
                        def _gray(f):
                            a = np.asarray(Image.open(f).convert("RGB"))
                            return bool((a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all())
                        pic = next((f for f in fs if not _gray(f)), None)
                        msk = next((f for f in fs if f != pic and _gray(f)), None)
                        if pic and msk:
                            cands.append((pic, msk))
                    if not cands:
                        print("[skip k] cut %d s%d: no stage-1 candidates" % (cid, sd)); continue
                    best, rows = _lf_pick(W, kit, args.ep, cid, regions, cands, Wd, H)
                    picks["cut%02d_s%d" % (cid, sd)] = {"chosen": best[0], "overlap": {str(k): round(o, 4) for k, o, _ in rows},
                                                        "suggest_front": "lora" if best[1] < LCK_BACK_AT else "partner"}
                    print("cut %d s%d: partner-zone overlap %s -> candidate %d"
                          % (cid, sd, " / ".join("c%d %.3f" % (k, o) for k, o, _ in rows), best[0]))
                    up = W._upload_input(nk, cfg, best[2], "%s_cut%02d_s%d_stage1.png" % (args.ep, cid, sd))
                    label = "cut%02d_%s_s%d" % (cid, tag, sd)
                    if mck:
                        for back in (False, True):
                            lab = "cut%02d_%s%s_s%d" % (cid, tag, "b" if back else "", sd)
                            g = _lc_graph(W, cfg, s, bp, bn, regions, sd, "nk/regtest_%s/%s" % (name, lab), hires,
                                          back=back, init_img=up)
                            if v.endswith("+O"):
                                W._pose_cn(g, s, poses[cid], float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5)))
                                if cid in solo_back and "721107" in g:
                                    g["707"] = {"class_type": "LoadImage", "inputs": {"image": solo_back[cid]}}
                                    g["708"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["707", 0]))
                                    g["721107"]["inputs"]["image"] = ["708", 0]
                            jobs.append({"label": lab, "graph": g, "positive": bp, "negative": bn, "settings": s, "seed": sd,
                                         "meta": {"regtest": {"variant": v, "cut": cid, "stage1_candidate": best[0],
                                                              "front": "partner" if back else "lora"}}})
                        continue
                    g = _lf_graph(W, cfg, s, bp, bn, regions, sd, "nk/regtest_%s/%s" % (name, label),
                                  dn1, hires, init_img=up, **kw)
                    if v.endswith("+O"):
                        W._pose_cn(g, s, poses[cid], float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5)))
                    jobs.append({"label": label, "graph": g, "positive": bp, "negative": bn, "settings": s, "seed": sd,
                                 "meta": {"regtest": {"variant": v, "cut": cid, "stage1_candidate": best[0]}}})
            t0 = time.time()
            res = nk.run_jobs(cfg, jobs, run_root + "/" + tag, False) or []
            times[v] = round((t1 + time.time() - t0) / max(1, len(jobs)), 1)
            for r in res:
                res_all[r["label"]] = os.path.join(out_dir, tag, r["file"])
            print("[time] %s: %.1f s per final picture (%d finals, %d stage-1 candidates)" % (v, times[v], len(jobs), len(jobs1)))
            continue
        for cid, (cut, s, bp, bn, regions) in plan.items():
            if v.endswith("+O") and cid not in poses:
                continue
            if vb.startswith("AMI") and cid not in inits:
                continue
            for sd in seeds:
                label = "cut%02d_%s_s%d" % (cid, tag, sd)
                if vb == "LP" and cid not in fronts:
                    continue
                g = _graph(W, cfg, s, bp, bn, regions, sd, "nk/regtest_%s/%s" % (name, label), vb,
                           None if vb.startswith("AMI") else hires,
                           {"front_mask": fronts[cid]} if vb == "LP" else inits.get(cid))
                if v.endswith("+O"):
                    W._pose_cn(g, s, poses[cid], float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5)))
                    if vb in ("LC", "LCb"):
                        if cid in solo:
                            g["705"] = {"class_type": "LoadImage", "inputs": {"image": solo[cid]}}
                            g["706"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["705", 0]))
                        if cid in solo_back:
                            g["707"] = {"class_type": "LoadImage", "inputs": {"image": solo_back[cid]}}
                            g["708"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["707", 0]))
                        for k2, n2 in g.items():
                            if n2["class_type"] != "ControlNetApplyAdvanced":
                                continue
                            if k2 == "721107" and cid in solo_back:
                                n2["inputs"]["image"] = ["708", 0]
                            elif k2 != "721107" and cid in solo:
                                n2["inputs"]["image"] = ["706", 0]
                    if vb == "LP" and cid in solo_back:      # 1단계(뒤 캐릭터+배경)만 뒤 캐릭터 뼈대, 2단계(646)는 두 사람 뼈대
                        g["705"] = {"class_type": "LoadImage", "inputs": {"image": solo_back[cid]}}
                        g["706"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["705", 0]))
                        for k2, n2 in g.items():
                            if n2["class_type"] == "ControlNetApplyAdvanced" and k2 != "72646":
                                n2["inputs"]["image"] = ["706", 0]
                    if vb.startswith("LF") and LF_RE.fullmatch(vb).group(6):
                        if cid not in solo:
                            continue
                        # ①(먼저 그릴 사람) 단계만 그 사람 뼈대로, ②(상대 617·637)·경계 띠(671)는 두 사람 뼈대 그대로
                        g["705"] = {"class_type": "LoadImage", "inputs": {"image": solo[cid]}}
                        g["706"] = dict(g["702"], inputs=dict(g["702"]["inputs"], image=["705", 0]))
                        for k2, n2 in g.items():
                            if n2["class_type"] == "ControlNetApplyAdvanced" and k2 not in ("72617", "72637", "72671"):
                                n2["inputs"]["image"] = ["706", 0]
                jobs.append({"label": label, "graph": g, "positive": bp, "negative": bn, "settings": s, "seed": sd,
                             "meta": {"regtest": {"variant": v, "cut": cid}}})
        if args.dry:
            for j in jobs:
                print("[dry] %s nodes=%d %s" % (j["label"], len(j["graph"]),
                                                sorted({n["class_type"] for n in j["graph"].values()})))
            continue
        if not jobs:
            continue
        t0 = time.time()
        res = nk.run_jobs(cfg, jobs, run_root + "/" + tag, False) or []
        times[v] = round((time.time() - t0) / max(1, len(jobs)), 1)
        for r in res:
            res_all[r["label"]] = os.path.join(out_dir, tag, r["file"])
        print("[time] %s: %.1f s per picture (%d pictures)" % (v, times[v], len(jobs)))
    if args.dry:
        return
    judge = {"times_s": times, "cuts": {}, "picks": picks}
    import hashlib
    judge["poses_md5"] = {str(cid): hashlib.md5(open(W._pose_file(kit, args.ep, cid)[:-4] + "_kp.json", "rb").read()).hexdigest()[:12]
                          for cid in poses if os.path.exists(W._pose_file(kit, args.ep, cid)[:-4] + "_kp.json")}
    allp = [p for p in res_all.values() if os.path.exists(p)] + \
        [W._final_file(kit, args.ep, cid) for cid in plan if os.path.exists(W._final_file(kit, args.ep, cid))]
    heads = C.head_counts(nk, kit, cfg, args.ep, allp, run="regtest_heads") if C.HEAD_CHECK and allp else {}

    def jdg(cut, p):
        sc, fl, det = C.judge(kit, conti, cut, p)
        hn, ha = heads.get(p, (None, []))
        hf, hp = C.head_flags(hn, ha, C.head_allowed(conti, cut)[0])
        return round(sc - hp, 3), fl + hf, dict(det, heads=hn)
    for cid, (cut, s, bp, bn, regions) in plan.items():
        rows = []
        try:
            src = C.pick_sources(W, kit, conti, cut)
            for k, c2 in src.items():
                rows.append(("solo %s (cut %d)" % (k, c2), W._final_file(kit, args.ep, c2), ""))
        except LookupError:
            pass
        now = W._final_file(kit, args.ep, cid)
        jc = {}
        o = os.path.join(W.ep_dir(kit, args.ep), "cuts_unify", "orig", "cut%02d.png" % cid)
        if getattr(args, "init", None) == "orig" and os.path.exists(o):
            rows.append(("compose (before unify)", o, ""))
        if os.path.exists(now):
            sc, fl, _ = jdg(cut, now)
            jc["now"] = {"score": sc, "flags": fl}
            rows.append(("now (final)", now, "; ".join(fl) or "ok"))
        for v in variants:
            for sd in seeds:
                p = res_all.get("cut%02d_%s_s%d" % (cid, v.replace(".", "").replace("+", ""), sd))
                if not p or not os.path.exists(p):
                    continue
                sc, fl, det = jdg(cut, p)
                jc["%s_s%d" % (v, sd)] = {"score": sc, "flags": fl, "file": p}
                rows.append(("%s s%d" % (v, sd), p, "; ".join(fl) or "ok"))
        judge["cuts"][cid] = jc
        sp = _sheet(rows, os.path.join(out_dir, "cut%02d_sheet.png" % cid))
        print("cut %d sheet: %s" % (cid, sp))
        for k, x in jc.items():
            print("   %-12s %6.2f  %s" % (k, x["score"], "; ".join(x["flags"]) or "ok"))
    with open(os.path.join(out_dir, "judge.json"), "w", encoding="utf-8") as f:
        json.dump(judge, f, ensure_ascii=False, indent=1)
    print("\nsaved: %s\\judge.json  times: %s" % (out_dir, times))


#   앞서 돈 LCk regtest 의 고른 1단계 그림 + 그때 상대 뼈대(back/pose_solo)를 그대로 쓰고 2단계만 같은 시드로 다시 돌리며 층을 저장
LAYER_SAVES = {"1140": ("L1", ["8", 0]), "1141": ("plate", ["488", 0]), "1142": ("R", ["1108", 0]),
               "1143": ("A", ["1116", 0]), "1144": ("B", ["1124", 0]), "1145": ("n1", ["1114", 0]), "1146": ("nR", ["1122", 0])}
LAYER_MASKS = {"1150": ("m1", ["602", 0]), "1151": ("mR", ["1111", 0]), "1152": ("h1", ["1131", 0]), "1153": ("hR", ["1132", 0])}


def _lc_layers_graph(W, cfg, s, bp, bn, regions, seed, prefix, hires, init_img, back_pose, pose_st=1.0, pose_end=0.5,
                     partner_mask=None):
    """LCk 2단계 그래프(상대 앞까지) + 머리 틀 + 층마다 저장 노드. 저장 노드 번호 -> 층 이름은 LAYER_SAVES·LAYER_MASKS"""
    g = _lc_graph(W, cfg, s, bp, bn, regions, seed, prefix + "_B", hires, back=True, init_img=init_img, partner_mask=partner_mask)
    W._pose_cn(g, s, back_pose, pose_st, pose_end)          # 상대 그리기(1107)에만 붙음 (배경판 487은 400번대라 안 붙음) = regtest LCk 와 같음
    g["1130"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["600", 1], "text": "head"}}
    for nid, img in (("1131", ["8", 0]), ("1132", ["1108", 0])):
        g[nid] = {"class_type": "SAM3_Detect", "inputs": {"model": ["600", 0], "image": img, "conditioning": ["1130", 0],
                                                         "threshold": 0.3, "refine_iterations": 2, "individual_masks": False}}
    del g["9"]
    for nid, (lay, src) in LAYER_SAVES.items():
        g[nid] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "%s_%s" % (prefix, lay), "images": src}}
    for nid, (lay, src) in LAYER_MASKS.items():
        g["%d" % (int(nid) + 10)] = {"class_type": "MaskToImage", "inputs": {"mask": src}}
        g[nid] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "%s_%s" % (prefix, lay), "images": ["%d" % (int(nid) + 10), 0]}}
    return g


def lc_layers(nk, kit, args):
    import glob
    import numpy as np
    import nk_webtoon as W
    from PIL import Image
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    root = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), "regtest")
    src = os.path.join(root, args.src)
    jd = json.load(open(os.path.join(src, "judge.json"), encoding="utf-8"))
    tag = args.variant.replace(".", "").replace("+", "")
    name = args.name or "layers_" + args.src
    d = conti.get("duo") or {}
    dflt = cfg.get("defaults") or {}
    hires = {"scale": float(args.hires), "denoise": float(dflt.get("hires_denoise", 0.35)), "steps": int(dflt.get("hires_steps", 20))}
    c = None if args.dry else nk.Comfy(cfg.get("server", "auto"))
    rep = {}

    def gray(f):
        a = np.asarray(Image.open(f).convert("RGB"))
        return bool((a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all())
    for cid in [int(x) for x in args.cuts]:
        cut = cuts.get(cid)
        if not cut or not cut.get("_roles"):
            print("[skip] cut %d is not a two-character cut" % cid); continue
        s = _settings(nk, W, cfg, conti, cut)
        bp, bn, regions = W._duo_parts(nk, cfg, conti, cut, s)
        _tagfix(regions, getattr(args, "tagfix", None))
        for sd in [int(x) for x in args.seeds.split(",") if x.strip()]:
            pk = (jd.get("picks") or {}).get("cut%02d_s%d" % (cid, sd))
            fs = sorted(glob.glob(os.path.join(src, tag + "_cand", "cut%02d_%s_s%d_c%d_*.png" % (cid, tag, sd, pk["chosen"])))) if pk else []
            pic = next((f for f in fs if not gray(f)), None)
            bpose = os.path.join(src, "back", "pose_solo_cut%02d.png" % cid)
            if not pic or not os.path.exists(bpose):
                print("[skip] cut %d s%d: no chosen stage-1 picture or partner pose in %s" % (cid, sd, src)); continue
            label = "cut%02d_s%d" % (cid, sd)
            up1 = W._upload_input(nk, cfg, pic, "%s_%s_L1.png" % (args.ep, label), args.dry)
            upb = W._upload_input(nk, cfg, bpose, "%s_cut%02d_backsolo_L.png" % (args.ep, cid), args.dry)
            g = _lc_layers_graph(W, cfg, s, bp, bn, regions, sd, "nk/regtest_%s/%s" % (name, label), hires, up1, upb,
                                 float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5)))
            print("== %s: stage 1 = %s | partner pose = %s | %d nodes" % (label, os.path.basename(pic), bpose, len(g)))
            if args.dry:
                continue
            t0 = time.time()
            outs = c.wait(c.queue(g), label)
            od = os.path.join(root, name, label)
            os.makedirs(od, exist_ok=True)
            got = []
            for nid, (lay, _) in list(LAYER_SAVES.items()) + list(LAYER_MASKS.items()):
                ims = (outs.get(nid) or {}).get("images") or []
                if ims:
                    c.fetch(ims[0], os.path.join(od, lay + ".png")); got.append(lay)
            r = {"layers": got, "secs": round(time.time() - t0, 1), "stage1": pic}
            for lay, old in (("A", "cut%02d_%s_s%d.png" % (cid, tag, sd)), ("B", "cut%02d_%sb_s%d.png" % (cid, tag, sd))):
                po, pn = os.path.join(src, tag, old), os.path.join(od, lay + ".png")
                if os.path.exists(po) and os.path.exists(pn):
                    a = np.asarray(Image.open(po).convert("RGB"), np.int16)
                    b = np.asarray(Image.open(pn).convert("RGB"), np.int16)
                    if a.shape == b.shape:
                        df = np.abs(a - b).max(2)
                        r["same_as_old_" + lay] = {"mean": round(float(df.mean()), 3), "px_over_16": round(float((df > 16).mean()), 5)}
            rep[label] = r
            print("   saved %s (%.0f s) %s" % (", ".join(got), r["secs"], {k: v for k, v in r.items() if k.startswith("same")}))
    if not args.dry:
        os.makedirs(os.path.join(root, name), exist_ok=True)
        json.dump(rep, open(os.path.join(root, name, "layers.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("next: python tools/lc_composite.py %s" % name)


def add_parser(esub, nk, kit):
    a = esub.add_parser("lclayers", help="TEST: redo LCk stage 2 of an earlier regtest and save every layer (for offline compositing tests)")
    a.add_argument("ep")
    a.add_argument("src", help="earlier regtest name under runs/regtest/ (LCk run with judge.json picks)")
    a.add_argument("cuts", nargs="+")
    a.add_argument("--variant", default="LCk3+O")
    a.add_argument("--seeds", default="71")
    a.add_argument("--hires", type=float, default=1.5)
    a.add_argument("--tagfix")
    a.add_argument("--name")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: lc_layers(nk, kit, x))
    a = esub.add_parser("regtest", help="TEST: two-character cut with regional prompts in one NoobAI picture (compare with compose)")
    a.add_argument("ep")
    a.add_argument("cuts", nargs="*")
    a.add_argument("--variants", help='default "P,PT0.2,AM" (P latent masks / PT0.2 + timestep split / AM attention masks)')
    a.add_argument("--seeds", help="default 71,72")
    a.add_argument("--name", help="folder under runs/regtest/")
    a.add_argument("--hires", type=float, help="final-size pass, e.g. 1.5 (same as the comic finals; default off = draft size)")
    a.add_argument("--tagfix", help='TEST: per-character tag edits, e.g. "mychar:-long tail;mychar:!thick tail;mychar:~tail" (- remove, + add, ! add negative, ~ remove negative)')
    a.add_argument("--init", choices=["final", "orig"], default="final",
                   help="AMI start picture: final (default) / orig = the compose picture before unify (cuts_unify/orig)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
    a = esub.add_parser("unify", help="repaint two-character finals with NoobAI + attention regions (keeps the compose layout)")
    a.add_argument("ep")
    a.add_argument("cuts", nargs="*")
    a.add_argument("--denoise", default="0.4", help="how much to repaint (0.4 = default; 0.55 makes new little figures)")
    a.add_argument("--seeds", help="default 71")
    a.add_argument("--no-apply", dest="no_apply", action="store_true", help="make candidates only, keep the finals")
    a.add_argument("--use", nargs="*", help="5=71 use that candidate / 5=0 back to the compose picture")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run_unify(nk, kit, x))


def _severe(fl):
    import nk_compose as C
    return sum(1 for x in fl if any(s in x for s in C.SEVERE))


def unify(nk, kit, conti, ids=None, denoise=0.5, seeds=(71,), apply=True, dry=False):
    """-> {"used": {cid: seed or 0}, "flags": {cid: [...]}}. 후보가 합친 그림보다 흠이 많거나 색이 쏠리면 합친 그림 유지.
    다시 돌려도 늘 합친 그림(cuts_unify/orig)에서 시작 (칠한 것을 또 칠하지 않음)"""
    import nk_webtoon as W
    import nk_compose as C
    import nk_restyle as RS
    import shutil
    from PIL import Image
    cfg = nk.load_presets()
    ep = conti["_ep"]
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    ids = [cid for cid in (ids or [c for c, ct in cuts.items() if ct.get("_roles")])
           if cid in cuts and cuts[cid].get("_roles") and os.path.exists(W._final_file(kit, ep, cid))]
    out = {"used": {}, "flags": {}}
    if not ids:
        print("unify: no two-character cut with a final picture"); return out
    d = os.path.join(W.ep_dir(kit, ep), "cuts_unify")
    os.makedirs(os.path.join(d, "cand"), exist_ok=True)
    rec_p = os.path.join(d, "unify.json")
    rec = json.load(open(rec_p, encoding="utf-8")) if os.path.exists(rec_p) else {}
    jobs, info = [], {}
    for cid in ids:
        cut = cuts[cid]
        f = W._final_file(kit, ep, cid)
        orig = os.path.join(d, "orig", "cut%02d.png" % cid)
        r0 = rec.get(str(cid)) or {}
        again = bool(r0.get("final_md5")) and r0["final_md5"] == C._md5(f) and os.path.exists(orig)
        src = orig if again else f                 # 지금 최종본이 이미 unify 결과면 합친 그림(orig)에서 다시
        if not again and os.path.exists(orig) and C._md5(orig) != C._md5(f):
            # 그 사이 합치기를 다시 함 -> 옛 합친 그림·옛 후보는 버림 (고르기 화면에 섞이지 않게)
            import glob as _g
            for x in _g.glob(os.path.join(d, "cand", "cut%02d_s*.png" % cid)) + [orig]:
                os.remove(x)
            rec.pop(str(cid), None)
        w0, h0 = Image.open(src).size
        init = {"image": W._upload_input(nk, cfg, src, "%s_unify_cut%02d.png" % (ep, cid), dry), "w": w0 // 8 * 8, "h": h0 // 8 * 8}
        s = _settings(nk, W, cfg, conti, cut)
        bp, bn, regions = W._duo_parts(nk, cfg, conti, cut, s)
        info[cid] = {"size": [w0, h0], "src": src, "again": again}
        for sd in seeds:
            label = "cut%02d_s%d" % (cid, sd)
            g = _graph(W, cfg, s, bp, bn, regions, sd, "nk/%s_unify/%s" % (ep, label), "AMI%g" % denoise, None, init)
            jobs.append({"label": label, "graph": g, "positive": bp, "negative": bn, "settings": s, "seed": sd})
    print("unify %s: %d cuts x %d seeds, denoise %.2f (attention regions + NoobAI; LoRA characters: SAM body + LoRA 0.6)"
          % (ep, len(ids), len(seeds), denoise))
    res = nk.run_jobs(cfg, jobs, "%s/unify" % ep, dry) or []
    if dry:
        return out
    src_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), ep, "unify")
    cands = {}
    for r in res:
        cid, sd = int(r["label"][3:5]), int(r["seed"])
        w0, h0 = info[cid]["size"]
        p = os.path.join(d, "cand", r["label"] + ".png")
        Image.open(os.path.join(src_dir, r["file"])).convert("RGB").resize((w0, h0), Image.LANCZOS).save(p)
        cands.setdefault(cid, []).append((sd, p))
    allp = [info[cid]["src"] for cid in cands] + [p for v in cands.values() for _, p in v]
    heads = C.head_counts(nk, kit, cfg, ep, allp, run="unify_heads") if C.HEAD_CHECK else {}
    # 작은 머리까지 셈 (같은 SAM 결과를 문턱만 낮춰 다시 셈 = 추가 계산 없음): 다시 칠하면서 구석에 작은 고양이·사람이 새로 생김
    small = C.head_counts(nk, kit, cfg, ep, allp, run="unify_heads", min_area=SMALL_HEAD) if C.HEAD_CHECK else {}
    figs = C.sam_blobs(nk, kit, cfg, ep, allp, prompt=UNIFY_FIG_PROMPTS, run="unify_figs", threshold=UNIFY_FIG_TH) if C.HEAD_CHECK else {}

    def jdg(cut, p):
        sc, fl, _ = C.judge(kit, conti, cut, p)
        hn, ha = heads.get(p, (None, []))
        hf, hp = C.head_flags(hn, ha, C.head_allowed(conti, cut)[0])
        return round(sc - hp, 3), fl + hf
    for cid, cl in cands.items():
        cut = cuts[cid]
        f, src = W._final_file(kit, ep, cid), info[cid]["src"]
        s0, f0 = jdg(cut, src)
        n_src = (small.get(src) or (None, []))[0]
        la = RS.lab_mean(Image.open(src))
        best, cfl = None, {}
        for sd, p in sorted(cl):
            sc, fl = jdg(cut, p)
            lb = RS.lab_mean(Image.open(p))
            cast = ((lb[1] - la[1]) ** 2 + (lb[2] - la[2]) ** 2) ** 0.5
            if cast >= RS.CAST_ON:
                fl = fl + ["color cast vs compose picture (%.0f)" % cast]
            gs = RS.grid_score(Image.open(p))
            if gs >= RS.GRID_ON:
                fl = fl + ["grid pattern over the picture (%.0f)" % gs]
            nf = C.new_figures(figs.get(src), figs.get(p))
            if nf:
                fl = fl + ["new figure: %s not in the compose picture" % ", ".join("%.2f%%" % (a * 100) for a in nf)]
            n_c, a_c = small.get(p) or (None, [])
            if n_src is not None and n_c is not None and n_c > n_src and not any(x.startswith("heads") for x in fl):
                fl = fl + ["heads: %d small heads, compose picture had %d (%s) - new little figure?"
                           % (n_c, n_src, ", ".join("%.2f%%" % (a * 100) for a in a_c))]
            print("[unify] cut %02d seed %d: %s" % (cid, sd, "; ".join(fl) or "ok"))
            cfl[str(sd)] = fl
            key = (_severe(fl), len(fl), -sc, sd)
            if best is None or key < best[0]:
                best = (key, sd, p, fl)
        print("[unify] cut %02d compose picture: %s" % (cid, "; ".join(f0) or "ok"))
        # 합친 그림보다 심한 흠이 늘거나 색이 쏠리면 합친 그림 유지
        take = best is not None and best[0][0] <= _severe(f0) and not any("color cast" in x for x in best[3])
        r = dict(rec.get(str(cid)) or {}, now_flags=f0, cand={str(sd): p for sd, p in cl}, denoise=denoise)
        r["cand_flags"] = dict(r.get("cand_flags") or {}, **cfl)      # 후보마다 흠 (손으로 고를 때 씀)
        if take and apply:
            orig = os.path.join(d, "orig", "cut%02d.png" % cid)
            if not info[cid]["again"]:
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                shutil.copy(f, orig)               # 합친 그림 보관 (되돌리기: --use N=0)
            shutil.copy(best[2], f)
            r.update(use=best[1], flags=best[3], final_md5=C._md5(f))
            out["used"][cid] = best[1]
            if best[3]:
                out["flags"][cid] = best[3]
            print("   -> cut %02d uses unify seed %d" % (cid, best[1]))
        else:
            out["used"][cid] = r.get("use", 0) if info[cid]["again"] else 0
            if not info[cid]["again"]:
                r.update(use=0, flags=[], final_md5=None)
            print("   -> cut %02d keeps %s%s" % (cid, "the earlier unify picture" if info[cid]["again"] else "the compose picture",
                                               "" if take else " (candidate worse or color cast)"))
        rec[str(cid)] = r
        _sheet([("compose", src, "; ".join(f0) or "ok")] + [("unify s%d" % sd, p, "") for sd, p in sorted(cl)],
               os.path.join(d, "cut%02d_cmp.png" % cid))
    json.dump(rec, open(rec_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def run_unify(nk, kit, args):
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    if args.use:
        import shutil
        import nk_compose as C
        d = os.path.join(W.ep_dir(kit, args.ep), "cuts_unify")
        rp = os.path.join(d, "unify.json")
        for ch in args.use:
            cid, sd = [int(x) for x in ch.split("=")]
            rec = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
            fin = W._final_file(kit, args.ep, cid)
            r0 = rec.get(str(cid)) or {}
            is_uni = bool(r0.get("final_md5")) and r0["final_md5"] == C._md5(fin)     # 지금 최종본 = 다시 칠한 그림?
            if sd == 0 and not is_uni:
                print("cut %02d already uses the compose picture" % cid); continue
            src = os.path.join(d, "orig", "cut%02d.png" % cid) if sd == 0 else os.path.join(d, "cand", "cut%02d_s%d.png" % (cid, sd))
            if not os.path.exists(src):
                print("[ERROR] not found:", src); sys.exit(1)
            if sd and not is_uni:                      # 지금 최종본(합친 그림)을 보관하고 바꿈
                os.makedirs(os.path.join(d, "orig"), exist_ok=True)
                shutil.copy(fin, os.path.join(d, "orig", "cut%02d.png" % cid))
            shutil.copy(src, fin)
            r = rec.setdefault(str(cid), {})
            r.update(use=sd, manual=True, flags=[] if sd == 0 else (r.get("cand_flags") or {}).get(str(sd), []),
                     final_md5=C._md5(W._final_file(kit, args.ep, cid)) if sd else None)
            json.dump(rec, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("cut %02d -> %s" % (cid, "compose picture (before unify)" if sd == 0 else "unify seed %d" % sd))
        return
    seeds = [int(x) for x in (args.seeds or "71").split(",") if x.strip()]
    unify(nk, kit, conti, [int(x) for x in args.cuts] or None, float(args.denoise), seeds, not args.no_apply, args.dry)
    print("then: nk ep restyle / letter %s  (back: nk ep unify %s --use 5=0)" % (args.ep, args.ep))
