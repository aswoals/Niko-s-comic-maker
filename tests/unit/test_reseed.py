# -*- coding: utf-8 -*-
"""nk_animacut reseed: '다시 그리기'(태그 안 바꿈)는 그 컷만 시드 +1000, 다른 컷·태그 고치기는 그대로"""
import nk_animacut as A


def test_reseed_moves_only_that_cut(tmp_path, monkeypatch):
    monkeypatch.setenv("NK_HOME", str(tmp_path))          # ep_dir 이 이 임시 폴더의 episodes 를 씀
    c3, c4 = {"id": 3}, {"id": 4}
    assert A.cut_seed("ep1", c3, "500") == 503 and A.cut_seed("ep1", c4, "500") == 504
    assert A.bump_reseed("ep1", 3) == 1
    assert A.cut_seed("ep1", c3, "500") == 1503 and A.cut_seed("ep1", c4, "500") == 504
    assert A.bump_reseed("ep1", 3) == 2 and A.cut_seed("ep1", c3, "500") == 2503
    assert A.cut_seed("ep2", c3, "500") == 503                 # 다른 화는 안 바뀜
    assert A.cut_seed("ep1", {"id": 3, "seed": 77}, "500") == 2077   # 콘티에 시드가 있으면 그 시드에서 옮김
    assert (tmp_path / "episodes" / "ep1" / "reseed.json").exists()
