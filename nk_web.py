# -*- coding: utf-8 -*-
"""
nk_web.py - 만화 작업실 화면

왜
  - 엔진(nk 명령)은 그대로 두고 화면만 얇게 (엔진과 화면 분리).

끄기: 검은 창 닫기.
  - 이 PC 안에서만 열림 (127.0.0.1). 다른 기기·인터넷에서는 못 들어옴.
  - 작업 줄(_remote\\inbox)은 이 화면이 직접 한 번에 하나씩 돌림 (nk_remote.py 가 있으면 그것을 새 창으로 켬).
  - '지금 작업 멈추기'로 작업을 멈추면, 그 작업은 줄 뒤에 다시 넣음 (auto 는 다시 돌리면 이어서 함).

  - 화면에서 폴더를 추가하면 그 폴더에 만화·결과를 씀 (환경 변수 NK_HOME -> nk.data_root).
    GPU가 겹치지 않게: 개인 작업이 있으면 키트 작업 줄을 _remote\\held 로 잠시 옮기고
    지금 도는 작업이 끝나면 개인 작업을 돌리고, 끝나면 되돌려 놓음.
  - ComfyUI: 결과를 공유 output 폴더에 저장하지 않음(PreviewImage = ComfyUI 임시 폴더), input 에 올린 그림은 작업 끝에 지움.
  - 폴더 목록은 %APPDATA%\\nk_workshop.json 에 저장 (키트 폴더 밖)."""
import os
import sys
import re
import json
import time
import glob
import shutil
import hashlib
import threading
import subprocess
import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8765
STEPS = ["write", "compile", "check", "layout", "make", "propfix", "facefix", "compose", "unify", "story", "handfix", "backfix",
         "restyle", "letter", "review"]
EP_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
FLOW_RE = re.compile(r"^[A-Za-z0-9_\-\uac00-\ud7a3.]{1,60}$")   # 워크플로 파일 이름 (한글 가능)
JOB_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,80}\.json$")
IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".pdf": "application/pdf"}
ALIVE_SECS = 90          # 우체통 status.json 이 이보다 오래되면 꺼진 것으로 봄 (우체통은 20초마다 씀)
CFG_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "nk_workshop.json")
# 열쇠가 있는데 틀리면 = 작업실을 다시 켜기 전에 열어 둔 옛 화면 -> 화면이 스스로 새로 고침 (stale).
PAGE_KEY = __import__("secrets").token_hex(16)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _kill_tree(proc):
    """자식·손자까지 끔"""
    if os.name == "nt":
        subprocess.call(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.poll() is None:
        proc.kill()


QUICK_KINDS = ("fix", "cands", "usecand", "partfix", "letter")


def _jobname(kind, ep, prio=True):
    ts = time.strftime("%y%m%d_%H%M%S") + "%03d" % (int(time.time() * 1000) % 1000)   # 같은 초에 두 개 넣어도 안 겹치게
    return "a%s%s_%s%s.json" % ("0" if (prio and kind in QUICK_KINDS) else "", ts, kind, ("_" + ep) if ep else "")


_FLOW_OK = {}


def _is_flow(p):
    """'NK prompt' 칸이 있는 API 형식 워크플로만 목록에"""
    k = (p, os.path.getmtime(p))
    if k not in _FLOW_OK:
        try:
            d = json.load(open(p, encoding="utf-8"))
            _FLOW_OK[k] = isinstance(d, dict) and "nodes" not in d and any(
                isinstance(v, dict) and str((v.get("_meta") or {}).get("title", "")).lower().replace(":", " ").startswith(("nk prompt", "nk  prompt"))
                for v in d.values())
        except Exception:
            _FLOW_OK[k] = False
    return _FLOW_OK[k]


class App:
    def __init__(self, nk, kit):
        self.nk, self.kit = nk, kit
        self.box = os.path.join(kit, "_remote")
        self.inbox = os.path.join(self.box, "inbox")
        self.done = os.path.join(self.box, "done")
        self.logs = os.path.join(self.box, "logs")
        self.held = os.path.join(self.box, "held")
        self.busy_mark = os.path.join(self.box, "PRIVATE_BUSY")
        self.front_path = os.path.join(self.box, "front.json")      # '바로 만들기'로 앞에 세운 작업 순서 [{name, root}]
        self.cleared_path = os.path.join(self.box, "cleared.json")
        for d in (self.inbox, self.done, self.logs):
            os.makedirs(d, exist_ok=True)
        self.has_runner = os.path.exists(os.path.join(kit, "nk_remote.py"))
        self._svc = {"t": 0, "v": {}}
        self.gpu = threading.Lock()                 # 우체통 없는 폴더: 화면의 두 일꾼이 GPU를 번갈아 씀
        self.worker = None
        self.folders = self._load_folders()
        self.priv = PrivateWorker(self)
        self.labels = Labels(self)
        self.ab = ABSets(self)

    def _load_folders(self):
        try:
            return [f for f in json.load(open(CFG_PATH, encoding="utf-8")).get("folders", []) if isinstance(f, str)]
        except Exception:
            return []

    def _save_folders(self):
        try:
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump({"folders": self.folders}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def roots(self):
        out = [{"id": "0", "path": self.kit, "name": "키트 폴더", "private": False}]
        for i, f in enumerate(self.folders, 1):
            out.append({"id": str(i), "path": f, "name": "개인: " + f, "private": True})
        return out

    def base(self, rid):
        rid = str(rid or "0")
        if rid == "0":
            return self.kit
        try:
            return self.folders[int(rid) - 1]
        except (ValueError, IndexError):
            raise ValueError("모르는 폴더 번호: %s" % rid)

    def add_folder(self, path):
        p = str(path or "").strip().strip('"')
        if not p or not os.path.isabs(p):
            raise ValueError("전체 경로를 적어 주세요 (예: C:\\my_comics)")
        rp = os.path.normcase(os.path.realpath(p))
        for bad in (self.kit, getattr(self.nk, "COMFY_SHARED", "")):
            if bad:
                rb = os.path.normcase(os.path.realpath(bad))
                if rp == rb or rp.startswith(rb + os.sep) or rb.startswith(rp + os.sep):
                    raise ValueError("이 폴더는 키트 폴더와 겹침 - 다른 곳을 골라 주세요: %s" % bad)
        for sub in ("episodes", "runs", "_nk"):
            os.makedirs(os.path.join(p, sub), exist_ok=True)
        same = lambda f: os.path.normcase(os.path.realpath(str(f).strip().strip('"'))) == rp
        if not any(same(f) for f in self.folders):
            self.folders.append(p)
            self._save_folders()
        return self.roots()

    def remove_folder(self, rid):
        i = int(rid) - 1
        if not 0 <= i < len(self.folders):
            raise ValueError("모르는 폴더")
        self.folders.pop(i)          # 목록에서만 뺌 (폴더·그림은 그대로)
        self._save_folders()
        return self.roots()

    # ------------------------------------------------------------ 상태
    def runner_status(self):
        p = os.path.join(self.box, "status.json")
        try:
            s = json.load(open(p, encoding="utf-8"))
            age = max(0.0, time.time() - os.path.getmtime(p))   # Windows: 방금 쓴 파일 시각이 지금보다 살짝 앞설 때가 있음
        except Exception:
            s, age = {}, 1e9
        s["alive"] = age < ALIVE_SECS and s.get("runner") not in ("stopped",)
        s["age"] = int(age) if age < 1e8 else None
        if s.get("job") and s.get("elapsed_s") is not None and age < ALIVE_SECS:
            s["elapsed_s"] = int(s["elapsed_s"] + age)
        try:
            s["progress"] = self.progress(s) if s.get("job") else None
        except Exception:
            s["progress"] = None
        s["mode"] = "runner" if self.has_runner else "web"
        if not self.has_runner and self.worker:
            s.update(self.worker.state())
            s["alive"] = True
        return s

    SEC_PER_CUT, SEC_TAIL = 85, 60
    SEC_DUO_LORA, SEC_SOLO_LORA, SEC_OTHER, SEC_COMPILE = 175, 50, 30, 5
    PART = {"duo": [("base", 25), ("mask", 25), ("paint", 105), ("face", 20)], "lora": [("draw", 30), ("face", 20)], "other": [("draw", 30)]}

    def _lora_files(self):
        out = set()
        for f in glob.glob(os.path.join(os.environ.get("NK_CHARS") or os.path.join(self.kit, "characters"), "*.yaml")):
            try:
                if (self.nk.load_yaml(f) or {}).get("anima_lora"):
                    out.add(os.path.splitext(os.path.basename(f))[0])
            except Exception:
                pass
        return out

    def _face_on(self, plan):
        """얼굴 다듬기를 하나: 계획표의 LoRA 캐릭터 파일에 anima_face_pass: false 면 안 함"""
        for fn in (plan.get("cast") or {}).values():
            try:
                d = self.nk.load_yaml(os.path.join(os.environ.get("NK_CHARS") or os.path.join(self.kit, "characters"), "%s.yaml" % fn)) or {}
            except Exception:
                continue
            if d.get("anima_lora") and str(d.get("anima_face_pass", True)).strip().lower() not in ("false", "0", "off", "no", "none"):
                return True
        return False

    def _cuts_secs(self, plan, skip=()):
        """계획표(AI 답) -> 컷마다 예상 초 (그린 컷 번호 skip 은 뺌)"""
        lora = self._lora_files()
        fsec = 0 if self._face_on(plan) else 20
        cast = plan.get("cast") or {}
        lk = {k for k, v in cast.items() if str(v) in lora}
        tot, n, i = 0, 0, 0
        for pg in plan.get("pages") or []:
            for c in pg.get("cuts") or []:
                i += 1
                if i in skip:
                    continue
                who = [str(w) for w in (c.get("who") or [])]
                has = any(w in lk for w in who)
                tot += (self.SEC_DUO_LORA - fsec) if (has and len(who) >= 2) else ((self.SEC_SOLO_LORA - fsec) if has else self.SEC_OTHER)
                n += 1
        return tot + (10 + 4.5 * n if n else 0), n          # + 말풍선·쪽 + 검토(머리 수)

    def cut_kinds(self, ep, rid="0"):
        """[(컷 번호, 'duo'|'lora'|'other')] — 계획표 who + LoRA 캐릭터 (컷 번호 = 계획표 순서)"""
        d = self.ep_dir(ep, rid)
        pp = os.path.join(d, "plan.yaml")
        if not os.path.exists(pp):
            return []
        plan = self.nk.load_yaml(pp)
        lora = self._lora_files()
        lk = {k for k, v in (plan.get("cast") or {}).items() if str(v) in lora}
        out, i = [], 0
        for pg in plan.get("pages") or []:
            for c in pg.get("cuts") or []:
                i += 1
                who = [str(w) for w in (c.get("who") or [])]
                has = any(w in lk for w in who)
                out.append((i, "duo" if (has and len(who) >= 2) else ("lora" if has else "other")))
        return out

    def detail(self, jid, rid="0"):
        """도는 만화 작업의 기록을 읽어 단계·컷마다 진행"""
        base = self.logs if str(rid) == "0" else os.path.join(self.base(rid), "_nk", "logs")
        lp = os.path.join(base, str(jid) + ".log")
        if not os.path.exists(lp):
            return None
        txt = open(lp, "rb").read().decode("utf-8", "replace")
        head = txt.split("\n", 1)[0].strip()
        m = re.match(r"^# nk ep (auto|paste) (\S+)", head)
        if not m:
            return None
        ep = m.group(2)
        kinds = self.cut_kinds(ep, rid)
        face_on = True
        try:
            face_on = self._face_on(self.nk.load_yaml(os.path.join(self.ep_dir(ep, rid), "plan.yaml")) or {})
        except Exception:
            pass
        if not kinds:
            return {"ep": ep, "title": ep, "cuts": [], "steps": [], "frac": 0.02, "remain_s": None}
        try:
            title = str((self.nk.load_yaml(os.path.join(self.ep_dir(ep, rid), "plan.yaml")) or {}).get("title") or ep)
        except Exception:
            title = ep
        K = dict(kinds)
        st = {c: {"stage": "wait", "t": 0.0} for c, _ in kinds}     # stage: wait draw base mask paint face done skip
        phase, face_set, letter, review, rv = None, set(), "wait", "wait", (0, 0)
        frags = []
        for line in txt.splitlines():
            frags += [x for x in re.split(r"(?=   \.\.\. )", line) if x.strip()]
        for f in frags:
            g = f.strip()
            if re.match(r"^animamake \S+: \d+ cuts \|", g):
                phase = "solo"; continue
            if re.match(r"^regionlora \S+ -> \S+: \d+ cuts", g):
                phase = "duo"; continue
            if re.match(r"^animafix \S+: \d+ cuts", g):
                phase = "face"; continue
            if g.startswith("==== [letter]"):
                phase = "letter"; letter = "done" if "done" in g else "now"; continue
            if g.startswith("==== [review]"):
                phase = "review"; review = "done" if "done" in g else "now"; continue
            if g.startswith("pages ->"):
                letter = "done"; continue
            mm = re.match(r"^== cut (\d+) ", g)
            if mm and phase == "solo" and int(mm.group(1)) in st:
                st[int(mm.group(1))].update(stage="draw", t=0.0); continue
            mm = re.match(r"^\[skip\] .*?cut ?0?(\d+)", g)
            if mm and int(mm.group(1)) in st:
                c = int(mm.group(1))
                st[c]["stage"] = "done" if "exists" in g else "skip"; continue
            mm = re.match(r"^\.\.\. cut(\d+) base (\d+)s", g)
            if mm and int(mm.group(1)) in st:
                st[int(mm.group(1))].update(stage="base", t=float(mm.group(2))); continue
            mm = re.match(r"^\.\.\. cut(\d+) (\d+)s", g)
            if mm and int(mm.group(1)) in st:
                c, t = int(mm.group(1)), float(mm.group(2))
                if phase == "solo":
                    st[c].update(stage="draw", t=t)
                elif phase == "duo":
                    st[c].update(stage="paint", t=t)
                elif phase == "face":
                    st[c].update(stage="face", t=t)
                continue
            mm = re.search(r"saved .*[\\/]cuts[\\/]cut(\d+)\.png \(", g)
            if mm and phase == "solo" and int(mm.group(1)) in st:
                c = int(mm.group(1))
                st[c].update(stage="done" if (K[c] == "other" or not face_on) else "drawn", t=0.0); continue
            mm = re.match(r"^cut(\d+): (mask by|partner)", g)
            if mm and int(mm.group(1)) in st:
                st[int(mm.group(1))].update(stage="mask", t=0.0); continue
            mm = re.match(r"^cut(\d+) -> .*cut\d+\.png \(", g)
            if mm and phase == "duo" and int(mm.group(1)) in st:
                st[int(mm.group(1))].update(stage="drawn" if face_on else "done", t=0.0); continue
            mm = re.match(r"^\[\d+/\d+\] cut(\d+)__", g)
            if mm and phase == "face":
                face_set.add(int(mm.group(1))); continue
            mm = re.match(r"^cut(\d+) box .* \(\d+ s\)", g)
            if mm and int(mm.group(1)) in st:
                st[int(mm.group(1))].update(stage="done", t=0.0); continue
            mm = re.match(r"^\[(\d+)/(\d+)\] h\d+_cut", g)
            if mm and phase == "review":
                rv = (int(mm.group(1)), int(mm.group(2))); continue
            if g.startswith("==== [make] done") or g.startswith("==== [make] failed"):
                for c in st:
                    if st[c]["stage"] == "drawn" and c not in face_set:
                        st[c]["stage"] = "done"
        # 컷마다 진행 (0~1) = 단계 무게의 합
        cuts, done_s, tot_s = [], 0.0, 0.0
        for c, k in kinds:
            parts = [x for x in self.PART[k] if face_on or x[0] != "face"]
            w = float(sum(x for _, x in parts))
            order = [n for n, _ in parts]
            stg, t = st[c]["stage"], st[c]["t"]
            if stg in ("done", "skip"):
                fr = 1.0
            elif stg == "wait":
                fr = 0.0
            else:
                key = {"drawn": "face"}.get(stg, stg)
                if stg == "draw" and "draw" not in order:
                    key = "paint"
                i = order.index(key) if key in order else 0
                before = sum(x for _, x in parts[:i])
                cur = parts[i][1]
                fr = (before + (0 if stg == "drawn" else min(t, cur * 0.95))) / w
                if stg == "mask":
                    fr = (before + cur * 0.5) / w
            ip = os.path.join(self.ep_dir(ep, rid), "cuts", "cut%02d.png" % c)
            cuts.append({"id": c, "kind": k, "stage": stg, "frac": round(fr, 3),
                         "img": ("episodes/%s/cuts/cut%02d.png" % (ep, c)) if os.path.exists(ip) else None,
                         "mtime": int(os.path.getmtime(ip)) if os.path.exists(ip) else 0})
            done_s += fr * w; tot_s += w
        n = len(kinds)
        tail = 10 + 4.5 * n
        tail_done = (6 if letter == "done" else 0) + (4.5 * n if review == "done" else (4.5 * rv[0] if rv[1] else 0))
        tot_s += tail + self.SEC_COMPILE; done_s += tail_done + self.SEC_COMPILE
        cnt = lambda ks, stages: sum(1 for x in cuts if x["kind"] in ks and x["stage"] in stages)
        solo_n, duo_n = sum(1 for _, k in kinds if k != "duo"), sum(1 for _, k in kinds if k == "duo")
        face_n = sum(1 for _, k in kinds if k != "other") if face_on else 0
        solo_d = sum(1 for x in cuts if x["kind"] != "duo" and x["stage"] in ("drawn", "face", "done", "skip"))
        duo_d = sum(1 for x in cuts if x["kind"] == "duo" and x["stage"] in ("drawn", "face", "done", "skip"))
        face_d = sum(1 for x in cuts if x["kind"] != "other" and x["stage"] in ("done", "skip"))

        def stt(d, t, now):
            return "done" if t and d >= t else ("now" if now else "wait")
        steps = [
            {"name": "계획표 검사", "state": "done"},
            {"name": "혼자·배경 컷 그리기", "n": solo_d, "of": solo_n, "state": stt(solo_d, solo_n, phase == "solo")},
            {"name": "두 명 컷 그리기", "n": duo_d, "of": duo_n, "state": stt(duo_d, duo_n, phase == "duo")},
            {"name": "LoRA 캐릭터 얼굴 다듬기", "n": face_d, "of": face_n, "state": stt(face_d, face_n, phase == "face")},
            {"name": "말풍선·쪽 합치기", "state": letter},
            {"name": "검토 (머리 수)", "n": rv[0], "of": rv[1], "state": review},
        ]
        steps = [x for x in steps if not ((x["name"] == "두 명 컷 그리기" and not duo_n) or (x["name"] == "LoRA 캐릭터 얼굴 다듬기" and not face_n))]
        return {"ep": ep, "root": str(rid), "title": title, "cuts": cuts, "steps": steps, "frac": round(done_s / tot_s, 3) if tot_s else 0,
                "remain_s": int(max(0, tot_s - done_s)), "total_s": int(tot_s)}

    def estimate(self, args, rid="0"):
        """작업 줄 쪽지 하나 -> (예상 초 또는 None, 쉬운 이름). 예상은 실측 평균 (추정)"""
        a = [str(x) for x in (args or [])]
        kind = a[1] if len(a) > 1 else ""
        ep = a[2] if len(a) > 2 and EP_RE.match(a[2]) else ""
        KO = {"paste": "새 만화", "auto": "만들기", "fix": "컷 다시 그리기", "cands": "후보 3장", "usecand": "후보로 바꾸기",
              "letter": "말풍선 다시", "aifile": "AI 첨부 파일", "animatest": "시험", "trainanima": "학습",
              "regionlora": "두 명 컷 영역 LoRA", "animamake": "Anima 그리기", "animafix": "LoRA 캐릭터 다시 그리기"}
        name = ((ep + " ") if ep else "") + KO.get(kind, kind or "작업")
        try:
            if kind == "paste":
                fp = a[a.index("--file") + 1] if "--file" in a else ""
                import nk_plan
                plan, _ = nk_plan._extract_yaml(open(fp, encoding="utf-8-sig").read())
                if "--go" not in a:
                    return self.SEC_COMPILE, name + " (검사만)"
                t, n = self._cuts_secs(plan)
                return self.SEC_COMPILE + t + self.SEC_TAIL, "%s (%d컷)" % (name, n)
            if kind == "auto" and ep:
                d = self.ep_dir(ep, rid)
                pp = os.path.join(d, "plan.yaml")
                if os.path.exists(pp):
                    plan = self.nk.load_yaml(pp)
                    drawn = {i for i in range(1, 200) if os.path.exists(os.path.join(d, "cuts", "cut%02d.png" % i))}
                    t, n = self._cuts_secs(plan, drawn)
                    return t + self.SEC_TAIL, "%s (남은 컷 %d)" % (name, n)
                return None, name
            if kind == "fix":
                return 150 + self.SEC_TAIL, name
            if kind == "cands":
                n = int(a[a.index("--n") + 1]) if "--n" in a else 3
                return n * 130, name
            if kind in ("usecand", "letter"):
                return self.SEC_TAIL, name
            if kind == "aifile":
                return 5, name
            if kind == "trainanima":
                return 1400, name
            if kind == "animatest" and len(a) > 2:
                y = self.nk.load_yaml(os.path.join(self.kit, a[2]))
                seeds = len(a[a.index("--seeds") + 1].split(",")) if "--seeds" in a else 1
                return 27 * len(y.get("prompts") or []) * max(1, len(y.get("variants") or [])) * seeds, name
        except Exception:
            pass
        return None, name

    def plan_view(self, st, pv, queue):
        """큰 진행 창: 지금 작업(남은 초) + 기다리는 작업(예상 초) + 전부 끝나는 데 남은 초 + 이번 묶음 진행률"""
        items = []
        now = time.time()
        cur = []
        if pv.get("job"):
            cur.append((pv["job"], pv.get("root") or "0", True, pv.get("elapsed_s") or 0))
        if st.get("alive") and st.get("job"):
            cur.append((st["job"], "0", False, st.get("elapsed_s") or 0))
        for jid, rid, private, el in cur:
            args = self._job_args(jid, rid)
            before = 0                              # 끊었다 이어 온 만화면 앞서 쓴 시간도 (타이머 = 제작 시작 뒤 총 걸린 시간)
            try:
                jd = self.done if str(rid) == "0" else os.path.join(self.base(rid), "_nk", "done")
                before = int(json.load(open(os.path.join(jd, str(jid) + ".job.json"), encoding="utf-8")).get("elapsed_before") or 0)
            except Exception:
                pass
            est, name = self.estimate(args, rid)
            pg = None
            try:
                pg = self.progress({"job": jid}, rid)
            except Exception:
                pass
            det = None
            try:
                det = self.detail(jid, rid)
            except Exception:
                det = None
            if det and det.get("remain_s") is not None:
                remain = det["remain_s"]
            elif pg and pg.get("eta_s") is not None:
                remain = pg["eta_s"]
            elif est is not None:
                remain = max(30, est - el)
            else:
                remain = None
            if det and det.get("title"):
                name = "%s · %s" % (name, det["title"])
            items.append({"name": name, "job": jid, "private": private, "running": True, "elapsed_s": el, "elapsed_total_s": before + el,
                          "remain_s": remain, "est_s": est, "progress": pg, "detail": det, "root": str(rid)})
        paused = []
        for q in queue:
            est, name = self.estimate(q.get("args"), q.get("root") or "0")
            it = {"name": name, "job": q.get("name"), "private": bool(q.get("private")), "running": False,
                  "remain_s": est, "est_s": est, "held": q.get("held"), "front": q.get("front"), "root": str(q.get("root") or "0")}
            if q.get("paused"):
                paused.append(dict(it, paused=True))      # 멈춘 작업: 남은 시간·작업 수에 안 넣음
            else:
                items.append(it)
        known = [x["remain_s"] for x in items if x["remain_s"] is not None]
        total = sum(known)
        unknown = sum(1 for x in items if x["remain_s"] is None)
        # 이번 묶음 = 지금·기다리는 작업 중 가장 먼저 넣은 것 이후에 끝난 작업들 (쪽지 이름 a260930_171651003 = 넣은 시각)
        starts = []
        for x in items:
            m = re.match(r"^a0?(\d{6})_(\d{6})", str(x["job"]))
            if m:
                try:
                    starts.append(time.mktime(time.strptime(m.group(1) + m.group(2), "%y%m%d%H%M%S")))
                except Exception:
                    pass
        for x in items:
            if x["running"] and x.get("elapsed_s"):
                starts.append(now - float(x["elapsed_s"]))
        done_s, done_items = 0, []
        at = self.cleared_at()
        if starts:
            b0 = min(starts)
            for r in self.recent(40) + self.priv.recent(20):
                try:
                    t0 = time.mktime(time.strptime(str(r.get("start"))[:19], "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    continue
                if t0 >= b0 - 5 and r.get("secs") is not None:
                    done_s += int(r["secs"] or 0)
                    _, nm = self.estimate(r.get("args"), "0")
                    done_items.append({"name": nm, "job": r.get("id"), "done": True, "ok": r.get("rc") == 0,
                                       "secs": r.get("secs"), "end": str(r.get("end") or "")[11:16], "error": r.get("error") or "",
                                       "private": bool(r.get("private")), "hid": _hid(r, at)})      # hid: 목록에서만 숨김 (진행 %는 그대로 셈)
            done_items.sort(key=lambda x: x["end"])
        run_el = sum(x.get("elapsed_s") or 0 for x in items if x["running"])
        frac = (done_s + run_el) / float(done_s + run_el + total) if (done_s + run_el + total) else None
        return {"items": items, "paused": paused, "done": done_items, "total_remain_s": total, "unknown": unknown, "batch_frac": frac,
                "finish_at": time.strftime("%H:%M", time.localtime(now + total)) if items else None}

    def _job_args(self, jid, rid="0"):
        """도는 작업의 명령 (기록 첫 줄 '# nk ep ...')"""
        base = self.logs if str(rid) == "0" else os.path.join(self.base(rid), "_nk", "logs")
        try:
            with open(os.path.join(base, str(jid) + ".log"), "rb") as f:
                head = f.readline().decode("utf-8", "replace").strip()
            if head.startswith("# nk "):
                import shlex
                return shlex.split(head[5:], posix=False)
        except Exception:
            pass
        return []

    def progress(self, s, rid="0"):
        jid = str(s.get("job") or "")
        lp = os.path.join(self.logs if str(rid) == "0" else os.path.join(self.base(rid), "_nk", "logs"), jid + ".log")
        if not os.path.exists(lp):
            return None
        with open(lp, "rb") as f:
            head = f.readline().decode("utf-8", "replace")
            f.seek(max(0, os.path.getsize(lp) - 65536))
            tail = f.read().decode("utf-8", "replace")
        m = re.match(r"^# nk (ep (auto|paste|fix|cands) (\S+).*)$", head.strip())
        if not m:
            return None
        ep = m.group(3)
        d = self.ep_dir(ep, rid)
        steps = re.findall(r"==== \[(\w+)\]", tail)
        cp = os.path.join(d, "conti.yaml")
        total = drawn = None
        if os.path.exists(cp):
            conti = self.nk.load_yaml(cp)
            ids = [int(c.get("id", 0)) for pg in conti.get("pages") or [] for c in pg.get("cuts") or []]
            total = len(ids)
            drawn = sum(1 for i in ids if os.path.exists(os.path.join(d, "cuts", "cut%02d.png" % i)))
        step = steps[-1] if steps else None
        eta = None
        if total and m.group(2) in ("auto", "paste") and step in (None, "write", "compile", "check", "layout", "make"):
            eta = (total - drawn) * self.SEC_PER_CUT + self.SEC_TAIL
        elif step in ("story", "letter", "review"):
            eta = self.SEC_TAIL
        return {"ep": ep, "kind": m.group(2), "step": step, "drawn": drawn, "total": total, "eta_s": eta}

    def services(self):
        if time.time() - self._svc["t"] < 10:
            return self._svc["v"]
        v = {"comfy": None, "ollama": False}
        for port in (8188, 8189, 8000, 8190, 8191):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/system_stats" % port, timeout=1).read()
                v["comfy"] = port
                break
            except Exception:
                continue
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1).read()
            v["ollama"] = True
        except Exception:
            pass
        self._svc = {"t": time.time(), "v": v}
        return v

    def queue(self):
        out = []
        for d, held, paused in ((self.inbox, False, False), (self.held, True, False), (os.path.join(self.box, "paused"), False, True)):
            if not os.path.isdir(d):
                continue
            for n in sorted(os.listdir(d)):
                if not n.endswith(".json"):
                    continue
                try:
                    j = json.load(open(os.path.join(d, n), encoding="utf-8"))
                except Exception:
                    j = {}
                out.append({"name": n, "args": j.get("args"), "note": j.get("note", ""), "mine": n.startswith("a"),
                            "held": held, "paused": paused, "root": "0", "elapsed_before": j.get("elapsed_before")})
        out.sort(key=lambda x: (x["paused"], x["name"]))          # 도는 줄은 이름(넣은 시각) 순서, 멈춘 작업은 맨 끝
        return out

    def ordered_queue(self):
        """화면·예상 시간용 순서: 앞줄(바로 만들기) -> 개인 작업 -> 키트 작업, 멈춘 작업은 맨 끝"""
        q = self.priv.queue_view() + self.queue()
        fr = self.front_load()
        pos = {(x["name"], str(x.get("root") or "0")): i for i, x in enumerate(fr)}

        def key(x):
            k = (x["name"], str(x.get("root") or "0"))
            return (1 if x.get("paused") else 0, 0 if k in pos else 1, pos.get(k, 0))
        q = sorted(q, key=key)          # 안정 정렬: 같은 묶음 안에서는 원래 순서 (개인 먼저, 이름 순)
        for x in q:
            x["front"] = (x["name"], str(x.get("root") or "0")) in pos
        return q

    def recent(self, k=12):
        fs = sorted(glob.glob(os.path.join(self.done, "*.result.json")), key=os.path.getmtime, reverse=True)[:k]
        out = []
        for f in fs:
            try:
                r = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            x = {k2: r.get(k2) for k2 in ("id", "args", "rc", "killed", "start", "end", "secs", "error", "note")}
            if x.get("rc") not in (0, None) and not x.get("error") and not x.get("killed"):
                x["error"] = _fail_reason(os.path.join(self.logs, str(x.get("id")) + ".log"))
            out.append(x)
        return out

    def log_tail(self, jid, n=80, logs=None):
        if not re.match(r"^[A-Za-z0-9_\-.]{1,80}$", jid or ""):
            return []
        p = os.path.join(logs or self.logs, jid + ".log")
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 12000))
                return f.read().decode("utf-8", "replace").replace("\r", "\n").splitlines()[-n:]
        except Exception:
            return []

    # ------------------------------------------------------------ 에피소드
    def ep_dir(self, ep, rid="0"):
        return os.path.join(self.base(rid), "episodes", ep)

    def interpret(self, b):
        """그림을 그리는 중이면 CPU 로 (그래픽 카드 안 겹치게)"""
        import nk_editcmd
        rid, ep, cid = str(b.get("root") or "0"), str(b.get("ep") or ""), int(b.get("cut"))
        text = str(b.get("text") or "").strip()
        if not EP_RE.match(ep) or not text or len(text) > 500:
            raise ValueError("요청 글이 없거나 너무 김")
        pp = os.path.join(self.ep_dir(ep, rid), "plan.yaml")
        if not os.path.exists(pp):
            raise ValueError("이 만화엔 계획표(plan.yaml)가 없어서 말로 수정할 수 없음")
        busy = bool((self.runner_status() or {}).get("job")) or bool(self.priv.state().get("job"))
        try:
            out = nk_editcmd.interpret(self.nk, self.kit, pp, cid, text, cpu=busy)
        except RuntimeError as e:
            return {"error": str(e)}
        return {k: out.get(k) for k in ("action", "human", "job", "warnings", "note", "secs")}

    def test_eps(self):
        """작업실 목록에서 기본으로 숨김"""
        try:
            return {l.split("#")[0].strip() for l in open(os.path.join(self.kit, "episodes", "_tests.txt"), encoding="utf-8")} - {""}
        except Exception:
            return set()

    def episodes(self, rid="0"):
        out = []
        tests = self.test_eps() if str(rid) == "0" else set()
        for d in glob.glob(os.path.join(self.base(rid), "episodes", "*")):
            ep = os.path.basename(d)
            if not os.path.isdir(d) or not EP_RE.match(ep):
                continue
            has = [f for f in ("conti.yaml", "plan.yaml") if os.path.exists(os.path.join(d, f))]
            if not has:
                continue
            title, mt = ep, max(os.path.getmtime(os.path.join(d, f)) for f in has)
            try:
                for f in has:
                    y = self.nk.load_yaml(os.path.join(d, f))
                    if y.get("title"):
                        title = str(y["title"]); break
            except Exception:
                pass
            pages = glob.glob(os.path.join(d, "out*", "page_*.png"))
            if pages:
                mt = max(mt, max(os.path.getmtime(p) for p in pages))
            out.append({"ep": ep, "title": title, "mtime": mt, "pages": len({os.path.basename(p) for p in pages}), "test": ep in tests})
        out.sort(key=lambda x: -x["mtime"])
        return out

    def flows(self, rid="0"):
        """그 폴더의 workflows/*.json"""
        d = os.path.join(self.base(rid), "workflows")
        if not os.path.isdir(d):
            return []
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.endswith("_final.json")
                      and FLOW_RE.match(f[:-5]) and _is_flow(os.path.join(d, f)))

    def episode(self, ep, rid="0"):
        root = self.base(rid)
        d = self.ep_dir(ep, rid)
        rel = lambda p: os.path.relpath(p, root).replace("\\", "/")
        conti = {}
        if os.path.exists(os.path.join(d, "conti.yaml")):
            try:
                conti = self.nk.load_yaml(os.path.join(d, "conti.yaml"))
            except Exception as e:
                conti = {"_error": str(e)}
        rs = conti.get("restyle")
        out_dir = os.path.join(d, "out_%s" % rs) if rs and os.path.isdir(os.path.join(d, "out_%s" % rs)) else os.path.join(d, "out")
        pages = sorted(glob.glob(os.path.join(out_dir, "page_*.png")))
        pdf = os.path.join(out_dir, "book.pdf")
        flags = {}
        rv = os.path.join(d, "auto", "review.md")
        if os.path.exists(rv):
            for line in open(rv, encoding="utf-8", errors="replace"):
                m = re.match(r"^- cut (\d+): (.*)$", line.strip())
                if m:
                    flags.setdefault(int(m.group(1)), []).append(m.group(2))
        state = {}
        try:
            st = json.load(open(os.path.join(d, "auto", "state.json"), encoding="utf-8"))
            state = {k: (v.get("status"), v.get("rc"), v.get("secs")) for k, v in st.items()}
        except Exception:
            pass
        plan_cuts, plan_doc = [], {}

        def _split(t):
            return [x.strip() for x in str(t or "").split(",") if x.strip()]

        def cut_tags(pc):
            """태그 고치기 화면용: 이 컷의 태그가 어디에 걸려 있나 — 공통 / 캐릭터별 / 배경(장소) / 소품"""
            if not pc:
                return None
            locs, props = plan_doc.get("locations") or {}, plan_doc.get("props") or {}
            pr = {}
            for nme in pc.get("props") or []:
                v = props.get(nme)
                pr[str(nme)] = _split(v.get("tags") if isinstance(v, dict) else v)
            return {"common": _split(pc.get("action")), "roles": {str(k): _split(v) for k, v in (pc.get("roles") or {}).items()},
                    "loc": pc.get("loc"), "loc_tags": _split(locs.get(pc.get("loc"))), "props": pr,
                    "sentence": pc.get("sentence") or "", "who": [str(w) for w in (pc.get("who") or []) if w]}
        if os.path.exists(os.path.join(d, "plan.yaml")):
            try:
                plan = self.nk.load_yaml(os.path.join(d, "plan.yaml"))
                for pg in plan.get("pages") or []:
                    for pc in pg.get("cuts") or []:
                        plan_cuts.append(pc)
                plan_doc = plan
            except Exception:
                pass
        ud = os.path.join(d, "cuts_unify")
        urec = {}
        try:
            urec = json.load(open(os.path.join(ud, "unify.json"), encoding="utf-8"))
        except Exception:
            pass

        def _md5(p):
            return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None

        def unify_info(cid):
            cands = []
            for f in sorted(glob.glob(os.path.join(ud, "cand", "cut%02d_s*.png" % cid))):
                m = re.search(r"_s(\d+)\.png$", f)
                if m:
                    cands.append({"seed": int(m.group(1)), "img": rel(f), "mtime": os.path.getmtime(f)})
            if not cands:
                return None
            r = urec.get(str(cid)) or {}
            for x in cands:
                x["flags"] = (r.get("cand_flags") or {}).get(str(x["seed"])) or []
            fin = os.path.join(d, "cuts", "cut%02d.png" % cid)
            use = r.get("use") if r.get("final_md5") and r.get("final_md5") == _md5(fin) else 0
            orig = os.path.join(ud, "orig", "cut%02d.png" % cid)
            cmp_ = os.path.join(ud, "cut%02d_cmp.png" % cid)
            return {"cands": cands, "use": use or 0, "orig": rel(orig) if os.path.exists(orig) else None,
                    "cmp": rel(cmp_) if os.path.exists(cmp_) else None, "flags": r.get("flags") or []}
        cuts = []
        for pi, pg in enumerate(conti.get("pages") or [], 1):
            for ct in pg.get("cuts") or []:
                cid = int(ct.get("id", 0))
                img = None
                for sub in (["cuts_%s" % rs] if rs else []) + ["cuts"]:
                    f = os.path.join(d, sub, "cut%02d.png" % cid)
                    if os.path.exists(f):
                        img = f; break
                raw = os.path.join(d, "cuts", "cut%02d.png" % cid)
                pc = plan_cuts[cid - 1] if 0 < cid <= len(plan_cuts) else {}
                who = pc.get("who") if pc else None
                if who is None:
                    who = [c.get("char") for c in ct.get("cast") or []] or ([] if str(ct.get("char", "")) == "none"
                                                                            else [ct.get("char") or conti.get("char")])
                cuts.append({"id": cid, "page": pi, "shot": ct.get("shot"), "scene": ct.get("scene"),
                             "who": [w for w in who if w], "duo": bool(ct.get("cast")),
                             "action": pc.get("action") if pc else ct.get("note"), "roles": pc.get("roles") if pc else None,
                             "tags": cut_tags(pc),
                             "lines": [t.get("text") for t in ct.get("text") or []],
                             "img": rel(img) if img else None, "raw": rel(raw) if os.path.exists(raw) else None,
                             "mtime": os.path.getmtime(img) if img else 0, "flags": flags.get(cid, []),
                             "unify": unify_info(cid) if ct.get("cast") else None,
                             "cands": [{"name": os.path.basename(p), "img": rel(p), "mtime": os.path.getmtime(p)}
                                       for p in sorted(glob.glob(os.path.join(d, "cands", "cut%02d" % cid, "[rp]*.png")))]})
        rvp = os.path.join(d, "auto", "review.png")
        #   (다시 칠하기 = NoobAI 로 칠해서 그림체가 섞임, 워크플로 슬롯 = Anima 그리기가 안 읽음). 옛 NoobAI 만화 = 합치기·다시 칠하기 폴더가 있음
        anima = not any(os.path.isdir(os.path.join(d, x)) for x in ("cuts_compose", "cuts_unify", "cuts_picturebook"))
        return {"ep": ep, "root": str(rid), "title": conti.get("title", ep), "artist": conti.get("artist"), "restyle": rs,
                "anima": anima, "flow": conti.get("flow"), "flows": self.flows(rid),
                "fix_prompt": open(os.path.join(d, "fix_prompt.md"), encoding="utf-8").read() if os.path.exists(os.path.join(d, "fix_prompt.md")) else None,
                "pages": [rel(p) for p in pages], "pdf": rel(pdf) if os.path.exists(pdf) else None,
                "state": state, "cuts": cuts, "has_plan": bool(plan_cuts), "has_conti": bool(conti),
                "review": rel(rvp) if os.path.exists(rvp) else None, "error": conti.get("_error")}

    # ------------------------------------------------------------ 그림 파일 (고른 폴더의 episodes/runs 안만)
    def image(self, rel, w=None, rid="0"):
        base = self.base(rid)
        p = os.path.realpath(os.path.join(base, rel))
        root = os.path.realpath(base)
        if not p.startswith(root + os.sep):
            return None, None
        top = os.path.relpath(p, root).split(os.sep)[0]
        ext = os.path.splitext(p)[1].lower()
        if top not in ("episodes", "runs") or ext not in IMG_EXT or not os.path.isfile(p):
            return None, None
        if w and ext != ".pdf":
            w = max(64, min(int(w), 1600))
            key = hashlib.md5(("%s|%s|%d" % (p, os.path.getmtime(p), w)).encode("utf-8")).hexdigest()
            th = os.path.join(base, "runs", "_thumbs", key + ".jpg")
            if not os.path.exists(th):
                try:
                    from PIL import Image
                    os.makedirs(os.path.dirname(th), exist_ok=True)
                    im = Image.open(p).convert("RGB")
                    im.thumbnail((w, w * 3))
                    im.save(th, quality=85)
                except Exception:
                    th = None
            if th:
                return open(th, "rb").read(), "image/jpeg"
        return open(p, "rb").read(), IMG_EXT[ext]

    # ------------------------------------------------------------ 작업
    def make_job(self, b):
        """화면에서 온 요청 -> nk 인자 (여기서 정한 것만 가능)"""
        kind = str(b.get("kind", ""))
        ep = str(b.get("ep", ""))
        rid = str(b.get("root") or "0")
        self.base(rid)
        if kind != "aifile" and not EP_RE.match(ep):
            raise ValueError("에피소드 이름이 이상함: %r" % ep)

        def tags(v):
            v = re.sub(r"[\r\n\t]+", " ", str(v or "")).strip()
            if len(v) > 300:
                raise ValueError("태그가 너무 김")
            return v
        if kind == "auto":
            args = ["ep", "auto", ep]
            fr = str(b.get("from") or "")
            if fr:
                if fr not in STEPS:
                    raise ValueError("단계 이름이 이상함: %s" % fr)
                args += ["--from", fr]
            return args, "%s 만들기%s" % (ep, (" (%s부터)" % fr) if fr else ""), rid
        if kind == "fix":
            cid = int(b.get("cut"))
            args = ["ep", "fix", ep, str(cid)]
            add, rem, who = tags(b.get("add")), tags(b.get("remove")), tags(b.get("who"))
            if add:
                args += ["--add", add]
            if rem:
                args += ["--remove", rem]
            if b.get("where") == "loc":
                args += ["--loc"]
            elif who:
                if not EP_RE.match(who):
                    raise ValueError("이름이 이상함: %s" % who)
                args += ["--who", who]
            return args, "%s %d번 컷 %s" % (ep, cid, ("태그 고치기 +[%s] -[%s]%s" % (add, rem, " (배경)" if b.get("where") == "loc" else (" (%s)" % who if who else ""))) if (add or rem) else "다시 그리기"), rid
        if kind == "partfix":
            cid, who, part = int(b.get("cut")), str(b.get("who") or ""), str(b.get("part") or "")
            if not EP_RE.match(who) or part not in ("head", "hand", "chest", "tail", "ear", "foot"):
                raise ValueError("캐릭터나 부위가 이상함: %s %s" % (who, part))
            return (["ep", "partfix", ep, str(cid), "--who", who, "--part", part, "--n", "2"],
                    "%s %d번 컷 %s %s만 다시 (후보 2장)" % (ep, cid, who, part), rid)
        if kind == "cands":
            cid = int(b.get("cut"))
            return ["ep", "cands", ep, str(cid), "--n", "3"], "%s %d번 컷 후보 3장" % (ep, cid), rid
        if kind == "usecand":
            cid, nm = int(b.get("cut")), str(b.get("name") or "")
            if not re.match(r"^[rp]\d{2,3}\.png$", nm):
                raise ValueError("후보 이름이 이상함: %s" % nm)
            return ["ep", "usecand", ep, str(cid), nm], "%s %d번 컷 -> 후보 %s (말풍선 다시)" % (ep, cid, nm), rid
        if kind == "letter":
            return ["ep", "letter", ep], "%s 말풍선 다시" % ep, rid
        if kind == "unify":
            cid = int(b.get("cut"))
            dn = float(b.get("denoise") or 0.4)
            if not 0.2 <= dn <= 0.7:
                raise ValueError("다시 칠하는 정도는 0.2~0.7")
            sd = int(b.get("seed") or 72)
            return (["ep", "unify", ep, str(cid), "--no-apply", "--denoise", "%g" % dn, "--seeds", str(sd)],
                    "%s %d번 컷 다시 칠하기 후보 (%g)" % (ep, cid, dn), rid)
        if kind == "unifyuse":                       # 후보 고르기 / 0 = 합친 그림으로 되돌리기
            cid, sd = int(b.get("cut")), int(b.get("seed"))
            return (["ep", "unify", ep, "--use", "%d=%d" % (cid, sd)],
                    "%s %d번 컷 -> %s" % (ep, cid, "합친 그림" if sd == 0 else "다시 칠한 그림 %d" % sd), rid)
        if kind == "setflow":
            name = str(b.get("flow") or "none")
            if name != "none" and name not in self.flows(rid):
                raise ValueError("그 폴더의 workflows 에 없는 워크플로: %s" % name)
            return ["ep", "flow", "set", name, "--ep", ep], "%s 그림 워크플로 -> %s" % (ep, name if name != "none" else "기본"), rid
        if kind == "aifile":
            return ["ep", "aifile"], "AI 첨부 파일 만들기", "0"
        if kind == "paste":
            text = str(b.get("text") or "")
            if not text.strip() or len(text) > 200000:
                raise ValueError("붙여 넣은 글이 없거나 너무 김")
            d = self.ep_dir(ep, rid)
            os.makedirs(d, exist_ok=True)
            fp = os.path.join(d, "ai_answer_%s.md" % time.strftime("%m%d_%H%M%S"))
            open(fp, "w", encoding="utf-8").write(text)
            args = ["ep", "paste", ep, "--file", fp]
            fl = str(b.get("flow") or "")
            if fl:
                if fl not in self.flows(rid):
                    raise ValueError("그 폴더의 workflows 에 없는 워크플로: %s" % fl)
                args += ["--flow", fl]
            if b.get("go"):
                args.append("--go")
            return args, "%s AI 답 검사%s" % (ep, " + 바로 만들기" if b.get("go") else ""), rid
        raise ValueError("모르는 작업: %s" % kind)

    def add_job(self, args, note, rid="0"):
        kind = args[1] if len(args) > 1 else args[0]
        ep = args[2] if len(args) > 2 and EP_RE.match(str(args[2])) else ""
        name = _jobname(kind, ep)
        if str(rid) == "0":
            d = self.inbox
            job = {"args": args, "note": "[화면] " + note, "timeout_min": 600}
        else:
            d = os.path.join(self.base(rid), "_nk", "queue")
            job = {"args": args, "note": note, "home": self.base(rid)}
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        return name

    # 취소 = 지우지 않고 '멈춘 작업'(paused 폴더)으로. 이어서 시작 = 도는 줄 맨 아래로. 대기열 삭제 = 멈춘 작업만 완전히 지움.
    # 바로 만들기 = 지금 도는 만화를 끊고(이어 갈 쪽지를 만들어 둠) 그 작업부터, 끝나면 끊긴 만화를 이어 감 (front.json 순서).
    RESUMABLE = ("paste", "auto", "fix", "cands", "partfix", "usecand", "letter")

    def _qdirs(self, rid):
        """-> (도는 줄 폴더 목록, 멈춘 작업 폴더)"""
        if str(rid) == "0":
            return [self.inbox, self.held], os.path.join(self.box, "paused")
        home = self.base(rid)
        return [os.path.join(home, "_nk", "queue")], os.path.join(home, "_nk", "paused")

    def _find_job(self, name, rid, paused=False):
        act, pz = self._qdirs(rid)
        for d in ([pz] if paused else act):
            fp = os.path.join(d, name)
            if os.path.exists(fp):
                return fp
        return None

    def _write_job(self, d, name, job):
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, name)
        with open(fp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        os.replace(fp + ".tmp", fp)
        return fp

    def front_load(self):
        try:
            return [x for x in json.load(open(self.front_path, encoding="utf-8")) if isinstance(x, dict) and x.get("name")]
        except Exception:
            return []

    def front_save(self, fr):
        if not fr:
            try:
                os.remove(self.front_path)
            except Exception:
                pass
            return
        with open(self.front_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(fr, f, ensure_ascii=False)
        os.replace(self.front_path + ".tmp", self.front_path)

    # 누른 시각만 적어 두고, 그 시각까지 잘 끝난(rc 0) 작업을 화면 목록에서만 숨김. 기록 파일·대기열·그림은 안 건드림 (실패·멈춘 작업은 남김).
    def cleared_at(self):
        try:
            return str(json.load(open(self.cleared_path, encoding="utf-8")).get("at") or "")
        except Exception:
            return ""

    def clear_done(self, undo=False):
        if undo:
            try:
                os.remove(self.cleared_path)
            except Exception:
                pass
            return ""
        at = _now()
        with open(self.cleared_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"at": at}, f)
        os.replace(self.cleared_path + ".tmp", self.cleared_path)
        return at

    def front_clean(self):
        """앞줄 기록에서 이미 시작했거나 없어진 작업을 뺌"""
        old = self.front_load()
        fr = []
        for x in old:
            try:
                if self._find_job(x["name"], str(x.get("root") or "0")):
                    fr.append(x)
            except Exception:
                pass
        if fr != old:
            self.front_save(fr)
        return fr

    def apply_front(self):
        """앞줄 맨 앞 작업이 먼저 돌게 우체통 줄을 정리: 키트 작업이면 그것만 inbox (나머지는 held), 개인 작업이면 키트 작업을 모두 held"""
        fr = self.front_clean()
        if not fr:
            return fr
        os.makedirs(self.held, exist_ok=True)
        if not os.path.exists(self.busy_mark):
            open(self.busy_mark, "w", encoding="utf-8").write(
                "작업 순서 조정 중 (%s) - '바로 만들기' 또는 개인 작업. 작업 줄은 _remote\\held 에 잠시 옮겨 둠. 새 작업을 넣지 말 것\n" % _now())
        f0 = fr[0]
        keep = f0["name"] if str(f0.get("root") or "0") == "0" else None
        for n in os.listdir(self.inbox):
            if n.endswith(".json") and n != keep:
                try:
                    os.replace(os.path.join(self.inbox, n), os.path.join(self.held, n))
                except Exception:
                    pass
        if keep and os.path.exists(os.path.join(self.held, keep)):
            os.replace(os.path.join(self.held, keep), os.path.join(self.inbox, keep))
        return fr

    def cancel(self, name, rid="0"):
        """취소 = 멈춘 작업으로 (지우지 않음). 이어서 시작·대기열 삭제는 resume_job·delete_job"""
        if not JOB_RE.match(name or ""):
            raise ValueError("작업 이름이 이상함")
        fp = self._find_job(name, rid)
        if not fp:
            raise ValueError("이미 시작했거나 없는 작업")
        pz = self._qdirs(rid)[1]
        os.makedirs(pz, exist_ok=True)
        os.replace(fp, os.path.join(pz, name))
        self.front_save([x for x in self.front_load() if not (x["name"] == name and str(x.get("root") or "0") == str(rid))])

    def resume_job(self, name, rid="0"):
        """멈춘 작업 -> 도는 줄 맨 아래 (새 이름 = 지금 시각)"""
        if not JOB_RE.match(name or ""):
            raise ValueError("작업 이름이 이상함")
        fp = self._find_job(name, rid, paused=True)
        if not fp:
            raise ValueError("멈춘 작업이 아님")
        try:
            args = json.load(open(fp, encoding="utf-8")).get("args") or []
        except Exception:
            args = []
        kind = str(args[1]) if len(args) > 1 else "job"
        ep = str(args[2]) if len(args) > 2 and EP_RE.match(str(args[2])) else ""
        new = _jobname(kind, ep, prio=False)          # 이어서 시작 = 도는 줄 맨 아래 (먼저 돌리는 표시 없이)
        if str(rid) == "0":
            dest = self.held if os.path.exists(self.busy_mark) else self.inbox
        else:
            dest = self._qdirs(rid)[0][0]
        os.makedirs(dest, exist_ok=True)
        os.replace(fp, os.path.join(dest, new))
        return new

    def delete_job(self, name, rid="0"):
        if not JOB_RE.match(name or ""):
            raise ValueError("작업 이름이 이상함")
        fp = self._find_job(name, rid, paused=True)
        if not fp:
            raise ValueError("멈춘 작업만 지울 수 있음 (먼저 취소)")
        os.remove(fp)

    def current(self):
        """지금 도는 작업 -> (jid, rid, 쪽지 dict, 지난 초) 또는 None"""
        if self.priv.cur:
            jid, rid = self.priv.cur, str(self.priv.cur_root)
            jp = os.path.join(self.base(rid), "_nk", "done", jid + ".job.json")
            el = int(time.time() - self.priv.t0)
        else:
            st = self.runner_status()
            if not (st.get("alive") and st.get("job")) or not self.has_runner:
                return None
            jid, rid = str(st["job"]), "0"
            jp = os.path.join(self.done, jid + ".job.json")
            el = int(st.get("elapsed_s") or 0)
        try:
            job = json.load(open(jp, encoding="utf-8"))
        except Exception:
            job = {}
        return jid, rid, job, el

    def resume_for(self, rid, job, elapsed):
        """끊긴 작업을 이어 갈 쪽지 (dict) 또는 None (학습·시험처럼 이어 갈 수 없는 작업)"""
        args = [str(x) for x in (job.get("args") or [])]
        kind = args[1] if len(args) > 1 else ""
        if kind not in self.RESUMABLE:
            return None
        ep = args[2] if len(args) > 2 else ""
        nargs = args
        if kind in ("paste", "auto", "fix") and EP_RE.match(ep):
            d = self.ep_dir(ep, rid)
            if kind == "fix":
                nargs = ["ep", "auto", ep, "--from", "make"]          # 그 컷은 이미 지워졌음 -> 없는 컷만 새로 그리고 뒤 단계
            elif kind == "auto" or os.path.exists(os.path.join(d, "plan.yaml")):
                nargs = ["ep", "auto", ep] if "--from" not in args else args      # 이미 있는 컷은 건너뛰고 이어 감
            elif "--go" not in args:
                return None
        note = "(이어서) " + re.sub(r"^(\(이어서\) )+", "", str(job.get("note") or ""))
        out = {"args": nargs, "note": note, "elapsed_before": int(job.get("elapsed_before") or 0) + int(elapsed or 0)}
        if str(rid) == "0":
            out["timeout_min"] = 600
        else:
            out["home"] = self.base(rid)
        return out

    def _kill(self, jid, rid):
        if str(rid) != "0":
            self.priv.kill()
        elif not self.has_runner and self.worker:
            self.worker.kill()
        else:
            open(os.path.join(self.box, "KILL_" + jid), "w").write("killed from the web page %s" % time.strftime("%H:%M:%S"))

    def kill_current(self):
        """지금 작업 멈추기: 만화 작업이면 '멈춘 작업'으로 남김 (이어서 시작 / 대기열 삭제)"""
        cur = self.current()
        if not cur:
            if not self.has_runner and self.worker and self.runner_status().get("job"):
                self.worker.kill()
                return self.runner_status().get("job")
            raise ValueError("지금 도는 작업이 없음")
        jid, rid, job, el = cur
        rj = self.resume_for(rid, job, el)
        self._kill(jid, rid)
        if rj:
            a = rj["args"]
            self._write_job(self._qdirs(rid)[1], _jobname(a[1], a[2] if len(a) > 2 and EP_RE.match(a[2]) else ""), rj)
        elif str(rid) == "0" and not jid.startswith("a") and not jid.endswith("_again"):
            src = os.path.join(self.done, jid + ".job.json")
            if os.path.exists(src):
                dest_dir = self.held if os.path.exists(self.busy_mark) else self.inbox
                j = json.load(open(src, encoding="utf-8"))
                j["note"] = "(%s에 멈춤 -> 다시) %s" % (time.strftime("%H:%M"), j.get("note", ""))
                self._write_job(dest_dir, jid + "_again.json", j)
        return ("개인 작업 " + jid) if str(rid) != "0" else jid

    def run_now(self, name, rid="0"):
        """바로 만들기: 그 작업을 맨 앞으로. 지금 도는 만화는 끊고 그 뒤에 이어 가게 함"""
        if not JOB_RE.match(name or ""):
            raise ValueError("작업 이름이 이상함")
        rid = str(rid or "0")
        if not self._find_job(name, rid):
            raise ValueError("기다리는 작업이 아님 (멈춘 작업이면 먼저 '이어서 시작')")
        front = [{"name": name, "root": rid}]
        cur = self.current()
        if cur:
            jid, crid, job, el = cur
            rj = self.resume_for(crid, job, el)
            if rj is None:
                self.front_save(front)
                self.apply_front()
                return "지금 도는 작업은 중간에 끊을 수 없는 종류라, 그 작업이 끝나면 바로 시작해"
            a = rj["args"]
            rname = _jobname(a[1], a[2] if len(a) > 2 and EP_RE.match(a[2]) else "")
            self._write_job(self.held if crid == "0" else self._qdirs(crid)[0][0], rname, rj)
            front.append({"name": rname, "root": crid})
            self.front_save(front)
            self.apply_front()
            self._kill(jid, crid)
            return "지금 만들던 만화를 멈추고 바로 시작 — 끝나면 멈춘 만화를 이어서 만들어"
        self.front_save(front)
        self.apply_front()
        return "맨 앞에 뒀어 — 바로 시작해"

    def check_plan(self, b):
        """글콘티 검사하기: AI 답을 바로 검사해서 결과를 돌려줌 (작업 줄을 안 거침, 그림 안 그림, 몇 초).
        -> {passed, can_make, error, fix_prompt, title, pages, cuts, est_s}"""
        rid, ep = str(b.get("root") or "0"), str(b.get("ep") or "")
        text = str(b.get("text") or "")
        if not EP_RE.match(ep):
            raise ValueError("에피소드 이름은 영어·숫자·밑줄만")
        if not text.strip() or len(text) > 200000:
            raise ValueError("붙여 넣은 글이 없거나 너무 김")
        d = self.ep_dir(ep, rid)
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, "ai_answer_%s.md" % time.strftime("%m%d_%H%M%S"))
        open(fp, "w", encoding="utf-8").write(text)
        args = ["ep", "paste", ep, "--file", fp]
        fl = str(b.get("flow") or "")
        if fl and fl in self.flows(rid):
            args += ["--flow", fl]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", NK_NO_CLIP="1")
        if rid != "0":
            env["NK_HOME"] = self.base(rid)
        try:
            r = subprocess.run([sys.executable, "-u", os.path.join(self.kit, "nk.py")] + args, cwd=self.kit, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            out, rc = r.stdout.decode("utf-8", "replace"), r.returncode
        except subprocess.TimeoutExpired:
            return {"passed": False, "can_make": False, "error": "검사가 3분 넘게 안 끝남 — 다시 눌러 줘"}
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        err = next((l for l in lines if "[ERROR]" in l or "[STOP]" in l), "")
        if not err and rc != 0:
            err = _fail_reason_text(lines) or "검사 중 오류 (rc %s)" % rc
        fxp = os.path.join(d, "fix_prompt.md")
        fix = open(fxp, encoding="utf-8").read() if (rc == 0 and os.path.exists(fxp)) else ""
        m = re.search(r"plan -> .*\((.*?) / (\d+) pages, (\d+) cuts", out)
        res = {"passed": rc == 0 and not fix and not err, "can_make": rc == 0 and os.path.exists(os.path.join(d, "conti.yaml")),
               "notes": _plan_notes_text(out)[:10],
               "error": err, "fix_prompt": fix, "ep": ep, "root": rid,
               "title": m.group(1) if m else ep, "pages": int(m.group(2)) if m else None, "cuts": int(m.group(3)) if m else None}
        try:
            res["est_s"] = self.estimate(["ep", "auto", ep], rid)[0]
        except Exception:
            res["est_s"] = None
        return res

    def start_runner(self):
        if not self.has_runner:
            return "이 폴더는 화면이 직접 작업을 돌림"
        if self.runner_status()["alive"]:
            return "우체통이 이미 켜져 있음"
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen([sys.executable, os.path.join(self.kit, "nk_remote.py")], cwd=self.kit, creationflags=flags)
        return "우체통을 새 창으로 켰음"

    # ------------------------------------------------------------ 우체통 잠시 비우기 (개인 작업 동안)
    def hold(self):
        os.makedirs(self.held, exist_ok=True)
        if not os.path.exists(self.busy_mark):
            open(self.busy_mark, "w", encoding="utf-8").write(
                "개인 폴더 작업 중 (%s) - 작업 줄은 _remote\\held 에 잠시 옮겨 둠. 새 작업을 넣지 말 것\n" % _now())
        for n in os.listdir(self.inbox):
            if n.endswith(".json"):
                try:
                    os.replace(os.path.join(self.inbox, n), os.path.join(self.held, n))
                except Exception:
                    pass

    def unhold(self):
        if os.path.isdir(self.held):
            for n in os.listdir(self.held):
                if n.endswith(".json"):
                    try:
                        os.replace(os.path.join(self.held, n), os.path.join(self.inbox, n))
                    except Exception:
                        pass
        try:
            os.remove(self.busy_mark)
        except Exception:
            pass


def _hid(r, at):
    """끝난 작업 r 을 목록에서 숨기나: 「잘 끝난 작업 지우기」를 누른 시각(at)까지 잘 끝난 것만 (실패·멈춘 작업은 늘 보임)"""
    return bool(at) and r.get("rc") == 0 and not r.get("killed") and bool(r.get("end")) and str(r.get("end")) <= at


# ---------------------------------------------------------------- 일꾼: 한 작업 돌리기
def mask_private(st):
    """보기 전용 화면(view=readonly, 열쇠 없음)에 보내는 상태: 개인 폴더 작업은 이름·내용을 가림"""
    st = dict(st)
    st["queue"] = [({"name": "private", "private": True, "mine": True, "args": ["(개인 작업)"], "note": "", "root": None,
                     "held": q.get("held"), "paused": q.get("paused"), "front": q.get("front")} if q.get("private") else q)
                   for q in st.get("queue") or []]
    st["recent"] = [({"id": "private", "private": True, "args": ["(개인 작업)"], "rc": r.get("rc"), "killed": r.get("killed"),
                      "end": r.get("end"), "secs": r.get("secs")} if r.get("private") else r) for r in st.get("recent") or []]
    pv = dict(st.get("private") or {})
    if pv.get("job"):
        pv["job"], pv["root"] = "private", None
    pv.pop("log_tail", None)
    st["private"] = pv
    pl = dict(st.get("plan") or {})
    items = []
    for x in pl.get("items") or []:
        if x.get("private"):
            det = x.get("detail") or {}
            x = {"name": "개인 작업", "job": "private", "private": True, "running": x.get("running"), "elapsed_s": x.get("elapsed_s"),
                 "elapsed_total_s": x.get("elapsed_total_s"), "front": x.get("front"), "root": None,
                 "remain_s": x.get("remain_s"), "est_s": x.get("est_s"), "held": x.get("held"), "progress": None,
                 "detail": ({"frac": det.get("frac"), "cuts": [], "steps": [], "title": "", "ep": ""} if det else None)}
        items.append(x)
    pl["items"] = items
    pl["done"] = [({"name": "개인 작업", "job": "private", "done": True, "ok": x.get("ok"), "end": x.get("end"), "private": True,
                    "error": "", "hid": x.get("hid")} if x.get("private") else x) for x in pl.get("done") or []]
    pl["paused"] = [({"name": "개인 작업", "job": "private", "private": True, "paused": True, "remain_s": x.get("remain_s"), "root": None}
                     if x.get("private") else x) for x in pl.get("paused") or []]
    st["plan"] = pl
    return st


def _plan_notes_text(out):
    """컴파일 출력의 '[참고]' 아래 '  - ' 줄들 = 돌려보내지 않는 참고 -> 글콘티 검사 창에 '참고'로"""
    notes, on = [], False
    for l in str(out or "").splitlines():
        if l.startswith("[참고]"):
            on = True
            continue
        if on:
            if l.startswith("  - "):
                notes.append(l[4:].strip())
            elif l.strip():
                on = False
    return notes


def _fail_reason_text(lines):
    """기록 줄 목록 -> 파이썬 오류 마지막 줄 (없으면 '')"""
    for i, l in enumerate(lines):
        if l.startswith("Traceback"):
            return lines[-1][:220]
    return ""


def _fail_reason(log_path):
    """실패한 작업 기록에서 이유 한 줄: 마지막 [ERROR]·[STOP] 줄, 없으면 파이썬 오류의 마지막 줄"""
    try:
        with open(log_path, "rb") as f:
            f.seek(max(0, os.path.getsize(log_path) - 65536))
            lines = [l.strip() for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()]
    except Exception:
        return ""
    errs = [l for l in lines if "[ERROR]" in l or "[STOP]" in l]
    root = [l for l in errs if "failed - stop" not in l]          # '...단계 failed - stop' 은 뒤따르는 줄 -> 앞의 진짜 이유
    if errs:
        return (root[0] if root else errs[-1])[:220]
    for i, l in enumerate(lines):
        if l.startswith("Traceback"):
            loc = [x for x in lines[i:] if x.startswith('File "')]
            where = ""
            if loc:
                mm = re.match(r'File "(?:.*[\\/])?([^\\/"]+)", line (\d+), in (\S+)', loc[-1])
                where = (" (%s %s줄 %s)" % mm.groups()) if mm else ""
            return (lines[-1] + where)[:260]
    return ""


def _run_nk(kit, args, log_path, env_extra=None, on_start=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env.update(env_extra or {})
    with open(log_path, "w", encoding="utf-8", buffering=1) as lf:
        lf.write("# nk %s\n# start %s\n" % (" ".join(args), _now()))
        p = subprocess.Popen([sys.executable, "-u", os.path.join(kit, "nk.py")] + args, cwd=kit,
                             stdout=lf, stderr=subprocess.STDOUT, env=env)
        if on_start:
            on_start(p)
        p.wait()
    return p.returncode


class Worker(threading.Thread):
    """우체통이 없는 폴더(실험 폴더)용: _remote\\inbox 를 화면이 직접 하나씩 돌림"""
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.cur, self.proc, self.t0, self.killed = None, None, 0, False

    def state(self):
        return {"runner": "busy" if self.cur else "idle", "job": self.cur,
                "elapsed_s": int(time.time() - self.t0) if self.cur else None,
                "log_tail": self.app.log_tail(self.cur, 15) if self.cur else []}

    def kill(self):
        self.killed = True
        if self.proc:
            _kill_tree(self.proc)

    def run(self):
        a = self.app
        while True:
            jobs = sorted(n for n in os.listdir(a.inbox) if n.endswith(".json")
                          and time.time() - os.path.getmtime(os.path.join(a.inbox, n)) > 2)
            if not jobs:
                time.sleep(2); continue
            with a.gpu:
                n = jobs[0]
                jid = n[:-5]
                src = os.path.join(a.inbox, n)
                try:
                    job = json.load(open(src, encoding="utf-8"))
                    os.replace(src, os.path.join(a.done, jid + ".job.json"))
                except Exception:
                    try:
                        os.remove(src)
                    except Exception:
                        pass
                    continue
                args = job.get("args") or []
                res = {"id": jid, "args": args, "note": job.get("note", ""), "start": _now()}
                if not args or args[0] != "ep" or "--force" in args:
                    res.update(rc=-1, error="not allowed")
                    json.dump(res, open(os.path.join(a.done, jid + ".result.json"), "w"))
                    continue
                self.cur, self.t0, self.killed = jid, time.time(), False
                rc = _run_nk(a.kit, args, os.path.join(a.logs, jid + ".log"), on_start=lambda p: setattr(self, "proc", p))
                res.update(rc=rc, killed=self.killed, end=_now(), secs=int(time.time() - self.t0))
                json.dump(res, open(os.path.join(a.done, jid + ".result.json"), "w", encoding="utf-8"), ensure_ascii=False)
                self.cur, self.proc = None, None


class PrivateWorker(threading.Thread):
    """기록은 그 폴더 _nk 안에만."""
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.cur, self.cur_root, self.proc, self.t0, self.killed = None, None, None, 0, False
        self.wait_msg = ""

    def pending(self):
        out = []
        for i, f in enumerate(self.app.folders, 1):
            q = os.path.join(f, "_nk", "queue")
            if os.path.isdir(q):
                for n in sorted(os.listdir(q)):
                    if n.endswith(".json"):
                        out.append((n, str(i), f))
        out.sort()
        return out

    def queue_view(self):
        out = []
        for n, rid, f in self.pending():
            try:
                j = json.load(open(os.path.join(f, "_nk", "queue", n), encoding="utf-8"))
            except Exception:
                j = {}
            out.append({"name": n, "args": j.get("args"), "note": j.get("note", ""), "mine": True, "private": True, "root": rid,
                        "paused": False, "elapsed_before": j.get("elapsed_before")})
        for i, f in enumerate(self.app.folders, 1):
            pz = os.path.join(f, "_nk", "paused")
            if os.path.isdir(pz):
                for n in sorted(os.listdir(pz)):
                    if n.endswith(".json"):
                        try:
                            j = json.load(open(os.path.join(pz, n), encoding="utf-8"))
                        except Exception:
                            j = {}
                        out.append({"name": n, "args": j.get("args"), "note": j.get("note", ""), "mine": True, "private": True,
                                    "root": str(i), "paused": True, "elapsed_before": j.get("elapsed_before")})
        return out

    def recent(self, k=8):
        fs = []
        for i, f in enumerate(self.app.folders, 1):
            fs += [(p, str(i)) for p in glob.glob(os.path.join(f, "_nk", "done", "*.result.json"))]
        fs = sorted(fs, key=lambda x: os.path.getmtime(x[0]), reverse=True)[:k]
        out = []
        for p, rid in fs:
            try:
                r = json.load(open(p, encoding="utf-8"))
                r["private"], r["root"] = True, rid
                if r.get("rc") not in (0, None) and not r.get("error") and not r.get("killed"):
                    r["error"] = _fail_reason(os.path.join(os.path.dirname(os.path.dirname(p)), "logs", str(r.get("id")) + ".log"))
                out.append(r)
            except Exception:
                pass
        return out

    def state(self):
        return {"job": self.cur, "root": self.cur_root, "elapsed_s": int(time.time() - self.t0) if self.cur else None,
                "wait": self.wait_msg}

    def kill(self):
        self.killed = True
        if self.proc:
            _kill_tree(self.proc)

    def _runner_busy(self):
        a = self.app
        if not a.has_runner:
            return False
        s = a.runner_status()
        return bool(s.get("alive") and s.get("job"))

    def run(self):
        a = self.app
        holding = False
        if os.path.exists(a.busy_mark):
            a.unhold()
        while True:
            try:
                pend = self.pending()
                fr = a.front_clean()
                if fr and str(fr[0].get("root") or "0") == "0":
                    a.apply_front(); holding = True          # 키트 작업이 먼저: 그것만 우체통에 두고 개인 작업은 기다림
                    self.wait_msg = "먼저 만들 작업이 끝나면 시작" if pend else ""
                    time.sleep(2); continue
                if not pend:
                    if holding or os.path.exists(a.busy_mark):
                        a.unhold(); holding = False
                    self.wait_msg = ""
                    time.sleep(2); continue
                if a.has_runner:
                    a.hold(); holding = True
                    if self._runner_busy():
                        s = a.runner_status()
                        self.wait_msg = "앞 작업(%s)이 끝나면 바로 시작 - 바로 하려면 '지금 작업 멈추기'" % s.get("job")
                        time.sleep(2); continue
                n, rid, home = pend[0]
                if fr:                              # 앞줄 맨 앞이 개인 작업이면 그것부터
                    hit = [x for x in pend if x[0] == fr[0]["name"] and str(x[1]) == str(fr[0].get("root"))]
                    if hit:
                        n, rid, home = hit[0]
                qd = os.path.join(home, "_nk", "queue")
                for sub in ("logs", "done"):
                    os.makedirs(os.path.join(home, "_nk", sub), exist_ok=True)
                jid = n[:-5]
                try:
                    job = json.load(open(os.path.join(qd, n), encoding="utf-8"))
                    os.replace(os.path.join(qd, n), os.path.join(home, "_nk", "done", jid + ".job.json"))
                except Exception:
                    try:
                        os.remove(os.path.join(qd, n))
                    except Exception:
                        pass
                    continue
                args = job.get("args") or []
                res = {"id": jid, "args": args, "note": job.get("note", ""), "start": _now()}
                if not args or args[0] != "ep" or "--force" in args:
                    res.update(rc=-1, error="not allowed")
                else:
                    self.wait_msg = ""
                    lock = a.gpu if not a.has_runner else threading.Lock()
                    with lock:
                        self.cur, self.cur_root, self.t0, self.killed = jid, rid, time.time(), False
                        rc = _run_nk(a.kit, args, os.path.join(home, "_nk", "logs", jid + ".log"), {"NK_HOME": home},
                                     on_start=lambda p: setattr(self, "proc", p))
                    res.update(rc=rc, killed=self.killed, end=_now(), secs=int(time.time() - self.t0))
                json.dump(res, open(os.path.join(home, "_nk", "done", jid + ".result.json"), "w", encoding="utf-8"),
                          ensure_ascii=False)
                self.cur, self.cur_root, self.proc = None, None, None
            except Exception as e:
                self.wait_msg = "개인 작업 일꾼 오류: %s" % e
                time.sleep(5)


# 컷 그림 = 만화에 실제로 들어간 판 (cuts_<restyle> 있으면 그것, 없으면 cuts). 키 = '편:컷:그림md5 앞 10자리' -> 그림이 바뀌면 새 표시.
LABEL_FLAGS = ["괜찮음", "얼굴", "손", "귀·머리", "몸·비율", "무늬·디자인", "그림체 괴리", "AI티", "이야기 불일치", "배경", "기타"]


class Labels:
    def __init__(self, app):
        self.app = app
        self.dir = os.environ.get("NK_LABELS_DIR") or os.path.join(app.kit, "_labels")      # NK_LABELS_DIR = 시험용
        self.path = os.path.join(self.dir, "labels.json")
        self.log = os.path.join(self.dir, "labels_log.jsonl")
        self.lock = threading.Lock()
        self._md5 = {}

    def md5(self, p):
        k = (p, os.path.getmtime(p), os.path.getsize(p))
        if k not in self._md5:
            self._md5[k] = hashlib.md5(open(p, "rb").read()).hexdigest()
        return self._md5[k]

    def load(self):
        try:
            return json.load(open(self.path, encoding="utf-8"))
        except Exception:
            return {}

    def _cut(self, ep, cid):
        c = next((x for x in self.app.episode(ep, "0")["cuts"] if x["id"] == cid and x["img"]), None)
        if not c:
            raise ValueError("그 컷 그림이 없음: %s %s" % (ep, cid))
        return c, "%s:%d:%s" % (ep, cid, self.md5(os.path.join(self.app.kit, c["img"]))[:10])

    def items(self):
        eps = []
        for e in self.app.episodes("0"):
            try:
                info = self.app.episode(e["ep"], "0")
            except Exception:
                continue
            cuts = [{"id": c["id"], "img": c["img"], "who": c["who"], "duo": c["duo"], "action": c.get("action"),
                     "key": "%s:%d:%s" % (e["ep"], c["id"], self.md5(os.path.join(self.app.kit, c["img"]))[:10])}
                    for c in info["cuts"] if c["img"]]
            if cuts:
                eps.append({"ep": e["ep"], "title": e["title"], "artist": info.get("artist"), "restyle": info.get("restyle"),
                            "cuts": cuts})
        return {"episodes": eps, "labels": self.load(), "flags": LABEL_FLAGS}

    def save(self, b):
        ep = str(b.get("ep", ""))
        if not EP_RE.match(ep):
            raise ValueError("편 이름이 이상함")
        cid = int(b.get("cut", 0))
        c, key = self._cut(ep, cid)                     # md5는 서버가 직접 잼 (화면이 보낸 값을 믿지 않음)
        flags = [f for f in (b.get("flags") or []) if f in LABEL_FLAGS]
        if "괜찮음" in flags and len(flags) > 1:
            raise ValueError("'괜찮음'과 흠을 같이 고를 수 없음")
        sc = b.get("score")
        sc = None if sc in (None, "") else max(0, min(100, int(sc)))
        note = str(b.get("note") or "")[:1000]
        rec = {"ep": ep, "cut": cid, "img": c["img"], "flags": flags, "score": sc, "note": note,
               "time": time.strftime("%Y-%m-%d %H:%M:%S"), "by": str(b.get("by") or "user")[:30]}
        with self.lock:
            os.makedirs(self.dir, exist_ok=True)
            d = self.load()
            if flags or note or sc is not None:
                d[key] = rec
            else:
                d.pop(key, None)                        # 다 지우면 표시 없음으로
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            with open(self.log, "a", encoding="utf-8") as f:       # 모든 저장 기록 (되돌리기용)
                f.write(json.dumps(dict(rec, key=key), ensure_ascii=False) + "\n")
        return {"ok": True, "key": key, "rec": rec if key in d else None}


# 화면엔 set.json 만 감 (어느 쪽이 켠 것인지는 key.json — 화면에 안 보냄). 답 = _labels/ab.json, 키 '<이름>:<쌍>'.
AB_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


class ABSets:
    def __init__(self, app):
        self.app = app
        self.dir = os.environ.get("NK_LABELS_DIR") or os.path.join(app.kit, "_labels")
        self.path = os.path.join(self.dir, "ab.json")
        self.log = os.path.join(self.dir, "ab_log.jsonl")
        self.root = os.path.join(app.kit, "runs", "ab")
        self.lock = threading.Lock()

    def load(self):
        try:
            return json.load(open(self.path, encoding="utf-8"))
        except Exception:
            return {}

    def _set(self, name):
        if not AB_NAME_RE.match(name or ""):
            raise ValueError("비교판 이름이 이상함")
        try:
            return json.load(open(os.path.join(self.root, name, "set.json"), encoding="utf-8"))
        except Exception:
            raise ValueError("그 비교판이 없음: %s" % name)

    def items(self):
        sets = []
        for p in sorted(glob.glob(os.path.join(self.root, "*", "set.json")), key=os.path.getmtime, reverse=True):
            name = os.path.basename(os.path.dirname(p))
            if "_old_" in name or not AB_NAME_RE.match(name):
                continue
            try:
                s = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            sets.append({k: s.get(k) for k in ("name", "title", "question", "kind", "choices", "created", "items")})
            sets[-1]["name"] = name
        return {"sets": sets, "answers": self.load()}

    def save(self, b):
        name, iid = str(b.get("set", "")), str(b.get("item", ""))
        s = self._set(name)
        if not any(it.get("id") == iid for it in s.get("items") or []):
            raise ValueError("그 쌍이 없음: %s" % iid)
        ch = str(b.get("choice") or "")
        if ch and ch not in [c["code"] for c in s.get("choices") or []]:
            raise ValueError("고를 수 없는 답: %s" % ch)
        note = str(b.get("note") or "")[:1000]
        key = "%s:%s" % (name, iid)
        rec = {"set": name, "item": iid, "choice": ch, "note": note, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "by": str(b.get("by") or "user")[:30]}
        with self.lock:
            os.makedirs(self.dir, exist_ok=True)
            d = self.load()
            if ch or note:
                d[key] = rec
            else:
                d.pop(key, None)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(rec, key=key), ensure_ascii=False) + "\n")
        return {"ok": True, "key": key, "rec": rec if key in d else None}


# ---------------------------------------------------------------- HTTP
def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _local(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self._local():
                return self._send(403, {"error": "local only"})
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            rid = q.get("root", "0")
            key = self.headers.get("X-NK-K") or q.get("k") or ""
            keyok = bool(key) and __import__("hmac").compare_digest(key, PAGE_KEY)
            cv = q.get("view") == "readonly" or not keyok
            try:
                if u.path == "/":
                    pv = q.get("view") == "readonly"
                    return self._send(200, PAGE.replace("<script>", "<script>window.CV=%s;window.NKK=%s;" % (
                        "true" if pv else "false", json.dumps("" if pv else PAGE_KEY)), 1), "text/html; charset=utf-8")
                if cv and str(rid) != "0":
                    return self._send(403, {"error": "보기 전용 화면에서는 개인 폴더를 안 보여 줌", "stale": bool(key) and not keyok})
                if u.path == "/label":
                    return self._send(200, LABEL_PAGE, "text/html; charset=utf-8")
                if u.path == "/api/labels":
                    return self._send(200, app.labels.items())
                if u.path == "/ab":
                    return self._send(200, AB_PAGE, "text/html; charset=utf-8")
                if u.path == "/api/ab":
                    return self._send(200, app.ab.items())
                if u.path == "/api/status":
                    pr = app.priv.recent()
                    allrec = sorted(app.recent() + pr, key=lambda x: x.get("end") or "", reverse=True)
                    at = app.cleared_at()                    # 「잘 끝난 작업 지우기」: 그 시각까지 잘 끝난 것은 목록에서 뺌
                    rec = [r for r in allrec if not _hid(r, at)][:14]
                    rs, pv, q = app.runner_status(), app.priv.state(), app.ordered_queue()
                    try:
                        pl = app.plan_view(rs, pv, q)
                    except Exception as e:
                        pl = {"items": [], "error": str(e)}
                    out = {"runner": rs, "services": app.services(), "queue": q, "recent": rec, "plan": pl,
                           "private": pv, "holding": os.path.exists(app.busy_mark), "cleared_at": at,
                           # 가장 최근에 끝난 작업의 끝 시각 (숨긴 것 포함) = 화면이 '새 작업이 끝났다'를 아는 값. 이름이 아니라 시각이라 개인 작업도 안 샘
                           "recent_top": (allrec[0].get("end") or "") if allrec else ""}
                    if cv:
                        out = mask_private(out)
                        out["stale"] = bool(key) and not keyok        # 옛 화면 -> 화면이 새로 고침
                    return self._send(200, out)
                if u.path == "/api/roots":
                    return self._send(200, [r for r in app.roots() if not (cv and r.get("private"))])
                if u.path == "/api/episodes":
                    return self._send(200, app.episodes(rid))
                if u.path == "/api/flows":
                    return self._send(200, {"flows": app.flows(rid)})
                if u.path == "/api/ep":
                    ep = q.get("ep", "")
                    if not EP_RE.match(ep) or not os.path.isdir(app.ep_dir(ep, rid)):
                        return self._send(404, {"error": "no episode"})
                    return self._send(200, app.episode(ep, rid))
                if u.path == "/api/log":
                    if rid != "0":
                        return self._send(200, {"lines": app.log_tail(q.get("id", ""), logs=os.path.join(app.base(rid), "_nk", "logs"))})
                    return self._send(200, {"lines": app.log_tail(q.get("id", ""))})
                if u.path == "/img":
                    data, ct = app.image(q.get("p", ""), q.get("w"), rid)
                    if data is None:
                        return self._send(404, {"error": "not found"})
                    return self._send(200, data, ct, cache=True)
                return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})

        def do_POST(self):
            # 다른 사이트가 몰래 작업을 넣지 못하게: 이 페이지의 스크립트만 붙이는 머리글 + 이 PC 주소만
            if not self._local() or self.headers.get("X-NK") != "1":
                return self._send(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(min(n, 400000)).decode("utf-8") or "{}")
                u = urllib.parse.urlparse(self.path).path
                if u == "/api/job":
                    args, note, rid = app.make_job(b)
                    return self._send(200, {"ok": True, "name": app.add_job(args, note, rid), "args": args,
                                            "private": rid != "0"})
                if u == "/api/interpret":
                    return self._send(200, app.interpret(b))
                if u == "/api/label":
                    return self._send(200, app.labels.save(b))
                if u == "/api/ab":
                    return self._send(200, app.ab.save(b))
                if u == "/api/cancel":
                    app.cancel(str(b.get("name", "")), str(b.get("root") or "0"))
                    return self._send(200, {"ok": True})
                if u == "/api/resume":
                    return self._send(200, {"ok": True, "name": app.resume_job(str(b.get("name", "")), str(b.get("root") or "0"))})
                if u == "/api/delete":
                    app.delete_job(str(b.get("name", "")), str(b.get("root") or "0"))
                    return self._send(200, {"ok": True})
                if u == "/api/runnow":
                    return self._send(200, {"ok": True, "msg": app.run_now(str(b.get("name", "")), str(b.get("root") or "0"))})
                if u == "/api/check":
                    return self._send(200, app.check_plan(b))
                if u == "/api/kill":
                    return self._send(200, {"ok": True, "job": app.kill_current()})
                if u == "/api/cleardone":
                    return self._send(200, {"ok": True, "at": app.clear_done(bool(b.get("undo")))})
                if u == "/api/runner":
                    return self._send(200, {"ok": True, "msg": app.start_runner()})
                if u == "/api/folders":
                    if b.get("remove"):
                        return self._send(200, app.remove_folder(b["remove"]))
                    return self._send(200, app.add_folder(b.get("path")))
                return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
    return H


class _Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"


def _already_running(port):
    import socket
    try:
        socket.create_connection(("127.0.0.1", port), 0.5).close()
        return True
    except OSError:
        return False


def run(nk, kit, args):
    port = int(getattr(args, "port", None) or PORT)
    if _already_running(port):
        print("[ERROR] 작업실이 이미 켜져 있음 (http://127.0.0.1:%d). 다른 '작업실' 검은 창을 모두 닫은 뒤 다시 켜 주세요." % port)
        print("        (옛 창이 남아 있으면 새로 고친 화면 대신 옛 화면이 나옴)")
        sys.exit(1)
    app = App(nk, kit)
    if app.has_runner:
        st = app.runner_status()
        if not st["alive"] and not getattr(args, "no_runner", False):
            print(app.start_runner())
    else:
        app.worker = Worker(app)
        app.worker.start()
        print("우체통이 없는 폴더 -> 이 화면이 작업을 직접 하나씩 돌림")
    try:
        srv = _Server(("127.0.0.1", port), make_handler(app))
    except OSError:
        print("[ERROR] %d 번 자리가 이미 쓰이는 중 - 작업실이 이미 켜져 있을 수 있음: http://127.0.0.1:%d" % (port, port))
        sys.exit(1)
    app.priv.start()
    url = "http://127.0.0.1:%d" % port
    print("만화 작업실: %s" % url)
    print("  이 창을 닫으면 화면과 작업 줄이 같이 멈춤 (지금 돌던 작업은 다음에 이어서 시작할 수 있음)")
    if not getattr(args, "no_open", False):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    if hasattr(nk, "keep_awake"):
        nk.keep_awake()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def add_parser(esub, nk, kit):
    a = esub.add_parser("web", help="open the comic workshop page in the browser (http://127.0.0.1:8765)")
    a.add_argument("--port", type=int)
    a.add_argument("--no-open", dest="no_open", action="store_true", help="do not open the browser")
    a.add_argument("--no-runner", dest="no_runner", action="store_true", help="do not start nk_remote.py")
    a.set_defaults(func=lambda x: run(nk, kit, x))


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>만화 작업실</title>
<style>
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1f2328;--mute:#6b7078;--line:#e3e1dc;--acc:#2f6fdb;--ok:#1f8a4c;--bad:#c93a3a;--warn:#b7791f;--chip:#efeee9}
@media (prefers-color-scheme: dark){:root{--bg:#16181b;--panel:#1f2226;--ink:#e8e8e6;--mute:#9aa0a6;--line:#30343a;--acc:#6ea0ff;--ok:#4cc27f;--bad:#ff7070;--warn:#e0a84a;--chip:#2a2e33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
h1{font-size:17px;margin:0 12px 0 0}
.chip{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:12.5px;display:inline-flex;gap:6px;align-items:center}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mute)}
.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}.dot.warn{background:var(--warn)}
main{display:grid;grid-template-columns:280px minmax(0,1fr);gap:16px;padding:16px;max-width:1500px;margin:0 auto}
@media (max-width:900px){main{grid-template-columns:minmax(0,1fr)}}
main>div{min-width:0}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:14px}
h2{font-size:14.5px;margin:0 0 8px}
h3{font-size:13.5px;margin:12px 0 6px}
button{font:inherit;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:7px;padding:4px 10px;cursor:pointer}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
button.danger{color:var(--bad)}
button:disabled{opacity:.5;cursor:default}
input,textarea,select{font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 7px}
textarea{width:100%;min-height:120px}
.mute{color:var(--mute)}.bad{color:var(--bad)}.ok{color:var(--ok)}
.eplist a{display:block;padding:6px 8px;border-radius:7px;color:inherit;text-decoration:none}
.eplist a:hover,.eplist a.sel{background:var(--chip)}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.pages{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px}
.pages img{height:260px;border:1px solid var(--line);border-radius:4px;cursor:zoom-in;background:#fff}
.cuts{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.cut{border:1px solid var(--line);border-radius:9px;padding:8px;display:flex;flex-direction:column;gap:6px}
.cut.flag{border-color:var(--bad)}
.cut img{width:100%;height:200px;object-fit:contain;background:var(--bg);border-radius:5px;cursor:zoom-in}
.cut .t{font-weight:600}
.cut .s{font-size:12.5px;color:var(--mute);word-break:break-word}
.cut .f{font-size:12.5px;color:var(--bad)}
.uni{border-top:1px dashed var(--line);padding-top:6px;display:flex;flex-direction:column;gap:5px;font-size:12.5px}
.uni .th{display:flex;gap:6px;flex-wrap:wrap}
.uni .th div{display:flex;flex-direction:column;gap:3px;align-items:center;width:31%;min-width:64px}
.uni .th img{height:60px;width:100%;object-fit:cover}
.uni .th .on{outline:2px solid var(--acc);border-radius:5px}
.fixbox{display:none;flex-direction:column;gap:5px}
.fixbox.open{display:flex}
.q li{margin:3px 0;overflow-wrap:anywhere}
pre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;max-height:260px;overflow:auto;font-size:12px;white-space:pre-wrap}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:20;cursor:zoom-out}
#zoom img{max-width:96vw;max-height:94vh}
#toast{position:fixed;right:16px;bottom:16px;background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:8px;display:none;z-index:30;max-width:70vw}
.steps span{font-size:12px;margin-right:6px}
.viewsw button.on{background:var(--acc);border-color:var(--acc);color:#fff}
#pg-timer{font-variant-numeric:tabular-nums;font-weight:800;font-size:22px;color:var(--acc);margin-left:10px}
#prog.big #pg-timer{font-size:32px}
.ct img{width:100%;height:74px;object-fit:cover;border-radius:6px;margin-top:5px;cursor:zoom-in;background:var(--chip)}
#prog.big .ct img{height:120px}
.qitem{border:1px solid var(--line);border-radius:8px;padding:6px 8px;margin:5px 0;font-size:12.5px;overflow-wrap:anywhere}
.qitem.paused{opacity:.75;border-style:dashed}
.qitem.front{border-color:var(--acc)}
.qitem .row{margin-top:4px;gap:5px}.qitem button{font-size:12px;padding:2px 8px}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;z-index:40}
#modal .mbox{background:var(--panel);border-radius:14px;padding:20px 24px;width:min(640px,92vw);max-height:86vh;overflow:auto;box-shadow:0 12px 50px rgba(0,0,0,.45)}
#modal h2{font-size:20px;margin:0 0 8px}#modal .ok{font-size:22px;font-weight:800}
#modal textarea{min-height:130px;font-size:12.5px}
.tg{cursor:pointer;margin:2px 3px 2px 0;border:1px solid transparent}.tg.off{background:transparent;border-color:var(--bad);color:var(--bad);text-decoration:line-through}
.tgrp{font-size:12.5px;margin:3px 0}.tgrp b{font-weight:600}
.bigpages{display:flex;flex-direction:column;gap:14px;align-items:center}
.bigpages img{width:100%;max-width:920px;border:1px solid var(--line);border-radius:6px;cursor:zoom-in;background:#fff}
.cuts.big{grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
.cuts.big .cut img{height:300px}
.editbox{display:none;flex-direction:column;gap:6px;border-top:1px dashed var(--line);padding-top:6px}
.editbox.open{display:flex}
.editbox textarea{min-height:64px}
.eres{font-size:13px}.eres .hu{font-weight:600}
#prog{max-width:1180px;margin:16px auto 0;padding:0 16px;display:none}
#prog .box{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 22px;box-shadow:0 6px 24px rgba(0,0,0,.12)}
#prog .lab{font-size:12.5px;font-weight:700;letter-spacing:.04em;color:var(--mute);margin:14px 0 6px;text-transform:uppercase}
#prog .ttl{font-size:22px;font-weight:800;margin:2px 0 4px}
#prog .sub{font-size:14.5px;color:var(--mute);margin-bottom:8px}
#prog .allt{font-size:15px;margin:6px 0 0}
.steps2{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px}
.steps2 span{border-radius:999px;padding:4px 12px;font-size:13px;background:var(--chip);color:var(--mute);border:1px solid var(--line)}
.steps2 span.done{background:color-mix(in srgb,var(--ok) 18%,var(--panel));color:var(--ok);border-color:transparent}
.steps2 span.now{background:var(--acc);color:#fff;border-color:transparent;animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{opacity:.7}}
.cutgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:8px}
.ct{border:1px solid var(--line);border-radius:10px;padding:7px 9px;background:var(--bg)}
.ct .h{display:flex;justify-content:space-between;font-size:12.5px;font-weight:700}
.ct .k{font-weight:500;color:var(--mute)}
.ct .st{font-size:11.5px;color:var(--mute);margin-top:4px}
.ct.now{border-color:var(--acc);box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 35%,transparent)}
.ct.done .st{color:var(--ok)}.ct.skip .st{color:var(--bad)}
.bar.mini{height:8px;border-radius:4px;margin-top:5px}.bar.mini>i{border-radius:4px}
.bar.mini>i:after{display:none}.ct.now .bar.mini>i:after{display:block}
.joblist{display:flex;flex-direction:column;gap:6px;margin-top:4px}
.jr{display:grid;grid-template-columns:minmax(0,1fr) 160px 70px;gap:10px;align-items:center;font-size:13.5px}
.jr .bar{height:10px}.jr .bar>i:after{display:none}.jr.run .bar>i:after{display:block}
.jr .t{color:var(--mute);text-align:right;font-size:12.5px}
.clr button{font-size:12px;font-weight:400;letter-spacing:0;text-transform:none;padding:2px 8px;margin-left:8px}.clr button:disabled{opacity:.45;cursor:default}
.clr span{font-size:12px;font-weight:400;letter-spacing:0;text-transform:none;color:var(--mute);margin-left:8px}
.bar{height:22px;background:var(--chip);border-radius:11px;overflow:hidden;position:relative}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--ok));border-radius:11px;transition:width 1s ease;position:relative;overflow:hidden}
.bar>i:after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(45deg,rgba(255,255,255,.25) 0 12px,transparent 12px 24px);animation:barmove 1s linear infinite}
@keyframes barmove{from{background-position:0 0}to{background-position:34px 0}}
.bar>b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12.5px;color:var(--ink)}
.bar.thin{height:12px}
#prog .all{margin-top:12px;font-size:15px}
#prog ol{margin:8px 0 0;padding-left:22px;font-size:13.5px}
#prog ol li{margin:3px 0}
#prog.big .box{position:fixed;inset:4vh 5vw;z-index:15;overflow:auto;box-shadow:0 10px 40px rgba(0,0,0,.35)}
#prog.big .cutgrid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}#prog.big .ct .h{font-size:15px}#prog.big .ct .st{font-size:13.5px}
#prog.big .jr{font-size:17px;grid-template-columns:minmax(0,1fr) 240px 90px}#prog.big .steps2 span{font-size:16px}#prog.big .lab{font-size:15px}
#prog.big .ttl{font-size:30px}#prog.big .sub{font-size:19px}#prog.big .bar{height:34px;border-radius:17px}#prog.big .bar.mini{height:14px;border-radius:7px}#prog.big .jr .bar{height:14px}#prog.big .bar>i{border-radius:17px}
#prog.big .all{font-size:20px}#prog.big ol{font-size:17px}#prog.big .bar>b{font-size:16px}
</style></head><body>
<header>
  <h1>만화 작업실</h1>
  <span class="chip"><span id="d-run" class="dot"></span><span id="t-run">우체통</span></span>
  <span class="chip"><span id="d-comfy" class="dot"></span>ComfyUI</span>
  <span class="chip"><span id="d-ollama" class="dot"></span>검수 AI (Ollama)</span>
  <span id="cur" class="mute"></span>
  <button id="b-kill" class="danger" style="display:none">지금 작업 멈추기</button>
  <button id="b-runner" style="display:none">우체통 켜기</button>
  <a href="/label" style="margin-left:auto">정답 표시 →</a> <a href="/ab">섞어서 비교 →</a>
</header>
<div id="prog"><div class="box">
  <div class="row" style="justify-content:space-between;align-items:flex-start"><div><div class="lab" style="margin-top:0">전체 진행 (지금 + 기다리는 만화)</div><div class="allt" id="pg-all"></div></div><button id="b-big">크게 보기</button></div>
  <div class="bar" style="margin-top:8px"><i id="pg-allbar" style="width:0%"></i><b id="pg-allpct"></b></div>
  <div class="lab">지금 만드는 만화</div>
  <div class="row" style="align-items:baseline"><div class="ttl" id="pg-now"></div><span id="pg-timer" title="이 만화를 만들기 시작한 뒤 지난 시간 (끊었다 이어 온 시간 포함)"></span><button id="b-openrun" style="margin-left:auto;display:none">이 만화 열기 (컷별로 보기)</button></div>
  <div class="sub" id="pg-sub"></div>
  <div class="bar"><i id="pg-bar" style="width:0%"></i><b id="pg-pct"></b></div>
  <div class="steps2" id="pg-steps"></div>
  <div id="pg-cutwrap"><div class="lab">컷마다</div><div class="cutgrid" id="pg-cuts"></div></div>
  <div class="lab clr">작업 목록 <button id="b-clear" title="잘 끝난(✓) 작업을 이 목록과 '최근 결과'에서 숨김. 그림·기록·대기열은 그대로. 실패한 작업은 남음">✓ 잘 끝난 작업 지우기</button><span id="pg-hid"></span></div>
  <div class="joblist" id="pg-list"></div>
  <div class="mute" style="font-size:12px;margin-top:10px">시간은 실측으로 잡은 추정 (8GB 그래픽카드 기준: LoRA 캐릭터 두 명 컷 약 3분 · LoRA 캐릭터 혼자 약 50초 · 다른 컷 약 30초 · 검토 컷당 약 5초). 개인 폴더 작업(🔒)이 먼저 돕니다.</div>
</div></div>
<main>
  <div>
    <section><h2>작업 줄</h2>
      <div id="queue" class="mute">불러오는 중…</div>
      <h3 class="clr">최근 결과 <button id="b-clear2" title="잘 끝난(✓) 작업을 목록에서 숨김. 그림·기록·대기열은 그대로. 실패한 작업은 남음">✓ 잘 끝난 작업 지우기</button><span id="rc-hid"></span></h3><ul id="recent" class="q" style="padding-left:18px;margin:0"></ul>
      <h3>지금 작업 기록</h3><pre id="log">(없음)</pre>
    </section>
    <section><h2>만화 목록</h2>
      <div class="row" style="margin-bottom:6px"><select id="root" style="max-width:100%"></select></div>
      <div class="row" style="margin-bottom:8px"><button id="b-addf">개인 폴더 추가</button><button id="b-rmf" style="display:none">목록에서 빼기</button></div>
      <div id="rootbtns" class="row" style="margin-bottom:6px"></div>
      <div id="rootnote" class="mute" style="font-size:12px;margin-bottom:6px"></div>
      <div id="eps" class="eplist"></div></section>
    <section><h2>새 만화 (AI 답 붙여 넣기)</h2>
      <div class="row" style="margin-bottom:6px"><button id="b-aifile">AI 첨부 파일 만들기</button></div>
      <div class="mute" style="font-size:12.5px;margin-bottom:6px">AI_첨부용.md 를 AI 채팅에 첨부하고 만들고 싶은 만화를 말하면, AI가 계획표(YAML)를 줌. 그 답 전체를 아래에 붙여 넣기.
        ChatGPT·Gemini 같은 아무 AI 채팅이나 됨 (무료판도 됨).</div>
      <details id="req" style="margin-bottom:8px"><summary style="cursor:pointer;font-size:13px"><b>AI 채팅에 보낼 요청 글 만들기</b> (칸을 채우면 복사)</summary>
        <div style="display:grid;gap:4px;margin-top:6px;font-size:12.5px">
          <input id="rq-cast" placeholder="등장 캐릭터 (예: 여우, 토끼)">
          <div class="row"><select id="rq-pages"><option>1</option><option selected>2</option><option>3</option><option>4</option></select><span class="mute">쪽</span>
            <input id="rq-artist" placeholder="작가 태그 (비우면 presets.yaml 의 첫 작가, 그것도 없으면 작가 없음)">
            <select id="rq-mood"><option value="">분위기 (고르기)</option><option>개그</option><option>따뜻한 일상</option><option>모험</option><option>감동</option><option>티격태격</option></select></div>
          <textarea id="rq-story" placeholder="내용 (예: 토끼가 찬 공이 나무에 걸려서 여우가 구하러 올라감)" style="min-height:60px"></textarea>
          <input id="rq-scene" placeholder="꼭 넣을 장면 (없으면 비움, 예: 여우가 나무에서 떨어지는 장면)">
          <input id="rq-tags" placeholder="꼭 넣을 태그 (없으면 비움, 예: 비, 우산)">
          <input id="rq-end" placeholder="끝 반전·마무리 (없으면 비움, 예: 구하러 간 여우가 오히려 구조받음)">
          <label><input type="checkbox" id="rq-first"> 줄거리 먼저 보기 (AI가 줄거리만 먼저 → '좋아'라고 하면 계획표)</label>
          <div class="row"><button id="b-req">요청 글 만들기 + 복사</button></div>
          <textarea id="rq-out" placeholder="여기 만든 글이 나옴 → AI 채팅 새 대화에 AI_첨부용.md 첨부 + 이 글 붙여 넣기" style="min-height:90px"></textarea>
        </div></details>
      <div class="row" style="margin-bottom:6px"><input id="new-ep" placeholder="에피소드 이름" style="width:170px"></div>
      <div class="row" style="margin-bottom:6px"><span class="mute" style="font-size:12.5px">저장할 곳</span><select id="new-root" style="max-width:100%"></select></div>
      <div class="row" style="margin-bottom:6px"><span class="mute" style="font-size:12.5px">그림 워크플로 (옛 NoobAI 흐름만 — 보통 '기본')</span><select id="new-flow" style="max-width:100%"></select></div>
      <textarea id="new-text" placeholder="AI 답 전체"></textarea>
      <div class="row" style="margin-top:6px"><button id="b-check" class="pri">글콘티 검사하기</button><span class="mute" style="font-size:12px">통과하면 바로 작업 줄에, 고칠 점이 있으면 창으로 알려 줌</span></div>
    </section>
  </div>
  <div id="detail"><section><h2>왼쪽에서 만화를 고르세요</h2><div class="mute">작업 줄에 넣은 일은 하나씩 차례로 돕니다.<br>
개인 폴더 작업은 이 화면이 직접 돌리며, 기록도 그 폴더에만 남습니다 (키트 작업 줄은 그동안 잠시 비켜 둡니다).</div></section></div>
</main>
<div id="zoom"><img alt=""></div>
<div id="modal"><div class="mbox" id="mbox"></div></div>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let curEp=null, lastDone=null, curRoot="0", roots=[];
const SHOW_N=5; let allEps=false, testEps=false, allRecent=false, epView="pages";
function toast(m,ms){const t=$("#toast");t.textContent=m;t.style.display="block";clearTimeout(t._h);t._h=setTimeout(()=>t.style.display="none",ms||3500)}
async function get(u){if(window.CV)u+=(u.indexOf("?")<0?"?":"&")+"view=readonly";const r=await fetch(u,window.NKK?{headers:{"X-NK-K":window.NKK}}:{});return r.json()}
async function post(u,b){const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json","X-NK":"1"},body:JSON.stringify(b||{})});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function img(p,w,r){return "/img?root="+encodeURIComponent(r==null?curRoot:r)+"&p="+encodeURIComponent(p)+(w?"&w="+w:"")+(window.NKK?"&k="+window.NKK:"")}
function zoom(p,r){const z=$("#zoom");z.querySelector("img").src=img(p,null,r);z.style.display="flex"}
function fmtT(s){s=Math.max(0,Math.floor(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+":"+String(m).padStart(2,"0"):m)+":"+String(x).padStart(2,"0")}
let tmr={on:false,base:0,t0:0};
setInterval(()=>{const e=$("#pg-timer");if(!e)return;e.textContent=tmr.on?"⏱ "+fmtT(tmr.base+(Date.now()-tmr.t0)/1000):""},1000);
let hidShown=null;
function modal(h){$("#mbox").innerHTML=h;$("#modal").style.display="flex"}
function modalClose(){$("#modal").style.display="none"}
$("#zoom").onclick=()=>$("#zoom").style.display="none";
function argsText(a){return (a||[]).map(x=>/[\\/]/.test(x)?x.split(/[\\/]/).pop():x).join(" ")}
const FLAG_KO=[[/^no candidate passed QA \((.*)\)/,"자동 검수를 통과한 후보가 없어서 가장 나은 것을 씀 ($1)"],[/^compose: /,"두 명 합치기: "],[/^unify: /,"두 명 다시 칠하기: "],[/^story fix applied \(edit seed (\d+): ([^)]*)\) - check the picture.*/,"이야기 맞추기: 그림을 글대로 고쳤음 (시드 $1: $2) - 그림 확인"],[/^story: the picture may not show: (.*?) - a fix is ready.*/,"이야기 맞추기: 그림에 안 보임 - $1 (글대로 고친 후보 준비됨)"],[/^story: the picture may not show: (.*?) \(no clean edit.*/,"이야기 맞추기: 그림에 안 보임 - $1 (깨끗하게 고친 후보 없음)"],[/^story: the picture may not show: (.*?) \(not fixed yet.*/,"이야기 맞추기: 그림에 안 보임 - $1 (아직 안 고침)"],[/figures: (\d+) found, (\d+) expected \(([^)]*)\)[^;]*/,"사람·생물 $1개 (콘티 $2개, 크기 $3) - 작은 형체가 더 있는지 보기"],[/heads: (\d+) found, (\d+) expected/,"머리 $1개 (콘티 $2개)"],[/new figure: (\S+) not in the compose picture/,"다시 칠하며 새 형체가 생김 ($1)"],[/color cast vs compose picture \((\d+)\)/,"색 쏠림 ($1)"],[/^hand (\d+) \((\w+)\): hand is not dark.*/,"손 $1($2): 손 색이 어둡지 않음 - 고친 후보가 준비됨"]];
function flagKo(f){for(const [re,t] of FLAG_KO){if(re.test(f))f=f.replace(re,t)}return f}
function mins(s){if(s==null)return "?";const m=Math.round(s/60);return m<1?"1분 안":m+"분"}
function stepPct(pg){if(!pg)return null;const w={write:2,compile:4,check:6,layout:8};if(pg.step in w)return w[pg.step];
  if(pg.step==="make"||pg.step==null){return pg.total?Math.round(8+82*pg.drawn/pg.total):8}
  return {story:92,letter:95,review:98}[pg.step]||50}
function drawProg(pl){
  const it=pl.items||[], dn=pl.done||[];
  if(!it.length){$("#prog").style.display="none";$("#prog").classList.remove("big");return}
  $("#prog").style.display="block";
  const c=it.find(x=>x.running)||it[0], pg=c.progress, det=c.detail, KO={write:"이야기",compile:"계획표 검사",check:"검사",layout:"칸 나누기",make:"그리기",story:"이야기 맞추기",letter:"말풍선",review:"검토"};
  // ① 전체
  const n=it.length, fin=pl.finish_at, ap=pl.batch_frac!=null?Math.round(100*pl.batch_frac):0;
  $("#pg-all").innerHTML="남은 작업 <b>"+n+"개</b> · 전부 약 <b>"+mins(pl.total_remain_s)+"</b>"+(fin?" → <b>"+fin+"</b>쯤 끝":"")+" <span class='mute'>(추정)</span>"+(pl.unknown?" <span class='mute'>· 시간 모르는 작업 "+pl.unknown+"개</span>":"")+(dn.length?" <span class='mute'>· 이번 묶음에서 끝남 "+dn.length+"개</span>":"");
  $("#pg-allbar").style.width=ap+"%";$("#pg-allpct").textContent=ap+"%";
  // ② 지금 만화
  $("#pg-now").textContent=(c.running?"":"다음: ")+(c.private?"🔒 ":"")+c.name;
  const nb=c.elapsed_total_s!=null?c.elapsed_total_s:(c.elapsed_s||0), shown=tmr.on&&tmr.job===c.job?tmr.base+(Date.now()-tmr.t0)/1000:0;
  tmr={on:!!c.running,base:Math.max(nb,shown<nb+30?shown:0),t0:Date.now(),job:c.job};      // 같은 작업이면 뒤로 가지 않게 (서버 값이 조금 늦음)
  runEp=(c.running&&det&&det.ep)?{ep:det.ep,root:det.root||"0"}:null;
  $("#b-openrun").style.display=runEp?"":"none";
  let pct=det?Math.round(100*det.frac):stepPct(pg); if(pct==null&&c.running&&c.est_s)pct=Math.min(95,Math.round(100*(c.elapsed_s||0)/c.est_s));
  const nowStep=det?(det.steps.find(x=>x.state==="now")||{}).name:(pg?(KO[pg.step]||pg.step):null);
  $("#pg-sub").textContent=c.running?((nowStep?nowStep+" 중":"도는 중")+" · 이 만화 약 "+mins(c.remain_s)+" 남음 (추정)"):"기다리는 중";
  $("#pg-bar").style.width=(pct||0)+"%";$("#pg-pct").textContent=pct!=null?pct+"%":"";
  $("#pg-steps").innerHTML=det?det.steps.map(x=>"<span class='"+x.state+"'>"+(x.state==="done"?"✓ ":x.state==="now"?"▶ ":"")+esc(x.name)+(x.of?" "+x.n+"/"+x.of:"")+"</span>").join(""):"";
  // ③ 컷마다
  const SK={wait:"대기",draw:"그리는 중",base:"밑그림",mask:"LoRA 캐릭터·상대 자리 찾기",paint:"칠하는 중",drawn:"얼굴 다듬기 대기",face:"얼굴 다듬는 중",done:"완료",skip:"건너뜀 (확인 필요)"}, KK={duo:"두 명",lora:"LoRA 캐릭터",other:"배경·상대"};
  const cuts=det?det.cuts:[];
  $("#pg-cutwrap").style.display=cuts.length?"":"none";
  $("#pg-cuts").innerHTML=cuts.map(x=>{const on=!["wait","done","skip","drawn"].includes(x.stage);return "<div class='ct "+(on?"now":x.stage)+"'><div class='h'><span>컷 "+x.id+"</span><span class='k'>"+KK[x.kind]+"</span></div><div class='bar mini'><i style='width:"+Math.round(100*x.frac)+"%'></i></div><div class='st'>"+(x.stage==="done"?"✓ ":"")+SK[x.stage]+"</div>"+
    (x.img?"<img loading='lazy' src='"+img(x.img,260,det.root||"0")+"&t="+x.mtime+"' data-zp='"+esc(x.img)+"' alt=''>":"")+"</div>"}).join("");
  document.querySelectorAll("[data-zp]").forEach(i=>i.onclick=()=>zoom(i.dataset.zp,(det&&det.root)||"0"));
  // 작업 목록 (끝난 것 + 지금 + 기다리는 것)
  $("#b-clear").disabled=!dn.some(x=>x.ok&&!x.hid);
  const rows=dn.filter(x=>!x.hid).map(x=>"<div class='jr'><span>"+(x.ok?"✓ ":"✗ ")+(x.private?"🔒 ":"")+esc(x.name)+(x.error?"<div class='bad' style='font-size:12px'>"+esc(x.error)+"</div>":"")+"</span><div class='bar'><i style='width:100%;"+(x.ok?"":"background:var(--bad)")+"'></i></div><span class='t'>"+(x.ok?"끝 "+esc(x.end):"실패")+"</span></div>")
    .concat(it.map(x=>{const p=x.running?(x.detail?Math.round(100*x.detail.frac):(stepPct(x.progress)||0)):0;return "<div class='jr"+(x.running?" run":"")+"'><span>"+(x.running?"▶ ":"")+(x.private?"🔒 ":"")+esc(x.name)+(x.held?" <span class='mute'>(잠시 비킴)</span>":"")+"</span><div class='bar'><i style='width:"+p+"%'></i></div><span class='t'>약 "+mins(x.remain_s)+"</span></div>"}));
  const pz=(pl.paused||[]).map(x=>"<div class='jr' style='opacity:.7'><span>⏸ "+(x.private?"🔒 ":"")+esc(x.name)+" <span class='mute'>(멈춤 — 작업 줄에서 '이어서 시작')</span></span><div class='bar'><i style='width:0%'></i></div><span class='t'>멈춤</span></div>");
  $("#pg-list").innerHTML=rows.concat(pz).join("");
  // 지금 만드는 만화를 열어 두었으면 (컷별로 보기) 15초마다 새로 — 글을 적는 중이면 건드리지 않음
  if(runEp&&curEp===runEp.ep&&curRoot===runEp.root&&Date.now()-lastFollow>15000&&!document.querySelector(".editbox.open,.fixbox.open")){lastFollow=Date.now();loadEp(curEp,true)}
}
let runEp=null,lastFollow=0;
$("#b-openrun").onclick=async()=>{if(!runEp)return;curRoot=runEp.root;$("#root").value=curRoot;$("#new-root").value=curRoot;testEps=true;await loadRoots();epView="cuts";await loadEp(runEp.ep);lastFollow=Date.now();$("#detail").scrollIntoView({behavior:"smooth",block:"start"})};
async function refresh(){
  let s; try{s=await get("/api/status")}catch(e){$("#t-run").textContent="화면 서버 연결 끊김";return}
  if(s.stale&&!window.CV){$("#t-run").textContent="작업실이 다시 켜짐 — 화면 새로 고치는 중";setTimeout(()=>location.reload(),800);return}
  const r=s.runner, sv=s.services;
  $("#d-run").className="dot "+(r.alive?(r.job?"warn":"ok"):"bad");
  $("#t-run").textContent=r.alive?(r.job?"우체통: 작업 중":"우체통: 쉬는 중"):"우체통: 꺼짐";
  $("#b-runner").style.display=(!r.alive&&r.mode==="runner")?"":"none";
  $("#d-comfy").className="dot "+(sv.comfy?"ok":"bad");
  $("#d-ollama").className="dot "+(sv.ollama?"ok":"bad");
  const pv=s.private||{};
  const pg=r.progress, STEP_KO={write:"이야기",compile:"콘티",check:"검사",layout:"칸 나누기",make:"그리기",story:"이야기 맞추기",letter:"말풍선",review:"검토"};
  const pgt=pg?(" — "+String(pg.ep)+" "+(pg.step?(STEP_KO[pg.step]||pg.step)+" 단계":"준비")+(pg.total?" · 컷 "+pg.drawn+"/"+pg.total:"")+(pg.eta_s!=null?" · 약 "+Math.max(1,Math.round(pg.eta_s/60))+"분 남음 (추정)":"")):"";
  $("#cur").textContent=pv.job?("🔒 개인 작업 "+pv.job+" · "+Math.round((pv.elapsed_s||0)/60)+"분째"):((r.alive&&r.job)?(r.job+" · "+Math.round((r.elapsed_s||0)/60)+"분째"+pgt):"")+(pv.wait?"  ·  🔒 "+pv.wait:"");
  $("#b-kill").style.display=(pv.job||(r.alive&&r.job))?"":"none";
  drawProg(s.plan||{});
  const q=s.queue;
  $("#queue").innerHTML=(s.holding?"<div class='mute' style='font-size:12px;margin-bottom:4px'>개인 작업 동안 키트 작업 줄은 잠시 비켜 둠 (끝나면 자동으로 되돌림)</div>":"")+(q.length?q.map(j=>"<div class='qitem"+(j.paused?" paused":"")+(j.front?" front":"")+"'>"+(j.paused?"<b>⏸ 멈춤</b> ":(j.front?"<b>▶ 먼저</b> ":""))+(j.private?"<b>🔒 개인</b> ":(j.mine?"<b>내 작업</b> ":"<span class='mute'>밖에서 넣음</span> "))+(j.held&&!j.paused?"<span class='mute'>(잠시 비킴)</span> ":"")+esc(argsText(j.args))+
      "<div class='mute' style='font-size:12px'>"+esc(j.note||"")+"</div><div class='row'>"+
      (j.paused?"<button class='pri' data-res='"+esc(j.name)+"' data-r='"+esc(j.root)+"'>이어서 시작</button><button class='danger' data-del='"+esc(j.name)+"' data-r='"+esc(j.root)+"'>대기열 삭제</button>"
               :"<button data-now='"+esc(j.name)+"' data-r='"+esc(j.root)+"' title='지금 만들던 만화를 멈추고 이것부터. 끝나면 멈춘 만화를 이어서'>바로 만들기</button><button data-c='"+esc(j.name)+"' data-r='"+esc(j.root)+"' title='지우지 않고 멈춰 둠 (이어서 시작 / 대기열 삭제)'>취소</button>")+
      "</div></div>").join(""):"<span class='mute'>기다리는 작업 없음</span>");
  const qpost=async(u,b,msg)=>{try{const r=await post(u,b);toast(r.msg||msg,6000);refresh()}catch(e){toast("안 됨: "+e.message,7000)}};
  document.querySelectorAll("[data-now]").forEach(b=>b.onclick=()=>{if(confirm("이 작업을 바로 만들까요?\n지금 만들던 만화는 멈췄다가, 이 작업이 끝나면 이어서 만듭니다."))qpost("/api/runnow",{name:b.dataset.now,root:b.dataset.r},"바로 만들기")});
  document.querySelectorAll("[data-res]").forEach(b=>b.onclick=()=>qpost("/api/resume",{name:b.dataset.res,root:b.dataset.r},"작업 줄 맨 아래에 다시 넣음"));
  document.querySelectorAll("[data-del]").forEach(b=>b.onclick=()=>{if(confirm("이 작업을 대기열에서 완전히 지울까요? (이미 그린 그림은 안 지워짐)"))qpost("/api/delete",{name:b.dataset.del,root:b.dataset.r},"대기열에서 지움")});
  document.querySelectorAll("[data-c]").forEach(b=>b.onclick=()=>qpost("/api/cancel",{name:b.dataset.c,root:b.dataset.r},"멈춰 둠 — '이어서 시작'이나 '대기열 삭제'를 고를 수 있어"));
  $("#recent").innerHTML=(allRecent?s.recent:s.recent.slice(0,SHOW_N)).map(x=>"<li><span class='"+(x.rc===0?"ok":"bad")+"'>"+(x.rc===0?"✓":(x.killed?"■":"✗"))+"</span> "+(x.private?"🔒 ":"")+esc(argsText(x.args))+" <span class='mute'>"+esc((x.end||"").slice(5,16))+(x.secs!=null?" · "+Math.round(x.secs/60)+"분":"")+"</span>"+(x.error?"<div class='bad' style='font-size:12px'>"+esc(x.error)+"</div>":"")+"</li>").join("")+
    (s.recent.length>SHOW_N?"<li style='list-style:none;margin-left:-18px'><button id='b-allrecent' style='font-size:12px'>"+(allRecent?"접기":"더 보기 ("+(s.recent.length-SHOW_N)+"개)")+"</button></li>":"");
  if($("#b-allrecent"))$("#b-allrecent").onclick=()=>{allRecent=!allRecent;refresh()};
  const hidT=s.cleared_at?"<span>"+esc(s.cleared_at.slice(11,16))+" 까지 잘 끝난 작업은 숨김</span><button data-unclear='1'>다시 보기</button>":"";
  if(hidShown!==hidT){hidShown=hidT;$("#pg-hid").innerHTML=hidT;$("#rc-hid").innerHTML=hidT;      // 바뀔 때만 다시 그림 (누르는 순간 버튼이 새로 그려져 눌림이 씹히지 않게)
    document.querySelectorAll("[data-unclear]").forEach(b=>b.onclick=()=>clearDone(true))}
  $("#b-clear2").disabled=!s.recent.some(x=>x.rc===0);
  if(pv.job){const l=await get("/api/log?root="+encodeURIComponent(pv.root)+"&id="+encodeURIComponent(pv.job));$("#log").textContent=(l.lines||[]).slice(-25).join("\n")}
  else if(r.alive&&r.job){const l=await get("/api/log?id="+encodeURIComponent(r.job));$("#log").textContent=(l.lines||[]).slice(-25).join("\n")}
  else $("#log").textContent="(없음)";
  const top=s.recent_top!==undefined?s.recent_top:(s.recent[0]&&s.recent[0].id);      // 숨긴 작업까지 쳐서 가장 최근에 끝난 것 (지우기를 눌러도 안 바뀜)
  if(lastDone&&top!==lastDone&&curEp){loadEp(curEp,true)}
  lastDone=top;
}
async function loadRoots(){
  roots=await get("/api/roots");
  const opt=roots.map(x=>"<option value='"+esc(x.id)+"'>"+(x.private?"🔒 ":"")+esc(x.name)+"</option>").join("");
  $("#root").innerHTML=opt; $("#new-root").innerHTML=opt;
  if(!roots.find(x=>x.id===curRoot)) curRoot="0";
  $("#root").value=curRoot; $("#new-root").value=curRoot;
  const cr=roots.find(x=>x.id===curRoot);
  $("#b-rmf").style.display=(cr&&cr.private)?"":"none";
  const fname=x=>String(x.path||"").replace(/[\\/]+$/,"").split(/[\\/]/).pop()||("개인 폴더 "+x.id);
  const pv=roots.filter(x=>x.private), dup=n=>pv.filter(y=>fname(y)===n).length>1;
  $("#rootbtns").innerHTML=roots.map(x=>"<button data-rf='"+esc(x.id)+"' title='"+esc(x.private?"🔒 "+x.path+" — ":"")+"이 폴더를 다시 읽어 만화 목록을 새로 (지운 만화는 사라지고 새 만화는 보임)'>↻ "+(x.private?"🔒 "+esc(fname(x))+(dup(fname(x))?" ("+esc(x.id)+")":""):"키트 폴더")+" 다시 읽기</button>").join("");
  document.querySelectorAll("[data-rf]").forEach(b=>b.onclick=async()=>{curRoot=b.dataset.rf;$("#root").value=curRoot;$("#new-root").value=curRoot;allEps=false;await loadRoots();const e=await loadEps();
    if(curEp&&!(e||[]).find(x=>x.ep===curEp)){curEp=null;$("#detail").innerHTML="<section><h2>왼쪽에서 만화를 고르세요</h2><div class='mute'>보던 만화가 이 폴더에 없어 (지워졌거나 다른 폴더)</div></section>"}else if(curEp){loadEp(curEp,true)}
    toast("폴더를 다시 읽었어: 만화 "+(e||[]).length+"편")});
  $("#rootnote").textContent=(cr&&cr.private)?"이 폴더의 만화·기록은 그 폴더 안에만 저장됩니다.":"키트 폴더: 만화는 키트의 episodes 폴더에 저장됩니다.";
}
$("#root").onchange=()=>{curRoot=$("#root").value;curEp=null;$("#new-root").value=curRoot;loadRoots();loadEps();$("#detail").innerHTML="<section><h2>왼쪽에서 만화를 고르세요</h2></section>"};
$("#b-addf").onclick=async()=>{const p=prompt("개인 폴더 전체 경로 (예: C:\\my_comics). 없으면 새로 만듭니다.");if(!p)return;try{await post("/api/folders",{path:p});toast("추가함: "+p);curRoot=String(roots.length);await loadRoots();loadEps()}catch(e){toast("안 됨: "+e.message,7000)}};
$("#b-rmf").onclick=async()=>{if(!confirm("이 폴더를 목록에서만 뺄까요? (폴더와 그림은 그대로 남음)"))return;try{await post("/api/folders",{remove:curRoot});curRoot="0";await loadRoots();loadEps()}catch(e){toast(e.message)}};
async function loadEps(){
  const e0=await get("/api/episodes?root="+encodeURIComponent(curRoot));
  const nTest=e0.filter(x=>x.test).length, e1=e0.filter(x=>testEps||!x.test), e=allEps?e1:e1.slice(0,SHOW_N);
  $("#eps").innerHTML=e.map(x=>"<a href='#' data-ep='"+esc(x.ep)+"' class='"+(x.ep===curEp?"sel":"")+"'><b>"+esc(x.ep)+"</b> "+esc(x.title)+(x.pages?" <span class='mute'>· "+x.pages+"쪽</span>":"")+(x.test?" <span class='mute'>(시험)</span>":"")+"</a>").join("")+
    (e1.length?"":"<div class='mute' style='font-size:12.5px'>아직 만화 없음</div>")+
    "<div class='row' style='margin-top:4px;font-size:12px'>"+(e1.length>SHOW_N?"<button id='b-alleps'>"+(allEps?"접기":"더 보기 ("+(e1.length-SHOW_N)+"개)")+"</button>":"")+
    (nTest?"<button id='b-testeps'>"+(testEps?"시험 편 숨기기":"시험 편 보기 ("+nTest+"개)")+"</button>":"")+"</div>";
  document.querySelectorAll("[data-ep]").forEach(a=>a.onclick=ev=>{ev.preventDefault();loadEp(a.dataset.ep)});
  if($("#b-alleps"))$("#b-alleps").onclick=()=>{allEps=!allEps;loadEps()};
  if($("#b-testeps"))$("#b-testeps").onclick=()=>{testEps=!testEps;loadEps()};
  return e0;
}
async function job(b,msg){if(b.root==null)b.root=curRoot;try{const j=await post("/api/job",b);toast((j.private?"🔒 개인 작업 줄에 넣음":(msg||"작업 줄에 넣음"))+": "+argsText(j.args),5000);refresh()}catch(e){toast("안 됨: "+e.message,6000)}}
function chips(id,scope,tags){return (tags||[]).map(t=>"<span class='chip tg' data-tg='"+id+"' data-sc='"+esc(scope)+"' data-tag='"+esc(t)+"'>"+esc(t)+"</span>").join("")||"<span class='mute'>(없음)</span>"}
function tagBox(c){const t=c.tags;if(!t)return "<div class='mute' style='font-size:12px'>계획표가 없는 만화라 지금 태그를 못 보여 줘</div>";
  const duo=(t.who||[]).length>=2;
  let h="<div class='tgrp'><b>"+(duo?"두 사람 공통":"이 컷")+"</b> "+chips(c.id,"",t.common)+"</div>";
  if(duo)Object.entries(t.roles||{}).forEach(([w,ts])=>{h+="<div class='tgrp'><b>"+esc(w)+"만</b> "+chips(c.id,"who:"+w,ts)+"</div>"});
  if(t.loc)h+="<div class='tgrp'><b>배경</b> <span class='mute'>(장소 "+esc(t.loc)+" — 이 장소의 모든 컷이 같이 씀)</span> "+chips(c.id,"loc",t.loc_tags)+"</div>";
  Object.entries(t.props||{}).forEach(([n,ts])=>{h+="<div class='tgrp mute'><b>소품 "+esc(n)+"</b> "+(ts||[]).map(esc).join(", ")+" <span>(여러 컷이 같이 써서 여기선 못 고침)</span></div>"});
  if(t.sentence)h+="<div class='tgrp mute'><b>동작 문장</b> "+esc(t.sentence)+"</div>";
  return h+"<div class='mute' style='font-size:12px'>캐릭터 겉모습(옷·무늬)은 캐릭터 파일에서 자동으로 붙어서 여기 없음</div>"}
function whereOpts(c){const t=c.tags||{}, duo=(t.who||c.who||[]).length>=2;
  return "<option value=''>"+(duo?"두 사람 공통":"이 컷")+"</option>"+(duo?(t.who||c.who||[]).map(w=>"<option value='who:"+esc(w)+"'>"+esc(w)+"만</option>").join(""):"")+(t.loc?"<option value='loc'>배경 (장소 "+esc(t.loc)+")</option>":"")}
function uniBox(c,anima){
  if(anima||!c.duo||!c.img)return "";
  const u=c.unify;
  let h="<div class='uni'><div class='row'><span class='mute'>두 명 다시 칠하기</span><select data-udn='"+c.id+"'><option selected>0.4</option><option>0.45</option><option>0.5</option><option>0.55</option></select>"+
    "<button data-uni='"+c.id+"'>후보 만들기</button></div>";
  if(u){
    const items=(u.orig?[{seed:0,img:u.orig,mtime:0}]:[]).concat(u.cands);
    h+="<div class='th'>"+items.map(x=>"<div class='"+(u.use===x.seed||(!u.use&&x.seed===0)?"on":"")+"'><img loading='lazy' src='"+img(x.img,300)+"&t="+Math.round(x.mtime)+"' data-z='"+esc(x.img)+"' alt=''>"+
      (u.use===x.seed||(!u.use&&x.seed===0)?"<span class='ok'>지금 씀</span>":"<button data-uuse='"+c.id+":"+x.seed+"'>"+(x.seed?"이걸로":"합친 그림")+"</button>")+((x.flags||[]).length?"<span class='bad' title='"+esc(x.flags.join("; "))+"'>흠 "+x.flags.length+"</span>":"")+"</div>").join("")+"</div>"+
      (u.use?"":(!u.orig?"<div class='mute'>지금 = 합친 그림</div>":""))+
      "<div class='mute'>바꾼 뒤 '이어서 만들기'를 restyle부터 (그림체판·말풍선)</div>";
  }
  return h+"</div>";
}
async function loadEp(ep,keep){
  curEp=ep; if(!keep) loadEps();
  const d=await get("/api/ep?root="+encodeURIComponent(curRoot)+"&ep="+encodeURIComponent(ep));
  if(d.error){$("#detail").innerHTML="<section class='bad'>"+esc(d.error)+"</section>";return}
  const st=Object.entries(d.state||{}).map(([k,v])=>"<span class='"+(v[0]==="done"?(v[1]===0?"ok":"bad"):"mute")+"'>"+esc(k)+"</span>").join("");
  let h="<section><div class='row' style='justify-content:space-between'><h2 style='margin:0'>"+esc(d.ep)+" · "+esc(d.title)+"</h2><div class='row'>"+
    "<button class='pri' id='b-auto'>이어서 만들기</button><select id='s-from'><option value=''>(안 된 단계부터)</option>"+(d.anima?["make","story","letter","review"]:["make","propfix","facefix","compose","unify","story","handfix","backfix","restyle","letter","review"]).map(x=>"<option>"+x+"</option>").join("")+"</select>"+
    "<button id='b-letter'>말풍선 다시</button>"+(d.pdf?"<a href='"+img(d.pdf)+"' target='_blank'><button>PDF</button></a>":"")+(d.review?"<button id='b-review'>검토 한 장</button>":"")+"</div></div>"+
    "<div class='mute' style='margin:4px 0'>작가 "+esc(d.artist||"-")+" · 그림체 입히기 "+esc(d.restyle||"없음")+"</div>"+
    (d.anima?"":"<div class='row mute' style='margin:4px 0;font-size:12.5px'>그림 워크플로 <select id='s-flow'>"+["none"].concat(d.flows||[]).map(f=>"<option value='"+esc(f)+"'"+((d.flow||"none")===f?" selected":"")+">"+(f==="none"?"기본 (nk 그리기)":esc(f))+"</option>").join("")+"</select>"+
    (d.flow&&(d.flows||[]).indexOf(d.flow)<0?"<span class='bad'>파일 없음: "+esc(d.flow)+"</span>":"")+"<span>혼자 컷만 · 바꾼 뒤 '이어서 만들기'를 make부터</span></div>")+
    "<div class='steps'>"+st+"</div>"+
    (d.fix_prompt?"<div class='fixp' style='margin-top:8px;padding:8px;border:1px solid #d9a441;border-radius:6px'><b>AI에게 돌려줄 고칠 점</b> <button id='b-fixcopy'>복사</button>"+
      "<div class='mute' style='font-size:12.5px'>AI 채팅의 같은 대화에 붙여 넣고 → 새 답을 '새 만화'에 다시 붙여 넣기 (아직 안 그렸으면 같은 이름, 이미 그렸으면 새 이름). 안 고치고 그대로 만들어도 됨 ('이어서 만들기').</div>"+
      "<pre style='white-space:pre-wrap;margin:6px 0 0'>"+esc(d.fix_prompt)+"</pre></div>":"");
  if(!d.pages.length&&epView==="pages")epView="cuts";
  h+="<div class='row viewsw' style='margin-top:10px'><button id='v-pages' class='"+(epView==="pages"?"on":"")+"'"+(d.pages.length?"":" disabled")+">전체 만화 보기</button><button id='v-cuts' class='"+(epView==="cuts"?"on":"")+"'>컷별로 보기 ("+d.cuts.length+")</button></div>";
  h+="</section>";
  h+="<section id='sec-pages' style='display:"+(epView==="pages"?"block":"none")+"'>"+(d.pages.length?"<div class='bigpages'>"+d.pages.map(p=>"<img loading='lazy' src='"+img(p,1400)+"' data-z='"+esc(p)+"' alt='page'>").join("")+"</div>":"<div class='mute'>아직 쪽 그림이 없음</div>")+"</section>";
  h+="<section id='sec-cuts' style='display:"+(epView==="cuts"?"block":"none")+"'><h2>컷 ("+d.cuts.length+")</h2><div class='cuts big'>"+d.cuts.map(c=>{
    const who=(c.who||[]).join("+")||"사람 없음";
    return "<div class='cut"+(c.flags.length?" flag":"")+"'>"+(c.img?"<img loading='lazy' src='"+img(c.img,500)+"&t="+Math.round(c.mtime)+"' data-z='"+esc(c.img)+"' alt='cut'>":"<div class='mute' style='height:200px;display:flex;align-items:center;justify-content:center'>아직 없음</div>")+
      "<div class='t'>"+c.id+"번 · "+esc(who)+" · "+esc(c.shot||"")+(c.duo?" · 두 명":"")+"</div>"+
      "<div class='s'>"+esc(c.action||c.scene||"")+(c.roles?"<br>"+Object.entries(c.roles).map(([k,v])=>esc(k)+": "+esc(v)).join("<br>"):"")+"</div>"+
      (c.lines.length?"<div class='s'>“"+c.lines.map(esc).join("” “")+"”</div>":"")+
      c.flags.map(f=>"<div class='f' title='"+esc(f)+"'>"+esc(flagKo(f))+"</div>").join("")+uniBox(c,d.anima)+
      ((c.cands||[]).length?"<div class='th'>"+c.cands.map(x=>"<div><img loading='lazy' src='"+img(x.img,300)+"&t="+Math.round(x.mtime)+"' data-z='"+esc(x.img)+"' alt=''><button data-ucand='"+c.id+":"+esc(x.name)+"'>이걸로</button></div>").join("")+"</div><div class='mute' style='font-size:12px'>후보 (새 시드) — '이걸로'를 누르면 그 그림으로 바꾸고 말풍선을 다시 넣음</div>":"")+
      (d.has_plan?"<div class='row'><button class='pri' data-edit='"+c.id+"'>수정하기</button><span class='mute' style='font-size:12px'>말로 적으면 이 PC 의 AI(Ollama)가 해석</span></div>"+
        "<div class='editbox' id='ed"+c.id+"'><textarea data-etext='"+c.id+"' placeholder='어떻게 고칠지 말로 적기 — 예: 주인공 배만 다시 그려 줘 / 토끼 손 고쳐 줘 / 우산 빼고 웃는 얼굴로 / 그냥 다시 그려 줘'></textarea>"+
        "<div class='row'><button data-einterp='"+c.id+"'>해석하기</button></div><div class='eres' id='er"+c.id+"'></div></div>":"")+
      "<div class='row'><button data-redo='"+c.id+"' title='같은 글, 새 시드로 이 컷만 다시 (누를 때마다 다른 그림)'>다시 그리기</button>"+(d.anima?"<button data-cands='"+c.id+"' title='새 시드로 3장 그려 두고 고르기 (지금 그림은 고를 때까지 그대로)'>후보 3장</button>":"")+"<button data-open='"+c.id+"'>태그 고치기</button>"+(c.raw&&c.raw!==c.img?"<button data-raw='"+esc(c.raw)+"'>원본</button>":"")+"</div>"+
      "<div class='fixbox' id='fx"+c.id+"'>"+tagBox(c)+"<input placeholder='더할 태그 (예: rain, umbrella)' data-add='"+c.id+"'><input placeholder='뺄 태그 (위 태그를 누르면 들어감)' data-rem='"+c.id+"'>"+
      "<div class='row'><span class='mute' style='font-size:12px'>어디에 적용</span><select data-where='"+c.id+"'>"+whereOpts(c)+"</select></div>"+
      "<button class='pri' data-fix='"+c.id+"'>고쳐서 다시 그리기</button></div></div>"}).join("")+"</div></section>";
  $("#detail").innerHTML=h;
  document.querySelectorAll("[data-z]").forEach(i=>i.onclick=()=>zoom(i.dataset.z));
  document.querySelectorAll("[data-raw]").forEach(b=>b.onclick=()=>zoom(b.dataset.raw));
  if(d.review)$("#b-review").onclick=()=>zoom(d.review);
  if(d.fix_prompt)$("#b-fixcopy").onclick=async()=>{try{await navigator.clipboard.writeText(d.fix_prompt);toast("복사함 — AI 채팅의 같은 대화에 붙여 넣기")}catch(e){toast("복사 안 됨 — 글을 직접 드래그해서 복사",6000)}};
  $("#b-auto").onclick=()=>job({kind:"auto",ep:ep,from:$("#s-from").value});
  $("#b-letter").onclick=()=>job({kind:"letter",ep:ep});
  if($("#s-flow"))$("#s-flow").onchange=()=>job({kind:"setflow",ep:ep,flow:$("#s-flow").value},"그림 워크플로 바꾸기");
  $("#v-pages").onclick=()=>{epView="pages";loadEp(ep,true)};$("#v-cuts").onclick=()=>{epView="cuts";loadEp(ep,true)};
  document.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>$("#ed"+b.dataset.edit).classList.toggle("open"));
  document.querySelectorAll("[data-einterp]").forEach(b=>b.onclick=async()=>{const id=b.dataset.einterp, box=$("#er"+id), text=document.querySelector("[data-etext='"+id+"']").value.trim();
    if(!text){toast("어떻게 고칠지 먼저 적어 줘");return}
    box.innerHTML="<span class='mute'>이 PC 의 AI(Ollama)가 읽는 중… (그림을 그리는 중이면 10~60초)</span>";b.disabled=true;
    try{const r=await post("/api/interpret",{root:curRoot,ep:ep,cut:+id,text:text});
      if(r.error){box.innerHTML="<span class='bad'>"+esc(r.error)+"</span>";return}
      box.innerHTML="<div class='hu'>이렇게 이해했어: "+esc(r.human)+"</div>"+(r.warnings||[]).map(w=>"<div class='bad' style='font-size:12px'>⚠ "+esc(w)+"</div>").join("")+
        (r.job?"<div class='row' style='margin-top:4px'><button class='pri' id='ego"+id+"'>이대로 실행</button><span class='mute' style='font-size:12px'>아니면 글을 고쳐서 다시 '해석하기'</span></div>":"");
      if(r.job)$("#ego"+id).onclick=()=>{job(Object.assign({ep:ep},r.job),"수정 작업을 줄에 넣음");box.innerHTML="<span class='ok'>작업 줄에 넣었어 — 끝나면 이 컷이 바뀌어 (부위 수정은 후보가 생김)</span>"};
    }catch(e){box.innerHTML="<span class='bad'>안 됨: "+esc(e.message)+"</span>"}finally{b.disabled=false}});
  document.querySelectorAll("[data-redo]").forEach(b=>b.onclick=()=>job({kind:"fix",ep:ep,cut:+b.dataset.redo}));
  document.querySelectorAll("[data-cands]").forEach(b=>b.onclick=()=>job({kind:"cands",ep:ep,cut:+b.dataset.cands},"후보 3장 (지금 그림은 그대로)"));
  document.querySelectorAll("[data-ucand]").forEach(b=>b.onclick=()=>{const [id,nm]=b.dataset.ucand.split(":");job({kind:"usecand",ep:ep,cut:+id,name:nm})});
  document.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>$("#fx"+b.dataset.open).classList.toggle("open"));
  document.querySelectorAll("[data-uni]").forEach(b=>b.onclick=()=>{const id=b.dataset.uni;
    job({kind:"unify",ep:ep,cut:+id,denoise:document.querySelector("[data-udn='"+id+"']").value,seed:71+Math.floor(Math.random()*900)},"다시 칠하기 후보 (최종본은 그대로)")});
  document.querySelectorAll("[data-uuse]").forEach(b=>b.onclick=()=>{const [id,sd]=b.dataset.uuse.split(":");job({kind:"unifyuse",ep:ep,cut:+id,seed:+sd})});
  document.querySelectorAll("[data-tg]").forEach(t=>t.onclick=()=>{const [id,scope]=[t.dataset.tg,t.dataset.sc], sel=document.querySelector("[data-where='"+id+"']"), inp=document.querySelector("[data-rem='"+id+"']");
    if(sel.value!==scope){sel.value=scope;inp.value="";document.querySelectorAll("[data-tg='"+id+"'].off").forEach(x=>x.classList.remove("off"))}      // 한 번에 한 곳만 고침
    t.classList.toggle("off");
    inp.value=[...document.querySelectorAll("[data-tg='"+id+"'].off")].map(x=>x.dataset.tag).join(", ")});
  document.querySelectorAll("[data-fix]").forEach(b=>b.onclick=()=>{const id=b.dataset.fix;
    const add=document.querySelector("[data-add='"+id+"']").value, rem=document.querySelector("[data-rem='"+id+"']").value;
    const wh=(document.querySelector("[data-where='"+id+"']")||{}).value||""; if(!add.trim()&&!rem.trim()){toast("더할 태그나 뺄 태그를 적어 주세요");return}
    if(wh==="loc"&&!confirm("배경(장소) 태그는 같은 장소의 다른 컷도 같이 씁니다.\n이 컷만 다시 그리고, 다른 컷은 다시 그릴 때 바뀐 배경으로 그려집니다. 계속할까요?"))return;
    job({kind:"fix",ep:ep,cut:+id,add:add,remove:rem,who:wh.startsWith("who:")?wh.slice(4):"",where:wh==="loc"?"loc":""})});
}
$("#b-kill").onclick=async()=>{if(!confirm("지금 도는 작업을 멈출까요?\n그리던 그림 1장은 버려지고, 만화 작업이면 '멈춘 작업'으로 남아서 '이어서 시작'으로 이어 갈 수 있어."))return;try{const j=await post("/api/kill");toast("멈춤: "+j.job+" — 작업 줄 맨 끝 '⏸ 멈춤'에서 이어서 시작",7000);refresh()}catch(e){toast(e.message)}};
$("#b-runner").onclick=async()=>{try{const j=await post("/api/runner");toast(j.msg)}catch(e){toast(e.message)}};
$("#b-aifile").onclick=()=>job({kind:"aifile",root:"0"},"AI 첨부 파일 만들기 (키트 폴더의 AI_첨부용.md)");
function paste(go){const ep=$("#new-ep").value.trim(), t=$("#new-text").value;if(!ep||!t.trim()){toast("이름과 AI 답을 넣어 주세요");return}job({kind:"paste",ep:ep,text:t,go:go,root:$("#new-root").value,flow:$("#new-flow").value})}
async function loadFlows(){try{const f=await get("/api/flows?root="+encodeURIComponent($("#new-root").value||"0"));$("#new-flow").innerHTML="<option value=''>기본 (nk 그리기)</option>"+(f.flows||[]).map(x=>"<option>"+esc(x)+"</option>").join("")}catch(e){}}
$("#new-root").onchange=loadFlows;
async function checkPlan(){const ep=$("#new-ep").value.trim(), t=$("#new-text").value, root=$("#new-root").value;
  if(!ep||!t.trim()){toast("에피소드 이름과 AI 답을 넣어 줘");return}
  modal("<h2>글콘티 검사 중…</h2><div class='mute'>몇 초 걸려 (그림은 안 그림)</div>");
  let r;try{r=await post("/api/check",{root:root,ep:ep,text:t,flow:$("#new-flow").value})}catch(e){modal("<h2 class='bad'>검사를 못 했어</h2><div>"+esc(e.message)+"</div><div class='row' style='margin-top:12px'><button class='pri' id='m-ok'>확인</button></div>");$("#m-ok").onclick=modalClose;return}
  const info="<div class='mute' style='margin:4px 0 10px'>"+esc(r.title||ep)+(r.pages?" · "+r.pages+"쪽 "+r.cuts+"컷":"")+(r.est_s?" · 만들기 약 "+mins(r.est_s)+" (추정)":"")+"</div>";
  const make=async()=>{await job({kind:"auto",ep:ep,root:root},"작업 줄에 넣음");$("#new-text").value="";$("#new-ep").value="";loadEps()};
  const notes=(r.notes||[]).length?"<div class='mute' style='margin-top:8px'><b>참고</b> (만들기는 그대로 진행 — 마음에 걸리면 나중에 컷 수정으로)<ul style='margin:4px 0 0 18px;padding:0'>"+r.notes.map(n=>"<li>"+esc(n)+"</li>").join("")+"</ul></div>":"";
  if(r.passed){await make();modal("<div class='ok'>✓ 검사 통과!</div>"+info+"<div>작업 줄에 넣었어 — 위 진행 창에서 볼 수 있어.</div>"+notes+"<div class='row' style='margin-top:12px'><button class='pri' id='m-ok'>확인</button></div>");$("#m-ok").onclick=modalClose;return}
  if(!r.can_make){modal("<h2 class='bad'>✗ 검사 불통과 — 이대로는 못 만들어</h2>"+info+"<div class='bad'>"+esc(r.error||"이유를 못 읽음")+"</div><div class='mute' style='margin-top:8px'>AI 답 전체를 복사했는지, 캐릭터·이름이 맞는지 확인하고 다시 붙여 넣어 줘.</div><div class='row' style='margin-top:12px'><button class='pri' id='m-ok'>확인</button></div>");$("#m-ok").onclick=modalClose;return}
  const probs=(r.fix_prompt||"").split("\n").filter(l=>l.trim().startsWith("- ")).map(l=>"<li>"+esc(l.trim().slice(2))+"</li>").join("");
  modal("<h2 class='bad'>✗ 검사 불통과 — 이대로면 만화가 통째로 틀어져</h2>"+info+(r.error?"<div class='bad'>"+esc(r.error)+"</div>":"")+"<b>큰 문제</b><ul style='margin:4px 0 8px 18px;padding:0'>"+probs+"</ul>"+notes+
    "<b>AI 채팅에 다시 붙여 넣을 글</b> <button id='m-copy'>복사</button><textarea id='m-fix' readonly>"+esc(r.fix_prompt||"")+"</textarea>"+
    "<div class='mute' style='font-size:12.5px;margin-top:4px'>AI 채팅의 같은 대화에 붙여 넣고 → 새 답을 같은 이름으로 다시 '글콘티 검사하기'. 작업 줄에는 아직 안 넣었어.</div>"+
    "<div class='row' style='margin-top:12px'><button class='pri' id='m-ok'>확인 (고쳐서 다시 할게)</button><button id='m-go'>수정 없이 바로 만화 만들기</button></div>");
  $("#m-ok").onclick=modalClose;
  $("#m-copy").onclick=async()=>{try{await navigator.clipboard.writeText(r.fix_prompt||"");toast("복사함 — AI 채팅의 같은 대화에 붙여 넣기")}catch(e){$("#m-fix").select();toast("글을 직접 복사해 줘")}};
  $("#m-go").onclick=async()=>{await make();modal("<div class='ok'>작업 줄에 넣었어</div>"+info+"<div>고칠 점은 그대로 두고 만들어.</div><div class='row' style='margin-top:12px'><button class='pri' id='m-ok'>확인</button></div>");$("#m-ok").onclick=modalClose}}
$("#b-check").onclick=checkPlan;
async function clearDone(undo){try{await post("/api/cleardone",{undo:!!undo});toast(undo?"지웠던 작업을 다시 보이게 함":"잘 끝난 작업을 목록에서 지움 — 그림·기록·대기열은 그대로 (실패한 작업은 남김)",5000);refresh()}catch(e){toast("안 됨: "+e.message,7000)}}
$("#b-clear").onclick=()=>clearDone(false);$("#b-clear2").onclick=()=>clearDone(false);
$("#b-big").onclick=()=>{const b=$("#prog").classList.toggle("big");$("#b-big").textContent=b?"작게 보기":"크게 보기"};
$("#b-req").onclick=async()=>{const v=id=>$("#"+id).value.trim();
  if(!v("rq-cast")||!v("rq-story")){toast("등장 캐릭터와 내용은 꼭 적어 줘",5000);return}
  const L=["첨부한 파일의 규칙대로 만화 계획표를 써 줘.","- 등장: "+v("rq-cast"),"- 쪽수: "+v("rq-pages")+"쪽","- 그림체(작가): "+v("rq-artist"),"- 내용: "+v("rq-story")];
  if(v("rq-mood"))L.push("- 분위기: "+v("rq-mood"));
  if(v("rq-scene"))L.push("- 꼭 넣을 장면: "+v("rq-scene"));
  if(v("rq-tags"))L.push("- 꼭 넣을 태그: "+v("rq-tags"));
  if(v("rq-end"))L.push("- 끝 반전·마무리: "+v("rq-end"));
  if($("#rq-first").checked)L.push("","줄거리 먼저: 이번에는 줄거리만 보여 줘. 내가 좋다고 하면 그때 계획표(YAML)를 써 줘.");
  const t=L.join("\n");$("#rq-out").value=t;
  try{await navigator.clipboard.writeText(t);toast("복사함 — AI 채팅 새 대화에 AI_첨부용.md 첨부 + 붙여 넣기",6000)}catch(e){toast("아래 글을 직접 복사해 줘",5000)}};
loadRoots().then(()=>{loadEps();loadFlows()});refresh();setInterval(refresh,5000);setInterval(loadEps,60000);
</script></body></html>
"""

LABEL_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>정답 표시</title>
<style>
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1f2328;--mute:#6b7078;--line:#e3e1dc;--acc:#2f6fdb;--ok:#1f8a4c;--bad:#c93a3a;--chip:#efeee9}
@media (prefers-color-scheme: dark){:root{--bg:#16181b;--panel:#1f2226;--ink:#e8e8e6;--mute:#9aa0a6;--line:#30343a;--acc:#6ea0ff;--ok:#4cc27f;--bad:#ff7070;--chip:#2a2e33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
h1{font-size:17px;margin:0 8px 0 0}
a{color:var(--acc)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;padding:10px 16px 0}
.tabs button{font:inherit;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:3px 12px;cursor:pointer}
.tabs button.sel{background:var(--acc);border-color:var(--acc);color:#fff}
.help{padding:6px 16px;color:var(--mute);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;padding:10px 16px 60px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:7px}
.card.done{border-color:var(--ok)}.card.hasbad{border-color:var(--bad)}
.card img{width:100%;height:260px;object-fit:contain;background:var(--bg);border-radius:6px;cursor:zoom-in}
.t{font-weight:600}.s{font-size:12.5px;color:var(--mute);overflow-wrap:anywhere}
.flags{display:flex;flex-wrap:wrap;gap:5px}
.flags button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:7px;padding:3px 9px;cursor:pointer}
.flags button.on{background:var(--bad);border-color:var(--bad);color:#fff}
.flags button.okb.on{background:var(--ok);border-color:var(--ok)}
.row{display:flex;gap:8px;align-items:center}
input,textarea{font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 7px}
input[type=number]{width:80px}textarea{width:100%;min-height:38px;resize:vertical}
.st{font-size:12px;color:var(--mute)}.st.ok{color:var(--ok)}.st.bad{color:var(--bad)}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;z-index:20;overflow:auto;cursor:zoom-out}
#zoom img{display:block;margin:auto}
</style></head><body>
<header>
  <h1>정답 표시</h1>
  <span id="prog" class="s"></span>
  <label class="s"><input type="checkbox" id="only"> 안 한 것만</label>
  <a href="/ab" style="margin-left:auto">섞어서 비교</a> <a href="/">← 작업실</a>
</header>
<div class="help">만화에 실제로 들어간 컷 그림이야. 흠이 있으면 그 버튼(여러 개 가능), 없으면 <b>괜찮음</b>. 누르면 바로 저장돼.
점수(0~100)와 메모는 적고 싶을 때만. 그림을 누르면 원본 크기로 커져 (한 번 더 누르면 닫힘). 키트 폴더 만화만 나와.<br><b>그림체 괴리</b> = 이 만화의 다른 컷과 그림체가 다름 · <b>AI티</b> = AI 그림 특유의 어색함·저퀄 · <b>몸·비율</b> = 체형·비율·자세·몸 깨짐 (SD처럼 머리 크고 몸 작아짐 포함) · <b>무늬·디자인</b> = 캐릭터 무늬·옷·색이 설정과 다름</div>
<div class="tabs" id="tabs"></div>
<div class="grid" id="grid">불러오는 중…</div>
<div id="zoom"><img id="zimg"></div>
<script>
const $=s=>document.querySelector(s);
let D=null,cur=null;
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function get(u){const r=await fetch(u);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
async function post(u,b){const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json","X-NK":"1"},body:JSON.stringify(b)});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
function rec(key){return D.labels[key]||{flags:[],score:null,note:""}}
function prog(){let n=0,t=0;for(const e of D.episodes)for(const c of e.cuts){t++;if(D.labels[c.key])n++}
  $("#prog").textContent="표시한 컷 "+n+" / 전체 "+t}
function tabs(){$("#tabs").innerHTML=D.episodes.map(e=>{const n=e.cuts.filter(c=>D.labels[c.key]).length;
  return '<button data-ep="'+esc(e.ep)+'" class="'+(e.ep===cur?"sel":"")+'">'+esc(e.ep)+' '+n+'/'+e.cuts.length+'</button>'}).join("");
  document.querySelectorAll("[data-ep]").forEach(b=>b.onclick=()=>{cur=b.dataset.ep;ls("nk_label_ep",cur);tabs();render()})}
function card(e,c){const r=rec(c.key),bad=r.flags.some(f=>f!=="괜찮음");
  return '<div class="card '+(D.labels[c.key]?(bad?"hasbad":"done"):"")+'" data-key="'+esc(c.key)+'">'+
   '<img loading="lazy" src="/img?p='+encodeURIComponent(c.img)+'&w=700" data-full="'+esc(c.img)+'">'+
   '<div class="t">'+esc(e.ep)+' · 컷 '+c.id+(c.duo?' · 두 명':'')+'</div>'+
   '<div class="s">'+esc((c.who||[]).join(", "))+(c.action?' — '+esc(c.action):'')+'</div>'+
   '<div class="flags">'+D.flags.map(f=>'<button data-f="'+esc(f)+'" class="'+(f==="괜찮음"?"okb ":"")+(r.flags.includes(f)?"on":"")+'">'+esc(f)+'</button>').join("")+'</div>'+
   '<div class="row"><span class="s">점수</span><input type="number" min="0" max="100" data-score value="'+(r.score==null?"":r.score)+'"><span class="st" data-st>'+(D.labels[c.key]?"저장됨 "+esc(r.time.slice(11,16)):"")+'</span></div>'+
   '<textarea data-note placeholder="메모 (어디가 어떻게)">'+esc(r.note)+'</textarea></div>'}
function render(){const e=D.episodes.find(x=>x.ep===cur);if(!e){$("#grid").textContent="만화가 없어";return}
  const only=$("#only").checked;
  $("#grid").innerHTML=e.cuts.filter(c=>!only||!D.labels[c.key]).map(c=>card(e,c)).join("")||"다 표시했어";
  document.querySelectorAll(".card").forEach(el=>{const c=e.cuts.find(x=>x.key===el.dataset.key);
    el.querySelector("img").onclick=ev=>{$("#zimg").src="/img?p="+encodeURIComponent(ev.target.dataset.full);$("#zoom").style.display="block"};
    el.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{let fl=rec(c.key).flags.slice();const f=b.dataset.f;
      if(fl.includes(f))fl=fl.filter(x=>x!==f);else if(f==="괜찮음")fl=["괜찮음"];else fl=fl.filter(x=>x!=="괜찮음").concat([f]);
      save(e,c,el,{flags:fl})});
    el.querySelector("[data-score]").onchange=ev=>save(e,c,el,{score:ev.target.value});
    el.querySelector("[data-note]").onchange=ev=>save(e,c,el,{note:ev.target.value});})}
async function save(e,c,el,ch){const r=rec(c.key),b={ep:e.ep,cut:c.id,flags:r.flags,score:r.score,note:r.note};Object.assign(b,ch);
  const st=el.querySelector("[data-st]");st.className="st";st.textContent="저장 중…";
  try{const j=await post("/api/label",b);if(j.key!==c.key){delete D.labels[c.key];c.key=j.key;el.dataset.key=j.key}
    if(j.rec)D.labels[c.key]=j.rec;else delete D.labels[c.key];
    const bad=(j.rec?j.rec.flags:[]).some(f=>f!=="괜찮음");
    el.className="card "+(j.rec?(bad?"hasbad":"done"):"");
    el.querySelectorAll("[data-f]").forEach(x=>x.classList.toggle("on",!!j.rec&&j.rec.flags.includes(x.dataset.f)));
    st.className="st ok";st.textContent=j.rec?"저장됨 "+j.rec.time.slice(11,16):"표시 지움";prog();tabs()}
  catch(err){st.className="st bad";st.textContent="저장 안 됨: "+err.message}}
$("#zoom").onclick=()=>{$("#zoom").style.display="none";$("#zimg").src=""};
$("#only").onchange=render;
get("/api/labels").then(d=>{D=d;const s=ls("nk_label_ep");cur=(D.episodes.find(e=>e.ep===s)||D.episodes[0]||{}).ep;prog();tabs();render()})
 .catch(err=>{$("#grid").textContent="불러오기 실패: "+err.message});
</script></body></html>
"""

AB_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>섞어서 비교</title>
<style>
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1f2328;--mute:#6b7078;--line:#e3e1dc;--acc:#2f6fdb;--ok:#1f8a4c;--bad:#c93a3a;--chip:#efeee9}
@media (prefers-color-scheme: dark){:root{--bg:#16181b;--panel:#1f2226;--ink:#e8e8e6;--mute:#9aa0a6;--line:#30343a;--acc:#6ea0ff;--ok:#4cc27f;--bad:#ff7070;--chip:#2a2e33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
h1{font-size:17px;margin:0 8px 0 0}
a{color:var(--acc)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;padding:10px 16px 0}
.tabs button{font:inherit;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:3px 12px;cursor:pointer}
.tabs button.sel{background:var(--acc);border-color:var(--acc);color:#fff}
.q{padding:8px 16px;font-size:15px}
.list{display:flex;flex-direction:column;gap:16px;padding:6px 16px 80px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:8px}
.card.done{border-color:var(--ok)}
.pan{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:700px){.pan{grid-template-columns:1fr}}
.pan figure{margin:0;display:flex;flex-direction:column;gap:4px;min-width:0}
.pan figcaption{font-weight:600}
.pan img{width:100%;background:var(--bg);border-radius:6px;cursor:zoom-in;object-fit:contain}
.pan img.crop{max-height:62vh}.pan img.full{max-height:200px}
.t{font-weight:600}.s{font-size:12.5px;color:var(--mute)}
.ch{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.ch button{font:inherit;font-size:14px;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:7px;padding:5px 14px;cursor:pointer}
.ch button.on{background:var(--acc);border-color:var(--acc);color:#fff}
textarea{font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 7px;width:100%;min-height:34px;resize:vertical}
.st{font-size:12px;color:var(--mute)}.st.ok{color:var(--ok)}.st.bad{color:var(--bad)}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;z-index:20;overflow:auto;cursor:zoom-out}
#zoom img{display:block;margin:auto}
</style></head><body>
<header>
  <h1>섞어서 비교</h1>
  <span id="prog" class="s"></span>
  <label class="s"><input type="checkbox" id="only"> 안 한 것만</label>
  <a href="/label" style="margin-left:auto">정답 표시</a> <a href="/">← 작업실</a>
</header>
<div class="tabs" id="tabs"></div>
<div class="q" id="q"></div>
<div class="list" id="list">불러오는 중…</div>
<div id="zoom"><img id="zimg"></div>
<script>
const $=s=>document.querySelector(s);
let D=null,cur=null;
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function get(u){const r=await fetch(u);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
async function post(u,b){const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json","X-NK":"1"},body:JSON.stringify(b)});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
function ans(s,it){return D.answers[s.name+":"+it.id]||null}
function S(){return D.sets.find(x=>x.name===cur)}
function prog(){const s=S();if(!s){$("#prog").textContent="";return}
  const n=s.items.filter(it=>ans(s,it)&&ans(s,it).choice).length;$("#prog").textContent="고른 것 "+n+" / "+s.items.length}
function tabs(){$("#tabs").innerHTML=D.sets.map(s=>{const n=s.items.filter(it=>ans(s,it)&&ans(s,it).choice).length;
  return '<button data-s="'+esc(s.name)+'" class="'+(s.name===cur?"sel":"")+'">'+esc(s.title||s.name)+' '+n+'/'+s.items.length+'</button>'}).join("");
  document.querySelectorAll("[data-s]").forEach(b=>b.onclick=()=>{cur=b.dataset.s;ls("nk_ab_set",cur);tabs();render()})}
function img(p,cls){return '<img loading="lazy" class="'+cls+'" src="/img?p='+encodeURIComponent(p)+'" data-full="'+esc(p)+'">'}
function card(s,it,i){const a=ans(s,it);
  return '<div class="card '+(a&&a.choice?"done":"")+'" data-id="'+esc(it.id)+'"><div class="t">'+(i+1)+'번 ('+esc(it.id)+')</div><div class="pan">'+
   it.panels.map(p=>'<figure><figcaption>'+esc(p.label)+'</figcaption>'+img(p.crop,"crop")+(p.full!==p.crop?img(p.full,"full"):"")+'</figure>').join("")+
   '</div><div class="ch">'+s.choices.map(c=>'<button data-c="'+esc(c.code)+'" class="'+(a&&a.choice===c.code?"on":"")+'">'+esc(c.label)+'</button>').join("")+
   '<span class="st" data-st>'+(a?"저장됨 "+esc(a.time.slice(11,16)):"")+'</span></div>'+
   '<textarea data-note placeholder="메모 (왜 그쪽인지, 적고 싶을 때만)">'+esc(a?a.note:"")+'</textarea></div>'}
function render(){const s=S();if(!s){$("#list").textContent="비교판이 없어";$("#q").textContent="";return}
  $("#q").innerHTML=esc(s.question||"");const only=$("#only").checked;
  $("#list").innerHTML=s.items.map((it,i)=>(!only||!(ans(s,it)&&ans(s,it).choice))?card(s,it,i):"").join("")||"다 골랐어";
  document.querySelectorAll(".card").forEach(el=>{const it=s.items.find(x=>x.id===el.dataset.id);
    el.querySelectorAll("img").forEach(m=>m.onclick=ev=>{$("#zimg").src="/img?p="+encodeURIComponent(ev.target.dataset.full);$("#zoom").style.display="block"});
    el.querySelectorAll("[data-c]").forEach(b=>b.onclick=()=>{const a=ans(s,it);const c=(a&&a.choice===b.dataset.c)?"":b.dataset.c;save(s,it,el,{choice:c})});
    el.querySelector("[data-note]").onchange=ev=>save(s,it,el,{note:ev.target.value});});prog()}
async function save(s,it,el,ch){const a=ans(s,it)||{},b={set:s.name,item:it.id,choice:a.choice||"",note:a.note||""};Object.assign(b,ch);
  const st=el.querySelector("[data-st]");st.className="st";st.textContent="저장 중…";
  try{const j=await post("/api/ab",b);if(j.rec)D.answers[j.key]=j.rec;else delete D.answers[j.key];
    el.className="card "+(j.rec&&j.rec.choice?"done":"");
    el.querySelectorAll("[data-c]").forEach(x=>x.classList.toggle("on",!!j.rec&&j.rec.choice===x.dataset.c));
    st.className="st ok";st.textContent=j.rec?"저장됨 "+j.rec.time.slice(11,16):"지움";prog();tabs()}
  catch(err){st.className="st bad";st.textContent="저장 안 됨: "+err.message}}
$("#zoom").onclick=()=>{$("#zoom").style.display="none";$("#zimg").src=""};
$("#only").onchange=render;
get("/api/ab").then(d=>{D=d;const s=ls("nk_ab_set");cur=(D.sets.find(x=>x.name===s)||D.sets[0]||{}).name;tabs();render()})
 .catch(err=>{$("#list").textContent="불러오기 실패: "+err.message});
</script></body></html>
"""
