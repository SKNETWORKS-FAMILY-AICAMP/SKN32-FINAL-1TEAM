"""app/orch/mapping.py — 웹연동_변경사항_웹팀전달.md 3절 대응표."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from orch_fakes import Notice, ProjectView, make_run

from app import pipeline_stages as ps
from app.orch import mapping

STEPS = ['공고선택', '자격확인', '계획서작성', '문서평가', '프로토타입제작', '산출물확인', '종합평가', '표현검수', '결과물']
PROGRESSES = ['실행', '재개대기', '사용자대기', '실패', '완료', '중단']


def test_step_to_stage_matches_table_3_1():
    assert set(mapping.STEP_TO_STAGE) == set(STEPS)
    assert mapping.stage_of('공고선택') is None and mapping.stage_of('자격확인') is None
    assert [mapping.stage_of(s) for s in STEPS[2:]] == [
        'plan_writing', 'plan_review_pending', 'prototype_building', 'artifact_review',
        'final_review_pending', 'reviewing', 'done',
    ]


def test_progress_to_status_and_display_match_table_3_2():
    expected = {
        '실행': ('in_progress', '진행'), '재개대기': ('waiting_resume', '진행'),
        '사용자대기': ('user_waiting', '확인이 필요합니다'), '실패': ('failed', '문제가 생겨 멈췄다'),
        '완료': ('completed', '완료'), '중단': ('halted', '중단됨'),
    }
    assert set(mapping.PROGRESS_TO_MATCH_STATUS) == set(PROGRESSES)
    for progress, (status, display) in expected.items():
        assert mapping.match_status_of(progress) == status
        assert mapping.display_status_of(progress) == display


def test_category_mapping():
    assert mapping.CATEGORY_TO_WEB == {'원페이지': 'onepage', '웹개발': 'webdev', 'AI_API': 'aiapi'}


@pytest.mark.parametrize('task_key, bundle_id, expected', [
    ('writing', '문제인식', '문제인식'), ('writing', '실현가능성', '실현가능성'),
    ('writing', '성장전략', '성장전략'), ('writing', '팀 구성', '팀 구성'),
    ('implement_prototype', '실행 파일 제작', '실행 파일'), ('implement_prototype', None, '실행 파일'),
    ('implement_infographic', '인포그래픽 제작', '인포그래픽'), ('implement_infographic', None, '인포그래픽'),
])
def test_rework_bundle_names(task_key, bundle_id, expected):
    assert mapping.orch_bundle_of(task_key, bundle_id) == expected


@pytest.mark.parametrize('task_key, bundle_id', [
    ('writing', None), ('writing', '없는 묶음'), ('implement_prototype', '인포그래픽 제작'),
    ('strategy', None), ('verify1_rubric', None), ('review_token_check', None),
])
def test_rework_bundle_rejects_unsupported(task_key, bundle_id):
    with pytest.raises(mapping.NotReworkable):
        mapping.orch_bundle_of(task_key, bundle_id)


def test_usage_bundle_ids_round_trip_to_web_names():
    assert mapping.web_bundle_id_of('문제인식') == '문제인식'
    assert mapping.web_bundle_id_of('실행 파일') == '실행 파일 제작'
    assert mapping.web_bundle_id_of('인포그래픽') == '인포그래픽 제작'


def test_status_without_run_is_before_matching():
    out = mapping.project_status_out(7, ProjectView(project_id='7'))
    assert out.screen == ps.NO_MATCH_SCREEN
    assert out.stage is None and out.match_status is None and out.progress_percent is None


def test_status_while_writing_has_percent_and_stage():
    out = mapping.project_status_out(7, ProjectView('7', run=make_run(percent=40)))
    assert (out.screen, out.stage, out.match_status, out.progress_percent) == (5, 'plan_writing', 'in_progress', 40)
    assert out.failure_reason is None and out.notice_closed is False


def test_status_percent_is_none_when_waiting_for_user():
    run = make_run(step='문서평가', progress='사용자대기', screen_status='확인 필요', resume_step=6, percent=0)
    out = mapping.project_status_out(7, ProjectView('7', run=run))
    assert (out.stage, out.match_status, out.progress_percent) == ('plan_review_pending', 'user_waiting', None)


def test_status_percent_during_rework_and_review():
    rework = make_run(step='산출물확인', progress='실행', resume_step=8, percent=50, rework_screen=8)
    assert mapping.project_status_out(7, ProjectView('7', run=rework)).progress_percent == 50
    review = make_run(step='표현검수', progress='실행', resume_step=10, percent=30)
    assert mapping.project_status_out(7, ProjectView('7', run=review)).progress_percent == 30


def test_status_resume_wait_exposes_next_retry_and_count():
    # 오케스트레이터 시각은 시간대 있는 UTC다(2026-10-05 변경) — 응답에도 Z가 붙어 브라우저가 한국 시간으로 바꿀 수 있다
    at = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
    run = make_run(progress='재개대기', resume_count=2, next_resume_at=at)
    out = mapping.project_status_out(7, ProjectView('7', run=run))
    assert (out.match_status, out.resume_count, out.next_retry_at) == ('waiting_resume', 2, at)
    assert out.model_dump(mode='json')['next_retry_at'].endswith('Z')


def test_status_failed_run_hides_failure_reason():
    run = make_run(progress='실패', screen_status='문제 발생', percent=0)
    out = mapping.project_status_out(7, ProjectView('7', run=run))
    assert out.match_status == 'failed' and out.failure_reason is None


def test_status_notice_closed_from_run_closed_notice():
    notice = Notice(code='E-RUN-CLOSED', message='마감', at=datetime(2026, 10, 5))
    out = mapping.project_status_out(7, ProjectView('7', run=make_run(notices=[notice])))
    assert out.notice_closed is True


# ── [SB-272] 재작성 진행 필드 ───────────────────────────────────────────────────────────
def test_status_exposes_rework_screen_and_collecting():
    run = make_run(step='산출물확인', progress='실행', resume_step=8, percent=50, rework_screen=8, collecting=True)
    out = mapping.project_status_out(7, ProjectView('7', run=run))
    assert (out.rework_screen, out.collecting) == (8, True)
    # 재작성 중에도 stage는 재작성 전 단계 그대로, match_status는 in_progress다
    assert (out.screen, out.stage, out.match_status) == (8, 'artifact_review', 'in_progress')


def test_status_rework_fields_default_when_not_reworking():
    out = mapping.project_status_out(7, ProjectView('7', run=make_run()))
    assert (out.rework_screen, out.collecting) == (None, False)


def test_status_without_run_has_no_rework_fields():
    out = mapping.project_status_out(7, ProjectView('7', run=None))
    assert (out.rework_screen, out.collecting) == (None, False)


def test_list_item_exposes_rework_fields():
    project = SimpleNamespace(project_id=7, description='설명', created_at=datetime(2026, 10, 6))
    reworking = make_run(step='종합평가', progress='실행', resume_step=9, rework_screen=9, collecting=False)
    item = mapping.project_list_item(project, ProjectView('7', run=reworking), None)
    assert (item.rework_screen, item.collecting) == (9, False)
    plain = mapping.project_list_item(project, ProjectView('7', run=make_run()), None)
    assert (plain.rework_screen, plain.collecting) == (None, False)
    no_run = mapping.project_list_item(project, ProjectView('7', run=None), None)
    assert (no_run.rework_screen, no_run.collecting) == (None, False)


# ── [SB-274] 자격 확인 응답의 업력 · 작성 가능 여부 ─────────────────────────────────────────
def test_eligibility_out_passes_screen_values_through():
    from orch_fakes import make_gate
    out = mapping.eligibility_out(make_gate(passed=True), 3.5, True)
    assert (out.business_age_years, out.can_start_writing) == (3.5, True)
    rejected = mapping.eligibility_out(make_gate(passed=False), 8.0, False)
    assert (rejected.business_age_years, rejected.can_start_writing) == (8.0, False)


def test_eligibility_out_defaults_can_start_writing_to_passed():
    """outputs(이미 작성 단계를 지난 실행 건)에는 작성 가능 여부가 없어 통과 여부로 대신한다."""
    from orch_fakes import make_gate
    assert mapping.eligibility_out(make_gate(passed=True)).can_start_writing is True
    assert mapping.eligibility_out(make_gate(passed=False)).can_start_writing is False
    assert mapping.eligibility_out(make_gate(passed=True)).business_age_years is None
