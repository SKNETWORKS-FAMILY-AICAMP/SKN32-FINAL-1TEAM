"""MySQL 8 통합 — 실제 웹 스키마(app_schema.sql) 위에서 전체 흐름 1회, 완전 삭제 뒤 실행 로그 보존, 검수 회수 문단,
탈퇴 중 계정 잠금(GET_LOCK).

proofread_logs는 웹팀이 바꿀 모양(project_id · model_version)을 테스트 DB에서만 흉내 낸다(mysqldb.py).

SBRAIN_TEST_MYSQL_URL(환경 변수 또는 .env)이 있을 때만 돈다. 로컬 DB는 docker/mysql-test.yml로 띄운다.
저장소 계약 테스트(test_store_contract.py)도 같은 DB에서 돈다.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from decimal import Decimal

import pytest
from conftest import Clock, executed, make_app, pre_input, set_consent, start_and_select, to_screen6, to_screen9
from fakes import item_json
from mysqldb import MYSQL, WEB_SCHEMA_ENV, require_mysql, web_schema
from sqlalchemy import text
from webdb import project_row, proofread_rows

from sbrain.agents.stubs import FakeLLM, StubScenario
from sbrain.bootstrap import build_app, build_web
from sbrain.orchestrator.store import StartRequest
from sbrain.store_sql import SqlStore
from sbrain.worker import Worker

pytestmark = MYSQL   # 이 파일 전체가 MySQL 묶음 (mysqldb.py)


def mysql_app(scenario: StubScenario | None = None):
    clock = Clock()
    return make_app(clock, scenario, store=SqlStore(require_mysql(), now=clock))


def test_full_flow_on_mysql():
    app = mysql_app()
    rid = to_screen9(app, account=uuid.uuid4().hex[:12])
    app.orchestrator.decide(rid, 9, "진행")
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("결과물", "완료")
    assert len(executed(app, rid)) == 23
    assert [n.kind for n in app.store.notifications(rid)] == ["문서평가", "산출물확인", "표현검수"]
    with app.store.engine.connect() as conn:
        pid = conn.execute(text("SELECT project_id FROM orch_runs WHERE run_id = :r"), {"r": rid}).scalar()
        assert str(pid) == run.project_id
        web = conn.execute(text("SELECT kind, target_step FROM notifications WHERE project_id = :p "
                                "ORDER BY notification_id"), {"p": pid}).all()
    assert [tuple(r) for r in web] == [("문서평가", 6), ("산출물확인", 8), ("표현검수", 10)]
    row = project_row(app.store.engine, pid)                                       # 진행 컬럼은 쓰지 않는다
    assert [row[c] for c in ("status", "stage", "progress_percent", "notice_id", "failure_reason")] == [None] * 5


def test_concurrent_rework_requests_merge_on_mysql():
    """동시에 들어온 묶음 요청 둘 — 한쪽이 접수를 저장하는 동안 다른 쪽은 점유를 짧게 다시 시도해 같은 재작성에 합쳐진다."""
    clock = Clock()
    app = make_app(clock, None, store=SqlStore(require_mysql(), now=clock))
    rid = to_screen9(app, account=uuid.uuid4().hex[:12])
    pid = app.store.load_run(rid).project_id
    commit, acquire = app.store.commit, app.store.acquire
    first, missed = threading.Event(), []

    def slow_commit(run_id, owner, batch):
        if not first.is_set():
            first.set()
            time.sleep(0.5)                                  # 첫 접수가 점유를 잡은 채 저장하는 동안
        commit(run_id, owner, batch)

    def counting_acquire(run_id, owner, lease_sec):
        ok = acquire(run_id, owner, lease_sec)
        if not ok:
            missed.append(owner)
        return ok
    app.store.commit, app.store.acquire = slow_commit, counting_acquire
    barrier, results, errors = threading.Barrier(2), {}, []

    def go(bundle):
        barrier.wait()
        try:
            results[bundle] = app.orchestrator.request_rework_for_project(pid, bundle)
        except Exception as e:  # noqa: BLE001 — 스레드 밖에서 확인
            errors.append(e)
    threads = [threading.Thread(target=go, args=(b,)) for b in ("실행 파일", "인포그래픽")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert missed                                            # 한쪽은 점유를 다시 시도했다
    a, b = results["실행 파일"], results["인포그래픽"]
    assert a.cycle_id == b.cycle_id and a.screen == b.screen == 9
    run = app.store.load_run(rid)
    assert sorted(run.cycle.counted_bundles) == ["실행 파일", "인포그래픽"]
    app.store.commit, app.store.acquire = commit, acquire
    clock.advance(seconds=3)
    app.orchestrator.advance(rid)
    assert len([e for e in app.store.events(rid) if e.kind == "재작성시작"]) == 1
    assert [r.task_id for r in app.store.executions(rid) if r.cycle_id == a.cycle_id] == [
        "T-B1", "T-B2", "G-04", "M-3", "T-V2", "G-02b"]
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.last_rework.status) == ("종합평가", "사용자대기", "완료")


def test_rejected_attempt_row_on_mysql():
    """학습 동의 계정의 반려된 시도 → 웹 proofread_logs 한 행 (project_id 외래 키 · 웹 기본값 포함)."""
    app = mysql_app(StubScenario(tp1_targets=2, tp2_behavior={"s-1-1-2": ["violate", "ok"]}))
    rid = to_screen9(app, account=uuid.uuid4().hex[:12])
    set_consent(app, rid)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"
    [row] = proofread_rows(app.store.engine, int(app.store.load_run(rid).project_id))
    assert (row["attempt_no"], row["passed"], row["recovery_status"], row["violation_type"], row["model_version"]) == (
        1, 0, "pending", "수치·금액", "미정")
    assert row["original_text"].endswith("문장 2 (1억원)") and row["corrected_text"] == "변형 0"
    assert (row["plan_id"], row["section_id"], row["score"]) == (None, None, Decimal("100.00"))
    assert (row["violation_note"], row["reason"]) == ("빠짐: 1억원", "보호 토큰 검사 불통과 (빠짐 1건)")
    assert [r.attempt_no for r in app.store.rejected_attempts(rid)] == [1]


def test_project_delete_keeps_run_log():
    """웹이 프로젝트 행을 지워도(완전 삭제) 실행 건 · 실행 기록은 남고 project_id만 비워진다 (ON DELETE SET NULL)."""
    app = mysql_app()
    rid = to_screen9(app, account=uuid.uuid4().hex[:12])
    pid = int(app.store.load_run(rid).project_id)
    with app.store.engine.begin() as conn:
        conn.execute(text("DELETE FROM projects WHERE project_id = :p"), {"p": pid})
    assert app.store.find_run_by_project(pid) is None
    assert app.store.load_run(rid).state.step == "종합평가"
    assert len(app.store.executions(rid)) == 18
    assert app.store.notifications(rid) == []          # 웹 알림은 프로젝트와 함께 지워졌다


def test_missing_projects_after_full_deletion_on_mysql():
    """완전 삭제 두 단계 — delete_project_data 뒤에는 '있음', 웹이 projects 행을 지워 외래 키가 project_id를 비운 뒤 '없음'."""
    app = mysql_app()
    rid = start_and_select(app, uuid.uuid4().hex[:12])                     # 사용자대기 — 완전 삭제가 중단한다
    pid = int(app.store.load_run(rid).project_id)
    app.orchestrator.delete_project_data(pid)
    assert app.store.load_run(rid).state.progress == "중단"
    assert app.orchestrator.missing_projects([pid, str(pid)]) == []
    with app.store.engine.begin() as conn:
        conn.execute(text("DELETE FROM projects WHERE project_id = :p"), {"p": pid})
    assert app.orchestrator.missing_projects([str(pid), pid]) == [str(pid)]
    assert app.store.load_run(rid).project_id == str(pid)                  # run_json은 그대로 — 실행 건 줄 칸만 비었다


def test_account_delete_holds_account_lock_on_mysql():
    """탈퇴(delete_account_data) — 함수가 끝날 때까지 같은 계정의 add_start_request는 GET_LOCK을 기다린다(다른 연결).

    끝난 실행 건 · 진행 중 실행 건 · 시작 요청은 통계 줄로 옮겨지고 지워진다. 뒤에 들어온 요청은 남는다.
    """
    clock = Clock()
    app = make_app(clock, None, store=SqlStore(require_mysql(), now=clock))
    acct = uuid.uuid4().hex[:12]
    first = to_screen6(app, acct)
    app.orchestrator.abort_project(app.store.load_run(first).project_id)
    second = start_and_select(app, acct)                                    # 사용자대기 — 바로 중단된다
    runs_before, reqs_before = len(app.store.log_stats("실행")), len(app.store.log_stats("시작요청"))
    list_runs, seen = app.store.list_runs, {}

    def add():
        now = clock()
        req = StartRequest(request_id=uuid.uuid4().hex[:12], project_id=None, account_id=acct, status="대기",
                           form=pre_input().dump(), created_at=now, updated_at=now)
        seen["result"] = app.store.add_start_request(req)
        seen["request_id"] = req.request_id

    def hooked(account_id):
        if "thread" not in seen:
            t = threading.Thread(target=add)
            seen["thread"] = t
            t.start()
            t.join(0.5)
            seen["alive_inside"] = t.is_alive()
        return list_runs(account_id)
    app.store.list_runs = hooked
    res = app.orchestrator.delete_account_data(acct)
    app.store.list_runs = list_runs
    seen["thread"].join(15)
    assert seen["alive_inside"] is True and seen["result"] is None
    assert (res.aborted_runs, res.deleted_runs, res.deleted_requests, res.stats_rows) == ([second], 2, 2, 3)
    assert app.store.list_runs(acct) == []
    assert [r.request_id for r in app.store.list_start_requests(acct)] == [seen["request_id"]]
    for rid in (first, second):
        assert app.store.executions(rid) == [] and app.store.get_latest_versions(rid) == {}
        with app.store.engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM orch_runs WHERE run_id = :r"), {"r": rid}).scalar() == 0
    assert len(app.store.log_stats("실행")) == runs_before + 2
    assert len(app.store.log_stats("시작요청")) == reqs_before + 1
    # MySQL 테스트 DB는 테스트끼리 함께 쓴다 — 남은 '대기' 요청을 뒤 워커 테스트가 가져가지 않게 취소해 둔다
    assert app.store.cancel_start_request(seen["request_id"]) == "취소"


def insert_web_project(engine) -> tuple[int, int]:
    """웹 create_project가 저장한 것과 같은 행을 실제 웹 스키마에 넣는다 (계정 · 회사 · 프로젝트 · 팀 · 단가 · 사업 계획)."""
    key = uuid.uuid4().hex
    with engine.begin() as conn:
        uid = conn.execute(text("INSERT INTO users (email, name, google_sub) VALUES (:e, '김서준', :g)"),
                           {"e": f"{key}@test.local", "g": key}).lastrowid
        cid = conn.execute(text(
            "INSERT INTO companies (user_id, applicant_type, biz_type, ceo_name, founded_at, company_name, "
            "business_reg_no, rep_type) VALUES (:u, 'corp', '서비스업', '김서준', '2025-03-02', '헬스온', "
            "'123-45-67890', '단독')"), {"u": uid}).lastrowid
        pid = conn.execute(text("INSERT INTO projects (company_id, description) VALUES (:c, '동네 헬스장 회원 관리 서비스')"),
                           {"c": cid}).lastrowid
        conn.execute(text("INSERT INTO team_members (project_id, name, role, experience) "
                          "VALUES (:p, '이하늘', '개발', '웹 개발 3년')"), {"p": pid})
        conn.execute(text("INSERT INTO pricing_items (project_id, service_name, unit_price) "
                          "VALUES (:p, '월 구독', 35000.00)"), {"p": pid})
        conn.execute(text(
            "INSERT INTO project_plan_inputs (project_id, ceo_birth_date, ceo_gender, region_sido, region_sigungu, "
            "main_industry, certifications, ceo_careers, ceo_capability, dev_start_month, dev_end_month, "
            "self_funding_allowed, self_cash_limit, no_hires, hires, no_equipment, equipment, no_partners, partners) "
            "VALUES (:p, '1990-01-01', '남', '서울특별시', '마포구', '정보·통신', :cert, :careers, '운영 노하우', "
            "'2026-03', '2026-12', TRUE, 10000000, FALSE, :hires, FALSE, :equip, TRUE, '[]')"),
            {"p": pid, "cert": json.dumps(["노란우산공제"]),
             "careers": json.dumps([{"type": "경력", "title": "OO피트니스 운영", "period": "5년", "has_proof": True}]),
             "hires": json.dumps([{"job": "개발자", "headcount": "2", "required_skill": "React", "hire_month": "2026-06"}]),
             "equip": json.dumps([{"name": "태블릿", "status": "보유"}])})
    return uid, pid


def test_web_and_worker_on_real_web_schema():
    """웹 조립(build_web)이 실제 웹 스키마에서 입력을 읽어 요청을 넣고, 워커 조립(build_app)이 처리한다."""
    engine = require_mysql()
    url = engine.url.render_as_string(hide_password=False)
    uid, pid = insert_web_project(engine)
    web = build_web(url, profile_count=lambda a: 1)
    check = web.orchestrator.request_start(str(uid), pid)
    assert check.ok, check
    real = FakeLLM()
    real.respond("T-C1", lambda r: item_json())
    Worker(build_app(url, llm=real), log=lambda line: None).run_once("w")
    st = web.orchestrator.start_status(pid)
    assert st.status == "완료", st
    run = web.store.load_run(st.run_id)
    ctx = web.engine.open_context(run)
    form = ctx.get("formInput")
    assert form.representative_career == ["경력: OO피트니스 운영 (5년, 증빙 있음)"]       # S0 키 이름 변환
    assert form.hiring_plan == "개발자 2명 · 요구역량: React · 채용 시기: 2026-06"
    assert (form.facilities, form.partners, form.revenue_unit_price) == ("태블릿 (보유)", "없음", 35000)
    scoring = run.settings_snapshot["scoring"]                                           # verification_policies 첫 행
    assert (scoring["threshold"], scoring["docLayerMax"], scoring["deviationCap"]) == (80.0, 70.0, 5.0)


def test_web_schema_lookup(tmp_path, monkeypatch):
    """웹 스키마 위치 (DB 없이) — 환경 변수가 먼저, 없으면 웹과 같은 저장소 배치 → 작업 공간 배치 순서."""
    repo, workspace = tmp_path / "web.sql", tmp_path / "workspace.sql"
    workspace.write_text("-- workspace", encoding="utf-8")
    monkeypatch.setattr("mysqldb.WEB_SCHEMA_CANDIDATES", (repo, workspace))
    monkeypatch.setattr("mysqldb.get_env", lambda name, default=None: None)
    assert web_schema() == workspace
    repo.write_text("-- repo", encoding="utf-8")
    assert web_schema() == repo
    given = tmp_path / "given.sql"
    given.write_text("-- given", encoding="utf-8")
    monkeypatch.setattr("mysqldb.get_env", lambda name, default=None: str(given) if name == WEB_SCHEMA_ENV else None)
    assert web_schema() == given
    monkeypatch.setattr("mysqldb.get_env", lambda name, default=None: str(tmp_path / "none.sql"))
    with pytest.raises(pytest.fail.Exception):
        web_schema()
