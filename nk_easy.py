# -*- coding: utf-8 -*-
"""nk_easy.py — '누구나 간단한 요청으로 만화' 쪽 명령 세 개

  nk ep grokfile               -> Grok_첨부용.md  (Grok에 첨부하고 자유롭게 요청하면 계획표(plan.yaml)를 써 주는 안내서)
  nk ep paste <ep> [--go]      -> 복사해 둔 Grok 답을 episodes/<ep>/plan.yaml 로 저장 + 검사. 고칠 점은 클립보드로 (Grok에 다시 붙여 넣기)
                                  --go : 고칠 점이 없으면 바로 만화 만들기(nk ep auto)
  nk ep fix <ep> <컷> [--add "태그"] [--remove "태그"] [--who 이름] [--nodraw]
                               -> 계획표의 그 컷 태그를 넣고/빼고 -> 콘티 다시 -> 그 컷만 새로 그림 -> 얼굴·그림체·글자까지 다시

왜 따로 파일: 기존 명령(write/compile/redo/auto)을 사람이 순서대로 이어야 했던 것을 한 번에 묶는 '겉' 층. 안쪽 규칙은 그대로 씀."""
import os, sys, re, time, glob, shutil, subprocess, json

GROK_FILE = "Grok_첨부용.md"


# ================================================================ 1. Grok 첨부 파일
def _char_rows(kit):
    import yaml
    import nk_plan
    rows = []
    for f in sorted(glob.glob(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "*.yaml"))):
        fn = os.path.splitext(os.path.basename(f))[0]
        try:
            d = yaml.safe_load(open(f, encoding="utf-8")) or {}
        except Exception:
            continue
        if d.get("grok_hide") or fn.startswith("_"):
            continue
        short = nk_plan.ALIAS.get(fn, fn)
        rows.append((short, fn, str(d.get("name_ko") or fn), " ".join(str(d.get("anima") or "").split()),
                     bool(d.get("lora")), str(d.get("personality") or "").strip(), str(d.get("grok_note") or ANIMA_KNOWS.get(fn, "")).strip()))
    return rows


ANIMA_KNOWS = {}   # 캐릭터 파일 이름 -> 메모 (캐릭터 파일의 grok_note 가 있으면 그것을 씀)
ARTIST_NOTE = ("- 쓸 작가: [작가 목록]의 main_artists (presets.yaml 에서 정함). 사용자가 다른 작가를 말하면 Danbooru/e621 작가 태그 이름 그대로\n"
               "- 목록이 비어 있고 요청에도 작가가 없으면 artist 줄을 쓰지 않는다")


def _artists(nk):
    cfg = nk.load_presets()
    main = list(cfg.get("main_artists") or [])
    arts = [k for k, v in (cfg.get("presets") or {}).items() if isinstance(v, dict) and v.get("artist")]
    return main, arts


def _styles(nk):
    try:
        import nk_restyle
        st = sorted(set(list(nk_restyle.STYLES) + list((nk.load_presets().get("restyle") or {}).keys())))
    except Exception:
        st = ["anime", "picturebook", "watercolor", "pencil"]
    return st


STYLE_KO = {"anime": "애니풍(셀 채색)", "picturebook": "그림책", "watercolor": "수채화", "pencil": "색연필"}

READ_RULES = """# 요청 읽는 법 (사용자는 이 파일을 첨부하고 자유로운 한국어로 요청한다)
사용자의 메시지가 곧 [요청]이다. 아래처럼 옮겨서 plan.yaml을 쓴다. 요청에 없는 것은 네가 이야기에 맞게 정한다.
1. **캐릭터**: 아래 [캐릭터 목록]에 있는 캐릭터만 쓸 수 있다. 한국어 이름·별명으로 찾아 `cast: {짧은이름: 파일이름}` 로 적는다.
   목록에 없는 캐릭터를 요청하면 YAML을 쓰지 말고 한 줄로만 답한다: `캐릭터 파일 없음: <이름>` (프로그램이 그 캐릭터를 그릴 준비가 안 됨)
   주인공(`main`)은 요청에서 가장 중심인 캐릭터.
2. **쪽수**: "N쪽/N페이지" -> pages를 정확히 N개, 그리고 맨 위에 `pages_wanted: N`. 없으면 2쪽.
3. **그림체(작가)**: 작가 이름을 말하면 [작가 목록]에서 같은 것을 `artist:` 에. 목록에 없는 작가는 Danbooru/e621 작가 태그 이름을
   그대로(영어, 공백은 띄어쓰기) 적는다 — 프로그램이 태그 사전에서 확인한다. 말이 없으면 [작가 목록]의 첫 작가 (목록이 비면 artist 줄을 쓰지 않는다).
4. **마무리 그림체(restyle)는 쓰지 않는다**. '수채화·그림책' 같은 말이 있으면
   그 느낌에 가까운 작가를 [작가 목록]에서 고르고 맨 위 주석에 한 줄로 적는다. restyle 줄은 쓰지 않는다.
5. **내용**: 요청한 줄거리를 기승전결로 나눠 페이지마다 note에 한 줄. 요청에 없는 세부(장소·소품·대사)는 네가 만든다.
6. **꼭 넣을 태그**: 사용자가 "태그는 ~을 꼭" 이라고 한 것 -> 영어 Danbooru 태그로 옮겨 맨 위 `must_tags: [태그, ...]` 에 적고,
   **알맞은 컷의 action(또는 roles·locations·props)에 실제로 넣는다.** 한국어로 말하면 가장 가까운 실제 Danbooru 태그로 옮긴다
   (예: 비 -> rain, 벚꽃 -> cherry blossoms, 우산 -> umbrella). 프로그램이 모든 must_tags가 어느 컷엔가 들어갔는지 검사한다.
7. **꼭 넣을 장면**: 사용자가 "~하는 장면을 꼭" 이라고 한 것 -> 맨 위 `must_scenes: ["장면 설명", ...]` 에 한국어로 적고,
   그 장면을 그리는 컷에 `must: "같은 설명"` 을 적는다 (장면마다 컷 하나 이상). 프로그램이 짝이 맞는지 검사한다.
8. **요소**(대사량·효과음·집중선·마지막 컷 크게 등): 연출 규칙 9·10대로 반영한다.
9. **등급**: 항상 전연령(safe). 선정적·폭력적으로 그리는 요청이면 그 부분은 빼고 전연령으로 바꿔 쓴다.
10. 되묻지 않는다. 애매하면 가장 자연스러운 쪽으로 정하고, YAML 맨 위 주석(# ...)에 한 줄로 무엇을 정했는지 적는다.
11. **대사는 [캐릭터 목록]의 '성격·말투'대로** 쓴다. 같은 컷의 두 사람 말투가 똑같지 않게.
12. **'줄거리 먼저'**: 사용자가 "줄거리 먼저"라고 하면 이번 답에는 YAML을 쓰지 않고, 한국어로 제목 한 줄 + 페이지마다 한 줄(기승전결) + 끝 반전 한 줄만 쓴다.
    사용자가 "좋아"라고 하거나 고칠 점을 말하면 그다음 답에서 그 줄거리대로 YAML을 쓴다.

추가로 쓰는 값 (위 형식에 더해서):
```yaml
pages_wanted: 3                     # 요청한 쪽수
must_tags: [rain, umbrella]         # 요청에서 '꼭' 넣으라고 한 태그 (영어 Danbooru 태그)
must_scenes: ["둘이 우산을 같이 쓰는 장면"]
pages:
  - note: "..."
    cuts:
      - who: [hero, buddy]
        ...
        must: "둘이 우산을 같이 쓰는 장면"   # must_scenes 의 한 항목과 같은 글
```
"""


SELF_CHECK = """# 내기 전 스스로 확인 (하나라도 어기면 고쳐서 낸다)
1. `cast`·`who`·대사의 who 는 [캐릭터 목록]의 **짧은 이름**만. 한 컷에 보이는 사람은 0~2명.
2. 쪽수 = 요청한 쪽수 (`pages_wanted` 와 pages 개수가 같다). 한 쪽 4~6컷.
3. 모든 사람 컷에 `shot` 과 `angle` 이 있고, 값은 정해진 것만 (shot: wide/full/knee/waist/face/detail/eyes/hands, angle: eye/high/low/side/back/tilt/pov).
4. 같은 shot 3컷 연속 없음. 장소의 첫 컷은 wide. 뒷모습(back)은 쪽당 1컷 이하.
5. `action`·`roles` 는 영어 Danbooru 태그만 (문장 X). 가능하면 [자주 쓰는 태그]에서. 새 말을 만들지 않는다.
6. `holding` 은 혼자 쓰지 않고 `holding 물건` + 그 물건을 `props` 에. 두 명 컷에선 드는 사람의 roles 에만.
7. action·roles·scene 에 furry·anthro·1boy 같은 인원수 태그, 옷·무늬 말이 없다. scene 은 이름 대신 겉모습으로, 영어 2~3문장(자세·손·시선).
   손 모양은 모양으로 쓰고 물건 이름(scissors·rock)을 쓰지 않는다. chibi·over the shoulder·speed lines 태그를 쓰지 않는다.
8. `artist` 는 [작가 목록]의 '쓸 작가' 중 하나 (요청에 작가가 없으면 목록의 첫 작가, 목록이 비면 쓰지 않음).
9. 대사는 짧게(15자 안팎, 컷당 말풍선 2개까지), 캐릭터의 **성격·말투**대로. 마지막 컷은 이야기를 닫는 큰 컷(big: true).
10. 요청의 '꼭 넣을 태그·장면'이 must_tags·must_scenes 와 해당 컷에 모두 들어갔다.
11. 쪽마다 big 은 하나, 반응 컷 1~2개는 bg: simple, 대사 없는 컷이 하나쯤 있다. 효과음은 소리 나는 컷에만 쪽당 1~3개.
"""


def build_grokfile(nk, kit):
    tpl = open(os.path.join(kit, "docs", "prompt_plan.md"), encoding="utf-8").read()
    rows = _char_rows(kit)
    main, arts = _artists(nk)
    styles = _styles(nk)
    chars = "\n".join("- **%s** — 짧은 이름 `%s`, 파일 `%s`%s%s%s: %s" % (
        ko, short, fn, " (LoRA 있음)" if lora else "", (" — " + note) if note else "",
        (" — **성격·말투**: " + pers) if pers else "",
        look or "(외형 설명 없음)") for short, fn, ko, look, lora, pers, note in rows)
    chars += "\n(외형 태그는 프로그램이 자동으로 붙이므로 action·sentence에 외형을 쓰지 않는다. 대사의 who에는 짧은 이름을 쓴다)"
    art = str(nk.load_presets().get("artist_note") or ARTIST_NOTE)
    tpl = tpl.replace("(프로그램이 채움: 짧은 이름 / 파일 / 외형 요약. 외형 태그는 프로그램이 자동으로 붙이므로 action에 외형을 쓰지 않는다)",
                      "[캐릭터 목록]\n" + chars + "\n\n# 작가 목록 (artist, Anima 는 '@이름'으로 씀 — 여기엔 이름만)\n" + art)
    tpl = tpl.replace("# 요청\n(프로그램이 채움)", READ_RULES)
    tpl = tpl.replace("아래 [요청]을 읽고", "사용자의 요청(이 파일을 첨부하며 보낸 메시지)을 읽고")
    tail = ""
    exf = os.path.join(kit, "docs", "grok_example.yaml")
    if os.path.exists(exf):
        ex = "".join(l for l in open(exf, encoding="utf-8") if not l.startswith("#"))
        tail += ("\n# 잘 된 예시 (형식·리듬만 참고 — 이야기·대사·캐릭터는 베끼지 않는다)\n"
                 "예시 만화 (2쪽): 풍경으로 시작 → 동작 → 소품 클로즈업 → 두 명 컷, 쪽마다 기승전결, 마지막은 큰 컷.\n"
                 "```yaml\n" + ex.strip() + "\n```\n")
    tail += "\n" + SELF_CHECK
    tpl = tpl.replace("위 형식의 YAML만 출력하라.", tail + "\n위 형식의 YAML만 출력하라 ('줄거리 먼저'라고 했으면 그 답만 줄거리).")
    head = ("<!-- nk ep grokfile 이 만든 파일 (%s). 캐릭터를 추가하면 nk ep grokfile 로 다시 만들 것 -->\n"
            % time.strftime("%Y-%m-%d %H:%M"))
    return head + tpl


def run_grokfile(nk, kit, args):
    text = build_grokfile(nk, kit)
    out = os.path.join(kit, GROK_FILE)
    open(out, "w", encoding="utf-8").write(text)
    print("Grok attachment ->", out, "(%d chars)" % len(text))
    print("  1. Grok 새 대화에 이 파일을 첨부")
    print("  2. 그냥 쓰기: 예) 여우와 토끼가 눈싸움하는 만화, 2쪽, 태그는 snow 꼭, 눈사람 만드는 장면 꼭 (줄거리부터 보려면 '줄거리 먼저')")
    print("     Grok 한도가 차면: 같은 파일을 Gemini·ChatGPT 무료에 첨부해도 됨")
    print("  3. Grok 답을 전부 복사 -> nk ep paste <화이름>")


# ================================================================ 2. 붙여넣기
def _clip_get():
    """Windows 클립보드 글 (PowerShell). 실패하면 None"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                           capture_output=True, timeout=20)
        t = r.stdout.decode("utf-8", "replace")
        return t if t.strip() else None
    except Exception:
        return None


def _clip_set(text):
    """Windows 클립보드에 글 넣기 (clip.exe는 UTF-16 BOM이면 한글도 됨). 성공 여부"""
    if os.environ.get("NK_NO_CLIP"):
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16"), timeout=20, check=True)
        return True
    except Exception:
        return False


def run_paste(nk, kit, args):
    import yaml
    import nk_webtoon as W
    import nk_plan
    if args.file:
        raw = open(args.file, encoding="utf-8-sig").read()
    else:
        raw = _clip_get()
        if raw is None:
            print("[ERROR] 클립보드에서 글을 못 읽었음. Grok 답을 파일로 저장해서: nk ep paste %s --file 답.txt" % args.ep); sys.exit(1)
    m = re.search(r"캐릭터 파일 없음\s*:\s*(.+)", raw)
    if m and "pages" not in raw:
        print("[STOP] Grok 답: 캐릭터 파일 없음: %s" % m.group(1).strip())
        print("  그 캐릭터는 characters\\ 에 파일이 있어야 그릴 수 있음 (새 캐릭터 만들기는 문서 참고)"); sys.exit(1)
    try:
        plan, body = nk_plan._extract_yaml(raw)
    except Exception as e:
        print("[ERROR] 복사한 글에서 YAML을 못 찾음 (Grok 답 전체를 복사했는지 확인. '줄거리 먼저' 답이면 Grok 에 '좋아'라고 하고 그다음 YAML 답을 붙여 넣기): %s" % e); sys.exit(1)
    if not isinstance(plan, dict) or not plan.get("pages"):
        print("[ERROR] 복사한 글에 'pages:' 가 없음 - Grok 답 전체를 복사했는지 확인 (처음 60자: %r)" % raw.strip()[:60]); sys.exit(1)
    d = W.ep_dir(kit, args.ep)
    drawn = glob.glob(os.path.join(d, "cuts", "cut*.png"))
    if drawn:
        print("[STOP] '%s' 에는 이미 그린 컷이 %d개 있음 - 새 콘티를 넣으면 그림과 콘티가 섞임. 새 화 이름으로 다시 붙여 넣어 줘 (예: %s_2)"
              % (args.ep, len(drawn), args.ep)); sys.exit(1)
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%m%d_%H%M%S")
    open(os.path.join(d, "grok_answer_%s.md" % ts), "w", encoding="utf-8").write(raw)
    pp = os.path.join(d, "plan.yaml")
    if os.path.exists(pp):
        shutil.copy(pp, os.path.join(d, "plan_%s.bak.yaml" % ts))
        print("old plan kept: plan_%s.bak.yaml" % ts)
    open(pp, "w", encoding="utf-8").write("# Grok 답 (nk ep paste %s)\n" % time.strftime("%Y-%m-%d %H:%M") + body)
    if getattr(args, "flow", None):
        import nk_flow
        nk_flow.set_top_key(pp, "flow", args.flow)
        print("flow: %s (혼자 컷을 workflows\\%s.json 으로 그림)" % (args.flow, args.flow))
    n_cuts = sum(len(pg.get("cuts") or []) for pg in plan["pages"])
    print("plan -> %s  (%s / %d pages, %d cuts / cast %s)" % (pp, plan.get("title", "?"), len(plan["pages"]), n_cuts,
                                                            ", ".join((plan.get("cast") or {}).keys())))
    # 새 계획이면 옛 상태(자동 제작 기록·완성 그림)를 섞지 않게: 콘티가 바뀌는 것만 알림 (그림은 지우지 않음)
    if os.path.exists(os.path.join(d, "auto", "state.json")):
        print("[note] 이 화는 전에 만든 기록이 있음 -> 처음부터 새로 만들려면 새 화 이름을 쓰는 게 안전 (예: %s_2)" % args.ep)
    nk_plan.run_compile(nk, kit, nk_plan.argparse_ns(ep=args.ep, dry=False, plan="plan.yaml"))
    fp = os.path.join(d, "fix_prompt.md")
    if os.path.exists(fp):
        txt = open(fp, encoding="utf-8").read()
        ok = _clip_set(txt)
        print("\n[Grok에 돌려줄 고칠 점] %s" % ("클립보드에 복사됨 -> Grok 같은 대화에 붙여 넣고, 새 답을 복사해서 다시 nk ep paste %s"
                                          % args.ep if ok else "파일: %s" % fp))
        if not getattr(args, "go", False):
            print("  (고치지 않고 그대로 만들어도 됨: nk ep auto %s)" % args.ep)
            return
        print("  -> '바로 만들기'라서 고칠 점은 참고로만 두고 그대로 만듦 (고쳐서 만들려면 '검사만' 버튼)")
    else:
        print("\n검사 통과.")
    if args.go:
        import nk_auto
        print("-> 바로 만들기 (nk ep auto %s)" % args.ep)
        ns = nk_plan.argparse_ns(ep=args.ep, style=None, start=None, stop=None, n=3, layout_seeds=3, fresh=False,
                                 writer="prompt", model=None, duo="compose", redo_duo=False, dry=False)
        nk_auto.run(nk, kit, ns)
    else:
        print("만들기: nk ep auto %s" % args.ep)


# ================================================================ 3. 컷 하나 고치기
def _norm(t):
    return re.sub(r"\s+", " ", str(t).strip().lower().replace("_", " "))


def _edit_tags(text, add, remove):
    tags = [t.strip() for t in str(text or "").split(",") if t.strip()]
    rm = {_norm(x) for x in remove}
    out = [t for t in tags if _norm(t) not in rm]
    gone = [t for t in tags if _norm(t) in rm]
    have = {_norm(t) for t in out}
    added = []
    for a in add:
        if _norm(a) not in have:
            out.append(a.strip()); have.add(_norm(a)); added.append(a.strip())
    return ", ".join(out), added, gone


def run_fix(nk, kit, args):
    import yaml
    import nk_webtoon as W
    import nk_plan
    d = W.ep_dir(kit, args.ep)
    pp = os.path.join(d, "plan.yaml")
    add = [t for t in re.split(r"[,，]", args.add or "") if t.strip()]
    remove = [t for t in re.split(r"[,，]", args.remove or "") if t.strip()]
    cid = int(args.cut)
    changed = False
    if add or remove:
        if not os.path.exists(pp):
            print("[ERROR] no plan.yaml in %s - 태그 고치기는 계획표가 있는 화만 (콘티를 손으로 쓴 화는 conti.yaml을 직접)" % d); sys.exit(1)
        plan, _ = nk_plan._extract_yaml(open(pp, encoding="utf-8-sig").read())
        cuts = [pc for pg in plan.get("pages") or [] for pc in pg.get("cuts") or []]
        if not 1 <= cid <= len(cuts):
            print("[ERROR] cut %d: this episode has cuts 1-%d" % (cid, len(cuts))); sys.exit(1)
        pc = cuts[cid - 1]
        who = [w for w in (pc.get("who") or []) if w]
        if getattr(args, "loc", False):
            if not pc.get("loc") or pc["loc"] not in (plan.get("locations") or {}):
                print("[ERROR] cut %d has no location (loc) in the plan" % cid); sys.exit(1)
            where = "loc"
        elif args.who:
            if args.who not in who:
                print("[ERROR] cut %d: '%s' is not in this cut (who: %s)" % (cid, args.who, who)); sys.exit(1)
            if len(who) < 2:
                where = "action"
            else:
                where = "roles." + args.who
        else:
            where = "action"
        if where == "loc":
            plan["locations"][pc["loc"]], added, gone = _edit_tags(plan["locations"][pc["loc"]], add, remove)
            where = "locations.%s" % pc["loc"]
        elif where == "action":
            pc["action"], added, gone = _edit_tags(pc.get("action"), add, remove)
        else:
            roles = pc.setdefault("roles", {})
            roles[args.who], added, gone = _edit_tags(roles.get(args.who), add, remove)
        missing = [r for r in remove if _norm(r) not in {_norm(g) for g in gone}]
        print("cut %d %s: +%s -%s%s" % (cid, where, added or "[]", gone or "[]",
                                        ("  (없어서 못 뺀 것: %s)" % missing) if missing else ""))
        if not added and not gone:
            print("nothing changed in the plan")
        else:
            ts = time.strftime("%m%d_%H%M%S")
            shutil.copy(pp, os.path.join(d, "plan_%s.bak.yaml" % ts))
            open(pp, "w", encoding="utf-8").write(
                "# nk ep fix %s %d (%s): %s +%s -%s  (고치기 전: plan_%s.bak.yaml)\n"
                % (args.ep, cid, time.strftime("%Y-%m-%d %H:%M"), where, added, gone, ts)
                + yaml.safe_dump(plan, allow_unicode=True, sort_keys=False, width=160))
            nk_plan.run_compile(nk, kit, nk_plan.argparse_ns(ep=args.ep, dry=False, plan="plan.yaml"))
            changed = True
    else:
        # 계획표를 손(메모장)으로 고친 뒤 태그 없이 fix 한 경우: 콘티가 계획표보다 옛것이면 다시 만듦
        cp = os.path.join(d, "conti.yaml")
        if os.path.exists(pp) and (not os.path.exists(cp) or os.path.getmtime(pp) > os.path.getmtime(cp)):
            print("plan.yaml is newer than conti.yaml -> compile first")
            nk_plan.run_compile(nk, kit, nk_plan.argparse_ns(ep=args.ep, dry=False, plan="plan.yaml"))
            changed = True
    if args.nodraw:
        print("--nodraw: 계획·콘티만 고침. 그리기: nk ep fix %s %d" % (args.ep, cid)); return
    conti = W.load_conti(nk, kit, args.ep)
    ct = next((c for c in conti["cuts"] if int(c["id"]) == cid), None)
    if ct is None:
        print("[ERROR] cut %d is not in the conti" % cid); sys.exit(1)
    f = W._final_file(kit, args.ep, cid)
    if os.path.exists(f):
        keep = os.path.join(d, "cuts_old")
        os.makedirs(keep, exist_ok=True)
        dst = os.path.join(keep, "cut%02d_%s.png" % (cid, time.strftime("%m%d_%H%M%S")))
        shutil.copy(f, dst)
        print("old picture kept:", dst)
    import nk_auto
    comp = nk_auto._compose_cuts(W, conti, nk_plan.argparse_ns(duo="compose"))
    if getattr(args, "render", "anima") == "anima":
        if not changed:
            import nk_animacut
            n = nk_animacut.bump_reseed(args.ep, cid)
            print("새 시드로 다시 그림 (이 컷 %d번째 다시 그리기, 시드 +%d)" % (n, 1000 * n))
        if os.path.exists(f):
            os.remove(f)
        start = "make"
    elif cid in comp:
        # 두 명 컷(합치기): 최종본을 지우면 auto의 compose 단계가 새로 합침
        if os.path.exists(f):
            os.remove(f)
        start = "compose"
    else:
        W.redo(nk, kit, nk_plan.argparse_ns(ep=args.ep, cuts=[cid], all=False, n=3, noqa=False, full=False, seed=None, dry=False))
        start = "propfix"
    print("\n-> 뒤 단계 다시 (%s ~ review, 바뀐 컷만 새로 함)" % start)
    ns = nk_plan.argparse_ns(ep=args.ep, style=None, start=start, stop=None, n=3, layout_seeds=3, fresh=False,
                             writer="prompt", model=None, duo="compose", redo_duo=False, dry=False)
    nk_auto.run(nk, kit, ns)


# 최종본은 고를 때까지 그대로. 두 명 컷은 말풍선 꼬리 자리(regionlora.json 의 그 컷 기록)도 후보마다 남겼다가 고른 것으로 되돌림.
CAND_RE = re.compile(r"^[rp]\d{2,3}\.png$")          # r = 새 시드 후보 (cands), p = 부위만 다시 그린 후보 (partfix)


def _cand_dir(W, kit, ep, cid):
    return os.path.join(W.ep_dir(kit, ep), "cands", "cut%02d" % int(cid))


def _rl_entry(W, kit, ep, cid, value=None, put=False):
    """regionlora.json 의 그 컷 기록 읽기 / 쓰기 (두 명 컷 말풍선 꼬리 자리 'spans' 가 여기 있음)"""
    rp = os.path.join(W.ep_dir(kit, ep), "regionlora.json")
    nm = "cut%02d" % int(cid)
    try:
        rec = json.load(open(rp, encoding="utf-8"))
    except Exception:
        rec = None
    if not put:
        return (rec or {}).get(nm)
    if rec is None or value is None:
        return None
    rec[nm] = value
    json.dump(rec, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def run_cands(nk, kit, args):
    import nk_webtoon as W
    import nk_plan, nk_auto, nk_animacut
    cid, n = int(args.cut), max(1, min(6, int(args.n)))
    f = W._final_file(kit, args.ep, cid)
    cd = _cand_dir(W, kit, args.ep, cid)
    os.makedirs(cd, exist_ok=True)
    mark = os.path.join(cd, "_running.json")
    if os.path.exists(mark):
        try:
            old = json.load(open(mark, encoding="utf-8"))
            if old.get("had_final") and os.path.exists(os.path.join(cd, "_now.png")):
                shutil.copy2(os.path.join(cd, "_now.png"), f)
                _rl_entry(W, kit, args.ep, cid, old.get("rl"), put=True)
                print("[note] 끊긴 후보 그리기를 되돌림: 컷 %d 최종본 = 끊기기 전 그림" % cid)
        except Exception as e:
            print("[note] 끊긴 후보 그리기 되돌리기 실패: %s" % e)
    keep = os.path.join(cd, "_now.png") if os.path.exists(f) else None
    if keep:
        shutil.copy2(f, keep)
    orig_rl = _rl_entry(W, kit, args.ep, cid)
    json.dump({"had_final": bool(keep), "rl": orig_rl, "time": time.strftime("%Y-%m-%d %H:%M:%S")}, open(mark, "w", encoding="utf-8"), ensure_ascii=False)
    made = []
    try:
        for _ in range(n):
            k = nk_animacut.bump_reseed(args.ep, cid)
            if os.path.exists(f):
                os.remove(f)
            print("\n== 후보 %d/%d (컷 %d, 시드 +%d)" % (len(made) + 1, n, cid, 1000 * k))
            nk_auto.run(nk, kit, nk_plan.argparse_ns(ep=args.ep, style=None, start="make", stop="make", n=3, layout_seeds=3,
                                                     fresh=False, writer="prompt", model=None, duo="compose", redo_duo=False, dry=False))
            if os.path.exists(f):
                dst = os.path.join(cd, "r%02d.png" % k)
                shutil.copy2(f, dst)
                ent = _rl_entry(W, kit, args.ep, cid)
                if ent is not None:
                    json.dump(ent, open(dst[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                made.append(dst)
                try:
                    import nk_animacut as _A
                    cut = next(x for x in W.load_conti(nk, kit, args.ep)["cuts"] if int(x["id"]) == cid)
                    fl = _A.body_flags(kit, args.ep, cut, dst)
                    json.dump({"body_flags": fl}, open(dst[:-4] + "_inspect.json", "w", encoding="utf-8"), ensure_ascii=False)
                    print("   후보 %s: 검사 걸림 %d %s" % (os.path.basename(dst), len(fl), fl))
                except Exception as e:
                    print("   [inspect] 후보 검사 실패: %s" % e)
    finally:
        if keep:
            shutil.copy2(keep, f)
            _rl_entry(W, kit, args.ep, cid, orig_rl, put=True)
        if os.path.exists(mark):
            os.remove(mark)
    print("\n후보 %d장 -> %s (작업실 그 컷에서 '이걸로')" % (len(made), cd))


def run_usecand(nk, kit, args):
    import nk_webtoon as W
    import nk_plan, nk_auto
    cid = int(args.cut)
    if not CAND_RE.match(args.name):
        print("[ERROR] 후보 이름이 이상함: %s" % args.name); sys.exit(1)
    src = os.path.join(_cand_dir(W, kit, args.ep, cid), args.name)
    if not os.path.exists(src):
        print("[ERROR] 후보 없음: %s" % src); sys.exit(1)
    f = W._final_file(kit, args.ep, cid)
    if os.path.exists(f):
        old = os.path.join(W.ep_dir(kit, args.ep), "cuts_old")
        os.makedirs(old, exist_ok=True)
        shutil.copy2(f, os.path.join(old, "cut%02d_%s.png" % (cid, time.strftime("%m%d_%H%M%S"))))
    shutil.copy2(src, f)
    js = src[:-4] + ".json"
    if os.path.exists(js):
        _rl_entry(W, kit, args.ep, cid, json.load(open(js, encoding="utf-8")), put=True)
    print("컷 %d = %s (옛 그림은 cuts_old) -> 말풍선·검토 다시" % (cid, args.name))
    nk_auto.run(nk, kit, nk_plan.argparse_ns(ep=args.ep, style=None, start="letter", stop=None, n=3, layout_seeds=3,
                                             fresh=False, writer="prompt", model=None, duo="compose", redo_duo=False, dry=False))


# ================================================================ 4. 번호로 고르는 메뉴 (만화만들기.bat 더블클릭)
def _comfy_up(nk):
    import urllib.request
    for p in (8000, 8188, 8189, 8190, 8191):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/system_stats" % p, timeout=2)
            return p
        except Exception:
            continue
    return None


def _comfy_busy(port):
    """ComfyUI 대기열에 도는/기다리는 작업 수 (다른 폴더가 쓰는 중인지). 모르면 0"""
    import urllib.request, json as _j
    try:
        q = _j.loads(urllib.request.urlopen("http://127.0.0.1:%d/queue" % port, timeout=3).read().decode("utf-8"))
        return len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])
    except Exception:
        return 0


def _ok_to_draw(nk):
    port = _comfy_up(nk)
    if not port:
        print("[STOP] ComfyUI가 꺼져 있음 -> ComfyUI Desktop을 켜고 캔버스가 뜬 뒤 다시"); return False
    n = _comfy_busy(port)
    if n:
        print("[주의] ComfyUI가 다른 그림 작업 %d개를 하는 중 (다른 폴더의 작업일 수 있음)." % n)
        print("       같이 돌리면 둘 다 느려지고, 그래픽 메모리(8GB)가 모자라 멈출 수 있음.")
        return _ask("그래도 시작할까요? (y/n)", "n").lower().startswith("y")
    return True


def _ask(q, default=""):
    try:
        v = input(q + (" [%s]" % default if default else "") + ": ").strip()
    except EOFError:
        v = ""
    return v or default


def _open(path):
    try:
        os.startfile(path)            # Windows 탐색기/그림 보기
    except Exception:
        print("  열기:", path)


def _eps(kit):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(os.environ.get("NK_HOME") or kit, "episodes", "*"))
                  if os.path.isdir(p))


def run_menu(nk, kit, args):
    import nk_plan
    if hasattr(nk, "keep_awake"):
        nk.keep_awake()
    ns = nk_plan.argparse_ns
    last = ""
    while True:
        port = _comfy_up(nk)
        busy = _comfy_busy(port) if port else 0
        print("\n================ 만화 만들기 메뉴 ================  (%s)" % kit)
        print("ComfyUI: %s" % (("켜져 있음 (포트 %d)" % port + (" - 지금 다른 작업 %d개 진행 중" % busy if busy else ""))
                                if port else "꺼져 있음 -> 그리기 전에 ComfyUI Desktop을 켜 두기"))
        print(" 1. Grok 첨부 파일 만들기 (캐릭터를 추가했으면 다시)")
        print(" 2. Grok 답 붙여넣기 (Grok 답을 전부 복사한 뒤)")
        print(" 3. 만화 만들기 / 멈춘 곳부터 이어서")
        print(" 4. 컷 하나 고치기 (태그 넣기·빼기 -> 그 컷만 다시 / 태그 없이 엔터 = 새 시드로 다시 그리기)")
        print(" 5. 대사만 고친 뒤 글자 다시 넣기 (plan.yaml의 lines를 고친 뒤)")
        print(" 6. 결과 보기 (완성 쪽 폴더 + 검토 그림)")
        print(" 7. 캐릭터 추가 (시중 캐릭터: 이름 -> 시험 그림 8장 -> 캐릭터 파일)")
        print(" 0. 끝")
        c = _ask("번호")
        try:
            if c == "0" or c.lower() in ("q", "exit"):
                return
            if c == "1":
                run_grokfile(nk, kit, ns())
                _open(os.path.join(kit, GROK_FILE))
            elif c == "7":
                import nk_charadd as CA
                name = _ask("캐릭터 이름 (한국어나 영어, 작품 이름을 같이 쓰면 더 잘 찾음)")
                if not name:
                    continue
                res = CA.find(nk, kit, name.split())
                if not res:
                    print("후보 없음 -> 영어 이름으로 다시. 태그 사전에 없으면 모델이 모르는 캐릭터 (LoRA 필요)"); continue
                for i, (t, n) in enumerate(res, 1):
                    print("%2d. %-45s %6d장  %s" % (i, t, n, CA.verdict(n)))
                k = _ask("번호 (그만두려면 엔터)")
                if not k.isdigit() or not 1 <= int(k) <= len(res):
                    continue
                tag = res[int(k) - 1][0]
                ko = _ask("이 캐릭터를 부를 한국어 이름 (Grok 첨부 파일에 나옴)", name)
                if not _ok_to_draw(nk):
                    continue
                r = CA.run_add(nk, kit, ns(tag=tag, ko=ko, n=8, seed=501, artist=None, save=False, overwrite=False,
                                           force_low=True, dry=False))
                if r:
                    _open(r["sheet"])
                    print("\n확인 그림을 보고: 캐릭터가 맞고 외형 태그가 대체로 맞으면 저장.")
                    print("틀린 태그는 저장 뒤 characters\\%s 를 메모장으로 열어 지우면 됨." % os.path.basename(r["file"]))
                    if _ask("저장할까요? (y/n)", "n").lower().startswith("y"):
                        open(r["file"], "w", encoding="utf-8").write(r["text"])
                        print("저장:", r["file"])
                        run_grokfile(nk, kit, ns())
                        print("-> Grok 첨부 파일도 새로 만듦 (Grok 새 대화에 다시 첨부)")
            elif c in ("2", "3", "4", "5", "6"):
                print("있는 화: %s" % (", ".join(_eps(kit)) or "(없음)"))
                ep = _ask("화 이름 (영어·숫자, 예: ep01)", last)
                if not ep:
                    continue
                last = ep
                if c == "2":
                    run_paste(nk, kit, ns(ep=ep, file=None, go=False))
                    if not os.path.exists(os.path.join(os.environ.get("NK_HOME") or kit, "episodes", ep, "fix_prompt.md")) and \
                            _ask("바로 만들까요? (y/n)", "n").lower().startswith("y"):
                        c = "3"
                if c == "3":
                    if not _ok_to_draw(nk):
                        continue
                    import nk_auto
                    nk_auto.run(nk, kit, ns(ep=ep, style=None, start=None, stop=None, n=3, layout_seeds=3, fresh=False,
                                            writer="prompt", model=None, duo="compose", redo_duo=False, dry=False))
                elif c == "4":
                    cut = int(_ask("컷 번호"))
                    add = _ask("넣을 태그 (쉼표로, 없으면 엔터 — 둘 다 없으면 새 시드로 다시 그림)")
                    rem = _ask("뺄 태그 (쉼표로, 없으면 엔터)")
                    who = _ask("두 명 컷에서 한 사람만 고칠 때 그 짧은 이름 (아니면 엔터)")
                    if not _ok_to_draw(nk):
                        continue
                    run_fix(nk, kit, ns(ep=ep, cut=cut, add=add, remove=rem, who=who or None, nodraw=False))
                elif c == "5":
                    import nk_webtoon as W
                    nk_plan.run_compile(nk, kit, ns(ep=ep, dry=False, plan="plan.yaml"))
                    conti = W.load_conti(nk, kit, ep)
                    W.letter(nk, kit, ns(ep=ep, style=None))
                    if conti.get("restyle"):
                        W.letter(nk, kit, ns(ep=ep, style=conti["restyle"]))
                elif c == "6":
                    d = os.path.join(os.environ.get("NK_HOME") or kit, "episodes", ep)
                    outs = sorted(glob.glob(os.path.join(d, "out_*"))) or [os.path.join(d, "out")]
                    _open(outs[-1])
                    rv = os.path.join(d, "auto", "review.png")
                    if os.path.exists(rv):
                        _open(rv)
        except SystemExit:
            print("(이 단계는 위 메시지에서 멈춤 - 메뉴로 돌아감)")
        except KeyboardInterrupt:
            print("\n(중단 - 메뉴로 돌아감)")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("[ERROR] %s - 메뉴로 돌아감" % e)


# 키트는 그대로 두고, 필요한 것만 다른 폴더로 복사. 모델(ComfyUI·Ollama)은 PC에 하나라 같이 씀.
LAB_CODE = ["nk.bat", "만화만들기.bat", "작업실.bat"]                         # + nk*.py 전부
LAB_DOCS = ["prompt_plan.md", "conti_rules.md", "grok_example.yaml"]
LAB_DIRS = ["characters", "character", "tags", os.path.join("models", "wd-eva02-large-tagger-v3")]
LAB_FILES_ONCE = ["presets.yaml", "nk_guide.md"]
LAB_README = """# 실험 폴더 안내 (nk ep newlab 이 만듦, %(ts)s)

이 폴더는 키트(%(src)s)에서 복사한 **개인 시험 폴더**다. 원본 키트는 그대로 둔다.
그림 엔진(ComfyUI)·검수 AI(Ollama)·파이썬은 키트와 같은 것을 같이 쓴다.

## 쓰는 법
1. ComfyUI Desktop 켜기 (캔버스가 뜰 때까지)
2. 이 폴더의 `만화만들기.bat` 더블클릭
   - 1: Grok 첨부 파일 만들기 -> 이 폴더에 `Grok_첨부용.md`
   - 2: Grok 답 붙여넣기 (Grok 답 전체 복사 후) -> 화 이름 (예: n01)
   - 3: 만화 만들기 (Anima 흐름 2쪽 약 15분)   4: 컷 하나 고치기   5: 대사만   6: 결과 보기
3. 결과: `episodes\\<화>\\out\\page_01.png ...`, 검토 `episodes\\<화>\\auto\\review.png`

## 주의
- 그래픽 카드가 하나라서, 키트에서 다른 작업이 도는 중에 여기서 만들면 둘 다 느려지거나 멈출 수 있음.
  메뉴 맨 위에 "지금 다른 작업 N개 진행 중"이 보이면 끝날 때까지 기다리기 (메뉴 3·4가 물어봄).
- 화 이름은 키트과 겹치지 않게 (예: n01, n02 ...). ComfyUI 원본 출력 폴더는 둘이 같이 씀.
- 캐릭터·작가 설정을 여기서 바꿔도 키트에는 영향 없음.

## 기록 남기기 (좋았던 것·안 좋았던 것·고친 것)
- 이야기: `episodes\\<화>\\plan.yaml`, `grok_answer_*.md` (Grok 답 원문)
- 결과: `episodes\\<화>\\out_*\\page_*.png`, `episodes\\<화>\\auto\\review.md`
- 에러: 검은 창의 마지막 30줄 복사
- 여기서 고친 캐릭터·설정 파일: `characters\\<이름>.yaml`, `presets.yaml`

## 키트의 새 코드 받기
키트 폴더의 `실험폴더_업데이트.bat` 실행 -> 같은 경로 입력.
코드(nk*.py, bat)와 규칙 문서만 덮어쓰고, 이 폴더의 presets.yaml·캐릭터 파일·episodes·runs 는 그대로 둠 (키트에만 있는 새 캐릭터 파일은 추가).
"""


def _copy(src, dst, log):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    log.append(dst)


def _workshop_folders(cfg_path=None):
    """폴더 안은 읽지 않고 주소만"""
    if cfg_path is None:
        import nk_web
        cfg_path = nk_web.CFG_PATH
    try:
        fs = [f for f in json.load(open(cfg_path, encoding="utf-8")).get("folders", []) if isinstance(f, str)]
    except Exception:
        return []
    out = []
    for f in fs:
        f = os.path.normpath(f)
        if os.path.basename(f).lower() == "episodes":
            f = os.path.dirname(f)
        if f not in out:
            out.append(f)
    return out


def _refresh_chars(kit, dest, log):
    """--chars: 캐릭터 파일(characters·character)을 키트 것으로. 달라진 옛 파일은 <dest>\\_backup\\<시각>\\ 에 먼저 남김"""
    bk = os.path.join(dest, "_backup", time.strftime("%m%d_%H%M%S"))
    n_bk = 0
    for sub in ("characters", "character"):
        for root, dirs, files in os.walk(os.path.join(kit, sub)):
            dirs[:] = [x for x in dirs if x != "parts"]
            for fn in files:
                s_ = os.path.join(root, fn)
                d_ = os.path.join(dest, os.path.relpath(s_, kit))
                if os.path.exists(d_):
                    if open(d_, "rb").read() == open(s_, "rb").read():
                        continue
                    b_ = os.path.join(bk, os.path.relpath(s_, kit))
                    os.makedirs(os.path.dirname(b_), exist_ok=True)
                    shutil.copy2(d_, b_); n_bk += 1
                _copy(s_, d_, log)
    return bk if n_bk else None


def run_newlab(nk, kit, args):
    dest = (args.dest or "").strip().strip('"')
    if not dest and getattr(args, "workshop", False):
        fs = _workshop_folders()
        if not fs:
            print("[ERROR] 작업실에 추가한 개인 폴더가 없음 -> 작업실 '개인 폴더 추가' 또는 실험폴더_업데이트.bat 에 경로 입력"); sys.exit(1)
        if len(fs) == 1:
            dest = fs[0]
        else:
            for i, f in enumerate(fs, 1):
                print(" %d. %s" % (i, f))
            k = _ask("업데이트할 폴더 번호", "1")
            dest = fs[int(k) - 1] if k.isdigit() and 1 <= int(k) <= len(fs) else ""
        print("업데이트할 폴더:", dest)
    if not dest:
        dest = _ask("새 실험 폴더 경로 (예: C:\\comic_lab)", "C:\\comic_lab").strip().strip('"')
    dest = os.path.abspath(dest)
    k = os.path.normcase(os.path.abspath(kit))
    dn = os.path.normcase(dest)
    if dn == k or dn.startswith(k + os.sep) or k.startswith(dn + os.sep):
        print("[ERROR] 실험 폴더는 키트 폴더 안/밖(상위)이 아닌 다른 곳이어야 함: %s" % dest); sys.exit(1)
    has = os.path.exists(os.path.join(dest, "nk.py"))
    if has and not args.update:
        print("[ERROR] 이미 nk가 있는 폴더: %s  -> 새 코드만 받으려면 실험폴더_업데이트.bat (nk ep newlab --update)" % dest); sys.exit(1)
    if args.update and not has:
        print("[ERROR] 실험 폴더가 아님 (nk.py 없음): %s  -> 처음이면 실험폴더_만들기.bat" % dest); sys.exit(1)
    log = []
    for f in sorted(glob.glob(os.path.join(kit, "nk*.py"))) + [os.path.join(kit, x) for x in LAB_CODE]:
        if os.path.exists(f) and not os.path.basename(f) == "nk_remote.py":       # 우체통 러너는 안 가져감
            _copy(f, os.path.join(dest, os.path.basename(f)), log)
    for x in LAB_DOCS:
        s = os.path.join(kit, "docs", x)
        if os.path.exists(s):
            _copy(s, os.path.join(dest, "docs", x), log)
    for sub in LAB_DIRS:
        sd = os.path.join(kit, sub)
        for root, dirs, files in os.walk(sd):
            dirs[:] = [x for x in dirs if x != "parts"]
            for fn in files:
                s = os.path.join(root, fn)
                d = os.path.join(dest, os.path.relpath(s, kit))
                if args.update and os.path.exists(d) and (sub.startswith("character") or sub == "characters"):
                    continue
                if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s) and os.path.getmtime(d) >= os.path.getmtime(s):
                    continue                                      # 같은 파일 (큰 판별기 모델 다시 복사 안 함)
                if os.path.getsize(s) > 200 * 1024 * 1024:
                    print("  copying %s (%.1f GB) ..." % (fn, os.path.getsize(s) / 1e9))
                _copy(s, d, log)
    bk = _refresh_chars(kit, dest, log) if (args.update and getattr(args, "chars", False)) else None
    dw = os.path.join(kit, "models", "dwpose", "dw-ll_ucoco_384.onnx")
    if os.path.exists(dw) and not os.path.exists(os.path.join(dest, "models", "dwpose", "dw-ll_ucoco_384.onnx")):
        _copy(dw, os.path.join(dest, "models", "dwpose", "dw-ll_ucoco_384.onnx"), log)
    if not args.update:
        for x in LAB_FILES_ONCE:
            s = os.path.join(kit, x)
            if os.path.exists(s):
                _copy(s, os.path.join(dest, x), log)
        pp = os.path.join(dest, "presets.yaml")
        if os.path.exists(pp):
            t = open(pp, encoding="utf-8").read()
            t = re.sub(r"(?m)^output_root:.*$", "output_root: runs   # 실험 폴더: 이 폴더의 runs (nk ep newlab)", t)
            open(pp, "w", encoding="utf-8").write(t)
        for sub in ("episodes", "runs"):
            os.makedirs(os.path.join(dest, sub), exist_ok=True)
        open(os.path.join(dest, "실험폴더_안내.md"), "w", encoding="utf-8").write(
            LAB_README % {"ts": time.strftime("%Y-%m-%d %H:%M"), "src": kit})
    print("\n%s: %d files -> %s" % ("updated" if args.update else "new lab", len(log), dest))
    for f in log[:40]:
        print("  ", os.path.relpath(f, dest))
    if len(log) > 40:
        print("   ... (%d more)" % (len(log) - 40))
    if bk:
        print("\n옛 캐릭터 파일(바뀐 것만) 백업: %s" % bk)
    if args.update and getattr(args, "chars", False):     # 캐릭터가 키트와 같아졌으니 Grok 첨부 파일도 그 폴더 것으로 새로
        gf = os.path.join(dest, GROK_FILE)
        open(gf, "w", encoding="utf-8").write(build_grokfile(nk, dest))
        print("Grok 첨부 파일도 새로: %s  (Grok 새 대화에 다시 첨부)" % gf)
    print("\n다음: %s\\만화만들기.bat 더블클릭 -> 1 (Grok 첨부 파일 만들기)" % dest)
    if not args.update:
        print("안내: %s\\실험폴더_안내.md" % dest)


# ================================================================ 명령 등록 (nk_webtoon.add_parser 에서 부름)
def add_parsers(esub, nk, kit):
    a = esub.add_parser("grokfile", help="make Grok_첨부용.md: attach it in Grok and ask in plain Korean -> Grok writes plan.yaml")
    a.set_defaults(func=lambda x: run_grokfile(nk, kit, x))
    a = esub.add_parser("paste", help="save the copied Grok answer as episodes/<ep>/plan.yaml, check it (fix notes -> clipboard)")
    a.add_argument("ep"); a.add_argument("--file", help="read the answer from a file instead of the clipboard")
    a.add_argument("--go", action="store_true", help="make the comic right away (nk ep auto); fix points from the check are shown but do not stop it")
    a.add_argument("--flow", help="your ComfyUI workflow slot for solo cuts (workflows/<name>.json), written into plan.yaml")
    a.set_defaults(func=lambda x: run_paste(nk, kit, x))
    a = esub.add_parser("fix", help="one cut: add/remove tags in the plan, redraw that cut, redo face/style/letters, e.g. nk ep fix ep01 7 --add rain")
    a.add_argument("ep"); a.add_argument("cut", type=int)
    a.add_argument("--add", help='tags to add, comma separated, e.g. "rain, umbrella"')
    a.add_argument("--remove", help='tags to remove, e.g. "smile"')
    a.add_argument("--who", help="two-character cut: change only this person's tags (roles)")
    a.add_argument("--loc", action="store_true", help="change the background tags of this cut's location (shared by every cut in that place)")
    a.add_argument("--nodraw", action="store_true", help="only change the plan/conti, do not draw")
    a.set_defaults(func=lambda x: run_fix(nk, kit, x))
    a = esub.add_parser("cands", help="draw N new-seed candidates of one cut (final stays until you pick): nk ep cands <ep> <cut> --n 3")
    a.add_argument("ep"); a.add_argument("cut", type=int); a.add_argument("--n", default="3")
    a.set_defaults(func=lambda x: run_cands(nk, kit, x))
    a = esub.add_parser("usecand", help="use one candidate as the final cut, then redo letters/review: nk ep usecand <ep> <cut> r02.png")
    a.add_argument("ep"); a.add_argument("cut", type=int); a.add_argument("name")
    a.set_defaults(func=lambda x: run_usecand(nk, kit, x))
    a = esub.add_parser("menu", help="numbered menu for the steps above (double-click 만화만들기.bat)")
    a.set_defaults(func=lambda x: run_menu(nk, kit, x))
    a = esub.add_parser("newlab", help="copy what the comic steps need into a separate test folder (your own lab); --update = new code only")
    a.add_argument("dest", nargs="?", help="folder path, e.g. C:\\comic_lab (asked if missing)")
    a.add_argument("--update", action="store_true", help="only code (nk*.py, bat) and rule docs; keep the lab's presets, characters, episodes")
    a.add_argument("--chars", action="store_true", help="with --update: also replace character files with the kit's (changed old ones backed up in <lab>/_backup/<time>) and rebuild its Grok file")
    a.add_argument("--workshop", action="store_true", help="no path: use the personal folder added in the workshop (asks if several) - 망가메이커_업데이트.bat")
    a.set_defaults(func=lambda x: run_newlab(nk, kit, x))
