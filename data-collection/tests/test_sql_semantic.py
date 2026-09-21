# -*- coding: utf-8 -*-
r"""정형 필터 + 의미 검색 실험 테스트 — 지시서 8절의 필수 항목.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_sql_semantic -v

**외부 DB·모델을 부르지 않는다.** 가짜 연결과 가짜 모델로 확인한다.
여기 통과했다고 실제 데이터가 맞다는 뜻은 아니다(지시서 8절).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from datetime import date
from unittest.mock import patch

import numpy as np

from experiments.sql_semantic import conditions, config, embedding, search
from search import gate


def notice(**kw):
    row = {'notice_id': 'n001', 'source': 'test', 'title': '공고', 'body': '',
           'target_text': '', 'target_category': '중소기업', 'category': '창업',
           'subcategory': '', 'organizer': '', 'region': '전국',
           'age_condition_raw': '', 'apply_start': '2026-01-01', 'apply_end': '2026-12-31',
           'apply_period_type': 'fixed', 'recruitment_status': 'open', 'url': ''}
    row.update(kw)
    return row


class ConfigGuardTests(unittest.TestCase):
    """소스 DB 로 새지 않는지. 이 실험은 쓰기를 하므로 가장 먼저 막는다."""

    SOURCE = {'host': '43.0.0.1', 'port': 3306, 'database': 's_brain'}

    def test_missing_settings_refuses_instead_of_falling_back(self):
        with patch.object(config.pipeline_config, 'get', lambda name, default=None: default):
            with self.assertRaises(config.LabConfigError) as caught:
                config.lab_settings()
        self.assertIn('SQL_LAB_HOST', str(caught.exception))

    def test_remote_host_is_rejected(self):
        lab = {'host': '43.0.0.1', 'port': 3306, 'user': 'u', 'password': 'p', 'database': 'lab'}
        with self.assertRaises(config.LabConfigError):
            config.guard(lab, self.SOURCE)

    def test_same_database_name_is_rejected(self):
        lab = {'host': '127.0.0.1', 'port': 3306, 'user': 'u', 'password': 'p',
               'database': 's_brain'}
        with self.assertRaises(config.LabConfigError):
            config.guard(lab, self.SOURCE)

    def test_local_and_separate_is_allowed(self):
        lab = {'host': '127.0.0.1', 'port': 3306, 'user': 'u', 'password': 'p',
               'database': 'notice_match_sql_lab'}
        self.assertTrue(config.guard(lab, self.SOURCE))

    def test_describe_hides_password(self):
        lab = {'host': '127.0.0.1', 'port': 3306, 'user': 'u', 'password': 'secret',
               'database': 'notice_match_sql_lab'}
        text = str(config.describe(lab, self.SOURCE))
        self.assertNotIn('secret', text)


class ConditionTests(unittest.TestCase):
    """값 없음과 제한 없음을 뭉개지 않는지."""

    def test_region_nationwide_is_no_limit(self):
        self.assertEqual(conditions.region_condition(notice(region='전국'))['status'], 'no_limit')

    def test_region_multiple_kept(self):
        row = conditions.region_condition(notice(region='경기,대구'))
        self.assertEqual(row['status'], 'known')
        self.assertEqual(row['value_text'], '경기,대구')

    def test_region_missing_is_unknown(self):
        self.assertEqual(conditions.region_condition(notice(region=''))['status'], 'unknown')

    def test_age_bounds_and_prestartup(self):
        row = conditions.business_age_condition(notice(age_condition_raw='7년미만'))
        self.assertEqual(row['status'], 'known')
        self.assertEqual(row['value_max'], 84)
        self.assertIn('max_exclusive_months', row['bound_note'])
        only = conditions.business_age_condition(notice(age_condition_raw='예비창업자'))
        self.assertEqual(only['bound_note'], 'prestartup_only')

    def test_age_missing_is_unknown(self):
        self.assertEqual(conditions.business_age_condition(notice())['status'], 'unknown')

    def test_period_rolling_is_no_limit_not_unknown(self):
        row = conditions.period_condition(notice(apply_end=None, apply_period_type='rolling'))
        self.assertEqual(row['status'], 'no_limit')
        unknown = conditions.period_condition(notice(apply_end=None, apply_period_type='unknown'))
        self.assertEqual(unknown['status'], 'unknown')

    def test_size_and_industry_missing_are_unknown(self):
        row = notice(target_category='', target_text='', title='공고', category='', subcategory='')
        self.assertEqual(conditions.company_size_condition(row)['status'], 'unknown')
        self.assertEqual(conditions.industry_condition(row)['status'], 'unknown')

    def test_amount_ignores_total_budget(self):
        self.assertEqual(
            conditions.support_amount_condition(notice(body='총사업비 30억원 규모'))['status'],
            'unknown')
        row = conditions.support_amount_condition(notice(body='기업당 최대 5,000만원 지원'))
        self.assertEqual(row['value_max'], 50_000_000)

    def test_purpose_is_not_industry(self):
        row_ = notice(category='기술', target_text='제조업을 영위하는 중소기업만 신청 가능')
        self.assertEqual(conditions.purpose_condition(row_)['value_text'], '기술')
        industry = conditions.industry_condition(row_)
        self.assertEqual(industry['status'], 'known')
        self.assertEqual(industry['value_text'], '제조업')

    def test_industry_without_limit_wording_is_unknown(self):
        row_ = notice(category='기술', target_text='제조 분야 지원사업')
        self.assertEqual(conditions.industry_condition(row_)['status'], 'unknown')

    def test_industry_missing_is_unknown(self):
        row_ = notice(target_text='', target_category='')
        self.assertEqual(conditions.industry_condition(row_)['status'], 'unknown')


class F1RegressionTests(unittest.TestCase):
    """자격 문구 오해석 (2026-09-18 Codex 리뷰 F1) 의 최소 반례.

    수정 전에는 두 건 모두 **신청할 수 있는 사람을 떨어뜨리는** 값이 나왔다.
    이 검사들을 지우지 말 것 — 단어만 보고 제한으로 단정하는 코드가 다시 들어오면 여기서 깨진다.
    """

    def test_no_limit_wording_is_not_a_size_restriction(self):
        """'제목에 대기업' + '규모 제한 없음' → 대기업 전용으로 읽지 않는다."""
        row = notice(title='대기업과 함께하는 기술교류', target_category='',
                     target_text='기업 규모 제한 없이 모든 기업 신청 가능')
        size = conditions.company_size_condition(row)
        self.assertEqual(size['status'], 'no_limit')
        self.assertNotEqual(size.get('value_text'), '대기업')

    def test_excluded_industry_does_not_become_the_allow_list(self):
        """'제조업은 제외' → '제조업만 가능' 으로 뒤집지 않는다."""
        row = notice(target_category='',
                     target_text='제조업을 영위하는 기업은 제외하며 그 외 업종은 모두 신청 가능')
        industry = conditions.industry_condition(row)
        self.assertNotEqual(industry['status'], 'known')
        self.assertIsNone(industry['value_text'])
        self.assertTrue(industry['evidence'])        # 왜 모르는지 근거는 남긴다

    def test_title_alone_never_becomes_the_allow_list(self):
        """제목·사업 분류는 자격 문구가 아니다. 제목의 '대기업'이 허용 목록이 되면 안 된다.

        지원대상은 중소기업이지만 제목이 다른 규모를 말한다 → 목록이 전부라고 단정하지 않고
        확인 필요로 남긴다. 어느 쪽으로도 잘못 탈락시키지 않는 선택이다.
        """
        row = notice(title='대기업 협력 프로그램', category='대기업 동반성장',
                     target_category='중소기업', target_text='중소기업')
        size = conditions.company_size_condition(row)
        self.assertEqual(size['status'], 'unknown')
        self.assertIsNone(size['value_text'])

    def test_positive_and_negative_in_one_sentence(self):
        """'중소기업만 신청 가능, 대기업은 제외' → 허용은 중소기업뿐이다."""
        row = notice(target_category='', target_text='중소기업만 신청 가능, 대기업은 제외')
        self.assertEqual(conditions.company_size_condition(row)['value_text'], '중소기업')

    def test_other_field_mentions_another_size_so_the_list_is_not_trusted(self):
        """실제 공고 반례: 제목 '소상공인 경영안정자금' · target_category '중소기업'.

        지원대상 칸만 믿으면 중소기업 전용이 되어 소상공인을 떨어뜨린다. 좁히지 말고 확인 필요로 남긴다.
        """
        row = notice(title='[대전] 서구 2026년 소상공인 경영안정자금 지원사업 공고',
                     target_category='중소기업', target_text='', category='금융')
        size = conditions.company_size_condition(row)
        self.assertEqual(size['status'], 'unknown')
        self.assertIn('소상공인', size['evidence'])

    def test_partner_company_is_not_the_applicant(self):
        """실제 공고 반례(kstartup:179258): '대기업·중견기업과 계약 실적을 보유한 기업'.

        여기서 대기업은 **거래 상대**다. 신청자가 대기업이라는 뜻이 아니다.
        이것을 자격으로 읽으면 중소기업 신청자가 떨어진다.
        """
        row = notice(target_category='', target_text=(
            '다음 요건을 충족하는 B2B 기업\n'
            '대기업·중견기업 또는 공공기관과 1건 이상의 계약 실적을 보유한 기업\n'
            '※ 당장 특정 연결 수요가 없더라도 향후 대기업·공공기관 판로 확대를 계획'))
        self.assertEqual(conditions.company_size_condition(row)['status'], 'unknown')

    def test_exclusion_line_narrows_the_list_on_purpose(self):
        """'스타트업 대상 … ※ 대기업 제외' → 스타트업만 남는다. 이건 맞는 좁힘이다."""
        row = notice(target_category='',
                     target_text='위치정보 산업에 진출하려는 스타트업\n※ 대기업 제외')
        size = conditions.company_size_condition(row)
        self.assertEqual(size['value_text'], '스타트업')

    # ---- 다른 조건의 '제한 없음' 이 새어 들어오지 않는지 (2026-09-21 Codex F1 리뷰 P1)

    def fields(self, text):
        row = notice(target_category='', target_text=text, title='', category='')
        return {c['field']: c for c in conditions.build(row)}

    def test_industry_free_does_not_free_the_size(self):
        """'업종 제한 없이 중소기업만' → 규모는 중소기업, 대기업 신청자는 불충족."""
        got = self.fields('업종 제한 없이 중소기업만 신청 가능')
        self.assertEqual(got['company_size']['value_text'], '중소기업')
        self.assertEqual(got['industry']['status'], 'no_limit')
        row = {'size_status': got['company_size']['status'],
               'size_value': got['company_size']['value_text']}
        verdict, _ = search.judge_list(row, {'company_size': '대기업'}, 'size_status',
                                       'size_value', 'company_size', '기업 규모')
        self.assertEqual(verdict, search.NO)

    def test_size_free_does_not_free_the_industry(self):
        """'기업 규모 제한 없이 제조업만' → 업종은 제조업, 서비스업 신청자는 불충족."""
        got = self.fields('기업 규모 제한 없이 제조업을 영위하는 기업만 신청 가능')
        self.assertEqual(got['company_size']['status'], 'no_limit')
        self.assertEqual(got['industry']['value_text'], '제조업')
        row = {'industry_status': got['industry']['status'],
               'industry_value': got['industry']['value_text']}
        verdict, _ = search.judge_list(row, {'industry': '서비스업'}, 'industry_status',
                                       'industry_value', 'industry', '업종')
        self.assertEqual(verdict, search.NO)

    def test_age_free_frees_neither(self):
        got = self.fields('업력 무관, 제조업을 영위하는 중소기업만 신청 가능')
        self.assertEqual(got['company_size']['value_text'], '중소기업')
        self.assertEqual(got['industry']['value_text'], '제조업')

    def test_size_free_with_industry_exclusion(self):
        got = self.fields('기업 규모 제한 없이 모든 기업 신청 가능. 제조업은 제외')
        self.assertEqual(got['company_size']['status'], 'no_limit')
        self.assertEqual(got['industry']['status'], 'unknown')

    def test_region_or_age_free_is_not_size_or_industry_free(self):
        """실제 공고 표현(kstartup:176755·179297 등): 지역·연령 제한 없음, '누구나'."""
        for text in ('창업기업 지역 제한 없음', '연령제한 없음 누구나 신청 가능',
                     '지역 관계없이 신청 가능', '누구나 신청 가능', '모든 기업 신청 가능'):
            got = self.fields(text)
            self.assertNotEqual(got['company_size']['status'], 'no_limit', text)
            self.assertNotEqual(got['industry']['status'], 'no_limit', text)

    def test_same_field_free_and_restriction_is_not_decided(self):
        """같은 필드에 '제한 없음' 과 '중소기업만' 이 함께 있으면 단정하지 않는다."""
        got = self.fields('기업 규모 제한 없음. 단 중소기업만 신청 가능')
        self.assertEqual(got['company_size']['status'], 'unknown')

    def test_plain_positive_statement_still_works(self):
        """고치면서 정상 추출까지 죽이지 않았는지. 평범한 지원대상은 그대로 known 이다."""
        row = notice(target_category='중소기업', target_text='경기도 소재 중소기업')
        self.assertEqual(conditions.company_size_condition(row)['status'], 'known')

    def test_no_limit_counts_as_met_not_unknown(self):
        """'제한 없음' 은 신청자 값을 몰라도 충족이다. 확인 필요로 미루지 않는다."""
        row = {'size_status': 'no_limit', 'size_value': '제한 없음'}
        verdict, why = search.judge_list(row, {}, 'size_status', 'size_value',
                                         'company_size', '기업 규모')
        self.assertEqual(verdict, search.OK)
        self.assertIn('제한 없음', why)

    def test_unknown_still_needs_a_human_check(self):
        row = {'size_status': 'unknown', 'size_value': None}
        verdict, _why = search.judge_list(row, {'company_size': '중소기업'}, 'size_status',
                                          'size_value', 'company_size', '기업 규모')
        self.assertEqual(verdict, search.CHECK)

    def test_coverage_counts(self):
        rows = conditions.build(notice()) + conditions.build(notice(region=''))
        cover = conditions.coverage(rows)
        self.assertEqual(cover['region']['total'], 2)
        self.assertEqual(cover['region']['unknown'], 1)


class FilterTests(unittest.TestCase):
    """SQL 은 확실한 불일치만 제외한다. 값은 파라미터로 넘긴다."""

    def test_sql_uses_parameters_only(self):
        sql, params = search.build_filter({'region': '경기'}, date(2026, 9, 18))
        self.assertNotIn('경기', sql)
        self.assertIn('경기', params)
        self.assertIn('%s', sql)

    def test_region_filter_keeps_unknown_and_nationwide(self):
        sql, _ = search.build_filter({'region': '경기'}, date(2026, 9, 18))
        self.assertIn("c_region.status <> 'known'", sql)   # 모르면 남긴다
        self.assertIn('FIND_IN_SET', sql)

    def test_parameter_order_matches_sql(self):
        # 물음표는 SQL 에 나온 순서대로 채워진다. 계약은 LEFT JOIN 안이라 WHERE 보다 앞이다.
        # 실제 DB 에서 "Incorrect DATE value: '경기'" 로 드러난 버그의 회귀 테스트다.
        sql, params = search.build_filter({'region': '경기'}, date(2026, 9, 18))
        self.assertEqual(params[0], embedding.CONTRACT)
        self.assertEqual(params[1], '2026-09-18')
        self.assertEqual(params[2], '경기')
        self.assertEqual(sql.count('%s'), len(params))
        self.assertLess(sql.index('v.contract = %s'), sql.index('WHERE'))

    def test_placeholder_count_matches_params_without_region(self):
        sql, params = search.build_filter({'region': ''}, date(2026, 9, 18))
        self.assertEqual(sql.count('%s'), len(params))

    def test_no_region_means_no_region_clause(self):
        sql, params = search.build_filter({'region': ''}, date(2026, 9, 18))
        self.assertNotIn('FIND_IN_SET', sql)
        self.assertEqual(len(params), 2)                  # as_of + contract

    def test_expired_only_excluded_when_end_date_exists(self):
        sql, _ = search.build_filter({}, date(2026, 9, 18))
        self.assertIn('n.apply_end IS NULL OR n.apply_end >= %s', sql)


class VerdictTests(unittest.TestCase):
    """세 값(충족·불충족·확인 필요)으로 다루는지."""

    AS_OF = date(2026, 9, 18)

    def test_unknown_age_is_check_not_reject(self):
        verdict, _ = search.judge_age({'age_status': 'unknown'}, 24)
        self.assertEqual(verdict, search.CHECK)

    def test_age_boundary_is_exclusive(self):
        row = {'age_status': 'known', 'age_max': 84, 'age_bound': 'max_exclusive_months'}
        self.assertEqual(search.judge_age(row, 83)[0], search.OK)
        self.assertEqual(search.judge_age(row, 84)[0], search.NO)

    def test_prestartup_rules(self):
        only = {'age_status': 'known', 'age_max': 0, 'age_bound': 'prestartup_only'}
        self.assertEqual(search.judge_age(only, None)[0], search.OK)
        self.assertEqual(search.judge_age(only, 24)[0], search.NO)
        no_pre = {'age_status': 'known', 'age_max': 84,
                  'age_bound': 'max_exclusive_months_no_prestartup'}
        self.assertEqual(search.judge_age(no_pre, None)[0], search.NO)

    def test_unknown_founded_date_is_check(self):
        row = {'age_status': 'known', 'age_max': 84, 'age_bound': 'max_exclusive_months'}
        self.assertEqual(search.judge_age(row, gate.UNKNOWN_AGE)[0], search.CHECK)

    def test_region_verdicts(self):
        self.assertEqual(search.judge_region({'region_status': 'no_limit'}, {'region': '경기'})[0],
                         search.OK)
        self.assertEqual(search.judge_region({'region_status': 'unknown'}, {'region': '경기'})[0],
                         search.CHECK)
        self.assertEqual(search.judge_region({'region_status': 'known', 'region_value': '경기,대구'},
                                             {'region': '경기'})[0], search.OK)
        self.assertEqual(search.judge_region({'region_status': 'known', 'region_value': '서울'},
                                             {'region': '경기'})[0], search.NO)
        self.assertEqual(search.judge_region({'region_status': 'known', 'region_value': '서울'},
                                             {'region': ''})[0], search.CHECK)

    def test_period_verdicts(self):
        self.assertEqual(search.judge_period({'apply_end': '2026-09-30'}, self.AS_OF)[0], search.OK)
        self.assertEqual(search.judge_period({'apply_end': '2026-09-17'}, self.AS_OF)[0], search.NO)
        self.assertEqual(search.judge_period({'apply_end': None, 'apply_period_type': 'rolling'},
                                             self.AS_OF)[0], search.OK)
        self.assertEqual(search.judge_period({'apply_end': None, 'apply_period_type': 'unknown'},
                                             self.AS_OF)[0], search.CHECK)


class VectorTests(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        vector = np.arange(8, dtype='float32') / 8
        back = embedding.unpack(embedding.pack(vector), 8)
        self.assertTrue(np.allclose(vector, back))

    def test_wrong_dimension_raises(self):
        with self.assertRaises(ValueError):
            embedding.unpack(embedding.pack(np.zeros(8, dtype='float32')), 1024)

    def test_nan_raises(self):
        bad = np.array([1.0, float('nan'), 0.0], dtype='float32')
        with self.assertRaises(ValueError):
            embedding.unpack(embedding.pack(bad), 3)

    def test_cosine_matches_manual(self):
        q = np.array([1.0, 0.0], dtype='float32')
        m = np.array([[1.0, 0.0], [0.0, 1.0], [0.7071, 0.7071]], dtype='float32')
        got = embedding.cosine(q, m)
        self.assertAlmostEqual(float(got[0]), 1.0, places=4)
        self.assertAlmostEqual(float(got[1]), 0.0, places=4)
        self.assertAlmostEqual(float(got[2]), 0.7071, places=3)

    def test_input_contract_order_and_hash(self):
        text, sources = embedding.build_input(notice(title='제목', category='분야',
                                                     body='내용', target_text='자격'))
        self.assertEqual(text.splitlines()[0], '제목: 제목')
        self.assertEqual(text.splitlines()[1], '지원 분야: 분야')
        self.assertEqual(text.splitlines()[2], '지원 내용: 내용')
        self.assertEqual(text.splitlines()[3], '신청 자격: 자격')
        self.assertIn('본문 사용', sources['지원 내용'])
        self.assertEqual(embedding.input_sha256(text), embedding.input_sha256(text))


class FakeCursor:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log
        self.description = [(k,) for k in (rows[0] if rows else {})]

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchall(self):
        return [tuple(r.values()) for r in self.rows]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConnection:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def cursor(self):
        return FakeCursor(self.rows, self.log)

    def close(self):
        pass


def row(notice_id, vector, **kw):
    """검색이 보는 한 줄. 저장 벡터가 지금 내용으로 만들어진 것처럼 해시를 맞춰 둔다."""
    meta = embedding.meta()
    base = {'notice_id': notice_id, 'title': notice_id, 'url': '', 'apply_start': '2026-01-01',
            'apply_end': '2026-12-31', 'apply_period_type': 'fixed',
            'region_status': 'no_limit', 'region_value': '전국',
            'age_status': 'unknown', 'age_max': None, 'age_bound': None, 'age_text': None,
            'size_status': 'unknown', 'size_value': None,
            'industry_status': 'unknown', 'industry_value': None,
            'type_status': 'unknown', 'type_value': None,
            'body': '내용', 'target_text': '자격', 'target_category': '중소기업',
            'category': '창업', 'subcategory': '',
            'vector': embedding.pack(np.asarray(vector, dtype='float32')),
            'dim': len(vector), 'dtype': meta['dtype'], 'normalized': 1,
            'model': meta['model'], 'model_revision': meta['model_revision'],
            'contract': meta['contract']}
    base.update(kw)
    text, _ = embedding.build_input(base)
    base.setdefault('input_sha256', embedding.input_sha256(text))
    if 'input_sha256' not in kw:
        base['input_sha256'] = embedding.input_sha256(text)
    return base


class RunTests(unittest.TestCase):
    """SQL 통과 후보만 유사도 계산에 들어가는지, 누락을 조용히 버리지 않는지."""

    def setUp(self):
        # 리비전을 고정한다. 이 PC 의 모델 캐시 유무로 결과가 달라지지 않게 (F2 검사가 리비전을 본다)
        patcher = patch.object(embedding, 'model_revision', lambda: 'test-revision')
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_search(self, rows, applicant=None, **kw):
        applicant = applicant or {'idea': '창업 지원', 'region': '', 'founded_at': '2025-01-01'}
        connection = FakeConnection(rows)
        model = object()
        with patch.object(embedding, 'encode',
                          lambda m, texts, **kwargs: np.array([[1.0, 0.0]], dtype='float32')):
            out = search.run(applicant, as_of=date(2026, 9, 18), connection=connection,
                             model=model, **kw)
        return out, connection

    def test_only_candidates_are_compared(self):
        rows = [row('keep', [1.0, 0.0]),
                row('drop', [1.0, 0.0], region_status='known', region_value='서울',
                    apply_end='2026-12-31')]
        out, _ = self.run_search(rows, {'idea': 'x', 'region': '경기', 'founded_at': '2025-01-01'})
        self.assertEqual(out['counts']['after_conditions'], 1)
        self.assertEqual([r['notice_id'] for r in out['results']], ['keep'])
        self.assertEqual(out['dropped_examples'][0]['fields'], ['region'])

    def test_missing_vector_is_reported_not_silent(self):
        rows = [row('a', [1.0, 0.0]), dict(row('b', [1.0, 0.0]), vector=None)]
        out, _ = self.run_search(rows)
        self.assertEqual(out['counts']['missing_vector'], 1)
        self.assertIn('b', out['missing_vector_examples'])

    def test_broken_vector_is_reported(self):
        bad = dict(row('bad', [1.0, 0.0]), dim=1024)      # 저장 길이와 dim 이 다르다
        out, _ = self.run_search([row('ok', [1.0, 0.0]), bad])
        self.assertEqual(out['counts']['broken_vector'], 1)

    def test_fewer_than_top_returns_actual_count(self):
        out, _ = self.run_search([row('only', [1.0, 0.0])], top=5)
        self.assertEqual(out['counts']['returned'], 1)

    def test_zero_candidates_returns_zero(self):
        rows = [row('x', [1.0, 0.0], region_status='known', region_value='서울')]
        out, _ = self.run_search(rows, {'idea': 'x', 'region': '경기', 'founded_at': '2025-01-01'})
        self.assertEqual(out['counts']['returned'], 0)
        self.assertEqual(out['results'], [])

    def test_no_filter_mode_keeps_everything(self):
        rows = [row('a', [1.0, 0.0]), row('b', [1.0, 0.0], region_status='known',
                                          region_value='서울')]
        out, _ = self.run_search(rows, {'idea': 'x', 'region': '경기', 'founded_at': '2025-01-01'},
                                 use_filter=False)
        self.assertEqual(out['counts']['after_conditions'], 2)

    def test_needs_check_is_recorded(self):
        out, _ = self.run_search([row('a', [1.0, 0.0])],
                                 {'idea': 'x', 'region': '', 'founded_at': '2025-01-01'})
        self.assertIn('region', out['results'][0]['needs_check'])

    def test_experiment_never_writes(self):
        _out, connection = self.run_search([row('a', [1.0, 0.0])])
        for sql, _params in connection.log:
            self.assertTrue(sql.strip().upper().startswith('SELECT'), sql[:40])


class ReviewRegressionTests(RunTests):
    """2026-09-18 Codex 리뷰 1~4번 회귀."""

    def test_stale_vector_is_excluded_and_reported(self):
        # 리뷰 2번 — 공고 내용이 바뀌었는데 벡터가 그대로면 쓰지 않는다
        stale = row('stale', [1.0, 0.0], input_sha256='obsolete-input-hash')
        out, _ = self.run_search([row('fresh', [1.0, 0.0]), stale])
        self.assertEqual(out['counts']['stale_vector'], 1)
        self.assertEqual([r['notice_id'] for r in out['results']], ['fresh'])

    def test_other_model_vector_is_stale(self):
        other = row('other', [1.0, 0.0], model='다른모델')
        out, _ = self.run_search([row('ok', [1.0, 0.0]), other])
        self.assertEqual(out['counts']['stale_vector'], 1)

    def test_mixed_dimension_does_not_break_whole_search(self):
        # 리뷰 3번 — 차원이 다른 한 건 때문에 전체가 실패하면 안 된다
        out, _ = self.run_search([row('good', [1.0, 0.0]), row('odd', [1.0, 0.0, 0.0])])
        self.assertEqual(out['counts']['broken_vector'], 1)
        self.assertEqual([r['notice_id'] for r in out['results']], ['good'])

    def test_upcoming_notice_is_not_ok(self):
        # 리뷰 4번 — 접수 시작 전인데 '충족' 이라고 말하지 않는다
        upcoming = row('soon', [1.0, 0.0], apply_start='2026-10-01', apply_end='2026-10-31')
        out, _ = self.run_search([upcoming])
        checks = out['results'][0]['conditions']['application_period']
        self.assertEqual(checks['verdict'], 'check')
        self.assertIn('예정', checks['why'])

    def test_company_size_mismatch_is_excluded(self):
        # 리뷰 1번 — 규모가 명시된 공고와 신청자 규모가 다르면 제외한다
        small = row('small', [1.0, 0.0], size_status='known', size_value='중소기업')
        out, _ = self.run_search([small], {'idea': 'x', 'region': '', 'founded_at': '2025-01-01',
                                           'company_size': '대기업'})
        self.assertEqual(out['counts']['returned'], 0)
        self.assertEqual(out['dropped_examples'][0]['fields'], ['company_size'])

    def test_company_size_missing_input_is_check(self):
        small = row('small', [1.0, 0.0], size_status='known', size_value='중소기업')
        out, _ = self.run_search([small])
        self.assertIn('company_size', out['results'][0]['needs_check'])

    def test_industry_mismatch_is_excluded(self):
        maker = row('maker', [1.0, 0.0], industry_status='known', industry_value='제조업')
        out, _ = self.run_search([maker], {'idea': 'x', 'region': '', 'founded_at': '2025-01-01',
                                           'industry': '서비스업'})
        self.assertEqual(out['counts']['returned'], 0)

    def test_industry_unknown_keeps_candidate(self):
        out, _ = self.run_search([row('a', [1.0, 0.0])],
                                 {'idea': 'x', 'region': '', 'founded_at': '2025-01-01',
                                  'industry': '제조업'})
        self.assertEqual(out['counts']['returned'], 1)
        self.assertIn('industry', out['results'][0]['needs_check'])


class RankTests(unittest.TestCase):
    def test_similarity_then_id(self):
        rows = [row('b', [1, 0]), row('a', [1, 0]), row('c', [1, 0])]
        ordered = search.rank(rows, [0.5, 0.5, 0.9], {})
        self.assertEqual([o['row']['notice_id'] for o in ordered], ['c', 'a', 'b'])

    def test_preference_comes_first_with_reason(self):
        rows = [row('plain', [1, 0]), row('pref', [1, 0], type_status='known',
                                          type_value='보조금,교육')]
        ordered = search.rank(rows, [0.9, 0.1], {'preferred_support_type': '보조금'})
        self.assertEqual(ordered[0]['row']['notice_id'], 'pref')
        self.assertIn('보조금', ordered[0]['rank_reason'])

    def test_no_preference_falls_back_to_similarity(self):
        rows = [row('a', [1, 0]), row('b', [1, 0])]
        ordered = search.rank(rows, [0.1, 0.9], {})
        self.assertEqual(ordered[0]['row']['notice_id'], 'b')
        self.assertEqual(ordered[0]['rank_reason'], '유사도 순')


if __name__ == '__main__':
    unittest.main()


class ReextractTests(unittest.TestCase):
    """저장된 공고로 조건만 다시 뽑는 경로 (2026-09-21).

    소스(EC2)를 부르지 않는지, 덮어쓰기 전에 백업하는지, 백업이 모자라면 멈추는지 본다.
    """

    class Cursor:
        def __init__(self, conn):
            self.conn = conn
            self.description = None
            self._rows = []

        def execute(self, sql, params=None):
            self.conn.log.append(sql)
            if sql.startswith('SELECT COUNT(*) FROM lab_conditions'):
                self._rows = [(self.conn.original,)]
            elif sql.startswith('SELECT COUNT(*) FROM `lab_conditions_bak_'):
                self._rows = [(self.conn.copied,)]
            elif sql.startswith('SELECT notice_id, field'):
                self._rows = [('n1', 'company_size', 'known', '대기업', 'sql_lab_v1')]
            elif sql.startswith('SELECT notice_id,title'):
                from experiments.sql_semantic import prepare
                self.description = [(k,) for k in prepare.STORED_FIELDS]
                self._rows = [('n1', '대기업과 함께하는 기술교류', '', '기업 규모 제한 없이 모든 기업 신청 가능',
                               '', '기술', '', '전국', '', None, None, 'rolling')]
            else:
                self._rows = []

        def fetchone(self):
            return self._rows[0]

        def fetchall(self):
            return self._rows

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Conn:
        def __init__(self, original=9, copied=9):
            self.original, self.copied = original, copied
            self.log, self.commits, self.rollbacks = [], 0, 0

        def cursor(self):
            return ReextractTests.Cursor(self)

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            pass

    def run_it(self, conn):
        from experiments.sql_semantic import prepare

        def no_source():
            raise AssertionError('재추출이 소스(EC2) 연결을 열었다')

        with patch.object(config, 'source_connection', no_source):
            return prepare.reextract_conditions(say=lambda *_: None, connection=conn)

    def test_does_not_touch_source_and_backs_up_first(self):
        conn = self.Conn()
        out = self.run_it(conn)
        first_backup = next(i for i, sql in enumerate(conn.log) if sql.startswith('CREATE TABLE'))
        first_write = next(i for i, sql in enumerate(conn.log)
                           if sql.startswith('INSERT INTO lab_conditions'))
        self.assertLess(first_backup, first_write)
        self.assertTrue(out['backup_table'].startswith('lab_conditions_bak_'))

    def test_uses_new_extractor_and_reports_changes(self):
        out = self.run_it(self.Conn())
        self.assertEqual(out['extractor'], conditions.EXTRACTOR)
        self.assertNotEqual(out['extractor'], 'sql_lab_v1')
        self.assertIn('company_size known->no_limit', out['changed'])

    def test_short_backup_stops_before_overwriting(self):
        conn = self.Conn(original=9, copied=8)
        with self.assertRaises(RuntimeError):
            self.run_it(conn)
        self.assertFalse(any(sql.startswith('INSERT INTO lab_conditions') for sql in conn.log))
        self.assertEqual(conn.rollbacks, 1)


class F2RevisionTests(unittest.TestCase):
    """검색이 모델 **리비전**까지 대조하는지 (2026-09-18 Codex 리뷰 F2).

    예전에는 모델 이름·입력 해시·차원만 같으면 리비전이 달라도 통과했다(반환 1건, stale 0건).
    """

    def setUp(self):
        patcher = patch.object(embedding, 'model_revision', lambda: 'current-rev')
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_search(self, rows):
        with patch.object(embedding, 'encode',
                          lambda m, texts, **kwargs: np.array([[1.0, 0.0]], dtype='float32')):
            return search.run({'idea': 'x', 'region': '', 'founded_at': '2025-01-01'},
                              as_of=date(2026, 9, 18), connection=FakeConnection(rows),
                              model=object())

    def test_other_revision_is_stale_not_returned(self):
        """리뷰의 재현 그대로: 같은 모델명·입력 해시·차원, 리비전만 'obsolete-revision'."""
        out = self.run_search([row('same', [1.0, 0.0]),
                               row('old', [1.0, 0.0], model_revision='obsolete-revision')])
        self.assertEqual([r['notice_id'] for r in out['results']], ['same'])
        self.assertEqual(out['counts']['stale_vector'], 1)
        self.assertIn('다른 모델 리비전', out['stale_vector_examples'][0]['reason'])

    def test_missing_stored_revision_is_not_trusted(self):
        out = self.run_search([row('norev', [1.0, 0.0], model_revision=None)])
        self.assertEqual(out['counts']['returned'], 0)
        self.assertIn('확인 불가', out['stale_vector_examples'][0]['reason'])

    def test_unknown_current_revision_is_not_trusted(self):
        """질의 인코더의 리비전을 모르면 어떤 저장 벡터와도 같다고 말할 수 없다."""
        rows = [row('a', [1.0, 0.0])]            # 저장 리비전 current-rev
        with patch.object(embedding, 'model_revision', lambda: None):
            out = self.run_search(rows)
        self.assertEqual(out['counts']['returned'], 0)
        self.assertEqual(out['counts']['stale_vector'], 1)

    def test_same_revision_passes_and_is_recorded(self):
        out = self.run_search([row('a', [1.0, 0.0])])
        self.assertEqual(out['counts']['returned'], 1)
        self.assertEqual(out['encoder']['model_revision'], 'current-rev')


class _VectorTable:
    """F3 테스트용 가짜 lab_vectors. **실제 VECTOR_SQL 의 UPDATE 절에 적힌 칸만** 바꾼다.

    그래서 SQL 에서 칸 하나가 빠지면 옛 값이 남아 테스트가 깨진다. SQL 문자열 자체를 시험한다.
    """

    SELECT_COLS = ('notice_id', 'title', 'body', 'target_text', 'target_category', 'category',
                   'subcategory', 'input_sha256', 'model', 'model_revision', 'dim', 'dtype',
                   'normalized')

    def __init__(self, notices, vectors):
        self.notices, self.vectors, self.commits = notices, vectors, 0

    def cursor(self):
        return _VectorCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


class _VectorCursor:
    def __init__(self, table):
        self.t, self.description, self._rows = table, None, []

    def execute(self, sql, params=None):
        from experiments.sql_semantic import prepare
        if sql.startswith('SELECT n.notice_id'):
            cols = _VectorTable.SELECT_COLS
            self.description = [(c,) for c in cols]
            self._rows = []
            for n in self.t.notices:
                v = self.t.vectors.get(n['notice_id'], {})
                self._rows.append(tuple(n[c] if c in n else v.get(c) for c in cols))
            return
        if sql.startswith('INSERT INTO lab_vectors'):
            values = dict(zip(prepare.VECTOR_COLUMNS, params))
            key = values['notice_id']
            if key not in self.t.vectors:
                self.t.vectors[key] = values
                return
            update = sql.split('ON DUPLICATE KEY UPDATE', 1)[1]
            for part in update.split(','):
                col = part.split('=')[0].strip()
                self.t.vectors[key][col] = values[col]
            return
        raise AssertionError('예상하지 못한 SQL: ' + sql[:60])

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class F3VectorMetaTests(unittest.TestCase):
    """벡터를 다시 만들 때 메타데이터가 함께 갱신되는지 (2026-09-18 Codex 리뷰 F3)."""

    def setUp(self):
        patcher = patch.object(embedding, 'model_revision', lambda: 'new-rev')
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def notice_row():
        return {'notice_id': 'n1', 'title': '공고', 'body': '내용', 'target_text': '자격',
                'target_category': '', 'category': '창업', 'subcategory': ''}

    def build(self, table):
        from experiments.sql_semantic import prepare

        def fake_encode(model, texts, **kw):
            return np.ones((len(texts), embedding.DIM), dtype='float32') / 32.0

        with patch.object(embedding, 'encode', fake_encode), \
                patch.object(embedding, 'token_info', lambda text: (10, False)):
            return prepare.build_vectors(say=lambda *_: None, connection=table, model=object())

    def test_upsert_updates_every_non_key_column(self):
        from experiments.sql_semantic import prepare
        update = prepare.VECTOR_SQL.split('ON DUPLICATE KEY UPDATE', 1)[1]
        updated = {part.split('=')[0].strip() for part in update.split(',')}
        self.assertEqual(updated, set(prepare.VECTOR_COLUMNS) - set(prepare.VECTOR_KEY))
        for col in ('model', 'dim', 'dtype', 'normalized', 'model_revision'):
            self.assertIn(col, updated)

    def test_wrong_old_row_is_rebuilt_then_searchable_then_skipped(self):
        """리뷰가 요구한 흐름: 불일치 행 재생성 → 검색 통과 → 다음 생성은 건너뜀."""
        text, _ = embedding.build_input(self.notice_row())
        old = {'notice_id': 'n1', 'contract': embedding.CONTRACT, 'model': 'old/model',
               'model_revision': 'old-rev', 'dim': 512, 'dtype': 'float16', 'normalized': 0,
               'input_sha256': embedding.input_sha256(text), 'truncated': 0,
               'token_count': 5, 'vector': b'old', 'created_at': None}
        table = _VectorTable([self.notice_row()], {'n1': dict(old)})

        self.assertEqual(self.build(table)['created'], 1)
        stored = table.vectors['n1']
        meta = embedding.meta()
        self.assertEqual(stored['model'], meta['model'])
        self.assertEqual(stored['model_revision'], 'new-rev')
        self.assertEqual(stored['dim'], embedding.DIM)
        self.assertEqual(stored['dtype'], meta['dtype'])
        self.assertEqual(stored['normalized'], 1)

        # 검색이 이 행을 손상·낡음 없이 쓰는지
        search_row = row('n1', [0.0])                 # 모양만 빌리고 저장된 값으로 덮는다
        search_row.update({k: stored[k] for k in (
            'vector', 'dim', 'dtype', 'normalized', 'model', 'model_revision', 'contract')})
        search_row.update({k: v for k, v in self.notice_row().items() if k != 'notice_id'})
        search_row['input_sha256'] = stored['input_sha256']

        def query(model, texts, **kw):
            return np.ones((1, embedding.DIM), dtype='float32')

        with patch.object(embedding, 'encode', query):
            out = search.run({'idea': 'x', 'region': '', 'founded_at': '2025-01-01'},
                             as_of=date(2026, 9, 18), connection=FakeConnection([search_row]),
                             model=object())
        self.assertEqual(out['counts']['returned'], 1)
        self.assertEqual(out['counts']['broken_vector'] + out['counts']['stale_vector'], 0)

        self.assertEqual(self.build(table), {'created': 0, 'skipped': 1})

    def test_needs_vector_sees_dtype_and_normalized(self):
        from experiments.sql_semantic import prepare
        meta = embedding.meta()
        base = {'input_sha256': 'h', 'model': meta['model'], 'model_revision': 'new-rev',
                'dim': meta['dim'], 'dtype': meta['dtype'], 'normalized': 1}
        self.assertFalse(prepare.needs_vector(base, 'h', meta))
        for change in ({'dtype': 'float16'}, {'normalized': 0}, {'dim': 512},
                       {'model_revision': 'old'}, {'model': 'other/model'}):
            self.assertTrue(prepare.needs_vector(dict(base, **change), 'h', meta), change)
        self.assertTrue(prepare.needs_vector({}, 'h', meta))
