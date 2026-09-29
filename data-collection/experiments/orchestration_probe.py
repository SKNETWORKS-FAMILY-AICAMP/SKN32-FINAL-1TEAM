# -*- coding: utf-8 -*-
r"""조율 에이전트용 함수 설명서(docs/guides/ORCHESTRATION_HANDOFF.md)의 예시 코드가 실제로 도는지 확인한다.

2026-09-29 — 조율 에이전트(SB-86 `agent-orchestration/`)에 넘긴 설명서를 Codex 가 다시 검증할 수 있게 저장소에 둔다.
설명서의 코드 블록을 **그대로 꺼내** 실행한다. 문서와 시험 코드가 따로 놀지 않게 하려는 것이다.
절 번호가 바뀌어도 되게, 블록은 내용으로 찾는다 — "# 빠른 시작" 으로 시작하는 블록(D), `def tc2(` 가 있는 블록(A·B·C).

확인하는 것
  D. 빠른 시작  설명서 맨 앞 코드가 그대로 실행되는가 (boot 도 여기서 한 번 한다).
               수집 상태 "지연"이면 추천하지 않는지, 추천 0건이면 빈 목록을 주는지도 대역으로 본다
  A. T-C2  첫 조회(offset 0)·더 보기(offset 10) 결과가 조율 쪽 TC2Out 검사를 통과하는가
  B. G-01  설명서의 eligibility_of() + g01() 이 매칭 1단계(app.eligible_with_types, 마감 제외)와
           공고 전체 × 신청자 5가지 경우에서 같은 결론인가
  C. 흐름  조율 쪽 build_stub_app() 에 T-C2·G-01 을 registry.bind 로 끼워
           start_run → more_candidates → select_announcement → G-01 → '계획서작성' 까지 가는가

준비: 없음. 조율 코드는 저장소 루트 agent-orchestration/ 에 있다(main 머지본, deb5c81 과 같다).
  특정 커밋에 고정하려면 git archive deb5c81 agent-orchestration | tar -x -C <임시 폴더> 후 --sbrain <임시 폴더>\agent-orchestration

실행 (data-collection 에서)
  .\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration

읽기 전용이다. 공용 DB 는 boot()·수집 상태 확인의 SELECT 만, 파일·DB 에 쓰지 않는다. 유료 API 호출 없음.
boot() 가 임베딩 모델(bge-m3)을 올리므로 약 2GB 메모리와 20초가 든다.
"""
import argparse
import contextlib
import os
import re
import sys
import types
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, 'docs', 'guides', 'ORCHESTRATION_HANDOFF.md')
PRE = '예비창업자'

# G-01 대조에 쓰는 신청자 경우: (유형, 설립일). 설립일 None 은 예비창업자 또는 입력 누락
CASES = [(PRE, None), ('개인사업자', date(2025, 3, 1)), ('법인', date(2019, 1, 1)),
         ('법인', date(2024, 12, 1)), ('개인사업자', None)]


def code_block(marker):
    """설명서의 파이썬 코드 블록 중 marker 가 들어 있는 첫 블록."""
    with open(DOC, encoding='utf-8') as f:
        blocks = re.findall(r'```python\n(.*?)```', f.read(), re.S)
    for block in blocks:
        if marker in block:
            return block
    raise SystemExit('설명서에서 "%s" 가 들어 있는 파이썬 코드 블록을 찾지 못했다: %s' % (marker, DOC))


def load_example():
    """조율 규격에 끼우는 예시(tc2·eligibility_of·g01)를 모듈로 만든다."""
    mod = types.ModuleType('handoff_example')
    exec(compile(code_block('def tc2('), 'ORCHESTRATION_HANDOFF.md#예시', 'exec'), mod.__dict__)
    return mod


@contextlib.contextmanager
def patched(obj, name, value):
    """obj.name 을 잠깐 value 로 바꾼다. 수집 상태 '지연'·추천 0건처럼 지금 데이터로는 안 생기는 경로를 시험할 때 쓴다."""
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def _no_match(req):
    raise AssertionError('수집 상태가 정상이 아닌데 app.match() 를 불렀다')


def _stale_status(connection=None, **kw):
    return {'status': '지연', 'block_matching': True, 'reasons': ['시험용'], 'last_run_at': None, 'age_hours': 30.0}


def run_quickstart():
    """맨 앞 '빠른 시작' 블록을 그대로 실행한다. 이 안에서 app.boot() 가 한 번 돈다.

    지금 데이터(수집 정상·추천 있음) 경로에 더해, 수집 상태 '지연' 이면 추천하지 않는지와
    추천 0건이면 오류 없이 빈 목록을 돌려주는지를 대역으로 확인한다(Codex 재검수 P2-2).
    """
    from search import app, collection_status
    scope = {'__name__': 'handoff_quickstart'}
    exec(compile(code_block('# 빠른 시작'), 'ORCHESTRATION_HANDOFF.md#빠른시작', 'exec'), scope)
    status, cards = scope['status'], scope['cards']
    # 계약: 정상이 아니면 빈 목록. 정상이면 목록(0건도 계약상 맞다 — 조건에 맞는 공고가 없을 수 있다)
    contract_ok = cards == [] if status != '정상' else isinstance(cards, list)
    if status == '정상' and not cards:
        print('D. 참고: 수집 정상인데 오늘 데이터로 추천 0건 — 계약 위반은 아니나 데이터를 확인할 것')
    recommend = scope['recommend']
    with patched(collection_status, 'check', _stale_status), patched(app, 'match', _no_match):
        stale = recommend('예비창업자', '시험')
    # 0건 경로는 실제 수집 상태와 상관없이 늘 시험한다(상태가 '지연'인 날 건너뛰고 통과로 찍히지 않게)
    with patched(collection_status, 'check', lambda connection=None, **kw: {'status': '정상'}), \
            patched(app, 'match', lambda req: {'results': []}):
        empty = recommend('예비창업자', '시험')
    print('D. 빠른 시작 수집 %s · 추천 %d건 · 1위 %s · 지연이면 %s · 0건이면 %s' % (
        status, len(cards), cards[0]['notice_id'] if cards else '-', stale, empty))
    return contract_ok and stale == ('지연', []) and empty == ('정상', [])


def company(applicant_type, founded):
    from sbrain.models.domain import CompanyInfo
    return CompanyInfo(representative_name='홍길동', representative_career=[], founded_at=founded,
                       applicant_type=applicant_type, revenue_unit_price=0, team_careers=[], region='서울',
                       industry_code='', birth_date=date(1990, 1, 1), gender='남성', hiring_plan='',
                       facilities='', partners='')


class _Tools:
    """A 에서만 쓰는 대역. 조율 쪽 tools.search 처럼 fn(timeout) 을 불러 결과를 돌려준다."""
    def search(self, purpose, fn):
        return fn(30)


def check_tc2(mod):
    from sbrain.contracts import tasks as c
    from sbrain.models.domain import ItemSpec
    item = ItemSpec(item_name='펫케어', one_line_summary='AI 기반 반려동물 건강관리 앱', target_customer='반려인',
                    core_features=['건강 기록', '이상 징후 알림'], category='AI_API', keywords=['반려동물', 'AI'])
    ok = True
    for offset in (0, 10):
        out = mod.tc2(c.TC2In(item_spec=item, company_info=company(PRE, None), today=date.today(),
                              top_k=10, offset=offset), _Tools())
        ranks = [card.rank for card in out.candidates]
        print('A. T-C2 offset=%-2d 카드 %d건 · 순위 %s~%s · 수집 %s · 필터 통과 %d · 대체 %s' % (
            offset, len(out.candidates), ranks[0] if ranks else '-', ranks[-1] if ranks else '-',
            out.collection_status, out.filtered_count, out.fallback_mode))
        # 설명서의 "offset 0·10 각 10건(1~10위, 11~20위)" 을 그대로 검사한다
        ok = ok and ranks == list(range(offset + 1, offset + 11))
    # 수집 상태가 정상이 아니면: 첫 조회는 추천하지 않고 빈 카드 + 그 상태(조율 흐름이 E-C2-STALE 로 멈춘다),
    # 더 보기는 카드를 그대로 준다(조율 흐름이 더 보기 뒤에는 상태를 보지 않아, 빈 카드면 안내 없이 0건이 된다)
    from search import app, collection_status
    with patched(collection_status, 'check', _stale_status), patched(app, 'match', _no_match):
        stale = mod.tc2(c.TC2In(item_spec=item, company_info=company(PRE, None), today=date.today(),
                                top_k=10, offset=0), _Tools())
    with patched(collection_status, 'check', _stale_status):
        stale_more = mod.tc2(c.TC2In(item_spec=item, company_info=company(PRE, None), today=date.today(),
                                     top_k=10, offset=10), _Tools())
    print('A. T-C2 수집 지연이면 첫 조회 카드 %d건(%s) · 더 보기 카드 %d건' % (
        len(stale.candidates), stale.collection_status, len(stale_more.candidates)))
    return (ok and not stale.candidates and stale.collection_status == '지연'
            and len(stale_more.candidates) > 0)


def check_g01(mod):
    from sbrain.contracts import tasks as c
    from search import app, gate
    today = date.today()
    types_table = app.STATE.get('applicant_types')
    rules = {nid: mod.eligibility_of(nid) for nid in app.STATE['rows']}
    total_diff = 0
    for applicant_type, founded in CASES:
        co = company(applicant_type, founded)
        age_months = gate.applicant_age(applicant_type, founded.isoformat() if founded else '', today)
        diff = []
        for nid, row in app.STATE['rows'].items():
            keep, _why, _ = app.eligible_with_types(nid, row, age_months, today, check_deadline=False,
                                                    types_table=types_table if applicant_type == PRE else None)
            rule, parsed = rules[nid]
            out = mod.g01(c.G01In(company_info=co, eligibility=rule, eligibility_parsed=parsed, today=today))
            if out.gate_result.passed != keep:
                diff.append((nid, keep, out.gate_result.failed_conditions))
        total_diff += len(diff)
        print('B. G-01 %-5s 설립 %-10s 같음 %d · 다름 %d %s' % (
            applicant_type, founded or '없음', len(app.STATE['rows']) - len(diff), len(diff), diff[:3]))
    return total_diff == 0


def check_flow(mod):
    """C. 조율 스텁 흐름. 정상 경로가 통과하는지와, 더 보기 실패를 주입하면 검사가 그것을 실패로 잡는지를 함께 본다.

    Codex 2차 재검수 P2-1 — 예전에는 더 보기가 실패해도(조율 흐름은 옛 후보를 남기고 공고선택으로 돌아간다)
    첫 조회 후보로 계획서작성까지 가서 통과로 찍혔다. 이제 새 후보가 11~20위로 저장됐는지와 실패 알림 여부를 본다.
    """
    from search import app

    def timeout_on_more(original):
        def match(req):
            if req.offset == 10:
                raise TimeoutError('시험용 — 더 보기 검색 시간 초과')
            return original(req)
        return match

    normal = _run_flow(mod)
    with patched(app, 'match', timeout_on_more(app.match)):
        broken = _run_flow(mod, label='C′ 더 보기 실패 주입')
    print('C′ 실패 주입 결과 %s — 검사가 실패를 %s' % (
        '통과' if broken['ok'] else '실패', '잡았다' if not broken['ok'] else '놓쳤다(거짓 통과)'))
    return normal['ok'] and not broken['ok']


def _run_flow(mod, label='C. 흐름'):
    from datetime import datetime
    from search import app
    from sbrain.agents.stubs import make_announcement
    from sbrain.bootstrap import build_stub_app
    from sbrain.models.domain import PreInput
    sb = build_stub_app()
    sb.registry.bind('T-C2', mod.tc2)
    sb.registry.bind('G-01', mod.g01)

    def announcements(aid):
        # 양식·평가 항목은 공고팀 데이터에 없어 스텁 값을 쓴다(설명서 2절 ③). 제목·자격 조건만 공고팀 값
        base = make_announcement(aid, datetime.now().date())
        rule, parsed = mod.eligibility_of(aid)
        return base.model_copy(update={'title': app.STATE['rows'][aid]['title'],
                                       'eligibility': rule, 'eligibility_parsed': parsed})

    sb.orchestrator.announcements = announcements
    orch = sb.orchestrator
    # 조율 쪽 tests/conftest.py 의 pre_input() 과 같은 값(pytest 없이 쓰려고 옮겨 적음)
    form = PreInput(idea_text='동네 헬스장 회원 관리 서비스', applicant_type='법인', representative_name='김서준',
                    representative_career=['헬스장 운영 5년'], founded_at=date(2025, 3, 2), revenue_unit_price=35000,
                    development_period='6개월', team_careers=['개발자 1명'], birth_date=date(1990, 1, 1), gender='남',
                    region='서울', industry_code='J62', hiring_plan='없음', facilities='없음', partners='없음',
                    business_reg_no='123-45-67890', self_fund_amount=10_000_000)
    res = orch.start_run('acc-1', form)
    if not res.ok:
        print('%s start_run 실패: %s %s' % (label, res.code, res.message))
        return {'ok': False}
    rid = res.run_id
    ctx = sb.engine.open_context(sb.store.load_run(rid))
    cards = ctx.get('candidates')
    orch.more_candidates(rid)
    orch.advance(rid)
    ctx = sb.engine.open_context(sb.store.load_run(rid))
    versions = ctx.latest.get('candidates', 0)            # 더 보기가 새 결과를 저장하면 2
    more = ctx.get('candidates')                          # 최신 버전(실패했으면 첫 조회 후보 그대로)
    notices = [n.code for n in sb.store.load_run(rid).notices]
    orch.select_announcement(rid, cards[0].announcement_id)
    orch.advance(rid)
    view = orch.view(rid)
    gate_result = sb.engine.open_context(sb.store.load_run(rid)).get('gateResult')
    checks = {
        '첫 조회 1~10위': [card.rank for card in cards] == list(range(1, 11)),
        '더 보기 결과 저장': versions == 2,
        '더 보기 11~20위': [card.rank for card in more] == list(range(11, 21)),
        '더 보기 실패 알림 없음': 'X-C2-FAIL' not in notices,
        'G-01 통과': bool(gate_result and gate_result.passed),
        '계획서작성 진입': view.step == '계획서작성',
    }
    print('%s 후보 %d건 → 더 보기 %d건(%s위부터, 결과 버전 %d, 알림 %s) → 선택 %s → G-01 통과 %s → %s/%s · 어긋남 %s' % (
        label, len(cards), len(more), more[0].rank if more else '-', versions, notices or '없음',
        cards[0].announcement_id, gate_result.passed if gate_result else '-', view.step, view.progress,
        [k for k, v in checks.items() if not v] or '없음'))
    return {'ok': all(checks.values()), 'checks': checks}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sbrain', required=True, help='agent-orchestration 폴더 (sbrain 패키지가 있는 곳). 보통 ..\\agent-orchestration')
    args = ap.parse_args(argv)
    if not os.path.isdir(os.path.join(args.sbrain, 'sbrain')):
        raise SystemExit('sbrain 패키지를 찾지 못했다: %s' % args.sbrain)
    sys.path.insert(0, ROOT)
    sys.path.insert(0, args.sbrain)
    os.chdir(ROOT)

    mod = load_example()
    results = {'D. 빠른 시작': run_quickstart()}          # 여기서 app.boot() 가 돈다
    results.update({'A. T-C2': check_tc2(mod), 'B. G-01': check_g01(mod), 'C. 흐름': check_flow(mod)})
    print('결과: ' + ' · '.join('%s %s' % (k, '통과' if v else '실패') for k, v in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
