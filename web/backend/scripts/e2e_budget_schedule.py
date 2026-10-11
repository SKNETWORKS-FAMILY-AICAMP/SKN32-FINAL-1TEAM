"""사업비 · 추진 일정 입력이 웹 저장 → 오케스트레이터 시작 요청까지 이어지는지 실제 DB로 확인한다 (SB-333).

    python scripts/e2e_budget_schedule.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

준비는 e2e_worker_flow.py와 같다(SB-254 준비 1~4: 로컬 MySQL · prepare_local_mysql.py). **워커는 띄우지 않아도 된다** — 시작 요청(request_start)까지만
보고, 대기 중인 요청은 케이스가 끝날 때마다 휴지통 삭제로 취소한다. 오케스트레이터가 이 두 표(project_budget_items · project_schedule_items)를
읽는 코드는 SB-310(전략 · 작성 · 검증-1 연동)에 있으므로 **최신 SB-304를 합친 트리에서** 돌려야 한다(없으면 첫 확인이 실패한다).

차례대로(웹 스위치 REQUIRE_BUDGET_SCHEDULE · 오케스트레이터 스위치 PLAN_TABLES_REQUIRED는 프로세스 안에서 끄고 켠다):
  1. 예비창업 + 사업비(1 · 2단계) · 일정(협약기간 내 · 협약 이후)  201, 두 표에 순서대로 저장(phase 컬럼 포함), GET 응답이 같고,
     오케스트레이터가 저장한 시작 요청(orch_start_requests.form_json)에 같은 사업비 · 일정이 단계 · 범위(agreement / roadmap)와 함께 담김
  2. 법인 + 사업비(자기부담 현금 · 현물)  phase 없이 저장되고 시작 요청에 단계 없음 · 금액이 그대로 담김
  3. 예비창업인데 사업비 · 일정 없음, 두 스위치 모두 꺼짐  통과(기본 동작)
  4. 오케스트레이터 스위치만 켬  시작 요청이 E-C1-REQUIRED로 거절하고 missing 이름이 웹과 같으며 프로젝트를 남기지 않음
  5. 웹 스위치도 켬  웹이 먼저 같은 이름으로 거절하고 오케스트레이터를 부르지 않음
  6. 두 스위치를 켠 채 조건을 채움  예비창업 1 · 2단계 각 1건 + 협약기간 내 일정 1건이면 통과(협약 이후 일정은 없어도 됨)
  7. 예비창업 2단계만 빠짐  두 곳이 같은 이름('사업비 집행계획(2단계)')으로 거절
"""
import argparse
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


BUDGET_PRELIMINARY = [
    {'phase': '1단계', 'category': '외주용역비', 'execution_plan': '앱 개발 외주', 'total_amount': 15000000,
     'government_amount': 15000000, 'self_cash_amount': 0, 'self_in_kind_amount': 0},
    {'phase': '1단계', 'category': '재료비', 'execution_plan': '학습 데이터 라벨링', 'total_amount': 5000000,
     'government_amount': 5000000, 'self_cash_amount': 0, 'self_in_kind_amount': 0},
    {'phase': '2단계', 'category': '광고선전비', 'execution_plan': 'SNS 마케팅', 'total_amount': 10000000,
     'government_amount': 10000000, 'self_cash_amount': 0, 'self_in_kind_amount': 0},
]
SCHEDULE = [
    {'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.11~2027.01', 'detail': '정확도 80%'},
    {'section': 'feasibility', 'category': '출시', 'content': '앱 출시', 'period': '2027.01~2027.02', 'detail': ''},
    {'section': 'growth', 'category': '사업화', 'content': '보험사 제휴', 'period': '2027.03~2027.08', 'detail': '구독 모델'},
]
BUDGET_CORP = [
    {'category': '인건비', 'execution_plan': '개발자 채용', 'total_amount': 100000000, 'government_amount': 60000000,
     'self_cash_amount': 30000000, 'self_in_kind_amount': 10000000},
]
BUSINESS_INPUT = {'applicant_type': 'corp', 'founded_at': '2023-04-15', 'main_industry': '정보·통신', 'self_funding_allowed': True,
                  'self_cash_limit': 500}
MISSING_ALL_PRELIMINARY = ['사업비 집행계획', '사업비 집행계획(1단계)', '사업비 집행계획(2단계)', '추진 일정(협약기간 내)']


def pick(obj: dict, *names: str):
    """오케스트레이터가 JSON으로 저장한 칸 이름이 camelCase든 snake_case든 읽는다."""
    for name in names:
        if name in obj:
            return obj[name]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--wait-sec', type=float, default=60, help='앞 프로젝트 정리를 기다리는 최대 시간(초, 기본 60)')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from fastapi.testclient import TestClient
    from sbrain.orchestrator import settings as orch_settings
    from sqlalchemy import text

    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app.database import SessionLocal, engine
    from app.main import app
    from app.models import Project, ProjectBudgetItem, ProjectScheduleItem
    from app.orch.gateway import account_id_of, get_gateway

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    with TestClient(app) as client:
        security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
        auth_router.verify_google_id_token = security.verify_google_id_token
        gateway = get_gateway()
        me: dict = {}

        def set_switches(*, web: bool, orchestrator: bool) -> None:
            projects.REQUIRE_BUDGET_SCHEDULE = web
            orch_settings.PLAN_TABLES_REQUIRED = orchestrator

        def release() -> None:
            """대기 중인 시작 요청이 있으면 휴지통 삭제로 취소해 동시 실행 제한을 푼다."""
            deadline = time.time() + args.wait_sec
            while time.time() < deadline:
                work = gateway.active_work(account_id_of(me['id']))
                if work is None:
                    return
                if work.project_id is not None:
                    client.delete(f'/projects/{work.project_id}')
                time.sleep(0.5)
            raise Abort('앞 프로젝트 정리: 시간 안에 되지 않음')

        def post(payload: dict):
            return client.post('/projects', data={'payload': json.dumps(payload)})

        def start_form(project_id: int) -> dict | None:
            """오케스트레이터가 이 프로젝트의 시작 요청에 저장한 검사 통과 입력(form_json)."""
            with engine.connect() as conn:
                row = conn.execute(text('SELECT form_json FROM orch_start_requests WHERE project_id = :p '
                                        'ORDER BY created_at DESC LIMIT 1'), {'p': project_id}).first()
            return json.loads(row[0]) if row and row[0] else None

        def project_count() -> int:
            with SessionLocal() as db:
                return db.query(Project).count()

        try:
            res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
            step('로그인', res.status_code == 200, f'{res.status_code}')
            me['id'] = j(res).get('user', {}).get('user_id')
            client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
            res = client.post('/profile', json=PROFILE)
            if not step('프로필 저장', res.status_code == 201 and me['id'] is not None, f'{res.status_code}'):
                raise Abort('프로필 저장 실패')

            # 1) 예비창업 + 사업비 · 일정
            set_switches(web=False, orchestrator=False)
            release()
            res = post({**FULL_INPUT, 'budget_items': BUDGET_PRELIMINARY, 'schedule_items': SCHEDULE})
            body = j(res)
            if not step('1. 예비창업 + 사업비 · 일정: 프로젝트 생성', res.status_code == 201, f'{res.status_code} {body if res.status_code != 201 else ""}'):
                raise Abort('1. 생성 실패')
            pid = body['project_id']
            with SessionLocal() as db:
                budget = db.query(ProjectBudgetItem).filter_by(project_id=pid).order_by(ProjectBudgetItem.item_order).all()
                schedule = db.query(ProjectScheduleItem).filter_by(project_id=pid).order_by(ProjectScheduleItem.item_order).all()
                budget_rows = [(b.item_order, b.phase, b.category, int(b.total_amount)) for b in budget]
                schedule_rows = [(s.item_order, s.section, s.category, s.period) for s in schedule]
            step('1. 사업비가 보낸 순서 · 단계(phase)와 함께 저장됨',
                 budget_rows == [(1, '1단계', '외주용역비', 15000000), (2, '1단계', '재료비', 5000000), (3, '2단계', '광고선전비', 10000000)],
                 f'{budget_rows}')
            step('1. 일정이 보낸 순서 · 구분(section)과 함께 저장됨',
                 schedule_rows == [(1, 'feasibility', '개발', '2026.11~2027.01'), (2, 'feasibility', '출시', '2027.01~2027.02'),
                                   (3, 'growth', '사업화', '2027.03~2027.08')], f'{schedule_rows}')
            got = j(client.get(f'/projects/{pid}'))
            step('1. GET /projects/{id}가 같은 사업비 · 일정을 돌려줌',
                 [(b['phase'], b['category'], b['total_amount']) for b in got.get('budget_items', [])]
                 == [('1단계', '외주용역비', 15000000), ('1단계', '재료비', 5000000), ('2단계', '광고선전비', 10000000)]
                 and [(s['section'], s['category']) for s in got.get('schedule_items', [])]
                 == [('feasibility', '개발'), ('feasibility', '출시'), ('growth', '사업화')])
            form = start_form(pid)
            if not step('1. 오케스트레이터가 시작 요청을 대기로 저장함', form is not None, '' if form else 'orch_start_requests.form_json 없음'):
                raise Abort('1. 시작 요청 없음')
            seen_budget = pick(form, 'budgetItems', 'budget_items') or []
            seen_schedule = pick(form, 'scheduleItems', 'schedule_items') or []
            step('1. 시작 요청에 사업비가 순서 · 단계 · 금액 그대로 담김',
                 [(pick(b, 'phase'), pick(b, 'category'), pick(b, 'totalAmount', 'total_amount')) for b in seen_budget]
                 == [('1단계', '외주용역비', 15000000), ('1단계', '재료비', 5000000), ('2단계', '광고선전비', 10000000)],
                 f'{[(pick(b, "phase"), pick(b, "category"), pick(b, "totalAmount", "total_amount")) for b in seen_budget]}')
            step('1. 시작 요청에 일정이 범위(agreement · roadmap)와 함께 담김(feasibility → agreement, growth → roadmap)',
                 [(pick(s, 'scope'), pick(s, 'category')) for s in seen_schedule]
                 == [('agreement', '개발'), ('agreement', '출시'), ('roadmap', '사업화')],
                 f'{[(pick(s, "scope"), pick(s, "category")) for s in seen_schedule]}')

            # 2) 법인
            release()
            res = post({**FULL_INPUT, **BUSINESS_INPUT, 'budget_items': BUDGET_CORP, 'schedule_items': SCHEDULE[:2]})
            body = j(res)
            if not step('2. 법인 + 사업비: 프로젝트 생성', res.status_code == 201, f'{res.status_code} {body if res.status_code != 201 else ""}'):
                raise Abort('2. 생성 실패')
            pid = body['project_id']
            with SessionLocal() as db:
                row = db.query(ProjectBudgetItem).filter_by(project_id=pid).one()
                saved = (row.phase, int(row.government_amount), int(row.self_cash_amount), int(row.self_in_kind_amount))
            step('2. phase 없이 저장되고 자기부담 현금 · 현물이 그대로임', saved == (None, 60000000, 30000000, 10000000), f'{saved}')
            seen = (pick(start_form(pid) or {}, 'budgetItems', 'budget_items') or [{}])[0]
            step('2. 시작 요청에 단계 없음 · 자기부담 현금 · 현물이 그대로 담김',
                 pick(seen, 'phase') is None and pick(seen, 'selfCashAmount', 'self_cash_amount') == 30000000
                 and pick(seen, 'selfInKindAmount', 'self_in_kind_amount') == 10000000, f'{seen}')

            # 3) 입력 없음, 스위치 꺼짐
            release()
            res = post(FULL_INPUT)
            step('3. 사업비 · 일정 없이도 통과(두 스위치 꺼짐 — 기본 동작)', res.status_code == 201, f'{res.status_code}')

            # 4) 오케스트레이터 스위치만 켬
            release()
            set_switches(web=False, orchestrator=True)
            before = project_count()
            res = post(FULL_INPUT)
            body = j(res)
            missing = (body.get('detail') or {}).get('missing') if isinstance(body.get('detail'), dict) else None
            step('4. 오케스트레이터가 E-C1-REQUIRED로 거절하고 missing이 웹과 같은 이름',
                 res.status_code == 422 and body.get('code') == 'E-C1-REQUIRED' and missing == MISSING_ALL_PRELIMINARY,
                 f'{res.status_code} code={body.get("code")} missing={missing}')
            step('4. 거절되면 프로젝트를 남기지 않음', project_count() == before, f'프로젝트 {before}→{project_count()}')

            # 5) 웹 스위치도 켬
            set_switches(web=True, orchestrator=True)
            res = post(FULL_INPUT)
            body = j(res)
            missing = (body.get('detail') or {}).get('missing') if isinstance(body.get('detail'), dict) else None
            step('5. 웹이 먼저 같은 이름으로 거절함', res.status_code == 422 and body.get('code') == 'E-C1-REQUIRED'
                 and missing == MISSING_ALL_PRELIMINARY, f'{res.status_code} missing={missing}')
            with engine.connect() as conn:
                waiting = conn.execute(text("SELECT COUNT(*) FROM orch_start_requests WHERE status = '대기'")).scalar()
            step('5. 웹이 거절하면 오케스트레이터에 시작 요청을 넣지 않음', waiting == 0, f'대기 요청 {waiting}건')

            # 6) 조건을 채움 (협약 이후 일정 없음)
            release()
            res = post({**FULL_INPUT, 'budget_items': BUDGET_PRELIMINARY, 'schedule_items': SCHEDULE[:2]})
            step('6. 두 스위치를 켠 채 1 · 2단계 사업비 + 협약기간 내 일정만으로 통과(협약 이후 일정은 선택)',
                 res.status_code == 201, f'{res.status_code} {j(res) if res.status_code != 201 else ""}')

            # 7) 2단계만 빠짐
            release()
            only_first = [b for b in BUDGET_PRELIMINARY if b['phase'] == '1단계']
            res = post({**FULL_INPUT, 'budget_items': only_first, 'schedule_items': SCHEDULE[:2]})
            body = j(res)
            web_missing = (body.get('detail') or {}).get('missing') if isinstance(body.get('detail'), dict) else None
            set_switches(web=False, orchestrator=True)
            res = post({**FULL_INPUT, 'budget_items': only_first, 'schedule_items': SCHEDULE[:2]})
            body = j(res)
            orch_missing = (body.get('detail') or {}).get('missing') if isinstance(body.get('detail'), dict) else None
            step('7. 2단계만 없으면 웹 · 오케스트레이터가 같은 이름으로 거절',
                 web_missing == ['사업비 집행계획(2단계)'] and orch_missing == ['사업비 집행계획(2단계)'],
                 f'웹={web_missing} 오케스트레이터={orch_missing}')
        except Abort as exc:
            step('중단', False, str(exc))
        except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록한다
            step('예상 못 한 오류', False, f'{type(exc).__name__}: {str(exc)[:300]}')
        finally:
            set_switches(web=False, orchestrator=False)
            try:
                release()
            except Abort:
                pass

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
