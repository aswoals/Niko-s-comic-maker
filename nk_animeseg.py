# -*- coding: utf-8 -*-
"""그림 캐릭터 배경 분리
모델: skytnt/anime-seg isnetis.onnx (HuggingFace, Apache-2.0, 176,069,933 바이트,
      sha256 f15622d853e8260172812b657053460e20806f04b9e05147d49af7bed31a6e99) -> models/animeseg/isnetis.onnx
왜: 글자 v2 의 사람 마스크는 뼈대(DWPose)로 만들어서 케모노는 몸을 다 못 잡음 -> 효과선이 캐릭터를 덮음 (lt01 컷 10).
    이 모델은 그림 속 캐릭터 실루엣을 통째로 잡음. CPU 로만 돌림 (ComfyUI 가 GPU 를 쓰는 중이어도 안 건드림).
쓰는 곳: nk_webtoon.page_letter (conti letter: v2 일 때만) — 사람 마스크에 더함.
결과는 poses/cutNN_seg_<md5 8자리>.png 에 저장 (같은 그림이면 다시 안 돌림)."""
import hashlib
import os

KIT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(KIT, "models", "animeseg", "isnetis.onnx")
_SESS = None


def available():
    return os.path.exists(MODEL)


def _sess():
    global _SESS
    if _SESS is None:
        import onnxruntime as ort
        _SESS = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    return _SESS


def mask(img, s=1024):
    """PIL 그림 -> 캐릭터 마스크 (L, 같은 크기, 0~255). 모델 저장소 app.py 의 get_mask 와 같은 방식 (정사각 s 에 비율 유지해 넣음)"""
    import cv2
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h0, w0 = a.shape[:2]
    h, w = (s, int(s * w0 / h0)) if h0 > w0 else (int(s * h0 / w0), s)
    ph, pw = s - h, s - w
    x = np.zeros([s, s, 3], dtype=np.float32)
    x[ph // 2:ph // 2 + h, pw // 2:pw // 2 + w] = cv2.resize(a, (w, h))
    x = np.transpose(x, (2, 0, 1))[np.newaxis, :]
    sess = _sess()
    m = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    m = m[0] if m.ndim == 3 else m
    m = m[ph // 2:ph // 2 + h, pw // 2:pw // 2 + w]
    m = cv2.resize(m, (w0, h0))
    return Image.fromarray((np.clip(m, 0.0, 1.0) * 255).astype(np.uint8), "L")


def cached_mask(pose_dir, cid, img_path):
    """컷 그림의 캐릭터 마스크 (L). 모델이 없거나 실패하면 None"""
    if not available():
        return None
    from PIL import Image
    md5 = hashlib.md5(open(img_path, "rb").read()).hexdigest()
    p = os.path.join(pose_dir, "cut%02d_seg_%s.png" % (int(cid), md5[:8]))
    if os.path.exists(p):
        return Image.open(p).convert("L")
    try:
        m = mask(Image.open(img_path))
    except Exception as e:
        print("[note] cut %s: anime-seg skipped (%s)" % (cid, e))
        return None
    os.makedirs(pose_dir, exist_ok=True)
    m.save(p)
    return m
