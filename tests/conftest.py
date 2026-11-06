# -*- coding: utf-8 -*-
"""pytest 공통: 키트 폴더와 tests 폴더를 import 경로에 (python -m pytest tests 로 실행, README '시험')"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
for p in (KIT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
# 시험은 가짜 캐릭터 파일만 씀 (키트의 characters/ 는 사용자 것)
os.environ["NK_CHARS"] = os.path.join(HERE, "fixtures", "characters")
os.environ["NK_AGREE"] = "1"          # 시험은 사용 정책 동의 묻기를 건너뜀
