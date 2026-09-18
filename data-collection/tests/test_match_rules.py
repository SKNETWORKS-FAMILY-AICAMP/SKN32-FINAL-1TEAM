# -*- coding: utf-8 -*-
"""규칙이 결합될 때의 순서와 자격 판정 — Codex 검토(2026-09-18) 회귀 테스트.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_match_rules -v

DB·모델·HTTP 없이 `app.match()` 와 `app.eligibility()` 를 가짜 색인으로 직접 부른다.
검토 문서: docs/MATCHING_REVIEW_20260918.md

여기서 고정하는 것
  1번  시·도 → 시·군·구 → 집단 순서. 나중 규칙이 앞선 규칙을 덮어쓰지 않는다
  4번  설립일을 모르는 사업자를 예비창업자(미설립)로 보지 않는다
  날짜 잘못된 설립일이 HTTP 500 이 되지 않는다 (형식 오류 + 달력에 없는 날짜)
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

    def count(self):
        return len(self.ids)

    def query(self, query_embeddings=None, n_results=10):
        ids = self.ids[:n_results]
        return {'ids': [ids], 'distances': [[0.20 + i * 0.005 for i in range(len(ids))]]}

    def get(self, ids=None, include=None):
        ids = list(ids or [])
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
