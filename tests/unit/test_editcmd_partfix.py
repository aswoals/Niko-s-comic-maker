# -*- coding: utf-8 -*-
import numpy as np
import nk_editcmd as E
import nk_partfix as P

PLAN = {"cast": {"hero": "testcat", "bunny": "testbunny"},
        "pages": [{"cuts": [{"who": [], "action": "park, tree"},
                            {"who": ["hero"], "action": "looking up, surprised, :o"},
                            {"who": ["hero", "bunny"], "action": "looking up, tree", "roles": {"hero": "sweatdrop", "bunny": "pout"}}]}]}
NAMES = {"hero": "주인공 (시험용)", "bunny": "토끼 (시험용)"}


def v(cid, text, raw, tmp="."):
    return E.validate(tmp, E.cut_context(PLAN, cid, NAMES), raw, text)


def test_part_needs_who_and_part():
    o = v(3, "토끼 왼손이 이상해", {"action": "part", "who": "", "part": "", "add": [], "remove": []})
    assert o["job"] == {"kind": "partfix", "cut": 3, "who": "bunny", "part": "hand"}          # 이름·부위를 요청 글에서 찾음
    assert v(3, "손 고쳐줘", {"action": "part", "who": "", "part": "hand"})["job"] is None            # 두 명 컷인데 누구인지 없음
    assert v(2, "손 고쳐줘", {"action": "part", "who": "", "part": "hand"})["job"]["who"] == "hero"  # 혼자 컷이면 그 캐릭터
    assert v(1, "손 고쳐줘", {"action": "part", "who": "", "part": "hand"})["job"] is None            # 사람 없는 컷


def test_retag_checks_tags(monkeypatch):
    import nk_webtoon as W
    monkeypatch.setattr(W, "_load_tagdb", lambda kit: None)          # 태그 사전 없이 (형식 검사만)
    o = v(2, "웃게, 놀란 표정 빼", {"action": "retag", "who": "", "part": "", "add": ["Smile", "웃음"], "remove": ["surprised", "rain"]})
    assert o["job"] == {"kind": "fix", "cut": 2, "add": "smile", "remove": "surprised", "who": ""}
    assert any("영어 태그가 아닌" in w for w in o["warnings"]) and any("못 뺌" in w for w in o["warnings"])
    assert v(2, "음", {"action": "retag", "add": [], "remove": []})["action"] == "unknown"


def test_other_actions_and_garbage():
    assert v(2, "다시", {"action": "redraw"})["job"] == {"kind": "fix", "cut": 2}
    assert v(2, "여러 장", {"action": "cands"})["job"] == {"kind": "cands", "cut": 2}
    assert v(2, "?", {"action": "dance"})["action"] == "unknown" and v(2, "?", None)["job"] is None


def test_partfix_helpers(tmp_path):
    body = np.zeros((10, 10), bool); body[:, :5] = True
    a = np.zeros((10, 10), bool); a[2:4, 1:3] = True            # 몸 안
    b = np.zeros((10, 10), bool); b[2:8, 6:9] = True            # 몸 밖 (상대의 손)
    c = np.zeros((10, 10), bool); c[5:9, 0:4] = True            # 몸 안, 더 큼
    got = P.keep_in_body([a, b, c], body)
    assert len(got) == 2 and got[0].sum() == c.sum()              # 몸 안 것만, 큰 순서
    assert P.next_name(str(tmp_path)) == "p01.png"
    (tmp_path / "p01.png").write_bytes(b"x")
    assert P.next_name(str(tmp_path)) == "p02.png"
    t = P.part_text({"anima": "a white rabbit", "tags_short": "rabbit"}, "hand", "artist a")
    assert "@artist a" in t and "hand focus" in t and "furry" not in t and "a white rabbit" in t
    assert "furry, anthro" in P.part_text({"anima_lora": "x.safetensors", "anima_chest": "testcat chest"}, "chest", "")
