# -*- coding: utf-8 -*-
"""nk 안에서 도는 무거운 부품(onnx 모델)을 가짜로 바꿈

- 태그 판별기 nk_tagger (WD EVA02, onnxruntime) -> fake_tags: 그림 파일에 가짜 ComfyUI 가 적어 둔
  프롬프트(PNG 글 칸 'nk_mock_prompt')를 읽어서, 프롬프트에 있는 태그는 높은 점수, 없는 태그는 낮은 점수.
  글 칸이 없는 그림(잘라 낸 머리 등)은 '나쁜 태그'(뒷모습·캐릭터 forbid) 0.02, 나머지 0.9.
  NK_MOCK_MODE=fail 이면 모든 태그 0.0 (= '그려지지 않음' -> 소품 넣기·고치기 경로를 탐)
- 뼈대 찾기 nk_pose (DWPose onnx) -> fake_pose_one: 칸(box) 안에 서 있는 사람 모양 133점 (믿음 0.9)

nk 코드 파일은 고치지 않고, 모듈 속 함수만 이 프로세스 안에서 바꿔 끼움 (tests/nk_mocked.py 가 부름)."""
import os


class FakeTags(dict):
    """dict 처럼 쓰이지만 모르는 태그도 점수를 돌려줌 (nk_tagger.score 는 t.get(태그, 0.0) 을 씀)"""

    def __init__(self, present, default):
        super().__init__()
        self.present = present
        self.default = default

    def get(self, k, d=None):
        k = str(k).replace(" ", "_").lower()
        if k in self.present:
            return 0.9
        return self.default

    def __getitem__(self, k):
        return self.get(k)

    def __contains__(self, k):
        return True

    def __bool__(self):                     # 빈 dict 는 거짓 -> nk 의 'tags(...) or {}' 가 판별기 없음으로 봄. 늘 참으로
        return True


def _prompt_of(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return (im.info or {}).get("nk_mock_prompt")
    except Exception:
        return None


_BAD = None


def bad_tags(kit):
    """'있으면 안 되는' 태그: 뒷모습 + 캐릭터 파일 forbid (글 칸 없는 그림에서 낮은 점수로)"""
    global _BAD
    if _BAD is None:
        import glob, yaml
        _BAD = {"from_behind", "blurry", "multiple_views", "extra_ears", "bad_anatomy", "monochrome", "greyscale",
                "heterochromia"}
        for p in glob.glob(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "*.yaml")):
            try:
                d = yaml.safe_load(open(p, encoding="utf-8")) or {}
            except Exception:
                continue
            for k in ("forbid", "duo_exclusive"):          # 캐릭터에 없어야 할 것 + 상대 전용 소품
                _BAD |= set(x.strip().replace(" ", "_").lower() for x in str(d.get(k) or "").split(",") if x.strip())
            for v in (d.values() if isinstance(d, dict) else []):     # facefix 의 bad: "..." 목록 (어느 키 밑이든)
                if isinstance(v, dict) and isinstance(v.get("bad"), str):
                    _BAD |= set(x.strip().replace(" ", "_").lower() for x in v["bad"].split(",") if x.strip())
    return _BAD


class _NoMeta(FakeTags):
    """글 칸이 없는 그림 (nk 가 잘라 내거나 다시 저장한 그림): 나쁜 태그는 0.02, 나머지는 0.9 = '다 잘 그려짐'"""

    def get(self, k, d=None):
        k = str(k).replace(" ", "_").lower()
        return 0.02 if k in self.present else 0.9


def fake_tags(kit, path):
    mode = os.environ.get("NK_MOCK_MODE", "pass")
    if mode == "fail":
        return FakeTags(set(), 0.0)
    txt = _prompt_of(path)
    if txt is None:
        return _NoMeta(bad_tags(kit), 0.9)
    present = set(t.strip().replace(" ", "_").lower() for t in txt.replace("\n", ",").split(",") if t.strip())
    return FakeTags(present, 0.03)


def fake_pose_one(img, box):
    """nk_pose.pose_one 와 같은 모양: (133x2 좌표, 133 믿음). 칸 가운데에 서 있는 사람"""
    import numpy as np
    x0, y0, x1, y1 = [float(v) for v in box]
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    cx = x0 + w / 2

    def P(fx, fy):
        return [cx + fx * w, y0 + fy * h]
    body = [P(0, .20), P(-.04, .18), P(.04, .18), P(-.08, .19), P(.08, .19),       # 코 눈 눈 귀 귀
            P(-.14, .32), P(.14, .32), P(-.20, .45), P(.20, .45), P(-.24, .58), P(.24, .58),   # 어깨 팔꿈치 손목
            P(-.08, .62), P(.08, .62), P(-.09, .78), P(.09, .78), P(-.09, .93), P(.09, .93)]  # 엉덩이 무릎 발목
    feet = [P(-.10, .96), P(-.06, .96), P(-.09, .95), P(.10, .96), P(.06, .96), P(.09, .95)]
    face = [P(-.06 + .12 * i / 67.0, .17 + .06 * ((i * 7) % 10) / 10.0) for i in range(68)]
    lh = [P(-.24 + .01 * (i % 5), .58 + .01 * (i // 5)) for i in range(21)]
    rh = [P(.24 - .01 * (i % 5), .58 + .01 * (i // 5)) for i in range(21)]
    kp = np.array(body + feet + face + lh + rh, dtype=np.float64)
    conf = np.full(133, 0.9, dtype=np.float64)
    return kp, conf


def install(kit):
    """nk_tagger·nk_pose 를 가짜로. 돌려줌: 바꾼 것 목록"""
    import nk_tagger, nk_pose
    done = []
    nk_tagger.available = lambda k: (True, "")
    nk_tagger.tags = fake_tags
    done.append("nk_tagger.available/tags")
    nk_pose.pose_one = fake_pose_one
    dw = os.environ.get("NK_MOCK_DW")               # 'DWPose 모델 파일이 있나' 검사용 빈 파일 (실행기가 임시 폴더에 만듦)
    if dw:
        nk_pose.DW = dw
    done.append("nk_pose.pose_one (+DW=%s)" % (dw or "unchanged"))
    return done
