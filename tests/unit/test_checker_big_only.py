# -*- coding: utf-8 -*-
"""빡빡한 규칙이 연출·자세를 경직시킴 ->
제작이 불가능할 정도로 큰 문제만 검사, 콘티에 손대는 검사는 제거"""
import os
import pytest
import nk_plan

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _plan(**kw):
    p = {"title": "t", "pages_wanted": 2, "cast": {"hero": "testcat", "zun": "testgirl"}, "artist": "",
         "locations": {"park": "park, grass", "room": "room, indoors"}, "props": {"ball": {"tags": "soccer ball"}},
         "pages": [{"cuts": [
             # 예전 검사라면 걸렸던 것들: 장소 첫 컷이 knee, 두 명 컷 roles 없음, 소품만 보이는 detail 컷 없음, 같은 자세·angle 반복,
             # 혼자 컷 0개, show: 없음, 태그가 아닌 말, 혼자 컷인데 닿는 동작
             {"who": ["hero", "zun"], "shot": "knee", "angle": "eye", "loc": "park", "action": "sitting, gently smiling softly", "props": ["ball"]},
             {"who": ["hero", "zun"], "shot": "knee", "angle": "eye", "loc": "park", "action": "sitting, smile", "props": ["ball"],
              "roles": {"hero": "smile", "zun": "smile"}},
             {"who": ["hero"], "shot": "waist", "angle": "eye", "loc": "room", "action": "hug, happy"},
         ]}]}
    p.update(kw)
    return p


def test_old_style_rules_no_longer_send_back():
    assert nk_plan.plan_problems(KIT, _plan()) == []


def test_unknown_artist_is_still_big():
    probs = nk_plan.plan_problems(KIT, _plan(artist="zz_no_such_artist_zz"))
    assert len(probs) == 1 and "작가" in probs[0]
    assert nk_plan.plan_problems(KIT, _plan(artist="")) == []          # 작가를 안 정한 것은 막지 않음


def test_listed_artists_pass_even_if_not_in_tag_dict(monkeypatch):
    """presets.yaml 의 main_artists 에 있는 작가는 태그 사전에 없어도 통과"""
    import nk
    real = nk.load_presets
    monkeypatch.setattr(nk, "load_presets", lambda *a, **k: dict(real(), main_artists=["artist c", "artist e"]))
    for a in ("artist c", "artist e"):
        assert nk_plan.plan_problems(KIT, _plan(artist=a)) == [], a


def test_notes_are_only_notes():
    p = _plan(must_tags=["rain", "soccer ball", "umbrella"], must_scenes=["공 차기"])
    p["pages"][0]["cuts"][0]["sentence"] = "They play in the rain"
    notes = nk_plan.plan_notes(KIT, p)
    assert any("umbrella" in n for n in notes) and not any("'rain'" in n for n in notes)     # 문장에 있으면 빠진 게 아님
    assert not any("soccer ball" in n for n in notes)                                       # 소품 태그에 있음
    assert any("공 차기" in n for n in notes) and any("2쪽" in n for n in notes)              # 장면 표시 없음, 쪽수 다름
    assert nk_plan.plan_problems(KIT, p) == []                                               # 돌려보내지는 않음


def test_compiler_quietly_fixes_picture_breaking_bits():
    p = _plan()
    p["locations"]["park"] = "park, grass, blue theme, monochrome"
    p["pages"][0]["cuts"][2]["shot"] = "detail"
    conti, notes = nk_plan.compile_plan(p, None, KIT)
    tags = conti["world"]["locations"]["park"]["tags"]
    assert "blue theme" not in tags and "monochrome" not in tags and "park" in tags
    assert any(n.startswith("D11") for n in notes)
    cut3 = [c for pg in conti["pages"] for c in pg["cuts"]][2]
    assert cut3["shot"] == "face"


def test_compiler_drops_people_tags_from_cut_tags():
    p = _plan()
    p["pages"][0]["cuts"][1]["action"] = "2boys, duo, sitting, furry, smile"
    p["pages"][0]["cuts"][1]["roles"] = {"hero": "1boy, smile", "zun": "anthro, smile"}
    conti, notes = nk_plan.compile_plan(p, None, KIT)
    c2 = [c for pg in conti["pages"] for c in pg["cuts"]][1]
    sc = [t.strip() for t in c2["scene"].split(",")]
    assert "sitting" in sc and "furry" not in sc and sc.count("2boys") <= 1 and sc.count("duo") <= 1     # 인원수는 컴파일러가 한 번만 붙임
    assert all(r["pos"] == "smile" for r in c2["cast"]) and any(n.startswith("D12") for n in notes)


def test_t36_like_plan_passes():
    import yaml
    p = os.path.join(KIT, "episodes", "t36", "plan.yaml")
    if not os.path.exists(p):
        pytest.skip("t36 없음")
    assert nk_plan.plan_problems(KIT, yaml.safe_load(open(p, encoding="utf-8"))) == []


def test_scene_sentence_and_story():
    """옛 sentence 도 받음"""
    p = _plan(story="주인공이 공을 찬다.\n공이 나무에 걸린다.")
    cuts = p["pages"][0]["cuts"]
    cuts[0]["scene"] = "The grey cat boy kneels on the grass.\n  The goat boy laughs."
    cuts[1]["sentence"] = "They sit side by side."
    conti, _ = nk_plan.compile_plan(p, None, KIT)
    cs = [c for pg in conti["pages"] for c in pg["cuts"]]
    assert cs[0]["anima_act"] == "The grey cat boy kneels on the grass. The goat boy laughs."
    assert cs[1]["anima_act"] == "They sit side by side." and "anima_act" not in cs[2]
    assert conti["story"].startswith("주인공이")
    text = nk_plan._dump(conti, [], "plan.yaml")
    assert "anima_act: The grey cat boy kneels" in text or "The grey cat boy kneels on the grass." in text


def test_workshop_reads_notes_from_compile_output():
    import nk_web
    out = ("conti -> x\n[plan] 큰 문제 1개\n  - 작가 모름\n\n[참고] 만화는 그대로 만듦 — 확인만 해 줘:\n  - 꼭 넣을 장면 '공 차기'을 그리는 컷 표시(must:)가 없음\n"
           "  - 요청은 3쪽인데 2쪽으로 씀\n[tag] 경고 1개\n  - 다른 줄\n")
    assert nk_web._plan_notes_text(out) == ["꼭 넣을 장면 '공 차기'을 그리는 컷 표시(must:)가 없음", "요청은 3쪽인데 2쪽으로 씀"]
    assert nk_web._plan_notes_text("") == []


def test_anima_negative_has_rating_guard():
    """다시 빠지지 않게"""
    import nk_animacut, nk_webtoon
    for neg in (nk_animacut.NEG, nk_webtoon.ANIMA_NEG):
        t = [x.strip() for x in neg.split(",")]
        assert "nsfw" in t, neg
    t = [x.strip() for x in nk_animacut.NEG.split(",")]
    assert "explicit" in t and "sensitive" in t


def test_speed_patch_off_by_default():
    """켜면 모델 -> INT8 어텐션 -> EasyCache -> 샘플러"""
    import nk_animatest as T
    v = {"unet": "u", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple", "lora": "x.safetensors"}
    g0 = T.graph(v, "a", "b", 64, 64, 1, "p")
    assert "16" not in g0 and "17" not in g0
    g1 = T.graph(dict(v, ck_attention=True, easycache={"reuse_threshold": 0.3}), "a", "b", 64, 64, 1, "p")
    ks = [n for n in g1.values() if n["class_type"] == "KSampler"][0]
    assert ks["inputs"]["model"] == ["17", 0] and g1["17"]["inputs"]["model"] == ["16", 0] and g1["16"]["inputs"]["model"] == ["11", 0]
    assert g1["16"]["inputs"]["attention"] == "comfy kitchen attention" and g1["17"]["inputs"]["reuse_threshold"] == 0.3


def test_speed_from_presets(monkeypatch):
    """혼자 컷은 둘 다, 기준 그림·영역 그리기·부분 다시 칠하기는 EasyCache 없이"""
    import nk_animatest as T, nk_regionlora as R, nk_animafix as F
    monkeypatch.setattr(T, "anima_speed", lambda: {"ck_attention": True, "easycache": True})
    v = {"unet": "u", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple", "lora": "x.safetensors"}
    g = T.graph(v, "a", "b", 64, 64, 1, "p")                                  # 혼자 컷 (animamake)
    assert "16" in g and "17" in g
    g = T.graph(dict(v, easycache=False), "a", "b", 64, 64, 1, "p")         # 두 명 컷 기준 그림
    assert "16" in g and "17" not in g
    g = F.graph(v, "a", "b", "i.png", "m.png", 1, 0.6, "p")                  # 얼굴·부위 다시 칠하기
    assert "16" in g and "17" not in g
    p = {"unet": "u", "lora": "x.safetensors", "lora_strength": 1.0, "steps": 32, "cfg": 5, "base_only": 6, "overlap": 10}
    rg = R.speed_region(R.split_graph(p, "t", "n", "pt", "neg", "m1.png", "m2.png", 64, 64, 1))
    assert rg["18"]["inputs"]["model"] == ["1", 0] and rg["11"]["inputs"]["model"] == ["18", 0]
    assert all(n["inputs"].get("model") != ["1", 0] for k, n in rg.items() if k != "18")      # 모든 모델 길이 INT8 어텐션을 지남
    monkeypatch.setattr(T, "anima_speed", lambda: {})
    assert "18" not in R.speed_region(R.split_graph(p, "t", "n", "pt", "neg", "m1.png", "m2.png", 64, 64, 1))
    assert "16" not in T.graph(v, "a", "b", 64, 64, 1, "p")                 # 설정이 없으면 예전 그대로


def test_presets_speed_section_parses():
    import nk
    sp = nk.load_presets().get("anima_speed")
    assert isinstance(sp, dict) and set(sp) >= {"ck_attention", "easycache"}


def test_anima_tags_and_neg_flow_to_cut_text():
    """없으면 예전 그대로"""
    import nk, nk_webtoon as W, nk_animacut as A
    p = _plan(cast={"man": "testman"}, artist="", anima_tags="anime coloring, flat color", anima_neg="depth of field, bokeh",
              pages=[{"cuts": [{"who": ["man"], "shot": "waist", "angle": "eye", "loc": "room", "action": "smile"}]}])
    info = {"man": nk.load_yaml(os.path.join(os.environ["NK_CHARS"], "testman.yaml"))}
    conti, _ = nk_plan.compile_plan(p, info, KIT)
    assert conti["anima_tags"] == "anime coloring, flat color" and conti["anima_neg"] == "depth of field, bokeh"
    W.attach_chars(nk, KIT, conti) if hasattr(W, "attach_chars") else None
    assert A.neg_for(conti).endswith(", depth of field, bokeh") and A.neg_for({}) == A.NEG
    p2 = dict(p); p2.pop("anima_tags"); p2.pop("anima_neg")
    c2, _ = nk_plan.compile_plan(p2, info, KIT)
    assert c2["anima_tags"] == nk_plan.ANIMA_DEFAULTS["anima_tags"] and c2["anima_neg"] == nk_plan.ANIMA_DEFAULTS["anima_neg"]
    c3, _ = nk_plan.compile_plan(dict(p2, anima_tags="none", anima_neg="none"), info, KIT)   # 'none' = 끔
    assert "anima_tags" not in c3 and "anima_neg" not in c3


def test_grok_artist_note_points_to_presets():
    """작가 목록은 코드에 박지 않고 presets.yaml(main_artists·artist_note)에서"""
    import nk_easy
    assert nk_plan.ARTISTS_LISTED == () and "main_artists" in nk_easy.ARTIST_NOTE
