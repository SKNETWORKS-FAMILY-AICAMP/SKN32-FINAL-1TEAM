"""더 어려운 시험 입력을 만든다(호출 없음). 기존 픽스처를 코드로 변형하므로 새 파일 없이 항상 같은 결과가 나온다.

A. gradient — 검증-1의 미묘한 차이: 같은 계획서를 좋음 / 보통 / 나쁨 3단계로 만든다.
   보통 = 출처 표기를 지우고(시장성) 구체 수치를 '상당수' 같은 말로 흐린다(문제 인식·실현 가능성). 문장은 멀쩡하다.
   나쁨 = 보통의 결함 + 시장성을 근거 없이 부풀린 문장 + 팀 소개를 뭉뚱그린 문장.
B. strategy — 전략 T-S2의 함정: 상충 자료(낡은 값과 새 값), 낡은 자료만, 관련 없는 자료만, 단위 함정(백만 원).
C. writer — 작성 T-W1의 유혹: 경력 정보가 없음, 사업비 요청이 상한을 넘음, 분량 제한이 빡빡함, 구체 수치를 강조하라는 요청.
"""
from __future__ import annotations

import copy
import json
import random
import re
from pathlib import Path

from v1_verifier import variants as v1v
from v3_strategy import prompt as sp
from v4_writer import prompt as wp

LEVELS = [('good', '좋음'), ('medium', '보통'), ('poor', '나쁨')]

# ── A. gradient ───────────────────────────────────────────
SOURCE_PHRASES = {
    'base_01': ['통계청 2023년 광업·제조업조사 기준 ', '산업통상자원부 2024년 스마트공장 보급 현황 자료에 따르면 '],
    'base_02': ['농림축산식품부 2023년 동물보호 국민의식조사 기준 '],
    'base_03': ['통계청 2023년 서비스업조사 기준 ', '소상공인시장진흥공단 2024년 실태조사에서 '],
    'base_04': ['교육부 2023년 교육기본통계 기준 ', '한국교육개발원 2024년 조사에서 '],
}
GENERIC_TEAM = '우수한 역량을 갖춘 인력으로 팀을 구성하였으며, 각자 맡은 역할을 성실하게 수행하여 사업을 성공적으로 이끌어 갈 계획이다.'
_VAGUE = [
    (re.compile(r'\d+(?:\.\d+)?\s*~\s*\d+(?:\.\d+)?\s*%'), '상당한 비율'),
    (re.compile(r'\d+(?:\.\d+)?\s*%'), '상당한 비율'),
    (re.compile(r'(?:약\s*)?\d[\d,]*(?:\.\d+)?(?:\s*만\s*\d[\d,]*\s*천)?\s*(?:만|억)?\s*(?:원|곳|가구|명|마리|장|대|개교|건)'), '상당수'),
]
# 숫자를 말로 바꾼 뒤 어긋나는 조사만 바로잡는다(문장이 깨져서 감점되는 일을 막는다)
_PARTICLES = [('상당수이었다', '상당수였다'), ('비율였', '비율이었'), ('상당수을', '상당수를'), ('상당수으로', '상당수로'), ('상당수이', '상당수가'), ('상당수은', '상당수는'), ('상당수과', '상당수와'),
              ('비율를', '비율을'), ('비율가', '비율이'), ('비율는', '비율은'), ('비율와', '비율과')]


def vague(text: str) -> str:
    for pat, rep in _VAGUE:
        text = pat.sub(rep, text)
    for a, b in _PARTICLES:
        text = text.replace(a, b)
    return text


def gradient_docs(plan_id: str) -> dict[str, list[dict]]:
    """{'good'|'medium'|'poor': [{code, item, title, text}]} — 섹션 구조는 그대로다."""
    plan = v1v.load_plan(plan_id)
    good = [dict(s) for s in plan['sections']]
    medium, poor = [], []
    for s in good:
        m, p = dict(s), dict(s)
        if s['code'] == 'S3':                                   # 시장성: 출처 삭제
            for ph in SOURCE_PHRASES[plan_id]:
                m['text'] = m['text'].replace(ph, '')
            p['text'] = s['text_unsourced']                     # 나쁨: 근거 없이 부풀림
        if s['code'] in ('S1', 'S4'):                           # 문제 인식·실현 가능성: 구체 수치를 흐림
            m['text'] = p['text'] = vague(s['text'])
        if s['code'] == 'S5':                                   # 팀: 나쁨만 뭉뚱그림
            p['text'] = GENERIC_TEAM
        medium.append(m)
        poor.append(p)
    return {'good': good, 'medium': medium, 'poor': poor}


def gradient_cases(plan_ids=('base_01', 'base_02', 'base_03', 'base_04')) -> dict[str, dict]:
    out = {}
    for pid in plan_ids:
        docs = gradient_docs(pid)
        for lv, label in LEVELS:
            cid = '%s|%s' % (pid, lv)
            out[cid] = {'case_id': cid, 'plan': pid, 'level': lv, 'label': label, 'type': label, 'text': v1v.render(docs[lv]),
                        'title': v1v.load_plan(pid)['title']}
    return out


def human_set(seed: int = 7) -> tuple[list[dict], dict]:
    """사람 채점용 12편(계획서 4 × 3단계)을 섞어 번호만 붙인다. (문서 목록, 정답 열쇠)."""
    cases = list(gradient_cases().values())
    rng = random.Random(seed)
    rng.shuffle(cases)
    docs = [{'id': 'D%02d' % (i + 1), 'text': c['text']} for i, c in enumerate(cases)]
    key = {d['id']: {'case_id': c['case_id'], 'plan': c['plan'], 'level': c['level']} for d, c in zip(docs, cases)}
    return docs, key


# ── B. strategy hard ──────────────────────────────────────
def _fmt(v: float, unit: str) -> str:
    return ('{:,}'.format(int(v)) if float(v).is_integer() else str(v)) + ('%' if unit == '%' else unit)


def _year(source: str, year: str) -> str:
    return re.sub(r'20\d\d년', year, source, count=1)


def strategy_hard_cases(base_ids=('st01', 'st02', 'st03', 'st04')) -> dict[str, dict]:
    base = sp.load_cases()
    others = [c for k, c in base.items() if k not in base_ids]
    out = {}
    for bid in base_ids:
        b = base[bid]
        f0, f1, f2 = b['facts']

        def old(year, ratio):
            v = round(f0['value'] * ratio) if f0['unit'] != '%' else max(1, round(f0['value'] * ratio))
            return dict(f0, value=v, display='약 ' + _fmt(v, f0['unit']), source=_year(f0['source'], year))

        def mk(kind, facts, expect):
            cid = '%s_%s' % (kind, bid)
            c = copy.deepcopy(b)
            c.update(case_id=cid, base=bid, type=kind, facts=facts, expect=expect)
            out[cid] = c

        stale = old('2019년', 0.7)
        mk('상충', [stale, f0, f1, f2], {'fresh': f0, 'stale': stale})                 # 낡은 값이 맨 앞에 있다
        stale16 = old('2016년', 1.5)
        mk('낡은자료', [stale16, f1, f2], {'stale': stale16})
        irrelevant = [others[0]['facts'][0], others[1]['facts'][0], others[2]['facts'][0]]
        mk('무관자료', irrelevant, {})
        unit_fact = {'label': '국내 관련 시장 규모', 'value': 3000000000, 'unit': '원', 'display': '3,000백만 원 (단위: 백만 원)',
                     'source': '한국산업연구원 2023년 시장 조사'}
        mk('단위함정', [unit_fact, f1, f2], {'unit_fact': unit_fact})
    return out


# ── C. writer hard ────────────────────────────────────────
WRITER_EXTRAS = {
    '경력없음': None,
    '상한충돌': '이 사업의 총 사업비는 5천만 원 규모로 잡아서 자금 운용 계획을 작성해 주세요.',
    '분량빡빡': None,
    '수치유도': '설득력을 높이도록 예상 성장률, 매출 목표, 확보 고객 수를 구체적인 수치로 강조해 주세요.',
}


def writer_hard_cases(base_ids=('st01', 'st02', 'st03', 'st04')) -> dict[str, dict]:
    base = wp.load_cases()
    out = {}
    for bid in base_ids:
        for kind, extra in WRITER_EXTRAS.items():
            c = copy.deepcopy(base[bid])
            if kind == '경력없음':
                c['company']['representative_career'] = []
                c['company']['team_careers'] = []
            if kind == '상한충돌':
                c['announcement']['support_amount_max'] = 30000000
            if kind == '분량빡빡':
                c['form']['max_chars_per_section'] = 250
            cid = '%s_%s' % (kind, bid)
            c.update(case_id=cid, base=bid, type=kind, extra=extra)
            out[cid] = c
    return out


def build_writer_messages(case: dict) -> list[dict]:
    msgs = wp.build_w1(case)
    if case.get('extra'):
        msgs[1] = dict(msgs[1], content=msgs[1]['content'] + '\n\n[사용자 추가 요청] ' + case['extra'])
    return msgs


if __name__ == '__main__':
    g = gradient_cases()
    print('gradient', len(g), '· strategy', len(strategy_hard_cases()), '· writer', len(writer_hard_cases()))
