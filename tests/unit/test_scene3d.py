# -*- coding: utf-8 -*-
import os
import sys
KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(KIT, "tools")); sys.path.insert(0, KIT)
from scene3d import export_doll as E  # noqa: E402


def test_vrm_for_defaults():
    assert E.vrm_for({"tags_full": "1boy, solo"}).endswith("Base_Male.vrm")
    assert E.vrm_for({"tags_full": "1girl"}).endswith("Base_Female.vrm")
    assert E.vrm_for({"vrm": "x.vrm"}) == "x.vrm"


def test_export_scene_json(tmp_path):
    cut = {"id": 7, "shot": "full", "angle": "eye", "scene": "arm hug, walking",
           "_roles": [({"pos": "walking"}, {"name": "a", "height_cm": 160}), ({"pos": "arm hug"}, {"name": "b", "height_cm": 157})]}
    d = E.export(cut, 320, 200, ["a.vrm", "b.vrm"], str(tmp_path / "s.json"))
    assert d["pose"] == "L_arm_hug" and len(d["people"]) == 2 and d["people"][1]["vrm"] == "b.vrm"
    assert set(("pelvis", "l_ankle", "head")) <= set(d["people"][0]["pos"]) and d["camera"]["fov"] > 0


def test_regionlora_apply_control_rewires_models():
    import nk_regionlora as R
    g = {"1": {"class_type": "UNETLoader", "inputs": {}}, "40": {"inputs": {"model": ["1", 0]}}, "11": {"inputs": {"model": ["1", 0]}}}
    R.apply_control(g, {"_control_up": "a.png", "lllite": "x", "lllite_strength": 0.45, "lllite_end": 0.45,
                        "_control_up2": "b.png", "lllite2": "y", "lllite2_strength": 0.3, "lllite2_end": 0.7})
    assert g["40"]["inputs"]["model"] == ["16z", 0] and g["11"]["inputs"]["model"] == ["16z", 0] and g["14c"]["inputs"]["model"] == ["1", 0]
    assert R.apply_control({"40": {"inputs": {"model": ["1", 0]}}}, {})["40"]["inputs"]["model"] == ["1", 0]
