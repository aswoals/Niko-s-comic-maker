# -*- coding: utf-8 -*-
"""regtest 변형 이름 검사 (nk_regional.run) — 모르는 이름은 그림을 그리기 전에 멈춰야 함"""
import os, sys, shutil, argparse
import pytest

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ep(tmp_path, monkeypatch):
    """임시 NK_HOME 에 시험 편 콘티를 만듦"""
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    d = tmp_path / "episodes" / "selftest01"
    shutil.copytree(os.path.join(KIT, "tests", "fixtures", "selftest01"), d)
    import nk, nk_plan
    nk_plan.run_compile(nk, KIT, argparse.Namespace(ep="selftest01", dry=False, plan=None))
    return nk


def _run(nk, variants, capsys):
    import nk_regional
    args = argparse.Namespace(ep="selftest01", cuts=[4], variants=variants, seeds="71", name="t", dry=True)
    try:
        nk_regional.run(nk, KIT, args)
        code = 0
    except SystemExit as e:
        code = e.code
    return code, capsys.readouterr().out


@pytest.mark.parametrize("bad", ["X", "PT", "PTx", "AMB0.7.1", "AMIZ", "AMIB0.75s", "p"])
def test_unknown_variant_stops(ep, capsys, bad):
    code, out = _run(ep, bad, capsys)
    assert code == 1 and "unknown variant" in out


@pytest.mark.parametrize("good", ["P", "PT0.2", "AM", "AMB", "AMB0.7", "AMI0.5", "AMIN0.4", "AMIL0.4", "AMIC", "AMIB0.75s8",
                                  "AMIBL0.8", "P+O"])
def test_known_variant_passes_name_check(ep, capsys, good):
    code, out = _run(ep, good, capsys)
    assert "unknown variant" not in out
