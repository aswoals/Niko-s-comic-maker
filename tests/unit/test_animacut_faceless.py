# -*- coding: utf-8 -*-
"""Anima 컷 글: 컷 neg 넣기 / 서로 보기 문장의 his·her·their / 얼굴이 칸 밖인 사람 (GPU 없이 글만)"""
import nk
import nk_animacut as A
import nk_pose
import nk_webtoon as W

FOX = {"name": "fox", "trigger": "testfox", "compose_name": "the fox boy",
       "tags_full": "1boy, furry, anthro, fox boy, orange fur, white muzzle, green eyes, pointy ears, fluffy tail, blue hoodie",
       "anima": "A small anthro fox boy with orange fur, a white muzzle, green eyes, pointy ears, a fluffy tail and a blue hoodie.",
       "anima_body": "The body of a small anthro fox boy with orange fur, a fluffy tail and a blue hoodie."}
RAB = {"name": "rab", "trigger": "testrabbit", "compose_name": "the rabbit girl",
       "tags_full": "1girl, furry, anthro, rabbit girl, white fur, long ears, red eyes, yellow raincoat",
       "anima": "A small anthro rabbit girl with white fur, long ears, red eyes and a yellow raincoat."}
HEAD = "masterpiece, best quality, score_7, safe, "


def _text(monkeypatch, cut, text, neg=""):
    monkeypatch.setattr(nk_pose, "_cut_prompt", lambda nk_, W_, cfg, conti, c: ({"negative_extra": neg, "size": "832x1216"}, text, None))
    return A.cut_text(nk, W, {}, {"char_tags": False}, cut, "")[1]


def test_cut_neg_adds_cut_and_location_neg_once():
    s = {"negative_extra": "Watermark, umbrella, rain, umbrella"}            # 컷 neg + 장소 neg (watermark 는 NEG 에 이미 있음)
    assert A.cut_neg(s) == A.NEG + ", umbrella, rain"
    assert A.cut_neg(s, {"anima_neg": "bokeh, rain"}) == A.NEG + ", bokeh, rain, umbrella"
    assert A.cut_neg({}, {}) == A.NEG and A.cut_neg(None) == A.NEG


def test_cut_neg_reaches_draw(monkeypatch, tmp_path):
    """계획표 컷 neg·장소 neg 가 실제 그리기 neg 로 들어감 (예전엔 neg_for 만 써서 빠졌음) - 모의 실행으로 그래프에 넘기는 neg 확인"""
    import argparse, nk_animatest
    cut = {"id": 1, "shot": "knee", "scene": "solo, smile", "_char": RAB}
    monkeypatch.setattr(W, "load_conti", lambda nk_, kit, ep: {"cuts": [cut], "anima_neg": "bokeh"})
    monkeypatch.setattr(W, "ep_dir", lambda kit, ep: str(tmp_path))
    monkeypatch.setattr(W, "tag_report", lambda *a: None)
    monkeypatch.setattr(W, "_final_file", lambda kit, ep, cid: str(tmp_path / ("cut%02d.png" % cid)))
    monkeypatch.setattr(nk_pose, "_cut_prompt", lambda *a: ({"negative_extra": "umbrella, text", "size": "832x1216"}, HEAD + "solo. " + RAB["anima"], None))
    got = []
    monkeypatch.setattr(nk_animatest, "graph", lambda v, text, neg, *a: got.append(neg) or {})
    A.run(nk, str(tmp_path), argparse.Namespace(ep="ep", cuts=[], unet="u", steps="30", cfg="4.5", sampler="er_sde", shift=None,
                                                 artist=None, seed="500", force=False, dry=True, neg_extra=None, nolora=False))
    assert got == [A.NEG + ", bokeh, umbrella"]                               # 'text' 는 NEG 에 이미 있어서 한 번만


def test_gaze_poss():
    assert A.gaze_poss(FOX) == "his" and A.gaze_poss(RAB) == "her"
    assert A.gaze_poss({"anima": "A tall adult man with a grey coat."}) == "his"
    assert A.gaze_poss({"anima": "A woman with a red hat."}) == "her"
    assert A.gaze_poss({"anima": "A round robot."}) == "their" and A.gaze_poss(None) == "their"
    assert A.gaze_poss({"tags_full": "1girl, holding his sword"}) == "her"          # 1boy/1girl 태그가 먼저


def test_gaze_sentence_uses_each_gender(monkeypatch):
    cut = {"id": 2, "shot": "full", "scene": "duo, grass", "_roles": [({"pos": "smile"}, FOX), ({"pos": "smile"}, RAB)]}
    t = _text(monkeypatch, cut, HEAD + "duo. On the left is " + FOX["anima"] + " On the right is " + RAB["anima"])
    assert "The fox boy turns his head and looks directly at the rabbit girl" in t
    assert "The rabbit girl turns her head and looks directly at the fox boy" in t


def test_faceless_person_in_duo(monkeypatch):
    """얼굴이 칸 밖인 사람: 서로 보기 문장 없음, 몸 설명(anima_body)"""
    cut = {"id": 3, "shot": "knee", "scene": "duo, park", "_roles": [({"pos": "standing, head out of frame"}, FOX), ({"pos": "smile"}, RAB)]}
    assert A.gaze_people({}, cut) == [False, True]
    t = _text(monkeypatch, cut, HEAD + "duo. On the left is " + FOX["anima"] + " On the right is " + RAB["anima"])
    assert "turns his head" not in t and "The rabbit girl turns her head and looks directly at the fox boy" in t
    assert FOX["anima_body"] in t and FOX["anima"] not in t and RAB["anima"] in t


def test_faceless_solo_drops_head_tags(monkeypatch):
    """혼자 컷 + 얼굴 칸 밖: 핵심 태그에서 머리 묘사 빼기, 머리가 들어가는 구도 태그(cowboy shot) 빼기"""
    cut = {"id": 4, "shot": "knee", "scene": "solo, head out of frame, holding cup", "_char": FOX}
    monkeypatch.setattr(nk_pose, "_cut_prompt", lambda *a: ({}, HEAD + "cowboy shot, solo, head out of frame, holding cup. " + FOX["anima"], None))
    t = A.cut_text(nk, W, {}, {}, cut, "")[1]
    assert "cowboy shot" not in t and FOX["anima_body"] in t
    assert "orange fur" in t and "blue hoodie" in t
    assert "green eyes" not in t and "pointy ears" not in t and "white muzzle" not in t
    assert A.headless_tags("1boy, brown hair, ponytail, green eyes, cat ears, round glasses, red scarf, earrings") == "1boy, red scarf, earrings"
    cut2 = dict(cut, scene="solo, smile, holding cup")                       # 얼굴이 보이면 그대로
    monkeypatch.setattr(nk_pose, "_cut_prompt", lambda *a: ({}, HEAD + "cowboy shot, solo, smile. " + FOX["anima"], None))
    t2 = A.cut_text(nk, W, {}, {}, cut2, "")[1]
    assert "cowboy shot" in t2 and "green eyes" in t2 and FOX["anima"] in t2


def test_faceless_words():
    assert A.faceless("standing, face out of frame") and A.faceless("Head out of frame")
    assert not A.faceless("standing, out of frame") and not A.faceless(None)
