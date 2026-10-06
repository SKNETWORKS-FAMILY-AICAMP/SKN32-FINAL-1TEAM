"""시트 7 재작성 · 재수행 매핑 (데이터).

- 사용자 재작성: 묶음 이름 → 층 · 받는 화면 · 다시 돌릴 Task. 기회는 이 묶음 이름으로만 센다(spec 3.2).
- 검사 미통과 재수행: 확정 동작 예외 여섯 곳
판정(어느 항목이 미달인지)은 G-02a · G-02b(조율 Agent)가 하고, 이 표는 그 판정과 Orchestrator의 검증이 같이 쓴다.
"""
from __future__ import annotations

from typing import Any

# 산출물층 묶음
BUNDLE_EXECUTABLE = "실행 파일"
BUNDLE_INFOGRAPHIC = "인포그래픽"
BUNDLE_README = "안내 문서"

DOCUMENT_TASKS = ("T-W1", "T-W2", "T-W3")

# 재작성 요청 묶음 이름 — 웹은 고른 묶음마다 이 이름으로 요청한다. 재작성 기회를 세는 이름은 이것뿐이다
# (판정 지시의 대상 이름 — 예: 스텁의 '묶음-<항목>' — 으로는 세지 않는다).
# 문서층 4개는 임시 구성 (잠정) — 문서층 담당자의 묶음 구성 문서가 오면 바꾼다. 어느 이름이든 계획서 전체
# (T-W1 · T-W2 · T-W3)를 다시 만든다 (sbrain_flow.bundle_orders).
DOCUMENT_BUNDLES = ("문제인식", "실현가능성", "성장전략", "팀 구성")
ARTIFACT_BUNDLES = (BUNDLE_EXECUTABLE, BUNDLE_INFOGRAPHIC)
BUNDLE_LAYER: dict[str, str] = {**{b: "document" for b in DOCUMENT_BUNDLES},
                                **{b: "artifact" for b in ARTIFACT_BUNDLES}}
BUNDLE_TASK = {BUNDLE_EXECUTABLE: "T-B1", BUNDLE_INFOGRAPHIC: "T-B2"}
# 층별로 받는 화면 (시트 7) — 화면 6은 문서층만, 화면 8은 산출물층만, 화면 9는 둘 다
LAYER_SCREENS: dict[str, tuple[int, ...]] = {"document": (6, 9), "artifact": (8, 9)}

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


def order_bundles(order: Any) -> list[str]:
    """판정의 재작성 지시 → 기회를 세는 묶음 이름.

    산출물층은 그 Task의 묶음, 문서층은 문서층 묶음 4개 전부다(임시 처리에서는 어느 이름으로 요청해도 계획서
    전체를 다시 만들기 때문, 잠정).
    """
    if order.layer == "document":
        return list(DOCUMENT_BUNDLES)
    return [TASK_BUNDLE.get(order.task_id, order.task_id)]
