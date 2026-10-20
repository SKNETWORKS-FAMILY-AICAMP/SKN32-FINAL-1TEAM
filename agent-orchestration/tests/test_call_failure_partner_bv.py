"""호출 실패 처리 — 구현 · 검증-2 담당자 코드의 대체 경로.

- T-V2 대조 LLM(llm_judge — 요소 뽑기 · 판정 · 핵심 칸): 받은 소진이 결제 · 한도(billing_limit)면 다시 올린다 — 규칙 판정으로
  넘어가지 않고 재개 대기, 재개 상한을 넘으면 실행 실패(재작성 중이면 되돌림). 한도가 아닌 소진은 지금처럼 규칙 판정.
- T-B2 아이콘판(artsheet.generate의 넓은 받기): 한도 소진이면 다시 올린다(재개 대기, iconFallback · '이미지대체' 없음).
  한도가 아닌 소진은 지금처럼 기본 아이콘.
- '이미지대체' 사건 설명: 최종 실패한 이미지 호출의 마지막 시도 설명에 오류 코드가 있으면 끝에 ' (code=…)'.
메모리 · SQLite 두 저장소(store_backend), 네트워크 · 실제 대기 없음.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from bv_fake import CONTENT, EchoImage, respond_bv
from conftest import make_app, to_screen6, to_screen8
from flow_helpers import ctx_of, records_of_task, rework, state

from sbrain.agents.partner_bv.engineering_agent.infographic import artsheet, design
from sbrain.agents.partner_bv.tasks import bind_partner_bv
from sbrain.agents.partner_bv.verification_agent import llm_judge
from sbrain.flow.sbrain_flow import EVENT_IMAGE_FALLBACK, ICON_FALLBACK_DETAIL, IMAGE_FALLBACK_DETAIL
from sbrain.orchestrator.errors import ToolCallExhausted

FEATURES = ["회원 등록·조회", "수업 예약"]
PLAN = ("헬스온 사업계획서\n"
        "회원 등록·조회: 회원 정보를 입력하면 목록에 보여 준다.\n"
        "수업 예약: 수업을 고르면 예약을 확인한다.\n"
        "수익모델: 월 구독.")
HTML = "<html><body><button>회원 등록·조회</button><button>수업 예약</button></body></html>"


def billing() -> ToolCallExhausted:
    return ToolCallExhausted(error="호출실패", error_kind="일시", tries=1, call_id="c",
                             detail="status=429 code=insufficient_quota", code="insufficient_quota", billing_limit=True)


def transient() -> ToolCallExhausted:
    return ToolCallExhausted(error="호출실패", error_kind="일시", tries=6, call_id="c",
                             detail="status=503 code=server_is_overloaded", code="server_is_overloaded")


class RaisingTools:
    """llm(…, purpose=)가 fail(purpose)이 참인 목적에서 make()의 예외를 올리고, 그 밖은 '충족' 답을 돌려주는 작은 가짜 tools."""

    def __init__(self, make, fail) -> None:
        self.make, self.fail = make, fail

    def for_item(self, key):
        return self

    def llm(self, messages, *, parse=None, purpose="", **_):
        if self.fail(purpose):
            raise self.make()
        user = messages[-1]["content"]
        if purpose.startswith("계획서 대조 요소: "):
            reply = '{"elements": ["입력칸", "결과 표시"]}'
        elif "[확인할 요소]" in user:
            count = len(user.split("[확인할 요소]\n", 1)[1].splitlines())
            reply = '{"checks": [' + ", ".join(['{"element": "e", "reason": "있음", "present": true}'] * count) + "]}"
        else:
            reply = '{"reason": "계획서와 같다", "verdict": "충족"}'
        return parse(reply) if parse else reply


def element_stage(purpose: str) -> bool:
    return purpose.startswith("계획서 대조 요소: ")


def check_stage(purpose: str) -> bool:
    return purpose.startswith("계획서 대조: ")


# ── llm_judge 세 곳 ────────────────────────────────────────
@pytest.mark.parametrize("stage", [element_stage, check_stage], ids=["요소", "판정"])
def test_judge_reraises_billing_limit(stage):
    with pytest.raises(ToolCallExhausted) as e:
        llm_judge.make_judge(RaisingTools(billing, stage), "html", HTML, PLAN, {})(FEATURES)
    assert e.value.billing_limit and e.value.code == "insufficient_quota"


def test_judge_non_billing_keeps_fallbacks():
    store: dict = {}
    out = llm_judge.make_judge(RaisingTools(transient, element_stage), "html", HTML, PLAN, store)(FEATURES)
    assert store == {} and all(v == (1.0, "계획서와 같다") for v in out.values())   # 통째로 묻는 판정(지금 동작)
    out = llm_judge.make_judge(RaisingTools(transient, check_stage), "html", HTML, PLAN, {})(FEATURES)
    assert out == {f: None for f in FEATURES}                                      # 규칙 판정으로 대체(지금 동작)


def test_field_judge_reraises_billing_limit_only():
    with pytest.raises(ToolCallExhausted) as e:
        llm_judge.make_field_judge(RaisingTools(billing, check_stage), PLAN)({"문제 정의": "회원 관리"})
    assert e.value.billing_limit
    assert llm_judge.make_field_judge(RaisingTools(transient, check_stage), PLAN)(
        {"문제 정의": "회원 관리"}) == {"문제 정의": None}


# ── artsheet.generate ──────────────────────────────────────
class ImageTools:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def image(self, prompt, **_):
        raise self.error


def _content() -> dict:
    data = design.apply("원페이지", dict(CONTENT, feature_details=[d["detail"] for d in CONTENT["feature_details"]]))
    assert artsheet.icon_items("원페이지", data)                                    # 아이콘 항목이 있어 이미지를 부른다
    return data


def test_artsheet_reraises_billing_limit():
    with pytest.raises(ToolCallExhausted) as e:
        artsheet.generate("원페이지", _content(), ImageTools(billing()))
    assert e.value.billing_limit


@pytest.mark.parametrize("error", [transient(), ValueError("그림 해석 오류")], ids=["소진", "그 밖"])
def test_artsheet_other_failures_still_default_icon(error):
    assert artsheet.generate("원페이지", _content(), ImageTools(error)) is None


# ── 흐름: T-V2 ─────────────────────────────────────────────
def bv_app(clock, **kw):
    app = make_app(clock, **kw)
    bind_partner_bv(app.registry)
    respond_bv(app.llm)
    return app


def _resume_until_done(app, clock, rid: str) -> int:
    """재개대기면 다음 재개 시각 뒤로 시계를 옮겨 tick — 재개대기가 아닐 때까지. 재개한 횟수를 돌려준다."""
    count = 0
    while app.store.load_run(rid).state.progress == "재개대기":
        assert count < 10
        clock.t = app.store.load_run(rid).next_resume_at + timedelta(seconds=1)
        app.orchestrator.tick(clock.t)
        count += 1
    return count


def _to_tv2(app) -> str:
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    return rid


def test_tv2_billing_limit_waits_for_resume_then_scores(clock):
    app = bv_app(clock)
    app.llm.plan("T-V2", ["quota"])
    rid = _to_tv2(app)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.current_task, run.last_error_kind) == ("재개대기", "T-V2", "일시")
    [rec] = records_of_task(app, rid, "T-V2")
    assert (rec.status, rec.error, rec.error_kind) == ("재개대기", "호출실패", "일시")
    [quota] = [c for c in app.store.call_logs(rid) if c.task_id == "T-V2" and c.final_outcome == "소진"]
    assert [t.detail for t in quota.tries] == ["status=429 code=insufficient_quota"]
    assert _resume_until_done(app, clock, rid) == 1
    assert state(app, rid) == ("산출물확인", "사용자대기")
    [rec] = records_of_task(app, rid, "T-V2")
    assert (rec.status, rec.resume_count) == ("성공", 1)
    assert ctx_of(app, rid).get("artifactScore").total > 0


def test_tv2_billing_limit_over_resume_cap_fails_without_fallback(clock):
    app = bv_app(clock)
    app.llm.plan("T-V2", ["quota"] * 1000)
    rid = _to_tv2(app)
    assert _resume_until_done(app, clock, rid) == 5
    run = app.store.load_run(rid)
    assert run.state.progress == "실패" and run.notices[-1].code == "E-RUN-FAIL"
    assert all(r.status != "성공" for r in records_of_task(app, rid, "T-V2"))       # 규칙 판정으로 넘어가지 않았다
    assert "artifactScore" not in app.store.get_pointers(rid)


def test_tv2_billing_limit_in_rework_over_resume_cap_rolls_back(clock):
    app = bv_app(clock)
    rid = to_screen8(app)
    before = app.store.get_pointers(rid)
    app.llm.plan("T-V2", ["quota"] * 1000)
    rework(app, clock, rid, "실행 파일")
    assert app.store.load_run(rid).state.progress == "재개대기"
    assert _resume_until_done(app, clock, rid) == 5
    run = app.store.load_run(rid)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    s = run.last_rework
    assert (s.status, s.rolled_back, s.notice_code) == ("실패", True, "E-RUN-ROLLBACK")
    assert app.store.get_pointers(rid)["artifactScore"] == before["artifactScore"]


@pytest.mark.parametrize("outcome", ["timeout", "overloaded"])
def test_tv2_non_billing_exhaustion_still_rule_judges(clock, outcome):
    app = bv_app(clock)
    app.llm.plan("T-V2", [outcome] * 1000)
    rid = _to_tv2(app)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    [rec] = records_of_task(app, rid, "T-V2")
    assert rec.status == "성공"
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "T-V2" and c.purpose.startswith("계획서 대조")]
    assert calls and {(c.purpose[:7], c.final_outcome) for c in calls} == {("계획서 대조:", "소진")}, \
        [(c.purpose, c.final_outcome, len(c.tries)) for c in app.store.call_logs(rid) if c.task_id == "T-V2"]


# ── 흐름: T-B2 ─────────────────────────────────────────────
def test_tb2_image_billing_limit_waits_for_resume_without_fallback(clock):
    app = bv_app(clock)
    app.engine.image_providers["openai"] = EchoImage(outcomes=["quota"])           # 한도 뒤에는 맞춤 아이콘이 나온다
    rid = _to_tv2(app)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.current_task) == ("재개대기", "T-B2")
    assert [e for e in app.store.events(rid) if e.kind == EVENT_IMAGE_FALLBACK] == []
    assert _resume_until_done(app, clock, rid) == 1
    assert state(app, rid) == ("산출물확인", "사용자대기")
    ctx = ctx_of(app, rid)
    tb2 = records_of_task(app, rid, "T-B2")
    assert tb2 and all(not ctx.get_ref(r.result_ref).icon_fallback for r in tb2)
    assert [e for e in app.store.events(rid) if e.kind == EVENT_IMAGE_FALLBACK] == []  # 재개 뒤 호출만 본다


def test_tb2_image_billing_limit_over_resume_cap_fails_without_fallback(clock):
    app = bv_app(clock)
    app.engine.image_providers["openai"] = EchoImage(outcomes=["quota"] * 1000)
    rid = _to_tv2(app)
    assert _resume_until_done(app, clock, rid) == 5
    run = app.store.load_run(rid)
    assert run.state.progress == "실패" and run.notices[-1].code == "E-RUN-FAIL"
    assert all(r.status != "성공" for r in records_of_task(app, rid, "T-B2"))       # 기본 아이콘으로 넘어가지 않았다
    assert [e for e in app.store.events(rid) if e.kind == EVENT_IMAGE_FALLBACK] == []


@pytest.mark.parametrize("outcome,detail", [
    ("overloaded", f"{IMAGE_FALLBACK_DETAIL} (code=server_is_overloaded)"),
    ("timeout", IMAGE_FALLBACK_DETAIL),
])
def test_tb2_image_non_billing_exhaustion_default_icon_event_with_code(clock, outcome, detail):
    app = bv_app(clock)
    app.image.plan("T-B2", [outcome] * 60)
    rid = to_screen8(app)
    tb2 = records_of_task(app, rid, "T-B2")
    events = [e for e in app.store.events(rid) if e.kind == EVENT_IMAGE_FALLBACK]
    assert sorted(e.execution_id for e in events) == sorted(r.execution_id for r in tb2)   # 실행 기록마다 하나
    assert {e.detail for e in events} == {detail}
    ctx = ctx_of(app, rid)
    assert all(ctx.get_ref(r.result_ref).icon_fallback for r in tb2)


def test_icon_fallback_detail_has_no_code(clock):
    """둘째 설명(맞춤 아이콘 사용 불가 — 칸 수 불일치)은 그대로다."""
    app = bv_app(clock)                                                              # 스텁 그림 1×1 → 칸 수 불일치
    rid = to_screen8(app)
    events = [e for e in app.store.events(rid) if e.kind == EVENT_IMAGE_FALLBACK]
    assert events and {e.detail for e in events} == {ICON_FALLBACK_DETAIL}
