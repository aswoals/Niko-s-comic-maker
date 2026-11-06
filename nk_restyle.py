# -*- coding: utf-8 -*-
"""
nk_restyle.py - 완성 컷에 그림체를 한 번에 입히기

왜: 컷마다 그림체가 조금씩 다르면 한 만화로 안 보임.
방법: 그리기는 지금처럼(무늬 정확하게) -> 마지막에 Qwen-Image-Edit 2509(fp8, 1장 약 90초)로 컷 전체를 같은 문장으로 다시 그림.
    컷 전체가 같은 그림체가 됨.
  1) 문장에 물건 이름을 나열하면 Qwen이 그걸 '그려 넣음': "glasses ..
     "Do not add hair" -> 금발 머리카락. -> 물건 이름·'하지 마' 문장을 빼고, 모든 컷에 있는 것(구도·배경·빛·인물)만 말함 (KEEP)
  2) FluxKontextImageScale이 비율을 바꾸며 가운데를 잘라냄 (1344x768 -> 1328x800) -> 되돌릴 때 약 5% 늘어남.
     -> 원래 비율 그대로 약 1MP(16의 배수)로 줄이는 ImageScale.
  3) denoise 1.0 유지: 0.8 이하는 그림체가 거의 안 바뀌고(원본과 거의 같음) 머리카락이 생기는 건 그대로였음
  4) 같은 문장이라도 시드마다 사고가 다름 -> 컷마다 시드 2개(기본)를 그리고 판별기 비교로 경고가 적은 쪽을 고름
사용: nk ep restyle <ep> [컷 번호...] [--style picturebook] [--seed 21] [--tries 2] [--dry]
      nk ep restyle <ep> --check          (이미 그린 후보를 원본과 판별기로 다시 비교 -> 다시 고름)
      nk ep restyle <ep> --use 5=22 7=0   (컷5는 시드 22 후보로, 컷7은 그림체 입히지 않은 원본으로)
      결과: episodes/<ep>/cuts_<style>/cutNN.png (고른 것, 원래 최종본 크기) / cand/cutNN_s<시드>.png (후보 전부)
            episodes/<ep>/cuts_<style>/check.json (후보별 판별기 비교: 새로 생긴 것 / 사라진 것, 고른 시드)
      조립: nk ep letter <ep> --style picturebook  -> episodes/<ep>/out_picturebook/
그림체 문장은 presets.yaml의 restyle: {이름: 문장} 으로 더하거나 바꿀 수 있음."""
import os, sys, json, math

STYLES = {
    "picturebook": ("Redraw this illustration as a soft hand-drawn picture-book illustration with thin dark brown outlines, "
                    "flat pastel colors and simple soft shading."),
    "watercolor": "Redraw this illustration as a soft watercolor picture-book illustration with light pencil lines and pale paper texture.",
    "anime": "Redraw this illustration as a soft cel-shaded anime illustration with gentle gradients and thin clean lines.",
    "pencil": "Redraw this illustration as a colored pencil drawing with visible hatching strokes on white paper.",
}
KEEP = " Keep the composition, the background, the lighting and the characters exactly the same."
KEEP_OBJ = " Keep the composition, the background and the lighting exactly the same."
DENOISE = 1.0

QWEN_SETS = {
    "2509": {"unet": "qwen_image_edit_2509_fp8_e4m3fn.safetensors",
             "lightning": "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors",
             "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "vae": "qwen_image_vae.safetensors"},
    # 파일 = Comfy-Org/Qwen-Image-Edit_ComfyUI fp8mixed (20,533,762,817 B) + lightx2v 2511 Lightning 8단계 LoRA (849,608,296 B)
    # 공식 2511 예제 그래프 = 2509와 같은 부품 + 'Edit Model Reference Method'(index_timestep_zero)를 조건 두 개에 한 번씩
    #   (예제 메모: Comfy 파일이면 없어도 되지만 명시해도 같은 값) -> ref_method
    "2511": {"unet": "qwen_image_edit_2511_fp8mixed.safetensors",
             "lightning": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors",
             "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "vae": "qwen_image_vae.safetensors",
             "ref_method": "index_timestep_zero"},
}
QWEN = dict(QWEN_SETS["2509"])


def use_qwen(ver):
    """이번 실행만 Qwen 편집 모델 바꾸기 (QWEN 사전을 제자리에서 바꿔서 R.QWEN을 쓰는 모든 곳에 적용)"""
    ver = str(ver or "2509")
    if ver not in QWEN_SETS:
        print("[ERROR] unknown Qwen edit version %s (have %s)" % (ver, ", ".join(QWEN_SETS))); sys.exit(1)
    QWEN.clear(); QWEN.update(QWEN_SETS[ver])
    print("Qwen edit model:", ver, QWEN["unet"])
    return ver


def qwen_ver():
    return next((k for k, v in QWEN_SETS.items() if v["unet"] == QWEN["unet"]), "?")


def add_ref_method(g, ks="3"):
    """2511: KSampler 앞 조건(positive/negative)마다 FluxKontextMultiReferenceLatentMethod 한 번씩 (공식 예제와 같게)"""
    m = QWEN.get("ref_method")
    if not m:
        return g
    for slot, nid in (("positive", "130"), ("negative", "131")):
        g[nid] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                  "inputs": {"conditioning": g[ks]["inputs"][slot], "reference_latents_method": m}}
        g[ks]["inputs"][slot] = [nid, 0]
    return g


def fit_size(w, h, area=1024 * 1024, mult=16):
    """원래 비율 그대로(오차 최소) 약 1MP, 16의 배수. 예: 2304x960 -> 1536x640 / 1344x1728 -> 896x1152"""
    ar = w / float(h)
    best = None
    for hh in range(512, 2049, mult):
        ww = int(round(hh * ar / mult)) * mult
        if ww < 512 or ww > 2048:
            continue
        s = abs(math.log((ww / float(hh)) / ar)) * 20 + abs(math.log(ww * hh / float(area)))
        if best is None or s < best[0]:
            best = (s, ww, hh)
    return best[1], best[2]


def graph(img, prompt, seed, prefix, w, h, denoise=DENOISE, ref=None):
    """공식 Qwen-Image-Edit 2509 템플릿 구조 + Lightning 8단계 (tools/qwen_back.py graph와 같은 부품, 각도 LoRA 없음).
    크기: FluxKontextImageScale(비율을 바꿔 잘라냄) 대신 ImageScale로 원래 비율 그대로 w x h"""
    g = {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN["unet"], "weight_dtype": "default"}},
        "89": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["37", 0], "strength_model": 1.0,
                                                               "lora_name": QWEN["lightning"]}},
        "66": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["89", 0], "shift": 3.0}},
        "75": {"class_type": "CFGNorm", "inputs": {"model": ["66", 0], "strength": 1.0}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN["clip"], "type": "qwen_image", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN["vae"]}},
        "78": {"class_type": "LoadImage", "inputs": {"image": img}},
        "117": {"class_type": "ImageScale", "inputs": {"image": ["78", 0], "upscale_method": "lanczos",
                                                       "width": int(w), "height": int(h), "crop": "disabled"}},
        "88": {"class_type": "VAEEncode", "inputs": {"pixels": ["117", 0], "vae": ["39", 0]}},
        "111": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["38", 0], "vae": ["39", 0],
                                                                       "image1": ["117", 0], "prompt": prompt}},
        "110": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["38", 0], "vae": ["39", 0],
                                                                       "image1": ["117", 0], "prompt": ""}},
        "3": {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": 8, "cfg": 1.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "denoise": float(denoise), "model": ["75", 0],
                                                   "positive": ["111", 0], "negative": ["110", 0], "latent_image": ["88", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }
    if ref:                                   # 참고 그림(picture 2) - nk_backfix: 시트 뒷모습
        g["79"] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        g["111"]["inputs"]["image2"] = ["79", 0]
        g["110"]["inputs"]["image2"] = ["79", 0]
    return add_ref_method(g)


def style_text(cfg, name, objects=False):
    t = (cfg.get("restyle") or {}).get(name) or STYLES.get(name)
    if not t:
        print("[ERROR] unknown style '%s' (%s, or add it to presets.yaml restyle:)" % (name, ", ".join(sorted(STYLES))))
        sys.exit(1)
    return t.strip() + (KEEP_OBJ if objects else KEEP)


# ------------------------------------------------------------------ 판별기 비교 (원본 vs 그림체 입힌 것)
# 시험에서 나온 사고: 없던 안경·머리띠·금발 머리카락·작은 캐릭터가 생김 / 노을빛이 사라짐 / 가짜 말풍선·글자.
# 판별기(WD)로 원본과 새 그림을 같은 자리(전체 + 두 명 컷은 좌우 절반)에서 재서 '없던 것이 생김'·'있던 것이 사라짐'을 적음.
ADDED = {
    "hair": "blonde_hair|brown_hair|orange_hair|red_hair|grey_hair|light_brown_hair",
    "text": "text|english_text|speech_bubble|signature|watermark|artist_name|letterboxed|border|black_border",
    "people_duo": "3boys|4boys|5boys|6+boys|1girl|2girls|multiple_girls",
    "people_solo": "2boys|multiple_boys|duo|1girl|2girls|multiple_girls",
    "people_none": "1boy|1girl|2boys|2girls|multiple_boys|multiple_girls|solo|duo|child|furry|anthro",
    "headwear": "headband|hairband|hair_ornament|hair_bow",
    "eyewear": "glasses|round_eyewear|rimless_eyewear|semi-rimless_eyewear|black-framed_eyewear|red-framed_eyewear|"
               "blue-framed_eyewear|rectangular_eyewear|opaque_glasses|sunglasses",
    "sky": "sky|blue_sky|cloud|cloudy_sky",
}
LOST = {
    "light": "sunset|evening|orange_sky|twilight|night|night_sky|backlighting|sunlight|light_rays",
}
ON, OFF = 0.4, 0.2          # 새로 생김 = 원본 < OFF 이고 새 그림 >= ON / 사라짐 = 원본 >= ON 이고 새 그림 < 0.15

#   (깨끗한 컷 11도 같은 경고) -> 판별기로는 못 봄. 그림 자체에서 '가로·세로로 곧게 뻗은, 양쪽이 평평한 경계'의 길이를 잼.
#   -> 새 그림 >= 8 이고 원본의 3배 이상이면 깨짐. 깨짐은 다른 경고보다 먼저 봄
MOSAIC_ON = 8.0


GRID_ON = 400.0


def grid_score(im):
    """그림 전체에 규칙적인 격자선(Qwen 타일 깨짐)이 있나: 가로·세로 기울기 평균 줄의 주파수 봉우리 / 중앙값 (두 방향 중 작은 값).
    mosaic_score(긴 곧은 경계)가 못 잡는 가는 격자용"""
    import numpy as np
    a = np.asarray(im.convert("L"), dtype=np.float32)
    out = []
    for arr in (a, a.T):
        prof = np.abs(np.diff(arr, axis=1)).mean(axis=0)
        prof = prof - prof.mean()
        P = np.abs(np.fft.rfft(prof)) ** 2
        n = len(prof)
        seg = P[max(8, n // 64): max(9, n // 4)]
        out.append(float(seg.max() / (np.median(seg) + 1e-6)) if len(seg) else 0.0)
    return min(out)


def mosaic_score(im, size=512, edge=90, flat=40, run=24):
    """곧은 가로·세로 경계(양쪽이 평평) 길이 합 / 폭. 모자이크·네모 조각 깨짐일수록 큼"""
    import numpy as np
    from PIL import Image
    a = np.asarray(im.convert("RGB").resize((size, size), Image.BILINEAR), dtype=np.int16)
    tot = 0
    for arr in (a, a.transpose(1, 0, 2)):
        H = arr.shape[0]
        y = np.arange(4, H - 5)
        e = np.abs(arr[y + 2] - arr[y - 1]).sum(-1)          # y|y+1 사이의 색 차이
        fu = np.abs(arr[y - 1] - arr[y - 3]).sum(-1)         # 위쪽 평평
        fd = np.abs(arr[y + 2] - arr[y + 4]).sum(-1)         # 아래쪽 평평
        hu = np.abs(np.diff(arr[y - 2], axis=1)).sum(-1)     # 경계를 따라 매끈 (위)
        hd = np.abs(np.diff(arr[y + 3], axis=1)).sum(-1)     # (아래)
        m = (e >= edge) & (fu < flat) & (fd < flat)
        m = m[:, 1:] & (hu < flat) & (hd < flat)
        for row in m:
            if row.any():
                r = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
                L = np.where(r == -1)[0] - np.where(r == 1)[0]
                tot += int(L[L >= run].sum())
    return tot / float(size)


#   밝기(L)는 그림체판이 거의 다 밝아짐(+0~23) -> 25 넘을 때만 참고 경고
CAST_ON, BRIGHT_ON = 17.0, 25.0


def lab_mean(im):
    """그림 평균 Lab (sRGB D65, 256px)"""
    import numpy as np
    from PIL import Image
    a = np.asarray(im.convert("RGB").resize((256, 256), Image.BILINEAR), dtype=float) / 255.0
    a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = a @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116.0)
    return (float((116 * f[..., 1] - 16).mean()), float((500 * (f[..., 0] - f[..., 1])).mean()),
            float((200 * (f[..., 1] - f[..., 2])).mean()))


def _broken(r):
    return any(str(f).startswith("all: mosaic") or str(f).startswith("all: color cast") for f in (r or {}).get("flags") or [])


def _severity(r):
    """경고가 같은 수일 때 덜 나쁜 쪽: 경고 난 항목의 변화량 합"""
    s = 0.0
    sc = (r or {}).get("scores") or {}
    for f in (r or {}).get("flags") or []:
        try:
            nm, rest = f.split(": ", 1)
            kind, key = rest.split(" ")[0], rest.split(" ")[1]
            a, b = sc.get("%s:%s%s" % (nm, "-" if kind == "lost" else "+", key)) or [0, 0]
            s += abs(b - a)
        except Exception:
            s += 1.0
    return s


def _crops(im, cut):
    """[(자리 이름, 그림, 그 자리 캐릭터 dict 목록)] - 전체 + 두 명 컷은 좌우 절반 (콘티 cast side 기준)"""
    w, h = im.size
    roles = cut.get("_roles") or []
    if roles:
        out = [("all", im, [ch for _, ch in roles])]
        for r, ch in roles:
            box = (0, 0, w // 2, h) if r.get("side") == "left" else (w // 2, 0, w, h)
            out.append((r.get("side", "?"), im.crop(box), [ch]))
        return out
    return [("all", im, [cut["_char"]] if cut.get("_char") else [])]


def _tag_img(kit, im, tmp):
    import nk_tagger
    im.save(tmp)
    t = nk_tagger.tags(kit, tmp) or {}
    try:
        os.remove(tmp)
    except OSError:
        pass
    return t


def check_one(nk, kit, conti, cut, orig_path, new_path, tmpdir):
    """-> {"flags": [...], "scores": {자리:규칙: [원본, 새 그림]}} . 판별기가 없으면 None"""
    import nk_tagger
    from PIL import Image
    ok, why = nk_tagger.available(kit)
    if not ok:
        return None
    a = Image.open(orig_path).convert("RGB")
    b = Image.open(new_path).convert("RGB").resize(a.size)
    duo = len(cut.get("_roles") or []) >= 2
    pool = list((conti.get("_cast") or {}).values())
    flags, scores = [], {}
    ma, mb = mosaic_score(a), mosaic_score(b)
    scores["all:mosaic"] = [round(ma, 2), round(mb, 2)]
    if mb >= MOSAIC_ON and mb >= 3 * ma:
        flags.append("all: mosaic glitch (%.1f -> %.1f)" % (ma, mb))
    (La, Aa, Ba), (Lb, Ab, Bb) = lab_mean(a), lab_mean(b)
    dab = ((Ab - Aa) ** 2 + (Bb - Ba) ** 2) ** 0.5
    scores["all:color"] = [[round(La, 1), round(Aa, 1), round(Ba, 1)], [round(Lb, 1), round(Ab, 1), round(Bb, 1)]]
    if dab >= CAST_ON:
        flags.append("all: color cast (Lab a,b %+.0f,%+.0f -> %+.0f,%+.0f, shift %.0f)" % (Aa, Ba, Ab, Bb, dab))
    if abs(Lb - La) >= BRIGHT_ON:
        flags.append("all: %s (L %.0f -> %.0f)" % ("much brighter" if Lb > La else "much darker", La, Lb))
    for (nm, ca, who), (_, cb, _) in zip(_crops(a, cut), _crops(b, cut)):
        ta = _tag_img(kit, ca, os.path.join(tmpdir, "_rs_a.png"))
        tb = _tag_img(kit, cb, os.path.join(tmpdir, "_rs_b.png"))
        rules = {k: v for k, v in ADDED.items() if not k.startswith("people")}
        if nm == "all":
            rules["people"] = ADDED["people_duo" if duo else ("people_solo" if who else "people_none")]
        # 이 자리 캐릭터가 원래 안 쓰는 '다른 캐릭터 전용 소품'(duo_exclusive: 안경 등)이 생기면 표시.
        # 두 명 컷 전체 그림은 두 사람이 다 있어서 제외 (좌우 절반에서 봄)
        names = set(ch.get("name") for ch in who)
        if not (nm == "all" and duo):
            excl = []
            for other in pool:
                if other.get("name") in names:
                    continue
                excl += [x.strip().replace(" ", "_") for x in str(other.get("duo_exclusive") or "").split(",") if x.strip()]
            if any("eyewear" in x or x == "glasses" for x in excl):
                excl.append("glasses")
            if excl:
                rules["other_props"] = "|".join(sorted(set(excl)))
        for key, tag in rules.items():
            sa, sb = nk_tagger.score(ta, tag), nk_tagger.score(tb, tag)
            scores["%s:+%s" % (nm, key)] = [round(sa, 3), round(sb, 3)]
            if sa < OFF and sb >= ON:
                flags.append("%s: new %s (%.2f -> %.2f)" % (nm, key, sa, sb))
        if nm == "all":
            for key, tag in LOST.items():
                sa, sb = nk_tagger.score(ta, tag), nk_tagger.score(tb, tag)
                scores["%s:-%s" % (nm, key)] = [round(sa, 3), round(sb, 3)]
                if sa >= ON and sb < 0.15:
                    flags.append("%s: lost %s (%.2f -> %.2f)" % (nm, key, sa, sb))
    return {"flags": flags, "scores": scores}


def _md5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _cand_dir(W, kit, ep, name):
    return os.path.join(W.ep_dir(kit, ep), "cuts_" + name, "cand")


def _cands(cdir, cid):
    """[(seed, path)] of cuts_<style>/cand/cutNN_s<seed>.png"""
    if not os.path.isdir(cdir):
        return []
    pre = "cut%02d_s" % cid
    out = []
    for f in sorted(os.listdir(cdir)):
        if f.startswith(pre) and f.endswith(".png") and f[len(pre):-4].isdigit():
            out.append((int(f[len(pre):-4]), os.path.join(cdir, f)))
    return out


def run_check(nk, kit, args, conti, name, ids):
    """후보(시드별)를 원본과 판별기로 비교 -> 경고가 가장 적은 후보를 cutNN.png로 (--use로 고른 컷은 그대로)"""
    import nk_webtoon as W
    import shutil
    dst_dir = os.path.join(W.ep_dir(kit, args.ep), "cuts_" + name)
    cdir = _cand_dir(W, kit, args.ep, name)
    cuts = {int(ct["id"]): ct for ct in conti["cuts"]}
    path = os.path.join(dst_dir, "check.json")
    rep = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    for cid in ids:
        f = W._final_file(kit, args.ep, cid)
        cands = _cands(cdir, cid)
        if not (os.path.exists(f) and cands):
            continue
        rec = rep.get(str(cid)) or {}
        for sd, g in cands:
            r = check_one(nk, kit, conti, cuts[cid], f, g, cdir)
            if r is None:
                print("[check] tagger not available - skipped (no automatic choice; cutNN.png = first seed)")
                r = {"flags": [], "scores": {}}
            rec["s%d" % sd] = r
            print("[check] cut %02d seed %d: %s" % (cid, sd, "; ".join(r["flags"]) or "ok"))
        if not rec.get("manual"):
            # 깨짐(모자이크) 없는 것 > 경고 수 적은 것 > 변화량 작은 것(0.1 단위 — 더 작은 차이는 의미 없음:
            best = min(cands, key=lambda x: (_broken(rec["s%d" % x[0]]), len(rec["s%d" % x[0]]["flags"]),
                                             round(_severity(rec["s%d" % x[0]]), 1), x[0]))
            rec.pop("fallback", None)
            if _broken(rec["s%d" % best[0]]):
                # 후보가 전부 깨짐 -> 그림체 안 입힌 원본이 깨진 그림보다 나음
                rec["use"] = 0
                rec["fallback"] = "all seeds broken (mosaic / color cast) -> original kept. try: nk ep restyle %s %d --seed 23" % (args.ep, cid)
                shutil.copy(f, os.path.join(dst_dir, "cut%02d.png" % cid))
                print("   -> cut %02d: every seed is broken (mosaic / color cast) -> original picture kept" % cid)
            else:
                rec["use"] = best[0]
                shutil.copy(best[1], os.path.join(dst_dir, "cut%02d.png" % cid))
                print("   -> cut %02d uses seed %d" % (cid, best[0]))
        rep[str(cid)] = rec
    with open(path, "w", encoding="utf-8") as fo:
        json.dump(rep, fo, ensure_ascii=False, indent=1)
    print("check -> %s  (flags are hints: look at every cut. other seed: nk ep restyle %s --use 5=22)" % (path, args.ep))


def run_use(kit, args, name):
    import nk_webtoon as W
    import shutil
    dst_dir = os.path.join(W.ep_dir(kit, args.ep), "cuts_" + name)
    cdir = _cand_dir(W, kit, args.ep, name)
    path = os.path.join(dst_dir, "check.json")
    rep = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    for ch in args.use:
        try:
            cid, sd = [int(x) for x in ch.split("=")]
        except ValueError:
            print("[ERROR] --use needs cut=seed, e.g. 5=22"); sys.exit(1)
        if str(sd) == "0" or sd == 0:            # 5=0 : 그림체 입히지 않은 원본 그대로
            shutil.copy(W._final_file(kit, args.ep, cid), os.path.join(dst_dir, "cut%02d.png" % cid))
        else:
            src = os.path.join(cdir, "cut%02d_s%d.png" % (cid, sd))
            if not os.path.exists(src):
                print("[ERROR] no candidate", src); sys.exit(1)
            shutil.copy(src, os.path.join(dst_dir, "cut%02d.png" % cid))
        rec = rep.get(str(cid)) or {}
        rec["use"], rec["manual"] = sd, True
        rep[str(cid)] = rec
        print("cut %02d -> %s" % (cid, "original (no restyle)" if sd == 0 else "seed %d" % sd))
    with open(path, "w", encoding="utf-8") as fo:
        json.dump(rep, fo, ensure_ascii=False, indent=1)


def run(nk, kit, args):
    import nk_webtoon as W
    from PIL import Image
    cfg = nk.load_presets()
    c = W.load_conti(nk, kit, args.ep)
    name = args.style or c.get("restyle") or "picturebook"
    ids = [int(x) for x in args.cuts] if args.cuts else [int(ct["id"]) for ct in c["cuts"]]
    if getattr(args, "use", None):
        run_use(kit, args, name)
        return
    if getattr(args, "check", False):
        run_check(nk, kit, args, c, name, ids)
        return
    text = style_text(cfg, name)
    text_obj = style_text(cfg, name, objects=True)
    cutmap = {int(ct["id"]): ct for ct in c["cuts"]}
    dn = args.denoise if getattr(args, "denoise", None) is not None else float(c.get("restyle_denoise", DENOISE))
    tries = max(1, int(getattr(args, "tries", None) or c.get("restyle_tries", 2)))
    todo = []
    #   (check.json의 src_md5 = 그때 원본 md5). 컷 번호를 적거나 --force면 다시 함
    ck_path = os.path.join(W.ep_dir(kit, args.ep), "cuts_" + name, "check.json")
    ck = json.load(open(ck_path, encoding="utf-8")) if os.path.exists(ck_path) else {}
    skipped = []
    for cid in ids:
        f = W._final_file(kit, args.ep, cid)
        if not os.path.exists(f):
            print("[skip] cut %d: no final picture yet (%s)" % (cid, f))
            continue
        if not args.cuts and not getattr(args, "force", False) and (ck.get(str(cid)) or {}).get("src_md5") == _md5(f) \
                and os.path.exists(os.path.join(W.ep_dir(kit, args.ep), "cuts_" + name, "cut%02d.png" % cid)):
            skipped.append(cid)
            continue
        todo.append((cid, f))
    if skipped:
        print("restyle: %d cuts unchanged since the last restyle - skipped %s (--force to redo)" % (len(skipped), skipped))
    if not todo:
        print("[ERROR] nothing to restyle"); sys.exit(1)
    seed = args.seed if args.seed is not None else 21
    seeds = [seed + k for k in range(tries)]
    print("restyle %s: %d cuts x %d seeds %s, style '%s', denoise %.2f (~85 s each, about %d min)\n  %s\n  (object cuts: %s)"
          % (args.ep, len(todo), tries, seeds, name, dn, len(todo) * tries * 85 // 60 + 1, text, text_obj))
    jobs = []
    for cid, f in todo:
        w0, h0 = Image.open(f).size
        w, h = fit_size(w0, h0)
        img = W._upload_input(nk, cfg, f, "%s_cut%02d_final.png" % (args.ep, cid), args.dry)
        ct = cutmap.get(cid) or {}
        tx = text if (ct.get("_roles") or ct.get("_char")) else text_obj
        for sd in seeds:
            label = "cut%02d_s%d" % (cid, sd)
            jobs.append({"label": label, "graph": graph(img, tx, sd, "nk/%s_restyle_%s/%s" % (args.ep, name, label), w, h, dn),
                         "positive": tx, "negative": "", "seed": sd,
                         "settings": {"cfg": 1.0, "steps": 8, "width": w, "height": h, "denoise": dn, "model": QWEN["unet"]}})
    res = nk.run_jobs(cfg, jobs, "%s/restyle_%s" % (args.ep, name), args.dry)
    if args.dry:
        return
    src_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "restyle_" + name)
    cdir = _cand_dir(W, kit, args.ep, name)
    os.makedirs(os.path.join(cdir, "_old"), exist_ok=True)
    finals = dict(todo)
    for cid in finals:                      # 예전 후보(옛 최종본·다른 시드)는 _old/로 치움 -> 선택에 섞이지 않게
        for sd, pth in _cands(cdir, cid):
            os.replace(pth, os.path.join(cdir, "_old", os.path.basename(pth)))
    done = []
    for r in res:
        cid = int(r["label"][3:5])
        im = Image.open(os.path.join(src_dir, r["file"])).convert("RGB")
        w, h = Image.open(finals[cid]).size
        im.resize((w, h), Image.LANCZOS).save(os.path.join(cdir, r["label"] + ".png"))
        if cid not in done:
            done.append(cid)
    # 새로 그린 컷은 예전 수동 선택(--use)을 지움
    path = os.path.join(os.path.dirname(cdir), "check.json")
    if os.path.exists(path):
        rep = json.load(open(path, encoding="utf-8"))
        for cid in done:
            rep.pop(str(cid), None)
        with open(path, "w", encoding="utf-8") as fo:
            json.dump(rep, fo, ensure_ascii=False, indent=1)
    print("restyled candidates -> %s" % cdir)
    run_check(nk, kit, args, c, name, done)
    try:                                    # 다음 전체 실행 때 '안 바뀐 컷' 건너뛰기용
        rep = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        for cid in done:
            rep.setdefault(str(cid), {})["src_md5"] = _md5(finals[cid])
        with open(path, "w", encoding="utf-8") as fo:
            json.dump(rep, fo, ensure_ascii=False, indent=1)
    except Exception as e:
        print("[WARN] could not record src_md5:", e)
    print("next: look at every cut, then nk ep letter %s --style %s" % (args.ep, name))
