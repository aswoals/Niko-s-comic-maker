# -*- coding: utf-8 -*-
"""
python tools\\pose3d\\run.py <명령>

  list                         자세 틀 목록
  check                        settings.yaml 을 읽어 체형 숫자만 보여 줌 (설정 오타 확인용)
  render --pose NAME [--yaw 20 --pitch 6 --dist 3 --fov 35 --size 512x640 --swap --spans 0.5-1.0,0.0-0.5 --name cut09 --out 폴더]
         → 폴더에 depth.png / label.png / mask_a.png / mask_b.png / openpose.png(조종용: 상대에 가린 점·뒤통수에 가린 얼굴 점 뺌) /
           openpose_all.png(전부) / openpose_check.png(가려진 점 속 빈 동그라미) / lineart.png / sheet.png / kp.json / scene.json
           + 사람마다 혼자: depth_a·b.png(혼자 깊이) / openpose_a·b.png(혼자 층용 뼈대: 뒤통수에 가린 얼굴 점만 뺌) / behind_a·b.png(상대에 가린 곳)
           + --name 을 주면 <name>.png·<name>_kp.json (nk poses 폴더 모양, --spans 로 콘티 칸과 맞춤)
  examples --out 폴더 [--panel 256]
         → 5개 자세 × 카메라 2개 = 10장의 한눈에 보기 (네 그림 나란히)

에러가 나면
  - "No module named numpy/PIL": nk 파이썬으로 돌렸는지 확인.
  - "No module named tools": 키트 폴더(nk.bat 있는 곳)에서 돌려야 함.
  - 그림이 비었으면: --dist 를 빼서(자동 거리) 다시 돌려 봄."""
import argparse
import json
import os
import sys
import time

import numpy as np

from . import render as R
from .body import load_settings
from .poses import EXAMPLE_CAMERAS, EXAMPLE_POSES, KOREAN, POSES, contact_report, make


def _size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def build(pose, settings, yaw, pitch, dist, fov, width, height, swap=False, spans=None):
    """자세 + 카메라 → 네 가지 그림과 기록 (dict). 사람마다 혼자 그림(깊이·뼈대)과 '상대에 가린 곳' 틀도 만듦 (누끼 레이어용)"""
    dolls, contacts = make(pose, settings, swap)
    cam = R.auto_camera(dolls, yaw, pitch, fov, width, height, dist=dist, margin=settings["camera"].get("margin", 1.12))
    rr = R.render(dolls, cam)
    kps = R.keypoints_2d(dolls, cam, rr["parts"])
    img = settings["image"]
    colors = [tuple(c) for c in img["person_colors"]]
    out = {
        "depth": R.depth_image(rr, img.get("depth_far", 40)),
        "label": R.label_image(rr, colors),
        "masks": R.person_masks(rr, len(dolls)),
        "openpose": R.openpose_image(width, height, kps, "control"),
        "openpose_all": R.openpose_image(width, height, kps, "all"),
        "openpose_check": R.openpose_image(width, height, kps, "check"),
        "lineart": R.line_image(rr, img.get("line_px", 2)),
        "kp": R.kp_json(kps, width, height, spans),
        "contacts": contact_report(dolls, contacts),
        "reach": [dict(d.reach_err) for d in dolls],
        "cam": cam, "dolls": dolls, "render": rr, "kps": kps,
    }
    # 사람마다 혼자: 깊이(두 사람 그림과 같은 밝기 범위), 뼈대(자기 몸에 가린 점만 뺌), 상대에 가린 곳
    solos = [R.render([d], cam) for d in dolls]
    zr = (R.depth_range(rr)[0], max(R.depth_range(x)[1] for x in solos))    # 가려진 뒷부분까지 들어가는 범위
    for i, solo in enumerate(solos):
        tag = "ab"[i]
        out["depth_" + tag] = R.depth_image(solo, img.get("depth_far", 40), zr)
        out["openpose_" + tag] = R.openpose_image(width, height, kps, "solo", only=i)
        out["behind_" + tag] = np.where((solo["who"] == 0) & (rr["who"] != i), 255, 0).astype(np.uint8)
    return out


def sheet(res, title, panel=256):
    """네 그림 나란히 (깊이 | 사람별 틀 | OpenPose 확인용 | 선화) + 위에 제목 줄"""
    from PIL import Image, ImageDraw
    names = ["depth", "label", "openpose_check", "lineart"]
    ims = [Image.fromarray(res[n]) for n in names]
    w0, h0 = ims[0].size
    ph = int(round(panel * h0 / w0))
    bar = 18
    S = Image.new("RGB", (panel * 4 + 3 * 4, ph + bar), (40, 40, 40))
    dr = ImageDraw.Draw(S)
    dr.text((4, 3), title, fill=(230, 230, 230))
    labels = ["depth", "person masks (a red / b blue)", "openpose (hollow = hidden)", "lineart"]
    for k, im in enumerate(ims):
        x = k * (panel + 4)
        S.paste(im.resize((panel, ph), Image.LANCZOS if k == 0 else Image.NEAREST if k == 1 else Image.BILINEAR), (x, bar))
        dr.text((x + 3, bar + 2), labels[k], fill=(255, 255, 255))
    return S


def save_all(res, out_dir, title, panel=256, name=None):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    for n in ("depth", "label", "openpose", "openpose_all", "openpose_check", "lineart",
              "depth_a", "depth_b", "openpose_a", "openpose_b", "behind_a", "behind_b"):
        if n in res:
            Image.fromarray(res[n]).save(os.path.join(out_dir, n + ".png"))
    for i, m in enumerate(res["masks"]):
        Image.fromarray(m).save(os.path.join(out_dir, "mask_%s.png" % "ab"[i]))
    with open(os.path.join(out_dir, "kp.json"), "w", encoding="utf-8") as f:
        json.dump(res["kp"], f, ensure_ascii=False)
    cam = res["cam"]
    scene = {"camera": {"yaw": cam.yaw, "pitch": cam.pitch, "dist": cam.dist, "fov": cam.fov, "W": cam.W, "H": cam.H,
                        "pos": cam.pos.tolist(), "target": cam.target.tolist()},
             "contacts": [{"what": d, "dist": round(x, 4), "tol": t, "ok": bool(ok)} for d, x, t, ok in res["contacts"]],
             "reach_err": res["reach"],
             "joints": [{k: [round(float(v), 4) for v in p] for k, p in d.pos.items()} for d in res["dolls"]]}
    with open(os.path.join(out_dir, "scene.json"), "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=1)
    sheet(res, title, panel).save(os.path.join(out_dir, "sheet.png"))
    if name:        # nk 뼈대 파일 모양으로도 저장: <name>.png(두 사람 뼈대, 가려진 점 뺌) + <name>_kp.json
        Image.fromarray(res["openpose"]).save(os.path.join(out_dir, name + ".png"))
        with open(os.path.join(out_dir, name + "_kp.json"), "w", encoding="utf-8") as f:
            json.dump(res["kp"], f, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tools/pose3d/run.py")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("--settings")
    r = sub.add_parser("render")
    r.add_argument("--pose", required=True, choices=sorted(POSES))
    r.add_argument("--yaw", type=float)
    r.add_argument("--pitch", type=float)
    r.add_argument("--dist", type=float)
    r.add_argument("--fov", type=float)
    r.add_argument("--size", default=None, help="가로x세로, 예: 832x1216")
    r.add_argument("--swap", action="store_true", help="a·b 역할 바꾸기 (예: 업는 사람을 b로)")
    r.add_argument("--settings")
    r.add_argument("--out", default=os.path.join("runs", "pose3d", "render"))
    r.add_argument("--spans", help="사람별 가로 칸 (콘티 cast 와 맞추기), 예: 0.5-1.0,0.0-0.5 (a 먼저)")
    r.add_argument("--name", help="nk 뼈대 파일 이름으로도 저장, 예: cut09 → cut09.png + cut09_kp.json")
    e = sub.add_parser("examples")
    e.add_argument("--out", required=True)
    e.add_argument("--size", default="384x480")
    e.add_argument("--panel", type=int, default=224)
    e.add_argument("--settings")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for k in POSES:
            print("%-13s %s   카메라 예: %s" % (k, KOREAN[k], EXAMPLE_CAMERAS[k]))
        return 0
    if args.cmd == "check":
        s = load_settings(args.settings)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "render":
        s = load_settings(args.settings)
        cs, ims = s["camera"], s["image"]
        W, H = _size(args.size) if args.size else (int(ims["width"]), int(ims["height"]))
        yaw = cs["yaw"] if args.yaw is None else args.yaw
        pitch = cs["pitch"] if args.pitch is None else args.pitch
        dist = cs.get("dist") if args.dist is None else args.dist
        fov = cs["fov"] if args.fov is None else args.fov
        t0 = time.time()
        spans = [[float(v) for v in x.split("-")] for x in args.spans.split(",")] if args.spans else None
        res = build(args.pose, s, yaw, pitch, dist, fov, W, H, args.swap, spans)
        title = "%s  yaw %g pitch %g  %dx%d" % (args.pose, yaw, pitch, W, H)
        save_all(res, args.out, title, name=args.name)
        print("[OK] %s -> %s (%.1fs)" % (args.pose, args.out, time.time() - t0))
        for d, x, t, ok in res["contacts"]:
            print("  닿는 곳 %-24s %.3f (허용 %.3f) %s" % (d, x, t, "OK" if ok else "멂"))
        return 0
    if args.cmd == "examples":
        from PIL import Image
        s = load_settings(args.settings)
        W, H = _size(args.size)
        os.makedirs(args.out, exist_ok=True)
        t0 = time.time()
        n = 0
        for pose in EXAMPLE_POSES:
            for cname, yaw, pitch in EXAMPLE_CAMERAS[pose]:
                res = build(pose, s, yaw, pitch, None, s["camera"]["fov"], W, H)
                title = "%s / cam %s (yaw %g, pitch %g)" % (pose, cname, yaw, pitch)
                im = sheet(res, title, args.panel)
                p = os.path.join(args.out, "%s_%s.png" % (pose, cname))
                im.quantize(colors=96, method=Image.MEDIANCUT).save(p, optimize=True)
                n += 1
                bad = [d for d, x, t, ok in res["contacts"] if not ok]
                print("[OK] %s%s" % (p, ("  닿는 곳 멂: " + ", ".join(bad)) if bad else ""))
        print("%d장, %.1fs" % (n, time.time() - t0))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
