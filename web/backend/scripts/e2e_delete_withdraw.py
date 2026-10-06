"""영구 삭제 · 계정 탈퇴와 BUSY(워커가 단계를 도는 중)를 실제 흐름으로 확인한다 (SB-259).

    python scripts/e2e_delete_withdraw.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

e2e_failure_resume.py처럼 워커를 이 프로세스 안에서 돌린다(따로 띄운 워커가 있으면 끈다). 계획서 작성(T-W1) 호출을
이벤트로 붙잡아 "워커가 단계를 도는 중" 상태를 정확히 만든다 — 붙잡은 동안 실행 건은 워커가 점유하고 있다.
조율 T-C1 · T-C3는 평소처럼 실제 LLM이라 OPENAI_API_KEY(agent-orchestration/.env)가 필요하다.

차례대로:
  1. 영구 삭제(쉬는 중)   화면 6 대기 프로젝트 → 204, 웹 행 · 알림 삭제, 산출물 삭제, 실행 기록은 남고 project_id만 비워짐, 삭제 기록 +1
  2. 영구 삭제 + BUSY     단계를 도는 중 → 409(웹 행 그대로, 중단 요청만 남음) → 단계가 끝난 뒤 다시 → 204
  3. 탈퇴 + BUSY          프로젝트 2개(하나는 보관, 하나는 단계 진행 중) → 409(세션 · 웹 행 그대로, 먼저 처리한 프로젝트는 산출물만 지워짐)
                          → 단계가 끝난 뒤 다시 → 204, 웹 행 · 오케스트레이터 데이터 삭제, 통계 줄(탈퇴)만 남고 세션 무효
  4. 탈퇴 뒤 재가입       같은 구글 계정으로 다시 로그인 → 비어 있는 새 계정
  5. 탈퇴 + 시작 요청     (a) 프로젝트를 만든 직후(대기 중) 탈퇴 → 204 (b) 워커가 요청을 처리 중일 때 탈퇴 → 409 → 요청이 끝난 뒤 다시 → 204. 실행 건이 남지 않음
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


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


class Abort(Exception):
    """이어갈 수 없는 실패."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--wait-sec', type=float, default=180, help='상태가 바뀌길 기다리는 최대 시간(초, 기본 180)')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from fastapi.testclient import TestClient
    from sbrain.bootstrap import build_app
    from sbrain.worker import Worker, WorkerConfig
    from sqlalchemy import text

    import app.routers.auth as auth_router
    import app.security as security
    from app.database import SessionLocal, engine
    from app.main import app
    from app.models import Notification, PermanentDeletionLog, Project, User
    from app.orch.gateway import get_gateway

    worker_app = build_app()
    worker = Worker(worker_app, WorkerConfig(poll_sec=0.3, threads=2, lease_sec=60), log=lambda line: None)
    worker_thread = threading.Thread(target=worker.run, name='e2e-worker', daemon=True)
    worker_thread.start()
    llm = worker_app.llm

    gate, entered = threading.Event(), threading.Event()

    def blocking(request):
        entered.set()
        gate.wait(120)
        return '{"ok": true}'

    def arm():
        """다음 T-W1 호출을 gate.set()까지 붙잡는다."""
        gate.clear()
        entered.clear()
        llm.respond('T-W1', blocking)

    def disarm():
        gate.set()
        llm.responders.pop('T-W1', None)

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    def scalar(sql: str, **params):
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    try:
        with TestClient(app) as client:
            security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
            auth_router.verify_google_id_token = security.verify_google_id_token
            gateway = get_gateway()
            me: dict = {}

            def wait_for(label: str, cond, interval: float = 0.3, timeout: float | None = None):
                deadline = time.time() + (timeout or args.wait_sec)
                while time.time() < deadline:
                    value = cond()
                    if value:
                        return value
                    time.sleep(interval)
                raise Abort(f'{label}: 시간 안에 되지 않음')

            def login():
                res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
                me['id'] = j(res).get('user', {}).get('user_id')
                client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
                res2 = client.post('/profile', json=PROFILE)
                return res.status_code == 200 and res2.status_code == 201 and me['id'] is not None

            def create_project():
                return client.post('/projects', data={'payload': json.dumps(FULL_INPUT)})

            def run_of(pid):
                return gateway.view_project(pid).run

            def progress(pid):
                run = run_of(pid)
                return run.progress if run is not None else None

            def request_status(pid):
                req = gateway.start_status(pid)
                return req.status if req is not None else None

            def candidates(pid):
                body = j(client.get(f'/projects/{pid}/match-candidates'))
                return body if body.get('status') != 'pending' else None

            def new_project_selected():
                res = create_project()
                if res.status_code != 201:
                    raise Abort(f'프로젝트 생성 실패 {res.status_code} {j(res)}')
                pid = j(res)['project_id']
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

            def reach_screen6(pid):
                client.post(f'/projects/{pid}/plan/start')
                wait_for('화면 6', lambda: (lambda b: b.get('stage') == 'plan_review_pending'
                                           and b.get('match_status') == 'user_waiting')(j(client.get(f'/projects/{pid}/status'))))

            def start_blocked_stage(pid):
                """계획서 작성을 시작하고 워커가 T-W1 호출 안에서 멈춘(단계를 도는 중) 상태를 만든다."""
                arm()
                res = client.post(f'/projects/{pid}/plan/start')
                if res.status_code != 200:
                    raise Abort(f'계획서 작성 시작 실패 {res.status_code}')
                if not entered.wait(60):
                    raise Abort('워커가 T-W1에 들어가지 않음 — 따로 떠 있는 워커가 있으면 끄세요')

            def web_counts(pid):
                with SessionLocal() as db:
                    return {'project': db.get(Project, pid) is not None,
                            'notifications': db.query(Notification).filter(Notification.project_id == pid).count()}

            def orch_counts(run_id):
                return {'artifacts': scalar('SELECT COUNT(*) FROM orch_artifact_versions WHERE run_id=:r', r=run_id),
                        'pointers': scalar('SELECT COUNT(*) FROM orch_artifact_pointers WHERE run_id=:r', r=run_id),
                        'executions': scalar('SELECT COUNT(*) FROM orch_executions WHERE run_id=:r', r=run_id),
                        'run_row': scalar('SELECT COUNT(*) FROM orch_runs WHERE run_id=:r', r=run_id)}

            def account_counts(account):
                return {'runs': scalar('SELECT COUNT(*) FROM orch_runs WHERE account_id=:a', a=account),
                        'requests': scalar('SELECT COUNT(*) FROM orch_start_requests WHERE account_id=:a', a=account)}

            try:
                if not step('로그인 · 동의 · 프로필', login()):
                    raise Abort('로그인 실패')
                leftover = gateway.active_work(str(me['id']))
                if leftover is not None and leftover.project_id is not None:
                    client.delete(f'/projects/{leftover.project_id}')
                    wait_for('앞 실행 정리', lambda: gateway.active_work(str(me['id'])) is None, timeout=60)

                # 1) 영구 삭제(쉬는 중)
                pid = new_project_selected()
                reach_screen6(pid)
                run_id = run_of(pid).run_id
                before_web, before_orch = web_counts(pid), orch_counts(run_id)
                with SessionLocal() as db:
                    logs_before = db.query(PermanentDeletionLog).count()
                step('1. 삭제 전: 산출물 · 알림이 있음', before_orch['artifacts'] > 0 and before_web['notifications'] > 0,
                     f'산출물 버전 {before_orch["artifacts"]}개, 알림 {before_web["notifications"]}건, 실행 기록 {before_orch["executions"]}건')
                res = client.delete(f'/projects/{pid}/permanent')
                step('1. 영구 삭제', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                after_web, after_orch = web_counts(pid), orch_counts(run_id)
                step('1. 웹 행 · 알림이 지워짐', not after_web['project'] and after_web['notifications'] == 0, f'{after_web}')
                step('1. 산출물은 지워지고 실행 기록은 남음', after_orch['artifacts'] == 0 and after_orch['pointers'] == 0
                     and after_orch['executions'] == before_orch['executions'] and after_orch['run_row'] == 1, f'{after_orch}')
                orphan = scalar('SELECT project_id FROM orch_runs WHERE run_id=:r', r=run_id)
                step('1. 실행 건의 project_id는 비워짐 · 진행 중 아님', orphan is None and gateway.active_work(str(me['id'])) is None,
                     f'project_id={orphan} 상태={scalar("SELECT progress FROM orch_runs WHERE run_id=:r", r=run_id)}')
                with SessionLocal() as db:
                    logs_after = db.query(PermanentDeletionLog).count()
                step('1. 삭제 기록(식별자 없음) +1', logs_after == logs_before + 1, f'{logs_before} → {logs_after}')
                step('1. 삭제한 프로젝트는 이제 404', client.get(f'/projects/{pid}').status_code == 404)

                # 2) 영구 삭제 + BUSY
                pid = new_project_selected()
                start_blocked_stage(pid)
                run_id = run_of(pid).run_id
                res = client.delete(f'/projects/{pid}/permanent')
                body = j(res)
                step('2. 단계를 도는 중 영구 삭제 → 409(BUSY)', res.status_code == 409, f'{res.status_code} {body}')
                step('2. 웹 행은 그대로', client.get(f'/projects/{pid}').status_code == 200 and web_counts(pid)['project'])
                abort_flag = scalar('SELECT abort_requested FROM orch_runs WHERE run_id=:r', r=run_id)
                step('2. 중단 요청만 남음(단계는 아직 진행 중)', bool(abort_flag) and progress(pid) in ('실행',),
                     f'abort_requested={abort_flag} 진행={progress(pid)}')
                disarm()
                wait_for('단계 종료 · 중단 반영', lambda: progress(pid) == '중단')
                step('2. 단계가 끝나자 실행 건이 중단됨', True, f'진행={progress(pid)}')
                res = client.delete(f'/projects/{pid}/permanent')
                after_orch = orch_counts(run_id)
                step('2. 다시 영구 삭제 → 204', res.status_code == 204 and not web_counts(pid)['project']
                     and after_orch['artifacts'] == 0, f'{res.status_code} 산출물 {after_orch["artifacts"]}개')

                # 3) 탈퇴 + BUSY — 프로젝트 C(보관) · D(단계 진행 중)
                account = str(me['id'])
                pid_c = new_project_selected()
                reach_screen6(pid_c)
                run_c = run_of(pid_c).run_id
                res = client.delete(f'/projects/{pid_c}')
                step('3. 프로젝트 C 휴지통(보관)', res.status_code == 204, f'{res.status_code}')
                pid_d = new_project_selected()
                start_blocked_stage(pid_d)
                run_d = run_of(pid_d).run_id
                with engine.connect() as conn:
                    stats_before = conn.execute(text("SELECT COUNT(*) FROM orch_log_stats WHERE reason='탈퇴'")).scalar()
                res = client.delete('/auth/me')
                step('3. 단계를 도는 중 탈퇴 → 409(BUSY)', res.status_code == 409, f'{res.status_code} {j(res)}')
                step('3. 세션은 그대로', client.get('/auth/me').status_code == 200)
                with SessionLocal() as db:
                    user_row = db.get(User, me['id']) is not None
                step('3. 웹 행은 그대로(사용자 · 프로젝트 2개)', user_row and web_counts(pid_c)['project'] and web_counts(pid_d)['project'])
                step('3. 먼저 처리한 프로젝트 C는 산출물만 지워짐(다시 부르면 남은 것부터)',
                     orch_counts(run_c)['artifacts'] == 0 and orch_counts(run_d)['artifacts'] > 0,
                     f"C 산출물 {orch_counts(run_c)['artifacts']}개, D 산출물 {orch_counts(run_d)['artifacts']}개")
                disarm()
                wait_for('D 중단 반영', lambda: progress(pid_d) == '중단')
                res = client.delete('/auth/me')
                step('3. 단계가 끝난 뒤 다시 탈퇴 → 204', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                step('3. 세션 무효', client.get('/auth/me').status_code == 401)
                with SessionLocal() as db:
                    gone = db.get(User, me['id']) is None and db.get(Project, pid_c) is None and db.get(Project, pid_d) is None
                step('3. 웹 행(사용자 · 프로젝트) 삭제', gone)
                counts = account_counts(account)
                step('3. 오케스트레이터의 실행 건 · 시작 요청이 남지 않음', counts == {'runs': 0, 'requests': 0}, f'{counts}')
                step('3. 산출물이 남지 않음', orch_counts(run_c)['run_row'] == 0 and orch_counts(run_d)['artifacts'] == 0
                     and orch_counts(run_c)['artifacts'] == 0, f'C {orch_counts(run_c)} D {orch_counts(run_d)}')
                with engine.connect() as conn:
                    stats_after = conn.execute(text("SELECT COUNT(*) FROM orch_log_stats WHERE reason='탈퇴'")).scalar()
                stat_columns = [r[0] for r in engine.connect().execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='orch_log_stats' "
                    "AND table_schema=DATABASE()")).fetchall()]
                id_columns = [c for c in stat_columns if c in ('account_id', 'project_id', 'run_id', 'request_id')]
                step('3. 통계 줄(탈퇴)이 늘었고 계정 · 프로젝트 · 실행 건 식별자 열이 없음', stats_after > stats_before and not id_columns,
                     f'{stats_before} → {stats_after}줄, 식별자 열 {id_columns}')

                # 4) 재가입
                old_id = me['id']
                step('4. 같은 구글 계정으로 다시 로그인(새 계정)', login() and me['id'] != old_id, f'이전 {old_id} → 새 {me["id"]}')
                step('4. 새 계정은 비어 있음', j(client.get('/projects')) == [] and gateway.active_work(str(me['id'])) is None)

                # 5) 탈퇴 + 시작 요청 처리 중
                res = create_project()
                step('5. 프로젝트 생성 직후(시작 요청 처리 중)', res.status_code == 201, f'{res.status_code}')
                account = str(me['id'])
                codes = []
                deadline = time.time() + 90
                while time.time() < deadline:
                    res = client.delete('/auth/me')
                    codes.append(res.status_code)
                    if res.status_code != 409:
                        break
                    time.sleep(0.5)
                step('5a. 시작 요청이 아직 대기 중일 때 탈퇴 → 바로 204(요청 취소)', codes[-1] == 204, f'응답 순서 {codes}')
                counts = account_counts(account)
                step('5a. 실행 건 · 시작 요청이 남지 않음', counts == {'runs': 0, 'requests': 0}, f'{counts}')

                # 5b) 워커가 시작 요청을 처리 중일 때 탈퇴 — 취소 요청만 남고 BUSY, 요청이 끝난 뒤 다시 하면 204
                seen_busy = False
                for attempt in range(1, 4):
                    if not login():
                        raise Abort('5b 재가입 실패')
                    account = str(me['id'])
                    res = create_project()
                    cand = j(res)['project_id'] if res.status_code == 201 else None
                    if cand is None:
                        raise Abort(f'5b 프로젝트 생성 실패 {res.status_code}')
                    wait_for('요청 처리 중', lambda pid=cand: request_status(pid) in ('처리중', '완료', '실패'), interval=0.05)
                    first = client.delete('/auth/me')
                    codes = [first.status_code]
                    while codes[-1] == 409 and len(codes) < 200:
                        time.sleep(0.5)
                        codes.append(client.delete('/auth/me').status_code)
                    step(f'5b. 요청 처리 중 탈퇴 (시도 {attempt})', codes[-1] == 204 and codes[0] == 409,
                         f'응답 순서 {codes}')
                    counts = account_counts(account)
                    step(f'5b. 끝난 뒤 실행 건 · 시작 요청이 남지 않음 (시도 {attempt})', counts == {'runs': 0, 'requests': 0}, f'{counts}')
                    if codes[0] == 409:
                        seen_busy = True
                        break
                if not seen_busy:
                    raise Abort('5b: 처리 중 BUSY 경로를 만들지 못함')
            except Abort as exc:
                step('중단', False, str(exc))
            except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
                step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')
    finally:
        disarm()
        worker.stop()
        worker_thread.join(timeout=60)

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
