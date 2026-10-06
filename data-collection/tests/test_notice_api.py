# -*- coding: utf-8 -*-
"""조율 에이전트 창구 — 01 수집 상태·추천 결과 키 (2026-10-06, docs/notice_api/01_status_match). DB·모델 없음."""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from search import app as server  # noqa: E402
from search import collection_status, content_version, gate, notice_api  # noqa: E402
from test_match_rules import notice, state  # noqa: E402

NOW = datetime(2026, 10, 6, 3, 0, tzinfo=timezone.utc)


def content_row(**kw):
    row = {name: None for name in content_version.CONTENT_FIELDS}
    row.update({'title': '창업 지원 공고', 'body': '사업 개요', 'apply_start': date(2026, 10, 1),
                'apply_end': date(2026, 10, 31), 'apply_period_raw': '{"start": "2026-10-01", "end": "2026-10-31"}',
                'apply_period_type': 'fixed', 'recruitment_status': 'open'})
    row.update(kw)
    return row


class ContentVersionTests(unittest.TestCase):
    def test_same_content_same_version(self):
        a = content_version.compute(content_row(), ['b' * 64, 'a' * 64])
        b = content_version.compute(content_row(), ['a' * 64, 'b' * 64])      # 첨부 순서만 다르다
        self.assertEqual(a, b)
        self.assertTrue(a.startswith('cv2-'))
        self.assertEqual(len(a), len('cv2-') + 32)

    def test_collection_time_fields_do_not_change_version(self):
        # 수집 때마다 바뀌는 값은 넣지 않는다 — 넘겨도 지문이 같아야 한다
        base = content_version.compute(content_row())
        noisy = content_version.compute(content_row(snapshot_at=NOW, updated_at=NOW, last_import_id='x' * 32,
                                                    source_updated_at_raw='"2026-10-06"', raw='{"fetched": 1}'))
        self.assertEqual(base, noisy)

    def test_content_change_changes_version(self):
        base = content_version.compute(content_row())
        for change in ({'body': '사업 개요 수정'}, {'target_text': '예비창업자'}, {'apply_end': date(2026, 11, 30)},
                       {'age_condition_raw': '7년미만'}, {'recruitment_status': 'closed'}):
            self.assertNotEqual(base, content_version.compute(content_row(**change)), change)

    def test_attachment_file_change_changes_version_but_missing_hash_is_ignored(self):
        base = content_version.compute(content_row(), ['a' * 64])
        self.assertNotEqual(base, content_version.compute(content_row(), ['c' * 64]))
        self.assertEqual(base, content_version.compute(content_row(), ['a' * 64, None]))

    def test_date_and_json_forms_are_normalized(self):
        # DB 드라이버가 날짜를 date 로 주든 문자열로 주든, JSON 키 순서가 달라도 같은 값
        a = content_version.compute(content_row())
        b = content_version.compute(content_row(apply_start='2026-10-01', apply_end='2026-10-31',
                                                apply_period_raw='{"end": "2026-10-31", "start": "2026-10-01"}'))
        self.assertEqual(a, b)

    def test_load_joins_attachment_hashes_by_notice(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                self.sql = sql

            def fetchall(self):
                if 'content_sha256' in self.sql:
                    return [(1, b'a' * 64), (1, 'b' * 64)]          # bytes 로 와도 같게 읽는다
                cols = ('id', 'notice_id') + content_version.CONTENT_FIELDS
                return [tuple(dict(content_row(), id=1, notice_id='x:1').get(c) for c in cols),
                        tuple(dict(content_row(), id=2, notice_id='x:2').get(c) for c in cols)]

        class Conn:
            def cursor(self):
                return Cursor()
        out = content_version.load(Conn())
        self.assertEqual(out['x:1'], content_version.compute(content_row(), ['a' * 64, 'b' * 64]))
        self.assertEqual(out['x:2'], content_version.compute(content_row()))


    def test_compare_reports_which_field_changed(self):
        def snap(rows):
            return {'versions': {n: content_version.compute(r) for n, r in rows.items()},
                    'field_hashes': {n: {f: content_version._short(content_version._plain(f, r.get(f)))
                                         for f in content_version.CONTENT_FIELDS} for n, r in rows.items()}}
        old = snap({'a': content_row(), 'b': content_row(), 'gone': content_row()})
        new = snap({'a': content_row(), 'b': content_row(body='바뀐 개요'), 'new': content_row()})
        out = content_version.compare(old, new)
        self.assertEqual((out['common'], out['changed'], out['added'], out['removed']), (2, 1, 1, 1))
        self.assertEqual(out['by_field'], {'body': {'count': 1, 'examples': ['b']}})


class ServedStatusTests(unittest.TestCase):
    def checked(self, status='정상'):
        return {'status': status, 'reasons': [] if status == '정상' else ['DB 이유']}

    def test_fresh_server_data_keeps_db_status(self):
        self.assertEqual(notice_api.served_status(self.checked(), NOW - timedelta(hours=3), NOW), ('정상', []))

    def test_stale_server_data_downgrades_normal_to_delayed(self):
        status, reasons = notice_api.served_status(self.checked(), NOW - timedelta(hours=30), NOW)
        self.assertEqual(status, '지연')
        self.assertIn('30.0시간', reasons[-1])
        self.assertIn('다시 켜야', reasons[-1])

    def test_failure_stays_failure(self):
        status, reasons = notice_api.served_status(self.checked('실패'), NOW - timedelta(hours=30), NOW)
        self.assertEqual(status, '실패')
        self.assertEqual(reasons[0], 'DB 이유')

    def test_unknown_loaded_time_is_not_normal(self):
        # 서버 공고의 저장 시각을 모르면 새것인지 확인할 수 없다 — '정상'으로 두지 않는다(2026-10-06 Codex 검수 P2-8)
        status, reasons = notice_api.served_status(self.checked(), None, NOW)
        self.assertEqual(status, '지연')
        self.assertIn('모른다', reasons[-1])
        self.assertEqual(notice_api.served_status(self.checked('실패'), None, NOW)[0], '실패')


class CollectionStatusRouteTests(unittest.TestCase):
    def client(self, state, connect):
        app = FastAPI()
        app.include_router(notice_api.build_router(state, connect))
        return TestClient(app)

    def test_returns_one_of_three_statuses(self):
        class Conn:
            def close(self):
                pass
        fake = {'status': '정상', 'reasons': [], 'last_run_at': '2026-10-06T00:05:00+00:00',
                'checked_at': NOW.isoformat()}
        with patch.object(collection_status, 'check', lambda connection=None, now=None: fake):
            res = self.client({'loaded_store_at': datetime.now(timezone.utc) - timedelta(hours=1)}, Conn).get(
                '/api/collection_status')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body['status'], '정상')
        self.assertIn(body['status'], ('정상', '지연', '실패'))
        self.assertEqual(body['db_status'], '정상')

    def test_stale_server_snapshot_is_delayed(self):
        class Conn:
            def close(self):
                pass
        fake = {'status': '정상', 'reasons': []}
        with patch.object(collection_status, 'check', lambda connection=None, now=None: fake):
            body = self.client({'loaded_store_at': datetime.now(timezone.utc) - timedelta(days=3)}, Conn).get(
                '/api/collection_status').json()
        self.assertEqual((body['status'], body['db_status']), ('지연', '정상'))

    def test_db_failure_is_503_not_a_made_up_status(self):
        def broken():
            raise OSError('connection refused to secret-host:3306')
        res = self.client({}, broken).get('/api/collection_status')
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()['code'], 'COLLECTION_STATUS_UNAVAILABLE')
        self.assertNotIn('secret-host', res.text)                      # 주소·원문 오류를 응답에 싣지 않는다

    def test_route_is_mounted_on_service_app(self):
        # 실제 서비스 앱에 붙어 있고, app._connect 를 바꿔 끼우면 그 연결을 쓴다
        # (FastAPI 0.141 은 포함한 라우터를 routes 목록에 경로 없이 넣어서 목록 대신 직접 부른다)
        class Conn:
            def close(self):
                pass
        with patch.object(server, '_connect', Conn), patch.dict(server.STATE, {'loaded_store_at': None}), \
                patch.object(collection_status, 'check', lambda connection=None, now=None: {'status': '실패', 'reasons': []}):
            res = TestClient(server.app).get('/api/collection_status')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], '실패')


class MatchResultKeysTests(unittest.TestCase):
    def test_results_carry_content_version_and_empty_bonus(self):
        rows = {'n01': notice('n01'), 'n02': notice('n02')}
        out = match_with_versions(rows, {'n01': 'cv1-abc'})
        by_id = {r['notice_id']: r for r in out['results']}
        self.assertEqual(by_id['n01']['content_version'], 'cv1-abc')
        self.assertIsNone(by_id['n02']['content_version'])             # 지문이 없는 공고는 null
        for r in out['results']:
            self.assertIsNone(r['bonus_score'])                        # 계산하지 못함 = null · [] (03 전까지)
            self.assertEqual(r['bonus_items'], [])


class MatchBonusTests(unittest.TestCase):
    def test_bonus_filled_per_applicant(self):
        # 03 — 신청자 정보(성별·인증)로 공고 가점을 계산해 결과에 싣는다. 0 과 null 을 구분한다
        rows = {'n01': notice('n01'), 'n02': notice('n02'), 'n03': notice('n03')}
        bonus_table = {
            'n01': {'status': 'found', 'max_total_points': None, 'bonus_info': '여성기업 가점 2점',
                    'items': [{'kind': '여성', 'points': 2, 'name': '여성기업', 'certs': ['여성기업'], 'regions': [],
                               'detail': None, 'quote': '여성기업 가점 2점'}]},
            'n02': {'status': 'no_mention', 'max_total_points': None, 'bonus_info': None, 'items': []},
        }
        out = match_with_versions(rows, {}, bonus_table, gender='여성', certifications=['여성기업'])
        by_id = {r['notice_id']: r for r in out['results']}
        self.assertEqual((by_id['n01']['bonus_score'], by_id['n01']['bonus_items']),
                         (2.0, [{'name': '여성기업', 'points': 2.0}]))
        self.assertEqual((by_id['n02']['bonus_score'], by_id['n02']['bonus_items']), (0, []))     # 가점 없음
        self.assertEqual((by_id['n03']['bonus_score'], by_id['n03']['bonus_items']), (None, []))  # 읽지 못한 공고

    def test_bonus_weight_reorders_only_within_rule_tier(self):
        # 3-4 — 세기 0 이면 순서 그대로, 세기를 주면 같은 묶음 안에서만 올라온다(다른 지역 전용은 그대로 뒤)
        female10 = {'status': 'found', 'max_total_points': None, 'bonus_info': 'x',
                    'items': [{'kind': '여성', 'points': 10, 'name': '여성 대표자', 'certs': [], 'regions': [],
                               'detail': None, 'quote': 'x'}]}
        rows = {'n01': notice('n01'), 'n02': notice('n02'), 'n03': notice('n03'), 'n04': notice('n04', region='부산')}
        table = {'n03': female10, 'n04': female10}

        def order(weight):
            out = match_with_versions(rows, {}, table, gender='여성', region='서울',
                                      weights=server.Weights(bonus=weight))
            return [r['notice_id'] for r in out['results']]
        self.assertEqual(order(0.0), ['n01', 'n02', 'n03', 'n04'])
        self.assertEqual(order(0.2), ['n03', 'n01', 'n02', 'n04'])         # n04 는 다른 시·도 전용이라 맨 뒤 그대로
        # 가산점이 아무 데도 없으면 세기를 줘도 순서가 같다
        self.assertEqual([r['notice_id'] for r in match_with_versions(rows, {}, {}, gender='여성', region='서울',
                                                                      weights=server.Weights(bonus=0.2))['results']],
                         ['n01', 'n02', 'n03', 'n04'])

    def test_detail_bonus_info_only_when_found(self):
        st = {'rows': {'b:1': notice('b:1'), 'b:2': notice('b:2')}, 'amounts': {}, 'applicant_types': {},
              'bonus': {'b:1': {'status': 'found', 'bonus_info': '여성기업 가점 2점', 'items': []},
                        'b:2': {'status': 'none', 'bonus_info': None, 'items': []}}}
        app = FastAPI()
        app.include_router(notice_api.build_router(st, lambda: None))
        c = TestClient(app)
        self.assertEqual(c.get('/api/notices/b%3A1').json()['bonus_info'], '여성기업 가점 2점')
        self.assertIsNone(c.get('/api/notices/b%3A2').json()['bonus_info'])


def match_with_versions(rows, versions, bonus_table=None, **kw):
    """test_match_rules.match 와 같지만 STATE 에 공고 내용 지문·가점을 함께 넣는다."""
    st = state(rows)
    st['content_versions'] = versions
    st['bonus'] = bonus_table or {}
    req = server.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원', search='dense', **kw)
    with patch.dict(server.STATE, st, clear=True), patch.object(server, '_encode', lambda text: [0.0] * 4):
        return server.match(req)


# ── 02 공고 상세 · 자격 판정 ─────────────────────────────────
def cell(status, strength=None, evidence=None):
    return {'status': status, 'strength': strength, 'evidence': evidence}


def type_info(pre, varies=False):
    return {'varies': varies, 'pre_founder': cell(*pre), 'sole_proprietor': cell('not_mentioned'),
            'corporation': cell('not_mentioned'), 'registered_only': None}


TYPES = {'active': True, 'source': 'test', 'notices': {
    'k:불가': type_info(('not_allowed', 'strong', '사업자등록증 보유')),
    'k:가능': type_info(('allowed', 'strong', '예비창업자 신청 가능')),
    'k:세부': type_info(('allowed', 'strong', '일부 과제 예비창업자'), varies=True),
    'k:추정': type_info(('implied_no', 'strong', '도내 제조기업')),
}}


def rows_for_02():
    return {
        'k:1': notice('k:1', age_condition_raw='7년미만', source='kstartup', organizer='창업진흥원',
                      apply_start=date(2026, 10, 1), apply_end=date(2026, 10, 31), category='사업화'),
        'k:예비전용': notice('k:예비전용', age_condition_raw='예비창업자'),
        'k:예비3년': notice('k:예비3년', age_condition_raw='예비창업자,3년미만'),
        'b:빈칸': notice('b:빈칸', age_condition_raw='', source='bizinfo', organizer='', supervising_org='중기부',
                       apply_end=None, recruitment_status='weird'),
        'k:마감': notice('k:마감', age_condition_raw='', apply_end='2000-01-31', recruitment_status='closed'),
        'k:불가': notice('k:불가', age_condition_raw=''),
        'k:가능': notice('k:가능', age_condition_raw='7년미만'),
        'k:세부': notice('k:세부', age_condition_raw='예비창업자,5년미만'),
        'k:추정': notice('k:추정', age_condition_raw=''),
        'a/b:슬래시': notice('a/b:슬래시', age_condition_raw=''),
    }


class NoticeRoutesTests(unittest.TestCase):
    def client(self, rows=None, amounts=None, types=TYPES):
        st = {'rows': rows or rows_for_02(), 'amounts': amounts or {}, 'applicant_types': types}
        app = FastAPI()
        app.include_router(notice_api.build_router(st, lambda: None))
        return TestClient(app)

    # 공고 상세
    def test_detail_has_every_promised_key(self):
        body = self.client(amounts={'k:1': {'won': 100000000, 'quote': '최대 1억원'}}).get(
            '/api/notices/k%3A1').json()                                   # 퍼센트 인코딩을 풀어 찾는다
        for key in ('notice_id', 'title', 'organizer', 'supervising_org', 'executing_org', 'source', 'url',
                    'apply_url', 'category', 'apply_start', 'apply_end', 'recruitment_status',
                    'support_amount_max_won', 'support_amount_text', 'eligibility'):
            self.assertIn(key, body)
        for key in ('applicant_types', 'business_age_max_months', 'parsed'):
            self.assertIn(key, body['eligibility'])
        self.assertEqual(body['notice_id'], 'k:1')
        self.assertEqual((body['apply_start'], body['apply_end']), ('2026-10-01', '2026-10-31'))
        self.assertEqual(body['support_amount_max_won'], 100000000)
        self.assertIsNone(body['support_amount_text'])
        self.assertEqual(body['eligibility'], {'applicant_types': ['개인사업자', '법인'],   # 7년미만 — 예비창업자 불가
                                               'business_age_max_months': 84, 'parsed': True})

    def test_detail_unknown_values_are_null_not_made_up(self):
        body = self.client(amounts={'b:빈칸': {'won': 0, 'quote': 'x'}}).get(
            '/api/notices/b%3A%EB%B9%88%EC%B9%B8').json()
        self.assertIsNone(body['organizer'])                               # 빈 문자열 → null
        self.assertEqual(body['supervising_org'], '중기부')
        self.assertIsNone(body['apply_end'])
        self.assertEqual(body['recruitment_status'], 'unknown')            # 약속 밖 값 → unknown
        self.assertIsNone(body['support_amount_max_won'])                  # 0 을 '정보 없음'으로 쓰지 않는다
        self.assertEqual(body['eligibility'], {'applicant_types': ['예비창업자', '개인사업자', '법인'],
                                               'business_age_max_months': None, 'parsed': False})

    def test_detail_applicant_types_follow_judgment(self):
        c = self.client()

        def types(nid):
            return c.get('/api/notices/' + nid.replace(':', '%3A')).json()['eligibility']['applicant_types']
        self.assertEqual(types('k:예비전용'), ['예비창업자'])                 # 사업자 신청 불가
        self.assertEqual(types('k:예비3년'), ['예비창업자', '개인사업자', '법인'])
        self.assertEqual(types('k:불가'), ['개인사업자', '법인'])             # 본문 '불가'(강한 근거)
        self.assertEqual(types('k:가능'), ['예비창업자', '개인사업자', '법인'])  # 본문 '가능'이 업력 칸을 덮는다
        self.assertEqual(types('k:추정'), ['예비창업자', '개인사업자', '법인'])  # 추정은 빼지 않는다

    def test_slash_in_id_and_not_found(self):
        c = self.client()
        self.assertEqual(c.get('/api/notices/a%2Fb%3A%EC%8A%AC%EB%9E%98%EC%8B%9C').json()['notice_id'], 'a/b:슬래시')
        for res in (c.get('/api/notices/nope%3A1'),
                    c.post('/api/notices/nope%3A1/eligibility',
                           json={'applicant_type': '법인', 'founded_at': '2020-01-01', 'today': '2026-10-06'})):
            self.assertEqual(res.status_code, 404)
            self.assertEqual(res.json(), {'code': 'NOTICE_NOT_FOUND'})      # 본문 최상위에 code

    # 자격 판정
    def ask(self, nid, applicant_type, founded_at='', today='2026-10-06', client=None):
        res = (client or self.client()).post('/api/notices/%s/eligibility' % nid.replace(':', '%3A'),
                                             json={'applicant_type': applicant_type, 'founded_at': founded_at,
                                                   'today': today})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_business_age_uses_today_from_request(self):
        ok = self.ask('k:1', '법인', '2019-01-01', today='2025-12-31')        # 83개월 < 84
        self.assertEqual((ok['passed'], ok['failed_conditions'], ok['business_age_months']), (True, [], 83))
        no = self.ask('k:1', '법인', '2019-01-01', today='2026-01-01')        # 84개월 — 7년 미만 아님
        self.assertEqual((no['passed'], no['failed_conditions'], no['business_age_months']), (False, ['업력'], 84))
        self.assertEqual(no['unknown_conditions'], ['지원대상 유형'])          # 개인·법인은 자동 판정하지 않는다

    def test_period_and_status_are_not_judged(self):
        out = self.ask('k:마감', '개인사업자', '2024-03-02')                  # 접수 마감 · 모집 마감 공고
        self.assertTrue(out['passed'])
        self.assertEqual(set(out['failed_conditions'] + out['unknown_conditions']) - {'지원대상 유형', '업력'}, set())

    def test_pre_founder_cases(self):
        self.assertEqual(self.ask('k:1', '예비창업자')['failed_conditions'], ['업력'])
        self.assertEqual(self.ask('k:불가', '예비창업자')['failed_conditions'], ['지원대상 유형'])
        allowed = self.ask('k:가능', '예비창업자')
        self.assertEqual((allowed['passed'], allowed['failed_conditions'], allowed['unknown_conditions']),
                         (True, [], []))
        partial = self.ask('k:세부', '예비창업자')
        self.assertEqual((partial['passed'], sorted(partial['unknown_conditions'])), (True, ['업력', '지원대상 유형']))
        blank = self.ask('b:빈칸', '예비창업자')
        self.assertEqual((blank['passed'], blank['business_age_months']), (True, None))
        self.assertEqual(sorted(blank['unknown_conditions']), ['업력', '지원대상 유형'])

    def test_business_without_founded_date_is_unknown_not_failed(self):
        out = self.ask('k:1', '개인사업자', '')
        self.assertEqual((out['passed'], out['business_age_months']), (True, None))
        self.assertIn('업력', out['unknown_conditions'])

    def test_bad_request_is_422(self):
        c = self.client()
        for body in ({'applicant_type': '법인사업자', 'founded_at': '', 'today': '2026-10-06'},
                     {'applicant_type': '법인', 'founded_at': '', 'today': '20261006'},
                     {'applicant_type': '법인', 'founded_at': '2026-02-30', 'today': '2026-10-06'},
                     {'applicant_type': '법인', 'founded_at': ''}):
            self.assertEqual(c.post('/api/notices/k%3A1/eligibility', json=body).status_code, 422, body)

    def test_inactive_types_table_is_not_used(self):
        # 추천의 정형 필터처럼 판정표가 꺼져 있으면 본문 유형을 쓰지 않는다
        out = self.ask('k:불가', '예비창업자', client=self.client(types=dict(TYPES, active=False)))
        self.assertTrue(out['passed'])

    def test_same_rule_as_match_prefilter(self):
        # 요청서 2.5 — 정형 필터(접수기간·모집 상태 제외)와 결론이 같아야 한다. 공고 × 신청자 전부 대조
        rows = rows_for_02()
        c = self.client(rows=rows)
        cases = [('예비창업자', ''), ('개인사업자', '2024-03-02'), ('법인', '2016-01-01'),
                 ('개인사업자', '2026-09-01'), ('법인', '')]
        for nid, row in rows.items():
            for applicant_type, founded in cases:
                age = gate.applicant_age(applicant_type, founded, date(2026, 10, 6))
                keep, _why, _ = server.eligible_with_types(
                    nid, row, age, date(2026, 10, 6), check_deadline=False,
                    types_table=TYPES if applicant_type == '예비창업자' else None)
                out = self.ask(nid, applicant_type, founded, client=c)
                self.assertEqual(out['passed'], keep, (nid, applicant_type, founded))


if __name__ == '__main__':
    unittest.main()
