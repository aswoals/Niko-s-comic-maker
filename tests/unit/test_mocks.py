# -*- coding: utf-8 -*-
"""가짜 서버 자체 시험 — 가짜가 틀리면 selftest 결과도 믿을 수 없으므로"""
import os, json, argparse, urllib.request

import mock_ollama, mock_comfy


def test_ollama_parses_nk_qa_prompt_pass_and_fail():
    prompt = ('Questions:\n'
              '  "scarf": What is around the neck?  Options: a red plaid scarf around the neck | a blue tie | nothing\n'
              '  "solo": Is there one character?  (answer true or false)\n')
    exp = {"scarf": ["red plaid scarf"]}
    a, qs = mock_ollama.answer(prompt, "pass", exp)
    assert a == {"scarf": "a red plaid scarf around the neck", "solo": True}
    b, _ = mock_ollama.answer(prompt, "fail", exp)
    assert b["scarf"] in ("a blue tie", "nothing") and b["solo"] is False


def test_ollama_parses_one_of_questions():
    import nk_facefix
    a, qs = mock_ollama.answer(nk_facefix.BROKEN_Q, "pass", {})
    assert a == {"eyes": "two normal eyes", "face": "clean", "ears": "clean ears"}


def test_ollama_answer_goes_through_nk_parser():
    import nk
    prompt = '  "f1": The cat holds a ball\n  "f2": It is raining\n'
    a, _ = mock_ollama.answer(prompt, "pass", {})
    assert nk.parse_answers(json.dumps(a), ["f1", "f2"]) == {"f1": True, "f2": True}


def test_comfy_graph_size_follows_hires():
    import nk
    cfg = nk.load_presets()
    s = nk.build_settings(cfg, argparse.Namespace(preset=None, size="832x1216", hires=1.5))
    g = nk.build_graph(cfg, s, None, "1boy, solo", "bad", 1, 1, "nk/x")
    G = mock_comfy.Graph(g, {})
    save = [k for k, v in g.items() if v.get("class_type") == "SaveImage"][0]
    w, h = G.size(save)
    assert (w, h) in ((832, 1216), (1248, 1824))     # hires 가 켜진 그래프면 1.5배


def test_comfy_server_roundtrip(tmp_path):
    srv, st = mock_comfy.serve(0, str(tmp_path))
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        g = {"1": {"class_type": "EmptyLatentImage", "inputs": {"width": 320, "height": 200, "batch_size": 1}},
             "2": {"class_type": "KSampler", "inputs": {"seed": 5, "latent_image": ["1", 0]}},
             "3": {"class_type": "VAEDecode", "inputs": {"samples": ["2", 0]}},
             "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "nk/t/a"}}}
        req = urllib.request.Request(base + "/prompt", data=json.dumps({"prompt": g}).encode(),
                                     headers={"Content-Type": "application/json"})
        pid = json.loads(urllib.request.urlopen(req).read())["prompt_id"]
        h = json.loads(urllib.request.urlopen(base + "/history/" + pid).read())[pid]
        im = h["outputs"]["4"]["images"][0]
        data = urllib.request.urlopen(base + "/view?filename=%s&subfolder=%s&type=output" % (im["filename"], im["subfolder"])).read()
        from PIL import Image
        import io
        assert Image.open(io.BytesIO(data)).size == (320, 200)
        bad = {"1": {"class_type": "NoSuchNode", "inputs": {}}}
        req = urllib.request.Request(base + "/prompt", data=json.dumps({"prompt": bad}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            assert False, "unknown node must be rejected"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        oi = json.loads(urllib.request.urlopen(base + "/object_info/LoraLoader").read())
        assert "testcat_v1.safetensors" in oi["LoraLoader"]["input"]["required"]["lora_name"][0]
    finally:
        srv.shutdown()


def test_env_hook_server_addresses(monkeypatch):
    """nk.load_presets: 환경 변수가 있을 때만 서버 주소를 바꿈 (없으면 presets.yaml 그대로)"""
    import nk
    monkeypatch.delenv("NK_COMFY_SERVER", raising=False)
    monkeypatch.delenv("NK_OLLAMA", raising=False)
    base = nk.load_presets()
    assert base.get("server") == "auto"
    assert base["qa"]["ollama"] == "http://127.0.0.1:11434"
    monkeypatch.setenv("NK_COMFY_SERVER", "http://127.0.0.1:18188")
    monkeypatch.setenv("NK_OLLAMA", "http://127.0.0.1:18434")
    c = nk.load_presets()
    assert c["server"] == "http://127.0.0.1:18188" and c["qa"]["ollama"] == "http://127.0.0.1:18434"
