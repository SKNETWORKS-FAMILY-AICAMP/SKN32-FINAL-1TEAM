"""기준 문서 v1.10 확장 표시 — 새 판에 들어간 필드는 ext() 표시가 없고, 새 판에서 빠졌지만 남긴 필드와
아직 기준 문서에 없는 필드는 ext()로 표시한다 (extension_fields는 JSON 이름을 돌려준다)."""
from __future__ import annotations

import pytest

from sbrain.contracts import tasks as c
from sbrain.models import (
    Announcement, AnnouncementCard, CodeCheck, CodeCheckResult, CompanyInfo, FeatureMatchResult, GateResult,
    Notification, PreInput, ReworkComparison, ReworkInput, Run, TaskInstruction, extension_fields,
)
from sbrain.orchestrator.settings import TaskModelSetting
from sbrain.orchestrator.trace import ExecutionRecord

FORM_FIELDS = {"revenueItems", "companyName", "bizType", "representativeType", "outputSummary", "techField",
               "regionalPriorityArea", "occupation", "representativeCapability", "selfInKindResources"}

# 새 판(v1.10)에 들어간 필드 — 확장 아님
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
    (ReworkInput, {"previousSourceText"}),
]

# 새 판에서 빠졌지만 남긴 필드 — 확장
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
]


def _ids(cases):
    return [m.__name__ for m, _ in cases]


@pytest.mark.parametrize(("model", "names"), IN_BASEDOC, ids=_ids(IN_BASEDOC))
def test_basedoc_fields_are_not_extensions(model, names):
    aliases = {info.alias or n for n, info in model.model_fields.items()}
    assert names <= aliases                                  # 이름이 그대로 있다
    assert not names & set(extension_fields(model))
    props = model.model_json_schema(by_alias=True)["properties"]
    assert all("x-extension" not in props[n] for n in names)


@pytest.mark.parametrize(("model", "names"), DROPPED_KEPT, ids=_ids(DROPPED_KEPT))
def test_dropped_but_kept_fields_are_extensions(model, names):
    assert names <= set(extension_fields(model))
    props = model.model_json_schema(by_alias=True)["properties"]
    assert all(props[n]["x-note"].startswith("새 판(v1.10)에서 빠졌지만 남김 — ") for n in names)


@pytest.mark.parametrize(("model", "names"), STILL_EXTENSION, ids=_ids(STILL_EXTENSION))
def test_other_extensions_stay(model, names):
    assert names <= set(extension_fields(model))


def test_required_ness_unchanged():
    # 기준 문서는 필수지만 옛 실행 건 호환으로 선택 선언을 지킨다 (사용자 결정)
    assert c.TV2In.model_fields["plan_doc"].default is None
    assert c.TB1In.model_fields["plan_doc"].default is None
    assert PreInput.model_fields["revenue_items"].default_factory is list
    # 확장으로 바꿔도 필수 · 기본값은 그대로
    assert PreInput.model_fields["revenue_unit_price"].is_required()
    assert CompanyInfo.model_fields["revenue_unit_price"].is_required()
    assert PreInput.model_fields["is_first_startup"].default is None
    assert c.G01In.model_fields["eligibility"].default is None
    assert c.G01In.model_fields["announcement_id"].is_required()
    assert c.G01Out.model_fields["selected_announcement"].is_required()
