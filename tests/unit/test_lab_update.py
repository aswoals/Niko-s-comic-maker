# -*- coding: utf-8 -*-
"""망가메이커 업데이트"""
import json, os
import nk_easy as E


def test_workshop_folders(tmp_path):
    cfg = tmp_path / "nk_workshop.json"
    cfg.write_text(json.dumps({"folders": [r"C:\a\lab\episodes", r"C:\a\lab", r"D:\b"]}), encoding="utf-8")
    assert E._workshop_folders(str(cfg)) == [os.path.normpath(r"C:\a\lab"), os.path.normpath(r"D:\b")]   # episodes 로 끝나면 윗 폴더, 겹침 한 번
    assert E._workshop_folders(str(tmp_path / "none.json")) == []


def test_refresh_chars_backs_up_changed_only(tmp_path):
    kit, lab = tmp_path / "kit", tmp_path / "lab"
    (kit / "characters").mkdir(parents=True); (lab / "characters").mkdir(parents=True)
    (kit / "characters" / "a.yaml").write_text("new", encoding="utf-8")
    (kit / "characters" / "b.yaml").write_text("same", encoding="utf-8")
    (lab / "characters" / "a.yaml").write_text("old", encoding="utf-8")
    (lab / "characters" / "b.yaml").write_text("same", encoding="utf-8")
    log = []
    bk = E._refresh_chars(str(kit), str(lab), log)
    assert (lab / "characters" / "a.yaml").read_text(encoding="utf-8") == "new"
    assert bk and open(os.path.join(bk, "characters", "a.yaml"), encoding="utf-8").read() == "old"
    assert not os.path.exists(os.path.join(bk, "characters", "b.yaml"))          # 같은 파일은 백업·복사 안 함
