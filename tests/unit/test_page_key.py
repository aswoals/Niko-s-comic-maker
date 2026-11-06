# -*- coding: utf-8 -*-
"""작업실 '기본이 가린 보기'
화면(/)에 심은 열쇠가 맞을 때만 개인 항목이 보이고, 열쇠가 없는 요청(curl 등)은 늘 가린 보기"""
import json, os, threading, urllib.request, urllib.error
import pytest
import nk
import nk_web as W

SECRET = "zz_private_title_zz"


@pytest.fixture
def srv(tmp_path, monkeypatch):
    kit = tmp_path / "kit"; kit.mkdir()
    (kit / "nk_remote.py").write_text("# fake", encoding="utf-8")
    home = tmp_path / "home"
    (home / "_nk" / "queue").mkdir(parents=True)
    json.dump({"args": ["ep", "fix", SECRET, "3"], "note": SECRET}, open(home / "_nk" / "queue" / "a261001_100000001_fix_x.json", "w"))
    ep = home / "episodes" / SECRET; (ep / "cuts").mkdir(parents=True)
    (ep / "conti.yaml").write_text("title: " + SECRET + "\npages: []\n", encoding="utf-8")
    from PIL import Image
    Image.new("RGB", (8, 8)).save(ep / "cuts" / "cut01.png")
    cfg = tmp_path / "workshop.json"; cfg.write_text(json.dumps({"folders": [str(home)]}), encoding="utf-8")
    monkeypatch.setattr(W, "CFG_PATH", str(cfg))
    app = W.App(nk, str(kit))
    s = W._Server(("127.0.0.1", 0), W.make_handler(app))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % s.server_address[1], SECRET
    s.shutdown()


def get(base, path, key=None):
    rq = urllib.request.Request(base + path, headers={"X-NK-K": key} if key else {})
    try:
        r = urllib.request.urlopen(rq, timeout=10)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_no_key_is_masked(srv):
    base, sec = srv
    c, b = get(base, "/api/status")
    assert c == 200 and sec.encode() not in b and json.loads(b)["queue"][0]["name"] == "private"      # 열쇠 없음 = 가린 보기
    assert json.loads(b).get("stale") is False
    c, b = get(base, "/api/roots")
    assert c == 200 and not any(r.get("private") for r in json.loads(b))
    for p in ("/api/episodes?root=1", "/api/ep?root=1&ep=" + sec, "/img?root=1&p=episodes/%s/cuts/cut01.png" % sec, "/api/log?root=1&id=x"):
        assert get(base, p)[0] == 403, p


def test_page_key_unmasks(srv):
    base, sec = srv
    c, page = get(base, "/")
    key = page.decode("utf-8").split("window.NKK=")[1].split(";")[0].strip('"')
    assert c == 200 and len(key) == 32 and key == W.PAGE_KEY
    c, b = get(base, "/api/status", key)
    assert c == 200 and sec.encode() in b and "stale" not in json.loads(b)                             # 화면은 다 보임
    assert any(r.get("private") for r in json.loads(get(base, "/api/roots", key)[1]))
    assert get(base, "/img?root=1&p=episodes/%s/cuts/cut01.png&k=%s" % (sec, key))[0] == 200            # 그림은 주소에 열쇠
    assert get(base, "/api/episodes?root=1", key)[0] == 200


def test_claude_view_page_has_no_key(srv):
    base, sec = srv
    c, page = get(base, "/?view=readonly")
    assert c == 200 and "window.CV=true;window.NKK=\"\";" in page.decode("utf-8") and W.PAGE_KEY not in page.decode("utf-8")
    key = W.PAGE_KEY
    c, b = get(base, "/api/status?view=readonly", key)                                                     # view=readonly 는 열쇠가 있어도 가림
    assert sec.encode() not in b


def test_wrong_key_is_stale_and_masked(srv):
    base, sec = srv
    c, b = get(base, "/api/status", "0" * 32)
    j = json.loads(b)
    assert c == 200 and j["stale"] is True and sec.encode() not in b                                    # 다시 켜기 전 옛 화면 -> 새로 고침 신호
    c, b = get(base, "/api/episodes?root=1", "0" * 32)
    assert c == 403 and json.loads(b)["stale"] is True


def test_kit_folder_works_without_key(srv):
    base, _ = srv
    assert get(base, "/api/episodes?root=0")[0] == 200                                                   # 키트 폴더(정답 표시·시험 스크립트)는 그대로
    assert get(base, "/label")[0] == 200 and get(base, "/api/labels")[0] == 200
