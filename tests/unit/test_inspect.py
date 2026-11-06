# -*- coding: utf-8 -*-
import numpy as np
import nk_inspect as I


def P(**kw):
    d = {k: np.array(v, float) for k, v in kw.items()}
    return I._pts(list(d), [v.tolist() for v in d.values()], [1] * len(d))


def test_seg_errors_and_leg_swap():
    doll = P(neck=[0, 0], r_hip=[-5, 50], l_hip=[5, 50], r_knee=[-5, 100], l_knee=[25, 95], r_ankle=[-5, 150], l_ankle=[45, 140])
    same = P(neck=[0, 0], r_hip=[-5, 50], l_hip=[5, 50], r_knee=[-5, 100], l_knee=[25, 95], r_ankle=[-5, 150], l_ankle=[45, 140])
    assert max(I.seg_errors(doll, same, I.SEGS).values()) < 1
    swapped = P(neck=[0, 0], r_hip=[-5, 50], l_hip=[5, 50], l_knee=[-5, 100], r_knee=[25, 95], l_ankle=[-5, 150], r_ankle=[45, 140])
    assert max(I.seg_errors(doll, swapped, I.SEGS).values()) < 15            # DWPose 좌우 헷갈림은 봐줌
    flipped = P(neck=[0, 150], r_hip=[-5, 100], l_hip=[5, 100], r_knee=[-5, 50], l_knee=[25, 55], r_ankle=[-5, 0], l_ankle=[45, 10])
    assert I._robust(I.seg_errors(doll, flipped, I.SEGS)) > 120             # 거꾸로


def test_facing_sign():
    front = P(neck=[0, 0], r_shoulder=[-20, 0], l_shoulder=[20, 0], r_hip=[-8, 60], l_hip=[8, 60])
    back = P(neck=[0, 0], r_shoulder=[20, 0], l_shoulder=[-20, 0], r_hip=[8, 60], l_hip=[-8, 60])
    assert I.facing_score(front, front)[0] > 0 and I.facing_score(front, back)[0] < 0


def test_judge_flags_and_skips():
    base = {"char": "a", "colors": None, "doll_legs": 4, "draw_legs": 4, "facing": 0.3, "arm_err": None}
    cuts = [{"id": 1, "pose": "s_stand", "people": [dict(base, pose_err=90.0)]},
            {"id": 2, "pose": "s_sit_floor", "people": [dict(base, pose_err=10.0, draw_legs=0)]},      # 앉기: 다리 못 찾아도 안 걸림
            {"id": 3, "pose": "s_stand", "people": [dict(base, pose_err=10.0, facing=-0.5)]}]
    v = {x["id"]: [f[0] for f in x["flags"]] for x in I.judge(cuts)}
    assert v[1] == ["pose"] and v[2] == [] and v[3] == ["facing"]
