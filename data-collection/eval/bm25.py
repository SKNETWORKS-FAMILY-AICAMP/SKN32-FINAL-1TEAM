# -*- coding: utf-8 -*-
"""BM25 — 실제 구현은 루트의 hybrid.py 로 옮겼다(서비스와 평가가 같은 코드를 쓴다).

기존 평가 스크립트의 `from bm25 import BM25` 가 그대로 돌게 남겨 둔 연결 파일이다.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from search.hybrid import BM25, tokenize  # noqa: E402,F401
