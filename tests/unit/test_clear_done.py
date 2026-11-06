# -*- coding: utf-8 -*-
"""작업실 「잘 끝난 작업 지우기」.
누른 시각만 적어 두고 그 시각까지 잘 끝난 작업을 목록에서만 숨김 — 대기열·기록 파일은 그대로, 실패·멈춘 작업은 남김. 가짜 키트 폴더"""
import hashlib, json, os, time
import pytest
import nk
import nk_web as W


@pytest.fixture
def app(tmp_path, monkeypatch):
    kit = tmp_path / "kit"; kit.mkdir()
    (kit / "nk_remote.py").write_text("# fake", encoding="utf-8")
    home = tmp_path / "home"; (home / "_nk" / "queue").mkdir(parents=True); (home / "_nk" / "done").mkdir()
    cfg = tmp_path / "workshop.json"; cfg.write_text(json.dumps({"folders": [str(home)]}), encoding="utf-8")
    monkeypatch.setattr(W, "CFG_PATH", str(cfg))
    a = W.App(nk, str(kit))
    a._home = str(home)
    return a


def T(off):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + off))


def put(d, name, obj):
    os.makedirs(d, exist_ok=True)
    json.dump(obj, open(os.path.join(d, name), "w", encoding="utf-8"), ensure_ascii=False)


def snap(*dirs_and_files):
    """대기열 쪽 파일들의 (경로, 내용 md5) — 지우기 전후가 같아야 함"""
    out = []
    for p in dirs_and_files:
        fs = [os.path.join(p, n) for n in sorted(os.listdir(p))] if os.path.isdir(p) else ([p] if os.path.exists(p) else [])
        out += [(f, hashlib.md5(open(f, "rb").read()).hexdigest()) for f in fs if os.path.isfile(f)]
    return out


def test_hid_rule():
    at = "2030-01-01 00:30:00"
    ok = {"rc": 0, "end": "2030-01-01 00:29:59"}
    assert W._hid(ok, at) and W._hid(dict(ok, end=at), at)
    assert not W._hid(ok, "")                                        # 안 눌렀으면 아무것도 안 숨김
    assert not W._hid(dict(ok, end="2030-01-01 00:30:01"), at)       # 누른 뒤에 끝난 작업은 보임
    assert not W._hid(dict(ok, rc=1), at)                            # 실패한 작업은 남김
    assert not W._hid(dict(ok, rc=1, killed=True), at)               # 멈춘 작업도 남김
    assert not W._hid({"rc": 0}, at)                                 # 끝 시각이 없는 기록은 건드리지 않음


def test_clear_and_undo_keeps_queue(app):
    jid = lambda off, tag: time.strftime("a%y%m%d_%H%M%S", time.localtime(time.time() + off)) + "000_" + tag
    wait, front_job = jid(-60, "auto_w") + ".json", jid(-50, "fix_w2") + ".json"
    put(app.inbox, wait, {"args": ["ep", "auto", "w"], "note": "n"})
    put(app.inbox, front_job, {"args": ["ep", "fix", "w2", "3"], "note": "n"})
    put(os.path.join(app.box, "paused"), jid(-55, "auto_p") + ".json", {"args": ["ep", "auto", "p"], "note": "n"})
    pq = os.path.join(app._home, "_nk", "queue")
    put(pq, jid(-40, "fix_pv") + ".json", {"args": ["ep", "fix", "pv", "2"], "note": "n"})
    app.front_save([{"name": front_job, "root": "0"}])
    # 끝난 작업: 키트 성공 1·실패 1, 개인 성공 1 (모두 '이번 묶음' 안 = 가장 먼저 넣은 대기 작업 뒤에 시작)
    put(app.done, "k_ok.result.json", {"id": "k_ok", "args": ["ep", "fix", "a", "1"], "rc": 0, "start": T(-30), "end": T(-20), "secs": 10})
    put(app.done, "k_bad.result.json", {"id": "k_bad", "args": ["ep", "fix", "a", "2"], "rc": 1, "error": "x", "start": T(-30), "end": T(-19), "secs": 11})
    put(os.path.join(app._home, "_nk", "done"), "p_ok.result.json",
        {"id": "p_ok", "args": ["ep", "fix", "pv", "1"], "rc": 0, "start": T(-30), "end": T(-18), "secs": 12})
    watch = (app.inbox, os.path.join(app.box, "paused"), app.front_path, pq, app.done, os.path.join(app._home, "_nk", "done"))
    before = snap(*watch)

    def view():
        q = app.ordered_queue()
        return q, app.plan_view({"alive": False}, {"job": None}, q)

    q0, p0 = view()
    assert app.cleared_at() == "" and len(p0["done"]) == 3 and not any(x["hid"] for x in p0["done"])
    at = app.clear_done()
    q1, p1 = view()
    assert app.cleared_at() == at and os.path.exists(app.cleared_path)
    assert {x["job"]: x["hid"] for x in p1["done"]} == {"k_ok": True, "k_bad": False, "p_ok": True}      # 잘 끝난 것만 숨김
    assert p1["batch_frac"] == p0["batch_frac"] and p1["total_remain_s"] == p0["total_remain_s"]        # 진행 %·남은 시간은 그대로
    assert [(x["name"], x.get("paused"), x.get("front")) for x in q1] == [(x["name"], x.get("paused"), x.get("front")) for x in q0]
    assert snap(*watch) == before                                    # 대기열·앞줄·멈춘 작업·끝난 기록 파일 모두 그대로
    # 누른 뒤에 끝난 작업은 다시 보임
    put(app.done, "k_new.result.json", {"id": "k_new", "args": ["ep", "fix", "a", "3"], "rc": 0, "start": T(1), "end": T(2), "secs": 1})
    assert {x["job"]: x["hid"] for x in view()[1]["done"]}["k_new"] is False
    # 보기 전용 화면: 개인 항목은 이름 없이, 숨김 표시는 유지
    m = W.mask_private({"queue": q1, "recent": [], "private": {"job": None}, "plan": p1})
    pv = [x for x in m["plan"]["done"] if x.get("private")]
    assert len(pv) == 1 and pv[0]["hid"] is True and "p_ok" not in json.dumps(m, ensure_ascii=False)
    # 다시 보기
    assert app.clear_done(undo=True) == "" and app.cleared_at() == "" and not os.path.exists(app.cleared_path)
    assert not any(x["hid"] for x in view()[1]["done"])
    app.clear_done(undo=True)                                        # 두 번 눌러도 오류 없음
    os.remove(os.path.join(app.done, "k_new.result.json"))
    assert snap(*watch) == before


def test_broken_cleared_file_is_ignored(app):
    open(app.cleared_path, "w", encoding="utf-8").write("{not json")
    assert app.cleared_at() == ""                                    # 깨진 파일이면 '안 누름'으로 (목록이 다 보임)
    assert app.clear_done() and app.cleared_at()
