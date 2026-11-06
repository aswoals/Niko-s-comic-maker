# -*- coding: utf-8 -*-
"""학습이 실패해도 다시 켜기"""
import types
import nk_trainanima as T


def test_comfy_roots_top_only():
    procs = [(5380, 7788, "C:/x/Comfy Desktop.exe"), (5400, 5380, "C:/x/Comfy Desktop.exe"), (5401, 5380, "C:/x/Comfy Desktop.exe")]
    assert T.comfy_roots(procs) == [(5380, "C:/x/Comfy Desktop.exe")]
    assert T.comfy_roots([]) == []


def test_restart_even_if_training_fails(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(T, "build_cmd", lambda kit, c, b: ["py", "x", "--m", str(tmp_path), "--q", str(tmp_path), "--v", str(tmp_path), "--d", str(tmp_path)])
    monkeypatch.setattr(T, "comfy_stop", lambda kit, dry=False: calls.append("stop") or "C:/x/Comfy Desktop.exe")
    monkeypatch.setattr(T, "comfy_start", lambda exe, wait_s=420: calls.append(("start", exe)))
    monkeypatch.setattr(T, "comfy_free", lambda cfg: calls.append("free"))
    monkeypatch.setattr(T, "gpu_used_mb", lambda: (0, 0))
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    class P:
        pid = 1
        def wait(self):
            raise KeyboardInterrupt          # 학습이 도중에 멈춤
    monkeypatch.setattr(T.subprocess, "Popen", lambda *a, **k: P())
    (tmp_path / "_remote").mkdir()
    (tmp_path / "c.yaml").write_text("output_name: t", encoding="utf-8")
    nk = types.SimpleNamespace(load_presets=lambda: {})
    args = types.SimpleNamespace(config="c.yaml", bench=None, dry=False, stop_comfy=True)
    try:
        T.run(nk, str(tmp_path), args)
    except KeyboardInterrupt:
        pass
    assert calls == ["stop", ("start", "C:/x/Comfy Desktop.exe")]      # /free 대신 끄기, 멈춰도 다시 켬
