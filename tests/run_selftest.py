# -*- coding: utf-8 -*-
"""selftest 실행기 — GPU 없이 `nk ep auto` 전체가 끝까지 도는지 확인

하는 일:
  1. 임시 폴더를 만들고 시험 편(tests/fixtures/selftest01)을 복사 (NK_HOME = 임시 폴더 -> 키트 폴더에는 아무것도 안 씀)
  2. 가짜 ComfyUI(tests/mock_comfy.py)·가짜 Ollama(tests/mock_ollama.py)를 빈 포트에 띄움
  3. python tests/nk_mocked.py ep auto selftest01 --fresh  (태그 판별기·뼈대 찾기도 가짜, tests/fakes.py)
  4. 단계마다 기록(auto/state.json)과 결과 파일이 생겼는지 보고 표로 출력
     (말풍선 단계의 표지도 봄: page_00.png · cover/cover.png, 끝까지 가는 경우는 가짜 ComfyUI 로 그린 cover/art.png 까지)

사용:
  python tests/run_selftest.py                 여섯 경우 다 (기본, 1~2분): pass fail garbage error qwenfail unifyfail
  python tests/run_selftest.py --mode pass     검수 AI·판별기가 '다 좋음' 이라고 답하는 경우만
  python tests/run_selftest.py --mode fail     '다 틀림' 이라고 답하는 경우만 (고치기 경로)
  python tests/run_selftest.py --mode both     pass + fail
  python tests/run_selftest.py --mode duo      LoRA 없는 두 명 컷 나눠 그리기 (nk_duosplit) / duonoimpact = Impact Pack 없는 ComfyUI
  python tests/run_selftest.py --keep          임시 폴더를 지우지 않음 (그림·로그 보기)
끝 코드: 0 = 모두 통과, 1 = 하나라도 실패"""
import os, sys, json, time, shutil, socket, argparse, subprocess, tempfile, hashlib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
EP = "selftest01"

STEPS = ["write", "compile", "check", "layout", "make", "propfix", "facefix", "compose", "unify", "story", "handfix", "backfix",
         "restyle", "letter", "review"]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _exists(d, *parts):
    return os.path.exists(os.path.join(d, *parts))


def _glob(d, sub, ext=".png"):
    p = os.path.join(d, sub)
    return sorted(f for f in os.listdir(p) if f.endswith(ext)) if os.path.isdir(p) else []


def file_checks(ep_dir, mode, duo="compose", need_art=False):
    """단계 -> (통과?, 설명). 파일로만 판단 (단계 기록은 따로 봄)"""
    cuts = _glob(ep_dir, "cuts")
    out = {}
    out["write"] = (_exists(ep_dir, "plan.yaml"), "plan.yaml")
    out["compile"] = (_exists(ep_dir, "conti.yaml"), "conti.yaml")
    out["check"] = (True, "(기록만)")
    out["layout"] = (True, "(합치기 방식이면 할 일 없음)")
    solo = ["cut01.png", "cut02.png", "cut03.png"]
    out["make"] = (all(c in cuts for c in solo) and _exists(ep_dir, "auto.json"), "cuts/cut01~03.png + auto.json (있음: %s)" % ",".join(cuts))
    out["propfix"] = (_exists(ep_dir, "cuts_propfix", "propfix.json") or mode == "pass",
                      "cuts_propfix/propfix.json" + (" (판별기 pass 면 소품이 보여서 할 일 없음)" if mode == "pass" else ""))
    out["facefix"] = (_exists(ep_dir, "cuts_facefix", "facefix.json") or _exists(ep_dir, "cuts_facefix", "facecheck.json"),
                      "cuts_facefix/facefix.json 또는 facecheck.json")
    out["compose"] = ("cut04.png" in cuts and _exists(ep_dir, "cuts_compose", "compose.json"), "cuts/cut04.png + cuts_compose/compose.json")
    out["unify"] = (_exists(ep_dir, "cuts_unify", "unify.json"), "cuts_unify/unify.json")
    if duo == "layer":
        out["layout"] = (_exists(ep_dir, "poses", "cut04.png") and _exists(ep_dir, "poses", "cut04_kp.json"), "poses/cut04.png + cut04_kp.json")
        comp8 = _glob(ep_dir, os.path.join("cuts_layer", "cut04", "comp"))
        out["compose"] = ("cut04.png" in cuts and _exists(ep_dir, "cuts_layer", "layer.json") and len(comp8) == 8,
                          "cuts/cut04.png + cuts_layer/layer.json + 후보 8장 (있음 %d)" % len(comp8))
        out["unify"] = (True, "(누끼 레이어는 다시 칠하기 없음)")
    if duo == "anima":
        # 모든 컷(두 명 컷 4 포함)을 animamake 가 그림 + animamake.json. NoobAI 단계는 건너뜀(단계 기록 done)
        out["make"] = (all(c in cuts for c in ("cut01.png", "cut02.png", "cut03.png", "cut04.png")) and _exists(ep_dir, "animamake.json"),
                       "cuts/cut01~04.png + animamake.json (있음: %s)" % ",".join(cuts))
    out["story"] = (_exists(ep_dir, "story", "storyfix.json"), "story/storyfix.json")
    out["handfix"] = (_exists(ep_dir, "cuts_handfix", "handfix.json"), "cuts_handfix/handfix.json")
    out["backfix"] = (True, "(시험 편에 뒷모습 컷 없음)")
    rs = _glob(ep_dir, "cuts_picturebook")
    out["restyle"] = (len([f for f in rs if f.startswith("cut")]) >= 4, "cuts_picturebook/cut01~04.png (있음 %d)" % len(rs))
    outs = [d for d in os.listdir(ep_dir) if d.startswith("out") and os.path.isdir(os.path.join(ep_dir, d))] if os.path.isdir(ep_dir) else []
    pdf = [d for d in outs if _exists(ep_dir, d, "book.pdf")]
    out["letter"] = (len(pdf) >= 2, "out*/book.pdf 두 벌 (기본·그림체) (있음: %s)" % ",".join(pdf))
    out["review"] = (_exists(ep_dir, "auto", "review.png") and _exists(ep_dir, "auto", "review.md"), "auto/review.png + review.md")
    if duo == "anima":            # NoobAI 단계는 건너뜀(단계 기록 done), 그림체 입히기가 없으니 책은 한 벌
        for k in ("layout", "propfix", "facefix", "compose", "unify", "handfix", "backfix", "restyle"):
            out[k] = (True, "(--render anima: 건너뜀)")
        out["letter"] = (pdf == ["out"], "out/book.pdf 한 벌 (있음: %s)" % ",".join(pdf))
        out["story"] = (not _exists(ep_dir, "story", "storyfix.json"), "(--render anima: 이야기 검사 꺼짐 — storyfix.json 없어야 함)")
    # 표지 (nk_cover.py): 책마다 page_00.png + 표지만 따로 cover/cover.png. need_art = 가짜 ComfyUI 로 표지 그림까지 그려졌는지
    ok_l, d_l = out["letter"]
    cov = all(_exists(ep_dir, d, "page_00.png") for d in pdf) and _exists(ep_dir, "cover", "cover.png")
    art = _exists(ep_dir, "cover", "art.png")
    out["letter"] = (ok_l and cov and (art or not need_art),
                     d_l + " + 표지 page_00.png·cover/cover.png %s, 그림 cover/art.png %s" % ("있음" if cov else "없음", "있음" if art else "없음"))
    return out


def _other_job(k):
    """같은 시간에 도는 다른 작업(우체통 GPU 작업)이 쓴 파일: runs/<키트에 있는 다른 편>/... 또는 runs/regtest/..."""
    p = k.split("/")
    return len(p) > 2 and p[0] == "runs" and (p[1] == "regtest" or (p[1] != EP and os.path.isdir(os.path.join(KIT, "episodes", p[1]))))


def _ours(k):
    """이 시험이 만든 것이 확실한 경로만 지움"""
    return EP in k or k.startswith("runs/_judge")


def kit_snapshot():
    """키트 폴더에 시험 흔적이 남지 않았나 보려고: episodes/selftest01 + runs/ 아래 모든 파일 (NK_HOME 이면 둘 다 안 생겨야 함)"""
    snap = {"episodes/" + EP: os.path.exists(os.path.join(KIT, "episodes", EP))}
    for root, _, files in os.walk(os.path.join(KIT, "runs")):
        for f in files:
            snap[os.path.relpath(os.path.join(root, f), KIT).replace(os.sep, "/")] = True
    return snap


# 모드: (가짜 검수 AI 답, 가짜 판별기, 가짜 ComfyUI 가 실패시킬 노드, 기대)
#   기대 all  = 모든 단계 done + 결과 파일
#   기대 stop = make 에서 멈춤 (끝 코드 1, 로그에 이유) - 검수 AI 가 죽었을 때 몇 시간 헛돌지 않는지
#   기대 continue = 실패한 단계는 기록만 하고 끝까지 감 (review 까지) - 코드 오류(rc 99)는 없어야 함
MODES = {
    "pass": ("pass", "pass", "", "all"),
    "fail": ("fail", "fail", "", "all"),
    "garbage": ("garbage", "pass", "", "all"),
    "error": ("error", "pass", "", "stop"),
    "qwenfail": ("fail", "fail", "TextEncodeQwenImageEditPlus", "continue"),
    "unifyfail": ("pass", "pass", "ETN_AttentionMask", "continue"),
    "layer": ("pass", "pass", "", "all"),
    "layerw": ("pass", "pass", "", "all"),
    "anima": ("pass", "pass", "", "all"),
    "duo": ("pass", "pass", "", "all"),
    "duonoimpact": ("pass", "pass", "", "all"),
}
MODE_ARGS = {"layer": ["--duo", "layer", "--render", "noob"], "layerw": ["--duo", "layer", "--render", "noob"], "anima": ["--render", "anima"],
             "duo": ["--render", "anima"], "duonoimpact": ["--render", "anima"]}
_DUO4 = '        shot: %s\n        angle: eye\n        loc: park\n        action: "looking at another"'
_NOLORA = ("cast: {hero: testcat, buddy: testgoat}", "cast: {hero: testknight, buddy: testgoat}")    # 두 사람 다 LoRA 없음
PLAN_PATCH = {"layerw": (_DUO4 % "full", _DUO4 % "waist"), "duo": _NOLORA, "duonoimpact": _NOLORA}
# 가짜 ComfyUI 에서 없는 척할 노드 (Impact Pack 이 없는 ComfyUI -> 두 명 컷은 예전처럼 한 번에)
MODE_HIDE = {"duonoimpact": ("RegionalSampler", "CombineRegionalPrompts", "RegionalPrompt", "KSamplerAdvancedProvider", "ToBasicPipe")}


def duo_checks(ep_dir, mode, log):
    """duo·duonoimpact: 두 명 컷 4 를 어느 길로 그렸나 -> (통과?, 설명)"""
    def js(name):
        p = os.path.join(ep_dir, name)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    ds, am, rl = js("duosplit.json"), js("animamake.json"), js("regionlora.json")
    if mode == "duo":
        r = ds.get("4") or {}
        ok = bool(r.get("split_ok")) and "4" not in am and _exists(ep_dir, "cuts_base", "cut04.png") and \
            bool((rl.get("cut04") or {}).get("spans")) and (rl.get("cut04") or {}).get("duosplit") is True
        return ok, "duosplit.json 4 split_ok=%s, cuts_base/cut04.png, regionlora.json cut04 spans=%s" % (r.get("split_ok"), (rl.get("cut04") or {}).get("spans"))
    warned = "[WARN] ComfyUI 에 나눠 그리기 노드(RegionalSampler" in log
    ok = "4" in am and not ds and warned
    return ok, "Impact Pack 없음 -> animamake.json 에 4 (%s), duosplit.json 없음 (%s), 경고 줄 (%s)" % ("4" in am, not ds, warned)


def run_once(mode, keep, timeout, verbose):
    import mock_comfy, mock_ollama
    om, tm, fail_class, expect = MODES[mode]
    home = tempfile.mkdtemp(prefix="nk_selftest_%s_" % mode)
    ep_dir = os.path.join(home, "episodes", EP)
    shutil.copytree(os.path.join(HERE, "fixtures", EP), ep_dir)
    if mode in PLAN_PATCH:
        pp = os.path.join(ep_dir, "plan.yaml")
        txt = open(pp, encoding="utf-8").read()
        assert txt.count(PLAN_PATCH[mode][0]) == 1, "fixture changed - fix PLAN_PATCH"
        open(pp, "w", encoding="utf-8").write(txt.replace(*PLAN_PATCH[mode]))
    dw = os.path.join(home, "fake_dwpose.onnx")
    open(dw, "wb").close()
    cp, op = free_port(), free_port()
    csrv, cstate = mock_comfy.serve(cp, os.path.join(home, "_comfy"), fail_class, hide=MODE_HIDE.get(mode, ()))
    osrv, ostate = mock_ollama.serve(op, om)
    env = dict(os.environ)
    env.setdefault("NK_CHARS", os.path.join(KIT, "tests", "fixtures", "characters"))
    env.setdefault("NK_AGREE", "1")
    env.update({"NK_HOME": home, "NK_COMFY_SERVER": "http://127.0.0.1:%d" % cp, "NK_OLLAMA": "http://127.0.0.1:%d" % op,
                "NK_COMFY_WAIT": "5", "NK_MOCK_MODE": tm, "NK_MOCK_DW": dw, "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1"})
    before = kit_snapshot()
    log_p = os.path.join(home, "selftest_%s.log" % mode)
    cmd = [sys.executable, os.path.join(HERE, "nk_mocked.py"), "ep", "auto", EP, "--fresh"] + MODE_ARGS.get(mode, ["--render", "noob"])
    print("\n=== selftest [%s]  검수 AI %s / 판별기 %s / ComfyUI 실패 노드 %s / 기대 %s" % (mode, om, tm, fail_class or "-", expect))
    print("    NK_HOME=%s  ComfyUI(가짜) :%d  Ollama(가짜) :%d" % (home, cp, op))
    t0 = time.time()
    timed_out = False
    with open(log_p, "w", encoding="utf-8") as lf:
        try:
            p = subprocess.run(cmd, cwd=KIT, env=env, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc, timed_out = -1, True
    secs = time.time() - t0
    log = open(log_p, encoding="utf-8", errors="replace").read()
    csrv.shutdown(); osrv.shutdown()

    sp = os.path.join(ep_dir, "auto", "state.json")
    state = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    fc = file_checks(ep_dir, tm, "layer" if mode in ("layer", "layerw") else ("anima" if mode in ("anima", "duo", "duonoimpact") else "compose"),
                     need_art=(expect == "all"))
    if mode in ("duo", "duonoimpact"):
        ok_m, d_m = fc["make"]
        ok_d, d_d = duo_checks(ep_dir, mode, log)
        fc["make"] = (ok_m and ok_d, d_m + " + " + d_d)
    if mode == "layerw":
        kpf = os.path.join(ep_dir, "poses", "cut04_kp.json")
        fr = (json.load(open(kpf, encoding="utf-8")).get("framed") or {}) if os.path.exists(kpf) else {}
        ok_l, d_l = fc.get("layout", (True, ""))
        fc["layout"] = (ok_l and fr.get("shot") == "waist" and "waist shot -> pose zoom" in open(log_p, encoding="utf-8", errors="replace").read(),
                        d_l + " + 허리 위 확대 기록 framed=%s" % fr)
    rows = []
    if expect == "all":
        ok_all = rc == 0 and not timed_out
    elif expect == "stop":
        ok_all = rc == 1 and not timed_out and "[ERROR] make failed - stop" in log
    else:
        ok_all = rc == 0 and not timed_out
    mi = STEPS.index("make")
    for i, s in enumerate(STEPS):
        r = state.get(s) or {}
        st = r.get("status", "-")
        rcs = r.get("rc", "-")
        fok, fdesc = fc.get(s, (True, ""))
        if expect == "all":
            # 통과 = 단계 기록 done + 코드 오류(rc 99) 아님 + 결과 파일 있음
            good = st == "done" and rcs != 99 and fok
        elif expect == "stop":
            good = (st == "done" and rcs != 99) if i < mi else (st == "failed" if i == mi else st == "-")
            fdesc = "(멈춤 기대: make 실패, 뒤 단계 없음)" if i >= mi else fdesc
            fok = True
        else:
            good = st in ("done", "failed") and rcs != 99 and (fok if s in ("make", "review", "compile") else True)
        ok_all = ok_all and good
        note = "; ".join(str(x) for x in (r.get("notes") or [])[:1])[:70]
        rows.append((s, "OK" if good else "FAIL", st, rcs, r.get("secs", "-"), ("" if fok else "없음: ") + fdesc, note))
    after = kit_snapshot()
    new = sorted(k for k in after if after[k] and not before.get(k))
    other = [k for k in new if _other_job(k)]
    leak = [k for k in new if not _other_job(k)]
    if other:
        print("[참고] 같은 시간에 다른 작업이 쓴 파일 %d개는 셈에서 뺌 (지우지 않음): %s" % (len(other), ", ".join(other[:3])))
    tb = log.count("Traceback (most recent call last)")
    jobs = sum(1 for x in cstate.log if x[1] == "prompt")
    fails = sum(1 for x in cstate.log if x[1] == "prompt" and str(x[2]).startswith("FAIL"))
    chats = sum(1 for x in ostate.log if x[1] == "chat")

    print("\n| 단계 | 판정 | 기록 | rc | 초 | 결과 파일 | 메모 |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print("| %s |" % " | ".join(str(x) for x in r))
    print("\n끝 코드 %s%s, %.0f초 / 가짜 ComfyUI 작업 %d개 (오류 %d) / 가짜 검수 AI 질문 %d개 / 로그 속 Traceback %d개"
          % (rc, " (시간 초과)" if timed_out else "", secs, jobs, fails, chats, tb))
    if leak:
        print("[FAIL] 키트 폴더에 시험 흔적이 생김 (NK_HOME 인데 키트에 씀) %d개: %s" % (len(leak), ", ".join(leak[:4])))
        print("       -> 이번 시험이 만든 것이 확실한 파일(시험 편 이름·runs/_judge)만 지움")
        ok_all = False
        for k in leak:
            if not _ours(k):
                print("       (안 지움, 확인 필요: %s)" % k)
                continue
            p = os.path.join(KIT, *k.split("/"))
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        for d in (os.path.join(KIT, "runs", "_judge"), os.path.join(KIT, "runs")):   # 시험 때문에 새로 생긴 빈 폴더
            if os.path.isdir(d) and not os.listdir(d) and not any(x.startswith(os.path.relpath(d, KIT).replace(os.sep, "/"))
                                                                   for x in before):
                os.rmdir(d)
    if tb:
        print("[주의] 로그에 Traceback 이 있음 (단계가 코드 오류로 끝남) -> %s" % log_p)
        if verbose:
            i = log.find("Traceback (most recent call last)")
            print(log[i:i + 3000])
    print("로그: %s" % log_p)
    print("결과: %s" % ("통과" if ok_all else "실패"))
    if not keep and ok_all:
        shutil.rmtree(home, ignore_errors=True)
    elif not keep:
        print("(실패해서 임시 폴더를 남김: %s)" % home)
    why = []                                     # 알려진 원인
    if leak and all(k.startswith("runs/_judge/") for k in leak):
        why.append("문제1 nk_compose.py:364 가 키트 runs/_judge 에 씀")
    elif leak:
        why.append("키트에 샌 파일 (새 문제?)")
    if expect == "continue" and "job failed" in log and "[ERROR] make failed" not in log:
        last = [s for s in STEPS if s in state][-1:] or ["?"]
        nxt = STEPS[STEPS.index(last[0]) + 1] if last[0] in STEPS and last[0] != STEPS[-1] else "?"
        if nxt in ("compose", "unify") and rc == 1:
            why.append("문제2 nk_auto.py %s 단계 ComfyUI 실패가 nk ep auto 전체를 멈춤" % nxt)
    if not ok_all and not why:
        why.append("새 문제 - 로그를 볼 것")
    return ok_all, rows, {"why": "; ".join(why), "leak": len(leak), "rc": rc, "secs": round(secs), "jobs": jobs, "chats": chats, "tracebacks": tb, "home": home}


def main():
    a = argparse.ArgumentParser(description="nk ep auto selftest (가짜 ComfyUI·Ollama)")
    a.add_argument("--mode", choices=list(MODES) + ["both", "all"], default="all",
                   help="all = 다섯 가지 다 (기본) / both = pass+fail / pass / fail / garbage = 검수 AI 가 JSON 아닌 말 / "
                        "error = 검수 AI HTTP 500 / qwenfail = ComfyUI 편집(Qwen) 작업이 실패 / unifyfail = 다시 칠하기 작업이 실패")
    a.add_argument("--keep", action="store_true", help="임시 폴더를 남김")
    a.add_argument("--timeout", type=int, default=600, help="한 번 도는 최대 초")
    a.add_argument("-v", "--verbose", action="store_true", help="Traceback 내용도 출력")
    o = a.parse_args()
    modes = {"both": ["pass", "fail"], "all": list(MODES)}.get(o.mode, [o.mode])
    t0 = time.time()
    res = [(m,) + run_once(m, o.keep, o.timeout, o.verbose) for m in modes]
    print("\n==== 요약 (%.0f초)" % (time.time() - t0))
    for m, ok, _, info in res:
        print("  %-9s %s  (%s초, 그리기 %d, 질문 %d, Traceback %d, 키트에 샌 파일 %d)%s" % (
            m, "통과" if ok else "실패", info["secs"], info["jobs"], info["chats"], info["tracebacks"], info["leak"],
            ("  <- " + info["why"]) if info["why"] else ""))
    sys.exit(0 if all(r[1] for r in res) else 1)


if __name__ == "__main__":
    main()
