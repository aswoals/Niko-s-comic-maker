# -*- coding: utf-8 -*-
"""
nk_fetch.py

왜: 큰 모델(수 GB)을 Hugging Face에서 안전하게 받기 (nk ep fetch).
안전: huggingface.co 주소만 / 받기 전에 남은 디스크 확인 / 이어받기(.part) / 끝나면 SHA256 확인 후에만 진짜 이름으로 바꿈
    이미 같은 이름 파일이 있으면 받지 않음

사용: nk ep fetch <url> <폴더> --size <바이트> --sha256 <해시>
     폴더 = ComfyUI-Shared/models 아래 이름 (diffusion_models, loras, text_encoders ...)"""
import os, sys, time, shutil, hashlib, urllib.request, urllib.parse

MODELS = os.path.join((os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")), "Comfy-Desktop", "ComfyUI-Shared", "models")
MARGIN = 3 * 1024 ** 3


def run(nk, kit, args):
    u = urllib.parse.urlparse(args.url)
    if u.scheme != "https" or u.hostname != "huggingface.co":
        print("[ERROR] only https://huggingface.co/... URLs are allowed"); sys.exit(1)
    sub = args.folder.strip("\\/")
    if ".." in sub or not sub.replace("_", "").isalnum():
        print("[ERROR] bad folder name:", args.folder); sys.exit(1)
    dest_dir = os.path.join(MODELS, sub)
    os.makedirs(dest_dir, exist_ok=True)
    name = args.name or os.path.basename(u.path)
    dest = os.path.join(dest_dir, name)
    part = dest + ".part"
    if os.path.exists(dest):
        print("already there:", dest, os.path.getsize(dest)); return
    size = int(args.size)
    have = os.path.getsize(part) if os.path.exists(part) else 0
    free = shutil.disk_usage(dest_dir).free
    print("target %s (%.2f GB) | already %.2f GB | disk free %.1f GB" % (dest, size / 1e9, have / 1e9, free / 1e9))
    if free < (size - have) + MARGIN:
        print("[ERROR] not enough disk space (need %.1f GB incl. 3 GB margin)" % (((size - have) + MARGIN) / 1e9)); sys.exit(1)
    t0 = time.time(); last = 0; tries = 0
    while have < size:
        req = urllib.request.Request(args.url, headers={"Range": "bytes=%d-" % have, "User-Agent": "nk-fetch/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab") as f:
                if have and r.status != 206:
                    print("[WARN] server ignored resume -> starting over"); f.truncate(0); have = 0
                while True:
                    b = r.read(8 * 1024 * 1024)
                    if not b:
                        break
                    f.write(b); have += len(b)
                    if time.time() - last > 30:
                        el = time.time() - t0
                        print("   %.2f / %.2f GB  (%.1f MB/s)" % (have / 1e9, size / 1e9, have / 1e6 / max(el, 1)), flush=True)
                        last = time.time()
        except Exception as e:
            tries += 1
            print("[WARN] download error (%s) - retry %d" % (e, tries), flush=True)
            if tries > 20:
                print("[ERROR] too many errors"); sys.exit(1)
            time.sleep(10)
            have = os.path.getsize(part)
    if have != size:
        print("[ERROR] size mismatch %d != %d" % (have, size)); sys.exit(1)
    if args.sha256:
        print("checking SHA256 ...", flush=True)
        h = hashlib.sha256()
        with open(part, "rb") as f:
            while True:
                b = f.read(16 * 1024 * 1024)
                if not b:
                    break
                h.update(b)
        if h.hexdigest() != args.sha256.lower():
            print("[ERROR] SHA256 mismatch: %s" % h.hexdigest()); sys.exit(1)
        print("SHA256 OK")
    os.replace(part, dest)
    print("done:", dest, "in %.0f min" % ((time.time() - t0) / 60))
