# -*- coding: utf-8 -*-
"""T4b

왜: 두 명 닿는 컷은 두 캐릭터를 다 아는 모델이 한 장에 한 번에 그려야 됨 (Anima 4/4·5/5)
도구 = kohya sd-scripts anima_train_network.py.
    설정 근거 = sd-scripts/docs/anima_train_network.md 예시(networks.lora_anima, AdamW8bit, sigmoid, flow shift 1.0, bf16,
    gradient checkpointing, 캐시) + 8GB 용 blocks_to_swap. 데이터 = NoobAI v7 과 같은 폴더·캡션 (training/dataset_config_anima_v1.toml).

사용: nk ep trainanima training/anima_v1.yaml [--bench 30] [--dry]
  - 먼저 ComfyUI에 /free (모델 내리기) -> GPU를 학습이 씀. 학습이 끝나면 ComfyUI는 다음 그림 때 모델을 다시 올림
  - --bench N: N 걸음만 (속도·메모리 재기), 결과는 training/output/<name>_bench
  - 학습 파이썬의 PID 를 _remote/train_pid.txt 에 적음 (우체통 KILL 은 nk 만 끄므로, 멈추려면 taskkill /PID <pid> /T /F)
    -> 학습이 끝나면(실패해도) 같은 exe 로 다시 켜고 /queue 가 답할 때까지 기다림. exe 경로는 _remote/comfy_exe.txt 에도 남김"""
import os, sys, json, time, subprocess, urllib.request

KOHYA = os.environ.get("NK_KOHYA", r"C:\kohya_ss")      # kohya_ss 설치 폴더 (다르면 환경 변수 NK_KOHYA)
PY = os.path.join(KOHYA, "venv", "Scripts", "python.exe")
SD = os.path.join(KOHYA, "sd-scripts")
MODELS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Comfy-Desktop", "ComfyUI-Shared", "models")


def comfy_free(cfg):
    for port in (8188, 8000, 8189, 8190, 8191):
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/free" % port, data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
            print("ComfyUI :%d -> /free (models unloaded)" % port)
            return port
        except Exception:
            continue
    print("[note] ComfyUI not found for /free")
    return None


def gpu_used_mb():
    try:
        out = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], text=True)
        u, t = [int(x) for x in out.strip().splitlines()[0].split(",")]
        return u, t
    except Exception:
        return None, None


def build_cmd(kit, c, bench=0):
    name = c["output_name"] + ("_bench" if bench else "")
    cmd = [PY, "anima_train_network.py",
           "--pretrained_model_name_or_path", os.path.join(MODELS, "diffusion_models", c.get("dit", "anima-base-v1.0.safetensors")),
           "--qwen3", os.path.join(MODELS, "text_encoders", c.get("qwen3", "qwen_3_06b_base.safetensors")),
           "--vae", os.path.join(MODELS, "vae", c.get("vae", "qwen_image_vae.safetensors")),
           "--dataset_config", os.path.join(kit, c["dataset_config"]),
           "--output_dir", os.path.join(kit, "training", "output"), "--output_name", name,
           "--save_model_as", "safetensors", "--save_precision", "bf16",
           "--network_module", "networks.lora_anima", "--network_train_unet_only", "--network_dim", str(c.get("dim", 16)), "--network_alpha", str(c.get("alpha", 1.0)),
           "--learning_rate", str(c.get("lr", 1e-4)), "--optimizer_type", c.get("optimizer", "AdamW8bit"),
           "--lr_scheduler", c.get("scheduler", "constant"),
           "--timestep_sampling", c.get("timestep_sampling", "sigmoid"), "--discrete_flow_shift", str(c.get("flow_shift", 1.0)),
           "--mixed_precision", "bf16", "--gradient_checkpointing", "--sdpa",
           "--cache_latents", "--cache_latents_to_disk", "--cache_text_encoder_outputs", "--cache_text_encoder_outputs_to_disk",
           "--qwen_image_vae_2d", "--max_data_loader_n_workers", "1", "--train_batch_size", "1",
           "--logging_dir", os.path.join(kit, "training", "logs"), "--seed", str(c.get("seed", 42))]
    if c.get("blocks_to_swap"):
        cmd += ["--blocks_to_swap", str(c["blocks_to_swap"])]
    if c.get("network_weights"):
        nw = c["network_weights"]
        cmd += ["--network_weights", nw if os.path.isabs(nw) else os.path.join(kit, nw)]
    if c.get("masked_loss"):          # T6 v2: 학습 그림 PNG 알파 0 인 곳(가린 가슴·뒤통수 등)은 배우지 않음. 데이터 설정에 alpha_mask = true
        cmd += ["--masked_loss"]
    if bench:
        cmd += ["--max_train_steps", str(bench)]
    else:
        cmd += ["--max_train_epochs", str(c.get("epochs", 10)), "--save_every_n_epochs", str(c.get("save_every", 1))]
    return cmd


COMFY_EXE_NAME = "Comfy Desktop.exe"
COMFY_PORTS = (8188, 8000, 8189, 8190, 8191)


def comfy_desktop_procs():
    """-> [(pid, 부모 pid, exe 경로)]"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | Select-Object ProcessId,ParentProcessId,ExecutablePath | ConvertTo-Json -Compress"
          % COMFY_EXE_NAME)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60).stdout.strip()
    if not out:
        return []
    rows = json.loads(out)
    rows = rows if isinstance(rows, list) else [rows]
    return [(int(r["ProcessId"]), int(r["ParentProcessId"] or 0), r.get("ExecutablePath") or "") for r in rows]


def comfy_roots(procs):
    pids = {p for p, _, _ in procs}
    return [(p, exe) for p, pp, exe in procs if pp not in pids]


def comfy_port_up(ports=COMFY_PORTS):
    for port in ports:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/queue" % port, timeout=3).read()
            return port
        except Exception:
            continue
    return None


def comfy_stop(kit, dry=False):
    """-> 다시 켤 exe 경로 (없으면 None). dry 면 찾기만"""
    roots = comfy_roots(comfy_desktop_procs())
    if not roots:
        print("[note] Comfy Desktop not running - nothing to stop")
        return None
    exe = roots[0][1]
    print("ComfyUI Desktop: %s (pid %s)%s" % (exe, ", ".join(str(p) for p, _ in roots), " [dry: not stopped]" if dry else ""))
    if dry:
        return exe
    open(os.path.join(kit, "_remote", "comfy_exe.txt"), "w", encoding="utf-8").write(exe)
    for pid, _ in roots:
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if not comfy_port_up() and not comfy_desktop_procs():
            break
        time.sleep(2)
    print("ComfyUI stopped (port up: %s)" % comfy_port_up())
    return exe


def comfy_start(exe, wait_s=420):
    """exe 를 우체통·학습과 떨어진 프로세스로 켜고 /queue 가 답할 때까지 기다림 -> 포트 또는 None"""
    if not exe or not os.path.exists(exe):
        print("[WARN] ComfyUI exe not found (%s) - start ComfyUI yourself" % exe); return None
    fl = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe), creationflags=fl | 0x01000000, close_fds=True)   # + CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen([exe], cwd=os.path.dirname(exe), creationflags=fl, close_fds=True)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        port = comfy_port_up()
        if port:
            print("ComfyUI back on :%d (%.0f s)" % (port, time.time() - t0)); return port
        time.sleep(5)
    print("[WARN] ComfyUI did not answer in %d s - check the ComfyUI window (start it again if needed)" % wait_s)
    return None


def run(nk, kit, args):
    import yaml
    c = yaml.safe_load(open(os.path.join(kit, args.config), encoding="utf-8"))
    cmd = build_cmd(kit, c, int(args.bench or 0))
    print("train anima: %s%s" % (c["output_name"], " (bench %s steps)" % args.bench if args.bench else ""))
    print(" ".join('"%s"' % x if " " in x else x for x in cmd))
    for p in (cmd[3], cmd[5], cmd[7], cmd[9]):
        if not os.path.exists(p):
            print("[ERROR] missing: %s" % p); sys.exit(1)
    stop = getattr(args, "stop_comfy", False)
    if args.dry:
        if stop:
            comfy_stop(kit, dry=True)
        return
    cfg = nk.load_presets()
    exe = comfy_stop(kit) if stop else None
    if not stop:
        comfy_free(cfg)
    time.sleep(5)
    u, t = gpu_used_mb()
    print("GPU memory used before training: %s / %s MB" % (u, t))
    t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.Popen(cmd, cwd=SD, stdin=subprocess.DEVNULL, env=env)
    open(os.path.join(kit, "_remote", "train_pid.txt"), "w").write(str(p.pid))
    print("training pid %d (stop: taskkill /PID %d /T /F)" % (p.pid, p.pid))
    try:
        rc = p.wait()
    finally:
        if exe:
            comfy_start(exe)                  # 학습이 실패하거나 멈춰도 ComfyUI 는 다시 켬
    print("training rc %s, %.1f min" % (rc, (time.time() - t0) / 60))
    try:
        os.remove(os.path.join(kit, "_remote", "train_pid.txt"))
    except Exception:
        pass
    if rc == 0 and not bench_n(args):
        copy_to_comfy(kit, c["output_name"])
    sys.exit(rc)


def bench_n(args):
    return int(args.bench or 0)


def copy_to_comfy(kit, name):
    """학습이 끝나면 에포크별 LoRA를 ComfyUI loras 폴더로 복사 — 다음 우체통 비교 작업이 바로 씀 (예전엔 손으로 복사).
    이미 같은 크기의 파일이 있으면 건너뜀. 이름: <name>.safetensors, <name>-00000N.safetensors (kohya 규칙)"""
    import glob, shutil
    dst = os.path.join(MODELS, "loras")
    n = 0
    for f in sorted(glob.glob(os.path.join(kit, "training", "output", name + "*.safetensors"))):
        b = os.path.basename(f)
        if b != name + ".safetensors" and not b.startswith(name + "-"):
            continue                                                  # 다른 이름(예: _bench) 은 복사 안 함
        t = os.path.join(dst, b)
        if os.path.exists(t) and os.path.getsize(t) == os.path.getsize(f):
            continue
        shutil.copy2(f, t)
        n += 1
        print("copied to ComfyUI loras: %s" % b)
    print("LoRA copy: %d files -> %s" % (n, dst))


def add_parser(esub, nk, kit):
    a = esub.add_parser("trainanima", help="TEST: train a character LoRA for Anima with kohya sd-scripts (frees ComfyUI VRAM first)")
    a.add_argument("config", help="training/anima_v1.yaml")
    a.add_argument("--bench", help="only N steps (speed / memory check)")
    a.add_argument("--dry", action="store_true")
    a.add_argument("--stop-comfy", dest="stop_comfy", action="store_true",
                   help="stop ComfyUI Desktop during training (3x faster), start it again afterwards and wait for /queue")
    a.set_defaults(func=lambda x: run(nk, kit, x))
