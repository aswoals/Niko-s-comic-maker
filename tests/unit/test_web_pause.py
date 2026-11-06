# -*- coding: utf-8 -*-
"""작업실 '⏸ 전부 잠깐 멈춤 / ▶ 다시 시작': 작업실이 돌리는 작업의 파이썬 프로세스만 얼리고 풂, 멈춘 상태는 껐다 켜도 남음
— 가짜 키트 폴더, 그래픽카드 비우기(ComfyUI·Ollama 호출)는 시험에서 끔"""
import json, os, shutil, subprocess, sys, time, types
import pytest
import nk
import nk_web as W


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


@pytest.fixture
def app(tmp_path, monkeypatch):
    kit = tmp_path / "kit"; kit.mkdir()
    cfg = tmp_path / "workshop.json"; cfg.write_text(json.dumps({"folders": []}), encoding="utf-8")
    monkeypatch.setattr(W, "CFG_PATH", str(cfg))
    monkeypatch.setattr(W.Pauser, "_free_gpu", lambda self, since: None)      # 네트워크 없음
    monkeypatch.setattr(W.Pauser, "_start_keep", lambda self: None)           # 2초마다 도는 일꾼 없이
    return W.App(nk, str(kit))


def test_job_tree_only_python_children(monkeypatch):
    procs = {10: (1, "python.exe"), 11: (10, "conhost.exe"), 12: (10, "python.exe"), 13: (12, "python3"),
             14: (99, "python.exe"), 15: (11, "python.exe")}
    monkeypatch.setattr(W, "_procs", lambda: procs)
    got = sorted(p for p, _ in W._job_tree(10))
    assert got == [10, 12, 13, 15]                       # 다른 프로그램(conhost)은 안 얼림, 그 아래 파이썬은 얼림, 남의 것(14)은 안 건드림


def test_pause_resume_freezes_only_job_tree(app, monkeypatch):
    calls = []
    monkeypatch.setattr(W, "_job_tree", lambda pid: [(pid, "python.exe"), (pid + 1, "python.exe")])
    monkeypatch.setattr(W, "_suspend", lambda pid, on: calls.append((pid, on)) or True)
    t0 = time.time() - 100
    app.worker = types.SimpleNamespace(proc=FakeProc(111), cur="j1", t0=t0)
    msg = app.pauser.pause()
    assert "얼림" in msg and app.pauser.on and set(app.pauser.frozen) == {111, 112}
    assert sorted(calls) == [(111, True), (112, True)] and os.path.exists(app.pauser.path)
    st = app.pauser.state()
    assert st["on"] and st["frozen"] == 2
    assert app.pauser.pause() == "이미 멈춰 있음"
    p2 = W.Pauser(app)                                   # 작업실을 껐다 켜도 멈춘 채
    assert p2.on and set(p2.frozen) == {111, 112}
    monkeypatch.setattr(W, "_procs", lambda: {111: (1, "python.exe"), 112: (111, "notepad.exe")})
    calls.clear()
    app.pauser.since -= 5                                # 5초 멈춰 있었던 셈 (윈도우 time.time() 은 15ms 단위라 바로 풀면 0초로 잴 수 있음)
    assert "다시 시작" in app.pauser.resume()
    assert calls == [(111, False)]                       # 같은 번호를 다른 프로그램이 쓰면 안 건드림
    assert not app.pauser.on and not os.path.exists(app.pauser.path) and app.worker.t0 > t0
    assert app.pauser.resume() == "멈춰 있지 않음" and app.pauser.state() == {"on": False}


def test_pause_cannot_freeze_does_not_crash(app, monkeypatch):
    monkeypatch.setattr(W, "_job_tree", lambda pid: [(pid, "python")])
    monkeypatch.setattr(W, "_suspend", lambda pid, on: False)
    app.worker = types.SimpleNamespace(proc=FakeProc(5), cur="j1", t0=time.time())
    assert "얼리지 못함" in app.pauser.pause() and app.pauser.on and app.pauser.frozen == {}
    app.pauser.resume()
    app.worker = None
    assert "새 작업을 안 시작" in app.pauser.pause()        # 도는 작업이 없으면 새 작업만 막음


@pytest.mark.skipif(os.name == "nt" or not os.path.isdir("/proc") or not shutil.which("ps"), reason="리눅스 SIGSTOP 확인용")
def test_pause_really_stops_python_child_on_linux(app):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        app.worker = types.SimpleNamespace(proc=p, cur="j1", t0=time.time())

        def state():
            return open("/proc/%d/stat" % p.pid).read().rsplit(")", 1)[1].split()[0]
        time.sleep(0.2)
        app.pauser.pause()
        time.sleep(0.2)
        assert p.pid in app.pauser.frozen and state() == "T"        # 멈춤 (stopped)
        app.pauser.resume()
        time.sleep(0.2)
        assert state() != "T"
    finally:
        p.kill(); p.wait()


def test_page_has_pause_button():
    assert "⏸ 전부 잠깐 멈춤" in W.PAGE and "/api/pause" in W.PAGE and "▶ 다시 시작" in W.PAGE
