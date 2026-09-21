# -*- coding: utf-8 -*-
"""정형 필터 + 의미 검색 실험 (지시서 docs/SQL_SEMANTIC_EXPERIMENT_TASK_20260918.md).

기존 서비스 경로(dense+BM25 하이브리드)는 그대로 두고, 별도 로컬 MySQL 에서
  정형 필터(SQL) → 후보 벡터와 직접 비교 → 규칙 정렬 → Top N
을 시험한다. VectorDB·BM25 를 쓰지 않는다.
"""
