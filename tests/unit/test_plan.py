# -*- coding: utf-8 -*-
"""계획표(plan.yaml) -> 콘티(conti) 변환 (nk_plan) — 순수 함수만, 서버 없음"""
import os
import yaml
import pytest

import nk_plan

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(KIT, "tests", "fixtures", "selftest01", "plan.yaml")


def _compile(plan):
    info = {k: yaml.safe_load(open(os.path.join(os.environ["NK_CHARS"], v + ".yaml"), encoding="utf-8"))
            for k, v in plan["cast"].items()}
    return nk_plan.compile_plan(plan, info, KIT)


@pytest.fixture
def plan():
    return yaml.safe_load(open(FIX, encoding="utf-8"))


def test_compile_fixture_cut_kinds(plan):
    conti, notes = _compile(plan)
    cuts = [c for p in conti["pages"] for c in p["cuts"]]
    assert [c["id"] for c in cuts] == [1, 2, 3, 4]
    assert cuts[0]["char"] == "none"                             # 풍경 컷
    assert "solo" in cuts[1]["scene"] and "char" not in cuts[1]  # 주인공 혼자 컷 = 기본 캐릭터
    assert cuts[2]["char"] == "buddy"
    assert [r["char"] for r in cuts[3]["cast"]] == ["hero", "buddy"]   # 두 명 컷
    assert "2boys" in cuts[3]["scene"]


def test_compile_props_become_tagger_qa(plan):
    conti, _ = _compile(plan)
    c2 = conti["pages"][0]["cuts"][1]
    assert c2["props"] == ["ball"]
    assert {"tag": "ball", "min": 0.35, "must": True} in c2["qa"]
    assert c2["show"] == ["The grey cat holds a ball"]


def test_compile_speech_text_kept(plan):
    conti, _ = _compile(plan)
    texts = [t["text"] for p in conti["pages"] for c in p["cuts"] for t in c.get("text", [])]
    assert "공 놀이 하자!" in texts and "받았다!" in texts


def test_compile_keeps_restyle_and_artist(plan):
    conti, _ = _compile(dict(plan, artist="some artist"))
    assert conti["restyle"] == "picturebook"
    assert conti["artist"] == "some artist"


def test_ranges():
    assert nk_plan._ranges([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8"
    assert nk_plan._ranges([4]) == "4"
    assert nk_plan._ranges([3, 1, 2, 2]) == "1-3"
    assert nk_plan._ranges([]) == ""


def test_join_dedup_and_trim():
    assert nk_plan._join("a, b,, c", " b ,d", None) == "a, b, c, d"


def test_prop_qa_tag_strips_colors():
    assert nk_plan._prop_qa_tag("white bowl, mixing bowl, whisk") == "white_bowl|bowl|mixing_bowl|whisk"
    assert nk_plan._prop_qa_tag("") == ""


def test_extract_yaml_from_web_ai_answer():
    raw = "네, 계획입니다.\n```yaml\ntitle: \"x\"\npages: []\n```\n더 필요하면 말해 주세요."
    d, body = nk_plan._extract_yaml(raw)
    assert d == {"title": "x", "pages": []}
    d2, _ = nk_plan._extract_yaml("title: y\n")
    assert d2 == {"title": "y"}


def _touch_plan(plan, **extra):
    """시험 편 두 명 컷(4)을 손잡기로"""
    plan = dict(plan, **extra)
    cut = plan["pages"][0]["cuts"][3]
    cut["action"] = "holding hands, looking at another"
    return plan


def test_rule5_lifted_touch_cut_stays_duo(plan):
    conti, notes = _compile(_touch_plan(plan))
    c4 = conti["pages"][0]["cuts"][3]
    assert [r["char"] for r in c4["cast"]] == ["hero", "buddy"] and "holding hands" in c4["scene"]
    assert "D1" in conti["rules_off"] and not any(n.startswith("D1 cut") for n in notes)


def test_rule5_can_be_turned_back_on(plan):
    """plan rules_on: [D1] = 예전처럼 닿는 두 명 컷을 혼자 컷으로"""
    conti, notes = _compile(_touch_plan(plan, rules_on=["D1"]))
    c4 = conti["pages"][0]["cuts"][3]
    assert "cast" not in c4 and "holding hands" not in c4.get("scene", "")
    assert any(n.startswith("D1 cut 4") for n in notes) and "D1" not in (conti.get("rules_off") or [])


def test_anima_interaction_sentences():
    """닿는 동작 태그 -> 자리 잡기(Anima) 동작 문장 (계획표 규칙 5 에 적은 동작 모두)"""
    import nk_webtoon as W
    rs = [{"key": "hero", "char": {"compose_name": "grey cat"}, "rp": "smile"},
          {"key": "buddy", "char": {"compose_name": "white goat"}, "rp": "smile"}]
    for tag in ("holding hands", "high five", "arm around shoulder", "hug", "back-to-back", "headpat", "giving"):
        act = W._anima_interaction("duo, 2boys, %s, park" % tag, rs)
        assert act and act[0] == tag, tag
    assert W._anima_interaction("duo, 2boys, piggyback", [dict(rs[0], rp="carrying another"), rs[1]])[0] == "piggyback"
    assert W._anima_interaction("duo, 2boys, standing, park", rs) is None



def test_conti_check_touch_warning_follows_rule5(plan):
    """검사기: D1 꺼진 편(기본) = 닿는 동작 경고 없음 / D1 켠 편 = 경고 (규칙서 '몸 겹침'). 검사기는 conti["cuts"] 를 봄"""
    import nk_webtoon as W
    conti, _ = _compile(_touch_plan(plan))
    cuts = [c for p in conti["pages"] for c in p["cuts"]]
    assert any(c.get("cast") for c in cuts)                               # 두 명 컷이 실제로 검사 대상
    off = " ".join(W.conti_check(dict(conti, cuts=cuts)))
    on = " ".join(W.conti_check(dict(conti, cuts=cuts, rules_off=[])))
    assert "몸이 겹치는 동작" not in off
    assert "몸이 겹치는 동작" in on


def test_rule6_duo_face_allowed_by_default(plan):
    """rules_on: [D2] 면 예전처럼 knee"""
    for shot, on, want in (("waist", False, "waist"), ("face", False, "face"), ("face", True, "knee")):
        p = yaml.safe_load(open(FIX, encoding="utf-8"))
        p["pages"][0]["cuts"][3]["shot"] = shot
        if on:
            p["rules_on"] = ["D2"]
        conti, notes = _compile(p)
        assert conti["pages"][0]["cuts"][3]["shot"] == want, (shot, on, notes)
        assert any(n.startswith("D2 cut 4") for n in notes) == on


def test_frame_pose_file_zooms_waist_and_keeps_original(tmp_path):
    """auto 가 waist 두 명 컷 뼈대를 확대: 원본은 _unframed 로 남고, 두 번 불러도 한 번만 확대"""
    import json
    import numpy as np
    import nk_pose
    W_, H_ = 1024, 1024
    def person(cx):
        k = np.zeros((18, 2)); c = np.ones(18)
        k[0] = (cx, 200); k[1] = (cx, 300)
        for i, (dx, y) in enumerate(((-60, 300), (-80, 450), (-90, 600), (60, 300), (80, 450), (90, 600)), start=2):
            k[i] = (cx + dx, y)
        for i, (dx, y) in zip((8, 9, 10, 11, 12, 13), ((-40, 600), (-40, 780), (-40, 950), (40, 600), (40, 780), (40, 950))):
            k[i] = (cx + dx, y)
        for i, dx in zip((14, 15, 16, 17), (-15, 15, -30, 30)):
            k[i] = (cx + dx, 190)
        return k, c
    ppl = [person(350), person(700)]
    dst = str(tmp_path / "cut04.png")
    import cv2
    cv2.imwrite(dst, nk_pose.draw(H_, W_, ppl)[:, :, ::-1])
    nk_pose.save_kp(dst, W_, H_, [(0.0, 0.5), (0.5, 1.0)], ppl)
    z = nk_pose.frame_pose_file(dst, "waist")
    assert z > 1.1
    assert os.path.exists(dst[:-4] + "_unframed.png") and os.path.exists(dst[:-4] + "_unframed_kp.json")
    j = json.load(open(dst[:-4] + "_kp.json", encoding="utf-8"))
    assert j["framed"]["shot"] == "waist"
    hip_y = max(j["people"][0]["k"][8][1], j["people"][0]["k"][11][1])
    assert abs(hip_y - H_) < 0.05 * H_            # 엉덩이가 컷 아래 끝
    assert nk_pose.frame_pose_file(dst, "waist") == round(z, 3)   # 두 번째는 다시 확대하지 않음


def test_anima_duo_head_furry_only_when_needed():
    """털 캐릭터가 있을 때만 'furry, anthro', 인원수는 장면 태그 것 (예전: '2boys, furry' 고정)"""
    import nk_webtoon as W
    s = {"quality_tags": "masterpiece, best quality"}
    human = [{"key": "a", "span": (0.5, 1.0), "char": {"tags_short": "1girl, blonde hair"}, "anima": "A", "rp": "smile"},
             {"key": "b", "span": (0.0, 0.5), "char": {"tags_short": "1girl, green hair"}, "anima": "B", "rp": "smile"}]
    t = W._anima_prompt(s, "duo, 2girls, standing, park", human)
    assert "furry" not in t and "2boys" not in t and "safe, duo, 2girls, standing" in t
    fur = [dict(human[0], char={"tags_short": "anthro, domestic cat"}), human[1]]
    assert "safe, 2boys, duo, furry, anthro, standing" in W._anima_prompt(s, "duo, 2boys, standing, park", fur)   # 예전 글과 같음


def test_anima_solo_head_follows_character():
    """털 캐릭터만 furry·anthro, 남자 태그가 있을 때만 1boy (예전: '1boy, furry, anthro' 고정)"""
    import nk_webtoon as W
    cut = {"scene": "sitting, smile", "anima": True}
    reg = {"tags_short": "1boy, brown hair", "anima": "a boy"}
    nana = {"tags_short": "furry, animal ears", "anima": "a rabbit creature"}
    hero = {"tags_short": "anthro, domestic cat, male, girly", "anima": "Hero"}
    assert "safe, 1boy, solo, A single" in W._anima_solo({}, cut, reg, "")["text"]
    assert "safe, solo, furry, anthro, A single" in W._anima_solo({}, cut, nana, "")["text"]
    assert "safe, 1boy, solo, furry, anthro, A single" in W._anima_solo({}, cut, hero, "")["text"]


def test_anima_piggyback_rider_head_only():
    import nk_webtoon as W
    car = {"key": "hero", "span": (0.5, 1.0), "rp": "carrying", "anima": "CARRIER FULL", "char": {"anima": "CARRIER FULL"}}
    rid = {"key": "nana", "span": (0.0, 0.5), "rp": "smile", "anima": "RIDER FULL with pants", "char": {"anima": "RIDER FULL with pants", "anima_head": "RIDER HEAD"}}
    act = W._anima_interaction("duo, piggyback, forest", [car, rid])
    assert act[0] == "piggyback" and "The carrier: CARRIER FULL" in act[1] and "The one on their back: RIDER HEAD" in act[1] and "pants" not in act[1]
    rid2 = dict(rid, char={"anima": "RIDER FULL with pants"})          # anima_head 없으면 예전처럼 전체
    assert "RIDER FULL with pants" in W._anima_interaction("duo, piggyback, forest", [car, rid2])[1]


def test_animacut_shot_desc():
    """face = anima_head, waist = anima_upper, full = LoRA 캐릭터면 anima_lora_desc, 아니면 그대로"""
    import nk_animacut as A
    hero = {"anima": "FULL", "anima_head": "HEAD", "anima_upper": "UPPER", "anima_lora": "x.safetensors", "anima_lora_desc": "LORADESC"}
    assert A.shot_desc(hero, "face") == "HEAD" and A.shot_desc(hero, "waist") == "UPPER" and A.shot_desc(hero, "full") == "LORADESC"
    nana = {"anima": "FULL", "anima_head": "HEAD"}
    assert A.shot_desc(nana, "face") == "HEAD" and A.shot_desc(nana, "waist") is None and A.shot_desc(nana, "full") is None
    assert A.shot_desc(dict(hero, anima_back="BACK"), "full", back=True) == "BACK" and A.shot_desc(hero, "full", back=True) == "LORADESC"
    assert A.is_back({"scene": "duo, walking away, from behind, facing away"}) and not A.is_back({"scene": "duo, from behind, looking back, waving"})
    assert not A.is_back({"scene": "duo, holding hands"}) and A.is_back({"scene": "solo", "anima_act": "Seen from behind, he stands."})
    assert not A.is_back({"scene": "duo, piggyback"}) and A.is_back({"scene": "solo", "angle": "back"})     # 업기(piggyback)는 뒷모습 아님


def test_animafix_box_paste_desc():
    """키울 크기 16배수·긴 변 1024, 붙이기는 틀 밖을 안 바꿈, 뒷모습이면 anima_back"""
    import numpy as np
    from PIL import Image
    import nk_animafix as F
    m = np.zeros((1000, 800), bool); m[100:600, 500:780] = True
    box = F.box_from_mask(m, 800, 1000)
    assert box[0] < 500 and box[1] < 100 and box[2] == 800 and box[3] > 600          # 오른쪽 끝은 그림 폭에서 멈춤
    cw, ch = F.crop_size(box[2] - box[0], box[3] - box[1])
    assert max(cw, ch) == 1024 and cw % 16 == 0 and ch % 16 == 0
    assert F.box_from_mask(np.zeros((10, 10), bool), 10, 10) is None
    orig = Image.new("RGB", (800, 1000), (10, 200, 10))
    crop = Image.new("RGB", (cw, ch), (250, 0, 0))
    mk = Image.fromarray((m * 255).astype(np.uint8)).crop(box).resize((cw, ch))
    out = np.asarray(F.paste_back(orig, crop, mk, box))
    assert tuple(out[50, 50]) == (10, 200, 10) and tuple(out[20, 400]) == (10, 200, 10)       # 상자 밖·틀 밖은 그대로
    assert out[350, 640, 0] > 200                                                         # 틀 안은 바뀜
    big = np.zeros((2000, 2000), bool); big[100:1900, 200:1800] = True
    bb = F.box_from_mask(big, 2000, 2000); assert all(type(v) is int for v in bb)
    cw2, ch2 = F.crop_size(bb[2] - bb[0], bb[3] - bb[1])
    F.paste_back(Image.new("RGB", (2000, 2000)), Image.new("RGB", (cw2, ch2)), Image.new("L", (cw2, ch2), 255), bb)
    ch_ = {"anima": "FULL", "anima_upper": "UPPER", "anima_lora_desc": "LORA", "anima_back": "BACK"}
    assert F.desc_for(ch_, {"scene": "duo, from behind, facing away"}, (0, 0, 10, 900), 1000)[0] == "BACK"
    assert F.desc_for(ch_, {"scene": "duo, hug"}, (0, 0, 10, 900), 1000)[0] == "LORA"
    assert F.desc_for(ch_, {"scene": "duo, hug"}, (0, 0, 10, 400), 1000)[0] == "UPPER"
    ch_["anima_head"] = "HEAD"
    assert F.desc_for(ch_, {"scene": "duo, hug"}, (0, 0, 10, 900), 1000, "head")[0] == "HEAD"


def test_duo_ratio_no_limit():
    def plan(n_duo, n_solo):
        duo = {"shot": "knee", "angle": "eye", "who": ["hero", "zun"], "action": "smile",
               "roles": {"hero": "smile", "zun": "smile"}}
        solo = [{"shot": "waist", "angle": "eye", "who": [w], "action": "smile"} for w in ("hero", "zun")]
        cuts = [dict(duo) for _ in range(n_duo)] + [dict(solo[i % 2]) for i in range(n_solo)]
        return {"cast": {"hero": "testcat", "zun": "testgirl"}, "pages": [{"cuts": cuts}]}
    duo_msg = lambda ps: [x for x in ps if "두 명 컷이 사람 컷" in x]
    assert duo_msg(nk_plan.plan_problems(KIT, plan(2, 2))) == []            # 50%
    assert duo_msg(nk_plan.plan_problems(KIT, plan(4, 0))) == []            # 100% 도 괜찮음


def test_paste_go_makes_even_with_fix_points(tmp_path, monkeypatch):
    """    --go = 고칠 점은 보여 주고 그대로 만듦 / --go 없음(검사만) = 예전처럼 멈춤"""
    import argparse, nk_easy, nk_auto
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    ans = tmp_path / "ans.md"
    ans.write_text("```yaml\ntitle: t\ncast: {hero: testcat}\npages:\n  - cuts:\n      - {shot: wide, who: []}\n```\n", encoding="utf-8")

    def fake_compile(nk, kit, a):
        (tmp_path / "episodes" / "e1" / "fix_prompt.md").write_text("그림이 잘 나오려면 고칠 점:\n- 예시", encoding="utf-8")
    calls = []
    monkeypatch.setattr(nk_plan, "run_compile", fake_compile)          # nk_easy 는 함수 안에서 import nk_plan
    monkeypatch.setattr(nk_auto, "run", lambda nk, kit, a: calls.append(a.ep))
    monkeypatch.setattr(nk_easy, "_clip_set", lambda t: False)
    nk_easy.run_paste(None, KIT, argparse.Namespace(ep="e1", file=str(ans), go=False, flow=None))
    assert calls == []                                   # 검사만 = 멈춤
    nk_easy.run_paste(None, KIT, argparse.Namespace(ep="e1", file=str(ans), go=True, flow=None))
    assert calls == ["e1"]                               # 바로 만들기 = 고칠 점이 있어도 만듦


def test_story_off_in_anima_flow():
    """직접 켜면 그대로, noob 흐름은 예전 기본(suggest)"""
    import argparse, nk_auto
    ns = lambda **k: argparse.Namespace(**k)
    assert nk_auto._story_mode({}, ns(render="anima", story=None)) == "off"
    assert nk_auto._story_mode({}, ns()) == "off"                               # paste --go 처럼 render 가 없으면 anima
    assert nk_auto._story_mode({}, ns(render="anima", story="check")) == "check"
    assert nk_auto._story_mode({"story": "fix"}, ns(render="anima", story=None)) == "fix"
    assert nk_auto._story_mode({}, ns(render="noob", story=None)) == "suggest"


def test_animafix_chest_band():
    """머리는 빼고, 머리 못 찾으면 None"""
    import numpy as np, nk_animafix as F
    body = np.zeros((400, 200), bool); body[50:390, 40:160] = True
    head = np.zeros((400, 200), bool); head[50:150, 50:150] = True        # 머리 높이 100
    m = F.chest_mask(body, head)
    ys = np.where(m.any(axis=1))[0]
    assert ys.min() == 134 and ys.max() == 288                            # 머리 아래 끝(149)-15(목) ~ +140, 머리 자리는 빠짐
    assert not (m & head).any() and not (m & ~body).any()
    assert F.chest_mask(body, np.zeros_like(head)) is None
    ch = {"anima_chest": "CHEST", "anima_upper": "UPPER", "anima_face": "FACE"}
    assert F.desc_for(ch, {"scene": "standing"}, (0, 0, 10, 10), 100, "chest") == ("CHEST", "upper body, close-up")


def test_paste_refuses_episode_with_drawn_cuts(tmp_path, monkeypatch):
    """그린 컷이 있으면 멈추고 새 이름을 권함.
    그린 컷이 없으면(검사만 → 고쳐서 다시 붙이기) 예전처럼 됨"""
    import argparse, nk_easy
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    ans = tmp_path / "ans.md"
    ans.write_text("```yaml\ntitle: t\ncast: {hero: testcat}\npages:\n  - cuts:\n      - {shot: wide, who: []}\n```\n", encoding="utf-8")
    compiled = []
    monkeypatch.setattr(nk_plan, "run_compile", lambda nk, kit, a: compiled.append(a.ep))
    monkeypatch.setattr(nk_easy, "_clip_set", lambda t: False)
    nk_easy.run_paste(None, KIT, argparse.Namespace(ep="e1", file=str(ans), go=False, flow=None))
    nk_easy.run_paste(None, KIT, argparse.Namespace(ep="e1", file=str(ans), go=False, flow=None))    # 아직 안 그림 = 다시 붙이기 됨
    assert compiled == ["e1", "e1"]
    (tmp_path / "episodes" / "e1" / "cuts").mkdir(parents=True)
    (tmp_path / "episodes" / "e1" / "cuts" / "cut01.png").write_bytes(b"x")
    plan_before = (tmp_path / "episodes" / "e1" / "plan.yaml").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        nk_easy.run_paste(None, KIT, argparse.Namespace(ep="e1", file=str(ans), go=True, flow=None))
    assert compiled == ["e1", "e1"] and (tmp_path / "episodes" / "e1" / "plan.yaml").read_text(encoding="utf-8") == plan_before


def test_ai_char_rows_skip_hidden(tmp_path, monkeypatch):
    """ai_hide 캐릭터는 AI 첨부 파일 목록에서 뺌"""
    import nk_easy
    monkeypatch.setenv("NK_CHARS", str(tmp_path / "characters"))
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "a.yaml").write_text("name_ko: A\nanima: a\n", encoding="utf-8")
    (tmp_path / "characters" / "b.yaml").write_text("name_ko: B\nanima: b\nai_hide: true\n", encoding="utf-8")
    assert [r[1] for r in nk_easy._char_rows(str(tmp_path))] == ["a"]


def test_bubble_uses_real_spans():
    """원본 컷은 그대로"""
    import nk_webtoon as W
    ct = {"id": 5, "_roles": [({"char": "don", "side": "right"}, {}), ({"char": "hero", "side": "left"}, {})], "_img_size": (100, 100)}
    ct2 = W._with_real_spans(ct, {5: {"don": [0.0, 0.3], "hero": [0.4, 0.9]}})
    x, _ = W._speaker_point({"who": "don"}, (0, 0, 100, 100), {"_cut": ct2})
    assert x < 30                                                           # 콘티는 오른쪽이지만 실제로 왼쪽
    assert "span" not in ct["_roles"][0][0]                                 # 원본 안 바뀜
    assert W._with_real_spans(ct, {}) is ct


def test_smart_at_prefers_speaker_side():
    """near_x 가 없으면 예전처럼"""
    import nk_webtoon as W
    from PIL import Image
    st = {"_edges": Image.new("L", (400, 300), 0), "_occupied": []}
    x_r, _ = W._smart_at(80, 40, (0, 0, 400, 300), "top", st, near_x=350)
    st["_occupied"] = []
    x_l, _ = W._smart_at(80, 40, (0, 0, 400, 300), "top", st, near_x=40)
    assert x_r + 40 > 250 and x_l + 40 < 150
