# -*- coding: utf-8 -*-
"""전연령 안전장치: ComfyUI 로 가는 그래프의 긍정 글에서 성인·잔혹 단어를 지우고, 부정 글에는 nsfw 막는 말을 넣는다"""
import argparse
import nk


def test_safe_text_removes_blocked_words():
    assert nk.safe_text("masterpiece, nsfw, 1boy, nude, smile") == "masterpiece, 1boy, smile"
    assert "naked" not in nk.safe_text("A naked cat boy sits on a bench.").lower()
    assert nk.safe_text("1girl, park, sunny") == "1girl, park, sunny"           # 멀쩡한 글은 그대로


def test_safe_graph_pos_and_neg():
    g = {"5": {"class_type": "CLIPTextEncode", "inputs": {"text": "best quality, explicit, cat boy, gore"}},
         "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "worst quality"}},
         "7": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "Make him topless"}},
         "3": {"class_type": "KSampler", "inputs": {"positive": ["5", 0], "negative": ["6", 0]}}}
    nk.safe_graph(g)
    pos, neg = g["5"]["inputs"]["text"], g["6"]["inputs"]["text"]
    assert "explicit" not in pos and "gore" not in pos and "cat boy" in pos
    assert neg.startswith(nk.SAFE_NEG) and "worst quality" in neg
    assert "topless" not in g["7"]["inputs"]["prompt"].lower()


def test_queue_always_runs_the_guard(monkeypatch):
    sent = {}
    c = nk.Comfy.__new__(nk.Comfy)
    c.client_id = "t"
    monkeypatch.setattr(c, "_resolve_files", lambda g: None, raising=False)
    monkeypatch.setattr(c, "_post", lambda path, data: sent.setdefault("g", data["prompt"]) and {"prompt_id": "x"} or {"prompt_id": "x"}, raising=False)
    g = {"5": {"class_type": "CLIPTextEncode", "inputs": {"text": "nsfw, cat"}}}
    c.queue(g, raw=True)
    assert sent["g"]["5"]["inputs"]["text"] == "cat"


def test_prompt_is_always_safe():
    s = {"quality": "off", "rating": "explicit", "negative": "lowres"}
    pos, neg = nk.compose_prompt(s, None, "park")
    assert "safe" in pos and "nsfw" not in pos and "explicit" not in pos
    assert "nsfw" in neg and "explicit" in neg


def test_rating_option_is_safe_only():
    import nk as m
    ap = argparse.ArgumentParser()
    m.add_common(ap)
    act = next(a for a in ap._actions if "--rating" in a.option_strings)
    assert list(act.choices) == ["safe"]
