# -*- coding: utf-8 -*-
"""
tools/pose3d/library_sheet.py - 자세 도서관 미리보기

  이름을 안 주면 도서관 자세 전부. 자세마다 <out>/<이름>.png = 정면 / 옆 / 위에서 (깊이 그림 + 인형 선화),
  모두 모은 <out>/sheet.png, 그리고 글로 점검 결과 (발이 땅 밑, 팔다리가 목표에 못 닿음, 닿아야 할 곳이 멂, 두 사람이 겹침).
  자동 만화와 같은 사람 체형(여자 체형, 두 번째 사람은 키 0.92)·같은 팔 규칙(arms=False 면 팔을 뺌)으로 그림."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, KIT)

from pose3d import library_human as LH  # noqa: E402
from pose3d.body import load_settings  # noqa: E402
from pose3d.__main__ import build  # noqa: E402

VIEWS = [("front", 15, 6), ("side", 70, 8), ("high", 25, 50)]
FLOOR_TOL = 0.02          # 관절이 땅(y 0) 밑으로 이만큼 넘게 들어가면 경고
REACH_TOL = 0.03          # IK 가 목표에 이만큼 넘게 못 닿으면 경고
OVERLAP_TOL = 0.6         # 두 사람 몸통 중심 거리 < (몸통 두께 합 x 이 값) 이면 겹침 경고


def settings_for(name, s=None):
    import nk_pose3d_auto as A
    s = s or load_settings(os.path.join(HERE, "settings_human.yaml"))
    keep = LH.arms_kept(name)
    sh = dict(A.SHAPES["female"], no_arms=not keep, upper_arms_only=False)
    s = dict(s)
    s["body"] = dict(s["body"])
    s["camera"] = dict(s["camera"], margin=1.0)
    s["people"] = {"a": {"scale": 1.0, "shape": dict(sh)}, "b": {"scale": 0.92, "shape": dict(sh)}}
    return s


def pose_key(name):
    return ("s_" if LH.LIB[name]["n"] == 1 else "L_") + name


def check(name, res):
    """글로 된 점검: [(무엇, 값)]"""
    out = []
    for i, d in enumerate(res["dolls"]):
        low = min(float(p[1]) for j, p in d.pos.items() if not j.startswith("tail"))
        if low < -FLOOR_TOL:
            out.append(("사람 %s 관절이 땅 밑" % "ab"[i], round(low, 3)))
        for limb, err in res["reach"][i].items():
            if err > REACH_TOL:
                out.append(("사람 %s %s 목표에 못 닿음" % ("ab"[i], limb), round(err, 3)))
    for desc, dist, tol, ok in res["contacts"]:
        if not ok:
            out.append(("닿는 곳 멂: " + desc, round(dist, 3)))
    if len(res["dolls"]) == 2:
        a, b = res["dolls"]
        ca, cb = (a.pos["pelvis"] + a.pos["chest"]) / 2, (b.pos["pelvis"] + b.pos["chest"]) / 2
        lim = (a.b["torso_rz"] + b.b["torso_rz"]) * OVERLAP_TOL
        if float(np.linalg.norm(ca - cb)) < lim:
            out.append(("두 사람 몸통이 겹침", round(float(np.linalg.norm(ca - cb)), 3)))
    return out


def _font(size=14):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", size)
    except Exception:
        return ImageFont.load_default()


def render_one(name, out_dir, W=240, H=300):
    from PIL import Image, ImageDraw
    s = settings_for(name)
    tiles, problems = [], None
    for vname, yaw, pitch in VIEWS:
        res = build(pose_key(name), s, yaw, pitch, None, 35, W, H)
        if problems is None:
            problems = check(name, res)
        dep = Image.fromarray(res["depth"]).convert("RGB")
        ln = Image.fromarray(res["lineart"]).convert("RGB")
        t = Image.new("RGB", (W * 2, H + 18), "white")
        t.paste(dep, (0, 18)); t.paste(ln, (W, 18))
        ImageDraw.Draw(t).text((4, 3), vname, fill=(0, 0, 0))
        tiles.append(t)
    row = Image.new("RGB", (sum(t.width for t in tiles), tiles[0].height + 22), "white")
    x = 0
    for t in tiles:
        row.paste(t, (x, 22)); x += t.width
    e = LH.LIB[name]
    label = "%s  (%s)  tags: %s  arms: %s  %s" % (name, "혼자" if e["n"] == 1 else "둘", ", ".join(e["tags"]), e["arms"],
                                                  ("!! " + "; ".join("%s %s" % p for p in problems)) if problems else "OK")
    ImageDraw.Draw(row).text((4, 3), label, fill=(180, 0, 0) if problems else (0, 90, 0), font=_font())
    os.makedirs(out_dir, exist_ok=True)
    row.save(os.path.join(out_dir, name + ".png"))
    return row, problems


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = os.path.join(KIT, "runs", "pose3d", "library")
    if "--out" in argv:
        i = argv.index("--out"); out = argv[i + 1]; del argv[i:i + 2]
    names = argv or list(LH.LIB)
    unknown = [n for n in names if n not in LH.LIB]
    if unknown:
        print("모르는 자세:", unknown); return 2
    LH.install()
    rows, bad = [], 0
    for n in names:
        row, probs = render_one(n, out)
        rows.append(row)
        print("%-22s %s" % (n, "OK" if not probs else "!! " + "; ".join("%s %s" % p for p in probs)))
        bad += bool(probs)
    if len(rows) > 1:
        from PIL import Image
        W = max(r.width for r in rows)
        sheet = Image.new("RGB", (W, sum(r.height for r in rows)), "white")
        y = 0
        for r in rows:
            sheet.paste(r, (0, y)); y += r.height
        sheet.save(os.path.join(out, "sheet.png"))
    print("자세 %d개, 점검 걸림 %d개 -> %s" % (len(names), bad, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
