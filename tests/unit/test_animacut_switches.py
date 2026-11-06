# -*- coding: utf-8 -*-
"""캐릭터 태그 겹침 빼기, 콘티 통과"""
import nk_animacut as A

R = {"name": "r"}; L = {"name": "l"}


def cut(p1, p2, scene="park"):
    return {"id": 2, "scene": scene, "_roles": [({"pos": p1}, R), ({"pos": p2}, L)]}


def test_gaze_people_rules():
    on = {"gaze": "auto"}
    assert A.gaze_people({"gaze": "off"}, cut("walking", "smile")) == [False, False]     # 끔
    assert A.gaze_people({}, cut("walking", "smile")) == [True, True]
    assert A.gaze_people(on, cut("walking, half-closed eyes", "smile")) == [True, True]  # 반쯤 감은 눈은 시선 아님
    assert A.gaze_people(on, cut("hug, looking away", "hug, closed eyes")) == [False, False]
    assert A.gaze_people(on, cut("smirk", "looking up")) == [True, False]
    assert A.gaze_people(on, cut("sitting", "sitting", "back-to-back, grass")) == [False, False]
    assert A.gaze_people(on, dict(cut("a", "b"), angle="back")) == [False, False]          # 뒷모습
    assert A.gaze_people(on, cut("carrying", "sleepy", "piggyback, walking")) == [False, False]   # 업기
    assert A.gaze_on(on, cut("smirk", "happy")) and not A.gaze_on(on, cut("smirk", "looking up"))
    assert A.gaze_people(on, {"id": 1, "scene": "solo", "_char": R}) == [False, False]


def test_dedupe_tags():
    assert A._dedupe_tags("safe, 1girl, white hair. text", "1girl, white hair, black vest, black vest") == "black vest"


def test_adopted_defaults():
    assert A.char_tags_on({}) and A.char_tags_on({"char_tags": True})
    assert not A.char_tags_on({"char_tags": False}) and not A.char_tags_on({"char_tags": "off"})


def test_char_negs_skip_conflicts():
    F = {"trigger": "testwoman", "tags_full": "white hair", "anima": "adult woman", "negative_extra": "weapon, long hair, animal ears, furry"}
    N = {"trigger": "testneko", "tags_full": "cat ears, animal ears, grey hair", "anima": "cat ears", "negative_extra": "child, long hair"}
    c = {"_roles": [({"pos": "a"}, F), ({"pos": "b"}, N)]}
    assert A.char_negs({}, c) == ""                                            # 기본 꺼짐
    assert A.char_negs({"char_neg": True}, c) == "weapon, long hair, child"    # 상대 긍정 말(animal ears)·furry 는 뺌


def test_duo_strength_default():
    assert A.duo_strength({}, cut("a", "b")) == [0.45, 0.45, 0.3, 0.7]
    assert A.duo_strength({}, {"id": 1, "_char": R}) is None                              # 혼자 컷은 그대로
    assert A.duo_strength({"duo_strength": "off"}, cut("a", "b")) is None
    assert A.duo_strength({"pose3d_strength": "0.3/0.7,0.3/0.7"}, {"id": 1}) == [0.3, 0.7, 0.3, 0.7]


def test_auto_retry_keeps_best(tmp_path, monkeypatch):
    """검사기에 걸린 컷만 다시 그리고, 걸림이 가장 적은 판을 최종으로 (GPU 없이 가짜 ComfyUI)"""
    import argparse, json, os
    import nk_webtoon as W
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    monkeypatch.setattr(A, "_reseed_path", lambda ep: str(tmp_path / "reseed.json"))
    dst = tmp_path / "cut01.png"; dst.write_bytes(b"orig")
    scores = {"cut01.png": 2, "cut01_try1.png": 1, "cut01_try2.png": 0}
    monkeypatch.setattr(A, "body_flags", lambda kit, ep, cut, img: [("pose", "x", 1)] * scores[os.path.basename(img)])
    class C:
        def queue(self, g): return g
        def wait(self, g, label): return {"10": {"images": [label]}}
        def fetch(self, im, p): open(p, "wb").write(im.encode())
    rec = {"1": {"seed": 501}}
    args = argparse.Namespace(ep="e", seed="500")
    A.auto_retry(None, ".", args, {}, {"id": 1}, C(), {"steps": 30, "cfg": 4.5, "sampler": "er_sde", "unet": "u"}, "t", "n", 64, 64, "cut01",
                 str(dst), 3, rec, str(tmp_path / "rec.json"))
    assert dst.read_bytes() == b"cut01 try2" and rec["1"]["retry"] == 2       # 걸림 0 인 두 번째 시도에서 멈추고 그걸 최종으로
    assert (tmp_path / "_alt" / "cut01_try0.png").read_bytes() == b"orig"
