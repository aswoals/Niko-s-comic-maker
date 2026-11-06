# -*- coding: utf-8 -*-
"""작업실 진행 표시: 도는 작업 기록에서 편·단계, 컷 파일 수로 몇 번째 컷·남은 시간(추정)"""
import os, types
import nk_web


def _app(tmp_path):
    ep_root = tmp_path / "episodes"
    a = types.SimpleNamespace(logs=str(tmp_path / "logs"), SEC_PER_CUT=85, SEC_TAIL=60,
                              ep_dir=lambda ep, rid: str(ep_root / ep),
                              nk=types.SimpleNamespace(load_yaml=lambda p: {"pages": [{"cuts": [{"id": 1}, {"id": 2}, {"id": 3}]}]}))
    os.makedirs(a.logs)
    d = ep_root / "n01" / "cuts"; d.mkdir(parents=True)
    (ep_root / "n01" / "conti.yaml").write_text("x", encoding="utf-8")
    (d / "cut01.png").write_bytes(b"x")
    return a


def test_progress_make_step(tmp_path):
    a = _app(tmp_path)
    open(os.path.join(a.logs, "j1.log"), "w", encoding="utf-8").write("# nk ep auto n01\n==== [compile]\n==== [make] 16:40\n")
    p = nk_web.App.progress(a, {"job": "j1"})
    assert p["ep"] == "n01" and p["step"] == "make" and (p["drawn"], p["total"]) == (1, 3) and p["eta_s"] == 2 * 85 + 60


def test_progress_other_jobs(tmp_path):
    a = _app(tmp_path)
    open(os.path.join(a.logs, "j2.log"), "w", encoding="utf-8").write("# nk ep animatest T.yaml\n")
    assert nk_web.App.progress(a, {"job": "j2"}) is None                       # 만화 만들기가 아닌 작업은 표시 안 함
    open(os.path.join(a.logs, "j3.log"), "w", encoding="utf-8").write("# nk ep paste n01 --file a.md --go\n==== [letter]\n")
    assert nk_web.App.progress(a, {"job": "j3"})["eta_s"] == 60
