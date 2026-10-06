# -*- coding: utf-8 -*-
"""04 계약 시험 — 조율 에이전트의 **실제 연결 코드**로 우리 공고 서버를 HTTP로 불러 본다 (2026-10-06, docs/notice_api/04_contract_test).

  # 1) 조율 브랜치 코드를 작업 폴더 밖 임시 폴더에 푼다(작업 트리를 바꾸지 않는다)
  git archive origin/feature/SB-87-init-supervisor-integration agent-orchestration/sbrain | tar -x -C <임시 폴더>
  # 2) 공고 서버(8000)를 켠 상태에서
  python -X utf8 -m experiments.notice_api_contract --sbrain <임시 폴더>/agent-orchestration [--url http://127.0.0.1:8000] [--all]

조율 쪽 코드(sbrain.agents.notice)를 그대로 쓴다 — 요청 본문 만들기(match_request), HTTP 클라이언트(NoticeClient·UrllibTransport),
응답 검사·변환(parse_status·parse_match·to_card·to_announcement·to_gate), Task 함수(make_tc2·make_g01)와 재시도 도구(Tools).
응답이 약속 밖이면 조율 쪽이 FormatError → 재시도 → ToolCallExhausted 를 낸다. 그것이 나오지 않으면 계약을 지킨 것이다.

신청자 정보는 **가짜**다(조율 쪽 시험 견본 tests/test_notice_tasks.py 의 item()·company() 와 같은 모양).
공고 서버의 OpenAI 호출·DB 쓰기는 없다(공고 서버는 읽기만 한다). 결과는 reports/notice_api_contract_<시각>/ 에 남긴다.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 가짜 신청자 — 웹 값 그대로(시·도는 웹 17개 표기, 조율 쪽이 공고팀 16개 값으로 바꾼다)
COMPANIES = {
    '법인 · 서울 마포구 · 벤처': {},
    '예비창업자 · 광주광역시 · 여성': {'applicant_type': '예비창업자', 'founded_at': None, 'region': '광주광역시 북구',
                                    'gender': '여성', 'certifications': []},
    '개인사업자 · 경기도 성남시 · 여성기업·벤처': {'applicant_type': '개인사업자', 'founded_at': date(2019, 5, 1),
                                         'region': '경기도 성남시', 'gender': '여성', 'certifications': ['여성기업', '벤처기업']},
    '법인 · 충청남도 천안시 · 장애인기업 · 오래된 회사': {'founded_at': date(2012, 1, 2), 'region': '충청남도 천안시',
                                             'certifications': ['장애인기업', '이노비즈']},
}


def load_sbrain(path):
    sys.path.insert(0, path)
    from sbrain.agents import notice                                  # noqa: F401  — 불러지는지 먼저 본다
    return path


def fixtures():
    """조율 쪽 시험 견본과 같은 모양의 가짜 입력·도구."""
    from sbrain.models import CompanyInfo, ItemSpec, RevenueItem
    from sbrain.models.clock import utc_now
    from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

    def item():
        return ItemSpec(item_name='헬스온 매니저', one_line_summary='동네 헬스장 회원 관리 서비스', target_customer='소규모 헬스장',
                        core_features=['회원 등록·조회', '수업 예약'], category='웹개발', keywords=['헬스장', '회원관리'])

    def company(**over):
        base = dict(representative_name='가짜대표', representative_career=['헬스장 운영 5년'], founded_at=date(2025, 3, 2),
                    applicant_type='법인', revenue_unit_price=35000, team_careers=['개발 3년', '디자인 2년'],
                    region='서울특별시 마포구', industry_code='정보·통신', birth_date=date(1990, 1, 1), gender='남성',
                    certifications=['벤처기업'], hiring_plan='없음', facilities='태블릿 보유', partners='없음',
                    business_reg_no='000-00-00000', self_fund_amount=10_000_000, desired_scale='5천만원',
                    revenue_items=[RevenueItem(service_name='월 구독', unit_price=35000)],
                    company_name='가짜상호', representative_capability='헬스장 운영')
        base.update(over)
        return CompanyInfo(**base)

    def tools(task_id):
        sink = CallSink()
        cfg = ToolsConfig(agent='조율', provider='openai', model='gpt-6-luna', temperature=None, timeout_sec=30.0,
                          retry_count=1, retry_interval_sec=0)
        ctx = ToolsContext(run_id='contract', execution_id='e1', task_id=task_id, providers={}, sink=sink,
                           now=utc_now, sleep=lambda s: None)
        return Tools(cfg, ctx), sink
    return item, company, tools


def main(argv=None):
    ap = argparse.ArgumentParser(description='04 계약 시험 — 조율 쪽 실제 연결 코드로 공고 서버 HTTP 호출')
    ap.add_argument('--sbrain', required=True, help='조율 브랜치의 agent-orchestration 폴더(임시로 푼 곳)')
    ap.add_argument('--url', default='http://127.0.0.1:8000')
    ap.add_argument('--all', action='store_true', help='모든 공고에 G-01(상세+판정)을 돌린다(가짜 신청자 1명)')
    args = ap.parse_args(argv)
    load_sbrain(args.sbrain)
    from sbrain.agents.notice import NoticeClient, make_g01, make_tc2, match_request
    from sbrain.contracts import tasks as c
    from sbrain.orchestrator.errors import ProviderError, ResourceNotFound, ToolCallExhausted
    item, company, tools = fixtures()
    client = NoticeClient(args.url)
    today = date.today()
    checks, log = [], {'tc2': {}, 'g01': {}, 'edge': {}}

    def check(name, ok, detail=''):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
        print('%s %s %s' % ('✅' if ok else '❌', name, detail))

    # ── T-C2: 수집 상태 → 공고 추천 → 카드 (첫 조회 + 추가 조회) ──
    tc2 = make_tc2(client)
    first_ids = {}
    for label, over in COMPANIES.items():
        comp = company(**over)
        body = match_request(item(), comp, top=10, offset=0)
        for offset in (0, 10):
            t, sink = tools('T-C2')
            started = time.time()
            try:
                out = tc2(c.TC2In(item_spec=item(), company_info=comp, today=today, top_k=10, offset=offset), t)
            except ToolCallExhausted as exc:
                check('T-C2 %s offset %d' % (label, offset), False, '형식 오류로 재시도를 다 씀: %s' % exc)
                continue
            ms = (time.time() - started) * 1000
            cards = out.candidates
            ranks = [card.rank for card in cards]
            log['tc2']['%s/%d' % (label, offset)] = {
                'collection_status': out.collection_status, 'filtered_count': out.filtered_count,
                'fallback_used': out.fallback_used, 'fallback_mode': out.fallback_mode, 'cards': len(cards), 'ms': round(ms),
                'ranks': ranks, 'bonus': [card.bonus_score for card in cards],
                'region_sent': body['region'], 'district_sent': body['district'], 'calls': len(getattr(sink, '_logs', []))}
            check('T-C2 %s offset %d' % (label, offset), out.collection_status == '정상' and 0 < len(cards) <= 10,
                  '카드 %d · 수집 상태 %s · 필터 통과 %s · rank %s · %.0fms · 보낸 지역 %r'
                  % (len(cards), out.collection_status, out.filtered_count, ranks[:3] + ['…'], ms, body['region']))
            if offset == 0:
                first_ids[label] = [card.announcement_id for card in cards]

    # ── G-01: 공고 상세 → 자격 판정 (각 신청자 × 첫 조회 카드 10건) ──
    g01 = make_g01(client)
    for label, over in COMPANIES.items():
        comp = company(**over)
        res = []
        for aid in first_ids.get(label, []):
            t, _ = tools('G-01')
            try:
                out = g01(c.G01In(company_info=comp, today=today, announcement_id=aid), t)
            except ToolCallExhausted as exc:
                res.append({'id': aid, 'error': str(exc)})
                continue
            g = out.gate_result
            res.append({'id': aid, 'passed': g.passed, 'failed': g.failed_conditions, 'unknown': g.unknown_conditions,
                        'age_years': out.business_age_years, 'title': out.selected_announcement.title[:40],
                        'support_amount_max': out.selected_announcement.support_amount_max,
                        'bonus_info': bool(out.selected_announcement.bonus_info)})
        log['g01'][label] = res
        errors = [r for r in res if 'error' in r]
        check('G-01 %s' % label, res and not errors,
              '%d건 · 통과 %d · 불통과 %d · 확인 필요 있음 %d · 형식 오류 %d'
              % (len(res), sum(1 for r in res if r.get('passed')), sum(1 for r in res if r.get('passed') is False),
                 sum(1 for r in res if r.get('unknown')), len(errors)))

    # ── 경계 경우 ──
    t, _ = tools('G-01')
    try:
        g01(c.G01In(company_info=company(), today=today, announcement_id='kstartup:000000000'), t)
        check('공고 없음 → ResourceNotFound', False, '예외가 나지 않았다')
    except ResourceNotFound:
        check('공고 없음 → ResourceNotFound', True, '404 + NOTICE_NOT_FOUND 를 값으로 받아 X-C2-GONE 경로')
    wrong = NoticeClient(args.url.rstrip('/') + '/no-such-prefix')
    try:
        wrong.notice('kstartup:179418', 10)
        check('경로 없음 404 ≠ 공고 없음', False, '공고 없음으로 잘못 받았다')
    except ProviderError as exc:
        check('경로 없음 404 ≠ 공고 없음', getattr(exc, 'status', None) == 404, '본문 코드 없는 404 → ProviderError(%s)' % getattr(exc, 'status', None))
    no_found = company(founded_at=None)
    t, sink = tools('G-01')
    out = g01(c.G01In(company_info=no_found, today=today, announcement_id=next(iter(first_ids.values()))[0]), t)
    check('설립일 없는 사업자 → 판정 API 부르지 않음', out.gate_result.missing_inputs == ['foundedAt'],
          'missing_inputs=%s' % out.gate_result.missing_inputs)

    # ── 모든 공고 G-01 (선택) ──
    if args.all:
        from shared import store_mysql                                # 공고 ID 목록만 읽는다(SELECT)
        conn = store_mysql.connect()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT notice_id FROM notices ORDER BY notice_id')
                ids = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
        comp = company(**COMPANIES['개인사업자 · 경기도 성남시 · 여성기업·벤처'])
        started, errors, passed, unknown = time.time(), [], 0, 0
        for aid in ids:
            t, _ = tools('G-01')
            try:
                out = g01(c.G01In(company_info=comp, today=today, announcement_id=aid), t)
                passed += out.gate_result.passed
                unknown += bool(out.gate_result.unknown_conditions)
            except (ToolCallExhausted, ResourceNotFound) as exc:
                errors.append({'id': aid, 'error': type(exc).__name__})
        sec = time.time() - started
        log['g01_all'] = {'notices': len(ids), 'errors': errors[:20], 'error_count': len(errors), 'passed': passed,
                          'with_unknown': unknown, 'sec': round(sec, 1)}
        check('G-01 모든 공고(가짜 신청자 1명)', not errors,
              '%d건 · 형식 오류·공고 없음 %d · 통과 %d · 확인 필요 있음 %d · %.0f초(건당 %.0fms, HTTP 2회)'
              % (len(ids), len(errors), passed, unknown, sec, sec / max(1, len(ids)) * 1000))

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = os.path.join(ROOT, 'reports', 'notice_api_contract_' + stamp)
    os.makedirs(out_dir)
    meta = {'run_at': stamp, 'url': args.url, 'today': today.isoformat(),
            'sbrain_ref': 'origin/feature/SB-87-init-supervisor-integration', 'checks': checks, 'log': log,
            'fake_applicants': list(COMPANIES), 'openai_calls': 0, 'db_writes': 0}
    with open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1, default=str)
    lines = ['# 04 계약 시험 (%s)' % stamp, '', '- 공고 서버 %s · 조율 코드 `origin/feature/SB-87-init-supervisor-integration` · 가짜 신청자 %d명'
             % (args.url, len(COMPANIES)), '', '| 결과 | 확인 | 내용 |', '|---|---|---|']
    lines += ['| %s | %s | %s |' % ('✅' if x['ok'] else '❌', x['check'], x['detail'].replace('|', '/')) for x in checks]
    with open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    failed = [x for x in checks if not x['ok']]
    print('\n%d개 확인 중 실패 %d → %s' % (len(checks), len(failed), out_dir))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
