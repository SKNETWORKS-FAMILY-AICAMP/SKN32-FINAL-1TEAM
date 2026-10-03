"""선택 공고의 기본 양식 (잠정) — 신청서 양식(formSpec)과 평가 항목(evaluationItems).

공고 서버는 양식 · 평가 항목을 주지 않는다. 실제 값은 작성 · 검수 Agent를 연동할 때 정하고, 그 전에는 스텁 공고와
공고 서버 연결(G-01)이 모두 이 기본 양식을 쓴다 (spec 2.2 · 4.4, orchestrator/settings.py PROVISIONAL announcement.formSpec).
"""
from __future__ import annotations

from ..models import EvalItem, FormatSpec, FormSpec

# 평가 항목 (코드, 배점) — 문서층 70점 (잠정)
EVAL_ITEMS: tuple[tuple[str, float], ...] = (("문제인식", 20.0), ("실현가능성", 20.0), ("성장전략", 15.0), ("팀구성", 15.0))


def default_form_spec() -> FormSpec:
    return FormSpec(form_version="예비-2026", applicant_types=["예비창업자", "개인사업자", "법인"],
                    section_codes=["1-1", "2-1", "3-3"], section_titles=["문제인식", "실현가능성", "성장전략"],
                    format_spec=FormatSpec(style_type="개조식", ending_rule="단정형", banned_expressions=[]),
                    attachment_required=False)


def default_evaluation_items() -> list[EvalItem]:
    return [EvalItem(item_code=code, item_name=code, max_score=m, description=code) for code, m in EVAL_ITEMS]
