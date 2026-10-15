"""결과 통합 T-C4 — 조율 Agent의 Task (기준 문서 시트 2 r18 · 시트 3 r161 ~ 167).

LLM · 검색 · 이미지 · 파일 창구를 부르지 않는다(등록 uses_llm=False). 등록 종류가 task라 엔진이 tools와 함께 부르지만 쓰지 않는다.
계획서 파일(DOCX · HWP · PDF)은 만들지 않는다 — 웹이 planDoc으로 내려받기 파일을 만든다(웹팀 · 담당자 동의).

1. 누락 검사 — 맞는 경우를 모두 모아 ContractError 하나(E-C4-MISSING, 잠정)를 올린다. 엔진이 운영 오류로 실행을 실패시킨다
   (관리자 알림 · 사용자에게는 E-RUN-FAIL). 메시지에는 경우 번호와 빠진 산출물 키 이름만 싣는다(내용 · 파일 이름 · 키 없음).
   ① 계획서 · 프로토타입 · 인포그래픽 · 점수 보고서 중 없는 것  ② 계획서 항목 0개  ④ 점수 보고서에 검증-2 점수 없음.
   진입 파일 없음은 누락이 아니다(entryFile을 읽지 않는다 — 검증-2가 통과 필수 조건 entry로 판정하면 미달 항목으로 보인다).
   안내 문서 없음도 막지 않는다.
2. 미달 항목(shortfallItems) — 판정 칸(status · inputError · passed · applicable · gateFailures · withheld · 목록)으로만 가른다.
   담당자 글(issues · detail)은 사유로 옮기기만 한다.
   - 문서층: 검증-1 항목 판정의 status fail만(총점이 통과여도). 입력 오류면 inputError, 아니면 verifyFail. warning은 넣지 않는다.
   - 산출물층: 통과 필수 조건 실패면 어긴 조건마다 gateFailure만. 아니면 코드 점검(만점 아님 · 해당 있음 — 부분 점수 포함) →
     대조 불가면 featureMatchWithheld 하나만, 아니면 빠진 기능 → 부분 인정 기능.
   - 점수는 화면에 보이는 값: 문서층 = docScore 항목 줄, 코드 점검 = 점수 보고서 환산 칸(codeCheckItems)의 earned · weight,
     대조 불가 = featureMatchScore · featureMatchMax. 환산 칸이 빈 옛 보고서는 flow/score_scale의 scaled_report_fields로
     한 번 계산한다(환산 공식을 여기 다시 쓰지 않는다).
3. 안내 문구(userMessage, 잠정) — 미달 항목이 없고 총점 통과면 기준 문서 예시 한 줄. 아니면 그 줄 · 총점 미달 줄 · 층별 항목 줄 ·
   본인 검토 안내 줄.
4. 결과물 묶음 — 계획서 파일 칸은 비우고, 프로토타입 파일 = 진입 파일(있으면) · 안내 문서(있으면) · 자산 순, 고지 4칸은 기획서 6-8.
미달 항목 · 안내 문구는 산출물 값 안에만 있다 — 기록 · 사건 · 로그 · 관리자 조회 · 예외 메시지에 넣지 않는다.
"""
from __future__ import annotations

from ...contracts.tasks import TC4In, TC4Out
from ...flow.score_scale import scaled_report_fields, score_maxes
from ...models import CodeCheck, Deliverable, ScoreReport, SectionResult, ShortfallItem
from ...orchestrator.errors import ContractError
from ...orchestrator.tools import Tools
from .readme import PROTOTYPE_NOTICE

# 기획서 6-8 고정 문구 (AI 생성 고지 PROTOTYPE_NOTICE는 안내 문서 실구현 쪽 상수를 쓴다)
DISCLAIMER = "본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다."
SCORE_NOTICE = "검증 점수는 서비스 내부 기준(rubric 상수)에 따른 값이며 실제 심사 점수가 아닙니다."
SUBMISSION_NOTICE = "공고에 따라 AI 작성 문서의 제출을 제한하거나 명시를 요구할 수 있습니다. 제출 요건을 확인해주세요."

# 누락 오류 코드 (잠정 · 확장 — orchestrator/errors.py ERROR_CODES)
MISSING_CODE = "E-C4-MISSING"
# 누락 경우 번호 (③ '진입 파일 없음'은 누락이 아니라 번호를 쓰지 않는다)
CASE_ABSENT, CASE_NO_SECTIONS, CASE_NO_ARTIFACT_SCORE = "①", "②", "④"
# ①에서 보는 입력과 산출물 키 (메시지에 싣는 이름 — 이 순서)
ABSENT_KEYS = (("plan_doc", "planDoc"), ("prototype", "prototype"), ("infographic", "infographic"),
               ("score_report", "scoreReport.overall"))
SECTIONS_KEY = "planDoc.sections"
ARTIFACT_SCORE_KEY = "scoreReport.overall.artifactScore"

# 미달 항목 고정 이름 · 사유 (잠정, PROVISIONAL tc4.shortfall)
VERIFY_FAIL_REASON = "fail"                     # 검증-1 판정의 issues가 비었을 때
GATE_NAMES = {"entry": "진입 파일", "secret": "비밀값 노출", "sandbox": "sandbox 제한"}
GATE_REASONS = {
    "entry": "실행할 진입 파일이 없어 산출물층이 0점입니다.",
    "secret": "코드에 비밀값(API 키 등)이 들어 있어 산출물층이 0점입니다.",
    "sandbox": "허용되지 않은 브라우저 기능(저장소 등)을 써서 산출물층이 0점입니다.",
}
CODE_CHECK_REASON = "만점을 받지 못했습니다."        # 코드 점검 줄의 detail이 빈 글일 때
WITHHELD_NAME = "계획서 대조"
WITHHELD_REASON = "계획서 대조를 판정하지 못해 0점으로 합산했습니다(대조 불가)."
MISSING_FEATURE_REASON = "프로토타입에서 이 기능을 찾지 못했습니다."
PARTIAL_FEATURE_REASON = "프로토타입에 이 기능의 일부만 있습니다."

# 안내 문구 (잠정, PROVISIONAL tc4.userMessage) — 첫 줄은 기준 문서 T-C4 예시 그대로
READY_MESSAGE = "계획서 · 프로토타입 · 검증 결과를 내려받을 수 있습니다."
TOTAL_SHORT_LINE = "총점 {score}점으로 기준 점수 {threshold}점에 미달합니다."   # 기준 문서 T-C4 Failure ②
LAYER_HEADINGS = {"document": "계획서에서 보완이 필요한 항목:", "artifact": "프로토타입에서 보완이 필요한 항목:"}
REVIEW_LINE = "제출 전 작성자 본인의 검토가 필요합니다."


def _num(value: float) -> str:
    return f"{value:g}"


# ── 누락 검사 ───────────────────────────────────────────
def missing_cases(inp: TC4In) -> list[tuple[str, str]]:
    """맞는 누락 경우 (경우 번호, 빠진 산출물 키) — ① → ② → ④ 순서, 맞는 것을 모두."""
    found = [(CASE_ABSENT, key) for field, key in ABSENT_KEYS if getattr(inp, field) is None]
    if inp.plan_doc is not None and not inp.plan_doc.sections:
        found.append((CASE_NO_SECTIONS, SECTIONS_KEY))
    if inp.score_report is not None and inp.score_report.artifact_score is None:
        found.append((CASE_NO_ARTIFACT_SCORE, ARTIFACT_SCORE_KEY))
    return found


def missing_error(found: list[tuple[str, str]]) -> ContractError:
    """'E-C4-MISSING <경우 번호들>: <키 이름들>' — 내용 · 파일 이름 · 키는 넣지 않는다."""
    marks = "".join(dict.fromkeys(mark for mark, _ in found))
    return ContractError(f"{MISSING_CODE} {marks}: {', '.join(key for _, key in found)}")


# ── 미달 항목 ───────────────────────────────────────────
def document_items(results: list[SectionResult] | None, inp: TC4In) -> list[ShortfallItem]:
    """문서층 — 검증-1 판정 status fail 항목만(판정 목록 순서 = 양식 순서). 판정 목록이 없으면 없음."""
    titles = {s.section_code: s.title for s in inp.plan_doc.sections}
    scores = {it.item_code: it for it in inp.score_report.doc_score.items}
    items = []
    for r in results or []:
        if r.status != "fail":
            continue
        row = scores.get(r.section_code)
        items.append(ShortfallItem(
            layer="document", kind="inputError" if r.input_error else "verifyFail", code=r.section_code, tag=r.tag,
            name=titles.get(r.section_code) or r.section_code,
            score=row.score if row is not None else None, max_score=row.max_score if row is not None else None,
            reason=" · ".join(r.issues) or VERIFY_FAIL_REASON))
    return items


def _scaled(report: ScoreReport) -> tuple[list[CodeCheck], float | None, float | None]:
    """점수 보고서 환산 칸 (코드 점검 항목 줄 · 대조 환산 점수 · 대조 만점). 빈 옛 보고서는 환산 모듈로 한 번 계산한다."""
    if report.code_check_items and report.feature_match_score is not None:
        return report.code_check_items, report.feature_match_score, report.feature_match_max
    fields = scaled_report_fields(score_maxes(report.settings_snapshot), report.artifact_score)
    return fields["code_check_items"], fields["feature_match_score"], fields["feature_match_max"]


def artifact_items(report: ScoreReport) -> list[ShortfallItem]:
    """산출물층 — 통과 필수 조건 실패면 그 줄만, 아니면 코드 점검 → 대조 불가 하나 또는 빠진 · 부분 인정 기능."""
    art = report.artifact_score
    cc, fm = art.code_check, art.feature_match
    if cc.gate_failures:
        return [ShortfallItem(layer="artifact", kind="gateFailure", code=g, name=GATE_NAMES[g], reason=GATE_REASONS[g])
                for g in cc.gate_failures]
    scaled_checks, fm_score, fm_max = _scaled(report)
    scaled = {ch.no: ch for ch in scaled_checks}
    items = []
    for ch in sorted(cc.checks, key=lambda x: x.no):
        if ch.passed or not ch.applicable:
            continue
        row = scaled.get(ch.no)
        items.append(ShortfallItem(
            layer="artifact", kind="codeCheck", code=str(ch.no), name=ch.name,
            score=row.earned if row is not None else None, max_score=row.weight if row is not None else None,
            reason=(row.detail if row is not None else "") or CODE_CHECK_REASON))
    if fm.withheld:
        items.append(ShortfallItem(layer="artifact", kind="featureMatchWithheld", name=WITHHELD_NAME,
                                   score=fm_score, max_score=fm_max, reason=WITHHELD_REASON))
        return items
    items += [ShortfallItem(layer="artifact", kind="missingFeature", name=f, reason=MISSING_FEATURE_REASON)
              for f in fm.missing_features]
    items += [ShortfallItem(layer="artifact", kind="partialFeature", name=f, reason=PARTIAL_FEATURE_REASON)
              for f in fm.partial_features]
    return items


def shortfall_items(inp: TC4In) -> list[ShortfallItem]:
    """미달 항목 — 문서층 → 산출물층 (순서는 잠정)."""
    return document_items(inp.section_results, inp) + artifact_items(inp.score_report)


# ── 안내 문구 ───────────────────────────────────────────
def _item_line(item: ShortfallItem) -> str:
    points = (f" ({_num(item.score)}/{_num(item.max_score)}점)"
              if item.score is not None and item.max_score is not None else "")
    return f"- {item.name}{points}: {item.reason}"


def user_message(report: ScoreReport, items: list[ShortfallItem]) -> str:
    """안내 문구 (잠정) — 총점 미달은 점수 보고서의 passed 칸으로 가르고, 줄에는 표시 값(displayScore · threshold)을 쓴다."""
    if report.passed and not items:
        return READY_MESSAGE
    lines = [READY_MESSAGE]
    if not report.passed:
        lines.append(TOTAL_SHORT_LINE.format(score=_num(report.display_score), threshold=_num(report.threshold)))
    for layer, heading in LAYER_HEADINGS.items():
        group = [i for i in items if i.layer == layer]
        if group:
            lines.append(heading)
            lines += [_item_line(i) for i in group]
    lines.append(REVIEW_LINE)
    return "\n".join(lines)


# ── Task 함수 ───────────────────────────────────────────
def run(inp: TC4In, tools: Tools) -> TC4Out:
    """결과 통합 — 누락이면 E-C4-MISSING으로 실패, 아니면 계획서 파일 없이 미달 항목 · 안내 문구가 든 결과물 묶음.
    tools는 받지만 부르지 않는다(LLM · 검색 · 이미지 · 파일 창구 없음)."""
    found = missing_cases(inp)
    if found:
        raise missing_error(found)
    items = shortfall_items(inp)
    proto = inp.prototype
    proto_files = [f for f in (proto.entry_file, proto.readme_file) if f is not None] + list(proto.asset_files)
    d = Deliverable(plan_doc_file=None, prototype_files=proto_files, infographic_file=inp.infographic.image_file,
                    score_report=inp.score_report, proofread_log=inp.proofread_log, disclaimer=DISCLAIMER,
                    prototype_notice=PROTOTYPE_NOTICE, score_notice=SCORE_NOTICE, submission_notice=SUBMISSION_NOTICE,
                    shortfall_items=items)
    return TC4Out(deliverable=d, user_message=user_message(inp.score_report, items))


__all__ = [
    "CODE_CHECK_REASON", "DISCLAIMER", "GATE_NAMES", "GATE_REASONS", "LAYER_HEADINGS", "MISSING_CODE",
    "MISSING_FEATURE_REASON", "PARTIAL_FEATURE_REASON", "READY_MESSAGE", "REVIEW_LINE", "SCORE_NOTICE",
    "SUBMISSION_NOTICE", "TOTAL_SHORT_LINE", "VERIFY_FAIL_REASON", "WITHHELD_NAME", "WITHHELD_REASON",
    "artifact_items", "document_items", "missing_cases", "missing_error", "run", "shortfall_items", "user_message",
]
