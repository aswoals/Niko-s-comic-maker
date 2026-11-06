# -*- coding: utf-8 -*-
"""
nk_tagger.py - 태그 판별기(WD EVA02-Large Tagger v3)로 "프롬프트에 넣은 것이 실제로 그려졌나" 검사

왜: 작은 검수 AI(gemma e4b)는 "없음·가려짐·작은 것"에 약함.
    태그 판별기는 Danbooru 태그로 학습된 모델이라 우리가 프롬프트에 쓰는 바로 그 태그로 답함.
      꽃이 있나 20/21 (틀린 1장 = 화분 옆 풀밭의 작은 꽃까지 잡음 -> 화분 컷은 문턱 0.8로 올리면 21/21)
      눈이 가려졌나 6/6 (gemma 0/3) / 두 명인가 6/6 / 머리 위 나뭇잎 2/2 / 얼굴 그을음 2/3 (작은 얼룩은 놓침)
    한계: 그림 "어디에" 있는지는 모름(화분 안의 꽃인지 풀밭의 꽃인지) -> 컷마다 문턱을 정해서 씀

모델 파일 (한 번만 받기, 약 1.26GB):
실행: onnxruntime (CPU로 돌림 - 검수 중엔 VRAM을 검수 AI가 씀)

콘티에서 쓰는 법 (qa 항목에 q 대신 tag):
  qa:
    - {tag: flower, max: 0.8, must: true}                 # 이 태그 점수가 0.8 넘으면 불합격
    - {tag: "holding_hat|holding", min: 0.35, must: false} # | = 여러 태그 중 가장 높은 점수"""
import os, csv

_SESS = None
_NAMES = None
_ERR = None


def model_dir(kit):
    return os.path.join(kit, "models", "wd-eva02-large-tagger-v3")


def available(kit):
    """(True, "") 또는 (False, 이유). 판별기가 없어도 nk는 돌아감 (검수 AI만으로)"""
    d = model_dir(kit)
    if not os.path.exists(os.path.join(d, "model.onnx")) or not os.path.exists(os.path.join(d, "selected_tags.csv")):
        return False, "tagger model not found in %s" % d
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False, "onnxruntime is not installed in this python"
    return True, ""


def _load(kit):
    global _SESS, _NAMES, _ERR
    if _SESS is not None or _ERR:
        return _SESS
    ok, why = available(kit)
    if not ok:
        _ERR = why
        return None
    import onnxruntime as ort
    d = model_dir(kit)
    _SESS = ort.InferenceSession(os.path.join(d, "model.onnx"), providers=["CPUExecutionProvider"])
    with open(os.path.join(d, "selected_tags.csv"), encoding="utf-8") as f:
        _NAMES = [r["name"] for r in csv.DictReader(f)]
    return _SESS


def _prep(path, size):
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    im = bg.convert("RGB")
    w, h = im.size
    m = max(w, h)
    sq = Image.new("RGB", (m, m), (255, 255, 255))      # 정사각형으로 흰 여백을 붙임 (판별기 학습 방식과 같게)
    sq.paste(im, ((m - w) // 2, (m - h) // 2))
    sq = sq.resize((size, size), Image.BICUBIC)
    return np.asarray(sq, dtype=np.float32)[:, :, ::-1]  # RGB -> BGR (모델 입력 규칙)


_CACHE = {}


def tags(kit, path):
    """{태그: 점수 0~1}. 판별기가 없으면 None"""
    key = (path, os.path.getmtime(path))
    if key in _CACHE:
        return _CACHE[key]
    sess = _load(kit)
    if sess is None:
        return None
    import numpy as np
    inp = sess.get_inputs()[0]
    x = np.stack([_prep(path, int(inp.shape[1]))])
    out = sess.run(None, {inp.name: x})[0][0]
    res = dict(zip(_NAMES, out.tolist()))
    _CACHE[key] = res
    return res


def score(t, tag):
    """tag = "a|b|c" -> 가장 높은 점수. 판별기 어휘에 없는 태그는 0 (경고는 check_vocab에서)"""
    names = [x.strip().replace(" ", "_") for x in str(tag).split("|") if x.strip()]
    return max((t.get(n, 0.0) for n in names), default=0.0)


_VOCAB = None


def vocab(kit):
    """판별기 단어장(selected_tags.csv)만 읽음 - 모델은 안 올림 (콘티 검사용, 1초 이내). 없으면 빈 set"""
    global _VOCAB
    if _VOCAB is None:
        p = os.path.join(model_dir(kit), "selected_tags.csv")
        try:
            with open(p, encoding="utf-8") as f:
                _VOCAB = set(r["name"] for r in csv.DictReader(f))
        except Exception:
            _VOCAB = set()
    return _VOCAB


def check_vocab(kit, tag):
    """판별기가 모르는 태그 목록 (콘티 검사용).
    이제 nk ep check 가 부름. 모델 대신 단어장 파일만 읽도록 바꿈."""
    v = vocab(kit)
    if not v:
        return []
    names = [x.strip().replace(" ", "_") for x in str(tag).split("|") if x.strip()]
    return [n for n in names if n not in v]


def judge(kit, path, items):
    """items: [{id, tag, min?/max?, must}] -> (answers{id: {"answer": 점수, "ok": bool}}, fails[ids], soft 개수, 판별기 없음 여부)"""
    t = tags(kit, path)
    if t is None:
        return {}, [], 0, True
    answers, fails, soft = {}, [], 0
    for it in items:
        s = score(t, it["tag"])
        ok = True
        if it.get("min") is not None and s < float(it["min"]):
            ok = False
        if it.get("max") is not None and s > float(it["max"]):
            ok = False
        answers[it["id"]] = {"answer": round(s, 3), "ok": ok}
        if not ok:
            if it.get("must"):
                fails.append(it["id"])
            else:
                soft += 1
    return answers, fails, soft, False
