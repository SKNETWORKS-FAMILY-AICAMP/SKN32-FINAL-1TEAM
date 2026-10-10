"""전략 · 작성 · 검증-1 실구현을 흐름에 끼워 돌린다 (spec 4.15, 7절 2번 연결) — 스텁 조립에 bind_partner_sw, 가짜 LLM은
목적(F번호)별 응답. 메모리 · SQLite 두 저장소(store_backend)에서 돈다. 네트워크 없음.
"""
from __future__ import annotations

from decimal import Decimal

from conftest import make_app, to_screen6
from partner_fake import BODY_MARK, PARTNER_TASKS, respond_partner

from sbrain.agents.partner_sw.tasks import IMPLEMENTED, bind_partner_sw
from sbrain.orchestrator.settings import Settings


def partner_app(clock, **kw):
    app = make_app(clock, **kw)
    bind_partner_sw(app.registry)
    respond_partner(app.llm)
    return app


def test_partner_tasks_run_in_flow_to_screen6(clock):
    app = partner_app(clock)
    assert all(app.registry.get(t).fn is fn for t, fn in IMPLEMENTED.items())
    rid = to_screen6(app)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("문서평가", "사용자대기")
    ctx = app.engine.open_context(run)
    form = ctx.get("formSpec")
    plan = ctx.get("planDoc")
    assert [s.section_code for s in plan.sections] == form.section_codes            # 모든 항목 · 양식 순서 (M-1 뒤)
    tables = [s for s in plan.sections if s.content_type == "table"]
    assert tables and all(s.sentences for s in tables)                             # 표 항목은 T-W3 서술
    assert plan.charts == [] and [t.source_ref for t in plan.tables] == [s.section_code for s in tables]
    assert len(plan.diagrams) == 2 and plan.diagrams == ctx.get("diagrams")
    for d in plan.diagrams:                                                        # SVG는 파일 저장소에 있다
        assert app.engine.files.read(d.image_file.key).startswith(b"<svg")
    results = ctx.get("sectionResults")
    assert [x.section_code for x in results] == form.section_codes
    score = ctx.get("docScore")
    assert [i.item_code for i in score.items] == form.section_codes and score.total > 0
    # 호출: 실구현 Task는 목적 = F번호 · json_mode, T-W3는 LLM 없음
    reqs = [q for q in app.llm.requests if q.metadata["task_id"] in PARTNER_TASKS]
    assert reqs and all(q.json_mode and q.metadata["purpose"].startswith("F") for q in reqs)
    assert not [q for q in app.llm.requests if q.metadata["task_id"] == "T-W3"]
    logs = app.store.call_logs(rid)
    assert {log.purpose for log in logs if log.task_id == "T-S1" and log.call_type == "search"} == {"자료 검색"}
    # 기록에 산출물 내용이 없다 (spec 4.17)
    recorded = " ".join([log.model_dump_json() for log in logs] +
                        [r.model_dump_json() for r in app.store.executions(rid)])
    assert BODY_MARK not in recorded


def test_doc_layer_max_setting_reaches_tv1(clock):
    """문서층 배점 D = 설정 사본 scoring.docLayerMax — 관리자가 60으로 바꾸면 60 기준 (spec 4.9)."""
    s = Settings()
    s.scoring.doc_layer_max = 60
    app = partner_app(clock, settings=s)
    rid = to_screen6(app)
    score = app.engine.open_context(app.store.load_run(rid)).get("docScore")
    assert abs(sum(i.max_score for i in score.items) - 60) < 1e-9
    assert score.total <= 60 and score.total == float(sum(Decimal(str(i.score)) for i in score.items))
