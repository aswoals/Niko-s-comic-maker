# -*- coding: utf-8 -*-
"""캐릭터 LoRA 학습 도우미 (Anima용). 자세한 사용법은 docs/TRAINING.md

kohya sd-scripts 의 anima_train_network.py 를 8GB 그래픽카드에 맞춘 설정으로 돌린다.
    설정 근거 = sd-scripts/docs/anima_train_network.md 예시(networks.lora_anima, AdamW8bit, sigmoid, flow shift 1.0, bf16,
    gradient checkpointing, 캐시) + 8GB 용 blocks_to_swap. 예시 설정 = training/example_anima.yaml

사용: nk ep trainanima training/<설정>.yaml [--bench 30] [--dry] [--stop-comfy]
  - 먼저 ComfyUI 에 /free (모델 내리기) -> 그래픽 메모리를 학습이 씀. ComfyUI 는 다음 그림 때 모델을 다시 올림
  - --stop-comfy: 학습하는 동안 ComfyUI Desktop 을 껐다가 끝나면(실패해도) 다시 켜고 /queue 가 답할 때까지 기다림
  - --bench N: N 걸음만 (속도·메모리 재기), 결과는 training/output/<name>_bench
  - 학습 파이썬의 PID 를 training/train_pid.txt 에 적음. 멈추려면 taskkill /PID <pid> /T /F
  - 끝나면 결과 LoRA 를 ComfyUI models/loras 로 복사

nk ep captions <그림 폴더> [--file 답.txt] [--trigger 이름]
  - AI 채팅이 AI_캡션_만들기.md 대로 써 준 답('=== 01.png' 다음 줄이 캡션)을 그림마다 같은 이름의 .txt 로 나눔"""
import os, re, sys, json, time, subprocess, urllib.request

KOHYA = os.environ.get("NK_KOHYA", r"C:\kohya_ss")      # kohya_ss 설치 폴더 (다르면 환경 변수 NK_KOHYA)
_PYS = [os.path.join(KOHYA, d, "Scripts", "python.exe") for d in ("venv", ".venv")]   # setup.bat = venv, uv 설치 = .venv
PY = next((x for x in _PYS if os.path.exists(x)), _PYS[0])
SD = os.path.join(KOHYA, "sd-scripts")
# ComfyUI 모델 폴더. ComfyUI Desktop 기본 위치가 아니면 환경 변수 NK_COMFY_MODELS 에 models 폴더 경로
MODELS = os.environ.get("NK_COMFY_MODELS") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Comfy-Desktop", "ComfyUI-Shared", "models")


def kohya_problems():
    """학습 전에 kohya 가 제자리에 있나 -> 문제 목록 (빈 목록 = 괜찮음)"""
    out = []
    if not os.path.exists(PY):
        out.append("kohya_ss python not found: %s (install kohya_ss -> docs/TRAINING.md, or set NK_KOHYA)" % PY)
    if not os.path.exists(os.path.join(SD, "anima_train_network.py")):
        out.append("sd-scripts/anima_train_network.py not found in %s (kohya_ss too old? update it)" % SD)
    return out


def _state(kit, name):
    d = os.path.join(kit, "training")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


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
    if c.get("masked_loss"):          # 학습 그림 PNG 의 투명한 곳(알파 0)은 배우지 않음. 데이터 설정에 alpha_mask = true
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
    open(_state(kit, "comfy_exe.txt"), "w", encoding="utf-8").write(exe)
    for pid, _ in roots:
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if not comfy_port_up() and not comfy_desktop_procs():
            break
        time.sleep(2)
    print("ComfyUI stopped (port up: %s)" % comfy_port_up())
    return exe


def comfy_start(exe, wait_s=420):
    """exe 를 학습과 떨어진 프로세스로 켜고 /queue 가 답할 때까지 기다림 -> 포트 또는 None"""
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
    kp = kohya_problems()
    if os.path.isfile(cmd[9]):                 # 데이터 설정 안의 그림 폴더가 실제로 있나 (주석 줄은 빼고)
        txt = open(cmd[9], encoding="utf-8", errors="replace").read()
        for d in re.findall(r"""^\s*image_dir\s*=\s*['"]([^'"]+)['"]""", txt, re.M):
            if not os.path.isdir(d):
                kp.append("image_dir not found: %s (use the full path with / in %s)" % (d, os.path.basename(cmd[9])))
    for x in kp:
        print("[ERROR] " + x)
    if kp and not args.dry:
        sys.exit(1)
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
    open(_state(kit, "train_pid.txt"), "w").write(str(p.pid))
    print("training pid %d (stop: taskkill /PID %d /T /F)" % (p.pid, p.pid))
    try:
        rc = p.wait()
    finally:
        if exe:
            comfy_start(exe)                  # 학습이 실패하거나 멈춰도 ComfyUI 는 다시 켬
    print("training rc %s, %.1f min" % (rc, (time.time() - t0) / 60))
    try:
        os.remove(_state(kit, "train_pid.txt"))
    except Exception:
        pass
    if rc == 0 and not bench_n(args):
        copy_to_comfy(kit, c["output_name"])
    sys.exit(rc)


def bench_n(args):
    return int(args.bench or 0)


def copy_to_comfy(kit, name):
    """학습이 끝나면 에포크별 LoRA를 ComfyUI loras 폴더로 복사 (바로 그려 보고 비교할 수 있게).
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



# ------------------------------------------------------------ 캡션 나누기 (AI_캡션_만들기.md 의 답 -> 그림마다 .txt)
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
_CAP_HEAD = re.compile(r"^={3,}\s*(.+?)\s*=*$")


def parse_captions(text):
    """AI 답 -> {그림 이름(확장자 뺀 것): 캡션}. '=== 01.png' 줄 바로 다음의 글 한 줄이 그 그림의 캡션.
    코드 블록 표시(```)와 그 뒤의 설명 줄은 무시"""
    out, cur = {}, None
    for line in str(text or "").replace("\r", "").split("\n"):
        t = line.strip()
        if not t or t.startswith("```"):
            continue
        m = _CAP_HEAD.match(t)
        if m:
            name = m.group(1).strip().strip("`*").strip()
            cur = os.path.splitext(os.path.basename(name))[0]
            continue
        if cur is not None and cur not in out:
            out[cur] = t.strip("`").strip()
    return out


def with_trigger(cap, trigger):
    """캡션 맨 앞이 트리거가 아니면 붙임 (데이터 설정 keep_tokens = 1 이라 맨 앞 자리가 고정)"""
    if not trigger:
        return cap
    first = cap.split(",")[0].strip().lower()
    return cap if first == trigger.strip().lower() else "%s, %s" % (trigger.strip(), cap)


def run_captions(nk, kit, args):
    folder = args.folder if os.path.isabs(args.folder) else os.path.join(kit, args.folder)
    if not os.path.isdir(folder):
        print("[ERROR] 그림 폴더가 없음: %s" % folder); sys.exit(1)
    if args.file:
        text = open(args.file, encoding="utf-8").read()
    else:
        import nk_easy
        text = nk_easy._clip_get()
        if not text:
            print("[ERROR] 클립보드에서 글을 못 읽었음. AI 답을 파일로 저장해서: nk ep captions %s --file 답.txt" % args.folder); sys.exit(1)
    caps = parse_captions(text)
    if not caps:
        print("[ERROR] 답에서 '=== 01.png' 같은 줄을 못 찾음. AI 답 전체를 복사했는지 확인"); sys.exit(1)
    imgs = {os.path.splitext(f)[0]: f for f in sorted(os.listdir(folder)) if f.lower().endswith(IMG_EXT)}
    made, no_img = 0, []
    for stem, cap in caps.items():
        if stem not in imgs:
            no_img.append(stem); continue
        cap = with_trigger(cap, args.trigger)
        print("  %-20s %s" % (imgs[stem], cap[:110]))
        if not args.dry:
            open(os.path.join(folder, stem + ".txt"), "w", encoding="utf-8").write(cap + "\n")
        made += 1
    no_cap = [imgs[s] for s in imgs if s not in caps and not os.path.exists(os.path.join(folder, s + ".txt"))]
    print("\ncaptions: %d files %s -> %s" % (made, "(dry: not written)" if args.dry else "written", folder))
    if no_img:
        print("[주의] 답에는 있는데 폴더에 그림이 없음: %s" % ", ".join(no_img))
    if no_cap:
        print("[주의] 캡션이 없는 그림: %s" % ", ".join(no_cap))


def add_parser(esub, nk, kit):
    a = esub.add_parser("trainanima", help="train a character LoRA for Anima with kohya sd-scripts (frees ComfyUI VRAM first). guide: docs/TRAINING.md")
    a.add_argument("config", help="training config, e.g. training/example_anima.yaml (copy it and edit)")
    a.add_argument("--bench", help="only N steps (speed / memory check)")
    a.add_argument("--dry", action="store_true")
    a.add_argument("--stop-comfy", dest="stop_comfy", action="store_true",
                   help="stop ComfyUI Desktop during training (3x faster), start it again afterwards and wait for /queue")
    a.set_defaults(func=lambda x: run(nk, kit, x))
    c = esub.add_parser("captions", help="split an AI answer (AI_캡션_만들기.md format: '=== 01.png' line + caption line) into one .txt caption per image")
    c.add_argument("folder", help="training image folder, e.g. training/data/fox")
    c.add_argument("--file", help="read the AI answer from a file instead of the clipboard")
    c.add_argument("--trigger", help="put this word first in every caption if it is missing (e.g. fox)")
    c.add_argument("--dry", action="store_true", help="show only, write nothing")
    c.set_defaults(func=lambda x: run_captions(nk, kit, x))
