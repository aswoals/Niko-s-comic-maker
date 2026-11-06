# -*- coding: utf-8 -*-
"""작업실 작업 줄: 취소 = 멈춘 작업, 이어서 시작, 대기열 삭제, 바로 만들기 (앞줄 기록), 개인 항목 가림 — 가짜 키트 폴더"""
import json, os
import pytest
import nk
import nk_web as W


@pytest.fixture
def app(tmp_path, monkeypatch):
    kit = tmp_path / "kit"; kit.mkdir()
    (kit / "nk_remote.py").write_text("# fake", encoding="utf-8")
    home = tmp_path / "home"; (home / "_nk" / "queue").mkdir(parents=True)
    cfg = tmp_path / "workshop.json"; cfg.write_text(json.dumps({"folders": [str(home)]}), encoding="utf-8")
    monkeypatch.setattr(W, "CFG_PATH", str(cfg))
    a = W.App(nk, str(kit))
    a._home = str(home)
    return a


def put(d, name, args, **kw):
    os.makedirs(d, exist_ok=True)
    json.dump(dict({"args": args, "note": "n"}, **kw), open(os.path.join(d, name), "w", encoding="utf-8"))


def names(d):
    return sorted(n for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []


A1, A2 = "a260930_100000001_auto_x.json", "a260930_100000002_auto_y.json"


def test_cancel_pauses_then_resume_and_delete(app):
    pz = os.path.join(app.box, "paused")
    put(app.inbox, A1, ["ep", "auto", "x"]); put(app.inbox, A2, ["ep", "auto", "y"])
    app.cancel(A1, "0")
    assert names(app.inbox) == [A2] and names(pz) == [A1]
    assert [(x["name"], x["paused"]) for x in app.ordered_queue()] == [(A2, False), (A1, True)]        # 멈춘 작업은 맨 끝
    with pytest.raises(ValueError):
        app.delete_job(A2, "0")                                  # 도는 줄의 작업은 '대기열 삭제' 못 함
    new = app.resume_job(A1, "0")
    assert names(pz) == [] and new in names(app.inbox) and new > A2 and new.endswith("_auto_x.json")   # 맨 아래 (새 시각 이름)
    app.cancel(new, "0"); app.delete_job(new, "0")
    assert names(pz) == [] and names(app.inbox) == [A2]


def test_private_cancel_resume(app):
    q, p = os.path.join(app._home, "_nk", "queue"), os.path.join(app._home, "_nk", "paused")
    put(q, "a260930_100000003_paste_p.json", ["ep", "paste", "p", "--file", "f", "--go"])
    app.cancel("a260930_100000003_paste_p.json", "1")
    assert names(q) == [] and names(p) == ["a260930_100000003_paste_p.json"]
    n2 = app.resume_job("a260930_100000003_paste_p.json", "1")
    assert names(q) == [n2]
    out = json.dumps(W.mask_private({"queue": app.ordered_queue(), "recent": [], "private": {"job": None},
                                     "plan": app.plan_view({"alive": False}, {"job": None}, app.ordered_queue())}), ensure_ascii=False)
    assert n2 not in out and "paste_p" not in out               # 보기 전용 화면에는 개인 이름이 없음


def test_run_now_idle_puts_front(app):
    put(app.inbox, A1, ["ep", "auto", "x"]); put(app.inbox, A2, ["ep", "auto", "y"])
    app.run_now(A2, "0")
    assert app.front_load() == [{"name": A2, "root": "0"}]
    assert names(app.inbox) == [A2] and names(app.held) == [A1] and os.path.exists(app.busy_mark)      # 그것만 우체통에
    assert app.ordered_queue()[0]["name"] == A2 and app.ordered_queue()[0]["front"]
    os.remove(os.path.join(app.inbox, A2))                       # 우체통이 가져가면 앞줄에서 빠짐
    assert app.front_clean() == [] and not os.path.exists(app.front_path)


def test_run_now_interrupts_comic_and_queues_resume(app):
    os.makedirs(os.path.join(app.kit, "episodes", "y")); open(os.path.join(app.kit, "episodes", "y", "plan.yaml"), "w").write("title: y\n")
    put(app.done, "a260930_100000002_auto_y.job.json", ["ep", "paste", "y", "--file", "f", "--go"], elapsed_before=100)
    json.dump({"runner": "busy", "job": "a260930_100000002_auto_y", "elapsed_s": 250}, open(os.path.join(app.box, "status.json"), "w"))
    put(app.inbox, A1, ["ep", "auto", "x"])
    app.run_now(A1, "0")
    fr = app.front_load()
    assert fr[0] == {"name": A1, "root": "0"} and fr[1]["name"].endswith("_auto_y.json")
    assert os.path.exists(os.path.join(app.box, "KILL_a260930_100000002_auto_y"))
    rj = json.load(open(os.path.join(app.held, fr[1]["name"]), encoding="utf-8"))
    assert rj["args"] == ["ep", "auto", "y"] and 350 <= rj["elapsed_before"] <= 360 and rj["note"].startswith("(이어서)")
    assert names(app.inbox) == [A1]


def test_not_resumable_job_is_not_killed(app):
    put(app.done, "j8_train.job.json", ["ep", "trainanima", "x.yaml"])
    json.dump({"runner": "busy", "job": "j8_train", "elapsed_s": 10}, open(os.path.join(app.box, "status.json"), "w"))
    put(app.inbox, A1, ["ep", "auto", "x"])
    app.run_now(A1, "0")
    assert not os.path.exists(os.path.join(app.box, "KILL_j8_train")) and app.front_load() == [{"name": A1, "root": "0"}]
    assert app.resume_for("0", {"args": ["ep", "fix", "y", "3"]}, 5)["args"] == ["ep", "auto", "y", "--from", "make"]
    assert app.resume_for("0", {"args": ["ep", "animatest", "t.yaml"]}, 5) is None


def test_kill_current_leaves_paused_resume(app):
    os.makedirs(os.path.join(app.kit, "episodes", "y")); open(os.path.join(app.kit, "episodes", "y", "plan.yaml"), "w").write("title: y\n")
    put(app.done, "a260930_100000002_auto_y.job.json", ["ep", "auto", "y"])
    json.dump({"runner": "busy", "job": "a260930_100000002_auto_y", "elapsed_s": 60}, open(os.path.join(app.box, "status.json"), "w"))
    app.kill_current()
    pz = names(os.path.join(app.box, "paused"))
    assert len(pz) == 1 and pz[0].endswith("_auto_y.json") and os.path.exists(os.path.join(app.box, "KILL_a260930_100000002_auto_y"))


def test_cut_edits_sort_before_comics(app):
    import time
    comic = W._jobname("auto", "x"); time.sleep(0.01)
    fix, cands = W._jobname("fix", "y"), W._jobname("cands", "y")
    assert fix < comic and cands < comic and W.JOB_RE.match(fix)            # 나중에 넣어도 앞에
    put(app.inbox, comic, ["ep", "auto", "x"]); put(app.inbox, fix, ["ep", "fix", "y", "3"])
    assert [q["name"] for q in app.ordered_queue()] == [fix, comic]
    app.cancel(fix, "0")
    assert app.resume_job(fix, "0") > comic                                  # 이어서 시작 = 맨 아래


def test_add_same_folder_twice_keeps_one(app, tmp_path):
    n0 = len(app.folders)
    d = tmp_path / "MyComics"; d.mkdir()
    app.add_folder(str(d))
    app.add_folder(str(d) + os.sep)
    app.add_folder(str(d).upper() if os.name == "nt" else str(d))
    assert len(app.folders) == n0 + 1
    e = tmp_path / "Other"; e.mkdir()
    app.add_folder(str(e))
    assert len(app.folders) == n0 + 2


def test_reload_buttons_show_folder_names():
    """화면: 다시 읽기 버튼 이름에 폴더 이름 (같은 이름이면 번호)"""
    page = W.PAGE
    assert "fname(x)" in page and "dup(fname(x))" in page and "🔒 개인 폴더\":\"키트 폴더\")+\" 다시 읽기" not in page
