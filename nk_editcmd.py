# -*- coding: utf-8 -*-
"""컷 수정 요청 해석.
개인 만화도 밖으로 안 나감.

명령 종류:
  retag  = 태그 넣기·빼기 (표정·동작·소품·배경) -> nk ep fix <ep> <cut> --add/--remove [--who]
  part   = 한 캐릭터의 한 부위만 다시 그리기 (얼굴·손·가슴/배·꼬리·귀·발) -> nk ep partfix
  redraw = 컷 전체를 새 시드로 다시 -> nk ep fix <ep> <cut>
  cands  = 후보 3장 -> nk ep cands
  unknown = 모르겠음 (실행 안 함)"""
import os, sys, json, re

ACTIONS = ("retag", "part", "redraw", "cands", "unknown")
PARTS = {"head": ("head", "face", "얼굴", "머리", "표정", "눈", "입"), "hand": ("hand", "hands", "손", "왼손", "오른손", "손가락", "paw", "paws"),
         "chest": ("chest", "belly", "stomach", "torso", "가슴", "배", "몸통", "무늬"), "tail": ("tail", "꼬리"),
         "ear": ("ear", "ears", "귀"), "foot": ("foot", "feet", "leg", "legs", "발", "다리")}
PART_KO = {"head": "얼굴·머리", "hand": "손", "chest": "가슴·배", "tail": "꼬리", "ear": "귀", "foot": "발·다리"}

SYSTEM = """너는 만화 컷 수정 요청을 '정해진 명령'으로 바꾸는 도구다. 컷 정보와 사용자의 요청을 읽고 JSON 하나만 출력한다. 설명 문장을 쓰지 않는다.

action (하나):
- "retag": 그림에 무언가를 넣거나 빼거나, 표정·동작·소품·배경·날씨를 바꿔 달라는 요청. add = 넣을 것, remove = 뺄 것.
- "part": 그림은 그대로 두고 한 캐릭터의 한 부위만 다시 그려 달라는 요청 (예: 손이 이상하다, 배 무늬만 다시, 얼굴만 다시).
- "redraw": 컷 전체를 그냥 다시 그려 달라는 요청.
- "cands": 여러 장 뽑아서 고르고 싶다는 요청.
- "unknown": 위 어느 것도 아니거나 무슨 말인지 모를 때.

who: 요청이 특정 캐릭터를 말하면 그 캐릭터의 짧은 이름 (컷 정보의 캐릭터 목록에 있는 것만), 아니면 "".
part: action 이 "part" 일 때만 — "head"(얼굴·머리), "hand"(손), "chest"(가슴·배 무늬·몸통), "tail"(꼬리), "ear"(귀), "foot"(발·다리) 중 하나. 아니면 "".
add, remove: action 이 "retag" 일 때만 — 영어 Danbooru 태그 목록 (소문자, 쉼표 없이 하나씩). 한국어 요청은 가장 가까운 흔한 태그로 옮긴다
  (웃는 얼굴 -> smile, 우는 -> crying, 비 -> rain, 우산 -> umbrella, 눈 감은 -> closed eyes, 앉은 -> sitting, 밤 -> night). remove 는 되도록 지금 컷 태그에 있는 말 그대로.
note: 네가 이해한 내용을 한국어 한 문장으로.

예시:
요청 "주인공 배만 다시 그려줘" -> {"action":"part","who":"hero","part":"chest","add":[],"remove":[],"note":"주인공의 가슴·배 부분만 다시 그린다"}
요청 "토끼 왼손이 이상해" -> {"action":"part","who":"bunny","part":"hand","add":[],"remove":[],"note":"토끼의 손만 다시 그린다"}
요청 "우산 빼고 웃는 얼굴로" -> {"action":"retag","who":"","part":"","add":["smile"],"remove":["umbrella"],"note":"우산을 빼고 웃는 표정으로 바꾼다"}
요청 "주인공이 울고 있게" -> {"action":"retag","who":"hero","part":"","add":["crying","tears"],"remove":[],"note":"주인공이 우는 모습으로 바꾼다"}
요청 "그냥 다시 그려줘" -> {"action":"redraw","who":"","part":"","add":[],"remove":[],"note":"컷 전체를 새로 그린다"}
요청 "몇 장 뽑아서 고를래" -> {"action":"cands","who":"","part":"","add":[],"remove":[],"note":"후보 여러 장을 그려 고른다"}
"""

SCHEMA = {"type": "object",
          "properties": {"action": {"type": "string", "enum": list(ACTIONS)}, "who": {"type": "string"}, "part": {"type": "string"},
                         "add": {"type": "array", "items": {"type": "string"}}, "remove": {"type": "array", "items": {"type": "string"}},
                         "note": {"type": "string"}},
          "required": ["action", "who", "part", "add", "remove", "note"]}


def _norm(t):
    return re.sub(r"\s+", " ", str(t or "").strip().lower().replace("_", " "))


def cut_context(plan, cid, names=None):
    """계획표에서 그 컷의 캐릭터·태그. names = {짧은 이름: 한국어 이름}"""
    cuts = [c for pg in plan.get("pages") or [] for c in pg.get("cuts") or []]
    if not 1 <= cid <= len(cuts):
        raise ValueError("컷 %d 은 없음 (이 만화는 1~%d)" % (cid, len(cuts)))
    c = cuts[cid - 1]
    who = [str(w) for w in (c.get("who") or []) if w]
    tags = [t.strip() for t in str(c.get("action") or "").split(",") if t.strip()]
    roles = {k: [t.strip() for t in str(v or "").split(",") if t.strip()] for k, v in (c.get("roles") or {}).items()}
    return {"cut": cid, "who": who, "names": {w: (names or {}).get(w, w) for w in who}, "tags": tags, "roles": roles,
            "shot": c.get("shot"), "props": list(c.get("props") or [])}


def build_messages(ctx, text):
    chars = ", ".join("%s(%s)" % (w, ctx["names"].get(w, w)) for w in ctx["who"]) or "(사람 없음)"
    info = "컷 %d / 캐릭터: %s / 지금 공통 태그: %s" % (ctx["cut"], chars, ", ".join(ctx["tags"]) or "(없음)")
    for w, ts in ctx["roles"].items():
        info += " / %s 태그: %s" % (w, ", ".join(ts))
    if ctx.get("props"):
        info += " / 소품: %s" % ", ".join(ctx["props"])
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "[컷 정보] %s\n[요청] %s" % (info, text.strip())}]


def _who(raw, ctx, text):
    """LLM 의 who + 요청 글의 이름으로 캐릭터를 정함. 컷에 한 명뿐이면 그 캐릭터"""
    who = ctx["who"]
    r = _norm(raw)
    for w in who:
        if r and (r == w.lower() or r == _norm(ctx["names"].get(w, ""))):
            return w
    for w in who:                                   # 요청 글에 한국어 이름·짧은 이름이 있으면
        ko = str(ctx["names"].get(w, "")).split("(")[0].strip()
        if (ko and ko in text) or re.search(r"\b%s\b" % re.escape(w), text, re.I):
            return w
    return who[0] if len(who) == 1 else ""


def _part(raw, text):
    r = _norm(raw)
    for k, words in PARTS.items():
        if r == k or r in words:
            return k
    for k, words in PARTS.items():                  # LLM 이 빈칸이면 요청 글에서
        if any(w in text for w in words if not w.isascii()):
            return k
    return ""


def validate(kit, ctx, raw, text):
    """LLM 답(dict) -> 검사한 명령 {action, who, part, add, remove, warnings, human, job}. 실행 못 할 것은 action=unknown"""
    import nk_webtoon as W
    act = str((raw or {}).get("action") or "unknown").strip().lower()
    if act not in ACTIONS:
        act = "unknown"
    warn = []
    out = {"action": act, "who": "", "part": "", "add": [], "remove": [], "note": str((raw or {}).get("note") or "")[:200]}
    cid = ctx["cut"]
    if act == "part":
        out["who"] = _who(raw.get("who"), ctx, text)
        out["part"] = _part(raw.get("part"), text)
        if not ctx["who"]:
            act, _ = "unknown", warn.append("이 컷엔 캐릭터가 없어서 부위를 다시 그릴 수 없음")
        elif not out["who"]:
            act, _ = "unknown", warn.append("어느 캐릭터인지 모르겠음 — 이름을 넣어 다시 적어 줘 (%s)" % ", ".join(str(x).split("(")[0].strip() for x in ctx["names"].values()))
        elif not out["part"]:
            act, _ = "unknown", warn.append("어느 부위인지 모르겠음 — 얼굴·손·가슴/배·꼬리·귀·발 중에서")
    elif act == "retag":
        db = W._load_tagdb(kit)
        have = {_norm(t) for t in ctx["tags"]} | {_norm(t) for ts in ctx["roles"].values() for t in ts}
        for key in ("add", "remove"):
            for t in (raw.get(key) or []):
                t = _norm(t)
                if not t or re.search(r"[^\x00-\x7f]", t) or len(t) > 40:
                    warn.append("영어 태그가 아닌 말은 뺌: %s" % t); continue
                if key == "add" and db:
                    st, n = W._tag_verdict(db, t)
                    if st == "NOT A TAG":
                        warn.append("태그 사전에 없는 말 (그림에 안 먹힐 수 있음): %s" % t)
                    elif st == "weak":
                        warn.append("드문 태그 (%d건, 약하게 먹힘): %s" % (n, t))
                if key == "remove" and t not in have:
                    warn.append("지금 컷 태그에 없는 말이라 못 뺌: %s" % t); continue
                if t not in out[key]:
                    out[key].append(t)
        if len(ctx["who"]) >= 2:
            out["who"] = _who(raw.get("who"), ctx, text) if (raw.get("who") or any(
                str(ctx["names"].get(w, "")).split("(")[0].strip() in text for w in ctx["who"])) else ""
        if not out["add"] and not out["remove"]:
            act, _ = "unknown", warn.append("넣거나 뺄 태그를 못 찾음 — 조금 더 구체적으로 적어 줘")
    out["action"] = act
    nm = str(ctx["names"].get(out["who"], out["who"])).split("(")[0].strip()
    if act == "retag":
        out["human"] = "컷 %d%s: 태그 %s%s → 그 컷을 다시 그림" % (
            cid, (" (%s만)" % nm) if out["who"] else "",
            ("넣기 [%s]" % ", ".join(out["add"])) if out["add"] else "",
            ((" · " if out["add"] else "") + "빼기 [%s]" % ", ".join(out["remove"])) if out["remove"] else "")
        out["job"] = {"kind": "fix", "cut": cid, "add": ", ".join(out["add"]), "remove": ", ".join(out["remove"]), "who": out["who"]}
    elif act == "part":
        out["human"] = "컷 %d: %s의 %s만 다시 그림 (후보 2장을 만들고, 마음에 드는 걸 '이걸로')" % (cid, nm, PART_KO[out["part"]])
        out["job"] = {"kind": "partfix", "cut": cid, "who": out["who"], "part": out["part"]}
    elif act == "redraw":
        out["human"] = "컷 %d: 같은 글, 새 시드로 컷 전체를 다시 그림" % cid
        out["job"] = {"kind": "fix", "cut": cid}
    elif act == "cands":
        out["human"] = "컷 %d: 새 시드 후보 3장을 그려 두고 고름 (지금 그림은 그대로)" % cid
        out["job"] = {"kind": "cands", "cut": cid}
    else:
        out["human"] = "무슨 수정인지 모르겠어. " + (" / ".join(warn) if warn else "예: '주인공 배만 다시 그려 줘', '우산 빼고 웃는 얼굴로', '그냥 다시 그려 줘'")
        out["job"] = None
    out["warnings"] = warn
    return out


def ask_ollama(cfg, messages, cpu=False):
    """로컬 Ollama 에 JSON 으로 답하게 함. (dict, 걸린 초) / 꺼져 있으면 RuntimeError"""
    import urllib.request, urllib.error, time
    q = cfg.get("qa") or {}
    url = str(q.get("ollama", "http://127.0.0.1:11434")).rstrip("/")
    body = {"model": q.get("model", "gemma4:e4b-it-qat"), "stream": False, "messages": messages, "format": SCHEMA, "keep_alive": "2m",
            "options": {"temperature": 0, "num_ctx": 4096}}
    if cpu:
        body["options"]["num_gpu"] = 0          # 그림 그리는 중이면 그래픽 카드를 안 건드림 (느리지만 안 겹침)
    t0 = time.time()
    try:
        req = urllib.request.Request(url + "/api/chat", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("Ollama 가 꺼져 있거나 응답이 없음 (%s) — 시작 메뉴에서 Ollama 를 켠 뒤 다시" % e)
    txt = (r.get("message") or {}).get("content") or ""
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0) if m else txt), time.time() - t0
    except Exception:
        return {"action": "unknown", "note": "답을 못 읽음: %s" % txt[:80]}, time.time() - t0


def char_names(nk, kit, plan):
    out = {}
    for short, fn in (plan.get("cast") or {}).items():
        try:
            d = nk.load_yaml(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "%s.yaml" % fn)) or {}
            out[str(short)] = str(d.get("name_ko") or short)
        except Exception:
            out[str(short)] = str(short)
    return out


def interpret(nk, kit, plan_path, cid, text, cpu=False, raw=None):
    """raw 를 주면 Ollama 를 안 부름 (시험용)"""
    plan = nk.load_yaml(plan_path)
    ctx = cut_context(plan, int(cid), char_names(nk, kit, plan))
    secs = 0.0
    if raw is None:
        raw, secs = ask_ollama(nk.load_presets(), build_messages(ctx, text), cpu=cpu)
    out = validate(kit, ctx, raw, text)
    out["secs"], out["llm"] = round(secs, 1), raw
    return out


def run(nk, kit, args):
    import nk_webtoon as W
    pp = os.path.join(W.ep_dir(kit, args.ep), "plan.yaml")
    raw = json.loads(args.raw) if args.raw else None
    try:
        out = interpret(nk, kit, pp, int(args.cut), args.text, cpu=args.cpu, raw=raw)
    except (RuntimeError, ValueError) as e:
        print("[ERROR] %s" % e); sys.exit(1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def add_parser(esub, nk, kit):
    a = esub.add_parser("editcmd", help="turn a Korean edit request for one cut into a checked command with local Ollama (does not run it)")
    a.add_argument("ep"); a.add_argument("cut", type=int); a.add_argument("text")
    a.add_argument("--cpu", action="store_true", help="Ollama on CPU (while ComfyUI is drawing)")
    a.add_argument("--raw", help="skip Ollama: use this JSON as its answer (tests)")
    a.set_defaults(func=lambda x: run(nk, kit, x))
