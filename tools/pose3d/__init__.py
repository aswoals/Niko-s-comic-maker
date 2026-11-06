# -*- coding: utf-8 -*-
"""
tools/pose3d - 3D 인형 두 개로 자세를 잡아 조종 그림(깊이·사람별 틀·OpenPose·선화)을 만드는 시제품

왜: 자리 잡기(Anima) 그림에서 OpenPose 뼈대만 뽑으면, 몸이 겹칠 때 사람을 못 가르고 앞뒤·닿는 곳 정보가 없음.
    3D 인형이면 '어느 픽셀이 누구인지', '누가 앞인지', '손이 어디 닿는지'를 계산으로 정확히 알 수 있음.
순수 파이썬 (numpy + PIL, 설정 읽기에 PyYAML — nk 파이썬에 이미 있음). GPU·ComfyUI 필요 없음. 파이프라인에는 아직 안 붙임 (제안만).

쓰는 법 (키트 폴더에서, nk 파이썬으로 — tools/pose3d/README.md):
  python tools/pose3d/run.py list
  python tools/pose3d/run.py render --pose piggyback --yaw 20 --pitch 6 --size 832x1216 --out runs/pose3d/test
  python tools/pose3d/run.py examples --out docs/research/interaction_tech_0928_img"""
from .body import Doll, load_settings  # noqa: F401
from .poses import POSES, make  # noqa: F401
