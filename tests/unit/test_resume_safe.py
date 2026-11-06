# -*- coding: utf-8 -*-
"""이어 그리기 안전: 얼굴 다듬기 기록, 깨진 그림 가리기, 컷 범위"""
import nk_auto as A


def test_facepass_record(tmp_path):
    d = str(tmp_path)
    assert A.facepass_load(d, [1, 4]) == {1, 4}
    A.facepass_save(d, {2, 5})
    assert A.facepass_load(d, [1, 4]) == {2, 5}                 # 기록이 있으면 기록대로


def test_png_ok(tmp_path):
    from PIL import Image
    good, bad = tmp_path / "g.png", tmp_path / "b.png"
    Image.new("RGB", (8, 8)).save(good)
    bad.write_bytes(open(good, "rb").read()[:30])               # 쓰다 끊긴 그림
    assert A._png_ok(str(good)) and not A._png_ok(str(bad)) and not A._png_ok(str(tmp_path / "none.png"))


def test_face_pass_switch_words():
    """없거나 true 면 켬 (nk_auto·nk_web 같은 규칙)"""
    off = lambda v: str(v).strip().lower() in ("false", "0", "off", "no", "none")
    assert off(False) and off("false") and off(0) and off("off") and not off(True) and not off(0.6) and not off("true")
    import yaml, os
    d = yaml.safe_load(open(os.path.join(os.environ["NK_CHARS"], "testcat.yaml"), encoding="utf-8"))
    assert off(d.get("anima_face_pass", True))
