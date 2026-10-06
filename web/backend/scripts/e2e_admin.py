"""관리자 화면 API를 실제 워커가 만든 데이터로 확인한다 (SB-263).

    python scripts/e2e_admin.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

e2e_failure_resume.py처럼 워커를 이 프로세스 안에서 돌린다(따로 띄운 워커가 있으면 끈다). 서로 다른 상태의 프로젝트 네 개를 만든다:
  nomatch  공고 후보 0건 → 실행 건 없음('공고 매칭 전')
  fail     계획서 작성이 시간 초과를 계속 → 재개 2번 뒤 '실패'
  done     끝까지(재작성 1번 포함) → '완료'
  wait     계획서 작성 단계를 붙잡아 '진행중' → 마지막 갱신을 72시간 전으로 돌려 정체(stalled) 확인 → 풀어 '판단 대기'
그 위에서 진행 현황 · 이력보기 · 보관/복원 · 에이전트 실행 기록 · Task별 보기 · 운영 지표 · 알림 · 사용자 · 배점 · 체크리스트를 부르고,
숫자는 오케스트레이터 표를 직접 센 값(SQL)과 맞춰 본다. 관리자 설정이 새 실행에 반영되는지(합격선 · 재작성 횟수)와 일반 사용자의
접근 거부(403)도 본다. 조율 T-C1 · T-C3는 평소처럼 실제 LLM이라 OPENAI_API_KEY(agent-orchestration/.env)가 필요하다.
끝나면 바꾼 설정(배점 · 합격선 · 체크리스트)을 원래대로 돌린다.
"""
import argparse
import datetime
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_worker_flow import DEFAULT_URL, FULL_INPUT, PROFILE, configure_env  # noqa: E402

results: list[tuple[str, bool, str]] = []
if hasattr(sys.stdout, 'reconfigure'):  # 콘솔 인코딩(cp949 등)에 없는 문자(— 등)가 있어도 출력이 죽지 않게
    sys.stdout.reconfigure(errors='replace')

RETRIES, MAX_RESUME, RESUME_WAIT_SEC = 2, 2, 3.0


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


class Abort(Exception):
    """이어갈 수 없는 실패."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--wait-sec', type=float, default=300, help='단계 하나를 기다리는 최대 시간(초, 기본 300)')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from fastapi.testclient import TestClient
    from sbrain.bootstrap import build_app
    from sbrain.orchestrator.settings import ResumeSettings, RetrySettings, Settings
    from sbrain.worker import Worker, WorkerConfig
    from sqlalchemy import text

    import app.routers.auth as auth_router
    import app.security as security
    from app.database import SessionLocal, engine
    from app.main import app
    from app.models import User
    from app.orch.gateway import get_gateway

    fast = Settings(
        retry=RetrySettings(retry_count=RETRIES, retry_interval_sec=0.05),
        resume=ResumeSettings(first_interval_min=RESUME_WAIT_SEC / 60, multiplier=1, max_count=MAX_RESUME, total_cap_hours=12))
    worker_app = build_app(settings=fast)
    worker = Worker(worker_app, WorkerConfig(poll_sec=0.3, threads=2, lease_sec=60), log=lambda line: None)
    worker_thread = threading.Thread(target=worker.run, name='e2e-worker', daemon=True)
    worker_thread.start()
    llm, scenario = worker_app.llm, worker_app.scenario
    gate, entered = threading.Event(), threading.Event()

    def blocking(request):
        entered.set()
        gate.wait(120)
        return '{"ok": true}'

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    def scalar(sql: str, **params):
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    originals: dict = {}
    try:
        with TestClient(app) as client, TestClient(app) as client2, TestClient(app) as anon:
            security.verify_google_id_token = lambda t: (
                {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'} if t == 'x'
                else {'sub': 'e2e-sub-2', 'email': 'e2e2@example.com', 'name': 'E2E2'})
            auth_router.verify_google_id_token = security.verify_google_id_token
            gateway = get_gateway()
            ids: dict = {}

            def wait_for(label: str, cond, interval: float = 0.4, timeout: float | None = None):
                deadline = time.time() + (timeout or args.wait_sec)
                while time.time() < deadline:
                    value = cond()
                    if value:
                        return value
                    time.sleep(interval)
                raise Abort(f'{label}: 시간 안에 되지 않음')

            def login(c, token):
                res = c.post('/auth/google', json={'id_token': token, 'aiTrainingAgreed': True, 'notifyAgreed': True})
                c.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
                c.post('/profile', json=PROFILE)
                return j(res).get('user', {}).get('user_id')

            def status(pid):
                return j(client.get(f'/projects/{pid}/status'))

            def wait_stage(pid, stage, match):
                return wait_for(f'{stage} 대기', lambda: (lambda b: b if b.get('stage') == stage and b.get('match_status') == match else None)(status(pid)))

            def create():
                res = client.post('/projects', data={'payload': json.dumps(FULL_INPUT)})
                if res.status_code != 201:
                    raise Abort(f'프로젝트 생성 실패 {res.status_code} {j(res)}')
                return j(res)['project_id']

            def candidates(pid):
                body = j(client.get(f'/projects/{pid}/match-candidates'))
                return body if body.get('status') != 'pending' else None

            def create_selected():
                pid = create()
                cands = wait_for('공고 후보', lambda: candidates(pid))
                if cands.get('status') != 'ready':
                    raise Abort(f"공고 후보를 못 받음: {cands.get('status')}")
                blocked = set(cands.get('blocked_notice_ids') or [])
                for cand in [c for c in cands['candidates'] if c['notice_id'] not in blocked][:3]:
                    body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': cand['notice_id']}))
                    if body.get('status') == 'pending':
                        body = wait_for('자격 확인', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                            j(client.get(f'/projects/{pid}/eligibility'))))
                    if body.get('status') == 'ready' and (body.get('eligibility') or {}).get('passed'):
                        return pid
                raise Abort('자격을 통과한 공고를 고르지 못함')

            def items():
                res = client.get('/admin/items')
                return {i['project_id']: i for i in (j(res) if res.status_code == 200 else [])}

            def run_id(pid):
                run = gateway.view_project(pid).run
                return run.run_id if run is not None else None

            try:
                # 0) 계정 — 관리자(U) · 일반 사용자(U2)
                uid = login(client, 'x')
                uid2 = login(client2, 'y')
                if uid is None or uid2 is None:
                    raise Abort('로그인 실패')
                with SessionLocal() as db:
                    db.query(User).filter(User.user_id == uid).update({'role': 'admin'})
                    db.commit()
                step('계정 준비(관리자 · 일반 사용자)', True, f'관리자 {uid}, 일반 {uid2}')
                leftover = gateway.active_work(str(uid))
                if leftover is not None and leftover.project_id is not None:
                    client.delete(f'/projects/{leftover.project_id}')
                    wait_for('앞 실행 정리', lambda: gateway.active_work(str(uid)) is None, timeout=60)

                # 1) 접근 권한
                paths = ['/admin/policy', '/admin/checklist', '/admin/items', '/admin/generation-alerts', '/admin/items/1/score-history',
                         '/admin/notices', '/admin/collection-status', '/admin/users', '/admin/faqs', '/admin/agent-executions',
                         '/admin/agent-tasks', '/admin/agent-ops-summary', '/admin/ops-summary', '/admin/recovery-items']
                denied = {p: client2.get(p).status_code for p in paths}
                step('1. 일반 사용자는 관리자 조회 전부 403', set(denied.values()) == {403}, f'{sorted(set(denied.values()))} {len(paths)}개')
                put = client2.put('/admin/policy/thresholds', json={'pass_threshold': 50, 'rerun_cap': 1, 'rework_cap': 1,
                                                                    'deviation_cap': 10, 'token_retry_cap': 1})
                step('1. 일반 사용자의 설정 변경도 403', put.status_code == 403, f'{put.status_code}')
                step('1. 로그인 안 한 요청은 401', anon.get('/admin/policy').status_code == 401, f'{anon.get("/admin/policy").status_code}')

                # 2) 관리자 설정 — 배점 합 검증 · 합격선 / 재작성 횟수 변경
                policy = j(client.get('/admin/policy'))
                originals['policy'] = dict(policy)
                bad = client.put('/admin/policy/scores', json={'doc_weight': 50, 'code_weight': 20, 'plan_weight': 20})
                step('2. 배점 합이 100이 아니면 422 · 값 그대로', bad.status_code == 422 and j(client.get('/admin/policy')) == policy,
                     f'{bad.status_code}')
                res = client.put('/admin/policy/thresholds', json={
                    'pass_threshold': 88, 'rerun_cap': policy['rerun_cap'], 'rework_cap': 2,
                    'deviation_cap': policy['deviation_cap'], 'token_retry_cap': policy['token_retry_cap']})
                step('2. 합격선 88 · 재작성 횟수 2로 변경', res.status_code == 200 and j(res)['pass_threshold'] == 88 and j(res)['rework_cap'] == 2,
                     f'{res.status_code}')

                # 3) 데이터 만들기 — nomatch / fail / done
                scenario.candidate_count = 0
                ids['nomatch'] = create()
                wait_for('nomatch 결과', lambda: candidates(ids['nomatch']))
                scenario.candidate_count = 10
                step('3. nomatch: 후보 0건(실행 건 없음)', run_id(ids['nomatch']) is None, f'프로젝트 {ids["nomatch"]}')

                ids['fail'] = create_selected()
                llm.plan('T-W1', ['timeout'] * ((RETRIES + 1) * (MAX_RESUME + 1)))
                client.post(f'/projects/{ids["fail"]}/plan/start')
                wait_for('fail 실패', lambda: status(ids['fail']).get('match_status') == 'failed')
                llm.script.clear()
                step('3. fail: 재개 상한 뒤 실패', status(ids['fail']).get('resume_count') == MAX_RESUME, f'프로젝트 {ids["fail"]}')

                ids['done'] = create_selected()
                pid = ids['done']
                client.post(f'/projects/{pid}/plan/start')
                wait_stage(pid, 'plan_review_pending', 'user_waiting')
                client.post(f'/projects/{pid}/prototype/start')
                wait_stage(pid, 'artifact_review', 'user_waiting')
                client.post(f'/projects/{pid}/final-review/start')
                res = client.post(f'/projects/{pid}/retry-task', json={'task_key': 'writing', 'bundle_id': '문제인식'})
                step('3. done: 재작성 요청', res.status_code == 200, f'{res.status_code}')
                wait_for('재작성 결과', lambda: j(client.get(f'/projects/{pid}/rework-result')).get('status') in ('완료', '실패'))
                wait_stage(pid, 'final_review_pending', 'user_waiting')
                res = client.post(f'/projects/{pid}/review/start')
                if res.status_code == 409 and (j(res).get('detail') or {}).get('confirmation_required'):
                    res = client.post(f'/projects/{pid}/review/start', json={'confirmed': True})
                wait_stage(pid, 'done', 'completed')
                result = j(client.get(f'/projects/{pid}/result'))
                verdict = result.get('verdict') or {}
                usage = {u['bundle_id']: (u['used'], u['remaining']) for u in result.get('bundle_usages', [])}
                step('3. 관리자 설정이 새 실행에 반영됨(합격선 88 · 재작성 횟수 2)',
                     verdict.get('pass_threshold') == 88 and usage.get('문제인식') == (1, 1),
                     f"합격선 {verdict.get('pass_threshold')} 문제인식 (사용, 남음)={usage.get('문제인식')}")

                # wait: 계획서 작성 단계를 붙잡는다
                ids['wait'] = create_selected()
                gate.clear()
                entered.clear()
                llm.respond('T-W1', blocking)
                client.post(f'/projects/{ids["wait"]}/plan/start')
                if not entered.wait(60):
                    raise Abort('워커가 T-W1에 들어가지 않음')
                wait_run = run_id(ids['wait'])
                # 관리자 조회는 열(updated_at)이 아니라 run_json 안의 updatedAt을 읽는다 — 둘 다 72시간 전으로 돌린다
                old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=72)).replace(tzinfo=None)
                with engine.begin() as conn:
                    doc = json.loads(conn.execute(text('SELECT run_json FROM orch_runs WHERE run_id=:r'), {'r': wait_run}).scalar())
                    doc['updatedAt'] = old.isoformat(timespec='microseconds') + 'Z'
                    conn.execute(text('UPDATE orch_runs SET updated_at=:t, run_json=:j WHERE run_id=:r'),
                                 {'t': old, 'j': json.dumps(doc, ensure_ascii=False), 'r': wait_run})

                # 4) 진행 현황
                table = items()
                step('4. 프로젝트마다 한 줄(4줄)', all(ids[k] in table for k in ids), f'{len(table)}줄')
                labels = {k: table[ids[k]]['status_label'] for k in ids if ids[k] in table}
                step('4. 상태 표기가 실제 상태와 같음', labels == {'nomatch': '공고 매칭 전', 'fail': '실패', 'done': '완료', 'wait': '진행중'}, f'{labels}')
                f = table[ids['fail']]
                step('4. 실패 줄: 재개 횟수 · 원인 분류 · 사유(관리자용)', f['generation_resume_count'] == MAX_RESUME
                     and f['generation_last_error_kind'] == '일시' and bool(f['generation_failure_reason']),
                     f"재개 {f['generation_resume_count']} 분류 {f['generation_last_error_kind']} 사유 {f['generation_failure_reason']}")
                d = table[ids['done']]
                total = (j(client.get(f'/projects/{ids["done"]}/result')).get('verdict') or {}).get('total_score')
                step('4. 완료 줄의 점수가 결과 화면 총점과 같음', d['score'] is not None and total is not None and abs(d['score'] - total) < 0.01,
                     f"관리자 {d['score']} / 결과 {total}")
                w = table[ids['wait']]
                step('4. 진행중이면서 72시간 전 갱신 → 정체(stalled)', w['stalled'] is True and w['status_label'] == '진행중', f"stalled={w['stalled']}")
                step('4. 나머지는 정체 아님', not table[ids['done']]['stalled'] and not table[ids['fail']]['stalled'] and not table[ids['nomatch']]['stalled'])

                # 5) 보관 / 복원
                res = client.put(f'/admin/items/{ids["nomatch"]}/archive', json={'archived': True})
                step('5. 실행 건이 없는 프로젝트는 보관 불가(400)', res.status_code == 400, f'{res.status_code}')
                res = client.put(f'/admin/items/{ids["wait"]}/archive', json={'archived': True})
                item = j(res)
                step('5. 진행중 프로젝트 보관 → 보관 표시 · 정체 해제', res.status_code == 200 and item.get('archived') is True and item.get('stalled') is False,
                     f"{res.status_code} archived={item.get('archived')} stalled={item.get('stalled')}")
                step('5. 보관해도 동시 실행 제한은 풀리지 않음(A-7 현재 동작)', gateway.active_work(str(uid)) is not None)
                res = client.put(f'/admin/items/{ids["wait"]}/archive', json={'archived': False})
                step('5. 복원 → 정체 다시 표시', res.status_code == 200 and j(res).get('archived') is False and j(res).get('stalled') is True)
                res = client.put(f'/admin/items/{ids["done"]}/archive', json={'archived': True})
                mine = [p['project_id'] for p in j(client.get('/projects'))]
                step('5. 관리자가 보관하면 사용자 목록에서 숨김', res.status_code == 200 and ids['done'] not in mine,
                     f"{res.status_code} archived_by 관리자 처리, 사용자 목록 {len(mine)}개")
                client.put(f'/admin/items/{ids["done"]}/archive', json={'archived': False})
                step('5. 복원하면 다시 보임', ids['done'] in [p['project_id'] for p in j(client.get('/projects'))])

                # wait 풀기 → 판단 대기
                gate.set()
                llm.responders.pop('T-W1', None)
                wait_stage(ids['wait'], 'plan_review_pending', 'user_waiting')
                w = items()[ids['wait']]
                step('5. 단계가 끝나면 판단 대기 · 정체 아님', w['status_label'] == '판단 대기' and w['stalled'] is False,
                     f"{w['status_label']} stalled={w['stalled']}")

                # 6) 이력보기
                hist = j(client.get(f'/admin/items/{ids["done"]}/score-history'))
                doc = hist.get('doc') or []
                step('6. 완료 프로젝트 이력: 문서 점수가 재작성 전 · 후 둘 이상, 재작성 표시 포함',
                     len(doc) >= 2 and any(e['is_rerun'] for e in doc) and any(not e['is_rerun'] for e in doc),
                     f"문서 {len(doc)}건 코드 {len(hist.get('code') or [])} 대조 {len(hist.get('plan') or [])} 재작성표시 {[e['is_rerun'] for e in doc]}")
                empty = j(client.get(f'/admin/items/{ids["nomatch"]}/score-history'))
                step('6. 실행 건이 없으면 빈 이력(오류 아님)', empty == {'doc': [], 'code': [], 'plan': []}, f'{empty}')
                step('6. 없는 프로젝트는 404', client.get('/admin/items/99999999/score-history').status_code == 404)

                # 7) 에이전트 실행 기록 · Task별 보기
                total_exec = scalar('SELECT COUNT(*) FROM orch_executions')
                done_exec = scalar('SELECT COUNT(*) FROM orch_executions WHERE project_id=:p', p=ids['done'])
                rows = j(client.get('/admin/agent-executions', params={'project_id': ids['done'], 'limit': 500}))
                step('7. 프로젝트별 실행 기록 수가 표를 센 값과 같음', len(rows) == done_exec, f'{len(rows)} / SQL {done_exec}')
                step('7. 첫 실행과 재작성 실행이 모두 있음(rerun_type)', {r['rerun_type'] for r in rows} == {'initial', 'rerun'},
                     f"{sorted({r['rerun_type'] for r in rows})} 트리거 {sorted({r['trigger'] for r in rows})}")
                failed_sql = scalar("SELECT COUNT(*) FROM orch_executions WHERE project_id=:p AND status='실패'", p=ids['fail'])
                web = j(client.get('/admin/agent-executions', params={'project_id': ids['fail'], 'status': 'failed', 'limit': 500}))
                ko = j(client.get('/admin/agent-executions', params={'project_id': ids['fail'], 'status': '실패', 'limit': 500}))
                step('7. 실패 거름(웹 표기 · 한글 표기)이 같고 표를 센 값과 같음',
                     len(web) == len(ko) == failed_sql > 0 and all(r['status'] == 'failed' and r['retryable'] is True for r in web),
                     f"웹 {len(web)} 한글 {len(ko)} SQL {failed_sql}, 재개 대상 표시 {sorted({r['retryable'] for r in web})}")
                step('7. limit 적용', len(j(client.get('/admin/agent-executions', params={'limit': 3}))) == 3)
                tasks = j(client.get('/admin/agent-tasks'))
                step('7. Task별 보기: 실행 기록 합이 표 전체와 같음', tasks and sum(t['total_executions'] for t in tasks) == total_exec,
                     f"Agent {len(tasks)}개 {[t['agent_name'] for t in tasks]} 합 {sum(t['total_executions'] for t in tasks)} / SQL {total_exec}")

                # 8) 운영 지표
                summary = j(client.get('/admin/ops-summary'))
                counts: dict[str, int] = {}
                for i in items().values():
                    counts[i['status_label']] = counts.get(i['status_label'], 0) + 1
                step('8. 운영 현황: 상태별 건수가 진행 현황과 같음', summary.get('status_counts') == counts, f"{summary.get('status_counts')}")
                step('8. 운영 현황: 합격선이 바꾼 값(88)', summary.get('pass_threshold') == 88, f"{summary.get('pass_threshold')}")
                pc, tc, pr = summary.get('pass_count'), summary.get('total_count'), summary.get('pass_rate')
                step('8. 운영 현황: 통과율 = 통과 수 / 점수 수', (tc == 0 and pr in (None, 0)) or (tc and pr is not None and abs(pr - pc / tc) < 0.01),
                     f'통과 {pc} / 점수 {tc} = {pr}')
                ops = j(client.get('/admin/agent-ops-summary'))
                initial_sql = scalar("SELECT COUNT(*) FROM orch_executions WHERE `trigger`='첫실행'")
                step('8. 에이전트 운영 지표: 실행 수가 표를 센 값과 같음', ops.get('total_executions') == total_exec
                     and ops.get('initial_executions') == initial_sql
                     and ops.get('initial_executions') + ops.get('rerun_executions') == total_exec,
                     f"전체 {ops.get('total_executions')}/{total_exec} 첫실행 {ops.get('initial_executions')}/{initial_sql} 재실행 {ops.get('rerun_executions')}")

                # 9) 생성 실패 알림
                alerts = [a for a in j(client.get('/admin/generation-alerts')) if a['project_id'] == ids['fail']]
                step('9. 실패 알림: 실패한 프로젝트 1건(미확인)', len(alerts) == 1 and alerts[0]['acknowledged_at'] is None, f'{len(alerts)}건')
                if alerts:
                    res = client.put(f"/admin/generation-alerts/{alerts[0]['alert_id']}/ack", json={'acknowledged': True})
                    gone = [a for a in j(client.get('/admin/generation-alerts')) if a['project_id'] == ids['fail']]
                    shown = [a for a in j(client.get('/admin/generation-alerts', params={'include_acknowledged': True}))
                             if a['project_id'] == ids['fail']]
                    step('9. 확인 처리하면 기본 목록에서 빠지고 전체 목록에는 남음', res.status_code == 200 and not gone and len(shown) == 1)

                # 10) 사용자 관리
                users = {u['user_id']: u for u in j(client.get('/admin/users'))}
                step('10. 사용자 목록에 두 계정', uid in users and uid2 in users)
                res = client.put(f'/admin/users/{uid2}', json={'status': 'suspended'})
                me2 = client2.get('/auth/me').status_code
                step('10. 계정 정지 → 그 사용자의 요청 거부(401)', res.status_code == 200 and me2 == 401, f'{res.status_code} /auth/me {me2}')
                res = client.put(f'/admin/users/{uid2}', json={'status': 'active'})
                step('10. 정지 해제 → 다시 사용 가능', res.status_code == 200 and client2.get('/auth/me').status_code == 200)
                res = client.put(f'/admin/users/{uid}', json={'role': 'user'})
                step('10. 자기 자신의 관리자 권한 해제는 422', res.status_code == 422, f'{res.status_code}')
                step('10. 잘못된 역할 값은 422 · 없는 사용자는 404', client.put(f'/admin/users/{uid2}', json={'role': 'boss'}).status_code == 422
                     and client.put('/admin/users/99999999', json={'role': 'user'}).status_code == 404)

                # 11) 체크리스트 · 공고 · 수집 현황 · FAQ
                checklist = j(client.get('/admin/checklist'))
                originals['checklist'] = [{'check_item_id': c['check_item_id'], 'weight': c['weight'], 'enabled': c['enabled']} for c in checklist]
                res = client.put('/admin/checklist', json=originals['checklist'])
                step('11. 체크리스트: 같은 값으로 저장 200', res.status_code == 200 and len(j(res)) == len(checklist), f'{res.status_code} {len(checklist)}항목')
                skewed = [dict(c) for c in originals['checklist']]
                first_enabled = next(c for c in skewed if c['enabled'])
                first_enabled['weight'] += 1
                res = client.put('/admin/checklist', json=skewed)
                after = {c['check_item_id']: c['weight'] for c in j(client.get('/admin/checklist'))}
                step('11. 카테고리 가중치 합이 어긋나면 422 · 값 그대로', res.status_code == 422
                     and after[first_enabled['check_item_id']] == next(c['weight'] for c in originals['checklist']
                                                                        if c['check_item_id'] == first_enabled['check_item_id']),
                     f'{res.status_code}')
                codes = {p: client.get(p).status_code for p in ('/admin/notices', '/admin/collection-status', '/admin/faqs')}
                step('11. 공고 · 수집 현황 · FAQ 조회가 오류 없이 답함', set(codes.values()) == {200}, f'{codes}')
            except Abort as exc:
                step('중단', False, str(exc))
            except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
                step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')
            finally:
                # 바꾼 설정을 원래대로, 붙잡은 단계를 풀고 남은 작업 정리
                gate.set()
                llm.responders.pop('T-W1', None)
                try:
                    pol = originals.get('policy')
                    if pol:
                        client.put('/admin/policy/scores', json={k: pol[k] for k in ('doc_weight', 'code_weight', 'plan_weight')})
                        client.put('/admin/policy/thresholds', json={k: pol[k] for k in (
                            'pass_threshold', 'rerun_cap', 'rework_cap', 'deviation_cap', 'token_retry_cap')})
                    if originals.get('checklist'):
                        client.put('/admin/checklist', json=originals['checklist'])
                    if 'wait' in ids:
                        client.delete(f"/projects/{ids['wait']}")  # 판단 대기로 남은 실행 건을 중단
                except Exception as exc:  # noqa: BLE001 - 정리 실패는 요약에 적는다
                    step('정리', False, f'{type(exc).__name__}: {str(exc)[:200]}')
                else:
                    if originals.get('policy'):
                        restored = j(client.get('/admin/policy'))
                        step('정리: 바꾼 설정을 원래대로 돌림', restored == originals['policy'], f'{restored}')
    finally:
        gate.set()
        worker.stop()
        worker_thread.join(timeout=60)

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
