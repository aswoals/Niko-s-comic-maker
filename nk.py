#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
nk.py - furry_oc_kit command line (P1: ComfyUI API runner)

  nk gen   [--char mychar] [--preset mystyle] [--scene cafe] [--n 5] ...
  nk style --artist "artist a,artist b" [--cfg 3.5,4.5] [--quality on,off] [--seed 42]
  nk qa    --run <name> | --dir <folder>   [--char mychar]   detail QA via Ollama VLM
  nk run   (same options as gen) [--n 8] [--final 3]   gen -> QA -> best 3 re-rendered with hires -> final/
  nk sheet --artists "artist a,artist b" [--views front,back] [--n 2] [--denoise 0.75] [--cn 0.7]   sheet img2img + lineart ControlNet
  nk pick  --run NAME --ids 2,5               re-render chosen drafts with hires -> NAME/final/
  nk suite <name> [--preset mystyle]          scene list from suites/<name>.yaml -> one folder + numbered grid
  nk board                     QA pass-rate scoreboard by artist
  nk list                      show presets / scenes / characters
  nk free                      unload models from ComfyUI (before running a VLM)
  add --dry to any gen/style command to only print the prompt (no server needed)

All tunables live in presets.yaml and characters/<name>.yaml."""
import sys, os, re, json, time, uuid, argparse, random, shutil, urllib.request, urllib.error, urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KIT = os.path.dirname(os.path.abspath(__file__))

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml missing. run:  pip install pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------- config
#   ComfyUI 결과를 공유 output 폴더에 저장하지 않고(SaveImage -> PreviewImage = ComfyUI 임시 폴더),
#   ComfyUI input 에 올린 그림은 작업이 끝나면 지움. 코드·설정·캐릭터 파일은 키트 것을 그대로 읽음.
NK_HOME = os.environ.get("NK_HOME") or ""
PRIVATE = bool(NK_HOME)
COMFY_SHARED = os.path.join((os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")), "Comfy-Desktop", "ComfyUI-Shared")
_PRIVATE_UPLOADS = []


def data_root(kit=None):
    return NK_HOME or kit or KIT


def upload_subfolder(default):
    return "nk_private" if PRIVATE else default


def remember_upload(name):
    """개인 모드에서 ComfyUI input 에 올린 파일 -> 끝날 때 지움"""
    if PRIVATE and name:
        _PRIVATE_UPLOADS.append(name)


def _cleanup_private_uploads():
    for n in _PRIVATE_UPLOADS:
        p = os.path.join(COMFY_SHARED, "input", *str(n).split("/"))
        try:
            if os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass


if PRIVATE:
    import atexit
    atexit.register(_cleanup_private_uploads)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_presets():
    cfg = load_yaml(os.path.join(KIT, "presets.yaml"))
    r = cfg.get("output_root")
    if r and not os.path.isabs(str(r)) and not re.match(r"^[A-Za-z]:[\\/]", str(r)):
        cfg["output_root"] = os.path.join(KIT, str(r))
    if PRIVATE:
        cfg["output_root"] = os.path.join(NK_HOME, "runs")
    if os.environ.get("NK_COMFY_SERVER"):
        cfg["server"] = os.environ["NK_COMFY_SERVER"]
    if os.environ.get("NK_OLLAMA"):
        cfg.setdefault("qa", {})["ollama"] = os.environ["NK_OLLAMA"]
    return cfg


def load_char(name):
    p = os.path.join(chars_dir(), name + ".yaml")
    if not os.path.exists(p):
        print("[ERROR] character file not found:", p)
        sys.exit(1)
    return load_yaml(p)


def clean_tags(s):
    """'a, b,, c ' -> 'a, b, c'  (also folds newlines from yaml >- blocks)"""
    if not s:
        return ""
    parts = [t.strip() for t in str(s).replace("\n", " ").split(",")]
    return ", ".join([t for t in parts if t])


def keep_awake():
    """이 프로그램이 도는 동안 Windows 절전 막기 (화면은 꺼져도 됨, 끝나면 자동 해제).
우체통(nk_remote)은 절전을 막지만 메뉴·nk ep auto 는 안 막고 있었음
    (자리를 비우면 PC가 잠들어 그리기가 멈췄을 가능성, 추정)"""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetThreadExecutionState(0x80000000 | 0x00000001)
        # 검은 창을 마우스로 클릭하면 '선택 모드'가 돼서 출력(=프로그램)이 멈추는 Windows 기능(빠른 편집) 끄기
        # (우체통 nk_remote 와 같은 처리. 메뉴 창에는 없었음)
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass


ARTIST_MIN_POSTS = 50          # 이보다 적으면 모델이 그림체를 거의 모름 (추정 - 작가 태그 시험으로 조정)
_ARTISTS = None
_ARTIST_NOTED = set()


def artist_tag_posts(name):
    """tags/danbooru.csv·e621.csv 에서 작가(분류 1) 태그의 게시물 수. 없으면 0"""
    global _ARTISTS
    if _ARTISTS is None:
        import csv
        _ARTISTS = {}
        for fn in ("danbooru.csv", "e621.csv"):
            p = os.path.join(KIT, "tags", fn)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 3 and row[1].strip() == "1":
                        try:
                            n = int(row[2] or 0)
                        except ValueError:
                            continue
                        k = row[0].strip().lower()
                        _ARTISTS[k] = max(_ARTISTS.get(k, 0), n)
    return _ARTISTS.get(str(name).strip().lower().replace(" ", "_"), 0)


# ---------------------------------------------------------------- settings merge
def artist_known(cfg, name):
    """설정표(presets)에 있거나 태그 사전 작가 게시물이 충분한가 (build_settings 가 멈추지 않을 이름인가)"""
    return name in (cfg.get("presets") or {}) or artist_tag_posts(name) >= ARTIST_MIN_POSTS


def build_settings(cfg, args):
    """defaults <- presets (in order) <- explicit cli options"""
    s = dict(cfg.get("defaults", {}))
    s["artist"] = ""
    s["extra"] = ""
    s["negative_extra"] = ""
    s["loras"] = []  # list of (file, strength)

    if getattr(args, "preset", None):
        for name in [p.strip() for p in args.preset.split(",") if p.strip()]:
            pr = cfg.get("presets", {}).get(name)
            if pr is None:
                n = artist_tag_posts(name)
                if n >= ARTIST_MIN_POSTS:
                    pr = {"artist": name.replace("_", " ").replace("(", "\\(").replace(")", "\\)")}
                    if name not in _ARTIST_NOTED:
                        _ARTIST_NOTED.add(name)
                        print("[note] '%s' is not a preset - using it as an artist tag (%d posts in the tag dictionary)" % (name, n))
                else:
                    print("[ERROR] unknown preset:", name, " (nk list)%s" % (
                        "" if not n else " - artist tag with only %d posts (need %d)" % (n, ARTIST_MIN_POSTS)))
                    sys.exit(1)
            for k, v in pr.items():
                if k == "extra":
                    s["extra"] = clean_tags(s["extra"] + ", " + str(v))
                elif k == "negative_extra":
                    s["negative_extra"] = clean_tags(s["negative_extra"] + ", " + str(v))
                else:
                    s[k] = v

    # explicit cli overrides
    for k in ("cfg", "steps", "sampler", "scheduler", "quality", "rating", "year",
              "artist", "artist_weight", "artist_position", "tags", "strength", "charlora",
              "hires", "hires_denoise", "hires_steps", "hires_method", "upscale_model"):
        v = getattr(args, k, None)
        if v is not None and v != "":
            s[k] = v
    if getattr(args, "size", None):
        w, h = args.size.lower().split("x")
        s["width"], s["height"] = int(w), int(h)
    if getattr(args, "extra", None):
        s["extra"] = clean_tags(s["extra"] + ", " + args.extra)
    if getattr(args, "neg", None):
        s["negative_extra"] = clean_tags(s["negative_extra"] + ", " + args.neg)
    if getattr(args, "lora", None):
        for item in args.lora:
            if ":" in item:
                f, st = item.rsplit(":", 1)
                s["loras"].append((f, float(st)))
            else:
                s["loras"].append((item, 1.0))
    s["quality"] = str(s.get("quality", "on")).lower()
    return s


def resolve_scene(cfg, scene):
    if not scene:
        return ""
    return clean_tags(cfg.get("scenes", {}).get(scene, scene))


def compose_prompt(s, char, scene_tags):
    """returns (positive, negative)"""
    pos = []
    if s["quality"] == "on":
        pos.append(clean_tags(s.get("quality_tags", "")))

    artist = ""
    if s.get("artist"):
        w = float(s.get("artist_weight", 1.0))
        artist = "by %s" % s["artist"] if abs(w - 1.0) < 1e-6 else "(by %s:%.2f)" % (s["artist"], w)
    if artist and s.get("artist_position", "front") == "front":
        pos.append(artist)

    rating = "safe"                  # 전연령 전용: 설정과 상관없이 늘 safe (안전장치 safe_graph 도 한 번 더 막음)
    pos.append("safe")

    if char:
        block = char["trigger"]
        tag_field = "tags_full" if str(s.get("tags", "short")) == "full" else "tags_short"
        if char.get(tag_field):
            block += ", " + clean_tags(char[tag_field])
        pos.append(block)

    if scene_tags:
        pos.append(scene_tags)
    if s.get("extra"):
        pos.append(clean_tags(s["extra"]))
    if artist and s.get("artist_position", "front") == "back":
        pos.append(artist)
    if s.get("year"):
        pos.append("year %s" % s["year"])

    neg = clean_tags(s.get("negative", ""))
    neg = clean_tags(SAFE_NEG + ", " + neg)
    if char and char.get("negative_extra"):
        neg = clean_tags(neg + ", " + char["negative_extra"])
    if s.get("negative_extra"):
        neg = clean_tags(neg + ", " + s["negative_extra"])
    return clean_tags(", ".join([p for p in pos if p])), neg


# ---------------------------------------------------------------- graph (ComfyUI API format)
def build_graph(cfg, s, char, positive, negative, seed, batch, prefix):
    g = {}
    g["4"] = {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": cfg["checkpoint"]}}
    model, clip = ["4", 0], ["4", 1]
    loras = []
    if char and char.get("lora"):
        lf = s.get("charlora") or char["lora"]
        st = s["strength"] if s.get("strength") is not None else float(char.get("lora_strength", 1.0))
        loras.append((lf, float(st)))
    loras += s.get("loras", [])
    nid = 20
    for f, st in loras:
        g[str(nid)] = {"class_type": "LoraLoader",
                       "inputs": {"model": model, "clip": clip, "lora_name": f,
                                  "strength_model": st, "strength_clip": st}}
        model, clip = [str(nid), 0], [str(nid), 1]
        nid += 1
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": clip}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": clip}}
    g["5"] = {"class_type": "EmptyLatentImage",
              "inputs": {"width": int(s["width"]), "height": int(s["height"]), "batch_size": int(batch)}}
    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                         "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": 1.0,
                         "model": model, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}}
    last = ["3", 0]
    hires = float(s.get("hires", 0) or 0)
    if hires and hires > 1.0:
        method = str(s.get("hires_method", "pixel"))
        if method == "latent":
            g["10"] = {"class_type": "LatentUpscaleBy",
                       "inputs": {"samples": ["3", 0], "upscale_method": "nearest-exact", "scale_by": hires}}
            up_latent = ["10", 0]
        else:
            # pixel way: decode -> upscale image (lanczos, or an upscale model) -> encode. faithful at low denoise
            g["12"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
            img = ["12", 0]
            if method == "model" and s.get("upscale_model"):
                g["13"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": s["upscale_model"]}}
                g["14"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": img}}
                # model upscales x4 (or x2) -> scale back to the wanted factor
                w_t, h_t = int(int(s["width"]) * hires) // 8 * 8, int(int(s["height"]) * hires) // 8 * 8
                g["15"] = {"class_type": "ImageScale", "inputs": {"image": ["14", 0], "upscale_method": "lanczos",
                                                                "width": w_t, "height": h_t, "crop": "disabled"}}
                img = ["15", 0]
            else:
                g["15"] = {"class_type": "ImageScaleBy", "inputs": {"image": img, "upscale_method": "lanczos",
                                                                  "scale_by": hires}}
                img = ["15", 0]
            g["16"] = {"class_type": "VAEEncode", "inputs": {"pixels": img, "vae": ["4", 2]}}
            up_latent = ["16", 0]
        g["11"] = {"class_type": "KSampler",
                   "inputs": {"seed": int(seed), "steps": int(s.get("hires_steps", 20)), "cfg": float(s["cfg"]),
                              "sampler_name": s["sampler"], "scheduler": s["scheduler"],
                              "denoise": float(s.get("hires_denoise", 0.35)),
                              "model": model, "positive": ["6", 0], "negative": ["7", 0], "latent_image": up_latent}}
        last = ["11", 0]
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": last, "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    if s.get("style_ref"):
        import nk_styleref
        nk_styleref.attach(g, s, KIT, cfg)
    return g


# ComfyUI 기본 노드 RescaleCFG -> 설치 없음. presets.yaml defaults.cfg_rescale 로 바꿈 (0 = 끔). 키가 없으면(예: 옛 실험 폴더) 0.2.
CFG_RESCALE_DEFAULT = 0.2
_RESCALE = None
_MODEL_STOP = ("UNETLoader", "UnetLoaderGGUF", "ModelSamplingAuraFlow")   # Qwen·Anima 쪽 -> 손대지 않음


def cfg_rescale_value():
    global _RESCALE
    if _RESCALE is None:
        try:
            v = (load_presets().get("defaults") or {}).get("cfg_rescale", CFG_RESCALE_DEFAULT)
            _RESCALE = float(v or 0)
        except Exception:
            _RESCALE = CFG_RESCALE_DEFAULT
    return _RESCALE


def apply_cfg_rescale(graph, mult=None):
    """NoobAI(CheckpointLoaderSimple)에서 온 모델을 쓰는 KSampler(cfg>1)에만 RescaleCFG 를 끼움.
    Qwen 편집·Anima 뼈대(cfg 1, UNETLoader)는 그대로. 그래프에 이미 RescaleCFG 가 있으면(cfgtest) 건드리지 않음."""
    mult = cfg_rescale_value() if mult is None else float(mult)
    if not mult or not isinstance(graph, dict):
        return graph
    if any(isinstance(n, dict) and n.get("class_type") == "RescaleCFG" for n in graph.values()):
        return graph

    def from_ckpt(ref):
        for _ in range(30):
            node = graph.get(str(ref[0])) if isinstance(ref, list) and ref else None
            if not node:
                return False
            ct = node.get("class_type")
            if ct == "CheckpointLoaderSimple":
                return True
            if ct in _MODEL_STOP:
                return False
            ref = node.get("inputs", {}).get("model")
        return False

    made, nid = {}, 9700
    for n in list(graph.values()):
        if not isinstance(n, dict) or n.get("class_type") != "KSampler":
            continue
        inp = n.get("inputs", {})
        m = inp.get("model")
        try:
            if float(inp.get("cfg", 1.0)) <= 1.0 or not from_ckpt(m):
                continue
        except (TypeError, ValueError):
            continue
        key = (str(m[0]), m[1])
        if key not in made:
            while str(nid) in graph:
                nid += 1
            graph[str(nid)] = {"class_type": "RescaleCFG", "inputs": {"model": list(m), "multiplier": mult}}
            made[key] = str(nid)
        inp["model"] = [made[key], 0]
    return graph


# ---------------------------------------------------------------- ComfyUI client
class Comfy:
    def __init__(self, server):
        self.base = None
        cands = ["http://127.0.0.1:%d" % p for p in (8000, 8188, 8189, 8190, 8191)] if server in (None, "", "auto") else [server]
        # 창 없이 도는 작업(우체통·작업실 = 입력 창 없음)은 ComfyUI가 다시 켜질 때까지 기다림 (NK_COMFY_WAIT 초, 기본 900)
        try:
            interactive = sys.stdin is not None and sys.stdin.isatty()
        except Exception:
            interactive = False
        wait = float(os.environ.get("NK_COMFY_WAIT", "0" if interactive else "900"))
        t0 = time.time()
        while True:
            for c in cands:
                try:
                    urllib.request.urlopen(c + "/system_stats", timeout=3).read()
                    self.base = c
                    break
                except Exception:
                    continue
            if self.base or time.time() - t0 >= wait:
                break
            if int(time.time() - t0) % 60 < 11:
                print("   ComfyUI 기다리는 중 (%d초째, 최대 %d초) - 다시 켜는 중이면 곧 이어서 함" % (time.time() - t0, wait))
            time.sleep(10)
        if not self.base:
            print("[ERROR] ComfyUI not reachable (tried %s). Is ComfyUI running?" % ", ".join(cands))
            sys.exit(1)
        self.client_id = str(uuid.uuid4())

    def _post(self, path, data):
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            print("[ERROR] ComfyUI %s -> %s\n%s" % (path, e.code, body[:2000]))
            sys.exit(1)

    def _get(self, path):
        return json.loads(urllib.request.urlopen(self.base + path, timeout=30).read().decode("utf-8"))

    def upload_input(self, path, name, subfolder):
        """파일 하나를 ComfyUI input/<subfolder>/<name> 으로 올림 (multipart /upload/image). 반환: LoadImage 에 쓸 이름"""
        bd = "----nk" + uuid.uuid4().hex
        data = open(path, "rb").read()
        body = (("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
                 % (bd, name)).encode() + data +
                ("\r\n--%s\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\n%s"
                 "\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--%s--\r\n"
                 % (bd, subfolder, bd, bd)).encode())
        req = urllib.request.Request(self.base + "/upload/image", data=body,
                                     headers={"Content-Type": "multipart/form-data; boundary=" + bd})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
        return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]

    def _resolve_files(self, graph):
        if not hasattr(self, "_uploaded"):
            self._uploaded = {}
        for n in graph.values():
            if not isinstance(n, dict) or n.get("class_type") != "LoadImage":
                continue
            v = str(n.get("inputs", {}).get("image", ""))
            if not v.startswith("@file:"):
                continue
            p = v[len("@file:"):]
            if p not in self._uploaded:
                import nk_styleref
                tmp = os.path.join(data_root(), "runs", "_upload_tmp")
                os.makedirs(tmp, exist_ok=True)
                name = nk_styleref.upload_name(p)
                sq = nk_styleref.square_png(p, os.path.join(tmp, name))
                self._uploaded[p] = self.upload_input(sq, name, upload_subfolder("nk_style"))
                remember_upload(self._uploaded[p])
            n["inputs"]["image"] = self._uploaded[p]

    def queue(self, graph, raw=False):
        safe_graph(graph)                       # 전연령 안전장치 (raw 여도 늘)
        if not raw:
            apply_cfg_rescale(graph)
        self._resolve_files(graph)
        if PRIVATE:
            for n in graph.values():
                if isinstance(n, dict) and n.get("class_type") == "SaveImage":
                    n["class_type"] = "PreviewImage"
                    n["inputs"] = {"images": n["inputs"]["images"]}
        r = self._post("/prompt", {"prompt": graph, "client_id": self.client_id})
        return r["prompt_id"]

    def wait(self, pid, label=""):
        t0 = time.time()
        while True:
            h = self._get("/history/" + pid)
            if pid in h:
                st = h[pid].get("status", {})
                if st.get("status_str") == "error":
                    print("[ERROR] job failed:", json.dumps(st.get("messages", []))[:1500])
                    sys.exit(1)
                return h[pid]["outputs"]
            time.sleep(1.0)
            el = int(time.time() - t0)
            if el % 10 == 0:
                print("   ... %s %ds" % (label, el), end="\r")

    def fetch(self, img, dest):
        q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                    "type": img.get("type", "output")})
        data = urllib.request.urlopen(self.base + "/view?" + q, timeout=60).read()
        with open(dest, "wb") as f:
            f.write(data)

    def free(self):
        self._post("/free", {"unload_models": True, "free_memory": True})


# ---------------------------------------------------------------- commands
def run_jobs(cfg, jobs, run_name, dry):
    """jobs: list of dict(label, graph, positive, negative, settings, seed). returns list of result dicts"""
    out_dir = os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), run_name)
    if dry:
        for j in jobs:
            print("\n[%s] seed=%s cfg=%s steps=%s %sx%s" % (j["label"], j["seed"], j["settings"]["cfg"],
                  j["settings"]["steps"], j["settings"]["width"], j["settings"]["height"]))
            print("  +", j["positive"])
            print("  -", j["negative"])
            loras = [(n["inputs"].get("lora_name"), n["inputs"].get("strength_model")) for n in j["graph"].values()
                     if isinstance(n, dict) and n.get("class_type") == "LoraLoader"]
            print("  lora:", loras, "| hires:", j["settings"].get("hires") or "off")
        print("\n(dry run: nothing sent. output would go to %s)" % out_dir)
        return []

    os.makedirs(out_dir, exist_ok=True)
    c = Comfy(cfg.get("server", "auto"))
    print("ComfyUI:", c.base, "| output:", out_dir)
    results = []
    for i, j in enumerate(jobs, 1):
        print("[%d/%d] %s" % (i, len(jobs), j["label"]))
        pid = c.queue(j["graph"], raw=bool(j.get("raw")))
        outputs = c.wait(pid, j["label"])
        imgs = []
        for node in outputs.values():
            for im in node.get("images", []):
                imgs.append(im)
        for k, im in enumerate(imgs):
            fn = "%s_%02d.png" % (j["label"], k) if len(imgs) > 1 else "%s.png" % j["label"]
            dest = os.path.join(out_dir, fn)
            c.fetch(im, dest)
            results.append({"file": fn, "label": j["label"], "seed": j["seed"], "positive": j["positive"],
                            "negative": j["negative"], "settings": {k2: v for k2, v in j["settings"].items()
                                                                  if k2 != "loras"},
                            "loras": [list(x) for x in j["settings"].get("loras", [])]})
            if j.get("meta"):
                results[-1].update(j["meta"])
            print("   saved", fn)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("done. %d images -> %s" % (len(results), out_dir))
    return results


def cmd_gen(args):
    cfg = load_presets()
    char = load_char(args.char) if args.char and args.char.lower() != "none" else None
    s = build_settings(cfg, args)
    scene = resolve_scene(cfg, args.scene)
    pos, neg = compose_prompt(s, char, scene)
    base_seed = args.seed if args.seed is not None else random.randint(1, 2**31)
    run_name = args.name or time.strftime("gen_%m%d_%H%M%S")
    jobs = []
    for i in range(args.n):
        seed = base_seed + i
        label = "%03d_s%d" % (i + 1, seed)
        g = build_graph(cfg, s, char, pos, neg, seed, 1, "nk/%s/%s" % (run_name, label))
        jobs.append({"label": label, "graph": g, "positive": pos, "negative": neg, "settings": s, "seed": seed})
    results = run_jobs(cfg, jobs, run_name, args.dry)
    if results and len(results) > 1:
        make_grid(os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), run_name), results)


def cmd_style(args):
    cfg = load_presets()
    char = load_char(args.char) if args.char and args.char.lower() != "none" else None
    scene = resolve_scene(cfg, args.scene or "white")
    artists = [a.strip() for a in (args.artist or "").split(",") if a.strip()] or [""]
    cfgs = [float(x) for x in str(args.cfg or "").split(",") if x.strip()] or [None]
    quals = [q.strip() for q in str(args.quality or "").split(",") if q.strip()] or [None]
    years = [y.strip() for y in str(args.year or "").split(",") if y.strip()] or [None]
    weights = [float(w) for w in str(args.weight or "").split(",") if w.strip()] or [None]
    seed = args.seed if args.seed is not None else random.randint(1, 2**31)
    run_name = args.name or time.strftime("style_%m%d_%H%M%S")
    jobs = []
    for a in artists:
        for cf in cfgs:
            for q in quals:
                for y in years:
                    for w in weights:
                        ns = argparse.Namespace(**vars(args))
                        ns.artist = a
                        ns.cfg = cf
                        ns.quality = q
                        ns.year = y
                        ns.artist_weight = w
                        s = build_settings(cfg, ns)
                        pos, neg = compose_prompt(s, char, scene)
                        label = "_".join([x for x in [
                            (a or "noartist").replace(" ", "-"),
                            ("cfg%g" % s["cfg"]),
                            ("q" + s["quality"]),
                            ("y%s" % y) if y else "",
                            ("w%g" % float(s.get("artist_weight", 1.0))) if w else ""] if x])
                        g = build_graph(cfg, s, char, pos, neg, seed, 1, "nk/%s/%s" % (run_name, label))
                        jobs.append({"label": label, "graph": g, "positive": pos, "negative": neg,
                                     "settings": s, "seed": seed})
    print("style grid: %d images, seed %d" % (len(jobs), seed))
    results = run_jobs(cfg, jobs, run_name, args.dry)
    if results:
        out_dir = os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), run_name)
        make_grid(out_dir, results, cols=args.cols)


def make_grid(out_dir, results, cols=4, thumb=384):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("[WARN] Pillow missing, no grid. pip install pillow")
        return
    n = len(results)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    th = int(thumb * 1216 / 832)
    sheet = Image.new("RGB", (cols * thumb, rows * (th + 22)), "white")
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(results):
        im = Image.open(os.path.join(out_dir, r["file"])).convert("RGB")
        im.thumbnail((thumb, th))
        x, y = (i % cols) * thumb, (i // cols) * (th + 22)
        sheet.paste(im, (x, y + 22))
        d.text((x + 4, y + 4), r["label"][:60], fill="black")
    p = os.path.join(out_dir, "grid.png")
    sheet.save(p)
    print("grid ->", p)


def cmd_list(args):
    cfg = load_presets()
    print("== presets ==")
    for k, v in cfg.get("presets", {}).items():
        print("  %-12s %s" % (k, json.dumps(v, ensure_ascii=False)))
    print("== scenes ==")
    for k, v in cfg.get("scenes", {}).items():
        print("  %-12s %s" % (k, v))
    print("== characters ==")
    cdir = chars_dir()
    for f in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
        if f.endswith(".yaml") and not f.startswith("_"):
            c = load_yaml(os.path.join(cdir, f))
            print("  %-12s trigger=%s lora=%s @%s" % (f[:-5], c.get("trigger"), c.get("lora"), c.get("lora_strength")))
    print("== defaults ==")
    print("  ", json.dumps(cfg.get("defaults", {}), ensure_ascii=False))


def cmd_free(args):
    cfg = load_presets()
    c = Comfy(cfg.get("server", "auto"))
    c.free()
    print("models unloaded from", c.base)



# ---------------------------------------------------------------- QA (P3): Ollama VLM + checklist
def _img_b64(path, max_side):
    import base64, io
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        data = buf.getvalue()
    except ImportError:
        data = open(path, "rb").read()
    return base64.b64encode(data).decode("ascii")


def _img_b64_region(path, max_side, region):
    """region 'face': top ~45% of the image, centered 70% width, upscaled -> small markings become visible"""
    import base64, io
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if region == "face":
        box = (int(w * 0.15), 0, int(w * 0.85), int(h * 0.45))
    elif region == "upper":
        box = (0, 0, w, int(h * 0.7))
    elif region == "lower":
        box = (0, int(h * 0.5), w, h)
    else:
        box = (0, 0, w, h)
    im = im.crop(box)
    scale = max_side / max(im.size)
    if scale > 1:
        im = im.resize((int(im.size[0] * scale), int(im.size[1] * scale)), Image.LANCZOS)
    else:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ollama_ask(qa_cfg, b64, prompt):
    url = qa_cfg.get("ollama", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    body = {"model": qa_cfg.get("model", "qwen2.5vl:7b"), "stream": False, "format": "json",
            "options": {"temperature": float(qa_cfg.get("temperature", 0))},
            "keep_alive": qa_cfg.get("keep_alive", "5m"),
            "messages": [{"role": "user", "content": prompt, "images": [b64]}]}
    if qa_cfg.get("num_ctx"):
        body["options"]["num_ctx"] = int(qa_cfg["num_ctx"])   # small context = less VRAM = stays on GPU
    if qa_cfg.get("cpu"):
        body["options"]["num_gpu"] = 0      # force CPU (use while LoRA training occupies the GPU)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=1800).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("[ERROR] Ollama %s -> %s: %s" % (url, e.code, e.read().decode("utf-8", "replace")[:500]))
        print("        (404 usually = model not installed. check:  ollama list)")
        sys.exit(1)
    except urllib.error.URLError as e:
        print("[ERROR] Ollama not reachable at %s (%s). Is Ollama running?" % (url, e))
        sys.exit(1)
    msg = r.get("message", {})
    content = msg.get("content", "") or ""
    if not content.strip() and msg.get("thinking"):
        content = msg["thinking"]          # some models put the answer in the thinking field
    return content


def ollama_unload(qa_cfg):
    """free VLM VRAM so ComfyUI can load SDXL again"""
    url = qa_cfg.get("ollama", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
    body = {"model": qa_cfg.get("model", "gemma4:e4b-it-qat"), "keep_alive": 0}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
        print("VLM unloaded (VRAM freed for ComfyUI)")
    except Exception as e:
        print("[WARN] could not unload VLM:", e)


def parse_answers(raw, ids):
    """robust: plain JSON -> first {...} block -> key: true/false pairs in text"""
    import re
    raw = raw.strip()
    for cand in [raw, (re.search(r"\{.*\}", raw, re.S) or re.match(r"", "")).group(0)]:
        if not cand:
            continue
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    d = {}
    for i in ids:
        m = re.search(r'"?%s"?\s*[:=]\s*"?(true|false|null|yes|no)"?' % re.escape(i), raw, re.I)
        if m:
            d[i] = m.group(1).lower()
    return d


def _judge_option(v, options, expect):
    """검수 AI 답(v)을 먼저 '보기 하나'에 맞춘 뒤, 그 보기가 합격 목록(expect, 부분 일치)에 있는지 봄.
    반환: True(합격) / False(불합격) / None(답 없음·판단 불가 = 탈락시키지 않음)"""
    import re as _re
    if v is None:
        return None
    txt = _re.sub(r"\s+", " ", str(v).strip().lower().strip(" .,'\"`"))
    if not txt:
        return None
    opts = [str(o).strip().lower() for o in options]
    exp = [str(e).strip().lower() for e in expect]

    def expected(opt):
        return any(e in opt for e in exp)

    if txt in opts:                                   # 1) 보기를 그대로 베낀 답
        cands = [txt]
    else:                                             # 2) 보기 안에 답이 단어로 들어있음(줄임) 또는 답 안에 보기가 들어있음(덧붙임)
        pat = r"(?<![a-z])" + _re.escape(txt) + r"(?![a-z])"
        cands = [o for o in opts if _re.search(pat, o)]
        if not cands:
            cands = [o for o in opts if _re.search(r"(?<![a-z])" + _re.escape(o) + r"(?![a-z])", txt)]
            if len(cands) > 1:                        # 가장 긴 보기 하나만 (예: "no text at all" 과 "text" 둘 다 걸리면 긴 쪽)
                cands = [max(cands, key=len)]
    if not cands:                                     # 3) 어느 보기에도 안 맞음 -> 예전 방식(합격 글자가 답 안에 있나)
        return any(e in txt for e in exp)
    flags = set(expected(o) for o in cands)
    if len(flags) == 1:                               # 걸린 보기가 모두 합격이거나 모두 불합격
        return flags.pop()
    return None                                       # 합격 보기·불합격 보기에 동시에 걸림(예: "white" -> "solid white"/"white with dots")


def qa_folder(folder, char, qa_cfg, rating="safe", files=None):
    """returns list of dict(file, pass, answers{id: bool|None}, fails[list])"""
    items = char.get("qa_checklist", [])
    active = []
    for it in items:
        cond = str(it.get("only_when", "")).replace(" ", "")
        if cond == "rating!=safe" and rating == "safe":
            continue
        active.append(it)
    if files is None:
        files = sorted([f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                        and f != "grid.png"])
    def make_prompt(items):
        lines = []
        for it in items:
            if it.get("options"):
                lines.append('  "%s": %s  Options: %s' % (it["id"], it["q"], " | ".join(it["options"])))
            else:
                lines.append('  "%s": %s  (answer true or false)' % (it["id"], it["q"]))
        return ("You are a strict quality inspector for an illustration of " + char.get("qa_desc", "an anthropomorphic cat character")
                + " named %s.\n"
                "Look at the image carefully, especially small details of fur markings, and answer every question. "
                "For questions with Options, copy exactly one option text as the answer. "
                "Do not guess: if a part is not visible, pick the 'not visible' option.\n"
                "Questions:\n%s\n"
                "Reply with a single JSON object whose keys are exactly the question ids and whose values are the chosen "
                "option text (or true/false for true/false questions). No explanations.") % (
                    char.get("name", "character"), "\n".join(lines))

    two_pass = bool(qa_cfg.get("face_pass", True))
    groups = {}   # region -> items
    for it in active:
        reg = str(it.get("region", "full")) if two_pass else "full"
        groups.setdefault(reg, []).append(it)
    results = []
    for i, f in enumerate(files, 1):
        path = os.path.join(folder, f)
        t0 = time.time()
        ans, raws = {}, {}
        for reg, items in groups.items():
            ms = int(qa_cfg.get("max_side", 1024))
            b64 = _img_b64(path, ms) if reg == "full" else _img_b64_region(path, ms, reg)
            raw = ollama_ask(qa_cfg, b64, make_prompt(items))
            raws[reg] = raw
            ans.update(parse_answers(raw, [it["id"] for it in items]))
            if qa_cfg.get("debug"):
                print("   raw[%s]: %s" % (reg, raw[:600].replace("\n", " ")))
        with open(os.path.join(folder, "qa_raw.jsonl"), "a", encoding="utf-8") as lf:
            lf.write(json.dumps({"file": f, "raw": raws}, ensure_ascii=False) + "\n")
        answers, fails = {}, []
        for it in active:
            v = ans.get(it["id"])
            if it.get("options"):
                ok_item = _judge_option(v, it.get("options", []), it.get("expect", []))
                answers[it["id"]] = {"answer": v, "ok": ok_item}
                if it.get("must") and ok_item is False:
                    fails.append(it["id"])
            else:
                if isinstance(v, str):
                    v = {"true": True, "false": False, "yes": True, "no": False}.get(v.strip().lower())
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    v = bool(v)
                answers[it["id"]] = v
                if it.get("must") and v is False:
                    fails.append(it["id"])
        ok = len(fails) == 0 and len(ans) > 0
        soft = sum(1 for it in active if not it.get("must") and isinstance(answers.get(it["id"]), dict)
                   and answers[it["id"]].get("ok") is False)
        results.append({"file": f, "pass": ok, "fails": fails, "soft_fails": soft, "answers": answers})
        detail = "; ".join("%s=%s" % (k, answers[k]["answer"] if isinstance(answers[k], dict) else answers[k])
                           for k in fails)
        print("[%d/%d] %-28s %s  %s  (%.0fs)" % (i, len(files), f, "PASS" if ok else "FAIL",
              detail if fails else ("" if ans else "(no answer)"), time.time() - t0))
    return results


def write_qa_report(folder, results, char_name):
    with open(os.path.join(folder, "qa.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    passed = [r for r in results if r["pass"]]
    pdir = os.path.join(folder, "pass")
    os.makedirs(pdir, exist_ok=True)
    for r in passed:
        shutil.copy2(os.path.join(folder, r["file"]), os.path.join(pdir, r["file"]))
    # fail statistics per item
    from collections import Counter
    cnt = Counter()
    for r in results:
        for k in r["fails"]:
            cnt[k] += 1
    lines = ["# QA report (%s) - %d/%d pass" % (char_name, len(passed), len(results)), ""]
    lines.append("| file | result | failed items |")
    lines.append("|---|---|---|")
    for r in results:
        det = "; ".join("%s=%s" % (k, r["answers"][k]["answer"] if isinstance(r["answers"].get(k), dict)
                                    else r["answers"].get(k)) for k in r["fails"])
        lines.append("| %s | %s | %s |" % (r["file"], "PASS" if r["pass"] else "FAIL", det))
    lines += ["", "## most common failures"]
    for k, v in cnt.most_common():
        lines.append("- %s: %d" % (k, v))
    with open(os.path.join(folder, "qa_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("QA: %d/%d pass -> %s  (report: qa_report.md)" % (len(passed), len(results), pdir))
    # scoreboard: per-run pass rate grouped by artist (from meta.json if present)
    try:
        meta = {}
        mp = os.path.join(folder, "meta.json")
        if os.path.exists(mp):
            for m in json.load(open(mp, encoding="utf-8")):
                meta[m["file"]] = m
        groups = {}
        for r in results:
            m = meta.get(r["file"], {})
            art = (m.get("settings", {}) or {}).get("artist") or "noartist"
            g = groups.setdefault(art, [0, 0])
            g[1] += 1
            g[0] += 1 if r["pass"] else 0
        board = os.path.join(os.path.dirname(folder.rstrip("/\\")), "scoreboard.csv")
        new = not os.path.exists(board)
        with open(board, "a", encoding="utf-8") as f:
            if new:
                f.write("date,run,artist,pass,total,rate\n")
            for art, (pc, tc) in groups.items():
                f.write("%s,%s,%s,%d,%d,%.2f\n" % (time.strftime("%Y-%m-%d %H:%M"), os.path.basename(folder), art, pc, tc, pc / tc))
        print("scoreboard updated:", board)
    except Exception as e:
        print("[WARN] scoreboard not updated:", e)
    return passed


def cmd_board(args):
    cfg = load_presets()
    board = os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), "scoreboard.csv")
    if not os.path.exists(board):
        print("no scoreboard yet (run: nk qa / nk run)")
        return
    tot = {}
    for line in open(board, encoding="utf-8").read().splitlines()[1:]:
        d, run, art, pc, tc, rate = line.split(",")
        t = tot.setdefault(art, [0, 0])
        t[0] += int(pc)
        t[1] += int(tc)
    print("== pass rate by artist (all runs) ==")
    for art, (pc, tc) in sorted(tot.items(), key=lambda x: -x[1][0] / max(1, x[1][1])):
        print("  %-18s %3d/%3d  %5.0f%%" % (art, pc, tc, 100.0 * pc / max(1, tc)))


def cmd_qa(args):
    cfg = load_presets()
    char = load_char(args.char)
    qa_cfg = dict(cfg.get("qa", {}))
    if args.cpu:
        qa_cfg["cpu"] = True
    if args.model:
        qa_cfg["model"] = args.model
    if args.debug:
        qa_cfg["debug"] = True
    if args.single:
        qa_cfg["face_pass"] = False
    folder = args.dir or os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), args.run or "")
    if not args.dir and not args.run:
        print("[ERROR] give --run <name> or --dir <folder>")
        sys.exit(1)
    if not os.path.isdir(folder):
        print("[ERROR] folder not found:", folder)
        sys.exit(1)
    rating = args.rating or "safe"
    mp = os.path.join(folder, "meta.json")
    if not args.rating and os.path.exists(mp):
        try:
            m = json.load(open(mp, encoding="utf-8"))
            if m:
                rating = str(m[0].get("settings", {}).get("rating", "safe"))
        except Exception:
            pass
    print("QA model: %s%s | folder: %s | rating: %s" % (qa_cfg.get("model"), " (CPU)" if qa_cfg.get("cpu") else "",
                                                       folder, rating))
    files = None
    if args.limit:
        files = sorted([f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                        and f != "grid.png"])[:args.limit]
    results = qa_folder(folder, char, qa_cfg, rating, files)
    write_qa_report(folder, results, char.get("name", args.char))


def cmd_run(args):
    """P5 one-button: gen N -> free VRAM -> QA -> unload VLM -> re-render best K passed with hires -> final/"""
    cfg = load_presets()
    if not args.name:
        args.name = time.strftime("run_%m%d_%H%M%S")
    if args.seed is None:
        args.seed = random.randint(1, 2**31)
    # 1) generate (no hires here: cheap drafts)
    final_hires = args.hires if args.hires else float(cfg.get("defaults", {}).get("final_hires", 1.5))
    args.hires = 0
    cmd_gen(args)
    if args.dry:
        print("(dry) then: QA -> best %d passed re-rendered with hires %.2f -> final/" % (args.final, final_hires))
        return
    # 2) QA
    try:
        Comfy(cfg.get("server", "auto")).free()
        print("ComfyUI models unloaded (VRAM freed for VLM)")
    except SystemExit:
        pass
    char = load_char(args.char)
    folder = os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), args.name)
    s = build_settings(cfg, args)
    qa_cfg = cfg.get("qa", {})
    results = qa_folder(folder, char, qa_cfg, str(s.get("rating", "safe")))
    passed = write_qa_report(folder, results, char.get("name", args.char))
    make_grid(folder, [{"file": r["file"], "label": "%s  %s" % (r["file"][:3], "PASS" if r["pass"] else "x " + ",".join(r["fails"]))}
                       for r in results])
    ollama_unload(qa_cfg)
    if args.final <= 0 or not passed:
        if not passed:
            print("no image passed QA -> no final. check qa_report.md (try another preset or more --n)")
        return
    # 3) best K passed (fewest reference-item misses) -> same seed + prompt, now with hires
    meta = {m["file"]: m for m in json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))}
    best = sorted(passed, key=lambda r: r.get("soft_fails", 0))[:args.final]
    s["hires"] = final_hires
    jobs = []
    for r in best:
        m = meta[r["file"]]
        label = "final_" + m["label"]
        g = build_graph(cfg, s, char, m["positive"], m["negative"], m["seed"], 1,
                        "nk/%s/%s" % (args.name, label))
        jobs.append({"label": label, "graph": g, "positive": m["positive"], "negative": m["negative"],
                     "settings": s, "seed": m["seed"]})
    print("rendering %d final image(s) with hires %.2f ..." % (len(jobs), final_hires))
    run_jobs(cfg, jobs, args.name + "/final", False)
    print("DONE -> %s" % os.path.join(folder, "final"))



def cmd_pick(args):
    """re-render chosen drafts (by number) with hires into <run>/final/"""
    cfg = load_presets()
    folder = os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), args.run)
    mp = os.path.join(folder, "meta.json")
    if not os.path.exists(mp):
        print("[ERROR] no meta.json in", folder)
        sys.exit(1)
    meta = json.load(open(mp, encoding="utf-8"))
    char = load_char(args.char)
    want = [int(x) for x in args.ids.replace(" ", "").split(",") if x]
    ns = argparse.Namespace(preset=None, extra=None, neg=None, lora=None, size=None)
    jobs = []
    for m in meta:
        num = int(m["file"][:3]) if m["file"][:3].isdigit() else -1
        if num not in want:
            continue
        s = dict(m["settings"])
        s["loras"] = [tuple(x) for x in m.get("loras", [])]
        s["hires"] = args.hires or float(cfg.get("defaults", {}).get("final_hires", 1.5))
        dflt = cfg.get("defaults", {})
        s["hires_denoise"] = args.hires_denoise if args.hires_denoise is not None else dflt.get("hires_denoise", 0.35)
        s["hires_method"] = args.hires_method or dflt.get("hires_method", "pixel")
        s["upscale_model"] = dflt.get("upscale_model", "")
        s.setdefault("hires_steps", dflt.get("hires_steps", 20))
        label = "final_" + m["label"] + (("_" + args.tag) if args.tag else "")
        g = build_graph(cfg, s, char, m["positive"], m["negative"], m["seed"], 1, "nk/%s/%s" % (args.run, label))
        jobs.append({"label": label, "graph": g, "positive": m["positive"], "negative": m["negative"],
                     "settings": s, "seed": m["seed"]})
    if not jobs:
        print("[ERROR] no matching numbers. files look like 001_s123.png -> use --ids 1")
        sys.exit(1)
    print("re-rendering %d image(s) with hires %.2f" % (len(jobs), jobs[0]["settings"]["hires"]))
    run_jobs(cfg, jobs, args.run + "/final", args.dry)


def cmd_suite(args):
    """run a list of scenes from suites/<name>.yaml -> one folder + numbered grid"""
    cfg = load_presets()
    sp = os.path.join(KIT, "suites", args.suite + ".yaml")
    if not os.path.exists(sp):
        print("[ERROR] suite not found:", sp)
        sys.exit(1)
    su = load_yaml(sp)
    char = load_char(args.char)
    preset = args.preset or su.get("preset", "")
    n = args.n or int(su.get("n", 2))
    base_seed = args.seed if args.seed is not None else random.randint(1, 2**31)
    run_name = args.name or time.strftime(args.suite + "_%m%d_%H%M")
    jobs, k = [], 0
    for it in su.get("items", []):
        rating, extra = "safe", ""          # 전연령 전용 (scene list 의 rating 은 무시)
        ns = argparse.Namespace(preset=preset, extra=(extra + ", " + (args.extra or "")).strip(", "), neg=args.neg,
                                lora=None, size=None, rating=rating, cfg=args.cfg, steps=None, sampler=None,
                                scheduler=None, quality=None, year=None, artist=None, artist_weight=None,
                                artist_position=None, tags=None, strength=args.strength, charlora=None,
                                hires=0, hires_denoise=None, hires_steps=None, hires_method=None, upscale_model=None)
        s = build_settings(cfg, ns)
        pos, neg = compose_prompt(s, char, clean_tags(it["scene"]))
        for i in range(n):
            k += 1
            seed = base_seed + k
            label = "%03d_%s" % (k, it.get("name", "item"))
            g = build_graph(cfg, s, char, pos, neg, seed, 1, "nk/%s/%s" % (run_name, label))
            jobs.append({"label": label, "graph": g, "positive": pos, "negative": neg, "settings": s, "seed": seed})
    print("suite %s: %d images (%d scenes x %d), preset=%s" % (args.suite, len(jobs), len(su.get("items", [])), n, preset))
    results = run_jobs(cfg, jobs, run_name, args.dry)
    if results:
        make_grid(os.path.join(cfg.get("output_root", os.path.join(KIT, "runs")), run_name), results, cols=5)

# ---------------------------------------------------------------- sheet data (img2img + lineart ControlNet)
def build_sheet_graph(cfg, sh, view, positive, negative, seed, steps, cfgv, denoise, cn_strength, cn_end, prefix):
    g = {}
    g["4"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}
    g["40"] = {"class_type": "LoadImage", "inputs": {"image": view["image"]}}
    g["41"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["40", 0], "vae": ["4", 2]}}
    g["50"] = {"class_type": "LoadImage", "inputs": {"image": view["lineart"]}}
    g["51"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": sh["controlnet"]}}
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}}
    g["52"] = {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["6", 0], "negative": ["7", 0], "control_net": ["51", 0], "image": ["50", 0],
                          "strength": float(cn_strength), "start_percent": 0.0, "end_percent": float(cn_end)}}
    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(steps), "cfg": float(cfgv), "sampler_name": "euler",
                         "scheduler": "normal", "denoise": float(denoise), "model": ["4", 0],
                         "positive": ["52", 0], "negative": ["52", 1], "latent_image": ["41", 0]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


def cmd_sheet(args):
    cfg = load_presets()
    sh = cfg.get("sheet")
    if not sh:
        print("[ERROR] presets.yaml has no 'sheet:' section")
        sys.exit(1)
    char = load_char(args.char)
    d = cfg.get("defaults", {})
    artists = [a.strip() for a in (args.artists or "").split(",") if a.strip()] or [""]
    views = [v.strip() for v in (args.views or "front,back").split(",") if v.strip()]
    denoises = [float(x) for x in str(args.denoise or sh.get("denoise", 0.75)).split(",")]
    cn = float(args.cn if args.cn is not None else sh.get("cn_strength", 0.7))
    base_seed = args.seed if args.seed is not None else random.randint(1, 2**31)
    run_name = args.name or time.strftime("sheet_%m%d_%H%M%S")
    tags_full = clean_tags(char.get("tags_full", ""))
    neg = clean_tags(", ".join([d.get("negative", ""), char.get("negative_extra", ""), sh.get("negative_extra", ""), args.neg or ""]))
    jobs = []
    for a in artists:
        for vname in views:
            view = sh["views"].get(vname)
            if not view:
                print("[ERROR] unknown view:", vname)
                sys.exit(1)
            for dn in denoises:
                for i in range(args.n):
                    seed = base_seed + i
                    pos = clean_tags(", ".join([d.get("quality_tags", "") if args.quality != "off" else "",
                                                ("by %s" % a) if a else "", tags_full, view["tags"],
                                                sh.get("extra", ""), args.extra or ""]))
                    label = "%s_%s_d%g_s%d" % ((a or "noartist").replace(" ", "-"), vname, dn, seed)
                    g = build_sheet_graph(cfg, sh, view, pos, neg, seed, args.steps or d.get("steps", 30),
                                          args.cfg or d.get("cfg", 4.5), dn, cn, sh.get("cn_end", 0.8),
                                          "%s/%s/%s" % (sh.get("output_prefix", "v4_sheet_nk"), run_name, label))
                    jobs.append({"label": label, "graph": g, "positive": pos, "negative": neg, "seed": seed,
                                 "settings": {"denoise": dn, "cn_strength": cn, "view": vname, "artist": a,
                                              "cfg": args.cfg or d.get("cfg", 4.5), "steps": args.steps or d.get("steps", 30),
                                              "width": "sheet", "height": "sheet", "loras": []}})
    print("sheet run: %d images (%d artists x %d views x %d denoise x %d seeds)" % (
        len(jobs), len(artists), len(views), len(denoises), args.n))
    run_jobs(cfg, jobs, run_name, args.dry)

def cmd_graph(args):
    """PNG -> ComfyUI API json. Our jobs are sent by code, so the PNG only holds 'prompt' (API graph),
    not 'workflow' (canvas layout). Dropping such a PNG may just load it as an image;
    dropping the .json this writes opens it as nodes (ComfyUI invents the layout)."""
    import glob as _glob
    from PIL import Image
    out_dir = os.path.join(KIT, "workflows")
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            files += sorted(_glob.glob(os.path.join(p, "**", "*.png"), recursive=True))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print("[skip] not found:", p)
    files = [f for f in files if not f.lower().endswith("_grid.png")]
    if not files:
        print("[ERROR] no png found. e.g. .\\nk graph runs\\ep01\\duotest\\d1_cut04")
        return
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for f in files:
        try:
            info = Image.open(f).info
        except Exception as e:
            print("[skip] %s (%s)" % (f, e))
            continue
        if "prompt" not in info:
            print("[skip] no graph inside:", os.path.basename(f))
            continue
        graph = json.loads(info["prompt"])
        parent = os.path.basename(os.path.dirname(os.path.abspath(f)))
        name = "%s__%s.json" % (parent, os.path.splitext(os.path.basename(f))[0])
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(graph, fh, ensure_ascii=False, indent=1)
        kinds = sorted(set(v.get("class_type", "?") for v in graph.values()))
        print("  %s  (%d nodes: %s)" % (name, len(graph), ", ".join(kinds)))
        n += 1
    print("done. %d json -> %s\n(drag a .json onto the ComfyUI canvas to see it as nodes)" % (n, out_dir))


def chars_dir():
    """캐릭터 파일 폴더 (환경 변수 NK_CHARS 가 있으면 그 폴더 = 시험용)"""
    return os.environ.get("NK_CHARS") or os.path.join(KIT, "characters")


# ---------------------------------------------------------------- 안전장치 (전연령 전용)
# 이 프로그램은 전연령(safe) 그림만 만든다. ComfyUI 로 보내는 모든 그래프가 Comfy.queue -> safe_graph 를 지남:
#   긍정 글(text·prompt)에서 성인·잔혹 단어를 지우고, 부정 글에는 SAFE_NEG 를 꼭 넣는다.
#   이 장치를 지우거나 우회해서 쓰는 것은 사용 정책(USE_POLICY.md) 위반이다.
BLOCKED_WORDS = ("nsfw", "explicit", "questionable", "nude", "nudity", "naked", "topless", "bottomless", "nipples?",
                 "areolae?", "genitals?", "penis(?:es)?", "pussy", "vagina", "anus", "sex", "sexy", "sexual\\w*", "cum",
                 "erection", "masturbat\\w*", "fellatio", "porn\\w*", "hentai", "lewd", "ecchi", "lingerie", "bdsm",
                 "bondage", "loli", "shota", "gore", "guro", "dismember\\w*", "decapitat\\w*", "disembowel\\w*")
_BLOCK_RX = re.compile(r"\b(?:%s)\b" % "|".join(BLOCKED_WORDS), re.I)
SAFE_NEG = "nsfw, explicit, nude, sexual, gore"


def safe_text(t):
    """긍정 글에서 막힌 말을 지움 (태그든 문장이든)"""
    if not isinstance(t, str) or not _BLOCK_RX.search(t):
        return t
    t = _BLOCK_RX.sub("", t)
    t = re.sub(r"\s*,(?:\s*,)+", ",", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip(" ,")


def safe_graph(graph):
    """그래프의 글 노드: 부정(negative 로 연결된 것)에는 SAFE_NEG, 나머지(긍정)에서는 막힌 말 지우기"""
    neg_ids = set()
    for n in graph.values():
        if isinstance(n, dict):
            for k, v in (n.get("inputs") or {}).items():
                if k.startswith("negative") and isinstance(v, list) and v:
                    neg_ids.add(str(v[0]))
    for nid, n in graph.items():
        if not isinstance(n, dict):
            continue
        ins = n.get("inputs") or {}
        for k in ("text", "prompt"):
            if not isinstance(ins.get(k), str):
                continue
            if str(nid) in neg_ids:
                if "nsfw" not in ins[k].lower():
                    ins[k] = (SAFE_NEG + ", " + ins[k]) if ins[k].strip() else SAFE_NEG
            else:
                ins[k] = safe_text(ins[k])
    return graph


# ---------------------------------------------------------------- 처음 실행할 때 사용 정책 동의
POLICY_VERSION = "1"
AGREE_FILE = os.path.join(KIT, ".nk_agreed")
POLICY_TEXT = """
==================================================================
 nk 만화 제작기 — 사용 정책 (USE_POLICY.md)
==================================================================
 1. 전연령(safe) 그림만 만든다. NSFW·성인·선정적·잔혹한 그림에 쓰지 않는다.
 2. 불법적인 용도(남의 저작권·초상권·명예 침해, 실존 인물 사칭, 미성년자를
    성적으로 다루는 것, 괴롭힘·사기 등)에 쓰지 않는다.
 3. 상업적으로 쓰지 않는다 (LICENSE: PolyForm Noncommercial 1.0.0).
 4. 이 프로그램은 '있는 그대로' 제공된다. 이 프로그램과 만든 결과물로 생기는
    모든 문제(법적 책임 포함)는 전적으로 사용자 책임이다. 원작자(니코)는
    어떤 책임도 지지 않는다.
 5. 쓰는 모델(그림 모델·LoRA·검수 AI)의 라이선스는 사용자가 따로 지킨다.

 1. All-ages (safe) images only. Never for NSFW, sexual or gory content.
 2. No illegal use (copyright/likeness infringement, impersonation,
    sexualizing minors, harassment, fraud, ...).
 3. No commercial use (PolyForm Noncommercial 1.0.0).
 4. Provided AS IS. You alone are responsible for everything you do with
    this software and its outputs. The author (Niko) accepts no liability.
 5. You must follow the licenses of the models you use.
==================================================================
"""


def ensure_agreed():
    """처음 한 번: 사용 정책을 보여 주고 '동의'(또는 agree)를 받음. 받은 기록 = 키트 폴더 .nk_agreed"""
    try:
        if open(AGREE_FILE, encoding="utf-8").read().split()[0] == POLICY_VERSION:
            return
    except (OSError, IndexError):
        pass
    if os.environ.get("NK_AGREE") == POLICY_VERSION:
        return
    print(POLICY_TEXT)
    if not sys.stdin or not sys.stdin.isatty():
        print("[STOP] 먼저 창에서 nk 를 한 번 실행해 사용 정책에 동의해 주세요 (First run nk once in a terminal and agree).")
        sys.exit(2)
    try:
        ans = input("위 내용에 동의하면 '동의' 또는 'agree' 를 입력하세요 (Type 'agree' to accept): ").strip().lower()
    except EOFError:
        ans = ""
    if ans not in ("동의", "agree"):
        print("동의하지 않으면 쓸 수 없습니다. (Not accepted - exiting.)")
        sys.exit(2)
    with open(AGREE_FILE, "w", encoding="utf-8") as f:
        f.write("%s agreed %s\n" % (POLICY_VERSION, time.strftime("%Y-%m-%d")))


# ---------------------------------------------------------------- argparse
def add_common(p):
    p.add_argument("--char", default="none", help="characters/<name>.yaml  (none = no character)")
    p.add_argument("--preset", help="preset name(s), comma separated")
    p.add_argument("--scene", help="scene name from presets.yaml or raw tags")
    p.add_argument("--extra", help="extra positive tags")
    p.add_argument("--neg", help="extra negative tags")
    p.add_argument("--lora", action="append", help="extra lora file[:strength]  (repeatable)")
    p.add_argument("--strength", type=float, help="character LoRA strength override (default from characters yaml)")
    p.add_argument("--charlora", help="character LoRA file override, e.g. mychar_v1.safetensors")
    p.add_argument("--hires", type=float, help="2nd pass upscale factor, e.g. 1.5 (0/omit = off)")
    p.add_argument("--hires_denoise", type=float, help="2nd pass denoise (default 0.45)")
    p.add_argument("--hires_steps", type=int, help="2nd pass steps (default 20)")
    p.add_argument("--hires_method", choices=["pixel", "model", "latent"], help="how to upscale before the 2nd pass")
    p.add_argument("--steps", type=int)
    p.add_argument("--sampler")
    p.add_argument("--scheduler")
    p.add_argument("--size", help="e.g. 832x1216")
    p.add_argument("--rating", choices=["safe"], help="always safe (all-ages only)")
    p.add_argument("--tags", choices=["short", "full"])
    p.add_argument("--artist_position", choices=["front", "back"])
    p.add_argument("--seed", type=int)
    p.add_argument("--name", help="run folder name")
    p.add_argument("--dry", action="store_true", help="print prompts only")


def main():
    ap = argparse.ArgumentParser(prog="nk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("gen", help="generate N images")
    add_common(g)
    g.add_argument("--n", type=int, default=4)
    g.add_argument("--artist")
    g.add_argument("--artist_weight", type=float)
    g.add_argument("--cfg", type=float)
    g.add_argument("--quality", choices=["on", "off"])
    g.add_argument("--year")
    g.set_defaults(func=cmd_gen)

    st = sub.add_parser("style", help="grid over artists x cfg x quality x year (same seed)")
    add_common(st)
    st.add_argument("--artist", help="comma list of artist tags, e.g. \"artist a,artist b\"")
    st.add_argument("--cfg", help="comma list, e.g. 3.5,4.5")
    st.add_argument("--quality", help="on,off")
    st.add_argument("--year", help="comma list, e.g. 2022,2024")
    st.add_argument("--weight", help="artist weights, e.g. 1.0,1.3")
    st.add_argument("--cols", type=int, default=4)
    st.set_defaults(func=cmd_style)

    q = sub.add_parser("qa", help="detail QA on a run folder via Ollama VLM")
    q.add_argument("--run", help="run name under runs/")
    q.add_argument("--dir", help="any folder of images")
    q.add_argument("--char", default="none")
    q.add_argument("--rating", choices=["safe"], help="always safe (all-ages only)")
    q.add_argument("--cpu", action="store_true", help="run VLM on CPU (while GPU is busy training)")
    q.add_argument("--model", help="override ollama model, e.g. qwen2.5vl:3b")
    q.add_argument("--limit", type=int, help="only first N images")
    q.add_argument("--debug", action="store_true", help="print raw VLM answer")
    q.add_argument("--single", action="store_true", help="one pass only (no face crop second pass)")
    q.set_defaults(func=cmd_qa)

    r = sub.add_parser("run", help="one button: gen -> qa -> best K re-rendered with hires -> final/")
    add_common(r)
    r.add_argument("--n", type=int, default=8)
    r.add_argument("--final", type=int, default=3, help="how many passed images to re-render in high quality")
    r.add_argument("--artist")
    r.add_argument("--artist_weight", type=float)
    r.add_argument("--cfg", type=float)
    r.add_argument("--quality", choices=["on", "off"])
    r.add_argument("--year")
    r.set_defaults(func=cmd_run)

    sh = sub.add_parser("sheet", help="sheet img2img + lineart ControlNet data generation")
    sh.add_argument("--char", required=True, help="characters/<name>.yaml")
    sh.add_argument("--artists", help="comma list of artist tags, e.g. \"artist a,artist b\"")
    sh.add_argument("--views", default="front,back", help="front,back")
    sh.add_argument("--n", type=int, default=1, help="seeds per combination")
    sh.add_argument("--denoise", help="e.g. 0.75 or 0.7,0.8")
    sh.add_argument("--cn", type=float, help="controlnet strength")
    sh.add_argument("--cfg", type=float)
    sh.add_argument("--steps", type=int)
    sh.add_argument("--quality", choices=["on", "off"], default="on")
    sh.add_argument("--extra")
    sh.add_argument("--neg")
    sh.add_argument("--seed", type=int)
    sh.add_argument("--name")
    sh.add_argument("--dry", action="store_true")
    sh.set_defaults(func=cmd_sheet)

    pk = sub.add_parser("pick", help="re-render chosen drafts with hires: nk pick --run NAME --ids 2,5")
    pk.add_argument("--run", required=True)
    pk.add_argument("--ids", required=True, help="draft numbers, e.g. 2,5,7")
    pk.add_argument("--char", default="none")
    pk.add_argument("--hires", type=float)
    pk.add_argument("--hires_denoise", type=float)
    pk.add_argument("--hires_method", choices=["pixel", "model", "latent"])
    pk.add_argument("--tag", default="", help="suffix for output names, e.g. px35")
    pk.add_argument("--dry", action="store_true")
    pk.set_defaults(func=cmd_pick)

    su = sub.add_parser("suite", help="run a scene list: nk suite <name> [--preset mystyle]")
    su.add_argument("suite")
    su.add_argument("--char", default="none")
    su.add_argument("--preset")
    su.add_argument("--n", type=int)
    su.add_argument("--cfg", type=float)
    su.add_argument("--strength", type=float)
    su.add_argument("--extra")
    su.add_argument("--neg")
    su.add_argument("--seed", type=int)
    su.add_argument("--name")
    su.add_argument("--dry", action="store_true")
    su.set_defaults(func=cmd_suite)

    sub.add_parser("board", help="pass rate by artist from all QA runs").set_defaults(func=cmd_board)
    sub.add_parser("list", help="show presets/scenes/characters").set_defaults(func=cmd_list)
    sub.add_parser("free", help="unload models from ComfyUI").set_defaults(func=cmd_free)
    gr = sub.add_parser("graph", help="png -> workflows/*.json to open in ComfyUI: nk graph runs\\ep01\\duotest")
    gr.add_argument("paths", nargs="+", help="png files or folders")
    gr.set_defaults(func=cmd_graph)

    # webtoon episode commands (nk ep ...) live in nk_webtoon.py next to this file
    sys.path.insert(0, KIT)
    import nk_webtoon
    nk_webtoon.add_parser(sub, sys.modules[__name__], KIT)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    ensure_agreed()
    if args.cmd == "ep" and not getattr(args, "ep_cmd", None):
        print(nk_webtoon.__doc__)
        return
    args.func(args)


if __name__ == "__main__":
    main()
