"""재개 · 실패 경로를 실제 흐름으로 확인한다 (SB-261) — 워커를 이 프로세스 안에서 돌려 실패를 일부러 끼워 넣는다.

    python scripts/e2e_failure_resume.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

e2e_worker_flow.py와 달리 워커를 따로 띄우지 않는다(띄워 둔 워커가 있으면 끄고 돌린다 — 같은 DB를 두 워커가 가져가면
실패를 끼운 쪽이 아닌 워커가 일을 가져가 시험이 틀어진다). 이유: 워커의 스텁 Agent에 "이 호출은 시간 초과", "공고 서버 오류"
같은 상황을 만드는 장치(FakeLLM.plan · StubScenario)가 워커 프로세스 메모리에 있어서, 같은 프로세스에서 워커를 돌려야 조절할 수 있다.
웹은 평소처럼 TestClient로 부른다. 재시도 · 재개 간격은 짧게(재시도 2회 · 0.05초, 재개 3초 · 최대 2회) 줄여서 돈다.
조율 T-C1 · T-C3는 평소처럼 실제 LLM이라 OPENAI_API_KEY(agent-orchestration/.env)가 필요하다.

차례대로(앞이 뒤의 상태를 만든다):
  1. 사전 단계 실패   T-C2 공고 서버 오류 → 공고 후보 'failed'(X-C2-FAIL), 후보 0건 → 'no_match'(E-C2-NOMATCH), 둘 다 동시 실행 제한을 막지 않음
  2. 공고 선택 실패 → 다시 시도   G-01 오류 → 'failed'(고르기 전 화면 유지) → 오류를 없애고 다시 고르면 통과
  2b. 화면 5에서 다시 고른 공고 실패(SB-275)   G-01 오류 → 'failed' · 화면 5 유지, GET /eligibility는 notice_id를 붙이면 'failed'(없으면 이전 공고 결과)
  3. 일시 오류 → 재개 → 성공   계획서 작성(T-W1)이 시간 초과 3번(=재시도 소진) → '재개대기'(resume_count 1 · next_retry_at) → 재개 → 화면 6
  4. 재개 상한 초과 → 실패   시간 초과가 계속 → 재개 2번 뒤 '실패' → 관리자 알림 1건 · 사용자 알림 · 결과 409 · 새 프로젝트 가능
  5. 영구 오류 → 즉시 실패   잘못된 요청(400)이 재시도를 다 쓴 뒤 → 재개 없이 '실패' → 관리자 알림(원인 분류가 '일시'가 아님)
"""
import argparse
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

RETRIES = 2                      # 재시도 횟수 — 호출 한 번이 재시도를 다 쓰려면 RETRIES + 1번 실패해야 한다
TRIES_PER_EXHAUST = RETRIES + 1
MAX_RESUME = 2                   # 재개 횟수 상한 — (MAX_RESUME + 1)번 소진하면 실패로 확정된다
RESUME_WAIT_SEC = 3.0


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


class Abort(Exception):
    """이어갈 수 없는 실패."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--wait-sec', type=float, default=240, help='상태가 바뀌길 기다리는 최대 시간(초, 기본 240)')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from fastapi.testclient import TestClient
    from sbrain.bootstrap import build_app
    from sbrain.orchestrator.settings import ResumeSettings, RetrySettings, Settings
    from sbrain.worker import Worker, WorkerConfig

    import app.pipeline_stages as ps
    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app.database import SessionLocal
    from app.main import app
    from app.models import GenerationFailureAlert, User
    from app.orch.gateway import get_gateway

    projects.ORCH_WAIT_TIMEOUT_SEC = 5.0

    fast = Settings(
        retry=RetrySettings(retry_count=RETRIES, retry_interval_sec=0.05),
        resume=ResumeSettings(first_interval_min=RESUME_WAIT_SEC / 60, multiplier=1, max_count=MAX_RESUME, total_cap_hours=12))
    worker_app = build_app(settings=fast)  # 시작 요청이 만드는 실행 건에 이 설정이 고정된다
    worker = Worker(worker_app, WorkerConfig(poll_sec=0.3, threads=2, lease_sec=60), log=lambda line: None)
    worker_thread = threading.Thread(target=worker.run, name='e2e-worker', daemon=True)
    worker_thread.start()
    llm, scenario = worker_app.llm, worker_app.scenario

    def reset_faults():
        llm.script.clear()
        scenario.exhaust_in = set()
        scenario.candidate_count = 10

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    try:
        with TestClient(app) as client:
            security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
            auth_router.verify_google_id_token = security.verify_google_id_token
            gateway = get_gateway()
            me = {}

            def wait_for(label: str, cond, interval: float = 0.3, timeout: float | None = None):
                deadline = time.time() + (timeout or args.wait_sec)
                while time.time() < deadline:
                    value = cond()
                    if value:
                        return value
                    time.sleep(interval)
                raise Abort(f'{label}: 시간 안에 되지 않음')

            def create_project():
                return client.post('/projects', data={'payload': json.dumps(FULL_INPUT)})

            def status(pid):
                return j(client.get(f'/projects/{pid}/status'))

            def run_progress(pid):
                run = gateway.view_project(pid).run
                return run.progress if run is not None else None

            def alerts_of(pid):
                with SessionLocal() as db:
                    rows = db.query(GenerationFailureAlert).filter(GenerationFailureAlert.project_id == pid).all()
                    return [{'stage': r.stage, 'resume_count': r.resume_count, 'last_error_kind': r.last_error_kind,
                             'failure_reason': r.failure_reason, 'alert_id': r.alert_id} for r in rows]

            def notification_kinds(pid):
                res = client.get('/projects/notifications')
                return sorted(n['kind'] for n in (j(res) if res.status_code == 200 else []) if n['project_id'] == pid)

            def candidates(pid):
                body = j(client.get(f'/projects/{pid}/match-candidates'))
                return body if body.get('status') != 'pending' else None

            def new_project_with_candidates():
                res = create_project()
                if res.status_code != 201:
                    raise Abort(f'프로젝트 생성 실패 {res.status_code} {j(res)}')
                pid = j(res)['project_id']
                cands = wait_for('공고 후보', lambda: candidates(pid))
                if cands.get('status') != 'ready':
                    raise Abort(f"공고 후보를 못 받음: {cands.get('status')} {cands.get('message')}")
                return pid, cands

            def select_eligible(pid, cands):
                blocked = set(cands.get('blocked_notice_ids') or [])
                for cand in [c for c in cands['candidates'] if c['notice_id'] not in blocked][:3]:
                    body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': cand['notice_id']}))
                    if body.get('status') == 'pending':
                        body = wait_for('자격 확인', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                            j(client.get(f'/projects/{pid}/eligibility'))))
                    if body.get('status') == 'ready' and (body.get('eligibility') or {}).get('passed'):
                        return cand['notice_id']
                raise Abort('자격을 통과한 공고를 고르지 못함')

            def watch_plan(pid, *, until):
                """계획서 작성이 끝나거나 until(status)이 참이 될 때까지 상태를 자주 읽으며 관찰한 값을 모은다."""
                seen = {'match': [], 'max_resume': 0, 'retry_at': False}
                deadline = time.time() + args.wait_sec
                while time.time() < deadline:
                    body = status(pid)
                    if not seen['match'] or seen['match'][-1] != body.get('match_status'):
                        seen['match'].append(body.get('match_status'))
                    seen['max_resume'] = max(seen['max_resume'], body.get('resume_count') or 0)
                    if body.get('match_status') == ps.GENERATION_STATUS_WAITING_RESUME and body.get('next_retry_at'):
                        seen['retry_at'] = True
                    if until(body):
                        return body, seen
                    time.sleep(0.2)
                raise Abort(f'계획서 작성 관찰: 시간 안에 끝나지 않음(관찰 {seen})')

            def release(pid):
                client.delete(f'/projects/{pid}')
                wait_for('정리', lambda: gateway.active_work(str(me['id'])) is None, timeout=60)

            try:
                # 0) 로그인 · 동의 · 프로필
                res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
                step('로그인', res.status_code == 200, f'{res.status_code}')
                me['id'] = j(res).get('user', {}).get('user_id')
                client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
                res = client.post('/profile', json=PROFILE)
                if not step('프로필 저장', res.status_code == 201, f'{res.status_code}') or me['id'] is None:
                    raise Abort('프로필 저장 실패')

                # 앞서 중단된 실행이 남긴 진행 중 작업이 있으면 정리한다(다시 돌려도 막히지 않게)
                leftover = gateway.active_work(str(me['id']))
                if leftover is not None and leftover.project_id is not None:
                    release(int(leftover.project_id))
                    step('앞 실행이 남긴 진행 중 작업 정리', True, f'프로젝트 {leftover.project_id}')

                # 1) 사전 단계 실패
                reset_faults()
                scenario.exhaust_in = {'T-C2'}
                res = create_project()
                pid1 = j(res)['project_id'] if res.status_code == 201 else None
                step('1. 프로젝트 생성(T-C2 오류 주입)', res.status_code == 201, f'{res.status_code}')
                body = wait_for('후보 결과', lambda: candidates(pid1))
                start = gateway.start_status(pid1)
                step('1. T-C2 오류 → 공고 후보 failed', body.get('status') == 'failed' and start.code == 'X-C2-FAIL',
                     f"status={body.get('status')} 요청={start.status}/{start.code} 안내={body.get('message')}")
                step('1. 실패한 요청은 동시 실행 제한을 막지 않음', gateway.active_work(str(me['id'])) is None,
                     f'active_work={gateway.active_work(str(me["id"]))}')

                reset_faults()
                scenario.candidate_count = 0
                res = create_project()
                pid1b = j(res)['project_id'] if res.status_code == 201 else None
                step('1. 후보 0건 상황에서 프로젝트 생성', res.status_code == 201, f'{res.status_code}')
                body = wait_for('후보 결과', lambda: candidates(pid1b))
                start = gateway.start_status(pid1b)
                step('1. 후보 0건 → no_match', body.get('status') == 'no_match' and start.code == 'E-C2-NOMATCH',
                     f"status={body.get('status')} 요청={start.status}/{start.code}")

                # 2) 공고 선택 실패 → 다시 시도
                reset_faults()
                pid, cands = new_project_with_candidates()
                step('2. 정상 상황의 새 프로젝트(후보 받음)', True, f'프로젝트 {pid} 후보 {len(cands["candidates"])}건')
                scenario.exhaust_in = {'G-01'}
                first = next(c for c in cands['candidates'] if c['notice_id'] not in set(cands.get('blocked_notice_ids') or []))
                body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': first['notice_id']}))
                if body.get('status') == 'pending':
                    body = wait_for('자격 확인', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                        j(client.get(f'/projects/{pid}/eligibility'))))
                step('2. G-01 오류 → 선택 failed(고르기 전 화면)', body.get('status') == 'failed',
                     f"status={body.get('status')} code={body.get('code')} 안내={body.get('message')}")
                again = candidates(pid) or {}
                run = gateway.view_project(pid).run
                step('2. 후보가 그대로 남고 실행 건은 화면 3 대기', again.get('status') == 'ready' and bool(again.get('candidates'))
                     and run is not None and run.progress == '사용자대기',
                     f"후보={again.get('status')} 실행 건={(run.progress, run.step) if run else None}")
                reset_faults()
                chosen = select_eligible(pid, again)
                step('2. 오류를 없애고 다시 고르면 통과', True, f'공고 {chosen}')

                # 2b) 화면 5에서 다시 고른 공고의 자격 확인 실패 (SB-275) — 화면 4는 이전 공고 값 그대로다
                other = next((c['notice_id'] for c in again['candidates']
                              if c['notice_id'] not in set(again.get('blocked_notice_ids') or []) and c['notice_id'] != chosen), None)
                if other is None:
                    step('2b. 다시 고를 다른 공고', False, '후보가 하나뿐')
                else:
                    scenario.exhaust_in = {'G-01'}
                    body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': other}))
                    polled_with_id = body.get('status') == 'pending'
                    if polled_with_id:  # 프론트가 하는 대로 방금 고른 공고 ID를 붙여 폴링한다
                        body = wait_for('자격 확인(다시 고르기)', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                            j(client.get(f'/projects/{pid}/eligibility', params={'notice_id': other}))))
                    st = status(pid)
                    step('2b. 다시 고른 공고의 G-01 오류 → failed', body.get('status') == 'failed' and body.get('eligibility') is None,
                         f"status={body.get('status')} code={body.get('code')} (pending 뒤 폴링={polled_with_id})")
                    step('2b. 실패 뒤에도 화면 5 대기 지점', st.get('screen') == 5, f"screen={st.get('screen')} stage={st.get('stage')}")
                    kept = j(client.get(f'/projects/{pid}/eligibility'))
                    step('2b. notice_id 없이 읽으면 이전 공고 결과(명세 6.1)', kept.get('status') == 'ready'
                         and (kept.get('match') or {}).get('notice_id') == chosen,
                         f"status={kept.get('status')} 공고={(kept.get('match') or {}).get('notice_id')}(이전 {chosen})")
                    asked = j(client.get(f'/projects/{pid}/eligibility', params={'notice_id': other}))
                    step('2b. notice_id를 붙이면 failed(이전 공고를 ready로 주지 않음)',
                         asked.get('status') == 'failed' and asked.get('eligibility') is None and asked.get('match') is None,
                         f"status={asked.get('status')} code={asked.get('code')}")
                    reset_faults()
                    body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': other}))
                    if body.get('status') == 'pending':
                        body = wait_for('자격 확인(오류 없앤 뒤)', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                            j(client.get(f'/projects/{pid}/eligibility', params={'notice_id': other}))))
                    step('2b. 오류를 없애고 다시 고르면 notice_id를 붙여도 ready',
                         body.get('status') == 'ready' and (body.get('match') or {}).get('notice_id') == other,
                         f"status={body.get('status')} 공고={(body.get('match') or {}).get('notice_id')}")
                    if not (body.get('eligibility') or {}).get('passed'):  # 3)에서 계획서를 쓰려면 통과한 공고여야 한다
                        j(client.post(f'/projects/{pid}/generate', json={'notice_id': chosen}))
                        wait_for('통과 공고로 되돌리기', lambda: (lambda b: b if b.get('status') == 'ready' else None)(
                            j(client.get(f'/projects/{pid}/eligibility', params={'notice_id': chosen}))))

                # 3) 일시 오류 → 재개 → 성공
                llm.plan('T-W1', ['timeout'] * TRIES_PER_EXHAUST)
                res = client.post(f'/projects/{pid}/plan/start')
                step('3. 계획서 작성 시작(T-W1 시간 초과 주입)', res.status_code == 200, f'{res.status_code}')
                body, seen = watch_plan(pid, until=lambda b: b.get('stage') == 'plan_review_pending'
                                        and b.get('match_status') == 'user_waiting')
                step('3. 재개대기가 보이고 재개 시각이 내려옴', ps.GENERATION_STATUS_WAITING_RESUME in seen['match'] and seen['retry_at'],
                     f"관찰 {seen['match']} resume_count 최대 {seen['max_resume']} next_retry_at={seen['retry_at']}")
                step('3. 재개 뒤 화면 6 도착 · 재개 횟수 초기화', seen['max_resume'] == 1 and body.get('resume_count') == 0,
                     f"최대 {seen['max_resume']} 마지막 {body.get('resume_count')}")
                result = j(client.get(f'/projects/{pid}/result'))
                step('3. 결과 계획서 있음', bool((result.get('plan') or {}).get('sections')),
                     f"섹션 {len((result.get('plan') or {}).get('sections', []))}개")
                step('3. 실패 알림 · 관리자 알림 없음', not alerts_of(pid) and '실패' not in ''.join(notification_kinds(pid)),
                     f'관리자 알림 {len(alerts_of(pid))}건 사용자 알림 {notification_kinds(pid)}')
                release(pid)

                # 4) 재개 상한 초과 → 실패
                reset_faults()
                pid, cands = new_project_with_candidates()
                select_eligible(pid, cands)
                llm.plan('T-W1', ['timeout'] * (TRIES_PER_EXHAUST * (MAX_RESUME + 1)))
                res = client.post(f'/projects/{pid}/plan/start')
                step('4. 계획서 작성 시작(시간 초과를 계속 주입)', res.status_code == 200, f'{res.status_code}')
                body, seen = watch_plan(pid, until=lambda b: b.get('match_status') == ps.GENERATION_STATUS_FAILED)
                step('4. 재개를 상한만큼 한 뒤 실패', seen['max_resume'] == MAX_RESUME and ps.GENERATION_STATUS_WAITING_RESUME in seen['match'],
                     f"관찰 {seen['match']} resume_count 최대 {seen['max_resume']}(상한 {MAX_RESUME})")
                step('4. 사용자 응답에 실패 사유를 싣지 않음', body.get('failure_reason') is None, f"failure_reason={body.get('failure_reason')!r}")
                alerts = alerts_of(pid)
                step('4. 관리자 알림 1건(원인 \'일시\')', len(alerts) == 1 and alerts[0]['last_error_kind'] == '일시'
                     and alerts[0]['resume_count'] == MAX_RESUME, f'{alerts}')
                kinds = notification_kinds(pid)
                step('4. 사용자 알림에 실패 1건', kinds.count('실패') == 1, f'알림 {kinds}')
                res = client.get(f'/projects/{pid}/result')
                step('4. 실패한 실행의 결과 조회 → 409', res.status_code == 409, f'{res.status_code}')
                res = client.get('/projects')
                row = next((p for p in j(res) if p['project_id'] == pid), {})
                step('4. 목록 표시 \'문제 발생\'', row.get('display_status') == ps.status_to_display(ps.GENERATION_STATUS_FAILED),
                     f"display={row.get('display_status')} match={row.get('match_status')}")
                res = client.post(f'/projects/{pid}/plan/start')
                again = j(res)
                step('4. 실패한 실행에 단계 시작을 또 불러도 상태만 돌려줌(다시 돌지 않음)',
                     res.status_code == 200 and again.get('match_status') == ps.GENERATION_STATUS_FAILED
                     and again.get('resume_count') == MAX_RESUME and len(alerts_of(pid)) == 1,
                     f"{res.status_code} match={again.get('match_status')} resume_count={again.get('resume_count')} 알림 {len(alerts_of(pid))}건")
                step('4. 실패한 실행은 동시 실행 제한을 막지 않음', gateway.active_work(str(me['id'])) is None,
                     f'active_work={gateway.active_work(str(me["id"]))}')
                # 관리자 화면에서도 보인다 — 이 계정을 잠깐 관리자로 올려 알림 목록을 읽는다(로컬 시험 DB)
                with SessionLocal() as db:
                    db.query(User).filter(User.user_id == me['id']).update({'role': 'admin'})
                    db.commit()
                try:
                    res = client.get('/admin/generation-alerts')
                    listed = [a for a in (j(res) if res.status_code == 200 else []) if a['project_id'] == pid]
                    step('4. 관리자 알림 API에 보임', res.status_code == 200 and len(listed) == 1,
                         f"{res.status_code} 이 프로젝트 {len(listed)}건 {listed[0]['stage'] if listed else ''}")
                    if listed:
                        res = client.put(f"/admin/generation-alerts/{listed[0]['alert_id']}/ack", json={'acknowledged': True})
                        step('4. 관리자 알림 확인 처리', res.status_code == 200 and j(res).get('acknowledged_at') is not None,
                             f'{res.status_code}')
                finally:
                    with SessionLocal() as db:
                        db.query(User).filter(User.user_id == me['id']).update({'role': 'user'})
                        db.commit()

                # 5) 영구 오류 → 즉시 실패
                reset_faults()
                pid, cands = new_project_with_candidates()
                select_eligible(pid, cands)
                # 호출 안의 재시도는 오류 종류와 상관없이 횟수만큼 돈다 — 종류('입력')는 소진된 뒤 재개 · 실패를 가를 때만 쓰인다
                llm.plan('T-W1', ['bad_request'] * TRIES_PER_EXHAUST)
                res = client.post(f'/projects/{pid}/plan/start')
                step('5. 계획서 작성 시작(잘못된 요청 오류 주입)', res.status_code == 200, f'{res.status_code}')
                body, seen = watch_plan(pid, until=lambda b: b.get('match_status') == ps.GENERATION_STATUS_FAILED)
                step('5. 재개 없이 바로 실패', seen['max_resume'] == 0 and ps.GENERATION_STATUS_WAITING_RESUME not in seen['match'],
                     f"관찰 {seen['match']} resume_count 최대 {seen['max_resume']}")
                alerts = alerts_of(pid)
                step('5. 관리자 알림 1건(원인이 \'일시\'가 아님)', len(alerts) == 1 and alerts[0]['last_error_kind'] != '일시', f'{alerts}')
                step('5. 사용자 알림에 실패 1건', notification_kinds(pid).count('실패') == 1, f'알림 {notification_kinds(pid)}')
            except Abort as exc:
                step('중단', False, str(exc))
            except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
                step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')
    finally:
        worker.stop()
        worker_thread.join(timeout=60)

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
