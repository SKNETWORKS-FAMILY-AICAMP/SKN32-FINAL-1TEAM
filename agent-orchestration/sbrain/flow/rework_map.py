"""시트 7 재작성 · 재수행 매핑 (데이터).

- 사용자 재작성: 미달 유형 → 다시 돌릴 Task · 재작성 단위(묶음)
- 검사 미통과 재수행: 확정 동작 예외 여섯 곳
판정(어느 항목이 미달인지)은 G-02a · G-02b(조율 Agent)가 하고, 이 표는 그 판정과 Orchestrator의 검증이 같이 쓴다.
"""
from __future__ import annotations

# 재작성 묶음 (산출물층). 문서층 계획서 항목 묶음은 구성 미확정 — G-02a가 정한다.
BUNDLE_EXECUTABLE = "실행 파일"
BUNDLE_INFOGRAPHIC = "인포그래픽"
BUNDLE_README = "안내 문서"

DOCUMENT_TASKS = ("T-W1", "T-W2", "T-W3")

# 코드 검증 항목 번호 → 다시 돌릴 Task (카테고리별)
CODE_CHECK_TARGET: dict[str, dict[int, str]] = {
    "html": {1: "T-B1", 2: "T-B2", 3: "T-B1", 4: "T-B1", 5: "T-B1", 6: "T-B1", 7: "G-04", 8: "T-B1"},
    "svg-onepage": {1: "T-B2", 2: "T-B2", 3: "T-B2", 4: "T-B2", 5: "T-B2", 6: "T-B2", 7: "T-B2", 8: "G-04"},
}
# 대조 missingFeatures → 다시 돌릴 Task
FEATURE_MISSING_TARGET = {"html": "T-B1", "svg-onepage": "T-B2"}

TASK_BUNDLE = {"T-B1": BUNDLE_EXECUTABLE, "T-B2": BUNDLE_INFOGRAPHIC, "G-04": BUNDLE_README}

# 검사 미통과 재수행 뒤 확정 동작을 따르는 여섯 곳
FINAL_ACTION_EXCEPTIONS = frozenset({"T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-P2"})

# 안내 문서 미충족을 재작성 목록에 올릴지 — 미확정. 올리지 않는다 (잠정)
LIST_README_BUNDLE = False
