"""시트 7 재작성 · 재수행 매핑 (데이터).

- 사용자 재작성: 묶음 이름 → 층 · 받는 화면 · 다시 돌릴 Task. 기회는 이 묶음 이름으로만 센다(spec 3.2).
- 검사 미통과 재수행: 확정 동작 예외 여섯 곳
- 산출물층 미달 → 다시 돌릴 Task: artifact_rework_reasons (규칙만 쓰고 재량이 없다 — G-02b 스텁 · 실구현이 같이 쓴다)
판정(어느 항목이 미달인지)은 G-02a · G-02b(조율 Agent)가 하고, 이 표는 그 판정과 Orchestrator의 검증이 같이 쓴다.
"""
from __future__ import annotations

from typing import Any

from ..models import ArtifactScore

# 산출물층 묶음
BUNDLE_EXECUTABLE = "실행 파일"
BUNDLE_INFOGRAPHIC = "인포그래픽"
# 안내 문서(README)는 점수 밖이라 재작성 묶음이 없다 — G-04 자체 검사가 확인 · 재실행한다 (2026-09-30 결정 5)

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

# 코드 점검 칸 번호 → 다시 돌릴 Task (카테고리별). HTML 2번(대체 텍스트)은 결함 출처(defect_sources)로 가르므로 빠진다
CODE_CHECK_TARGET: dict[str, dict[int, str]] = {
    "html": {1: "T-B1", 3: "T-B1", 4: "T-B1", 5: "T-B1", 6: "T-B1", 7: "T-B1", 8: "T-B1"},
    "svg-onepage": {n: "T-B2" for n in range(1, 9)},
}
GATE_TARGET = {"html": "T-B1", "svg-onepage": "T-B2"}                  # 통과 필수 조건 실패 — 칸 번호를 보지 않는다
DEFECT_SOURCE_TARGET = {"prototype": "T-B1", "infographic": "T-B2"}    # HTML 2번 결함 출처
ALT_TEXT_CHECK = 2                                                     # HTML 2번(대체 텍스트)
# HTML 2번 미충족인데 결함 출처가 비었을 때(담당자 쪽 누락) — v1.9 매핑대로 인포그래픽으로 보낸다 (잠정)
ALT_TEXT_FALLBACK_TARGET = "T-B2"
# 대조 미충족 · 부분 인정 → 다시 돌릴 Task
FEATURE_MISSING_TARGET = {"html": "T-B1", "svg-onepage": "T-B2"}

TASK_BUNDLE = {"T-B1": BUNDLE_EXECUTABLE, "T-B2": BUNDLE_INFOGRAPHIC}

# 검사 미통과 재수행 뒤 확정 동작을 따르는 여섯 곳
FINAL_ACTION_EXCEPTIONS = frozenset({"T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-P2"})


def order_bundles(order: Any) -> list[str]:
    """판정의 재작성 지시 → 기회를 세는 묶음 이름.

    산출물층은 그 Task의 묶음, 문서층은 문서층 묶음 4개 전부다(임시 처리에서는 어느 이름으로 요청해도 계획서
    전체를 다시 만들기 때문, 잠정).
    """
    if order.layer == "document":
        return list(DOCUMENT_BUNDLES)
    return [TASK_BUNDLE.get(order.task_id, order.task_id)]


def alt_text_source_missing(score: ArtifactScore, kind: str) -> bool:
    """HTML 2번(대체 텍스트)이 미충족인데 결함 출처(defect_sources)가 비었는지 — 그 사유는 ALT_TEXT_FALLBACK_TARGET으로 가고
    흐름이 관리자 사건을 남긴다 (잠정). 통과 필수 조건 실패면 칸을 보지 않으므로 거짓이다."""
    if kind != "html" or score.code_check.gate_failures:
        return False
    return any(ch.no == ALT_TEXT_CHECK and not ch.passed and not ch.defect_sources for ch in score.code_check.checks)


def artifact_rework_reasons(score: ArtifactScore, kind: str) -> dict[str, list[str]]:
    """산출물층 미달 → {다시 돌릴 Task: 사유 목록} (Task는 처음 나온 순서). 규칙만 쓰고 재량이 없다.

    1. 통과 필수 조건 실패(gate_failures)가 있으면 카테고리의 Task 하나만 돌려준다 — 칸과 대조는 보지 않는다.
    2. 불통과 칸마다: HTML 2번은 결함 출처(defect_sources)로, 나머지는 CODE_CHECK_TARGET으로.
       HTML 2번인데 결함 출처가 비었으면 ALT_TEXT_FALLBACK_TARGET (잠정).
    3. 대조: 누락 기능(missing_features)과 부분 인정 기능(partial_features)이 있으면 FEATURE_MISSING_TARGET으로
       '누락 기능: a, b' · '부분 인정 기능: c' (있는 쪽만). 판정 보류(withheld)면 넣지 않는다.
    4. G-04(안내 문서)는 어떤 경우에도 넣지 않는다 (점수 밖).
    흐름을 가르는 값은 필드로만 읽는다 — detail · findings · diagnostics 문구로 가르지 않는다.
    """
    cc, fm = score.code_check, score.feature_match
    if cc.gate_failures:
        return {GATE_TARGET[kind]: [f"통과 필수 조건 실패: {', '.join(cc.gate_failures)}"]}
    reasons: dict[str, list[str]] = {}
    for ch in cc.checks:
        if ch.passed:
            continue
        line = f"코드 검증 {ch.no}번 {ch.name}"
        if kind == "html" and ch.no == ALT_TEXT_CHECK:
            targets = [DEFECT_SOURCE_TARGET[src] for src in ch.defect_sources] or [ALT_TEXT_FALLBACK_TARGET]
        else:
            targets = [CODE_CHECK_TARGET[kind][ch.no]]
        for task_id in dict.fromkeys(targets):
            reasons.setdefault(task_id, []).append(line)
    if not fm.withheld:
        lines = ([f"누락 기능: {', '.join(fm.missing_features)}"] if fm.missing_features else []) + (
            [f"부분 인정 기능: {', '.join(fm.partial_features)}"] if fm.partial_features else [])
        if lines:
            reasons.setdefault(FEATURE_MISSING_TARGET[kind], []).extend(lines)
    return reasons
