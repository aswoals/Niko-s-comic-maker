# -*- coding: utf-8 -*-
"""칸 v2 — 컷의 역할·구도에 맞춰 칸 크기·모양을 고르는 페이지 칸 나누기

지금(v1, nk_plan._rows): 줄마다 1~3칸 격자, big·첫 풍경만 한 줄 통째 -> 칸이 거의 같은 크기, 세로로 긴 칸 불가.
v2: 칸을 '나무'로 나눔 (가로 줄로 나누고, 줄 안에서 세로로 나누고, 그 안에서 다시 가로로) -> 세로로 긴 칸 옆에 작은 칸 둘 같은 묶음이 됨.
    컷마다 '무게'(큰 사건·풍경·맺음은 크게, 반응·소품·얼굴은 작게)와 '좋은 모양'(풍경·두 명 = 가로로 긴 칸, 혼자 전신 = 세로 칸,
    얼굴·소품 = 정사각에 가까운 칸)을 정하고, 가능한 칸 나누기를 모두 만들어 점수가 가장 좋은 것을 고름.
    그림은 칸 비율에 맞춰 그려짐 (nk_webtoon._flatten_pages 가 칸 비율에 가까운 그림 크기를 고름 — 지금과 같음).
나무 모양: {"split": "h"|"v", "r": [비율...], "kids": [...]} / 잎 {"cut": 컷 번호}. h = 위아래로 쌓기, v = 옆으로 나란히 (오른쪽부터 읽음).
켜는 법: plan.yaml 맨 위 layout: v2 (컴파일러가 pages[].tree 를 씀, rows 는 옛 방식 그대로 남김). 미리보기: python nk_layout2.py <편>"""
import itertools, math

ASPECT_MIN, ASPECT_MAX = 0.45, 2.4         # 그림 크기 표(PAGE_SIZES)가 다루는 비율 안쪽


def profile(c, first=False, last=False):
    """컷 -> (무게, 좋은 비율 가로/세로). c = 컴파일된 컷 (shot, angle, cast/char, _big 또는 big)"""
    shot = str(c.get("shot") or "knee")
    n = len(c.get("cast") or []) if c.get("cast") else (0 if str(c.get("char", "")).lower() == "none" else 1)
    big = bool(c.get("_big") or c.get("big"))
    if n == 0:
        pref = {"wide": 2.0, "detail": 1.15}.get(shot, 1.6)
        w = 2.0 if (shot == "wide" and first) else (1.0 if shot == "detail" else 1.4)
    elif n >= 2:
        pref = {"face": 1.5, "waist": 1.5, "knee": 1.45, "full": 1.6, "wide": 2.0}.get(shot, 1.5)
        w = 2.0
    else:
        pref = {"eyes": 1.6, "face": 1.0, "hands": 1.2, "detail": 1.1, "waist": 0.95, "knee": 0.8, "full": 0.72, "wide": 1.8}.get(shot, 0.9)
        w = {"eyes": 0.85, "face": 1.0, "hands": 0.85, "detail": 0.9, "waist": 1.15, "knee": 1.35, "full": 1.45, "wide": 1.8}.get(shot, 1.2)
        if str(c.get("angle") or "") in ("high", "low") and shot in ("full", "knee"):
            w += 0.15                        # 부감·앙각 전신 = 보여 줄 것이 많음
    if "chibi" in str(c.get("scene") or "") + " " + str(c.get("anima_act") or ""):
        w, pref = 0.85, 0.95                     # 치비 개그 칸 = 작게
    if big:
        w = max(w, 2.6) + (0.4 if last else 0.0)
    return w, pref


def _compositions(n, maxpart=3, maxrows=4):
    """n 컷을 순서대로 줄로 나누는 모든 방법 (줄마다 1~maxpart)"""
    out = []

    def go(rest, cur):
        if len(cur) > maxrows:
            return
        if rest == 0:
            out.append(list(cur)); return
        for k in range(1, min(maxpart, rest) + 1):
            go(rest - k, cur + [k])
    go(n, [])
    return out


def _row_variants(ids):
    """한 줄 안의 모양: 나란히 / (3컷) 첫 칸 세로 길게 + 나머지 위아래 / 마지막 칸 세로 길게 + 앞 둘 위아래"""
    k = len(ids)
    vs = [("flat", ids)]
    if k == 3:
        vs.append(("tallfirst", ids))
        vs.append(("talllast", ids))
    return vs


def _row_ideal_height(kind, prefs, width, gutter):
    """그 줄의 좋은 높이 (칸들이 좋은 비율을 가지려면)"""
    if kind == "flat":
        return (width - gutter * (len(prefs) - 1)) / sum(prefs)
    a, b, c = prefs if kind == "tallfirst" else (prefs[2], prefs[0], prefs[1])
    stack = 1.0 / (1.0 / b + 1.0 / c)                 # 위아래 두 칸 묶음의 비율
    return (width - gutter) / (a + stack)


def _row_tree(kind, ids, prefs, width, height, gutter):
    """줄 -> 나무 조각 (비율은 실제 픽셀에서)"""
    if kind == "flat":
        ws = [p * height for p in prefs]
        s = sum(ws); avail = width - gutter * (len(ids) - 1)
        return {"split": "v", "r": [x / s for x in ws], "kids": [{"cut": i} for i in ids]} if len(ids) > 1 else {"cut": ids[0]}
    if kind == "tallfirst":
        a, (b, c) = prefs[0], prefs[1:]
        big, pair = ids[0], ids[1:]
    else:
        a, (b, c) = prefs[2], prefs[:2]
        big, pair = ids[2], ids[:2]
    wa = a * height
    wr = max(width - gutter - wa, width * 0.25)
    hb, hc = wr / b, wr / c
    col = {"split": "h", "r": [hb / (hb + hc), hc / (hb + hc)], "kids": [{"cut": pair[0]}, {"cut": pair[1]}]}
    kids = [{"cut": big}, col] if kind == "tallfirst" else [col, {"cut": big}]
    tot = wa + wr
    r = [wa / tot, wr / tot] if kind == "tallfirst" else [wr / tot, wa / tot]
    return {"split": "v", "r": r, "kids": kids}


def rects(tree, box, rtl=True, gutter=24):
    """나무 -> {컷 번호: [x0, y0, x1, y1]}. box = [x0, y0, x1, y1]. v 나누기는 rtl 이면 첫 칸이 오른쪽"""
    out = {}

    def go(node, b):
        x0, y0, x1, y1 = b
        if "cut" in node:
            out[int(node["cut"])] = [int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))]
            return
        kids, r = node["kids"], node["r"]
        if node["split"] == "h":
            avail = (y1 - y0) - gutter * (len(kids) - 1)
            y = y0
            for k, f in zip(kids, r):
                h = avail * f
                go(k, [x0, y, x1, y + h]); y += h + gutter
        else:
            avail = (x1 - x0) - gutter * (len(kids) - 1)
            if rtl:
                x = x1
                for k, f in zip(kids, r):
                    w = avail * f
                    go(k, [x - w, y0, x, y1]); x -= w + gutter
            else:
                x = x0
                for k, f in zip(kids, r):
                    w = avail * f
                    go(k, [x, y0, x + w, y1]); x += w + gutter
    go(tree, box)
    return out


def score(tree, prof, box, gutter=24):
    """작을수록 좋음: 칸 모양이 좋은 비율에서 먼 정도 + 칸 넓이가 무게와 어긋난 정도 + 너무 얇은·작은 칸 + 칸이 다 같은 크기(리듬 없음)"""
    rs = rects(tree, box, True, gutter)
    page_area = (box[2] - box[0]) * (box[3] - box[1])
    areas, sc = {}, 0.0
    for cid, (x0, y0, x1, y1) in rs.items():
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        asp = w / float(h)
        wt, pref = prof[cid]
        sc += wt * math.log(asp / pref) ** 2
        if asp < ASPECT_MIN or asp > ASPECT_MAX:
            sc += 6.0 * (math.log(asp / (ASPECT_MIN if asp < ASPECT_MIN else ASPECT_MAX)) ** 2 + 0.3)
        areas[cid] = w * h
        if wt >= 1.3 and w * h < page_area * 0.07:
            sc += 1.5                                 # 사람이 보여야 하는 컷이 너무 작음
    tw = sum(prof[c][0] for c in areas); ta = float(sum(areas.values()))
    sc += 20.0 * sum((areas[c] / ta - prof[c][0] / tw) ** 2 for c in areas) * len(areas)
    vals = list(areas.values()); mu = sum(vals) / len(vals)
    cv = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 / mu
    if len(vals) >= 4 and cv < 0.28:
        sc += 2.0 * (0.28 - cv) / 0.28                # 칸 크기가 다 같으면 리듬이 없음 (실제 만화는 크고 작은 칸이 섞임)
    return sc


def best_tree(cuts, box, gutter=24):
    """한 쪽의 컷들 (순서대로) -> 가장 점수가 좋은 나무. cuts = 컴파일된 컷 목록 (id, shot, angle, cast/char, _big)"""
    ids = [int(c["id"]) for c in cuts]
    prof = {int(c["id"]): profile(c, i == 0, i == len(cuts) - 1) for i, c in enumerate(cuts)}
    W, H = box[2] - box[0], box[3] - box[1]
    # 한 줄을 통째로 쓰는 컷: 쪽 첫 컷이 사람 없는 풍경(장소 소개), 큰 컷(big) — v1 규칙과 같음 (실제 만화도 장소·큰 사건은 크게)
    def _wide_big(i, c):
        n = len(c.get("cast") or []) if c.get("cast") else (0 if str(c.get("char", "")).lower() == "none" else 1)
        return i == len(cuts) - 1 or n != 1 or str(c.get("shot")) in ("wide", "full")
    alone = {int(c["id"]) for i, c in enumerate(cuts)
             if ((c.get("_big") or c.get("big")) and _wide_big(i, c))
             or (i == 0 and str(c.get("shot")) == "wide" and profile(c)[1] >= 1.6 and not c.get("cast")
                 and str(c.get("char", "")).lower() == "none")}
    #   점수가 확실히(벌점 1.5 넘게) 좋으면 그쪽 (큰 컷은 무게 2.6 이라 여전히 크게 나옴)
    first_scene = {x for x in alone if not any((c.get("_big") or c.get("big")) for c in cuts if int(c["id"]) == x)}
    best = None
    for rule, pen in ((alone, 0.0), (first_scene, 1.5)):
        b2 = _search(ids, prof, rule, W, H, box, gutter)
        if b2 and (best is None or b2[0] + pen < best[0]):
            best = (b2[0] + pen, b2[1])
    return best[1], best[0]


def _search(ids, prof, alone, W, H, box, gutter):
    best = None
    for comp in _compositions(len(ids)):
        groups, i = [], 0
        for k in comp:
            groups.append(ids[i:i + k]); i += k
        if any(len(g) > 1 and any(x in alone for x in g) for g in groups):
            continue
        for choice in itertools.product(*[_row_variants(g) for g in groups]):
            ideal = [_row_ideal_height(kind, [prof[x][1] for x in g], W, gutter) for kind, g in choice]
            wts = [sum(prof[x][0] for x in g) / len(g) ** 0.5 for kind, g in choice]
            raw = [h * (wt ** 0.35) for h, wt in zip(ideal, wts)]
            avail = H - gutter * (len(choice) - 1)
            hs = [x / sum(raw) * avail for x in raw]
            rows = [_row_tree(kind, g, [prof[x][1] for x in g], W, h, gutter) for (kind, g), h in zip(choice, hs)]
            tree = {"split": "h", "r": [h / avail for h in hs], "kids": rows} if len(rows) > 1 else rows[0]
            s = score(tree, prof, box, gutter)
            if best is None or s < best[0]:
                best = (s, tree)
    return best


def page_box(st):
    """페이지 설정(nk_webtoon._page_style) -> 칸이 들어갈 안쪽 상자"""
    return [st["margin"], st["margin"], st["width"] - st["margin"], st["height"] - st["margin"]]


def preview(nk, kit, ep, out=None):
    """칸만 그린 미리보기 (컷 번호·구도·사람 수) — 그림 없이. episodes/<ep>/layout_v1_v2.png (왼쪽 v1, 오른쪽 v2)"""
    import os
    import nk_webtoon as W
    from PIL import Image, ImageDraw, ImageFont
    c = nk.load_yaml(os.path.join(W.ep_dir(kit, ep), "conti.yaml"))
    st = W._page_style(nk.load_presets())
    box = page_box(st)
    font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 30)
    import nk_plan
    plan, _ = nk_plan._extract_yaml(open(os.path.join(W.ep_dir(kit, ep), "plan.yaml"), encoding="utf-8-sig").read())
    plan["layout"] = "v2"
    info = {k: nk.load_yaml(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "%s.yaml" % f)) or {} for k, f in (plan.get("cast") or {}).items()}
    c2, _ = nk_plan.compile_plan(plan, info, kit)
    v2pages = {int(p_["page"]): p_.get("tree") for p_ in c2["pages"]}
    tiles = []
    for pg in c["pages"]:
        cuts = pg["cuts"]
        for ver in ("v1", "v2"):
            im = Image.new("RGB", (st["width"], st["height"]), "white")
            d = ImageDraw.Draw(im)
            if ver == "v1":
                c1 = {"pages": [{k: v for k, v in pg.items() if k != "tree"}], "read": c.get("read", "rtl"), "defaults": c.get("defaults", {})}   # v2 콘티도 왼쪽은 줄 방식으로
                W._flatten_pages(nk, c1)
                rs = {int(x["id"]): x["rect"] for x in c1["cuts"]}
            else:
                tree = pg.get("tree") or v2pages[int(pg["page"])]
                rs = rects(tree, box, str(c.get("read", "rtl")) == "rtl", st["gutter"])
            byid = {int(x["id"]): x for x in cuts}
            for cid, (x0, y0, x1, y1) in rs.items():
                ct = byid[cid]
                n = len(ct.get("cast") or []) if ct.get("cast") else (0 if str(ct.get("char", "")).lower() == "none" else 1)
                d.rectangle([x0, y0, x1, y1], outline="black", width=st["border"], fill=(235, 240, 248) if n == 0 else (250, 238, 230) if n == 1 else (236, 248, 236))
                d.text((x0 + 14, y0 + 10), "%d  %s%s%s" % (cid, ct.get("shot"), " · %d명" % n if n else " · 사람 없음", " · 큰 컷" if ct.get("big") else ""),
                       fill="black", font=font)
                d.text((x0 + 14, y1 - 46), "%.2f" % ((x1 - x0) / float(max(1, y1 - y0))), fill=(90, 90, 90), font=font)
            d.text((24, 12), "%s 쪽 %s" % (pg.get("page"), "지금 (v1)" if ver == "v1" else "칸 v2"), fill=(200, 60, 40), font=font)
            tiles.append(im)
    s = 0.4
    tw, th = int(st["width"] * s), int(st["height"] * s)
    sheet = Image.new("RGB", (tw * 2 + 30, (th + 30) * (len(tiles) // 2)), "white")
    for k, im in enumerate(tiles):
        sheet.paste(im.resize((tw, th)), ((k % 2) * (tw + 30), (k // 2) * (th + 30)))
    out = out or os.path.join(W.ep_dir(kit, ep), "layout_v1_v2.png")
    sheet.save(out)
    return out


if __name__ == "__main__":
    import sys, os
    KIT = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, KIT)
    import nk
    print(preview(nk, KIT, sys.argv[1] if len(sys.argv) > 1 else "gl01"))
