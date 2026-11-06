# -*- coding: utf-8 -*-
"""nk ep auto <ep> — 콘티 한 편을 처음부터 끝까지 자동으로

왜: 시험 만화에서 가장 큰 병목은 그림 품질이 아니라 '단계 사이를 사람이 이어 줘야 한다'는 것이었음
.
무엇: 이미 있는 도구를 순서대로 돌리고, 단계마다 결과를 기록하고, 마지막에 사람이 볼 검토 한 장을 만듦.
    check -> layout -> make -> facefix -> backfix -> restyle -> letter -> review
    - 단계가 실패해도(sys.exit) 기록하고 다음 단계로 (make 실패만 멈춤)
    - 다시 돌리면 끝난 단계는 건너뜀 (--from 단계 로 그 단계부터 다시)
    - layout: 두 명 컷(MB/O)에 뼈대 그림이 없으면 Anima 배치 3장 -> 두 사람 뼈대 점이 많고 몸이 덜 겹치는 것을 자동으로 고름
      (규칙: 몸 안 겹침 = conti_rules)
    - review: 모든 컷을 한 장에 + 자동 검수가 걸러 낸 흠 목록 (episodes/<ep>/auto/review.png, review.md)
사람이 할 일: review를 보고 고칠 컷만 ep redo / pick / facefix --use."""
import os, sys, json, time, argparse

ANIMA_SKIP = ("layout", "propfix", "facefix", "compose", "unify", "handfix", "backfix", "restyle")
STEPS = ["write", "compile", "check", "layout", "make", "propfix", "facefix", "compose", "unify", "story", "handfix", "backfix",
         "restyle", "letter", "review"]
#   소품 넣기도 합치기 앞 (재료 혼자 컷에 소품이 있으면 좋음). 손 고치기는 합친 컷까지 보려고 합치기 뒤
UNIFY_DEFAULT = 0.4
#   show 가 없는 컷은 건너뜀. 끄기/묻기만: 콘티 story: off / check, 또는 --story off / check. 되돌리기 nk ep edit <ep> --use N=0
STORY_DEFAULT = "suggest"


def _compose_cuts(W, conti, args):
    """이 에피소드에서 합치기로 만들 두 명 컷 id 집합 (--duo draw 면 없음)"""
    if getattr(args, "duo", "compose") != "compose":
        return set()
    import nk_compose
    return {int(c["id"]) for c in conti["cuts"] if W._is_duo(c) and nk_compose.can_compose(conti, c)}


def _layer_cuts(W, conti, args):
    """--duo layer: 누끼 레이어로 만들 두 명 컷 id 집합"""
    if getattr(args, "duo", "compose") != "layer":
        return set()
    return {int(c["id"]) for c in conti["cuts"] if W._is_duo(c)}


def _ns(**kw):
    return argparse.Namespace(**kw)


def _state_path(W, kit, ep):
    d = os.path.join(W.ep_dir(kit, ep), "auto")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "state.json")


def _call(fn, *a):
    """단계 함수 실행. sys.exit를 잡아서 (코드, 걸린 초) 로 돌려줌"""
    t0 = time.time()
    try:
        fn(*a)
        rc = 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except KeyboardInterrupt:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 99                      # 코드 오류 = 기록하고 다음 단계로 (make만 멈춤)
    return rc, int(time.time() - t0)


def _guard(rec, fn, *a):
    """_call 과 같지만 단계 함수의 돌려준 값(rc)을 살림. ComfyUI 작업 실패(sys.exit)로 auto 전체가 기록 없이 끝나지 않게"""
    try:
        return fn(*a)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if rc:
            rec.setdefault("notes", []).append("stopped with exit %s (look at the log above)" % rc)
        return rc
    except KeyboardInterrupt:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        rec.setdefault("notes", []).append("code error: %s" % e)
        return 99


# ---------------------------------------------------------------- layout 자동 고르기
def _layout_score(nk_pose, path, spans, back):
    """(점수, 사람별 점 수, 겹침) — 점수 = 두 사람 중 적은 쪽 점 수 - 겹침 x 10"""
    import numpy as np
    _, _, npts, people = nk_pose.pose_image(path, spans, back=back)
    boxes = []
    for k, c in people:
        ok = c >= 0.3
        if ok.sum() < 3:
            boxes.append(None); continue
        xs = k[ok][:, 0]
        boxes.append((float(xs.min()), float(xs.max())))
    ov = 1.0
    if len(boxes) == 2 and all(boxes):
        (a0, a1), (b0, b1) = boxes
        inter = max(0.0, min(a1, b1) - max(a0, b0))
        ov = inter / max(1.0, min(a1 - a0, b1 - b0))
    return min(npts) - 10.0 * ov, npts, round(ov, 2)


def step_compose(nk, kit, W, args, conti, rec):
    """두 명 컷 = 혼자 컷 최종본 두 장 합치기. 최종본이 없는 컷만 (--redo-duo 면 예전 방식으로 그린 최종본도 바꿈, 원본 보관)"""
    if getattr(args, "duo", "") == "layer":
        return step_layer(nk, kit, W, args, conti, rec)
    import nk_compose
    comp = _compose_cuts(W, conti, args)
    if not comp:
        rec["notes"] = ["no two-character cut to compose" + (" (--duo draw)" if getattr(args, "duo", "") == "draw" else "")]
        return 0
    todo = []
    for cid in sorted(comp):
        f = W._final_file(kit, args.ep, cid)
        if not os.path.exists(f):
            todo.append(cid)
        elif getattr(args, "redo_duo", False) and not W._composed(kit, args.ep, cid, f):
            todo.append(cid)                    # 최종본이 합치기(+unify)로 만든 것이 아님 -> 바꿈 (원본은 cuts_compose/orig/)
    if not todo:
        rec["notes"] = ["every two-character cut already has a final picture (--redo-duo to replace drawn ones)"]
        return 0
    out = nk_compose.auto(nk, kit, conti, todo, dry=args.dry)
    rec["used"] = {str(k): v for k, v in out["used"].items()}
    if out["flags"]:
        rec["flags"] = ["cut %d: %s" % (k, "; ".join(v)) for k, v in out["flags"].items()]
    if out["failed"]:
        rec.setdefault("flags", []).extend("cut %d: compose failed - %s" % (k, v) for k, v in out["failed"].items())
    return 0 if not out["failed"] else 1


def step_layer(nk, kit, W, args, conti, rec):
    """--duo layer: 두 명 컷을 누끼 레이어로 (nk_layer). 최종본이 없는 컷만 (--redo-duo 면 누끼 레이어가 만들지 않은 최종본도 바꿈, 원본 보관)"""
    import nk_layer
    rp = os.path.join(W.ep_dir(kit, args.ep), "cuts_layer", "layer.json")
    lr = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
    todo = []
    for cid in sorted(_layer_cuts(W, conti, args)):
        f = W._final_file(kit, args.ep, cid)
        if not os.path.exists(f):
            todo.append(cid)
        elif getattr(args, "redo_duo", False) and nk_layer._md5(f) != (lr.get(str(cid)) or {}).get("final_md5"):
            todo.append(cid)
    if not todo:
        rec["notes"] = ["every two-character cut already has a final picture (--redo-duo to replace ones not made by layer)"]
        return 0
    out = nk_layer.draw(nk, kit, conti, todo, dry=args.dry)
    rec["used"] = {str(k): v for k, v in out["used"].items()}
    rec["notes"] = ["layer: cuts %s -> %s (candidates episodes/%s/cuts_layer/cutNN/comp, change: nk ep layer %s --use N=A_SF)"
                    % (todo, rec["used"], args.ep, args.ep)]
    if out["failed"]:
        rec["flags"] = ["cut %d: layer failed - %s" % (k, v) for k, v in out["failed"].items()]
    return 0 if not out["failed"] else 1


def _unify_level(conti, args):
    """0 = 끔. --unify 가 콘티보다 먼저, 둘 다 없으면 UNIFY_DEFAULT (off/none/0 = 끔)"""
    v = getattr(args, "unify", None)
    if v is None:
        v = (conti.get("duo") or {}).get("unify", UNIFY_DEFAULT)
    if v in (None, False, "", "off", "none", "no"):
        return 0.0
    try:
        return max(0.0, min(0.8, float(v)))
    except (TypeError, ValueError):
        return 0.0


def step_unify(nk, kit, W, args, conti, rec):
    """합치기로 만든 두 명 컷(지금 최종본 = 합친 그림 그대로)만 다시 칠함. 이미 칠했거나 손으로 바꾼 컷은 건너뜀"""
    dn = _unify_level(conti, args)
    if not dn:
        rec["notes"] = ["off (conti duo: {unify: off} or --unify off)"]
        return 0
    import nk_compose, nk_regional
    if not args.dry:
        try:
            c = nk.Comfy(nk.load_presets().get("server", "auto"))
            miss = [n for n in nk_regional.AM_NODES if n not in c._get("/object_info/" + n)]
        except Exception as e:
            miss = ["(ComfyUI check failed: %s)" % e]
        if miss:
            rec["notes"] = ["skipped: ComfyUI has no %s (Acly comfyui-tooling-nodes)" % ", ".join(miss)]
            return 0
    p = os.path.join(W.ep_dir(kit, args.ep), "cuts_compose", "compose.json")
    cr = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    todo = [int(k) for k, r in cr.items() if r.get("final_md5") and r.get("final_md5") == nk_compose._md5(W._final_file(kit, args.ep, int(k)))]
    if not todo:
        rec["notes"] = ["no composed two-character cut to repaint (already done or changed by hand)"]
        return 0
    out = nk_regional.unify(nk, kit, conti, sorted(todo), dn, (71,), True, args.dry)
    rec["used"] = {str(k): v for k, v in out["used"].items()}
    if out["flags"]:                           # 흠 목록은 review가 unify.json에서 읽음 (최종본이 그대로일 때만)
        rec["notes"] = ["cut %d: %s" % (k, "; ".join(v)) for k, v in out["flags"].items()]
    return 0


def _story_mode(conti, args):
    v = getattr(args, "story", None) or (conti or {}).get("story")
    if not v and getattr(args, "render", "anima") == "anima":
        #   켜려면 --story suggest/check/fix 또는 콘티 story:
        v = "off"
    v = v or STORY_DEFAULT
    v = str(v).lower()
    return "off" if v in ("off", "none", "no", "false", "0") else (v if v in ("check", "fix") else "suggest")


def step_story(nk, kit, W, args, conti, rec):
    """show: 사실이 있는 컷만. 다시 돌려도 이미 검사한 그림(고친 그림 포함)이 그대로면 건너뜀"""
    import nk_story
    mode = _story_mode(conti, args)
    if mode == "off":
        rec["notes"] = ["off (conti story: off or --story off)"]; return 0
    ids = [int(c["id"]) for c in conti["cuts"] if nk_story.all_facts(conti, c)[0]]
    if not ids:
        rec["notes"] = ["no cut has show: facts (plan.yaml show:, docs/prompt_plan.md) or character design_show"]; return 0
    out = nk_story.storyfix(nk, kit, conti, ids, 2, mode == "fix", args.dry, None, skip_done=args.start != "story",
                            edit=mode in ("fix", "suggest"))
    rec["notes"] = ["%d cuts with facts: ok %s, fixed %s, fix ready %s, not fixed %s, unchanged since last check %s"
                    % (len(ids), out["ok"], sorted(out["fixed"]), sorted(out["ready"]), sorted(out["failed"]), out["skipped"])]
    rec["used"] = {str(k): v for k, v in out["fixed"].items()}
    return 0


def step_layout(nk, kit, W, args, conti, rec):
    import nk_pose
    need = []
    comp = _compose_cuts(W, conti, args)
    layer = _layer_cuts(W, conti, args)
    for ct in conti["cuts"]:
        if not W._is_duo(ct) or int(ct["id"]) in comp:      # 합치기로 만들 컷은 배치 그림이 필요 없음
            continue
        modes = W._duo_modes(conti, ct)
        if int(ct["id"]) not in layer and not any(m[:1] == "O" or m[:2] == "MB" for m in modes):
            continue
        if os.path.exists(W._pose_file(kit, args.ep, ct["id"])):
            continue
        need.append(ct)
    if not need:
        rec["notes"] = ["every two-character cut already has a pose"]
        return 0
    cfg = nk.load_presets()
    lay = os.path.join(cfg.get("output_root", os.path.join(kit, "runs")), args.ep, "layout")
    seeds = int(args.layout_seeds)
    rc, _ = _call(nk_pose.layout, nk, kit, _ns(ep=args.ep, cuts=[int(c["id"]) for c in need], seeds=seeds, dry=args.dry))
    if rc or args.dry:
        return rc
    picks = {}
    for ct in need:
        cid = int(ct["id"])
        spans = [tuple(r["span"]) if r.get("span") else W.SIDES[str(r.get("side", "left"))] for r, _ in ct["_roles"]]
        back = str(ct.get("angle", "")) == "back"
        best = None
        for k in range(1, seeds + 1):
            name = "cut%02d_s%d.png" % (cid, k)
            p = os.path.join(lay, name)
            if not os.path.exists(p):
                continue
            sc, npts, ov = _layout_score(nk_pose, p, spans, back)
            print("[layout] cut %d %s: score %.1f points %s overlap %.2f" % (cid, name, sc, npts, ov))
            if best is None or sc > best[0]:
                best = (sc, name, npts, ov)
        if best is None:
            rec.setdefault("flags", []).append("cut %d: no layout picture" % cid); continue
        _call(nk_pose.pose, nk, kit, _ns(ep=args.ep, cut=cid, image=best[1]))
        picks[cid] = {"image": best[1], "points": best[2], "overlap": best[3]}
        if str(ct.get("shot", "")) == "waist":
            z = nk_pose.frame_pose_file(W._pose_file(kit, args.ep, cid), "waist")
            picks[cid]["framed_zoom"] = round(z, 3)
            print("[layout] cut %d: waist shot -> pose zoom x%.2f" % (cid, z))
        if min(best[2]) < 8 or best[3] > 0.3:
            rec.setdefault("flags", []).append("cut %d: layout %s weak (points %s, overlap %.2f) - look at runs/%s/layout/cut%02d_pose_check.png"
                                               % (cid, best[1], best[2], best[3], args.ep, cid))
    rec["picks"] = picks
    return 0


# ---------------------------------------------------------------- review 한 장
def _fmd5(p):
    import hashlib
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def _flags(W, kit, ep, style):
    """자동 검수·고치기 기록에서 사람이 볼 흠 목록 {cut: [문장]}"""
    d = W.ep_dir(kit, ep)
    out = {}

    def add(cid, s):
        out.setdefault(int(cid), []).append(s)
    try:
        auto = json.load(open(os.path.join(d, "auto.json"), encoding="utf-8"))
        for cid, r in auto.items():
            notes = r.get("notes") or []
            pk = int(r.get("pick") or 1)
            if 0 < pk <= len(notes) and str(notes[pk - 1]).startswith("x"):
                add(cid, "no candidate passed QA (%s)" % str(notes[pk - 1])[2:])
    except Exception:
        pass
    try:
        ff = json.load(open(os.path.join(d, "cuts_facefix", "facefix.json"), encoding="utf-8"))
        for cid, r in ff.items():
            if r.get("final_md5") and r.get("final_md5") != _fmd5(W._final_file(kit, ep, int(cid))):
                continue
            if r.get("seeds") and not r.get("use"):
                add(cid, "face fix: no candidate passed (look at cuts_facefix/cand/cut%02d_*_head.png)" % int(cid))
            elif r.get("rescue") and not r.get("manual"):
                add(cid, "face fix: broken face replaced by a better but not perfect one (mark %.2f -> %.2f) - check "
                         "cuts_facefix/cand/cut%02d_s%s_head.png (back: nk ep facefix %s --use %s=0)"
                    % (r["rescue"]["orig_mark"], r["rescue"]["mark"], int(cid), r.get("use"), ep, cid))
    except Exception:
        pass
    try:
        hf = json.load(open(os.path.join(d, "cuts_handfix", "handfix.json"), encoding="utf-8"))
        for cid, r in hf.items():
            if r.get("applied") or r.get("final_md5") != _fmd5(W._final_file(kit, ep, int(cid))):
                continue
            for h in r.get("hands") or []:
                if not h.get("flaw"):
                    continue
                if h.get("use"):
                    add(cid, "hand %s (%s): %s - a fix is ready (%s), look at cuts_handfix/cand/cut%02d_h%s.png "
                             "(it may be a pink marking, not a hand) -> nk ep handfix %s %s --apply"
                        % (h["j"], h.get("owner"), h["flaw"], h["use"], int(cid), h["j"], ep, cid))
                else:
                    add(cid, "hand %s (%s): %s - no candidate fixed it (cuts_handfix/cand/cut%02d_h%s.png)"
                        % (h["j"], h.get("owner"), h["flaw"], int(cid), h["j"]))
    except Exception:
        pass
    propfixed = set()
    try:
        pf = json.load(open(os.path.join(d, "cuts_propfix", "propfix.json"), encoding="utf-8"))
        for cid, r in pf.items():
            if r.get("final_md5") != _fmd5(W._final_file(kit, ep, int(cid))):
                continue
            if r.get("use"):
                add(cid, "prop added by propfix (seed %s) - check it fits (back: nk ep propfix %s --use %s=0)" % (r["use"], ep, cid))
                propfixed.add(int(cid))
            else:
                add(cid, "prop still missing: %s (propfix found no clean candidate, see cuts_propfix/cut%02d_cmp.png)"
                    % (", ".join(r.get("miss") or []), int(cid)))
    except Exception:
        pass
    try:
        cr = json.load(open(os.path.join(d, "cuts_compose", "compose.json"), encoding="utf-8"))
        for cid, r in cr.items():
            if r.get("flags") and r.get("final_md5") == _fmd5(W._final_file(kit, ep, int(cid))):
                add(cid, "compose: " + "; ".join(r["flags"]) + " (other seed: nk ep compose %s --use %s=<seed>)" % (ep, cid))
    except Exception:
        pass
    try:
        ur = json.load(open(os.path.join(d, "cuts_unify", "unify.json"), encoding="utf-8"))
        for cid, r in ur.items():
            if r.get("flags") and r.get("final_md5") == _fmd5(W._final_file(kit, ep, int(cid))):
                add(cid, "unify: " + "; ".join(r["flags"]) + " (back to the compose picture: nk ep unify %s --use %s=0)" % (ep, cid))
    except Exception:
        pass
    try:
        sr = json.load(open(os.path.join(d, "story", "storyfix.json"), encoding="utf-8"))
        for cid, r in sr.items():
            cur = _fmd5(W._final_file(kit, ep, int(cid)))
            if r.get("use") and r.get("after_md5") == cur:
                add(cid, "story fix applied (edit seed %s: %s) - check the picture (back: nk ep edit %s --use %s=0)"
                    % (r["use"], "; ".join(r.get("wrong") or []), ep, cid))
            elif r.get("wrong") and r.get("final_md5") == cur:
                add(cid, "story: the picture may not show: %s%s" % ("; ".join(r["wrong"]),
                    (" - a fix is ready: nk ep edit %s --use %s=%s" % (ep, cid, r["ready"])) if r.get("ready")
                    else (" (no clean edit passed, see cuts_edit/cut%02d_cmp.png)" % int(cid)) if r.get("cand")
                    else " (not fixed yet - nk ep storyfix %s %s --apply)" % (ep, cid)))
    except Exception:
        pass
    if style:
        try:
            ck = json.load(open(os.path.join(d, "cuts_" + style, "check.json"), encoding="utf-8"))
            for cid, r in ck.items():
                u = r.get("use")
                fl = (r.get("s%s" % u) or {}).get("flags") if u else None
                if r.get("fallback"):
                    add(cid, "restyle: " + r["fallback"])
                elif fl:
                    add(cid, "restyle: " + "; ".join(fl))
        except Exception:
            pass
    for cid in propfixed:                      # 소품 넣기로 고친 컷: 초안 검수의 '소품 없음'은 지난 이야기
        out[cid] = [x for x in out.get(cid, []) if not x.startswith("no candidate passed QA (cut_q")]
    return {k: v for k, v in out.items() if v}


def step_review(nk, kit, W, args, conti, rec, state):
    from PIL import Image, ImageDraw
    style = args.style
    d = W.ep_dir(kit, args.ep)
    src_dir = os.path.join(d, "cuts_" + style) if style and os.path.isdir(os.path.join(d, "cuts_" + style)) else os.path.join(d, "cuts")
    fl = _flags(W, kit, args.ep, style)
    if getattr(args, "render", "anima") == "anima":
        try:
            import nk_headcheck
            _call(nk_headcheck.run, nk, kit, _ns(ep=args.ep, cuts=[], dry=getattr(args, "dry", False)))
            hc = json.load(open(os.path.join(d, "headcheck.json"), encoding="utf-8"))
            for k, v in hc.items():
                if v.get("flag"):
                    fl.setdefault(int(k[3:]), []).append("머리 수 (제안만): %s" % v["flag"])
        except Exception as e:
            print("[note] headcheck skipped (%s)" % e)
    for s in STEPS:
        for f in (state.get(s) or {}).get("flags", []):
            try:
                fl.setdefault(int(f.split()[1].rstrip(":")), []).append(f.split(":", 1)[1].strip())
            except Exception:
                pass
    ids = [int(ct["id"]) for ct in conti["cuts"]]
    th, maxw = 320, 2600
    tiles = []
    for cid in ids:
        p = os.path.join(src_dir, "cut%02d.png" % cid)
        if not os.path.exists(p):
            p = W._final_file(kit, args.ep, cid)
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB")
        im = im.resize((max(1, int(im.width * th / im.height)), th))
        tiles.append((cid, im))
    if not tiles:
        rec["notes"] = ["no pictures"]; return 1
    # 줄 채우기: 가로 긴 컷(풍경)과 세로 컷을 실제 폭대로 왼쪽부터 놓고 maxw를 넘으면 다음 줄
    pos, x, y, gap, lab = [], 12, 12, 14, 30
    for cid, t in tiles:
        if x + t.width > maxw and x > 12:
            x, y = 12, y + th + lab + gap
        pos.append((cid, t, x, y))
        x += t.width + gap
    W_ = max(px + t.width for _, t, px, _ in pos) + 12
    sheet = Image.new("RGB", (W_, y + th + lab + 12), "white")
    dr = ImageDraw.Draw(sheet)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=22)       # Pillow 10.1+
    except Exception:
        font = None
    for cid, t, px, py in pos:
        sheet.paste(t, (px, py + lab))
        bad = cid in fl
        dr.rectangle([px - 4, py + lab - 4, px + t.width + 3, py + lab + th + 3], outline=(220, 30, 30) if bad else (205, 205, 205),
                     width=4 if bad else 2)
        dr.text((px, py + 2), "cut %d%s" % (cid, "   ! %d" % len(fl[cid]) if bad else ""), fill=(200, 0, 0) if bad else (0, 0, 0),
                font=font)
    out_dir = os.path.join(d, "auto")
    png = os.path.join(out_dir, "review.png")
    sheet.save(png)
    lines = ["# %s 자동 제작 검토 (%s)" % (args.ep, time.strftime("%Y-%m-%d %H:%M")), "",
             "그림: auto/review.png (빨간 테두리 = 자동 검수가 걸러 낸 컷)", "",
             "## 단계", ""]
    for s in STEPS:
        r = state.get(s) or {}
        lines.append("- %s: %s%s" % (s, r.get("status", "-"), (" (%ss)" % r["secs"]) if r.get("secs") is not None else ""))
    lines += ["", "## 사람이 볼 컷 (자동 검수 기준 — 얼굴은 무늬 점수, 손은 색만 봄. 손 모양·귀 깨짐은 아직 못 봄)", ""]
    if not fl:
        lines.append("- (자동 검수가 걸러 낸 컷 없음 — 그래도 전체를 한 번 봄)")
    for cid in sorted(fl):
        for s in fl[cid]:
            lines.append("- cut %d: %s" % (cid, s))
    # -> 고치기 전|후 머리를 한 장에 모아서 사람이 반드시 봄 (auto/review_faces.png)
    faces = []
    try:
        ff = json.load(open(os.path.join(d, "cuts_facefix", "facefix.json"), encoding="utf-8"))
        for cid, r in sorted(ff.items(), key=lambda x: int(x[0])):
            u = r.get("use")
            hp = os.path.join(d, "cuts_facefix", "cand", "cut%02d_s%s_head.png" % (int(cid), u))
            if r.get("final_md5") and r.get("final_md5") != _fmd5(W._final_file(kit, args.ep, int(cid))):
                continue                                # 옛 기록 (그 뒤에 컷이 바뀜)
            if u and os.path.exists(hp):
                faces.append((int(cid), u, hp))
    except Exception:
        pass
    if faces:
        fh = 300
        ims = []
        for cid, u, hp in faces:
            im = Image.open(hp).convert("RGB")
            ims.append((cid, u, im.resize((max(1, int(im.width * fh / im.height)), fh))))
        fw = max(im.width for _, _, im in ims)
        cols = max(1, 2600 // (fw + 14))
        rows_n = (len(ims) + cols - 1) // cols
        fs = Image.new("RGB", (cols * (fw + 14) + 14, rows_n * (fh + 44) + 14), "white")
        fd = ImageDraw.Draw(fs)
        for i, (cid, u, im) in enumerate(ims):
            r_, c_ = divmod(i, cols)
            px, py = 14 + c_ * (fw + 14), 14 + r_ * (fh + 44)
            fs.paste(im, (px, py + 30))
            fd.text((px, py + 4), "cut %d  (before | after, seed %s)" % (cid, u), fill=(0, 0, 0), font=font)
        fs.save(os.path.join(out_dir, "review_faces.png"))
        lines += ["", "## 얼굴 고치기가 바꾼 컷 — 깨졌는지 반드시 볼 것 (auto/review_faces.png = 고치기 전 | 후)", ""]
        lines += ["- cut %d: seed %s  (되돌리기: nk ep facefix %s --use %d=0)" % (cid, u, args.ep, cid) for cid, u, _ in faces]
    open(os.path.join(out_dir, "review.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    rec["notes"] = ["%d cuts, %d flagged, %d face-fixed" % (len(tiles), len(fl), len(faces))]
    print("review -> %s\n          %s" % (png, os.path.join(out_dir, "review.md")))
    return 0


# ---------------------------------------------------------------- 전체
def step_write(nk, kit, W, args, rec):
    """request.yaml -> plan.yaml. 이미 plan.yaml이 있으면 건너뜀. prompt 백엔드면 여기서 멈추고 사람(웹 AI)을 기다림"""
    import nk_plan
    d = W.ep_dir(kit, args.ep)
    if os.path.exists(os.path.join(d, "plan.yaml")):
        rec["notes"] = ["plan.yaml exists"]; return 0
    if not os.path.exists(os.path.join(d, "request.yaml")):
        rec["notes"] = ["no request.yaml / plan.yaml - using conti.yaml as it is"]; return 0
    rc, _ = _call(nk_plan.run_write, nk, kit, _ns(ep=args.ep, backend=args.writer, model=args.model, ctx=16384, temperature=0.7,
                                                  fix=2, cpu=False, nocompile=True, out=None))
    if args.writer == "prompt":
        print("\n[STOP] 사람 차례 (AI 채팅):\n  1. episodes\\%s\\write_prompt.md 내용을 전부 복사해서 AI 채팅에 붙여 넣기\n"
              "  2. AI 답을 전부 복사해서 episodes\\%s\\plan.yaml 로 저장 (설명 문장·```yaml 이 섞여 있어도 됨)\n"
              "  3. 다시: nk ep auto %s" % (args.ep, args.ep, args.ep))
        sys.exit(0)
    return rc


def step_compile(nk, kit, W, args, rec):
    """plan.yaml -> conti.yaml (plan이 conti보다 새것이거나 conti가 없을 때). 손으로 쓴 conti만 있고 plan이 없으면 그대로"""
    import nk_plan
    d = W.ep_dir(kit, args.ep)
    pp, cp = os.path.join(d, "plan.yaml"), os.path.join(d, "conti.yaml")
    if not os.path.exists(pp):
        rec["notes"] = ["no plan.yaml - conti.yaml as it is"]; return 0 if os.path.exists(cp) else 1
    if os.path.exists(cp) and os.path.getmtime(cp) >= os.path.getmtime(pp) and "plan.yaml에서 자동 생성" in open(cp, encoding="utf-8").read(2000):
        rec["notes"] = ["conti.yaml is newer than plan.yaml"]; return 0
    rc, _ = _call(nk_plan.run_compile, nk, kit, _ns(ep=args.ep, dry=args.dry, plan=None))
    return rc


def _lora_key(conti):
    """콘티 cast 에서 Anima LoRA 가 있는 캐릭터 키 (없으면 None). 한 만화에 LoRA 캐릭터는 하나로 봄 (둘이면 첫 것)"""
    for k, ch in (conti.get("_cast") or {}).items():
        if ch and ch.get("anima_lora"):
            return k
    return None


#   기록이 없는 옛 편 = 이미 있는 컷은 끝난 것으로 봄. 끊길 때 쓰다 만(깨진) 그림은 지우고 다시 그림.
FACEPASS = "facepass.json"


def _png_ok(p):
    try:
        from PIL import Image
        with Image.open(p) as im:
            im.verify()
        return True
    except Exception:
        return False


def facepass_load(d, lora_cuts_existing):
    p = os.path.join(d, FACEPASS)
    try:
        return set(int(x) for x in json.load(open(p, encoding="utf-8")).get("done", []))
    except Exception:
        return set(lora_cuts_existing)


def facepass_save(d, done):
    p = os.path.join(d, FACEPASS)
    json.dump({"done": sorted(done)}, open(p + ".tmp", "w", encoding="utf-8"))
    os.replace(p + ".tmp", p)


def _duosplit_on(nk, kit, W, ep, conti):
    """LoRA 없는 두 명 컷을 나눠 그리나 -> (True/False, 이유).
    끄기 = duosplit_settings.yaml 의 enabled: false, 또는 계획표·콘티의 duo_split: off (파일이 없거나 못 읽으면 켬)"""
    import nk_duosplit
    try:
        return nk_duosplit.enabled(kit, conti, os.path.join(W.ep_dir(kit, ep), "plan.yaml"))
    except Exception as e:
        return True, "check failed: %s" % e


def step_make_anima(nk, kit, W, args, conti, rec):
    """Anima 흐름: 계획표의 컷을 그림
    ① 혼자 컷·사람 없는 컷 = nk ep animamake (Anima 한 번에, 그 캐릭터 LoRA 는 혼자 컷에만)
    ①-2 LoRA 캐릭터 없는 두 명 컷 = nk_duosplit.run (나눠 그리기: 기준 그림 -> SAM3 두 사람 자리 -> 사람마다 자기 구역에서 자기 글로만
       다시 그림 -> 두 사람 옷·생김새가 덜 섞임). 끄기 = duosplit_settings.yaml enabled: false 또는 계획표 duo_split: off.
       끄거나 ComfyUI 에 Impact Pack 이 없으면 ① 처럼 한 번에 그림 (Impact Pack 이 없으면 경고 한 줄)
    ② LoRA 캐릭터가 나오는 두 명 컷 = nk ep regionlora --split (그 캐릭터 자리만 LoRA + 그 캐릭터 설명,
       밖 = LoRA 없음, 사람 상대는 furry·anthro 뺌 -> 상대에게 무늬·옷이 번지는 것을 줄임)
    ③ 이번에 새로 그린 컷 중 LoRA 캐릭터가 나오는 컷 = 얼굴만 한 번 더 (nk ep animafix --desc head 0.6, 원본은 _alt/preface)
    이미 있는 컷은 건너뜀 (다시 그리려면 컷을 _alt 로 옮기고 --from make)"""
    import shutil
    import nk_animacut, nk_regionlora, nk_animafix, nk_duosplit
    lk = _lora_key(conti)
    ids = [int(c["id"]) for c in conti["cuts"]]
    ed = W.ep_dir(kit, args.ep)
    if not args.dry:
        for i in ids:                                   # 끊길 때 쓰다 만 그림 (열리지 않는 png) 은 지우고 다시
            f = W._final_file(kit, args.ep, i)
            if os.path.exists(f) and not _png_ok(f):
                print("[note] cut %d: broken picture (interrupted?) - redraw" % i)
                os.remove(f)
    before = {i for i in ids if os.path.exists(W._final_file(kit, args.ep, i))}
    lora_cuts = [int(c["id"]) for c in conti["cuts"]
                 if lk and (lk in [str(r.get("char")) for r in c.get("cast") or []] or str(c.get("_charkey")) == lk)]
    #   -> 캐릭터 파일 anima_face_pass: false 면 얼굴 다듬기를 안 함 (없으면 예전처럼 함. 되돌리기 = true)
    fp_on = bool(lk) and str((conti["_cast"].get(lk) or {}).get("anima_face_pass", True)).strip().lower() not in ("false", "0", "off", "no", "none")
    fdone = facepass_load(ed, [i for i in lora_cuts if i in before])
    fdone -= {i for i in ids if i not in before}        # 이제 새로 그릴 컷은 얼굴 다듬기를 다시 해야 함
    if not args.dry and fp_on:
        facepass_save(ed, fdone)
    duo_lora = []
    if lk:
        for c in conti["cuts"]:
            if c.get("cast") and lk in [str(r.get("char")) for r in c["cast"]]:
                duo_lora.append(int(c["id"]))
    notes, rc = [], 0
    duo_nolora = [int(c["id"]) for c in conti["cuts"] if int(c["id"]) not in duo_lora and nk_duosplit.is_duo(c)]
    if duo_nolora:
        on, why = _duosplit_on(nk, kit, W, args.ep, conti)
        if not on:                                      # 끔 -> 혼자 컷과 같은 길(animamake)로 한 번에
            print("[note] duosplit off (%s) - two-character cuts %s are drawn in one pass" % (why, duo_nolora))
            notes.append("duosplit off (%s): cuts %s drawn in one pass" % (why, duo_nolora))
            duo_nolora = []
    rest = [i for i in ids if i not in duo_lora and i not in duo_nolora and i not in before]
    todo_duo = [i for i in duo_lora if i not in before]
    todo_nolora = [i for i in duo_nolora if i not in before]
    d = nk_animacut.DEFAULT
    if rest:
        r1, _ = _call(nk_animacut.run, nk, kit, _ns(ep=args.ep, cuts=[str(i) for i in rest], unet=d["unet"], steps=d["steps"], cfg=d["cfg"],
                                                     sampler=d["sampler"], shift=None, artist=None, seed="500", force=False,
                                                     nolora=False, dry=args.dry))
        notes.append("animamake cuts %s rc %s" % (rest, r1)); rc = rc or r1
    if todo_duo:
        find = W.find_word(conti["_cast"][lk])
        r2, _ = _call(nk_regionlora.run, nk, kit, _ns(ep=args.ep, cuts=[str(i) for i in todo_duo], who=lk, find=find, to=args.ep,
                                                       unet=d["unet"], steps="32", cfg="5.0", base_only="6", overlap="10", lora_strength=None,
                                                       seed="500", redo=False, dry=args.dry, invert=False, split=True,
                                                       overlap_fix="subtract", covered_warn=0.0))
        notes.append("regionlora --split cuts %s rc %s" % (todo_duo, r2)); rc = rc or r2
    if todo_nolora:                                     # 걸음·base_only·cfg 등은 duosplit_settings.yaml
        got = {}                                        # Impact Pack 이 없으면 nk_duosplit.run 이 경고 한 줄을 내고 animamake 로 한 번에 그림
        r4, _ = _call(lambda *a: got.update(nk_duosplit.run(*a) or {}), nk, kit,
                      _ns(ep=args.ep, cuts=[str(i) for i in todo_nolora], unet=d["unet"], seed="500", force=False, dry=args.dry))
        if got.get("one_pass"):
            notes.append("duosplit skipped (no Impact Pack): cuts %s drawn in one pass rc %s" % (got["one_pass"], r4))
        else:
            notes.append("duosplit (no-LoRA two-character split) cuts %s rc %s%s" % (
                todo_nolora, r4, (" - base kept for %s" % got["base_kept"]) if got.get("base_kept") else ""))
        rc = rc or r4
    face = []
    if lk and not fp_on:
        notes.append("face pass off (characters: anima_face_pass false)")
    if fp_on and not args.dry:
        # 얼굴 다듬기 = 그림이 있고 아직 안 다듬은 LoRA 캐릭터 컷 (이번에 그린 것 + 지난번에 그리기만 하고 끊긴 것)
        face = [i for i in lora_cuts if i not in fdone and os.path.exists(W._final_file(kit, args.ep, i))]
        if face:
            alt = os.path.join(W.ep_dir(kit, args.ep), "_alt", "preface")
            os.makedirs(alt, exist_ok=True)
            for i in face:
                shutil.copy(W._final_file(kit, args.ep, i), os.path.join(alt, "cut%02d.png" % i))
            fhead = W.find_word(conti["_cast"][lk]) + " head"
            def _faced(cid):
                fdone.add(int(cid)); facepass_save(ed, fdone)
            r3, _ = _call(nk_animafix.run, nk, kit, _ns(ep=args.ep, cuts=[str(i) for i in face], who=lk, find=fhead,
                                                        denoise="0.6", seed="910", to=args.ep, desc="head", dry=False, on_done=_faced))
            if r3 == 0:                                 # 머리를 못 찾아 건너뛴 컷도 끝난 것으로 (이어 갈 때마다 되풀이하지 않게)
                fdone |= set(face); facepass_save(ed, fdone)
            notes.append("face pass cuts %s rc %s (originals in _alt/preface)" % (face, r3))
    rec["notes"] = notes
    return rc


def run(nk, kit, args):
    import nk_webtoon as W
    if hasattr(nk, "keep_awake"):
        nk.keep_awake()
    conti = None
    if os.path.exists(os.path.join(W.ep_dir(kit, args.ep), "conti.yaml")):
        conti = W.load_conti(nk, kit, args.ep)
    sp = _state_path(W, kit, args.ep)
    state = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) and not args.fresh else {}
    start = STEPS.index(args.start) if args.start else 0
    stop = STEPS.index(args.stop) if args.stop else len(STEPS) - 1
    print("auto %s: steps %s" % (args.ep, " -> ".join(STEPS[start:stop + 1])))

    def style_of(c):
        st = args.style if args.style is not None else (c or {}).get("restyle")
        return None if st in ("none", "off", "", None) else st

    def save():
        if not args.dry:
            json.dump(state, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for i, s in enumerate(STEPS):
        if i < start or i > stop:
            continue
        if (state.get(s) or {}).get("status") == "done" and not args.start and s not in ("write", "compile"):
            print("\n==== [%s] done before - skipped (--from %s to run it again)" % (s, s)); continue
        print("\n==== [%s] %s" % (s, time.strftime("%H:%M:%S")))
        rec = {"start": time.strftime("%Y-%m-%d %H:%M:%S")}
        if getattr(args, "render", "anima") == "anima" and s in ANIMA_SKIP:
            rec.update(status="done", rc=0, secs=0, notes=["--render anima: skipped (NoobAI step)"])
            state[s] = rec
            save()
            print("==== [%s] skipped (--render anima)" % s)
            continue
        t0 = time.time()
        if s in ("check", "layout", "make", "facefix", "backfix", "restyle", "letter", "review") and conti is None:
            conti = W.load_conti(nk, kit, args.ep)          # write/compile 뒤에 처음 읽음
        if conti is not None and not hasattr(args, "_style_set"):
            args.style, args._style_set = style_of(conti), True
            print("style:", args.style or "(no restyle)")
        if s == "write":
            rc = step_write(nk, kit, W, args, rec)
        elif s == "compile":
            rc = step_compile(nk, kit, W, args, rec)
            if rc == 0 and os.path.exists(os.path.join(W.ep_dir(kit, args.ep), "conti.yaml")):
                conti = W.load_conti(nk, kit, args.ep)      # 새 콘티로 다시 읽음
                if hasattr(args, "_style_set"):
                    del args._style_set
        elif s == "check":
            rc, _ = _call(W.check, nk, kit, _ns(ep=args.ep))
        elif s == "layout":
            rc = step_layout(nk, kit, W, args, conti, rec)
        elif s == "make" and getattr(args, "render", "anima") == "anima":
            rc = step_make_anima(nk, kit, W, args, conti, rec)
        elif s == "make":
            comp = _compose_cuts(W, conti, args) | _layer_cuts(W, conti, args)
            cids = set(int(ct["id"]) for ct in conti["cuts"]
                       if not os.path.exists(W._final_file(kit, args.ep, int(ct["id"]))) and int(ct["id"]) not in comp)
            if comp:
                rec["notes"] = ["two-character cuts %s: made in the compose step%s"
                                % (sorted(comp), " (layer)" if getattr(args, "duo", "") == "layer" else "")]
            rc, _ = _call(W._pipeline, nk, kit, _ns(ep=args.ep, n=args.n, noqa=False, full=False, seed=None, dry=args.dry,
                                                    style=None), cids, conti, True)
        elif s == "compose":
            rc = _guard(rec, step_compose, nk, kit, W, args, conti, rec)
        elif s == "unify":
            rc = _guard(rec, step_unify, nk, kit, W, args, conti, rec)
        elif s == "story":
            try:                                        # 검수 AI·편집이 실패해도 만화는 계속 (그림은 그대로)
                rc = step_story(nk, kit, W, args, conti, rec)
            except (Exception, SystemExit) as e:
                import traceback
                traceback.print_exc()
                rec["notes"] = ["story step error: %s" % e]; rc = 1
        elif s == "propfix":
            import nk_propfix
            rc, _ = _call(nk_propfix.run, nk, kit, _ns(ep=args.ep, cuts=[], seed=None, tries=None, use=None, dry=args.dry))
        elif s == "facefix":
            import nk_facefix
            rc, _ = _call(nk_facefix.run, nk, kit, _ns(ep=args.ep, cuts=[], who=None, denoise=None, seed=None, tries=None,
                                                       force=False, use=None, box=None, sharp=False, dry=args.dry))
        elif s == "handfix":
            import nk_handfix
            rc, _ = _call(nk_handfix.run_fix, nk, kit, _ns(ep=args.ep, cuts=[], seed=None, threshold=0.3, apply=False,
                                                           dry=args.dry))
        elif s == "backfix":
            import nk_backfix
            if not nk_backfix._targets(conti, None):
                rec["notes"] = ["no back-view cut - nothing to do"]; rc = 0
            else:
                rc, _ = _call(nk_backfix.run, nk, kit, _ns(ep=args.ep, cuts=[], seed=None, tries=None, use=None, any=False,
                                                           dry=args.dry))
        elif s == "restyle":
            if not args.style:
                rec["notes"] = ["no style (conti 'restyle:' or --style)"]; rc = 0
            else:
                import nk_restyle
                rc, _ = _call(nk_restyle.run, nk, kit, _ns(ep=args.ep, cuts=[], style=args.style, seed=None, dry=args.dry,
                                                           denoise=None, check=False, tries=None, use=None))
        elif s == "letter":
            rc, _ = _call(W.letter, nk, kit, _ns(ep=args.ep, style=None))
            if args.style and not rc and getattr(args, "render", "anima") != "anima":   # anima: 그림체 입히기 없음 -> 책 한 벌
                rc, _ = _call(W.letter, nk, kit, _ns(ep=args.ep, style=args.style))
        elif s == "review":
            rc = 1 if args.dry else step_review(nk, kit, W, args, conti, rec, state)
        rec["secs"] = int(time.time() - t0)
        rec["rc"] = rc
        # facefix·backfix의 exit 1 = '고칠 컷 없음'일 때가 많음 -> 흠으로 보지 않고 기록만
        rec["status"] = "done" if rc == 0 or s in ("check", "facefix", "handfix", "backfix", "propfix") else "failed"   # compose 실패도 기록만 하고 계속
        if s in ("write", "compile") and rec["status"] != "done":
            state[s] = rec; save()
            print("[ERROR] %s failed - stop" % s); sys.exit(1)
        state[s] = rec
        save()
        print("==== [%s] %s (%ss, rc %s)" % (s, rec["status"], rec["secs"], rc))
        if s == "make" and rec["status"] != "done":
            print("[ERROR] make failed - stop (fix and run again: nk ep auto %s --from make)" % args.ep)
            sys.exit(1)
    print("\nauto %s finished. look at episodes/%s/auto/review.png and review.md" % (args.ep, args.ep))


def add_args(a):
    a.add_argument("ep")
    a.add_argument("--style", help="restyle name (default: conti 'restyle:'; none = skip)")
    a.add_argument("--from", dest="start", choices=STEPS, help="start at this step (runs it again even if done)")
    a.add_argument("--to", dest="stop", choices=STEPS, help="stop after this step")
    a.add_argument("--n", type=int, default=3, help="candidates per cut for make")
    a.add_argument("--layout-seeds", type=int, default=3, help="Anima layout pictures per two-character cut")
    a.add_argument("--fresh", action="store_true", help="forget earlier auto state")
    a.add_argument("--writer", choices=["prompt", "ollama"], default="prompt",
                   help="who writes plan.yaml from request.yaml when there is no plan (prompt = stop and wait for a web AI answer)")
    a.add_argument("--model", help="ollama model for --writer ollama")
    a.add_argument("--render", choices=["noob", "anima"], default="anima",
                   help="anima: 혼자·사람 없는 컷 = Anima 한 번에, LoRA 캐릭터가 나오는 두 명 컷 = "
                        "나눠 그리기(nk ep regionlora --split: LoRA 는 그 캐릭터 자리에만), 그 캐릭터 얼굴만 한 번 더(nk ep animafix 0.6). "
                        "LoRA 없는 두 명 컷도 나눠 그리기(nk_duosplit, duosplit_settings.yaml). "
                        "noob = 예전 NoobAI 흐름")
    a.add_argument("--duo", choices=["compose", "draw", "layer"], default="compose",
                   help="two-character cuts: compose = combine the two characters' solo pictures / draw = old MB way / "
                        "layer = draw each character on the same background and stack cut-outs")
    a.add_argument("--redo-duo", dest="redo_duo", action="store_true",
                   help="compose step also replaces two-character finals that were drawn the old way (originals kept)")
    a.add_argument("--unify", help="repaint composed two-character cuts with NoobAI: 0.4 (default, or conti duo: {unify: ...}) / off")
    a.add_argument("--story", choices=["suggest", "fix", "check", "off"],
                   help="cuts with show: facts - ask the vision QA; suggest = make edit candidates only (default for --render noob), fix = apply, check = ask only. --render anima: off unless set here or in the conti")
    a.add_argument("--dry", action="store_true")
