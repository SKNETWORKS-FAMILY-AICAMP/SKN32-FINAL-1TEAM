"""오후 테스트 요청 3종 중 2)동시 실행 1건 제한, 3)에러/예외 케이스를 폭넓게 검증한다.
1)개별 작업 재시도는 팀이 이미 만들어둔 verify_retry_task.py(10개 task_key 전부 + 에러
케이스 3종)로 이미 커버돼 있어 여기선 다루지 않는다.

동시 실행 1건 제한은 2026-09-15에 회사 프로필(Company) 락에서 User 행 락으로 옮겼다 —
이 테스트는 그 리팩터링이 원래 동작(진행 중 매칭 있으면 차단)을 그대로 보존하면서,
동시에 "계정당 회사 프로필 1건" 가정이 빠져도 여전히 계정 단위로만 막고 다른 계정은
안 건드리는지까지 확인한다."""
import json

from orch_fakes import ActiveWork, StartCheck

from app.models import Notice, Project, User


def _payload(**overrides):
    body = dict(
        biz_type=None, ceo_name='김서준', founded_at=None,
        description='동네 헬스장 예약 서비스',
        team_members=[], pricing_items=[],
    )
    body.update(overrides)
    return {'payload': json.dumps(body, default=str)}


def _seed_notice(db_session, notice_id='test:PBLN_CONC'):
    notice = Notice(
        id=hash(notice_id) % 1_000_000 + 1, notice_id=notice_id, source='test', title='테스트 공고',
        target_text=None, category=None, organizer=None, supervising_org=None,
        executing_org=None, apply_start=None, apply_end=None,
        recruitment_status='open', url=None,
    )
    db_session.add(notice)
    db_session.flush()
    return notice


def _set_match(db_session, project_id: int, notice_id: str, fit_score=80, status='in_progress'):
    """[2026-09-28, match_results 테이블 통합] 예전엔 MatchResult 행을 새로 만들었으나,
    이제 매칭 상태는 project 행 자체에 있는 컬럼이라 기존 project를 가져와 갱신한다."""
    project = db_session.get(Project, project_id)
    project.notice_id = notice_id
    project.fit_score = fit_score
    project.status = status
    return project


# ---------------------------------------------------------------------------
# 2) 동시 실행 1건 제한
# ---------------------------------------------------------------------------
def _active(project_id, step='계획서작성', resume_step=5, screen_status='진행 중'):
    return ActiveWork(project_id=str(project_id), run_id='r1', step=step, resume_step=resume_step,
                      screen_status=screen_status)


class TestConcurrencyLimit:
    """[SB-242] 동시 실행 1건 제한은 오케스트레이터가 판단한다 — 웹은 저장 전에 active_work로 묻고, 저장 뒤
    request_start가 계정 잠금 안에서 최종 확인한다. 가짜 오케스트레이터로 그 답을 정해 웹 응답을 확인한다."""

    def test_blocks_while_first_in_progress(self, authed_client, db_session, orch):
        orch.responses['active_work'] = _active(7)
        res = authed_client.post('/projects', data=_payload())
        assert res.status_code == 409
        detail = res.json()['detail']
        assert detail['blocked'] is True
        assert detail['active_project_id'] == 7  # 어느 프로젝트가 막았는지 나와야 함
        assert detail['active_stage'] == 'plan_writing'
        assert detail['active_screen'] == 5
        assert detail['active_display_status'] == '진행'
        assert db_session.query(Project).count() == 0, '막힌 요청이 프로젝트를 만들었다'

    def test_blocks_while_first_user_waiting(self, authed_client, orch):
        """사용자 판단 대기(확인 필요)도 진행 중으로 센다 — 기능정의서 v1.9 R-9."""
        orch.responses['active_work'] = _active(7, step='문서평가', resume_step=6, screen_status='확인 필요')
        res = authed_client.post('/projects', data=_payload())
        assert res.status_code == 409
        assert res.json()['detail']['active_stage'] == 'plan_review_pending'
        assert res.json()['detail']['active_display_status'] == '확인이 필요합니다'

    def test_pre_stage_in_progress_blocks_and_points_to_screen_3(self, authed_client, orch):
        """실행 건이 아직 없고 사전 단계(요구사항 해석 · 공고 매칭)만 도는 중이어도 막는다."""
        orch.responses['active_work'] = ActiveWork(project_id='7', request_id='q1')
        detail = authed_client.post('/projects', data=_payload()).json()['detail']
        assert (detail['active_stage'], detail['active_screen']) == (None, 3)

    def test_nothing_active_creates_project_and_requests_start(self, authed_client, db_session, orch):
        res = authed_client.post('/projects', data=_payload())
        assert res.status_code == 201, res.text
        project_id = res.json()['project_id']
        starts = [c for c in orch.calls if c[0] == 'request_start']
        assert len(starts) == 1 and starts[0][1][1] == project_id

    def test_limit_is_asked_per_account(self, login_as, db_session, orch):
        """계정마다 자기 account_id(users.user_id 문자열)로 묻는다 — A가 진행 중이어도 B는 따로 판단된다."""
        client_a = login_as('concurrency-a@example.com', 'A유저')
        account_a = str(db_session.query(User).filter_by(email='concurrency-a@example.com').one().user_id)
        orch.responses['active_work'] = lambda account_id: _active(7) if account_id == account_a else None

        assert client_a.post('/projects', data=_payload()).status_code == 409
        client_b = login_as('concurrency-b@example.com', 'B유저')
        assert client_b.post('/projects', data=_payload()).status_code == 201
        asked = [c[1][0] for c in orch.calls if c[0] == 'active_work']
        assert len(set(asked)) == 2

    def test_race_after_save_is_blocked_and_project_is_removed(self, authed_client, db_session, orch):
        """저장 사이에 다른 작업이 생겨 request_start가 E-RUN-CONCURRENT로 거절하면 같은 409 응답이고,
        방금 만든 프로젝트는 남기지 않는다."""
        orch.responses['request_start'] = lambda account_id, project_id: StartCheck(
            ok=False, code='E-RUN-CONCURRENT', active=_active(7))
        res = authed_client.post('/projects', data=_payload())
        assert res.status_code == 409 and res.json()['detail']['blocked'] is True
        assert db_session.query(Project).count() == 0

    def test_missing_required_inputs_is_422_and_project_is_removed(self, authed_client, db_session, orch):
        orch.responses['request_start'] = lambda account_id, project_id: StartCheck(
            ok=False, code='E-C1-REQUIRED', message='필수 항목이 비어 있어요', missing=['수익모델 단가', '성별'])
        res = authed_client.post('/projects', data=_payload())
        assert res.status_code == 422
        assert res.json()['detail'] == {
            'message': '필수 항목이 비어 있어요', 'code': 'E-C1-REQUIRED', 'missing': ['수익모델 단가', '성별']}
        assert db_session.query(Project).count() == 0

    def test_profile_error_from_orchestrator_is_403(self, authed_client, db_session, orch):
        orch.responses['request_start'] = lambda account_id, project_id: StartCheck(
            ok=False, code='E-AUTH-PROFILE', message='프로필을 먼저 만들어 주세요')
        res = authed_client.post('/projects', data=_payload())
        assert res.status_code == 403 and res.json()['detail'] == '프로필을 먼저 만들어 주세요'
        assert db_session.query(Project).count() == 0

    def test_gateway_not_ready_is_503(self, authed_client):
        from app.orch import reset_gateway
        reset_gateway()
        assert authed_client.post('/projects', data=_payload()).status_code == 503


# ---------------------------------------------------------------------------
# 3) 에러/예외 케이스
# ---------------------------------------------------------------------------
class TestErrorCases:
    def test_unauthenticated_requests_get_401(self, client):
        for method, path in [('get', '/projects'), ('post', '/projects'), ('get', '/projects/1')]:
            res = getattr(client, method)(path)
            assert res.status_code == 401, f'{method.upper()} {path} -> {res.status_code} (401 기대)'

    def test_invalid_session_cookie_gets_401(self, client):
        client.cookies.set('sbrain_session', 'not-a-real-jwt')
        res = client.get('/projects')
        assert res.status_code == 401

    def test_malformed_create_payload_gets_422(self, authed_client):
        # description(필수)이 빠짐
        bad_body = dict(biz_type='개인')
        res = authed_client.post('/projects', data={'payload': json.dumps(bad_body)})
        assert res.status_code == 422, res.text

    def test_create_payload_not_json_gets_422(self, authed_client):
        res = authed_client.post('/projects', data={'payload': '이것은 JSON이 아님'})
        assert res.status_code == 422, res.text

    def test_get_nonexistent_project_gets_404(self, authed_client):
        res = authed_client.get('/projects/999999')
        assert res.status_code == 404

    def test_cannot_access_another_users_project(self, login_as, db_session):
        owner = login_as('owner@example.com', '소유자')
        r = owner.post('/projects', data=_payload())
        assert r.status_code == 201
        project_id = r.json()['project_id']

        intruder = login_as('intruder@example.com', '침입자')
        res = intruder.get(f'/projects/{project_id}')
        assert res.status_code == 404, '다른 계정 프로젝트가 404가 아니라 실제로 노출됨 — 소유권 체크 회귀'

    def test_generate_on_project_without_match_gets_400(self, authed_client):
        r = authed_client.post('/projects', data=_payload())
        assert r.status_code == 201
        project_id = r.json()['project_id']
        # notice_id를 명시했는데 실제로 없는 공고면 400/404 계열로 실패해야지 500이면 안 된다
        res = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': 'no-such-notice'})
        assert res.status_code < 500, f'존재하지 않는 공고로 generate 호출 시 서버 에러(500) 발생: {res.status_code} {res.text}'

    def test_retry_task_on_project_without_match_gets_404(self, authed_client):
        r = authed_client.post('/projects', data=_payload())
        assert r.status_code == 201
        project_id = r.json()['project_id']
        res = authed_client.post(f'/projects/{project_id}/retry-task', json={'task_key': 'strategy'})
        assert res.status_code == 404

    def test_retry_task_invalid_task_key_gets_400(self, authed_client, db_session):
        from seed_dummy_pipeline import seed_dummy_pipeline
        r = authed_client.post('/projects', data=_payload())
        project_id = r.json()['project_id']
        notice = _seed_notice(db_session, 'test:PBLN_RETRY400')
        seed_dummy_pipeline(db_session, project_id=project_id, notice_id=notice.notice_id, write_real_files=False)
        db_session.commit()
        res = authed_client.post(f'/projects/{project_id}/retry-task', json={'task_key': 'not_a_real_task'})
        assert res.status_code == 400
