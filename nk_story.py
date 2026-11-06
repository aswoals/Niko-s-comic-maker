# -*- coding: utf-8 -*-
"""그림이 글(콘티)과 맞나 검사

왜: 자동 검수는 '캐릭터가 맞나·소품이 보이나'(판별기 태그)만 봄
어떻게: 컷마다 '그림에서 참이어야 하는 문장'(영어, show)을 검수 AI(Ollama 비전 모델, presets qa.model)에게 참/거짓으로 물음.
    문장 출처 = 콘티 컷의 show: (계획표에서 넘어옴) 또는 --facts. 틀리면 nk ep edit 로 그 문장대로 고칠 수 있음 (storyfix 는 다음 단계).
사용: nk ep storycheck <ep> [컷...] [--facts "9=The cookies are burnt black|Smoke rises;15=..."] [--style anime]
      -> episodes/<ep>/story/storycheck.json + 화면 출력 (최종본은 안 바꿈)"""
import os
import sys
import json
import time


def _facts_arg(s):
    """'9=a|b;15=c' -> {9: [a, b], 15: [c]}"""
    out = {}
    for part in str(s or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        fs = [x.strip() for x in v.split("|") if x.strip()]
        if k.strip().isdigit() and fs:
            out.setdefault(int(k), []).extend(fs)
    return out


def cut_facts(cut):
    v = cut.get("show") or []
    if isinstance(v, str):
        v = [x.strip() for x in v.split("|") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


#   계획표 show 와 같은 길(묻기 -> 글로 고치기)을 탐. 얼굴·사물 컷은 뺌(팔이 안 보임).
DESIGN_SKIP_SHOTS = ("face", "detail", "eyes", "hands")


def _cut_chars(cut):
    if cut.get("_roles"):
        return [ch for _, ch in cut["_roles"]]
    return [cut["_char"]] if cut.get("_char") else []


def design_facts(cut):
    """-> [(사실, 고치는 문장 또는 None)]"""
    if not cut or str(cut.get("shot", "")).lower() in DESIGN_SKIP_SHOTS:
        return []
    out = []
    for ch in _cut_chars(cut):
        for d in ch.get("design_show") or []:
            if isinstance(d, dict):
                out.append((str(d.get("fact", "")).strip(), d.get("fix")))
            else:
                out.append((str(d).strip(), None))
    return [x for x in out if x[0]]


def all_facts(conti, cut, extra=()):
    """컷 show + --facts + 캐릭터 design_show -> (사실 목록, {사실: 고치는 문장})"""
    d = design_facts(cut)
    facts = norm_facts(conti, (cut_facts(cut) if cut else []) + list(extra or []))
    facts += [f for f, _ in d if f not in facts]
    return facts, {f: x for f, x in d if x}


def norm_facts(conti, facts):
    """캐릭터 이름 -> 겉모습 이름 (검수 AI·편집 모델은 이름을 모름)
    이름 = 콘티 cast 짧은 이름·캐릭터 파일 이름·trigger, 겉모습 = 캐릭터 파일 compose_name (없으면 그대로)"""
    import re
    names = {}
    for key, ch in ((conti or {}).get("_cast") or {}).items():
        look = ch.get("compose_name")
        if not look:
            continue
        for n in (key, ch.get("name"), ch.get("trigger"), ch.get("_key")):
            if n and len(str(n)) >= 3:
                names[str(n).lower()] = look
    if not names:
        return list(facts)
    pat = re.compile(r"\b(%s)\b" % "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)), re.I)
    out = []
    for f in facts:
        g = pat.sub(lambda m: "the " + names[m.group(1).lower()], f)
        g = re.sub(r"\bthe the\b", "the", g, flags=re.I)
        out.append(g[:1].upper() + g[1:])
    return out


def ask(nk, qa_cfg, path, facts):
    """-> ({id: True/False/None}, raw)"""
    ids = ["f%d" % (i + 1) for i in range(len(facts))]
    prompt = ("You are a strict checker for one panel of a comic. Look at the image carefully.\n"
              "For each statement, answer true only if the picture clearly shows it, otherwise false.\n"
              "Statements:\n%s\n"
              "Reply with a single JSON object whose keys are exactly the statement ids and whose values are true or false. "
              "No explanations." % "\n".join('  "%s": %s' % (i, f) for i, f in zip(ids, facts)))
    b64 = nk._img_b64(path, int(qa_cfg.get("max_side", 1024)))
    raw = nk.ollama_ask(qa_cfg, b64, prompt)
    ans = nk.parse_answers(raw, ids)
    out = {}
    for i in ids:
        v = ans.get(i)
        if isinstance(v, str):
            v = {"true": True, "false": False, "yes": True, "no": False}.get(v.strip().lower())
        out[i] = v if isinstance(v, bool) else None
    return out, raw


def run(nk, kit, args):
    import nk_webtoon as W
    cfg = nk.load_presets()
    qa_cfg = dict(cfg.get("qa") or {})
    conti = W.load_conti(nk, kit, args.ep)
    extra = _facts_arg(args.facts)
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    ids = [int(x) for x in args.cuts] if args.cuts else sorted(cuts)
    d = os.path.join(W.ep_dir(kit, args.ep), "story")
    os.makedirs(d, exist_ok=True)
    rp = os.path.join(d, "storycheck.json")
    rec = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
    todo = []
    for cid in ids:
        if cid not in cuts:
            continue
        facts, _ = all_facts(conti, cuts[cid], extra.get(cid, []))
        if not facts:
            continue
        f = W._final_file(kit, args.ep, cid)
        if args.style:
            fs = os.path.join(W.ep_dir(kit, args.ep), "cuts_" + args.style, "cut%02d.png" % cid)
            f = fs if os.path.exists(fs) else f
        if os.path.exists(f):
            todo.append((cid, f, facts))
    if not todo:
        print("storycheck %s: no cut with 'show:' facts (conti) or --facts" % args.ep); return
    print("storycheck %s: %d cuts, model %s" % (args.ep, len(todo), qa_cfg.get("model")))
    bad = 0
    for cid, f, facts in todo:
        t0 = time.time()
        try:
            ans, raw = ask(nk, qa_cfg, f, facts)
        except Exception as e:
            print("[ERROR] cut %d: %s" % (cid, e)); continue
        res = [{"fact": fa, "ok": ans.get("f%d" % (i + 1))} for i, fa in enumerate(facts)]
        miss = [r["fact"] for r in res if r["ok"] is False]
        bad += bool(miss)
        rec[str(cid)] = {"file": f, "facts": res, "raw": raw[:500], "time": time.strftime("%m-%d %H:%M")}
        print("cut %2d %s (%.0fs)" % (cid, "OK" if not miss else "MISMATCH", time.time() - t0))
        for r in res:
            print("    [%s] %s" % ({True: "yes", False: "NO ", None: " ? "}[r["ok"]], r["fact"]))
    json.dump(rec, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        nk.ollama_unload(qa_cfg)                 # 그림 그리기와 VRAM 나눠 씀
    except Exception:
        pass
    print("storycheck %s: %d of %d cuts do not match -> %s" % (args.ep, bad, len(todo), rp))


# ---------------------------------------------------------------- storyfix: 틀린 컷을 그 문장대로 Qwen으로 고친 후보 -> 다시 검사
# nk ep auto 의 'story' 단계는 적용 (review 에 '고쳤음 - 볼 것 + 되돌리기' 로 뜸). 적용 조건 = 깨끗한 후보(바뀐 정도·색·격자·디자인 지킴)가
#   -> ① 모든 컷 묻기 ② 틀린 컷 모두 고치기 ③ 모든 후보 묻기 (바꿔 쓰기 3번)
STORYFIX_APPLY = False


def storyfix(nk, kit, conti, ids=None, tries=2, apply=None, dry=False, extra=None, skip_done=False, edit=True):
    """-> {"fixed": {cid: seed}, "ready": {cid: seed}, "failed": {cid: [사실]}, "ok": [cid], "skipped": [cid]}
    skip_done: 지난번에 검사한 그림(고친 뒤 그림 포함)이 그대로면 다시 묻지 않음 (auto 를 다시 돌릴 때)"""
    import nk_webtoon as W
    import nk_edit as E
    apply = STORYFIX_APPLY if apply is None else bool(apply)
    cfg = nk.load_presets()
    qa_cfg = dict(cfg.get("qa") or {})
    ep = conti["_ep"]
    cuts = {int(c["id"]): c for c in conti["cuts"]}
    out = {"fixed": {}, "ready": {}, "failed": {}, "ok": [], "skipped": []}
    d = os.path.join(W.ep_dir(kit, ep), "story")
    os.makedirs(d, exist_ok=True)
    rp = os.path.join(d, "storyfix.json")
    rec = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
    todo, fixes = [], {}
    for cid in sorted(ids or set(cuts) | set(extra or {})):
        cut = cuts.get(cid)
        facts, fx = all_facts(conti, cut, (extra or {}).get(cid, []))
        fixes[cid] = fx
        f = W._final_file(kit, ep, cid)
        if not facts or not os.path.exists(f):
            continue
        old = rec.get(str(cid)) or {}
        if skip_done and old.get("facts") == facts and E._md5(f) in (old.get("final_md5"), old.get("after_md5")):
            out["skipped"].append(cid); continue
        todo.append((cid, facts, f))
    if dry:
        for cid, facts, _ in todo:
            print("[dry] cut %d: %s" % (cid, facts))
        return out
    if not todo:
        return out
    # ① 묻기
    wrong = {}
    try:
        nk.Comfy(cfg.get("server", "auto")).free()          # 검수 AI 가 GPU 를 쓸 수 있게
    except Exception:
        pass
    for cid, facts, f in todo:
        ans, _ = ask(nk, qa_cfg, f, facts)
        bad = [fa for i, fa in enumerate(facts) if ans.get("f%d" % (i + 1)) is False]
        rec[str(cid)] = {"facts": facts, "wrong": bad, "answers": ans, "time": time.strftime("%m-%d %H:%M"), "final_md5": E._md5(f)}
        if bad:
            print("[story] cut %d: not shown -> %s" % (cid, bad)); wrong[cid] = (facts, bad)
        else:
            print("[story] cut %d: ok" % cid); out["ok"].append(cid)
    json.dump(rec, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not wrong or not edit:
        out["failed"].update({k: v[1] for k, v in wrong.items()} if not edit else {})
        nk.ollama_unload(qa_cfg)
        return out
    # ② 고치기 (Qwen)
    nk.ollama_unload(qa_cfg)
    made_all = {}
    for cid, (facts, bad) in sorted(wrong.items()):
        plain = [w for w in bad if w not in fixes.get(cid, {})]
        parts = (["Change the picture so that " + "; ".join(w[0].lower() + w[1:] for w in plain)] if plain else []) + \
            [fixes[cid][w].strip().rstrip(".") for w in bad if w in fixes.get(cid, {})]
        text = ". ".join(parts)
        try:
            made_all[cid] = (text, E.make_candidates(nk, kit, cfg, ep, cid, text, [91 + k for k in range(max(1, int(tries)))]))
        except (Exception, SystemExit) as e:                # 한 컷 편집이 실패해도 나머지는 계속
            print("[story] cut %d: edit failed - %s" % (cid, e))
            rec[str(cid)].update(text=text, error=str(e)); out["failed"][cid] = bad
    # ③ 후보 묻기
    try:
        nk.Comfy(cfg.get("server", "auto")).free()
    except Exception:
        pass
    for cid, (text, made) in sorted(made_all.items()):
        facts, bad = wrong[cid]
        r = rec[str(cid)]
        win, cand = None, {}
        for m in made:
            ok_clean = E.clean(m)
            dz = m[5] if len(m) > 5 else None
            a2, _ = ask(nk, qa_cfg, m[1], facts) if ok_clean else ({}, "")
            good = ok_clean and all(a2.get("f%d" % (i + 1)) is True for i in range(len(facts)))
            cand[str(m[0])] = {"clean": ok_clean, "answers": a2, "pass": good, "change": m[2],
                               "lost": (dz or {}).get("lost"), "gained": (dz or {}).get("gained")}
            why = "PASS" if good else ("not clean (change %.0f%s)" % (m[2], E._dz_text(dz)) if not ok_clean else "still wrong %s" % a2)
            print("[story] cut %d seed %d: %s" % (cid, m[0], why))
            if good and win is None:
                win = m[0]
        r.update(text=text, cand=cand)
        if win and apply:
            E.run_use(W, kit, ep, ["%d=%d" % (cid, win)])
            out["fixed"][cid] = win; r["use"] = win; r["after_md5"] = E._md5(W._final_file(kit, ep, cid))
        elif win:
            out["ready"][cid] = win; r["ready"] = win
        else:
            out["failed"][cid] = bad
    json.dump(rec, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        nk.ollama_unload(qa_cfg)
    except Exception:
        pass
    return out


def run_fix(nk, kit, args):
    import nk_webtoon as W
    conti = W.load_conti(nk, kit, args.ep)
    out = storyfix(nk, kit, conti, [int(x) for x in args.cuts] or None, args.tries or 2, True if args.apply else None, args.dry,
                   _facts_arg(args.facts))
    print("storyfix %s: fixed %s | candidate ready (nk ep edit %s --use N=S) %s | no fix %s"
          % (args.ep, out["fixed"], args.ep, out["ready"], list(out["failed"])))


def add_parser(esub, nk, kit):
    a = esub.add_parser("storyfix", help="cuts whose picture does not show their 'show:' facts -> Qwen edit candidates, checked again")
    a.add_argument("ep")
    a.add_argument("cuts", nargs="*")
    a.add_argument("--tries", type=int, help="edit candidates per cut (default 2)")
    a.add_argument("--apply", action="store_true", help="use a candidate that passes (default: candidates only)")
    a.add_argument("--facts", help='extra facts like storycheck: "9=The cookies are burnt black"')
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run_fix(nk, kit, x))

    a = esub.add_parser("storycheck", help="does each picture show what the conti says? (vision QA on 'show:' facts or --facts)")
    a.add_argument("ep")
    a.add_argument("cuts", nargs="*")
    a.add_argument("--facts", help='extra facts: "9=The cookies are burnt black|Smoke rises;15=No rain"')
    a.add_argument("--style", help="check the restyled picture (cuts_<style>) instead of the final")
    a.set_defaults(func=lambda x: run(nk, kit, x))
