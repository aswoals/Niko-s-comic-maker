# -*- coding: utf-8 -*-
"""ComfyUI 워크플로 슬롯 + 설치 노드 확인

nk는 콘티·검수·재시도·글자(감독)를 맡는다. 워크플로는 '빈칸 규칙'만 지키면 됨.

빈칸 규칙 (ComfyUI에서 노드 제목을 'NK <이름>' 으로 바꿈. 대소문자 상관없음):
  NK prompt     긍정 프롬프트 칸 (CLIPTextEncode 등 글 칸)   ← 꼭 있어야 함
  NK negative   부정 프롬프트 칸
  NK seed       시드 칸 (KSampler seed / RandomNoise noise_seed)
  NK size       그림 크기 (EmptyLatentImage 등 width+height)   (또는 NK width / NK height 따로)
  NK steps / NK cfg
  NK lora       LoraLoader - 컷의 캐릭터 LoRA 파일·세기로 바꿈 (LoRA 없는 캐릭터 컷이면 세기 0 = 안 걸림)
  NK output     결과 그림 노드 (SaveImage/PreviewImage) - 없으면 모든 저장 노드
  입력 이름을 직접 정하려면 'NK prompt:text_g' 처럼 ':입력이름'
프롬프트 칸의 글에 아래 자리표시가 있으면 그 자리만 바꾸고 나머지 글은 그대로
  %prompt% (nk가 만든 전체 긍정) %negative% %char% (캐릭터 태그) %scene% (장면+장소+카메라) %quality% %artist%
  자리표시가 없으면 칸 전체를 nk 프롬프트로 바꿈.
      <이름>_final.json 이 있으면 최종본(크게 그리기)에 씀. 없으면 최종본도 같은 파일·같은 시드.
쓰는 법: 콘티 맨 위 또는 컷에 flow: <이름>  (혼자 컷만. 두 명 컷 슬롯은 리저널 시험 뒤)
nk가 사용자 워크플로에는 아무 노드도 끼우지 않음 (CFG 0.2 자동 삽입 X) - 칸 값만 바꿈.

명령:
  nk ep nodes                          설치 노드 목록 -> runs/_nodes/nodes.txt (읽기만)
  nk ep flow export                    지금 nk 혼자 컷 그리기를 워크플로 파일로 -> workflows/solo_default.json (+_final)
  nk ep flow check <이름|파일>          빈칸 규칙·설치 노드·모델 파일 검사
  nk ep flow try <이름> --ep <ep> --cut <컷> [--seeds 1,2] [--vs]   컷 하나를 그 워크플로로 (--vs: 기본 nk 그리기와 같은 시드 비교)
  nk ep flow set <이름|none> --ep <ep>  그 화의 혼자 컷 워크플로 정하기 (plan.yaml·conti.yaml 맨 위 flow:)"""
import os, sys, json, time, copy, re

# ------------------------------------------------------------------ 설치 노드 목록
REGIONAL = [
    ("ConditioningSetMask", "기본 내장 - 영역 조건(잠재 단계에서 섞기, 지금 N·C·MB·P 방식이 씀)"),
    ("ConditioningSetArea", "기본 내장 - 직사각형 영역 조건"),
    ("ConditioningSetTimestepRange", "기본 내장 - 단계 범위 (아카 161686015: 처음 0~0.2 전체, 0.2~1 영역)"),
    ("CreateHookLora", "기본 내장 - 훅 LoRA (영역별 LoRA, 우리 B 방식: dtype 에러 + 8배 느림)"),
    ("PairConditioningSetProperties", "기본 내장 - 훅/마스크 조건 묶음"),
    ("AttentionCouple", "어텐션 커플 (어느 패키지인지 python_module 참고)"),
    ("AttentionCouplePPM", "어텐션 커플 (pamparamm ComfyUI-ppm)"),
    ("Attention couple", "어텐션 커플 (cgem156 계열)"),
    ("PCLazyTextEncode", "comfyui-prompt-control (COUPLE 문법 = 어텐션 커플)"),
    ("PCTextEncode", "comfyui-prompt-control"),
    ("PCAttentionCoupleBatchNegative", "comfyui-prompt-control 어텐션 커플 보조"),
    ("DenseDiffusionApplyNode", "DenseDiffusion (huchenlei)"),
    ("DenseDiffusionAddCondNode", "DenseDiffusion (huchenlei)"),
    ("ETN_AttentionMask", "Acly comfyui-tooling-nodes (Krita AI Diffusion 영역 기능)"),
    ("ETN_DefineRegion", "Acly comfyui-tooling-nodes"),
    ("RegionalSampler", "Impact Pack - 영역마다 따로 샘플링(영역별 모델·LoRA 가능, 느림)"),
    ("RegionalSamplerAdvanced", "Impact Pack"),
    ("RegionalPrompt", "Impact Pack"),
    ("CombineRegionalPrompts", "Impact Pack"),
    ("RegionalPromptSimple //Inspire", "Inspire Pack"),
    ("RegionalConditioningSimple //Inspire", "Inspire Pack"),
    ("RegionalPromptColorMask //Inspire", "Inspire Pack"),
    ("Comfy Couple", "Danand ComfyCouple"),
    ("MultiAreaConditioning", "Davemane42"),
    ("IPAdapterAdvanced", "IP-Adapter Plus"),
    ("ControlNetApplyAdvanced", "기본 내장 - ControlNet"),
]


def _module_name(m):
    m = str(m or "")
    if m.startswith("custom_nodes."):
        return m[len("custom_nodes."):].split(".")[0]
    if m in ("nodes",) or m.startswith("comfy_extras") or m.startswith("comfy_api") or m.startswith("comfy."):
        return "(ComfyUI 기본 내장)"
    return m or "(알 수 없음)"


def cmd_nodes(nk, kit, args):
    cfg = nk.load_presets()
    c = nk.Comfy(cfg.get("server", "auto"))
    info = c._get("/object_info")
    groups = {}
    for name, d in info.items():
        groups.setdefault(_module_name((d or {}).get("python_module")), []).append(name)
    out_dir = os.path.join(nk.data_root(kit), "runs", "_nodes")
    os.makedirs(out_dir, exist_ok=True)
    lines = ["ComfyUI %s  노드 %d개  (%s)" % (c.base, len(info), time.strftime("%Y-%m-%d %H:%M:%S")), ""]
    lines.append("== 리저널(영역) 프롬프트 후보 ==")
    for n, what in REGIONAL:
        d = info.get(n)
        lines.append("  [%s] %-38s %s%s" % ("있음" if d else " -- ", n, what,
                                          ("  <- " + _module_name(d.get("python_module"))) if d else ""))
    extra = sorted(n for n in info if any(k in n.lower() for k in ("region", "couple", "hook", "attention"))
                   and n not in dict(REGIONAL))
    if extra:
        lines.append("  (그 밖에 이름에 region/couple/hook/attention 이 있는 노드)")
        for n in extra:
            lines.append("      %-40s <- %s" % (n, _module_name(info[n].get("python_module"))))
    lines += ["", "== 설치 묶음별 노드 수 =="]
    for g in sorted(groups, key=lambda k: (k != "(ComfyUI 기본 내장)", k.lower())):
        lines.append("  %-45s %4d" % (g, len(groups[g])))
    lines += ["", "== 묶음별 노드 이름 =="]
    for g in sorted(groups, key=lambda k: (k != "(ComfyUI 기본 내장)", k.lower())):
        if g == "(ComfyUI 기본 내장)":
            continue
        lines.append("[%s]" % g)
        lines.append("   " + ", ".join(sorted(groups[g])))
    txt = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "nodes.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    with open(os.path.join(out_dir, "object_info_names.json"), "w", encoding="utf-8") as f:
        json.dump({g: sorted(v) for g, v in groups.items()}, f, ensure_ascii=False, indent=1)
    print("\n".join(lines[:len(REGIONAL) + 12]))
    print("\nsaved:", os.path.join(out_dir, "nodes.txt"))


# ------------------------------------------------------------------ 워크플로 슬롯
TEXT_INPUTS = ("text", "prompt", "positive", "string", "value", "text_g", "text_l")
SEED_INPUTS = ("seed", "noise_seed")
SAVE_TYPES = ("SaveImage", "PreviewImage", "SaveImageWebsocket")
KEYS = ("prompt", "negative", "seed", "size", "width", "height", "steps", "cfg", "lora", "output")
PLACEHOLDERS = ("%prompt%", "%negative%", "%char%", "%scene%", "%quality%", "%artist%")


class FlowError(Exception):
    pass


def flow_dir(nk, kit=None):
    return os.path.join(nk.data_root(kit), "workflows")


def flow_path(nk, name, kit=None, final=False):
    """이름 -> 파일. 이름이 경로면 그대로. final=True면 <이름>_final.json 이 있을 때 그것"""
    if not name:
        return None
    if name.lower().endswith(".json") or os.sep in name or "/" in name:
        p = name if os.path.isabs(name) else os.path.join(nk.data_root(kit), name)
    else:
        p = os.path.join(flow_dir(nk, kit), name + ".json")
    if final:
        f2 = p[:-5] + "_final.json"
        if os.path.exists(f2):
            return f2
    return p


def load_flow(path):
    if not path or not os.path.exists(path):
        raise FlowError("워크플로 파일이 없음: %s" % path)
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        raise FlowError("JSON을 못 읽음 (%s): %s" % (path, e))
    if isinstance(d, dict) and "nodes" in d and "links" in d:
        raise FlowError("이건 '보통 저장' 형식입니다. ComfyUI 메뉴 File -> Export Workflow (API) 로 저장한 파일이 필요해요: %s" % path)
    if isinstance(d, dict) and "prompt" in d and isinstance(d["prompt"], dict) and "class_type" not in d:
        d = d["prompt"]                                    # /prompt 요청 모양 {"prompt": {...}} 도 받아 줌
    if not isinstance(d, dict) or not d or not all(isinstance(v, dict) and "class_type" in v for v in d.values()):
        raise FlowError("API 형식 워크플로가 아님 (노드마다 class_type 이 있어야 함): %s" % path)
    return d


def _title(node):
    return str((node.get("_meta") or {}).get("title") or "").strip()


def find_slots(graph):
    """{'prompt': [(노드id, 입력이름)], ...}  'NK prompt' / 'NK prompt:text_g' / 'nk:prompt' 모두 받음"""
    slots = {}
    for nid, n in graph.items():
        t = _title(n)
        m = re.match(r"^\s*nk\s*[: ]\s*([a-z_]+)\s*(?::\s*([A-Za-z0-9_]+))?\s*$", t, re.I)
        if not m:
            continue
        key, inp = m.group(1).lower(), m.group(2)
        if key not in KEYS:
            continue
        slots.setdefault(key, []).append((str(nid), inp))
    return slots


def _text_input(node, inp=None):
    ins = node.get("inputs", {})
    if inp:
        return inp
    for k in TEXT_INPUTS:
        if k in ins and isinstance(ins[k], str):
            return k
    for k, v in ins.items():
        if isinstance(v, str) and not k.endswith("_name"):
            return k
    return None


def check(nk, kit, name, info=None, quiet=False):
    """-> (문제 목록, 경고 목록, 칸 요약)"""
    path = flow_path(nk, name, kit)
    probs, warns = [], []
    try:
        g = load_flow(path)
    except FlowError as e:
        return [str(e)], [], {}
    slots = find_slots(g)
    if "prompt" not in slots:
        probs.append("'NK prompt' 제목을 가진 노드가 없음 (긍정 프롬프트 노드 제목을 NK prompt 로)")
    for key, lst in slots.items():
        for nid, inp in lst:
            node = g[nid]
            ins = node.get("inputs", {})
            if key in ("prompt", "negative"):
                k = _text_input(node, inp)
                if not k or (k in ins and isinstance(ins[k], list)):
                    probs.append("NK %s (노드 %s %s): 글을 넣을 칸을 못 찾음 (':입력이름' 으로 정해 주세요)"
                                 % (key, nid, node["class_type"]))
            elif key == "seed":
                if not (inp or any(k in ins for k in SEED_INPUTS)):
                    probs.append("NK seed (노드 %s %s): seed / noise_seed 칸이 없음" % (nid, node["class_type"]))
            elif key == "size":
                if not ("width" in ins and "height" in ins):
                    probs.append("NK size (노드 %s %s): width/height 칸이 없음" % (nid, node["class_type"]))
            elif key == "lora":
                if "lora_name" not in ins:
                    probs.append("NK lora (노드 %s %s): lora_name 칸이 없음 (LoraLoader 계열)" % (nid, node["class_type"]))
            elif key == "output":
                if node["class_type"] not in SAVE_TYPES:
                    warns.append("NK output (노드 %s %s): 저장 노드가 아님 - 그림을 못 받을 수 있음" % (nid, node["class_type"]))
    if "seed" not in slots:
        warns.append("NK seed 없음 -> 후보마다 같은 그림이 나올 수 있음 (워크플로 안 시드가 고정이면)")
    if "size" not in slots and "width" not in slots:
        warns.append("NK size 없음 -> 콘티 크기(와이드·세로) 대신 워크플로 크기로 그림")
    if not any(n["class_type"] in SAVE_TYPES for n in g.values()):
        probs.append("저장 노드(SaveImage/PreviewImage)가 없음")
    placeholders = [p for nid, _ in slots.get("prompt", []) for p in PLACEHOLDERS
                    if p in str(g[nid]["inputs"].get(_text_input(g[nid], None) or "", ""))]
    if info is not None:
        missing = sorted({n["class_type"] for n in g.values() if n["class_type"] not in info})
        if missing:
            probs.append("ComfyUI에 없는 노드: %s (설치 필요)" % ", ".join(missing))
        for nid, n in g.items():                    # 모델 파일 이름이 목록에 있나 (ckpt_name, lora_name, unet_name ...)
            spec = ((info.get(n["class_type"]) or {}).get("input") or {})
            allin = dict(spec.get("required") or {}, **(spec.get("optional") or {}))
            for k, v in n.get("inputs", {}).items():
                if not isinstance(v, str) or k not in allin:
                    continue
                sp = allin[k] if isinstance(allin[k], list) else []
                choices = sp[0] if sp and isinstance(sp[0], list) else \
                    ((sp[1] or {}).get("options") if len(sp) > 1 and sp[0] == "COMBO" and isinstance(sp[1], dict) else None)
                if choices and v not in choices and not (k == "lora_name" and any(x[0] == nid for x in slots.get("lora", []))):
                    probs.append("노드 %s %s: %s = '%s' 이(가) ComfyUI 목록에 없음" % (nid, n["class_type"], k, v))
    summary = {k: ["%s(%s)" % (nid, g[nid]["class_type"]) for nid, _ in v] for k, v in slots.items()}
    summary["_placeholders"] = placeholders
    summary["_path"] = path
    return probs, warns, summary


def prompt_parts(nk, s, char, scene):
    """nk 프롬프트를 조각으로 (자리표시용)"""
    pos, neg = nk.compose_prompt(s, char, scene)
    cb = ""
    if char:
        tf = "tags_full" if str(s.get("tags", "short")) == "full" else "tags_short"
        cb = nk.clean_tags(char["trigger"] + (", " + char[tf] if char.get(tf) else ""))
    sc = nk.clean_tags(", ".join(x for x in [scene or "", s.get("extra") or ""] if x))
    q = nk.clean_tags(s.get("quality_tags", "")) if s.get("quality") == "on" else ""
    art = ""
    if s.get("artist"):                     # nk.compose_prompt 와 같은 모양 (가중치 1이 아니면 괄호)
        w = float(s.get("artist_weight", 1.0))
        art = "by %s" % s["artist"] if abs(w - 1.0) < 1e-6 else "(by %s:%.2f)" % (s["artist"], w)
    return {"%prompt%": pos, "%negative%": neg, "%char%": cb, "%scene%": sc, "%quality%": q, "%artist%": art}


def _fill_text(old, full, parts):
    if isinstance(old, str) and any(p in old for p in PLACEHOLDERS):
        out = old
        for k, v in parts.items():
            out = out.replace(k, v)
        return ", ".join(t.strip() for t in out.replace("\n", " ").split(",") if t.strip())   # = nk.clean_tags
    return full


def render(graph, parts, seed=None, width=None, height=None, steps=None, cfg=None, lora=None, prefix=None):
    """칸 채우기 (원본은 안 바꿈). lora = (파일, 세기) 또는 None(= 세기 0)"""
    g = copy.deepcopy(graph)
    slots = find_slots(g)
    for nid, inp in slots.get("prompt", []):
        k = _text_input(g[nid], inp)
        g[nid]["inputs"][k] = _fill_text(g[nid]["inputs"].get(k), parts["%prompt%"], parts)
    for nid, inp in slots.get("negative", []):
        k = _text_input(g[nid], inp)
        g[nid]["inputs"][k] = _fill_text(g[nid]["inputs"].get(k), parts["%negative%"], parts)
    if seed is not None:
        for nid, inp in slots.get("seed", []):
            ins = g[nid]["inputs"]
            for k in ([inp] if inp else [k for k in SEED_INPUTS if k in ins]):
                ins[k] = int(seed)
    for key, val in (("width", width), ("height", height)):
        if val:
            for nid, inp in slots.get("size", []) + slots.get(key, []):
                ins = g[nid]["inputs"]
                if key in ins or inp:
                    ins[inp or key] = int(val)
    for key, val, cast in (("steps", steps, int), ("cfg", cfg, float)):
        if val is not None:
            for nid, inp in slots.get(key, []):
                g[nid]["inputs"][inp or key] = cast(val)
    for nid, inp in slots.get("lora", []):
        ins = g[nid]["inputs"]
        if lora:
            ins["lora_name"] = lora[0]
            for k in ("strength_model", "strength_clip", "strength"):
                if k in ins:
                    ins[k] = float(lora[1])
        else:                                       # LoRA 없는 캐릭터 컷: 세기 0 (ComfyUI LoraLoader는 0이면 그냥 통과)
            for k in ("strength_model", "strength_clip", "strength"):
                if k in ins:
                    ins[k] = 0.0
    outs = [nid for nid, _ in slots.get("output", [])] or [nid for nid, n in g.items() if n["class_type"] in SAVE_TYPES]
    for nid, n in list(g.items()):                  # 결과로 안 쓰는 저장 노드는 미리보기로 (output 폴더에 쌓이지 않게)
        if n["class_type"] == "SaveImage" and nid not in outs:
            n["class_type"] = "PreviewImage"
            n["inputs"] = {"images": n["inputs"]["images"]}
    if prefix:
        for nid in outs:
            if g[nid]["class_type"] == "SaveImage":
                g[nid]["inputs"]["filename_prefix"] = prefix
    return g


def cut_flow(conti, cut):
    """이 컷에 쓸 워크플로 이름 (컷 > 콘티 맨 위). 두 명 컷은 아직 None"""
    if cut is not None and cut.get("_roles"):
        return None
    v = (cut or {}).get("flow") if cut is not None and "flow" in cut else (conti or {}).get("flow")
    return str(v) if v and str(v).lower() not in ("none", "default", "nk") else None


def solo_graph(nk, kit, name, s, char, scene, seed, prefix, final=False):
    """혼자 컷 그리기 그래프 (사용자 워크플로). s = nk 설정(크기·스텝 등), char = 캐릭터(LoRA)"""
    path = flow_path(nk, name, kit, final=final)
    g = load_flow(path)
    parts = prompt_parts(nk, s, char, scene)
    lora = None
    if char and char.get("lora"):
        lora = (s.get("charlora") or char["lora"],
                float(s["strength"]) if s.get("strength") is not None else float(char.get("lora_strength", 1.0)))
    W, H = int(s["width"]), int(s["height"])
    return render(g, parts, seed=seed, width=W, height=H, lora=lora, prefix=prefix), parts


def set_top_key(path, key, value):
    """YAML 파일 맨 위 단계의 'key: 값' 한 줄을 바꾸거나 넣음 (value None = 지움). 다른 줄·주석은 그대로"""
    lines = open(path, encoding="utf-8").read().splitlines()
    pat = re.compile(r"^%s\s*:" % re.escape(key))
    out = [ln for ln in lines if not pat.match(ln)]
    if value is not None:
        idx = next((i + 1 for i, ln in enumerate(out) if re.match(r"^title\s*:\s*[^|>\s]", ln)), None)
        if idx is None:
            idx = next((i for i, ln in enumerate(out) if ln.strip() and not ln.lstrip().startswith("#")), len(out))
        out.insert(idx, "%s: %s" % (key, json.dumps(str(value), ensure_ascii=False)))
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def cmd_set(nk, kit, args):
    """nk ep flow set <이름|none> --ep <ep> : 콘티·계획표 맨 위 flow: 를 바꿈 (그림은 안 다시 그림)"""
    import nk_webtoon as W
    if not args.ep or not args.name:
        print("[ERROR] nk ep flow set <이름|none> --ep <ep>"); sys.exit(1)
    name = None if args.name.lower() in ("none", "default", "nk", "off") else args.name
    if name:
        probs, warns, _ = check(nk, kit, name, None)
        for w in warns:
            print("[경고]", w)
        if probs:
            for p in probs:
                print("[문제]", p)
            sys.exit(2)
    d = W.ep_dir(kit, args.ep)
    done = []
    for f in ("plan.yaml", "conti.yaml"):
        p = os.path.join(d, f)
        if os.path.exists(p):
            set_top_key(p, "flow", name)
            done.append(f)
    if not done:
        print("[ERROR] %s 에 plan.yaml / conti.yaml 이 없음" % d); sys.exit(1)
    print("%s: flow = %s  (%s)" % (args.ep, name or "기본 nk 그리기", ", ".join(done)))
    print("다시 그리려면: 작업실 '이어서 만들기' 를 make 부터, 또는 nk ep auto %s --from make" % args.ep)


# ------------------------------------------------------------------ 명령
def _titled_default(nk, kit, final):
    """지금 nk 혼자 컷 그리기(build_graph)를 NK 제목을 붙여 워크플로로"""
    cfg = nk.load_presets()
    import argparse
    ns = argparse.Namespace(preset=None, extra=None, neg=None, lora=None, size=None, rating=None, cfg=None, steps=None,
                            sampler=None, scheduler=None, quality=None, year=None, artist=None, artist_weight=None,
                            artist_position=None, tags=None, strength=None, charlora=None,
                            hires=(float((cfg.get("defaults") or {}).get("final_hires", 1.5)) if final else 0),
                            hires_denoise=None, hires_steps=None, hires_method=None, upscale_model=None)
    s = nk.build_settings(cfg, ns)
    import glob
    cdir = os.environ.get("NK_CHARS") or os.path.join(kit, "characters")
    lora = [os.path.splitext(os.path.basename(f))[0] for f in sorted(glob.glob(os.path.join(cdir, "*.yaml")))
            if not os.path.basename(f).startswith("_") and (nk.load_yaml(f) or {}).get("lora")]
    char = nk.load_char(lora[0]) if lora else None        # LoRA 캐릭터가 있으면 그 LoRA 노드까지 파일에 넣음
    pos = "%quality%, %artist%, safe, %char%, %scene%"
    g = nk.build_graph(cfg, s, char, pos, "%negative%", 1, 1, "nk/flow_default")
    nk.apply_cfg_rescale(g)                         # 지금 nk 그리기와 똑같이 (CFG 0.2 노드를 파일 안에 넣어 둠)
    titles = {"6": "NK prompt", "7": "NK negative", "3": "NK seed", "11": "NK seed", "5": "NK size", "9": "NK output",
              "20": "NK lora"}                      # 11 = 최종본 크게 다시 그리기 KSampler (초안과 같은 시드)
    for nid, n in g.items():
        n["_meta"] = {"title": titles.get(nid, n["class_type"])}
    return g


def cmd_flow(nk, kit, args):
    act = args.action
    if act == "export":
        d = flow_dir(nk, kit)
        os.makedirs(d, exist_ok=True)
        for final in (False, True):
            p = os.path.join(d, "solo_default%s.json" % ("_final" if final else ""))
            if os.path.exists(p) and not args.overwrite:
                print("[keep] %s 이미 있음 (다시 만들려면 --overwrite)" % p); continue
            json.dump(_titled_default(nk, kit, final), open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("saved:", p)
        print("ComfyUI 화면에 이 파일을 끌어다 놓으면 열림 -> 고친 뒤 File -> Export Workflow (API) 로 새 이름 저장"
              "\n(노드 제목 NK ... 은 그대로 두기)")
        return
    if act == "check":
        if not args.name:
            print("[ERROR] nk ep flow check <이름|파일>"); sys.exit(1)
        info = None
        if not args.offline:
            try:
                cfg = nk.load_presets()
                info = nk.Comfy(cfg.get("server", "auto"))._get("/object_info")
            except SystemExit:
                print("(ComfyUI가 꺼져 있어 노드·모델 검사는 건너뜀)")
        probs, warns, summ = check(nk, kit, args.name, info)
        print("파일:", summ.get("_path", flow_path(nk, args.name, kit)))
        for k in KEYS:
            if summ.get(k):
                print("  NK %-9s -> %s" % (k, ", ".join(summ[k])))
        if summ.get("_placeholders"):
            print("  자리표시:", " ".join(summ["_placeholders"]))
        for w in warns:
            print("[경고]", w)
        for p in probs:
            print("[문제]", p)
        fin = flow_path(nk, args.name, kit, final=True)
        print("최종본용:", fin if fin != summ.get("_path") else "(따로 없음 -> 같은 파일·같은 시드)")
        print("결과: %s" % ("통과" if not probs else "고칠 것 %d개" % len(probs)))
        if probs:
            sys.exit(2)
        return
    if act == "try":
        return _try(nk, kit, args)
    if act == "set":
        return cmd_set(nk, kit, args)
    print("[ERROR] 모르는 명령: %s (export / check / try / set)" % act); sys.exit(1)


def _try(nk, kit, args):
    """컷 하나를 워크플로로 그려 보기 (+ --vs: 같은 시드로 기본 nk 그리기) -> runs/flowtry/<이름>/"""
    import nk_webtoon as W
    import nk_regional as R
    if not (args.name and args.ep and args.cut):
        print("[ERROR] nk ep flow try <이름> --ep <ep> --cut <컷>"); sys.exit(1)
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    cut = next((c for c in conti["cuts"] if int(c["id"]) == int(args.cut)), None)
    if cut is None or cut.get("_roles"):
        print("[ERROR] 컷 %s 이 없거나 두 명 컷 (지금은 혼자 컷만)" % args.cut); sys.exit(1)
    probs, warns, _ = check(nk, kit, args.name, None)
    if probs:
        for p in probs:
            print("[문제]", p)
        sys.exit(2)
    s = R._settings(nk, W, cfg, conti, cut)
    char = W._cut_char(conti.get("_default_char"), cut)
    scene = nk.resolve_scene(cfg, cut["scene"])
    seeds = [int(x) for x in (args.seeds or "1,2").split(",") if x.strip()]
    run = "flowtry/%s_%s_cut%02d" % (os.path.splitext(os.path.basename(args.name))[0], args.ep, int(args.cut))
    jobs = []
    for sd in seeds:
        g, parts = solo_graph(nk, kit, args.name, s, char, scene, sd, "nk/%s/flow_s%d" % (run.replace("/", "_"), sd))
        jobs.append({"label": "flow_s%d" % sd, "graph": g, "positive": parts["%prompt%"], "negative": parts["%negative%"],
                     "settings": s, "seed": sd, "raw": True})
        if args.vs:
            pos, neg = nk.compose_prompt(s, char, scene)
            jobs.append({"label": "nk_s%d" % sd, "graph": nk.build_graph(cfg, s, char, pos, neg, sd, 1,
                                                                         "nk/%s/nk_s%d" % (run.replace("/", "_"), sd)),
                         "positive": pos, "negative": neg, "settings": s, "seed": sd})
    res = nk.run_jobs(cfg, jobs, run, args.dry) or []
    if res:
        out = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), run)
        rows = [(r["label"], os.path.join(out, r["file"]), "") for r in res]
        R._sheet(rows, os.path.join(out, "sheet.png"))
        print("look:", os.path.join(out, "sheet.png"))


def add_parser(esub, nk, kit):
    a = esub.add_parser("nodes", help="list the nodes installed in ComfyUI (read only) -> runs/_nodes/nodes.txt")
    a.set_defaults(func=lambda args: cmd_nodes(nk, kit, args))
    a = esub.add_parser("flow", help="your own ComfyUI workflow as a drawing slot: export / check <name> / try <name> --ep --cut")
    a.add_argument("action", choices=["export", "check", "try", "set"])
    a.add_argument("name", nargs="?", help="workflow name in workflows/ (without .json) or a file path")
    a.add_argument("--ep"); a.add_argument("--cut")
    a.add_argument("--seeds", help="try: seeds, default 1,2")
    a.add_argument("--vs", action="store_true", help="try: also draw the same seeds with the built-in nk graph")
    a.add_argument("--overwrite", action="store_true", help="export: replace existing files")
    a.add_argument("--offline", action="store_true", help="check: do not ask ComfyUI")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda args: cmd_flow(nk, kit, args))
