"""기준 문서 확장 표시 — 기준 문서(기능정의서 v1.10 · v1.11)에 들어간 필드는 ext() 표시가 없고, 새 판에서 빠졌지만 남긴
필드와 아직 기준 문서에 없는 필드는 ext()로 표시한다 (extension_fields는 JSON 이름을 돌려준다)."""
from __future__ import annotations

import pytest

from sbrain.contracts import tasks as c
from sbrain.models import (
    Announcement, AnnouncementCard, BudgetItem, ChartSpec, CheckResult, CodeCheck, CodeCheckResult, CompanyInfo,
    Deliverable, DiagramSpec, FeatureMatchResult, FileRef, FormSpec, GateResult, Infographic, Notification, PlanDoc,
    PlanSection, PreInput, Prototype, ReworkComparison, ReworkInput, Run, ScheduleItem, ScoreReport, SectionResult,
    ShortfallItem, TaskInstruction, TeamMemberEntry, Verify1State, extension_fields,
)
from sbrain.models.domain import FILE_NOTE, NEW_TYPE_NOTE
from sbrain.orchestrator.settings import RetrySettings, ScoringSettings, TaskModelSetting
from sbrain.flow.reads import DocumentScreen, Outputs, ResultScreen, ReworkFileChange, TableFallback
from sbrain.orchestrator.trace import ExecutionRecord

FORM_FIELDS = {"revenueItems", "companyName", "bizType", "representativeType", "outputSummary", "techField",
               "regionalPriorityArea", "occupation", "representativeCapability", "selfInKindResources"}
# 사업비 · 일정 · 팀원 역할 · 목표 고객 · 창업아이템명 · 팀원 표 행 (기능정의서 v1.11에 들어감)
FORM_FIELDS_V111 = {"budgetItems", "scheduleItems", "teamRoleCareers", "targetCustomer", "startupItemName",
                    "teamMemberRows"}

# 기준 문서(v1.10)에 들어간 필드 — 확장 아님
IN_BASEDOC = [
    (CompanyInfo, FORM_FIELDS),
    (PreInput, FORM_FIELDS),
    (Run, {"projectId"}),
    (c.SentenceResult, {"attempts"}),
    (GateResult, {"unknownConditions"}),
    (Announcement, {"applyPeriodType"}),
    (AnnouncementCard, {"applyPeriodType", "contentChanged", "contentVersion", "bonusScore", "bonusItems"}),
    (c.G01In, {"announcementId"}),
    (c.G01Out, {"selectedAnnouncement"}),
    (c.TC3In, {"businessAgeYears"}),
    (c.TC3Out, {"formSpec", "evaluationItems", "rubric"}),
    (TaskInstruction, {"guidance"}),
    (c.TV2In, {"planDoc"}),
    (c.TV2Out, {"diagnostics"}),
    (CodeCheckResult, {"gateFailures"}),
    (CodeCheck, {"defectSources"}),
    (FeatureMatchResult, {"withheld", "withheldReason", "partialFeatures"}),
    (c.TB1In, {"planDoc"}),
]

# 기능정의서 v1.11에 들어간 필드 — 확장 아님 (우리가 확장으로 더했던 칸)
IN_BASEDOC_V111 = [
    (CompanyInfo, FORM_FIELDS_V111),
    (PreInput, FORM_FIELDS_V111),
    (FormSpec, {"sectionTags", "sectionKinds"}),
    (PlanSection, {"tag", "contentType"}),
    (PlanDoc, {"diagrams"}),
    (ChartSpec, {"imageFile"}),
    (Prototype, {"entryFile", "assetFiles", "readmeFile"}),
    (Infographic, {"imageFile", "iconFallback"}),
    (Deliverable, {"planDocFile", "prototypeFiles", "infographicFile", "proofreadLog", "shortfallItems"}),
    (ReworkInput, {"previousSourceFile"}),
    (CodeCheck, {"earned", "applicable"}),
    (ScoreReport, {"docLayerMax", "codeCheckScore", "codeCheckMax", "featureMatchScore", "featureMatchMax",
                   "artifactLayerScore", "artifactLayerMax", "codeCheckItems"}),
    (c.TS1In, {"companyInfo", "formInput"}),
    (c.TS1Out, {"strategyData"}),
    (c.TS2Out, {"marketStrategyData"}),
    (c.TW1In, {"strategyData", "marketStrategyData"}),
    (c.TW2Out, {"diagrams"}),
    (c.TV1In, {"strategyData", "marketStrategyData"}),
    (c.TV1Out, {"sectionResults"}),
    (c.TV2In, {"featureElements"}),
    (c.TV2Out, {"featureElements"}),
    (c.TB1Out, {"entryFile"}),
    (c.G02bIn, {"category"}),
    (c.G04Out, {"readmeFile"}),
    (c.TC4In, {"planDoc", "prototype", "infographic", "scoreReport", "proofreadLog", "sectionResults"}),
    # 시트 1 재시도 간격 · 시트 4 ScoreReport.settingsSnapshot 층별 배점
    (RetrySettings, {"backoffMultiplier", "jitterRatio", "retryAfterCapSec", "waitCapSec", "waitCapByKey"}),
    (ScoringSettings, {"codeCheckMax", "featureMatchMax"}),
]

# 기능정의서 v1.11에 들어간 타입 — 칸이 모두 확장이 아니다
TYPES_V111 = [BudgetItem, ScheduleItem, TeamMemberEntry, DiagramSpec, SectionResult, ShortfallItem, FileRef]

# 새 판(v1.10)에서 빠졌지만 남긴 필드 — 확장
DROPPED_KEPT = [
    (CompanyInfo, {"revenueUnitPrice", "isFirstStartup"}),
    (PreInput, {"revenueUnitPrice", "isFirstStartup"}),
    (c.G01In, {"eligibility", "eligibilityParsed"}),
]

# 기준 문서에 아직 없는 필드(대표) — 확장
STILL_EXTENSION = [
    (TaskModelSetting, {"reasoningEffort", "imageModel"}),
    (c.G04Out, {"check"}),
    (c.TP2Out, {"nextRedoHint"}),
    (c.TC1Out, {"categoryDefaulted"}),
    (ExecutionRecord, {"inputTokens"}),
    (Run, {"segment", "queue", "createdAt"}),
    (ReworkComparison, {"cycleId", "screen", "basis", "comparedAt"}),
    (ReworkInput, {"sourceRefs", "feedbackId"}),
    (c.TC3In, {"priorGuidance"}),
    (c.G02aIn, {"cycleInfo"}),
    (Notification, {"notificationId"}),
    (ScoringSettings, {"deviationCap"}),
    # 전략 · 작성 · 검증-1 연동
    (TaskModelSetting, {"purposeModels"}),
    (CheckResult, {"failedItems"}),
    (ReworkInput, {"targetItems", "redoSource", "unit", "fallbackItems"}),
    (Run, {"verify1"}),
    (c.TS2In, {"strategyData"}),
    (c.TW1In, {"featureList", "basePlanDoc", "baseSectionOutputs"}),
    (c.TW2In, {"strategyData", "featureList", "baseDiagrams"}),
    (c.TW3In, {"strategyData", "formSpec"}),
    (c.TV1In, {"featureList", "formSpec", "sectionOutputs", "baseSectionResults"}),
    (c.TV1Out, {"scorePolicyVersion"}),
    (c.G02aIn, {"sectionResults"}),
    (c.G02bIn, {"sectionResults"}),
    (c.M1In, {"diagrams", "tableSections"}),
    # 담당자 10-12 새 판 뒷정리 — 입력 오류 · 표 대체 사유 화면 칸
    (DocumentScreen, {"tableFallbacks"}),
    (ResultScreen, {"tableFallbacks"}),
    (Outputs, {"tableFallbacks"}),
    (TableFallback, {"sectionCode", "reason", "displayReason"}),
]

# 기준 문서에 없는 새 타입 — 칸은 모두 확장이고, 이 타입을 담는 칸의 note가 NEW_TYPE_NOTE로 시작한다
NEW_TYPES = [Verify1State]
NEW_TYPE_HOLDERS = [(Run, {"verify1"})]

# 기준 문서 타입에 없는 모양(합치기 입력 · 화면)의 파일 칸 — 확장, note FILE_NOTE
FILE_REF_EXTENSION_FIELDS = [
    (c.M3In, {"readmeFile"}),
    (ReworkFileChange, {"beforeFile", "afterFile"}),
]


def _ids(cases):
    return [m.__name__ for m, _ in cases]


@pytest.mark.parametrize(("model", "names"), IN_BASEDOC + IN_BASEDOC_V111, ids=_ids(IN_BASEDOC + IN_BASEDOC_V111))
def test_basedoc_fields_are_not_extensions(model, names):
    aliases = {info.alias or n for n, info in model.model_fields.items()}
    assert names <= aliases                                  # 이름이 그대로 있다
    assert not names & set(extension_fields(model))
    props = model.model_json_schema(by_alias=True)["properties"]
    assert all("x-extension" not in props[n] for n in names)


@pytest.mark.parametrize("model", TYPES_V111, ids=[m.__name__ for m in TYPES_V111])
def test_basedoc_v111_types_have_no_extensions(model):
    assert extension_fields(model) == []


@pytest.mark.parametrize(("model", "names"), DROPPED_KEPT, ids=_ids(DROPPED_KEPT))
def test_dropped_but_kept_fields_are_extensions(model, names):
    assert names <= set(extension_fields(model))
    props = model.model_json_schema(by_alias=True)["properties"]
    assert all(props[n]["x-note"].startswith("새 판(v1.10)에서 빠졌지만 남김 — ") for n in names)


@pytest.mark.parametrize(("model", "names"), STILL_EXTENSION, ids=_ids(STILL_EXTENSION))
def test_other_extensions_stay(model, names):
    assert names <= set(extension_fields(model))


@pytest.mark.parametrize(("model", "names"), FILE_REF_EXTENSION_FIELDS, ids=_ids(FILE_REF_EXTENSION_FIELDS))
def test_file_ref_extension_fields_have_note(model, names):
    assert names <= set(extension_fields(model))
    props = model.model_json_schema(by_alias=True)["properties"]
    assert all(props[n]["x-note"] == FILE_NOTE for n in names)


@pytest.mark.parametrize("model", NEW_TYPES, ids=[m.__name__ for m in NEW_TYPES])
def test_new_types_fields_are_extensions(model):
    assert set(extension_fields(model)) == {info.alias or n for n, info in model.model_fields.items()}


@pytest.mark.parametrize(("model", "names"), NEW_TYPE_HOLDERS, ids=_ids(NEW_TYPE_HOLDERS))
def test_new_type_holders_note(model, names):
    props = model.model_json_schema(by_alias=True)["properties"]
    assert all(props[n]["x-note"].startswith(NEW_TYPE_NOTE) for n in names)


@pytest.mark.parametrize("model", [PreInput, CompanyInfo], ids=["PreInput", "CompanyInfo"])
def test_input_fix_fields_default_none_for_old_json(model):
    """칸이 없던 옛 JSON은 None — 팀원 표 행 None(모름)은 빈 목록(팀원 없음)과 다르다."""
    for name in ("target_customer", "startup_item_name", "team_member_rows"):
        assert model.model_fields[name].default is None and not model.model_fields[name].is_required()


def test_required_ness_unchanged():
    # 기준 문서는 필수지만 옛 실행 건 호환으로 선택 선언을 지킨다
    assert c.TV2In.model_fields["plan_doc"].default is None
    assert c.TB1In.model_fields["plan_doc"].default is None
    assert c.TS1In.model_fields["form_input"].default is None
    assert PreInput.model_fields["revenue_items"].default_factory is list
    # 확장으로 바꿔도 필수 · 기본값은 그대로
    assert PreInput.model_fields["revenue_unit_price"].is_required()
    assert CompanyInfo.model_fields["revenue_unit_price"].is_required()
    assert PreInput.model_fields["is_first_startup"].default is None
    assert c.G01In.model_fields["eligibility"].default is None
    assert c.G01In.model_fields["announcement_id"].is_required()
    assert c.G01Out.model_fields["selected_announcement"].is_required()
    # 확장 표시를 떼도 필수 · 기본값은 그대로 (기능정의서 v1.11)
    assert all(not f.is_required() for f in c.TC4In.model_fields.values())
    assert BudgetItem.model_fields["total_amount"].is_required() and BudgetItem.model_fields["phase"].default is None
    assert SectionResult.model_fields["status"].is_required() and SectionResult.model_fields["input_error"].default is False
    assert Deliverable.model_fields["shortfall_items"].default_factory is list
    assert CodeCheck.model_fields["earned"].default is None and CodeCheck.model_fields["applicable"].default is True
    assert RetrySettings().wait_cap_by_key == {"T-C1": 45.0}
