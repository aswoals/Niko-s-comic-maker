# -*- coding: utf-8 -*-
"""칸 v2: 컷 역할·구도로 칸 크기·모양, 세로로 긴 칸"""
import itertools
import nk_layout2 as L

BOX = [70, 70, 1530, 2189]


def cut(i, shot="knee", n=1, big=False, scene=""):
    c = {"id": i, "shot": shot, "angle": "eye", "_big": big, "scene": scene}
    if n == 0:
        c["char"] = "none"
    elif n >= 2:
        c["cast"] = [{"char": "a"}, {"char": "b"}]
    return c


def check(tree, ids):
    rs = L.rects(tree, BOX, True, 24)
    assert sorted(rs) == sorted(ids)
    for (a, ra), (b, rb) in itertools.combinations(rs.items(), 2):
        assert ra[2] <= rb[0] or rb[2] <= ra[0] or ra[3] <= rb[1] or rb[3] <= ra[1], (a, b)      # 칸끼리 안 겹침
    for r in rs.values():
        assert BOX[0] <= r[0] < r[2] <= BOX[2] and BOX[1] <= r[1] < r[3] <= BOX[3]
    return rs


def test_first_scenery_and_big_get_full_rows():
    cuts = [cut(1, "wide", 0), cut(2, "full"), cut(3, "detail", 0), cut(4, "face"), cut(5, "knee"), cut(6, "detail", 0)]
    tree, _ = L.best_tree(cuts, BOX)
    rs = check(tree, list(range(1, 7)))
    assert rs[1][2] - rs[1][0] == BOX[2] - BOX[0]                     # 첫 풍경 = 한 줄 통째
    cuts2 = [cut(7, "knee", 2, big=True), cut(8, "face"), cut(9, "full", scene="chibi"), cut(10, "waist"), cut(11, "full", 2, big=True)]
    tree2, _ = L.best_tree(cuts2, BOX)
    rs2 = check(tree2, list(range(7, 12)))
    for k in (7, 11):
        assert rs2[k][2] - rs2[k][0] == BOX[2] - BOX[0]                 # 큰 컷 = 한 줄 통째


def test_tall_panel_appears_and_aspects_in_range():
    cuts = [cut(1, "wide", 0), cut(2, "full"), cut(3, "detail", 0), cut(4, "face"), cut(5, "knee"), cut(6, "detail", 0)]
    tree, _ = L.best_tree(cuts, BOX)
    rs = check(tree, list(range(1, 7)))
    h = lambda r: r[3] - r[1]
    assert h(rs[2]) > 1.6 * min(h(rs[3]), h(rs[4]))                    # 혼자 전신 = 세로로 긴 칸, 옆에 작은 칸 둘
    for r in rs.values():
        assert L.ASPECT_MIN - 0.05 <= (r[2] - r[0]) / float(r[3] - r[1]) <= L.ASPECT_MAX + 0.15


def test_compile_v2_default_v1_when_asked():
    """plan 에 layout: v1 / letter: v1 이면 예전대로"""
    import os, yaml, nk, nk_plan
    kit = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plan = {"title": "t", "cast": {"a": "testgirl"}, "locations": {"p": "park"},
            "pages": [{"cuts": [{"who": [], "shot": "wide", "loc": "p"}, {"who": ["a"], "shot": "full", "loc": "p"},
                                {"who": [], "shot": "detail", "loc": "p"}, {"who": ["a"], "shot": "face", "loc": "p"}]}]}
    c1, _ = nk_plan.compile_plan(dict(plan, layout="v1", letter="v1"), None, kit)
    assert "tree" not in c1["pages"][0] and "letter" not in c1
    c2, _ = nk_plan.compile_plan(dict(plan), None, kit)
    assert c2.get("letter") == "v2"
    t = c2["pages"][0]["tree"]
    import nk_webtoon as W
    c2["defaults"] = c2.get("defaults") or {}
    W._flatten_pages(nk, c2)
    assert len(c2["cuts"]) == 4 and all(x["size"] in ["%dx%d" % s for s in W.PAGE_SIZES] for x in c2["cuts"])


def test_new_shots_and_pov_survive_compile():
    import os, nk_plan, nk_webtoon as W
    kit = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plan = {"title": "t", "cast": {"a": "testgirl"}, "locations": {"p": "park"},
            "pages": [{"cuts": [{"who": ["a"], "shot": "eyes", "loc": "p"}, {"who": ["a"], "shot": "hands", "angle": "pov", "loc": "p"},
                                {"who": ["a"], "shot": "knee", "angle": "tilt", "loc": "p"}]}]}
    c, notes = nk_plan.compile_plan(plan, None, kit)
    cs = c["pages"][0]["cuts"]
    assert [x["shot"] for x in cs] == ["eyes", "hands", "knee"] and [x["angle"] for x in cs] == ["eye", "pov", "tilt"], notes
    assert "eye focus" in W._camera_tags(cs[0]) and "hand focus" in W._camera_tags(cs[1]) and "pov" in W._camera_tags(cs[1])
    assert "dutch angle" in W._camera_tags(cs[2])


def test_bg_simple_drops_location():
    import os, nk_plan
    kit = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plan = {"title": "t", "cast": {"a": "testgirl"}, "locations": {"p": "park, tree"},
            "pages": [{"cuts": [{"who": ["a"], "shot": "face", "loc": "p", "bg": "simple", "action": "shocked"},
                                {"who": ["a"], "shot": "knee", "loc": "p", "action": "smile"}]}]}
    c, _ = nk_plan.compile_plan(plan, None, kit)
    a, b = c["pages"][0]["cuts"]
    assert "loc" not in a and "simple background" in a["scene"] and b.get("loc") == "p"


def test_solo_big_not_last_can_be_tall():
    cuts = [cut(1, "wide", 0), cut(2, "knee", big=True), cut(3, "waist"), cut(4, "detail", 0), cut(5, "eyes"), cut(6, "face")]
    tree, _ = L.best_tree(cuts, BOX)
    rs = check(tree, [1, 2, 3, 4, 5, 6])
    x0, y0, x1, y1 = rs[2]
    assert (x1 - x0) < (BOX[2] - BOX[0]) * 0.9                       # 한 줄 통째가 아님
    for c in (3, 4, 6):
        a, b, cc, d = rs[c]
        assert (cc - a) / float(d - b) < 2.4, (c, rs[c])               # 납작한 띠 없음


def test_many_alone_cuts_no_flat_strips():
    """에서 남은 두 컷이 납작한 띠가 되던 것 -> 큰 컷 '한 줄 통째'를 푼 판도 계산"""
    cuts = [cut(1, "wide", 0), cut(2, "full"), cut(3, "full", big=True), cut(4, "waist"), cut(5, "full", n=2)]
    tree, _ = L.best_tree(cuts, BOX)
    rs = check(tree, [1, 2, 3, 4, 5])
    for c in (2, 3, 4, 5):
        a, b, cc, d = rs[c]
        assert (cc - a) / float(d - b) < 2.6, (c, rs[c])
