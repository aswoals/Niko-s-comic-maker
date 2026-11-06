# -*- coding: utf-8 -*-
"""
nk_styleref.py - 그림체 기준 그림 (IP-Adapter 'style transfer')

왜: 태그만 있는 캐릭터는 같은 프롬프트라도 시드마다 그림체가 흔들림.
    프롬프트·설정은 셋 다 같고 시드만 다름 (meta.json). 검수는 '맞게 그렸나'만 보니 그림체는 운에 맡겨짐.
    -> 에피소드의 모든 컷이 같은 '기준 그림' 한 장의 그림체를 따라가게 함.

방식: ComfyUI_IPAdapter_plus 의 IPAdapterAdvanced, weight_type "style transfer".
      SDXL에서는 그림체를 맡는 블록 하나(6번)에만 기준 그림을 넣음 -> 내용(캐릭터·물건)은 안 베끼고 그림체만 (InstantStyle 방식).
      출처: github.com/cubiq/ComfyUI_IPAdapter_plus IPAdapterPlus.py (weight_type 'style transfer' -> SDXL {6: weight})
설치: 없음
      models/ipadapter/ip_adapter_Noobtest_800000.bin (kataragi, NoobAI용 비공식·"학습 부족" 표기)
      models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors
      -> 효과는 시험으로 확인해야 함 (nk ep styleref)

쓰는 법 (시험에서 효과 확인 후):
                                style_ref_weight: 1.0               (선택)
                                style_ref_type: style transfer      (선택)
  컷 하나만 끄기:               style_ref: none
  작가별 기준 그림: styles/<작가>.png 가 있으면 compile 이 자동으로 넣음 (plan 에 style_ref: none 이면 안 넣음)

      -> runs/styleref/<이름>/sheet_cutNN.png  (가로 = 없음 / 세기별, 세로 = 후보)"""
import os
import sys
import json
import hashlib

FILE_TAG = "@file:"                     # LoadImage 에 이 표시가 있으면 nk.Comfy.queue 가 ComfyUI input 으로 올림
DEF_MODEL = "ip_adapter_Noobtest_800000.bin"
DEF_CLIP = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
DEF_TYPE = "style transfer"
KEYS = ("style_ref", "style_ref_weight", "style_ref_type")
NODES = ["IPAdapterModelLoader", "IPAdapterAdvanced", "CLIPVisionLoader", "LoadImage"]
_STOP = ("UNETLoader", "UnetLoaderGGUF", "ModelSamplingAuraFlow")


def _off(v):
    return v is None or v is False or str(v).strip().lower() in ("", "none", "off", "false", "0")


def resolve_path(kit, p):
    if _off(p):
        return None
    p = str(p).strip().strip('"')
    return p if os.path.isabs(p) else os.path.join(kit, p)


def cut_settings(conti, cut):
    """콘티(에피소드) 값 -> 컷 값 순서로 덮어씀. 반환: settings 에 넣을 dict (끄면 style_ref="")"""
    out = {}
    for k in KEYS:
        v = cut.get(k, conti.get(k)) if cut is not None else conti.get(k)
        if v is not None:
            out[k] = "" if (k == "style_ref" and _off(v)) else v
    return out


def attach(g, s, kit, cfg=None):
    """build_graph 그래프에 기준 그림을 붙임. NoobAI(체크포인트)에서 온 모델을 쓰는 KSampler(cfg>1)에만."""
    path = resolve_path(kit, s.get("style_ref"))
    if not path:
        return g
    if not os.path.exists(path):
        print("[WARN] style_ref not found, drawing without it: %s" % path)
        return g
    d = (cfg or {}).get("defaults", {}) if cfg else {}
    w = float(s.get("style_ref_weight") or d.get("style_ref_weight") or 1.0)
    wt = str(s.get("style_ref_type") or d.get("style_ref_type") or DEF_TYPE)
    g["9800"] = {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": d.get("style_ref_model", DEF_MODEL)}}
    g["9801"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": d.get("style_ref_clip", DEF_CLIP)}}
    g["9802"] = {"class_type": "LoadImage", "inputs": {"image": FILE_TAG + os.path.abspath(path)}}

    def from_ckpt(ref):
        for _ in range(30):
            node = g.get(str(ref[0])) if isinstance(ref, list) and ref else None
            if not node:
                return False
            if node.get("class_type") == "CheckpointLoaderSimple":
                return True
            if node.get("class_type") in _STOP:
                return False
            ref = node.get("inputs", {}).get("model")
        return False

    made, nid = {}, 9810
    for k, n in list(g.items()):
        if n.get("class_type") != "KSampler":
            continue
        inp = n["inputs"]
        m = inp.get("model")
        if float(inp.get("cfg", 1.0)) <= 1.0 or not from_ckpt(m):
            continue
        key = (str(m[0]), m[1])
        if key not in made:
            while str(nid) in g:
                nid += 1
            g[str(nid)] = {"class_type": "IPAdapterAdvanced",
                           "inputs": {"model": list(m), "ipadapter": ["9800", 0], "image": ["9802", 0],
                                      "clip_vision": ["9801", 0], "weight": w, "weight_type": wt,
                                      "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                                      "embeds_scaling": "V only"}}
            made[key] = str(nid)
        inp["model"] = [made[key], 0]
    return g


INSET = 0.06


def square_png(src, dst):
    """IP-Adapter 는 기준 그림을 가운데 정사각형으로 잘라 씀 -> 미리 같은 방식으로 잘라서 올림 (어디가 쓰이는지 눈으로 확인 가능)"""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        w, h = im.size
        m = min(w, h)
        im = im.crop(((w - m) // 2, (h - m) // 2, (w - m) // 2 + m, (h - m) // 2 + m))
        k = int(m * INSET)
        im.crop((k, k, m - k, m - k)).save(dst)
        return dst
    except Exception:
        return src


def upload_name(path):
    h = hashlib.md5(open(path, "rb").read()).hexdigest()[:12]
    return "ref_%s.png" % h


# ------------------------------------------------------------------ preflight
def preflight(nk, cfg, c=None):
    """문제 목록 (빈 목록 = OK). ComfyUI 에 노드·파일이 있는지"""
    probs = []
    try:
        c = c or nk.Comfy(cfg.get("server", "auto"))
        for n in NODES:
            if n not in c._get("/object_info/" + n):
                probs.append("ComfyUI has no node %s (style_ref needs ComfyUI_IPAdapter_plus)" % n)
        if not probs:
            d = cfg.get("defaults", {})
            ipa = c._get("/object_info/IPAdapterModelLoader")["IPAdapterModelLoader"]["input"]["required"]["ipadapter_file"][0]
            cv = c._get("/object_info/CLIPVisionLoader")["CLIPVisionLoader"]["input"]["required"]["clip_name"][0]
            if d.get("style_ref_model", DEF_MODEL) not in ipa:
                probs.append("IP-Adapter file not in ComfyUI: %s" % d.get("style_ref_model", DEF_MODEL))
            if d.get("style_ref_clip", DEF_CLIP) not in cv:
                probs.append("CLIP vision file not in ComfyUI: %s" % d.get("style_ref_clip", DEF_CLIP))
            wts = c._get("/object_info/IPAdapterAdvanced")["IPAdapterAdvanced"]["input"]["required"]["weight_type"][0]
            if DEF_TYPE not in wts:
                probs.append("IPAdapterAdvanced has no weight_type '%s' (update ComfyUI_IPAdapter_plus)" % DEF_TYPE)
    except SystemExit:
        raise
    except Exception as e:
        probs.append("could not check IP-Adapter nodes (%s)" % e)
    return probs


# ------------------------------------------------------------------ 시험: nk ep styleref
def _variants(txt):
    """'0,st0.6,st1.0' -> [(label, type or None, weight)]. st=style transfer, sst=strong style transfer,
    stp=style transfer precise, lin=linear(내용까지 베낌 - 비교용)"""
    kinds = {"st": "style transfer", "sst": "strong style transfer", "stp": "style transfer precise", "lin": "linear"}
    out = []
    for part in (txt or "0,st0.6,st1.0,st1.5").split(","):
        p = part.strip().lower()
        if not p:
            continue
        if p in ("0", "none", "off"):
            out.append(("none", None, 0.0)); continue
        for pre in sorted(kinds, key=len, reverse=True):
            if p.startswith(pre):
                try:
                    out.append((p, kinds[pre], float(p[len(pre):])))
                except ValueError:
                    print("[ERROR] bad variant '%s' (e.g. 0, st1.0, sst0.5, stp1.0, lin0.3)" % part); sys.exit(1)
                break
        else:
            print("[ERROR] bad variant '%s' (e.g. 0, st1.0, sst0.5, stp1.0, lin0.3)" % part); sys.exit(1)
    return out


def _specs(txt):
    out = []
    for part in (txt or "").split(","):
        part = part.strip()
        if not part:
            continue
        c, _, k = part.partition(":")
        out.append((int(c), int(k or 1)))
    return out


def _sheet(out_dir, rows, name, ref):
    from PIL import Image, ImageDraw
    H = 420
    body = []
    for label, tiles in rows:
        ims = []
        for lb, p in tiles:
            if p and os.path.exists(p):
                im = Image.open(p).convert("RGB")
                ims.append((lb, im.resize((int(im.width * H / im.height), H))))
        if ims:
            body.append((label, ims))
    if not body:
        return None
    r = Image.open(ref).convert("RGB")
    r = r.resize((int(r.width * H / r.height), H))
    Wd = max(r.width + 8 + sum(t.width + 8 for _, t in ims) for _, ims in body)
    sheet = Image.new("RGB", (Wd, len(body) * (H + 24)), "white")
    dr = ImageDraw.Draw(sheet)
    y = 0
    for label, ims in body:
        sheet.paste(r, (0, y + 24)); dr.text((4, y + 6), "REF (style reference)", fill="black")
        x = r.width + 8
        for lb, t in ims:
            sheet.paste(t, (x, y + 24)); dr.text((x + 4, y + 6), "%s | %s" % (label, lb), fill="black"); x += t.width + 8
        y += H + 24
    p = os.path.join(out_dir, "sheet_%s.png" % name)
    sheet.save(p)
    print("sheet:", p)
    return p


def run_test(nk, kit, args):
    import nk_webtoon as W
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    char = conti["_default_char"]
    byid = {int(x["id"]): x for x in conti["cuts"]}
    ref = resolve_path(kit, args.ref)
    if not ref or not os.path.exists(ref):
        print("[ERROR] --ref not found: %s" % args.ref); sys.exit(1)
    variants = _variants(args.variants)
    specs = _specs(args.cuts)
    if not specs:
        print("[ERROR] --cuts needed, e.g. 2:1,2:2 (cut:candidate)"); sys.exit(1)
    name = args.name or "%s_%s" % (args.ep, os.path.splitext(os.path.basename(ref))[0][:20])
    run = "styleref/%s" % name
    if not args.dry:
        probs = preflight(nk, cfg)
        if probs:
            for p in probs:
                print("[ERROR]", p)
            sys.exit(1)
        print("preflight OK: IP-Adapter nodes and files present")
    jobs, rows_src = [], []
    for cid, k in specs:
        m, src = W._picked_meta(cfg, kit, args.ep, cid, k)
        if not m:
            print("[skip] cut %d candidate %d: no meta" % (cid, k)); continue
        if m.get("duo"):
            print("[skip] cut %d: two-character candidates are not supported in this test" % cid); continue
        ct = byid.get(cid)
        cchar = W._cut_char(char, ct) if ct is not None else char
        tiles = [("original (as drawn)", src)]
        for lb, wt, w in variants:
            s = dict(m["settings"])
            s["loras"] = [tuple(x) for x in m.get("loras", [])]
            s["hires"] = 0
            if wt:
                s.update(style_ref=ref, style_ref_weight=w, style_ref_type=wt)
            else:
                s["style_ref"] = ""
            label = "c%02d_k%d_%s" % (cid, k, lb.replace(".", "p"))
            g = nk.build_graph(cfg, s, cchar, m["positive"], m["negative"], m["seed"], 1, "nk/%s/%s" % (run.replace("/", "_"), label))
            if m.get("anima"):
                W._anima_init(g, s, m["anima"]["text"], m["seed"], m["anima"]["a1"])
            jobs.append({"label": label, "graph": g, "positive": m["positive"], "negative": m["negative"],
                         "settings": s, "seed": m["seed"]})
            tiles.append((lb, label + ".png"))
        rows_src.append(("cut %d cand %d" % (cid, k), tiles))
    print("styleref test: %d candidates x %d settings = %d pictures (~30-45 s each, no hires)"
          % (len(rows_src), len(variants), len(jobs)))
    res = nk.run_jobs(cfg, jobs, run, args.dry)
    if args.dry:
        return
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), run)
    rows = [(lb, [(t, p if os.path.isabs(p) else os.path.join(out_dir, p)) for t, p in tiles]) for lb, tiles in rows_src]
    sq = os.path.join(out_dir, "_ref_square.png")
    square_png(ref, sq)
    _sheet(out_dir, rows, "all", sq)
    json.dump({"ref": ref, "variants": [v[0] for v in variants], "cuts": args.cuts}, open(os.path.join(out_dir, "test.json"), "w"),
              indent=1)
    print("look: %s\\sheet_all.png" % out_dir)


def add_parser(esub, nk, kit):
    a = esub.add_parser("styleref", help="TEST: redraw candidates with a style reference picture (IP-Adapter style transfer)")
    a.add_argument("ep")
    a.add_argument("--cuts", required=True, help="cut:candidate list, e.g. 2:1,2:2,5:1")
    a.add_argument("--ref", required=True, help="reference picture (path from the kit folder or absolute)")
    a.add_argument("--variants", help='default "0,st0.6,st1.0,st1.5" (st=style transfer, sst=strong, stp=precise, lin=linear)')
    a.add_argument("--name", help="output folder name under runs/styleref/")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run_test(nk, kit, x))
