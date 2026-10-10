"""시트 7 재작성 · 재수행 매핑 (데이터).

- 사용자 재작성: 묶음 이름 → 층 · 받는 화면 · 다시 돌릴 Task. 기회는 이 묶음 이름으로만 센다(spec 3.2).
- 계획서 항목 → (웹 태그, 문서층 묶음) 짝짓기 표 SECTION_BUNDLE_TABLE 하나와 그 읽기 함수 (결정 0024, 잠정).
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

# ── 계획서 항목 → (웹 태그, 재작성 묶음) 짝짓기 표 (spec 4.6, 결정 0024) ─────────────
# (잠정) 웹의 묶음 4개와 전략 · 작성 · 검증-1 담당자 양식 항목(예비창업 2.x.x · 초기창업 3.x.x)을 기준으로 우리 쪽에서
# 정했다 — 담당자 · 웹팀 확인 대기. 키 = 항목 번호 앞부분(점으로 나눈 마디 단위, 예: '2.4'는 2.4.1 · 2.4.2 …),
# 값 = (웹 태그, 묶음 이름). 표에 없는 항목(일반현황 · 개요 2.1 ~ 2.3 · 3.1 ~ 3.3, 그림 2.3.6 · 3.3.6 포함)은 묶음 없음 —
# 사용자 재작성 대상이 아니다. 답이 오면 이 표만 바꾼다. 항목 번호 · 묶음 이름 · 묶음 수를 다른 곳에 다시 적지 않는다 —
# 양식 묶음의 sectionTags, 재작성 목표 항목, 판정 후보, 다시 만들 Task는 모두 아래 함수(section_tag_bundle ·
# bundle_sections)로 끌어낸다. 함수는 부를 때마다 이 표를 읽는다(테스트가 표를 바꿔 끼울 수 있다).
SECTION_BUNDLE_TABLE: dict[str, tuple[str, str]] = {
    "2.4": ("1-1", "문제인식"), "3.4": ("1-1", "문제인식"),
    "2.5": ("2-1", "실현가능성"), "3.5": ("2-1", "실현가능성"),
    "2.6": ("3-1", "성장전략"), "3.6": ("3-1", "성장전략"),
    "2.7": ("4-1", "팀 구성"), "3.7": ("4-1", "팀 구성"),
}

# 재작성 요청 묶음 이름 — 웹은 고른 묶음마다 이 이름으로 요청한다. 재작성 기회를 세는 이름은 이것뿐이다
# (판정 지시의 대상 이름은 문서층이면 이 묶음 이름, 산출물층이면 TASK_BUNDLE의 이름이다).
# 문서층 묶음은 짝짓기 표에서 끌어낸다(표에 처음 나온 순서). 묶음이 늘면 웹 화면 · 기회 세기도 바뀌므로 표만으로 끝나지 않는다.
# 문서층 묶음을 고르면 그 묶음 항목만 종류별 Task(KIND_TASK)로 다시 만든다 (sbrain_flow.bundle_orders · spec 4.11).
# 이 상수는 불러올 때의 표 값이다 — 표를 바꿔 끼우는 테스트 · 흐름 계산은 document_bundles()로 그때의 표를 읽는다.
DOCUMENT_BUNDLES: tuple[str, ...] = tuple(dict.fromkeys(bundle for _, bundle in SECTION_BUNDLE_TABLE.values()))
# 판정 지시가 없는 묶음의 재작성 지시 문구 (기준 문서 v1.10 시트 4 ReworkOrder.reason) — 흐름의 재작성 지시와 판정의
# '묶음 모두' 후보(spec 4.12 ②)가 같이 쓴다
REWORK_DEFAULT_REASON = "사용자가 이 묶음의 재작성을 요청했습니다."
# 계획서 항목 종류 → 그 항목을 만드는 Task (spec 4.6 · 4.11 — 본문 T-W1 · 그림 T-W2 · 표 T-W3)
KIND_TASK: dict[str, str] = {"section": "T-W1", "image": "T-W2", "table": "T-W3"}
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


# ── 짝짓기 표 읽기 (spec 4.6) ─────────────────────────────
def section_tag_bundle(section_code: str) -> tuple[str, str] | None:
    """계획서 항목 번호 → (웹 태그, 묶음 이름). 표에 없으면 None(묶음 없음 — 재작성 대상 아님).

    항목 번호를 점으로 나눈 앞부분 중 가장 긴 것부터 표에서 찾는다(예: '2.4.1' → '2.4.1' · '2.4' · '2')."""
    table = SECTION_BUNDLE_TABLE
    parts = str(section_code).split(".")
    for n in range(len(parts), 0, -1):
        hit = table.get(".".join(parts[:n]))
        if hit is not None:
            return hit
    return None


def section_tag(section_code: str) -> str | None:
    """계획서 항목 번호 → 웹 태그(없으면 None)."""
    hit = section_tag_bundle(section_code)
    return hit[0] if hit else None


def section_bundle(section_code: str) -> str | None:
    """계획서 항목 번호 → 재작성 묶음 이름(없으면 None)."""
    hit = section_tag_bundle(section_code)
    return hit[1] if hit else None


def section_tags(section_codes: list[str]) -> list[str | None]:
    """양식 항목 번호 목록 → 같은 길이의 웹 태그 목록 (FormSpec.sectionTags)."""
    return [section_tag(code) for code in section_codes]


def bundle_sections(bundle: str, section_codes: list[str]) -> list[str]:
    """재작성 묶음 이름 → 그 묶음에 속한 항목 번호(양식 순서). 양식에 그 묶음 항목이 없으면 빈 목록."""
    return [code for code in section_codes if section_bundle(code) == bundle]


def document_bundles() -> tuple[str, ...]:
    """지금 짝짓기 표의 문서층 묶음 이름(표에 처음 나온 순서) — '묶음 모두' 후보가 쓴다. 부를 때마다 표를 읽는다."""
    return tuple(dict.fromkeys(bundle for _, bundle in SECTION_BUNDLE_TABLE.values()))


def form_kinds(form: Any) -> list[tuple[str, str]]:
    """양식(FormSpec)의 (항목 번호, 종류) — 양식 순서. 종류 칸이 항목 수와 맞지 않으면(비어 있음) 모두 본문으로 본다."""
    codes = list(form.section_codes)
    kinds = list(form.section_kinds) if len(form.section_kinds) == len(codes) else ["section"] * len(codes)
    return list(zip(codes, kinds))


def bundle_items(bundles: list[str], form: Any) -> list[tuple[str, str]]:
    """고른 문서층 묶음들의 항목 (항목 번호, 종류) — 양식 순서, 합집합. 짝짓기 표로 가른다(묶음 없는 항목은 들지 않는다)."""
    chosen = set(bundles)
    return [(code, kind) for code, kind in form_kinds(form) if section_bundle(code) in chosen]


def bundle_tasks(bundles: list[str], form: Any) -> list[str]:
    """고른 문서층 묶음들의 항목을 다시 만들 Task (DOCUMENT_TASKS 순서) — 그 종류 항목이 없는 Task는 빠진다 (spec 4.11)."""
    needed = {KIND_TASK[kind] for _, kind in bundle_items(bundles, form)}
    return [t for t in DOCUMENT_TASKS if t in needed]


def order_bundles(order: Any) -> list[str]:
    """판정의 재작성 지시 → 기회를 세는 묶음 이름.

    산출물층은 그 Task의 묶음, 문서층은 그 지시의 대상(targets) 중 문서층 묶음 이름만이다(spec 4.11 — 화면의 남은 기회는
    그 묶음의 남은 기회).
    """
    if order.layer == "document":
        names = set(document_bundles())
        return [t for t in dict.fromkeys(order.targets) if t in names]
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
