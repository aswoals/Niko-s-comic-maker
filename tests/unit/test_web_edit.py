# -*- coding: utf-8 -*-
"""작업실 컷 카드 고치기: 대사 고치기(nk_lines + /api/lines), 문장·show 고치기(쪽지 -> nk ep fix --edit-file),
실제로 쓴 글 보기(animamake.json / regionlora.json) — 가짜 키트 폴더, 그림·네트워크 없음"""
import argparse, json, os, types
import pytest
import nk
import nk_web as W
import nk_lines

CONTI = """# 콘티 머리 주석 (지우면 안 됨)
title: 시험
format: page
pages:
- cuts:
  - id: 1
    scene: tree
    text:
    - {type: narration, text: "맑은 날."}   # 해설
  - id: 2
    scene: duo
    text:
    - {type: speech, who: hero, text: 안녕!}
    - {type: speech, who: buddy, text: '반가워'}
"""

PLAN = """# 계획표 주석
title: 시험
cast: {hero: testcat, buddy: testgoat}
pages:
  - cuts:
      - who: []
        action: "tree"
        lines:
          - {kind: narration, text: "맑은 날."}
      - who: [hero, buddy]
        action: "smile"
        scene: "A fox and a rabbit wave at each other."
        show: ["a red ball"]
        lines:
          - {who: hero, text: "안녕!"}
          - {who: buddy, text: "반가워"}
"""


def _ep(root, name="e1", conti=CONTI, plan=PLAN):
    d = os.path.join(str(root), "episodes", name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "conti.yaml"), "w", encoding="utf-8").write(conti)
    if plan is not None:
        open(os.path.join(d, "plan.yaml"), "w", encoding="utf-8").write(plan)
    return d


def _read(p):
    return open(p, encoding="utf-8").read()


# ---------------------------------------------------------------- nk_lines (대사 고치기)
def test_lines_save_changes_only_that_text_and_backs_up(tmp_path):
    d = _ep(tmp_path)
    r = nk_lines.save(d, 2, [{"i": 1, "old": "반가워", "text": "또 보자"}])
    assert r["changed"] == 1 and "그 글자만" in r["conti"] and "그 글자만" in r["plan"]
    c, p = _read(os.path.join(d, "conti.yaml")), _read(os.path.join(d, "plan.yaml"))
    assert "# 콘티 머리 주석" in c and "# 해설" in c and "# 계획표 주석" in p      # 주석·모양은 그대로
    assert '"또 보자"' in c and "반가워" not in c and '"또 보자"' in p and "반가워" not in p
    assert c.replace('"또 보자"', "'반가워'") == CONTI                              # 바뀐 곳은 그 글자뿐
    bak = os.path.join(d, "_lines_bak", r["backup"])
    assert _read(os.path.join(bak, "conti.yaml")) == CONTI and _read(os.path.join(bak, "plan.yaml")) == PLAN
    log = [json.loads(x) for x in _read(os.path.join(d, "_lines_bak", "log.jsonl")).splitlines()]
    assert log[-1]["cut"] == 2 and log[-1]["edits"][0]["old"] == "반가워" and log[-1]["edits"][0]["new"] == "또 보자"


def test_lines_save_stale_and_bad_input_change_nothing(tmp_path):
    d = _ep(tmp_path)
    with pytest.raises(ValueError, match="화면이 낡았어요"):
        nk_lines.save(d, 2, [{"i": 0, "old": "옛 글", "text": "새 글"}])
    with pytest.raises(ValueError, match="너무 길어요"):
        nk_lines.save(d, 2, [{"i": 0, "old": "안녕!", "text": "가" * (nk_lines.MAX_LEN + 1)}])
    with pytest.raises(ValueError, match="빈 칸"):
        nk_lines.save(d, 2, [{"i": 0, "old": "안녕!", "text": "   "}])
    with pytest.raises(ValueError, match="줄 번호"):
        nk_lines.save(d, 2, [{"i": 9, "old": "", "text": "x"}])
    with pytest.raises(ValueError, match="없어요"):
        nk_lines.save(d, 7, [{"i": 0, "old": "", "text": "x"}])
    assert _read(os.path.join(d, "conti.yaml")) == CONTI and not os.path.exists(os.path.join(d, "_lines_bak"))
    assert nk_lines.save(d, 2, [{"i": 0, "old": "안녕!", "text": "안녕!"}])["changed"] == 0    # 그대로면 아무것도 안 함


def test_lines_save_restores_when_write_fails(tmp_path, monkeypatch):
    d = _ep(tmp_path)
    real = nk_lines._atomic_write

    def boom(path, text, bom):
        if path.endswith("plan.yaml"):
            raise OSError("디스크 오류 흉내")
        return real(path, text, bom)
    monkeypatch.setattr(nk_lines, "_atomic_write", boom)
    with pytest.raises(ValueError, match="저장 중 오류"):
        nk_lines.save(d, 1, [{"i": 0, "old": "맑은 날.", "text": "흐린 날."}])
    assert _read(os.path.join(d, "conti.yaml")) == CONTI and _read(os.path.join(d, "plan.yaml")) == PLAN    # 먼저 쓴 콘티도 되돌림


def test_lines_save_plan_mismatch_changes_conti_only(tmp_path):
    d = _ep(tmp_path, plan=PLAN.replace('"반가워"', '"다른 글"'))
    r = nk_lines.save(d, 2, [{"i": 1, "old": "반가워", "text": "또 보자"}])
    assert r["changed"] == 1 and "못 맞춤" in r["plan"]
    assert "또 보자" in _read(os.path.join(d, "conti.yaml")) and "또 보자" not in _read(os.path.join(d, "plan.yaml"))


def test_lines_items_of():
    ct = {"text": [{"type": "speech", "who": "hero", "text": "안녕"}, "깨진 줄", {"type": "sfx", "text": "쾅"}]}
    assert nk_lines.items_of(ct) == [{"i": 0, "type": "speech", "type_ko": "대사", "who": "hero", "text": "안녕"},
                                     {"i": 2, "type": "sfx", "type_ko": "효과음", "who": "", "text": "쾅"}]
    assert nk_lines.items_of({}) == [] and W._lines_items(None) == []


# ---------------------------------------------------------------- 작업실 App
@pytest.fixture
def app(tmp_path, monkeypatch):
    kit = tmp_path / "kit"; kit.mkdir()
    cfg = tmp_path / "workshop.json"; cfg.write_text(json.dumps({"folders": []}), encoding="utf-8")
    monkeypatch.setattr(W, "CFG_PATH", str(cfg))
    a = W.App(nk, str(kit))
    _ep(kit)
    return a


def test_api_lines_saves_and_queues_letter(app):
    r = app.lines_save({"root": "0", "ep": "e1", "cut": 2, "letter": True, "edits": [{"i": 0, "old": "안녕!", "text": "안녕하세요!"}]})
    assert r["changed"] == 1 and r["job"].endswith("_letter_e1.json")
    job = json.load(open(os.path.join(app.inbox, r["job"]), encoding="utf-8"))
    assert job["args"] == ["ep", "letter", "e1"]
    with pytest.raises(ValueError):
        app.lines_save({"root": "0", "ep": "../x", "cut": 2, "edits": [{"i": 0}]})
    with pytest.raises(ValueError):
        app.lines_save({"root": "0", "ep": "e1", "cut": 2, "edits": []})


def test_api_lines_refuses_while_that_comic_is_running(app):
    app.worker = types.SimpleNamespace(cur="j1")
    open(os.path.join(app.logs, "j1.log"), "w", encoding="utf-8").write("# nk ep auto e1\n")
    with pytest.raises(ValueError, match="도는 중"):
        app.lines_save({"root": "0", "ep": "e1", "cut": 2, "edits": [{"i": 0, "old": "안녕!", "text": "x"}]})
    open(os.path.join(app.logs, "j1.log"), "w", encoding="utf-8").write("# nk ep auto other\n")
    assert app.lines_save({"root": "0", "ep": "e1", "cut": 2, "edits": [{"i": 0, "old": "안녕!", "text": "x"}]})["changed"] == 1


def test_fix_job_with_text_edit_writes_note(app):
    import nk_easy
    args, note, rid = app.make_job({"kind": "fix", "ep": "e1", "cut": 2,
                                    "edit": {"sentence": "  A fox  and a rabbit\nhug. ", "show": "a ball\n\n  a tree "}})
    assert args[:4] == ["ep", "fix", "e1", "2"] and args[4] == "--edit-file" and "문장 고치기" in note
    assert nk_easy.EDIT_FILE_RE.match(args[5])
    pay = json.load(open(os.path.join(app.ep_dir("e1"), args[5]), encoding="utf-8"))
    assert pay == {"sentence": "A fox and a rabbit hug.", "show": ["a ball", "a tree"]}
    args2, note2, _ = app.make_job({"kind": "fix", "ep": "e1", "cut": 2})
    assert "--edit-file" not in args2 and "다시 그리기" in note2
    with pytest.raises(ValueError, match="너무 길어요"):
        app.make_job({"kind": "fix", "ep": "e1", "cut": 2, "edit": {"sentence": "x" * (app.SENTENCE_MAX + 1)}})


def test_episode_cut_has_lines_sentence_show_and_used(app):
    d = app.ep_dir("e1")
    json.dump({"2": {"text": "SOLO TEXT", "negative": "NEG", "seed": 502, "time": "2030-01-01 10:00:00",
                     "settings": {"_regions": [["up_a.png", "REGION A"], ["up_b.png", "REGION B"]]}}},
              open(os.path.join(d, "animamake.json"), "w", encoding="utf-8"))
    cuts = {c["id"]: c for c in app.episode("e1")["cuts"]}
    c2 = cuts[2]
    assert [x["text"] for x in c2["items"]] == ["안녕!", "반가워"]
    assert c2["tags"]["sentence"] == "A fox and a rabbit wave at each other." and c2["tags"]["sentence_key"] == "scene"
    assert c2["tags"]["show"] == ["a red ball"]
    assert c2["used"] == [["글", "SOLO TEXT"], ["사람 A 자리 글", "REGION A"], ["사람 B 자리 글", "REGION B"],
                          ["빼는 글 (negative)", "NEG"], ["시드", "502"]]
    assert cuts[1]["used"] == [] and cuts[1]["tags"]["sentence_key"] == "sentence"


def test_used_prompt_takes_latest_record():
    am = {"3": {"text": "OLD ONE-SHOT", "time": "2030-01-01 10:00:00", "seed": 1}}
    rl = {"cut03": {"text": "BASE", "lora_text": "LORA PLACE", "seed": 7, "time": "2030-01-02 09:00:00"}}
    assert W.used_prompt(3, am, rl) == [["글 (전체)", "BASE"], ["LoRA 캐릭터 자리 글", "LORA PLACE"], ["시드", "7"]]
    am["3"]["time"] = "2030-01-03 00:00:00"
    assert W.used_prompt(3, am, rl)[0] == ["글", "OLD ONE-SHOT"]
    assert W.used_prompt(4, am, rl) == [] and W.used_prompt("x", am, rl) == []


# ---------------------------------------------------------------- nk_easy (문장 쪽지 -> 계획표)
def test_apply_text_edit_scene_or_sentence():
    import nk_easy
    pc = {"scene": "Old scene.", "show": "a | b"}
    assert nk_easy._apply_text_edit(pc, {"sentence": "New scene.", "show": ["a", "b"]}) == ["scene"]
    assert pc == {"scene": "New scene.", "show": "a | b"}                     # show 는 같은 내용 -> 안 바꿈
    pc = {"sentence": "Old."}
    assert nk_easy._apply_text_edit(pc, {"sentence": "New.", "show": ["x"]}) == ["sentence", "show"]
    assert pc == {"sentence": "New.", "show": ["x"]}
    assert nk_easy._apply_text_edit(pc, {"sentence": "", "show": []}) == ["sentence", "show"] and pc == {}


def test_load_edit_moves_note(tmp_path):
    import nk_easy
    fn = "cutedit_02_1106120000123.json"
    json.dump({"sentence": " A  cat ", "show": ["x", " "]}, open(tmp_path / fn, "w", encoding="utf-8"))
    e = nk_easy._load_edit(argparse.Namespace(edit_file=fn), str(tmp_path))
    assert e == {"sentence": "A cat", "show": ["x"]}
    assert not (tmp_path / fn).exists() and (tmp_path / "_cutedit_done" / fn).exists()
    assert nk_easy._load_edit(argparse.Namespace(edit_file=None), str(tmp_path)) is None
    with pytest.raises(SystemExit):
        nk_easy._load_edit(argparse.Namespace(edit_file="../plan.yaml"), str(tmp_path))


def _fix_ns(**k):
    base = dict(ep="e1", cut=2, add=None, remove=None, who=None, loc=False, edit_file=None, nodraw=False)
    base.update(k)
    return argparse.Namespace(**base)


def test_run_fix_text_edit_updates_plan_and_reseeds(tmp_path, monkeypatch):
    import nk_easy, nk_plan, nk_auto, nk_animacut
    import nk_webtoon as Wt
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    d = _ep(tmp_path)
    compiled, runs = [], []
    monkeypatch.setattr(nk_plan, "run_compile", lambda nk_, kit, a: compiled.append(a.ep))
    monkeypatch.setattr(Wt, "load_conti", lambda nk_, kit, ep: {"cuts": [{"id": 1}, {"id": 2}]})
    monkeypatch.setattr(nk_auto, "_compose_cuts", lambda *a, **k: [])
    monkeypatch.setattr(nk_auto, "run", lambda nk_, kit, a: runs.append(a.start))
    fn = "cutedit_02_1106120000001.json"
    json.dump({"sentence": "A fox and a rabbit hug.", "show": ["a red ball", "a tree"]}, open(os.path.join(d, fn), "w", encoding="utf-8"))
    nk_easy.run_fix(nk, str(tmp_path), _fix_ns(edit_file=fn))
    plan = nk_plan._extract_yaml(_read(os.path.join(d, "plan.yaml")))[0]
    pc = plan["pages"][0]["cuts"][1]
    assert pc["scene"] == "A fox and a rabbit hug." and pc["show"] == ["a red ball", "a tree"]
    assert compiled == ["e1"] and runs == ["make"]
    assert nk_animacut.reseed_count("e1", 2) == 1                        # 문장을 고치면 새 시드
    nk_easy.run_fix(nk, str(tmp_path), _fix_ns(add="rain"))
    assert nk_animacut.reseed_count("e1", 2) == 1                        # 태그만 고치면 시드 그대로 (예전과 같음)


def test_run_fix_text_edit_reverts_plan_when_compile_fails(tmp_path, monkeypatch):
    import nk_easy, nk_plan
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    d = _ep(tmp_path)

    def bad_compile(nk_, kit, a):
        raise SystemExit(1)
    monkeypatch.setattr(nk_plan, "run_compile", bad_compile)
    fn = "cutedit_02_1106120000002.json"
    json.dump({"sentence": "Broken."}, open(os.path.join(d, fn), "w", encoding="utf-8"))
    with pytest.raises(SystemExit):
        nk_easy.run_fix(nk, str(tmp_path), _fix_ns(edit_file=fn))
    assert _read(os.path.join(d, "plan.yaml")) == PLAN


def test_page_has_edit_buttons():
    page = W.PAGE
    for s in ("대사 고치기", "저장만", "저장하고 말풍선 다시", "태그·문장 고치기", "/api/lines", "실제로 쓴 글", "data-sen=", "data-show="):
        assert s in page
    assert ">태그 고치기</button>" not in page
