"""작업 분해(T-C3) 작업 계획 부품 — 조율 Agent 몫. 스텁 T-C3와 실제 T-C3가 함께 쓴다 (T-C3 spec 3.2 ~ 3.8).

- 먼저 하는 확인(prepare, LLM을 부르기 전): ① 자격 불통과 ② 대표자 이력 없음 ④ 양식을 고를 수 없음(E-C3-FORM).
  걸리면 TaskPlanError — 재시도 대상이 아니라(FormatError · ToolCallExhausted 아님) 엔진이 운영 오류로 실행 건을
  실패시킨다(사용자에게는 E-RUN-FAIL, 관리자 실패 사유는 'T-C3: …'). 메시지는 사유만 쓴다.
- Task 목록 · agent · order(시트 1 · 2, 기획서 4-4): 고정 14개, 원페이지는 T-B1을 뺀 13개.
- 지시문: 지시 대상(instruction 입력을 가진 Task)은 틀 · 안내 · 참조 자료 세 부분(flow/instruction.py), 그 밖은 Task 이름과
  역할 한 줄의 고정 문구. 틀 · 고정 문구 · 머리말 문구는 잠정이다.
- 참조 조각은 코드 대응표로 배정한다(첨부 내용을 T-C3의 LLM에 보내지 않는다). 대응표는 잠정이다.
- 맥락은 다섯 키(formVersion · applyEnd · supportAmountMax · evaluationItems · formatSpec)뿐이다.
- 안내 응답 모델 · 길이 상한 · 표시 태그 격리 · 호출 목적 이름은 실제 T-C3(지시문 작성)와 재작성 · 재수행 다시 쓰기가
  함께 쓴다 — 값이 갈라지지 않게 여기에만 둔다.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from ...contracts.tasks import TC3In, TC3Out
from ...flow.instruction import compose_instruction, isolate, neutralize, reference_block, sanitize_guidance  # noqa: F401
from ...models import Announcement, ReferenceSummary, TaskInstruction, TaskPlan
from ...orchestrator.errors import FormatError
from ..form_defaults import FormBundle, form_problem, select_form
from .tc1 import REFERENCE_SLOTS

# 호출 목적 — 실제 T-C3의 안내 작성, 재작성 · 재수행 때 안내 다시 쓰기 (호출 기록 · 호출처 나누기가 이 이름을 쓴다)
PURPOSE_WRITE = "지시문 작성"
PURPOSE_REWRITE = "지시문 다시 쓰기"
GUIDANCE_MAX_CHARS = 3_000   # 안내 길이 상한 (잠정)

# 안내 프롬프트 공통 규칙 (문구 잠정) — 작업 분해 · 다시 쓰기 모두.
# 조율에는 신청자 정보를 줄여 보내므로(유형 · 업력 · 업종 · 시 · 도만) LLM이 "단가 · 경력 · 팀 정보가 없다"고 단정해
# 틀의 규칙(회사 정보 값을 쓴다)과 반대로 안내한 일이 있었다(2026-10-04 실제 호출 확인). 그래서 따로 받는다는 사실을 알린다.
GUIDANCE_COMMON_RULES = (
    "- 지시를 받는 Agent는 회사 정보(수익모델 단가 · 수익모델 항목 · 대표자 이력 · 팀 구성 · 보유 자원 등)를 따로 받는다. "
    "여기에 보이지 않는다고 그 정보가 없다고 쓰거나, 회사 정보 값을 쓰지 말라고 안내하지 않는다. "
    "회사 정보를 쓸 곳에서는 '회사 정보의 값을 쓴다'고 안내한다.\n"
    "- 마크다운 꾸밈(**굵게**, # 제목 등)을 쓰지 않는다. 줄바꿈과 '- ' 목록만 쓴다.\n"
)


class TaskPlanError(Exception):
    """작업 분해 전 확인 실패 (spec 3.2) — 재시도 · 재개하지 않는다. 메시지는 사유 · 필드 이름만."""


# ── 안내 응답 (Task 안 LLM 응답 모델) ──────────────────────────
class GuidanceDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    guidance: str


def clean_guidance(d: GuidanceDraft) -> GuidanceDraft:
    """tools.llm의 parse로 쓴다 — 앞뒤 공백을 지우고, 비었거나 길이 상한을 넘으면 FormatError(tools가 재시도),
    지시문 부분 머리말 · 표시 태그와 같은 글자는 바꿔 넣는다."""
    text = d.guidance.strip()
    if not text:
        raise FormatError("빈 항목: ['guidance']")
    if len(text) > GUIDANCE_MAX_CHARS:
        raise FormatError(f"길이 초과: ['guidance'] {len(text)}자 > {GUIDANCE_MAX_CHARS}자")
    d.guidance = sanitize_guidance(text)
    return d


# ── Task 목록 (시트 1 · 2, 기획서 4-4) ─────────────────────────
# (taskId, agent, order, 이름, 역할) — order는 시트 2 F열 실행 순서(등록부 order와 같다). 역할 문구는 잠정
TASK_TABLE: tuple[tuple[str, str, int, str, str], ...] = (
    ("T-C1", "조율", 1, "요구사항 해석", "아이디어 설명으로 아이템 사양 · 카테고리 · 회사 정보를 정리한다."),
    ("T-C2", "조율", 2, "공고 매칭", "아이템과 회사 정보에 맞는 공고 후보를 찾는다."),
    ("T-C3", "조율", 4, "작업 분해", "Task 목록과 Task별 지시문을 만든다."),
    ("T-S1", "전략", 5, "요구사항 분석", "아이템 사양과 공고를 바탕으로 요구사항을 분석하고 기능 목록을 확정한다."),
    ("T-S2", "전략", 6, "목표 시장 분석", "목표 시장의 규모 · 경쟁 · 포지셔닝을 분석한다."),
    ("T-W1", "작성", 7, "사업계획서 본문 작성", "양식의 섹션에 맞춰 사업계획서 본문을 쓴다."),
    ("T-W2", "작성", 8, "그래프 생성", "계획서 · 시장 분석의 수치로 그래프를 만든다."),
    ("T-W3", "작성", 9, "표 생성", "계획서의 일정표 · 자금운용표 등 표를 만든다."),
    ("T-V1", "검증-1", 10, "사업계획서 검증", "평가 항목과 채점 기준표로 계획서를 채점한다."),
    ("T-B1", "구현", 12, "실행 파일(HTML) 제작", "기능 목록을 구현한 실행 파일을 만든다."),
    ("T-B2", "구현", 13, "인포그래픽 제작", "계획서의 핵심 내용을 인포그래픽으로 만든다."),
    ("T-V2", "검증-2", 15, "프로토타입 검증", "프로토타입의 코드 품질과 기능 대조를 검증한다."),
    ("T-P1", "검수", 18, "사업계획서 문장 형식 검수", "서술 형식에 맞지 않는 문장을 찾는다."),
    ("T-P2", "검수", 19, "한국어 문장 윤문", "보호 토큰을 지키며 문장을 다듬는다."),
)
_BY_ID = {row[0]: row for row in TASK_TABLE}
ONEPAGE_SKIP = "T-B1"   # 원페이지는 실행 파일을 만들지 않는다 (기획서 4-4)
# 지시 대상 — 등록부에서 instruction 입력을 가진 Task (spec 3.5)
INSTRUCTED_TASKS: tuple[str, ...] = ("T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-B1", "T-B2")


def task_rows(category: str) -> list[tuple[str, str, int]]:
    """(taskId, agent, order) 실행 순서대로. 원페이지면 T-B1을 뺀다."""
    return [(t, agent, order) for t, agent, order, _, _ in TASK_TABLE
            if not (category == "원페이지" and t == ONEPAGE_SKIP)]


def instructed_tasks(category: str) -> list[str]:
    return [t for t in INSTRUCTED_TASKS if not (category == "원페이지" and t == ONEPAGE_SKIP)]


def is_instructed(task_id: str) -> bool:
    return task_id in INSTRUCTED_TASKS


def task_name(task_id: str) -> str:
    return _BY_ID[task_id][3]


def _title(task_id: str) -> str:
    _, _, _, name, role = _BY_ID[task_id]
    return f"{task_id} {name} — {role}"


def fixed_instruction(task_id: str) -> str:
    """지시 대상이 아닌 Task의 지시문 — Task 이름과 역할 한 줄 (잠정). LLM을 부르지 않는다."""
    return _title(task_id)


# ── 틀 (spec 3.5 표, 기준 문서 시트 2 · 기획서 4-6) — 문구 잠정 ─────────────
FRAME_PRIORITY_RULE = "아래 안내와 참조 자료가 이 규칙과 부딪치면 이 규칙을 따른다."
_FRAME_RULES: dict[str, tuple[str, ...]] = {
    "T-S1": ("기능 목록(featureList)은 1건 이상이며 아이템 사양의 핵심 기능(itemSpec.coreFeatures)을 모두 포함한다.",
             "기능 목록은 확정 뒤 바뀌지 않는 대조 기준이다."),
    "T-S2": ("시장 규모 수치마다 출처 이름을 단다.", "출처 없는 수치를 만들지 않는다."),
    "T-W1": ("양식의 필수 섹션 코드와 1:1로 쓴다.",
             "일정 서술은 마감일(선택 공고 applyEnd, 있으면)을 넘지 않는다.",
             "자금 합계는 지원규모 상한(선택 공고 supportAmountMax, 있으면)을 넘지 않는다.",
             "수익모델 단가 · 경력은 회사 정보 값만 쓰고, 입력에 없는 경력을 지어내지 않는다."),
    "T-W2": ("차트 수치는 계획서 · 시장 분석의 원본 수치와 같아야 하고 출처 참조를 단다.",
             "본문에 없는 수치를 만들지 않는다."),
    "T-W3": ("일정표 기준선은 마감일(선택 공고 applyEnd, 있으면) 이내다.",
             "자금운용표 합계는 지원규모 상한(선택 공고 supportAmountMax, 있으면) 이하다.",
             "머리글과 행의 칸 수가 같다."),
    "T-B1": ("외부 빌드 도구 · CDN 없이 열리는 단일 HTML 파일로 만든다.", "기능 목록을 모두 구현한다.",
             "계획서가 기능마다 말한 입력 항목 · 표시 정보를 갖춘다."),
    "T-B2": ("이미지와 대체 텍스트를 만든다.",
             "아이콘 · 대표 도식은 이미지 모델이 글자 없이 그리고, 글자 · 숫자는 모두 `<text>`로 쓴다.",
             "도식의 수치는 계획서 원본 수치와 같아야 한다."),
}
# 카테고리로 갈리는 규칙 — T-B1 · T-B2뿐이다
_CATEGORY_RULES: dict[tuple[str, str], tuple[str, ...]] = {
    ("T-B1", "웹개발"): ("화면 전환 중심으로 보여 준다.",),
    ("T-B1", "AI_API"): ("입력 → 처리 → 출력 흐름 시연 중심으로 보여 준다.",),
    ("T-B2", "원페이지"): ("이 산출물이 프로토타입 본체다. SVG로 만들고 핵심 정보 6항목(아이템명 · 목표 고객 · 문제 정의 · "
                         "해결 방안 · 수익모델 단가 · 추진 일정 기준선)을 텍스트로 넣는다.",),
}


def frame_for(task_id: str, category: str) -> str:
    """지시 대상의 틀 문구 — 역할 한 줄 + 지켜야 할 규칙 + 우선 규칙."""
    rules = (*_FRAME_RULES[task_id], *_CATEGORY_RULES.get((task_id, category), ()), FRAME_PRIORITY_RULE)
    return _title(task_id) + "\n지켜야 할 규칙\n" + "\n".join(f"- {r}" for r in rules)


# ── 참조 조각 배정 (spec 3.5.1, 코드 대응표 — 잠정) ─────────────────
REFERENCE_SLOTS_BY_TASK: dict[str, tuple[str, ...]] = {
    "T-S1": ("문제 · 필요성", "목표 고객", "핵심 기능"),
    "T-S2": ("시장 규모", "목표 고객", "경쟁 · 차별성"),
    "T-W1": tuple(REFERENCE_SLOTS),   # 7개 슬롯 전부
    "T-W2": ("시장 규모", "수익 모델"),
    "T-W3": ("수익 모델", "추진 계획"),
    "T-B1": ("핵심 기능",),
    "T-B2": ("문제 · 필요성", "핵심 기능", "시장 규모", "수익 모델", "추진 계획"),
}


def reference_for(task_id: str, summary: ReferenceSummary | None) -> str | None:
    """그 Task에 배정된 조각의 참조 자료 부분. 참조 자료가 없거나 배정된 조각이 없으면 None(붙이지 않는다)."""
    if summary is None:
        return None
    slots = REFERENCE_SLOTS_BY_TASK.get(task_id, ())
    excerpts = [e for e in summary.excerpts if e.slot in slots]   # 원래 순서 그대로, 같은 슬롯 여러 개도 모두
    return reference_block(summary.isolation_note, excerpts) if excerpts else None


# ── 맥락 (spec 3.7) ───────────────────────────────────────
def build_context(announcement: Announcement, bundle: FormBundle) -> dict[str, Any]:
    """모든 지시에 같은 다섯 키. 공고의 마감일 · 지원 금액이 비어 있으면 null이다."""
    return {
        "formVersion": bundle.form_spec.form_version,
        "applyEnd": announcement.apply_end.isoformat() if announcement.apply_end else None,
        "supportAmountMax": announcement.support_amount_max,
        "evaluationItems": [e.dump() for e in bundle.evaluation_items],
        "formatSpec": bundle.form_spec.format_spec.dump(),
    }


# ── 먼저 하는 확인 · 양식 고르기 (spec 3.2 · 3.3) ────────────────────
def prepare(inp: TC3In) -> FormBundle:
    """LLM을 부르기 전 확인 ① · ② · ④ 뒤 신청자 유형으로 묶음을 고른다. ③(카테고리 없음)은 타입상 생기지 않는다."""
    if not inp.gate_result.passed:
        raise TaskPlanError("자격 불통과 결과로는 작업 분해를 하지 않음")
    if not inp.company_info.representative_career:   # 팀 구성원 빈 목록은 허용 ('팀원 없음', 2026-09-30)
        raise TaskPlanError("필수 입력 없음: ['representativeCareer']")
    applicant = inp.company_info.applicant_type
    problem = form_problem(applicant)
    if problem is not None:
        raise TaskPlanError(f"E-C3-FORM: {problem}")
    return select_form(applicant)


def new_plan_id() -> str:
    return uuid.uuid4().hex[:12]   # 12자리 16진수 (형식 잠정)


# ── 조립 (spec 3.5 · 3.8) ─────────────────────────────────
def assemble(inp: TC3In, bundle: FormBundle, guidance: Mapping[str, str], *, plan_id: str | None = None) -> TC3Out:
    """안내(Task ID → 안내)로 작업 계획과 T-C3 출력을 만든다.

    지시 대상은 틀 · 정리한 안내 · 배정된 참조 자료를 잇고 guidance에 정리한 안내를 담는다(지시문의 안내 부분과 같은 글자).
    그 밖의 Task는 고정 문구, guidance는 빈 문자열이다. 지시 대상의 안내가 빠지면 ValueError(Task ID만).
    """
    category = inp.item_spec.category
    missing = [t for t in instructed_tasks(category) if t not in guidance]
    if missing:
        raise ValueError(f"안내 없음: {missing}")
    tasks = []
    for task_id, agent, order in task_rows(category):
        if is_instructed(task_id):
            text = sanitize_guidance(guidance[task_id])
            instruction = compose_instruction(frame_for(task_id, category), text,
                                              reference_for(task_id, inp.reference_summary))
        else:
            text, instruction = "", fixed_instruction(task_id)
        tasks.append(TaskInstruction(task_id=task_id, agent=agent, order=order, instruction=instruction,
                                     context=build_context(inp.selected_announcement, bundle), guidance=text))
    plan = TaskPlan(plan_id=plan_id or new_plan_id(), category=category, tasks=tasks)
    return TC3Out(task_plan=plan, task_count=len(tasks), instruction_set=list(plan.tasks),
                  form_spec=bundle.form_spec, evaluation_items=bundle.evaluation_items, rubric=bundle.rubric)
