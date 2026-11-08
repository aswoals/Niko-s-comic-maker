# -*- coding: utf-8 -*-
"""글자·효과 v2 — conti 맨 위 letter: v2 일 때만 (기본은 v1 그대로)

v1 (nk_webtoon._draw_item·_draw_fx): 효과음 = 맑은 고딕 굵게 일자, 말풍선 = 타원·생각 구름·네모 해설, 효과선 = 반투명 줄을 칸 위에 덮음.
v2:
  효과음 — 손글씨·만화 글꼴(fonts/, Google Fonts OFL)을 소리 느낌으로 고름 (쾅·쿵·뚝 = 굵고 각진 / 맴맴·주룩 = 붓 손글씨 / 부스럭 = 거친 손글씨 /
           두근·반짝 = 둥근), 글자마다 크기·회전·높이를 흔들고 전체를 기울임, 굵은 흰 테두리. 크기는 글자 수·칸 크기로, 자리는 사람·얼굴을 피함.
           콘티 lines sfx 에 size (s/m/l/xl)·style (hard/heavy/brush/rough/round/pen)·vertical (세로로)·angle 을 적을 수 있음
  말풍선 — shout (가시 폭발 풍선 + 굵은 글꼴) / whisper (점선 풍선 + 작은 글자) / tremble (떨리는 물결 풍선) / aside (풍선 없는 작은 손글씨 혼잣말)
           speech 에 '!' 가 둘 이상이면 shout 로 (실제 만화의 외침 풍선)
  효과선 — 집중선·속도선을 사람 마스크(_final_people) 밖에만 (v1 은 사람 위에도 덮어 그림을 가렸음)"""
import math, os, random

KIT = os.path.dirname(os.path.abspath(__file__))
FONTS = {"hard": "BlackHanSans-Regular.ttf", "heavy": "BagelFatOne-Regular.ttf", "brush": "EastSeaDokdo-Regular.ttf",
         "rough": "Dokdo-Regular.ttf", "round": "Jua-Regular.ttf", "pen": "NanumPenScript-Regular.ttf", "hand": "Gaegu-Bold.ttf"}
HARD = ("쾅", "쿵", "꽝", "뚝", "탁", "빡", "퍽", "쿠궁", "펑", "퍼어", "팍", "쨍", "콰", "와장창", "덜컥", "딸깍", "짝", "두둥", "번쩍")
WATER = ("첨벙", "철벅", "풍덩", "찰박", "텀벙", "철썩", "촤악", "쏴아")
BRUSH = ("맴", "주룩", "쏴", "솨", "휘이", "부웅", "웅", "우르르", "스르", "사르", "슈", "휭", "쉬익")
ROUND = ("두근", "반짝", "뿅", "말랑", "꼬르륵", "뽀", "톡", "콩", "냠")


def font_path(style):
    return os.path.join(KIT, "fonts", FONTS.get(style, FONTS["hard"]))


_HAS = {}
SUBST = {"…": "...", "—": "-", "―": "-", "♪": "~", "♥": "~"}


def has_glyph(font, ch):
    """글꼴에 이 글자가 있나 (없으면 빈칸이나 네모로 나옴 — gl01v 첫 판: BlackHanSans 에 '…' 없음, 외침 풍선이 '가위바위   !')"""
    key = (getattr(font, "path", ""), ch)
    if key not in _HAS:
        def sig(c):
            m = font.getmask(c)
            return (m.size, sum(bytes(m)))
        a = sig(ch)
        _HAS[key] = not (a[1] == 0 or a == sig("󰀀"))
    return _HAS[key]


def fit_text(text, font):
    """글꼴에 없는 글자를 비슷한 글자로 ('…' -> '...')"""
    return "".join(SUBST[c] if c in SUBST and not has_glyph(font, c) else c for c in str(text))


def sfx_style(text):
    t = str(text)
    if any(k in t for k in ROUND):
        return "round"
    if any(k in t for k in WATER):
        return "heavy"                                  # 물소리 = 둥글고 굵게
    if any(k in t for k in BRUSH) or t.count("…") or t.endswith("~"):
        return "brush"
    if any(k in t for k in HARD):
        return "hard"
    return "rough"


def _glyph(ch, font, fill, stroke, sw):
    """글자 하나 -> RGBA 그림 (흰 테두리)"""
    from PIL import Image, ImageDraw
    l, t, r, b = font.getbbox(ch, stroke_width=sw)
    im = Image.new("RGBA", (max(1, r - l + 4), max(1, b - t + 4)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - l, 2 - t), ch, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)
    return im


def sfx_layer(text, size, style, vertical=False, seed=0, fill=(20, 20, 20), stroke=(255, 255, 255)):
    """효과음 글자 줄 -> RGBA 그림 (글자마다 크기·회전·높이 흔들기)"""
    from PIL import Image, ImageFont
    rnd = random.Random(seed)
    glyphs = []
    text = fit_text(text, ImageFont.truetype(font_path(style), 40))
    chars = [c for c in str(text) if c.strip()]
    for k, ch in enumerate(chars):
        grow = 1.0 + (0.18 if k == 0 and style in ("hard", "heavy") else 0.0)      # 첫 글자를 조금 크게 (만화 효과음 버릇)
        s = int(size * grow * rnd.uniform(0.86, 1.12) * (0.55 if ch in "…~.!?" else 1.0))
        f = ImageFont.truetype(font_path(style), max(12, s))
        g = _glyph(ch, f, fill, stroke, max(3, int(s * 0.14)))
        g = g.rotate(rnd.uniform(-9, 9), resample=Image.BICUBIC, expand=True)
        glyphs.append(g)
    if not glyphs:
        return None
    if vertical:
        W = max(g.width for g in glyphs); H = int(sum(g.height * 0.82 for g in glyphs)) + glyphs[-1].height
        L = Image.new("RGBA", (W + 20, H + 20), (0, 0, 0, 0)); y = 10
        for g in glyphs:
            L.alpha_composite(g, (10 + (W - g.width) // 2 + int(rnd.uniform(-0.08, 0.08) * W), y)); y += int(g.height * 0.82)
    else:
        H = max(g.height for g in glyphs); W = int(sum(g.width * 0.86 for g in glyphs)) + glyphs[-1].width
        L = Image.new("RGBA", (W + 20, H + 40), (0, 0, 0, 0)); x = 10
        for g in glyphs:
            L.alpha_composite(g, (x, 20 + (H - g.height) // 2 + int(rnd.uniform(-0.12, 0.12) * H))); x += int(g.width * 0.86)
    return L


def vertical_hint(text, pw, ph):
    n = len([c for c in text if c.strip() and c not in "…~.!?"])
    return n >= 4 and ph > pw * 1.3


def draw_sfx(P, item, panel, st, idx=0):
    """효과음 v2 를 페이지 P 에 (자리는 nk_webtoon._smart_at 이 사람·얼굴·다른 글자를 피해서 고름)"""
    import nk_webtoon as Wt
    from PIL import Image
    px, py, pw, ph = panel
    text = str(item.get("text", ""))
    n = max(1, len([c for c in text if c.strip() and c not in "…~.!?"]))
    size = item.get("size")
    frac = {"s": 0.10, "m": 0.15, "l": 0.21, "xl": 0.29}.get(str(size), None)
    if frac is None:
        frac = 0.20 if n <= 2 else 0.15 if n <= 4 else 0.12 if n <= 6 else 0.10
    base = min(ph, pw * 1.1) * frac
    if size is None:                                     # 자동 크기: 글줄 전체가 칸 폭의 약 40% 를 넘지 않게 (lt01 첫 판: 캐릭터를 덮음)
        base = min(base, (ph if vertical_hint(text, pw, ph) else pw) * 0.40 / (n + 0.5 * (len(text) - n)))
    style = str(item.get("style") or sfx_style(text))
    vertical = bool(item.get("vertical")) or (n >= 4 and ph > pw * 1.3)
    L = sfx_layer(text, base, style, vertical, seed=hash((text, px, py, idx)) & 0xffff)
    if L is None:
        return
    ang = float(item.get("angle", -10 if style in ("hard", "heavy") else 6 if style == "brush" else -5))
    L = L.rotate(ang, resample=Image.BICUBIC, expand=True)
    maxw, maxh = int(pw * 0.92), int(ph * 0.9)
    if L.width > maxw or L.height > maxh:
        s = min(maxw / float(L.width), maxh / float(L.height))
        L = L.resize((max(1, int(L.width * s)), max(1, int(L.height * s))), Image.LANCZOS)
    x, y = Wt._smart_at(L.width, L.height, panel, item.get("at") or "bl", st)
    PM = st.get("_people")
    for _ in range(3):                                   # 사람을 많이 덮으면 조금 작게 해서 다시 자리 찾기
        if PM is None:
            break
        hb = PM.crop((x, y, x + L.width, y + L.height)).histogram()
        if sum(i * c for i, c in enumerate(hb)) / max(1, sum(hb)) / 255.0 < 0.5:
            break
        L = L.resize((max(1, int(L.width * 0.8)), max(1, int(L.height * 0.8))), Image.LANCZOS)
        x, y = Wt._smart_at(L.width, L.height, panel, item.get("at") or "bl", st)
    base_img = P.crop((x, y, x + L.width, y + L.height)).convert("RGBA")
    P.paste(Image.alpha_composite(base_img, L).convert("RGB"), (x, y))
    st.setdefault("_occupied", []).append((x, y, L.width, L.height))


def bubble_shape(kind, x, y, w, h, seed=0):
    """풍선 윤곽 점들 (shout = 가시, tremble = 물결, 그 밖 = 타원)"""
    rnd = random.Random(seed)
    cx, cy, rx, ry = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
    pts = []
    if kind == "shout":
        n = 22
        for k in range(n * 2):
            a = math.pi * k / n
            r = (1.32 + rnd.uniform(-0.08, 0.14)) if k % 2 == 0 else (0.98 + rnd.uniform(-0.03, 0.03))
            pts.append((cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r))
    elif kind == "tremble":
        n = 90
        for k in range(n):
            a = 2 * math.pi * k / n
            r = 1.0 + 0.035 * math.sin(a * 23) + 0.02 * math.sin(a * 37)
            pts.append((cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r))
    else:
        n = 72
        for k in range(n):
            a = 2 * math.pi * k / n
            pts.append((cx + math.cos(a) * rx, cy + math.sin(a) * ry))
    return pts


def draw_bubble(P, d, item, panel, st, idx, kind):
    """말풍선 v2: shout / whisper / tremble / aside. 줄바꿈·자리·꼬리 방향은 nk_webtoon 의 것을 씀"""
    import nk_webtoon as Wt
    from PIL import ImageFont
    text = str(item.get("text", ""))
    px, py, pw, ph = panel
    fs0 = int(st["font_size"])
    if kind == "aside":                                     # 손글씨 글꼴이 작아 보여서 크게 (gl01v 첫 판: 안 읽힘)
        fsize = int(fs0 * 1.0)
        font = ImageFont.truetype(font_path("pen"), int(fsize * 1.4))
    elif kind == "shout":
        fsize = int(fs0 * 1.15)
        font = ImageFont.truetype(font_path("hard"), fsize)
    elif kind == "whisper":
        fsize = int(fs0 * 0.82)
        font = Wt._font(st.get("font"), fsize)
    else:
        fsize = fs0
        font = Wt._font(st.get("font"), fsize)
    if kind != "aside" and hasattr(Wt, "_fit_text"):        # 작은 칸이면 글씨를 줄이고 폭을 넓힘 (외침은 가시 몫까지 넉넉히)
        of = {"shout": lambda s: ImageFont.truetype(font_path("hard"), s)}.get(kind, lambda s: Wt._font(st.get("font"), s))
        font, fsize, text, lines = Wt._fit_text(d, text, panel, st, fsize, st.get("bubble_ratio", 0.42), of,
                                                pad_w=3.2 if kind == "shout" else 2.0, pad_h=2.6 if kind == "shout" else 1.6,
                                                max_frac=0.5 if kind == "shout" else 0.9)
    else:
        text = fit_text(text, font)
        maxw = int(max(pw * st.get("bubble_ratio", 0.42), fsize * 4))
        if kind == "aside" and len(text) <= 12:             # 짧은 혼잣말은 한 줄로 ('치사하게...' 의 점이 다음 줄로 갈라짐)
            maxw = max(maxw, int(d.textlength(text, font=font)) + 4)
        lines = Wt._wrap(d, text, font, maxw)
    lh = int(fsize * 1.32)
    tw = max(d.textlength(l, font=font) for l in lines)
    th = lh * len(lines)
    lw = int(st["line"])
    if kind == "aside":                                     # 풍선 없이 작은 손글씨 (흰 테두리)
        x, y = Wt._smart_at(int(tw) + 10, th + 10, panel, item.get("at") or "tr", st)
        for i, l in enumerate(lines):
            d.text((x + 5, y + 5 + i * lh), l, font=font, fill=(25, 25, 25), stroke_width=max(2, fsize // 9), stroke_fill="white")
        st.setdefault("_occupied", []).append((x, y, int(tw) + 10, th + 10))
        return
    padx, pady = int(fsize * (1.35 if kind == "shout" else 1.0)), int(fsize * (1.05 if kind == "shout" else 0.8))
    bw, bh = int(tw + padx * 2), int(th + pady * 2)
    mx, my = (int(bw * 0.24), int(bh * 0.24)) if kind == "shout" else (0, 0)    # 가시가 칸·쪽 밖으로 안 나가게 (가시 = 반지름의 1.46배까지)
    spk0 = Wt._speaker_point(item, panel, st) if len((st.get("_cut") or {}).get("_roles") or []) >= 2 else None
    x, y = Wt._smart_at(bw + 2 * mx, bh + 2 * my, panel, item.get("at") or ["tl", "tr", "bl", "br"][idx % 4], st,
                        near_x=spk0[0] if isinstance(spk0, tuple) else None)
    x, y = x + mx, y + my
    cx, cy = x + bw / 2.0, y + bh / 2.0
    tx_, ty_ = px + pw / 2.0, py + ph / 2.0
    spk = Wt._speaker_point(item, panel, st)
    off = spk == "offscreen"
    if isinstance(spk, tuple):
        tx_, ty_ = spk
    vx, vy = tx_ - cx, ty_ - cy
    if off:
        vx, vy = -vx, -vy
    nrm = max(1.0, (vx * vx + vy * vy) ** 0.5); vx, vy = vx / nrm, vy / nrm
    pts = bubble_shape(kind, x, y, bw, bh, seed=hash((text, idx)) & 0xffff)
    tail_len = fsize * (2.2 if kind == "shout" else 1.6)
    if hasattr(Wt, "_tail_len"):                            # 말한 사람이 멀면 그쪽으로 더 길게
        tail_len = Wt._tail_len(tail_len, fsize, ((tx_ - cx) ** 2 + (ty_ - cy) ** 2) ** 0.5, bw, bh, isinstance(spk, tuple) and not off)
    tip = (cx + vx * (bw / 2.0 + tail_len), cy + vy * (bh / 2.0 + tail_len))
    base = (cx + vx * bw * 0.32, cy + vy * bh * 0.32)
    ox, oy = -vy * fsize * 0.45, vx * fsize * 0.45
    tail = [(base[0] + ox, base[1] + oy), tip, (base[0] - ox, base[1] - oy)]
    fill, ink = Wt._bubble_colors(item, st) if hasattr(Wt, "_bubble_colors") else ("white", "black")   # 캐릭터 파일 bubble: 말풍선 색
    d.polygon(tail, fill=fill)
    d.polygon(pts, fill=fill)
    if kind == "whisper":                                   # 점선 테두리
        for k in range(0, len(pts), 2):
            a, b = pts[k], pts[(k + 1) % len(pts)]
            d.line([a, b], fill=ink, width=max(2, lw - 1))
        d.line([tail[0], tip], fill=ink, width=max(2, lw - 1)); d.line([tip, tail[2]], fill=ink, width=max(2, lw - 1))
    else:
        d.line(pts + [pts[0]], fill=ink, width=lw + (1 if kind == "shout" else 0), joint="curve")
        d.line([tail[0], tip, tail[2]], fill=ink, width=lw)
    d.polygon(pts, fill=fill)                               # 꼬리 뿌리의 선을 덮음
    if kind != "whisper":
        d.line(pts + [pts[0]], fill=ink, width=lw + (1 if kind == "shout" else 0), joint="curve")
    for i, l in enumerate(lines):
        w_ = d.textlength(l, font=font)
        d.text((cx - w_ / 2.0, cy - th / 2.0 + i * lh), l, font=font, fill="black")
    st.setdefault("_occupied", []).append((x - mx, y - my, bw + 2 * mx, bh + 2 * my))


def bubble_kind(item):
    """v2: 콘티가 정한 종류 그대로, speech 인데 '!' 가 둘 이상이면 shout"""
    k = str(item.get("type", "speech"))
    if k == "speech" and str(item.get("text", "")).count("!") >= 2:
        return "shout"
    return k


def face_center(PM, rect):
    """얼굴 극근접 컷: 칸 가운데 타원(폭 72%·높이 86%)을 사람 마스크에 더함 (효과선·효과음이 얼굴을 덮지 않게)"""
    from PIL import ImageDraw
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    ImageDraw.Draw(PM).ellipse([x0 + w * 0.14, y0 + h * 0.07, x1 - w * 0.14, y1 - h * 0.07], fill=255)


def mask_people(L, rect, PM):
    """효과선 레이어 L(RGBA, 칸 크기)에서 사람 마스크(PM, 페이지 크기 L) 부분을 지움 — 선이 인물을 덮지 않게"""
    if PM is None:
        return L
    from PIL import ImageChops, ImageFilter
    x0, y0, x1, y1 = rect
    m = PM.crop((x0, y0, x1, y1)).point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(10))   # 뼈대 마스크가 얇아서 넉넉히 넓힘
    a = L.getchannel("A")
    a = ImageChops.multiply(a, ImageChops.invert(m))
    L.putalpha(a)
    return L


#   컷마다 캐릭터 실루엣(anime-seg) 안의 채도·밝기 평균을 재서, 편 전체의 가운데 값 쪽으로 반쯤 당김 (그림 전체에 같은 배율).
def char_stats(im, mask):
    import numpy as np
    hsv = np.asarray(im.convert("RGB").convert("HSV")).astype(float)
    m = np.asarray(mask.resize(im.size)) > 128
    if m.mean() < 0.03:
        return None
    return float(hsv[..., 1][m].mean()), float(hsv[..., 2][m].mean())


def color_targets(stats):
    """[(채도, 밝기)] -> 가운데 값"""
    import statistics
    ok = [s for s in stats if s]
    if len(ok) < 3:
        return None
    return statistics.median(s[0] for s in ok), statistics.median(s[1] for s in ok)


def match_color(im, stat, target, pull=0.5, lim=(0.75, 1.3)):
    """그림 전체 채도·밝기에 같은 배율 — 캐릭터 평균이 target 쪽으로 pull 만큼"""
    if not stat or not target:
        return im
    import numpy as np
    from PIL import Image
    ks = min(max((target[0] / max(stat[0], 1.0)) ** pull, lim[0]), lim[1])
    kv = 1.0          # 밝기는 안 건드림 (gl03c 첫 판: 흰 배경 컷이 회색으로 — 밝기는 장면 분위기)
    hsv = np.asarray(im.convert("RGB").convert("HSV")).astype(float)
    hsv[..., 1] = np.clip(hsv[..., 1] * ks, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * kv, 0, 255)
    return Image.fromarray(hsv.astype("uint8"), "HSV").convert("RGB")
