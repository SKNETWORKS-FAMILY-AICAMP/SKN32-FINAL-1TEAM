"""양식 · 평가 항목 · 채점 기준표 (잠정) — 선택 공고의 기본 양식과, 작업 분해(T-C3)가 고르는 신청자 유형별 묶음.

선택 공고의 기본 양식(default_form_spec · default_evaluation_items)
  공고 서버는 양식 · 평가 항목을 주지 않는다. 스텁 공고와 공고 서버 연결(G-01)이 모두 이 자리 표시 값을 붙인다.
  뒷 단계는 이 값을 읽지 않는다 — 기준은 T-C3가 고른 묶음이다 (T-C3 spec 2.2 · 4, settings PROVISIONAL
  announcement.formSpec).

신청자 유형별 묶음(FORM_TABLE) — 시트 2 T-C3 "양식 · 평가항목 · rubric을 신청자 유형에 따라 미리 정해 둔 것 중에서 고른다"
  묶음 = 양식 FormSpec + 평가 항목 list[EvalItem] + 채점 기준표 Rubric. T-C3가 신청자 유형으로 고른다(코드, LLM 아님).
  값은 잠정이다(사용자 결정 2026-10-04): 웹이 쓰는 두 계획서 양식(예비창업자 '예비창업패키지', 개인사업자 · 법인
  '초기창업패키지(일반형)')의 섹션 구조(PSST 4개, 웹 섹션 태그와 같은 코드)에 맞추고, 평가 항목 · 채점 기준표는 기본값이다.
  담당자 회신이 오면 이 표만 바꾼다 (settings PROVISIONAL taskPlan.formTable). 섹션 코드가 바뀌면 웹 계획서 내려받기가
  고정 태그로 본문을 찾으므로 웹팀에도 알린다. 문서층 70점 · 스텁 배점 · 문서층 재작성 묶음 이름과 어긋나는지도 본다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import EvalItem, FormatSpec, FormSpec, Rubric, RubricItem

# 평가 항목 (코드, 배점) — 문서층 70점 (잠정)
EVAL_ITEMS: tuple[tuple[str, float], ...] = (("문제인식", 20.0), ("실현가능성", 20.0), ("성장전략", 15.0), ("팀구성", 15.0))


# ── 선택 공고의 기본 양식 (자리 표시 값) ─────────────────────
def default_form_spec() -> FormSpec:
    return FormSpec(form_version="예비-2026", applicant_types=["예비창업자", "개인사업자", "법인"],
                    section_codes=["1-1", "2-1", "3-3"], section_titles=["문제인식", "실현가능성", "성장전략"],
                    format_spec=_default_format(), attachment_required=False)


def default_evaluation_items() -> list[EvalItem]:
    return [EvalItem(item_code=code, item_name=code, max_score=m, description=code) for code, m in EVAL_ITEMS]


def stub_rubric() -> Rubric:
    """기본 채점 기준표 (잠정) — 평가 항목과 1:1. 신청자 유형별 묶음과 스텁 상수 공급처가 함께 쓴다."""
    return Rubric(rubric_id="rubric-stub", version="stub-1", items=[
        RubricItem(item_code=code, criteria=["기준"], score_bands=[{"min": 0, "max": m, "label": "구간"}],
                   evidence_required=True) for code, m in EVAL_ITEMS])


def _default_format() -> FormatSpec:
    # 서술 형식 기본값 (잠정) — 개조식 · 단정형 · 금지 표현 없음
    return FormatSpec(style_type="개조식", ending_rule="단정형", banned_expressions=[])


# ── 신청자 유형별 묶음 (작업 분해 T-C3가 고른다) ─────────────────
@dataclass
class FormBundle:
    """양식 · 평가 항목 · 채점 기준표 한 묶음."""
    form_spec: FormSpec
    evaluation_items: list[EvalItem]
    rubric: Rubric

    def copy(self) -> "FormBundle":
        return FormBundle(self.form_spec.model_copy(deep=True),
                          [e.model_copy(deep=True) for e in self.evaluation_items],
                          self.rubric.model_copy(deep=True))


# 웹 계획서 양식의 본문 섹션 (PSST) — 섹션 코드는 웹 섹션 태그(PLAN_SECTION_TAG_*)와 같다 (잠정)
PLAN_SECTIONS: tuple[tuple[str, str], ...] = (("1-1", "문제인식"), ("2-1", "실현가능성"), ("3-1", "성장전략"),
                                              ("4-1", "팀 구성"))


def _plan_bundle(form_version: str, applicant_types: list[str]) -> FormBundle:
    form = FormSpec(form_version=form_version, applicant_types=applicant_types,
                    section_codes=[code for code, _ in PLAN_SECTIONS],
                    section_titles=[title for _, title in PLAN_SECTIONS],
                    max_chars_per_section=None, format_spec=_default_format(), attachment_required=False)
    return FormBundle(form, default_evaluation_items(), stub_rubric())


_PRE_STARTUP = _plan_bundle("예비창업패키지(잠정)", ["예비창업자"])               # 예비창업패키지 (잠정)
_EARLY_STARTUP = _plan_bundle("초기창업패키지-일반형(잠정)", ["개인사업자", "법인"])  # 초기창업패키지(일반형) (잠정)

# 신청자 유형 → 묶음 (잠정). 고르는 함수가 부를 때마다 이 표를 읽는다(테스트는 표를 바꿔 끼워 E-C3-FORM을 만든다)
FORM_TABLE: dict[str, FormBundle] = {"예비창업자": _PRE_STARTUP, "개인사업자": _EARLY_STARTUP, "법인": _EARLY_STARTUP}

# 고른 묶음의 불변식 — 어기면 E-C3-FORM: <사유 이름> (시트 6 E-C3-FORM, 사유 이름은 T-C3 spec 3.3)
FORM_PROBLEMS: tuple[str, ...] = ("유형 양식 없음", "유형 불일치", "섹션 없음", "섹션 수 불일치", "평가항목 없음",
                                  "기준표 불일치")


def form_problem(applicant_type: str) -> str | None:
    """그 신청자 유형의 묶음이 어긴 첫 불변식의 사유 이름. 다 지키면 None."""
    bundle = FORM_TABLE.get(applicant_type)
    if bundle is None:
        return "유형 양식 없음"
    form = bundle.form_spec
    if applicant_type not in form.applicant_types:
        return "유형 불일치"
    if not form.section_codes:
        return "섹션 없음"
    if len(form.section_codes) != len(form.section_titles):
        return "섹션 수 불일치"
    if not bundle.evaluation_items:
        return "평가항목 없음"
    eval_codes = [e.item_code for e in bundle.evaluation_items]
    rubric_codes = [r.item_code for r in bundle.rubric.items]
    if set(rubric_codes) != set(eval_codes) or len(rubric_codes) != len(eval_codes):   # 1:1 (시트 4 RubricItem)
        return "기준표 불일치"
    return None


def select_form(applicant_type: str) -> FormBundle:
    """그 신청자 유형의 묶음(사본). 불변식 확인은 form_problem으로 먼저 한다 — 표에 없으면 KeyError."""
    return FORM_TABLE[applicant_type].copy()
