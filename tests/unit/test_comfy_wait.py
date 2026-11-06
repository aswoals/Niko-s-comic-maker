# -*- coding: utf-8 -*-
"""ComfyUI 가 작업을 잃어버리거나(재시작·대기열 지움) 시간 제한을 넘기면 영원히 기다리지 않고 ComfyJobError (GPU·네트워크 없이 가짜 시계)"""
import urllib.error

import pytest

import nk


class Clock:
    """time.time / time.sleep 대신: sleep 하면 시계만 앞으로"""
    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(float(s), 0.01)


def fake_comfy(history=None, queue=None, down=False):
    """Comfy.__init__ (ComfyUI 찾기) 없이 _get 만 가짜로. history/queue = 부를 때마다 값을 돌려주는 함수"""
    c = object.__new__(nk.Comfy)
    c.base = "http://mock"
    c.cancelled = []

    def get(path):
        if down:
            raise urllib.error.URLError("connection refused")
        if path.startswith("/history/"):
            return history() if history else {}
        if path == "/queue":
            return queue() if queue else {"queue_running": [], "queue_pending": []}
        raise AssertionError(path)
    c._get = get
    c.cancel = lambda pids: c.cancelled.extend(pids)
    return c


@pytest.fixture
def clock(monkeypatch):
    k = Clock()
    monkeypatch.setattr(nk.time, "time", k.time)
    monkeypatch.setattr(nk.time, "sleep", k.sleep)
    monkeypatch.delenv("NK_COMFY_JOB_TIMEOUT", raising=False)
    return k


def test_lost_job_raises(clock):
    """대기열에도 기록에도 없음 -> 몇 번 확인한 뒤 ComfyJobError (예전엔 끝없이 기다림)"""
    c = fake_comfy()
    with pytest.raises(nk.ComfyJobError, match="잃어버렸"):
        c.wait("p1", "cut01")
    assert clock.t - 1000.0 < 60                  # 몇십 초 안에 멈춤


def test_comfy_down_raises(clock):
    """ComfyUI 가 꺼짐(연결 거부) -> traceback 대신 ComfyJobError"""
    with pytest.raises(nk.ComfyJobError, match="대답하지"):
        fake_comfy(down=True).wait("p1", "cut01")


def test_waiting_in_queue_then_done(clock):
    """대기열에 줄 서 있는 동안은 기다리고, 기록에 생기면 결과를 돌려줌"""
    start = clock.t
    hist = lambda: {"p1": {"status": {"status_str": "success"}, "outputs": {"10": {"images": [1]}}}} if clock.t - start > 40 else {}
    q = lambda: {"queue_running": [[0, "other", {}, {}, []]], "queue_pending": [[1, "p1", {}, {}, []]]}
    assert fake_comfy(hist, q).wait("p1", "cut01") == {"10": {"images": [1]}}


def test_timeout_removes_job(clock):
    """시간 제한을 넘기면 그 작업을 ComfyUI 대기열에서 빼고 ComfyJobError"""
    q = lambda: {"queue_running": [[0, "p1", {}, {}, []]], "queue_pending": []}
    c = fake_comfy(queue=q)
    with pytest.raises(nk.ComfyJobError, match="20초"):
        c.wait("p1", "cut01", timeout=20)
    assert c.cancelled == ["p1"]


def test_env_timeout(clock, monkeypatch):
    monkeypatch.setenv("NK_COMFY_JOB_TIMEOUT", "15")
    assert nk.job_timeout() == 15
    monkeypatch.setenv("NK_COMFY_JOB_TIMEOUT", "abc")
    assert nk.job_timeout() is None               # 잘못된 값 = 제한 없음


def test_unknown_queue_shape_is_not_lost(clock):
    """대기열 모양을 모르면 잃어버렸다고 판단하지 않음 (기록에 생길 때까지 기다림)"""
    start = clock.t
    hist = lambda: {"p1": {"status": {}, "outputs": {}}} if clock.t - start > 60 else {}
    assert fake_comfy(hist, lambda: {"weird": 1}).wait("p1") == {}


def test_run_jobs_cancels_unfinished(tmp_path, monkeypatch):
    """run_jobs 가 도중에 멈추면 넣어 두고 아직 안 받은 작업은 ComfyUI 대기열에서 뺌"""
    log = {"cancel": [], "queued": []}

    class C:
        base = "http://mock"

        def __init__(self, server):
            pass

        def queue(self, g, raw=False):
            log["queued"].append(g["id"])
            return "p%d" % g["id"]

        def wait(self, pid, label="", timeout=None, poll=1.0):
            if pid == "p2":
                raise nk.ComfyJobError("lost")
            return {}

        def cancel(self, pids):
            log["cancel"].extend(pids)

    monkeypatch.setattr(nk, "Comfy", C)
    jobs = [{"label": "j%d" % i, "graph": {"id": i}, "positive": "", "negative": "", "seed": 0, "settings": {}} for i in (1, 2, 3)]
    with pytest.raises(nk.ComfyJobError):
        nk.run_jobs({"output_root": str(tmp_path)}, jobs, "r", False, window=3)
    assert log["queued"] == [1, 2, 3] and sorted(log["cancel"]) == ["p2", "p3"]
    log["cancel"].clear(); log["queued"].clear()
    with pytest.raises(nk.ComfyJobError):
        nk.run_jobs({"output_root": str(tmp_path)}, jobs, "r2", False)          # window 1 (기본): 하나씩
    assert log["queued"] == [1, 2] and log["cancel"] == ["p2"]


def test_job_error_message_without_traceback(capsys, monkeypatch):
    """ComfyJobError -> 한국어 [ERROR] 한 줄 + 종료 코드 1 (nk 명령·nk_animacut.run 둘 다)"""
    with pytest.raises(SystemExit) as e:
        nk.comfy_job_failed(nk.ComfyJobError("ComfyUI 가 작업을 잃어버렸습니다 (cut03)"))
    assert e.value.code == 1 and "[ERROR] ComfyUI 가 작업을 잃어버렸습니다 (cut03)" in capsys.readouterr().out

    class ComfyJobError(RuntimeError):           # nk.py 를 바로 실행하면 '__main__' 쪽 클래스 -> 이름으로 알아봄
        pass
    assert nk.is_job_error(ComfyJobError("x")) and not nk.is_job_error(RuntimeError("x"))

    import nk_animacut as A

    def boom(nk_, kit, args):
        raise ComfyJobError("lost (cut01)")
    monkeypatch.setattr(A, "_run", boom)
    with pytest.raises(SystemExit) as e:
        A.run(nk, ".", None)
    assert e.value.code == 1
    monkeypatch.setattr(A, "_run", lambda *a: (_ for _ in ()).throw(ValueError("code bug")))
    with pytest.raises(ValueError):                # 다른 오류는 그대로 (숨기지 않음)
        A.run(nk, ".", None)
