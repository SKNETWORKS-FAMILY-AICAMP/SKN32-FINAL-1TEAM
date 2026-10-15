# -*- coding: utf-8 -*-
"""eval/metrics_report — 지표 묶음 규칙(DB·서버 없이): 단위·이름 겹침·못 잰 지표·전후 묶기·한눈에 보기·주소 걸러 내기·기록 값 목록."""
import json
import os
import sys
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval import metrics_report as mr  # noqa: E402

TODAY = date(2026, 10, 14)


def run(at, status='ok', elapsed=500, ks='ok', complete=True):
    return {'job': 'pipeline', 'run_at': at, 'status': status, 'elapsed_sec': elapsed,
            'sources': {'kstartup': {'status': ks, 'complete': complete}, 'bizinfo': {'status': 'ok'}}}


class BookTests(unittest.TestCase):
    def test_unknown_unit_or_area_rejected(self):
        b = mr.Book(TODAY)
        with self.assertRaises(ValueError):
            b.add('1', 'x', 1, 'percent')
        with self.assertRaises(ValueError):
            b.add('99', 'y', 1, 'count')

    def test_duplicate_name_rejected(self):
        b = mr.Book(TODAY)
        b.add('1', '누적 공고 수', 1, 'count')
        with self.assertRaises(ValueError):
            b.add('2', '누적 공고 수', 2, 'count')

    def test_miss_marks_value_null_and_records_reason(self):
        b = mr.Book(TODAY)
        b.miss('8', '추천 응답 시간(이 PC, 중앙값)', 'ms', '서버 꺼짐', expected=False)
        m = b.metrics[0]
        self.assertIsNone(m['value'])
        self.assertIn('측정 못 함(서버 꺼짐)', m['detail'])
        self.assertEqual(b.missing, [{'name': '추천 응답 시간(이 PC, 중앙값)', 'reason': '서버 꺼짐', 'expected': False}])
        self.assertTrue(m['plain'])                          # 못 재도 쉬운 설명은 있다

    def test_guarded_fills_planned_names_on_error(self):
        b = mr.Book(TODAY)

        def boom(book):
            book.add('1', '누적 공고 수', 3016, 'count')
            raise ConnectionError('host 1.2.3.4 refused')

        mr.guarded(b, [('1', '누적 공고 수', 'count', 'live'), ('1', '지금 모집 중인 공고 수', 'count', 'live')], boom)
        self.assertEqual(b.metrics[0]['value'], 3016)
        self.assertIsNone(b.metrics[1]['value'])
        self.assertEqual(b.missing[0]['reason'], 'ConnectionError')   # 예외 원문(주소)은 남기지 않는다
        self.assertFalse(b.missing[0]['expected'])


class OpsTests(unittest.TestCase):
    def test_dry_run_is_not_a_real_run(self):
        self.assertFalse(mr.real_run(run('2026-09-14T09:36:01', ks='dry-run', elapsed=3)))
        self.assertTrue(mr.real_run(run('2026-10-05T00:00:46', elapsed=44)))   # 새 공고 없는 날 40초 배치도 실행이다
        self.assertFalse(mr.real_run({'run_at': 't', 'count': 3}))

    def test_window_counts_days_and_success(self):
        rows = [run('2026-10-02T09:05:15'), run('2026-10-03T00:06:59', status='fail'), run('2026-10-05T00:00:46', elapsed=44),
                run('2026-10-05T01:00:00', ks='dry-run')]
        w = mr.ops_window(rows, date(2026, 10, 2), date(2026, 10, 5))
        self.assertEqual((w['runs'], w['ok'], w['days'], w['span']), (3, 2, 3, 4))
        self.assertEqual(w['not_ok'], ['fail'])

    def test_batch_days_keeps_longest_per_day(self):
        days = mr.batch_days([run('2026-09-28T08:55:00', elapsed=618), run('2026-09-28T09:02:00', elapsed=118)], TODAY)
        self.assertEqual(days['2026-09-28']['elapsed_sec'], 618)

    def test_kst_day_pc_rows_kst_server_rows_utc(self):
        self.assertEqual(mr.kst_day('2026-10-02T09:05:15'), '2026-10-02')         # PC 시절(한국 시각) 그대로
        self.assertEqual(mr.kst_day('2026-09-14T23:30:00'), '2026-09-14')
        self.assertEqual(mr.kst_day('2026-10-03T00:06:59'), '2026-10-03')         # 서버 줄(UTC 00시 = 한국 09시)
        self.assertEqual(mr.kst_day('2026-10-20T18:00:00'), '2026-10-21')         # 배치를 한국 새벽 3시로 옮겨도 날짜가 맞다
        self.assertEqual(mr.kst_day('2026-10-20T18:00:00+00:00'), '2026-10-21')   # 시간대가 붙어 있으면 그것을 따른다
        self.assertEqual(mr.kst_day('2026-10-21T03:00:00+09:00'), '2026-10-21')
        days = mr.batch_days([run('2026-10-20T18:00:00', elapsed=400)], TODAY)
        self.assertEqual(list(days), ['2026-10-21'])

    def test_server_window_starts_at_first_server_run(self):
        """10/2 배치는 PC 의 밀린 실행 — '서버 이전 뒤'는 서버에서 처음 돈 10/3부터(결정 0006)."""
        self.assertEqual(mr.SERVER_FIRST_RUN, date(2026, 10, 3))
        rows = [run('2026-10-02T09:05:15', elapsed=1294.2), run('2026-10-03T00:06:59', elapsed=417.7),
                run('2026-10-04T00:00:43', elapsed=41.4), run('2026-10-09T00:06:35', elapsed=393.2)]
        w = mr.ops_window(rows, mr.SERVER_FIRST_RUN, date(2026, 10, 4))
        self.assertEqual((w['runs'], w['days'], w['span']), (2, 2, 2))
        self.assertIn('10/3부터', mr.PLAIN['배치 성공률(서버 이전 뒤)'])
        self.assertNotIn('10/2', mr.PLAIN['배치 가동일 비율(서버 이전 뒤)'])

    def test_notice_count_from_detail(self):
        self.assertEqual(mr.notice_count('p95 503ms · 최대 564ms · 질의 58개 · 공고 2603건'), 2603)
        self.assertIsNone(mr.notice_count(None))

    def test_topic_particle_follows_last_syllable(self):
        self.assertEqual(mr.with_topic('공고 1건'), '공고 1건은')
        self.assertEqual(mr.with_topic('전체 다시 만들기'), '전체 다시 만들기는')
        self.assertEqual(mr.with_topic('GPU'), 'GPU은(는)')

    def test_batch_source_line_has_one_bracket(self):
        both = {'sources': ['이 PC 복사본(sbrain-web)', 'sbrain-web 서버']}
        self.assertEqual(mr.batch_src(both, 'collect_log'), '배치 기록 collect_log(서버 sbrain-web, 이 PC 복사본과 합침)')
        self.assertIn('서버에서 새로 읽지 못함', mr.batch_src({'sources': ['이 PC 복사본(sbrain-web)']}, 'run.log'))
        self.assertEqual(mr.batch_src({'sources': []}, 'run.log'), '배치 기록 run.log(없음)')

    def test_kstartup_complete_old_and_new_rows(self):
        rows = [{'run_at': 't1', 'status': 'ok', 'count': 244, 'reported_total': 244},
                {'run_at': 't2', 'status': 'ok', 'count': 240, 'reported_total': 244},
                run('2026-10-14T00:08:16'), run('2026-10-13T00:08:29', complete=False), run('2026-10-12T00:00:45', ks='dry-run')]
        self.assertEqual(mr.kstartup_complete(rows), (2, 4))

    def test_daily_costs_skip_estimates(self):
        log = ('[2026-10-14 09:00:02] start\n'
               '  추출 47건 · 약 $0.0206\n'
               '  열린 공고 중 … 예상 약 $0.04(추정)\n'
               '  저장 39건 · 약 $0.031(추정)\n'
               '[2026-10-15 09:00:02] start\n'
               '  추출 3건 · 약 $0.001\n')
        c = mr.daily_costs(log)
        self.assertAlmostEqual(c['2026-10-14'], 0.0516)
        self.assertAlmostEqual(c['2026-10-15'], 0.001)


class AccuracyTests(unittest.TestCase):
    BASE = {'ineligible_k': {'vector_only': 0.243, 'filter_first': 0.0}, 'p3_lo': {'vector_only': 0.494, 'filter_first': 0.621}}

    def now(self, p3=0.6):
        return {'meta': {'queries': 58, 'qrels_pairs': 1617},
                'summary': {'hybrid': {'ineligible_k': {'vector_only': 0.3, 'filter_first': 0.0, 'diff_vs_vector': [-0.3, -0.35, -0.25]},
                                       'p3_lo': {'vector_only': 0.5, 'filter_first': p3, 'diff_vs_vector': [0.1, 0.0, 0.2]}}}}

    def test_compare_holds_now_and_0928_reference(self):
        b = mr.Book(TODAY)
        mr.area_accuracy(b, (self.BASE, self.now(), 'reports/filter_first_now_20261014T111013Z'))
        m = {x['name']: x for x in b.metrics}[mr.INELIGIBLE]
        self.assertEqual(m['compare']['before'], 0.3)
        self.assertEqual(m['compare']['after'], 0.0)
        self.assertEqual(m['compare']['reference'], {'label': '9/28 평가', 'before': 0.243, 'after': 0.0,
                                                     'label_before': '처음(의미 검색만)', 'label_after': '9/28 서비스'})
        self.assertEqual(m['measured_at'], '2026-10-14')
        self.assertIn(mr.P3_HI, {x['name'] for x in b.metrics})     # 다시 재기에 없는 지표는 못 잰 것으로
        self.assertTrue(any(x['name'] == mr.P3_HI for x in b.missing))
        self.assertEqual(b.raw['acc_meta']['queries'], 58)

    def test_accuracy_names_are_plain_with_term_in_explanation(self):
        self.assertEqual((mr.INELIGIBLE, mr.P3_LO, mr.P3_HI),
                         ('상위 10건 중 신청 불가', '상위 3건 적합(낮게 센 값)', '상위 3건 적합(높게 센 값)'))
        for name, term in ((mr.INELIGIBLE, '신청 불가@10'), (mr.P3_LO, 'P@3(2) 하한'), (mr.P3_HI, 'P@3(2) 상한')):
            self.assertIn(term, mr.PLAIN[name])

    def test_missing_rerun_is_unexpected_gap(self):
        b = mr.Book(TODAY)
        mr.area_accuracy(b, (self.BASE, None, None))
        self.assertTrue(all(x['value'] is None for x in b.metrics))
        self.assertTrue(all(not x['expected'] for x in b.missing))

    def test_lower_than_0928_is_written_as_weakness(self):
        b = mr.Book(TODAY)
        try:
            mr.area_weak(b, (self.BASE, self.now(p3=0.575), 'reports/filter_first_now_x'))
        except FileNotFoundError:
            self.skipTest('판정자 일치 결과 폴더 없음')
        names = {x['name'] for x in b.metrics}
        self.assertIn('약점: 다시 잰 정확도가 9/28보다 낮음', names)
        b2 = mr.Book(TODAY)
        mr.area_weak(b2, (self.BASE, self.now(p3=0.7), 'reports/filter_first_now_x'))
        self.assertNotIn('약점: 다시 잰 정확도가 9/28보다 낮음', {x['name'] for x in b2.metrics})


class HeadlineTests(unittest.TestCase):
    def book_with_all(self):
        b = mr.Book(TODAY)
        for name in (mr.INELIGIBLE, mr.P3_LO):
            b.add('4', name, 0.5, 'ratio', compare={'before': 0.4, 'after': 0.5, 'label_before': 'a', 'label_after': 'b',
                                                    'reference': {'label': '9/28 평가', 'before': 0.494, 'after': 0.621}})
        for area, name, unit in (('1', '누적 공고 수', 'count'), ('1', '하루 평균 신규 공고', 'count'), ('2', '첨부 공고문 본문 추출 성공률', 'ratio'),
                                 ('7', '연결 계약 시험 통과', 'count'), ('7', '자격 판정 응답 형식 오류', 'count'),
                                 ('8', '추천 응답 시간(이 PC, 중앙값)', 'ms'), ('8', '추천 응답 시간(실제 서버, 중앙값)', 'ms'), ('9', '하루 AI 비용', 'usd')):
            b.add(area, name, 1, unit)
        return b

    def test_seven_cards_and_two_value_cards(self):
        cards = mr.headline(self.book_with_all())
        self.assertEqual(len(cards), 7)
        two = {c['title'] for c in cards if len(c['values']) == 2}
        self.assertEqual(two, {'공고 수', '조율 연결', '추천 응답 시간'})
        for c in cards:
            self.assertEqual(set(c), {'title', 'values', 'chart', 'note'})
        self.assertEqual([c['chart'] for c in cards if c['chart']], [mr.INELIGIBLE, mr.P3_LO])
        labels = [v['label'] for c in cards for v in c['values']]
        self.assertIn('하루 평균 신규(새 공고가 들어온 날)', labels)   # 0인 날을 뺀 평균이라는 것을 이름에

    def test_p3_note_mentions_drop(self):
        cards = mr.headline(self.book_with_all())
        note = next(c['note'] for c in cards if c['title'] == '상위 3건 적합 비율')
        self.assertIn('낮다', note)
        self.assertNotIn('11. 약점과 한계', note)        # 그림(PNG)만 붙여도 뜻이 통하게 — 문서 절을 가리키지 않는다

    def test_p3_note_explains_low_count_and_ai_judges(self):
        b = self.book_with_all()
        b.add('4', mr.P3_HI, 0.7414, 'ratio')
        b.add('11', '판정자 일치율: LLM(gpt-4.1-mini) vs 사람', 0.6434, 'ratio')
        b.raw['acc_meta'] = {'queries': 58}
        cards = mr.headline(b)
        note = next(c['note'] for c in cards if c['title'] == '상위 3건 적합 비율')
        for want in ('평가 질의 58개', '낮은 쪽 값', '높게 세면 74.1%', 'AI', '64%'):
            self.assertIn(want, note)
        first = next(c['note'] for c in cards if c['chart'] == mr.INELIGIBLE)
        self.assertIn('같은 규칙', first)

    def test_missing_metric_reference_is_an_error(self):
        with self.assertRaises(ValueError):
            mr.headline(mr.Book(TODAY))

    def test_latency_card_does_not_claim_same_conditions_as_0930(self):
        """9/30 응답 시간은 옛 검색 방식·다른 공고 수(그리고 그때 PC)에서 잼 — '같은 조건'이라고 쓰지 않는다."""
        note = next(c['note'] for c in mr.headline(self.book_with_all()) if c['title'] == '추천 응답 시간')
        self.assertNotIn('같은 조건', note)
        self.assertIn('이 PC 안에서 잰 값', note)
        self.assertNotIn('같은 조건', mr.PLAIN['추천 응답 시간(이 PC, 중앙값)'])


class OutputTests(unittest.TestCase):
    def test_scrub_removes_addresses_and_key_files(self):
        n, text = mr.scrub('url http://43.201.90.238:8000/api · 13.125.40.88 · key sbrain-web.pem · 값 0.243 · 2026-10-14 · v2.14.1')
        self.assertEqual(n, 3)
        self.assertNotIn('43.201', text)
        self.assertNotIn('.pem', text)
        self.assertIn('0.243', text)
        self.assertIn('2.14.1', text)

    def test_fmt_by_unit(self):
        self.assertEqual(mr.fmt({'value': 0.2431, 'unit': 'ratio', 'name': 'x', 'target': ''}), '24.3%')
        self.assertEqual(mr.fmt({'value': 0.597, 'unit': 'score', 'name': 'x', 'target': ''}), '0.597')
        self.assertEqual(mr.fmt({'value': 3016, 'unit': 'count', 'name': 'x', 'target': ''}), '3,016')
        self.assertEqual(mr.fmt({'value': 1.86, 'unit': 'count', 'name': 'x', 'target': ''}), '1.86')
        self.assertEqual(mr.fmt({'value': 16, 'unit': 'count', 'name': '연결 계약 시험 통과', 'target': '16'}), '16/16')
        self.assertEqual(mr.fmt({'value': 0.033, 'unit': 'usd', 'name': 'x', 'target': ''}), '$0.033')
        self.assertEqual(mr.fmt({'value': None, 'unit': 'ms', 'name': 'x', 'target': ''}), '측정 못 함')

    def test_area_titles_cover_plan(self):
        self.assertEqual(list(mr.AREAS), [str(i) for i in range(1, 12)] + ['ML'])


class RecordsTests(unittest.TestCase):
    def test_records_have_existing_sources_and_no_addresses(self):
        text = mr.read_text(mr.RECORDS)
        self.assertEqual(mr.scrub(text)[0], 0, '기록 값 목록에 주소·키 파일 이름이 있다')
        data = json.loads(text)
        keys = set()
        for r in data['records']:
            self.assertIn(r['unit'], mr.UNITS)
            self.assertIn(r['area'], mr.AREAS)
            self.assertTrue(os.path.exists(os.path.join(ROOT, r['source'])), r['source'])
            self.assertTrue(r.get('evidence') and r.get('measured_at'))
            self.assertNotIn(r['key'], keys)
            keys.add(r['key'])

    def test_record_values_appear_in_source(self):
        for r in mr.read_json(mr.RECORDS)['records']:
            quote = r['evidence'].split('"')[1] if '"' in r['evidence'] else ''
            if quote:
                src = ' '.join(mr.read_text(os.path.join(ROOT, r['source'])).split())   # 칸 맞춤 공백은 하나로
                self.assertIn(' '.join(quote.split()), src, '%s: 근거 문장이 출처에 없다' % r['key'])


RUN_LOG = ('[2026-09-28  9:00:02.16] start \n'
           '  추출 3건 · 실패 0건 · 누적 2475건\n'                                 # 비용 줄 생기기 전 날 — 그래프에서 빠짐
           '[2026-09-29  9:00:02.14] start \n'
           '  추출 50건 · 실패 0건 · 누적 2525건 · 약 $0.0462\n'
           '[2026-10-04 09:00:01] start (server)\n'
           '  추출 0건 · 실패 0건 · 누적 2765건 · 약 $0.0000\n'
           '[2026-10-08 09:00:01] start (server)\n'
           '  추출 36건 · 실패 0건 · 누적 2861건 · 약 $0.0155\n'
           '  열린 공고 중 … 부를 것 300 · 예상 약 $0.37(추정)\n'
           '    150/300 · 실패 0 · 약 $0.136\n'
           '    300/300 · 실패 0 · 약 $0.279\n'
           '  저장 1448건(LLM 300) · 실패 0 · 약 $0.279(추정)\n'
           '[2026-10-09 09:00:01] start (server)\n'
           '  (비용 줄이 남지 않은 날)\n')
SPEC_IDS = ('c01_cumulative_notices', 'c02_daily_new_notices', 'c03_notices_by_source', 'c04_batch_minutes',
            'c05_attachment_extraction', 'c06_apply_period_types', 'c07_judgment_coverage', 'c08_type_agreement',
            'c09_accuracy_before_after', 'c10_status_timing', 'c11_entity_block', 'c12_bonus_steps', 'c13_bonus_by_persona',
            'c14_g01_all', 'c15_latency', 'c16_embedding_cpu_gpu', 'c17_server_memory', 'c18_daily_ai_cost',
            'c19_server_monthly_cost', 'c20_test_count', 'c21_judge_agreement', 'c22_reranker', 'c23_age_classifier')


def fake_ctx():
    """DB·서버 없이 그래프를 만들 수 있는 가짜 재료. 기록 파일(reports/·ml/data/·eval/metrics_records.json)은 진짜를 읽는다."""
    b = mr.Book(TODAY)
    for name, v in (('판정표 적용 범위: 자격요건(금액·형태·업력)', 0.91), ('판정표 적용 범위: 신청자 유형', 0.99),
                    ('판정표 적용 범위: 업종', None), ('판정표 적용 범위: 가점(열린 기업마당 공고)', 0.72)):
        b.add('3', name, v, 'ratio')
    b.add('1', '지금 모집 중인 공고 수', 1730, 'count')
    b.add('6', '열린 공고 중 가점 언급 공고', 305, 'count')
    b.add('6', '신청자별 가산점이 나오는 공고', 29, 'count', source='reports/bonus_boostable_20261013T022836Z', kind='record',
          measured_at='2026-10-13')
    b.add('6', '원문 대조를 마친 가산점 공고', 30, 'count')
    b.raw['coverage'] = {'판정표 적용 범위: 자격요건(금액·형태·업력)': {'judged': 2061, 'base': 2265, 'notices': 3072},
                         '판정표 적용 범위: 신청자 유형': {'judged': 3041, 'base': 3072, 'notices': 3072},
                         '판정표 적용 범위: 가점(열린 기업마당 공고)': {'judged': 1115, 'base': 1548, 'notices': 3072}}
    for t, before, after in (('개인사업자', 7, 0), ('법인', 2, 1)):
        b.add('5', '%s "강한 불가" 공고가 상위 20에 뜬 질의' % t, after, 'count',
              compare={'before': before, 'after': after, 'label_before': '차단 전', 'label_after': '차단 후'})
    for name, unit, before, after in (('임베딩 공고 1건(CPU→GPU)', 'ms', 408.4, 21.2), ('임베딩 검색어 1건(CPU→GPU)', 'ms', 178.5, 21.7),
                                      ('임베딩 전체 다시 만들기(CPU→GPU)', 'min', 20.53, 1.07)):
        b.add('8', name, after, unit, compare={'before': before, 'after': after, 'label_before': 'CPU', 'label_after': 'GPU'})
    b.add('10', '자동 테스트 수', 1080, 'count')
    b.raw['latency'] = {'pc': {'median': 300.04, 'p95': 450.0, 'max': 500.0, 'n': 58}}
    db = {'per_day': [('2026-09-08', 1832), ('2026-09-09', 101), ('2026-10-13', 63), ('2026-10-14', 45)],
          'by_source': {'kstartup': 604, 'bizinfo': 2468}, 'open_by_source': {'kstartup': 210, 'bizinfo': 1520},
          'att_status': {'ok': 2265, 'image_only': 197, 'parse_error': 6}, 'att_sources': {'bizinfo': 2468},
          'period_types': {'fixed': 2043, 'rolling': 155, 'unknown': 67, 'budget_exhaustion': 702, 'until_filled': 105}}
    rows = [run('2026-09-28T08:55:00', elapsed=618), run('2026-10-02T09:05:15', elapsed=1294), run('2026-10-04T00:00:41', elapsed=41),
            run('2026-10-05T01:00:00', ks='dry-run', elapsed=3)]
    logs = {'collect_rows': rows, 'run_log': RUN_LOG, 'sources': ['이 PC 복사본(시험)']}
    base = {'ineligible_k': {'vector_only': 0.243, 'filter_first': 0.0}, 'p3_lo': {'vector_only': 0.494, 'filter_first': 0.6207}}
    hybrid = {'ineligible_k': {'vector_only': 0.2466, 'filter_first': 0.0}, 'p3_lo': {'vector_only': 0.4943, 'filter_first': 0.6149},
              'p3_hi': {'vector_only': 0.6092, 'filter_first': 0.7414}, 'unjudgedk': {'vector_only': 0.1603, 'filter_first': 0.3241}}
    now = {'meta': {'queries': 58, 'as_of': '2026-09-15', 'status_as_of': {'date': '2026-09-15', 'reopened': 12}},
           'summary': {'hybrid': hybrid}, 'summary_today_status': {'hybrid': {'p3_lo': {'vector_only': 0.4943, 'filter_first': 0.5747}}}}
    acc = (base, now, os.path.join(mr.REPORTS, 'filter_first_now_20261014T113101Z'))
    return {'today': TODAY, 'metrics': {m['name']: m for m in b.metrics}, 'raw': b.raw, 'db': db, 'logs': logs, 'acc': acc,
            'records': mr.load_records()}


def good_chart(**over):
    c = mr.chart('c99_test', '1', '제목', '부제', 'bar', 'count', ['가', '나', '다'], [('계열', [1, None, 3])], '한 문장', '출처',
                 'live', '2026-10-14', highlight=[0, 2], top=10, reference=[{'value': 5, 'label': '기준'}], errors=[[0, 2], None, [2, 4]])
    c.update(over)
    return c


class ChartContractTests(unittest.TestCase):
    def test_ids_match_plan(self):
        self.assertEqual(mr.CHART_IDS, SPEC_IDS)

    def test_good_chart_passes_and_has_every_key(self):
        c = good_chart()
        self.assertEqual(set(c), set(mr.CHART_KEYS))
        self.assertIs(mr.check_chart(c), c)

    def test_bad_charts_are_rejected(self):
        bad = [dict(unit='percent'), dict(form='pie'), dict(id='C-01'), dict(area='12'), dict(highlight=[3]), dict(highlight=[0, 0]),
               dict(series=[{'name': 'a', 'values': [1, 2]}]), dict(series=[{'name': 'a', 'values': [1, 2, 'x']}]),
               dict(series=[{'name': 'a', 'values': [1, 2, True]}]), dict(series=[{'name': 'a', 'values': [1, 2, float('nan')]}]),
               dict(series=[{'name': str(i), 'values': [1, 2, 3]} for i in range(4)]), dict(errors=[[2, 1], None, None]),
               dict(errors=[None]), dict(reference=[{'value': 'x', 'label': 'a'}]), dict(measured_at='10/14'), dict(kind='guess'),
               dict(note=''), dict(units=['ms', 'ms', 'ms']), dict(max=2), dict(max=3.5)]   # 값(3)·구간 끝(4)이 축 끝을 넘음
        for over in bad:
            with self.assertRaises(ValueError, msg=str(over)):
                mr.check_chart(good_chart(**over))
        two = good_chart(series=[{'name': 'a', 'values': [1, 2, 3]}, {'name': 'b', 'values': [1, 2, 3]}])
        with self.assertRaises(ValueError):                          # 강조는 계열 1개일 때만
            mr.check_chart(two)
        with self.assertRaises(ValueError):                          # line 은 계열 1개
            mr.check_chart(dict(two, form='line', highlight=None))
        missing = good_chart()
        del missing['errors']
        with self.assertRaises(ValueError):
            mr.check_chart(missing)
        with self.assertRaises(mr.NoData):                           # 값이 하나도 없으면 그 그래프는 뺀다
            mr.check_chart(good_chart(series=[{'name': 'a', 'values': [None, None, None]}]))

    def test_pairs_use_units_not_unit(self):
        ok = good_chart(form='pairs', unit=None, units=['ms', 'ms', 'min'], highlight=None)
        mr.check_chart(ok)
        for over in (dict(unit='ms'), dict(units=['ms', 'ms']), dict(units=['ms', 'ms', 'hour'])):
            with self.assertRaises(ValueError):
                mr.check_chart(dict(ok, **over))


class ChartDataTests(unittest.TestCase):
    def test_cumulative_never_decreases_and_fills_empty_days(self):
        per_day = [('2026-09-14', 84), ('2026-09-08', 1832), ('2026-09-10', 67)]       # 순서가 섞여도
        days, values = mr.cumulative_by_day(per_day, date(2026, 9, 16))
        self.assertEqual(days[0], '2026-09-08')
        self.assertEqual(days[-1], '2026-09-16')
        self.assertEqual(len(days), 9)
        self.assertEqual(values[1], 1832)                     # 빈 날(9/9)은 앞 값 그대로
        self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))
        self.assertEqual(values[-1], 1832 + 67 + 84)
        self.assertEqual(mr.cumulative_by_day([], date(2026, 9, 16)), ([], []))

    def test_daily_new_has_30_days_including_zero_days(self):
        per_day = [('2026-09-08', 1832), ('2026-09-16', 69), ('2026-10-03', 51), ('2026-10-07', 60), ('2026-10-14', 45)]
        days, values = mr.daily_new(per_day, date(2026, 10, 15), 30)
        self.assertEqual(len(days), 30)
        self.assertEqual((days[0], days[-1]), ('2026-09-16', '2026-10-15'))
        self.assertEqual(values[days.index('2026-10-04')], 0)      # 연휴처럼 새 공고가 없는 날도 0으로 남는다
        self.assertEqual(values[-1], 0)
        self.assertEqual(sum(values), 69 + 51 + 60 + 45)            # 30일 밖(9/8)은 세지 않는다
        days, values = mr.daily_new([('2026-10-10', 5)], date(2026, 10, 15), 30)
        self.assertEqual(days[0], '2026-10-10')                       # 첫 수집일보다 앞 날짜는 넣지 않는다

    def test_daily_costs_skip_progress_lines(self):
        c = mr.daily_costs(RUN_LOG)
        self.assertAlmostEqual(c['2026-10-08'], 0.0155 + 0.279)      # 진행 줄(누적 금액)과 예상 줄은 빼고 저장 줄만
        self.assertEqual(c['2026-10-04'], 0.0)

    def test_cost_days_keep_zero_days_and_skip_estimates(self):
        days, values = mr.cost_days(RUN_LOG, 14)
        self.assertEqual(days, ['2026-09-29', '2026-10-04', '2026-10-08', '2026-10-09'])   # 비용 줄 생기기 전(9/28)은 빠짐
        self.assertEqual(values[1], 0.0)                              # 0인 날 포함
        self.assertAlmostEqual(values[2], 0.2945)                     # "예상 약 $" 줄은 더하지 않음
        self.assertIsNone(values[3])                                  # 배치는 돌았는데 비용 줄이 없으면 모름(0으로 짐작 안 함)
        many = ''.join('[2026-10-%02d 09:00:01] start (server)\n  추출 1건 · 약 $0.0010\n' % d for d in range(1, 21))
        days, values = mr.cost_days(many, 14)
        self.assertEqual(len(days), 14)
        self.assertEqual(days[-1], '2026-10-20')

    def test_batch_minutes_highlight_days_after_server_move(self):
        rows = [run('2026-09-28T08:55:00', elapsed=618), run('2026-10-02T09:05:15', elapsed=1294), run('2026-10-04T00:00:41', elapsed=41),
                run('2026-10-05T01:00:00', ks='dry-run', elapsed=3)]
        days, values, after = mr.batch_minutes(rows, TODAY)
        # 날짜가 이어진다(안 돈 날은 빈칸) — 오늘 배치가 없으면 어제까지
        self.assertEqual((days[0], days[-1], len(days)), ('2026-09-28', '2026-10-13', 16))
        self.assertEqual([v for v in values if v is not None], [10.3, 21.6, 0.7])
        self.assertIsNone(values[days.index('2026-10-01')])
        self.assertIsNone(values[days.index('2026-10-03')])
        # 강조는 서버에서 처음 돈 10/3부터 — 10/2 는 PC 의 밀린 실행이라 들어가지 않는다
        self.assertEqual(after, list(range(days.index('2026-10-03'), len(days))))
        self.assertNotIn(days.index('2026-10-02'), after)
        days, values, _ = mr.batch_minutes(rows + [run('2026-10-14T00:08:16', elapsed=494.6)], TODAY)
        self.assertEqual((days[-1], values[-1]), ('2026-10-14', 8.2))          # 오늘 배치가 있으면 오늘까지
        self.assertEqual(mr.batch_minutes([], TODAY), ([], [], []))

    def test_chart_values_keep_six_digits(self):
        """그래프 값은 넷째 자리로 줄이지 않는다 — 0.8235294 를 0.8235 로 줄이면 그리기 쪽에서 82.3%가 된다."""
        self.assertEqual(mr.r6(0.8235294117647058), 0.823529)
        self.assertEqual('%.1f' % (mr.r6(0.8235294117647058) * 100), '82.4')
        self.assertIsNone(mr.r6(None))


class BuildChartsTests(unittest.TestCase):
    FILES = {'c08_type_agreement': ['reports/label_pack_20260928/score.json'],
             'c13_bonus_by_persona': [],
             'c14_g01_all': [],
             'c15_latency': ['reports/metrics_20260930T105348/metrics.json'],
             'c20_test_count': ['reports/metrics_20260930T105348/metrics.json', 'reports/unit_test_20261007T062019Z/README.md',
                                'reports/unit_test_20261012T020731Z/README.md'],
             'c21_judge_agreement': [],
             'c22_reranker': ['ml/data/reranker_results.json'],
             'c23_age_classifier': ['ml/data/ml_experiments.json']}

    def build(self, ctx=None):
        said = []
        charts = mr.build_charts(ctx or fake_ctx(), say=said.append)
        return charts, said

    def expected_present(self, cid):
        if cid in ('c13_bonus_by_persona', 'c14_g01_all', 'c21_judge_agreement'):
            return bool(mr.latest({'c13_bonus_by_persona': 'bonus_boostable_*', 'c14_g01_all': 'notice_api_contract_*',
                                   'c21_judge_agreement': 'jev_judge_probe_*'}[cid]))
        return all(os.path.exists(os.path.join(ROOT, p)) for p in self.FILES.get(cid, []))

    def test_every_chart_keeps_contract(self):
        charts, said = self.build()
        ids = [c['id'] for c in charts]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [i for i in mr.CHART_IDS if i in ids])             # 계획 순서 그대로
        for cid in mr.CHART_IDS:
            if self.expected_present(cid):
                self.assertIn(cid, ids, '%s 빠짐: %s' % (cid, said))
        for c in charts:
            mr.check_chart(c)
            self.assertIn(c['form'], mr.CHART_FORMS)
            if c['form'] == 'pairs':
                self.assertTrue(all(u in mr.CHART_UNITS for u in c['units']))
            else:
                self.assertIn(c['unit'], mr.CHART_UNITS)
            for s in c['series']:
                self.assertEqual(len(s['values']), len(c['categories']))
            for i in c['highlight'] or []:
                self.assertTrue(0 <= i < len(c['categories']))
            self.assertEqual(mr.scrub(json.dumps(c, ensure_ascii=False))[0], 0, c['id'])   # 주소·키 파일 이름 없음
            self.assertNotIn('①', c['note'] + c['subtitle'] + c['title'])

    def test_values_follow_sources(self):
        charts = {c['id']: c for c in self.build()[0]}
        c01 = charts['c01_cumulative_notices']
        self.assertEqual(c01['categories'][0], '9/8')
        self.assertEqual(c01['categories'][-1], '10/14')
        self.assertEqual(c01['series'][0]['values'][-1], 1832 + 101 + 63 + 45)
        c02 = charts['c02_daily_new_notices']
        self.assertEqual(len(c02['categories']), 30)
        self.assertEqual(c02['categories'][-1], '10/14')                     # 오늘 공고가 있으면 오늘까지
        self.assertIn(0, c02['series'][0]['values'])
        c03 = charts['c03_notices_by_source']
        self.assertEqual(c03['categories'], ['누적', '지금 모집 중'])
        self.assertEqual([s['name'] for s in c03['series']], ['K-Startup', '기업마당'])
        self.assertEqual(c03['series'][1]['values'], [2468, 1520])
        c02 = charts['c02_daily_new_notices']
        self.assertIn('0인 날까지 넣은 30일 평균', c02['note'])                  # 한눈에 보기 평균(들어온 날만)과 함께
        c04 = charts['c04_batch_minutes']
        cats4 = c04['categories']
        self.assertEqual(c04['highlight'][0], cats4.index('10/3'))              # 서버에서 처음 돈 10/3부터 진하게
        self.assertNotIn(cats4.index('10/2'), c04['highlight'])                 # 10/2 는 PC 의 밀린 실행
        self.assertIn('0.7분', c04['note'])                                      # 서버 쪽 중앙값에 10/2(21.6분)가 섞이지 않는다
        self.assertIn('빈 동그라미', c04['subtitle'])
        self.assertNotIn('(이 PC 복사본(', c04['source'])                       # 출처 괄호는 한 겹
        c05 = charts['c05_attachment_extraction']
        self.assertEqual(c05['series'][0]['values'], [2265, 197, 6])
        self.assertIn('기업마당', c05['subtitle'])
        self.assertIn('K-Startup', c05['subtitle'])
        self.assertNotIn('활성', c05['subtitle'])
        c06 = charts['c06_apply_period_types']
        self.assertEqual(c06['categories'][0], '기간 고정')
        self.assertEqual(c06['series'][0]['values'], sorted(c06['series'][0]['values'], reverse=True))
        c07 = charts['c07_judgment_coverage']
        self.assertEqual(c07['series'][0]['values'], [0.91, 0.99, None, 0.72])     # 영역 3 지표 값 그대로, 못 잰 칸은 null
        self.assertEqual(c07['max'], 1)
        self.assertEqual(c07['categories'], ['자격요건(첨부 글자 있는 2,265건 중)', '신청자 유형(전체 3,072건 중)', '업종',
                                             '가점(열린 기업마당 1,548건 중)'])   # 막대마다 분모를 이름에
        self.assertIn('807건', c07['note'])
        self.assertIn('67%', c07['note'])                                        # 2,061 / 3,072 — 전체 공고 기준
        c09 = charts['c09_accuracy_before_after']
        self.assertEqual([s['name'] for s in c09['series']], ['지금 서비스', '처음(의미 검색만)'])   # 나중이 첫 계열(청록)
        self.assertEqual(c09['series'][0]['values'], [0.0, 0.6149, 0.7414, 0.3241])
        self.assertTrue(all(('좋음' in c) or ('참고' in c) for c in c09['categories']))     # 줄마다 좋은 방향
        self.assertIn('참고', c09['categories'][3])
        self.assertIn('같은 규칙', c09['note'])                                   # 신청 불가 0%의 단서
        self.assertNotIn('미판정은 낮을수록', c09['subtitle'])
        self.assertNotIn('P@3', c09['note'] + ' '.join(c09['categories']))
        c10 = charts['c10_status_timing']
        self.assertEqual(c10['series'][0]['values'], [0.6207, 0.6149, 0.5747])
        self.assertEqual(c10['series'][0]['name'], '상위 3건 적합(낮게 센 값)')
        self.assertNotIn('P@3', c10['subtitle'])
        self.assertEqual(c10['highlight'], [1])
        c11 = charts['c11_entity_block']
        self.assertEqual([s['name'] for s in c11['series']], ['차단 후', '차단 전'])
        self.assertEqual(c11['series'][1]['values'], [7, 2])
        self.assertIn('법인등록번호', c11['note'])
        c12 = charts['c12_bonus_steps']
        self.assertEqual(c12['series'][0]['values'], [1730, 305, 29])
        self.assertIn('30건', c12['note'])
        self.assertNotIn('사람이', c12['note'])                                  # 목록 30건은 모두 AI(Claude) 대조
        if mr.all_ai_reviewed(mr.read_json(os.path.join(ROOT, 'search', 'bonus_reviewed.json'))):
            self.assertIn('AI(Claude)', c12['note'])
        if os.path.exists(os.path.join(ROOT, 'reports', 'bonus_boostable_20261013T022836Z', 'results.json')):
            self.assertIn('27건은 목록에 있고', c12['note'])                     # 29건과 30건의 관계
            self.assertIn('2건은 아직 목록 밖 새 후보', c12['note'])
        if 'c14_g01_all' in charts:
            c14 = charts['c14_g01_all']
            self.assertIn('가상 신청자', c14['subtitle'])
            self.assertIn('통과 못 함 %s건' % format(c14['series'][1]['values'][0], ','), c14['note'])
        c16 = charts['c16_embedding_cpu_gpu']
        self.assertEqual((c16['form'], c16['unit'], c16['units']), ('pairs', None, ['ms', 'ms', 'min']))
        self.assertIn('공고 1건·검색어 1건은 ms, 전체 다시 만들기는 분', c16['subtitle'])   # 세 칸 중 두 칸은 같은 ms
        self.assertNotIn('항목마다 단위가 다름', c16['subtitle'])
        c17 = charts['c17_server_memory']
        self.assertEqual((c17['max'], c17['reference']), (4096, [{'value': 4096, 'label': '서버 메모리 4GB'}]))
        c18 = charts['c18_daily_ai_cost']
        self.assertEqual(c18['categories'], ['9/29', '10/4', '10/8', '10/9'])
        self.assertEqual(c18['series'][0]['values'][2], 0.2945)
        self.assertIn('자격요건 추출 제외', c18['title'])
        c19 = charts['c19_server_monthly_cost']
        self.assertEqual(c19['series'][0]['values'], [37.96, 472.31])
        self.assertIn('12배', c19['note'])
        if 'c15_latency' in charts:
            c15 = charts['c15_latency']
            self.assertEqual(c15['series'][0]['values'][1:], [300.0, None])   # 실제 서버는 못 잼 → null
            self.assertEqual(c15['series'][1]['values'][1], 450.0)
            self.assertEqual(c15['kind'], 'live')
            # 9/30 값은 조건(옛 검색 방식·그때 공고 수·그때 PC)이 달라 '빨라졌다'로 읽히지 않게
            self.assertIn('옛 검색 방식', c15['categories'][0])
            self.assertIn('공고 2,603건', c15['categories'][0])
            self.assertIn('빨라졌다고 말할 수 없다', c15['note'])
            self.assertNotIn('같은 조건', c15['note'] + c15['subtitle'])
            past = mr.past_pc_latency()
            if past:                                                      # 실행마다 달라진 폭도 출처 값으로
                runs = [v for _, v in past] + [300.04]
                self.assertIn('%.0f~%.0fms' % (min(runs), max(runs)), c15['note'])
                self.assertIn(past[0][0], c15['source'])
        if 'c20_test_count' in charts:
            c20 = charts['c20_test_count']
            self.assertEqual(c20['series'][0]['values'][:3], [686, 884, 965])
            self.assertEqual((c20['categories'][-1], c20['series'][0]['values'][-1]), ('지금(10/14)', 1080))
            self.assertIn('손으로', c20['subtitle'])                             # 저장소 CI 로 도는 것처럼 읽히지 않게
            self.assertIn('CI에는 아직 없음', c20['note'])
        if 'c21_judge_agreement' in charts:
            c21 = charts['c21_judge_agreement']
            self.assertIn('Jev(외부 채점 모델)', c21['categories'])
            self.assertEqual(c21['reference'], [{'value': 0.70, 'label': '기준 70%'}])
            if 'Codex(다른 표본)' in c21['categories']:
                self.assertEqual(c21['measured_at'], '2026-09-30')              # 가장 늦은 출처 날짜
                # 같은 쌍으로 잰 LLM·Jev 만 진하게 — 표본이 다른 Codex 는 회색
                self.assertEqual(c21['highlight'], [i for i, c in enumerate(c21['categories']) if not c.startswith('Codex')])
                self.assertIn('회색', c21['note'])
            else:
                self.assertIsNone(c21['highlight'])
        if 'c22_reranker' in charts:
            c22 = charts['c22_reranker']
            self.assertEqual(len(c22['errors']), len(c22['categories']))
            self.assertIn('단정할 수 없다', c22['note'])
            self.assertIn('견주지 않는다', c22['note'])
            self.assertTrue(c22['subtitle'].startswith(mr.ML_PREFIX))
            self.assertNotIn('당시 서비스)', ' '.join(c22['categories']))
            self.assertEqual(c22['max'], 1)
            sysd = mr.read_json(os.path.join(ROOT, 'ml', 'data', 'reranker_results.json'))['systems']
            i = [s['system'] for s in sysd].index('rrf+rerank (학습)')
            want = '%.1f' % (sysd[i]['p3_rec_ci95'][1] * 100)
            self.assertEqual('%.1f' % (c22['errors'][i][1] * 100), want)        # 두 번 반올림해 0.1%p 틀리지 않는다
        if 'c23_age_classifier' in charts:
            c23 = charts['c23_age_classifier']
            self.assertTrue(c23['subtitle'].startswith(mr.ML_PREFIX))
            self.assertIn('시연 화면에만', c23['note'])
            # 시험 83건 F1 만 그리면 순위가 확실해 보인다 — 교차검증 F1 을 함께 그린다
            m = mr.read_json(os.path.join(ROOT, 'ml', 'data', 'ml_experiments.json'))
            exps = m['experiments']
            self.assertEqual([s['name'] for s in c23['series']],
                             ['시험 F1(%d건)' % m['n_test'], '교차검증 F1(학습 %d건)' % m['n_train']])
            self.assertEqual(c23['series'][1]['values'], [mr.r6(e['cv_f1_mean']) for e in exps])
            self.assertIsNone(c23['highlight'])                                 # 계열 둘 — 고른 것은 이름에 표시
            marked = [i for i, c in enumerate(c23['categories']) if c.endswith('(고른 것)')]
            self.assertEqual(marked, [[e['exp'] for e in exps].index(m['chosen'])])
            full = [e for e in exps if e['coverage'] >= 0.999]
            if max(full, key=lambda e: e['f1']) is not max(full, key=lambda e: e['cv_f1_mean']):
                self.assertIn('단정할 수 없다', c23['note'])
            self.assertIn('정밀도', c23['note'])                               # 고른 기준
            self.assertNotIn('진한 막대', c23['note'])

    def test_not_measured_now_stays_null_or_left_out(self):
        ctx = fake_ctx()
        ctx['raw'] = {}
        ctx['metrics'] = dict(ctx['metrics'])
        del ctx['metrics']['자동 테스트 수']
        charts = {c['id']: c for c in self.build(ctx)[0]}
        if 'c15_latency' in charts:
            c15 = charts['c15_latency']
            self.assertEqual(c15['series'][0]['values'][1:], [None, None])
            self.assertEqual((c15['kind'], c15['measured_at']), ('record', '2026-09-30'))
            self.assertIn('옛 검색 방식', c15['note'])
            self.assertNotIn('지난 실행', c15['source'])                       # 이번에 안 쟀으면 실행 간 비교도 없음
        if 'c20_test_count' in charts:
            self.assertNotIn('지금', ' '.join(charts['c20_test_count']['categories']))
            self.assertEqual(charts['c20_test_count']['kind'], 'record')

    def test_one_failing_chart_drops_only_itself(self):
        def c90_boom(ctx):
            raise ConnectionError('host 43.201.90.238 refused')

        def c91_empty(ctx):
            raise mr.NoData('값 없음')

        def c92_ok(ctx):
            return good_chart(id='c92_ok')

        said = []
        charts = mr.build_charts({}, builders=(c90_boom, c91_empty, c92_ok), say=said.append)
        self.assertEqual([c['id'] for c in charts], ['c92_ok'])
        self.assertEqual(len(said), 2)
        self.assertIn('c90_boom', said[0])
        self.assertIn('ConnectionError', said[0])
        self.assertNotIn('43.201', ' '.join(said))                   # 예외 원문(주소)은 쓰지 않는다

    def test_missing_db_parts_drop_db_charts_only(self):
        ctx = fake_ctx()
        ctx['db'] = {}
        charts, said = self.build(ctx)
        ids = {c['id'] for c in charts}
        for cid in ('c01_cumulative_notices', 'c02_daily_new_notices', 'c03_notices_by_source', 'c05_attachment_extraction',
                    'c06_apply_period_types'):
            self.assertNotIn(cid, ids)
            self.assertTrue(any(cid in s for s in said))
        self.assertIn('c04_batch_minutes', ids)


class ChartOutputTests(unittest.TestCase):
    def test_write_scrubs_charts_and_lists_them_in_summary(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            c = good_chart(source='http://43.201.90.238:8000/api/match · key sbrain-web.pem')
            data = {'run_at': '2026-10-14T20:00:00+09:00', 'conditions': [], 'metrics': [], 'headline': [], 'missing': [], 'charts': [c]}
            out = mr.write(data, os.path.join(tmp, 'out'))
            text = mr.read_text(os.path.join(tmp, 'out', 'metrics.json'))
            self.assertNotIn('43.201', text)
            self.assertNotIn('.pem', text)
            saved = json.loads(text)
            self.assertEqual(list(saved), ['run_at', 'conditions', 'metrics', 'headline', 'missing', 'charts'])
            self.assertEqual(saved['charts'][0]['series'], c['series'])
            self.assertEqual(out['charts'][0]['id'], 'c99_test')
            self.assertIn('## 그래프 1개', mr.read_text(os.path.join(tmp, 'out', 'summary.md')))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
