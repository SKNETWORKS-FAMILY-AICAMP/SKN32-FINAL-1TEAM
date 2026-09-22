# -*- coding: utf-8 -*-
r"""검색어 구성 비교(eval/query_ablation.py) 테스트 — Codex 리뷰 QUERY_ABLATION_REVIEW_20260921.md.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_query_ablation -v

**DB·모델·Chroma 를 부르지 않는다.** 서비스 match() 는 진짜로 부르고, 그 아래 벡터·공고·BM25·인코더만 가짜다.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'eval'))
import unittest
from datetime import date

import numpy as np

import query_ablation as qa
from search import app, hybrid

AS_OF = date(2026, 9, 15)


class FakeBM25:
    """단어 검색 대역 — 질의에 '팀' 이 있으면 c 를 1위로 올린다(검색어가 바뀌면 결과가 바뀌는지 보려고)."""
    def __init__(self, ids):
        self.ids = ids

    def search(self, text, top=50):
        order = ['c', 'a', 'b', 'd'] if '팀 경력' in text else ['a', 'b', 'c', 'd']
        return [(n, 1.0 / (i + 1)) for i, n in enumerate(order)][:top]

    def __len__(self):
        return len(self.ids)


def rows():
    base = {'title': '', 'organizer': '', 'supervising_org': '', 'executing_org': '', 'source': 't',
            'target_category': '', 'category': '', 'apply_start': None, 'apply_period_type': 'fixed',
            'url': '', 'apply_url': '', 'region': '전국'}
    return {
        'a': dict(base, notice_id='a', title='AI 검사 장비 지원', apply_end=None),
        'b': dict(base, notice_id='b', title='마감된 공고', apply_end='2026-09-01'),     # 기준일 전에 마감
        'c': dict(base, notice_id='c', title='부산 전용 지원', apply_end=None, region='부산'),
        'd': dict(base, notice_id='d', title='기타 지원', apply_end=None),
    }


def pipeline():
    ids = ['a', 'b', 'c', 'd']
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.1, 0.9]], dtype='float32')
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return qa.Pipeline(collection=qa.NumpyCollection(ids, vectors), rows=rows(),
                       bm25=FakeBM25(ids), encode=lambda text: [1.0, 0.0])


PAYLOAD = {'applicant_type': '법인', 'founded_at': '2021-04-01', 'idea': 'AI 검사 장비',
           'revenue': [{'item': '장비 판매'}], 'team': [{'career': '금형 설계 12년'}], 'region': '경기'}


class QueryOnlyTests(unittest.TestCase):
    def test_variant_changes_query_text_only(self):
        req = app.MatchRequest(**PAYLOAD)
        full = app.build_query(req)
        with qa.query_only({'team': []}):
            stripped = app.build_query(req)
        self.assertIn('팀 경력', full)
        self.assertNotIn('팀 경력', stripped)
        self.assertEqual(req.team[0].career, '금형 설계 12년')        # 입력(req)은 그대로
        self.assertEqual(app.build_query(req), full)                  # 끝나면 원래대로

    def test_rules_still_see_team_when_query_drops_it(self):
        """팀 경력은 대상 집단 규칙에도 쓰인다. 검색어에서 빼도 match() 의 규칙은 팀을 본다."""
        seen = {}
        from search import rank_rules
        original = rank_rules.applicant_text

        def spy(idea, words):
            seen['words'] = list(words)
            return original(idea, words)

        rank_rules.applicant_text = spy
        try:
            pipeline().final(PAYLOAD, 'hybrid', {'team': []}, AS_OF)
        finally:
            rank_rules.applicant_text = original
        self.assertIn('금형 설계 12년', seen['words'])

    def test_all_variants_defined(self):
        self.assertEqual(set(qa.QUERY_VARIANTS), {'전체', '-팀경력', '-수익모델', '-팀경력-수익모델'})
        self.assertEqual(qa.PROBES['+채용계획'], {'hiring_plan': True})


class FinalPipelineTests(unittest.TestCase):
    def test_final_applies_expiry_and_region_rules(self):
        p = pipeline()
        raw, _ = p.raw(PAYLOAD, 'dense', {}, AS_OF)
        final, _ = p.final(PAYLOAD, 'dense', {}, AS_OF, top=3)
        self.assertEqual(raw[:3], ['a', 'b', 'c'])                    # 검색 직후
        self.assertNotIn('b', final)                                  # 기준일 전 마감 → 숨김
        self.assertEqual(final[-1], 'c')                              # 부산 전용 → 경기 신청자에게 뒤로
        self.assertEqual(final, ['a', 'd', 'c'])

    def test_hybrid_query_change_reaches_bm25(self):
        p = pipeline()
        with_team, _ = p.raw(PAYLOAD, 'hybrid', {}, AS_OF)
        without_team, _ = p.raw(PAYLOAD, 'hybrid', {'team': []}, AS_OF)
        self.assertNotEqual(with_team[:3], without_team[:3])

    def test_today_is_pinned_to_as_of(self):
        """기준일 뒤에 마감한 공고는 '오늘' 이 기준일이면 보여야 한다."""
        p = pipeline()
        final_early, _ = p.final(PAYLOAD, 'dense', {}, date(2026, 8, 31), top=3)
        self.assertIn('b', final_early)                               # 8/31 기준으로는 아직 마감 전
        self.assertIsNot(app.date, None)
        self.assertEqual(app.date.today(), date.today())              # 끝나면 원래 날짜로


class ServiceDefaultsTests(unittest.TestCase):
    """비교가 기대는 서비스 기본값. 바뀌면 비교 결과를 다시 봐야 하므로 여기서 먼저 깨진다."""

    def test_match_request_defaults(self):
        req = app.MatchRequest(applicant_type='법인', idea='x')
        self.assertEqual((req.top, req.hide_expired, req.demote_groups, req.demote_region,
                          req.demote_district, req.search), (3, True, True, True, True, 'hybrid'))

    def test_weights_and_depth(self):
        w = app.Weights()
        self.assertEqual((w.dense, w.bm25, w.rrf_k, w.mode), (1.0, 1.0, 60, 'order'))
        self.assertEqual(hybrid.DEPTH, 50)


class ReportTests(unittest.TestCase):
    def test_run_and_report_with_fixture(self):
        import tempfile
        import shutil
        queries = {'q1': {'kind': 'normal', 'as_of_date': '2026-09-15', 'payload': PAYLOAD},
                   'q2': {'kind': 'normal', 'as_of_date': '2026-09-15',
                          'payload': dict(PAYLOAD, team=[])}}
        qrels = {'q1': {'a': 2, 'd': 1}, 'q2': {'a': 2}}
        human = {'q1': {'a'}}
        results = qa.run_all(queries, qrels, human, pipeline(), modes=('dense',))
        self.assertIn(('final', 'dense', '-팀경력'), results)
        self.assertIn(('raw', 'dense', '+채용계획'), results)
        summary = results[('final', 'dense', '전체')][1]
        self.assertEqual(summary['queries'], 2)
        self.assertEqual(summary['human_judged_slots'], 1)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        mani = {'run_at': 'test', 'qrels_pairs': {}, 'judges': 'all', 'as_of_dates': ['2026-09-15'],
                'eval_queries': {'normal': 2}}
        text = qa.write_report(tmp, results, mani)
        self.assertIn('최종 Top 3 (서비스 match)', text)
        self.assertIn('원시 Top 3 (검색 직후)', text)
        self.assertIn('팀 경력 전체 제거', text)
        for name in ('summary.json', 'summary.md', 'per_query.jsonl'):
            self.assertTrue(os.path.isfile(os.path.join(tmp, name)))
        with open(os.path.join(tmp, 'per_query.jsonl'), encoding='utf-8') as f:
            first = f.readline()
        self.assertIn('"run_at": "test"', first)                      # 두 파일이 같은 실행을 가리킨다


if __name__ == '__main__':
    unittest.main()
