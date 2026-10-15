# -*- coding: utf-8 -*-
"""eval/filter_first_now.py — 지금 서비스로 9/28 평가 다시 재기(2026-10-14). DB·모델 없이 본다."""
import io
import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'eval')):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402

from eval import filter_first_now as fnow  # noqa: E402
import filter_first_eval as ffe  # noqa: E402
from search import app, memvec  # noqa: E402

REF_RESULTS = os.path.join(ROOT, 'reports', fnow.REFERENCE_RUN, 'results.json')
# 9/28 결과 파일 meta.vector_only_settings 를 그대로 옮겨 적은 값
SETTINGS_0928 = {'search': 'dense', 'structured_filter': False, 'hide_expired': False, 'demote_region': False,
                 'demote_groups': False, 'demote_district': False, 'demote_industry': False,
                 'use_applicant_types': False}


def _memory():
    """공고 a·b·c·d 네 건. 질의 [1,0,0] 에 가까운 순서는 a > b > c > d. 말뭉치는 a·c·d(b 는 9/16 뒤 수집)."""
    vecs = np.array([[1.0, 0, 0], [0.9, 0.43589, 0], [0.6, 0.8, 0], [0, 0, 1.0]], dtype='float32')
    return memvec.MemoryCollection(['a', 'b', 'c', 'd'], vecs)


class CorpusMemoryTests(unittest.TestCase):
    def test_query_hides_notices_outside_corpus(self):
        col = fnow.CorpusMemory(_memory(), {'a', 'c', 'd'})
        self.assertEqual(col.count(), 3)
        got = col.query(query_embeddings=[[1.0, 0, 0]], n_results=10)
        self.assertEqual(got['ids'][0], ['a', 'c', 'd'])                  # b 는 더 가깝지만 말뭉치 밖
        got = col.query(query_embeddings=[[1.0, 0, 0]], ids=['b', 'c', 'x'], n_results=5)
        self.assertEqual(got['ids'][0], ['c'])                            # 넘긴 ids 도 말뭉치 안만
        got = col.query(query_embeddings=[[1.0, 0, 0]], ids=['b'], n_results=5)
        self.assertEqual(got['ids'][0], [])

    def test_get_without_ids_is_corpus_only(self):
        col = fnow.CorpusMemory(_memory(), {'a', 'c'})
        self.assertEqual(sorted(col.get(include=[])['ids']), ['a', 'c'])
        got = col.get(ids=['b', 'c'], include=['embeddings'])
        self.assertEqual(got['ids'], ['c'])
        self.assertEqual(len(got['embeddings']), 1)

    def test_service_dense_path_stays_memory_and_inside_corpus(self):
        """서비스 _dense_within 이 감싼 묶음에서도 정상 경로('memory')로 돌고 말뭉치 밖을 내지 않는다."""
        col = fnow.CorpusMemory(_memory(), {'a', 'c', 'd'})
        with mock.patch.dict(app.STATE, {'vector_ids': {'a', 'c', 'd'}}):
            hits, path, error = app._dense_within(col, [1.0, 0, 0], ['a', 'b', 'c', 'd'], 2)
        self.assertEqual((path, error), ('memory', None))
        self.assertEqual([n for n, _ in hits], ['a', 'c'])


class RestrictCorpusTests(unittest.TestCase):
    def _state(self):
        rows = {n: {'notice_id': n, 'title': 't' + n} for n in 'abcde'}
        return {'rows': rows, 'collection': _memory(), 'vector_ids': {'a', 'b', 'c', 'd'}, 'bm25': None}

    def test_rows_vectors_and_bm25_shrink_to_corpus(self):
        state = self._state()
        corpus = {n: {'notice_id': n, 'title': '창업 지원 ' + n, 'body': '본문'} for n in ('a', 'c', 'e')}
        ids = fnow.restrict_corpus(state, corpus)
        self.assertEqual(ids, {'a', 'c'})                                 # e 는 벡터가 없다
        self.assertEqual(set(state['rows']), {'a', 'c'})
        self.assertEqual(state['vector_ids'], {'a', 'c'})
        self.assertIsInstance(state['collection'], fnow.CorpusMemory)
        self.assertEqual(state['collection'].count(), 2)
        self.assertEqual(sorted(state['bm25'].ids), ['a', 'c'])

    def test_stops_when_vectors_missing(self):
        state = self._state()
        state.update(collection=None, vector_ids=None, boot_errors={'vector_db': {}})
        with self.assertRaises(SystemExit):
            fnow.restrict_corpus(state, {'a': {'title': 'x'}})


class SettingsTests(unittest.TestCase):
    def test_vector_only_switches_match_0928_meta(self):
        self.assertEqual(fnow.VECTOR_ONLY_SWITCHES, SETTINGS_0928)
        if os.path.exists(REF_RESULTS):
            with io.open(REF_RESULTS, encoding='utf-8') as f:
                meta = json.load(f)['meta']
            self.assertEqual(fnow.VECTOR_ONLY_SWITCHES, meta['vector_only_settings'])

    def test_vector_only_request_is_pure_similarity(self):
        req = app.MatchRequest(**fnow.request_for('vector_only', {'idea': 'x', 'applicant_type': '법인'}))
        self.assertEqual(req.search, 'dense')
        self.assertEqual(req.top, fnow.K)
        self.assertEqual(req.weights.bonus, 0.0)                          # 9/28 에 없던 가산점 반영은 끈다
        on = [k for k, f in app.MatchRequest.model_fields.items() if f.annotation is bool and getattr(req, k)]
        self.assertEqual(on, [])

    def test_filter_first_request_is_service_default(self):
        req = app.MatchRequest(**fnow.request_for('filter_first', {'idea': 'x', 'applicant_type': '법인'}))
        default = app.MatchRequest(idea='x', applicant_type='법인')
        self.assertEqual(req.search, 'hybrid')
        self.assertEqual(req.top, fnow.K)
        self.assertEqual(req.weights, default.weights)                    # 가산점 세기 등 서비스 기본값 그대로
        for key in ('structured_filter', 'hide_expired', 'use_applicant_types', 'demote_groups', 'demote_industry'):
            self.assertEqual(getattr(req, key), getattr(default, key), key)
        with self.assertRaises(ValueError):
            fnow.request_for('legacy', {})


class QrelsTests(unittest.TestCase):
    ROWS = [{'qid': 'q1', 'notice_id': 'a', 'topic_rel': 2}, {'qid': 'q1', 'notice_id': 'b', 'topic_rel': 0},
            {'qid': 'q2', 'notice_id': 'a', 'topic_rel': 1}]

    def test_current_file_used_when_count_matches(self):
        loader = mock.Mock()
        rows, source = fnow.choose_qrels(self.ROWS, loader, expected=3)
        self.assertIs(rows, self.ROWS)
        self.assertIn('지금 파일', source)
        loader.assert_not_called()

    def test_0928_version_used_when_count_differs(self):
        rows, source = fnow.choose_qrels(self.ROWS[:2], lambda: self.ROWS, expected=3)
        self.assertEqual(rows, self.ROWS)
        self.assertIn(fnow.QRELS_COMMIT_0928, source)
        with self.assertRaises(SystemExit):
            fnow.choose_qrels(self.ROWS[:2], lambda: self.ROWS[:1], expected=3)

    def test_qrels_from_rows(self):
        self.assertEqual(fnow.qrels_from_rows(self.ROWS), {'q1': {'a': 2, 'b': 0}, 'q2': {'a': 1}})


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake(nid, row, age, today, check_deadline, table, kind):
            self.calls.append((nid, table is not None, kind, check_deadline))
            return (nid != 'x', [] if nid != 'x' else ['접수 마감'], None)
        self.fake = fake
        self.rows = {'a': {}, 'x': {}}
        self.table = {'active': True, 'notices': {}}

    def test_current_criterion_passes_table_to_entities(self):
        out = fnow.eligibility_checks(self.fake, self.rows, ['a', 'x'], 12, date(2026, 9, 15), self.table, '법인')
        self.assertEqual(out, {'a': (True, []), 'x': (False, ['접수 마감'])})
        self.assertTrue(all(c[1] and c[3] for c in self.calls))           # 판정표 넘김 · 마감 확인

    def test_0928_criterion_only_pre_founder_uses_table(self):
        fnow.eligibility_checks(self.fake, self.rows, ['a'], 12, date(2026, 9, 15), self.table, '개인사업자',
                                entity_blocks=False)
        fnow.eligibility_checks(self.fake, self.rows, ['a'], None, date(2026, 9, 15), self.table, '예비창업자',
                                entity_blocks=False)
        self.assertEqual([c[1] for c in self.calls], [False, True])

    def test_inactive_table_is_not_used(self):
        fnow.eligibility_checks(self.fake, self.rows, ['a'], None, date(2026, 9, 15), {'active': False}, '예비창업자')
        self.assertEqual([c[1] for c in self.calls], [False])

    def test_real_service_rule_blocks_entity_strong_no(self):
        """실제 app.eligible_with_types — 법인 '불가' strong 공고는 지금 기준에서만 불가로 센다."""
        info = {'pre_founder': {'status': 'unknown', 'strength': None},
                'sole_proprietor': {'status': 'unknown', 'strength': None},
                'corporation': {'status': 'not_allowed', 'strength': 'strong'}, 'varies': False}
        table = {'active': True, 'notices': {'n1': info}}
        rows = {'n1': {'notice_id': 'n1', 'recruitment_status': 'open', 'apply_end': '2026-12-31',
                       'age_condition_raw': None}}
        now = fnow.eligibility_checks(app.eligible_with_types, rows, ['n1'], 30, date(2026, 9, 15), table, '법인')
        then = fnow.eligibility_checks(app.eligible_with_types, rows, ['n1'], 30, date(2026, 9, 15), table, '법인',
                                       entity_blocks=False)
        self.assertEqual(now['n1'], (False, ['법인 불가(공고 본문)']))
        self.assertEqual(then['n1'], (True, []))


def _metrics(**kw):
    m = {key: 0.0 for key, _l, _b in ffe.METRICS}
    m.update(kw)
    return m


class SummaryShapeTests(unittest.TestCase):
    def _per(self):
        return {'hybrid': {'vector_only': [_metrics(ineligible_k=0.3, p3_lo=1 / 3), _metrics(ineligible_k=0.2, p3_lo=0.0),
                                           _metrics(ineligible_k=None, p3_lo=2 / 3)],
                           'filter_first': [_metrics(ineligible_k=0.0, p3_lo=2 / 3), _metrics(ineligible_k=0.0, p3_lo=1 / 3),
                                            _metrics(ineligible_k=0.1, p3_lo=2 / 3)]}}

    def test_same_keys_as_0928_summary(self):
        summary = fnow.build_summary(self._per())
        self.assertEqual(list(summary), ['hybrid'])
        self.assertEqual(list(summary['hybrid']), [k for k, _l, _b in ffe.METRICS])
        expected = {'label', 'better', 'vector_only', 'legacy', 'filter_first', 'diff', 'diff_vs_vector'}
        if os.path.exists(REF_RESULTS):
            with io.open(REF_RESULTS, encoding='utf-8') as f:
                old = json.load(f)['summary']['hybrid']
            self.assertEqual(list(summary['hybrid']), list(old))
            expected = set(old['ineligible_k'])
        for key, row in summary['hybrid'].items():
            self.assertEqual(set(row), expected, key)
            self.assertIsNone(row['legacy'])
            self.assertIsNone(row['diff'])
        row = summary['hybrid']['ineligible_k']
        self.assertAlmostEqual(row['vector_only'], 0.25)                 # None 은 평균에서 뺀다
        self.assertAlmostEqual(row['filter_first'], 1 / 30)
        self.assertEqual(len(row['diff_vs_vector']), 3)
        self.assertAlmostEqual(row['diff_vs_vector'][0], -0.25)          # 짝이 맞는 두 질의만: (-0.3 + -0.2)/2
        json.dumps(summary)                                               # JSON 으로 쓸 수 있어야 한다

    def test_meta_has_required_fields(self):
        state = {'vectors_info': {'count': 3, 'dropped': 0, 'fingerprints': {'fp': 3}},
                 'applicant_types': {'active': True, 'source': 'db', 'notices': {'a': {}}},
                 'bonus_reviewed': {'a': {}}, 'boot_errors': {'bonus_documents': 'x'}}
        meta = fnow.build_meta(__import__('datetime').datetime(2026, 10, 14, 1, 2, 3), {'a', 'b'}, date(2026, 9, 15),
                               [{}] * 58, {'q1': {'a': 2, 'b': 0}}, 'src', 'sha', state)
        for key in ('run_at', 'corpus_before', 'corpus_notices', 'as_of', 'queries', 'k', 'modes', 'qrels_pairs',
                    'systems', 'openai_calls', 'db_writes', 'kind', 'ineligibility_criterion', 'vector_only_settings',
                    'legacy_commit', 'judges', 'status_as_of', 'summary_status'):
            self.assertIn(key, meta)
        self.assertEqual(meta['modes'], ['hybrid'])
        self.assertEqual(meta['systems'], ['vector_only', 'filter_first'])
        self.assertEqual((meta['openai_calls'], meta['db_writes']), (0, 0))
        self.assertEqual(meta['kind'], '지금 서비스 다시 재기')
        self.assertEqual(meta['ineligibility_criterion'], '10/13 기준: 예비창업자 + 개인사업자·법인 강한 불가 포함')
        self.assertEqual((meta['corpus_before'], meta['corpus_notices'], meta['queries'], meta['qrels_pairs']),
                         ('2026-09-16', 2, 58, 2))
        self.assertIsNone(meta['legacy_commit'])
        self.assertEqual(meta['boot_warnings'], ['bonus_documents'])       # 오류 원문(주소 등)은 남기지 않는다
        self.assertNotIn('x', json.dumps(meta['boot_warnings']))


class BreakdownTests(unittest.TestCase):
    LISTS = [
        {'system': 'vector_only', 'qid': 'q1', 'mode': 'hybrid', 'ranked': ['a', 'b', 'c', 'd'],
         'ineligible': ['a', 'b', 'c'],
         'why': {'a': ['모집 마감'], 'b': ['모집 마감', '접수 마감'], 'c': ['법인 불가(공고 본문)']},
         'ineligible_0928_criterion': ['a', 'b']},
        {'system': 'filter_first', 'qid': 'q1', 'mode': 'hybrid', 'ranked': ['d'], 'ineligible': [], 'why': {},
         'ineligible_0928_criterion': []},
    ]

    def test_reasons_and_0928_criterion(self):
        rows = {'a': {'apply_end': date(2026, 9, 30)}, 'b': {'apply_end': date(2026, 9, 1)}, 'c': {}}
        b = fnow.ineligible_breakdown(self.LISTS, rows, date(2026, 9, 15), 'vector_only')
        self.assertEqual((b['slots'], b['ineligible_slots'], b['entity_block_slots']), (4, 3, 1))
        self.assertEqual(b['by_reason'], {'모집 마감': 2, '접수 마감': 1, '법인 불가(공고 본문)': 1})
        self.assertEqual(b['only_reason'], {'모집 마감': 1, '법인 불가(공고 본문)': 1})
        self.assertEqual(b['closed_status_but_open_on_as_of'], 1)         # a: 9/15 에는 마감 전
        self.assertAlmostEqual(b['ineligible_k_0928_criterion'], 0.5)
        self.assertEqual(fnow.ineligible_breakdown(self.LISTS, rows, date(2026, 9, 15), 'filter_first')['ineligible_slots'], 0)

    def test_overlap_with_reference(self):
        ref = [{'system': 'vector_only', 'qid': 'q1', 'mode': 'hybrid', 'ranked': ['a', 'b', 'e', 'd'],
                'ineligible': ['b', 'e']},
               {'system': 'vector_only', 'qid': 'q1', 'mode': 'dense', 'ranked': ['z'], 'ineligible': ['z']}]
        o = fnow.list_overlap(ref, self.LISTS, 'vector_only')
        self.assertEqual((o['queries'], o['same_order'], o['same_set_k']), (1, 0, 0))
        self.assertAlmostEqual(o['overlap_k'], 0.75)
        self.assertEqual(o['ineligible_slots'], {'both': 1, 'now_only': 1, 'now_in_new_notices': 1,
                                                 'then_in_dropped_notices': 1})
        self.assertEqual(o['now_only_reasons'], {'모집 마감': 1})

    def test_direction_words(self):
        self.assertEqual(fnow.direction(0.621, 0.65), '올랐다')
        self.assertEqual(fnow.direction(0.621, 0.60), '내렸다')
        self.assertEqual(fnow.direction(0.5, 0.5), '같다')
        self.assertEqual(fnow.direction(None, 0.5), '비교할 수 없다')


class AsOfStatusTests(unittest.TestCase):
    """기준일 모집 상태 — 지금 closed 인 공고를 기준일에도 닫혀 있었다고 볼지(2026-10-14 사용자 결정)."""
    AS_OF = date(2026, 9, 15)
    SWEEP = __import__('datetime').datetime(2026, 10, 1, 23, 43)      # close_missing 첫 일괄 닫기

    def decide(self, **ev):
        ev = dict({'status': 'closed', 'listed_open': True}, **ev)
        return fnow.status_decision(ev, self.AS_OF, self.SWEEP)

    def test_open_and_unknown_are_left_alone(self):
        self.assertIsNone(fnow.status_decision({'status': 'open', 'apply_end': date(2026, 9, 1)}, self.AS_OF))
        self.assertIsNone(fnow.status_decision({'status': 'unknown'}, self.AS_OF))

    def test_deadline_on_or_after_as_of_reopens(self):
        snap = __import__('datetime').datetime(2026, 10, 1, 23, 43)
        self.assertEqual(self.decide(apply_end=date(2026, 9, 30), snapshot_at=snap), 'reopened_deadline_after_as_of')
        self.assertEqual(self.decide(apply_end=date(2026, 9, 15), snapshot_at=snap), 'reopened_deadline_after_as_of')
        self.assertEqual(self.decide(apply_end='2026-10-20', snapshot_at='2026-10-07 00:00:00'),
                         'reopened_deadline_after_as_of')

    def test_deadline_before_as_of_stays_closed(self):
        self.assertEqual(self.decide(apply_end=date(2026, 9, 14), snapshot_at=self.SWEEP), 'kept_closed_deadline_passed')

    def test_closed_record_on_or_before_as_of_stays_closed(self):
        """기준일 당일·전에 이미 닫힌 기록이 있으면 마감일이 남아 있어도 그대로 둔다(일찍 닫힘)."""
        self.assertEqual(self.decide(apply_end=date(2026, 9, 30), snapshot_at=date(2026, 9, 15), listed_open=False),
                         'kept_closed_recorded_by_as_of')
        self.assertEqual(self.decide(apply_end=None, snapshot_at=date(2026, 9, 10)), 'kept_closed_recorded_by_as_of')

    def test_no_deadline_can_only_be_dated_after_first_sweep(self):
        # 첫 일괄 닫기(10/1)에 닫힌 공고는 언제 목록에서 빠졌는지 모른다 → 그대로
        self.assertEqual(self.decide(apply_end=None, snapshot_at=self.SWEEP), 'kept_closed_undatable')
        # 그 뒤의 날에 닫혔으면 10/1 목록에는 모집 중으로 있었다 → 기준일에도 열림
        self.assertEqual(self.decide(apply_end=None, snapshot_at=date(2026, 10, 7)), 'reopened_listed_after_first_sweep')
        # 출처가 마감으로 준 공고·원본 표시를 모르는 공고·첫 일괄 닫기를 모르면 날짜를 정할 수 없다
        self.assertEqual(self.decide(apply_end=None, snapshot_at=date(2026, 10, 7), listed_open=False),
                         'kept_closed_undatable')
        self.assertEqual(self.decide(apply_end=None, snapshot_at=date(2026, 10, 7), listed_open=None),
                         'kept_closed_undatable')
        self.assertEqual(fnow.status_decision({'status': 'closed', 'listed_open': True, 'snapshot_at': date(2026, 10, 7)},
                                              self.AS_OF, None), 'kept_closed_undatable')
        # 첫 일괄 닫기가 기준일 전이면(그때 이미 닫기가 돌았다) 이 규칙으로 되살리지 않는다
        self.assertEqual(fnow.status_decision({'status': 'closed', 'listed_open': True, 'snapshot_at': date(2026, 10, 7)},
                                              self.AS_OF, date(2026, 9, 1)), 'kept_closed_undatable')

    def test_unreadable_dates_do_not_raise(self):
        self.assertEqual(self.decide(apply_end='2026-02-30', snapshot_at='모름'), 'kept_closed_undatable')

    def test_as_of_status_and_reopen_change_memory_rows_only(self):
        evidence = {'a': {'status': 'closed', 'apply_end': date(2026, 9, 30), 'snapshot_at': self.SWEEP, 'listed_open': True},
                    'b': {'status': 'closed', 'apply_end': date(2026, 9, 1), 'snapshot_at': self.SWEEP, 'listed_open': True},
                    'c': {'status': 'open', 'apply_end': None, 'snapshot_at': self.SWEEP, 'listed_open': True},
                    'd': {'status': 'closed', 'apply_end': None, 'snapshot_at': self.SWEEP, 'listed_open': True}}
        decisions = fnow.as_of_status(evidence, self.AS_OF, self.SWEEP)
        self.assertEqual(decisions, {'a': 'reopened_deadline_after_as_of', 'b': 'kept_closed_deadline_passed',
                                     'd': 'kept_closed_undatable'})
        rows = {n: {'recruitment_status': evidence[n]['status']} for n in evidence}
        rows['a2'] = {'recruitment_status': 'open'}
        changed = fnow.reopen(rows, [n for n, d in decisions.items() if d in fnow.REOPEN] + ['a2', 'zz'])
        self.assertEqual(changed, {'a'})
        self.assertEqual({n: r['recruitment_status'] for n, r in rows.items()},
                         {'a': 'open', 'b': 'closed', 'c': 'open', 'd': 'closed', 'a2': 'open'})
        meta = fnow.status_meta(decisions, evidence, self.AS_OF, self.SWEEP, changed)
        self.assertEqual((meta['date'], meta['reopened'], meta['closed_now_in_corpus'], meta['db_rows_changed']),
                         ('2026-09-15', 1, 3, 0))
        self.assertEqual(meta['decisions']['kept_closed_undatable'], 1)
        self.assertEqual(meta['first_close_sweep'], '2026-10-01')
        self.assertEqual(set(meta['decisions']), set(fnow.DECISIONS))
        self.assertIn('rule', meta)

    def test_reopened_notice_passes_service_filter(self):
        """되돌린 공고는 서비스 정형 필터(gate.prefilter)를 통과한다 — 마감일이 지난 공고는 여전히 접수 마감."""
        from search import gate
        row = {'notice_id': 'a', 'recruitment_status': 'closed', 'apply_end': '2026-09-30', 'age_condition_raw': None}
        self.assertEqual(gate.prefilter(row, None, self.AS_OF), (False, ['모집 마감']))
        fnow.reopen({'a': row}, ['a'])
        self.assertEqual(gate.prefilter(row, None, self.AS_OF), (True, []))


def _readme_inputs():
    per = {'hybrid': {s: [_metrics(ineligible_k=0.3, p3_lo=0.5)] * 3 for s in fnow.SYSTEMS}}
    per['hybrid']['filter_first'] = [_metrics(ineligible_k=0.0, p3_lo=0.6)] * 3
    per_t = {'hybrid': {'vector_only': [_metrics(ineligible_k=0.4, p3_lo=0.5)] * 3,
                        'filter_first': [_metrics(ineligible_k=0.0, p3_lo=0.55)] * 3}}
    state = {'vectors_info': {'count': 3}, 'applicant_types': {}, 'bonus_reviewed': {}, 'boot_errors': {}}
    st = fnow.status_meta({'a': 'reopened_deadline_after_as_of'},
                          {'a': {'status': 'closed', 'listed_open': True}}, date(2026, 9, 15), None, {'a'})
    meta = fnow.build_meta(__import__('datetime').datetime(2026, 10, 14), {'a'}, date(2026, 9, 15), [{}] * 3,
                           {'q': {'a': 2}}, 'src', 'sha', state, status_as_of=st)
    lists = [{'system': s, 'qid': 'q', 'mode': 'hybrid', 'ranked': ['a'], 'ineligible': [], 'why': {},
              'ineligible_0928_criterion': []} for s in fnow.SYSTEMS]
    breakdown = {s: fnow.ineligible_breakdown(lists, {}, date(2026, 9, 15), s) for s in fnow.SYSTEMS}
    return meta, fnow.build_summary(per), fnow.build_summary(per_t), breakdown, lists


class ReadmeTests(unittest.TestCase):
    def test_readme_renders_with_and_without_reference(self):
        meta, summary, summary_t, breakdown, lists = _readme_inputs()
        self.assertEqual(meta['status_as_of']['reopened'], 1)
        text = '\n'.join(fnow.render_readme(meta, summary, summary_t, breakdown, breakdown, None))
        self.assertIn('| 신청 불가@10 | 30.0% | 0.0% |', text)
        self.assertIn('시계 비유', text)
        self.assertIn('| 신청 불가@10 | 30.0% | 40.0% | 0.0% | 0.0% |', text)       # 기준일 상태 vs 오늘 상태
        self.assertNotIn('9/28 과 비교', text)
        ref = {'meta': {'corpus_notices': 2084},
               'summary': {'hybrid': {k: {'vector_only': 0.243, 'filter_first': 0.621} for k, _l, _b in ffe.METRICS}},
               'lists': []}
        reference, reference_t = fnow.compare_reference(ref, summary, lists), fnow.compare_reference(ref, summary_t, lists)
        text = '\n'.join(fnow.render_readme(meta, summary, summary_t, breakdown, breakdown, reference, reference_t))
        self.assertIn('9/28 과 비교', text)
        self.assertIn('**필터 먼저 P@3(2) 하한**: 9/28 62.1% → 지금 60.0% — **내렸다**', text)
        self.assertIn('필터 먼저 P@3(2) 하한 55.0% (9/28 대비 내렸다', text)


if __name__ == '__main__':
    unittest.main()
