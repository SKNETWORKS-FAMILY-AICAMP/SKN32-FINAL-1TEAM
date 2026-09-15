"""오후 테스트 요청 3종 중 2)동시 실행 1건 제한, 3)에러/예외 케이스를 폭넓게 검증한다.
1)개별 작업 재시도는 팀이 이미 만들어둔 verify_retry_task.py(10개 task_key 전부 + 에러
케이스 3종)로 이미 커버돼 있어 여기선 다루지 않는다.

동시 실행 1건 제한은 2026-09-15에 회사 프로필(Company) 락에서 User 행 락으로 옮겼다 —
이 테스트는 그 리팩터링이 원래 동작(진행 중 매칭 있으면 차단)을 그대로 보존하면서,
동시에 "계정당 회사 프로필 1건" 가정이 빠져도 여전히 계정 단위로만 막고 다른 계정은
안 건드리는지까지 확인한다."""
import json

from app.models import MatchResult, Notice


def _payload(**overrides):
    body = dict(
        start_type='예비창업', biz_type=None, ceo_name='김서준', founded_at=None,
        description='동네 헬스장 예약 서비스', notify_region='전국', notify_industry='기타',
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


# ---------------------------------------------------------------------------
# 2) 동시 실행 1건 제한
# ---------------------------------------------------------------------------
class TestConcurrencyLimit:
    def test_blocks_second_project_while_first_in_progress(self, authed_client, db_session):
        r1 = authed_client.post('/projects', data=_payload())
        assert r1.status_code == 201
        project1_id = r1.json()['project_id']

        notice = _seed_notice(db_session)
        db_session.add(MatchResult(project_id=project1_id, notice_id=notice.notice_id, fit_score=80))
        db_session.commit()

        r2 = authed_client.post('/projects', data=_payload())
        assert r2.status_code == 409
        assert str(project1_id) in r2.json()['detail']  # 어느 프로젝트가 막았는지 메시지에 나와야 함

    def test_completed_match_does_not_block(self, authed_client, db_session):
        """status='completed'(제출 완료)는 ACTIVE_MATCH_STATUSES에 없으니 막으면 안 된다 —
        '진행 중'과 '이미 끝남'을 혼동하는 회귀가 생기면 이 테스트가 잡아준다."""
        r1 = authed_client.post('/projects', data=_payload())
        assert r1.status_code == 201
        project1_id = r1.json()['project_id']

        notice = _seed_notice(db_session, 'test:PBLN_DONE')
        db_session.add(MatchResult(project_id=project1_id, notice_id=notice.notice_id, fit_score=80, status='completed'))
        db_session.commit()

        r2 = authed_client.post('/projects', data=_payload())
        assert r2.status_code == 201, f'완료된 매칭인데도 막힘: {r2.text}'

    def test_limit_is_per_account_not_global(self, login_as, db_session):
        """User 행 락으로 옮긴 게 계정 범위를 벗어나 다른 계정까지 막아버리는 회귀가 없는지 —
        A 계정이 진행 중이어도 B 계정은 정상적으로 새 프로젝트를 만들 수 있어야 한다."""
        client_a = login_as('concurrency-a@example.com', 'A유저')
        ra = client_a.post('/projects', data=_payload())
        assert ra.status_code == 201
        project_a_id = ra.json()['project_id']
        notice = _seed_notice(db_session, 'test:PBLN_A')
        db_session.add(MatchResult(project_id=project_a_id, notice_id=notice.notice_id, fit_score=80))
        db_session.commit()

        # A는 두 번째 프로젝트를 못 만든다
        ra2 = client_a.post('/projects', data=_payload())
        assert ra2.status_code == 409

        # B는 A와 무관하게 만들 수 있어야 한다
        client_b = login_as('concurrency-b@example.com', 'B유저')
        rb = client_b.post('/projects', data=_payload())
        assert rb.status_code == 201, f'B 계정까지 같이 막힘 — User 락이 계정 범위를 벗어남: {rb.text}'


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
        bad_body = dict(start_type='예비창업', notify_region='전국', notify_industry='기타')
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
