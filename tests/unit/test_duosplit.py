# -*- coding: utf-8 -*-
"""nk_duosplit (LoRA 없는 두 명 컷 나눠 그리기): 설정·끄기, 두 사람 조각 고르기, 구역 틀, 구역 글, 그림 틀, 컷 하나 흐름(가짜 ComfyUI·SAM3),
결과 저장, nk_auto 길 나누기. GPU·네트워크 없음"""
import os, json, shutil, argparse, types
import numpy as np
import pytest
import yaml
from PIL import Image

import nk
import nk_duosplit as D
import nk_regionlora as RL
import nk_animacut as A
import nk_animatest as T
import nk_webtoon as W

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHARS = os.path.join(KIT, "tests", "fixtures", "characters")


def _box(x0, y0, x1, y1, w=100, h=100):
    a = np.zeros((h, w), bool)
    a[y0:y1, x0:x1] = True
    return a


def _char(name):
    ch = yaml.safe_load(open(os.path.join(CHARS, name + ".yaml"), encoding="utf-8"))
    ch["_key"] = name
    return ch


def _duo_cut(scene="duo, 1boy, 1girl, looking at another, holding hands", shot="full"):
    return {"id": 4, "scene": scene, "shot": shot,
            "_roles": [({"char": "hero", "side": "right", "pos": "grin, standing"}, _char("testknight")),
                       ({"char": "buddy", "side": "left", "pos": "smile, standing"}, _char("testgoat"))]}


# ---------------------------------------------------------------- 설정·끄기
def test_settings_missing_file_gives_defaults(tmp_path):
    assert D.load_settings(str(tmp_path)) == D.DEFAULTS


def test_shipped_settings_file_reads_without_warning():
    logs = []
    S = D.load_settings(KIT, logs.append)
    assert not logs and S == D.DEFAULTS            # 저장소의 duosplit_settings.yaml = 처음 값


def test_settings_values_and_bad_values(tmp_path):
    p = tmp_path / D.SETTINGS_FILE
    p.write_text("enabled: true\nmin_region: 0.02\nsteps: 30\nbase_only: 8\ncfg: 4\noverlap: 16\n", encoding="utf-8")
    S = D.load_settings(str(tmp_path))
    assert (S["min_region"], S["steps"], S["base_only"], S["cfg"], S["overlap"]) == (0.02, 30, 8, 4.0, 16)
    for bad in ("min_region: 0.9\n", "base_only: 12.5\n", "steps: abc\n", "cfg: true\n", "- just a list\n"):
        p.write_text(bad, encoding="utf-8")
        logs = []
        assert D.load_settings(str(tmp_path), logs.append) == D.DEFAULTS
        assert logs and "[WARN]" in logs[0]


def test_enabled_switches(tmp_path):
    kit = str(tmp_path)
    assert D.enabled(kit, {}, None) == (True, "")
    assert D.enabled(kit, {"duo_split": "off"}, None)[0] is False
    plan = tmp_path / "plan.yaml"
    plan.write_text("title: t\nduo_split: false\n", encoding="utf-8")
    assert D.enabled(kit, {}, str(plan))[0] is False
    assert D.enabled(kit, {"duo_split": True}, str(plan))[0] is True      # 콘티가 계획표보다 먼저
    (tmp_path / D.SETTINGS_FILE).write_text("enabled: false\n", encoding="utf-8")
    on, why = D.enabled(kit, {}, None)
    assert on is False and "enabled: false" in why


def test_missing_nodes():
    class C:
        def _get(self, path):
            n = path.rsplit("/", 1)[1]
            if n == "SAM3_Detect":
                raise OSError("down")
            return {} if n == "RegionalSampler" else {n: {}}
    assert D.missing_nodes(C()) == ["RegionalSampler", "SAM3_Detect"]


def test_cut_kinds():
    c = _duo_cut()
    assert D.is_duo(c) and not D.has_lora(c)
    c["_roles"][0] = (c["_roles"][0][0], _char("testcat"))
    assert D.has_lora(c)
    assert not D.is_duo({"_roles": [({"char": "a"}, _char("testgoat")), ({"char": "b"}, None)]})


# ---------------------------------------------------------------- 조각 고르기·구역 틀
def test_pick_side_piece():
    left, right = _box(5, 0, 35, 100), _box(60, 0, 90, 100)
    pm, info = D.pick_side_piece([left, right], "right")
    assert pm is right and info["index"] == 1 and info["cx"] > 0.5
    pm, info = D.pick_side_piece([_box(60, 0, 61, 10), _box(0, 0, 100, 100)], "right")    # 너무 작음·너무 큼
    assert pm is None and info["why"] == "no piece on that side"
    assert D.pick_side_piece([left], "middle")[1]["why"] == "no side"


def test_find_two_skips_same_figure_and_swallowing_piece():
    a_piece, b_piece = _box(55, 0, 85, 100), _box(5, 0, 35, 100)
    both = _box(20, 0, 80, 100)                          # 두 사람을 한 덩어리로 잡은 조각 (왼쪽에 중심, B 보다 큼)
    pieces = {"girl": [a_piece], "boy": [a_piece.copy(), both, b_piece]}
    ma, mb, info = D.find_two(lambda w: pieces.get(w, []), ["girl"], ["boy"], "right", "left", RL, log=lambda *a: None)
    assert info["ok"] and ma is a_piece and mb is b_piece and info["iou"] == 0.0
    ma, mb, info = D.find_two(lambda w: [], ["girl", "person"], ["boy"], "right", "left", RL, log=lambda *a: None)
    assert ma is None and not info["ok"] and info["why"].startswith("A not found")


def test_region_masks_remove_overlap_and_min_region():
    ma, mb = _box(30, 0, 60, 100), _box(50, 0, 80, 100)
    ga, gb, info = D.region_masks(ma, mb, 0.03, 0.08)
    assert info["ok"] and not (ga & gb).any() and not (ga & mb).any() and not (gb & ma).any()
    assert info["cover_A"] >= 0.08 and info["cover_B"] >= 0.08
    ga, gb, info = D.region_masks(_box(0, 0, 40, 100), _box(60, 0, 63, 10), 0.03, 0.08)
    assert not info["ok"] and info["why"].startswith("region too small")


def test_span():
    assert D.span(_box(20, 0, 41, 10)) == [0.22, 0.38]
    assert D.span(np.zeros((5, 5), bool)) is None


# ---------------------------------------------------------------- 글·부정어·그림 틀
def test_region_text():
    cut = _duo_cut()
    conti = {"anima_tags": "flat color"}
    (ra, ka), (rb, gb) = cut["_roles"]
    ta = D.region_text(A, W, conti, cut, ka, ra, "someartist", look=True)
    tb = D.region_text(A, W, conti, cut, gb, rb, "", look=False)
    assert ta.startswith("masterpiece, best quality, score_7, safe, @someartist, flat color, 1girl")
    assert "testknight" in ta and "holding hands" in ta and "grin, standing" in ta and "1boy" not in ta
    assert ta.count("looking at another") == 1 and "duo" not in ta.split(". ")[0].split(", ")
    assert ta.endswith("silver armor and a blue cape.") and ".." not in ta
    assert "1boy, furry, anthro" in tb and "smile, standing" in tb and "1girl" not in tb
    assert "testknight" not in D.region_text(A, W, {"char_tags": False}, cut, ka, ra, "")


def test_cut_neg_follows_one_pass_rules():
    cut = _duo_cut(scene="duo, 1boy, 1girl, pulling")
    neg = D.cut_neg(A, {"anima_neg": "bokeh"}, cut)
    assert neg.startswith(A.NEG) and "bokeh" in neg and "tail pull" in neg and "looking at viewer" in neg


def test_duo_graph_is_safe_and_takes_controls():
    p = {"unet": "anima-base-v1.0.safetensors", "steps": 25, "cfg": 5.0, "base_only": 12, "overlap": 10}
    g = D.duo_graph(T, p, "base text", "text a", "text b", "worst quality", "ma.png", "mb.png", 1344, 768, 504, RL.SAMPLER, RL.SCHED)
    assert g["49"]["inputs"]["base_only_steps"] == 12 and g["49"]["inputs"]["steps"] == 25 and g["49"]["inputs"]["seed"] == 504
    assert g["47"]["inputs"] == {"regional_prompts1": ["46", 0], "regional_prompts2": ["54", 0]}
    nk.safe_graph(g)
    assert g["6"]["inputs"]["text"].startswith(nk.SAFE_NEG)                   # 부정어 노드로 알아봄
    assert g["5"]["inputs"]["text"] == "base text" and g["7"]["inputs"]["text"] == "text a"
    ctl = {"lllite": "x.safetensors", "lllite_strength": 0.45, "lllite_end": 0.45, "_control_up": "d.png"}
    g = RL.apply_control(g, ctl)
    assert all(g[k]["inputs"]["model"] == ["14c", 0] for k in ("40", "41", "50"))


# ---------------------------------------------------------------- 컷 하나 (가짜 ComfyUI·SAM3)
class FakeComfy:
    def __init__(self, fail_regional=False):
        self.graphs, self.fail_regional = [], fail_regional

    def queue(self, g):
        self.graphs.append(g)
        return str(len(self.graphs))

    def wait(self, pid, label=""):
        if self.fail_regional and any(n.get("class_type") == "RegionalSampler" for n in self.graphs[int(pid) - 1].values()):
            raise SystemExit(1)
        return {"10": {"images": [{"filename": pid}]}}

    def fetch(self, img, dest):
        Image.new("RGB", (100, 60), (200, 180, int(img["filename"]) * 20 % 255)).save(dest)


def _env(tmp_path, pieces, c_):
    def segment(nk_, kit, cfg, to, items, thr, run="", individual=False):
        (tag, bp, prompt), = items
        out = []
        for i, m in enumerate(pieces.get(prompt.split(":")[0], [])):
            f = tmp_path / ("%s_%s_%d.png" % (tag, prompt.replace(":", "-"), i))
            Image.fromarray((m * 255).astype(np.uint8)).save(f)
            out.append(str(f))
        return {(tag, prompt): out}
    Wf = types.SimpleNamespace(head_tags=W.head_tags, _upload_input=lambda nk_, cfg, p, name, dry=False: name)
    return {"nk": nk, "kit": KIT, "cfg": {}, "conti": {}, "c_": c_, "W": Wf, "A": A, "T": T, "RL": RL,
            "SAM": types.SimpleNamespace(segment=segment), "S": dict(D.DEFAULTS)}


P = {"unet": "anima-base-v1.0.safetensors", "steps": 25, "cfg": 5.0, "base_only": 12, "overlap": 10}
TWO = {"girl": [_box(5, 0, 35, 60), _box(60, 0, 90, 60)], "boy": [_box(5, 0, 35, 60), _box(60, 0, 90, 60)]}


def _one(tmp_path, pieces, c_, text="base text"):
    return D.split_one(_env(tmp_path, pieces, c_), _duo_cut(), text, "neg", 100, 60, 504, "cut04_s504", str(tmp_path / "work"), "ep",
                       dict(P), "", {}, log=lambda *a: None, label="cut04")


def test_split_one_success(tmp_path):
    c_ = FakeComfy()
    r = _one(tmp_path, TWO, c_)
    assert r["ok"] and os.path.exists(r["final"]) and os.path.exists(r["base"])
    assert r["spans"]["hero"][0] > 0.5 and r["spans"]["buddy"][1] < 0.5          # hero = right, buddy = left
    assert r["texts"]["A"].startswith("masterpiece") and r["masks"]["ok"]
    kinds = [sorted(n["class_type"] for n in g.values()) for g in c_.graphs]
    assert len(c_.graphs) == 2 and "KSampler" in kinds[0] and "RegionalSampler" in kinds[1]
    assert c_.graphs[0]["8"]["inputs"]["sampler_name"] == RL.SAMPLER and c_.graphs[0]["8"]["inputs"]["scheduler"] == RL.SCHED
    _one(tmp_path, TWO, c_)                                                   # 같은 글·시드 = 기준 그림 다시 씀
    assert len(c_.graphs) == 3
    _one(tmp_path, TWO, c_, text="changed text")                              # 글이 바뀌면 기준 그림도 새로
    assert len(c_.graphs) == 5


def test_split_one_falls_back_to_base(tmp_path):
    r = _one(tmp_path, {"girl": [_box(60, 0, 90, 60)]}, FakeComfy())          # 한 사람만 찾음
    assert not r["ok"] and r["base"] and r["final"] is None and r["why"].startswith("나누기 실패")
    r = _one(tmp_path, TWO, FakeComfy(fail_regional=True))                     # 나눠 그리기 작업 실패
    assert not r["ok"] and os.path.exists(r["base"]) and "ComfyUI" in r["why"]


def test_save_result(tmp_path):
    ed = tmp_path / "ep"
    base, split = tmp_path / "b.png", tmp_path / "s.png"
    Image.new("RGB", (8, 8), (1, 1, 1)).save(base)
    Image.new("RGB", (8, 8), (9, 9, 9)).save(split)
    dst = str(ed / "cuts" / "cut04.png")
    rec, rl = {}, {"cut04": {"spans": {"old": [0, 1]}}}
    ok = D.save_result(str(ed), 4, dst, {"ok": True, "base": str(base), "final": str(split), "spans": {"hero": [0.6, 0.8]}}, rec, rl, {"text": "t"})
    assert ok and Image.open(dst).getpixel((0, 0)) == (9, 9, 9) and os.path.exists(ed / "cuts_base" / "cut04.png")
    assert rl["cut04"]["spans"] == {"hero": [0.6, 0.8]} and rl["cut04"]["duosplit"] is True and rec["4"]["split_ok"] and rec["4"]["text"] == "t"
    ok = D.save_result(str(ed), 4, dst, {"ok": False, "base": str(base), "final": None, "why": "x"}, rec, rl)
    assert not ok and Image.open(dst).getpixel((0, 0)) == (1, 1, 1) and "cut04" not in rl
    assert len(os.listdir(ed / "_alt")) >= 1 and rec["4"]["why"] == "x"


# ---------------------------------------------------------------- 콘티 전체 (그리지 않음)
@pytest.fixture
def ep(tmp_path, monkeypatch):
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    d = tmp_path / "episodes" / "selftest01"
    shutil.copytree(os.path.join(KIT, "tests", "fixtures", "selftest01"), d)

    def compile_(nolora):
        import nk_plan
        pp = d / "plan.yaml"
        if nolora:
            pp.write_text(pp.read_text(encoding="utf-8").replace("hero: testcat", "hero: testknight"), encoding="utf-8")
        nk_plan.run_compile(nk, KIT, argparse.Namespace(ep="selftest01", dry=False, plan=None))
    return compile_


def test_run_dry_prints_both_region_texts(ep, capsys):
    ep(True)
    out = D.run(nk, KIT, argparse.Namespace(ep="selftest01", cuts=[], seed="500", force=False, dry=True))
    txt = capsys.readouterr().out
    assert "regionlora selftest01 -> selftest01: 1 cuts" in txt and "== duo-split cut 4" in txt
    assert "[A hero] masterpiece" in txt and "[B buddy] masterpiece" in txt and out["made"] == 0


def test_run_skips_lora_cuts(ep, capsys):
    ep(False)
    D.run(nk, KIT, argparse.Namespace(ep="selftest01", cuts=[], seed="500", force=False, dry=True))
    assert "[skip] cut 4: LoRA character" in capsys.readouterr().out


# ---------------------------------------------------------------- nk_auto 길 나누기
def _auto(tmp_path, monkeypatch, cast_hero="testknight", settings=None, one_pass=False):
    import nk_auto
    calls = {}
    monkeypatch.setattr(A, "run", lambda nk_, kit, a: calls.setdefault("animamake", []).extend(int(x) for x in a.cuts))
    monkeypatch.setattr(RL, "run", lambda nk_, kit, a: calls.setdefault("regionlora", []).extend(int(x) for x in a.cuts))

    def ds(nk_, kit, a):
        calls.setdefault("duosplit", []).extend(int(x) for x in a.cuts)
        return {"one_pass": [int(x) for x in a.cuts]} if one_pass else {"made": len(a.cuts), "split": len(a.cuts), "base_kept": []}
    monkeypatch.setattr(D, "run", ds)
    if settings:
        (tmp_path / D.SETTINGS_FILE).write_text(settings, encoding="utf-8")
    hero, goat = _char(cast_hero), _char("testgoat")
    conti = {"_cast": {"hero": hero, "buddy": goat},
             "cuts": [{"id": 1, "_charkey": None}, {"id": 2, "_charkey": "hero"},
                      {"id": 3, "cast": [{"char": "hero"}, {"char": "buddy"}], "_roles": [({"char": "hero"}, hero), ({"char": "buddy"}, goat)]}]}
    Wf = types.SimpleNamespace(ep_dir=lambda kit, e: str(tmp_path / "ep"), find_word=lambda ch: "x",
                               _final_file=lambda kit, e, i: str(tmp_path / "ep" / "cuts" / ("cut%02d.png" % i)))
    rec = {}
    rc = nk_auto.step_make_anima(nk, str(tmp_path), Wf, argparse.Namespace(ep="t", dry=True), conti, rec)
    return rc, calls, rec["notes"]


def test_auto_no_lora_duo_goes_to_duosplit(tmp_path, monkeypatch):
    rc, calls, notes = _auto(tmp_path, monkeypatch)
    assert rc == 0 and calls == {"animamake": [1, 2], "duosplit": [3]}
    assert any("duosplit (no-LoRA" in n for n in notes)


def test_auto_lora_duo_still_goes_to_regionlora(tmp_path, monkeypatch):
    rc, calls, _ = _auto(tmp_path, monkeypatch, cast_hero="testcat")
    assert calls == {"animamake": [1, 2], "regionlora": [3]}


def test_auto_duosplit_off_draws_in_one_pass(tmp_path, monkeypatch):
    rc, calls, notes = _auto(tmp_path, monkeypatch, settings="enabled: false\n")
    assert calls == {"animamake": [1, 2, 3]} and any("duosplit off" in n for n in notes)


def test_auto_note_when_impact_pack_missing(tmp_path, monkeypatch):
    rc, calls, notes = _auto(tmp_path, monkeypatch, one_pass=True)
    assert rc == 0 and calls["duosplit"] == [3] and any("no Impact Pack" in n for n in notes)


# ---------------------------------------------------------------- 작업실 진행 표시와 맞나 (nk_web 이 읽는 줄 꼴)
def test_log_lines_match_workshop_progress(tmp_path):
    import nk_web
    logs = tmp_path / "logs"; logs.mkdir()
    (logs / "j.log").write_text("\n".join([
        "# nk ep auto e1", "==== [make] 10:00",
        "regionlora e1 -> e1: 1 cuts | euler sgm_uniform steps 25 cfg 5.0 base_only 12 overlap 10 | no LoRA (duo split, nk_duosplit)",
        "   ... cut02 base 10s", "cut02: mask by 'girl' + 'boy' (right side + left side)", "   ... cut02 20s",
        "cut02 -> /x/episodes/e1/cuts/cut02.png (90 s, duo split)", "==== [make] done (95s, rc 0)"]), encoding="utf-8")
    app = types.SimpleNamespace(logs=str(logs), PART=nk_web.App.PART, SEC_COMPILE=5, ep_dir=lambda ep, rid: str(tmp_path / ep),
                                cut_kinds=lambda ep, rid: [(1, "other"), (2, "duo")], _face_on=lambda plan: False,
                                nk=types.SimpleNamespace(load_yaml=lambda p: {"title": "t"}))
    d = nk_web.App.detail(app, "j")
    st = {c["id"]: c["stage"] for c in d["cuts"]}
    assert st[2] == "done"
