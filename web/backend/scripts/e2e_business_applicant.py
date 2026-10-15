"""사업자(개인사업자 · 법인) 입력으로 자격 확인 응답의 업력이 값으로 오는지 실제 흐름으로 확인한다 (SB-296).

    python scripts/e2e_business_applicant.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

e2e_worker_flow.py와 같이 워커를 따로 띄워 둔다(SB-254 준비 1~4). 다른 E2E는 예비창업자 입력이라 업력이 항상 None이었다 —
이 스크립트는 사업자 입력으로 SB-274의 business_age_years · can_start_writing이 값으로 내려오는 경로를 본다.
스텁 G-01은 설립일(founded_at)로 업력을 계산한다(실제 G-01도 같은 계산 — agent-orchestration/sbrain/agents/notice/g01.py).

차례대로(사례마다 새 프로젝트, 앞 프로젝트는 휴지통으로 중단해 동시 실행 제한을 푼다):
  1. 개인사업자 + 설립일   업력이 설립일에서 계산한 값(오케스트레이터와 같은 계산)이고 POST · GET /eligibility가 같다
  2. 법인 + 설립일         같은 확인(법인)
  3. 개인사업자, 설립일 없음  자격 확인까지 가지 못한다 — 시작 요청의 필수 항목 검사가 E-C1-REQUIRED(설립일자)로 거절하고 프로젝트를 남기지 않는다
  4. 예비창업자(대조)       업력 None · 작성 가능 true — 사업자와 다르게 나오는지
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


# 개인사업자 · 법인 전용 입력 — 주업종은 드롭다운 9종만 저장되고(예비창업자는 자유 텍스트), 자기부담금은 필수 항목이다(E-C1-REQUIRED)
BUSINESS_INPUT = {'main_industry': '정보·통신', 'self_funding_allowed': True, 'self_cash_limit': 500}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--wait-sec', type=float, default=300, help='상태가 바뀌길 기다리는 최대 시간(초, 기본 300)')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from fastapi.testclient import TestClient
    from sbrain.agents.stubs import business_age_months, business_age_years

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

    today = datetime.datetime.now(datetime.UTC).date()

    def expected_age(founded_at: str) -> float:
        """오케스트레이터와 같은 계산 — 설립일 → 개월 수 → 업력(년, 반올림)."""
        return business_age_years(business_age_months(datetime.date.fromisoformat(founded_at), today))

    with TestClient(app) as client:
        security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
        auth_router.verify_google_id_token = security.verify_google_id_token
        gateway = get_gateway()
        me: dict = {}

        def wait_for(label: str, cond, interval: float = 1.0):
            deadline = time.time() + args.wait_sec
            while time.time() < deadline:
                value = cond()
                if value:
                    return value
                time.sleep(interval)
            raise Abort(f'{label}: {args.wait_sec:.0f}초 안에 되지 않음 — 워커가 떠 있는지 확인하세요')

        def release():
            """진행 중인 작업이 있으면 휴지통으로 중단해 동시 실행 제한을 푼다."""
            work = gateway.active_work(account_id_of(me['id']))
            if work is not None and work.project_id is not None:
                client.delete(f'/projects/{work.project_id}')
                wait_for('앞 프로젝트 정리', lambda: gateway.active_work(account_id_of(me['id'])) is None)

        def candidates(pid):
            body = j(client.get(f'/projects/{pid}/match-candidates'))
            return body if body.get('status') != 'pending' else None

        def eligibility_of(pid, notice_id):
            body = j(client.post(f'/projects/{pid}/generate', json={'notice_id': notice_id}))
            if body.get('status') == 'pending':
                body = wait_for('자격 확인', lambda: (lambda b: b if b.get('status') != 'pending' else None)(
                    j(client.get(f'/projects/{pid}/eligibility', params={'notice_id': notice_id}))))
            return body

        def run_case(label: str, overrides: dict, *, drop: tuple[str, ...] = ()):
            """프로젝트를 만들어 공고를 골라 자격 확인 응답을 돌려준다. 통과 공고가 있으면 그것을, 없으면 처음 고른 응답을."""
            release()
            payload = {**FULL_INPUT, **overrides}
            for key in drop:
                payload.pop(key, None)
            res = client.post('/projects', data={'payload': json.dumps(payload)})
            if not step(f'{label}: 프로젝트 생성', res.status_code == 201, f'{res.status_code} {j(res) if res.status_code != 201 else ""}'):
                raise Abort(f'{label}: 프로젝트 생성 실패')
            pid = j(res)['project_id']
            cands = wait_for('공고 후보', lambda: candidates(pid))
            if cands.get('status') != 'ready':
                raise Abort(f"{label}: 공고 후보를 못 받음 {cands.get('status')} {cands.get('message')}")
            blocked = set(cands.get('blocked_notice_ids') or [])
            first = None
            for cand in [c for c in cands['candidates'] if c['notice_id'] not in blocked][:5]:
                body = eligibility_of(pid, cand['notice_id'])
                first = first or (cand['notice_id'], body)
                if body.get('status') == 'ready' and (body.get('eligibility') or {}).get('passed'):
                    return pid, cand['notice_id'], body
            if first is None:
                raise Abort(f'{label}: 고를 공고가 없음')
            return pid, first[0], first[1]

        try:
            res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
            step('로그인', res.status_code == 200, f'{res.status_code}')
            me['id'] = j(res).get('user', {}).get('user_id')
            client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
            res = client.post('/profile', json=PROFILE)
            if not step('프로필 저장', res.status_code == 201 and me['id'] is not None, f'{res.status_code}'):
                raise Abort('프로필 저장 실패')

            for label, applicant, founded in [('1. 개인사업자 + 설립일', 'individual', '2023-04-15'),
                                              ('2. 법인 + 설립일', 'corp', '2019-11-20')]:
                pid, notice_id, body = run_case(label, {'applicant_type': applicant, 'founded_at': founded, **BUSINESS_INPUT})
                eligibility = body.get('eligibility') or {}
                want = expected_age(founded)
                step(f'{label}: 자격 확인 응답에 업력이 값으로 옴',
                     body.get('status') == 'ready' and eligibility.get('business_age_years') is not None
                     and abs(eligibility['business_age_years'] - want) < 0.05,
                     f"status={body.get('status')} 업력={eligibility.get('business_age_years')} (기대 {want}, 설립일 {founded}) "
                     f"통과={eligibility.get('passed')}")
                step(f'{label}: 작성 가능 여부가 통과 여부와 같음', eligibility.get('can_start_writing') is eligibility.get('passed'),
                     f"작성 가능={eligibility.get('can_start_writing')} 통과={eligibility.get('passed')}")
                again = (j(client.get(f'/projects/{pid}/eligibility', params={'notice_id': notice_id})).get('eligibility')) or {}
                step(f'{label}: GET /eligibility도 같은 업력 · 작성 가능', again.get('business_age_years') == eligibility.get('business_age_years')
                     and again.get('can_start_writing') == eligibility.get('can_start_writing'),
                     f"업력={again.get('business_age_years')} 작성 가능={again.get('can_start_writing')}")

            # 설립일 없는 사업자는 자격 확인(G-01)까지 가지 못한다 — 시작 요청의 필수 항목 검사(E-C1-REQUIRED)가 먼저 거절한다
            release()
            payload = {**FULL_INPUT, 'applicant_type': 'individual', **BUSINESS_INPUT}
            payload.pop('founded_at', None)
            with SessionLocal() as db:
                projects_before = db.query(Project).count()
            res = client.post('/projects', data={'payload': json.dumps(payload)})
            body = j(res)
            step('3. 설립일 없는 사업자: 필수 항목(설립일자) 누락으로 거절',
                 res.status_code == 422 and body.get('code') == 'E-C1-REQUIRED' and '설립일자' in (body.get('detail') or {}).get('missing', []),
                 f"{res.status_code} code={body.get('code')} 누락={(body.get('detail') or {}).get('missing')}")
            with SessionLocal() as db:
                projects_after = db.query(Project).count()
            step('3. 거절된 입력이 프로젝트 · 실행을 남기지 않음',
                 projects_after == projects_before and gateway.active_work(account_id_of(me['id'])) is None,
                 f'프로젝트 {projects_before}→{projects_after}')

            pid, _notice_id, body = run_case('4. 예비창업자(대조)', {'applicant_type': 'preliminary'}, drop=('founded_at',))
            eligibility = body.get('eligibility') or {}
            step('4. 예비창업자: 업력 None',
                 body.get('status') == 'ready' and eligibility.get('business_age_years') is None,
                 f"status={body.get('status')} 업력={eligibility.get('business_age_years')} 작성 가능={eligibility.get('can_start_writing')}")
            release()
        except Abort as exc:
            step('중단', False, str(exc))
        except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
            step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
