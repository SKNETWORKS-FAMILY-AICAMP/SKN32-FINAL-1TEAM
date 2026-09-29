# -*- coding: utf-8 -*-
"""업종 순위 신호 — 허용 업종 목록 밖이면 뒤로, 모르면 그대로 (2026-09-28). DB·모델 없음."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from search import app, industry_rank  # noqa: E402
from test_match_rules import notice, state  # noqa: E402


def llm(status='known', allowed=('제조업',), complete=True, truncated=False, scope=False):
    return {'industry_status': status, 'list_complete': complete, 'truncated': truncated,
            'scope_unresolved': scope, 'allowed': [{'text': t} for t in allowed]}


class UsableTests(unittest.TestCase):
    def test_only_certain_rows_are_used(self):
        self.assertEqual(industry_rank.usable_sections(llm()), {'C'})
        self.assertEqual(industry_rank.usable_sections(llm(allowed=('제조업', '도소매업'))), {'C', 'G'})
        for bad in (llm(status='not_mentioned'), llm(status='excluded_only'), llm(status='conditional'),
                    llm(complete=False), llm(truncated=True), llm(scope=True),
                    llm(allowed=('제조업', '바이오')),        # 분야값이 섞이면 비교 불가
                    llm(allowed=())):
            self.assertIsNone(industry_rank.usable_sections(bad), bad)

    def test_branches_left_in_evidence_block_the_rule(self):
        # 2026-09-28 Codex 통합 재검수 P1 — 원문의 다른 허용 갈래가 allowed 에서 빠진 공고
        def row(values, evidence):          # final5 의 llm 칸 모양 — 허용값마다 근거 문장이 붙는다
            return dict(llm(allowed=values), allowed=[{'text': v, 'evidence': evidence} for v in values])
        cases = [
            (('제조',), '◦ 모집대상: 도내 소재한 중소기업으로 제조 또는 수출 기업'),
            (('모빌리티 제조',), '- 모빌리티 제조 및 공장 등록이 되어있는 기업 ※ 또는 PBV 관련이 있다고 판단되는 경우'),
            (('농식품 제조ㆍ가공업체',), '☞ 광주광역시 관내 농업인과 농업법인, 생산자 단체 및 농식품 제조ㆍ가공업체'),
            (('무역업',), 'o 무역업의 경우 매출액 대비 직수출금액 70% 이상 충족 필수'),
            (('도소매 유통기업',), "① 중소기업이 제조ㆍ위탁하여 '생산'한 완제품 ② 국내 제조기업에서 공급받아 판매하는 중소기업(도소매 유통기업)"),
        ]
        for values, ev in cases:
            self.assertIsNotNone(industry_rank.branch_problem(row(values, ev)), ev)
            self.assertIsNone(industry_rank.usable_sections(row(values, ev)), ev)
        # 소재지의 '또는'은 갈래가 아니다
        ok = row(('제조기업',), '지원대상: 청주시에 본사 또는 공장이 등록되어 있는 제조기업')
        self.assertIsNone(industry_rank.branch_problem(ok))
        self.assertEqual(industry_rank.usable_sections(ok), {'C'})

    def test_load_reads_file_and_missing_file_turns_rule_off(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'run1', 'results.jsonl')
            os.makedirs(os.path.dirname(path))
            with io.open(path, 'w', encoding='utf-8') as f:
                for nid, row in (('a', llm()), ('b', llm(status='unknown'))):
                    f.write(json.dumps({'notice_id': nid, 'llm': row}, ensure_ascii=False) + '\n')
            table = industry_rank.load(path)
            self.assertTrue(table['active'])
            self.assertEqual(table['rows'], 2)
            self.assertEqual(list(table['notices']), ['a'])
            self.assertEqual(table['source'], 'run1')
            missing = industry_rank.load(os.path.join(tmp, 'none', 'results.jsonl'))
            self.assertFalse(missing['active'])
            self.assertIn('없다', missing['error'])
        finally:
            shutil.rmtree(tmp)

    def test_off_industry_only_when_both_sides_known(self):
        table = {'notices': {'a': {'sections': ['C'], 'allowed': ['제조업']}}}
        self.assertTrue(industry_rank.off_industry(table, 'a', 'I'))
        self.assertFalse(industry_rank.off_industry(table, 'a', 'C'))
        self.assertFalse(industry_rank.off_industry(table, 'b', 'I'))      # 공고 업종 모름
        self.assertFalse(industry_rank.off_industry(table, 'a', None))     # 신청자 업종 모름
        self.assertFalse(industry_rank.off_industry({}, 'a', 'I'))         # 결과 파일 없음


TABLE = {'active': True, 'source': 'test', 'notices': {
    '제조전용': {'sections': ['C'], 'allowed': ['제조업']},
    '음식가능': {'sections': ['C', 'I'], 'allowed': ['제조업', '음식점업']},
}}


def match(rows, table=TABLE, **kw):
    kw.setdefault('search', 'dense')
    # 업종 순위는 2026-09-28 부터 기본 꺼짐(Codex 판정에서 부당 밀림 11/34). 규칙 자체를 시험할 때는 켠다
    kw.setdefault('demote_industry', True)
    req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원', **kw)
    st = dict(state(rows), industry=table)
    with patch.dict(app.STATE, st, clear=True), \
            patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]):
        return app.match(req)


class MatchIndustryTests(unittest.TestCase):
    def rows(self):
        # 검색 순서: 제조전용 → 모름 → 음식가능
        return {'제조전용': notice('제조 창업지원'), '모름': notice('창업지원'), '음식가능': notice('외식 창업지원')}

    def ids(self, out):
        return [r['notice_id'] for r in out['results']]

    def test_outside_allowed_list_goes_back_not_out(self):
        out = match(self.rows(), main_industry='음식점업', top=3)
        self.assertEqual(self.ids(out), ['모름', '음식가능', '제조전용'])   # 빼지 않고 맨 뒤
        self.assertEqual([x['notice_id'] for x in out['industry_demoted']], ['제조전용'])
        self.assertEqual(out['industry']['section'], 'I')
        self.assertTrue(out['results'][-1]['rules']['off_industry'])

    def test_inside_list_or_unknown_is_untouched(self):
        out = match(self.rows(), main_industry='제조업', top=3)
        self.assertEqual(self.ids(out), ['제조전용', '모름', '음식가능'])
        self.assertEqual(out['industry_demoted'], [])

    def test_unclear_applicant_industry_changes_nothing(self):
        for text in ('', '바이오', '제조 및 무역업'):
            out = match(self.rows(), main_industry=text, top=3)
            self.assertEqual(self.ids(out), ['제조전용', '모름', '음식가능'], text)
            self.assertIsNone(out['industry']['section'])

    def test_rule_is_off_by_default(self):
        self.assertFalse(app.MatchRequest(applicant_type='법인', idea='x').demote_industry)
        req_rows = self.rows()
        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원',
                               main_industry='음식점업', search='dense', top=3)
        st = dict(state(req_rows), industry=TABLE)
        with patch.dict(app.STATE, st, clear=True), patch.object(app, '_encode', lambda t: [0.0] * 4):
            out = app.match(req)
        self.assertEqual(self.ids(out), ['제조전용', '모름', '음식가능'])
        self.assertEqual(out['industry_demoted'], [])

    def test_switch_off_and_missing_file(self):
        out = match(self.rows(), main_industry='음식점업', demote_industry=False, top=3)
        self.assertEqual(self.ids(out), ['제조전용', '모름', '음식가능'])
        out = match(self.rows(), table={}, main_industry='음식점업', top=3)
        self.assertEqual(self.ids(out), ['제조전용', '모름', '음식가능'])
        self.assertFalse(out['industry']['active'])

    def test_region_stays_stronger_than_industry(self):
        rows = {'업종밖': notice('제조 창업지원', region='경기'), '다른도': notice('서울 창업지원', region='서울'),
                '정상': notice('창업지원', region='경기')}
        table = {'active': True, 'notices': {'업종밖': {'sections': ['C'], 'allowed': ['제조업']}}}
        out = match(rows, table=table, main_industry='음식점업', region='경기', top=3)
        self.assertEqual(self.ids(out), ['정상', '업종밖', '다른도'])

    def test_industry_is_stronger_than_group_rule(self):
        rows = {'집단': notice('여성기업 육성사업'), '업종밖': notice('제조 창업지원'), '정상': notice('창업지원')}
        table = {'active': True, 'notices': {'업종밖': {'sections': ['C'], 'allowed': ['제조업']}}}
        out = match(rows, table=table, main_industry='음식점업', top=3)
        self.assertEqual(self.ids(out), ['정상', '집단', '업종밖'])

    def test_score_mode_uses_industry_penalty(self):
        out = match(self.rows(), main_industry='음식점업', top=3,
                    weights={'mode': 'score', 'penalty_industry': 1.0})
        self.assertEqual(self.ids(out)[-1], '제조전용')


if __name__ == '__main__':
    unittest.main()
