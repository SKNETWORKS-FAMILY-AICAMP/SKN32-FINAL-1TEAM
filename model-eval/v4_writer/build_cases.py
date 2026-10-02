"""작성 Agent(T-W1 본문·T-W2 그래프·T-W3 표) 시험용 입력을 fixtures/writer_cases.json 으로 만든다(호출 없음).

전략 실험의 아이템 8건(fixtures/strategy_cases.json)을 재사용하고 작성에 필요한 입력을 더한다.
- 양식(formSpec): 필수 섹션 코드 7개, 서술 형식(개조식·단정형), 금지 표현, 분량 제한(일부 아이템만).
- 공고: 접수 마감일, 지원규모 상한.
- 회사 정보(companyInfo): 대표자·팀 경력, 수익모델 단가 — T-W1은 이 밖의 경력을 지어내면 안 된다.
- T-W2·T-W3는 모델이 쓴 본문에 의존하지 않도록 **코드가 만든 고정 계획서**(fixed_doc)를 입력으로 준다. 모든 후보가 같은 입력을 받는다.
모든 회사·수치는 시험용 가상 값이다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = [('1-1', '문제 인식'), ('1-2', '해결 방안'), ('2-1', '시장 분석'), ('2-2', '경쟁 우위'),
            ('3-1', '자금 운용 계획'), ('3-3', '추진 일정'), ('4-1', '팀 구성')]
FORMAT = {'style_type': '개조식', 'ending_rule': '단정형', 'banned_expressions': ['획기적', '혁신적인', '최고의', '압도적', '세계 최초']}
APPLY_END = '2026-11-30'

# 케이스별 추가 입력: (회사 정보, 지원규모 상한(원), 분량 제한, 자금 항목, 개발 기간)
EXTRA = {
    'st01': (['금형 품질 관리 8년', '비전 AI 개발 4년'], ['금형 품질 관리 8년', '비전 AI 개발 4년', '광학 설계 6년'], 25000000, 100000000, 700, [('인건비', 40000000), ('개발비', 30000000), ('마케팅비', 20000000)], '8개월'),
    'st02': (['수의사 9년'], ['수의사 9년', '펌웨어 개발 5년', '생체신호 분석 석사'], 69000, 100000000, 700, [('인건비', 45000000), ('시제품 제작비', 30000000), ('임상 검증비', 20000000)], '8개월'),
    'st03': (['프랜차이즈 구매 담당 7년'], ['프랜차이즈 구매 담당 7년', '수요 예측 모델 개발 3년', '챗봇 서비스 운영 2년'], 29000, 100000000, 700, [('인건비', 40000000), ('개발비', 30000000), ('마케팅비', 20000000)], '5개월'),
    'st04': (['중학교 진로 교사 11년'], ['중학교 진로 교사 11년', '학습 서비스 기획 4년', '대화 엔진 개발 3년'], 1200000, 100000000, 700, [('인건비', 40000000), ('개발비', 30000000), ('시범 운영비', 20000000)], '6개월'),
    'st05': (['번역 에이전시 운영 5년'], ['번역 에이전시 운영 5년', '웹 개발 3년'], 50000, 50000000, None, [('인건비', 20000000), ('개발비', 15000000), ('마케팅비', 10000000)], '6개월'),
    'st06': (['인사 담당 6년', '머신러닝 엔지니어 3년'], ['인사 담당 6년', '머신러닝 엔지니어 3년'], 9900, 50000000, None, [('인건비', 20000000), ('클라우드 사용료', 15000000), ('마케팅비', 10000000)], '4개월'),
    'st07': (['제과 경력 7년'], ['제과 경력 7년', '매장 운영 3년'], 6000, 50000000, None, [('시설비', 20000000), ('재료비', 15000000), ('홍보비', 10000000)], '3개월'),
    'st08': (['고객센터 운영 7년', '백엔드 개발 3년'], ['고객센터 운영 7년', '백엔드 개발 3년'], 290000, 50000000, None, [('인건비', 20000000), ('클라우드 사용료', 15000000), ('마케팅비', 10000000)], '6개월'),
}


def money(v: int) -> str:
    return '{:,}원'.format(v)


def fact_sentence(f: dict) -> str:
    v = f['value']
    num = '{:,}'.format(int(v)) if float(v).is_integer() else str(v)
    return '%s은(는) %s%s임.' % (f['label'], num, f['unit'] if f['unit'] == '%' else f['unit'])


def fixed_doc(case: dict, extra: tuple) -> list[dict]:
    """코드가 만든 고정 계획서(T-W2·T-W3 입력). 모든 수치는 평이한 자릿수 표기로 적는다."""
    spec = case['item_spec']
    career, team, price, max_amount, _, funds, period = extra
    total = sum(v for _, v in funds)
    parts = ', '.join('%s %s' % (k, money(v)) for k, v in funds)
    return [
        {'section_code': '1-1', 'title': '문제 인식', 'text': '%s 대상: %s.' % (spec['one_line_summary'], spec['target_customer'])},
        {'section_code': '1-2', 'title': '해결 방안', 'text': '핵심 기능: %s.' % ', '.join(spec['core_features'])},
        {'section_code': '2-1', 'title': '시장 분석', 'text': ' '.join(fact_sentence(f) for f in case['facts'])},
        {'section_code': '3-1', 'title': '자금 운용 계획', 'text': '총 %s을 %s으로 사용할 계획임. 지원규모 상한은 %s임.' % (money(total), parts, money(max_amount))},
        {'section_code': '3-3', 'title': '추진 일정', 'text': '개발 기간은 %s이며 1~2개월차 기획·설계, 3~4개월차 개발, 5개월차 이후 시범 운영을 진행할 예정임. 접수 마감일은 %s임.' % (period, APPLY_END)},
        {'section_code': '4-1', 'title': '팀 구성', 'text': '대표자 경력: %s. 팀 경력: %s.' % (', '.join(career), ', '.join(team))},
    ]


def build() -> dict:
    src = json.loads((ROOT / 'fixtures' / 'strategy_cases.json').read_text(encoding='utf-8'))['cases']
    out = []
    for c in src:
        career, team, price, max_amount, max_chars, funds, period = EXTRA[c['case_id']]
        extra = EXTRA[c['case_id']]
        out.append({
            'case_id': c['case_id'], 'item_spec': c['item_spec'], 'differentiator': c['differentiator'], 'facts': c['facts'],
            'company': {'representative_career': career, 'team_careers': team, 'revenue_unit_price': price, 'development_period': period},
            'announcement': {'apply_end': APPLY_END, 'support_amount_max': max_amount},
            'form': {'sections': [{'code': k, 'title': t} for k, t in SECTIONS], 'max_chars_per_section': max_chars, 'format': FORMAT},
            'funds': [{'label': k, 'amount': v} for k, v in funds],
            'fixed_doc': fixed_doc(c, extra),
        })
    return {'_note': __doc__.strip(), 'cases': out}


if __name__ == '__main__':
    doc = build()
    (ROOT / 'fixtures' / 'writer_cases.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(doc['cases']), '건')
