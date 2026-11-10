# -*- coding: utf-8 -*-
"""
nk_webtoon.py - episode pipeline for nk (webtoon / vertical strip)

  nk ep new   ep01              make episodes/ep01/conti.yaml (the only file the writer edits)
  nk ep make  ep01              ONE BUTTON: every cut without a finished image ->
                                candidates -> VLM auto-pick -> hires final -> lettered strip
  nk ep redo  ep01 3 5          throw away cuts 3 and 5, draw them again (auto-pick, final, letter)
  nk ep pick  ep01 3=2          override the auto-pick: cut 3 -> candidate 2 (then final + letter again)
  nk ep letter ep01             only redo speech bubbles (after editing text/at in conti.yaml, seconds)

  advanced: nk ep draft / nk ep final (single steps)"""
import os, sys, json, glob, shutil, random, argparse, time

SIZES = {"wide": (1216, 832), "tall": (832, 1216), "square": (1024, 1024),
         "banner": (1344, 768), "long": (768, 1344)}

TEMPLATE = """# ============================================================
#  글콘티 (conti.yaml) - 컷 하나 = 아래 블록 하나. 사람이 고치는 파일은 이것뿐.
# ============================================================
title: 월요일 아침
artist: ""              # 그림체: presets.yaml 의 작가 이름 또는 Danbooru/e621 작가 태그 (비우면 작가 없음)
char: mychar            # characters/mychar.yaml (없으면 none)
# 컷 공통 설정 (컷마다 덮어쓸 수 있음)
defaults:
  size: wide            # wide(가로) / tall(세로) / square / banner(넓은 가로) / long(긴 세로)

cuts:
  - id: 1
    size: banner
    scene: "solo, upper body, lying on side, head on pillow, bed, sleeping, closed eyes, blanket, bedroom, morning, sunlight through window"
    text:
      - {type: narration, text: "월요일 아침.", at: tl}

  - id: 2
    size: wide
    scene: "solo, upper body, sitting, bed, sleepy, half-closed eyes, yawning, messy fur"
    text:
      - {type: speech, text: "으음... 5분만 더...", at: tr}

  - id: 3
    size: tall
    scene: "solo, close-up, face, shocked, wide eyes, looking at alarm clock, sweat"
    text:
      - {type: sfx, text: "따르르릉!!", at: top}
      - {type: speech, text: "지각이다!!", at: bl}

  - id: 4
    size: wide
    scene: "solo, running, dynamic pose, motion lines, city street, morning, toast in mouth, full body"
    text:
      - {type: thought, text: "오늘은 꼭 늦으면 안 되는데...", at: tr}

  - id: 5
    size: tall
    scene: "solo, standing, cafe, counter, apron, smile, waving, upper body"
    text:
      - {type: speech, text: "어서오세요~!", at: tl}
      - {type: narration, text: "…결국 오늘도 1분 지각.", at: br}

# 텍스트 종류: speech(말풍선) / thought(생각 풍선) / narration(네모 해설) / sfx(효과음)
# at(위치): tl tr bl br top bottom left right (t=위 b=아래 l=왼 r=오)
# scene 쓰는 법: 인물 수(solo) + 구도(close-up / upper body / full body) + 포즈 + 표정 + 배경
# 컷별 선택 항목: strength(캐릭터 LoRA 강도, 기본 1.0) / lora(LoRA 파일) / artist / extra / neg / cfg / gap_after
#
# --- world: 컷 사이 일관성 ---------------------------------
# 컷을 따로 생성하면 앞 컷을 모르니 털실 색·앞치마·배경이 컷마다 바뀜. world: 에 한 번만 적어두면
# 해당 컷의 프롬프트·부정태그·검수질문에 자동으로 붙음.
#   world:
#     locations: {kitchen: {tags: "kitchen, ...", neg: "simple background"}}
#     props:     {yarn: {tags: "red ball of yarn", qa: {q: "...", options: [...], expect: [red], must: true}}}
#     wear:  [{tags: "pink apron", cuts: "5-8,15", qa: {...}}]     # cuts = 착용 구간
#     state: [{tags: "cream on nose", cuts: "24-28"}]              # 이후 컷으로 자동 전달되는 상태
#     neg_always: "english text, watermark"
#   컷에서: loc: kitchen / props: [yarn, bag] / qa: [{q,options,expect,must}]  (컷 전용 질문)
# 페이지 조립 옵션: flip: true(좌우 반전 - RTL에서 전진은 왼쪽) / crop: top|center|bottom(잘리는 쪽 지정)
# 요령: 누운 전신·옆으로 누운 전신은 아직 잘 깨짐 → upper body 로 가깝게 잡기.
"""


def ep_dir(kit, ep):
    return os.path.join(os.environ.get("NK_HOME") or kit, "episodes", ep)


SPECIES = ("cat", "dog", "wolf", "fox", "rabbit", "bear", "goat", "sheep", "deer", "horse", "tiger", "lion", "mouse",
           "otter", "raccoon", "dragon", "bird", "lizard", "shark", "hyena", "bat")


def char_tags(ch):
    return [t.strip().lower() for t in str((ch or {}).get("tags_short", "")).split(",") if t.strip()]


def find_words(ch):
    """SAM3 로 그 캐릭터 몸을 찾을 짧은 명사 후보 (앞이 우선): 캐릭터 파일 anima_find > sam_body > sam_find > 동물 종 > furry > character"""
    ch = ch or {}
    out = [str(ch[k]) for k in ("anima_find", "sam_body", "sam_find") if ch.get(k)]
    tags = char_tags(ch)
    out += [t for t in SPECIES if t in tags]
    out += ["furry"] if "furry" in tags else []
    return list(dict.fromkeys(out + ["character"]))


def find_word(ch):
    return find_words(ch)[0]


def head_tags(ch):
    """영역 글 머리말의 인원·종 태그: 캐릭터 파일 anima_region_head 가 있으면 그것, 없으면 태그에서 (1boy/1girl, furry·anthro)"""
    ch = ch or {}
    if ch.get("anima_region_head"):
        return str(ch["anima_region_head"])
    tags = char_tags(ch)
    out = [t for t in ("1boy", "1girl", "1other") if t in tags][:1]
    out += ["furry", "anthro"] if ("furry" in tags or "anthro" in tags) else []
    return ", ".join(out)


def load_conti(nk, kit, ep):
    p = os.path.join(ep_dir(kit, ep), "conti.yaml")
    if not os.path.exists(p):
        print("[ERROR] no conti:", p, " (make one: nk ep new %s)" % ep)
        sys.exit(1)
    c = nk.load_yaml(p)
    c["_ep"] = ep                                  # O 방식 뼈대 그림 위치 확인용 (preflight)
    c.setdefault("defaults", {})
    if c.get("format") == "page":
        _flatten_pages(nk, c)
    for i, cut in enumerate(c.get("cuts", []), 1):
        cut.setdefault("id", i)
        for k, v in c["defaults"].items():
            cut.setdefault(k, v)
        cut.setdefault("size", "wide")
        cut.setdefault("text", [])
    _resolve_cast(nk, c)
    return c


#              scene 에는 두 사람 공통(인원수 duo, 2boys + 함께 하는 동작)만 씀
def _resolve_cast(nk, c):
    cache = {}

    def get(name):
        if name in cache:
            return cache[name]
        files = c.get("chars") or {}
        ch = nk.load_char(files.get(name, name))
        ch = dict(ch)
        ch["_key"] = name
        cache[name] = ch
        return ch

    dflt = str(c.get("char", "none"))
    c["_default_char"] = None if dflt.lower() == "none" else get(dflt)
    c["_cast"] = {k: get(k) for k in (c.get("chars") or {})}
    for cut in c.get("cuts", []):
        if cut.get("cast"):
            roles = []
            for r in cut["cast"]:
                roles.append((dict(r), get(str(r["char"]))))
            cut["_roles"] = roles
            cut["_char"] = roles[0][1]            # "캐릭터가 있는 컷" 표시용 (사물 컷 아님)
            cut["_charkey"] = None
            continue
        key = str(cut.get("char", dflt))
        if key.lower() == "none":
            cut["_char"], cut["_charkey"] = None, None
        else:
            cut["_char"], cut["_charkey"] = get(key), key


def _is_duo(cut):
    return bool(cut.get("_roles"))


# ------------------------------------------------------------------ page (Japanese manga) layout
# SDXL-safe sizes; each panel is drawn at the closest aspect ratio, then center-cropped into its frame
PAGE_SIZES = [(1536, 640), (1344, 768), (1216, 832), (1152, 896), (1024, 1024),
              (896, 1152), (832, 1216), (768, 1344), (640, 1536)]


def _page_style(cfg):
    st = {"width": 1600, "ratio": 257 / 182, "margin": 70, "gutter": 24, "border": 4, "font": "",
          "font_size": 30, "line": 3, "bubble_w": 0.3}
    st.update((cfg or {}).get("manga") or {})
    st["height"] = int(st["width"] * st["ratio"])
    return st


def _flatten_pages(nk, c):
    """pages -> rows -> cuts  =>  flat c['cuts'] with pixel frame (rect) and generation size per cut.
    reading order is right-to-left: the first cut of a row sits at the right."""
    st = _page_style(nk.load_presets())
    W, H, M, G = st["width"], st["height"], st["margin"], st["gutter"]
    rtl = str(c.get("read", "rtl")) == "rtl"
    cuts = []
    for pg in c.get("pages", []):
        byid = {int(ct["id"]): ct for ct in pg.get("cuts", [])}
        if pg.get("tree"):
            import nk_layout2
            rs = nk_layout2.rects(pg["tree"], [M, M, W - M, H - M], rtl, G)
            for cid in sorted(rs, key=lambda k: [int(x["id"]) for x in pg["cuts"]].index(k)):
                x0, y0, x1, y1 = rs[cid]
                ct = dict(byid[cid])
                ct["page"] = int(pg["page"])
                ct["rect"] = [x0, y0, x1, y1]
                asp = (x1 - x0) / float(max(1, y1 - y0))
                bw, bh = min(PAGE_SIZES, key=lambda s_: abs((s_[0] / s_[1]) / asp - 1))
                ct["size"] = "%dx%d" % (bw, bh)
                for k, v in c["defaults"].items():
                    ct.setdefault(k, v)
                ct.setdefault("text", [])
                cuts.append(ct)
            continue
        y = M
        ih = H - 2 * M - G * (len(pg["rows"]) - 1)
        for row in pg["rows"]:
            rh = ih * float(row["h"])
            ids = [int(x) for x in row["cuts"]]
            ws = row.get("w") or [1.0 / len(ids)] * len(ids)
            iw = W - 2 * M - G * (len(ids) - 1)
            x = W - M if rtl else M
            for cid, wf in zip(ids, ws):
                cw = iw * float(wf)
                x0 = x - cw if rtl else x
                ct = dict(byid[cid])
                ct["page"] = int(pg["page"])
                ct["rect"] = [int(round(x0)), int(round(y)), int(round(x0 + cw)), int(round(y + rh))]
                asp = cw / rh
                if str(ct.get("char", "")).lower() != "none" and (asp > 2.2 or asp < 0.5):
                    print("[warn] cut %d: panel is %.1f:1 - a character's head/ears/feet will be cut off "
                          "(줄 높이 h를 키우거나 crop: top 을 쓸 것)" % (cid, asp if asp > 1 else 1 / asp))
                bw, bh = min(PAGE_SIZES, key=lambda s_: abs((s_[0] / s_[1]) / asp - 1))
                ct["size"] = "%dx%d" % (bw, bh)
                for k, v in c["defaults"].items():
                    ct.setdefault(k, v)
                ct.setdefault("text", [])
                cuts.append(ct)
                x = (x0 - G) if rtl else (x0 + cw + G)
            y += rh + G
    c["cuts"] = cuts


# ------------------------------------------------------------------ world (Phase 1: the conti remembers the setting)
# 문제: 컷마다 따로 생성하니 앞 컷이 뭘 그렸는지 모름 -> 털실 색·앞치마·배경이 컷마다 바뀜.
# 해결: conti.yaml의 world: 에 한 번만 적고, 그 컷에 해당하면 프롬프트·부정태그·검수질문을 자동으로 붙임.
def _parse_range(spec):
    """'5-8,15' -> {5,6,7,8,15}
    AI가 '5-'(끝까지)·'-3'·'1~5'·'1–5'·'all'·'전부' 처럼 쓰면 멈췄음 -> 끝이 비면 끝까지(999), 모르는 조각은 건너뜀"""
    t = str(spec or "").strip().lower()
    if t in ("all", "전부", "모두", "*"):
        return set(range(1, 1000))
    for d in ("~", "–", "—", "−", "to"):
        t = t.replace(d, "-")
    for e in ("end", "last", "끝", "마지막"):          # '3-end' = 3번부터 끝까지
        t = t.replace(e, "")
    out = set()
    for part in t.replace(" ", "").replace("、", ",").replace(";", ",").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                a = int(a) if a else 1
                b = int(b) if b else 999
                out |= set(range(a, b + 1))
            else:
                out.add(int(part))
        except ValueError:
            print("[warn] 컷 범위를 못 읽은 조각 '%s' 건너뜀 (전체: %s)" % (part, spec))
    return out


def _cut_qa(cut):
    """컷에 직접 적은 검수 질문. conti엔 id를 안 적으니 여기서 붙임"""
    out = []
    for i, q in enumerate(cut.get("qa") or [], 1):
        it = dict(q)
        it.setdefault("id", "cut_q%d" % i)
        it.setdefault("must", False)
        out.append(it)
    return out


DETAIL_ATMOS = {"indoors", "outdoors", "day", "night", "evening", "morning", "sunset", "sunrise", "dusk", "twilight", "fog", "mist",
                "light rays", "sunlight", "sunbeam", "moonlight", "rain", "raining", "snow", "snowing", "campfire", "lamp", "lantern",
                "candlelight", "fire", "winter", "summer", "autumn", "spring (season)", "cloudy", "starry sky",
                "kitchen", "room", "bedroom", "living room", "classroom", "library", "cafe", "restaurant", "shop", "bathroom",
                "cave", "table"}          # 방 종류는 남김 (가까이 찍어도 '어디'인지는 필요), 절벽·물·나무 같은 풍경만 뺌


def _world_for(c, cut):
    """(붙일 태그, 붙일 부정태그, 추가 검수질문) for one cut"""
    w = (c or {}).get("world") or {}
    cid = int(cut["id"])
    tags, negs, qa = [], [], []

    def add(entry, key):
        if entry is None:
            return
        if isinstance(entry, str):
            tags.append(entry)
            return
        if entry.get("tags"):
            tags.append(entry["tags"])
        if entry.get("neg"):
            negs.append(entry["neg"])
        if entry.get("qa"):
            it = dict(entry["qa"])
            it.setdefault("id", key)
            it.setdefault("must", False)
            qa.append(it)

    loc = cut.get("loc")
    if loc:
        locs = w.get("locations") or {}
        if loc not in locs:
            print("[warn] cut %d: loc '%s' is not in world.locations" % (cid, loc))
        le = locs.get(loc)
        if le and str(cut.get("char", "")).lower() == "none" and str(cut.get("shot", "")) == "detail":
            # 사물 클로즈업(detail): 장소의 풍경 태그(cliff, water, jungle...)를 붙이면 풍경화가 되고 소품이 구석에 작게 나옴
            lt = le if isinstance(le, str) else (le.get("tags") or "")
            keep = [t.strip() for t in lt.split(",") if t.strip().lower() in DETAIL_ATMOS]
            tags.append(", ".join(keep + ["still life", "depth of field", "blurry background"]))
            if isinstance(le, dict) and le.get("neg"):
                negs.append(le["neg"])
        else:
            add(le, "w_loc")
    props = cut.get("props") or []
    if isinstance(props, str):
        props = [x.strip() for x in props.split(",") if x.strip()]
    for p in props:
        pr = w.get("props") or {}
        if p not in pr:
            print("[warn] cut %d: prop '%s' is not in world.props" % (cid, p))
        add(pr.get(p), "w_prop_%s" % p)
    for key in ("wear", "state"):
        for i, e in enumerate(w.get(key) or []):
            if cid in _parse_range(e.get("cuts")):
                who = e.get("who")
                if who and (_is_duo(cut) or str(cut.get("_charkey", "")) != str(who)):
                    continue
                add(e, "w_%s%d" % (key, i))
    if str(cut.get("char", "")).lower() == "none":
        add(w.get("object_cut"), "w_object")
    if w.get("neg_always"):
        negs.append(w["neg_always"])
    return ", ".join(t for t in tags if t), ", ".join(n for n in negs if n), qa


# 교훈: 이 모델은 영어 문장이 아니라 Danbooru/e621 '태그 사전'으로 알아들음.
#   'spatula'(Danbooru 3,450건) = 뒤집개 / 'cake pan'은 태그 없음 -> 프라이팬 / 'burnt cake' -> 초코케이크.
# 그래서 실행 전에 콘티 문구를 태그 사전(tags/danbooru.csv, tags/e621.csv — a1111 tagcomplete 공개 목록)과 대조해 경고.
_TAGDB = None
_COLORS = ("red", "pink", "blue", "navy", "dark", "light", "white", "black", "grey", "gray", "brown", "yellow",
           "green", "orange", "purple", "gold", "silver", "beige", "cream")


def _world_role(c, cut, who):
    """두 명 컷에서 한 사람 몫의 wear/state (who가 그 사람인 것만) -> (태그, 부정태그, 검수질문)"""
    w = (c or {}).get("world") or {}
    cid = int(cut["id"])
    tags, negs, qa = [], [], []
    for key in ("wear", "state"):
        for i, e in enumerate(w.get(key) or []):
            if str(e.get("who", "")) != str(who) or cid not in _parse_range(e.get("cuts")):
                continue
            if e.get("tags"):
                tags.append(e["tags"])
            if e.get("neg"):
                negs.append(e["neg"])
            if e.get("qa"):
                it = dict(e["qa"])
                it.setdefault("id", "w_%s%d" % (key, i))
                it.setdefault("must", False)
                qa.append(it)
    return ", ".join(tags), ", ".join(negs), qa


def _load_tagdb(kit):
    global _TAGDB
    if _TAGDB is not None:
        return _TAGDB
    import csv
    db = {}
    for name in ("danbooru.csv", "e621.csv"):
        p = os.path.join(kit, "tags", name)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 3:
                    continue
                try:
                    cnt = int(row[2] or 0)
                except ValueError:
                    continue
                key = row[0].strip().lower()
                db[key] = max(db.get(key, 0), cnt)
                if len(row) > 3 and row[3]:
                    for al in row[3].split(","):
                        al = al.strip().lower()
                        if al:
                            db[al] = max(db.get(al, 0), cnt)
    _TAGDB = db
    return db


def _tag_key(t):
    """'(red plaid scarf:1.2)' -> red_plaid_scarf / 'calendar \\(object\\)' -> calendar_(object)"""
    import re
    t = t.strip()
    m = re.match(r"^\((.+):\s*[\d.]+\)$", t)          # ComfyUI weight syntax
    if m:
        t = m.group(1)
    t = t.replace("\\(", "(").replace("\\)", ")")      # escaped parentheses
    return t.strip().lower().replace(" ", "_")


def _tag_verdict(db, t, weak=300):
    """-> (status, count)  status: ok / color+tag / weak / NOT A TAG"""
    k = _tag_key(t)
    if not k:
        return "ok", 0
    n = db.get(k, 0)
    if n >= weak:
        return "ok", n
    words = k.split("_")                      # 'red_yarn_ball' -> red + yarn_ball
    i = 0
    while i < len(words) - 1 and words[i] in _COLORS:
        i += 1
    if i:
        rest = "_".join(words[i:])
        if db.get(rest, 0) >= weak:
            return "color+tag", db[rest]
    return ("weak" if n else "NOT A TAG"), n


def tag_report(kit, conti, cuts, quiet_ok=True):
    """print tag-dictionary warnings for these cuts. returns number of problems."""
    db = _load_tagdb(kit)
    if not db:
        print("[note] tag check skipped: tags/danbooru.csv, tags/e621.csv not found")
        return 0
    bad = 0
    for ct in cuts:
        wt, _, _ = _world_for(conti, ct)
        roles = [str(r.get("pos", "")) for r in (ct.get("cast") or [])]
        text = ", ".join(x for x in [ct.get("scene"), ct.get("extra"), wt] + roles if x)
        probs = []
        for t in [x for x in text.split(",") if x.strip()]:
            st, n = _tag_verdict(db, t)
            if st in ("weak", "NOT A TAG"):
                probs.append("%s(%s)" % (t.strip(), st if st != "weak" else "%d posts" % n))
        if probs:
            bad += len(probs)
            print("[tags] cut %d: %s" % (int(ct["id"]), "; ".join(probs)))
        elif not quiet_ok:
            print("[tags] cut %d: ok" % int(ct["id"]))
    if bad:
        print("[tags] %d phrases are not tags (or rare). The model reads them as loose words -> "
              "relations/actions usually get lost. Rewrite with tags if the result is wrong." % bad)
    return bad


# 실측(256px 회색조): 백지 = 명암편차 1.5~11 / 새까만 1차 컷21 = 평균밝기 15 / 정상 그림 = 편차 48~83
def _blank_check(path):
    from PIL import Image, ImageStat
    g = Image.open(path).convert("L").resize((256, 256))
    s = ImageStat.Stat(g)
    mean, std = s.mean[0], s.stddev[0]
    if std < 25:
        return "blank (almost no contrast, std %.0f)" % std
    # 4차 수정: 어둡기만 한 건 탈락시키지 않음. 어두운데 명암도 없어야 탈락.
    #   실측: 1차 컷21(읽을 수 없는 검정) 평균 15·편차 26 / 4차 컷21 오븐 불꽃·컷2 스포트라이트 달력 평균 22~32·편차 43~52 (연출로 쓸 만함)
    if mean < 35 and std < 40:
        return "too dark (mean %.0f, std %.0f)" % (mean, std)
    if mean > 235:
        return "washed out (mean %.0f)" % mean
    sp = _split_score(path)
    if sp >= 0.75:
        return "split into two panels (vertical seam %.2f)" % sp
    bd = _border_sides(path)
    if bd:
        return "black border / letterbox on %s" % bd
    return None


def _border_sides(path):
    """가장자리 2% 띠가 균일한 검정인 변."""
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(path).convert("L")).astype(np.float32)
    H, W = a.shape
    e = max(4, int(0.02 * min(H, W)))
    out = [k for k, v in (("left", a[:, :e]), ("right", a[:, -e:]), ("top", a[:e, :]), ("bottom", a[-e:, :]))
           if v.mean() < 10 and v.std() < 12]
    return ", ".join(out)


def _split_score(path):
    """두 칸 만화처럼 가운데가 세로로 갈라진 그림 점수 (0~1). Anima 구도가 가끔 이렇게 그림
    가운데 60% 폭에서, 위에서 아래까지 거의 끊김 없이 이어지는 세로 경계선이 있는 열의 비율.
    측정: 갈라진 그림 8장 0.82~1.00(1장 0.37 놓침) / 멀쩡한 그림 66장 최대 0.70(나무 기둥) -> 문턱 0.75"""
    import numpy as np
    from PIL import Image
    im = np.asarray(Image.open(path).convert("L").resize((512, 512)), dtype=np.float32)
    strong = np.abs(im[:, 1:] - im[:, :-1]) > 25
    cover = (strong[:, :-1] | strong[:, 1:]).mean(axis=0)
    w = cover.shape[0]
    return float(cover[int(w * 0.2):int(w * 0.8)].max())


# 콘티에 shot(거리)·angle(각도)을 따로 적으면 코드가 태그로 바꿔 붙이고, 반복·누락을 검사함.
# 태그는 전부 태그 사전으로 확인한 것 (Danbooru 게시물 수: full body 80만, cowboy shot 55만, from above 9.9만 ...)
SHOTS = {
    "wide":   "wide shot, full body, scenery",   # 장소 소개(전경). 인물이 작게 -> 얼굴 뭉개질 위험, 표정 컷으로 쓰지 말 것
    "full":   "full body",                        # 전신 (동작)
    "knee":   "cowboy shot",                      # 허벅지까지 (몸짓+표정)
    "waist":  "upper body",                       # 상반신 (대화)
    "face":   "portrait, close-up",               # 얼굴 (감정)
    "detail": "close-up",                         # 사물·손 클로즈업 (char: none 컷 등)
    "eyes":   "close-up, eye focus",
    "hands":  "close-up, hand focus, head out of frame",
}
ANGLES = {
    "eye":   "",                                  # 눈높이 (기본, 중립)
    "high":  "from above",                        # 내려다봄 -> 작고 약해 보임 (좌절·슬픔)
    "low":   "from below",                        # 올려다봄 -> 크고 결연해 보임 (결심·위압)
    "side":  "from side",                         # 옆 -> 이동·동작 (방향은 결과 보고 flip)
    "back":  "from behind",                       # 뒷모습 (LoRA가 약함, Phase 3 전까지는 아껴 쓸 것)
    "tilt":  "dutch angle",                       # 기울임 -> 당황·혼란
    "pov":   "pov",                               # 화면 밖 인물(미코)의 눈 -> 캐릭터가 이쪽을 봄
}
_BIG_ACTION = ("dynamic pose", "jumping", "pouncing", "running")
_LIGHT_WORDS = ("sunlight", "light", "lamp", "fire", "burning", "backlighting", "light rays", "window", "daylight", "ceiling light")


def _camera_tags(cut):
    """shot/angle -> tags. unknown keys are reported by conti_check."""
    shot = str(cut.get("shot", ""))
    st = SHOTS.get(shot, "")
    if shot == "wide" and str(cut.get("char", "")).lower() != "none":
        st = "wide shot, full body"
    return _joined(st, ANGLES.get(str(cut.get("angle", "")), ""))


OVERLAP_TAGS = {"hug", "hugging", "hug from behind", "holding hands", "carrying", "carrying person", "piggyback",
                "princess carry", "sitting on lap", "sitting on person", "lap pillow", "arm around shoulder",
                "arm around waist", "hand on another's shoulder", "hand on another's head", "headpat", "kiss",
                "cheek-to-cheek", "back-to-back", "leaning on person", "cuddling", "hand on another's cheek"}
REACH_TAGS = {"giving", "feeding", "sharing food", "handshake", "high five", "incoming food", "holding another's arm",
              "pointing at another"}


def conti_check(conti, cuts=None):
    """연출 검사 (그림 안 그림). returns list of warning strings. 규칙 근거는 docs/conti_rules.md"""
    cuts = cuts if cuts is not None else conti.get("cuts", [])
    w = conti.get("world") or {}
    warn = []
    seen_loc = set()
    prev = []                     # (shot, angle) of previous character cuts
    per_page_action = {}
    stats = {}
    for ct in conti.get("cuts", []):
        cid = int(ct["id"]); pg = int(ct.get("page", 0))
        obj = str(ct.get("char", "")).lower() == "none"
        sh, an = ct.get("shot"), ct.get("angle", "eye")
        scene = str(ct.get("scene", ""))
        tags = [t.strip() for t in scene.split(",")]
        mine = (cuts is None) or any(int(x["id"]) == cid for x in cuts)
        def W(msg):
            m = "cut %d: %s" % (cid, msg)
            if mine and m not in warn:
                warn.append(m)
        if ct.get("cast"):
            cast = ct["cast"]
            sides = [str(r.get("side", "")) for r in cast]
            if len(cast) != 2:
                W("cast는 두 명만 지원 (지금 %d명)" % len(cast))
            if any(x not in SIDES for x in sides if not any(r.get("span") for r in cast)):
                W("cast side는 right / left")
            elif len(set(sides)) != len(sides):
                W("두 사람 side가 같음 -> 한 명은 right, 한 명은 left")
            low = [t.lower() for t in tags]
            if "solo" in low:
                W("두 명 컷 scene에 solo")
            if not any(t in low for t in ("duo", "2boys", "2girls", "1boy 1girl", "multiple boys")):
                W("두 명 컷 scene에 인원수 태그(duo, 2boys) 없음 -> 한 명만 그려질 수 있음")
            if any(not r.get("pos") for r in cast):
                W("cast에 pos(그 사람 동작·표정) 없는 사람이 있음")
            alltags = set(low)
            for r in cast:
                alltags |= set(t.strip().lower() for t in str(r.get("pos", "")).split(",") if t.strip())
            touch_ok = "D1" in (conti.get("rules_off") or [])
            hit = [] if touch_ok else sorted(alltags & OVERLAP_TAGS)
            if hit:
                W("두 명 컷에 몸이 겹치는 동작 %s -> 나란히 두고, 필요하면 손·얼굴 클로즈업 컷으로 따로 (규칙서 두 명 컷)" % ", ".join(hit))
            reach = [] if touch_ok else sorted(alltags & REACH_TAGS)
            if reach:
                W("두 명 컷에 손이 상대 자리로 넘어가는 동작 %s -> 경계에서 손·소품이 깨질 수 있음. modes: \"N,C0.75\" 또는 손 클로즈업 컷 권장" % ", ".join(reach))
        for q in (ct.get("qa") or []):          # 판별기 검사 항목: 문턱이 있어야 함
            if q.get("tag") and q.get("min") is None and q.get("max") is None:
                W("qa tag '%s'에 min 또는 max 문턱이 없음 (예: {tag: flower, max: 0.8})" % q["tag"])
        if obj and sh is None:
            sh = "detail"                      # 사물 컷 기본값
        if sh is None:
            W("shot 없음 (wide/full/knee/waist/face/detail 중 하나)")
        elif sh not in SHOTS:
            W("모르는 shot '%s'" % sh)
        if an not in ANGLES:
            W("모르는 angle '%s'" % an)
        cam_now = [y.strip() for y in (_camera_tags(ct) or "").split(",") if y.strip()]
        for t in tags:
            for v in list(SHOTS.values()) + [x for x in ANGLES.values() if x]:
                if t and t in [y.strip() for y in v.split(",")] and t not in ("close-up",):
                    if t in cam_now:
                        W("scene에 카메라 태그 '%s' — shot/angle 칸에서도 붙어서 두 번 들어감" % t)
                    elif not ct.get("keep_order"):   # keep_order: 시험한 태그 순서를 그대로 쓰려고 일부러 scene에 둔 컷
                        W("scene에 카메라 태그 '%s' — shot/angle 칸에 쓰는 게 규칙 (시험 순서를 지키려면 keep_order: true)" % t)
        if any(":" in t and t.startswith("(") for t in tags):
            W("강조 괄호 (x:1.2) — 색이 그림 전체로 번질 수 있음")
        if obj:
            txt = " ".join([scene, str(ct.get("extra", "")), _world_for(conti, ct)[0]])
            if not any(k in txt for k in _LIGHT_WORDS):
                W("사물 컷인데 빛 태그 없음 -> 새까맣게 나올 위험")
        loc = ct.get("loc")
        if loc and obj and str(ct.get("shot", "")) == "wide":
            lentry = ((w.get("locations") or {}).get(loc) or {})
            seen_loc.add(lentry.get("same_as", loc) if isinstance(lentry, dict) else loc)
        if loc and not obj:
            lentry = ((w.get("locations") or {}).get(loc) or {})
            place = lentry.get("same_as", loc) if isinstance(lentry, dict) else loc
            if place not in seen_loc and sh not in ("wide", "full"):
                W("장소 '%s' 첫 등장인데 전경(wide/full)이 아님 -> 독자가 어디인지 모름" % loc)
            seen_loc.add(place)
        if not obj and sh is not None:
            key = (sh, an or "eye")
            stats[key] = stats.get(key, 0) + 1
            if len(prev) >= 2 and prev[-1] == key and prev[-2] == key:
                W("같은 거리·각도 3연속 (%s/%s) — 하나는 바꿀 것" % key)
            if sh in ("waist", "face") and (an or "eye") == "eye" and len(prev) >= 2 and \
                    all(p[0] in ("waist", "face") and p[1] == "eye" for p in prev[-2:]):
                W("정면 상반신·얼굴 3연속 — 정면샷이 반복됨")
            prev.append(key)
            if any(a in tags for a in _BIG_ACTION):
                per_page_action.setdefault(pg, []).append(cid)
    for pg, ids in sorted(per_page_action.items()):
        if len(ids) > 2 and (cuts is None or any(int(x["id"]) in ids for x in cuts)):
            warn.append("page %d: 큰 동작 컷 %d개 (%s) — 페이지당 1~2개 권장" % (pg, len(ids), ids))
    n = sum(stats.values())
    if n:
        front = sum(v for (sh, an), v in stats.items() if sh in ("waist", "face") and an == "eye")
        if front * 2 > n:
            warn.append("전체: 정면 상반신·얼굴이 캐릭터 컷의 %d/%d — 절반 이하로" % (front, n))
    return warn


def _print_check(conti, cuts=None):
    ws = conti_check(conti, cuts)
    for x in ws:
        print("[direction] " + x)
    return len(ws)


# 해결: ComfyUI 기본 기능(2024-12~) '훅 LoRA' — LoRA를 조건(conditioning)에 붙이고, 조건마다 마스크(영역)를 줌.
#   공통 조건(default) = 장면·장소·카메라 / 영역 조건 = 공통 + 그 캐릭터 태그 + 그 캐릭터 동작, 부정도 영역별.
#   노드 이름·입력 칸은 ComfyUI 소스(comfy_extras/nodes_hooks.py, nodes_mask.py)에서 확인함.
DUO_NODES = ["CreateHookLora", "SetClipHooks", "PairConditioningSetProperties",
             "PairConditioningSetPropertiesAndCombine", "PairConditioningSetDefaultCombine",
             "SolidMask", "MaskComposite"]


def _char_block(ch):
    from_ = [ch["trigger"]] + ([ch["tags_short"]] if ch.get("tags_short") else [])
    return ", ".join(x for x in from_ if x)


def _region_masks(g, W, H, sides, overlap=0.06):
    """sides: {'L': (x0_frac, x1_frac), ...} -> {'L': node_ref}. 0 바탕에 1 직사각형을 더하는 방식"""
    g["50"] = {"class_type": "SolidMask", "inputs": {"value": 0.0, "width": W, "height": H}}
    out = {}
    nid = 51
    for key, (a, b) in sides.items():
        x0 = max(0, int(W * (a - overlap))); x1 = min(W, int(W * (b + overlap)))
        g[str(nid)] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": max(8, x1 - x0), "height": H}}
        g[str(nid + 1)] = {"class_type": "MaskComposite",
                           "inputs": {"destination": ["50", 0], "source": [str(nid), 0], "x": x0, "y": 0,
                                      "operation": "add"}}
        out[key] = [str(nid + 1), 0]
        nid += 2
    return out


def build_duo_graph(cfg, s, base_pos, base_neg, regions, seed, prefix):
    """regions: list of dict(char=<char dict>, pos=<region positive text>, neg=<region negative text>, span=(a,b))
    한 캐릭터만 LoRA가 있어도 되고 둘 다 있어도 됨 (각자 자기 영역에만 걸림)."""
    g = {}
    W, H = int(s["width"]), int(s["height"])
    g["4"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}
    g["40"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_pos, "clip": ["4", 1]}}
    g["41"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_neg, "clip": ["4", 1]}}
    masks = _region_masks(g, W, H, {str(i): r["span"] for i, r in enumerate(regions)})
    pair = None
    for i, r in enumerate(regions):
        clip = ["4", 1]
        ch = r["char"]
        lora = r.get("lora") or (ch.get("lora") if ch else None)
        if lora:
            st = float(r.get("strength", ch.get("lora_strength", 1.0)))
            g["%d" % (60 + i * 10)] = {"class_type": "CreateHookLora",
                                       "inputs": {"lora_name": lora, "strength_model": st, "strength_clip": st}}
            g["%d" % (61 + i * 10)] = {"class_type": "SetClipHooks",
                                       "inputs": {"clip": ["4", 1], "apply_to_conds": True, "schedule_clip": False,
                                                  "hooks": ["%d" % (60 + i * 10), 0]}}
            clip = ["%d" % (61 + i * 10), 0]
        g["%d" % (62 + i * 10)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["pos"], "clip": clip}}
        g["%d" % (63 + i * 10)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"], "clip": clip}}
        pn, nn = ["%d" % (62 + i * 10), 0], ["%d" % (63 + i * 10), 0]
        nid = "%d" % (64 + i * 10)
        if pair is None:
            g[nid] = {"class_type": "PairConditioningSetProperties",
                      "inputs": {"positive_NEW": pn, "negative_NEW": nn, "strength": 1.0,
                                 "set_cond_area": "default", "mask": masks[str(i)]}}
        else:
            g[nid] = {"class_type": "PairConditioningSetPropertiesAndCombine",
                      "inputs": {"positive": pair[0], "negative": pair[1], "positive_NEW": pn, "negative_NEW": nn,
                                 "strength": 1.0, "set_cond_area": "default", "mask": masks[str(i)]}}
        pair = ([nid, 0], [nid, 1])
    g["90"] = {"class_type": "PairConditioningSetDefaultCombine",
               "inputs": {"positive": pair[0], "negative": pair[1], "positive_DEFAULT": ["40", 0],
                          "negative_DEFAULT": ["41", 0]}}
    g["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}
    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                         "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": 1.0,
                         "model": ["4", 0], "positive": ["90", 0], "negative": ["90", 1], "latent_image": ["5", 0]}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


#   "mat1 and mat2 must have the same dtype, but got Half and BFloat16" 로 멈춤 (훅 LoRA 가중치와 모델 숫자형식 불일치로 추정).
#   -> C 방식: 이미 잘 돌아가는 표준 부품만 씀.
#   1단계(P) LoRA 없이, 캐릭터 프롬프트를 각자 자리에만 (ConditioningSetMask). 부정 태그도 자리별.
#   2단계    LoRA가 있는 캐릭터 자리만, 그 LoRA로 다시 그림 (SetLatentNoiseMask + 가장자리 부드럽게 FeatherMask)
def build_duo2_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, denoise=0.6, pass1_only=False, hires=None):
    g = {}
    W, H = int(s["width"]), int(s["height"])
    g["4"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}
    masks = _region_masks(g, W, H, {str(i): r["span"] for i, r in enumerate(regions)})
    g["40"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_pos, "clip": ["4", 1]}}
    g["41"] = {"class_type": "CLIPTextEncode", "inputs": {"text": base_neg, "clip": ["4", 1]}}
    pos, neg = ["40", 0], ["41", 0]
    for i, r in enumerate(regions):
        b = 100 + i * 10
        g[str(b)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["pos1"], "clip": ["4", 1]}}
        g[str(b + 1)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"], "clip": ["4", 1]}}
        g[str(b + 2)] = {"class_type": "ConditioningSetMask",
                         "inputs": {"conditioning": [str(b), 0], "mask": masks[str(i)], "strength": 1.0, "set_cond_area": "default"}}
        g[str(b + 3)] = {"class_type": "ConditioningSetMask",
                         "inputs": {"conditioning": [str(b + 1), 0], "mask": masks[str(i)], "strength": 1.0, "set_cond_area": "default"}}
        g[str(b + 4)] = {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": pos, "conditioning_2": [str(b + 2), 0]}}
        g[str(b + 5)] = {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": neg, "conditioning_2": [str(b + 3), 0]}}
        pos, neg = [str(b + 4), 0], [str(b + 5), 0]
    g["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}
    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]), "sampler_name": s["sampler"],
                         "scheduler": s["scheduler"], "denoise": 1.0, "model": ["4", 0], "positive": pos, "negative": neg,
                         "latent_image": ["5", 0]}}
    last = ["3", 0]
    if not pass1_only:
        for i, r in enumerate(regions):
            ch = r["char"]
            if not (ch and ch.get("lora")):
                continue
            b = 200 + i * 10
            st = float(ch.get("lora_strength", 1.0))
            g[str(b)] = {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": ch["lora"],
                                                                "strength_model": st, "strength_clip": st}}
            g[str(b + 1)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["pos"], "clip": [str(b), 1]}}
            g[str(b + 2)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"], "clip": [str(b), 1]}}
            fe = int(W * 0.05)
            g[str(b + 3)] = {"class_type": "FeatherMask", "inputs": {"mask": masks[str(i)], "left": fe, "top": 0, "right": fe, "bottom": 0}}
            g[str(b + 4)] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": last, "mask": [str(b + 3), 0]}}
            g[str(b + 5)] = {"class_type": "KSampler",
                             "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                        "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(denoise),
                                        "model": [str(b), 0], "positive": [str(b + 1), 0], "negative": [str(b + 2), 0],
                                        "latent_image": [str(b + 4), 0]}}
            last = [str(b + 5), 0]
    fixes = [] if pass1_only else [(str(200 + i * 10), [str(200 + i * 10), 0]) for i, r in enumerate(regions)
                                   if r["char"] and r["char"].get("lora")]
    # C 방식 2단계 부품 번호: 200+i*10 = LoRA, +1/+2 = 조건, +3 = 가장자리 마스크 -> _duo_hires가 쓰는 (조건, 마스크) 번호와 맞춤
    last = _duo_hires(g, s, seed, last, hires, ["4", 0], pos, neg, fixes, cond_off=1, mask_off=3)
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": last, "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}}
    return g


def _duo_hires(g, s, seed, last, hires, model1, pos1, neg1, fixes, cond_off=0, mask_off=3):
    """두 명 컷 최종본(고해상도). 초안과 같은 순서를 크게 한 번 더:
       1) 초안 결과를 1.5배로 키워 1단계 모델·영역 조건으로 살짝(0.35) 다시 그림
       2) 2단계에서 고친 자리만 그 모델로 다시 살짝 그림 -> 1)에서 LoRA가 번진 것을 지움
       fixes: [(부품 번호 b, 모델)] - 조건은 b+cond_off / b+cond_off+1, 가장자리 마스크는 b+mask_off
       영역 마스크는 초안 크기지만 ComfyUI가 샘플링 시작 때 잠재 크기로 늘려 줌 (samplers.py resolve_areas_and_cond_masks_multidim)"""
    if not hires or float(hires.get("scale", 0) or 0) <= 1.0:
        return last
    dn = float(hires.get("denoise", 0.35)); st = int(hires.get("steps", 20))
    g["400"] = {"class_type": "VAEDecode", "inputs": {"samples": last, "vae": ["4", 2]}}
    g["401"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["400", 0], "upscale_method": "lanczos",
                                                          "scale_by": float(hires["scale"])}}
    g["402"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["401", 0], "vae": ["4", 2]}}
    g["403"] = {"class_type": "KSampler",
                "inputs": {"seed": int(seed), "steps": st, "cfg": float(s["cfg"]), "sampler_name": s["sampler"],
                           "scheduler": s["scheduler"], "denoise": dn, "model": model1, "positive": pos1,
                           "negative": neg1, "latent_image": ["402", 0]}}
    last = ["403", 0]
    for k, (b, model) in enumerate(fixes):
        b = int(b)
        n = 450 + k * 10
        g[str(n)] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": last, "mask": [str(b + mask_off), 0]}}
        g[str(n + 1)] = {"class_type": "KSampler",
                         "inputs": {"seed": int(seed), "steps": st, "cfg": float(s["cfg"]), "sampler_name": s["sampler"],
                                    "scheduler": s["scheduler"], "denoise": dn, "model": model,
                                    "positive": [str(b + cond_off), 0], "negative": [str(b + cond_off + 1), 0],
                                    "latent_image": [str(n), 0]}}
        last = [str(n + 1), 0]
    return last


DUO2_NODES = ["ConditioningSetMask", "ConditioningCombine", "SetLatentNoiseMask", "FeatherMask", "SolidMask", "MaskComposite"]

# '아무 캐릭터'로 뼈대가 잡힌 뒤 0.6으로 덧칠만 해서 형태가 무너짐.
#       (lilting 2026-05 실험에서 '한 명 고정 + 나머지 인페인트'가 가장 안정적이었던 방식)
#       (작은 얼굴·무늬는 픽셀이 모자라서 깨짐 -> 디테일러와 같은 원리)
COUNT_TAGS = {"duo", "trio", "group", "1boy", "2boys", "3boys", "1girl", "2girls", "3girls", "multiple boys",
              "multiple girls", "solo"}


def _strip_counts(text):
    return ", ".join(t.strip() for t in text.split(",") if t.strip() and t.strip().lower() not in COUNT_TAGS)


def build_duo3_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, mode, fix_dn=0.7, refine_dn=None,
                     refine_scale=1.5, hires=None):
    g = {}
    W, H = int(s["width"]), int(s["height"])
    L = next(i for i, r in enumerate(regions) if r["char"].get("lora"))
    ch = regions[L]["char"]
    g["4"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": cfg["checkpoint"]}}
    st = float(ch.get("lora_strength", 1.0))
    g["200"] = {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": ch["lora"],
                                                        "strength_model": st, "strength_clip": st}}
    masks = _region_masks(g, W, H, {str(i): r["span"] for i, r in enumerate(regions)})
    scene = _strip_counts(base_pos)
    g1_pos = base_pos if mode == "N" else scene
    g["40"] = {"class_type": "CLIPTextEncode", "inputs": {"text": g1_pos, "clip": ["200", 1]}}
    g1_neg = base_neg if mode == "N" else clean_join(base_neg, "duo, 2boys, multiple boys")
    g["41"] = {"class_type": "CLIPTextEncode", "inputs": {"text": g1_neg, "clip": ["200", 1]}}
    pos, neg = ["40", 0], ["41", 0]
    for i, r in enumerate(regions):
        b = 100 + i * 10
        if i == L:
            txt = r["posL"] if mode == "N" else "solo, " + r["posL"]
        else:
            txt = r["pos1"] if mode == "N" else "no humans, scenery"
        g[str(b)] = {"class_type": "CLIPTextEncode", "inputs": {"text": txt, "clip": ["200", 1]}}
        g[str(b + 1)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"] if (mode == "N" or i == L) else base_neg,
                                                                     "clip": ["200", 1]}}
        g[str(b + 2)] = {"class_type": "ConditioningSetMask",
                         "inputs": {"conditioning": [str(b), 0], "mask": masks[str(i)], "strength": 1.0, "set_cond_area": "default"}}
        g[str(b + 3)] = {"class_type": "ConditioningSetMask",
                         "inputs": {"conditioning": [str(b + 1), 0], "mask": masks[str(i)], "strength": 1.0, "set_cond_area": "default"}}
        g[str(b + 4)] = {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": pos, "conditioning_2": [str(b + 2), 0]}}
        g[str(b + 5)] = {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": neg, "conditioning_2": [str(b + 3), 0]}}
        pos, neg = [str(b + 4), 0], [str(b + 5), 0]
    g["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}
    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]), "sampler_name": s["sampler"],
                         "scheduler": s["scheduler"], "denoise": 1.0, "model": ["200", 0], "positive": pos, "negative": neg,
                         "latent_image": ["5", 0]}}
    last = ["3", 0]
    # ---- 2단계: LoRA 없는 모델로 다른 캐릭터 자리만 (N: 고치기 fix_dn / E: 새로 그리기 1.0)
    for i, r in enumerate(regions):
        if i == L:
            continue
        b = 250 + i * 10
        g[str(b)] = {"class_type": "CLIPTextEncode", "inputs": {"text": clean_join(scene, r["posL"]), "clip": ["4", 1]}}
        g[str(b + 1)] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"], "clip": ["4", 1]}}
        fe = int(W * 0.05)
        g[str(b + 3)] = {"class_type": "FeatherMask", "inputs": {"mask": masks[str(i)], "left": fe, "top": 0, "right": fe, "bottom": 0}}
        g[str(b + 4)] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": last, "mask": [str(b + 3), 0]}}
        g[str(b + 5)] = {"class_type": "KSampler",
                         "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                                    "sampler_name": s["sampler"], "scheduler": s["scheduler"],
                                    "denoise": float(fix_dn) if mode == "N" else 1.0,
                                    "model": ["4", 0], "positive": [str(b), 0], "negative": [str(b + 1), 0],
                                    "latent_image": [str(b + 4), 0]}}
        last = [str(b + 5), 0]
    last = _duo_hires(g, s, seed, last, hires, ["200", 0], pos, neg,
                      [(str(250 + i * 10), ["4", 0]) for i in range(len(regions)) if i != L])
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": last, "vae": ["4", 2]}}
    img = ["8", 0]
    if refine_dn:
        a, bb = regions[L]["span"]
        x0 = max(0, int(W * (a - 0.06))); x1 = min(W, int(W * (bb + 0.06)))
        cw = x1 - x0
        W2 = int(cw * refine_scale) // 8 * 8; H2 = int(H * refine_scale) // 8 * 8
        r = regions[L]
        g["300"] = {"class_type": "ImageCrop", "inputs": {"image": img, "width": cw, "height": H, "x": x0, "y": 0}}
        g["301"] = {"class_type": "ImageScale", "inputs": {"image": ["300", 0], "upscale_method": "lanczos",
                                                            "width": W2, "height": H2, "crop": "disabled"}}
        g["302"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["301", 0], "vae": ["4", 2]}}
        g["303"] = {"class_type": "CLIPTextEncode", "inputs": {"text": clean_join(scene, r["posL"]), "clip": ["200", 1]}}
        g["304"] = {"class_type": "CLIPTextEncode", "inputs": {"text": r["neg"], "clip": ["200", 1]}}
        g["305"] = {"class_type": "KSampler",
                    "inputs": {"seed": int(seed), "steps": int(s["steps"]), "cfg": float(s["cfg"]),
                               "sampler_name": s["sampler"], "scheduler": s["scheduler"], "denoise": float(refine_dn),
                               "model": ["200", 0], "positive": ["303", 0], "negative": ["304", 0],
                               "latent_image": ["302", 0]}}
        g["306"] = {"class_type": "VAEDecode", "inputs": {"samples": ["305", 0], "vae": ["4", 2]}}
        g["307"] = {"class_type": "ImageScale", "inputs": {"image": ["306", 0], "upscale_method": "lanczos",
                                                            "width": cw, "height": H, "crop": "disabled"}}
        sx0 = int(W * a); sx1 = int(W * bb)
        sw = sx1 - sx0
        fe = int(sw * 0.12)
        g["311"] = {"class_type": "ImageCrop", "inputs": {"image": ["307", 0], "width": sw, "height": H, "x": sx0 - x0, "y": 0}}
        g["308"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": sw, "height": H}}
        g["309"] = {"class_type": "FeatherMask", "inputs": {"mask": ["308", 0], "left": fe if sx0 > 0 else 0, "top": 0,
                                                             "right": fe if sx1 < W else 0, "bottom": 0}}
        g["310"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": img, "source": ["311", 0], "x": sx0, "y": 0,
                                                                     "resize_source": False, "mask": ["309", 0]}}
        img = ["310", 0]
    g["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": img}}
    return g


def clean_join(*parts):
    seen, out = set(), []
    for p in parts:
        for t in str(p or "").split(","):
            t = t.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower()); out.append(t)
    return ", ".join(out)


DUO3_NODES = DUO2_NODES + ["LoraLoader", "ImageCrop", "ImageScale", "VAEEncode", "ImageCompositeMasked"]


def _plain_settings(nk, cfg, size, artist):
    ns = argparse.Namespace(preset=artist, extra=None, neg=None, lora=None, size=size, rating=None, cfg=None,
                            steps=None, sampler=None, scheduler=None, quality=None, year=None, artist=None,
                            artist_weight=None, artist_position=None, tags=None, strength=None, charlora=None,
                            hires=0, hires_denoise=None, hires_steps=None, hires_method=None, upscale_model=None)
    return nk.build_settings(cfg, ns)


def duotest(nk, kit, args):
    """episodes/<ep>/duotest.yaml 을 읽어
       - duo:   같은 시드로 A vs B(영역별 LoRA)
       결과: runs/<ep>/duotest/ 에 그림 + 장면별 비교표(grid)"""
    from PIL import Image, ImageDraw
    cfg = nk.load_presets()
    t = nk.load_yaml(os.path.join(ep_dir(kit, args.ep), "duotest.yaml"))
    chars = {k: nk.load_char(v) for k, v in (t.get("chars") or {}).items()}
    artist = args.artist or t.get("artist", "")
    seed0 = int(t.get("seed", 20260923))
    nseed = int(args.seeds or t.get("seeds", 3))
    variants = [v.strip() for v in str(args.variants or t.get("variants", "P,C")).split(",") if v.strip()]
    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    denoise = float(t.get("denoise", 0.6))
    fix_dn = float(t.get("fix_denoise", 0.7))
    refine_dn = float(t.get("refine_denoise", 0.4))
    for v in variants:
        ok = v in ("A", "B", "P", "C", "N", "E", "NR", "ER")
        if not ok and v[:1] in ("C", "N") and not v.startswith("NR"):
            try:
                ok = 0.1 <= float(v[1:]) <= 1.0
            except ValueError:
                ok = False
        if not ok:
            print("[ERROR] unknown variant '%s'. use A, B, P, C, C0.7, N, N0.85, E, NR, ER" % v)
            sys.exit(1)
    run = "%s/duotest_%s" % (args.ep, artist)   # 작가별 폴더: 그림체를 바꿔도 이전 결과를 덮어쓰지 않음
    if args.tag:                                 # 회차 이름: 같은 작가로 다시 돌려도 이전 결과를 덮어쓰지 않음
        run += "_" + args.tag
    plan = []                                   # (scene id, [(variant, label, job)])
    for sc in t.get("solo") or []:
        if only and not any(sc["id"].startswith(o) for o in only):
            continue
        ch = chars[sc["char"]]
        st = _plain_settings(nk, cfg, sc.get("size", t.get("size", "1216x832")), artist)
        pos, neg = nk.compose_prompt(st, ch, nk.clean_tags(sc["scene"]))
        if sc.get("neg"):
            neg = nk.clean_tags(neg + ", " + sc["neg"])
        jobs = []
        for k in range(nseed):
            sd = seed0 + k
            lab = "%s_S_%d" % (sc["id"], k + 1)
            jobs.append(("S", {"label": lab, "graph": nk.build_graph(cfg, st, ch, pos, neg, sd, 1, "nk/%s/%s" % (run.replace("/", "_"), lab)),
                               "positive": pos, "negative": neg, "settings": st, "seed": sd}))
        plan.append((sc["id"], jobs))
    for sc in t.get("duo") or []:
        if only and not any(sc["id"].startswith(o) for o in only):
            continue
        st = _plain_settings(nk, cfg, sc.get("size", t.get("size", "1216x832")), artist)
        base_pos, base_neg = nk.compose_prompt(st, None, nk.clean_tags(sc["base"]))
        roles = sc["roles"]
        # A: 지금 방식 — 한 프롬프트에 두 캐릭터 + LoRA 있는 캐릭터의 LoRA를 그림 전체에
        a_pos = nk.clean_tags(", ".join([base_pos] + ["%s, %s" % (_char_block(chars[r["char"]]), r.get("pos", ""))
                                                      for r in roles]))
        a_neg = nk.clean_tags(", ".join([base_neg] + [chars[r["char"]].get("negative_extra", "") for r in roles]))
        lora_char = next((chars[r["char"]] for r in roles if chars[r["char"]].get("lora")), None)
        # B: 영역별 — 오른쪽/왼쪽 (오른→왼 만화: 먼저 말하는 사람을 오른쪽에)
        span = {"right": (0.5, 1.0), "left": (0.0, 0.5)}
        regions = [{"char": chars[r["char"]], "span": span[r.get("side", "left")],
                    "pos": nk.clean_tags("%s, %s, %s" % (base_pos, _char_block(chars[r["char"]]), r.get("pos", ""))),
                    "neg": nk.clean_tags("%s, %s, %s" % (base_neg, chars[r["char"]].get("negative_extra", ""), r.get("neg", "")))}
                   for r in roles]
        # C/P 1단계용: LoRA가 없는 상태에서도 모양이 잡히게, LoRA 캐릭터는 외형 태그 전부(tags_full)
        for r, reg in zip(roles, regions):
            ch = chars[r["char"]]
            blk = ch["trigger"] + ", " + nk.clean_tags(ch.get("tags_full") or ch.get("tags_short", "")) if ch.get("lora") \
                else _char_block(ch)
            reg["pos1"] = nk.clean_tags("%s, %s" % (blk, r.get("pos", "")))
            reg["posL"] = nk.clean_tags("%s, %s" % (_char_block(ch), r.get("pos", "")))   # N/E용: 트리거 + 짧은 태그
        jobs = []
        for k in range(nseed):
            sd = seed0 + k
            for v in variants:
                lab = "%s_%s_%d" % (sc["id"], v, k + 1)
                pre = "nk/%s/%s" % (run.replace("/", "_"), lab)
                if v == "A":
                    gr, pp, nn = nk.build_graph(cfg, st, lora_char, a_pos, a_neg, sd, 1, pre), a_pos, a_neg
                elif v == "B":
                    gr = build_duo_graph(cfg, st, base_pos, base_neg, regions, sd, pre)
                    pp, nn = " || ".join(r["pos"] for r in regions), " || ".join(r["neg"] for r in regions)
                elif v == "P" or v.startswith("C"):
                    # C0.7 처럼 C 뒤에 숫자를 붙이면 그 값으로 2단계 denoise (같은 시드라 1단계는 P와 같은 그림)
                    dn = float(v[1:]) if len(v) > 1 else denoise
                    gr = build_duo2_graph(cfg, st, base_pos, base_neg, regions, sd, pre, dn, pass1_only=(v == "P"))
                    pp = "BASE: " + base_pos + " || " + " || ".join("R%d(1st): %s" % (i, r["pos1"]) for i, r in enumerate(regions))
                    if v.startswith("C"):
                        pp += " || " + " || ".join("R%d(LoRA pass): %s" % (i, r["pos"]) for i, r in enumerate(regions) if r["char"].get("lora"))
                    nn = " || ".join(r["neg"] for r in regions)
                elif v in ("N", "E", "NR", "ER") or (v.startswith("N") and v[1:2].isdigit()):
                    fdn = float(v[1:]) if v.startswith("N") and v[1:2].isdigit() else fix_dn
                    gr = build_duo3_graph(cfg, st, base_pos, base_neg, regions, sd, pre, v[0], fdn,
                                          refine_dn if v in ("NR", "ER") else None)
                    pp = " || ".join("R%d: %s" % (i, r["posL"]) for i, r in enumerate(regions))
                    nn = " || ".join(r["neg"] for r in regions)
                else:
                    continue
                jobs.append((v, {"label": lab, "graph": gr, "positive": pp, "negative": nn, "settings": st, "seed": sd}))
        plan.append((sc["id"], jobs))
    total = sum(len(j) for _, j in plan)
    secs = 0
    for _, jobs in plan:
        vs = [v for v, _ in jobs]
        for v in vs:
            if v in ("S", "A"):
                secs += 29
            elif v == "P":
                secs += 75
            elif v.startswith("C"):
                secs += 30 if ("P" in vs or vs.index(v) > vs.index(next(x for x in vs if x.startswith("C")))) else 105
            elif v in ("N", "E"):
                secs += 110 if v == "N" else 100
            elif v.startswith("N") and v[1:2].isdigit():
                secs += 35 if "N" in vs else 110
            elif v in ("NR", "ER"):
                secs += 45 if v[0] in vs else (155 if v == "NR" else 145)
    print("artist: %s -> runs\\%s" % (artist, run.replace("/", "\\")))
    print("duotest: %d images, %d scenes, %d seeds, variants %s -> about %d min"
          % (total, len(plan), nseed, ",".join(variants), secs // 60 + 1))
    if args.dry:
        for sid, jobs in plan:
            for v, j in jobs[:len(variants) + 1]:
                print("\n[%s] %s" % (j["label"], v))
                print("  + " + j["positive"][:900])
                print("  - " + j["negative"][:400])
                hooks = [(n["inputs"]["lora_name"]) for n in j["graph"].values() if n["class_type"] == "CreateHookLora"]
                lls = [(n["inputs"]["lora_name"]) for n in j["graph"].values() if n["class_type"] == "LoraLoader"]
                ks = [n["inputs"]["denoise"] for n in j["graph"].values() if n["class_type"] == "KSampler"]
                print("  LoraLoader: %s | hook LoRA: %s | KSampler denoise: %s | nodes: %d" % (lls, hooks, ks, len(j["graph"])))
        return
    # preflight: 노드가 이 ComfyUI에 있는지 (없으면 몇 초 만에 멈춤)
    c = nk.Comfy(cfg.get("server", "auto"))
    missing = []
    need = set()
    if "B" in variants:
        need |= set(DUO_NODES)
    if any(v in ("P",) or v.startswith("C") for v in variants):
        need |= set(DUO2_NODES)
    if any(v[0] in ("N", "E") for v in variants):   # N0.85 포함
        need |= set(DUO3_NODES)
    for n in sorted(need):
        try:
            if n not in c._get("/object_info/" + n):
                missing.append(n)
        except Exception:
            missing.append(n)
    if missing:
        print("[ERROR] this ComfyUI has no: %s  -> ComfyUI를 최신으로 업데이트해야 함" % ", ".join(missing))
        sys.exit(1)
    print("preflight OK: region-LoRA nodes present")
    out_dir = os.path.join(_root(cfg, kit), run)
    for sid, jobs in plan:
        nk.run_jobs(cfg, [j for _, j in jobs], run + "/" + sid, False)
        # grid: rows = variants, cols = seeds
        folder = os.path.join(out_dir, sid)
        rows = []
        for x, _ in jobs:                        # 변형이 나온 순서대로 한 줄씩
            if x not in rows:
                rows.append(x)
        names = {"S": "단독", "A": "A 한 프롬프트", "B": "B 훅 LoRA", "P": "P 영역만", "C": "C 영역+LoRA %.2g" % denoise,
                 "N": "N LoRA 캐릭터 먼저", "E": "E 빈자리 채우기", "NR": "NR LoRA 먼저+확대", "ER": "ER 빈자리+확대"}
        names.update({x: "C 영역+LoRA %s" % x[1:] for x in rows if x.startswith("C") and len(x) > 1})
        names.update({x: "N LoRA 먼저 %s" % x[1:] for x in rows if x.startswith("N") and x[1:2].isdigit()})
        w0, h0 = int(jobs[0][1]["settings"]["width"]), int(jobs[0][1]["settings"]["height"])
        tw = 560; th = int(h0 * tw / w0)
        font = _font(cfg.get("webtoon", {}).get("font"), 26)
        G = Image.new("RGB", (200 + nseed * (tw + 10), len(rows) * (th + 10) + 50), "white")
        d = ImageDraw.Draw(G)
        d.text((10, 10), sid, fill="black", font=font)
        for r, v in enumerate(rows):
            y = 50 + r * (th + 10)
            d.text((10, y + th // 2), names[v], fill="black", font=font)
            for k in range(nseed):
                f = os.path.join(folder, "%s_%s_%d.png" % (sid, v, k + 1))
                if os.path.exists(f):
                    G.paste(Image.open(f).convert("RGB").resize((tw, th)), (200 + k * (tw + 10), y))
        gp = os.path.join(out_dir, "%s_grid.png" % sid)
        G.save(gp)
        print("grid ->", gp)
    print("\nDONE. 비교표: %s\\*_grid.png" % out_dir)


def _joined(*parts):
    v = ", ".join(str(p) for p in parts if p)
    return v or None


def _gen_size(size):
    if size in SIZES:
        return "%dx%d" % SIZES[size]
    if isinstance(size, str) and "x" in size:
        return size
    return "%dx%d" % SIZES["wide"]


def _cut_char(char, cut):
    """char: none -> None (사물 컷).
    char_drop: "a, b" -> 이 컷만 캐릭터 태그에서 a, b를 뺌.
green-framed eyewear'
      때문에 안경 속 눈이 그려짐 0/2 -> 안경 태그만 빼니 모자가 눈을 덮음 2/2."""
    if str(cut.get("char", "")).lower() == "none":
        return None
    if "_char" in cut:                            # load_conti가 컷마다 캐릭터를 정해 둠 (여러 캐릭터 에피소드)
        char = cut["_char"]
    drop = cut.get("char_drop")
    if not drop or not char:
        return char
    if isinstance(drop, str):
        drop = [x.strip() for x in drop.split(",")]
    drop = set(x.strip().lower() for x in drop if x and x.strip())
    ch = dict(char)
    for key in ("tags_short", "tags_full"):
        if ch.get(key):
            parts = [t.strip() for t in str(ch[key]).replace("\n", " ").split(",")]
            ch[key] = ", ".join(t for t in parts if t and t.lower() not in drop)
    return ch


def picks_path(kit, ep):
    return os.path.join(ep_dir(kit, ep), "picks.json")


def load_picks(kit, ep):
    p = picks_path(kit, ep)
    return {int(k): int(v) for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}


def save_picks(kit, ep, picks):
    json.dump({str(k): v for k, v in sorted(picks.items())}, open(picks_path(kit, ep), "w"), indent=1)


def cut_filter(arg):
    return set(int(x) for x in arg.split(",") if x.strip()) if arg else None


def _root(cfg, kit):
    return cfg.get("output_root", os.path.join(kit, "runs"))


def _cut_folder(cfg, kit, ep, cid):
    return os.path.join(_root(cfg, kit), ep, "cut%02d" % cid)


def _final_file(kit, ep, cid):
    return os.path.join(ep_dir(kit, ep), "cuts", "cut%02d.png" % cid)


def _candidates(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.endswith(".png") and f[:3].isdigit())


# ------------------------------------------------------------------ steps
def _draft_cut(nk, cfg, conti, char, cut, ep, n, seed, dry, start=0):
    """start=0: 새로 그림(옛 후보 삭제). start>0: 적응형 추가 라운드 - 옛 후보 뒤에 번호를 이어서 붙임."""
    cid = int(cut["id"])
    wt, wn, _ = _world_for(conti, cut)          # world -> 장소·소품·의상 태그를 이 컷에 자동으로 붙임
    wt = _joined(_camera_tags(cut), wt)          # shot/angle -> 카메라 태그 (Phase 2)
    if wt:
        print("   world: %s" % wt)
    ns = argparse.Namespace(preset=cut.get("artist", conti.get("artist")),
                            extra=_joined(cut.get("extra"), wt), neg=_joined(cut.get("neg"), wn),
                            lora=None, size=_gen_size(cut["size"]), rating=None,
                            cfg=cut.get("cfg"), steps=None, sampler=None, scheduler=None, quality=None,
                            year=None, artist=None, artist_weight=None, artist_position=None, tags=None,
                            strength=cut.get("strength"), charlora=cut.get("lora"), hires=0, hires_denoise=None, hires_steps=None,
                            hires_method=None, upscale_model=None)
    s = nk.build_settings(cfg, ns)
    s.update(__import__("nk_styleref").cut_settings(conti, cut))
    if _is_duo(cut):
        return _draft_duo(nk, cfg, conti, cut, ep, n, seed, dry, start, s)
    char = _cut_char(char, cut)
    pos, neg = nk.compose_prompt(s, char, nk.resolve_scene(cfg, cut["scene"]))
    if seed is None and cut.get("seed") is not None:
        seed = int(cut["seed"])
    seed0 = (seed + start) if seed is not None else random.randint(1, 2 ** 31)
    run_name = "%s/cut%02d" % (ep, cid)
    folder = os.path.join(_root(cfg, nk.KIT), run_name)
    old_meta = []
    if start == 0:
        if not dry and os.path.isdir(folder):      # old candidates would mix with new ones
            shutil.rmtree(folder)
    elif os.path.exists(os.path.join(folder, "meta.json")):
        old_meta = json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))
    jobs = []
    an = _anima_solo(conti, cut, char, wt)        # 혼자·사물 컷도 Anima 구도 (콘티 anima: 0.55)
    flow = __import__("nk_flow").cut_flow(conti, cut)
    if flow and an:
        print("[flow] cut %d: flow '%s' -> anima 시작 그림은 안 씀 (워크플로가 그림 전체를 맡음)" % (cid, flow))
        an = None
    for i in range(start, start + n):
        sd = seed0 + (i - start)
        label = "%03d_s%d" % (i + 1, sd)
        if flow:
            import nk_flow
            g, parts = nk_flow.solo_graph(nk, nk.KIT, flow, s, char, nk.resolve_scene(cfg, cut["scene"]), sd,
                                          "nk/%s/%s" % (run_name.replace("/", "_"), label))
            jobs.append({"label": label, "graph": g, "positive": parts["%prompt%"], "negative": parts["%negative%"],
                         "settings": s, "seed": sd, "raw": True, "meta": {"flow": flow}})
            continue
        g = nk.build_graph(cfg, s, char, pos, neg, sd, 1, "nk/%s/%s" % (run_name.replace("/", "_"), label))
        job = {"label": label, "graph": g, "positive": pos, "negative": neg, "settings": s, "seed": sd}
        if an:
            _anima_init(g, s, an["text"], sd, an["a1"])
            job["meta"] = {"anima": an}
        jobs.append(job)
    print("\n== cut %d (%s, %d candidates%s)" % (cid, cut["size"], n, ", +%d so far" % start if start else ""))
    res = nk.run_jobs(cfg, jobs, run_name, dry)
    if old_meta and not dry:                        # run_jobs가 meta.json을 새 후보로만 덮어씀 -> 옛 후보 기록을 다시 합침
        json.dump(old_meta + (res or []), open(os.path.join(folder, "meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return folder


SIDES = {"right": (0.5, 1.0), "left": (0.0, 0.5)}


def _duo_modes(conti, cut):
    """후보마다 쓸 방식. 기본 N
    소품을 LoRA 캐릭터가 들어야 하는 컷은 modes: "N,C0.75" 처럼 섞음 (소품 들기 N 0/3, C 2/3)"""
    d = conti.get("duo") or {}
    raw = str(cut.get("modes") or d.get("modes") or "N")
    out = [m.strip() for m in raw.split(",") if m.strip()]
    for m in out:
        ok = m in ("N", "C", "P", "A", "O", "MB") or (m[:1] in ("N", "C", "A") and m[1:2] == "0") \
            or (m[:1] == "O" and all(ch in "0123456789.e" for ch in m[1:])) \
            or (m[:2] == "MB" and m[2:3] == "0" and all(ch in "0123456789." for ch in m[2:]))
        if not ok:
            print("[ERROR] cut %s: unknown duo mode '%s' (N / N0.8 / C / C0.75 / P / A / A0.55 / O / O0.85e0.6 / MB / MB0.9)"
                  % (cut.get("id"), m))
            sys.exit(1)
    return out


def _minus(tags, keep_text):
    """tags 중 keep_text(그 캐릭터의 긍정 태그)에 들어 있는 것은 뺌"""
    have = {t.strip().lower() for t in (keep_text or "").split(",")}
    return ", ".join(t.strip() for t in (tags or "").split(",") if t.strip() and t.strip().lower() not in have
                     and not any(t.strip().lower() in h for h in have))


def _duo_parts(nk, cfg, conti, cut, s):
    """두 명 컷 프롬프트: 공통(장면·장소·카메라·공통 소품) + 사람별(캐릭터 태그 + 그 사람 동작 + 그 사람 옷/상태)
    duotest(시험한 방식)와 같은 조립 규칙 -> 시험 결과가 그대로 통하게"""
    base_pos, base_neg = nk.compose_prompt(s, None, nk.resolve_scene(cfg, cut["scene"]))
    regions = []
    for r, ch in cut["_roles"]:
        others = ", ".join(c2.get("duo_exclusive", "") for r2, c2 in cut["_roles"] if r2 is not r and c2.get("duo_exclusive"))
        side = str(r.get("side", "left"))
        span = tuple(r["span"]) if r.get("span") else SIDES[side]
        wt, wn, _ = _world_role(conti, cut, r["char"])
        rp = _joined(r.get("pos"), wt) or ""
        full = ch["trigger"] + ", " + nk.clean_tags(ch.get("tags_full") or ch.get("tags_short", "")) if ch.get("lora") \
            else _char_block(ch)
        regions.append({"char": ch, "key": str(r["char"]), "span": span, "rp": rp, "anima": ch.get("anima") or "",
                        "pos": nk.clean_tags("%s, %s, %s" % (base_pos, _char_block(ch), rp)),
                        "neg": nk.clean_tags("%s, %s, %s, %s, %s" % (base_neg, ch.get("negative_extra", ""),
                                                                      r.get("neg", ""), wn or "",
                                                                      _minus(others, rp))),
                        "pos1": nk.clean_tags("%s, %s" % (full, rp)),
                        "posL": nk.clean_tags("%s, %s" % (_char_block(ch), rp))})
    return base_pos, base_neg, regions


# Anima(2B, 자연어 이해)는 같은 장면 16장 중 16장에서 두 인물 + 자세 + 소품을 맞게 배치 (원본 확인).
ANIMA = {"unet": "anima-turbo-v1.1.safetensors", "clip": "qwen_3_06b_base.safetensors", "vae": "qwen_image_vae.safetensors",
         "steps": 10, "sampler": "res_multistep", "scheduler": "simple", "shift": 3.0}
ANIMA_NODES = ["UNETLoader", "CLIPLoader", "ModelSamplingAuraFlow", "EmptySD3LatentImage"]
ANIMA_NEG = ("worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration, "
             "nsfw, explicit, realistic, text, watermark, comic, 2koma, split screen, multiple views, "
             "panel border, border")      # 캐릭터마다 다른 부정어는 캐릭터 파일 negative_extra 로
_NOOB_ONLY = ("masterpiece", "best quality", "newest", "absurdres", "highres", "safe", "duo", "2boys")


def _anima_mode(mode, d):
    """'A' / 'A0.55' / 'A0.55f0.5' ->"""
    body = mode[1:]
    a1, af = None, None
    if "f" in body:
        body, fs = body.split("f", 1)
        af = float(fs)
    if body:
        a1 = float(body)
    return (a1 if a1 is not None else float(d.get("anima_denoise", 0.55)),
            af if af is not None else float(d.get("anima_fix", 0.5)))


_CAM_WORDS = {"from behind": "seen from behind, we see their backs", "from above": "seen from above",
              "from below": "seen from below", "from side": "seen from the side", "dutch angle": "tilted camera",
              "wide shot": "a wide shot showing the whole place", "full body": "full body",
              "cowboy shot": "shown from the thighs up", "upper body": "shown from the waist up"}


def _anima_prompt(s, base_pos, regions, interact=False):
    """Anima용 문장: 품질 머리말 + 장면 태그(NoobAI 전용 품질·작가 태그·카메라 태그 뺌) + '한 장면 안에 두 사람' 문장.
On the right, B." 처럼 사람마다 따로 쓰면 1024 정사각에서 두 칸 만화로 갈라짐
    (컷20 1/2·컷28 2/2) + 카메라 태그(from behind)가 무시됨 -> 두 사람을 한 문장으로 묶고 카메라를 문장으로 씀"""
    drop = set(_NOOB_ONLY) | {t.strip().lower() for t in str(s.get("quality_tags", "")).split(",")}
    tags = [t.strip() for t in base_pos.split(",") if t.strip()]
    cam = [t for t in tags if t.lower() in _CAM_WORDS]
    scene = [t for t in tags if t.lower() not in drop and t.lower() not in _CAM_WORDS and not t.lower().startswith("by ")]
    rs = sorted(regions, key=lambda r: r["span"][0])
    def who(r):
        return "%s, %s" % (r.get("anima") or r.get("posL", ""), r.get("rp", ""))
    cams = ", ".join(_CAM_WORDS[t.lower()] for t in cam)
    #   인원수(2boys/2girls)는 콘티 장면 태그에 이미 있음 -> 머리말은 털 캐릭터가 있을 때만 furry, anthro
    fur = any(("furry" in str((r.get("char") or {}).get(k, "")) or "anthro" in str((r.get("char") or {}).get(k, "")))
              for r in regions for k in ("tags_short", "tags_full"))
    boys = "2boys, " if "2boys" in [t.lower() for t in tags] else ""      # 2boys·duo 는 _NOOB_ONLY 로 장면에서 빠짐 -> 여기서 (털 편은 예전과 같은 글)
    head = ("masterpiece, best quality, score_7, safe, " + boys + "duo, " + ("furry, anthro, " if fur else "") + ", ".join(scene) + ". "
            "One single illustration of two characters together in the same place" + (", " + cams if cams else "") + ". ")
    act = _anima_interaction(base_pos, rs) if interact else None
    if act and act[0] == "piggyback":
        return head + act[1]
    return head + "On the left is " + who(rs[0]) + "; on the right is " + who(rs[-1]) + "." + (" " + act[1] if act else "")


def _short(r):
    return (r.get("char") or {}).get("compose_name") or r.get("key", "character")


def _has_word(low, key):
    """태그 글에 key 가 낱말로 있나 (앞뒤가 글자가 아님): 'hug' 는 'hug, ' 에만, 'hugging object' 에는 아님"""
    import re
    return re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(key), low) is not None


def _anima_interaction(base_pos, rs):
    """닿는 동작이 있는 두 명 컷의 Anima 문장.
    duo1 1차: 장면 태그에 hug·piggyback이 있어도 'On the left is A; on the right is B' 문장 때문에 Anima가 10컷 모두
    나란히 선·앉은 그림을 그림 (runs/regtest/lck_duo1/layout_pose_checks.png) -> 동작을 문장으로 풀어 씀. 없으면 None"""
    low = " " + ", ".join(t.strip().lower() for t in base_pos.split(",")) + ", " +           ", ".join(str(r.get("rp", "")).lower() for r in rs) + " "
    A, B = _short(rs[0]), _short(rs[-1])
    if " piggyback" in low:
        car = next((r for r in rs if "carrying" in str(r.get("rp", "")).lower()), rs[0])
        rid = rs[-1] if car is rs[0] else rs[0]
        return ("piggyback", "%s carries %s on their back in a piggyback ride: %s is behind and above, arms around %s's neck, "
                "legs held at %s's sides. The carrier: %s. The one on their back: %s."
                % (_short(car), _short(rid), _short(rid), _short(car), _short(car),
                   car.get("anima") or car.get("posL", ""),
                   (rid.get("char") or {}).get("anima_head") or rid.get("anima") or rid.get("posL", "")))
    for key, text in (("hug", "The %s and the %s are hugging each other tightly, arms wrapped around each other, chests touching."),
                      ("holding hands", "The %s and the %s are holding hands, their hands clasped together between them."),
                      ("high five", "The %s and the %s are giving each other a high five, their raised palms pressed together."),
                      ("arm around shoulder", "The %s has one arm around the %s's shoulders, standing close together, bodies touching."),
                      ("back-to-back", "The %s and the %s sit back to back, their backs pressed against each other, facing away from each other."),
                      ("headpat", "The %s gently pats the %s's head with one hand, standing close together."),
                      ("giving", "The %s hands an object to the %s, their hands meeting around the object between them.")):
        if _has_word(low, key):
            return (key, text % (A, B))
    if _has_word(low, "lying") and ("couch" in low or "bed" in low):
        return ("lying", "The %s and the %s are both lying down on the %s, side by side, heads on the armrest, bodies close."
                % (A, B, "couch" if "couch" in low else "bed"))
    return None


def _anima_init(g, s, text, seed, a1):
    """build_duo3_graph가 만든 그래프의 시작 잠재(5번 EmptyLatentImage)를 Anima 그림으로 바꾸고 1단계 denoise를 a1로"""
    W, H = int(s["width"]), int(s["height"])
    g["600"] = {"class_type": "UNETLoader", "inputs": {"unet_name": ANIMA["unet"], "weight_dtype": "default"}}
    g["601"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": ANIMA["clip"], "type": "lumina2", "device": "default"}}
    g["602"] = {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA["vae"]}}
    g["603"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["600", 0], "shift": ANIMA["shift"]}}
    g["604"] = {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["601", 0]}}
    g["605"] = {"class_type": "CLIPTextEncode", "inputs": {"text": ANIMA_NEG, "clip": ["601", 0]}}
    g["606"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}
    g["607"] = {"class_type": "KSampler", "inputs": {"seed": int(seed), "steps": ANIMA["steps"], "cfg": 1.0,
                                                     "sampler_name": ANIMA["sampler"], "scheduler": ANIMA["scheduler"],
                                                     "denoise": 1.0, "model": ["603", 0], "positive": ["604", 0],
                                                     "negative": ["605", 0], "latent_image": ["606", 0]}}
    g["608"] = {"class_type": "VAEDecode", "inputs": {"samples": ["607", 0], "vae": ["602", 0]}}
    g["5"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["608", 0], "vae": ["4", 2]}}
    g["3"]["inputs"]["denoise"] = float(a1)
    return g


def _anima_solo(conti, cut, char, wt):
    """혼자 컷·사물 컷의 Anima 시작 그림 설정. 콘티 컷에 anima: 0.55 (또는 true) 가 있을 때만.
날아가는 모자 사물 컷(13)은 모자가 안 나옴"""
    v = cut.get("anima")
    if v in (None, False):
        return None
    a1 = float((conti.get("duo") or {}).get("anima_denoise", 0.55)) if v is True else float(v)
    tags = [t.strip() for t in (_joined(cut.get("scene"), wt) or "").split(",") if t.strip()]
    tags = [t for t in tags if t.lower() not in ("solo", "no humans", "anime coloring", "official art")]
    if char is None:
        head = "masterpiece, best quality, score_7, safe, no humans, A single continuous scene, "
        return {"text": head + ", ".join(tags) + ".", "a1": a1}
    desc = char.get("anima") or char.get("trigger", "")
    ct = " ".join(str(char.get(k, "")) for k in ("tags_short", "tags_full"))
    fur = "furry" in ct or "anthro" in ct
    boy = "1boy" in ct or " male" in " " + ct.replace(",", " ")
    head = ("masterpiece, best quality, score_7, safe, " + ("1boy, " if boy else "") + "solo, " + ("furry, anthro, " if fur else "")
            + "A single continuous scene, ")
    return {"text": head + ", ".join(tags) + ". The character: " + desc + ".", "a1": a1}


# 시험 (runs: ComfyUI output/layout_test, 같은 시드 777):
#   O = Anima 그림에서 뼈대만 뽑아(DWPose) OpenPose ControlNet + 빈 그림에서 새로 그림 -> 컷20·5에서 두 명 다 나오고
# 콘티: modes: "O" (기본 세기 1.0, 처음 50% 단계까지) / "O0.85e0.6" = 세기 0.85, 60%까지
# 뼈대 그림: episodes/<ep>/poses/cutNN.png (검은 바탕 OpenPose 그림, 그림 크기 = 컷 크기)
POSE_CN = "openpose_pre.safetensors"


def _pose_mode(mode, d):
    body = mode[1:]
    st, en = float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5))
    if body:
        if "e" in body:
            a, b = body.split("e", 1)
            st = float(a) if a else st
            en = float(b)
        else:
            st = float(body)
    return st, en


def _pose_file(kit, ep, cid):
    return os.path.join(ep_dir(kit, ep), "poses", "cut%02d.png" % int(cid))


def _pose_upload(nk, cfg, kit, ep, cid, dry=False):
    """뼈대 그림을 ComfyUI input/nk_pose/ 로 올리고 LoadImage 이름을 돌려줌"""
    p = _pose_file(kit, ep, cid)
    if not os.path.exists(p):
        print("[ERROR] cut %s: O / MB mode needs a pose image %s" % (cid, p))
        sys.exit(1)
    return _upload_input(nk, cfg, p, "%s_cut%02d.png" % (ep, int(cid)), dry)


def _mask_upload(nk, cfg, kit, ep, cid, regions, H, W, dry=False):
    """MB 방식: 뼈대 그림 -> 사람별 몸 모양 마스크 (nk_pose.body_masks) -> 파일로 남기고 ComfyUI에 올림.
    뼈대가 거의 없는 사람(점 500개 미만: 뼈대를 못 찾은 사람)은 예전처럼 자기 칸 직사각형 -> 경고"""
    import nk_pose, cv2, numpy as np
    spans = [tuple(r["span"]) for r in regions]
    #                     repaint = 2단계 LoRA 다시 그리기용(몸만: 머리 위 하늘까지 다시 그리면 그 자리 배경이 달라질 수 있음)
    out = {}
    g_reg = [0.055 * float(r["char"].get("mask_grow", 1.0)) for r in regions]
    c_reg = [float(r["char"].get("mask_cap", 1.0)) for r in regions]
    #   허벅지 하늘색 테두리). 원인 = 1단계가 그린 몸이 좁은 다시 그리기 마스크(뼈대+5.5%)보다 커서 가장자리에 1단계 그림이 남음.
    g_rep = [0.055 * float(r["char"].get("repaint_grow", 1.0)) for r in regions]
    c_rep = [float(r["char"].get("repaint_cap", 0.0)) for r in regions]
    b_rep = [float(r["char"].get("repaint_blur", 0.012)) for r in regions]
    tight = None
    for kind, cap, grow in (("repaint", c_rep, g_rep), ("region", c_reg, g_reg)):
        if kind == "repaint":
            ms, cnt = nk_pose.body_masks(_pose_file(kit, ep, cid), spans, W, H, grow=grow, cap=cap, blur=b_rep,
                                         solid=[bool(r["char"].get("repaint_grow")) for r in regions])
            if any(g > 0.055 for g in g_rep) or any(c > 0 for c in c_rep):
                other, _ = nk_pose.body_masks(_pose_file(kit, ep, cid), spans, W, H, grow=g_reg, cap=c_reg)
                ms = [np.clip(m.astype(int) - sum(other[j].astype(int) for j in range(len(ms)) if j != i), 0, 255).astype(np.uint8)
                      if (g_rep[i] > 0.055 or c_rep[i] > 0) else m for i, m in enumerate(ms)]
        else:
            ms, cnt = nk_pose.body_masks(_pose_file(kit, ep, cid), spans, W, H, grow=grow, cap=cap)
        if kind == "region" and any(g > 0.055 for g in g_reg):
            base = [m.copy() for m in ms]
            ms = [np.clip(m.astype(int) - sum(base[j].astype(int) for j in range(len(ms)) if j != i and g_reg[i] > g_reg[j]), 0, 255)
                  .astype(np.uint8) if g_reg[i] > 0.055 else m for i, m in enumerate(ms)]
        names = []
        for i, (m, c) in enumerate(zip(ms, cnt)):
            if c < 500:
                a, b = spans[i]
                m = np.zeros((H, W), np.uint8); m[:, max(0, int(W * (a - 0.06))):min(W, int(W * (b + 0.06)))] = 255
                if kind == "region":
                    print("[WARN] cut %s: no skeleton for %s -> using its half rectangle (background may darken there)"
                          % (cid, regions[i]["key"]))
            tag = "mask" if kind == "repaint" else "rmask"
            p = os.path.join(os.path.dirname(_pose_file(kit, ep, cid)), "cut%02d_%s%d.png" % (int(cid), tag, i))
            cv2.imwrite(p, cv2.merge([m, m, m]))
            names.append(_upload_input(nk, cfg, p, "%s_cut%02d_%s%d.png" % (ep, int(cid), tag, i), dry))
        out[kind] = names
    return {"region": out["region"], "repaint": out["repaint"]}


def _upload_input(nk, cfg, p, name, dry=False):
    """파일 하나를 ComfyUI input/nk_pose/<name> 으로 올림 (multipart /upload/image)"""
    if dry:
        return nk.upload_subfolder("nk_pose") + "/" + name
    import urllib.request, uuid as _uuid
    c = nk.Comfy(cfg.get("server", "auto"))
    bd = "----nk" + _uuid.uuid4().hex
    data = open(p, "rb").read()
    body = (("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
             % (bd, name)).encode() + data +
            ("\r\n--%s\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\n%s"
             "\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--%s--\r\n"
             % (bd, nk.upload_subfolder("nk_pose"), bd, bd)).encode())
    req = urllib.request.Request(c.base + "/upload/image", data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + bd})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    name = (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]
    nk.remember_upload(name)
    return name


def _pose_cn(g, s, pose_img, st, en):
    """build_duo3_graph 그래프의 그리기 단계에 OpenPose ControlNet을 붙임. 고해상도 단계(400번대)는 그대로"""
    W, H = int(s["width"]), int(s["height"])
    g["700"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": POSE_CN}}
    g["701"] = {"class_type": "LoadImage", "inputs": {"image": pose_img}}
    g["702"] = {"class_type": "ImageScale", "inputs": {"image": ["701", 0], "upscale_method": "lanczos",
                                                        "width": W, "height": H, "crop": "center"}}
    for k in [n for n, v in list(g.items()) if v["class_type"] == "KSampler" and not (400 <= int(n) < 500)]:
        ks = g[k]["inputs"]
        cn = "72%s" % k
        g[cn] = {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ks["positive"], "negative": ks["negative"],
                 "control_net": ["700", 0], "image": ["702", 0], "strength": float(st), "start_percent": 0.0,
                 "end_percent": float(en)}}
        ks["positive"] = [cn, 0]
        ks["negative"] = [cn, 1]
    return g


def _body_masks(g, regions, masks):
    """build_duo2_graph 그래프의 영역 마스크를 몸 모양 마스크로 바꿈:
    1단계 영역 조건(100+i*10+2/+3) = masks["region"] / 2단계 LoRA 다시 그리기 마스크(200+i*10+3, 고해상도 단계도 이 번호) = masks["repaint"]
    (예전 형식: 이름 목록 하나 = 둘 다 같은 마스크)"""
    reg, rep = (masks.get("region"), masks.get("repaint")) if isinstance(masks, dict) else (masks, masks)
    for i, r in enumerate(regions):
        nid, nid2 = str(760 + i), str(770 + i)
        g[nid] = {"class_type": "LoadImageMask", "inputs": {"image": reg[i], "channel": "red"}}
        for k in (100 + i * 10 + 2, 100 + i * 10 + 3):
            g[str(k)]["inputs"]["mask"] = [nid, 0]
        k = str(200 + i * 10 + 3)
        if k in g:
            if rep[i] != reg[i]:
                g[nid2] = {"class_type": "LoadImageMask", "inputs": {"image": rep[i], "channel": "red"}}
            src = nid2 if rep[i] != reg[i] else nid
            g[k] = {"class_type": "FeatherMask", "inputs": {"mask": [src, 0], "left": 0, "top": 0, "right": 0, "bottom": 0}}
    return g


def _duo_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, mode, conti, hires=None, pose=None, masks=None):
    d = conti.get("duo") or {}
    has_lora = [i for i, r in enumerate(regions) if r["char"].get("lora")]
    if len(has_lora) > 1:
        print("[ERROR] 두 캐릭터 모두 LoRA인 두 명 컷은 아직 지원 안 함 (N 방식은 LoRA 캐릭터 1명 기준)")
        sys.exit(1)
    if not has_lora or mode == "P":           # 둘 다 모델이 아는 캐릭터 -> 영역 나누기만
        return build_duo2_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, pass1_only=True, hires=hires), "P"
    if mode.startswith("MB") and has_lora:
        # -> 2단계 LoRA 캐릭터 몸 모양 안만 다시 그림(dn). 배경·조명은 1단계 한 장 그대로 -> 세로 경계·좌우 배경 차이 없음
        if not pose or not masks:
            print("[ERROR] MB mode needs a pose image and body masks")
            sys.exit(1)
        dn = float(mode[2:]) if len(mode) > 2 else float(d.get("mb_denoise", 0.9))
        g = build_duo2_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, dn, hires=hires)
        _body_masks(g, regions, masks)
        _pose_cn(g, s, pose, float(d.get("pose_strength", 1.0)), float(d.get("pose_end", 0.5)))
        return g, "MB%.2g" % dn
    if mode.startswith("O") and has_lora:
        if not pose:
            print("[ERROR] O mode without a pose image")
            sys.exit(1)
        st, en = _pose_mode(mode, d)
        g = build_duo3_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, "N", float(d.get("fix_denoise", 0.7)),
                             hires=hires)
        _pose_cn(g, s, pose, st, en)
        return g, "O%.2ge%.2g" % (st, en)
    if mode.startswith("A"):
        a1, af = _anima_mode(mode, d)
        g = build_duo3_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, "N", af, hires=hires)
        _anima_init(g, s, _anima_prompt(s, base_pos, regions), seed, a1)
        return g, "A%.2gf%.2g" % (a1, af)
    if mode.startswith("C"):
        dn = float(mode[1:]) if len(mode) > 1 else float(d.get("denoise", 0.75))
        return build_duo2_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, dn, hires=hires), "C%.2g" % dn
    fdn = float(mode[1:]) if len(mode) > 1 else float(d.get("fix_denoise", 0.7))
    return build_duo3_graph(cfg, s, base_pos, base_neg, regions, seed, prefix, "N", fdn, hires=hires), "N%.2g" % fdn


def _draft_duo(nk, cfg, conti, cut, ep, n, seed, dry, start, s):
    cid = int(cut["id"])
    base_pos, base_neg, regions = _duo_parts(nk, cfg, conti, cut, s)
    modes = _duo_modes(conti, cut)
    if seed is None and cut.get("seed") is not None:
        seed = int(cut["seed"])
    seed0 = (seed + start) if seed is not None else random.randint(1, 2 ** 31)
    run_name = "%s/cut%02d" % (ep, cid)
    folder = os.path.join(_root(cfg, nk.KIT), run_name)
    old_meta = []
    if start == 0:
        if not dry and os.path.isdir(folder):
            shutil.rmtree(folder)
    elif os.path.exists(os.path.join(folder, "meta.json")):
        old_meta = json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))
    jobs = []
    use_pose = any(m[:1] == "O" or m[:2] == "MB" for m in modes)
    pose = _pose_upload(nk, cfg, nk.KIT, ep, cid, dry) if use_pose else None
    masks = _mask_upload(nk, cfg, nk.KIT, ep, cid, regions, int(s["height"]), int(s["width"]), dry) \
        if any(m[:2] == "MB" for m in modes) else None
    for i in range(start, start + n):
        sd = seed0 + (i - start)
        mode = modes[i % len(modes)]
        label = "%03d_s%d" % (i + 1, sd)
        g, used = _duo_graph(cfg, s, base_pos, base_neg, regions, sd, "nk/%s/%s" % (run_name.replace("/", "_"), label),
                             mode, conti, pose=pose if (mode[:1] == "O" or mode[:2] == "MB") else None,
                             masks=masks if mode[:2] == "MB" else None)
        pp = "BASE: %s || %s" % (base_pos, " || ".join("%s(%s): %s" % (r["key"], "LoRA" if r["char"].get("lora") else "tags",
                                                                          r["posL"]) for r in regions))
        nn = " || ".join("%s: %s" % (r["key"], r["neg"]) for r in regions)
        meta = {"duo": {"mode": used, "base_pos": base_pos, "base_neg": base_neg,
                        "regions": [{k: v for k, v in r.items() if k != "char"} for r in regions]}}
        if used[:1] == "O" or used[:2] == "MB":
            meta["duo"]["pose"] = pose
        if used[:2] == "MB":
            meta["duo"]["masks"] = masks
        jobs.append({"label": label, "graph": g, "positive": pp, "negative": nn, "settings": s, "seed": sd, "meta": meta})
    print("\n== cut %d (%s, two characters %s, %d candidates%s)" % (cid, cut["size"], "/".join(r["key"] for r in regions),
                                                                  n, ", +%d so far" % start if start else ""))
    if dry:
        for j in jobs:
            ks = [x["inputs"]["denoise"] for x in j["graph"].values() if x["class_type"] == "KSampler"]
            ll = [x["inputs"]["lora_name"] for x in j["graph"].values() if x["class_type"] == "LoraLoader"]
            print("\n[%s] mode=%s seed=%s %sx%s | LoRA %s | KSampler denoise %s | nodes %d"
                  % (j["label"], j["meta"]["duo"]["mode"], j["seed"], s["width"], s["height"], ll, ks, len(j["graph"])))
            print("  + " + j["positive"])
            print("  - " + j["negative"])
        return folder
    res = nk.run_jobs(cfg, jobs, run_name, dry)
    if old_meta:
        json.dump(old_meta + (res or []), open(os.path.join(folder, "meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return folder


def _score(r):
    """higher = better. must-item misses weigh 10, reference-item misses 1"""
    return -(10 * len(r.get("fails", [])) + r.get("soft_fails", 0))


def _back_items(items, ch, ct):
    """뒷모습 컷(angle: back): 얼굴 질문은 답이 없음 -> 뺌 / 앞에만 있는 장식처럼 뒤에서 안 보이는 것은 필수에서 뺌.
    캐릭터 파일 qa_back_skip / qa_back_soft (없으면 region: face 항목을 뺌 / 필수에서 빼는 것 없음)"""
    if ct is None or str(ct.get("angle", "")) != "back":
        return items
    skip = set(ch.get("qa_back_skip") or [q.get("id") for q in items if q.get("region") == "face"])
    soft = set(ch.get("qa_back_soft") or [])
    return [dict(q, must=False) if q.get("id") in soft else q for q in items if q.get("id") not in skip]


def _expr_items(text):
    """콘티 표정 태그 -> 판별기 검수 항목.
    빙글빙글 눈(@_@)·눈물은 필수, 나머지는 참고(후보 순위에만)"""
    try:
        from nk_facefix import EXPR_TAGGER
    except Exception:
        return []
    out, seen = [], set()
    for t in [x.strip().lower().strip("() ").split(":")[0].strip() for x in str(text or "").split(",")]:
        tag = EXPR_TAGGER.get(t)
        if tag and tag not in seen:
            seen.add(tag)
            out.append({"id": "x_" + tag.replace("@_@", "spiral"), "tag": tag, "min": 0.25,
                        "must": tag in ("@_@", "tears")})
    return out


def _qa_char(char, conti, cid, object_only):
    """이 컷에 쓸 검수 목록 = 캐릭터 기본 체크리스트 + world(소품·의상) 질문 + 컷 전용 질문.
    사물 컷(char: none)은 캐릭터 항목을 빼고 자기 질문만 본다 (달력·오븐 컷이 무조건 통과하던 구멍)."""
    ct = None
    if conti:
        ct = next((x for x in conti.get("cuts", []) if int(x["id"]) == cid), None)
    if ct is not None and _is_duo(ct):
        return _qa_duo_spec(conti, ct)
    if ct is not None and not object_only:
        char = _cut_char(char, ct)                 # 여러 캐릭터 에피소드: 그 컷 캐릭터의 체크리스트
    extra = []
    if ct is not None:
        extra = _world_for(conti, ct)[2] + _cut_qa(ct) + ([] if object_only else _expr_items(ct.get("scene")))
    if object_only:
        if not extra:
            return None
        return {"name": "(none - this panel shows only objects)", "qa_checklist": extra,
                "qa_desc": "a comic panel that shows only objects and no characters"}   # 검수 AI에게 "고양이 그림"이라고 하지 않게
    base = _back_items(list(char.get("qa_checklist", [])), char, ct)
    if not extra and len(base) == len(char.get("qa_checklist", [])) and ct is not None and str(ct.get("angle", "")) != "back":
        return char
    c2 = dict(char)
    c2["qa_checklist"] = base + extra
    return c2


COUNT_Q = {"id": "count", "must": True,
           "q": "How many characters are in the image?",
           "options": ["exactly two characters", "only one character", "three or more characters"],
           "expect": ["exactly two"]}


#   망가진 5·18·20·21·28·29 = 0.02~0.36. 0.35면 컷 5(0.36, 인물이 뭉개짐)가 통과해 버림 -> 0.45에서 9/9)
COUNT_TAG = {"id": "t_count", "tag": "2boys|multiple_boys|2girls|multiple_girls|1boy 1girl|2others|multiple_others",
             "min": 0.45, "must": True}


PRESENCE_MIN = 0.7


def _split_items(items, tagger_ok):
    """검수 항목을 판별기용(tag)과 검수 AI용(q)으로 나눔. 판별기가 없으면 tag 항목은 버리고(경고), 있으면 COUNT_Q는 버림"""
    tag_items, vlm_items = [], []
    for it in items:
        if it.get("tag"):
            if tagger_ok:
                tag_items.append(it)
        elif it.get("id") == "count" and tagger_ok:
            continue
        else:
            vlm_items.append(it)
    return tag_items, vlm_items


def _tag_log(folder, f, t, items):
    """판별기 기록: 검사한 태그 점수 + 상위 태그 (나중에 문턱을 고칠 근거)"""
    import nk_tagger
    top = sorted(((v, k) for k, v in t.items() if v >= 0.35), reverse=True)[:30]
    rec = {"file": f, "checked": {it["id"]: [it["tag"], round(nk_tagger.score(t, it["tag"]), 3)] for it in items},
           "top": {k: round(v, 3) for v, k in top}}
    with open(os.path.join(folder, "tag_raw.jsonl"), "a", encoding="utf-8") as lf:
        lf.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _qa_one(nk, qa_cfg, folder, cchar, f):
    """한 후보 검수 = 판별기(빠름, tag 항목) 먼저 -> 필수 항목이 떨어지면 검수 AI는 건너뜀 -> 아니면 검수 AI(q 항목)"""
    import nk_tagger
    ok_t, why = nk_tagger.available(nk.KIT)
    items = list(cchar.get("qa_checklist", []))
    tag_items, vlm_items = _split_items(items, ok_t)
    if not ok_t and any(it.get("tag") for it in items):
        print("   [note] tag checks skipped (%s)" % why)
    answers, fails, soft = {}, [], 0
    if tag_items:
        answers, fails, soft, _ = nk_tagger.judge(nk.KIT, os.path.join(folder, f), tag_items)
        _tag_log(folder, f, nk_tagger.tags(nk.KIT, os.path.join(folder, f)), tag_items)
        if fails:
            print("   [tagger] %s FAIL %s" % (f, "; ".join("%s=%.2f" % (k, answers[k]["answer"]) for k in fails)))
            return {"file": f, "pass": False, "fails": fails, "soft_fails": soft, "answers": answers, "vlm_skipped": True}
    if not vlm_items:
        return {"file": f, "pass": not fails, "fails": fails, "soft_fails": soft, "answers": answers}
    c2 = dict(cchar)
    c2["qa_checklist"] = vlm_items
    r = nk.qa_folder(folder, c2, qa_cfg, "safe", files=[f])[0]
    r["fails"] = fails + r["fails"]
    r["soft_fails"] = soft + r.get("soft_fails", 0)
    r["answers"] = dict(answers, **r["answers"])
    r["pass"] = r["pass"] and not fails
    return r


def _qa_duo_spec(conti, ct):
    """두 명 컷 검수 = 사람마다 자기 자리만 잘라서 자기 체크리스트 + 그림 전체로 인원수·공통 질문"""
    roles = []
    for r, ch in ct["_roles"]:
        side = str(r.get("side", "left"))
        span = tuple(r["span"]) if r.get("span") else SIDES[side]
        c2 = dict(ch)
        c2["qa_checklist"] = _back_items(list(ch.get("qa_checklist", [])), ch, ct) + _world_role(conti, ct, r["char"])[2] + \
            [dict(q, id=q.get("id", "role_q%d" % i), must=q.get("must", False)) for i, q in enumerate(r.get("qa") or [], 1)] + \
            (_expr_items(r.get("pos")) if str(ct.get("angle", "")) != "back" else [])
        roles.append((str(r["char"]), c2, span))
    scene = [dict(COUNT_Q), dict(COUNT_TAG)] + _world_for(conti, ct)[2] + _cut_qa(ct)
    return {"duo": True, "roles": roles,
            "scene": {"name": "(a comic panel with two characters)", "qa_checklist": scene,
                      "qa_desc": "a comic panel with two characters"},
            "qa_checklist": scene + [q for _, c2, _ in roles for q in c2["qa_checklist"]]}   # 개수 표시용


def _qa_duo_one(nk, qa_cfg, folder, spec, f):
    """한 후보: 자리별로 잘라 저장(_qa/) -> 사람마다 검수 -> 그림 전체 검수 -> 하나로 합침"""
    from PIL import Image
    qdir = os.path.join(folder, "_qa")
    os.makedirs(qdir, exist_ok=True)
    im = Image.open(os.path.join(folder, f)).convert("RGB")
    W, H = im.size
    stem = os.path.splitext(f)[0]
    fails, soft, answers, parts = [], 0, {}, []
    scene = _qa_one(nk, qa_cfg, folder, spec["scene"], f)     # 그림 전체 먼저: 판별기로 "두 명인가" -> 아니면 자리별 검수는 생략
    if scene.get("fails") == ["t_count"]:
        # -> 자리별로 잘라 "그 자리에 캐릭터가 있나"(furry|1boy)를 다시 봄. 둘 다 0.7 이상이면 두 명으로 인정
        import nk_tagger
        pres = {}
        for key, c2, (a, b) in spec["roles"]:
            x0 = max(0, int(W * (a - 0.06))); x1 = min(W, int(W * (b + 0.06)))
            name = "%s__%s.png" % (stem, key)
            im.crop((x0, 0, x1, H)).save(os.path.join(qdir, name))
            t = nk_tagger.tags(nk.KIT, os.path.join(qdir, name)) or {}
            pres[key] = round(nk_tagger.score(t, "furry|1boy"), 3)
        if pres and min(pres.values()) >= PRESENCE_MIN:
            print("   [tagger] %s two by role crops %s -> count OK" % (f, pres))
            sc2 = dict(spec["scene"])
            sc2["qa_checklist"] = [q for q in sc2["qa_checklist"] if q.get("id") != "t_count"]
            scene = _qa_one(nk, qa_cfg, folder, sc2, f)
            scene["answers"]["t_count_roles"] = {"answer": pres, "ok": True}
    if scene.get("vlm_skipped"):
        parts.append(("scene", scene))
    else:
        for key, c2, (a, b) in spec["roles"]:
            x0 = max(0, int(W * (a - 0.06))); x1 = min(W, int(W * (b + 0.06)))
            name = "%s__%s.png" % (stem, key)
            im.crop((x0, 0, x1, H)).save(os.path.join(qdir, name))
            parts.append((key, _qa_one(nk, qa_cfg, qdir, c2, name)))
        parts.append(("scene", scene))
    got_any = False
    for key, r in parts:
        fails += ["%s:%s" % (key, x) for x in r["fails"]]
        soft += r.get("soft_fails", 0)
        answers.update({"%s:%s" % (key, k): v for k, v in r["answers"].items()})
        got_any = got_any or bool(r["answers"])
    return {"file": f, "pass": not fails and got_any, "fails": fails, "soft_fails": soft, "answers": answers}


def _qa_cut(nk, qa_cfg, folder, cchar, files, early=True):
    """후보를 하나씩 검수. early=True면 완벽한 후보(필수 통과 + 참고 항목도 0개 틀림)가 나오는 순간 멈춤.
컷마다 첫 합격까지만 보면 검수 94회 -> 41회."""
    out = []
    for f in files:
        if cchar.get("duo"):
            r = _qa_duo_one(nk, qa_cfg, folder, cchar, f)
            print("   %s: %s  %s" % (f, "PASS" if r["pass"] else "FAIL", ", ".join(r["fails"])))
        else:
            r = _qa_one(nk, qa_cfg, folder, cchar, f)
        out.append(r)
        if early and r["pass"] and r.get("soft_fails", 0) == 0:
            break
    return out


def _notes_in_order(files, blank, res):
    """보드에 후보 순서대로 쓰일 한 줄 메모 (예전엔 검수한 것 -> 백지 순서라 보드 번호와 어긋날 수 있었음)"""
    by = {r["file"]: r for r in res}
    out = []
    for f in files:
        if blank.get(f):
            out.append("x %s" % blank[f])
        elif f in by:
            out.append("%s %s" % ("OK" if by[f]["pass"] else "x", ",".join(by[f]["fails"])))
        else:
            out.append("- not checked")
    return out


def _auto_pick(nk, cfg, kit, char, ep, cids, nochar=(), conti=None, early=True):
    """VLM checks every candidate of these cuts and picks the best one per cut."""
    qa_cfg = cfg.get("qa", {})
    try:
        nk.Comfy(cfg.get("server", "auto")).free()
        print("\nComfyUI models unloaded (VRAM freed for VLM)")
    except SystemExit:
        pass
    auto_p = os.path.join(ep_dir(kit, ep), "auto.json")
    auto = json.load(open(auto_p, encoding="utf-8")) if os.path.exists(auto_p) else {}
    picks = load_picks(kit, ep)
    for cid in cids:
        folder = _cut_folder(cfg, kit, ep, cid)
        files = _candidates(folder)
        if not files:
            continue
        # 1) 백지·새까만 후보는 AI에게 묻기 전에 픽셀로 탈락 (검수 AI는 빈 그림에서도 없는 걸 지어냄)
        blank = {f: _blank_check(os.path.join(folder, f)) for f in files}
        for f in files:
            if blank[f]:
                print("   [blank] cut %d %s: %s" % (cid, f, blank[f]))
        good = [f for f in files if not blank[f]]
        if not good:
            print("   [WARN] cut %d: every candidate is blank/black -> fix the scene tags and redo this cut" % cid)
            picks[cid] = int(files[0][:3])
            auto[str(cid)] = {"pick": picks[cid], "notes": ["x blank"] * len(files), "all_blank": True}
        else:
            cchar = _qa_char(char, conti, cid, cid in nochar)
            if cchar is None:          # object-only panel with no question of its own -> first non-blank one
                picks[cid] = int(good[0][:3])
                auto[str(cid)] = {"pick": picks[cid], "notes": ["no questions"] + ["x blank"] * (len(files) - len(good))}
            else:
                print("\n== QA cut %d (%d candidates, %d questions%s)"
                      % (cid, len(good), len(cchar.get("qa_checklist", [])), ", object cut" if cid in nochar else ""))
                res = _qa_cut(nk, qa_cfg, folder, cchar, good, early)
                best = max(range(len(res)), key=lambda k: (_score(res[k]), -k))
                picks[cid] = int(res[best]["file"][:3])
                auto[str(cid)] = {"pick": picks[cid], "notes": _notes_in_order(files, blank, res)}
            print("   -> cut %d: candidate %d" % (cid, picks[cid]))
        save_picks(kit, ep, picks)
        json.dump(auto, open(auto_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    nk.ollama_unload(qa_cfg)
    save_picks(kit, ep, picks)
    json.dump(auto, open(auto_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def make_board(cfg, kit, ep, conti):
    """one picture with every cut's candidates; the chosen one has a thick green frame"""
    from PIL import Image, ImageDraw
    picks = load_picks(kit, ep)
    auto_p = os.path.join(ep_dir(kit, ep), "auto.json")
    auto = json.load(open(auto_p, encoding="utf-8")) if os.path.exists(auto_p) else {}
    rows = []
    for ct in conti["cuts"]:
        cid = int(ct["id"])
        folder = _cut_folder(cfg, kit, ep, cid)
        fs = _candidates(folder)
        if fs:
            rows.append((cid, [os.path.join(folder, f) for f in fs]))
    if not rows:
        return None
    th, cw = 300, 450
    maxn = max(len(r[1]) for r in rows)
    W = 110 + maxn * (cw + 16)
    H = 10 + len(rows) * (th + 50)
    S = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(S)
    font = _font(cfg.get("webtoon", {}).get("font"), 22)
    small = _font(cfg.get("webtoon", {}).get("font"), 16)
    for r, (cid, files) in enumerate(rows):
        y = 10 + r * (th + 50)
        d.text((10, y + th // 2), "컷 %d" % cid, fill="black", font=font)
        notes = auto.get(str(cid), {}).get("notes", [])
        for k, f in enumerate(files):
            im = Image.open(f).convert("RGB")
            im.thumbnail((cw, th))
            x = 110 + k * (cw + 16)
            S.paste(im, (x, y + 30))
            chosen = picks.get(cid) == int(os.path.basename(f)[:3])
            if chosen:
                d.rectangle([x - 6, y + 24, x + im.width + 5, y + 30 + im.height + 5], outline=(0, 170, 0), width=6)
            d.text((x, y), "%d%s" % (k + 1, "  ← 선택" if chosen else ""), fill=(0, 140, 0) if chosen else "red", font=font)
            if k < len(notes):
                d.text((x + 150, y + 4), "QA " + notes[k], fill="gray", font=small)
    out = os.path.join(_root(cfg, kit), ep, "board.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    S.save(out)
    return out


def _picked_meta(cfg, kit, ep, cid, num):
    folder = _cut_folder(cfg, kit, ep, cid)
    mp = os.path.join(folder, "meta.json")
    if not os.path.exists(mp):
        return None, None
    for m in json.load(open(mp, encoding="utf-8")):
        if m["file"][:3].isdigit() and int(m["file"][:3]) == num:
            return m, os.path.join(folder, m["file"])
    return None, None


def _final_cuts(nk, cfg, kit, char, ep, cids, hires=None, dry=False, nochar=(), conti=None):
    picks = load_picks(kit, ep)
    dflt = cfg.get("defaults", {})
    os.makedirs(os.path.join(ep_dir(kit, ep), "cuts"), exist_ok=True)
    byid = {int(x["id"]): x for x in (conti or {}).get("cuts", [])}
    for cid in cids:
        m, _ = _picked_meta(cfg, kit, ep, cid, picks.get(cid, 1))
        if not m:
            print("[skip] cut %d has no candidates yet" % cid)
            continue
        ct = byid.get(cid)
        if m.get("duo"):
            _final_duo(nk, cfg, kit, ep, cid, m, ct, picks, hires, dry, dflt)
            continue
        cchar = _cut_char(char, ct) if ct is not None else char   # 여러 캐릭터 에피소드: 그 컷의 캐릭터 LoRA
        s = dict(m["settings"])
        s["loras"] = [tuple(x) for x in m.get("loras", [])]
        s["hires"] = hires or float(dflt.get("final_hires", 1.5))
        s["hires_denoise"] = dflt.get("hires_denoise", 0.35)
        s["hires_method"] = dflt.get("hires_method", "pixel")
        s["upscale_model"] = dflt.get("upscale_model", "")
        s["hires_steps"] = dflt.get("hires_steps", 20)
        label = "cut%02d" % cid
        if m.get("flow"):
            import nk_flow
            s0 = dict(m["settings"])
            g, parts = nk_flow.solo_graph(nk, kit, m["flow"], s0, None if cid in nochar else cchar,
                                          nk.resolve_scene(cfg, ct["scene"]) if ct is not None else "", m["seed"],
                                          "nk/%s_final/%s" % (ep, label), final=True)
            job = {"label": label, "graph": g, "positive": parts["%prompt%"], "negative": parts["%negative%"],
                   "settings": s0, "seed": m["seed"], "raw": True, "meta": {"flow": m["flow"]}}
            print("\n== final cut %d: candidate %d -> flow %s" % (cid, picks.get(cid, 1), nk_flow.flow_path(nk, m["flow"], kit, final=True)))
            res = nk.run_jobs(cfg, [job], "%s/final_cut%02d" % (ep, cid), dry)
            if res:
                src = os.path.join(_root(cfg, kit), ep, "final_cut%02d" % cid, res[0]["file"])
                shutil.copy2(src, _final_file(kit, ep, cid))
            continue
        g = nk.build_graph(cfg, s, None if cid in nochar else cchar, m["positive"], m["negative"], m["seed"], 1,
                           "nk/%s_final/%s" % (ep, label))
        if m.get("anima"):                           # 초안과 같은 Anima 구도에서 시작 (같은 시드 -> 같은 그림)
            _anima_init(g, s, m["anima"]["text"], m["seed"], m["anima"]["a1"])
        job = {"label": label, "graph": g, "positive": m["positive"], "negative": m["negative"], "settings": s, "seed": m["seed"]}
        print("\n== final cut %d: candidate %d -> hires %.2f" % (cid, picks.get(cid, 1), s["hires"]))
        res = nk.run_jobs(cfg, [job], "%s/final_cut%02d" % (ep, cid), dry)
        if res:
            src = os.path.join(_root(cfg, kit), ep, "final_cut%02d" % cid, res[0]["file"])
            shutil.copy2(src, _final_file(kit, ep, cid))


def _final_duo(nk, cfg, kit, ep, cid, m, ct, picks, hires, dry, dflt):
    """두 명 컷 최종본: 고른 후보와 같은 시드·같은 영역·같은 방식으로 다시 그리고 끝에 고해상도 단계(_duo_hires)"""
    if ct is None or not _is_duo(ct):
        print("[skip] cut %d: two-character meta but the conti cut is not a two-character cut any more -> nk ep redo" % cid)
        return
    chars = {str(r["char"]): ch for r, ch in ct["_roles"]}
    d = m["duo"]
    regions = []
    for r in d["regions"]:
        r2 = dict(r)
        r2["char"] = chars[r["key"]]
        r2["span"] = tuple(r["span"])
        regions.append(r2)
    s = dict(m["settings"])
    hi = {"scale": hires or float(dflt.get("final_hires", 1.5)), "denoise": dflt.get("hires_denoise", 0.35),
          "steps": dflt.get("hires_steps", 20)}
    label = "cut%02d" % cid
    mode = d["mode"]
    g, _ = _duo_graph(cfg, s, d["base_pos"], d["base_neg"], regions, m["seed"], "nk/%s_final/%s" % (ep, label),
                      mode, {"duo": {"fix_denoise": float(mode[1:]) if mode[:1] == "N" else 0.7,
                                     "denoise": float(mode[1:]) if mode[:1] == "C" else 0.75}}, hires=hi,
                      pose=d.get("pose"), masks=d.get("masks"))
    s2 = dict(s); s2["hires"] = hi["scale"]
    job = {"label": label, "graph": g, "positive": m["positive"], "negative": m["negative"], "settings": s2,
           "seed": m["seed"], "meta": {"duo": d}}
    print("\n== final cut %d (two characters, %s): candidate %d -> hires %.2f" % (cid, mode, picks.get(cid, 1), hi["scale"]))
    res = nk.run_jobs(cfg, [job], "%s/final_cut%02d" % (ep, cid), dry)
    if res:
        src = os.path.join(_root(cfg, kit), ep, "final_cut%02d" % cid, res[0]["file"])
        shutil.copy2(src, _final_file(kit, ep, cid))


def _expected_adaptive(mx, has_qa, p=0.6):
    """적응형에서 한 컷당 예상 (그리는 장수, 검수 횟수). p = 후보 1장이 검수 합격할 확률"""
    if not has_qa:
        return 1.0, 0.0
    draws = qa = 0.0
    alive, cnt, first = 1.0, 0, True
    while cnt < mx and alive > 1e-6:
        k = min(ADAPT_FIRST if first else ADAPT_STEP, mx - cnt)
        draws += alive * k
        qa += alive * sum((1 - p) ** i for i in range(k))      # 합격하면 그 라운드에서 바로 멈춤
        alive *= (1 - p) ** k
        cnt += k; first = False
    return draws, qa


def _preflight(nk, cfg, conti, char, todo, noqa, adaptive=False):
    """3시간짜리 실행이 중간에 이름 오타로 죽지 않도록, 시작 전에 ComfyUI·Ollama에 실제로 있는지 확인."""
    import urllib.request
    c = nk.Comfy(cfg.get("server", "auto"))
    problems = []
    try:
        loras = c._get("/object_info/LoraLoader")["LoraLoader"]["input"]["required"]["lora_name"][0]
        ckpts = c._get("/object_info/CheckpointLoaderSimple")["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception as e:
        print("[WARN] preflight: could not read ComfyUI model lists (%s) - skipping name check" % e)
        loras, ckpts = None, None
    if ckpts is not None and cfg["checkpoint"] not in ckpts:
        problems.append("checkpoint not in ComfyUI: %s" % cfg["checkpoint"])
    use_a = any((_is_duo(ct) and any(m[:1] == "A" for m in _duo_modes(conti, ct))) or ct.get("anima") not in (None, False)
                for ct in todo)
    use_o = [ct for ct in todo if _is_duo(ct) and any(m[:1] == "O" or m[:2] == "MB" for m in _duo_modes(conti, ct))]
    if use_o:                                      # O 방식: 뼈대 그림 + OpenPose ControlNet 파일
        for ct in use_o:
            if not os.path.exists(_pose_file(nk.KIT, conti.get("_ep", ""), ct["id"])) and conti.get("_ep"):
                problems.append("cut %s: pose image missing %s" % (ct["id"], _pose_file(nk.KIT, conti["_ep"], ct["id"])))
        try:
            cns = c._get("/object_info/ControlNetLoader")["ControlNetLoader"]["input"]["required"]["control_net_name"][0]
            if POSE_CN not in cns:
                problems.append("ControlNet file not in ComfyUI: %s" % POSE_CN)
        except Exception:
            problems.append("ComfyUI has no node ControlNetLoader (O mode needs it)")
    if any(_is_duo(ct) for ct in todo) or use_a:   # 두 명 컷·Anima 부품이 이 ComfyUI에 있나
        for n in sorted(set((DUO3_NODES + ["ImageScaleBy"] if any(_is_duo(ct) for ct in todo) else [])
                            + (ANIMA_NODES + ["VAEEncode"] if use_a else []))):
            try:
                if n not in c._get("/object_info/" + n):
                    problems.append("ComfyUI has no node %s (two-character cuts need it)" % n)
            except Exception:
                problems.append("ComfyUI has no node %s (two-character cuts need it)" % n)
        if use_a:                                  # Anima 파일 이름 확인 (없으면 몇 초 만에 멈춤)
            try:
                unets = c._get("/object_info/UNETLoader")["UNETLoader"]["input"]["required"]["unet_name"][0]
                clips = c._get("/object_info/CLIPLoader")["CLIPLoader"]["input"]["required"]["clip_name"][0]
                for f, have in ((ANIMA["unet"], unets), (ANIMA["clip"], clips)):
                    if f not in have:
                        problems.append("Anima file not in ComfyUI: %s" % f)
            except Exception as e:
                problems.append("could not read ComfyUI model lists for Anima (%s)" % e)
    if loras is not None:
        need = set()
        for ct in todo:
            if _is_duo(ct):
                for _, ch in ct["_roles"]:
                    need.add(ch.get("lora"))
                continue
            cc = _cut_char(char, ct)
            if cc is not None:
                need.add(ct.get("lora") or cc.get("lora"))
        for f in sorted(x for x in need if x):
            if f not in loras:
                near = [x for x in loras if x.split(".")[0][:8] == f.split(".")[0][:8]]
                problems.append("LoRA not in ComfyUI: %s   (similar: %s)" % (f, ", ".join(near[:5]) or "none"))
    if not noqa:
        q = cfg.get("qa", {})
        try:
            tags = json.loads(urllib.request.urlopen(q.get("ollama", "http://127.0.0.1:11434").rstrip("/") + "/api/tags",
                                                     timeout=5).read().decode("utf-8"))
            names = [m.get("name") for m in tags.get("models", [])]
            if q.get("model") and q["model"] not in names:
                problems.append("Ollama model missing: %s (have: %s)" % (q["model"], ", ".join(names)))
        except Exception:
            problems.append("Ollama not reachable (auto-pick needs it) -> start Ollama, or add --noqa")
    import nk_styleref
    refs = {nk_styleref.resolve_path(nk.KIT, nk_styleref.cut_settings(conti, ct).get("style_ref")) for ct in todo} - {None}
    if refs:
        for r in sorted(refs):
            if not os.path.exists(r):
                problems.append("style_ref picture not found: %s" % r)
        problems += nk_styleref.preflight(nk, cfg, c)
        print("style reference: %s" % ", ".join(sorted(os.path.relpath(r, nk.KIT) for r in refs)))
    import nk_flow
    flows = sorted({nk_flow.cut_flow(conti, ct) for ct in todo} - {None})
    if flows:
        try:
            finfo = c._get("/object_info")
        except Exception:
            finfo = None
        for fl in flows:
            for fin in (False, True):
                p = nk_flow.flow_path(nk, fl, nk.KIT, final=fin)
                if fin and p == nk_flow.flow_path(nk, fl, nk.KIT):
                    continue
                pr, wr, _ = nk_flow.check(nk, nk.KIT, p, finfo)
                problems += ["flow %s: %s" % (os.path.basename(p), x) for x in pr]
                for x in wr:
                    print("[flow warn] %s: %s" % (os.path.basename(p), x))
        print("workflow slots: %s" % ", ".join(flows))
    tag_report(nk.KIT, conti, todo)        # 태그 사전에 없는 문구 경고 (실행은 계속함)
    _print_check(conti, todo)              # 연출 규칙 경고 (실행은 계속함)
    n_imgs = sum(int(ct.get("n", 3)) for ct in todo)
    n_duo = sum(1 for ct in todo if _is_duo(ct))
    # 사물 컷도 자기 질문이 있으면 검수함 (Phase 1)
    n_qa = 0 if noqa else sum(int(ct.get("n", 3)) for ct in todo
                              if _qa_char(char, conti, int(ct["id"]), _cut_char(char, ct) is None) is not None)
    lo = n_imgs * 29 + n_qa * 35 + len(todo) * 85
    hi = n_imgs * 29 + n_qa * 85 + len(todo) * 85
    if adaptive and not noqa:
        ex = [_expected_adaptive(int(ct.get("n", 3)),
                                 _qa_char(char, conti, int(ct["id"]), _cut_char(char, ct) is None) is not None) for ct in todo]
        n_imgs = sum(e[0] for e in ex); n_qa = sum(e[1] for e in ex)
        lo = int(n_imgs * 29 + n_qa * 35 + len(todo) * 85)
        hi = int(n_imgs * 29 + n_qa * 85 + len(todo) * 85)
        print("adaptive: ~%.0f drafts, ~%.0f QA checks"
              % (n_imgs, n_qa))
    if n_duo:
        # 검수는 자리 2 + 전체 1 = 3번 (검수 1번 35~85초)
        ex = [_expected_adaptive(int(ct.get("n", 3)), True) for ct in todo if _is_duo(ct)]
        add = sum(e[0] for e in ex) * (118 - 29) + sum(e[1] for e in ex) * 2 * 60 + n_duo * (183 - 85)
        lo += int(add); hi += int(add)
        print("two-character cuts: %d" % n_duo)
    print("preflight: %d cuts, %d candidates, QA %d  -> about %dh%02dm ~ %dh%02dm "
          ""
          % (len(todo), n_imgs, n_qa, lo // 3600, lo % 3600 // 60, hi // 3600, hi % 3600 // 60))
    if problems:
        for p_ in problems:
            print("[ERROR] " + p_)
        sys.exit(1)
    print("preflight OK")


ADAPT_FIRST = 2      # 첫 라운드 후보 수
ADAPT_STEP = 2       # 합격이 없을 때 추가로 그릴 수


def _adaptive(nk, kit, args, todo, conti, cfg, char, reuse):
    """적응형: 컷마다 먼저 2장 -> 검수 -> 합격 없는 컷만 2장씩 더 (최대 n장). 합격하는 순간 그 컷은 끝.
    근거: 후보 94장 중 56장(60%%) 합격, 26컷 중 23컷은 첫 3장 안에 합격이 있었음.
    어려운 컷만 끝까지 그리게 됨."""
    qa_cfg = cfg.get("qa", {})
    nochar = {int(c["id"]) for c in conti["cuts"] if _cut_char(char, c) is None}
    auto_p = os.path.join(ep_dir(kit, args.ep), "auto.json")
    auto = json.load(open(auto_p, encoding="utf-8")) if os.path.exists(auto_p) else {}
    picks = load_picks(kit, args.ep)
    state = {}
    for ct in todo:
        cid = int(ct["id"])
        have = _candidates(_cut_folder(cfg, kit, args.ep, cid)) if reuse else []
        state[cid] = {"ct": ct, "max": max(1, int(ct.get("n", args.n))), "count": len(have), "res": {}, "blank": {},
                      "done": False, "qa": _qa_char(char, conti, cid, cid in nochar)}
        if have:
            print("cut %d: using %d existing candidates" % (cid, len(have)))
    rnd = 0
    while True:
        pending = [st for st in state.values() if not st["done"]]
        if not pending:
            break
        rnd += 1
        # ---- 그리기 (ComfyUI)
        drew = False
        for st in pending:
            k = (ADAPT_FIRST if st["count"] == 0 else ADAPT_STEP)
            if st["qa"] is None and st["count"] == 0:
                k = 1                                    # 검수 질문 없는 사물 컷: 백지만 아니면 됨
            k = min(k, st["max"] - st["count"])
            if st["count"] > 0 and rnd == 1:
                k = 0                                    # 재사용: 1라운드는 있는 후보부터 검수
            if k <= 0:
                continue
            _draft_cut(nk, cfg, conti, char, st["ct"], args.ep, k, args.seed, False, start=st["count"])
            st["count"] += k
            drew = True
        # ---- 검수 (Ollama). 새 후보만, 합격 나오면 멈춤
        try:
            nk.Comfy(cfg.get("server", "auto")).free()
        except SystemExit:
            pass
        progress = False
        for st in pending:
            cid = int(st["ct"]["id"])
            folder = _cut_folder(cfg, kit, args.ep, cid)
            files = _candidates(folder)
            new = [f for f in files if f not in st["res"] and f not in st["blank"]]
            for f in new:
                b = _blank_check(os.path.join(folder, f))
                if b:
                    st["blank"][f] = b
                    print("   [blank] cut %d %s: %s" % (cid, f, b))
            good = [f for f in new if f not in st["blank"]]
            if good:
                progress = True
            if st["qa"] is None:
                if good:
                    for f in good:
                        st["res"][f] = {"file": f, "pass": True, "fails": [], "soft_fails": 0}
                    st["done"] = True
            elif good:
                print("\n== QA round %d cut %d (%d new candidates, %d questions)"
                      % (rnd, cid, len(good), len(st["qa"].get("qa_checklist", []))))
                for r in _qa_cut(nk, qa_cfg, folder, st["qa"], good, early=True):
                    st["res"][r["file"]] = r
                if any(r["pass"] for r in st["res"].values()):
                    st["done"] = True
            if st["count"] >= st["max"]:
                st["done"] = True
            # 컷마다 바로 기록 (중간에 멈춰도 앞 컷 결과 유지)
            res = list(st["res"].values())
            if res:
                best = max(res, key=lambda r: (_score(r), -int(r["file"][:3])))
                picks[cid] = int(best["file"][:3])
            elif files:
                picks[cid] = int(files[0][:3])
            auto[str(cid)] = {"pick": picks.get(cid), "notes": _notes_in_order(files, st["blank"], res),
                              "round": rnd, "drawn": st["count"]}
            if files and not res:
                auto[str(cid)]["all_blank"] = True
            save_picks(kit, args.ep, picks)
            json.dump(auto, open(auto_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        nk.ollama_unload(qa_cfg)
        if not drew and not progress:
            break                                        # 더 그릴 것도 새로 볼 것도 없음 (안전장치)
    total = sum(st["count"] for st in state.values())
    checked = sum(len(st["res"]) for st in state.values())
    hard = [int(st["ct"]["id"]) for st in state.values() if st["res"] and not any(r["pass"] for r in st["res"].values())]
    print("\nadaptive: %d rounds, %d candidates in total (full mode: %d), %d QA checks"
          % (rnd, total, sum(st["max"] for st in state.values()), checked))
    if hard:
        print("  no candidate passed QA (best one used, check the board): cut %s" % ", ".join(map(str, sorted(hard))))
    return nochar


def _pipeline(nk, kit, args, cids, conti, reuse=False):
    """candidates -> auto-pick -> final -> letter, for the given cuts.
    reuse=True: a cut that already has candidates (e.g. from nk ep draft) is not drawn again, only picked."""
    cfg = nk.load_presets()
    char = conti["_default_char"]
    todo = [ct for ct in conti["cuts"] if int(ct["id"]) in cids]
    if not todo:
        print("nothing to do: every cut already has a finished image (redo one: nk ep redo %s 3)" % args.ep)
        letter(nk, kit, args)
        return
    if not args.dry:
        _preflight(nk, cfg, conti, char, todo, args.noqa, adaptive=not getattr(args, "full", False))
    t0 = time.time()
    print("cuts to draw: %s" % ", ".join(str(int(c["id"])) for c in todo))
    if not args.dry and not args.noqa and not getattr(args, "full", False):
        char_ = char
        nochar = _adaptive(nk, kit, args, todo, conti, cfg, char_, reuse)
        ids = [int(c["id"]) for c in todo]
        _final_cuts(nk, cfg, kit, char, args.ep, ids, nochar=nochar, conti=conti)
        b = make_board(cfg, kit, args.ep, conti)
        letter(nk, kit, args)
        print("\nDONE in %.0f min" % ((time.time() - t0) / 60))
        _after_notes(kit, args, conti, ids, b)
        return
    for ct in todo:
        if reuse and _candidates(_cut_folder(cfg, kit, args.ep, int(ct["id"]))):
            print("cut %d: using existing candidates" % int(ct["id"]))
            continue
        _draft_cut(nk, cfg, conti, char, ct, args.ep, int(ct.get("n", args.n)), args.seed, args.dry)
    if args.dry:
        print("\n(dry) then: VLM auto-pick -> hires final -> letter"
              + ("" if (args.noqa or getattr(args, "full", False)) else
                 "\n(real run is adaptive: %d first per cut, +%d only when none passed, up to n)" % (ADAPT_FIRST, ADAPT_STEP)))
        return
    ids = [int(c["id"]) for c in todo]
    nochar = {int(c["id"]) for c in conti["cuts"] if _cut_char(char, c) is None}
    if not args.noqa:
        _auto_pick(nk, cfg, kit, char, args.ep, ids, nochar, conti, early=False)   # --full: 전부 검수 (예전 방식)
    else:
        picks = load_picks(kit, args.ep)
        for cid in ids:
            picks[cid] = 1
        save_picks(kit, args.ep, picks)
    _final_cuts(nk, cfg, kit, char, args.ep, ids, nochar=nochar, conti=conti)
    b = make_board(cfg, kit, args.ep, conti)
    letter(nk, kit, args)
    print("\nDONE in %.0f min" % ((time.time() - t0) / 60))
    _after_notes(kit, args, conti, ids, b)


def _after_notes(kit, args, conti, ids, b):
    try:                                   # 후보가 전부 백지·새까만 컷은 크게 알림 (그대로 두면 빈 컷이 페이지에 들어감)
        au = json.load(open(os.path.join(ep_dir(kit, args.ep), "auto.json"), encoding="utf-8"))
        blank_cuts = sorted(int(k) for k, v in au.items() if v.get("all_blank") and int(k) in ids)
        if blank_cuts:
            print("  !!! every candidate was blank/black: cut %s -> fix its scene tags, then: nk ep redo %s %s"
                  % (", ".join(map(str, blank_cuts)), args.ep, " ".join(map(str, blank_cuts))))
    except Exception:
        pass
    print("  1) look at the result: episodes\\%s\\out\\  (%s)" % (args.ep, "page_01.png ... + book.pdf" if conti.get("format") == "page" else "strip.png"))
    print("  2) a cut looks bad?    board: %s  -> other candidate: nk ep pick %s 3=2   / draw again: nk ep redo %s 3"
          % (b, args.ep, args.ep))


# ------------------------------------------------------------------ commands
def make(nk, kit, args):
    c = load_conti(nk, kit, args.ep)
    cids = set(int(ct["id"]) for ct in c["cuts"] if not os.path.exists(_final_file(kit, args.ep, int(ct["id"]))))
    _pipeline(nk, kit, args, cids, c, reuse=True)


def tags(nk, kit, args):
    c = load_conti(nk, kit, args.ep)
    n = tag_report(kit, c, c["cuts"], quiet_ok=False)
    print("tag check: %d problem phrases" % n)


def qa_vocab_report(kit, conti, cuts):
    """검수 질문의 판별기 태그가 판별기 단어장에 있는지.
    'a|b|c' 중 하나라도 알면 괜찮음(가장 높은 점수를 씀). 전부 모르면 경고. returns number of problems."""
    import nk_tagger
    if not nk_tagger.vocab(kit):
        return 0
    bad = 0
    for ct in cuts:
        items = _world_for(conti, ct)[2] + _cut_qa(ct)
        for it in items:
            tg = it.get("tag") if isinstance(it, dict) else None
            if not tg or it.get("max") is not None:      # max = '있으면 불합격' 질문: 모르는 태그면 그냥 안 걸릴 뿐
                continue
            alts = [x.strip().replace(" ", "_") for x in str(tg).split("|") if x.strip()]
            unk = nk_tagger.check_vocab(kit, tg)
            if alts and len(unk) == len(alts):
                bad += 1
                print("[qa] cut %d: the tagger does not know '%s' -> this check always scores 0 = false FAIL. "
                      "Use a tag from models\\wd-eva02-large-tagger-v3\\selected_tags.csv" % (int(ct["id"]), tg))
    return bad


def check(nk, kit, args):
    c = load_conti(nk, kit, args.ep)
    n1 = tag_report(kit, c, c["cuts"], quiet_ok=True)
    n1 += qa_vocab_report(kit, c, c["cuts"])
    n2 = _print_check(c)
    print("\n  cut  page  shot    angle  loc")
    for ct in c["cuts"]:
        print("  %3d  %4d  %-7s %-6s %s" % (int(ct["id"]), int(ct.get("page", 0)),
              "object" if str(ct.get("char", "")).lower() == "none" else ct.get("shot", "-"),
              ct.get("angle", "eye"), ct.get("loc", "-")))
    print("\ncheck: %d tag warnings, %d direction warnings  (규칙: docs\\conti_rules.md)" % (n1, n2))


def redo(nk, kit, args):
    c = load_conti(nk, kit, args.ep)
    if getattr(args, "all", False):
        cids = set(int(ct["id"]) for ct in c["cuts"])
    elif args.cuts:
        cids = set(int(x) for x in args.cuts)
    else:
        print("which cuts?  e.g.  nk ep redo %s 3 5   /  every cut:  nk ep redo %s --all" % (args.ep, args.ep))
        return
    for cid in cids:
        f = _final_file(kit, args.ep, cid)
        if os.path.exists(f) and not args.dry:
            os.remove(f)
    _pipeline(nk, kit, args, cids, c)


def pick(nk, kit, args):
    c = load_conti(nk, kit, args.ep)
    picks = load_picks(kit, args.ep)
    changed = []
    for item in args.choices:
        if "=" not in item:
            print("[ERROR] write cut=candidate, e.g. 3=2  (got %s)" % item)
            sys.exit(1)
        k, v = item.split("=")
        picks[int(k)] = int(v)
        changed.append(int(k))
    save_picks(kit, args.ep, picks)
    print("picks:", ", ".join("cut%d=%d" % kv for kv in sorted(picks.items())))
    if changed and not args.nofinal:
        cfg = nk.load_presets()
        ch = c["_default_char"]
        _final_cuts(nk, cfg, kit, ch, args.ep, changed, nochar={int(x["id"]) for x in c["cuts"] if _cut_char(ch, x) is None},
                    conti=c)
        make_board(cfg, kit, args.ep, c)
        letter(nk, kit, args)


def draft(nk, kit, args):
    cfg = nk.load_presets()
    c = load_conti(nk, kit, args.ep)
    char = c["_default_char"]
    only = cut_filter(args.cuts)
    for ct in c["cuts"]:
        if only and int(ct["id"]) not in only:
            continue
        _draft_cut(nk, cfg, c, char, ct, args.ep, int(ct.get("n", args.n)), args.seed, args.dry)
    if not args.dry:
        picks = load_picks(kit, args.ep)
        for ct in c["cuts"]:
            picks.setdefault(int(ct["id"]), 1)
        save_picks(kit, args.ep, picks)
        print("board ->", make_board(cfg, kit, args.ep, c))


def final(nk, kit, args):
    cfg = nk.load_presets()
    c = load_conti(nk, kit, args.ep)
    only = cut_filter(args.cuts)
    ids = [int(ct["id"]) for ct in c["cuts"] if not only or int(ct["id"]) in only]
    ch = c["_default_char"]
    _final_cuts(nk, cfg, kit, ch, args.ep, ids, args.hires, args.dry,
                nochar={int(x["id"]) for x in c["cuts"] if _cut_char(ch, x) is None}, conti=c)


# ------------------------------------------------------------------ lettering
def _font(path, size):
    from PIL import ImageFont
    for p in [path, "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    print("[WARN] no Korean font found; set webtoon.font in presets.yaml")
    return ImageFont.load_default()


def _wrap(draw, text, font, maxw):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for ch in para:
            t = cur + ch
            if draw.textlength(t, font=font) <= maxw or not cur:
                cur = t
            else:
                # prefer breaking at the last space
                sp = cur.rfind(" ")
                if sp > 0:
                    lines.append(cur[:sp])
                    cur = cur[sp + 1:] + ch
                else:
                    lines.append(cur)
                    cur = ch
        lines.append(cur)
    for i in range(1, len(lines)):                      # 문장부호만 다음 줄로 넘어가지 않게 (앞 줄 끝에 붙임)
        while lines[i] and lines[i][0] in WRAP_PUNCT and lines[i - 1]:
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    return [l for l in lines if l] or [""]


WRAP_PUNCT = ".,!?…~♡)」』'\"%—"

# 한국식(왼→오) 읽기: 콘티의 말풍선 자리는 일본식(오른쪽 위가 처음)으로 정해져 있어서 좌우를 뒤집음
MIRROR = {"tl": "tr", "tr": "tl", "bl": "br", "br": "bl", "left": "right", "right": "left"}
# 작은 칸에서 말풍선이 칸을 덮지 않게: (글씨 배율, 풍선 최대 폭 = 칸 폭 x 비율) 순서로 해 보고 처음 맞는 것
FIT_STEPS = ((1.0, None), (1.0, 0.55), (0.9, 0.58), (0.82, 0.62), (0.75, 0.66))


def _fit_text(draw, text, panel, st, fs0, ratio0, font_of, pad_w=2.0, pad_h=1.6, max_frac=0.9):
    """글씨 크기·줄바꿈 정하기. 풍선 하나가 칸 넓이의 일정 몫(같은 칸 글자 수로 나눔)보다 크거나 4줄 이상이면
    글씨를 조금씩 줄이고 폭을 넓힘. 돌려줌: (font, fsize, text, lines)"""
    px, py, pw, ph = panel
    texts = [t for t in ((st.get("_cut") or {}).get("text") or []) if str(t.get("type", "speech")) != "sfx"]
    limit = min(0.24, 0.45 / max(1, len(texts))) * pw * ph
    out = None
    for sc, r in FIT_STEPS:
        fsize = max(12, int(fs0 * sc))
        font = font_of(fsize)
        t2 = text
        try:
            import nk_letter2
            t2 = nk_letter2.fit_text(text, font)
        except Exception:
            pass
        maxw = int(min(pw * max_frac, max(pw * min(max(r or 0, ratio0), max_frac), fsize * 4)))
        lines = _wrap(draw, t2, font, maxw)
        tw = max(draw.textlength(l, font=font) for l in lines)
        area = (tw + fsize * pad_w) * (len(lines) * fsize * 1.3 + fsize * pad_h)
        out = (font, fsize, t2, lines)
        if area <= limit and len(lines) <= 3:
            break
    return out


ANCHOR = {"tl": (0.04, 0.04), "tr": (0.96, 0.04), "bl": (0.04, 0.96), "br": (0.96, 0.96),
          "top": (0.5, 0.04), "bottom": (0.5, 0.96), "left": (0.04, 0.5), "right": (0.96, 0.5)}


def _place(box_w, box_h, panel, at):
    px, py, pw, ph = panel
    ax, ay = ANCHOR.get(at, ANCHOR["tl"])
    x = px + ax * pw - ax * box_w
    y = py + ay * ph - ay * box_h
    return int(x), int(y)


NEAR = {"tl": ["tl", "top", "left", "tr"], "tr": ["tr", "top", "right", "tl"],
        "bl": ["bl", "bottom", "left", "br"], "br": ["br", "bottom", "right", "bl"],
        "top": ["top", "tl", "tr"], "bottom": ["bottom", "bl", "br"],
        "left": ["left", "tl", "bl"], "right": ["right", "tr", "br"]}


def _composed(kit, ep, cid, f):
    """이 최종본이 합치기(nk ep compose)로 만든 것인가 -> 그리기 전 뼈대 그림은 이 그림과 안 맞음"""
    import json, hashlib
    for sub, name in (("cuts_compose", "compose.json"), ("cuts_unify", "unify.json"), ("cuts_edit", "edit.json")):   # 글로 고치기(nk_edit)도 구도는 그대로
        p = os.path.join(ep_dir(kit, ep), sub, name)
        if not os.path.exists(p):
            continue
        try:
            r = json.load(open(p, encoding="utf-8")).get(str(cid)) or {}
            g = os.path.join(ep_dir(kit, ep), "cuts", "cut%02d.png" % cid)
            if r.get("final_md5") and r.get("final_md5") == hashlib.md5(open(g, "rb").read()).hexdigest():
                return True
        except Exception:
            pass
    return False


def _final_people(kit, ep, ct, img_path):
    """완성 그림에서 사람마다 뼈대(DWPose)를 찾아 몸 모양 마스크 + 머리 상자.
    예전: 머리만 피함 + 머리 자리는 '그리기 전 뼈대 그림'에서 -> 합치기(compose)로 새로 만든 두 명 컷은 뼈대 그림과 그림이 달라
지금: 완성 그림 자체에서 찾음 -> 몸 전체를 알고, 그림이 바뀌면 다시 찾음.
    돌려줌: {"heads": [(x0,y0,x1,y1) 0~1 비율], "mask": 사람 마스크 파일(L, 폭 256) 또는 None}. poses/cutNN_people.json에 md5와 저장"""
    import json, hashlib
    if not ct.get("_roles") and not ct.get("_char"):
        return {}
    import nk_pose
    nk_pose._join_parts()
    if not os.path.exists(nk_pose.DW):
        return {}
    md5 = hashlib.md5(open(img_path, "rb").read()).hexdigest()
    pd = os.path.join(ep_dir(kit, ep), "poses")
    cp = os.path.join(pd, "cut%02d_people.json" % int(ct["id"]))      # {md5: {...}} - 원래 그림·그림체판 둘 다 기억
    mp = os.path.join(pd, "cut%02d_people_%s.png" % (int(ct["id"]), md5[:8]))
    allrec = {}
    if os.path.exists(cp):
        try:
            allrec = json.load(open(cp, encoding="utf-8"))
            d = allrec.get(md5)
            if d and (not d.get("mask") or os.path.exists(mp)):
                return {"heads": [tuple(b) for b in d["heads"]], "mask": mp if d.get("mask") else None}
        except Exception:
            allrec = {}
    import numpy as np, cv2
    from PIL import Image
    img0 = cv2.imread(img_path)
    H, Wd = img0.shape[:2]
    spans = [tuple(r["span"]) if r.get("span") else SIDES[str(r.get("side", "left"))] for r, _ in ct["_roles"]] \
        if ct.get("_roles") else [(0.0, 1.0)]
    mask = np.zeros((H, Wd), np.uint8)
    heads = []
    for a, b in spans:
        box = np.array([max(0, (a - 0.02) * Wd), 0, min(Wd, (b + 0.02) * Wd), H])
        best = None
        for g in (1.0, 0.6, 0.45):
            im = img0 if g == 1.0 else np.clip(255 * ((img0 / 255.0) ** g), 0, 255).astype(np.uint8)
            k, c = nk_pose.to_openpose(*nk_pose.pose_one(im, box))
            n = int((c >= 0.3).sum())
            if best is None or n > best[0]:
                best = (n, k, c)
            if n >= 8:
                break
        n, k, c = best
        if n < 4:
            continue
        mask = np.maximum(mask, nk_pose.person_mask(k, c, H, Wd, thr=0.3))
        nose = k[0] if c[0] >= 0.3 else None
        neck = k[1] if c[1] >= 0.3 else None
        if nose is not None and neck is not None:
            d_ = float(np.hypot(*(nose - neck)))
            r = max(1.1 * d_, 0.07 * H)
            cx, cy = nose[0], nose[1] - 0.25 * r
        elif nose is not None:
            r = 0.09 * H
            cx, cy = nose[0], nose[1]
        elif neck is not None:
            r = 0.09 * H
            cx, cy = neck[0], neck[1] - 1.1 * r
        else:
            continue
        heads.append((max(0.0, (cx - r) / Wd), max(0.0, (cy - 1.3 * r) / H), min(1.0, (cx + r) / Wd), min(1.0, (cy + r) / H)))
    os.makedirs(pd, exist_ok=True)
    has_mask = bool(mask.max() > 0)
    if has_mask:
        Image.fromarray(mask).resize((256, max(1, int(256 * H / Wd))), Image.BILINEAR).save(mp)
    allrec[md5] = {"heads": heads, "mask": has_mask}
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(allrec, f)
    return {"heads": heads, "mask": mp if has_mask else None}


def _smart_at(box_w, box_h, panel, at, st, near_x=None):
    """콘티가 정한 자리(at)를 우선하되, 그 자리가 그림이 복잡한 곳(얼굴·몸 등 선이 많은 곳)이거나
    다른 말풍선과 겹치면 가까운 빈 자리로 옮김. 판단 기준 = 윤곽선 밀도(edge map).
    가까운 자리가 모두 얼굴이면 먼 자리(아래쪽 등)까지 봄"""
    E = st.get("_edges")
    occ = st.setdefault("_occupied", [])
    if E is None:
        return _place(box_w, box_h, panel, at)
    heads = [h for h in st.get("_heads", []) if h[4] == st.get("_cut_oid", id(st.get("_cut")))]
    PM = st.get("_people")
    near = NEAR.get(at, [at])
    px, py, pw, ph = panel
    cands = [(_place(box_w, box_h, panel, a), 0.04 * k) for k, a in enumerate(near)]
    # 정한 자리 근처(모서리 8곳)만 보던 것 -> 칸 안 격자 5x5까지 봄 (빈 하늘·땅이 있으면 그리로). 정한 자리에서 멀수록 조금 감점
    ax0, ay0 = _place(box_w, box_h, panel, at)
    m = 6
    grid = (0.0, 1 / 6.0, 2 / 6.0, 0.5, 4 / 6.0, 5 / 6.0, 1.0)      # 7x7 (빈자리를 더 촘촘히 찾음)
    for fx in grid:
        for fy in grid:
            x = px + m + fx * max(0, pw - box_w - 2 * m)
            y = py + m + fy * max(0, ph - box_h - 2 * m)
            dist = (((x - ax0) / max(1.0, pw)) ** 2 + ((y - ay0) / max(1.0, ph)) ** 2) ** 0.5
            cands.append(((int(x), int(y)), 0.1 + 0.2 * dist))
    kind = st.get("_kind", "speech")
    if st.get("_offscreen") and kind != "sfx":         # 화면 밖 대사: 칸 테두리에 걸친 자리도 봄 (바깥에서 들리는 목소리, 조금 우대)
        PW, PH = st.get("width") or 10 ** 6, st.get("height") or 10 ** 6
        for side in ("top", "bottom", "left", "right"):
            for f in (0.15, 0.5, 0.85):
                if side in ("top", "bottom"):
                    x = px + f * max(0, pw - box_w)
                    y = py - box_h * 0.4 if side == "top" else py + ph - box_h * 0.6
                else:
                    y = py + f * max(0, ph - box_h)
                    x = px - box_w * 0.4 if side == "left" else px + pw - box_w * 0.6
                x, y = min(max(0, x), PW - box_w), min(max(0, y), PH - box_h)
                cands.append(((int(x), int(y)), 0.05))
    # 읽는 순서: 같은 칸에서 앞서 놓은 글자(효과음 빼고)보다 먼저 읽히는 자리는 감점 (한국식 = 위·왼쪽이 먼저)
    cid = ((st.get("_cut") or {}).get("id"), (st.get("_cut") or {}).get("page"))
    prev = st.get("_prev_box") if (kind != "sfx" and st.get("_prev_cut") == cid) else None
    ltr = bool(st.get("_ltr"))
    others_x = _others_x(panel, st) if near_x is not None else []
    best, best_sc = None, None
    for (x, y), pen in cands:
        crop = E.crop((max(0, x), max(0, y), x + box_w, y + box_h))
        h = crop.histogram()
        busy = sum(i * c for i, c in enumerate(h)) / max(1, sum(h)) / 255.0
        ovf = 0.0                                       # 다른 글자와 겹치는 넓이 비율 (조금 띄워서 봄) — 겹칠수록 크게 감점
        for ox, oy, ow, oh in occ:
            iw_o = min(x + box_w, ox + ow + OCC_PAD) - max(x, ox - OCC_PAD)
            ih_o = min(y + box_h, oy + oh + OCC_PAD) - max(y, oy - OCC_PAD)
            if iw_o > 0 and ih_o > 0:
                ovf = max(ovf, iw_o * ih_o / float(max(1, box_w * box_h)))
        order = 0.0
        tk, tn = st.get("_text_kn") or (0, 1)
        if kind != "sfx" and tn >= 2:                   # 같은 칸에 글자가 여럿이면 앞 대사는 위쪽, 뒤 대사는 아래쪽을 조금 선호
            y_rel = (y - py) / float(max(1, ph - box_h))
            order += 1.0 * abs(y_rel - tk / float(tn - 1))
        if prev is not None:
            qx, qy, qw, qh = prev
            if y + box_h * 0.5 < qy:
                order += 2.5
            elif not (y + box_h < qy or qy + qh < y):
                c_new, c_old = x + box_w / 2.0, qx + qw / 2.0
                if (c_new < c_old) if ltr else (c_new > c_old):
                    order += 2.5
        face = 0.0
        for hx0, hy0, hx1, hy1, _ in heads:
            iw_ = max(0, min(x + box_w, hx1) - max(x, hx0))
            ih_ = max(0, min(y + box_h, hy1) - max(y, hy0))
            face = max(face, iw_ * ih_ / float(max(1, (hx1 - hx0) * (hy1 - hy0))))   # 얼굴이 가려지는 비율
        body = 0.0
        if PM is not None:
            bh_ = PM.crop((max(0, x), max(0, y), x + box_w, y + box_h)).histogram()
            body = sum(i * c for i, c in enumerate(bh_)) / max(1, sum(bh_)) / 255.0    # 말풍선 넓이 중 몸 위에 있는 비율
        sc = 0.6 * busy + pen + ((2.0 + 10.0 * ovf) if ovf > 0 else 0) + 3.0 * face + 1.2 * body + order
        if near_x is not None:
            sc += 0.8 * abs(x + box_w / 2.0 - near_x) / max(1.0, pw)
            bx_ = x + box_w / 2.0                        # 두 명 컷: 말한 사람보다 다른 사람 쪽에 더 가까운 자리는 감점 (꼬리가 엉뚱한 사람을 가리킴)
            if any(abs(bx_ - ox_) < abs(bx_ - near_x) for ox_ in others_x):
                sc += 1.5
        if best_sc is None or sc < best_sc:
            best, best_sc = (x, y), sc
    occ.append((best[0], best[1], box_w, box_h))
    if kind != "sfx":
        st["_prev_box"], st["_prev_cut"] = (best[0], best[1], box_w, box_h), cid
    return best


OCC_PAD = 8
SMALL_PANEL = 0.12          # 쪽 넓이의 이 몫보다 작은 칸 = 작은 칸


def _tail_len(base, fsize, dist, bw, bh, to_speaker):
    """꼬리 길이: 말한 사람이 멀면 그쪽으로 더 길게 (말풍선 가장자리에서 사람까지의 55%%, 글자 4.5개 높이까지)"""
    if not to_speaker:
        return base
    gap = max(0.0, dist - min(bw, bh) / 2.0)
    return max(base, min(gap * 0.55, fsize * 4.5))


def _others_x(panel, st):
    """두 명 컷에서 이번 대사를 말하지 않은 사람들의 x (자리 고를 때 '다른 사람 쪽' 판단용)"""
    who = str(st.get("_who") or "")
    roles = (st.get("_cut") or {}).get("_roles") or []
    out = []
    for r, _ in roles:
        if who and str(r.get("char")) != who:
            p = _speaker_point({"who": r.get("char")}, panel, st)
            if isinstance(p, tuple):
                out.append(p[0])
    return out


def _bubble_colors(item, st):
    """말풍선 (바탕, 선) 색. 캐릭터 파일의 bubble: {fill: "#...", line: "#..."} 를 씀.
    콘티 bubble_color: all(기본) = 그 캐릭터 말풍선 전부 / offscreen = 화면 밖 대사만 / off = 안 씀"""
    mode = str(st.get("_bubble_mode") or "all").lower()
    ch = (st.get("_castmap") or {}).get(str(item.get("who") or ""))
    b = (ch or {}).get("bubble") if isinstance(ch, dict) else None
    if not isinstance(b, dict) or mode == "off" or (mode == "offscreen" and not st.get("_offscreen")):
        return "white", "black"
    return str(b.get("fill") or "white"), str(b.get("line") or "black")


def _merge_same_speaker(items, small):
    """작은 칸에서 같은 사람이 연달아 한 보통 대사는 말풍선 하나에 두 줄로 (자리가 모자라 순서가 뒤집히는 것을 막음)"""
    if not small:
        return list(items)
    out = []
    for it in items:
        last = out[-1] if out else None
        if (last is not None and str(it.get("type", "speech")) == "speech" and str(last.get("type", "speech")) == "speech"
                and it.get("who") and it.get("who") == last.get("who") and "size" not in it and "size" not in last
                and str(last.get("text", "")).count("\n") < 2):
            out[-1] = dict(last, text="%s\n%s" % (last.get("text", ""), it.get("text", "")))
        else:
            out.append(it)
    return out


def _ellipse_exit(p0, p1, cx, cy, rx, ry):
    """p0(타원 안) -> p1(밖) 선분이 타원 테두리를 지나는 점. p0 가 이미 밖이면 p0"""
    ux, uy = (p0[0] - cx) / max(1e-6, rx), (p0[1] - cy) / max(1e-6, ry)
    wx, wy = (p1[0] - p0[0]) / max(1e-6, rx), (p1[1] - p0[1]) / max(1e-6, ry)
    a, b, c = wx * wx + wy * wy, 2 * (ux * wx + uy * wy), ux * ux + uy * uy - 1
    if c >= 0 or a <= 0:
        return p0
    t = (-b + (b * b - 4 * a * c) ** 0.5) / (2 * a)
    t = min(1.0, max(0.0, t))
    return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))


def _final_heads(kit, ep, ct, img_path):
    """뼈대 그림이 없는 컷(혼자 컷·사물 컷 제외): 완성 그림에서 DWPose 어깨로 머리 상자 (nk_facefix.head_box와 같은 방법, 귀 끝~턱).
    결과는 poses/cutNN_heads.json 에 그림 md5와 함께 저장 (같은 그림이면 다시 안 찾음). 돌려줌: [(x0,y0,x1,y1)] 0~1 비율"""
    import json, hashlib
    from PIL import Image
    if not ct.get("_roles") and not ct.get("_char"):
        return []
    import nk_pose
    nk_pose._join_parts()
    if not os.path.exists(nk_pose.DW):
        return []
    import nk_facefix
    md5 = hashlib.md5(open(img_path, "rb").read()).hexdigest()
    cp = os.path.join(ep_dir(kit, ep), "poses", "cut%02d_heads.json" % int(ct["id"]))
    if os.path.exists(cp):
        try:
            d = json.load(open(cp, encoding="utf-8"))
            if d.get("md5") == md5:
                return [tuple(b) for b in d["boxes"]]
        except Exception:
            pass
    W, H = Image.open(img_path).size
    spans = [tuple(r["span"]) if r.get("span") else SIDES[str(r.get("side", "left"))] for r, _ in ct["_roles"]] \
        if ct.get("_roles") else [(0.0, 1.0)]
    boxes = []
    for sp in spans:
        hb, why = nk_facefix.head_box(img_path, sp)
        if hb:
            boxes.append((hb[0] / W, hb[1] / H, hb[2] / W, hb[3] / H))
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    with open(cp, "w", encoding="utf-8") as f:
        json.dump({"md5": md5, "boxes": boxes}, f)
    return boxes


def _head_boxes(kit, ep, ct, rect, img_size, img_path=None):
    """사람마다 머리 자리를 페이지 좌표 상자로.
    뼈대 그림(poses/cutNN.png)이 있는 컷: 코(빨강 점)와 목(주황 점)으로 머리 중심·크기를 잡음. 얼굴 점을 뺀 뒷모습은 목 위쪽.
    없는 컷: 완성 그림에서 어깨로 (_final_heads). 컷 그림을 칸에 맞춰 자른 것(cover crop)·좌우반전까지 계산"""
    import numpy as np
    from PIL import Image
    p = _pose_file(kit, ep, ct["id"])
    if not os.path.exists(p):
        if not img_path:
            return []
        fr = _final_heads(kit, ep, ct, img_path)
        return _heads_to_page(ct, rect, img_size, [(a, b, c, d) for a, b, c, d in fr], 1.0, 1.0)
    P = np.asarray(Image.open(p).convert("RGB")).astype(int)
    Hp, Wp = P.shape[:2]

    def blobs(rgb, tol=40):
        import cv2
        m = ((abs(P[:, :, 0] - rgb[0]) < tol) & (abs(P[:, :, 1] - rgb[1]) < tol) & (abs(P[:, :, 2] - rgb[2]) < tol)).astype(np.uint8)
        n, lab, stats, cents = cv2.connectedComponentsWithStats(m, 8)
        return [tuple(cents[i]) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 8]
    noses, necks = blobs((255, 0, 0)), blobs((255, 85, 0))
    heads = []
    for nx, ny in necks:
        nose = min(noses, key=lambda q: (q[0] - nx) ** 2 + (q[1] - ny) ** 2) if noses else None
        if nose and ((nose[0] - nx) ** 2 + (nose[1] - ny) ** 2) ** 0.5 < 0.25 * Hp:
            d = ((nose[0] - nx) ** 2 + (nose[1] - ny) ** 2) ** 0.5
            r = max(1.1 * d, 0.07 * Hp)
            cx, cy = nose[0], nose[1] - 0.25 * r
        else:                                   # 뒷모습(얼굴 점 없음): 목 바로 위
            r = 0.09 * Hp
            cx, cy = nx, ny - 1.1 * r
        heads.append((cx - r, cy - 1.3 * r, cx + r, cy + r))        # 귀·모자 자리까지 위로 조금 더
    if not heads:
        return []
    return _heads_to_page(ct, rect, img_size, heads, float(Wp), float(Hp))


def _heads_to_page(ct, rect, img_size, heads, Wp, Hp):
    """머리 상자(그림 좌표, Wp x Hp 기준. 비율이면 1.0 x 1.0) -> 페이지 좌표 (cover crop·좌우반전)"""
    if not heads:
        return []
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    iw, ih = img_size
    sc = max(w / float(iw), h / float(ih))
    rw, rh = max(w, int(iw * sc + 0.5)), max(h, int(ih * sc + 0.5))
    fx = {"left": 0.0, "right": 1.0}.get(str(ct.get("place", "center")), 0.5)
    fy = {"top": 0.0, "center": 0.5, "bottom": 1.0}.get(str(ct.get("crop")), 0.35)
    ox, oy = int((rw - w) * fx), int((rh - h) * fy)
    out = []
    for a, b, c, d in heads:
        us = [a / Wp, c / Wp]
        if ct.get("flip"):
            us = [1 - us[1], 1 - us[0]]
        X0, X1 = x0 + us[0] * rw - ox, x0 + us[1] * rw - ox
        Y0, Y1 = y0 + b / Hp * rh - oy, y0 + d / Hp * rh - oy
        X0, X1 = max(x0, X0), min(x1, X1)
        Y0, Y1 = max(y0, Y0), min(y1, Y1)
        if X1 > X0 and Y1 > Y0:
            out.append((int(X0), int(Y0), int(X1), int(Y1), id(ct)))
    return out


def _real_spans(kit, ep):
    """regionlora.json 의 실제 자리 {컷 번호: {캐릭터: [a, b]}}. 없으면 {}"""
    try:
        rec = json.load(open(os.path.join(ep_dir(kit, ep), "regionlora.json"), encoding="utf-8"))
    except Exception:
        return {}
    return {int(k[3:]): v["spans"] for k, v in rec.items() if k.startswith("cut") and isinstance(v, dict) and v.get("spans")}


def _with_real_spans(ct, spans):
    """말풍선용 컷 사본: 두 명 컷 사람 자리를 그림에서 잰 실제 자리로 (콘티의 left/right 대신). 원본 컷은 안 바꿈"""
    sp = spans.get(int(ct.get("id", -1))) if ct.get("_roles") else None
    if not sp:
        return ct
    return dict(ct, _roles=[(dict(r, span=sp[str(r["char"])]) if str(r["char"]) in sp else r, ch) for r, ch in ct["_roles"]])


def _speaker_point(item, panel, st):
    """말풍선 꼬리 목표점. who가 없으면 None(예전처럼 컷 가운데).
    두 명 컷: 그 사람 자리(span) 가운데 x, 머리 높이(위에서 35%%) - 그림을 컷에 맞춰 자른 만큼(cover crop)·좌우반전까지 계산.
    who가 이 컷에 없는 사람이면 'offscreen' (화면 밖에서 하는 말)."""
    who = item.get("who")
    ct = st.get("_cut") or {}
    if not who:
        return None
    px, py, pw, ph = panel
    roles = ct.get("_roles")
    if roles:
        r = next((r for r, _ in roles if str(r["char"]) == str(who)), None)
        if r is None:
            return "offscreen"
        a, b = tuple(r["span"]) if r.get("span") else SIDES[str(r.get("side", "left"))]
        fx = (a + b) / 2
        if ct.get("flip"):
            fx = 1 - fx
        iw, ih = ct.get("_img_size") or (pw, ph)
        sc = max(pw / iw, ph / ih)
        W2 = iw * sc
        off = (W2 - pw) * {"left": 0.0, "right": 1.0}.get(str(ct.get("place", "center")), 0.5)
        x = px + fx * W2 - off
        x = min(px + pw * 0.95, max(px + pw * 0.05, x))
        return x, py + ph * 0.35
    if ct.get("_charkey") is not None and str(ct["_charkey"]) != str(who):
        return "offscreen"
    if ct.get("_char") is None:          # 사물 컷에서 누가 말하면 화면 밖
        return "offscreen"
    return None


def _draw_item(img, draw, item, panel, st, idx):
    if st.get("_ltr") and str(item.get("type", "speech")) not in ("narration", "sfx") and item.get("at") in MIRROR:
        item = dict(item, at=MIRROR[item["at"]])
    st["_kind"] = "sfx" if str(item.get("type", "speech")) == "sfx" else "text"
    allt = (st.get("_cut") or {}).get("text") or []
    st["_text_kn"] = (sum(1 for t in allt[:idx] if str(t.get("type", "speech")) != "sfx"),
                      sum(1 for t in allt if str(t.get("type", "speech")) != "sfx"))
    st["_offscreen"] = st["_kind"] != "sfx" and (str(item.get("type")) == "offscreen" or _speaker_point(item, panel, st) == "offscreen")
    st["_who"] = item.get("who")
    if st.get("v2"):
        import nk_letter2
        k2 = nk_letter2.bubble_kind(item)
        if k2 == "sfx":
            st["_kind"] = "sfx"
            return nk_letter2.draw_sfx(img, item, panel, st, idx)
        if k2 in ("shout", "whisper", "tremble", "aside"):
            return nk_letter2.draw_bubble(img, draw, item, panel, st, idx, k2)
    kind = item.get("type", "speech")
    if kind in ("shout", "whisper", "tremble", "aside"):      # v1 에서는 보통 말풍선으로
        kind = "speech"
    offscreen = kind == "offscreen"      # speaker outside the panel: speech bubble whose tail points out of the panel
    if offscreen:
        kind = "speech"
    text = item.get("text", "")
    at = item.get("at") or ["tl", "tr", "bl", "br"][idx % 4]
    fsize = int(item.get("size", st["font_size"] * (1.6 if kind == "sfx" else 1.0)))
    font = _font(st.get("font"), fsize)
    ratio = st.get("bubble_ratio", 0.42) if kind != "narration" else st.get("narration_ratio", 0.6)
    if kind == "sfx":
        ratio = st.get("sfx_ratio", 0.85)
    maxw = int(max(panel[2] * ratio, fsize * 4))
    if kind != "sfx" and "size" not in item:            # 말풍선·해설: 작은 칸이면 글씨를 줄이고 폭을 넓힘
        font, fsize, text, lines = _fit_text(draw, text, panel, st, fsize, ratio, lambda s: _font(st.get("font"), s),
                                             pad_w=1.2 if kind == "narration" else 2.0, pad_h=1.2 if kind == "narration" else 1.6)
    else:
        try:
            import nk_letter2
            text = nk_letter2.fit_text(text, font)
        except Exception:
            pass
        lines = _wrap(draw, text, font, maxw)
    lh = int(fsize * 1.3)
    tw = max(draw.textlength(l, font=font) for l in lines)
    th = lh * len(lines)
    lw = st["line"]
    if kind == "narration":
        pad = int(fsize * 0.6)
        bw, bh = int(tw + pad * 2), int(th + pad * 2)
        x, y = _smart_at(bw, bh, panel, at, st)
        draw.rectangle([x, y, x + bw, y + bh], fill="white", outline="black", width=lw)
        tx, ty = x + pad, y + pad
    elif kind == "sfx":
        bw, bh = int(tw), int(th)
        x, y = _smart_at(bw, bh, panel, at, st)
        for i, l in enumerate(lines):
            draw.text((x, y + i * lh), l, font=font, fill="black", stroke_width=max(3, fsize // 10), stroke_fill="white")
        return
    else:
        padx, pady = int(fsize * 1.0), int(fsize * 0.8)
        bw, bh = int(tw + padx * 2), int(th + pady * 2)
        # thought cloud bumps stick out by ~0.9*font -> reserve that margin so the cloud stays inside the panel
        m = int(fsize * 0.9) if kind == "thought" else 0
        spk0 = _speaker_point(item, panel, st) if len((st.get("_cut") or {}).get("_roles") or []) >= 2 else None
        x, y = _smart_at(bw + 2 * m, bh + 2 * m, panel, at, st, near_x=spk0[0] if isinstance(spk0, tuple) else None)
        x, y = x + m, y + m
        cx, cy = x + bw / 2, y + bh / 2
        px, py, pw, ph = panel
        # tail points toward panel centre (where the character usually is)
        tx_, ty_ = px + pw / 2, py + ph / 2
        spk = _speaker_point(item, panel, st)          # who: 말한 사람 쪽으로 (두 명 컷은 그 사람 자리)
        if spk == "offscreen":
            offscreen = True
        elif spk:
            tx_, ty_ = spk
        vx, vy = tx_ - cx, ty_ - cy
        if offscreen:                       # point away from the panel centre, toward the nearest edge
            vx, vy = -vx, -vy
        n = max(1.0, (vx * vx + vy * vy) ** 0.5)
        vx, vy = vx / n, vy / n
        tail_len = _tail_len(fsize * 1.6, fsize, n, bw, bh, isinstance(spk, tuple) and not offscreen)
        fill, ink = _bubble_colors(item, st)               # 캐릭터 파일 bubble: 말풍선 색 (없으면 흰 바탕·검은 선)
        if kind == "speech":
            base = (cx + vx * bw * 0.35, cy + vy * bh * 0.35)
            ox, oy = -vy * fsize * 0.45, vx * fsize * 0.45
            tip = (cx + vx * (bw / 2 + tail_len), cy + vy * (bh / 2 + tail_len))
            poly = [(base[0] + ox, base[1] + oy), (base[0] - ox, base[1] - oy), tip]
            # 꼬리를 풍선에 이어 붙임: 풍선을 먼저 그리고, 흰 꼬리로 이음매의 테두리를 덮은 뒤 풍선 밖 부분에만 선
            draw.ellipse([x, y, x + bw, y + bh], fill=fill, outline=ink, width=lw)
            draw.polygon(poly, fill=fill)
            for p0 in poly[:2]:
                draw.line([_ellipse_exit(p0, tip, cx, cy, bw / 2.0, bh / 2.0), tip], fill=ink, width=lw)
        else:  # thought: bumpy cloud + small circles
            for k in range(3):
                r = fsize * (0.35 - k * 0.09)
                ccx = cx + vx * (bw / 2 + fsize * (0.6 + k * 0.7))
                ccy = cy + vy * (bh / 2 + fsize * (0.6 + k * 0.7))
                draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=fill, outline=ink, width=max(2, lw - 1))
            import math
            nb = 12
            for k in range(nb):
                a = 2 * math.pi * k / nb
                ex, ey = cx + math.cos(a) * bw / 2, cy + math.sin(a) * bh / 2
                r = fsize * 0.9
                draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=fill, outline=ink, width=max(2, lw - 1))
            draw.ellipse([x, y, x + bw, y + bh], fill=fill, outline=None)
        tx, ty = cx - tw / 2, cy - th / 2
    for i, l in enumerate(lines):
        w_ = draw.textlength(l, font=font)
        lx = tx + (tw - w_) / 2 if kind != "narration" else tx
        draw.text((lx, ty + i * lh), l, font=font, fill="black")


def _pop_out(P, kit, ep, ct, border):
    """칸 넘기: ct["_pop"] = (위로 pop 만큼 더 잘라 둔 그림 E, pop, 원본 파일, 원본 크기). 칸 위쪽 띠(테두리 포함)에서
    캐릭터 실루엣(anime-seg, 0.5 넘는 곳)만 테두리·칸 사이 위에 얹음. 실루엣이 없으면 아무것도 안 함"""
    from PIL import Image, ImageFilter
    import nk_animeseg
    E, pop, f, isz = ct.pop("_pop")
    x0, y0, x1, y1 = ct["rect"]
    sm = nk_animeseg.cached_mask(os.path.join(ep_dir(kit, ep), "poses"), int(ct["id"]), f)
    if sm is None:
        return
    sm = sm.resize(isz)
    if ct.get("flip"):
        sm = sm.transpose(Image.FLIP_LEFT_RIGHT)
    sm = _cover_crop(sm, x1 - x0, y1 - y0 + pop, ct.get("place", "center"), ct.get("crop"))
    band = pop + border + 2                               # 칸 위 바깥 띠 + 테두리 두께
    m = sm.crop((0, 0, x1 - x0, band)).point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))
    if m.getbbox() is None:
        return
    top = y0 - pop
    if top < 0:                                           # 쪽 위 끝을 넘지 않게
        m = m.crop((0, -top, m.width, m.height)); E = E.crop((0, -top, E.width, E.height)); top = 0
    P.paste(E.crop((0, 0, x1 - x0, m.height)), (x0, top), m)


def _draw_fx(P, rect, fx, ct, st=None):
    """만화 강조선을 코드로 그림
       fx: focus   = 집중선 (가장자리에서 가운데로, 가운데는 비움)   fx_center: [0.5, 0.4] 로 가운데 위치
       fx: speed   = 가로 속도선 / speed_v = 세로 속도선
       선은 검정 반투명(컬러 그림 위라 너무 진하면 그림을 가림)"""
    import math
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    rnd = random.Random(int(ct.get("id", 0)) * 7919)
    L = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    alpha = int(255 * float(ct.get("fx_alpha", 0.6)))
    kinds = [k.strip() for k in str(fx).split(",") if k.strip()]
    for kind in kinds:
        if kind == "focus":
            cx, cy = ct.get("fx_center") or (0.5, 0.45)
            cx, cy = cx * w, cy * h
            R = math.hypot(max(cx, w - cx), max(cy, h - cy)) + 10
            n = int(ct.get("fx_count", 110))
            for k in range(n):
                a = 2 * math.pi * (k + rnd.random() * 0.8) / n
                inner = rnd.uniform(0.42, 0.62)
                rx, ry = w / 2 * inner, h / 2 * inner
                ex, ey = cx + math.cos(a) * R, cy + math.sin(a) * R
                ix, iy = cx + math.cos(a) * rx, cy + math.sin(a) * ry
                half = rnd.uniform(1.5, 6.0)
                px_, py_ = -math.sin(a) * half, math.cos(a) * half
                d.polygon([(ex + px_, ey + py_), (ex - px_, ey - py_), (ix, iy)], fill=(0, 0, 0, alpha))
        elif kind in ("speed", "speed_h", "speed_v"):
            vert = kind == "speed_v"
            n = int(ct.get("fx_count", 60))
            span = w if vert else h
            for k in range(n):
                t = rnd.uniform(0, span)
                ln = rnd.uniform(0.25, 0.7) * (h if vert else w)
                st0 = rnd.uniform(0, (h if vert else w) - ln)
                th = rnd.choice([1, 1, 2, 2, 3, 4])
                if vert:
                    d.line([(t, st0), (t, st0 + ln)], fill=(0, 0, 0, alpha), width=th)
                else:
                    d.line([(st0, t), (st0 + ln, t)], fill=(0, 0, 0, alpha), width=th)
        else:
            print("[warn] cut %s: unknown fx '%s' (focus / speed / speed_v)" % (ct.get("id"), kind))
    if st is not None:
        import nk_letter2
        L = nk_letter2.mask_people(L, rect, st.get("_people"))
    base = P.crop((x0, y0, x1, y1)).convert("RGBA")
    P.paste(Image.alpha_composite(base, L).convert("RGB"), (x0, y0))


def _styled(f, style):
    """nk ep restyle 결과(cuts_<style>/)가 있으면 그것, 없으면 원래 최종본"""
    if not style:
        return f
    g = os.path.join(os.path.dirname(os.path.dirname(f)), "cuts_" + style, os.path.basename(f))
    if os.path.exists(g):
        if os.path.exists(f) and os.path.getmtime(g) < os.path.getmtime(f):
            print("[WARN] %s: %s version is older than the final (redrawn after restyle) -> original. run: nk ep restyle <ep> %d"
                  % (os.path.basename(f), style, int(os.path.basename(f)[3:5])))
            return f
        return g
    print("[note] %s: no %s version -> original" % (os.path.basename(f), style))
    return f


def _cut_image(nk, cfg, kit, ep, cid, picks, style=None):
    f = _styled(os.path.join(ep_dir(kit, ep), "cuts", "cut%02d.png" % cid), style)
    if os.path.exists(f):
        return f
    _, f = _picked_meta(cfg, kit, ep, cid, picks.get(cid, 1))   # fall back to the draft
    if f:
        print("[note] cut %d: using draft (final not made yet)" % cid)
    return f


def _cover_crop(im, w, h, place="center", crop=None):
    """scale to cover w x h, then crop. place left/right keeps that side; crop top/bottom keeps that edge
    (crop: top = 긴 가로 컷에서 머리·귀가 잘리지 않게)."""
    from PIL import Image
    sc = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * sc + 0.5)), max(h, int(im.height * sc + 0.5))), Image.LANCZOS)
    fx = {"left": 0.0, "right": 1.0}.get(str(place), 0.5)
    fy = {"top": 0.0, "center": 0.5, "bottom": 1.0}.get(str(crop), 0.35)   # 기본은 위쪽을 조금 더 남김(얼굴)
    x = int((im.width - w) * fx)
    y = int((im.height - h) * fy)
    return im.crop((x, y, x + w, y + h))


def page_letter(nk, kit, args, c):
    """Japanese-style pages: frames from conti rows, pictures cropped into frames, bubbles, then PNG pages + PDF."""
    from PIL import Image, ImageDraw
    cfg = nk.load_presets()
    st = _page_style(cfg)
    st["bubble_ratio"] = st.get("bubble_w", 0.3)       # narrow bubbles -> taller, manga-like
    st["v2"] = str(c.get("letter") or "").lower() == "v2"
    st["_ltr"] = str(c.get("read", "rtl")) == "ltr"
    st["_castmap"] = c.get("_cast") or {}
    bm = c.get("bubble_color", "all")                   # YAML 은 off 를 false 로 읽음
    st["_bubble_mode"] = "off" if (bm is False or str(bm).lower() in ("false", "off", "no", "none", "0")) else str(bm or "all")
    picks = load_picks(kit, args.ep)
    cm = {}
    if c.get("color_match"):
        import nk_letter2, nk_animeseg
        pdir = os.path.join(ep_dir(kit, args.ep), "poses")
        for ct in c["cuts"]:
            f0 = _cut_image(nk, cfg, kit, args.ep, int(ct["id"]), picks, getattr(args, "style", None))
            if f0 and (ct.get("_char") or ct.get("_roles")):
                m0 = nk_animeseg.cached_mask(pdir, int(ct["id"]), f0)
                if m0 is not None:
                    cm[int(ct["id"])] = nk_letter2.char_stats(Image.open(f0), m0)
        cm["_target"] = nk_letter2.color_targets(list(cm.values()))
        print("[color] target sat/val %s from %d cuts" % (cm["_target"], len(cm) - 1))
        if str(c.get("color_match")).lower() != "chars":
            whole = lambda f: nk_letter2.char_stats(Image.open(f), Image.new("L", Image.open(f).size, 255))
            bg, ppl = {}, []
            for ct in c["cuts"]:
                f0 = _cut_image(nk, cfg, kit, args.ep, int(ct["id"]), picks, getattr(args, "style", None))
                if not f0:
                    continue
                (ppl.append(whole(f0)) if (ct.get("_char") or ct.get("_roles")) else bg.__setitem__(int(ct["id"]), whole(f0)))
            cm["_bg"], cm["_bg_target"] = bg, nk_letter2.color_targets(ppl)
            print("[color] 풍경 칸 %d 개 -> 사람 칸 전체 채도 %s 쪽으로" % (len(bg), cm["_bg_target"]))
    edir = ep_dir(kit, args.ep)
    out = os.path.join(edir, "out_" + args.style if getattr(args, "style", None) else "out")
    os.makedirs(out, exist_ok=True)
    for f in glob.glob(os.path.join(out, "*.png")) + glob.glob(os.path.join(out, "*.pdf")):
        os.remove(f)
    W, H = st["width"], st["height"]
    pages = sorted({int(ct["page"]) for ct in c["cuts"]})
    imgs = []
    for pn in pages:
        P = Image.new("RGB", (W, H), "white")
        PM = Image.new("L", (W, H), 0)                   # 사람 마스크 (말풍선 자리 판단용)
        d = ImageDraw.Draw(P)
        heads_pg = []
        for ct in [x for x in c["cuts"] if int(x["page"]) == pn]:
            cid = int(ct["id"])
            x0, y0, x1, y1 = ct["rect"]
            f = _cut_image(nk, cfg, kit, args.ep, cid, picks, getattr(args, "style", None))
            if f:
                im = Image.open(f).convert("RGB")
                if cm.get(cid) and cm.get("_target"):
                    import nk_letter2
                    im = nk_letter2.match_color(im, cm[cid], cm["_target"])
                elif cid in (cm.get("_bg") or {}) and cm.get("_bg_target"):
                    import nk_letter2
                    im = nk_letter2.match_color(im, cm["_bg"][cid], cm["_bg_target"])
                if ct.get("flip"):        # 오른->왼으로 읽는 만화에서 전진 방향은 왼쪽. 반전으로 방향만 뒤집음
                    im = im.transpose(Image.FLIP_LEFT_RIGHT)
                ct["_img_size"] = im.size        # 말풍선 꼬리(who) 계산용
                pop = int(ct.get("pop_px") or max(40, (y1 - y0) * 0.12)) if (st.get("v2") and ct.get("pop")) else 0
                if pop:
                    E = _cover_crop(im, x1 - x0, y1 - y0 + pop, ct.get("place", "center"), ct.get("crop"))
                    P.paste(E.crop((0, pop, x1 - x0, y1 - y0 + pop)), (x0, y0))
                    ct["_pop"] = (E, pop, f, im.size)
                else:
                    P.paste(_cover_crop(im, x1 - x0, y1 - y0, ct.get("place", "center"), ct.get("crop")), (x0, y0))
                try:
                    pp = _final_people(kit, args.ep, ct, f)      # 완성 그림에서 몸·머리 (말풍선이 캐릭터를 덜 가리게)
                    if pp.get("mask"):
                        mk = Image.open(pp["mask"]).convert("L").resize(im.size)
                        if ct.get("flip"):
                            mk = mk.transpose(Image.FLIP_LEFT_RIGHT)
                        PM.paste(_cover_crop(mk, x1 - x0, y1 - y0, ct.get("place", "center"), ct.get("crop")), (x0, y0))
                    if st.get("v2") and (ct.get("_char") or ct.get("_roles")):
                        import nk_animeseg
                        sm = nk_animeseg.cached_mask(os.path.join(ep_dir(kit, args.ep), "poses"), cid, f)
                        if sm is not None:
                            from PIL import ImageChops
                            sm = sm.resize(im.size)
                            if ct.get("flip"):
                                sm = sm.transpose(Image.FLIP_LEFT_RIGHT)
                            sm = _cover_crop(sm, x1 - x0, y1 - y0, ct.get("place", "center"), ct.get("crop"))
                            PM.paste(ImageChops.lighter(PM.crop((x0, y0, x1, y1)), sm), (x0, y0))
                    if st.get("v2") and str(ct.get("shot")) in ("face", "eyes") and (ct.get("_char") or ct.get("_roles")):
                        import nk_letter2
                        nk_letter2.face_center(PM, ct["rect"])
                    hb = _heads_to_page(ct, ct["rect"], im.size, pp.get("heads") or [], 1.0, 1.0)
                    if not hb and not _composed(kit, args.ep, cid, f):
                        hb = _head_boxes(kit, args.ep, ct, ct["rect"], im.size, f)   # 예전 방법 (그리기 전 뼈대 그림)
                    heads_pg.extend(hb)
                except Exception as e:           # 머리 자리를 못 구해도 조립은 계속 (예전처럼 윤곽선만으로)
                    print("[note] cut %d: head boxes skipped (%s)" % (cid, e))
            else:
                d.text((x0 + 10, y0 + 10), "cut %d: no image" % cid, fill="red", font=_font(st.get("font"), 24))
        from PIL import ImageFilter
        st["_edges"] = P.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.BoxBlur(6))
        st["_occupied"] = []
        st["_heads"] = heads_pg
        st["_people"] = PM
        for ct in [x for x in c["cuts"] if int(x["page"]) == pn]:       # 코드로 그리는 강조선 (말풍선 자리 판단 뒤라 선이 '복잡한 곳'으로 안 잡힘)
            if ct.get("fx"):
                _draw_fx(P, ct["rect"], ct["fx"], ct, st if st.get("v2") else None)
        for ct in [x for x in c["cuts"] if int(x["page"]) == pn]:       # frames after the edge map (so frames don't count as "busy")
            x0, y0, x1, y1 = ct["rect"]
            d.rectangle([x0, y0, x1 - 1, y1 - 1], outline="black", width=int(st["border"]))
        for ct in [x for x in c["cuts"] if int(x["page"]) == pn and x.get("_pop")]:
            _pop_out(P, kit, args.ep, ct, int(st["border"]))
        spans = _real_spans(kit, args.ep)
        for ct in [x for x in c["cuts"] if int(x["page"]) == pn]:       # bubbles last so they may overlap frames
            x0, y0, x1, y1 = ct["rect"]
            items = _merge_same_speaker(ct.get("text", []), (x1 - x0) * (y1 - y0) < SMALL_PANEL * W * H)
            st["_cut"] = dict(_with_real_spans(ct, spans), text=items)
            st["_cut_oid"] = id(ct)                     # 머리 상자는 원본 컷 기준 (사본을 만들어도 얼굴을 피하게)
            for i, item in enumerate(items):
                _draw_item(P, d, item, (x0, y0, x1 - x0, y1 - y0), st, i)
        d.text((W / 2 - 10, H - st["margin"] * 0.6), str(pn), fill="black", font=_font(st.get("font"), 22))
        P.save(os.path.join(out, "page_%02d.png" % pn))
        imgs.append(P)
    # spread preview: right page = odd, left page = even (Japanese binding)
    sp = []
    for k in range(0, len(imgs), 2):
        pair = imgs[k:k + 2]
        S = Image.new("RGB", (W * 2 + 20, H), (200, 200, 200))
        S.paste(pair[0], (W + 20, 0))
        if len(pair) > 1:
            S.paste(pair[1], (0, 0))
        sp.append(S)
    for k, S in enumerate(sp, 1):
        S.save(os.path.join(out, "spread_%02d.png" % k))
    Image.init()                     # PDF writer needs the JPEG plugin registered (lazy-loaded otherwise -> KeyError 'JPEG')
    imgs[0].save(os.path.join(out, "book.pdf"), save_all=True, append_images=imgs[1:], resolution=150)
    print("pages -> %s  (%d pages %dx%d + spreads + book.pdf)" % (out, len(imgs), W, H))
    try:                                 # 표지 = page_00.png + book.pdf 맨 앞 (nk_cover.py, 설정 cover.yaml). 실패해도 페이지는 그대로
        import nk_cover
        nk_cover.attach(nk, kit, args.ep, c, out, W, H)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        print("[note] cover skipped (%s)" % " ".join(str(e).split())[:200])
    try:                                 # 웹툰판 = out/webtoon/index.html (nk_webview.py, 끄기: presets.yaml manga: webview: false). 실패해도 페이지는 그대로
        import nk_webview
        nk_webview.attach(nk, kit, args.ep, c, out, st, getattr(args, "style", None))
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        print("[note] webtoon view skipped (%s)" % " ".join(str(e).split())[:200])


def letter(nk, kit, args):
    from PIL import Image, ImageDraw
    cfg = nk.load_presets()
    cc = load_conti(nk, kit, args.ep)
    if cc.get("format") == "page":
        return page_letter(nk, kit, args, cc)
    st = dict({"width": 800, "margin": 40, "gap": 120, "top": 80, "font": "", "font_size": 26, "line": 3,
               "slice_height": 1600, "border": 3}, **(cfg.get("webtoon") or {}))
    c = load_conti(nk, kit, args.ep)
    picks = load_picks(kit, args.ep)
    edir = ep_dir(kit, args.ep)
    W = int(st["width"])
    pw = W - 2 * int(st["margin"])
    panels = []
    for cut in c["cuts"]:
        cid = int(cut["id"])
        f = _styled(os.path.join(edir, "cuts", "cut%02d.png" % cid), getattr(args, "style", None))
        if not os.path.exists(f):
            _, f = _picked_meta(cfg, kit, args.ep, cid, picks.get(cid, 1))   # fall back to the draft
            if not f:
                print("[skip] cut %d: no image yet" % cid)
                continue
            print("[note] cut %d: using draft (run nk ep final for high quality)" % cid)
        im = Image.open(f).convert("RGB")
        h = int(im.height * pw / im.width)
        panels.append((cut, im.resize((pw, h), Image.LANCZOS)))
    if not panels:
        print("[ERROR] nothing to letter")
        sys.exit(1)
    H = int(st["top"]) * 2 + sum(p[1].height for p in panels) + sum(int(p[0].get("gap_after", st["gap"])) for p in panels[:-1])
    S = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(S)
    y = int(st["top"])
    for cut, im in panels:
        x = int(st["margin"])
        S.paste(im, (x, y))
        if int(st["border"]):
            d.rectangle([x, y, x + im.width - 1, y + im.height - 1], outline="black", width=int(st["border"]))
        st["_cut"] = dict(_with_real_spans(cut, _real_spans(kit, args.ep)), _img_size=im.size)
        for i, item in enumerate(cut.get("text", [])):
            _draw_item(S, d, item, (x, y, im.width, im.height), st, i)
        y += im.height + int(cut.get("gap_after", st["gap"]))
    out = os.path.join(edir, "out_" + args.style if getattr(args, "style", None) else "out")
    os.makedirs(out, exist_ok=True)
    for f in glob.glob(os.path.join(out, "*.png")):
        os.remove(f)
    S.save(os.path.join(out, "strip.png"))
    sh = int(st["slice_height"])
    n = 0
    for top in range(0, H, sh):
        n += 1
        S.crop((0, top, W, min(H, top + sh))).save(os.path.join(out, "%s_%02d.png" % (args.ep, n)))
    print("strip -> %s  (%dx%d, %d slices)" % (os.path.join(out, "strip.png"), W, H, n))


# ------------------------------------------------------------------ diagnosis: same seeds, one change at a time
TEST_ROUNDS = {
    1: [("B", "painterly 빼기", {"extra": ""}),
        ("C", "LoRA 0.6", {"strength": 0.6}),
        ("D", "LoRA 0 + 외형태그 전부", {"strength": 0.0, "tags": "full"})],
    2: [("E", "LoRA 0.8", {"extra": "", "strength": 0.8}),
        ("F", "LoRA 0.6", {"extra": "", "strength": 0.6})],
    # 같은 시드·같은 프롬프트(세계관 태그 포함)로 LoRA 강도만 바꿈. 캐릭터 모양은 보지 말고 배경만 비교할 것.
    4: [("L", "LoRA 0.7", {"strength": 0.7}),
        ("M", "LoRA 0 (배경만 볼 것)", {"strength": 0.0})],
}
TEST_VARIANTS = TEST_ROUNDS[1]


def test(nk, kit, args):
    """re-draw existing candidates with the SAME seed, changing one thing per row -> grid per cut"""
    from PIL import Image, ImageDraw
    cfg = nk.load_presets()
    c = load_conti(nk, kit, args.ep)
    char = c["_default_char"]
    only = set(int(x) for x in args.cuts) if args.cuts else None
    variants = TEST_ROUNDS[args.round]
    run = "%s/test%s" % (args.ep, "" if args.round == 1 else args.round)
    out_dir = os.path.join(_root(cfg, kit), run)
    plan = []
    for ct in c["cuts"]:
        cid = int(ct["id"])
        if only and cid not in only:
            continue
        mp = os.path.join(_cut_folder(cfg, kit, args.ep, cid), "meta.json")
        if not os.path.exists(mp):
            print("[skip] cut %d: no candidates" % cid)
            continue
        metas = [m for m in json.load(open(mp, encoding="utf-8")) if m["file"][:3].isdigit()]
        scene = nk.resolve_scene(cfg, ct["scene"])
        jobs = []
        for key, _, ov in variants:
            for m in metas:
                st = dict(m["settings"]); st["loras"] = [tuple(x) for x in m.get("loras", [])]
                st.update(ov)
                pos, neg = nk.compose_prompt(st, char, scene)
                label = "cut%02d_%s_%s" % (cid, key, m["file"][:3])
                g = nk.build_graph(cfg, st, char, pos, neg, m["seed"], 1, "nk/%s_test/%s" % (args.ep, label))
                jobs.append({"label": label, "graph": g, "positive": pos, "negative": neg, "settings": st, "seed": m["seed"]})
        plan.append((cid, metas, jobs))
    total = sum(len(p[2]) for p in plan)
    print("test: %d images (%s)" % (total, ", ".join("%s=%s" % (k, n) for k, n, _ in variants)))
    for cid, metas, jobs in plan:
        res = nk.run_jobs(cfg, jobs, run + "/cut%02d" % cid, args.dry)
        if not res:
            continue
        # grid: row A = original drafts, rows B.. = variants
        folder = os.path.join(out_dir, "cut%02d" % cid)
        rows = [("A", "원본")] + [(k, n) for k, n, _ in variants]
        w0, h0 = Image.open(os.path.join(_cut_folder(cfg, kit, args.ep, cid), metas[0]["file"])).size
        tw = 520; th = int(h0 * tw / w0)
        font = _font(cfg.get("webtoon", {}).get("font"), 26)
        G = Image.new("RGB", (220 + len(metas) * (tw + 10), len(rows) * (th + 10) + 50), "white")
        d = ImageDraw.Draw(G)
        for j, m in enumerate(metas):
            d.text((220 + j * (tw + 10), 10), "후보 %s" % int(m["file"][:3]), fill="black", font=font)
        for r, (key, name) in enumerate(rows):
            y = 50 + r * (th + 10)
            d.text((10, y + th // 2 - 30), "%s\n%s" % (key, name), fill="black", font=font)
            for j, m in enumerate(metas):
                f = (os.path.join(_cut_folder(cfg, kit, args.ep, cid), m["file"]) if key == "A"
                     else os.path.join(folder, "cut%02d_%s_%s.png" % (cid, key, m["file"][:3])))
                if os.path.exists(f):
                    G.paste(Image.open(f).convert("RGB").resize((tw, th)), (220 + j * (tw + 10), y))
        gp = os.path.join(out_dir, "cut%02d_grid.png" % cid)
        G.save(gp)
        print("grid ->", gp)



def new(nk, kit, args):
    d = ep_dir(kit, args.ep)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "conti.yaml")
    if os.path.exists(p) and not args.force:
        print("[ERROR] already exists:", p, "(use --force to overwrite)")
        sys.exit(1)
    open(p, "w", encoding="utf-8").write(TEMPLATE)
    print("conti ->", p)
    print("next: edit it (or keep the sample) -> nk ep make %s" % args.ep)


def add_parser(sub, nk, kit):
    ep = sub.add_parser("ep", help="webtoon episode: new / make / redo / pick / letter")
    esub = ep.add_subparsers(dest="ep_cmd")
    a = esub.add_parser("new"); a.add_argument("ep"); a.add_argument("--force", action="store_true")
    a.set_defaults(func=lambda x: new(nk, kit, x))
    for name, fn in (("make", make), ("redo", redo)):
        a = esub.add_parser(name); a.add_argument("ep")
        if name == "redo":
            a.add_argument("cuts", nargs="*", type=int, help="cut numbers, e.g. 3 5")
            a.add_argument("--all", action="store_true", help="every cut in the conti")
        a.add_argument("--n", type=int, default=3, help="candidates per cut")
        a.add_argument("--noqa", action="store_true", help="skip VLM, take candidate 1")
        a.add_argument("--full", action="store_true",
                       help="old way: draw all n candidates and check all (default: adaptive, 2 first, +2 only if none passed)")
        a.add_argument("--seed", type=int); a.add_argument("--dry", action="store_true")
        a.set_defaults(func=(lambda f: (lambda x: f(nk, kit, x)))(fn))
    a = esub.add_parser("pick"); a.add_argument("ep"); a.add_argument("choices", nargs="*", help="cut=candidate, e.g. 3=2")
    a.add_argument("--nofinal", action="store_true", help="only record the choice")
    a.set_defaults(func=lambda x: pick(nk, kit, x))
    a = esub.add_parser("test"); a.add_argument("ep"); a.add_argument("cuts", nargs="*", type=int)
    a.add_argument("--round", type=int, default=1, choices=sorted(TEST_ROUNDS)); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: test(nk, kit, x))
    a = esub.add_parser("letter"); a.add_argument("ep")
    a.add_argument("--style", help="use episodes/<ep>/cuts_<style>/ (from nk ep restyle) and write out_<style>/")
    a.set_defaults(func=lambda x: letter(nk, kit, x))
    try:                                 # nk ep cover <ep> [--redo] (표지만 다시). nk_cover.py 가 없어도 다른 명령은 그대로
        __import__("nk_cover").add_parser(esub, nk, kit)
    except Exception as e:
        print("[note] nk ep cover unavailable (%s)" % e)
    try:                                 # nk ep webview <ep> [--style S] (웹툰판만 다시). nk_webview.py 가 없어도 다른 명령은 그대로
        __import__("nk_webview").add_parser(esub, nk, kit)
    except Exception as e:
        print("[note] nk ep webview unavailable (%s)" % e)
    a = esub.add_parser("restyle",help="repaint final cuts in one art style with Qwen-Image-Edit, e.g. nk ep restyle ep01")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*", type=int); a.add_argument("--style")
    a.add_argument("--seed", type=int); a.add_argument("--dry", action="store_true")
    a.add_argument("--denoise", type=float, help="1.0 = full repaint (default). below ~0.9 the style hardly changes")
    a.add_argument("--check", action="store_true", help="re-compare existing candidates with cuts/ using the tagger and re-pick")
    a.add_argument("--tries", type=int, help="seeds per cut (default 2 = seed, seed+1)")
    a.add_argument("--use", nargs="+", help="choose by hand: cut=seed, e.g. 5=22 (5=0 = keep the original picture)")
    a.add_argument("--force", action="store_true", help="whole episode: redo cuts that did not change since the last restyle too")
    a.set_defaults(func=lambda x: __import__("nk_restyle").run(nk, kit, x))
    a = esub.add_parser("backfix", help="fix back markings of back-view cuts with Qwen + the back sheet, e.g. nk ep backfix ep01 7 21")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*", type=int)
    a.add_argument("--seed", type=int); a.add_argument("--tries", type=int, help="seeds per cut (default 3)")
    a.add_argument("--use", nargs="+", help="choose by hand: cut=seed, e.g. 7=32 (7=0 = back to the picture before backfix)")
    a.add_argument("--any", action="store_true", help="also when the tagger says the character is not seen from behind")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_backfix").run(nk, kit, x))
    a = esub.add_parser("facefix", help="redraw small faces with the character LoRA (head crop), e.g. nk ep facefix ep01 4 20")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*", type=int)
    a.add_argument("--who", help="character key in the conti (default: the one with a LoRA)")
    a.add_argument("--denoise", type=float, help="default 0.85")
    a.add_argument("--seed", type=int); a.add_argument("--tries", type=int, help="seeds per cut (default 2)")
    a.add_argument("--force", action="store_true", help="fix even when the face check says the original face is fine")
    a.add_argument("--use", nargs="+", help="choose by hand: cut=seed, e.g. 4=42 (4=0 = back to the picture before facefix)")
    a.add_argument("--box", nargs="+", help="head box by hand when DWPose misses the shoulders: cut=x0,y0,x1,y1 in final-picture"
                                            " pixels (ear tips to chin), e.g. 5=830,0,1330,540")
    a.add_argument("--sharp", action="store_true", help="add blur tags to the negative (test: keeps the background around the head sharp?)")
    a.add_argument("--boxes", action="store_true", help="only find the head boxes (SAM3, then DWPose) and save pictures of them")
    a.add_argument("--sam", action="store_true", help="SAM3 only (no DWPose fallback) - comparison test")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_facefix").run(nk, kit, x))
    # compile = plan.yaml -> conti.yaml (감독 규칙을 코드가 붙임). 실제 코드는 nk_plan.py
    a = esub.add_parser("write", help="story plan from episodes/<ep>/request.yaml: --backend prompt (for a web AI) or ollama (local)")
    a.add_argument("ep"); a.add_argument("--backend", choices=["prompt", "ollama"], default="prompt")
    a.add_argument("--model", help="ollama model (default: presets qa.model)")
    a.add_argument("--ctx", type=int, default=16384, help="ollama context length")
    a.add_argument("--temperature", type=float, default=0.7)
    a.add_argument("--fix", type=int, default=1, help="repair rounds when the YAML is broken")
    a.add_argument("--cpu", action="store_true", help="run the local model on CPU")
    a.add_argument("--nocompile", action="store_true")
    a.add_argument("--out", help="plan file name in the episode folder (default plan.yaml), e.g. plan_gemma.yaml to compare writers")
    a.set_defaults(func=lambda x: __import__("nk_plan").run_write(nk, kit, x))
    a = esub.add_parser("pull", help="download an approved local writer model into ollama (exaone3.5:7.8b, qwen3:8b)")
    a.add_argument("model"); a.set_defaults(func=lambda x: __import__("nk_plan").run_pull(nk, kit, x))
    a = esub.add_parser("request", help="blank request form episodes/<ep>/request.yaml (characters, artist, pages, story, elements)")
    a.add_argument("ep"); a.add_argument("--overwrite", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_plan").run_request(nk, kit, x))
    a = esub.add_parser("compile", help="episodes/<ep>/plan.yaml -> conti.yaml with the director rules")
    a.add_argument("ep"); a.add_argument("--dry", action="store_true", help="print the conti instead of writing it")
    a.add_argument("--plan", help="plan file name in the episode folder (default plan.yaml)")
    a.set_defaults(func=lambda x: __import__("nk_plan").run_compile(nk, kit, x))
    __import__("nk_easy").add_parsers(esub, nk, kit)
    __import__("nk_charadd").add_parsers(esub, nk, kit)
    a = esub.add_parser("auto", help="whole episode in one go: check, layout, make, facefix, backfix, restyle, letter, review sheet")
    __import__("nk_auto").add_args(a)
    a.set_defaults(func=lambda x: __import__("nk_auto").run(nk, kit, x))
    a = esub.add_parser("compose", help="TEST: two-character cut from two solo pictures with Qwen-Image-Edit, e.g. nk ep compose ep01 8 10")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*", type=int)
    a.add_argument("--src", help="solo cut to use per character, e.g. hero=4,buddy=3 (default: same place, full body)")
    a.add_argument("--seed", type=int); a.add_argument("--tries", type=int, help="seeds per cut (default 2)")
    a.add_argument("--apply", action="store_true", help="pick the best candidate with the tagger and make it the final (original kept)")
    a.add_argument("--use", nargs="+", help="choose by hand: cut=seed, e.g. 8=52 (8=0 = back to the picture before compose)")
    a.add_argument("--qwen", choices=["2509", "2511"], help="TEST: other Qwen edit model -> cuts_compose/q2511/ (nothing installed)")
    a.add_argument("--prompt", choices=["keepstyle", "classic"], help="compose sentence. other = comparison only -> cuts_compose/p_<name>/")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_compose").run(nk, kit, x))
    __import__("nk_styleref").add_parser(esub, nk, kit)
    __import__("nk_web").add_parser(esub, nk, kit)
    __import__("nk_flow").add_parser(esub, nk, kit)
    try:                                 # nk ep duosplit <ep> [컷...] (로라 없는 두 명 컷 나눠 그리기를 따로 돌릴 때). 없어도 nk ep auto 는 그대로
        __import__("nk_duosplit").add_parser(esub, nk, kit)
    except ImportError:
        pass
    __import__("nk_regional").add_parser(esub, nk, kit)
    __import__("nk_joint").add_parser(esub, nk, kit)
    __import__("nk_animatest").add_parser(esub, nk, kit)
    __import__("nk_refine").add_parser(esub, nk, kit)
    __import__("nk_detail").add_parser(esub, nk, kit)
    __import__("nk_inspect").add_parser(esub, nk, kit)
    __import__("nk_animacut").add_parser(esub, nk, kit)
    __import__("nk_trainanima").add_parser(esub, nk, kit)
    __import__("nk_trainmask").add_parser(esub, nk, kit)
    __import__("nk_animafix").add_parser(esub, nk, kit)
    __import__("nk_regionlora").add_parser(esub, nk, kit)
    __import__("nk_edit").add_parser(esub, nk, kit)
    __import__("nk_story").add_parser(esub, nk, kit)
    __import__("nk_lorablock").add_parser(esub, nk, kit)
    __import__("nk_layer").add_parser(esub, nk, kit)
    __import__("nk_headcheck").add_parser(esub, nk, kit)
    __import__("nk_editcmd").add_parser(esub, nk, kit)
    __import__("nk_partfix").add_parser(esub, nk, kit)
    a = esub.add_parser("propfix", help="add a missing prop to a character cut with Qwen-Image-Edit, e.g. nk ep propfix ep01 6 9")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*", type=int)
    a.add_argument("--seed", type=int); a.add_argument("--tries", type=int, help="seeds per cut (default 2)")
    a.add_argument("--use", nargs="+", help="choose by hand: cut=seed, e.g. 6=72 (6=0 = back to the picture before)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_propfix").run(nk, kit, x))
    a = esub.add_parser("samtest", help="TEST: SAM 3.1 masks for text prompts on pictures, e.g. nk ep samtest ep01 cut02 cut08")
    a.add_argument("ep"); a.add_argument("files", nargs="+")
    a.add_argument("--prompts", help="comma separated, e.g. face,hand,cat (':N' = at most N each)")
    a.add_argument("--threshold", type=float, default=0.4); a.add_argument("--dry", action="store_true")
    a.add_argument("--individual", action="store_true", help="one mask per found thing (e.g. both heads in a two-character cut)")
    a.set_defaults(func=lambda x: __import__("nk_sam").run_test(nk, kit, x))
    a = esub.add_parser("handtest", help="TEST: find hands with SAM3 and redraw them (comparison sheets only), e.g. nk ep handtest ep01 5 21")
    a.add_argument("ep"); a.add_argument("cuts", nargs="+")
    a.add_argument("--den", help="denoise list (default per method: sd 0.55,0.7 / dd 0.85,1.0)"); a.add_argument("--seed", type=int)
    a.add_argument("--methods", help="sd,dd,qwen (default sd)")
    a.add_argument("--threshold", type=float, default=0.3); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_handfix").run(nk, kit, x))
    a = esub.add_parser("handfix", help="fix hands whose color does not match the character (SAM3 + dd/Qwen), e.g. nk ep handfix ep01 5 21 --apply")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.add_argument("--seed", type=int); a.add_argument("--threshold", type=float, default=0.3)
    a.add_argument("--apply", action="store_true", help="put the fixed picture in as the final (original kept)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_handfix").run_fix(nk, kit, x))
    a = esub.add_parser("facecheck", help="TEST: ask the VLM whether face-fix heads are broken (cuts_facefix/cand/*_head.png)")
    a.add_argument("ep"); a.add_argument("files", nargs="*", help="head files in cuts_facefix/cand (default: all)")
    a.add_argument("--whole", action="store_true", help="judge the whole picture (default: right half = after)")
    a.add_argument("--pair", action="store_true", help="show before|after together and ask for a comparison")
    a.set_defaults(func=lambda x: __import__("nk_facefix").run_facecheck(nk, kit, x))
    a = esub.add_parser("tags",help="check conti phrases against the tag dictionary (no drawing)"); a.add_argument("ep")
    a.set_defaults(func=lambda x: tags(nk, kit, x))
    a = esub.add_parser("check", help="tag dictionary + direction rules (no drawing)"); a.add_argument("ep")
    a.set_defaults(func=lambda x: check(nk, kit, x))
    a = esub.add_parser("duotest", help="two-character panel test (variants A/B/P/C)"); a.add_argument("ep")
    a.add_argument("--dry", action="store_true")
    a.add_argument("--only", help="scene id prefixes, e.g. d1,d2")
    a.add_argument("--variants", help="e.g. P,C  (default from duotest.yaml or P,C)")
    a.add_argument("--artist", help="artist preset/tag override (default from duotest.yaml)")
    a.add_argument("--tag", help="round name -> runs/<ep>/duotest_<artist>_<tag>/ (keeps earlier results)")
    a.add_argument("--seeds", type=int, help="seeds per scene (default from duotest.yaml). 1 = quick screening")
    a.set_defaults(func=lambda x: duotest(nk, kit, x))
    a = esub.add_parser("train", help="LoRA training from training/<name>.yaml (kohya), e.g. nk ep train v6")
    a.add_argument("name"); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_train").run(nk, kit, x))
    a = esub.add_parser("layout", help="Anima layout pictures for cuts (O mode step 1), e.g. nk ep layout ep01 5 14")
    a.add_argument("ep"); a.add_argument("cuts", nargs="+", type=int); a.add_argument("--seeds", type=int, default=2)
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_pose").layout(nk, kit, x))
    a = esub.add_parser("pose", help="pose skeleton from a layout picture (O mode step 2), e.g. nk ep pose ep01 5 cut05_s2")
    a.add_argument("ep"); a.add_argument("cut", type=int); a.add_argument("image")
    a.set_defaults(func=lambda x: __import__("nk_pose").pose(nk, kit, x))
    a = esub.add_parser("posemask", help="TEST C1: pose from the layout picture with SAM3 person masks (vs half boxes), compare")
    a.add_argument("ep"); a.add_argument("cuts", nargs="+")
    a.add_argument("--words", help='SAM3 word per character file, e.g. "mychar:fox;buddy:girl" (default: anima_find/sam_body in each character file, else its species tag)')
    a.add_argument("--threshold", default="0.3")
    a.add_argument("--out", help="also save the C1 poses into this (new) episode's poses/ (conti copied)")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_pose").posemask(nk, kit, x))
    a = esub.add_parser("layout3d", help="TEST: Anima layout with a 3D doll control image (depth / regional / lineart LLLite)")
    a.add_argument("ep"); a.add_argument("cuts", nargs="+")
    a.add_argument("--pose3d", required=True, help="folder with tools/pose3d renders <dir>/cutNN")
    a.add_argument("--control", choices=["depth", "regional", "lineart"], default="depth")
    a.add_argument("--strength", default="0.6"); a.add_argument("--end", default="1.0"); a.add_argument("--seeds", default="2")
    a.add_argument("--name"); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: __import__("nk_pose").layout3d(nk, kit, x))
    a = esub.add_parser("fetch", help="download an approved model file from huggingface.co into ComfyUI-Shared/models/<folder>")
    a.add_argument("url"); a.add_argument("folder"); a.add_argument("--size", required=True); a.add_argument("--sha256")
    a.add_argument("--name")
    a.set_defaults(func=lambda x: __import__("nk_fetch").run(nk, kit, x))
    a = esub.add_parser("draft"); a.add_argument("ep"); a.add_argument("--n", type=int, default=3)
    a.add_argument("--cuts"); a.add_argument("--seed", type=int); a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: draft(nk, kit, x))
    a = esub.add_parser("final"); a.add_argument("ep"); a.add_argument("--cuts"); a.add_argument("--hires", type=float)
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: final(nk, kit, x))
