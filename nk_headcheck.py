# -*- coding: utf-8 -*-
"""머리 수 검사
예전 NoobAI 흐름의 머리 수 검사
(nk_compose.head_counts: SAM3 'head:4', 겹친 조각 합침, 면적 0.4% 미만 버림)를 다 그린 컷에 그대로 씀.

사용: nk ep headcheck <ep> [컷 ...] [--dry]
  기대 머리 수 = 그 컷 사람 수 (두 명 컷 2, 혼자 컷 1, 풍경·소품 0) + 머리 비슷한 소품(눈사람·인형 …) 하나당 2 (nk_compose.head_allowed)
  결과: episodes/<ep>/headcheck.json {cutNN: {found, expected, areas, flag}} — 지금은 '제안만'"""
import os, sys, json


def expected_heads(cut):
    """-> (기대 머리 수, 머리 비슷한 소품 수)"""
    import nk_compose as C
    if cut.get("_roles"):
        return C.head_allowed(None, cut)
    n_people = 0 if cut.get("_char") is None else 1
    allowed, n_like = C.head_allowed(None, dict(cut, _roles=[]))
    return allowed + n_people, n_like


#   헛걸림 9 = 사람 없는 컷의 나무·축구공·빵 4 + 귀·술 장식 같은 작은 조각 5 (가장 큰 머리의 0.11~0.34). 진짜 두 머리 = 0.67~0.98
#   -> 가장 큰 머리의 REL 배 이상만 머리로 셈 + 사람 없는 컷은 안 봄 = 잡음 1/1·헛걸림 0/31.
REL = 0.5


def count_heads(areas, rel=REL):
    """면적 목록 -> 가장 큰 머리의 rel 배 이상인 것만 셈"""
    if not areas:
        return 0
    top = max(areas)
    return sum(1 for a in areas if a >= top * rel)


def flag_of(found, expected):
    if found is None:
        return "SAM 실패"
    if expected == 0:
        return None                        # 사람 없는 컷 (나무·공·빵을 머리로 셈) — 안 봄
    if found > expected:
        return "머리 많음 %d > %d" % (found, expected)
    if expected and found == 0:
        return "머리 없음 (0 / %d)" % expected
    return None


def run(nk, kit, args):
    import nk_webtoon as W, nk_compose as C
    cfg = nk.load_presets()
    conti = W.load_conti(nk, kit, args.ep)
    ed = W.ep_dir(kit, args.ep)
    ids = [int(x) for x in args.cuts]
    cuts = [c for c in conti["cuts"] if not ids or int(c["id"]) in ids]
    todo = []
    for c in cuts:
        p = os.path.join(ed, "cuts", "cut%02d.png" % int(c["id"]))
        if os.path.exists(p):
            todo.append((c, p))
    print("headcheck %s: %d cuts" % (args.ep, len(todo)))
    if args.dry:
        for c, p in todo:
            print("  cut%02d expected %d" % (int(c["id"]), expected_heads(c)[0]))
        return
    #   그림이 그대로인 컷은 지난 결과를 다시 씀. 그림이 바뀐 컷(새로 그렸거나 고친 컷)만 SAM3 로 다시 잼
    hp = os.path.join(ed, "headcheck.json")
    try:
        old = json.load(open(hp, encoding="utf-8"))
    except Exception:
        old = {}
    sig_of = lambda p: [int(os.path.getmtime(p)), os.path.getsize(p)]
    old_t = os.path.getmtime(hp) if os.path.exists(hp) else 0

    def same(c, p):
        e = old.get("cut%02d" % int(c["id"])) or {}
        if e.get("found") is None:
            return False
        if "sig" in e:
            return e["sig"] == sig_of(p)
        return os.path.getmtime(p) <= old_t          # 표시(sig)가 없던 옛 기록: 그 기록을 쓴 뒤로 그림이 안 바뀌었으면 그대로
    need = [(c, p) for c, p in todo if not same(c, p)]
    if len(need) < len(todo):
        print("  %d cuts unchanged -> reuse the last count, check %d" % (len(todo) - len(need), len(need)))
    got = C.head_counts(nk, kit, cfg, args.ep, [p for _, p in need], run="headcheck") if need else {}
    fresh = {p for _, p in need}
    out = dict((k, v) for k, v in old.items() if ids and k not in {"cut%02d" % int(c["id"]) for c, _ in todo})   # 컷을 골라 돌릴 땐 나머지 기록을 지킴
    for c, p in todo:
        key = "cut%02d" % int(c["id"])
        if p in fresh:
            n, areas = got.get(p, (None, []))
            n = None if n is None else count_heads(areas)
        else:
            areas = old[key].get("areas") or []
            n = count_heads(areas)
        exp = expected_heads(c)[0]
        f = flag_of(n, exp)
        out[key] = {"found": n, "expected": exp, "areas": areas, "flag": f, "sig": sig_of(p)}
        print("  %s heads %s / expected %d %s%s" % (key, n, exp, ("<- " + f) if f else "", "" if p in fresh else " (same picture)"))
    json.dump(out, open(hp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("flagged %d / %d -> %s" % (sum(1 for v in out.values() if v["flag"]), len(out), os.path.join(ed, "headcheck.json")))


def add_parser(esub, nk, kit):
    a = esub.add_parser("headcheck", help="count heads (SAM3) in finished cuts vs people in the conti - suggest only")
    a.add_argument("ep"); a.add_argument("cuts", nargs="*")
    a.add_argument("--dry", action="store_true")
    a.set_defaults(func=lambda x: run(nk, kit, x))
