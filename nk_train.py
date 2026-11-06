# -*- coding: utf-8 -*-
"""
nk_train.py - LoRA 학습을 nk 명령으로

왜: 학습(kohya)도 nk 명령(`nk ep train <이름>`)으로 감싸서 작업 줄에서 돌릴 수 있게.

설정: training/<이름>.yaml  (예: training/v6.yaml)
  dataset_config: training/dataset_config_v6.toml
  epochs: 10
  dim: 16
  alpha: 16
  lr: 1.0e-4
학습 전에 하는 일: ComfyUI 모델 내리기(/free) + 검수 AI(Ollama) 모델 내리기 + 그래픽카드 빈 메모리 기록
학습 후: 결과 LoRA를 ComfyUI loras 폴더로 복사 (nk에서 바로 시험할 수 있게)
v5 학습 기록(train_lora_v5.bat)과 같은 설정 — 바꾸는 건 데이터(뒷모습 추가)뿐 (한 번에 한 가지만)"""
import os, sys, json, time, shutil, subprocess, urllib.request

KOHYA = os.environ.get("NK_KOHYA", r"C:\kohya_ss")      # kohya_ss 설치 폴더 (다르면 환경 변수 NK_KOHYA)
LORA_DIR = os.path.join((os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")),
                        "Comfy-Desktop", "ComfyUI-Shared", "models", "loras")
MODEL = os.path.join((os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")),
                     "Comfy-Desktop", "ComfyUI-Shared", "models", "checkpoints", "noobaiXLNAIXL_vPred10Version.safetensors")


def _post(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def _vram(nk, cfg):
    try:
        c = nk.Comfy(cfg.get("server", "auto"))
        st = c._get("/system_stats")
        d = st["devices"][0]
        return d["vram_free"] / 1e9, d["vram_total"] / 1e9
    except Exception as e:
        print("[WARN] could not read VRAM from ComfyUI:", e)
        return None, None


def train_args(kit, t):
    out = os.path.join(kit, "training", "output")
    return [
        "sdxl_train_network.py",
        "--pretrained_model_name_or_path", MODEL,
        "--v_parameterization", "--zero_terminal_snr",
        "--fp8_base",
        "--dataset_config", os.path.join(kit, t["dataset_config"]),
        "--output_dir", out, "--output_name", t["output_name"],
        "--save_model_as", "safetensors", "--save_precision", "fp16", "--save_every_n_epochs", "1",
        "--network_module", "networks.lora", "--network_dim", str(t.get("dim", 16)), "--network_alpha", str(t.get("alpha", 16)),
        "--network_train_unet_only",
        "--learning_rate", str(t.get("lr", 1e-4)), "--lr_scheduler", "cosine", "--lr_warmup_steps", "50",
        "--optimizer_type", "AdamW8bit",
        "--max_train_epochs", str(t.get("epochs", 10)), "--train_batch_size", "1",
        "--mixed_precision", "bf16", "--sdpa",
        "--gradient_checkpointing",
        "--cache_latents", "--cache_latents_to_disk",
        "--cache_text_encoder_outputs", "--cache_text_encoder_outputs_to_disk",
        "--max_data_loader_n_workers", "1",
        "--min_snr_gamma", "5",
        "--logging_dir", os.path.join(kit, "training", "logs"),
    ]


def run(nk, kit, args):
    cfg = nk.load_presets()
    p = os.path.join(kit, "training", args.name + ".yaml")
    if not os.path.exists(p):
        print("[ERROR] no training config:", p); sys.exit(1)
    t = nk.load_yaml(p)
    for k in ("output_name", "dataset_config"):
        if not t.get(k):
            print("[ERROR] %s missing in %s" % (k, p)); sys.exit(1)
    if os.path.exists(os.path.join(LORA_DIR, t["output_name"] + ".safetensors")) and not args.dry:
        print("[ERROR] %s already exists in loras - pick a new output_name (old versions are never overwritten)" % t["output_name"])
        sys.exit(1)
    py = sys.executable
    cmd = [py] + train_args(kit, t)
    print("train:", t["output_name"], "| config", p)
    print("cmd:", " ".join(cmd[:3]), "...", "(%d args)" % len(cmd))
    if args.dry:
        print("\n".join(cmd)); return
    # 1) 그래픽카드 비우기: ComfyUI 모델 + Ollama 검수 AI
    try:
        nk.Comfy(cfg.get("server", "auto")).free(); print("ComfyUI models unloaded")
    except Exception as e:
        print("[WARN] ComfyUI free failed:", e)
    q = cfg.get("qa", {})
    try:
        _post(q.get("ollama", "http://127.0.0.1:11434").rstrip("/") + "/api/generate", {"model": q.get("model"), "keep_alive": 0})
        print("Ollama model unloaded:", q.get("model"))
    except Exception as e:
        print("[WARN] Ollama unload failed (maybe not loaded):", e)
    time.sleep(8)
    free, total = _vram(nk, cfg)
    if free is not None:
        print("VRAM free %.1f / %.1f GB before training" % (free, total))
    # 2) 학습
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=os.path.join(KOHYA, "sd-scripts"))
    print("training finished rc=%s in %.0f min" % (rc, (time.time() - t0) / 60))
    if rc != 0:
        sys.exit(rc)
    # 3) 결과를 ComfyUI loras로 복사 (에폭별 포함)
    out = os.path.join(kit, "training", "output")
    n = 0
    for f in sorted(os.listdir(out)):
        if f.startswith(t["output_name"]) and f.endswith(".safetensors"):
            dst = os.path.join(LORA_DIR, f)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(out, f), dst); n += 1
    print("copied %d LoRA files to %s" % (n, LORA_DIR))
