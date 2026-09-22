# -*- coding: utf-8 -*-
"""검증 화면 테스트 — `docs/CLAUDE_UI_VERIFICATION_TASK_20260921.md` 5절.

  .\\.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -k test_verify_ui -v

**실제 DB·모델을 부르지 않는다.** fixture 와 저장된 결과 파일만 읽는다.
여기 통과했다고 실제 데이터가 맞다는 뜻은 아니다. 화면이 상태를 정직하게 보여 주는지만 본다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import unittest

from fastapi.testclient import TestClient

from experiments.sql_semantic import fixtures, viewer

client = TestClient(viewer.app)


class FixtureTests(unittest.TestCase):
    """fixture 가 사람이 봐야 할 상태를 실제로 만들어 내는지."""

    @classmethod
    def setUpClass(cls):
        cls.data = fixtures.fixture_run()

    def counts(self, case_id, mode):
        for row in self.data['responses']:
            if row['case_id'] == case_id and row['mode'] == mode:
                return row['response']['counts']
        self.fail('없는 사례: %s %s' % (case_id, mode))

    def test_same_every_time(self):
        """새로고침해도 같은 화면이어야 한다.

        **소요 시간(`timing_ms`)은 빼고 비교한다.** 같은 fixture 라도 0.0ms 냐 1.0ms 냐는
        실행할 때마다 달라진다. 이것까지 비교하면 돌릴 때마다 통과·실패가 갈린다
        (2026-09-21 Codex 리뷰 1번). 시간을 뺀 나머지는 전부 같아야 한다 —
        결과 ID·순위·유사도·조건 판정·탈락 사유·벡터 상태를 그대로 비교한다.
        """
        again = fixtures.fixture_run()

        def without_timing(rows):
            return [dict(row, response={k: v for k, v in row['response'].items()
                                        if k != 'timing_ms'})
                    for row in rows]

        self.assertEqual(
            json.dumps(without_timing(self.data['responses']), ensure_ascii=False,
                       sort_keys=True, default=str),
            json.dumps(without_timing(again['responses']), ensure_ascii=False,
                       sort_keys=True, default=str))

    def test_timing_is_reported_but_not_compared(self):
        """시간을 비교에서 뺐다고 화면에서 없애지는 않는다."""
        for row in self.data['responses']:
            self.assertIn('total', row['response']['timing_ms'])

    def test_vector_problems_are_visible(self):
        counts = self.counts('fx-case01', 'filter_on')
        self.assertEqual(counts['missing_vector'], 1)
        self.assertEqual(counts['broken_vector'], 1)
        self.assertEqual(counts['stale_vector'], 2)      # 내용 변경 1 + 다른 모델 리비전 1 (F2)

    def test_other_model_revision_is_stale_on_screen(self):
        """F2: 같은 모델 이름이라도 리비전이 다르면 비교하지 않고 사유를 보인다."""
        for row in self.data['responses']:
            if row['case_id'] == 'fx-case01' and row['mode'] == 'filter_on':
                reasons = {x['notice_id']: x['reason']
                           for x in row['response']['stale_vector_examples']}
                self.assertIn('다른 모델 리비전', reasons['fx-007'])
                ids = [r['notice_id'] for r in row['response']['results']]
                self.assertNotIn('fx-007', ids)
                self.assertEqual(row['response']['encoder']['model_revision'],
                                 fixtures.FIXTURE_REVISION)

    def test_broken_vector_does_not_kill_the_result(self):
        """한 건이 깨져도 정상 후보는 계속 나온다."""
        self.assertGreaterEqual(self.counts('fx-case01', 'filter_on')['returned'], 1)

    def test_condition_drop_is_counted(self):
        self.assertGreaterEqual(self.counts('fx-case01', 'filter_on')['dropped'], 1)

    def test_missing_applicant_info_keeps_candidates(self):
        """신청자 정보가 없다고 후보를 떨어뜨리지 않는다."""
        counts = self.counts('fx-case02', 'filter_on')
        self.assertEqual(counts['dropped'], 0)
        self.assertGreaterEqual(counts['returned'], 1)

    def test_zero_candidate_case_exists(self):
        self.assertEqual(self.counts('fx-case03', 'filter_on')['returned'], 0)

    def test_f1_counterexamples_pass_after_the_fix(self):
        """F1 수정 뒤에는 반례 네 건이 모두 '기대대로' 여야 한다 (2026-09-21).

        검사를 지우지 않고 남겨 둔다. 같은 오해석이 다시 들어오면 여기서 먼저 깨진다.
        """
        cases = {c['id']: c for c in self.data['condition_cases']}
        self.assertTrue(cases['fx-size-nolimit']['passed'])
        self.assertTrue(cases['fx-industry-exclude']['passed'])
        self.assertEqual(cases['fx-size-nolimit']['result'], '기대대로')
        self.assertTrue(all(c['passed'] for c in self.data['condition_cases']))

    def test_purpose_and_missing_age_stay_unknown(self):
        cases = {c['id']: c for c in self.data['condition_cases']}
        self.assertTrue(cases['fx-purpose-not-industry']['passed'])
        self.assertTrue(cases['fx-age-unknown']['passed'])


class RouteTests(unittest.TestCase):
    """라우트가 응답하는지, 화면 문구가 들어 있는지."""

    def test_index_html_has_four_sections(self):
        r = client.get('/')
        self.assertEqual(r.status_code, 200)
        for text in ('A. 실행·데이터 상태', 'B. 정형 조건 판정',
                     'C. 검색 결과', 'D. 벡터 검증'):
            self.assertIn(text, r.text)

    def test_health(self):
        body = client.get('/api/health').json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['read_only'])

    def test_runs_list_contains_fixture_and_issues(self):
        body = client.get('/api/runs').json()
        self.assertIn(viewer.FIXTURE_ID, [r['run_id'] for r in body['runs']])
        ids = [i['id'] for i in body['issues']]
        for key in ('F1', 'F2', 'F3', 'CHROMA', 'HUMAN'):
            self.assertIn(key, ids)

    def test_solved_only_after_codex_approval(self):
        """F1~F3 는 Codex 승인 뒤에만 '해결'이다. 검증하지 않은 두 항목은 그대로 둔다."""
        body = client.get('/api/runs').json()
        states = {i['id']: i['state'] for i in body['issues']}
        for key in ('F1', 'F2', 'F3'):
            self.assertIn('Codex 승인', states[key])
        self.assertIn('통과', states['CHROMA'])        # 재동기화 뒤 재검사로 확인한 뒤에만 통과
        self.assertIn('Codex 승인', states['CHROMA'])
        self.assertEqual(states['HUMAN'], '없음')

    def test_d_section_no_longer_says_revision_unchecked(self):
        html = client.get('/').text
        self.assertNotIn('검사하지 않는다 (F2 미해결)', html)
        self.assertIn('F2 해결', html)

    def test_f1_state_says_fixed_with_its_limit(self):
        body = client.get('/api/runs').json()
        f1 = next(i for i in body['issues'] if i['id'] == 'F1')
        self.assertIn('Codex 승인', f1['state'])      # 재검토 통과 후에만 해결로 적는다
        self.assertIn('sql_lab_v1', f1['detail'])     # 옛 결과가 무엇인지 밝힌다
        self.assertIn('입력이 없어', f1['detail'])    # 결과가 같았던 이유를 숨기지 않는다

    def test_run_labels_show_extractor_version(self):
        body = client.get('/api/runs').json()
        for run in body['runs']:
            if not run['is_fixture']:
                self.assertIn('추출기', run['label'])

    def test_fixture_run_is_labelled(self):
        body = client.get('/api/run/fixture').json()
        self.assertTrue(body['is_fixture'])
        self.assertIn('실제 검색 결과 아님', body['banner'])

    def test_fixture_case_detail_has_both_modes(self):
        body = client.get('/api/run/fixture/case/fx-case01').json()
        self.assertTrue(body['filter_on']['use_filter'])
        self.assertFalse(body['filter_off']['use_filter'])
        self.assertTrue(body['side_by_side'])
        self.assertIn('rows_from_sql', body['drops']['filter_on'])
        self.assertIn('sql_dropped', body['drops']['filter_on'])

    def test_zero_candidate_case_renders(self):
        body = client.get('/api/run/fixture/case/fx-case03').json()
        self.assertEqual(body['filter_on']['results'], [])
        self.assertEqual(body['side_by_side'][0]['where'], '필터 끔 전용')

    def test_condition_cases_route_reports_nothing_reproduced(self):
        body = client.get('/api/conditions/cases').json()
        self.assertEqual(body['reproduced'], [])      # F1 수정 후
        self.assertIn('실제 검색 결과 아님', body['banner'])

    def test_unknown_run_and_case_are_404_not_crash(self):
        self.assertEqual(client.get('/api/run/없는실행').status_code, 404)
        self.assertEqual(client.get('/api/run/fixture/case/없는사례').status_code, 404)

    def test_evidence_without_db_explains_instead_of_failing(self):
        from experiments.sql_semantic import config

        def boom():
            raise config.LabConfigError('실험 DB 설정이 없다: SQL_LAB_HOST')

        original = config.lab_settings
        config.lab_settings = boom
        try:
            body = client.get('/api/evidence/fx-001').json()
        finally:
            config.lab_settings = original
        self.assertFalse(body['available'])
        self.assertIn('근거를 읽지 못했다', body['reason'])


# /compare 에 넣는 **명백한 가짜** 입력 (2026-09-21 입력 확장). 실제 개인정보를 쓰지 않는다
VALID = {
    'applicant_type': '법인', 'owner_name': '테스트대표', 'birth_date': '1980-01-01',
    'gender': '응답 안 함', 'region': '경기', 'district': '수원시', 'main_industry': '제조업',
    'business_no': '0000000000', 'founded_at': '2021-04-01', 'owner_career': '금형 설계 12년',
    'revenue': [{'item': '검사 장비 판매', 'price': '12000000'}],
    'idea': '금형 불량 검출 AI', 'top': 5,
}


def valid(**overrides):
    body = json.loads(json.dumps(VALID))
    body.update(overrides)
    return body


class CompareTests(unittest.TestCase):
    """직접 검색 비교(/compare). 기존 서비스·실험 DB·모델은 가짜로 바꾼다."""

    def service(self, ids):
        return {'query': 'q', 'search_ms': 1.0,
                'results': [{'notice_id': i, 'title': i, 'url': '', 'score': 0.5, 'band': '참고',
                             'region': '전국', 'apply_end': '', 'dense_rank': 1, 'bm25_rank': 1}
                            for i in ids]}

    def lab(self, ids):
        return {'query_text': 'q', 'as_of_date': '2026-09-21', 'counts': {'rows_from_sql': 3},
                'timing_ms': {}, 'encoder': {'model_revision': 'r'},
                'results': [{'notice_id': i, 'title': i, 'url': '', 'rank': k, 'similarity': 0.5,
                             'region': '전국', 'apply_end': '', 'rank_reason': '유사도 순',
                             'conditions': {'region': {'verdict': 'ok', 'why': '전국'}},
                             'needs_check': []} for k, i in enumerate(ids, 1)]}

    def post(self, body, hybrid, dense, lab, lab_ids={'a', 'b', 'z'}):
        from unittest.mock import patch
        calls = {}

        def fake_service(payload, mode, timeout=120):
            calls.setdefault('service', []).append((payload, mode))
            return hybrid if mode == 'hybrid' else dense

        def fake_lab(applicant, top):
            calls['lab'] = (applicant, top)
            if isinstance(lab, Exception):
                raise lab
            return lab

        with patch.object(viewer, 'call_service', fake_service), \
                patch.object(viewer, 'run_lab', fake_lab), \
                patch.object(viewer, 'lab_notice_ids', lambda: lab_ids):
            return client.post('/api/compare', json=body), calls

    def test_page_renders(self):
        r = client.get('/compare')
        self.assertEqual(r.status_code, 200)
        self.assertIn('기존 방식과 새 방식 비교', r.text)
        self.assertIn('보는 공고가 다릅니다', r.text)      # 비교 한계를 화면에 적는다

    def test_idea_is_required(self):
        r, calls = self.post(valid(idea='  '), {}, {}, {})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(calls, {})

    def test_three_columns_and_overlap(self):
        r, calls = self.post(valid(applicant_type='예비창업자', top=3),
                             self.service(['a', 'b', 'c']), self.service(['a', 'c', 'd']),
                             self.lab(['a', 'z']))
        body = r.json()
        self.assertEqual([m for _p, m in calls['service']], ['hybrid', 'dense'])
        self.assertTrue(calls['lab'][0]['prestartup'])            # 예비창업자 → 새 방식에도 전달
        self.assertEqual(calls['lab'][1], 3)
        self.assertEqual(body['in_all_three'], ['a'])
        hybrid = {row['notice_id']: row for row in body['columns']['hybrid']}
        self.assertEqual(hybrid['c']['in_lab_data'], False)       # 새 방식 데이터에 없는 공고
        self.assertEqual(sorted(hybrid['a']['also_in']), ['dense', 'hybrid', 'lab'])
        self.assertIn('conditions', body['columns']['lab'][0])

    def test_service_down_is_shown_not_crashed(self):
        down = {'error': '기존 서비스에 연결하지 못했다'}
        r, _ = self.post(valid(), down, down, self.lab(['a']))
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertIn('hybrid', body['errors'])
        self.assertEqual(body['columns']['hybrid'], [])
        self.assertEqual(len(body['columns']['lab']), 1)

    def test_lab_failure_is_shown_not_crashed(self):
        r, _ = self.post(valid(), self.service(['a']), self.service(['a']),
                         RuntimeError('실험 DB 연결 실패'))
        body = r.json()
        self.assertIn('lab', body['errors'])
        self.assertEqual(body['columns']['lab'], [])

    def test_top_is_clamped(self):
        _r, calls = self.post(valid(top=999), self.service([]), self.service([]),
                              self.lab([]))
        self.assertEqual(calls['lab'][1], 10)

    def test_verify_page_links_to_compare(self):
        self.assertIn('/compare', client.get('/').text)

    # ---- 2026-09-21 Codex /compare 리뷰

    def test_overlap_is_scoped_to_top_n(self):
        """P2: Top 5 에서 '이 방식에만' 이던 공고가 Top 10 에서는 다른 방식에도 나온다.

        그래서 겹침은 전체 검색 공간이 아니라 Top N 목록 기준이라고 응답·화면에 적는다.
        """
        top5, _ = self.post(valid(top=5), self.service(['a', 'x']),
                            self.service(['a', 'b']), self.lab(['a']))
        top10, _ = self.post(valid(top=10), self.service(['a', 'x']),
                             self.service(['a', 'b', 'x']), self.lab(['a']))
        row5 = {r['notice_id']: r for r in top5.json()['columns']['hybrid']}['x']
        row10 = {r['notice_id']: r for r in top10.json()['columns']['hybrid']}['x']
        self.assertEqual(row5['also_in'], ['hybrid'])              # Top 5 목록 안에서는 혼자
        self.assertIn('dense', row10['also_in'])                   # Top 10 에서는 겹친다
        self.assertIn('Top 5', top5.json()['overlap_scope'])
        self.assertIn('Top 10', top10.json()['overlap_scope'])
        self.assertEqual(top5.json()['top'], 5)

    def test_page_never_claims_exclusivity_without_top_n(self):
        html = client.get('/compare').text
        self.assertNotIn('이 방식에만', html)                     # 범위 없는 '독점' 문구
        self.assertIn("이 방식 ' + N + '에만", html)              # 'Top N' 이 붙은 문구
        self.assertIn("세 방식 ' + N + ' 공통", html)
        self.assertIn('Top N 목록 안에서만', html)

    def test_lab_ids_are_read_fresh_every_request(self):
        """P2: 서버를 켠 채 실험 DB 를 재적재하면 두 번째 요청은 새 목록을 써야 한다."""
        from unittest.mock import patch
        from experiments.sql_semantic import config
        sets = [[('a',), ('b',)], [('a',), ('b',), ('c',)]]

        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def execute(self, sql, params=None):
                pass

            def fetchall(self):
                return self.rows

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class Conn:
            def __init__(self, rows):
                self.rows = rows

            def cursor(self):
                return Cursor(self.rows)

            def close(self):
                pass

        calls = {'n': 0}

        def fake_connect():
            rows = sets[min(calls['n'], 1)]
            calls['n'] += 1
            return Conn(rows)

        with patch.object(config, 'connect', fake_connect):
            first = viewer.lab_notice_ids()
            second = viewer.lab_notice_ids()
        self.assertEqual(first, {'a', 'b'})
        self.assertEqual(second, {'a', 'b', 'c'})

    def test_lab_ids_failure_is_explained(self):
        from unittest.mock import patch

        def boom():
            raise RuntimeError('접속 실패')

        with patch.object(viewer, 'call_service', lambda p, m, timeout=120: self.service(['a'])), \
                patch.object(viewer, 'run_lab', lambda a, t: self.lab(['a'])), \
                patch.object(viewer, 'lab_notice_ids', boom):
            body = client.post('/api/compare', json=valid()).json()
        self.assertIsNone(body['lab_notice_count'])
        self.assertIn('표시를 하지 않는다', body['lab_ids_error'])
        self.assertIsNone(body['columns']['hybrid'][0]['in_lab_data'])
        self.assertEqual(len(body['columns']['lab']), 1)          # 비교 자체는 계속한다

    def test_bad_top_is_400_not_500(self):
        """P3: 정수가 아닌 top 은 조용히 바꾸지 않고 400 으로 돌려준다."""
        for bad in ('abc', 1.5, '1.5', True):
            r, calls = self.post(valid(top=bad), self.service([]), self.service([]),
                                 self.lab([]))
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(calls, {}, bad)                       # 검색을 부르지 않는다
        self.assertEqual(viewer.parse_top('7'), (7, None))
        self.assertEqual(viewer.parse_top(0), (1, None))
        self.assertEqual(viewer.parse_top(None), (5, None))

    def test_links_are_http_only_and_status_is_announced(self):
        """P3: 링크는 http/https 만, 검색 상태는 화면 낭독기에 알린다."""
        html = client.get('/compare').text
        self.assertIn('safeUrl', html)
        self.assertIn('https?:', html)
        self.assertNotIn("'<a href=\"' + esc(r.url)", html)
        self.assertIn('role="status"', html)
        self.assertIn('aria-live="polite"', html)


class CompareInputTests(unittest.TestCase):
    """/compare 신청자 입력 확장 — docs/COMPARE_INPUT_EXPANSION_TASK_20260921.md '필수 테스트'.

    사용자 결정: 설립일은 개인사업자·법인만 필수, 성별은 여성/남성/응답 안 함 중 필수.
    """

    REQUIRED = ('applicant_type', 'owner_name', 'birth_date', 'gender', 'region', 'main_industry',
                'business_no', 'owner_career', 'revenue', 'idea')

    def setUp(self):
        self.helper = CompareTests()

    def post(self, body):
        h = self.helper
        return h.post(body, h.service(['a']), h.service(['a']), h.lab(['a']))

    # 1
    def test_all_required_calls_each_search_once(self):
        r, calls = self.post(valid())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(m for _p, m in calls['service']), ['dense', 'hybrid'])
        self.assertIn('lab', calls)

    # 2
    def test_each_missing_required_is_4xx_and_calls_nothing(self):
        for field in self.REQUIRED:
            body = valid()
            body[field] = [] if field == 'revenue' else ''
            r, calls = self.post(body)
            self.assertEqual(r.status_code, 400, field)
            self.assertEqual(calls, {}, field)
            self.assertIn(field, [e['field'] for e in r.json()['fields']], field)

    # 3
    def test_business_needs_business_no_and_founded_at(self):
        for kind in ('개인사업자', '법인'):
            for field in ('business_no', 'founded_at'):
                r, calls = self.post(valid(applicant_type=kind, **{field: ''}))
                self.assertEqual(r.status_code, 400, (kind, field))
                self.assertEqual(calls, {})

    # 4
    def test_prestartup_passes_without_and_drops_stale_values(self):
        r, calls = self.post(valid(applicant_type='예비창업자', business_no='0000000000',
                                   founded_at='2021-04-01', self_funding=True,
                                   self_funding_budget='100'))
        self.assertEqual(r.status_code, 200)
        payload = calls['service'][0][0]
        self.assertEqual(payload['business_no'], '')
        self.assertEqual(payload['founded_at'], '')
        self.assertIsNone(payload['self_funding'])
        self.assertEqual(calls['lab'][0]['founded_at'], '')
        self.assertTrue(calls['lab'][0]['prestartup'])
        self.assertEqual(sorted(r.json()['input_summary']['dropped_for_type']),
                         ['business_no', 'founded_at', 'self_funding', 'self_funding_budget'])
        r2, _ = self.post(valid(applicant_type='예비창업자', business_no='', founded_at=''))
        self.assertEqual(r2.status_code, 200)

    # 5
    def test_rejects_bad_formats(self):
        cases = {
            'business_no': valid(business_no='12345'),
            'birth_date': valid(birth_date='2999-01-01'),
            'revenue[0].price': valid(revenue=[{'item': '장비', 'price': ''}]),
            'revenue[0].item': valid(revenue=[{'item': '', 'price': '1000'}]),
            'revenue[0].price ': valid(revenue=[{'item': '장비', 'price': '-5'}]),
            'budget_scale': valid(applicant_type='예비창업자', budget_scale='abc'),
            'self_funding_budget': valid(self_funding=True, self_funding_budget='1.5'),
            'gender': valid(gender='기타'),
            'region': valid(region='어딘가'),
            'district': valid(district='강남구'),               # 경기에 없는 시·군·구
            'founded_at': valid(founded_at='2999-01-01'),
        }
        for name, body in cases.items():
            r, calls = self.post(body)
            self.assertEqual(r.status_code, 400, name)
            self.assertEqual(calls, {}, name)

    def test_errors_never_echo_personal_values(self):
        secret_name, secret_no = '비밀이름값', '98765'
        r, _ = self.post(valid(owner_name=secret_name, business_no=secret_no, birth_date='2999-12-31'))
        text = json.dumps(r.json(), ensure_ascii=False)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(secret_no, text)
        self.assertNotIn('2999-12-31', text)
        self.assertNotIn(secret_name, text)

    # 6
    def test_owner_career_and_team_are_not_duplicated(self):
        r, calls = self.post(valid(team=[{'name': '테스트팀원', 'role': '개발', 'career': '금형 설계 12년'},
                                         {'name': '테스트팀원2', 'role': '개발', 'career': '머신비전 5년'}]))
        team = calls['service'][0][0]['team']
        careers = [m['career'] for m in team]
        self.assertEqual(careers.count('금형 설계 12년'), 1)
        self.assertEqual(team[0]['role'], '대표')
        self.assertEqual(team[0]['name'], '')                # 대표 행에 이름을 퍼뜨리지 않는다
        self.assertIn('머신비전 5년', careers)

    def test_half_filled_team_row_is_an_error(self):
        r, calls = self.post(valid(team=[{'name': '테스트팀원', 'role': '', 'career': ''}]))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(calls, {})

    # 7
    def test_hybrid_and_dense_payloads_differ_only_by_search(self):
        _r, calls = self.post(valid(certifications=['벤처기업'], partners=['테스트기관'],
                                    equipment=['3D 프린터'], hiring_plan=True))
        (p1, m1), (p2, m2) = calls['service']
        self.assertEqual({m1, m2}, {'hybrid', 'dense'})
        self.assertEqual(p1, p2)                             # search 는 call_service 가 붙인다

    # 8
    def test_main_industry_reaches_lab_as_industry(self):
        _r, calls = self.post(valid(main_industry='제조'))
        self.assertEqual(calls['lab'][0]['industry'], '제조업')
        _r, calls = self.post(valid(main_industry='우주관광'))
        self.assertEqual(calls['lab'][0]['industry'], '')    # 어휘에 없으면 넘기지 않는다

    def test_industry_actually_changes_lab_judgement(self):
        """새 방식에 넘긴 업종이 조건 판정 문구를 실제로 바꾸는지 (진짜 judge_list)."""
        from experiments.sql_semantic import compare_input, search
        clean, errors = compare_input.validate(valid(main_industry='제조업'))
        self.assertEqual(errors, [])
        applicant, _ = compare_input.lab_applicant(clean)
        row = {'industry_status': 'known', 'industry_value': '서비스업'}
        verdict, _why = search.judge_list(row, applicant, 'industry_status', 'industry_value',
                                          'industry', '업종')
        self.assertEqual(verdict, search.NO)
        verdict, why = search.judge_list(row, dict(applicant, industry=''), 'industry_status',
                                         'industry_value', 'industry', '업종')
        self.assertIn('미입력', why)

    # 9
    def test_unused_fields_are_marked_unused(self):
        r, _ = self.post(valid(equipment=['3D 프린터']))
        usage = {u['field']: u for u in r.json()['usage']}
        for field in ('owner_name', 'birth_date', 'business_no', 'equipment'):
            self.assertEqual(usage[field]['service'], '입력만 받음', field)
            self.assertEqual(usage[field]['lab'], '미사용', field)
        self.assertIn('조건 판정', usage['region']['lab'])
        self.assertIn('조건 판정', usage['main_industry']['lab'])
        self.assertEqual(usage['district']['lab'], '미사용')
        self.assertEqual(usage['gender']['lab'], '미사용')
        self.assertIn('해당 없음', usage['gender']['service'])  # '응답 안 함' 은 규칙을 적용하지 않는다

    def test_gender_no_answer_is_sent_as_empty(self):
        _r, calls = self.post(valid(gender='응답 안 함'))
        self.assertEqual(calls['service'][0][0]['gender'], '')
        _r, calls = self.post(valid(gender='여성'))
        self.assertEqual(calls['service'][0][0]['gender'], '여성')

    # 10
    def test_page_hides_and_clears_conditional_fields(self):
        html = client.get('/compare').text
        self.assertIn('data-for="business"', html)
        self.assertIn('data-for="prestartup"', html)
        self.assertIn("i.value = ''", html)                  # 숨길 때 값을 지운다
        self.assertIn('유형에 맞지 않는 칸은 아예 보내지 않는다', html)

    # 11
    def test_no_personal_data_in_response_or_browser_storage(self):
        r, _ = self.post(valid(owner_name='비밀이름값', business_no='1234567890',
                               birth_date='1970-07-07'))
        text = json.dumps(r.json(), ensure_ascii=False)
        for secret in ('비밀이름값', '1234567890', '1970-07-07'):
            self.assertNotIn(secret, text)
        html = client.get('/compare').text
        self.assertNotIn('localStorage', html)
        self.assertNotIn('sessionStorage', html)
        self.assertNotIn('location.search', html)
        self.assertNotIn('history.pushState', html)
        self.assertIn("method:'POST'", html)

    # 12
    def test_accessibility_markers(self):
        html = client.get('/compare').text
        self.assertGreaterEqual(html.count('aria-required="true"'), 8)
        self.assertIn('aria-describedby="e-owner_name"', html)
        self.assertIn("setAttribute('aria-invalid', 'true')", html)
        self.assertIn('first.focus()', html)
        self.assertIn('role="status"', html)
        self.assertIn('* 필수', html)                         # 색만이 아니라 글자로 필수 표시

    # ---- 2026-09-21 Codex 입력 확장 리뷰

    def test_dates_must_be_exact_yyyy_mm_dd(self):
        """P2: 뒤에 글자가 붙은 날짜를 잘라 읽고 승인하던 문제."""
        for field, value in (('birth_date', '1980-01-01garbage'), ('founded_at', '2021-04-01garbage'),
                             ('birth_date', '19800101'), ('birth_date', '1980-13-01'),
                             ('founded_at', '2023-02-29')):
            r, calls = self.post(valid(**{field: value}))
            self.assertEqual(r.status_code, 400, (field, value))
            self.assertEqual(calls, {})
        r, _ = self.post(valid(founded_at='2024-02-29'))          # 윤년은 정상
        self.assertEqual(r.status_code, 200)

    def test_twenty_rows_ok_twenty_one_rejected(self):
        """P2: 21번째 행부터 조용히 버리던 문제 — 이제 21개면 오류."""
        rev = [{'item': '항목%d' % i, 'price': '100'} for i in range(20)]
        team = [{'name': '', 'role': '', 'career': '이력%d' % i} for i in range(20)]
        r, _ = self.post(valid(revenue=rev, team=team))
        self.assertEqual(r.status_code, 200)
        for field, extra in (('revenue', {'revenue': rev + [{'item': '항목20', 'price': '100'}]}),
                             ('team', {'team': team + [{'career': '이력20'}]})):
            r, calls = self.post(valid(**extra))
            self.assertEqual(r.status_code, 400, field)
            self.assertIn(field, [e['field'] for e in r.json()['fields']])
            self.assertEqual(calls, {})

    def test_lab_gets_no_district(self):
        """P3: 새 방식이 쓰지 않는 시·군·구는 넘기지 않는다."""
        _r, calls = self.post(valid())
        self.assertNotIn('district', calls['lab'][0])

    def test_selftest_page_and_hooks(self):
        """브라우저 동작 시험 페이지. 실제 실행 결과는 브라우저로 연다(문서 VERIFY_UI 3-3)."""
        page = client.get('/compare/selftest')
        self.assertEqual(page.status_code, 200)
        for name in ('이전 선택이 남지 않는다', '예시 전환 순서와 무관하게', '결과·사용 여부 표가 지워진다',
                     '늦게 온 응답을 버린다', '내용 있는 행 추가·삭제·예시는 무효화',
                     '20행에서 추가 버튼이 막히고', 'aria-invalid·초점',
                     '서버 오류의 행 번호를'):
            self.assertIn(name, page.text)
        html = client.get('/compare').text
        self.assertIn('window.__compare', html)
        self.assertIn('resetForm();', html)                         # 예시 적용 전에 초기화
        self.assertIn('if(my !== gen) return;', html)               # 늦은 응답 무시
        self.assertIn('role="group" aria-labelledby="l-revenue" aria-describedby="e-revenue"', html)

    def test_form_options_route(self):
        body = client.get('/api/compare/form').json()
        self.assertEqual(body['genders'], ['여성', '남성', '응답 안 함'])
        self.assertIn('예비창업자', body['applicant_types'])
        self.assertTrue(any(r['value'] == '경기' and '수원시' in r['districts']
                            for r in body['regions']))
        self.assertIn('벤처기업', body['certifications'])


class StoredRunTests(unittest.TestCase):
    """저장된 실제 결과 폴더가 있으면 그것도 읽어 본다. 없으면 건너뛴다."""

    @classmethod
    def setUpClass(cls):
        folders = viewer.stored_folders()
        if not folders:
            raise unittest.SkipTest('저장된 sql_semantic 결과 폴더가 없다')
        cls.run_id = os.path.basename(folders[-1])

    def test_stored_run_loads_with_files_and_hashes(self):
        body = client.get('/api/run/%s' % self.run_id).json()
        self.assertFalse(body['is_fixture'])
        self.assertEqual(body['banner'], '')
        self.assertTrue(body['cases'])
        self.assertTrue(all(f['sha256'] for f in body['files']))

    def test_stored_run_hides_account(self):
        body = client.get('/api/run/%s' % self.run_id).json()
        text = json.dumps(body, ensure_ascii=False)
        self.assertNotIn('"user"', text)
        self.assertNotIn('password', text)

    def test_stored_case_detail_side_by_side(self):
        overview = client.get('/api/run/%s' % self.run_id).json()
        case_id = overview['cases'][0]['case_id']
        body = client.get('/api/run/%s/case/%s' % (self.run_id, case_id)).json()
        self.assertTrue(body['side_by_side'])
        for row in body['side_by_side']:
            self.assertIn(row['where'], ('공통', '필터 켬 전용', '필터 끔 전용'))


class CompareHelperTests(unittest.TestCase):
    """순위 이동·제외 집계 계산."""

    def test_rank_move_and_only_flags(self):
        on = {'results': [{'notice_id': 'a', 'rank': 1, 'title': 'A'},
                          {'notice_id': 'b', 'rank': 2, 'title': 'B'}]}
        off = {'results': [{'notice_id': 'b', 'rank': 1, 'title': 'B'},
                           {'notice_id': 'c', 'rank': 2, 'title': 'C'}]}
        rows = {r['notice_id']: r for r in viewer.compare_modes(on, off)}
        self.assertEqual(rows['a']['where'], '필터 켬 전용')
        self.assertIsNone(rows['a']['move'])
        self.assertEqual(rows['b']['where'], '공통')
        self.assertEqual(rows['b']['move'], -1)      # 1위 → 2위, 내려갔다
        self.assertEqual(rows['c']['where'], '필터 끔 전용')

    def test_empty_results_do_not_crash(self):
        self.assertEqual(viewer.compare_modes({}, {}), [])
        self.assertEqual(viewer.drop_split({})['returned'], None)

    def test_sql_dropped_is_calculated_from_filter_off(self):
        """SQL 단계 제외를 화면이 직접 계산한다 (2026-09-21 Codex 리뷰 2번)."""
        on = {'counts': {'rows_from_sql': 819, 'dropped': 25, 'after_conditions': 794,
                         'compared': 794, 'returned': 5}}
        off = {'counts': {'rows_from_sql': 1852, 'dropped': 0, 'after_conditions': 1852,
                          'compared': 1852, 'returned': 5}}
        out = viewer.drop_split(on, off)
        self.assertEqual(out['total_candidates'], 1852)
        self.assertEqual(out['sql_dropped'], 1033)
        self.assertEqual(out['rows_from_sql'], 819)
        self.assertEqual(out['dropped_by_conditions'], 25)
        self.assertEqual(out['dropped_by_vector'], 0)
        self.assertEqual(out['sql_note'], '')

    def test_vector_drop_is_separated_from_condition_drop(self):
        out = viewer.drop_split({'counts': {'rows_from_sql': 10, 'dropped': 2,
                                            'after_conditions': 8, 'compared': 5,
                                            'returned': 5}},
                                {'counts': {'rows_from_sql': 10}})
        self.assertEqual(out['dropped_by_conditions'], 2)
        self.assertEqual(out['dropped_by_vector'], 3)

    def test_filter_off_compared_with_itself_drops_nothing_in_sql(self):
        off = {'counts': {'rows_from_sql': 1852, 'dropped': 0, 'after_conditions': 1852,
                          'compared': 1852, 'returned': 5}}
        self.assertEqual(viewer.drop_split(off, off)['sql_dropped'], 0)

    def test_no_baseline_explains_instead_of_guessing(self):
        out = viewer.drop_split({'counts': {'rows_from_sql': 819}}, None)
        self.assertIsNone(out['sql_dropped'])
        self.assertIn('계산하지 않았다', out['sql_note'])

    def test_smaller_baseline_does_not_become_negative(self):
        """기준이 더 작은 비정상 입력에서 음수를 만들지 않는다."""
        out = viewer.drop_split({'counts': {'rows_from_sql': 900}},
                                {'counts': {'rows_from_sql': 100}})
        self.assertIsNone(out['sql_dropped'])
        self.assertIn('작다', out['sql_note'])

    def test_drop_fields_counted_from_examples(self):
        out = viewer.drop_split({'counts': {'dropped': 2},
                                 'dropped_examples': [{'notice_id': 'x', 'fields': ['region']},
                                                      {'notice_id': 'y', 'fields': ['region',
                                                                                    'business_age']}]})
        self.assertEqual(out['dropped_fields_in_examples'],
                         {'region': 2, 'business_age': 1})

    def test_lab_account_is_stripped(self):
        safe = viewer._safe_lab({'lab': {'host': '127.0.0.1', 'user': 'root',
                                         'password': 'secret', 'database': 'lab'},
                                 'separated': True})
        text = json.dumps(safe)
        self.assertNotIn('root', text)
        self.assertNotIn('secret', text)
        self.assertIn('127.0.0.1', text)


if __name__ == '__main__':
    unittest.main()
