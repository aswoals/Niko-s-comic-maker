# -*- coding: utf-8 -*-
"""이야기 계획(plan.yaml) -> 콘티(conti.yaml) 컴파일러

왜 둘로 나누나:
  콘티(conti.yaml)에는 시험 만화에서 배운 규칙이 잔뜩 들어감 (두 명 컷 방식, 테두리 부정 태그, 모자 판별기 검수, 페이지 줄 나누기 ...).
  이걸 매번 글 쓰는 AI가 기억해서 쓰게 하면 빠뜨림. 그래서
    - 글 쓰는 쪽(사람·웹 AI·로컬 AI)은 '이야기 계획'만: 페이지·컷마다 누가, 어디서, 거리·각도, 동작 태그, 대사
    - 규칙은 이 코드가 기계적으로 붙임 = 연출 감독 규칙 (docs/conti_rules.md)
  -> 어떤 AI가 계획을 쓰든 같은 규칙이 지켜짐.

plan.yaml 형식 (docs/prompt_plan.md 에 예시):
  title, artist, restyle
  locations: {park: "park, grass, tree, blue sky, cloud, summer, outdoors, day"}
  props: {ball: "ball"}              (선택, qa: true 면 판별기 검수 붙임 -> {ball: {tags: "ball", qa: true}})
  wear / state: conti world와 같은 모양 (cuts: "1-5,9" 또는 "all")
  pages:
    - note: "기 — ..."
      cuts:
        - who:                 # [] = 사람 없는 컷, = 두 명
          shot: knee                  # wide / full / knee / waist / face / detail
          angle: eye                  # eye / high / low / side / back / tilt
          loc: park
          action: "running, happy"    # 태그. 두 명 컷이면 두 사람 공통
          props: [ball]
          fx: speed                   # 선택: focus / speed / speed_v
          big: true                   # 선택: 페이지 안에서 크게 (한 줄 통째로, 더 높게)
          lines:
감독 규칙 (코드가 적용, 바꾼 것은 콘티 머리말 주석과 화면에 남김):
  D1 두 명 컷에서 물건 주고받기·안기·손잡기 같은 '닿는 동작' -> 혼자 컷으로 (focus 또는 대사 많은 사람). 대사는 그대로(화면 밖 말풍선)
27을 혼자 컷으로 바꾸자 첫 회 2/2 성공
  D2 두 명 컷 얼굴(face) 샷 -> knee
face는 시험 안 함 = 그대로
  D3 두 명 컷이 사람 나오는 컷의 35%를 넘으면 경고
  D4 두 명 컷 자리: 먼저 말하는 사람이 오른쪽 (오른쪽 -> 왼쪽으로 읽음)
  D5 두 명 컷 기본 방식 MB (뼈대는 nk ep auto의 layout 단계가 자동으로 고름)"""
import os, sys, re, json

SHOTS = ("wide", "full", "knee", "waist", "face", "detail", "eyes", "hands")
ANGLES = ("eye", "high", "low", "side", "back", "tilt", "pov")
#   (duo1 닿는 동작 0/3 인 채로 풀기로 함 = 닿는 동작이 두 명 컷의 정면 과제. 근거 docs/reports/0928_1111_M1b_duo1_layer_judge.html)
#   D2 (두 명 컷 얼굴 샷 -> knee)·D3 (두 명 컷 35% 넘으면 경고)도 기본 끔. 다시 켜려면 plan.yaml rules_on: [D2]
RULES_OFF_DEFAULT = {"D1", "D2", "D3"}
TOUCH = ["giving", "give", "handing over", "handing", "sharing food", "sharing", "hug", "hugging", "holding hands",
         "carrying another", "piggyback", "kiss", "high five", "feeding", "headpat", "head pat", "hand on another's",
         "arm around", "touching another"]
# 혼자 컷에서 문제인 것 = 상대가 꼭 있어야 하는 동작만 (pushing·carrying 은 물건을 밀고 들 수도 있어서 뺌)
SOLO_TOUCH = ["hug", "hugging", "holding hands", "kiss", "high five", "piggyback", "headpat", "head pat", "arm around",
              "hand on another's", "feeding"]
# 연출 규칙 12 (같은 캐릭터 같은 자세 반복) 검사에 쓰는 몸 자세 태그
POSTURE = ["sitting", "standing", "lying", "on back", "on stomach", "kneeling", "squatting", "crouching", "walking", "running",
           "jumping", "seiza", "sitting on bench"]
NEG_ALWAYS = "english text, text, signature, watermark, black border, letterboxed, pillarboxed, vignetting, fisheye"
OBJECT_CUT = {"tags": "no humans, anime coloring, official art",
              "neg": "photorealistic, realistic, 3d, depth of field, blurry, flat color, vector",
              "qa": {"q": "What is the art style?",
                     "options": ["anime illustration with outlines and cel shading", "photograph or photorealistic 3d render",
                                 "flat vector clip art"],
                     "expect": ["anime illustration"], "must": True}}
LOC_NEG = "simple background, white background, indoors"
ANIMA_DEFAULTS = {"anima_tags": "anime coloring, flat color, lineart", "anima_neg": "depth of field, blurry background, bokeh, 3d, realistic"}
LOC_NEG_INDOORS = "simple background, white background, outdoors"


def _loc_neg(tags):
    return LOC_NEG_INDOORS if "indoors" in [t.strip().lower() for t in str(tags).split(",")] else LOC_NEG
DUO_LORA_NEG = "horns, heterochromia, orange eyes, long hair"


def _tags(s):
    return [t.strip() for t in str(s or "").split(",") if t.strip()]


def _join(*parts):
    out = []
    for p in parts:
        for t in _tags(p):
            if t not in out:
                out.append(t)
    return ", ".join(out)


def _touchy(text, words=None):
    low = " " + str(text or "").lower() + " "
    return [w for w in (words or TOUCH) if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)]


def _ranges(ids):
    """[1,2,3,5] -> '1-3,5'"""
    ids = sorted(set(int(i) for i in ids))
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(str(ids[i]) if i == j else "%d-%d" % (ids[i], ids[j]))
        i = j + 1
    return ",".join(out)


def _fix_tags(db, text, W):
    """D7: Danbooru 태그가 아닌 말 -> 그 안의 가장 긴 진짜 태그로 ('large snowball' -> 'snowball', 'gentle smile' -> 'smile').
    진짜 태그 조각이 없으면 그대로 둠 (모델이 느슨한 단어로라도 읽음). 돌려줌: (고친 문자열, [(원래, 바꾼 것)])"""
    if not db:
        return text, []
    out, changed = [], []
    for t in _tags(text):
        st, _ = W._tag_verdict(db, t)
        if st != "NOT A TAG" or t.startswith("("):
            out.append(t); continue
        words = [w for w in re.split(r"[\s_]+", t) if w]
        best = None
        for n in range(len(words) - 1, 0, -1):          # 긴 조각부터
            for i in range(0, len(words) - n + 1):
                cand = " ".join(words[i:i + n])
                if cand.lower() in ("two", "small", "large", "big", "the", "a", "at", "on", "in", "of", "by", "side", "down", "up",
                                    "heavy", "little", "gentle", "soft", "bright", "light", "dark", "huge", "tiny", "very", "slightly",
                                    "slow", "fast", "strong", "wet", "cold", "warm", "happy", "sad", "cute", "old", "new", "long", "short"):
                    continue
                if W._tag_verdict(db, cand)[0] in ("ok", "color+tag"):
                    best = cand; break
            if best:
                break
        if best:
            if best not in out:
                out.append(best)
            changed.append((t, best))
        else:
            out.append(t)
    return ", ".join(out), changed


#    -> 입 벌린 모습(open mouth)으로. 대사 말풍선은 우리가 letter 단계에서 따로 넣으므로 그림 속 말풍선 태그는 뺌
TALK_TAGS = ("talking", "talking to viewer", "talking to another", "speaking", "conversation", "dialogue", "chatting")
WHOLE_TINT = ("monochrome", "greyscale", "grayscale", "sepia", "limited palette", "spot color", "high contrast", "silhouette",
              "partially colored", "inverted colors")
BUBBLE_TAGS = ("speech bubble", "spoken heart", "spoken question mark", "spoken exclamation mark", "text", "english text")


def _talk_fix(text):
    out, changed = [], []
    for t in _tags(text):
        k = t.lower().replace("_", " ")
        if k in TALK_TAGS:
            changed.append((t, "open mouth"))
            if "open mouth" not in out:
                out.append("open mouth")
        elif k in BUBBLE_TAGS:
            changed.append((t, ""))
        elif t not in out:
            out.append(t)
    return ", ".join(out), changed


#   색 단어를 뗀 것(white_bowl -> bowl)도 같이 넣음 (그리기 모델은 색+명사를 알아듣지만 판별기는 한 단어 태그만 앎).
PROP_COLORS = ("red", "pink", "blue", "navy", "dark", "light", "white", "black", "grey", "gray", "brown", "yellow",
               "green", "orange", "purple", "gold", "silver", "beige", "cream")


def _prop_qa_tag(tags):
    """'white bowl, mixing bowl, whisk' -> 'white_bowl|bowl|mixing_bowl|whisk'"""
    out = []
    for t in str(tags or "").split(","):
        k = t.strip().lower().replace(" ", "_")
        if not k:
            continue
        ws = k.split("_")
        i = 0
        while i < len(ws) - 1 and ws[i] in PROP_COLORS:
            i += 1
        for x in (k, "_".join(ws[i:])):
            if x not in out:
                out.append(x)
    return "|".join(out)


def _rows(cuts):
    """페이지 줄 나누기 (페이지 1600x2259, 여백 70: 안쪽 폭 1460).
    - 사람 없는 wide 컷·big 컷만 한 줄 통째로, 나머지는 둘씩 (detail도 짝으로)
    - 끝에 하나 남으면 앞 줄에 붙여 셋 (사람 컷이 혼자 넓은 줄에 있으면 2.2:1 넘어서 머리·발이 잘림 - ep check 경고)
    - 높이: 사람 없는 wide 0.22 / big 0.40 / 둘 0.28 / 셋 0.26 -> 합 1로. 사람이 있는 한 줄 컷은 최소 0.34"""
    rows, i, n = [], 0, len(cuts)
    while i < n:
        c = cuts[i]
        if c["_big"] or (i == 0 and c["shot"] == "wide" and not c["_who"]):
            rows.append([c]); i += 1; continue           # big 컷, 페이지 첫 풍경 wide = 한 줄 통째로
        if i + 1 < n and not cuts[i + 1]["_big"]:
            rows.append([c, cuts[i + 1]]); i += 2; continue
        # 혼자 남은 컷 (다음이 big이거나 끝): 앞 줄에 붙여 셋, 또는 앞의 풍경 한 줄과 둘
        duo = lambda x: len(x["_who"]) >= 2
        if rows and len(rows[-1]) == 2 and not any(x["_big"] for x in rows[-1]) and duo(c):
            rows.append([c])
        elif rows and len(rows[-1]) == 2 and not any(x["_big"] for x in rows[-1]) and duo(rows[-1][0]):
            a, b = rows[-1]
            rows[-1] = [a]
            rows.append([b, c])
        elif rows and len(rows[-1]) == 2 and not any(x["_big"] for x in rows[-1]):
            rows[-1].append(c)
        elif rows and len(rows[-1]) == 1 and not rows[-1][0]["_who"] and not rows[-1][0]["_big"]:
            rows[-1].append(c)
        else:
            rows.append([c])
        i += 1
    base = []
    for r in rows:
        if len(r) == 1:
            base.append(0.40 if r[0]["_big"] else (0.22 if not r[0]["_who"] else 0.36))
        else:
            base.append(0.28 if len(r) == 2 else 0.26)
    tot = sum(base)
    hs = [b / tot for b in base]
    need = [i for i, r in enumerate(rows) if len(r) == 1 and r[0]["_who"]]
    for i in need:
        if hs[i] < 0.34:
            lack = 0.34 - hs[i]
            others = [j for j in range(len(rows)) if j not in need]
            pool = sum(hs[j] for j in others)
            if pool > lack:
                for j in others:
                    hs[j] -= lack * hs[j] / pool
                hs[i] = 0.34
    out = []
    near = {"eyes": 0, "face": 0, "hands": 1, "waist": 1, "detail": 1, "knee": 2, "full": 3, "wide": 4}
    for r, h in zip(rows, hs):
        row = {"h": round(h, 2), "cuts": [c["id"] for c in r]}
        if len(r) == 2:
            a, b = near.get(r[0]["shot"], 2), near.get(r[1]["shot"], 2)     # 가까운 샷은 좁게, 먼 샷은 넓게
            row["w"] = [0.5, 0.5] if a == b else ([0.45, 0.55] if a < b else [0.55, 0.45])
        elif len(r) == 3:
            row["w"] = [0.3, 0.4, 0.3] if len(r[1]["_who"]) >= 2 else [0.34, 0.33, 0.33]
        out.append(row)
    d = round(1.0 - sum(r["h"] for r in out), 2)
    out[-1]["h"] = round(out[-1]["h"] + d, 2)
    return out


def _at(kind, n_speech, n_sfx):
    if kind == "narration":
        return "tl"
    if kind == "sfx":
        return ["bl", "br", "tl"][n_sfx % 3]
    return ["tr", "bl", "br", "tl"][n_speech % 4]


def _duo_count(who, chars_info, plan):
    """두 명 컷 인원 태그.
    캐릭터 파일 tags_short 의 성별 태그로: 1girl·female·girl -> 여자, 1boy·male·boy -> 남자, 없으면 셈에서 뺌. chars_info 가 없으면 예전대로"""
    if not chars_info:
        return "duo, 2boys" if plan.get("duo_tag", "2boys") == "2boys" else "duo"
    boys = girls = 0
    for w in who:
        t = [x.strip().lower() for x in str((chars_info.get(w) or {}).get("tags_short", "")).split(",")]
        if any(x in ("1girl", "female", "girl") for x in t):
            girls += 1
        elif any(x in ("1boy", "male", "boy") for x in t):
            boys += 1
    tags = ["duo"] + (["2boys"] if boys == 2 else ["1boy"] * (boys == 1)) + (["2girls"] if girls == 2 else ["1girl"] * (girls == 1))
    return ", ".join(tags)


PEOPLE_TAGS = ("1boy", "2boys", "3boys", "multiple boys", "1girl", "2girls", "3girls", "multiple girls", "1other", "2others", "solo", "duo",
               "trio", "group", "furry", "anthro", "kemono", "furry male", "furry female", "male focus", "female focus")


def _drop_people(text, where, notes):
    parts = [x.strip() for x in str(text or "").split(",") if x.strip()]
    drop = [x for x in parts if x.lower().replace("_", " ") in PEOPLE_TAGS]
    if not drop:
        return text
    notes.append("D12 %s: '%s' -> removed (the program adds count/species tags per character)" % (where, "', '".join(drop)))
    return ", ".join(x for x in parts if x not in drop)


def compile_plan(plan, chars_info=None, kit=None):
    """plan(dict) -> (conti dict, notes[]). chars_info: {key: character yaml dict} (lora 여부 확인용, 없으면 main을 LoRA로 봄)"""
    notes = []
    db, W = None, None
    if kit:
        try:
            import nk_webtoon as W
            db = W._load_tagdb(kit)
        except Exception:
            db = None

    def fix(text, where):
        t2, ch = _fix_tags(db, text, W)
        for a, b in ch:
            notes.append("D7 %s: '%s' is not a tag -> '%s'" % (where, a, b))
        t3, ch2 = _talk_fix(t2)
        for a, b in ch2:
            notes.append("D9 %s: '%s' makes the model draw text/speech bubbles -> %s" % (where, a, ("'%s'" % b) if b else "removed"))
        #   같은 동굴을 'campfire, lamp'로 쓴 t06은 정상 -> 빼고, 빛은 불·등불 같은 광원 태그로
        parts = [x.strip() for x in str(t3 or "").split(",") if x.strip()]
        drop = [x for x in parts if x.lower().replace("_", " ") in ("dark", "darkness")]
        if drop:
            parts = [x for x in parts if x not in drop]
            notes.append("D10 %s: '%s' darkens the whole picture -> removed, use a light source (campfire, lamp)"
                         % (where, "', '".join(drop)))
            t3 = ", ".join(parts)
        #   캐릭터 색까지 사라짐) -> 조용히 뺌
        parts = [x.strip() for x in str(t3 or "").split(",") if x.strip()]
        drop = [x for x in parts if x.lower().replace("_", " ").endswith(" theme") or x.lower().replace("_", " ") in WHOLE_TINT]
        if drop:
            parts = [x for x in parts if x not in drop]
            notes.append("D11 %s: '%s' tints the whole picture one color -> removed" % (where, "', '".join(drop)))
            t3 = ", ".join(parts)
        return t3
    cast = dict(plan.get("cast") or {})
    if not cast:
        raise ValueError("plan needs cast: {short name: character file}")
    main = plan.get("main") or next(iter(cast))
    #   (plan rules_on: [D1] 이면 다시 켬)
    asked = {str(x).upper() for x in (plan.get("rules_off") or [])}
    rules_off = (asked | RULES_OFF_DEFAULT) - {str(x).upper() for x in (plan.get("rules_on") or [])}
    if asked:
        notes.append("rules_off %s (test plan: director rules skipped)" % sorted(asked))
    lora_keys = [k for k, f in cast.items() if (chars_info or {}).get(k, {}).get("lora")] if chars_info else [main]
    locs = dict(plan.get("locations") or {})
    props = {}
    for k, v in (plan.get("props") or {}).items():
        props[k] = v if isinstance(v, dict) else {"tags": str(v)}
    conti = {"title": plan.get("title", "untitled"), "format": "page", "read": plan.get("read", "rtl"),
             "artist": plan.get("artist", ""), "chars": cast, "char": main,
             "page": {"size": plan.get("page_size", "B5")}, "defaults": {"n": int(plan.get("n", 3))},
             "duo": {"modes": "MB", "fix_denoise": 0.7, "denoise": 0.75, "anima_denoise": 0.55, "anima_fix": 0.5}}
    if plan.get("restyle"):
        conti["restyle"] = plan["restyle"]
    if str(plan.get("letter") or "v2").lower() != "v1":
        conti["letter"] = "v2"
    p3 = str(plan.get("pose3d") or "scene3d").lower()
    if p3 == "auto":
        p3 = "scene3d"
    if p3 in ("scene3d", "capsule"):
        conti["pose3d"] = p3
    if plan.get("color_match"):
        conti["color_match"] = True
    for k in ("char_tags", "gaze", "pose3d_arms", "hug_yaw", "pose3d_strength", "region_strength", "char_neg", "duo_strength", "scene3d_parts", "auto_retry", "hand_refine",
              "bubble_color"):
        if plan.get(k) not in (None, ""):
            conti[k] = plan[k]
    for k in ("anima_tags", "anima_neg"):
        v = plan.get(k, ANIMA_DEFAULTS[k])
        if v and str(v).strip().lower() != "none":
            conti[k] = str(v).strip()
    if plan.get("story"):
        conti["story"] = str(plan["story"]).strip()
    if rules_off:
        conti["rules_off"] = sorted(rules_off)      # 시험 편 표시 (자리 잡기 동작 문장 등 시험용 기능이 이것을 봄)
    sr = plan.get("style_ref")
    if sr is None and kit and os.path.exists(os.path.join(kit, "styles", "%s.png" % conti["artist"])):
        sr = "styles/%s.png" % conti["artist"]
    if sr is not None and str(sr).strip().lower() not in ("", "none", "off", "false"):
        conti["style_ref"] = str(sr)
        for k in ("style_ref_weight", "style_ref_type"):
            if plan.get(k) is not None:
                conti[k] = plan[k]
    fl = plan.get("flow")
    if fl is not None and str(fl).strip().lower() not in ("", "none", "off", "false", "default", "nk"):
        conti["flow"] = str(fl).strip()
    world = {"locations": {}, "props": {}, "wear": [], "state": [], "object_cut": dict(OBJECT_CUT), "neg_always": NEG_ALWAYS}
    for k, v in locs.items():
        lt = fix(str(v if not isinstance(v, dict) else v.get("tags", "")), "location %s" % k)
        world["locations"][k] = {"tags": lt, "neg": _loc_neg(lt) if not isinstance(v, dict) else v.get("neg", _loc_neg(lt))}
        if isinstance(v, dict) and v.get("same_as"):
            world["locations"][k]["same_as"] = v["same_as"]
    for k, v in props.items():
        world["props"][k] = {"tags": fix(v["tags"], "prop %s" % k)}

    pages, cid, duo_ids, person_cuts, prop_qa = [], 0, [], 0, {}
    total = sum(len(p.get("cuts") or []) for p in plan.get("pages") or [])
    for pi, pg in enumerate(plan.get("pages") or [], 1):
        cuts = []
        for pc in pg.get("cuts") or []:
            cid += 1
            who = [w for w in (pc.get("who") or []) if w]
            for w in who:
                if w not in cast:
                    raise ValueError("cut %d: who '%s' is not in cast %s" % (cid, w, list(cast)))
            shot = str(pc.get("shot", "knee")).lower()
            angle = str(pc.get("angle", "eye")).lower()
            if shot not in SHOTS:
                notes.append("cut %d: shot '%s' unknown -> knee" % (cid, shot)); shot = "knee"
            if who and shot == "detail":
                notes.append("cut %d: person cut with shot 'detail' -> face" % cid); shot = "face"
            if angle not in ANGLES:
                notes.append("cut %d: angle '%s' unknown -> eye" % (cid, angle)); angle = "eye"
            loc = pc.get("loc") or (next(iter(locs)) if locs else None)
            simple_bg = str(pc.get("bg") or "").lower() == "simple" and bool(who)
            if simple_bg:
                loc = None
            if loc and loc not in locs:
                raise ValueError("cut %d: loc '%s' is not in locations %s" % (cid, loc, list(locs)))
            lines = list(pc.get("lines") or [])
            roles = {k: _drop_people(fix(str(v), "cut %d %s" % (cid, k)), "cut %d %s" % (cid, k), notes) for k, v in dict(pc.get("roles") or {}).items()}
            action = _drop_people(fix(str(pc.get("action", "")), "cut %d" % cid), "cut %d" % cid, notes)
            if simple_bg and "simple background" not in action:
                action = _join(action, "simple background")
            # D1: 닿는 동작이 있는 두 명 컷 -> 혼자 컷
            if len(who) >= 2 and "D1" not in rules_off:
                hit = _touchy(action + " " + " ".join(str(v) for v in roles.values()))
                if hit:
                    keep = pc.get("focus")
                    if keep not in who:
                        cnt = {w: sum(1 for l in lines if l.get("who") == w) for w in who}
                        keep = max(who, key=lambda w: (cnt[w], w == main))
                    notes.append("D1 cut %d: two-person touch action %s -> solo cut of %s (the other speaks off-panel)"
                                 % (cid, hit, keep))
                    action = ", ".join(t for t in _tags(_join(action, roles.get(keep, ""))) if not _touchy(t))
                    who = [keep]
                    roles = {}
            if len(who) >= 2 and shot == "face" and "D2" not in rules_off:
                notes.append("D2 cut %d: two-person %s shot -> knee (close two-person panels bleed features)" % (cid, shot))
                shot = "knee"
            c = {"id": cid}
            if not who:
                c["char"] = "none"
                c["scene"] = action
                lt = (action + " " + str((locs.get(loc) if not isinstance(locs.get(loc), dict) else locs[loc].get("tags", "")) or "")).lower()
                if not any(k in lt for k in ("sunlight", "light", "lamp", "fire", "window", "daylight", "moonlight",
                                             "rain", "overcast", "fog", "storm", "cloudy sky", "night")):
                    add = "moonlight" if "night" in lt else "sunlight"
                    c["scene"] = _join(action, add)
                    notes.append("D6 cut %d: object/scenery cut had no light tag -> added %s" % (cid, add))
            elif len(who) == 1:
                if who[0] != main:
                    c["char"] = who[0]
                c["scene"] = _join("solo", action)
                person_cuts += 1
            else:
                person_cuts += 1
                duo_ids.append(cid)
                c["scene"] = _join(_duo_count(who, chars_info, plan), action)
            c["shot"] = shot
            if who:
                c["angle"] = angle
            if loc:
                c["loc"] = loc
            if pc.get("props"):
                c["props"] = list(pc["props"])
                for p in c["props"]:
                    if p not in props:
                        raise ValueError("cut %d: prop '%s' is not in props %s" % (cid, p, list(props)))
                    if props[p].get("qa"):
                        tg = _prop_qa_tag(world["props"][p]["tags"])
                        c.setdefault("qa", []).append({"tag": tg, "min": 0.35, "must": True})
            if len(who) >= 2:
                c["modes"] = "MB"
                c["n"] = 4
                # D4: 먼저 말하는 사람이 오른쪽
                first = next((l.get("who") for l in lines if l.get("who") in who), who[0])
                order = [first] + [w for w in who if w != first]
                c["cast"] = [{"char": w, "side": s, "pos": _join(roles.get(w, ""))} for w, s in zip(order, ("right", "left"))]
            if pc.get("fx"):
                c["fx"] = pc["fx"]
            if pc.get("pop"):
                c["pop"] = True
            if pc.get("neg"):
                c["neg"] = pc["neg"]
            if pc.get("qa"):
                c.setdefault("qa", []).extend(pc["qa"])
            sc = pc.get("scene") or pc.get("sentence")
            if sc:
                c["anima_act"] = " ".join(str(sc).split())
            if pc.get("show"):
                c["show"] = pc["show"] if isinstance(pc["show"], list) else [x.strip() for x in str(pc["show"]).split("|") if x.strip()]
            text, ns, nx = [], 0, 0
            for l in lines:
                kind = str(l.get("kind", "speech"))
                kinds = ("speech", "narration", "sfx", "thought", "shout", "whisper", "tremble", "aside")
                t = {"type": kind if kind in kinds else "speech", "text": str(l.get("text", ""))}
                if l.get("who") and t["type"] in ("speech", "thought", "shout", "whisper", "tremble", "aside"):
                    t["who"] = l["who"]
                for k2 in ("style", "vertical", "angle"):
                    if l.get(k2) is not None and t["type"] == "sfx":
                        t[k2] = l[k2]
                t["at"] = l.get("at") or _at(t["type"], ns, nx)
                if l.get("web_at"):
                    t["web_at"] = str(l["web_at"])            # 웹툰판(nk_webview)에서만 쓰는 자리 tl/tr/bl/br. 쪽 조립은 안 봄
                if t["type"] == "sfx":
                    nx += 1
                    if l.get("size"):
                        t["size"] = int(l["size"]) if str(l["size"]).isdigit() else str(l["size"])     # 숫자 = 글자 크기 / s·m·l·xl = v2 칸 비율
                elif t["type"] != "narration":
                    ns += 1
                text.append(t)
            if text:
                c["text"] = text
            c["_who"], c["_big"] = who, bool(pc.get("big"))
            cuts.append(c)
        rows = _rows(cuts)
        #   -> 짝 줄이 0.22보다 낮아지면 그 페이지의 big을 빼고 다시 나눔
        if any(c["_big"] for c in cuts) and any(len(r["cuts"]) >= 2 and r["h"] < 0.22 for r in rows):
            for c in cuts:
                c["_big"] = False
            rows = _rows(cuts)
            notes.append("D8 page %d: too many cuts for a big panel (rows got too flat) -> big removed on this page" % pi)
        tree = None
        if str(plan.get("layout") or "v2").lower() != "v1":
            try:
                import nk, nk_webtoon as _W, nk_layout2 as L2
                st = _W._page_style(nk.load_presets())
                tree, _ = L2.best_tree(cuts, L2.page_box(st), st["gutter"])
            except Exception as e:
                notes.append("layout v2 page %d failed -> v1 rows: %s" % (pi, e))
        for c in cuts:
            c.pop("_who", None); c.pop("_big", None)
        pages.append({"page": pi, "note": pg.get("note", ""), "rows": rows, "cuts": cuts})
        if tree:
            pages[-1]["tree"] = tree
    # D3
    if "D3" not in rules_off and person_cuts and len(duo_ids) / float(person_cuts) > 0.35:
        notes.append("D3 two-person cuts %d of %d character cuts (%.0f%%) > 35%% - expect redraws"
                     % (len(duo_ids), person_cuts, 100.0 * len(duo_ids) / person_cuts))
    # wear / state (계획에 있는 것) + LoRA 캐릭터 두 명 컷 부정 태그
    for key in ("wear", "state"):
        for w in plan.get(key) or []:
            w = dict(w)
            if str(w.get("cuts", "")).strip().lower() == "all":
                w["cuts"] = "1-%d" % cid
            world[key].append(w)
    for k in lora_keys:
        if duo_ids:
            world["state"].append({"who": k, "neg": DUO_LORA_NEG, "cuts": _ranges(duo_ids)})
    conti["world"] = world
    conti["pages"] = pages
    return conti, notes


def _dump(conti, notes, plan_path):
    import yaml
    head = ["# ============================================================",
            "#  %s — plan.yaml에서 자동 생성 (nk ep compile, %s)" % (conti.get("title"), __import__("time").strftime("%Y-%m-%d %H:%M")),
            "#  손으로 고치지 말고 plan.yaml을 고친 뒤 다시 compile (손으로 고친 건 다음 compile 때 사라짐)",
            "#  감독 규칙이 바꾼 것:"] + ["#   - " + n for n in notes] + (["#   (없음)"] if not notes else []) + \
           ["# ============================================================"]
    body = yaml.safe_dump(conti, allow_unicode=True, sort_keys=False, width=160, default_flow_style=None)
    return "\n".join(head) + "\n" + body


def run_compile(nk, kit, args):
    import yaml
    import nk_webtoon as W
    d = W.ep_dir(kit, args.ep)
    pp = os.path.join(d, getattr(args, "plan", None) or "plan.yaml")
    if not os.path.exists(pp):
        print("[ERROR] no plan:", pp); sys.exit(1)
    raw = open(pp, encoding="utf-8-sig").read()
    try:
        plan, _ = _extract_yaml(raw)
    except Exception as e:
        print("[ERROR] %s is not valid YAML (웹 AI 답을 그대로 붙여 넣었는지, 들여쓰기가 깨지지 않았는지 확인):\n  %s" % (pp, e))
        sys.exit(1)
    if not isinstance(plan, dict) or not plan.get("pages"):
        print("[ERROR] %s has no 'pages:' - 웹 AI 답의 YAML 부분을 저장했는지 확인" % pp); sys.exit(1)
    rq = os.path.join(d, "request.yaml")
    req = {}
    if os.path.exists(rq):                       # 글쓴이가 빠뜨린 값은 요청서에서 (작가·그림체·캐릭터·제목)
        req = yaml.safe_load(open(rq, encoding="utf-8")) or {}
        for k in ("title", "artist", "restyle", "cast", "main", "style_ref", "style_ref_weight", "style_ref_type", "flow"):
            if req.get(k) and not plan.get(k):
                plan[k] = req[k]
        if str(plan.get("restyle", "")).lower() in ("none", "off"):
            plan.pop("restyle", None)
    info = {}
    for k, f in (plan.get("cast") or {}).items():
        cp = os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "%s.yaml" % f)
        if os.path.exists(cp):
            info[k] = yaml.safe_load(open(cp, encoding="utf-8")) or {}
        else:
            print("[ERROR] character file not found: %s" % cp); sys.exit(1)
    try:
        conti, notes = compile_plan(plan, info, kit)
    except ValueError as e:
        print("[ERROR] plan:", e); sys.exit(1)
    out = os.path.join(d, "conti.yaml")
    if os.path.exists(out) and not getattr(args, "dry", False):
        old = open(out, encoding="utf-8").read()
        if "plan.yaml에서 자동 생성" not in old:
            bak = out + ".hand.bak"
            open(bak, "w", encoding="utf-8").write(old)
            print("[note] conti.yaml was written by hand -> kept a copy:", bak)
    text = _dump(conti, notes, pp)
    if getattr(args, "dry", False):
        print(text)
    else:
        open(out, "w", encoding="utf-8").write(text)
        print("conti ->", out)
    n_cuts = sum(len(p["cuts"]) for p in conti["pages"])
    print("%d pages, %d cuts, director notes %d" % (len(conti["pages"]), n_cuts, len(notes)))
    for n in notes:
        print("  -", n)
    # 글쓴이에게 돌려줄 고칠 점 (웹 AI는 사람이 붙여 넣어 되돌림: fix_prompt.md). 태그 이름은 위 D7이 이미 고침
    probs = [x for x in plan_problems(kit, plan, req) if "태그가 아닌 말" not in x]
    fp = os.path.join(d, "fix_prompt.md")
    if probs:
        print("\n[plan] 큰 문제 %d개 (이대로면 만화가 통째로 틀어짐):" % len(probs))
        for x in probs:
            print("  -", x)
        if not getattr(args, "dry", False):
            open(fp, "w", encoding="utf-8").write(
                "그림이 잘 나오려면 고칠 점:\n- " + "\n- ".join(probs)
                + "\n이야기는 그대로 두고, 고친 YAML 전체를 같은 형식으로 다시 출력하라.\n")
            print("  -> %s : 웹 AI에 이 글을 붙여 넣으면 고친 계획을 다시 줌 (그대로 써도 만화는 만들어짐)" % fp)
    elif os.path.exists(fp) and not getattr(args, "dry", False):
        os.remove(fp)
    pn = plan_notes(kit, plan, req)
    if pn:
        print("\n[참고] 만화는 그대로 만듦 — 확인만 해 줘:")
        for x in pn:
            print("  -", x)
    print_tag_warnings(kit, plan, info)
    if not getattr(args, "dry", False):
        W.check(nk, kit, argparse_ns(ep=args.ep))


def argparse_ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


# ================================================================ 계획 쓰기 (이야기 -> plan.yaml)
# 백엔드: prompt = 프롬프트 파일만 만듦 (웹 AI 채팅에 붙여 넣고, 답을 episodes/<ep>/plan.yaml로 저장)
#         ollama = 이 PC의 로컬 모델이 씀 (무료. 모델은 --model, 기본은 presets qa.model)
ALIAS = {}   # 캐릭터 파일 이름 -> 짧은 이름 (비면 파일 이름 그대로)


def _request(W, kit, ep):
    import yaml
    rp = os.path.join(W.ep_dir(kit, ep), "request.yaml")
    if not os.path.exists(rp):
        print("[ERROR] no request: %s\n  example:\n    characters: [mychar, buddy]\n    pages: 2\n    story: \"...\"\n"
              "    elements: \"대사 많이, 효과음 3개 이상\"\n    restyle: picturebook" % rp)
        sys.exit(1)
    return yaml.safe_load(open(rp, encoding="utf-8")) or {}


def build_prompt(kit, req):
    import yaml
    tpl = open(os.path.join(kit, "docs", "prompt_plan.md"), encoding="utf-8").read()
    cast = dict(req.get("cast") or {})
    if not cast:
        for f in req.get("characters") or []:
            cast[ALIAS.get(str(f), str(f))] = str(f)
    lines = []
    for short, f in cast.items():
        cp = os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "%s.yaml" % f)
        info = yaml.safe_load(open(cp, encoding="utf-8")) if os.path.exists(cp) else {}
        look = str((info or {}).get("anima") or "").strip()
        lines.append("- %s (파일 %s): %s%s" % (short, f, look or "(외형 설명 없음)",
                                            "" if not req.get("personality", {}).get(short) else
                                            " / 성격: " + str(req["personality"][short])))
    rq = dict(req)
    rq["cast"] = cast
    tpl = tpl.replace("(프로그램이 채움: 짧은 이름 / 파일 / 외형 요약. 외형 태그는 프로그램이 자동으로 붙이므로 action에 외형을 쓰지 않는다)",
                      "\n".join(lines) + "\n(외형 태그는 프로그램이 자동으로 붙이므로 action에 외형을 쓰지 않는다)")
    tpl = tpl.replace("# 요청\n(프로그램이 채움)", "# 요청\n" + yaml.safe_dump(rq, allow_unicode=True, sort_keys=False).strip())
    return tpl, cast


def _extract_yaml(raw):
    import yaml
    m = re.search(r"```(?:yaml|yml)?\s*\n(.*?)(?:```|\Z)", raw, re.S)
    body = m.group(1) if m else raw
    return yaml.safe_load(body), body


def _ollama_chat(url, model, messages, num_ctx, temperature, cpu=False):
    import urllib.request, urllib.error
    body = {"model": model, "stream": False, "messages": messages, "keep_alive": "2m",
            "options": {"temperature": float(temperature), "num_ctx": int(num_ctx)}}
    if cpu:
        body["options"]["num_gpu"] = 0
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=3600).read().decode("utf-8"))
    msg = r.get("message", {})
    return (msg.get("content") or msg.get("thinking") or ""), r



#   목록이 ARTIST_NOTE 와 같은지는 tests/unit/test_checker_big_only.py 가 봄
ARTISTS_LISTED = ()   # 태그 사전 확인 없이 받아 주는 작가 이름 (presets.yaml 의 main_artists·presets 도 받아 줌)


def _artist_problem(plan):
    """작가 이름을 모름 (목록에도, 프리셋에도, 태그 사전의 작가 태그에도 없음 = 오타 같은 낯선 이름) -> 만화 전체의 그림체가 통째로 빠짐 = 큰 문제"""
    art = str(plan.get("artist") or "").strip()
    if not art or art.lower().replace("_", " ") in ARTISTS_LISTED:
        return None
    try:
        import nk
        cfg = nk.load_presets()
        if art not in (cfg.get("presets") or {}) and art not in (cfg.get("main_artists") or []) \
                and nk.artist_tag_posts(art) < nk.ARTIST_MIN_POSTS:
            return ("작가 '%s'를 모름 (프리셋에도, 태그 사전의 작가 태그(%d개 이상)에도 없음) -> 작가 목록에서 고르거나 Danbooru 작가 태그 이름으로"
                    % (art, nk.ARTIST_MIN_POSTS))
    except Exception:
        pass
    return None


def plan_problems(kit, plan, req=None):
    """글쓴이(AI)에게 돌려줄 고칠 점 = **만화가 통째로 틀어지는 큰 문제만** (한국어).
멀쩡한 콘티도 자꾸 돌려보내고
    빡빡한 규칙 때문에 연출·자세가 경직됨. 그래서 연출·형식 검사(혼자 컷 수, 장소 첫 컷 wide, 같은 자세 반복, 소품 detail 컷, show:,
    두 명 컷 roles, 혼자 컷의 닿는 동작, 태그 아닌 말, 쪽수, 말하는 사람 이름)는 뺐다.
    형식이 깨진 것(YAML·cast 에 없는 사람·없는 장소)은 컴파일러가 [ERROR] 로 멈춘다 = 정말 못 만드는 경우.
    그림을 망치는 태그(단색 '~ theme'·dark·말풍선 태그)는 컴파일러가 조용히 뺀다 (D9·D10·D11) — 돌려보내지 않음."""
    p = _artist_problem(plan)
    return [p] if p else []


def plan_notes(kit, plan, req=None):
    """참고만 (돌려보내지 않고 만화는 그대로 만듦): 사용자가 요청한 '꼭 넣을 태그·장면'이 빠졌나, 쪽수가 요청과 다른가"""
    notes = []
    norm = lambda t: re.sub(r"\s+", " ", str(t).strip().lower().replace("_", " "))
    pages = plan.get("pages") or []
    want = (req or {}).get("pages") or plan.get("pages_wanted")
    try:
        if want and len(pages) != int(want):
            notes.append("요청은 %s쪽인데 %d쪽으로 씀" % (want, len(pages)))
    except (TypeError, ValueError):
        pass
    have = set()
    for tbl in (plan.get("locations") or {}, plan.get("props") or {}):
        for v in tbl.values():
            have |= {norm(t) for t in _tags(v.get("tags", "") if isinstance(v, dict) else v)}
    for key in ("wear", "state"):
        for w in plan.get(key) or []:
            have |= {norm(t) for t in _tags((w or {}).get("tags", ""))}
    marks = []
    for pg in pages:
        for pc in pg.get("cuts") or []:
            have |= {norm(t) for t in _tags(pc.get("action", ""))}
            for v in (pc.get("roles") or {}).values():
                have |= {norm(t) for t in _tags(v)}
            for k in ("sentence", "must"):
                if pc.get(k):
                    marks.append(norm(pc[k]))
    for t in plan.get("must_tags") or []:
        if norm(t) not in have and not any(norm(t) in m for m in marks):
            notes.append("꼭 넣을 태그 '%s'가 어느 컷에도 없음" % t)
    for s in plan.get("must_scenes") or []:
        if not any(norm(s) == m or norm(s) in m or m in norm(s) for m in marks):
            notes.append("꼭 넣을 장면 '%s'을 그리는 컷 표시(must:)가 없음" % s)
    return notes


# 경고만: 계획표·콘티·캐릭터 파일을 읽고 목록을 돌려줌. 그림·콘티·기본값은 안 바꾸고, 웹 AI에게 돌려주는 fix_prompt.md에도
TAG_SPECIES = ("mammal", "anthro", "furry", "feral")     # 부정에 넣지 않음 - 퍼리 캐릭터가 사람·다른 모습으로 샘
# 퍼리 캐릭터면 누구나 가진 몸 부위. 두 명 컷에서 duo_exclusive(상대 영역 부정)에 들어가면 상대(퍼리)의 귀·꼬리까지 지우라는 말이 됨
TAG_SHARED_BODY = ("animal ears", "ears", "tail", "fur", "furry", "anthro")
TAG_FURRY_WORDS = ("anthro", "furry", "fur", "felid", "canid", "caprine", "animal ears", "tail")
# 색 비교는 색 이름만 (dark·light는 밝기 말이라 뺌)
TAG_HUES = ("red", "pink", "blue", "navy", "white", "black", "grey", "gray", "brown", "yellow", "green", "orange", "purple",
            "gold", "silver", "beige", "cream", "cyan")
TAG_SIZE = ("long", "short", "big", "large", "huge", "giant", "thick", "thin", "small", "tiny")


def _tnorm(t):
    t = str(t or "").strip()
    m = re.match(r"^\((.+):\s*[\d.]+\)$", t)
    if m:
        t = m.group(1)
    t = t.replace("\\(", "(").replace("\\)", ")").replace("_", " ")
    return re.sub(r"\s+", " ", t).strip().lower()


def _ttags(s):
    return [_tnorm(t) for t in _tags(str(s or "").replace("\n", " ")) if _tnorm(t)]


def _hues(t):
    return {("grey" if w == "gray" else w) for w in _tnorm(t).split() if w in TAG_HUES}


def _inside(small, big):
    """'tail' 이 'long tail' 안에 낱말 단위로 있나 (같아도 참)"""
    return re.search(r"(?<![a-z])" + re.escape(small) + r"(?![a-z])", big) is not None


def _char_pos(ch):
    return _ttags(ch.get("tags_short")) + [t for t in _ttags(ch.get("tags_full")) if t not in _ttags(ch.get("tags_short"))]


def _char_block_tags(ch):
    """캐릭터 파일이 막는 태그: negative_extra + avoid_tags + forbid(판별기 이름, 밑줄 -> 띄어쓰기)"""
    return {"negative_extra": _ttags(ch.get("negative_extra")), "avoid_tags": _ttags(ch.get("avoid_tags")),
            "forbid": _ttags(ch.get("forbid"))}


def _is_furry(ch):
    pos = " , ".join(_char_pos(ch))
    return bool(ch.get("lora")) or any(_inside(w, pos) for w in TAG_FURRY_WORDS)


def char_tag_warnings(key, ch, db=None):
    """캐릭터 파일 하나의 태그 경고. db = nk_webtoon._load_tagdb 결과(없으면 사전 검사 생략)"""
    import nk_webtoon as W
    out = []
    trig = _tnorm(ch.get("trigger"))
    fields = ("tags_short", "tags_full", "negative_extra", "duo_exclusive")
    for f in fields:
        for raw in _tags(str(ch.get(f) or "").replace("\n", " ")):
            t = _tnorm(raw)
            # [T2] 괄호·가중치: ComfyUI에선 ( ) 가 강조 문법 (conti_rules 2: 색 강조가 털·배경까지 물들임)
            if re.match(r"^\(.+:\s*[\d.]+\)$", raw.strip()) or re.search(r"(?<!\\)[()]", raw):
                out.append("[T2] %s %s: '%s' 괄호·가중치 = ComfyUI 강조 문법 (conti_rules 2 '강조 괄호 금지') -> 괄호를 빼거나 \\( \\) 로"
                           % (key, f, raw.strip()))
            if db and t != trig and W._tag_verdict(db, t)[0] == "NOT A TAG":
                out.append("[T1] %s %s: '%s' 태그 사전에 없음 -> 사전에 있는 태그로 바꾸거나 빼기 (nk ep tags)" % (key, f, raw.strip()))
    pos = _char_pos(ch)
    neg = _ttags(ch.get("negative_extra"))
    # [T3] 같은 캐릭터 긍정과 부정이 부딪침 (부정 태그가 긍정 태그 안에 낱말로 들어 있음)
    for n in neg:
        hit = [p for p in pos if _inside(n, p)]
        if hit:
            out.append("[T3] %s: 부정 '%s'가 긍정 %s 와 부딪침 -> 한쪽을 빼기" % (key, n, ", ".join("'%s'" % h for h in hit)))
    # [T4] 부정·duo_exclusive에 종 단어 (duo_exclusive는 두 명 컷에서 상대 영역 부정으로 들어감)
    for f in ("negative_extra", "duo_exclusive"):
        bad = [t for t in _ttags(ch.get(f)) if t in TAG_SPECIES]
        if bad:
            out.append("[T4] %s %s: 종 단어 %s -> 부정에 넣지 않는 규칙. %s"
                       % (key, f, ", ".join("'%s'" % b for b in bad),
                          "두 명 컷에서 상대 영역 부정으로 들어감 - 상대가 퍼리면 그 모습을 지우라는 말"
                          if f == "duo_exclusive" else "퍼리 모습이 약해질 수 있음"))
    # [T5] 부정의 색 단어가 이 캐릭터 긍정 색과 같음 (conti_rules 2: 부정 'red couch' -> 빨간 털실까지 흐려질 수 있음) - 확인 필요
    pos_h = set().union(*[_hues(p) for p in pos]) if pos else set()
    for n in neg:
        same = _hues(n) & pos_h
        if same:
            out.append("[T5] %s negative_extra: '%s'의 색 %s 이 긍정 태그에도 있음 -> 그 색 무늬가 약해질 수 있음 (추정, 같은 시드로 빼기 시험)"
                       % (key, n, "/".join(sorted(same))))
    # [T6] 캐릭터 파일이 스스로 막은 태그(avoid_tags)를 긍정에 씀
    for a in _ttags(ch.get("avoid_tags")):
        hit = [p for p in pos if p == a]
        if hit:
            out.append("[T6] %s: avoid_tags '%s'가 tags_short/tags_full에 있음 -> 빼기" % (key, a))
    return out


def char_tag_notes(key, ch):
    """[참고] 크기·길이 태그 목록 (경고 아님): 시트·원작과 대조했는지 사람이 봄"""
    sz = [t for t in _char_pos(ch) if any(w in TAG_SIZE for w in t.split())]
    return ["[참고] %s 크기·길이 태그: %s -> 시트(원작) 그림과 길이·굵기를 대조" % (key, ", ".join(sz))] if sz else []


def _cut_records(doc, info):
    """계획표(plan) 또는 콘티(conti)를 같은 모양의 컷 목록으로:
    {id, who: [키], per: {키: [태그]}, common: [태그], props: [이름], negs: [(어디, [태그], [영향받는 키])]}"""
    recs = []
    world = doc.get("world") or {}
    cuts = [c for p in doc.get("pages") or [] for c in p.get("cuts") or []] or list(doc.get("cuts") or [])
    is_conti = "world" in doc or "chars" in doc or any(("scene" in c or "cast" in c) for c in cuts)
    dflt = str(doc.get("char") or doc.get("main") or "")
    for i, c in enumerate(cuts, 1):
        cid = int(c.get("id", i))
        r = {"id": cid, "who": [], "per": {}, "common": [], "props": list(c.get("props") or []), "negs": []}
        if is_conti:
            if c.get("cast"):
                r["who"] = [str(x.get("char")) for x in c["cast"]]
                r["common"] = _ttags(c.get("scene"))
                for x in c["cast"]:
                    r["per"][str(x.get("char"))] = _ttags(x.get("pos"))
                    if x.get("neg"):
                        r["negs"].append(("cut %d cast %s neg" % (cid, x.get("char")), _ttags(x.get("neg")), [str(x.get("char"))]))
            elif str(c.get("char", dflt)).lower() != "none":
                k = str(c.get("char") or dflt)
                r["who"] = [k]
                r["per"][k] = [t for t in _ttags(c.get("scene")) if t != "solo"]
            else:
                r["common"] = _ttags(c.get("scene"))
            loc = (world.get("locations") or {}).get(c.get("loc"))
            if isinstance(loc, dict) and loc.get("neg") and r["who"]:
                r["negs"].append(("location %s neg" % c.get("loc"), _ttags(loc["neg"]), list(r["who"])))
        else:
            r["who"] = [str(w) for w in (c.get("who") or []) if w]
            if len(r["who"]) >= 2:
                r["common"] = _ttags(c.get("action"))
                for k in r["who"]:
                    r["per"][k] = _ttags((c.get("roles") or {}).get(k))
            elif r["who"]:
                r["per"][r["who"][0]] = _ttags(c.get("action"))
            else:
                r["common"] = _ttags(c.get("action"))
        if c.get("neg"):
            r["negs"].append(("cut %d neg" % cid, _ttags(c.get("neg")), list(r["who"])))
        for key in ("wear", "state"):
            src = world.get(key) if is_conti else doc.get(key)
            for j, e in enumerate(src or []):
                e = e or {}
                rng = str(e.get("cuts", "")).strip().lower()
                if rng != "all":
                    try:
                        import nk_webtoon as W
                        if cid not in W._parse_range(rng):
                            continue
                    except Exception:
                        continue
                ws = [str(e["who"])] if e.get("who") else list(r["who"])
                ws = [w for w in ws if w in r["who"]]
                if not ws:
                    continue
                for w in ws:
                    r["per"].setdefault(w, [])
                    r["per"][w] = r["per"][w] + [t for t in _ttags(e.get("tags")) if t not in r["per"][w]]
                if e.get("neg"):
                    r["negs"].append(("%s %d neg (who %s)" % (key, j + 1, e.get("who", "all")), _ttags(e.get("neg")), ws))
        recs.append(r)
    return recs


def tag_warnings(doc, info):
    """계획표·콘티의 태그 경고. info = {짧은 이름: 캐릭터 yaml dict}. 경고 문자열 목록 ([P코드] 로 시작)"""
    out = []
    pairs = {}                                   # (나, 상대) -> 두 명 컷 번호들
    p2 = {}                                      # 같은 부정 줄(world 옷·장소)이 컷마다 되풀이 -> (줄, 문구) 하나로 묶고 컷 번호만 모음
    for r in _cut_records(doc, info):
        cid = r["id"]
        for k, tags in r["per"].items():
            if "holding" not in tags:
                continue
            if len(r["who"]) >= 2:
                out.append("[P1] 컷 %d: 두 명 컷 %s의 'holding' = 무엇을 드는지 없음 (소품 태그는 두 사람 공통 글에 붙음) "
                           "-> 그 사람 태그를 'holding cookie'처럼 물건 이름이 붙은 태그로, 아니면 빼기" % (cid, k))
            elif not r["props"]:
                out.append("[P1] 컷 %d: %s 'holding'인데 소품(props)이 없음 = 빈손으로 쥐는 모양 -> 든 물건을 props에, 아니면 빼기" % (cid, k))
        if "holding" in r["common"] and len(r["who"]) >= 2:
            out.append("[P1] 컷 %d: 두 명 컷 공통 action의 'holding' = 누가 무엇을 드는지 없음 -> roles에 'holding 물건'으로" % cid)
        # [P2] 계획·콘티에 쓴 부정: 종 단어 / 그 컷 사람의 긍정 색과 같은 색 단어
        for where, negs, keys in r["negs"]:
            sp = [t for t in negs if t in TAG_SPECIES]
            if sp:
                p2.setdefault((where, "종 단어 %s -> 부정에 넣지 않는 규칙" % ", ".join("'%s'" % t for t in sp)), []).append(cid)
            for k in keys:
                ch = info.get(k) or {}
                ph = set().union(*[_hues(p) for p in _char_pos(ch) + r["per"].get(k, [])]) if ch else set()
                for t in negs:
                    same = _hues(t) & ph
                    if same and not t.endswith("background"):
                        p2.setdefault((where, "'%s'의 색 %s 이 %s 긍정에도 있음 -> 그 색이 약해질 수 있음 (추정, 같은 시드로 빼기 시험)"
                                       % (t, "/".join(sorted(same)), k)), []).append(cid)
        # [P3] 캐릭터 파일이 막는 태그를 그 캐릭터에게 씀 (긍정·부정이 서로 지움)
        for k, tags in r["per"].items():
            blk = _char_block_tags(info.get(k) or {})
            for f, lst in blk.items():
                hit = [t for t in tags if t in lst]
                if hit:
                    out.append("[P3] 컷 %d: %s에게 쓴 %s 가 캐릭터 파일 %s에 있음 -> 긍정과 부정이 서로 지움, 한쪽을 바꾸기"
                               % (cid, k, ", ".join("'%s'" % h for h in hit), f))
        if len(r["who"]) >= 2:
            for a in r["who"]:
                for b in r["who"]:
                    if a != b:
                        pairs.setdefault((a, b), []).append(cid)
    for (where, msg), cids in p2.items():
        out.append("[P2] %s%s: %s" % (where, "" if where.startswith("cut ") else " (컷 %s)" % _ranges(cids), msg))
    # [P4] 두 명 컷: 상대 duo_exclusive(= 내 영역 부정)가 내 모습을 지움 - 내 긍정 태그 안의 낱말·(내가 퍼리면) 종 단어·공통 몸 부위·내 색
    for (a, b), cids in sorted(pairs.items()):
        ca, cb = info.get(a) or {}, info.get(b) or {}
        mine = _char_pos(ca)
        mine_h = set().union(*[_hues(p) for p in mine]) if mine else set()
        bad = []
        for t in _ttags(cb.get("duo_exclusive")):
            why = None
            if any(_inside(t, p) for p in mine):
                why = "긍정 '%s' 안에 있음" % next(p for p in mine if _inside(t, p))
            elif t in TAG_SPECIES and _is_furry(ca):
                why = "종 단어"
            elif t in TAG_SHARED_BODY and _is_furry(ca):
                why = "퍼리 공통 몸 부위"
            elif _hues(t) & mine_h:
                why = "같은 색 %s" % "/".join(sorted(_hues(t) & mine_h))
            if why:
                bad.append("'%s'(%s)" % (t, why))
        if bad:
            out.append("[P4] 컷 %s: %s duo_exclusive 가 %s 영역 부정에 들어감 -> %s. %s 파일 duo_exclusive에서 빼는 것 검토 (그 캐릭터만 가진 것만 남기기)"
                       % (_ranges(cids), b, a, ", ".join(bad), b))
    return out


def load_cast_info(kit, doc):
    """계획표 cast / 콘티 chars -> {짧은 이름: 캐릭터 yaml dict} (없는 파일은 빈 dict)"""
    import yaml
    cast = dict(doc.get("cast") or doc.get("chars") or {})
    if not cast and doc.get("char") and str(doc["char"]).lower() != "none":
        cast = {str(doc["char"]): str(doc["char"])}
    info = {}
    for k, f in cast.items():
        p = os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "%s.yaml" % f)
        info[str(k)] = (yaml.safe_load(open(p, encoding="utf-8")) or {}) if os.path.exists(p) else {}
    return info


def print_tag_warnings(kit, plan, info):
    """nk ep compile 끝에 계획표 태그 경고(P)를 보여 주기만 함 (fix_prompt.md·웹 AI 되돌리기에는 안 넣음). 실패해도 컴파일은 계속.
    캐릭터 파일 경고(T)는 컴파일마다 되풀이되지 않게 개수만 알림"""
    try:
        import nk_webtoon as W
        db = W._load_tagdb(kit)
        ws = tag_warnings(plan, info)
        nt = sum(len(char_tag_warnings(k, ch, db)) for k, ch in info.items())
        if ws:
            print("\n[tag] 태그 경고 %d개 (제안만 - 그림·콘티는 그대로. 설명: docs/conti_rules.md 2절):" % len(ws))
            for x in ws:
                print("  -", x)
        if nt:
            print("[tag] 이 편 캐릭터 파일 태그 경고 %d개 -> 캐릭터 파일의 태그를 Danbooru/e621 태그로 고치기 (docs/ADDING.md)" % nt)
        return ws
    except Exception as e:
        print("[tag] 태그 경고 건너뜀 (%s: %s)" % (type(e).__name__, e))
        return []


def run_write(nk, kit, args):
    import yaml, time
    import nk_webtoon as W
    d = W.ep_dir(kit, args.ep)
    req = _request(W, kit, args.ep)
    prompt, cast = build_prompt(kit, req)
    pp = os.path.join(d, "write_prompt.md")
    open(pp, "w", encoding="utf-8").write(prompt)
    print("prompt -> %s (%d chars)" % (pp, len(prompt)))
    if args.backend == "prompt":
        print("copy this prompt into the web AI, save its YAML answer as %s, then: nk ep compile %s"
              % (os.path.join(d, "plan.yaml"), args.ep))
        return
    cfg = nk.load_presets()
    q = cfg.get("qa", {})
    model = args.model or q.get("model", "gemma4:e4b-it-qat")
    url = q.get("ollama", "http://127.0.0.1:11434")
    info = {}
    for k, f in cast.items():
        cp = os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "%s.yaml" % f)
        info[k] = yaml.safe_load(open(cp, encoding="utf-8")) if os.path.exists(cp) else {}
    try:
        import nk as _nk
        _nk.Comfy(cfg.get("server", "auto")).free()          # 로컬 모델이 GPU를 쓸 수 있게
    except Exception:
        pass
    msgs = [{"role": "user", "content": prompt}]
    log = {"model": model, "tries": []}
    best = None                       # (문제 수, plan) — 고칠수록 나빠지면 가장 나은 것을 씀
    for t in range(1 + int(args.fix)):
        t0 = time.time()
        raw, r = _ollama_chat(url, model, msgs, args.ctx, args.temperature, cpu=args.cpu)
        secs = round(time.time() - t0)
        tok = r.get("eval_count")
        open(os.path.join(d, "write_raw_%d.md" % (t + 1)), "w", encoding="utf-8").write(raw)
        err, plan, probs = None, None, []
        try:
            plan, body = _extract_yaml(raw)
            if not isinstance(plan, dict):
                raise ValueError("the answer is not a YAML mapping")
            plan.setdefault("cast", cast)
            compile_plan(plan, info)
            probs = plan_problems(kit, plan, req)
        except Exception as e:
            err, plan = "%s: %s" % (type(e).__name__, e), None
        log["tries"].append({"secs": secs, "tokens": tok, "error": err, "problems": probs})
        print("try %d: %ss, %s tokens -> %s" % (t + 1, secs, tok, err or ("ok, %d things to improve" % len(probs))))
        for pr in probs:
            print("   -", pr)
        if plan is not None and (best is None or len(probs) < best[0]):
            best = (len(probs), plan)
        if plan is not None and not probs:
            break
        fb = ("이 YAML에 문제가 있다: %s" % err) if err else ("그림이 잘 나오려면 고칠 점:\n- " + "\n- ".join(probs))
        msgs += [{"role": "assistant", "content": raw},
                 {"role": "user", "content": fb + "\n이야기는 그대로 두고, 고친 YAML 전체를 같은 형식으로 다시 출력하라."}]
    plan = best[1] if best else None
    if best:
        log["chosen_problems"] = best[0]
    json.dump(log, open(os.path.join(d, "write_log.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        nk.ollama_unload(dict(q, model=model))
    except Exception:
        pass
    if plan is None:
        print("[ERROR] no valid plan from %s. raw answers: %s/write_raw_*.md" % (model, d)); sys.exit(1)
    out = os.path.join(d, getattr(args, "out", None) or "plan.yaml")
    open(out, "w", encoding="utf-8").write("# written by %s via nk ep write (%s)\n" % (model, time.strftime("%Y-%m-%d %H:%M"))
                                          + yaml.safe_dump(plan, allow_unicode=True, sort_keys=False, width=160))
    print("plan ->", out)
    if not args.nocompile:
        run_compile(nk, kit, argparse_ns(ep=args.ep, dry=False, plan=os.path.basename(out)))


# ================================================================ 요청서 양식 (12단계 '쉽게 요청하기'의 첫 조각)
def run_request(nk, kit, args):
    """episodes/<ep>/request.yaml 빈 양식을 만듦 (있는 캐릭터·작가·그림체 목록을 주석으로)"""
    import nk_webtoon as W, glob
    d = W.ep_dir(kit, args.ep)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "request.yaml")
    if os.path.exists(p) and not getattr(args, "overwrite", False):
        print("[ERROR] already exists:", p, "(--overwrite to replace)"); sys.exit(1)
    chars = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "*.yaml")) if not os.path.basename(f).startswith("_"))
    cfg = nk.load_presets()
    arts = [k for k, v in (cfg.get("presets") or {}).items() if isinstance(v, dict) and v.get("artist")]
    try:
        import nk_restyle
        styles = sorted(set(list(nk_restyle.STYLES) + list((cfg.get("restyle") or {}).keys())))
    except Exception:
        styles = ["picturebook"]
    text = """# 만화 요청서 — 이것만 채우면: nk ep auto %(ep)s  (또는 웹 AI용: nk ep write %(ep)s)
# 캐릭터 파일: %(chars)s
# 작가 그림체(artist): %(arts)s
# 마지막 그림체 입히기(restyle): %(styles)s  (안 쓰려면 none)
title: "제목"
cast: {hero: mychar}           # 짧은 이름: 캐릭터 파일. 둘이면 {hero: mychar, buddy: buddy}
main: hero                     # 주인공
pages: 2                       # 쪽수 (한 쪽 4~6컷)
story: >-
  여기에 줄거리를 한국어로. 기승전결이 드러나게 3~5문장.
elements: "대사 많이, 효과음 3개 이상, 속도선 1컷, 마지막 컷은 크게"   # 넣고 싶은 만화 요소
artist: ""                     # (선택) 작가 태그 또는 presets.yaml 의 작가 이름
restyle: picturebook
# personality: {hero: "성격 한 줄"}   # (선택) 캐릭터 성격
""" % {"ep": args.ep, "chars": ", ".join(chars), "arts": ", ".join(arts), "styles": ", ".join(styles)}
    open(p, "w", encoding="utf-8").write(text)
    print("request form ->", p)


PULL_OK = {"exaone3.5:7.8b": "LG EXAONE 3.5 7.8B, 4.8GB, 한국어, 비상업 라이선스", "qwen3:8b": "Qwen3 8B, 5.2GB, Apache 2.0"}


def run_pull(nk, kit, args):
    """ollama 모델 받기 (허락된 것만). ollama HTTP API /api/pull"""
    import urllib.request, time
    if args.model not in PULL_OK:
        print("[ERROR] not an approved model: %s (approved: %s)" % (args.model, ", ".join(PULL_OK))); sys.exit(1)
    url = nk.load_presets().get("qa", {}).get("ollama", "http://127.0.0.1:11434").rstrip("/") + "/api/pull"
    req = urllib.request.Request(url, data=json.dumps({"model": args.model, "stream": True}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    print("pull %s (%s)" % (args.model, PULL_OK[args.model]))
    last, t0 = 0, time.time()
    with urllib.request.urlopen(req, timeout=7200) as r:
        for line in r:
            try:
                ev = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if ev.get("error"):
                print("[ERROR]", ev["error"]); sys.exit(1)
            st = ev.get("status", "")
            if ev.get("total") and time.time() - last > 20:
                last = time.time()
                print("  %s %.0f%% (%.1f / %.1f GB)" % (st[:30], 100.0 * ev.get("completed", 0) / ev["total"],
                                                      ev.get("completed", 0) / 1e9, ev["total"] / 1e9))
            elif not ev.get("total"):
                print(" ", st)
    print("done in %ds" % (time.time() - t0))
