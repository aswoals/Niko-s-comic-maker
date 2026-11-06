# -*- coding: utf-8 -*-
"""AI_캐릭터_만들기.md (AI 채팅에 첨부하는 캐릭터 만들기 파일): 예시 YAML 이 실제 캐릭터 파일로 읽히는지.
캐릭터 양식(characters/_template.yaml)이 바뀌면 이 시험이 깨져서 첨부 파일도 같이 고치게 함."""
import os
import re

import yaml

import nk

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(KIT, "AI_캐릭터_만들기.md")
NEED = ("name", "trigger", "name_ko", "personality", "tags_short", "tags_full", "anima", "compose_name")


def _doc():
    return open(DOC, encoding="utf-8").read()


def _example():
    m = re.search(r"```yaml\n(.*?)```", _doc(), re.S)
    assert m, "예시 YAML 코드 블록이 없음"
    return m.group(1)


def test_example_loads_with_required_fields():
    raw = _example()
    d = yaml.safe_load(raw)
    for k in NEED:
        assert str(d.get(k) or "").strip(), k
    fn = re.search(r"# 파일 이름: characters/(\w+)\.yaml", raw).group(1)
    assert d["name"] == d["trigger"] == fn
    assert "ai_hide" not in d                     # 이 줄이 있으면 캐릭터 목록에서 빠짐


def test_required_fields_are_explained():
    t = _doc()
    for k in NEED:
        assert "`%s`" % k in t, k


def test_template_required_fields_match():
    """양식이 '꼭 채우기'로 둔 칸이 첨부 파일의 꼭 쓰는 칸에 다 들어 있는지"""
    tpl = yaml.safe_load(open(os.path.join(KIT, "characters", "_template.yaml"), encoding="utf-8"))
    for k in NEED:
        assert k in tpl, k


def test_example_has_no_blocked_words():
    d = yaml.safe_load(_example())
    for k in ("tags_short", "tags_full", "anima", "anima_back"):
        assert nk.safe_text(d[k]) == d[k], k
