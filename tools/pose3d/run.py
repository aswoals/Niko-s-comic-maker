# -*- coding: utf-8 -*-
"""
tools/pose3d 실행기 — 어느 폴더에서 돌려도 되게 (다른 'tools' 패키지와 이름이 겹쳐도 안전)


명령 설명은 __main__.py 맨 위. 에러가 나면: 에러 마지막 줄을 확인."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tools 폴더

from pose3d.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
