"""양식 · 평가 항목 · 채점 기준표 (잠정) — 선택 공고의 기본 양식과, 작업 분해(T-C3)가 고르는 신청자 유형별 묶음.

선택 공고의 기본 양식(default_form_spec · default_evaluation_items)
  공고 서버는 양식 · 평가 항목을 주지 않는다. 스텁 공고와 공고 서버 연결(G-01)이 모두 이 자리 표시 값을 붙인다.
  뒷 단계는 이 값을 읽지 않는다 — 기준은 T-C3가 고른 묶음이다 (T-C3 spec 2.2 · 4, settings PROVISIONAL
  announcement.formSpec).

신청자 유형별 묶음(FORM_TABLE) — 시트 2 T-C3 "양식 · 평가항목 · rubric을 신청자 유형에 따라 미리 정해 둔 것 중에서 고른다"
  묶음 = 양식 FormSpec + 평가 항목 list[EvalItem] + 채점 기준표 Rubric. T-C3가 신청자 유형으로 고른다(코드, LLM 아님).
  전략 · 작성 · 검증-1 담당자 양식으로 만든다(spec 4.6, 결정 0024): 예비창업자 → 담당자 문서 유형 pre_startup
  (2.1.1 ~ 2.7.4, 25개), 개인사업자 · 법인 → early_startup(3.1.1 ~ 3.7.4, 24개). 항목 · 제목 · 종류는 담당자
  execution_contract.json에서 읽는다(손으로 옮겨 적지 않음 — 담당자 새 판을 받으면 저절로 따라간다).
  - 항목마다 웹 태그(sectionTags)는 flow/rework_map.py의 짝짓기 표에서 끌어낸다(잠정 — 담당자 · 웹 확인 대기).
  - 평가항목 = 계획서 항목 하나하나: itemCode = 항목 번호, itemName = 제목 앞 40자(잠정), maxScore = 기본 문서층 배점
    (70) ÷ 항목 수, description = 제목 전체. 실행 때 쓰는 문서층 배점은 실행 설정(scoring.docLayerMax)이다.
  - 채점 기준표 = 평가항목과 1:1: rubricId 'partner-sw', version = 담당자 채점 정책 버전(evaluation_rubric.json),
    criteria = 담당자 항목 기준(criteria_registry, 없으면 제목), scoreBands = [{min 0, max maxScore}], evidenceRequired 참.
  - formVersion = '<담당자 문서 유형>@<계약 버전>'. 일반형(general) 계약은 데이터로 남지만 고르지 않는다.
  settings PROVISIONAL taskPlan.formTable. 항목 번호가 바뀌면 웹 계획서 내려받기 · 문서층 재작성 묶음과 어긋나는지 본다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..flow.rework_map import section_tags
from ..models import EvalItem, FormatSpec, FormSpec, Rubric, RubricItem
from ..orchestrator.settings import ScoringSettings
from .partner_sw import contract as partner

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


# 평가항목 배점 기준 — 기본 문서층 배점(실행 설정 scoring.docLayerMax의 기본값 70). 항목 배점 = 이 값 ÷ 항목 수
DOC_LAYER_BASE: float = ScoringSettings().doc_layer_max
ITEM_NAME_CHARS = 40          # 평가항목 이름 = 항목 제목 앞 40자 (잠정)
PARTNER_RUBRIC_ID = "partner-sw"


def _partner_bundle(document_type: str, applicant_types: list[str]) -> FormBundle:
    """담당자 문서 유형의 계약 항목으로 묶음을 만든다 (spec 4.6)."""
    specs = partner.document_specs(document_type)
    codes = [str(s["sectionId"]) for s in specs]
    titles = [str(s["title"]) for s in specs]
    form = FormSpec(form_version=f"{document_type}@{partner.CONTRACT_VERSION}", applicant_types=applicant_types,
                    section_codes=codes, section_titles=titles,
                    max_chars_per_section=None, format_spec=_default_format(), attachment_required=False,
                    section_tags=section_tags(codes), section_kinds=[s["contentType"] for s in specs])
    max_score = DOC_LAYER_BASE / len(codes)
    items = [EvalItem(item_code=code, item_name=title[:ITEM_NAME_CHARS], max_score=max_score, description=title)
             for code, title in zip(codes, titles)]
    rubric = Rubric(rubric_id=PARTNER_RUBRIC_ID, version=partner.SCORE_POLICY_VERSION, items=[
        RubricItem(item_code=code, criteria=partner.section_criteria(document_type, code) or [title],
                   score_bands=[{"min": 0, "max": max_score}], evidence_required=True)
        for code, title in zip(codes, titles)])
    return FormBundle(form, items, rubric)


_PRE_STARTUP = _partner_bundle(partner.PRE_STARTUP, ["예비창업자"])                 # 예비창업패키지 양식
_EARLY_STARTUP = _partner_bundle(partner.EARLY_STARTUP, ["개인사업자", "법인"])      # 초기창업패키지 양식

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
    """그 신청자 유형의 묶음(사본). 불변식 확인은 form_problem으로 먼저 한다 — 표에 없으면 KeyError.

    웹 태그(sectionTags)는 고를 때마다 짝짓기 표(flow/rework_map.py)에서 다시 끌어낸다 — 표만 바꾸면 따라간다."""
    bundle = FORM_TABLE[applicant_type].copy()
    bundle.form_spec.section_tags = section_tags(bundle.form_spec.section_codes)
    return bundle
