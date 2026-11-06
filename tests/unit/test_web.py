# -*- coding: utf-8 -*-
"""작업실(nk_web): 워크플로 목록 필터(_is_flow)와 정답 표시 저장(Labels)"""
import os, json
import pytest

import nk_web


def _w(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
    return p


def test_is_flow_api_with_nk_prompt(tmp_path):
    p = _w(tmp_path / "a.json", {"3": {"class_type": "CLIPTextEncode", "inputs": {}, "_meta": {"title": "NK prompt"}}})
    assert nk_web._is_flow(str(p)) is True


def test_is_flow_title_with_colon(tmp_path):
    p = _w(tmp_path / "b.json", {"3": {"class_type": "CLIPTextEncode", "_meta": {"title": "NK: prompt positive"}}})
    assert nk_web._is_flow(str(p)) is True


def test_is_flow_ui_format_rejected(tmp_path):
    p = _w(tmp_path / "c.json", {"nodes": [{"title": "NK prompt"}], "links": []})
    assert nk_web._is_flow(str(p)) is False


def test_is_flow_without_slot_or_broken(tmp_path):
    p = _w(tmp_path / "d.json", {"3": {"class_type": "KSampler", "_meta": {"title": "KSampler"}}})
    q = _w(tmp_path / "e.json", "{not json")
    assert nk_web._is_flow(str(p)) is False
    assert nk_web._is_flow(str(q)) is False


class FakeApp:
    """Labels 가 쓰는 것만: kit, episodes(), episode()"""

    def __init__(self, kit):
        self.kit = str(kit)
        d = os.path.join(self.kit, "episodes", "e1", "cuts")
        os.makedirs(d)
        for i in (1, 2):
            with open(os.path.join(d, "cut%02d.png" % i), "wb") as f:
                f.write(b"fake-png-%d" % i)

    def episodes(self, rid="0"):
        return [{"ep": "e1", "title": "시험"}]

    def episode(self, ep, rid="0"):
        if ep != "e1":
            raise ValueError("no ep")
        return {"cuts": [{"id": i, "img": "episodes/e1/cuts/cut%02d.png" % i, "who": ["hero"], "duo": False}
                         for i in (1, 2)] + [{"id": 3, "img": None, "who": [], "duo": False}]}


@pytest.fixture
def labels(tmp_path, monkeypatch):
    monkeypatch.setenv("NK_LABELS_DIR", str(tmp_path / "_labels"))
    return nk_web.Labels(FakeApp(tmp_path / "kit"))


def test_labels_save_and_reload(labels):
    r = labels.save({"ep": "e1", "cut": 1, "flags": ["얼굴", "손", "없는흠"], "score": 150, "note": "눈이 녹음"})
    assert r["ok"] and r["key"].startswith("e1:1:")
    d = json.load(open(labels.path, encoding="utf-8"))
    rec = d[r["key"]]
    assert rec["flags"] == ["얼굴", "손"]          # 목록에 없는 흠 이름은 버림
    assert rec["score"] == 100                     # 0~100 으로 자름
    assert rec["note"] == "눈이 녹음"
    assert len(open(labels.log, encoding="utf-8").read().splitlines()) == 1


def test_labels_key_follows_picture(labels):
    k1 = labels.save({"ep": "e1", "cut": 1, "flags": ["괜찮음"]})["key"]
    with open(os.path.join(labels.app.kit, "episodes", "e1", "cuts", "cut01.png"), "wb") as f:
        f.write(b"redrawn")                         # 컷을 다시 그리면 다른 표시 (md5 가 키에 들어감)
    os.utime(os.path.join(labels.app.kit, "episodes", "e1", "cuts", "cut01.png"), (1, 1))
    k2 = labels.save({"ep": "e1", "cut": 1, "flags": ["손"]})["key"]
    assert k1 != k2
    assert set(labels.load()) == {k1, k2}


def test_labels_clear_removes(labels):
    k = labels.save({"ep": "e1", "cut": 2, "flags": ["배경"]})["key"]
    r = labels.save({"ep": "e1", "cut": 2, "flags": [], "note": "", "score": ""})
    assert r["rec"] is None and k not in labels.load()
    assert len(open(labels.log, encoding="utf-8").read().splitlines()) == 2    # 지운 것도 기록


def test_labels_rejects_bad_input(labels):
    with pytest.raises(ValueError):
        labels.save({"ep": "e1", "cut": 1, "flags": ["괜찮음", "얼굴"]})
    with pytest.raises(ValueError):
        labels.save({"ep": "../x", "cut": 1, "flags": ["얼굴"]})
    with pytest.raises(ValueError):
        labels.save({"ep": "e1", "cut": 3, "flags": ["얼굴"]})     # 그림 없는 컷
    assert not os.path.exists(labels.path)


def test_labels_items_lists_only_cuts_with_pictures(labels):
    it = labels.items()
    assert [c["id"] for c in it["episodes"][0]["cuts"]] == [1, 2]
    assert it["flags"] == nk_web.LABEL_FLAGS


@pytest.fixture
def ab(tmp_path, monkeypatch):
    monkeypatch.setenv("NK_LABELS_DIR", str(tmp_path / "_labels"))
    app = FakeApp(tmp_path / "kit")
    d = os.path.join(app.kit, "runs", "ab", "t1")
    os.makedirs(d)
    _w(os.path.join(d, "set.json"), {"name": "t1", "title": "시험", "kind": "ab", "question": "?",
                                     "choices": [{"code": "L", "label": "왼"}, {"code": "S", "label": "같"},
                                                 {"code": "R", "label": "오"}],
                                     "items": [{"id": "p01", "panels": []}, {"id": "p02", "panels": []}]})
    _w(os.path.join(d, "key.json"), {"p01": {"L": "on", "R": "off"}})
    os.makedirs(os.path.join(app.kit, "runs", "ab", "t1_old_0930_1000"))     # 옮겨 둔 예전 판은 안 보임
    _w(os.path.join(app.kit, "runs", "ab", "t1_old_0930_1000", "set.json"), {"items": []})
    return nk_web.ABSets(app)


def test_ab_items_hide_key_and_old(ab):
    it = ab.items()
    assert [s["name"] for s in it["sets"]] == ["t1"]
    assert "key" not in json.dumps(it) and '"on"' not in json.dumps(it)      # 정답표는 화면에 안 감


def test_ab_save_reload_clear(ab):
    r = ab.save({"set": "t1", "item": "p01", "choice": "R", "note": "눈이 또렷"})
    assert r["key"] == "t1:p01" and ab.load()["t1:p01"]["choice"] == "R"
    r = ab.save({"set": "t1", "item": "p01", "choice": "", "note": ""})
    assert r["rec"] is None and "t1:p01" not in ab.load()
    assert len(open(ab.log, encoding="utf-8").read().splitlines()) == 2


def test_ab_rejects_bad_input(ab):
    for b in ({"set": "../x", "item": "p01", "choice": "L"}, {"set": "nope", "item": "p01", "choice": "L"},
              {"set": "t1", "item": "p99", "choice": "L"}, {"set": "t1", "item": "p01", "choice": "X"}):
        with pytest.raises(ValueError):
            ab.save(b)
    assert not os.path.exists(ab.path)
