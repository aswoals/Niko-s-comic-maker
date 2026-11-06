# -*- coding: utf-8 -*-
"""nk_lines.py - 대사 고치기 (작업실 컷 카드의 '대사 고치기' 칸)

무엇
  한 컷의 말풍선·속마음·해설·효과음 글만 바꿈. 말하는 사람·자리·종류는 그대로 둠.
  작업실(nk_web.py)의 /api/lines 가 save() 를 부름. 컷 카드에 보여 줄 글 목록은 items_of().

어떻게
  episodes/<만화>/conti.yaml   말풍선을 그림 위에 입히는 쪽이 읽는 글 (이걸 고쳐야 '말풍선 다시'에 반영됨)
  episodes/<만화>/plan.yaml    원본 계획표 (같이 고쳐야 나중에 계획표로 콘티를 다시 만들어도 옛 대사로 안 돌아감)
  -> 두 파일 모두 '그 글자만' 바꾸고 주석·모양은 그대로 둠.
     그렇게 못 바꾸면 파일을 다시 써서 저장 (이때 주석 일부가 사라질 수 있음 — 늘 백업이 먼저).
  백업: episodes/<만화>/_lines_bak/<월일_시분초>/ 에 고치기 전 파일 + _lines_bak/log.jsonl 에 '옛 글 -> 새 글' 기록.
        되돌리려면 그 폴더의 conti.yaml / plan.yaml 을 만화 폴더로 복사해 덮어쓰기.

에러가 나면
  [화면이 낡았어요]   -> 다른 곳에서 그 대사가 바뀐 것. 만화를 다시 열어(F5) 새 글을 보고 고치기.
  [저장 중 오류]      -> 고치기 전 파일로 이미 되돌려 놓았음. 이 문구를 개발자에게 알려 주세요.
  [plan.yaml 못 맞춤] -> conti.yaml 만 고침 (말풍선은 바뀜). 계획표로 콘티를 다시 만들면 옛 대사로 돌아가니 그때는 다시 고치기.

설정값: 아래 MAX_LEN (대사 한 줄 최대 글자 수) 한 곳.
"""
import copy
import json
import os
import re
import shutil
import threading
import time

import yaml

MAX_LEN = 300                      # 대사 한 줄 최대 글자 수 (넘으면 저장을 막음)

# 화면에 보여 줄 글 종류 이름 (모르는 종류는 영어 이름 그대로)
TYPE_KO = {"speech": "대사", "thought": "속마음", "narration": "해설", "sfx": "효과음",
           "shout": "외침", "whisper": "속삭임", "tremble": "떨리는 말", "aside": "혼잣말",
           "offscreen": "화면 밖 대사"}
_LOCK = threading.Lock()           # 두 번 눌러도 저장이 겹치지 않게
_BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------------------------------------------------------------- 읽기
def _cuts(doc):
    """계획표·콘티의 컷 목록 (문서 순서). 쪽 형식 = pages[].cuts[], 옛 형식 = cuts[]"""
    if not isinstance(doc, dict):
        return []
    pgs = doc.get("pages")
    if isinstance(pgs, list) and pgs:
        return [ct for pg in pgs if isinstance(pg, dict) for ct in (pg.get("cuts") or []) if isinstance(ct, dict)]
    return [ct for ct in (doc.get("cuts") or []) if isinstance(ct, dict)]


def _cid(ct, pos):
    try:
        return int(ct.get("id", pos + 1))
    except (TypeError, ValueError):
        return pos + 1


def items_of(ct):
    """콘티 컷 하나의 글 목록 -> 화면용 [{i, type, type_ko, who, text}] (작업실 컷 카드가 씀)"""
    out = []
    lst = ct.get("text") if isinstance(ct, dict) else None
    if not isinstance(lst, list):
        return out
    for i, it in enumerate(lst):
        if not isinstance(it, dict):
            continue
        t = str(it.get("type", "speech"))
        out.append({"i": i, "type": t, "type_ko": TYPE_KO.get(t, t), "who": str(it.get("who") or ""),
                    "text": str(it.get("text", ""))})
    return out


def _read(path):
    """-> (글, BOM 있나). 줄바꿈(CRLF)은 그대로 둠"""
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    bom = raw.startswith("﻿")
    return (raw[1:] if bom else raw), bom


def _load_conti(raw):
    return yaml.safe_load(raw) or {}


def _plan_body(raw):
    """AI 답을 그대로 붙여 넣은 계획표(```yaml 코드 블록)도 읽음 (nk_plan._extract_yaml 과 같은 방식)"""
    m = re.search(r"```(?:yaml|yml)?\s*\n(.*?)(?:```|\Z)", raw, re.S)
    return m.group(1) if m else raw


def _load_plan(raw):
    return yaml.safe_load(_plan_body(raw)) or {}


def _nl(s):
    return str(s).replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------- 글자만 바꾸기 (주석·모양 보존)
def _forms(old):
    """파일에 그 글이 적혀 있을 수 있는 모양들: 그냥 / '작은따옴표' / "큰따옴표" """
    f = []
    if "\n" not in old:
        f.append(old)
        f.append("'" + old.replace("'", "''") + "'")
    f.append(json.dumps(old, ensure_ascii=False))
    return f


def _targeted(raw, loader, doc, want, key, edits):
    """raw 에서 해당 줄의 글자만 새 글로 바꾼 글을 돌려줌. 안전하게 못 하면 None.
    확인: 바꾼 결과를 다시 읽어서 want(고친 문서) 와 똑같아야 통과"""
    cur_raw, cur = raw, copy.deepcopy(doc)
    for cpos, idx, old, new in edits:
        cuts = _cuts(cur)
        order = [(a, b) for a, c in enumerate(cuts) for b, it in enumerate(c.get(key) or [])
                 if isinstance(it, dict) and str(it.get("text", "")) == old]       # 같은 글이 여러 곳이면 문서 순서로 몇 번째인지
        if (cpos, idx) not in order:
            return None
        n = order.index((cpos, idx))
        spans = []
        for f in _forms(old):
            for m in re.finditer(r"(\btext:[ \t]*)(" + re.escape(f) + r")(?=[ \t]*(?:[,}\r\n]|$)|[ \t]+#)", cur_raw):
                spans.append((m.start(2), m.end(2)))
        spans = sorted(set(spans))
        if len(spans) != len(order):
            return None
        s, e = spans[n]
        cur_raw = cur_raw[:s] + json.dumps(new, ensure_ascii=False) + cur_raw[e:]
        cuts[cpos][key][idx]["text"] = new
    try:
        if loader(cur_raw) != want:
            return None
    except Exception:
        return None
    return cur_raw


def _head_comments(raw):
    """파일 맨 위의 주석 줄들 (다시 쓸 때 보존)"""
    out = []
    for ln in raw.splitlines():
        if ln.startswith("#") or not ln.strip():
            out.append(ln)
        else:
            break
    while out and not out[-1].strip():
        out.pop()
    return ("\n".join(out) + "\n") if out else ""


def _redump(raw, want, conti):
    head = _head_comments(raw)
    if conti:
        body = yaml.safe_dump(want, allow_unicode=True, sort_keys=False, width=160, default_flow_style=None)
    else:
        body = yaml.safe_dump(want, allow_unicode=True, sort_keys=False, width=160)       # nk ep fix 가 계획표를 쓰는 방식과 같음
    return head + body


def _rewrite(raw, loader, doc, key, edits, conti):
    """-> (새 글, 방식 설명)"""
    want = copy.deepcopy(doc)
    for cpos, idx, old, new in edits:
        _cuts(want)[cpos][key][idx]["text"] = new
    out = _targeted(raw, loader, doc, want, key, edits)
    if out is not None:
        return out, "그 글자만 바꿈"
    return _redump(raw, want, conti), "파일을 다시 씀 (주석 일부가 사라질 수 있음)"


# ---------------------------------------------------------------- 쓰기
def _atomic_write(path, text, bom):
    tmp = path + ".lines_tmp"
    with open(tmp, "wb") as f:
        f.write((("﻿" if bom else "") + text).encode("utf-8"))
    last = None
    for _ in range(8):                         # OneDrive·편집기가 파일을 잡고 있으면 잠깐 기다림
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.6)
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last


def _clean(v):
    s = _nl(v if v is not None else "").strip()
    if not s:
        raise ValueError("빈 칸은 저장할 수 없어요 (대사를 지우는 기능은 아직 없음)")
    if len(s) > MAX_LEN:
        raise ValueError("대사가 너무 길어요 (%d자까지, 지금 %d자)" % (MAX_LEN, len(s)))
    if _BAD_CHARS.search(s):
        raise ValueError("대사에 쓸 수 없는 문자가 섞여 있어요")
    return s


def _plan_edits(pp, cid, items, todo):
    """계획표(plan.yaml) 쪽: 같은 컷의 같은 줄 찾기 (컷 번호 = 계획표 컷 순서, 줄 = lines 순서)
    -> (새 글 또는 None, BOM, 설명, [(컷 위치, 줄, 옛 글, 새 글)])"""
    if not os.path.exists(pp):
        return None, False, "계획표(plan.yaml) 없음 — conti.yaml 만 고침", []
    try:
        raw_p, bom_p = _read(pp)
        doc_p = _load_plan(raw_p)
        pcuts = _cuts(doc_p)
        if not 1 <= cid <= len(pcuts):
            raise ValueError("계획표에 %d번 컷이 없음" % cid)
        lines = pcuts[cid - 1].get("lines")
        if not isinstance(lines, list):
            raise ValueError("계획표 %d번 컷에 lines 가 없음" % cid)
        aligned = len(lines) == len(items) and all(
            isinstance(lines[i], dict) and _nl(lines[i].get("text", "")) == o for i, o, _ in todo)
        pe = []
        for i, o, n in todo:
            if aligned:
                j = i
            else:
                who = str(items[i].get("who") or "")
                cand = [k for k, ln in enumerate(lines) if isinstance(ln, dict) and _nl(ln.get("text", "")) == o
                        and (not who or not ln.get("who") or str(ln.get("who")) == who)]
                if len(cand) != 1:
                    raise ValueError("계획표에서 '%s' 줄을 하나로 못 찾음 (%d곳)" % (o[:20], len(cand)))
                j = cand[0]
            pe.append((cid - 1, j, o, n))
        if len({x[1] for x in pe}) != len(pe):
            raise ValueError("계획표 줄이 겹침")
        new_p, mode_p = _rewrite(raw_p, _load_plan, doc_p, "lines", pe, False)
        return new_p, bom_p, "plan.yaml: " + mode_p, pe
    except Exception as e:                  # 계획표를 못 맞추면 conti.yaml 만 고침 (말풍선은 바뀜)
        return None, False, ("plan.yaml 못 맞춤 — conti.yaml 만 고쳤어요 (%s). 계획표로 콘티를 다시 만들면 옛 대사로 돌아가요"
                             % " ".join(str(e).split())[:100]), []


def save(ed, cid, edits):
    """한 컷의 대사 고치기. ed = episodes/<만화> 폴더, cid = 컷 번호, edits = [{i: 줄 번호(0부터), old: 지금 글, text: 새 글}]
    -> {ok, changed, conti, plan, backup} / 막히면 ValueError(한국어 이유). 막히면 아무 파일도 안 바뀜"""
    cid = int(cid)
    cp, pp = os.path.join(ed, "conti.yaml"), os.path.join(ed, "plan.yaml")
    if not os.path.exists(cp):
        raise ValueError("이 만화에는 conti.yaml 이 아직 없어요 (콘티를 만든 뒤에 고칠 수 있음)")
    with _LOCK:
        raw_c, bom_c = _read(cp)
        try:
            doc_c = _load_conti(raw_c)
        except Exception as e:
            raise ValueError("conti.yaml 을 읽지 못했어요: %s" % " ".join(str(e).split())[:120])
        cuts_c = _cuts(doc_c)
        pos = next((k for k, ct in enumerate(cuts_c) if _cid(ct, k) == cid), None)
        if pos is None:
            raise ValueError("%d번 컷이 conti.yaml 에 없어요" % cid)
        items = cuts_c[pos].get("text")
        if not isinstance(items, list) or not items:
            raise ValueError("%d번 컷에는 대사가 없어요" % cid)
        todo, seen = [], set()
        for e in edits or []:
            try:
                i = int(e.get("i"))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("줄 번호가 이상해요")
            if i in seen or not 0 <= i < len(items) or not isinstance(items[i], dict):
                raise ValueError("줄 번호가 이상해요 (%s)" % i)
            seen.add(i)
            old = _nl(items[i].get("text", ""))
            if _nl(e.get("old", "")) != old:
                raise ValueError("화면이 낡았어요 — %d번째 줄 글이 그 사이에 바뀌었음. 이 만화를 다시 열어(F5) 주세요" % (i + 1))
            if _nl(e.get("text", "")) == old:
                continue
            todo.append((i, old, _clean(e.get("text"))))
        if not todo:
            return {"ok": True, "changed": 0, "conti": "바뀐 곳 없음", "plan": "", "backup": ""}

        new_c, mode_c = _rewrite(raw_c, _load_conti, doc_c, "text", [(pos, i, o, n) for i, o, n in todo], True)
        new_p, bom_p, plan_msg, pe = _plan_edits(pp, cid, items, todo)

        # 백업 -> 쓰기 -> 다시 읽어 확인. 실패하면 백업으로 되돌림
        ts = time.strftime("%m%d_%H%M%S")
        bdir = os.path.join(ed, "_lines_bak", ts)
        k = 1
        while os.path.exists(bdir):
            k += 1
            bdir = os.path.join(ed, "_lines_bak", "%s_%d" % (ts, k))
        os.makedirs(bdir)
        shutil.copy2(cp, os.path.join(bdir, "conti.yaml"))
        if new_p is not None:
            shutil.copy2(pp, os.path.join(bdir, "plan.yaml"))
        wrote = []
        try:
            _atomic_write(cp, new_c, bom_c)
            wrote.append((cp, "conti.yaml"))
            chk = _cuts(_load_conti(_read(cp)[0]))[pos]["text"]
            if any(str(chk[i].get("text", "")) != n for i, _, n in todo):
                raise RuntimeError("conti.yaml 확인 실패")
            if new_p is not None:
                _atomic_write(pp, new_p, bom_p)
                wrote.append((pp, "plan.yaml"))
                chk = _cuts(_load_plan(_read(pp)[0]))[cid - 1]["lines"]
                if any(str(chk[j].get("text", "")) != n for (_, j, _, n) in pe):
                    raise RuntimeError("plan.yaml 확인 실패")
        except Exception as e:
            for path, nm in wrote:
                try:
                    shutil.copyfile(os.path.join(bdir, nm), path)
                except Exception:
                    pass
            raise ValueError("저장 중 오류 (%s) — 고치기 전 파일로 되돌려 놓았어요" % " ".join(str(e).split())[:140])
        try:
            with open(os.path.join(ed, "_lines_bak", "log.jsonl"), "a", encoding="utf-8") as lf:
                lf.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "cut": cid, "backup": os.path.basename(bdir),
                                     "edits": [{"i": i, "type": str(items[i].get("type", "speech")), "who": str(items[i].get("who") or ""),
                                                "old": o, "new": n} for i, o, n in todo],
                                     "conti": mode_c, "plan": plan_msg}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return {"ok": True, "changed": len(todo), "conti": "conti.yaml: " + mode_c, "plan": plan_msg, "backup": os.path.basename(bdir)}
