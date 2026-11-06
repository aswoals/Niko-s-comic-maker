# -*- coding: utf-8 -*-
"""nk.py 를 가짜 부품(tests/fakes.py)을 끼운 채로 실행: python tests/nk_mocked.py ep auto <편> ...

가짜 서버 주소는 환경 변수로 받음 (NK_COMFY_SERVER, NK_OLLAMA — nk.load_presets 가 읽음). 실행기(run_selftest.py)가 씀."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, KIT)
sys.path.insert(0, HERE)

import nk          # noqa: E402
import fakes       # noqa: E402

fakes.install(KIT)
sys.argv = [os.path.join(KIT, "nk.py")] + sys.argv[1:]
nk.main()
