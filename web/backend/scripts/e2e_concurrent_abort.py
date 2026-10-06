"""실제 워커 + 로컬 MySQL로 "동시 실행 1건 제한"과 "중단"을 확인한다 (SB-260).

    python scripts/e2e_concurrent_abort.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

사전 준비는 e2e_worker_flow.py와 같다(로컬 MySQL + prepare_local_mysql.py + 워커를 따로 띄움). 이 스크립트는 한 계정으로
프로젝트를 여러 개 만들어 가며 아래를 차례로 본다 — 앞 시나리오가 뒤 시나리오의 상태를 만들기 때문에 순서대로 돈다.

  1. 시작 요청이 처리되는 중에 새 프로젝트  → 409 blocked(진행 중인 프로젝트 안내), 웹 행이 생기지 않음
  2. 실행 건이 생긴 뒤(화면 3)에 새 프로젝트 → 409 blocked, 진행 단계 안내
  3. 휴지통(DELETE /projects/{id})으로 중단   → 204, 실행 건 '중단', 목록에서 숨김(보관), 동시 실행 제한이 풀려 새 프로젝트 201
  4. 시작 요청이 처리되는 중에 중단          → 204. 대기 중에 바로 지우는 경로(a)와, 워커가 처리 중일 때 취소 요청을 남기는 경로(b)
                                              를 각각 만든다. (b)는 요청이 '처리중'이 되는 것을 보고 중단하며, 요청은 '취소'로 끝나고 실행 건은 안 생긴다
  5. 워커가 단계를 도는 중에 중단            → 204. 워커가 실행 건을 점유한 것을 보고 중단해 '중단요청' 경로를 만든다 — 단계가 끝나는 대로 '중단'

abort_project가 돌려준 결과(어느 경로를 탔는지)를 가로채 기록하므로 경로까지 확인한다. 타이밍 때문에 원하는 경로를 못 만들면
(워커가 먼저 끝냄) 새 프로젝트로 몇 번 다시 시도하고, 그래도 안 되면 FAIL로 남긴다.
"""
import argparse
import datetime
import json
import os
import sys
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
    parser.add_argument('--wait-sec', type=float, default=300, help='상태가 바뀌길 기다리는 최대 시간(초, 기본 300)')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from fastapi.testclient import TestClient

    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app.database import SessionLocal
    from app.main import app
    from app.models import Project
    from app.orch.gateway import account_id_of, get_gateway

    projects.ORCH_WAIT_TIMEOUT_SEC = 5.0

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    with TestClient(app) as client:
        security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
        auth_router.verify_google_id_token = security.verify_google_id_token
        gateway = get_gateway()
        user_id = {}
        aborts = []  # 웹이 gateway.abort_project를 부른 결과(AbortResult)를 순서대로 모은다
        real_abort = gateway.abort_project

        def recording_abort(project_id):
            result = real_abort(project_id)
            aborts.append(result)
            return result

        gateway.abort_project = recording_abort  # 인스턴스에 덮어써 라우터가 같은 객체를 부를 때 기록된다

        def wait_for(label: str, cond, interval: float = 2.0):
            """cond()가 참이 될 때까지. 시간 초과면 Abort."""
            deadline = time.time() + args.wait_sec
            started = time.time()
            while time.time() < deadline:
                value = cond()
                if value:
                    return value
                time.sleep(interval)
            raise Abort(f'{label}: {args.wait_sec:.0f}초 안에 되지 않음({time.time() - started:.0f}s) — 워커가 떠 있는지 확인하세요')

        def create_project():
            return client.post('/projects', data={'payload': json.dumps(FULL_INPUT)})

        def active():
            return gateway.active_work(account_id_of(user_id['id']))

        def run_progress(pid: int):
            run = gateway.view_project(pid).run
            return run.progress if run is not None else None

        def web_project(pid: int):
            with SessionLocal() as db:
                row = db.get(Project, pid)
                return None if row is None else {'archived_at': row.archived_at, 'archived_by': row.archived_by}

        def listed_ids():
            res = client.get('/projects')
            return [p['project_id'] for p in j(res)] if res.status_code == 200 else []

        def run_locked(pid: int) -> bool:
            """워커가 그 프로젝트의 실행 건을 지금 점유하고 있는가(단계를 도는 중)."""
            run = gateway.view_project(pid).run
            return run is not None and gateway._orch.store.is_locked(run.run_id, datetime.datetime.now(datetime.UTC))

        def request_status(pid: int):
            req = gateway.start_status(pid)
            return req.status if req is not None else None

        def wait_until(cond, timeout: float = 90.0, interval: float = 0.1) -> bool:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if cond():
                    return True
                time.sleep(interval)
            return False

        def project_count_in_db():
            with SessionLocal() as db:
                return db.query(Project).count()

        def candidates_ready(pid: int):
            body = j(client.get(f'/projects/{pid}/match-candidates'))
            return body if body.get('status') not in (None, 'pending') else None

        def pick_eligible(pid: int):
            """후보를 받아 자격을 통과하는 공고를 고른다. 못 고르면 Abort."""
            cands = wait_for('공고 후보', lambda: candidates_ready(pid))
            if cands.get('status') != 'ready' or not cands.get('candidates'):
                raise Abort(f"공고 후보를 받지 못함: {cands.get('status')} {cands.get('message')}")
            blocked = set(cands.get('blocked_notice_ids') or [])
            for cand in [c for c in cands['candidates'] if c['notice_id'] not in blocked][:3]:
                body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': cand['notice_id']}))
                if body.get('status') == 'pending':
                    body = wait_for('자격 확인', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                        j(client.get(f'/projects/{pid}/eligibility'))))
                if body.get('status') == 'ready' and (body.get('eligibility') or {}).get('passed'):
                    return cand['notice_id']
            raise Abort('자격을 통과한 공고를 고르지 못함')

        def blocked_by(res, pid: int):
            detail = j(res).get('detail') or {}
            return (res.status_code == 409 and detail.get('blocked') is True and detail.get('active_project_id') == pid
                    and j(res).get('code') == 'E-RUN-CONCURRENT',
                    f"HTTP {res.status_code} code={j(res).get('code')} blocked={detail.get('blocked')} 진행 중 프로젝트={detail.get('active_project_id')} "
                    f"단계={detail.get('active_stage')} 화면={detail.get('active_screen')} 상태={detail.get('active_display_status')}")

        try:
            # 0) 로그인 · 동의 · 프로필
            res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
            step('로그인', res.status_code == 200, f'{res.status_code}')
            user_id['id'] = j(res).get('user', {}).get('user_id') or j(client.get('/auth/me')).get('user_id')
            client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
            res = client.post('/profile', json=PROFILE)
            if not step('프로필 저장', res.status_code == 201, f'{res.status_code}'):
                raise Abort('프로필 저장 실패')
            if user_id['id'] is None:
                raise Abort('사용자 id를 알 수 없음')

            # 1) 시작 요청 처리 중에 새 프로젝트
            res = create_project()
            if not step('프로젝트 A 생성(시작 요청)', res.status_code == 201, f'{res.status_code}'):
                raise Abort('A 생성 실패')
            a = j(res)['project_id']
            before = project_count_in_db()
            res = create_project()
            ok, detail = blocked_by(res, a)
            step('1. 요청 처리 중 새 프로젝트 → 409', ok, detail)
            step('1. 거절된 프로젝트의 웹 행이 안 생김', project_count_in_db() == before and listed_ids() == [a],
                 f'DB 프로젝트 {project_count_in_db()}개(기대 {before}), 목록 {listed_ids()}')

            # 2) 실행 건이 생긴 뒤 새 프로젝트
            wait_for('A 공고 후보', lambda: candidates_ready(a))
            step('2. A 실행 건 생성(화면 3)', run_progress(a) in ('실행', '사용자대기'), f'진행={run_progress(a)}')
            res = create_project()
            ok, detail = blocked_by(res, a)
            step('2. 실행 건이 있을 때 새 프로젝트 → 409', ok, detail)

            # 3) 휴지통으로 중단 → 제한 풀림
            res = client.delete(f'/projects/{a}')
            step('3. 휴지통(중단)', res.status_code == 204, f'{res.status_code}')
            step('3. 경로: 워커가 안 돌 때는 바로 중단', bool(aborts) and aborts[-1].run_action == '중단',
                 f'run_action={aborts[-1].run_action if aborts else None}')
            step('3. 실행 건 중단됨', run_progress(a) == '중단', f'진행={run_progress(a)}')
            row = web_project(a)
            step('3. 보관 처리 · 목록에서 숨김', bool(row and row['archived_at'] and row['archived_by'] == 'user') and a not in listed_ids(),
                 f'웹 행={row} 목록={listed_ids()}')
            step('3. 진행 중인 작업 없음', active() is None, f'active_work={active()}')
            res = create_project()
            if not step('3. 중단 뒤 새 프로젝트 B 생성', res.status_code == 201, f'{res.status_code} {j(res) if res.status_code != 201 else ""}'):
                raise Abort('B 생성 실패')
            b = j(res)['project_id']

            # 4a) 시작 요청 처리 중에 바로 중단 — 대기 중이면 요청이 곧바로 취소된다(처리 중이면 취소 요청)
            res = client.delete(f'/projects/{b}')
            last = aborts[-1]
            step('4a. 요청 처리 중 바로 중단', res.status_code == 204,
                 f'{res.status_code} 취소={len(last.cancelled_requests)} 취소요청={len(last.cancel_requested)} run={last.run_action}')
            wait_for('B 정리', lambda: active() is None)
            progress = run_progress(b)
            step('4a. 끝 상태: 진행 중인 작업 없음 · 실행 건 중단 또는 없음', active() is None and progress in (None, '중단'),
                 f'실행 건={progress} 웹 행={"삭제됨" if web_project(b) is None else "보관"}')

            # 4b) 워커가 요청을 처리 중(T-C1 등)일 때 중단 — 취소 요청이 남고 요청은 '취소'로 끝나야 한다
            made = None
            for attempt in range(1, 4):
                res = create_project()
                if res.status_code != 201:
                    raise Abort(f'4b 프로젝트 생성 실패 {res.status_code} {j(res)}')
                cand = j(res)['project_id']
                if not wait_until(lambda pid=cand: request_status(pid) in ('처리중', '완료', '실패')):
                    raise Abort('4b: 워커가 요청을 가져가지 않음 — 워커가 떠 있는지 확인하세요')
                seen = request_status(cand)
                res = client.delete(f'/projects/{cand}')
                last = aborts[-1]
                path_ok = bool(last.cancel_requested)
                step(f'4b. 처리 중 요청 중단 (시도 {attempt})', res.status_code == 204 and path_ok,
                     f'{res.status_code} 중단 직전 요청={seen} 취소요청={len(last.cancel_requested)} 취소={len(last.cancelled_requests)} '
                     f'run={last.run_action}')
                wait_for('4b 정리', lambda: active() is None)
                if path_ok:
                    made = cand
                    break
            if made is None:
                raise Abort('4b: 처리 중 경로를 만들지 못함')
            step('4b. 요청은 취소로 끝나고 실행 건은 안 생김', request_status(made) == '취소' and run_progress(made) is None,
                 f'요청={request_status(made)} 실행 건={run_progress(made)}')
            res = create_project()
            if not step('4. 중단 뒤 새 프로젝트 C 생성', res.status_code == 201, f'{res.status_code}'):
                raise Abort('C 생성 실패')
            c = j(res)['project_id']

            # 5) 워커가 단계를 도는 중에 중단 — 점유한 것을 보고 중단하면 '중단요청'이 남고 단계 사이에 반영된다
            pick_eligible(c)
            res = client.post(f'/projects/{c}/plan/start')
            if res.status_code != 200:
                raise Abort(f'5 계획서 작성 시작 실패 {res.status_code} {j(res)}')
            if not wait_until(lambda: run_locked(c)):
                raise Abort('5: 워커가 실행 건을 점유하지 않음 — 워커가 떠 있는지 확인하세요')
            res = client.delete(f'/projects/{c}')
            last = aborts[-1]
            if not step('5. 단계 진행 중 중단 → 중단요청 경로', res.status_code == 204 and last.run_action == '중단요청',
                        f'{res.status_code} run_action={last.run_action}'):
                raise Abort('5: 중단요청 경로를 만들지 못함 — 점유를 본 뒤 단계가 먼저 끝났을 수 있음(다시 실행)')
            wait_for('C 중단 반영', lambda: run_progress(c) == '중단')
            step('5. 단계가 끝나자 실행 건 중단 · 진행 중인 작업 없음', run_progress(c) == '중단' and wait_until(lambda: active() is None, 30),
                 f'진행={run_progress(c)} active_work={active()}')
            res = create_project()
            ok = step('5. 중단 뒤 새 프로젝트 D 생성', res.status_code == 201, f'{res.status_code}')
            if ok:
                d = j(res)['project_id']
                client.delete(f'/projects/{d}')  # 정리 — 다음 실행이 막히지 않게
                wait_for('D 정리', lambda: active() is None)
        except Abort as exc:
            step('중단', False, str(exc))
        except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
            step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
