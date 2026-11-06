# -*- coding: utf-8 -*-
"""만화 표지 — 페이지형 만화 맨 앞에 표지 한 장 (제목 + 주인공 그림 + 'AI로 제작' 문구 + 작가 줄)

무엇을 하나
  - 페이지형 만화(format: page)의 '말풍선 조립(letter)'이 끝날 때마다 맨 앞에 표지를 끼움:
      episodes/<만화>/out/page_00.png  +  book.pdf 맨 앞 쪽  +  episodes/<만화>/cover/cover.png (표지만 따로)
    세로 웹툰(strip)에는 안 넣음.
  - 표지 그림 = 그 만화의 주인공(제목 캐릭터, 또는 가장 많이 나오는 한두 명)이 정면을 보고 웃는 전연령 그림 한 장.

어떻게
  - 그림은 기존 그리기 기능을 그대로 씀: episodes/<만화>/cover/_home/episodes/cv 에 한 컷짜리 계획표(plan.yaml)를 쓰고
    'nk ep auto cv --from compile --to make' 를 따로 돌림 (NK_HOME = 그 작은 폴더 -> 만화 폴더는 안 건드림).
    혼자 = Anima 혼자 컷 길, 두 명 = 그 단계가 쓰는 두 명 컷 길 (nk_auto 의 make 단계가 고름). ComfyUI 안전장치(safe_graph)도 그대로 지남.
  - 한 번 그리면 cover/art.png 로 남아서 다시 안 그림 (설정이 바뀌거나 variant 를 바꾸거나 --redo 일 때만 다시).
    옛 그림은 지우지 않고 cover/_old 로 옮김.
  - 내가 직접 넣은 cover/art.png 는 절대 덮어쓰지 않음 (art.json 기록과 다른 그림 = 직접 넣은 그림으로 봄).
  - 글자 = 제목(계획표 title, 끝의 (…) 설명은 자동으로 뺌) / 'AI로 제작' 문구 / 작가 줄(기본은 비어 있음).

설정
  - 키트 폴더 cover.yaml (presets.yaml 옆). 만화마다 바꾸려면 episodes/<만화>/cover.yaml 에 바꿀 칸만 적음 (그 값이 우선).
  - enabled: false = 표지 안 넣음 / variant: 1, 2 … = 다른 그림 / art: none = 그림 없이 글자만 / art: cut:12 = 12번 컷 그림을 씀

사용 (선택): nk ep cover <만화> [--redo]
  표지만 다시: 그림을 (필요하면) 그리고 out 안의 page_00.png · book.pdf 만 새로 씀. 페이지(page_01 …)는 안 건드림.

에러가 나면
  - 표지 그림을 못 그려도 말풍선 조립은 그대로 끝남. 그때는 색 바탕 + 글자만 있는 표지가 들어가고
    (전에 그린 그림이 있으면 그 그림), 이유는 episodes/<만화>/cover/draw.log 에 남음.
    ComfyUI 가 꺼져 있었으면 켜고 'nk ep cover <만화>' 또는 말풍선 다시 하기.
  - 표지 자체가 이상하면 cover.yaml 의 enabled: false 로 끄고 'nk ep letter <만화>' -> 예전처럼 표지 없는 책.
"""
import os, sys, re, json, time, glob, shutil, hashlib, subprocess

KIT = os.path.dirname(os.path.abspath(__file__))

DEFAULT = {
    "enabled": True,                         # false 면 표지를 안 넣음
    "title": "",                             # 비우면 계획표 title (끝의 (…) 설명은 자동으로 뺌, '—' 앞은 큰 글씨, 뒤는 작은 글씨)
    "author": "",                            # 비우면 작가 줄 없음. 예: "작가 - 이름"
    "ai_notice": "이 만화는 AI로 제작되었습니다",   # 비우면 안 씀 (공개할 때는 켜 두는 것을 권함)
    "art": "draw",                           # draw = 표지 그림을 그림 / none = 그림 없이 색 바탕 / cut:12 = 12번 컷 그림을 씀
    "variant": 0,                            # 그림이 마음에 안 들면 1, 2, 3 … (다른 시드로 다시 그림)
    "chars": [],                             # 표지에 그릴 캐릭터 키 (계획표 cast 의 키, 최대 2). 비우면 주인공·많이 나오는 한두 명
    "place": "",                             # 배경 태그 (비우면 만화의 첫 장소)
    "shot": "knee",                          # knee(무릎 위) / full(전신) / waist(허리 위)
    "action": "",                            # 동작 태그 (비우면 서서 정면을 보고 웃기)
    "sentence": "",                          # 동작 영어 문장 (비우면 기본 문장)
    "title_color": "#FFFFFF",
    "stroke_color": "#14141E",
    "shade": 0.8,                            # 위·아래 어두운 띠 진하기 (0 = 없음 ~ 1)
    "font": "",                              # 비우면 presets.yaml 의 manga.font
    "comfy_wait": 60,                        # 표지 그릴 때 ComfyUI 를 기다리는 최대 초
    "timeout_min": 40,                       # 표지 그리기 최대 시간 (분)
}
CV_EP = "cv"                                 # 표지 그림을 그리는 작은 작업 폴더의 만화 이름 (cover/_home/episodes/cv)
OFF = ("false", "0", "off", "no", "none", "")


# ------------------------------------------------------------------ 설정
def _ep_dir(kit, ep):
    import nk_webtoon as W
    return W.ep_dir(kit, ep)


def _cover_dir(kit, ep):
    return os.path.join(_ep_dir(kit, ep), "cover")


def art_path(kit, ep):
    return os.path.join(_cover_dir(kit, ep), "art.png")


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def load_cfg(nk, kit, ep):
    """기본값 <- 키트 cover.yaml <- episodes/<만화>/cover.yaml (뒤가 우선). 모르는 칸은 알려 주고 무시"""
    cfg = dict(DEFAULT)
    for p in (os.path.join(kit, "cover.yaml"), os.path.join(_ep_dir(kit, ep), "cover.yaml")):
        if not os.path.exists(p):
            continue
        try:
            y = nk.load_yaml(p)
        except Exception as e:
            print("[note] cover: %s 를 못 읽음 (%s) - 기본값 사용" % (p, " ".join(str(e).split())[:120]))
            continue
        if not isinstance(y, dict):
            print("[note] cover: %s 의 모양이 이상함 (칸: 값 목록이 아님) - 무시" % p)
            continue
        for k, v in y.items():
            if k in DEFAULT:
                cfg[k] = v
            else:
                print("[note] cover: %s 의 '%s' 는 모르는 칸 (무시)" % (os.path.basename(p), k))
    cfg["enabled"] = str(cfg["enabled"]).strip().lower() not in OFF
    cfg["variant"] = _int(cfg.get("variant"), 0)
    return cfg


def split_title(raw, fallback=""):
    """'숲속 모험 — 첫째 날 (시험 v3)' -> ('숲속 모험', '첫째 날'). 끝의 (…) [...] 설명은 모두 뺌"""
    t = " ".join(str(raw or "").split())
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"\s*[\(\[（【][^\)\]）】]*[\)\]）】]\s*$", "", t).strip()
    if not t:
        t = " ".join(str(fallback or "").split())
    parts = re.split(r"\s+[-–—]+\s+|\s*[–—]+\s*", t, maxsplit=1)
    main = parts[0].strip() or t
    sub = parts[1].strip() if len(parts) > 1 else ""
    return main, sub


# ------------------------------------------------------------------ 표지 그림 계획 (한 컷짜리 계획표)
def _cut_keys(ct):
    if ct.get("cast"):
        return [str(r.get("char")) for r in ct["cast"] if r.get("char")]
    k = ct.get("_charkey") or ct.get("char")
    return [str(k)] if k and str(k).lower() != "none" else []


def pick_chars(conti, cfgc):
    """표지에 그릴 캐릭터 (최대 2) -> [(키, 캐릭터 파일 이름)].
    cover.yaml chars 가 있으면 그것, 없으면 많이 나오는 순 (같으면 주인공 char 가 앞)"""
    chars = dict(conti.get("chars") or {})
    if not chars and conti.get("char") and str(conti["char"]).lower() != "none":
        chars = {str(conti["char"]): str(conti["char"])}
    want = [str(x) for x in (cfgc.get("chars") or []) if str(x) in chars][:2]
    if want:
        return [(k, chars[k]) for k in want]
    count = {k: 0 for k in chars}
    for ct in conti.get("cuts") or []:
        for k in _cut_keys(ct):
            if k in count:
                count[k] += 1
    order = {k: i for i, k in enumerate(chars)}
    keys = sorted(chars, key=lambda k: (-count[k], order[k]))
    keys = [k for k in keys if count[k] > 0][:2] or list(chars)[:1]
    main = str(conti.get("char") or "")
    if main in keys and keys[0] != main and count.get(main, 0) >= count.get(keys[0], 0):
        keys.remove(main)
        keys.insert(0, main)
    return [(k, chars[k]) for k in keys]


def build_plan(conti, cfgc, title_main):
    """표지 그림 한 장짜리 plan.yaml (딕셔너리). 전연령: 서서 정면을 보고 웃기만 함"""
    pair = pick_chars(conti, cfgc)
    if not pair:
        return None
    keys = [k for k, _ in pair]
    place = str(cfgc.get("place") or "").strip()
    if not place:
        for _, v in ((conti.get("world") or {}).get("locations") or {}).items():
            place = str((v or {}).get("tags") or "").strip() if isinstance(v, dict) else str(v or "").strip()
            if place:
                break
    if not place:
        place = "indoors, soft lighting"
    duo = len(keys) >= 2
    own = str(cfgc.get("action") or "").strip()
    action = own or ("standing, side by side, looking at viewer, smile" if duo else "standing, looking at viewer, smile")
    sent = " ".join(str(cfgc.get("sentence") or "").split()) or (
        "The two stand side by side facing the viewer, both smiling gently, like a bright book cover illustration." if duo else
        "The character stands facing the viewer with a gentle smile, like a bright book cover illustration.")
    shot = str(cfgc.get("shot") or "knee").strip().lower()
    cut = {"who": keys, "shot": shot, "angle": "eye", "loc": "cover", "action": action, "scene": sent}
    if duo and not own:                      # 두 명: 사람마다 같은 표정·자세 (두 명 컷 길이 사람 자리마다 씀)
        cut["roles"] = {k: "standing, looking at viewer, smile" for k in keys}
    return {"title": "%s (표지)" % title_main, "artist": conti.get("artist") or "", "read": "rtl",
            "cast": {k: f for k, f in pair}, "main": keys[0], "locations": {"cover": place},
            "pages": [{"cuts": [cut]}]}


def _stamp(plan, cfgc):
    """그림을 다시 그려야 하는지 보는 지문 (계획 + variant + art)"""
    blob = json.dumps({"plan": plan, "variant": _int(cfgc.get("variant"), 0), "art": str(cfgc.get("art"))},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _md5(p):
    try:
        return hashlib.md5(open(p, "rb").read()).hexdigest()
    except OSError:
        return ""


def _png_ok(p):
    try:
        from PIL import Image
        with Image.open(p) as im:
            im.verify()
        return True
    except Exception:
        return False


def _read_json(p):
    try:
        return json.load(open(p, encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_record(jp, ap, rec):
    """art.json = 이 프로그램이 만든 그림의 기록 (md5 가 같아야 '내가 만든 그림'으로 봄)"""
    rec = dict(rec, md5=_md5(ap), time=time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)


def is_user_art(kit, ep):
    """cover/art.png 가 직접 넣은 그림인가: 그림이 있고, art.json 이 없거나 md5 가 다름 (= 이 프로그램이 쓴 그림이 아님)"""
    ap = art_path(kit, ep)
    if not (os.path.exists(ap) and _png_ok(ap)):
        return False
    rec = _read_json(os.path.join(_cover_dir(kit, ep), "art.json"))
    return not rec or rec.get("md5") != _md5(ap)


def _archive(path, cdir):
    """덮어쓰지 않고 cover/_old 로 옮김 (지우지 않음)"""
    if not os.path.exists(path):
        return
    od = os.path.join(cdir, "_old")
    os.makedirs(od, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    stamp = time.strftime("%m%d_%H%M%S")
    dst, k = os.path.join(od, "%s_%s%s" % (base, stamp, ext)), 1
    while os.path.exists(dst):                       # 같은 초에 두 번 옮겨도 덮어쓰지 않음
        k += 1
        dst = os.path.join(od, "%s_%s_%d%s" % (base, stamp, k, ext))
    shutil.move(path, dst)


def log_note(kit, ep, msg):
    """cover/draw.log 끝에 한 줄 (왜 그림 없는 표지가 됐는지 나중에 보려고)"""
    try:
        cdir = _cover_dir(kit, ep)
        os.makedirs(cdir, exist_ok=True)
        with open(os.path.join(cdir, "draw.log"), "a", encoding="utf-8") as f:
            f.write("\n[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _stream(cmd, env, cwd, timeout, log, prefix=""):
    """자식 프로세스의 글을 작업 기록에 그대로 흘리면서 cover/draw.log 에도 남김 -> (rc, 전체 글).
    prefix: 줄마다(\\r 로 덮어쓰는 진행 조각마다도) 앞에 붙임 - 작업실 진행 표시가 표지 그리기 줄을 만화 컷으로 착각하지 않게.
    시간 제한은 1초씩 셈. 10초 넘는 틈(PC 절전·작업실 '잠깐 멈춤'으로 얼어 있던 시간)은 안 셈"""
    import threading
    lines = []
    try:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
    except Exception as e:
        out = "[error] %s" % e
        try:
            open(log, "w", encoding="utf-8").write(out)
        except Exception:
            pass
        return -2, out

    def _watch():
        left, last = float(timeout), time.time()
        while p.poll() is None:
            time.sleep(1.0)
            now = time.time()
            if now - last < 10:
                left -= now - last
            last = now
            if left <= 0:
                lines.append("[timeout] %d분이 넘어서 표지 그리기를 멈춤 (cover.yaml timeout_min)" % (timeout // 60))
                try:
                    p.kill()
                except Exception:
                    pass
                return
    threading.Thread(target=_watch, daemon=True).start()
    for raw in iter(p.stdout.readline, b""):
        ln = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        lines.append(ln)
        try:
            if prefix:
                ln = "\r".join(prefix + x.lstrip() for x in ln.split("\r") if x.strip())
            if ln or not prefix:
                print(ln, flush=True)
        except Exception:
            pass
    rc = p.wait()
    out = "\n".join(lines)
    try:
        open(log, "w", encoding="utf-8").write(out)
    except Exception:
        pass
    return rc, out


def _draw(nk, kit, ep, plan, cfgc):
    """한 컷짜리 작은 만화(cover/_home/episodes/cv)를 기존 흐름으로 그림 -> (그림 파일 또는 None, 걸린 초, 마지막 줄들)"""
    import yaml
    cdir = _cover_dir(kit, ep)
    home = os.path.join(cdir, "_home")
    d = os.path.join(home, "episodes", CV_EP)
    os.makedirs(d, exist_ok=True)
    _archive(os.path.join(d, "conti.yaml"), cdir)              # 옛 콘티·그림은 _old 로 (새 계획으로 다시 compile·그리기)
    cutf = os.path.join(d, "cuts", "cut01.png")
    _archive(cutf, cdir)
    with open(os.path.join(d, "plan.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(plan, f, allow_unicode=True, sort_keys=False, width=1000)
    var = _int(cfgc.get("variant"), 0)
    with open(os.path.join(d, "reseed.json"), "w", encoding="utf-8") as f:   # 컷 시드 + 1000 x variant (nk_animacut.cut_seed)
        json.dump({"1": var}, f)
    env = dict(os.environ, NK_HOME=home, NK_COMFY_WAIT=str(_int(cfgc.get("comfy_wait"), 60)), PYTHONIOENCODING="utf-8")
    tmo = max(1, _int(cfgc.get("timeout_min"), 40)) * 60
    print("[cover] 표지 그림 그리는 중 (%s, variant %d) - 처음 한 번만 (최대 %d분, cover.yaml timeout_min). "
          "아래 '[cover]' 줄이 표지 그리는 과정" % (" + ".join(plan["cast"]), var, tmo // 60))
    t0 = time.time()
    rc, out = _stream([sys.executable, "-u", os.path.join(kit, "nk.py"), "ep", "auto", CV_EP, "--from", "compile", "--to", "make"],
                      env, kit, tmo, os.path.join(cdir, "draw.log"), prefix="[cover] ")
    tail = " | ".join([x.strip() for x in out.strip().splitlines() if x.strip()][-3:])
    if os.path.exists(cutf) and _png_ok(cutf):
        return cutf, time.time() - t0, tail
    return None, time.time() - t0, "rc %s: %s" % (rc, tail)


def ensure_art(nk, kit, ep, conti, redo=False, cfgc=None):
    """표지 그림 파일 경로 (없으면 그림). 그림을 못 얻으면 None -> 색 바탕 + 글자 표지.
    직접 넣은 art.png 는 --redo 여도 그대로 씀 (절대 덮어쓰지 않음)"""
    import nk_webtoon as W
    cfgc = cfgc or load_cfg(nk, kit, ep)
    if not cfgc["enabled"]:
        return None
    mode = str(cfgc.get("art") or "draw").strip().lower()
    if mode in ("none", "off", "no", "false"):
        return None
    cdir = _cover_dir(kit, ep)
    os.makedirs(cdir, exist_ok=True)
    ap, jp = art_path(kit, ep), os.path.join(cdir, "art.json")
    if is_user_art(kit, ep):
        print("[cover] art.png (직접 넣은 그림) 사용%s" % (" - 직접 넣은 그림이라 다시 안 그림 (다시 그리게 하려면 art.png 를 다른 곳으로 옮김)" if redo else ""))
        return ap
    old_ok = os.path.exists(ap) and _png_ok(ap)
    tm, _ = split_title(cfgc.get("title") or conti.get("title"), ep)
    if mode.startswith("cut:"):
        plan = {"cut": mode}
    elif mode == "draw":
        plan = build_plan(conti, cfgc, tm)
        if plan is None:
            print("[note] cover: 그릴 캐릭터가 없음 - 글자만 표지")
            log_note(kit, ep, "그릴 캐릭터가 없음 (계획표 cast 가 비었음) - 글자만 표지")
            return None
    else:
        print("[note] cover: art '%s' 를 모름 (draw / none / cut:번호) - 글자만 표지" % mode)
        log_note(kit, ep, "art '%s' 를 모름 - 글자만 표지" % mode)
        return None
    stamp = _stamp(plan, cfgc)
    if old_ok and not redo and _read_json(jp).get("stamp") == stamp:
        print("[cover] art.png 있음 - 다시 안 그림 (variant 를 바꾸거나 nk ep cover %s --redo)" % ep)
        return ap
    if mode.startswith("cut:"):                               # 만화의 한 컷 그림을 그대로
        cid = _int(mode.split(":", 1)[1], -1)
        f = W._final_file(kit, ep, cid) if cid > 0 else ""
        if not (f and os.path.exists(f) and _png_ok(f)):
            print("[note] cover: %s 컷 그림이 아직 없음 - %s" % (mode, "지난 그림 사용" if old_ok else "글자만 표지"))
            log_note(kit, ep, "%s 컷 그림이 아직 없음" % mode)
            return ap if old_ok else None
        _archive(ap, cdir)
        shutil.copy(f, ap)
        _write_record(jp, ap, {"stamp": stamp, "source": mode})
        return ap
    got, secs, why = _draw(nk, kit, ep, plan, cfgc)
    if got:
        _archive(ap, cdir)
        shutil.copy(got, ap)
        _write_record(jp, ap, {"stamp": stamp, "source": "draw", "variant": _int(cfgc.get("variant"), 0),
                               "plan": plan, "secs": int(secs)})
        print("[cover] 그림 완성 (%d초) -> %s" % (secs, ap))
        return ap
    log_note(kit, ep, "표지 그림을 못 그림 (%s)" % why[:400])
    print("[note] cover: 표지 그림을 못 그림 - %s. 이유: %s  (전체 기록 %s)"
          % ("지난 그림을 그대로 씀" if old_ok else "글자만 있는 표지로 만듦", why[:300], os.path.join(cdir, "draw.log")))
    return ap if old_ok else None


# ------------------------------------------------------------------ 표지 조립 (글자·띠)
def _font(path, size):
    """글꼴: 설정 -> 맑은 고딕 굵게 -> 키트에 든 글꼴(fonts/, OFL) -> Noto CJK -> 기본 글꼴"""
    from PIL import ImageFont
    for p in (path, "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
              os.path.join(KIT, "fonts", "BlackHanSans-Regular.ttf"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
        if p and os.path.exists(str(p)):
            try:
                return ImageFont.truetype(str(p), int(size))
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=int(size))
    except Exception:
        return ImageFont.load_default()


def _fs(f, default=10):
    return getattr(f, "size", default)


def _hex(c, default=(255, 255, 255)):
    try:
        c = str(c).strip().lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _fit(d, text, fpath, start, min_size, max_w):
    """max_w 안에 한 줄로 들어가는 가장 큰 글자 크기 (min_size 에서도 넘치면 여러 줄로 나눔) -> (font, [줄])"""
    size = int(start)
    while size >= min_size:
        f = _font(fpath, size)
        if d.textlength(text, font=f) <= max_w:
            return f, [text]
        size -= 4
    f = _font(fpath, min_size)
    lines, cur = [], ""
    for w_ in text.split(" "):
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=f) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    lines.append(cur)
    if any(d.textlength(x, font=f) > max_w for x in lines):      # 띄어쓰기 없는 긴 제목 = 글자 단위로 자름
        lines, cur = [], ""
        for ch in text:
            if d.textlength(cur + ch, font=f) <= max_w or not cur:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return f, lines


def _text(P, xy_center, text, font, fill, stroke, sw):
    """가운데 맞춤 글자 (테두리 + 부드러운 그림자)"""
    from PIL import Image, ImageDraw, ImageFilter
    d = ImageDraw.Draw(P)
    cx, y = xy_center
    x = cx - d.textlength(text, font=font) / 2
    sh = Image.new("L", P.size, 0)
    ImageDraw.Draw(sh).text((x + sw * 0.6, y + sw * 0.9), text, font=font, fill=190, stroke_width=sw, stroke_fill=190)
    sh = sh.filter(ImageFilter.GaussianBlur(max(2, sw)))
    P.paste(Image.new("RGB", P.size, (0, 0, 0)), (0, 0), sh)
    ImageDraw.Draw(P).text((x, y), text, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)


def _band(P, y0, y1, shade, top_dark):
    """위(top_dark=True)나 아래가 어두운 띠 (글자가 그림 위에서 잘 읽히게)"""
    from PIL import Image
    h = max(1, y1 - y0)
    g = Image.linear_gradient("L").resize((P.width, h))           # 위 0 -> 아래 255
    if top_dark:
        g = g.point(lambda v: int(((255 - v) / 255.0) ** 1.5 * 255 * shade))
    else:
        g = g.point(lambda v: int((v / 255.0) ** 1.5 * 255 * shade))
    P.paste(Image.new("RGB", (P.width, h), (8, 8, 16)), (0, y0), g)


def compose(art, W_, H_, title_main, title_sub, cfgc, font_path):
    """표지 한 장 (PIL RGB, W_ x H_). art = PIL 그림 또는 None (그림이 없으면 색 바탕).
    배치: 맨 위 21% = 제목 자리 (그림 윗가장자리를 흐리게 늘려 이어 붙임 -> 제목이 머리를 안 가림), 그 아래 = 그림,
    맨 아래 = 'AI로 제작' 문구 · 작가 줄"""
    from PIL import Image, ImageDraw, ImageFilter
    import nk_webtoon as W
    top_h, fade = int(H_ * 0.21), int(H_ * 0.09)
    if art is not None:
        reg = W._cover_crop(art.convert("RGB"), W_, H_ - top_h + fade, "center", "top")     # 위쪽 기준으로 자름 = 머리 안 잘림
        P = Image.new("RGB", (W_, H_))
        ext = reg.crop((0, 0, W_, 16)).resize((W_, top_h + fade), Image.BILINEAR).filter(ImageFilter.GaussianBlur(48))
        ext = Image.blend(ext, Image.new("RGB", ext.size, (10, 10, 20)), 0.2)
        P.paste(ext, (0, 0))
        mask = Image.new("L", reg.size, 255)
        mask.paste(Image.linear_gradient("L").resize((W_, max(1, fade))), (0, 0))        # 그림이 위쪽에서 서서히 나타남
        P.paste(reg, (0, top_h - fade), mask)
    else:
        g = Image.linear_gradient("L").resize((W_, H_))
        P = Image.composite(Image.new("RGB", (W_, H_), (70, 44, 96)), Image.new("RGB", (W_, H_), (22, 26, 52)), g)
    try:
        shade = max(0.0, min(1.0, float(cfgc.get("shade") or 0)))
    except (TypeError, ValueError):
        shade = 0.8
    if art is not None and shade > 0:
        _band(P, 0, top_h + fade, shade * 0.55, True)
        _band(P, int(H_ * 0.80), H_, shade, False)
    d = ImageDraw.Draw(P)
    fill, stroke = _hex(cfgc.get("title_color")), _hex(cfgc.get("stroke_color"), (20, 20, 30))
    cx, maxw = W_ / 2, W_ * 0.86
    y = H_ * 0.04
    f, lines = _fit(d, title_main, font_path, int(W_ * 0.135), int(W_ * 0.07), maxw)
    sw = max(3, int(_fs(f) * 0.07))
    for ln in lines:
        _text(P, (cx, y), ln, f, fill, stroke, sw)
        y += _fs(f) * 1.18
    if title_sub:
        f2, l2 = _fit(d, title_sub, font_path, int(_fs(f) * 0.45), int(W_ * 0.035), maxw)
        y += _fs(f) * 0.02
        for ln in l2:
            _text(P, (cx, y), ln, f2, fill, stroke, max(2, int(_fs(f2) * 0.07)))
            y += _fs(f2) * 1.2
    # 맨 아래부터 위로: 작가 줄 (있으면) -> AI 문구
    yb = H_ - H_ * 0.045
    author = " ".join(str(cfgc.get("author") or "").split())
    note = " ".join(str(cfgc.get("ai_notice") or "").split())
    if author:
        fa, la = _fit(d, author, font_path, int(W_ * 0.042), int(W_ * 0.025), maxw)
        for ln in reversed(la):
            yb -= _fs(fa) * 1.15
            _text(P, (cx, yb), ln, fa, fill, stroke, max(2, int(_fs(fa) * 0.08)))
        yb -= _fs(fa) * 0.5
    if note:
        fn, ln_ = _fit(d, note, font_path, int(W_ * 0.027), int(W_ * 0.02), maxw)
        for ln in reversed(ln_):
            yb -= _fs(fn) * 1.2
            _text(P, (cx, yb), ln, fn, (232, 232, 238), stroke, max(2, int(_fs(fn) * 0.1)))
    return P


def _save_atomic(im, path, **kw):
    """임시 파일에 쓰고 바꿔치기 (쓰는 도중에 열어도 옛 파일이 열림)"""
    tmp = path + ".tmp"
    im.save(tmp, **kw)
    for i in range(8):                         # 윈도우: 그림 보기·OneDrive 가 파일을 잡고 있으면 잠깐 기다림 (nk_lines 와 같음)
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 7:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.6)


def _page_num(p):
    m = re.match(r"^page_(\d+)\.png$", os.path.basename(p))
    return int(m.group(1)) if m else -1


def add_to_out(nk, kit, ep, conti, out, W_, H_, art_file=None, cfgc=None):
    """표지를 조립해 cover/cover.png 에 저장. out(페이지 PNG 가 든 폴더)이 있으면 page_00.png 를 쓰고
    book.pdf 를 '표지 + 페이지들' 로 다시 만듦 (페이지 PNG 는 안 건드림). art_file = 그림 파일 또는 None(글자만)"""
    from PIL import Image
    import nk_webtoon as W
    cfgc = cfgc or load_cfg(nk, kit, ep)
    if not cfgc["enabled"]:
        return None
    fpath = str(cfgc.get("font") or (W._page_style(nk.load_presets()).get("font") or ""))
    tm, ts = split_title(cfgc.get("title") or conti.get("title"), ep)
    art = None
    if art_file and os.path.exists(art_file) and _png_ok(art_file):
        try:
            art = Image.open(art_file).convert("RGB")
        except Exception:
            art = None
    cv = compose(art, int(W_), int(H_), tm, ts, cfgc, fpath)
    cdir = _cover_dir(kit, ep)
    os.makedirs(cdir, exist_ok=True)
    _save_atomic(cv, os.path.join(cdir, "cover.png"), format="PNG")
    if not out:
        return cv
    pages = sorted((p for p in glob.glob(os.path.join(out, "page_*.png")) if _page_num(p) > 0), key=_page_num)
    _save_atomic(cv, os.path.join(out, "page_00.png"), format="PNG")
    imgs = []
    for p in pages:
        with Image.open(p) as im:
            imgs.append(im.convert("RGB"))
    Image.init()                      # PDF 저장에 JPEG 플러그인이 필요 (page_letter 와 같은 이유)
    _save_atomic(cv, os.path.join(out, "book.pdf"), format="PDF", save_all=True, append_images=imgs, resolution=150)
    print("cover -> %s  (%s%s%s, book.pdf 맨 앞에 넣음)" % (os.path.join(out, "page_00.png"), tm, (" / " + ts) if ts else "",
                                                          "" if art is not None else " [그림 없음: 글자만]"))
    return cv


def attach(nk, kit, ep, conti, out, W_, H_):
    """말풍선 조립(page_letter) 끝에 부름: 그림 준비 + 표지 조립. 무슨 일이 있어도 조립 결과(페이지)는 그대로 둠"""
    cfgc = load_cfg(nk, kit, ep)
    if not cfgc["enabled"]:
        print("[cover] 표지 꺼짐 (cover.yaml enabled: false)")
        return None
    ap = None
    try:
        ap = ensure_art(nk, kit, ep, conti, cfgc=cfgc)
    except KeyboardInterrupt:
        raise
    except BaseException as e:                        # SystemExit 도 (그리기 쪽 오류로 말풍선 단계가 끝나면 안 됨)
        why = " ".join(str(e).split())[:300] or type(e).__name__
        print("[note] cover: 그림 단계 오류 (%s) - 글자만 있는 표지로 만듦" % why)
        log_note(kit, ep, "그림 단계 오류: %s" % why)
    try:
        return add_to_out(nk, kit, ep, conti, out, W_, H_, ap, cfgc)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        if not ap:
            raise
        why = " ".join(str(e).split())[:300] or type(e).__name__
        print("[note] cover: 그림으로 표지를 못 만듦 (%s) - 글자만 있는 표지로 다시" % why)
        log_note(kit, ep, "그림으로 표지 조립 실패: %s" % why)
        return add_to_out(nk, kit, ep, conti, out, W_, H_, None, cfgc)


# ------------------------------------------------------------------ nk ep cover <만화> [--redo]
def refresh(nk, kit, ep, conti, ap, cfgc=None):
    """표지만 다시 조립: cover.png + out(·out_*) 의 page_00.png · book.pdf. 페이지가 아직 없으면 cover.png 만"""
    import nk_webtoon as W
    st = W._page_style(nk.load_presets())
    edir = W.ep_dir(kit, ep)
    done = 0
    for out in [os.path.join(edir, "out")] + sorted(glob.glob(os.path.join(edir, "out_*"))):
        if os.path.isdir(out) and any(_page_num(p) > 0 for p in glob.glob(os.path.join(out, "page_*.png"))):
            add_to_out(nk, kit, ep, conti, out, st["width"], st["height"], ap, cfgc)
            done += 1
    if not done:
        add_to_out(nk, kit, ep, conti, None, st["width"], st["height"], ap, cfgc)
        print("아직 만화 페이지(out)가 없어서 표지만 만들었음 -> %s" % os.path.join(_cover_dir(kit, ep), "cover.png"))
    return done


def run(nk, kit, args):
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    if conti.get("format") != "page":
        print("[note] 표지는 페이지형 만화(format: page)에만 넣음")
        return
    cfgc = load_cfg(nk, kit, args.ep)
    if not cfgc["enabled"]:
        print("표지가 꺼져 있음 (cover.yaml enabled: false). 이미 넣은 표지를 빼려면 nk ep letter %s" % args.ep)
        return
    ap = ensure_art(nk, kit, args.ep, conti, redo=bool(getattr(args, "redo", False)), cfgc=cfgc)
    refresh(nk, kit, args.ep, conti, ap, cfgc)


def add_parser(esub, nk, kit):
    a = esub.add_parser("cover", help="make/refresh the cover (page_00.png + book.pdf first page), e.g. nk ep cover ep01 [--redo]")
    a.add_argument("ep")
    a.add_argument("--redo", action="store_true", help="draw the cover picture again (old one kept in cover/_old; your own art.png is never replaced)")
    a.set_defaults(func=lambda x: run(nk, kit, x))
