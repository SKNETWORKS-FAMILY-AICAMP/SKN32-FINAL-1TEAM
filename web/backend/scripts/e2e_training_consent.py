"""학습 동의와 검수 회수 문단(proofread_logs)을 실제 흐름으로 확인한다 (SB-262).

    python scripts/e2e_training_consent.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

e2e_failure_resume.py처럼 워커를 이 프로세스 안에서 돌린다(따로 띄운 워커가 있으면 끈다). 검수(T-P2) 스텁이 일부 문장을 한 번
반려하게 만들어(StubScenario.tp2_behavior) 워커가 웹 proofread_logs에 행을 쓰는지 본다. 프로젝트 하나를 끝까지(표현 검수까지)
세 번 돌리므로 몇 분 걸린다. 조율 T-C1 · T-C3는 평소처럼 실제 LLM이라 OPENAI_API_KEY(agent-orchestration/.env)가 필요하다.

  P1 동의한 계정   검수가 끝나면 반려된 시도마다 한 행(pending) → 관리자 라벨링(labeled · excluded) → 학습 반영 표시(trained)
                   · 라벨링 안 된 행을 섞으면 409 · 반영된 행은 라벨 변경 409 → 동의 철회 → 반영 전 행만 지워짐 → 영구 삭제 → 반영된 행만 남음(연결 끊김)
  P2 동의 철회 뒤   검수를 시작하기 전에 동의를 철회하면 행이 쓰이지 않음(워커는 저장하는 순간의 동의를 본다)
  P3 다시 동의      행이 쓰이고 → 일부 라벨링 · 반영 표시 → 계정 탈퇴 → 반영된 행만 남음(P1의 반영된 행도 그대로)
"""
import argparse
import contextlib
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

TARGETS = 3  # 스텁 T-P1이 검수 대상으로 고르는 문장 수(StubScenario.tp1_targets 기본값)


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
    from sbrain.worker import Worker, WorkerConfig

    import app.routers.auth as auth_router
    import app.security as security
    from app.database import SessionLocal
    from app.main import app
    from app.models import ProofreadLog, User
    from app.orch.gateway import get_gateway

    worker_app = build_app()
    worker = Worker(worker_app, WorkerConfig(poll_sec=0.3, threads=2, lease_sec=60), log=lambda line: None)
    worker_thread = threading.Thread(target=worker.run, name='e2e-worker', daemon=True)
    worker_thread.start()
    scenario = worker_app.scenario

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
            me: dict = {}

            def wait_for(label: str, cond, interval: float = 0.5, timeout: float | None = None):
                deadline = time.time() + (timeout or args.wait_sec)
                while time.time() < deadline:
                    value = cond()
                    if value:
                        return value
                    time.sleep(interval)
                raise Abort(f'{label}: 시간 안에 되지 않음')

            def status(pid):
                return j(client.get(f'/projects/{pid}/status'))

            def wait_stage(pid, stage, match):
                wait_for(f'{stage} 대기', lambda: (lambda b: b.get('stage') == stage and b.get('match_status') == match)(status(pid)))

            def create_selected_project():
                res = client.post('/projects', data={'payload': json.dumps(FULL_INPUT)})
                if res.status_code != 201:
                    raise Abort(f'프로젝트 생성 실패 {res.status_code} {j(res)}')
                pid = j(res)['project_id']
                cands = wait_for('공고 후보', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                    j(client.get(f'/projects/{pid}/match-candidates'))))
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

            def run_until_review(pid):
                """계획서 → 프로토타입 → 종합 평가까지. 표현 검수(review/start) 직전에 멈춘다."""
                client.post(f'/projects/{pid}/plan/start')
                wait_stage(pid, 'plan_review_pending', 'user_waiting')
                client.post(f'/projects/{pid}/prototype/start')
                wait_stage(pid, 'artifact_review', 'user_waiting')
                res = client.post(f'/projects/{pid}/final-review/start')
                if res.status_code != 200:
                    raise Abort(f'종합 평가 진행 실패 {res.status_code} {j(res)}')

            def reject_targets(pid):
                """검수 대상 문장(앞 TARGETS개)을 첫 시도에서 반려하도록 스텁을 맞춘다. 대상 문장 ID를 돌려준다."""
                outputs = gateway.outputs(pid)
                ids = [s.sentence_id for sec in outputs.plan_doc.sections for s in sec.sentences][:TARGETS]
                scenario.tp2_behavior = {sid: ['violate', 'ok'] for sid in ids}
                return ids

            def finish_review(pid):
                res = client.post(f'/projects/{pid}/review/start')
                if res.status_code == 409 and (j(res).get('detail') or {}).get('confirmation_required'):
                    res = client.post(f'/projects/{pid}/review/start', json={'confirmed': True})
                if res.status_code != 200:
                    raise Abort(f'표현 검수 시작 실패 {res.status_code} {j(res)}')
                wait_stage(pid, 'done', 'completed')

            def logs(project_id=None, log_ids=None):
                with SessionLocal() as db:
                    q = db.query(ProofreadLog)
                    if project_id is not None:
                        q = q.filter(ProofreadLog.project_id == project_id)
                    if log_ids is not None:
                        q = q.filter(ProofreadLog.log_id.in_(log_ids))
                    return [{'log_id': r.log_id, 'project_id': r.project_id, 'status': r.recovery_status, 'passed': r.passed,
                             'violation_type': r.violation_type, 'model_version': r.model_version,
                             'original': r.original_text, 'attempt': r.corrected_text, 'attempt_no': r.attempt_no}
                            for r in q.order_by(ProofreadLog.log_id).all()]

            def set_consent(value: bool):
                res = client.patch('/auth/consent', json={'aiTrainingAgreed': value})
                return res.status_code == 200 and j(res).get('ai_training_agreed') is value

            @contextlib.contextmanager
            def as_admin():
                """이 계정을 잠깐 관리자로 올린다(로컬 시험 DB)."""
                with SessionLocal() as db:
                    db.query(User).filter(User.user_id == me['id']).update({'role': 'admin'})
                    db.commit()
                try:
                    yield
                finally:
                    with SessionLocal() as db:
                        db.query(User).filter(User.user_id == me['id']).update({'role': 'user'})
                        db.commit()

            def admin_items(project_id=None):
                res = client.get('/admin/recovery-items')
                rows = j(res) if res.status_code == 200 else []
                return [r for r in rows if project_id is None or r['project_id'] == project_id]

            def label(log_id, recovery_status, text=None):
                return client.put(f'/admin/recovery-items/{log_id}', json={'recovery_status': recovery_status, 'label': text})

            def mark_trained(ids):
                return client.post('/admin/recovery-items/trained', json={'log_ids': ids})

            try:
                # 0) 로그인(학습 동의로 가입) · 필수 동의 · 프로필
                res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
                me['id'] = j(res).get('user', {}).get('user_id')
                client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
                prof = client.post('/profile', json=PROFILE)
                if not step('로그인(학습 동의) · 프로필', res.status_code == 200 and prof.status_code == 201 and me['id'] is not None):
                    raise Abort('로그인 실패')
                leftover = gateway.active_work(str(me['id']))
                if leftover is not None and leftover.project_id is not None:
                    client.delete(f'/projects/{leftover.project_id}')
                    wait_for('앞 실행 정리', lambda: gateway.active_work(str(me['id'])) is None, timeout=60)

                # ── P1: 동의한 계정 ──────────────────────────────
                p1 = create_selected_project()
                run_until_review(p1)
                targets = reject_targets(p1)
                step('P1. 반려시킬 검수 대상 문장', len(targets) == TARGETS, f'{len(targets)}개')
                finish_review(p1)
                rows = logs(p1)
                step('P1. 반려된 시도마다 한 행(pending)이 쓰임', len(rows) == TARGETS and all(
                    r['passed'] is False and r['status'] == 'pending' and r['project_id'] == p1 for r in rows),
                     f"{len(rows)}행(기대 {TARGETS}) 상태 {sorted({r['status'] for r in rows})}")
                step('P1. 행에 위반 종류 · 모델 이름 · 원문 · 시도문이 있음', bool(rows) and all(
                    r['violation_type'] and r['model_version'] and r['original'] and r['attempt'] for r in rows),
                     f"위반 종류 {sorted({r['violation_type'] for r in rows})} 모델 {sorted({r['model_version'] for r in rows})}")
                result = j(client.get(f'/projects/{p1}/result'))
                attempts = (result.get('plan') or {}).get('proofread_logs') or []
                step('P1. 사용자 결과의 검수 기록에도 보임', len(attempts) > 0, f'{len(attempts)}건')
                ids = [r['log_id'] for r in rows]
                with as_admin():
                    items = admin_items(p1)
                    step('P1. 관리자 목록에 보임(동의 표시 포함)', len(items) == TARGETS and all(i['consent'] for i in items),
                         f"{len(items)}건 동의 {sorted({i['consent'] for i in items})}")
                    a, b, c = ids[0], ids[1], ids[2]
                    r1, r2, r3 = label(a, 'labeled', '정답 문장 A'), label(b, 'labeled', '정답 문장 B'), label(c, 'excluded')
                    step('P1. 라벨링(labeled 2 · excluded 1)', all(r.status_code == 200 for r in (r1, r2, r3)),
                         f'{[r.status_code for r in (r1, r2, r3)]}')
                    bad = mark_trained([a, c])
                    step('P1. 라벨링 안 된(excluded) 행이 섞이면 409 · 아무것도 안 바뀜', bad.status_code == 409
                         and logs(log_ids=[a])[0]['status'] == 'labeled', f"{bad.status_code} a={logs(log_ids=[a])[0]['status']}")
                    miss = mark_trained([a, 99999999])
                    step('P1. 없는 log_id가 섞이면 404', miss.status_code == 404, f'{miss.status_code}')
                    ok = mark_trained([a])
                    step('P1. 학습 반영 표시(trained)', ok.status_code == 200 and logs(log_ids=[a])[0]['status'] == 'trained',
                         f"{ok.status_code} {logs(log_ids=[a])[0]['status']}")
                    again = label(a, 'pending')
                    step('P1. 반영된 행은 라벨을 바꿀 수 없음(409)', again.status_code == 409, f'{again.status_code}')
                step('P1. 동의 철회', set_consent(False))
                left = logs(p1)
                step('P1. 철회로 반영 전 행(labeled · excluded)이 지워지고 trained만 남음',
                     [r['log_id'] for r in left] == [a] and left[0]['status'] == 'trained',
                     f"남은 행 {[(r['log_id'], r['status']) for r in left]}")
                res = client.delete(f'/projects/{p1}/permanent')
                kept = logs(log_ids=[a])
                step('P1. 영구 삭제 → 204, trained 행은 남고 프로젝트 연결만 끊김',
                     res.status_code == 204 and len(kept) == 1 and kept[0]['project_id'] is None and kept[0]['status'] == 'trained',
                     f"{res.status_code} 행 {[(r['log_id'], r['project_id'], r['status']) for r in kept]}")
                with as_admin():
                    items = [i for i in admin_items() if i['log_id'] == a]
                    step('P1. 관리자 목록에 연결 끊긴 trained 행이 보임(프로젝트 없음 · 동의로 표시)',
                         len(items) == 1 and items[0]['project_id'] is None and items[0]['consent'] is True,
                         f"{[(i['project_id'], i['consent'], i['recovery_status']) for i in items]}")
                trained_from_p1 = a

                # ── P2: 검수 시작 전에 동의 철회 ─────────────────────
                step('P2. 다시 동의했다가 새 프로젝트 시작', set_consent(True))
                p2 = create_selected_project()
                run_until_review(p2)
                reject_targets(p2)
                step('P2. 검수 시작 전에 동의 철회', set_consent(False))
                finish_review(p2)
                step('P2. 동의가 없으면 행이 쓰이지 않음(검수는 정상 완료)', len(logs(p2)) == 0 and status(p2).get('match_status') == 'completed',
                     f'{len(logs(p2))}행, 상태 {status(p2).get("match_status")}')

                # ── P3: 다시 동의 → 라벨링 · 반영 → 탈퇴 ───────────────
                step('P3. 다시 동의', set_consent(True))
                p3 = create_selected_project()
                run_until_review(p3)
                reject_targets(p3)
                finish_review(p3)
                rows3 = logs(p3)
                step('P3. 다시 동의하면 행이 쓰임', len(rows3) == TARGETS, f'{len(rows3)}행')
                x, y, z = [r['log_id'] for r in rows3][:3]
                with as_admin():
                    label(x, 'labeled', '정답 X')
                    label(y, 'labeled', '정답 Y')
                    done = mark_trained([x])
                step('P3. 한 행은 trained, 한 행은 labeled, 한 행은 pending', done.status_code == 200
                     and [logs(log_ids=[k])[0]['status'] for k in (x, y, z)] == ['trained', 'labeled', 'pending'],
                     f"{done.status_code} {[logs(log_ids=[k])[0]['status'] for k in (x, y, z)]}")
                account = str(me['id'])
                res = client.delete('/auth/me')
                remain = logs(log_ids=[x, y, z])
                step('P3. 탈퇴 → 204', res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}')
                step('P3. 반영된 행만 남고 연결이 끊김(반영 전 행은 삭제)',
                     [r['log_id'] for r in remain] == [x] and remain[0]['project_id'] is None and remain[0]['status'] == 'trained',
                     f"남은 행 {[(r['log_id'], r['project_id'], r['status']) for r in remain]}")
                step('P3. 이전 프로젝트에서 반영된 행도 그대로', len(logs(log_ids=[trained_from_p1])) == 1)
                with SessionLocal() as db:
                    user_gone = db.get(User, me['id']) is None
                step('P3. 계정 삭제 · 세션 무효', user_gone and client.get('/auth/me').status_code == 401)
                step('P3. 탈퇴한 계정의 실행 건이 남지 않음', gateway.active_work(account) is None)
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
