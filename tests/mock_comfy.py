# -*- coding: utf-8 -*-
"""가짜 ComfyUI 서버

nk 가 ComfyUI 에 보내는 HTTP 요청을 흉내낸다. GPU·모델 없이 '그림 모양만 맞는' PNG 를 돌려준다.
  GET  /system_stats           살아 있나 확인 (nk.Comfy 가 맨 처음 부름)
  GET  /object_info[/<노드>]   노드 목록·모델 파일 목록 (preflight 가 봄) — env_snapshot.md 의 노드 + 모델 이름
  POST /upload/image           그림 올리기 (multipart) -> 크기를 기억해 두고 LoadImage 에서 씀
  POST /prompt                 그래프 받기 -> 바로 '그림' 을 만들어 둠 (출력 크기는 그래프를 거꾸로 따라가서 계산)
  GET  /history/<id>           결과 목록
  GET  /view?filename=..       그림 파일
  GET  /queue, POST /free, POST /interrupt

그림 내용 (진짜 그림이 아님):
  - 보통 그림: 시드마다 다른 배경색 + 가운데(두 명이면 양쪽)에 검은 몸통·머리 모양 -> 얼굴·손 검사 코드가 '뭔가' 를 찾게
  - SAM3_Detect 가 들어간 그래프: 흰 타원 마스크 (프롬프트에 head/face 가 있으면 위쪽, hand 면 작은 원)
  - LoadImage 에서 온 그림(편집·다시 칠하기): 올린 그림을 크기만 맞추고 살짝 색을 바꿈 (전/후가 달라야 md5 비교가 동작)

실행(따로 띄울 때):  python tests/mock_comfy.py --port 18188 [--data <폴더>] [--fail-class KSampler]
  --fail-class: 그 노드가 들어간 작업은 status error 로 답함 (실패 경로 시험용)"""
import os, sys, io, json, uuid, time, random, argparse, threading, hashlib, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from PIL import Image, ImageDraw

# ------------------------------------------------------------------ /object_info
MODELS = {
    "ckpt_name": ["noobaiXLNAIXL_vPred10Version.safetensors", "sam3.1_multiplex_fp16.safetensors"],
    "control_net_name": ["noob_lineart_anime_fp16.safetensors", "openpose_pre.safetensors"],
    "ipadapter_file": ["ip_adapter_Noobtest_800000.bin"],
    "clip_name": ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors", "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                  "qwen_3_06b_base.safetensors"],
    "unet_name": ["anima-turbo-v1.1.safetensors", "qwen_image_edit_2509_fp8_e4m3fn.safetensors",
                  "qwen_image_edit_2511_fp8mixed.safetensors"],
    "vae_name": ["qwen_image_vae.safetensors", "anima_vae.safetensors"],
    "lora_name": ["testcat_v1.safetensors", "testcat_v1_noOUT1.safetensors", "testcat_v1.safetensors",
                  "testcat_v1.safetensors", "Qwen-Edit-2509-Multiple-angles.safetensors",
                  "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors",
                  "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"],
    "model_name": ["4x-AnimeSharp.pth", "RealESRGAN_x4plus_anime_6B.pth"],
}
# 입력 이름이 중요한 노드만 자세히 (preflight 가 ["input"]["required"][칸][0] 을 읽음)
DETAIL = {
    "CheckpointLoaderSimple": {"ckpt_name": [MODELS["ckpt_name"]]},
    "LoraLoader": {"lora_name": [MODELS["lora_name"]], "strength_model": ["FLOAT"], "strength_clip": ["FLOAT"]},
    "LoraLoaderModelOnly": {"lora_name": [MODELS["lora_name"]], "strength_model": ["FLOAT"]},
    "ControlNetLoader": {"control_net_name": [MODELS["control_net_name"]]},
    "IPAdapterModelLoader": {"ipadapter_file": [MODELS["ipadapter_file"]]},
    "CLIPVisionLoader": {"clip_name": [MODELS["clip_name"][:1]]},
    "CLIPLoader": {"clip_name": [MODELS["clip_name"]], "type": [["stable_diffusion", "qwen_image", "lumina2"]]},
    "UNETLoader": {"unet_name": [MODELS["unet_name"]], "weight_dtype": [["default", "fp8_e4m3fn"]]},
    "VAELoader": {"vae_name": [MODELS["vae_name"]]},
    "UpscaleModelLoader": {"model_name": [MODELS["model_name"]]},
    "IPAdapterAdvanced": {"weight_type": [["linear", "ease in", "ease out", "ease in-out", "reverse in-out", "weak input",
                                           "weak output", "weak middle", "strong middle", "style transfer",
                                           "composition", "strong style transfer", "style and composition",
                                           "style transfer precise" if os.environ.get("MOCK_IPA_PRECISE") else "linear"]]},
}
# env_snapshot 의 설치 노드 + nk 코드가 쓰는 기본 내장 노드 (나머지 기본 내장 959개는 생략)
NODES = sorted(set("""ModelAttentionBackend EasyCache 
CheckpointLoaderSimple CLIPTextEncode KSampler KSamplerAdvanced VAEDecode VAEEncode LoadImage LoadImageMask SaveImage PreviewImage
EmptyLatentImage EmptySD3LatentImage ImageScale ImageScaleBy ImageScaleToTotalPixels ImageCrop ImageBlur ImageCompositeMasked
ImageUpscaleWithModel UpscaleModelLoader LatentUpscaleBy LoraLoader LoraLoaderModelOnly VAELoader UNETLoader CLIPLoader CLIPVisionLoader
SolidMask FeatherMask GrowMask MaskComposite ImageToMask MaskToImage SetLatentNoiseMask InpaintModelConditioning DifferentialDiffusion
ConditioningSetMask ConditioningSetArea ConditioningCombine ConditioningSetTimestepRange ControlNetLoader ControlNetApplyAdvanced
ModelSamplingAuraFlow RescaleCFG CFGNorm TextEncodeQwenImageEditPlus FluxKontextMultiReferenceLatentMethod
CreateHookLora SetClipHooks PairConditioningSetProperties PairConditioningSetPropertiesAndCombine PairConditioningSetDefaultCombine
CombineHooks2 CombineHooks4 CombineHooks8 CreateHookKeyframe CreateHookLoraModelOnly SAM3_Detect
ETN_ApplyMaskToImage ETN_AttentionMask ETN_BackgroundRegion ETN_DefineRegion ETN_ListRegionMasks ETN_LoadImageBase64 ETN_LoadMaskBase64
IPAdapter IPAdapterAdvanced IPAdapterModelLoader IPAdapterUnifiedLoader IPAdapterRegionalConditioning IPAdapterStyleComposition
CLIPLoaderGGUF DualCLIPLoaderGGUF UnetLoaderGGUF SaveImageWebsocket
EmptyImage ModelPatchLoader AnimaLLLiteApply AnimaRefEncode AnimaRefLatentBatch AnimaInContextApply
ToBasicPipe KSamplerAdvancedProvider RegionalPrompt CombineRegionalPrompts RegionalSampler ConditioningSetPropertiesAndCombine ConditioningSetProperties
""".split()))
if os.environ.get("MOCK_NO_ETN"):          # 어텐션 영역 노드가 없는 ComfyUI 흉내 (unify 건너뛰기 경로)
    NODES = [n for n in NODES if not n.startswith("ETN_")]


def object_info(name=None):
    def one(n):
        req = dict(DETAIL.get(n, {}))
        return {"input": {"required": req, "optional": {}}, "output": [], "name": n, "display_name": n,
                "python_module": "comfy_extras.nodes_mock", "category": "mock"}
    if name is None:
        return {n: one(n) for n in NODES}
    return {name: one(name)} if name in NODES else {}


# ------------------------------------------------------------------ 그래프 따라가기
class Graph:
    def __init__(self, g, uploads):
        self.g, self.up, self.memo = g, uploads, {}

    def node(self, nid):
        return self.g.get(str(nid)) or {}

    def link(self, v):
        return isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and str(v[0]) in self.g

    def upstream(self, nid, seen=None):
        """nid 위쪽의 모든 노드 id"""
        seen = set() if seen is None else seen
        for v in (self.node(nid).get("inputs") or {}).values():
            if self.link(v) and str(v[0]) not in seen:
                seen.add(str(v[0]))
                self.upstream(v[0], seen)
        return seen

    def size(self, nid, depth=0):
        """(w, h) 그림/잠재의 픽셀 크기. 모르면 None"""
        nid = str(nid)
        if nid in self.memo:
            return self.memo[nid]
        if depth > 200:
            return None
        n = self.node(nid)
        ct, inp = n.get("class_type", ""), n.get("inputs") or {}

        def up(*names):
            for k in names:
                if self.link(inp.get(k)):
                    s = self.size(inp[k][0], depth + 1)
                    if s:
                        return s
            return None

        s = None
        if ct in ("EmptyLatentImage", "EmptySD3LatentImage", "SolidMask", "ImageScale", "ImageCrop"):
            w, h = int(inp.get("width", 0) or 0), int(inp.get("height", 0) or 0)
            if ct == "ImageScale" and (not w or not h):
                src = up("image") or (1024, 1024)
                w, h = (w, int(src[1] * w / src[0])) if w else (int(src[0] * h / src[1]), h)
            s = (max(8, w or 1024), max(8, h or 1024))
        elif ct in ("LoadImage", "LoadImageMask"):
            s = self.up.get(str(inp.get("image", "")).replace("\\", "/"), (1024, 1024))
        elif ct in ("ImageScaleBy", "LatentUpscaleBy"):
            src = up("image", "samples") or (1024, 1024)
            k = float(inp.get("scale_by", 1.0) or 1.0)
            s = (int(src[0] * k), int(src[1] * k))
        elif ct == "ImageScaleToTotalPixels":
            src = up("image") or (1024, 1024)
            mp = float(inp.get("megapixels", 1.0) or 1.0) * 1024 * 1024
            k = (mp / float(src[0] * src[1])) ** 0.5
            s = (int(src[0] * k), int(src[1] * k))
        elif ct == "ImageUpscaleWithModel":
            src = up("image") or (1024, 1024)
            s = (src[0] * 4, src[1] * 4)
        elif ct == "ImageCompositeMasked":
            s = up("destination", "source")
        elif ct == "InpaintModelConditioning":
            s = up("pixels")
        elif ct == "TextEncodeQwenImageEditPlus":
            s = up("image1", "image")
        else:
            s = up("images", "image", "pixels", "samples", "latent_image", "latent", "mask", "masks", "source",
                   "destination", "image1", "positive")
            if not s:                        # 그 밖: 연결된 아무 입력
                for v in inp.values():
                    if self.link(v):
                        s = self.size(v[0], depth + 1)
                        if s:
                            break
        self.memo[nid] = s
        return s

    def find_up(self, nid, cls):
        return [u for u in self.upstream(nid) if self.node(u).get("class_type") == cls]

    def positive_text(self, nid):
        """그리기(KSampler 등) 의 positive 쪽 글만 모음 (부정 프롬프트는 뺌)"""
        texts = []
        for u in sorted(self.upstream(nid)):
            inp = self.node(u).get("inputs") or {}
            if "positive" in inp and self.link(inp["positive"]):
                pu = {str(inp["positive"][0])} | self.upstream(inp["positive"][0])
                for x in sorted(pu):
                    n = self.node(x)
                    if n.get("class_type") in ("CLIPTextEncode", "TextEncodeQwenImageEditPlus"):
                        t = (n.get("inputs") or {}).get("text", (n.get("inputs") or {}).get("prompt", ""))
                        if isinstance(t, str) and t not in texts:
                            texts.append(t)
        return ", ".join(texts)

    def seed(self, nid):
        for u in sorted(self.upstream(nid)):
            inp = self.node(u).get("inputs") or {}
            for k in ("seed", "noise_seed"):
                if isinstance(inp.get(k), (int, float)):
                    return int(inp[k])
        return 0


# ------------------------------------------------------------------ 그림 만들기
def _figure(dr, cx, top, w, h, fur=(25, 25, 30)):
    """아주 단순한 '캐릭터' : 머리(원) + 귀(삼각형) + 몸통(타원) + 팔(선) + 흰 무늬"""
    hr = max(6, int(w * 0.16))
    hy = top + hr + int(h * 0.08)
    dr.polygon([(cx - hr, hy - hr // 2), (cx - hr // 2, hy - hr * 2), (cx, hy - hr)], fill=fur)
    dr.polygon([(cx + hr, hy - hr // 2), (cx + hr // 2, hy - hr * 2), (cx, hy - hr)], fill=fur)
    dr.ellipse([cx - hr, hy - hr, cx + hr, hy + hr], fill=fur)
    dr.polygon([(cx, hy - hr * 0.8), (cx - hr * 0.2, hy - hr * 0.3), (cx, hy), (cx + hr * 0.2, hy - hr * 0.3)], fill=(245, 245, 245))
    for ex in (-1, 1):
        dr.ellipse([cx + ex * hr * 0.45 - hr * 0.15, hy - hr * 0.1, cx + ex * hr * 0.45 + hr * 0.15, hy + hr * 0.2], fill=(240, 220, 60))
    by0, by1 = hy + hr, min(top + h, hy + hr + int(h * 0.55))
    dr.ellipse([cx - w * 0.28, by0, cx + w * 0.28, by1], fill=fur)
    dr.rectangle([cx - hr * 0.6, by0, cx + hr * 0.6, by0 + max(3, hr * 0.25)], fill=(20, 30, 90))     # 목도리
    for ex in (-1, 1):
        dr.line([(cx + ex * w * 0.25, by0 + 10), (cx + ex * w * 0.42, by0 + (by1 - by0) * 0.6)], fill=fur, width=max(3, hr // 3))
        hx, hy2 = cx + ex * w * 0.42, by0 + (by1 - by0) * 0.6
        dr.ellipse([hx - hr * 0.3, hy2 - hr * 0.3, hx + hr * 0.3, hy2 + hr * 0.3], fill=(240, 240, 240))  # 흰 손


def picture(w, h, seed, people=1):
    rnd = random.Random(seed)
    bg = tuple(rnd.randint(120, 235) for _ in range(3))
    im = Image.new("RGB", (w, h), bg)
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, int(h * 0.7), w, h], fill=tuple(max(0, c - 50) for c in bg))    # 땅
    for _ in range(6):                                                                # 나무·구름 (빈 그림 검사에 안 걸리게)
        x, y = rnd.randint(0, w), rnd.randint(int(h * 0.3), int(h * 0.7))
        r = rnd.randint(max(4, w // 30), max(8, w // 10))
        dr.rectangle([x - r // 6, y, x + r // 6, int(h * 0.75)], fill=(90, 60, 30))
        dr.ellipse([x - r, y - r, x + r, y + r], fill=(30, rnd.randint(100, 170), 40))
        cx, cy = rnd.randint(0, w), rnd.randint(0, int(h * 0.25))
        dr.ellipse([cx - r, cy - r // 2, cx + r, cy + r // 2], fill=(250, 250, 250))
    if people:
        slots = [0.5] if people == 1 else [0.28, 0.72]
        fw = w / (1.4 if people == 1 else 2.6)
        for i, sx in enumerate(slots):
            _figure(dr, int(w * sx), int(h * 0.1), int(fw), int(h * 0.85), (25, 25, 30) if i == 0 else (60, 150, 90))
    return im


def mask_picture(w, h, prompt, individual):
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    p = (prompt or "").lower()
    n = 2 if (individual and w > h * 1.15) else 1
    xs = [0.5] if n == 1 else [0.28, 0.72]
    outs = []
    for sx in xs:
        m = im.copy() if individual else im
        d = ImageDraw.Draw(m) if individual else dr
        cx = w * sx
        if "hand" in p or "paw" in p:
            r = min(w, h) * 0.05
            for ex in (-1, 1):
                hx, hy = cx + ex * w * 0.3 * (0.5 if n == 2 else 1), h * 0.62
                d.ellipse([hx - r, hy - r, hx + r, hy + r], fill=255)
        elif "head" in p or "face" in p or "hair" in p or "ear" in p:
            r = min(w, h) * 0.12
            d.ellipse([cx - r, h * 0.12, cx + r, h * 0.12 + 2 * r], fill=255)
        else:
            d.ellipse([cx - w * 0.2 / n, h * 0.1, cx + w * 0.2 / n, h * 0.95], fill=255)
        if individual:
            outs.append(m.convert("RGB"))
    return outs or [im.convert("RGB")]


# ------------------------------------------------------------------ 서버
class State:
    def __init__(self, data, fail_class):
        self.data = data
        self.fail_class = set(x for x in (fail_class or "").split(",") if x)
        self.uploads = {}         # "subfolder/name" -> (w, h)
        self.history = {}
        self.log = []             # [(시간, 경로, 요약)] - 실행기가 /mock/log 로 읽음
        self.lock = threading.Lock()
        for d in ("input", "output", "temp"):
            os.makedirs(os.path.join(data, d), exist_ok=True)

    def run(self, graph):
        pid = str(uuid.uuid4())
        G = Graph(graph, self.uploads)
        classes = sorted(set(n.get("class_type", "") for n in graph.values() if isinstance(n, dict)))
        if self.fail_class & set(classes):
            with self.lock:
                self.history[pid] = {"prompt": [0, pid, graph, {}, []], "outputs": {},
                                     "status": {"status_str": "error", "completed": False,
                                                "messages": [["execution_error", {"node_type": sorted(self.fail_class & set(classes))[0],
                                                                                  "exception_message": "mock failure (--fail-class)"}]]}}
                self.log.append((time.time(), "prompt", "FAIL " + ",".join(classes)))
            return pid
        outputs = {}
        for nid, n in graph.items():
            if not isinstance(n, dict) or n.get("class_type") not in ("SaveImage", "PreviewImage", "SaveImageWebsocket"):
                continue
            s = G.size(nid) or (1024, 1024)
            w, h = max(8, int(s[0])), max(8, int(s[1]))
            ups = G.upstream(nid)
            sam = [u for u in ups if G.node(u).get("class_type") == "SAM3_Detect"]
            ims, src_meta = [], {}
            if sam:
                sn = G.node(sam[0])["inputs"]
                prompt = ""
                cond = sn.get("conditioning")
                if G.link(cond):
                    prompt = str((G.node(cond[0]).get("inputs") or {}).get("text", ""))
                ims = mask_picture(w, h, prompt, bool(sn.get("individual_masks")))
            else:
                seed = G.seed(nid)
                loads = [u for u in ups if G.node(u).get("class_type") == "LoadImage"]
                src = None
                for u in sorted(loads):
                    nm = str(G.node(u)["inputs"].get("image", "")).replace("\\", "/")
                    p = os.path.join(self.data, "input", *nm.split("/"))
                    if os.path.exists(p):
                        src = p
                        break
                if src and not G.find_up(nid, "EmptyLatentImage") and not G.find_up(nid, "EmptySD3LatentImage"):
                    with Image.open(src) as im0:
                        src_meta = dict(im0.info or {})
                        im = im0.convert("RGB").resize((w, h))
                    tint = Image.new("RGB", (w, h), tuple(random.Random(seed).randint(0, 255) for _ in range(3)))
                    im = Image.blend(im, tint, 0.02)                 # 전/후가 조금 달라야 md5 비교가 동작 (크면 unify 색 틀어짐 검사에 걸림)
                    ims = [im]
                else:
                    text = " ".join(str((G.node(u).get("inputs") or {}).get("text", "")) for u in ups
                                    if G.node(u).get("class_type") == "CLIPTextEncode").lower()
                    people = 2 if re.search(r"\b2(boys|girls|others)\b|multiple (boys|girls|others)|\bduo\b", text) else (
                        0 if ("no humans" in text and "1boy" not in text and "solo" not in text) else 1)
                    ims = [picture(w, h, seed, people)]
            from PIL.PngImagePlugin import PngInfo
            meta = PngInfo()
            ptxt = G.positive_text(nid)
            if sam:
                ptxt = ""
            elif src_meta.get("nk_mock_prompt"):                       # 편집: 원래 그림의 태그 + 편집 글
                ptxt = src_meta["nk_mock_prompt"] + ", " + ptxt
            meta.add_text("nk_mock_prompt", ptxt)
            typ = "temp" if n.get("class_type") == "PreviewImage" else "output"
            prefix = str((n.get("inputs") or {}).get("filename_prefix", "ComfyUI")).replace("\\", "/")
            sub = os.path.dirname(prefix)
            base = os.path.basename(prefix) or "ComfyUI"
            if "filename_prefix" not in (n.get("inputs") or {}):
                base = "ComfyUI_temp_%s" % nid
            imgs = []
            for k, im in enumerate(ims):
                fn = "%s_%05d_.png" % (base, len(self.history) * 10 + k + 1)
                d = os.path.join(self.data, typ, *[x for x in sub.split("/") if x])
                os.makedirs(d, exist_ok=True)
                im.save(os.path.join(d, fn), pnginfo=meta)
                imgs.append({"filename": fn, "subfolder": sub, "type": typ})
            outputs[nid] = {"images": imgs}
        with self.lock:
            self.history[pid] = {"prompt": [0, pid, graph, {}, []], "outputs": outputs,
                                 "status": {"status_str": "success", "completed": True, "messages": []}}
            self.log.append((time.time(), "prompt", ",".join(classes)))
        return pid


def make_handler(S):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path
            if p == "/system_stats":
                return self._send(200, {"system": {"os": "mock", "python_version": sys.version, "comfyui_version": "mock"},
                                        "devices": [{"name": "mock", "type": "cpu", "vram_total": 8 << 30, "vram_free": 8 << 30}]})
            if p == "/object_info":
                return self._send(200, object_info())
            if p.startswith("/object_info/"):
                return self._send(200, object_info(p[len("/object_info/"):]))
            if p.startswith("/history/"):
                pid = p[len("/history/"):]
                with S.lock:
                    h = S.history.get(pid)
                return self._send(200, {pid: h} if h else {})
            if p == "/history":
                with S.lock:
                    return self._send(200, dict(S.history))
            if p == "/queue":
                return self._send(200, {"queue_running": [], "queue_pending": []})
            if p == "/view":
                q = parse_qs(u.query)
                fn = q.get("filename", [""])[0]
                sub = q.get("subfolder", [""])[0]
                typ = q.get("type", ["output"])[0]
                f = os.path.join(S.data, typ, *[x for x in sub.replace("\\", "/").split("/") if x], fn)
                if ".." in fn or not os.path.isfile(f):
                    return self._send(404, {"error": "not found"})
                return self._send(200, open(f, "rb").read(), "image/png")
            if p == "/mock/log":
                with S.lock:
                    return self._send(200, {"log": S.log, "uploads": len(S.uploads), "jobs": len(S.history)})
            return self._send(404, {"error": "mock: unknown path " + p})

        def do_POST(self):
            p = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            if p == "/prompt":
                try:
                    d = json.loads(raw.decode("utf-8"))
                except Exception as e:
                    return self._send(400, {"error": "bad json: %s" % e})
                g = d.get("prompt") or {}
                bad = [k for k, v in g.items() if not isinstance(v, dict) or "class_type" not in v]
                unknown = sorted(set(v.get("class_type") for v in g.values() if isinstance(v, dict)) - set(NODES))
                if bad or unknown:          # 진짜 ComfyUI 도 모르는 노드면 400 (node_errors)
                    return self._send(400, {"error": {"type": "invalid_prompt", "message": "mock: bad nodes %s unknown %s" % (bad, unknown)},
                                            "node_errors": {}})
                pid = S.run(g)
                return self._send(200, {"prompt_id": pid, "number": len(S.history), "node_errors": {}})
            if p == "/upload/image":
                ctype = self.headers.get("Content-Type", "")
                m = re.search(r"boundary=(.+)", ctype)
                if not m:
                    return self._send(400, {"error": "no boundary"})
                parts = raw.split(("--" + m.group(1)).encode())
                fields, img, fname = {}, None, "upload.png"
                for part in parts:
                    if b"\r\n\r\n" not in part:
                        continue
                    head, body = part.split(b"\r\n\r\n", 1)
                    body = body[:-2] if body.endswith(b"\r\n") else body
                    hd = head.decode("utf-8", "replace")
                    nm = re.search(r'name="([^"]+)"', hd)
                    fn = re.search(r'filename="([^"]*)"', hd)
                    if nm and nm.group(1) == "image":
                        img, fname = body, (fn.group(1) if fn else fname)
                    elif nm:
                        fields[nm.group(1)] = body.decode("utf-8", "replace")
                if img is None:
                    return self._send(400, {"error": "no image"})
                sub = fields.get("subfolder", "").replace("\\", "/").strip("/")
                d = os.path.join(S.data, "input", *[x for x in sub.split("/") if x])
                os.makedirs(d, exist_ok=True)
                fp = os.path.join(d, os.path.basename(fname))
                with open(fp, "wb") as f:
                    f.write(img)
                try:
                    with Image.open(fp) as im:
                        sz = im.size
                except Exception:
                    return self._send(400, {"error": "not an image"})
                key = (sub + "/" if sub else "") + os.path.basename(fname)
                with S.lock:
                    S.uploads[key] = sz
                    S.log.append((time.time(), "upload", key))
                return self._send(200, {"name": os.path.basename(fname), "subfolder": sub, "type": "input"})
            if p in ("/free", "/interrupt", "/queue"):
                return self._send(200, {})
            return self._send(404, {"error": "mock: unknown path " + p})
    return H


def serve(port, data, fail_class="", host="127.0.0.1"):
    """스레드로 띄우고 (server, state) 를 돌려줌 (실행기·pytest 가 씀)"""
    S = State(data, fail_class)
    srv = ThreadingHTTPServer((host, port), make_handler(S))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, S


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--port", type=int, default=18188)
    a.add_argument("--data", default=None, help="그림을 둘 폴더 (기본: 임시 폴더 - 키트 폴더에는 안 씀)")
    a.add_argument("--fail-class", default="")
    o = a.parse_args()
    if not o.data:
        import tempfile
        o.data = tempfile.mkdtemp(prefix="nk_mock_comfy_")
    srv, _ = serve(o.port, o.data, o.fail_class)
    print("mock ComfyUI on http://127.0.0.1:%d  (data %s)" % (o.port, o.data))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
