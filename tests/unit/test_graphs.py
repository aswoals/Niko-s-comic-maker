# -*- coding: utf-8 -*-
"""두 명 컷 그림 주문서(그래프) 만들기 모의 실행 — ComfyUI 없이

test_regional 은 이름만 보고
    (AMI 는 최종 그림이 없으면 건너뜀) selftest 는 몇 시간 동안 아무도 안 돌려서 못 잡음. 이 시험은 2~3초.
확인: 그래프가 예외 없이 만들어지고, 모든 노드 이름이 알려진 노드(가짜 ComfyUI 목록 = 설치 노드 + 쓰는 내장 노드)이고,
      모든 연결 [번호, 출력]이 있는 노드를 가리키고, 저장 노드가 있고, 고리(순환)가 없음."""
import os, sys, shutil, argparse
import pytest

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_graph(g):
    """-> 문제 목록 (빈 목록 = 통과)"""
    import mock_comfy
    known = set(mock_comfy.NODES)
    bad = []
    for nid, n in g.items():
        if n.get("class_type") not in known:
            bad.append("node %s: unknown class %s" % (nid, n.get("class_type")))
        for k, v in (n.get("inputs") or {}).items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int) and v[0] not in g:
                bad.append("node %s.%s -> missing node %s" % (nid, k, v[0]))
    if not any(n.get("class_type") == "SaveImage" for n in g.values()):
        bad.append("no SaveImage")
    state = {}

    def visit(nid, path):
        if state.get(nid) == 1:
            bad.append("cycle: %s" % " -> ".join(path + [nid])); return
        if state.get(nid) == 2 or nid not in g:
            return
        state[nid] = 1
        for v in (g[nid].get("inputs") or {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int):
                visit(v[0], path + [nid])
        state[nid] = 2
    for nid in g:
        visit(nid, [])
    return bad


@pytest.fixture
def duo(tmp_path, monkeypatch):
    """임시 NK_HOME 에 시험 편(selftest01) 콘티 + 두 명 컷(4) 재료"""
    monkeypatch.setenv("NK_HOME", str(tmp_path))
    d = tmp_path / "episodes" / "selftest01"
    shutil.copytree(os.path.join(KIT, "tests", "fixtures", "selftest01"), d)
    import nk, nk_plan, nk_webtoon as W, nk_regional as R
    nk_plan.run_compile(nk, KIT, argparse.Namespace(ep="selftest01", dry=False, plan=None))
    cfg = nk.load_presets()
    conti = W.load_conti(nk, KIT, "selftest01")
    cut = next(c for c in conti["cuts"] if c.get("_roles"))
    s = R._settings(nk, W, cfg, conti, cut)
    bp, bn, regions = W._duo_parts(nk, cfg, conti, cut, s)
    assert any(r["char"] and r["char"].get("lora") for r in regions), "시험 편 두 명 컷에 LoRA 캐릭터가 있어야 AMB 경로를 탐"
    return {"nk": nk, "W": W, "R": R, "cfg": cfg, "conti": conti, "cut": cut, "s": s, "bp": bp, "bn": bn, "regions": regions}


HIRES = {"scale": 1.5, "denoise": 0.35, "steps": 20}
INIT = {"image": "nk_pose/fake_init.png", "w": 1024, "h": 768}


@pytest.mark.parametrize("v", ["P", "PT0.2", "AM", "AMB", "AMB0.7", "AMI0.4", "AMI0.5", "AMIN0.4", "AMIL0.4", "AMIC0.4",
                               "AMIB0.75s8", "AMIBL0.8", "LC", "LCb", "LP", "LF", "LFs", "LFg8b4", "LFr0.3", "LFmB", "LFd", "LFw"])
@pytest.mark.parametrize("hires", [None, HIRES])
def test_variant_graph(duo, v, hires):
    x = duo
    init = {"front_mask": "nk_pose/fake_front.png"} if v == "LP" else (INIT if v.startswith("AMI") else None)
    g = x["R"]._graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/%s" % v, v,
                      None if v.startswith("AMI") else hires, init)
    assert check_graph(g) == []


@pytest.mark.parametrize("v", ["LC", "LCb", "LF", "LFs"])
def test_variant_graph_with_pose(duo, v):
    """+O = 뼈대 ControlNet 을 붙인 그래프 (regtest 가 붙이는 방식 그대로)"""
    x = duo
    g = x["R"]._graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/%s" % v, v, HIRES, None)
    x["W"]._pose_cn(g, x["s"], "nk_pose/fake_pose.png", 1.0, 0.5)
    assert check_graph(g) == []


@pytest.mark.parametrize("back", [False, True])
def test_lck_two_stage(duo, back):
    """LCk: ① 후보(stage1_only) 그래프 + 고른 ①에서 시작하는 누끼 레이어 그래프"""
    x = duo
    g1 = x["R"]._lf_graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 1071, "nk/t/c0", 1.0, HIRES, stage1_only=True)
    assert check_graph(g1) == []
    g2 = x["R"]._lc_graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/lck", HIRES,
                          back=back, init_img="nk_pose/fake_stage1.png")
    x["W"]._pose_cn(g2, x["s"], "nk_pose/fake_pose.png", 1.0, 0.5)
    assert check_graph(g2) == []


def test_unify_default_path_builds_valid_graphs(duo, monkeypatch):
    """기본 unify 가 실제로 지나가는 함수 그대로: nk_regional.unify(dry) 가 보내려는 주문서를 가로채 검사"""
    x = duo
    from PIL import Image
    f = x["W"]._final_file(KIT, "selftest01", int(x["cut"]["id"]))
    os.makedirs(os.path.dirname(f), exist_ok=True)
    Image.new("RGB", (1024, 768), (120, 160, 200)).save(f)
    sent = []

    def fake_run_jobs(cfg, jobs, run_name, dry):
        sent.extend(jobs)
        return []
    monkeypatch.setattr(x["nk"], "run_jobs", fake_run_jobs)
    x["R"].unify(x["nk"], KIT, x["conti"], ids=None, denoise=0.4, seeds=(71, 72), apply=False, dry=True)
    assert len(sent) == 2
    for j in sent:
        assert check_graph(j["graph"]) == []
        kinds = {n["class_type"] for n in j["graph"].values()}
        assert {"ETN_AttentionMask", "SAM3_Detect", "LoraLoader", "DifferentialDiffusion"} <= kinds


def test_check_graph_catches_problems():
    """검사기 자체: 모르는 노드·끊긴 연결·저장 없음·고리를 잡는지"""
    g = {"1": {"class_type": "NoSuchNode", "inputs": {}},
         "2": {"class_type": "VAEDecode", "inputs": {"samples": ["99", 0], "vae": ["3", 0]}},
         "3": {"class_type": "VAEDecode", "inputs": {"samples": ["2", 0]}}}
    bad = check_graph(g)
    assert any("unknown class NoSuchNode" in b for b in bad)
    assert any("missing node 99" in b for b in bad)
    assert any("no SaveImage" in b for b in bad)
    assert any(b.startswith("cycle") for b in bad)


def test_lc_layers_graph(duo):
    """nk ep lclayers: LCk 2단계 + 머리 틀 + 층 저장 그래프 (층 이름 11개가 다 저장되는지)"""
    x = duo
    g = x["R"]._lc_layers_graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/layers", HIRES,
                                "nk_pose/fake_stage1.png", "nk_pose/fake_backsolo.png")
    assert check_graph(g) == []
    saves = {n["inputs"]["filename_prefix"].rsplit("_", 1)[-1] for n in g.values() if n["class_type"] == "SaveImage"}
    assert saves == {"L1", "plate", "R", "A", "B", "n1", "nR", "m1", "mR", "h1", "hR"}
    assert g["721107"]["inputs"]["image"] == ["702", 0] and g["701"]["inputs"]["image"] == "nk_pose/fake_backsolo.png"


@pytest.mark.parametrize("lora", [False, True])
def test_touch_graph(duo, lora):
    """nk ep touchfix (조사 T5): 닿는 곳만 두 캐릭터 영역으로 다시 칠하는 그래프"""
    import nk_layer
    x = duo
    g = nk_layer._touch_graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/touch", "nk_pose/c.png",
                              "nk_pose/m.png", "nk_pose/m1.png", "nk_pose/mR.png", 1024, 768, 0.5, lora)
    assert check_graph(g) == []
    assert ("LoraLoader" in {n["class_type"] for n in g.values()}) == lora
    assert "duo" in g["100"]["inputs"]["text"] and "duo" in g["110"]["inputs"]["text"]      # 영역 글에 인원수 태그 유지 (solo 금지)


def test_touch_region(tmp_path):
    """닿는 곳 = 두 틀을 넓힌 겹침 - 머리. 멀리 떨어지면 None"""
    import numpy as np
    from PIL import Image
    import nk_layer
    H, W = 200, 300

    def put(name, box):
        a = np.zeros((H, W), np.uint8)
        if box:
            a[box[1]:box[3], box[0]:box[2]] = 255
        Image.fromarray(a).convert("RGB").save(str(tmp_path / (name + ".png")))
    put("m1", (40, 50, 140, 190)); put("mR", (150, 50, 260, 190)); put("h1", (60, 50, 120, 90)); put("hR", (140, 50, 240, 90))
    t, box = nk_layer.touch_region(str(tmp_path))
    assert t is not None and box[0] < 145 < box[2]
    assert t[70, 145] < 0.5 and t[150, 145] > 0.5                   # 상대 머리 안은 빠지고 몸 사이는 들어감
    put("mR", (270, 50, 300, 190))
    t2, _ = nk_layer.touch_region(str(tmp_path), grow_n=10)
    assert t2 is None


def test_lc_layers_graph_with_3d_partner_mask(duo):
    """작업 8 P2: 상대 칸 = 3D 인형 틀 (세로 띠 대신) — 띠 노드(950번대) 대신 LoadImageMask 957"""
    x = duo
    g = x["R"]._lc_layers_graph(x["W"], x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/l3d", HIRES,
                                "nk_pose/s1.png", "nk_pose/back.png", partner_mask="nk_pose/partner3d.png")
    assert check_graph(g) == []
    assert g["957"]["inputs"]["image"] == "nk_pose/partner3d.png" and "950" not in g
    assert g["1100"]["inputs"]["mask"] == ["957", 0]


def test_composite_front3d_z(tmp_path):
    import numpy as np
    from PIL import Image
    import nk_layer as L
    H, Wd = 120, 160
    L1 = np.zeros((H, Wd, 3), np.float32); L1[..., 0] = 1.0
    R = np.zeros((H, Wd, 3), np.float32); R[..., 2] = 1.0              # 상대 층 = 파랑
    m1 = np.zeros((H, Wd), np.float32); m1[20:100, 20:100] = 1
    mR = np.zeros((H, Wd), np.float32); mR[20:100, 60:140] = 1         # 60~100 이 겹침
    n1, nR = L.feather(m1, 3, 2), L.feather(mR, 3, 2)
    A = L.comp(L1, R, n1); B = L.comp(R, A, nR)
    zero = np.zeros((H, Wd), np.float32)
    for k, v in dict(L1=L1, R=R, A=A, B=B).items(): L.save(v, str(tmp_path / (k + ".png")))
    for k, v in dict(m1=m1, mR=mR, h1=zero, hR=zero, n1=n1, nR=nR).items():
        Image.fromarray((np.clip(v, 0, 1) * 255).astype(np.uint8)).convert("RGB").save(str(tmp_path / (k + ".png")))
    a3 = np.zeros((H, Wd), np.uint8); a3[20:100, 20:80] = 255
    Image.fromarray(a3).save(str(tmp_path / "a3.png")); Image.fromarray(255 - a3).save(str(tmp_path / "b3.png"))
    rep = L.composite(str(tmp_path), front3d=(str(tmp_path / "a3.png"), str(tmp_path / "b3.png")), sheet=False)
    Z = L.load(str(tmp_path / "comp" / "Z.png")); Bs = L.load(str(tmp_path / "comp" / "B_S.png"))
    assert Z[60, 70, 0] > 0.8 and Bs[60, 70, 2] > 0.8
    assert Z[60, 92, 2] > 0.8
    assert "front3d_area" in rep


@pytest.mark.parametrize("kind", ["depth", "regional", "lineart"])
def test_anima_lllite_graph(kind):
    """3번 시험 nk ep layout3d: Anima 자리 잡기 그래프에 AnimaLLLiteApply (603 -> 612 -> 607)"""
    import nk_pose, nk_webtoon as W
    s = {"width": 1152, "height": 896}
    g = nk_pose._anima_graph(W, s, "two characters", 1, "nk/t/l3d")
    nk_pose._lllite(g, nk_pose.ANIMA_LLLITE[kind], "nk_pose/ctrl.png", 0.6, 1.0)
    assert check_graph(g) == []
    assert g["607"]["inputs"]["model"] == ["612", 0] and g["612"]["inputs"]["model"] == ["603", 0]


def test_joint_graph_adds_line_and_depth(duo):
    """nk ep joint: MB 그래프 + 선·깊이 ControlNet 이 그리기 단계에만 사슬로"""
    import nk_joint
    x = duo
    masks = {"region": ["nk_pose/r0.png", "nk_pose/r1.png"], "repaint": ["nk_pose/p0.png", "nk_pose/p1.png"]}
    g, used = x["W"]._duo_graph(x["cfg"], x["s"], x["bp"], x["bn"], x["regions"], 71, "nk/t/joint", "MB0.9", x["conti"],
                                hires=HIRES, pose="nk_pose/pose.png", masks=masks)
    n0 = len(g)
    nk_joint.add_cn(g, x["s"], nk_joint.LINE_CN, "nk_pose/line.png", 0.45, 0.6, 8100)
    nk_joint.add_cn(g, x["s"], nk_joint.DEPTH_CN, "nk_pose/depth.png", 0.6, 0.8, 8200)
    assert check_graph(g) == [] and used == "MB0.9"
    draw = [k for k, v in g.items() if v["class_type"] == "KSampler" and not (400 <= int(k) < 500)]
    assert len(draw) == 2
    for k in draw:                                   # 그리기 단계 = OpenPose -> 선 -> 깊이 사슬 끝에 붙음
        p = g[k]["inputs"]["positive"][0]
        assert g[p]["class_type"] == "ControlNetApplyAdvanced" and g[g[p]["inputs"]["control_net"][0]]["inputs"]["control_net_name"] == nk_joint.DEPTH_CN
    names = [v["inputs"]["control_net_name"] for v in g.values() if v["class_type"] == "ControlNetLoader"]
    assert nk_joint.LINE_CN in names and nk_joint.DEPTH_CN in names
    assert len(g) == n0 + 2 * (3 + len(draw))


def test_joint_masks_3d(tmp_path):
    """3D 틀 -> 영역(넓게)·다시 그리기(상대가 보이는 곳 뺌) 파일"""
    import numpy as np, cv2
    import nk_joint
    p3 = tmp_path / "cut09"; p3.mkdir()
    a = np.zeros((100, 120), np.uint8); a[20:80, 60:100] = 255
    b = np.zeros((100, 120), np.uint8); b[20:80, 20:60] = 255
    cv2.imwrite(str(p3 / "mask_a.png"), a); cv2.imwrite(str(p3 / "mask_b.png"), b)
    out = nk_joint.masks_3d(str(p3), 240, 200, str(tmp_path), grow_region=4, grow_repaint=4)
    reg0 = cv2.imread(out[0][0], 0) > 127; rep0 = cv2.imread(out[0][1], 0) > 127
    bb = cv2.resize(b, (240, 200), interpolation=cv2.INTER_NEAREST) > 127
    assert reg0.sum() > rep0.sum() > 0
    assert not (rep0 & bb).any() and (reg0 & bb).any()     # 다시 그리기는 상대 픽셀을 안 건드림, 영역 글은 경계를 조금 넘음


def test_animatest_graph_with_lora():
    """T4c: 변형에 lora 가 있으면 LoraLoaderModelOnly 가 모델과 그리기 사이에"""
    import nk_animatest
    v = {"unet": "anima-base-v1.0.safetensors", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "lora": "testcat_anima_v1.safetensors", "lora_strength": 0.8}
    g = nk_animatest.graph(v, "text", "neg", 1024, 1024, 1, "nk/t/a")
    assert check_graph(g) == []
    assert g["8"]["inputs"]["model"] == ["11", 0] and g["11"]["inputs"]["strength_model"] == 0.8


def test_animatest_graph_with_lllite_and_lora():
    """T4e: LoRA 뒤에 Anima LLLite 조종 (ModelPatchLoader + AnimaLLLiteApply), 조종 그림이 없으면 안 붙음"""
    import nk_animatest
    v = {"unet": "anima-base-v1.0.safetensors", "steps": 30, "cfg": 4.5, "sampler": "er_sde", "lora": "testcat_anima_v1.safetensors",
         "lllite": "anima-lllite-regional-exp-v3.safetensors", "control_kind": "regional", "lllite_strength": 0.6, "_control_up": "nk_pose/r.png"}
    g = nk_animatest.graph(v, "text", "neg", 1152, 896, 1, "nk/t/a")
    assert check_graph(g) == []
    assert g["8"]["inputs"]["model"] == ["14", 0] and g["14"]["inputs"]["model"] == ["11", 0] and g["14"]["inputs"]["strength"] == 0.6
    g2 = nk_animatest.graph(dict(v, _control_up=None), "text", "neg", 1152, 896, 1, "nk/t/a")
    assert "14" not in g2 and g2["8"]["inputs"]["model"] == ["11", 0]


def test_animatest_graph_hires():
    """없으면 예전 그대로"""
    import nk_animatest
    v = {"unet": "anima-aesthetic-v1.1.safetensors", "steps": 30, "cfg": 4.5, "sampler": "er_sde",
         "hires": {"scale": 1.5, "denoise": 0.4, "steps": 30}}
    g = nk_animatest.graph(v, "text", "neg", 768, 1344, 7, "nk/t/a")
    assert check_graph(g) == []
    assert g["40"]["inputs"]["image"] == ["9", 0] and g["40"]["inputs"]["scale_by"] == 1.5
    assert g["42"]["inputs"]["latent_image"] == ["41", 0] and g["42"]["inputs"]["denoise"] == 0.4 and g["42"]["inputs"]["seed"] == 7
    assert g["10"]["inputs"]["images"] == ["43", 0]
    g0 = nk_animatest.graph(dict(v, hires=None), "text", "neg", 768, 1344, 7, "nk/t/a")
    assert "40" not in g0 and g0["10"]["inputs"]["images"] == ["9", 0]


def test_animatest_graph_incontext():
    """없으면 예전 그대로"""
    import nk_animatest
    v = {"unet": "anima-base-v1.0.safetensors", "steps": 30, "cfg": 4.5, "sampler": "er_sde",
         "incontext": {"strength": 1.3}, "_refs_up": ["a_full.png", "a_face.png"]}
    g = nk_animatest.graph(v, "text", "neg", 832, 1216, 1, "nk/t/a")
    assert check_graph(g) == []
    assert g["15"]["inputs"]["lora_name"] == "anima-incontext-character.safetensors" and g["15"]["inputs"]["model"] == ["1", 0]
    assert g["60"]["inputs"]["target_width"] == 832 and g["61"]["inputs"]["image"] == ["51", 0]
    assert g["71"]["inputs"]["ref_latent_1"] == ["60", 0] and g["71"]["inputs"]["ref_latent_2"] == ["61", 0]
    assert g["79"]["inputs"]["ref_latent"] == ["71", 0] and g["79"]["inputs"]["strength"] == 1.3 and g["79"]["inputs"]["model"] == ["15", 0]
    assert g["8"]["inputs"]["model"] == ["79", 0]
    g0 = nk_animatest.graph(dict(v, _refs_up=None), "text", "neg", 832, 1216, 1, "nk/t/a")
    assert "79" not in g0 and "15" not in g0 and g0["8"]["inputs"]["model"] == ["1", 0]
