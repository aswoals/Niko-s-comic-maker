# -*- coding: utf-8 -*-
"""LoRA 학습 키트: 예시 설정 두 개, 학습 명령 조립, 캡션 나누기(nk ep captions), AI_캡션_만들기.md 예시 형식"""
import os
import re
import types

import yaml

import nk_trainanima as T

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EX_YAML = os.path.join(KIT, "training", "example_anima.yaml")
EX_TOML = os.path.join(KIT, "training", "example_dataset.toml")


def test_example_yaml_points_to_example_toml():
    c = yaml.safe_load(open(EX_YAML, encoding="utf-8"))
    assert c["output_name"] and c["dataset_config"] == "training/example_dataset.toml"
    assert os.path.exists(os.path.join(KIT, c["dataset_config"]))


def test_example_toml_ascii_and_parses():
    raw = open(EX_TOML, "rb").read()
    raw.decode("ascii")                        # 한글이 들어가면 윈도우에서 sd-scripts 가 못 읽을 수 있음
    try:
        import tomllib as tl                   # 3.11+
        d = tl.loads(raw.decode("ascii"))
    except ImportError:
        try:
            import toml as tl
            d = tl.loads(raw.decode("ascii"))
        except ImportError:
            return
    sub = d["datasets"][0]["subsets"][0]
    assert "/" in sub["image_dir"] and "\\" not in sub["image_dir"]
    assert d["general"]["keep_tokens"] == 1 and d["general"]["caption_extension"] == ".txt"


def test_build_cmd_from_example():
    c = yaml.safe_load(open(EX_YAML, encoding="utf-8"))
    cmd = T.build_cmd("C:/kit", c)
    j = " ".join(cmd)
    assert cmd[1] == "anima_train_network.py"
    assert "--max_train_epochs 10" in j and "--save_every_n_epochs 2" in j and "--blocks_to_swap 12" in j
    assert "--masked_loss" not in j            # 예시는 꺼 둠 (투명 PNG 가 있을 때만)
    assert os.path.join("C:/kit", "training/example_dataset.toml") in cmd


def test_no_remote_folder_left():
    assert "_remote" not in open(T.__file__, encoding="utf-8").read()


def test_parse_captions_formats():
    text = ("좋아, 캡션이야:\n```\n=== 01.png\nfox, 1boy, front view\n=== 02.jpg ===\n\nfox, sitting\n"
            "=== **03.png**\n`fox, from behind`\n```\n필요하면 더 말해 줘")
    caps = T.parse_captions(text)
    assert caps == {"01": "fox, 1boy, front view", "02": "fox, sitting", "03": "fox, from behind"}
    assert T.parse_captions("그냥 글") == {}


def test_with_trigger():
    assert T.with_trigger("1boy, smile", "fox") == "fox, 1boy, smile"
    assert T.with_trigger("Fox, smile", "fox") == "Fox, smile"
    assert T.with_trigger("1boy", None) == "1boy"


def test_run_captions_writes_txt(tmp_path, capsys):
    d = tmp_path / "data"
    d.mkdir()
    for n in ("01.png", "02.jpg", "04.png"):
        (d / n).write_bytes(b"")
    ans = tmp_path / "ans.txt"
    ans.write_text("=== 01.png\n1boy, smile\n=== 02.png\nfox, sitting\n=== 03.png\nfox, walking\n", encoding="utf-8")
    args = types.SimpleNamespace(folder=str(d), file=str(ans), trigger="fox", dry=False)
    T.run_captions(None, str(tmp_path), args)
    assert (d / "01.txt").read_text(encoding="utf-8").strip() == "fox, 1boy, smile"
    assert (d / "02.txt").read_text(encoding="utf-8").strip() == "fox, sitting"      # 확장자가 달라도 이름으로 맞춤
    out = capsys.readouterr().out
    assert "03" in out and "04.png" in out                                            # 그림 없는 답, 캡션 없는 그림 알림


def test_caption_prompt_example_matches_parser():
    t = open(os.path.join(KIT, "AI_캡션_만들기.md"), encoding="utf-8").read()
    block = re.search(r"```\n(=== .*?)```", t, re.S).group(1)
    caps = T.parse_captions(block)
    assert len(caps) >= 3 and all(v.startswith("fox,") for v in caps.values())
    assert "ep captions" in t
