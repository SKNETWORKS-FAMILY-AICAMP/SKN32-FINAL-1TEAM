"""실제 워커 + 로컬 MySQL로 웹 → 오케스트레이터 전체 흐름을 한 번 끝까지 돌려 본다.

    python scripts/e2e_worker_flow.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4
    python scripts/e2e_worker_flow.py --rework --cleanup

사전 준비(순서):
  1. 로컬 MySQL(Docker) + scripts/prepare_local_mysql.py 로 스키마 준비
  2. 워커를 따로 띄운다 — 이 스크립트는 단계를 직접 돌지 않고 워커가 처리하길 기다린다
       cd agent-orchestration
       $env:SBRAIN_DB_URL = '<같은 URL>'; python -m sbrain.worker      (OPENAI_API_KEY는 agent-orchestration/.env)
  3. 이 스크립트 실행

흐름: 로그인 → 프로젝트 생성 → 공고 후보 → 공고 선택(자격 확인) → 계획서 작성 → 문서 평가 → 프로토타입 → 산출물 확인 →
      종합 평가 →(--rework: 재작성)→ 표현 검수 → 결과 →(--cleanup: 영구 삭제)

- 로컬 호스트의 e2e/test DB만 받는다(팀 공유 DB 거부). 구글 로그인은 가짜로 바꿔 끼운다(테스트용 계정).
- 워커의 Agent 중 조율 T-C1 · T-C3만 실제 구현이고 나머지는 스텁이다(agent-orchestration README 1.3) —
  이 스크립트는 "웹 ↔ 워커 배관과 흐름"을 확인하며 결과물의 품질은 보지 않는다.
- 각 단계는 [OK]/[FAIL]로 찍고, 하나라도 실패하면 마지막에 요약하고 종료 코드 1로 끝난다.
"""
import argparse
import json
import os
import sys
import time

DEFAULT_URL = 'mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}

if hasattr(sys.stdout, 'reconfigure'):  # 콘솔 인코딩(cp949 등)에 없는 문자(— 등)가 있어도 출력이 죽지 않게
    sys.stdout.reconfigure(errors='replace')

FULL_INPUT = {
    'description': 'E2E 아이템 — AI 반려동물 건강관리 앱', 'applicant_type': 'preliminary', 'ceo_name': 'E2E대표',
    'ceo_birth_date': '1990-01-01', 'ceo_gender': 'male', 'region_sido': '서울', 'region_sigungu': '',
    'main_industry': 'IT', 'dev_start_month': '2026-11', 'dev_end_month': '2027-02',
    'ceo_careers': [{'type': '경력', 'title': '백엔드 개발', 'period': '3년', 'has_proof': False}],
    'pricing_items': [{'service_name': '월 구독', 'unit_price': 9900}],
    'budget_scale_manwon': 1000, 'no_hires': True, 'no_equipment': True, 'no_partners': True, 'team_members': [],
}
PROFILE = {
    'basic': {'applicantType': 'preliminary', 'ceoName': 'E2E대표', 'birthDate': '1990-01-01', 'gender': 'male',
              'region': {'sido': '서울', 'sigungu': ''}, 'industry': 'IT'},
    'capability': {'careers': ['경력'], 'skills': '백엔드', 'soloFounder': True},
}

results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


class Abort(Exception):
    """이어갈 수 없는 실패."""


def configure_env(url_text: str) -> None:
    from sqlalchemy import make_url

    url = make_url(url_text)
    database = url.database or ''
    if url.host not in LOCAL_HOSTS or not ('e2e' in database or 'test' in database):
        raise SystemExit(f'거부: 로컬 호스트의 e2e/test DB만 받습니다 (호스트={url.host}, DB={database!r}).')
    os.environ.update({
        'DB_BACKEND': 'mysql', 'MYSQL_USER': url.username or 'root', 'MYSQL_PASSWORD': url.password or '',
        'MYSQL_HOST': url.host, 'MYSQL_PORT': str(url.port or 3306), 'MYSQL_DATABASE': database,
        'SBRAIN_DB_URL': url_text, 'GOOGLE_CLIENT_ID': 'e2e-client', 'JWT_SECRET': 'e2e-secret-not-for-production-use',
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--rework', action='store_true', help='종합 평가 화면에서 문서층 묶음 재작성도 해 본다')
    parser.add_argument('--cleanup', action='store_true', help='끝나면 프로젝트를 영구 삭제하고 웹 행이 지워졌는지 확인')
    parser.add_argument('--wait-sec', type=float, default=900, help='단계 하나를 기다리는 최대 시간(초, 기본 900)')
    args = parser.parse_args()

    configure_env(args.url)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, here)

    from fastapi.testclient import TestClient

    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app.main import app

    projects.ORCH_WAIT_TIMEOUT_SEC = 5.0  # 폴링하므로 한 번에 오래 붙잡지 않는다

    def j(res):
        try:
            return res.json()
        except Exception:
            return {'raw': res.text[:300]}

    with TestClient(app) as client:
        security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
        auth_router.verify_google_id_token = security.verify_google_id_token

        def poll(label: str, path: str, done, *, fail=None, interval: float = 3.0, method: str = 'get'):
            """done(body)가 참이 될 때까지 path를 부른다. fail(body)가 참이거나 시간 초과면 Abort."""
            deadline = time.time() + args.wait_sec
            last = None
            started = time.time()
            while time.time() < deadline:
                res = getattr(client, method)(path)
                body = j(res)
                if res.status_code >= 500:
                    raise Abort(f'{label}: 서버 오류 {res.status_code} {body}')
                brief = (body.get('stage'), body.get('match_status'), body.get('progress_percent'), body.get('status')) \
                    if isinstance(body, dict) else None
                if brief != last:
                    print(f'      · {label}: {brief} ({time.time() - started:.0f}s)', flush=True)
                    last = brief
                if done(body):
                    return body
                if fail and fail(body):
                    raise Abort(f'{label}: 실패 상태 {body}')
                time.sleep(interval)
            raise Abort(f'{label}: {args.wait_sec:.0f}초 안에 끝나지 않음(마지막 {last}) — 워커가 떠 있는지 확인하세요')

        def check(name: str, fn) -> None:
            """예상 못 한 예외(서버 오류 등)도 FAIL 한 줄로 남기고 다음 단계로 넘어간다."""
            try:
                ok, detail = fn()
                step(name, ok, detail)
            except Exception as exc:  # noqa: BLE001 - 점검 도구라 어떤 오류든 기록하고 계속한다
                step(name, False, f'{type(exc).__name__}: {str(exc)[:300]}')

        def check_listing(pid: int):
            res = client.get('/projects')
            row = next((p for p in j(res) if p['project_id'] == pid), {}) if res.status_code == 200 else {}
            return (res.status_code == 200 and row.get('match_status') == 'completed' and row.get('display_status') == '완료',
                    f"HTTP {res.status_code} match_status={row.get('match_status')} display={row.get('display_status')} "
                    f"공고={row.get('notice_id')} 제목={row.get('notice_title')}")

        def check_notifications(pid: int):
            """이 프로젝트의 알림만 센다(목록 API는 사용자의 모든 프로젝트 알림을 주므로 project_id로 거른다).
            워커 규칙: 문서평가(6) · 산출물확인(8) · 표현검수(10) 각 1건 + 재작성이 끝날 때마다 1건."""
            res = client.get('/projects/notifications')
            mine = [n for n in (j(res) if res.status_code == 200 else []) if n['project_id'] == pid]
            expected = 3 + (1 if args.rework else 0)
            return (res.status_code == 200 and len(mine) == expected,
                    f"HTTP {res.status_code} 이 프로젝트 {len(mine)}건(기대 {expected}): {sorted(n['kind'] for n in mine)}")

        def check_cleanup(pid: int):
            res = client.delete(f'/projects/{pid}/permanent')
            return res.status_code == 204, f'{res.status_code} {j(res) if res.status_code != 204 else ""}'

        try:
            # 1) 로그인 · 동의 · 프로필
            res = client.post('/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
            step('로그인', res.status_code == 200, f'{res.status_code}')
            res = client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
            step('필수 동의', res.status_code == 200)
            res = client.post('/profile', json=PROFILE)
            step('프로필 저장', res.status_code == 201, f'{res.status_code}')
            if not results[-1][1]:
                raise Abort('프로필 저장 실패')

            # 2) 프로젝트 생성 → 시작 요청
            res = client.post('/projects', data={'payload': json.dumps(FULL_INPUT)})
            if not step('프로젝트 생성(시작 요청)', res.status_code == 201, f'{res.status_code} {j(res) if res.status_code != 201 else ""}'):
                raise Abort('프로젝트 생성 실패')
            pid = j(res)['project_id']

            # 3) 공고 후보 — 워커가 T-C1 → T-C2를 돌 때까지
            cands = poll('공고 후보', f'/projects/{pid}/match-candidates', lambda b: b.get('status') != 'pending')
            if not step('공고 후보', cands.get('status') == 'ready' and cands['candidates'],
                        f"status={cands.get('status')} 후보 {len(cands.get('candidates', []))}건 {cands.get('message') or ''}"):
                raise Abort('공고 후보를 받지 못함')
            blocked = set(cands.get('blocked_notice_ids') or [])

            # 4) 공고 선택 → 자격 확인(통과하는 공고를 찾는다)
            chosen = None
            for cand in [c for c in cands['candidates'] if c['notice_id'] not in blocked][:3]:
                res = client.post(f'/projects/{pid}/generate', json={'notice_id': cand['notice_id']})
                body = j(res)
                if res.status_code == 200 and body.get('status') == 'pending':
                    body = poll('자격 확인', f'/projects/{pid}/eligibility', lambda b: b.get('status') != 'pending')
                passed = body.get('status') == 'ready' and (body.get('eligibility') or {}).get('passed')
                step(f"공고 선택 {cand['notice_id']}", bool(passed),
                     f"HTTP {res.status_code} status={body.get('status')} 통과={ (body.get('eligibility') or {}).get('passed')} "
                     f"안내={[n['code'] for n in body.get('notices', [])]} {body.get('message') or ''}")
                if passed:
                    # [SB-274] 화면 4 값: 업력(예비창업자는 None) · 작성 가능 여부. 다시 읽어도(GET) 같다
                    elig = body.get('eligibility') or {}
                    again = (j(client.get(f'/projects/{pid}/eligibility')).get('eligibility')) or {}
                    step('자격 확인 응답의 업력 · 작성 가능 여부',
                         elig.get('can_start_writing') is True and elig.get('business_age_years') is None
                         and again.get('can_start_writing') is True and 'business_age_years' in elig,
                         f"POST: 업력={elig.get('business_age_years')} 작성 가능={elig.get('can_start_writing')} / "
                         f"GET: 업력={again.get('business_age_years')} 작성 가능={again.get('can_start_writing')} (예비창업자는 업력 None)")
                    chosen = cand['notice_id']
                    break
            if chosen is None:
                raise Abort('자격을 통과한 공고를 고르지 못함')

            # 5) 계획서 작성
            res = client.post(f'/projects/{pid}/plan/start')
            step('계획서 작성 시작', res.status_code == 200, f'{res.status_code}')
            poll('계획서 작성', f'/projects/{pid}/status',
                 lambda b: b.get('stage') == 'plan_review_pending' and b.get('match_status') == 'user_waiting',
                 fail=lambda b: b.get('match_status') in ('failed', 'halted'))
            step('문서 평가 대기(화면 6)', True)
            result = j(client.get(f'/projects/{pid}/result'))
            plan = result.get('plan') or {}
            step('결과: 계획서', bool(plan.get('sections')),
                 f"섹션 {len(plan.get('sections', []))}개, 문서 점수 {plan.get('doc_score')}, "
                 f"점수 항목 {len(plan.get('score_reasons', []))}개")
            res = client.get(f'/projects/{pid}/plan-document.docx')
            step('계획서 docx 내려받기', res.status_code == 200 and res.content[:2] == b'PK',
                 f'{res.status_code} {len(res.content)}바이트')

            # 6) 프로토타입
            res = client.post(f'/projects/{pid}/prototype/start')
            step('프로토타입 제작 시작', res.status_code == 200, f'{res.status_code}')
            poll('프로토타입 제작', f'/projects/{pid}/status',
                 lambda b: b.get('stage') == 'artifact_review' and b.get('match_status') == 'user_waiting',
                 fail=lambda b: b.get('match_status') in ('failed', 'halted'))
            result = j(client.get(f'/projects/{pid}/result'))
            artifacts = (result.get('plan') or {}).get('artifacts') or []
            step('산출물 확인 대기(화면 8)', bool(artifacts),
                 f"산출물 {len(artifacts)}건, 카테고리 {artifacts[0]['category'] if artifacts else None}")

            # 7) 종합 평가 (8 → 9)
            res = client.post(f'/projects/{pid}/final-review/start')
            step('종합 평가로 진행(8→9)', res.status_code == 200 and j(res).get('stage') == 'final_review_pending',
                 f"{res.status_code} stage={j(res).get('stage')}")
            result = j(client.get(f'/projects/{pid}/result'))
            verdict = result.get('verdict') or {}
            step('결과: 종합 판정', bool(verdict),
                 f"총점 {verdict.get('total_score')} / 기준 {verdict.get('pass_threshold')} 통과={verdict.get('overall_passed')}")

            # 8) (선택) 재작성
            if args.rework:
                res = client.post(f'/projects/{pid}/retry-task', json={'task_key': 'writing', 'bundle_id': '문제인식'})
                acc = j(res)
                step('재작성 요청(문제인식)', res.status_code == 200,
                     f"{res.status_code} cycle={acc.get('cycle_id')} screen={acc.get('screen')} collect_until={acc.get('collect_until')}")
                if res.status_code == 200:
                    # [SB-272] 재작성 중에는 /status · 목록이 재작성 중인 화면을 알려 준다(stage는 재작성 전 단계 그대로)
                    st = j(client.get(f'/projects/{pid}/status'))
                    row = next((p for p in j(client.get('/projects')) if p['project_id'] == pid), {})
                    step('재작성 중 /status · 목록에 재작성 화면 표시',
                         st.get('rework_screen') == acc.get('screen') and row.get('rework_screen') == acc.get('screen')
                         and st.get('match_status') == 'in_progress',
                         f"status rework_screen={st.get('rework_screen')} collecting={st.get('collecting')} "
                         f"match={st.get('match_status')} stage={st.get('stage')} / 목록 rework_screen={row.get('rework_screen')} "
                         f"(기대 {acc.get('screen')})")
                    poll('재작성', f'/projects/{pid}/status',
                         lambda b: b.get('match_status') == 'user_waiting' and b.get('stage') == 'final_review_pending',
                         fail=lambda b: b.get('match_status') in ('failed', 'halted'), interval=3.0)
                    rr = j(client.get(f'/projects/{pid}/rework-result'))
                    step('재작성 결과', rr.get('status') in ('완료', '실패'),
                         f"status={rr.get('status')} kept={rr.get('kept')} 점수 {rr.get('before_score')}→{rr.get('after_score')} "
                         f"변경 섹션 {list((rr.get('changed') or {}).get('sections', {}))}")
                    st = j(client.get(f'/projects/{pid}/status'))
                    step('재작성이 끝나면 재작성 표시가 사라짐', st.get('rework_screen') is None and st.get('collecting') is False,
                         f"rework_screen={st.get('rework_screen')} collecting={st.get('collecting')}")
                    usage = {u['bundle_id']: (u['used'], u['remaining'])
                             for u in j(client.get(f'/projects/{pid}/result')).get('bundle_usages', [])}
                    step('재작성 기회 소진 표시', usage.get('문제인식', (None,))[0] == 1, f'문제인식 (사용, 남음)={usage.get("문제인식")}')

            # 9) 표현 검수 (9 → 10)
            res = client.post(f'/projects/{pid}/review/start')
            if res.status_code == 409 and (j(res).get('detail') or {}).get('confirmation_required'):
                step('기준 미달 확인 요청(409)', True, f"사유={j(res)['detail'].get('reason')}")
                res = client.post(f'/projects/{pid}/review/start', json={'confirmed': True})
            step('표현 검수 시작', res.status_code == 200, f'{res.status_code}')
            poll('표현 검수', f'/projects/{pid}/status',
                 lambda b: b.get('stage') == 'done' and b.get('match_status') == 'completed',
                 fail=lambda b: b.get('match_status') in ('failed', 'halted'))
            result = j(client.get(f'/projects/{pid}/result'))
            plan = result.get('plan') or {}
            step('결과: 검수 · 최종', True,
                 f"형식 지적 {len(plan.get('format_findings', []))}건, 검수 시도 {len(plan.get('proofread_logs', []))}건")

            # 10) 목록 · 알림 — 여기서 예외가 나도 뒤 단계(정리)는 계속한다
            check('목록 표시', lambda: check_listing(pid))
            check('알림', lambda: check_notifications(pid))

            # 11) (선택) 정리
            if args.cleanup:
                check('영구 삭제', lambda: check_cleanup(pid))
        except Abort as exc:
            step('중단', False, str(exc))

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
