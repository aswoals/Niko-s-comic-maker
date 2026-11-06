# -*- coding: utf-8 -*-
import nk_webtoon as W
import nk_web


def test_parse_range_loose_forms():
    assert W._parse_range("5-8,15") == {5, 6, 7, 8, 15}
    assert W._parse_range("-3") == {1, 2, 3}
    assert W._parse_range("1~3") == {1, 2, 3} and W._parse_range("1–2") == {1, 2}
    assert 5 in W._parse_range("5-") and 998 in W._parse_range("5-") and 4 not in W._parse_range("5-")
    assert 7 in W._parse_range("3-end") and 1 in W._parse_range("all")
    assert W._parse_range("") == set() and W._parse_range(None) == set()


def test_fail_reason(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("x\n[ERROR] unknown preset: foo  (nk list)\n[ERROR] make failed - stop (fix and run again)\n", encoding="utf-8")
    assert nk_web._fail_reason(str(p)).startswith("[ERROR] unknown preset")          # 뒤따르는 'failed - stop' 말고 진짜 이유
    p.write_text('Traceback (most recent call last):\n  File "C:\\k\\nk_webtoon.py", line 212, in _parse_range\nValueError: bad\n', encoding="utf-8")
    assert nk_web._fail_reason(str(p)) == "ValueError: bad (nk_webtoon.py 212줄 _parse_range)"
    assert nk_web._fail_reason(str(tmp_path / "none.log")) == ""
