# -*- coding: utf-8 -*-
"""nk_charadd.py — 시중 캐릭터(모델이 이미 아는 캐릭터)를 캐릭터 파일로 불러오기

왜: 새 캐릭터를 쓰려면 characters/<이름>.yaml 이 있어야 함
    태그 사전 확인 -> 이름 태그만으로 시험 -> 외형 태그 고르기 -> 외형 설명문 -> 검수 질문 -> 두 명 컷 번짐 태그.
    이 과정을 명령 하나로. 단 마지막 확인은 사람: 판별기가 틀릴 수 있음.

  nk ep charfind <이름...>                   태그 사전에서 캐릭터 태그 후보 (한국어면 검수 AI에게 영어 태그를 물어봄)
  nk ep charadd <태그> [--ko "이름"] [--n 8]  시험 N장 -> 판별기 공통 외형 태그 -> characters/<이름>.yaml 초안 + 확인 그림
  (메뉴 7 = 둘을 이어서)

기준 (추정, 오늘 두 캐릭터로 잰 것): 태그 게시물 1,394장 4/4 알아봄, 774장 2/4 -> 300장 이상 권장, 100장 미만은 LoRA"""
import os, sys, re, csv, json, time, glob

MIN_OK, MIN_TRY = 300, 100
KEEP_RATE = 0.6          # 시험 그림 중 이 비율 이상에서 나온 태그만 외형 태그로
KEEP_SCORE = 0.45
# 외형으로 쓸 태그 (단어가 들어 있으면): 머리·눈·귀·꼬리·옷·장신구·무늬
LOOK_WORDS = ("hair", "eyes", "pupils", "sclera", "ears", "tail", "horn", "fur", "skin", "wings", "halo", "whiskers", "fang",
              "bangs", "ahoge", "braid", "ponytail", "twintails", "bun", "sidelocks", "mark", "tattoo", "scar", "freckles", "mole",
              "shirt", "dress", "jacket", "coat", "cape", "cloak", "robe", "vest", "sweater", "hoodie", "kimono", "uniform", "apron",
              "armor", "pants", "shorts", "skirt", "shoes", "boots", "sandals", "socks", "thighhighs", "gloves", "sleeves", "hat",
              "cap", "helmet", "hood", "mask", "glasses", "eyewear", "goggles", "scarf", "collar", "necktie", "bowtie", "bow",
              "ribbon", "choker", "necklace", "earrings", "jewelry", "belt", "sash", "bag", "pouch", "headband", "hairband",
              "hair ornament", "headwear", "crown", "tiara", "furry", "animal", "robot", "mechanical", "joints", "prosthetic")
# 넣지 않을 것: 자세·구도·배경·표정·몸 노출 (외형이 아니거나 등급에 안 맞음)
DROP = ("solo", "standing", "full body", "looking at viewer", "simple background", "white background", "grey background",
        "smile", "open mouth", "closed mouth", "blush", ":3", "parted lips", "holding", "arms", "hand", "legs", "feet",
        "breasts", "cleavage", "navel", "midriff", "nipples", "thighs", "ass", "barefoot", "stomach", "collarbone",
        "shadow", "signature", "watermark", "border", "cowboy shot", "upper body", "teeth", "tongue", "sweat")
GENDER = ("1girl", "1boy", "1other")
DISTINCT = ("hat", "helmet", "glasses", "eyewear", "goggles", "scarf", "cape", "cloak", "mask", "wings", "halo", "horns",
            "tail", "animal ears", "hood", "crown", "robe", "armor", "necktie", "headband")
COLORS = ("white", "black", "brown", "blonde", "red", "pink", "blue", "green", "purple", "orange", "grey", "silver",
          "yellow", "aqua", "light brown", "dark blue", "light blue", "multicolored", "two-tone", "gradient")


# ---------------------------------------------------------------- 태그 사전 (분류까지)
_DB = None


def _db(kit):
    """{name: (category, count, [aliases])} - tags/danbooru.csv + e621.csv (게시물 수는 큰 쪽)"""
    global _DB
    if _DB is None:
        _DB = {}
        for fn in ("danbooru.csv", "e621.csv"):
            p = os.path.join(kit, "tags", fn)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) < 3:
                        continue
                    try:
                        cat, n = int(row[1] or 0), int(row[2] or 0)
                    except ValueError:
                        continue
                    al = [a.strip() for a in (row[3] if len(row) > 3 else "").split(",") if a.strip()]
                    old = _DB.get(row[0])
                    if old is None or n > old[1]:
                        _DB[row[0]] = (cat, n, al + (old[2] if old else []))
    return _DB


def search(kit, words, limit=10):
    """캐릭터 태그(분류 4) 중 단어가 모두 들어간 것, 게시물 많은 순"""
    toks = [t for t in re.split(r"[\s_()\-:,]+", " ".join(words).lower()) if t]
    if not toks:
        return []
    out = []
    for name, (cat, n, al) in _db(kit).items():
        if cat != 4:
            continue
        hay = " ".join([name] + al).lower().replace("_", " ")
        if all(t in hay for t in toks):
            out.append((n, name))
    return [(name, n) for n, name in sorted(out, reverse=True)[:limit]]


def _ask_llm_tags(nk, text):
    """한국어 이름 -> 영어 Danbooru 태그 후보 (검수 AI = Ollama). 실패하면 []"""
    try:
        import nk_plan
        q = nk.load_presets().get("qa", {})
        msg = ("Give the Danbooru character tag(s) for this character. The user wrote the name in Korean: \"%s\". "
               "Answer ONLY a JSON array of up to 3 lowercase tags with underscores, e.g. [\"character_name_(series_name)\"]." % text)
        raw, _ = nk_plan._ollama_chat(q.get("ollama", "http://127.0.0.1:11434"), q.get("model", "gemma4:e4b-it-qat"),
                                      [{"role": "user", "content": msg}], 4096, 0.2)
        m = re.search(r"\[.*?\]", raw, re.S)
        return [str(x).strip() for x in json.loads(m.group(0))] if m else []
    except Exception as e:
        print("  (검수 AI에게 못 물어봄: %s)" % e)
        return []


def find(nk, kit, words):
    text = " ".join(words).strip()
    res = search(kit, words)
    if re.search(r"[가-힣]", text):
        guesses = _ask_llm_tags(nk, text)
        db = _db(kit)
        seen = {r[0] for r in res}
        for g in guesses:
            g = g.replace(" ", "_")
            if g in db and db[g][0] == 4 and g not in seen:
                res.append((g, db[g][1])); seen.add(g)
            for r in search(kit, [g.split("_(")[0]], 5):       # 이름 부분만으로도
                if r[0] not in seen:
                    res.append(r); seen.add(r[0])
        res.sort(key=lambda r: -r[1])
    return res[:10]


def run_find(nk, kit, args):
    res = find(nk, kit, args.words)
    if not res:
        print("후보 없음. 영어 이름으로 다시 (예: nk ep charfind <영어 이름> <작품 이름>) - 태그 사전에 없으면 모델이 모르는 캐릭터 (LoRA 필요)")
        return
    for i, (t, n) in enumerate(res, 1):
        print("%2d. %-45s %6d장  %s" % (i, t, n, verdict(n)))


def verdict(n):
    return "좋음 (파일만으로 될 것)" if n >= MIN_OK else ("해 볼 만함 (흔들릴 수 있음)" if n >= MIN_TRY else "적음 (LoRA 필요할 것)")


# ---------------------------------------------------------------- 불러오기
def _copyright(kit, tag):
    db = _db(kit)
    cands = []
    for t in [tag] + list(db.get(tag, (0, 0, []))[2]):
        for q in re.findall(r"\(([^()]+)\)", t):
            q = q.strip()
            if q in db and db[q][0] == 3:
                cands.append((db[q][1], q))
    return max(cands)[1] if cands else ""


def _esc(t):
    return t.replace("_", " ").replace("(", "\\(").replace(")", "\\)")


def _cats(kit):
    import nk_tagger
    p = os.path.join(nk_tagger.model_dir(kit), "selected_tags.csv")
    with open(p, encoding="utf-8") as f:
        return {r["name"]: int(r.get("category") or 0) for r in csv.DictReader(f)}


def _is_look(t):
    s = t.replace("_", " ")
    if s in DROP or s.startswith("holding") or s.startswith("arms ") or s.startswith("hand ") or s.startswith("hands "):
        return False
    if any(w in s for w in ("breast", "nipple", "cleavage", "navel", "panties", "underwear", "pussy", "penis", "nude")):
        return False
    return any(w in s for w in LOOK_WORDS)


def _colors_of(tags, word):
    return [t for t in tags if t.endswith("_" + word) and t[: -len(word) - 1].replace("_", " ") in COLORS]


def aggregate(kit, files, tag):
    """그림 여러 장의 판별기 태그 -> (공통 외형 태그, 성별 태그, {태그: 장수}, 캐릭터 점수 목록, 장수)"""
    import nk_tagger
    cats = _cats(kit)
    hit, recog = {}, []
    for f in files:
        t = nk_tagger.tags(kit, f) or {}
        recog.append(round(float(t.get(tag, 0.0)), 2))
        for k, v in t.items():
            if v >= KEEP_SCORE and cats.get(k, 0) == 0:
                hit[k] = hit.get(k, 0) + 1
    n = max(1, len(files))
    common = sorted([k for k, c in hit.items() if c / n >= KEEP_RATE], key=lambda k: -hit[k])
    gender = max(GENDER, key=lambda g: hit.get(g, 0)) if any(hit.get(g) for g in GENDER) else ""
    look = [k for k in common if _is_look(k) and k not in GENDER]
    return look, gender, hit, recog, n


def build_text(tag, fname, ko, look, gender, cr, base, n_posts, n, rec_n, run):
    """판별기 공통 태그 -> 캐릭터 파일 글 (text, tags_short 목록, anima)"""
    hum = lambda ts: ", ".join(t.replace("_", " ") for t in ts)
    short = [x for x in [cr.replace("_", " ") if cr else "", gender] if x] + [t.replace("_", " ") for t in look[:8]]
    full = [x for x in [cr.replace("_", " ") if cr else "", gender] if x] + [t.replace("_", " ") for t in look]
    hair = _colors_of(look, "hair")
    eyes = _colors_of(look, "eyes")
    cloth = ("shirt", "dress", "jacket", "coat", "cape", "cloak", "robe", "vest", "sweater", "hoodie", "kimono", "uniform", "apron",
             "armor", "pants", "shorts", "skirt", "shoes", "boots", "sandals", "socks", "thighhighs", "gloves", "sleeves", "hat", "cap",
             "helmet", "hood", "mask", "glasses", "eyewear", "goggles", "scarf", "collar", "necktie", "bow", "ribbon", "choker",
             "necklace", "earrings", "jewelry", "belt", "sash", "bag", "pouch", "headband", "hairband", "ornament", "headwear",
             "crown", "tiara")
    wear = [t for t in look if any(w in t for w in cloth) and not t.endswith("_hair") and "hair_" not in t]
    body = [t for t in look if t not in wear and t not in hair and t not in eyes]
    who = {"1girl": "girl", "1boy": "boy"}.get(gender, "character")
    series = cr.replace("_", " ").title() if cr else ""
    name_en = base.replace("_", " ").title()
    anima = "%s%s, a %s%s%s%s" % (name_en, " from " + series if series else "", who,
                                  " with " + hum(hair + eyes + body) if (hair or eyes or body) else "",
                                  ", wearing " + hum(wear) if wear else "", "")
    dist = [t.replace("_", " ") for t in look if any(d in t.replace("_", " ") for d in DISTINCT)]
    neg = {"1girl": "1boy, male focus, muscular", "1boy": "1girl, breasts, female", "1other": "breasts"}.get(gender, "")
    qa = []
    if hair:
        c0 = hair[0].rsplit("_hair", 1)[0].replace("_", " ")
        opts = [c0] + [c for c in ("black", "brown", "blonde", "white", "red", "blue", "pink") if c != c0][:4] + ["not visible"]
        qa.append({"id": "c_hair", "must": True, "q": "What color is the character's hair?", "options": opts, "expect": [c0, "not visible"]})
    if eyes:
        c0 = eyes[0].rsplit("_eyes", 1)[0].replace("_", " ")
        opts = [c0] + [c for c in ("blue", "red", "green", "brown", "yellow", "purple") if c != c0][:4] + ["not visible"]
        qa.append({"id": "c_eyes", "must": False, "q": "What color are the character's eyes?", "options": opts, "expect": [c0, "not visible"]})
    qa.append({"id": "text", "must": True, "q": "Is there any text, signature, or watermark in the image?",
               "options": ["no text at all", "there is text or a signature or watermark"], "expect": ["no text"]})
    import yaml
    head = ("# ============================================================\n"
            "#  characters/%s.yaml — %s  (nk ep charadd 초안, %s)\n"
            "#  LoRA 없음: 태그 사전 %s %d장. 시험 %d장 중 판별기가 이 캐릭터로 본 그림 %d장 (-1 = 판별기가 모르는 캐릭터).\n"
            "#  외형 태그 = 시험 그림 %d%% 이상에 나온 판별기 태그 (자동). 틀린 태그가 있을 수 있음 -> runs\\%s\\sheet.png 보고 고치기\n"
            "#  개인 비상업 팬아트 시험용. 공유할 때 원작 표기.\n"
            "# ============================================================\n"
            % (fname, ko or name_en, time.strftime("%Y-%m-%d %H:%M"), tag, n_posts, n, rec_n, int(KEEP_RATE * 100), run))
    body_d = {"name": fname, "trigger": _esc(tag), "name_ko": ko or name_en, "lora": None, "draft": True,
              "tags_short": ", ".join(short), "tags_full": ", ".join(full),
              "compose_name": ("%s %s" % (hair[0].rsplit("_hair", 1)[0].replace("_", "-") + "-haired" if hair else "", who)).strip(),
              "anima": anima, "negative_extra": neg, "duo_exclusive": ", ".join(dist),
              "qa_desc": "the character %s" % name_en, "qa_checklist": qa}
    text = head + yaml.safe_dump(body_d, allow_unicode=True, sort_keys=False, width=160)
    return text, short, anima


def run_add(nk, kit, args):
    import nk_tagger
    from PIL import Image, ImageDraw
    tag = args.tag.strip().replace(" ", "_")
    db = _db(kit)
    if tag not in db or db[tag][0] != 4:
        print("[ERROR] '%s'는 태그 사전의 캐릭터 태그가 아님 -> nk ep charfind 로 찾기" % tag); sys.exit(1)
    n_posts = db[tag][1]
    base = re.sub(r"_\(.*$", "", tag)
    fname = re.sub(r"[^a-z0-9_]", "", base.lower()) or "char"
    if os.path.exists(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), fname + ".yaml")) and not args.overwrite:
        fname = fname + "_" + re.sub(r"[^a-z0-9]", "", _copyright(kit, tag))[:12]
        if os.path.exists(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), fname + ".yaml")):
            print("[ERROR] characters/%s.yaml 이 이미 있음 (--overwrite)" % fname); sys.exit(1)
    cr = _copyright(kit, tag)
    print("character: %s (%d posts, %s) / series tag: %s / file: characters/%s.yaml" % (tag, n_posts, verdict(n_posts), cr or "-", fname))
    if n_posts < MIN_TRY and not args.force_low:
        print("[STOP] 게시물이 %d장뿐 - 모델이 잘 모를 가능성이 큼 (LoRA 필요). 그래도 해 보려면 --force-low" % n_posts); sys.exit(1)
    # 1) 시험 그림: 이름·작품 태그만 + 단색 배경 (외형만 보이게)
    cfg = nk.load_presets()
    import argparse
    ns = argparse.Namespace(preset=args.artist, extra=None, neg=None, lora=None, size="832x1216", rating="safe", cfg=None,
                            steps=None, sampler=None, scheduler=None, quality=None, year=None, artist=None, artist_weight=None,
                            artist_position=None, tags=None, strength=None, charlora=None, hires=0, hires_denoise=None,
                            hires_steps=None, hires_method=None, upscale_model=None)
    scene = ", ".join(x for x in [_esc(tag), cr.replace("_", " ") if cr else "", "solo, standing, full body, looking at viewer, "
                                  "simple background, white background"] if x)
    run = "charadd_" + fname
    jobs = []
    for i in range(int(args.n)):
        s = nk.build_settings(cfg, ns)
        pos, neg = nk.compose_prompt(s, None, scene)
        sd = int(args.seed) + i
        jobs.append({"label": "%s_s%d" % (fname, sd), "graph": nk.build_graph(cfg, s, None, pos, neg, sd, 1, "nk/%s/%s_s%d" % (run, fname, sd)),
                     "positive": pos, "negative": neg, "seed": sd, "settings": s})
    res = nk.run_jobs(cfg, jobs, run, args.dry)
    if args.dry:
        return
    out_dir = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), run)
    files = [os.path.join(out_dir, r["file"]) for r in res]
    try:
        nk.Comfy(cfg.get("server", "auto")).free()
    except SystemExit:
        pass
    # 2) 판별기: 그림마다 태그 -> 여러 장에 공통인 외형 태그
    look, gender, hit, recog, n = aggregate(kit, files, tag)
    rec_n = sum(1 for r in recog if r >= 0.35)
    known = tag in nk_tagger.vocab(kit)
    if known:
        print("\n판별기가 이 캐릭터로 알아본 그림: %d/%d (%s)" % (rec_n, n, ", ".join("%.2f" % r for r in recog)))
    else:
        rec_n = -1
        print("\n판별기는 이 캐릭터 이름을 모름 (판별기 단어장에 없음) -> 알아봤는지는 눈으로 확인")
    print("공통 외형 태그 (%d장 중 몇 장): %s" % (n, ", ".join("%s(%d)" % (k, hit[k]) for k in look) or "(없음)"))
    # 3) 캐릭터 파일 초안
    text, short, anima = build_text(tag, fname, args.ko, look, gender, cr, base, n_posts, n, rec_n, run)
    cp = os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), fname + ".yaml")
    draft = os.path.join(out_dir, fname + ".yaml")
    open(draft, "w", encoding="utf-8").write(text)
    # 4) 확인 그림: 시험 그림 + 판별기 결과
    H = 420
    tiles = []
    for f, r in zip(files, recog):
        im = Image.open(f).convert("RGB")
        tiles.append((os.path.basename(f), r, im.resize((int(im.width * H / im.height), H))))
    W = sum(t[2].width for t in tiles) + 8 * len(tiles)
    lines = ["%s  (%d posts)  recognized %s" % (tag, n_posts, "%d/%d" % (rec_n, n) if rec_n >= 0 else "? (tagger does not know it)"), "tags_short: " + ", ".join(short)[:200],
             "anima: " + anima[:200]]
    sheet = Image.new("RGB", (max(W, 900), H + 26 + 18 * len(lines)), "white")
    d = ImageDraw.Draw(sheet)
    x = 0
    for fn, r, im in tiles:
        sheet.paste(im, (x, 24)); d.text((x + 4, 5), "%s  %.2f" % (fn[-12:], r), fill="black"); x += im.width + 8
    for i, ln in enumerate(lines):
        d.text((6, H + 30 + 18 * i), ln, fill="black")
    sp = os.path.join(out_dir, "sheet.png")
    sheet.save(sp)
    print("\n확인 그림: %s\n초안: %s" % (sp, draft))
    if args.save:
        open(cp, "w", encoding="utf-8").write(text)
        print("저장: %s  (글콘티용 첨부 파일 다시 만들기: nk ep aifile)" % cp)
    else:
        print("저장하려면: nk ep charadd %s --save (같은 시드라 같은 결과) 또는 초안을 characters\\ 로 복사" % tag)
    return {"tag": tag, "file": cp, "draft": draft, "sheet": sp, "text": text, "recognized": rec_n, "n": n}


def add_parsers(esub, nk, kit):
    a = esub.add_parser("charfind", help="find a character tag in the tag dictionary (Korean names: asks the local AI), e.g. nk ep charfind <name> <series>")
    a.add_argument("words", nargs="+")
    a.set_defaults(func=lambda x: run_find(nk, kit, x))
    a = esub.add_parser("charadd", help="make characters/<name>.yaml from a character tag: test pictures -> common look tags (tagger) -> draft")
    a.add_argument("tag"); a.add_argument("--ko", help="Korean display name, e.g. 캐릭터 이름 (작품 이름)")
    a.add_argument("--n", type=int, default=8); a.add_argument("--seed", type=int, default=501)
    a.add_argument("--artist", help="preset/artist for the test pictures (default: none)")
    a.add_argument("--save", action="store_true", help="write characters/<name>.yaml (otherwise only the draft in runs/)")
    a.add_argument("--overwrite", action="store_true"); a.add_argument("--force-low", dest="force_low", action="store_true")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run_add(nk, kit, x))
