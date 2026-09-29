# -*- coding: utf-8 -*-
"""규칙이 결합될 때의 순서와 자격 판정 — Codex 검토(2026-09-18) 회귀 테스트.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_match_rules -v

DB·모델·HTTP 없이 `app.match()` 와 `app.eligibility()` 를 가짜 색인으로 직접 부른다.
검토 문서: docs/reviews/matching/MATCHING_REVIEW_20260918.md

여기서 고정하는 것
  1번  시·도 → 시·군·구 → 집단 순서. 나중 규칙이 앞선 규칙을 덮어쓰지 않는다
  4번  설립일을 모르는 사업자를 예비창업자(미설립)로 보지 않는다
  날짜 잘못된 설립일이 HTTP 500 이 되지 않는다 (형식 오류 + 달력에 없는 날짜)
  3번  마감 공고를 걸러내 후보가 모자라면 더 깊이 찾는다
  2번  한 검색 안에서는 한 가지 점수 체계만 쓴다 (RRF 와 코사인을 섞지 않는다)
  P3   search_ms 가 검색 구간 전체를 담는다 (벡터 추가 조회·결합 시간이 빠지지 않는다)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from unittest.mock import patch

from search import app, gate, hybrid


class FakeCollection:
    """ID 순서대로 돌려주는 가짜 Chroma. 거리는 0.20 + i*0.005 (앞일수록 가깝다)."""

    def __init__(self, ids):
        self.ids = ids
        self.asked = []          # query(ids=...) 로 받은 후보 — 검색이 필터 뒤에 도는지 본다

    def count(self):
        return len(self.ids)

    def query(self, query_embeddings=None, n_results=10, ids=None):
        self.asked.append(None if ids is None else list(ids))
        pool = self.ids if ids is None else [n for n in self.ids if n in set(ids)]
        ids = pool[:n_results]
        return {'ids': [ids], 'distances': [[0.20 + self.ids.index(n) * 0.005 for n in ids]]}

    def get(self, ids=None, include=None):
        ids = list(self.ids if ids is None else ids)
        return {'ids': ids, 'embeddings': [[0.0] * 4 for _ in ids]}


def notice(nid, **kw):
    row = {'notice_id': nid, 'title': nid, 'organizer': '', 'source': 'test',
           'target_category': '중소기업', 'category': '', 'region': '전국',
           'age_condition_raw': '7년미만', 'apply_start': '2000-01-01',
           'apply_end': '2099-12-31', 'apply_period_type': 'fixed',
           'recruitment_status': 'open', 'url': '', 'apply_url': ''}
    row.update(kw)
    return row


def state(rows):
    ids = list(rows)
    return {'collection': FakeCollection(ids), 'rows': rows,
            'bm25': hybrid.BM25([(n, '창업 지원') for n in ids])}


def match(rows, **kw):
    # 규칙 순서만 보는 테스트라 검색은 의미 검색(dense)으로 고정한다.
    # 가짜 BM25 는 모든 공고 문장이 같아 순위가 동점이 되고, 동점은 id 순으로 갈려
    # 무엇을 재는지 흐려진다.
    kw.setdefault('search', 'dense')
    req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01',
                           idea='창업 지원', **kw)
    with patch.dict(app.STATE, state(rows), clear=True), \
            patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]):
        return app.match(req)


class RuleOrderTests(unittest.TestCase):
    """1번 — 시·군·구 규칙이 시·도 우선순위를 덮어쓰지 않는다."""

    def rows(self):
        # 검색 후보 순서: 성남(같은 도·다른 시) → 서울(다른 도) → 수원(우리 시)
        return {
            '성남': notice('[경기] 성남시 창업지원', region='경기'),
            '서울': notice('서울 창업지원', region='서울'),
            '수원': notice('[경기] 수원시 창업지원', region='경기'),
        }

    def test_same_province_beats_other_province(self):
        out = match(self.rows(), region='경기', district='수원시', top=3)
        self.assertEqual([r['notice_id'] for r in out['results']], ['수원', '성남', '서울'])

    def test_group_rule_is_the_weakest(self):
        rows = {
            '집단': notice('여성기업 육성사업', region='경기'),          # 집단 근거 없음
            '다른도': notice('서울 창업지원', region='서울'),             # 다른 시·도
            '정상': notice('[경기] 수원시 창업지원', region='경기'),
        }
        out = match(rows, region='경기', district='수원시', top=3)
        # 집단 규칙에 걸린 공고가 '다른 시·도' 공고보다는 앞이어야 한다
        self.assertEqual([r['notice_id'] for r in out['results']], ['정상', '집단', '다른도'])

    def test_lists_report_each_rule(self):
        out = match(self.rows(), region='경기', district='수원시', top=3)
        self.assertEqual([x['notice_id'] for x in out['region_demoted']], ['서울'])
        self.assertEqual([x['notice_id'] for x in out['district_demoted']], ['성남'])

    def test_order_is_unchanged_without_location(self):
        out = match(self.rows(), top=3)
        self.assertEqual([r['notice_id'] for r in out['results']], ['성남', '서울', '수원'])


class FilterFirstTests(unittest.TestCase):
    """정형 필터가 검색보다 먼저 돈다 — 기획서 5-3, 기능정의서 R-3 (2026-09-28).

    예전(3번)에는 검색 상위를 먼저 자르고 마감을 거른 뒤 모자라면 더 깊이 찾았다.
    이제는 모든 공고에 필터를 먼저 걸고, 통과한 공고 안에서만 검색한다.
    """

    def rows(self, expired=51, total=60):
        rows = {}
        for i in range(1, total + 1):
            nid = 'n%03d' % i
            rows[nid] = notice(nid, apply_end='2000-12-31' if i <= expired else '2099-12-31')
        return rows

    def run_match(self, rows, **kw):
        kw.setdefault('search', 'dense')
        req = app.MatchRequest(applicant_type=kw.pop('applicant_type', '법인사업자'),
                               founded_at=kw.pop('founded_at', '2025-01-01'), idea='창업 지원', **kw)
        st = state(rows)
        with patch.dict(app.STATE, st, clear=True), \
                patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]):
            return app.match(req), st['collection']

    def test_finds_live_notices_beyond_the_first_page(self):
        out = match(self.rows(), top=3)
        self.assertEqual([r['notice_id'] for r in out['results']], ['n052', 'n053', 'n054'])
        self.assertEqual(out['filtered_count'], 9)
        self.assertEqual(out['filter']['excluded'], {'접수 마감': 51})

    def test_search_only_sees_filtered_notices(self):
        out, col = self.run_match(self.rows(), top=3)
        self.assertEqual(len(col.asked), 1)
        self.assertEqual(sorted(col.asked[0]), ['n%03d' % i for i in range(52, 61)])
        self.assertEqual(out['pipeline'], ['정형 필터', '검색', '순위 통합'])

    def test_hybrid_bm25_is_also_limited(self):
        out = match(self.rows(), top=20, search='hybrid')
        self.assertEqual(out['count'], 9)
        self.assertTrue(all(r['notice_id'] >= 'n052' for r in out['results']))

    def test_everything_expired_returns_empty(self):
        out = match(self.rows(expired=60), top=3)
        self.assertEqual((out['count'], out['filtered_count']), (0, 0))    # 검색 순위로 채우지 않는다(R-3 ②)

    def test_expired_are_still_shown_when_asked(self):
        out = match(self.rows(), top=3, hide_expired=False)
        self.assertEqual([r['notice_id'] for r in out['results']], ['n001', 'n002', 'n003'])

    def test_structured_filter_off_is_plain_search(self):
        rows = self.rows()
        rows['n001'] = notice('n001', age_condition_raw='예비창업자', apply_end='2000-12-31')
        out = match(rows, top=3, structured_filter=False)
        self.assertEqual([r['notice_id'] for r in out['results']], ['n001', 'n002', 'n003'])
        self.assertEqual(out['filtered_count'], 60)

    def test_closed_status_is_excluded(self):
        rows = self.rows(expired=0, total=3)
        rows['n001'] = notice('n001', recruitment_status='closed')
        out = match(rows, top=3)
        self.assertEqual([r['notice_id'] for r in out['results']], ['n002', 'n003'])
        self.assertEqual(out['filter']['excluded'], {'모집 마감': 1})

    def test_business_age_and_applicant_type(self):
        rows = {'pre_only': notice('pre_only', age_condition_raw='예비창업자'),
                'under3': notice('under3', age_condition_raw='3년미만'),
                'under7': notice('under7', age_condition_raw='7년미만'),
                'pre_or7': notice('pre_or7', age_condition_raw='예비창업자,7년미만'),
                'no_field': notice('no_field', age_condition_raw='')}
        ids = lambda out: sorted(r['notice_id'] for r in out['results'])
        # 설립 5년 법인: 예비창업자 전용·3년 미만은 확실히 미달, 조건을 모르는 공고는 남긴다
        out, _ = self.run_match(rows, top=10, founded_at='2021-01-01')
        self.assertEqual(ids(out), ['no_field', 'pre_or7', 'under7'])
        self.assertEqual(out['filter']['excluded'], {'업력·신청자 유형': 2})
        # 예비창업자: 예비창업자를 받는 공고와 조건을 모르는 공고만
        out, _ = self.run_match(rows, top=10, applicant_type='예비창업자', founded_at='')
        self.assertEqual(ids(out), ['no_field', 'pre_only', 'pre_or7'])
        # 설립일을 모르는 사업자: 게이트와 같이 업력 판정 불가 → 아무것도 빼지 않는다(4번 검토의 원칙)
        out, _ = self.run_match(rows, top=10, founded_at='')
        self.assertEqual(ids(out), ['no_field', 'pre_only', 'pre_or7', 'under3', 'under7'])

    def test_region_is_not_a_filter(self):
        # 지역·업종은 순위에만 쓴다(기획서 4-2·5-3). 다른 시·도 공고도 후보에 남고 뒤로만 간다
        rows = {'서울': notice('서울 창업지원', region='서울'), '경기': notice('경기 창업지원', region='경기')}
        out = match(rows, region='경기', top=3)
        self.assertEqual([r['notice_id'] for r in out['results']], ['경기', '서울'])
        self.assertEqual(out['filtered_count'], 2)

    def test_dense_falls_back_when_query_has_no_ids(self):
        # 평가용 가짜 색인(eval.query_ablation.NumpyCollection)·옛 Chroma 는 ids 인자를 모른다
        class NoIds(FakeCollection):
            def query(self, query_embeddings=None, n_results=10):
                return FakeCollection.query(self, query_embeddings, n_results)
        rows = self.rows()
        st = state(rows)
        st['collection'] = NoIds(list(rows))
        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원',
                               top=3, search='dense')
        with patch.dict(app.STATE, st, clear=True), \
                patch.object(app, '_encode', lambda text: [1.0, 0.0, 0.0, 0.0]):
            out = app.match(req)
        self.assertEqual(out['dense_path'], 'vectors')
        self.assertIsNone(out['dense_error'])            # 호환성 차이는 오류가 아니다
        self.assertEqual(out['count'], 3)
        self.assertTrue(all(r['notice_id'] >= 'n052' for r in out['results']))

    def test_no_candidates_skips_encoding(self):
        # Codex 검수 P2 — 필터 통과 0건이면 인코더를 부르지 않고 빈 결과(R-3 ②). 인코더가 고장 나도 오류가 아니다
        def broken(text):
            raise RuntimeError('인코더 고장')
        st = state(self.rows(expired=60))
        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원', top=3)
        with patch.dict(app.STATE, st, clear=True), patch.object(app, '_encode', broken):
            out = app.match(req)
        self.assertEqual((out['count'], out['filtered_count'], out['encode_ms']), (0, 0, 0.0))
        self.assertEqual(out['pipeline'], ['정형 필터'])
        self.assertEqual(st['collection'].asked, [])     # Chroma 도 부르지 않았다

    def test_other_chroma_errors_are_reported(self):
        # Codex 검수 P2 — 색인 장애는 버전 차이와 구분해 원인을 남긴다
        class Broken(FakeCollection):
            def query(self, query_embeddings=None, n_results=10, ids=None):
                raise RuntimeError('Error executing plan: Internal error')
        rows = self.rows()
        st = state(rows)
        st['collection'] = Broken(list(rows))
        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원',
                               top=3, search='dense')
        with patch.dict(app.STATE, st, clear=True), \
                patch.object(app, '_encode', lambda text: [1.0, 0.0, 0.0, 0.0]), \
                patch('sys.stderr'):
            out = app.match(req)
        self.assertEqual(out['dense_path'], 'vectors')
        self.assertIn('RuntimeError', out['dense_error'])
        self.assertEqual(out['count'], 3)

    def test_only_indexed_ids_go_to_chroma(self):
        # 실제 Chroma 는 색인에 없는 ID 를 넘기면 오류를 낸다(2026-09-28 확인)
        rows = self.rows(expired=0, total=5)
        st = state(rows)
        st['vector_ids'] = {'n001', 'n002'}
        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원',
                               top=5, search='dense')
        with patch.dict(app.STATE, st, clear=True), \
                patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]):
            out = app.match(req)
        self.assertEqual(sorted(st['collection'].asked[0]), ['n001', 'n002'])
        self.assertEqual(out['dense_path'], 'chroma')


class ScoreModeTests(unittest.TestCase):
    """2번 — score 방식이 RRF 점수와 코사인 유사도를 섞지 않는다."""

    def rows(self, total=60):
        return {('n%03d' % i): notice('n%03d' % i) for i in range(1, total + 1)}

    def zero_penalty(self):
        return {'mode': 'score', 'penalty_group': 0, 'penalty_region': 0, 'penalty_district': 0}

    def test_zero_penalty_keeps_the_order(self):
        rows = self.rows()
        base = match(rows, top=3, search='hybrid')
        scored = match(rows, top=3, search='hybrid', weights=self.zero_penalty())
        self.assertEqual([r['notice_id'] for r in scored['results']],
                         [r['notice_id'] for r in base['results']])

    def test_weighted_score_uses_rrf_in_hybrid(self):
        out = match(self.rows(), top=3, search='hybrid', weights=self.zero_penalty())
        top1 = out['results'][0]
        self.assertEqual(top1['weighted_score'], top1['rrf_score'])
        self.assertLess(top1['weighted_score'], 0.1)     # 코사인(0.5~0.8)이 아니다

    def test_penalty_actually_demotes(self):
        rows = self.rows(total=5)
        rows['n001'] = notice('n001', region='서울')      # 다른 시·도
        out = match(rows, top=3, region='경기', weights={'mode': 'score', 'penalty_region': 1.0})
        self.assertNotEqual(out['results'][0]['notice_id'], 'n001')


class SearchTimingTests(unittest.TestCase):
    """P3 — 화면에 찍히는 검색 시간이 실제 검색 구간을 담는다.

    시간은 눈으로 확인할 수 없어 **모의 시계**로 잰다. 각 단계에 정해진 시간을 부여하고
    돌려받은 search_ms 가 그 합을 담는지 본다(2026-09-18 Codex 검토의 재현 방식).
    """

    def test_search_ms_includes_vector_lookup(self):
        rows = {('n%03d' % i): notice('n%03d' % i) for i in range(1, 61)}

        clock = {'now': 0.0}
        COSTS = {'query': 0.010, 'bm25': 0.020, 'get': 0.250}

        def tick(kind):
            clock['now'] += COSTS[kind]

        collection = FakeCollection(list(rows))
        real_query, real_get = collection.query, collection.get
        collection.query = lambda **kw: (tick('query'), real_query(**kw))[1]
        collection.get = lambda **kw: (tick('get'), real_get(**kw))[1]

        # 의미 검색 상위 50 밖(n060)을 BM25 가 찾아야 벡터 추가 조회가 일어난다
        texts = {n: '지원' for n in rows}
        texts['n060'] = '창업 지원 창업 지원'
        bm25 = hybrid.BM25([(n, texts[n]) for n in rows])
        real_search = bm25.search
        bm25.search = lambda query, top=10, allowed=None: (tick('bm25'), real_search(query, top=top, allowed=allowed))[1]

        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01',
                               idea='창업 지원', top=3, search='hybrid')
        with patch.dict(app.STATE, {'collection': collection, 'rows': rows, 'bm25': bm25},
                        clear=True),                 patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]),                 patch.object(app.time, 'time', lambda: clock['now']):
            out = app.match(req)

        # query 10 + bm25 20 + get 250 = 280ms. 이전 구현은 30ms 만 보고했다
        self.assertAlmostEqual(out['search_ms'], 280.0, places=6)
        self.assertGreaterEqual(out['search_ms'], out['dense_ms'] + out['bm25_ms'])


class UnknownFoundedDateTests(unittest.TestCase):
    """4번 — 설립일 미상과 예비창업자(미설립)를 구분한다."""

    def judge(self, applicant_type, founded_at):
        rows = {'n001': notice('n001')}
        req = app.GateRequest(notice_id='n001', applicant_type=applicant_type,
                              founded_at=founded_at)
        with patch.dict(app.STATE, state(rows), clear=True):
            out = app.eligibility(req)
        return [c for c in out['checks'] if c['조건'] == '업력'][0]

    def test_business_without_founded_date_is_unknown_not_prestartup(self):
        age = self.judge('법인사업자', '')
        self.assertIsNone(age['판정'])              # 신청 불가(False)가 아니다
        self.assertEqual(age['내 값'], '설립일 미상')

    def test_broken_founded_date_is_also_unknown(self):
        self.assertIsNone(self.judge('법인사업자', '설립일')['판정'])

    def test_impossible_dates_are_unknown(self):
        # 형식은 맞지만 달력에 없는 날짜. 2026-09-18 Codex 재검토에서 지적된 경우다
        for value in ('2026-02-30', '20260230', '2026-13-01', '2025-02-29', '2026-00-10'):
            with self.subTest(value=value):
                age = self.judge('법인사업자', value)
                self.assertIsNone(age['판정'])
                self.assertEqual(age['내 값'], '설립일 미상')

    def test_parse_ymd_never_raises(self):
        for value in ('2026-02-30', '20260230', '2026-13-01', '2025-02-29', '설립일', '', None):
            with self.subTest(value=value):
                self.assertIsNone(gate.parse_ymd(value))
        self.assertIsNotNone(gate.parse_ymd('2025-01-01'))
        self.assertIsNotNone(gate.parse_ymd('20250101'))


    def test_prestartup_still_judged_against_prestartup_notices(self):
        age = self.judge('예비창업자', '')
        self.assertIs(age['판정'], False)            # '7년미만' 공고는 예비창업자 불가
        self.assertEqual(age['내 값'], '예비창업자 (미설립)')

    def test_business_with_founded_date_is_judged(self):
        age = self.judge('법인사업자', '2025-01-01')
        self.assertIs(age['판정'], True)

    def test_gate_sentinel_is_documented(self):
        self.assertEqual(gate.UNKNOWN_AGE, 'unknown')
        verdict, need, mine = gate._check_age('7년미만', gate.UNKNOWN_AGE)
        self.assertIsNone(verdict)
        self.assertIn('확인할 수 없음', need)
        self.assertEqual(mine, '설립일 미상')


class HttpErrorTests(unittest.TestCase):
    """잘못된 설립일이 들어와도 두 API 가 500 을 내지 않는다.

    단위 테스트만으로는 부족하다. 예외가 FastAPI 까지 올라가면 요청 전체가 실패하는데,
    그 사실은 응답 코드로만 드러난다(2026-09-18 Codex 재검토에서 이 경로로 발견됐다).
    """

    BAD_DATES = ('', '설립일', '2026-02-30', '20260230', '2026-13-01', '2025-02-29')

    def test_match_and_eligibility_never_return_500(self):
        from fastapi.testclient import TestClient
        rows = {'n001': notice('n001')}
        with patch.dict(app.STATE, state(rows), clear=True), \
                patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]):
            with TestClient(app.app, raise_server_exceptions=False) as client:
                for value in self.BAD_DATES:
                    for path, extra in (('/api/match', {'idea': '창업 지원', 'top': 3}),
                                        ('/api/eligibility', {'notice_id': 'n001'})):
                        with self.subTest(date=value, path=path):
                            r = client.post(path, json={'applicant_type': '법인사업자',
                                                        'founded_at': value, **extra})
                            self.assertEqual(r.status_code, 200)


if __name__ == '__main__':
    unittest.main()
