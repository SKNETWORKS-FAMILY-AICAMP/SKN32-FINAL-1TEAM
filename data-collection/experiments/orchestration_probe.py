# -*- coding: utf-8 -*-
r"""조율 에이전트용 함수 설명서(docs/guides/ORCHESTRATION_HANDOFF.md)의 예시 코드가 실제로 도는지 확인한다.

2026-09-29 — 조율 에이전트(SB-86 `agent-orchestration/`)에 넘긴 설명서를 Codex 가 다시 검증할 수 있게 저장소에 둔다.
설명서의 코드 블록을 **그대로 꺼내** 실행한다. 문서와 시험 코드가 따로 놀지 않게 하려는 것이다.
절 번호가 바뀌어도 되게, 블록은 내용으로 찾는다 — "# 빠른 시작" 으로 시작하는 블록(D), `def tc2(` 가 있는 블록(A·B·C).

확인하는 것
  D. 빠른 시작  설명서 맨 앞 코드가 그대로 실행되는가 (boot 도 여기서 한 번 한다)
  A. T-C2  첫 조회(offset 0)·더 보기(offset 10) 결과가 조율 쪽 TC2Out 검사를 통과하는가
  B. G-01  설명서의 eligibility_of() + g01() 이 매칭 1단계(app.eligible_with_types, 마감 제외)와
           공고 전체 × 신청자 5가지 경우에서 같은 결론인가
  C. 흐름  조율 쪽 build_stub_app() 에 T-C2·G-01 을 registry.bind 로 끼워
           start_run → more_candidates → select_announcement → G-01 → '계획서작성' 까지 가는가

준비 (조율 코드는 이 브랜치에 없다 — 읽기 전용으로 꺼낸다)
  git fetch origin
  git archive origin/feature/SB-86-orchestration-flow agent-orchestration | tar -x -C <임시 폴더>

실행 (data-collection 에서)
  .\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain <임시 폴더>\agent-orchestration

읽기 전용이다. 공용 DB 는 boot()·수집 상태 확인의 SELECT 만, 파일·DB 에 쓰지 않는다. 유료 API 호출 없음.
boot() 가 임베딩 모델(bge-m3)을 올리므로 약 2GB 메모리와 20초가 든다.
"""
import argparse
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


def run_quickstart():
    """맨 앞 '빠른 시작' 블록을 그대로 실행한다. 이 안에서 app.boot() 가 한 번 돈다."""
    scope = {'__name__': 'handoff_quickstart'}
    exec(compile(code_block('# 빠른 시작'), 'ORCHESTRATION_HANDOFF.md#빠른시작', 'exec'), scope)
    first = scope['first']
    print('D. 빠른 시작 수집 %s · 필터 통과 %d · 1위 %s' % (scope['status'], scope['out']['filtered_count'],
                                                     first['notice_id']))
    return scope['status'] in ('정상', '지연', '실패') and bool(scope['out']['results'])


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
        ok = ok and len(out.candidates) > 0 and (not ranks or ranks[0] == offset + 1)
    return ok


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
    from datetime import datetime
    from search import app
    from sbrain.agents.stubs import make_announcement
    from sbrain.bootstrap import build_stub_app
    from sbrain.models.domain import PreInput
    sb = build_stub_app()
    sb.registry.bind('T-C2', mod.tc2)
    sb.registry.bind('G-01', mod.g01)

    def announcements(aid):
        # 양식·평가 항목은 공고팀 데이터에 없어 스텁 값을 쓴다(설명서 8절 ③). 제목·자격 조건만 공고팀 값
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
        print('C. 흐름 start_run 실패: %s %s' % (res.code, res.message))
        return False
    rid = res.run_id
    cards = sb.engine.open_context(sb.store.load_run(rid)).get('candidates')
    orch.more_candidates(rid)
    orch.advance(rid)
    more = sb.engine.open_context(sb.store.load_run(rid)).get('candidates')
    orch.select_announcement(rid, cards[0].announcement_id)
    orch.advance(rid)
    view = orch.view(rid)
    gate_result = sb.engine.open_context(sb.store.load_run(rid)).get('gateResult')
    print('C. 흐름 후보 %d건 → 더 보기 %d건(%d위부터) → 선택 %s → G-01 통과 %s → %s/%s' % (
        len(cards), len(more), more[0].rank if more else 0, cards[0].announcement_id,
        gate_result.passed, view.step, view.progress))
    return view.step == '계획서작성'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sbrain', required=True, help='꺼낸 agent-orchestration 폴더 (sbrain 패키지가 있는 곳)')
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
