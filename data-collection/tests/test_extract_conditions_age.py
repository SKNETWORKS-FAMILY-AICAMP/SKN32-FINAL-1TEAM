# -*- coding: utf-8 -*-
"""10단계 자격요건 추출의 업력 검사(verify_age) — 2026-09-28 넓힘. DB·LLM 없음.

버려진 204건 중 실제 업력 조건("사업자등록 후 1년 이상 10년 미만" 등)은 살리고,
근무·경력·거주·의무 기간은 계속 버린다.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import extract_conditions as ec  # noqa: E402


def why(quote, mx=7, mn=None):
    return ec.verify_age({'age_years_max': mx, 'age_years_min': mn, 'age_source_quote': quote})[1]


class VerifyAgeTests(unittest.TestCase):
    def test_business_start_expressions_are_kept(self):
        for q in ('본 대회에서 창업자란 공고일 기준 사업자등록 후 1년 이상 10년 미만인 개인사업자 또는 법인사업자를 말함.',
                  '(창업기업) 사업개시일로부터 보증신청 접수일까지의 기간이 7년 이내인 중소기업',
                  '사업을 개시한 날부터 7년이 지나지 아니한 기업',
                  '사업자등록일로부터 1년 이상 경과한 관내 중소기업',
                  '공고일 기준 영업신고 후 1년 이상 지난 업소',
                  '신규로 창업하고자 하는 자 또는 공고일 기준 창업한 지 5년 이내인 자',
                  '기업은 설립된 지 5년 미만이어야 하며',
                  '공고일 현재 보령시 관내에서 1년 이상 정상 가동 중인 제조업체',
                  '예비창업자(팀) 또는 7년 이내 창업기업',
                  '창업기업 : 공고일 기준 사업자등록증 5년 이내',
                  # 예전부터 되던 것
                  '업력 7년 이내 중소기업', '창업 후 3년 이내', '설립 후 5년 미만'):
            self.assertIsNone(why(q), q)

    def test_people_and_duty_periods_are_rejected(self):
        for q in ('공고일 기준 입사 5년 미만 근로자 (내국인·외국인)',
                  '추천일 기준 현재 해당분야 근무경력 3년 이상',
                  '광주시에 2년 이상 주소지를 등록하고 거주한 자 (사업개시일 이전 사업자등록증 소지자 포함)',
                  '보조금을 지원받은 사업자는 해당 설비를 3년 이상 운영하여야 함',
                  '만 19세 ~ 만 45세', '장기재직(3년 이상)'):
            self.assertIsNotNone(why(q), q)

    def test_mixed_residence_and_business_age_keeps_business_clause(self):
        # 업력과 거주가 한 근거에 섞이면 업력 구절은 살린다(2026-09-28 Codex 검수 P2 — 117511·120618·125410)
        # 뽑은 연수가 업력 구절의 연수와 같아야 한다(2026-09-28 Codex 재검수 P2)
        self.assertIsNone(why('진안군에 주민등록을 두고 실제 거주하며, 1년 이상 해당사업을 운영 중인 소상공인',
                              mx=None, mn=1))
        self.assertIsNone(why('창업 7년 이내이며 관내 거주 1년 이상인 기업', mx=7))
        # 업력 구절에 연수가 없고 거주 쪽에만 연수가 있으면 계속 버린다
        self.assertIsNotNone(why('광주시에 2년 이상 주소지를 등록하고 거주한 자 (사업개시일 이전 사업자등록증 소지자 포함)'))

    def test_mixed_quote_value_must_come_from_business_clause(self):
        # Codex 재검수 P2 반례 — 섞인 근거에서 뽑은 연수는 깨끗한 업력 구절에 있어야 한다
        from collect import extract_conditions as ec
        q = '거주 2년 이상이며 창업 7년 이내 기업'
        self.assertIsNotNone(ec.age_quote_problem(q, [2, None]))           # 거주 2년을 업력 하한으로 읽음
        self.assertIsNone(ec.age_quote_problem(q, [None, 7]))
        for q, v in (('근무경력 3년 이상이며 창업 7년 미만 기업은 대출금리 우대', [None, 7]),
                     ('거주 2년 이상 및 창업기업 6개월 미만 - 3천만원, 창업기업 1년 이상 - 5천만원', [1, None]),
                     ('우선선정기업 사업개시 3년 이내의 신생기업', [None, 3]),
                     ('제조업 업력 1년 미만인 기업의 경우 융자 추천 최대 5천만원', [None, 1])):
            self.assertIsNotNone(ec.age_quote_problem(q, v), q)
        # 자격 문장 속 금액은 우대로 보지 않는다
        self.assertIsNone(ec.age_quote_problem('개업일로부터 3년 이상 사업을 영위중인 사업자 중, 최근 2개년 평균 '
                                               '매출액 80백만 원 미만인 소상공인', [3, None]))
        # 주 조건이 깨끗하면 괄호 속 우선 선발은 문제 삼지 않는다
        self.assertIsNone(ec.age_quote_problem('7년이내 창업기업 (사업개시일로부터 3년 미만 사업장 우선 선발)', [None, 7]))

    def test_classify_demo_uses_same_check(self):
        from search import app
        self.assertEqual(app._rule_verdict('보조금을 지원받은 사업자는 해당 설비를 3년 이상 운영하여야 함')[0], False)
        self.assertEqual(app._rule_verdict('사업개시일로부터 7년 이내 기업')[0], True)

    def test_unrelated_sentences_still_rejected(self):
        for q in ('관내 중소기업자 및 소상공인 ☞ 중소기업 1억원 이내', '접수마감일 기준 1년 이내 제품검사 실적이 있을 것',
                  '예비창업자 신청 가능', ''):
            self.assertIsNotNone(why(q), q)

    def test_months_only_quote_still_rejected(self):
        self.assertEqual(why('도내에 사업장을 두고 3개월 이상 가동 중인 중소기업', mx=None, mn=3),
                         '근거가 개월 단위인데 연 단위로 읽음')

    def test_company_size_words_do_not_trigger_decoy(self):
        # "상시 근로자 30인 미만" 은 규모지 근속이 아니다(이미 통과하던 147건 중 1건)
        self.assertIsNone(why('설립 10년 이상 노후 시설을 보유한 상시 근로자 30인미만 영세 사업장', mx=None, mn=10))


class AgeRerunResumeTests(unittest.TestCase):
    def test_checkpoint_reused_only_for_same_document(self):
        # 중단 뒤 공고문이 바뀌면 옛 원답을 쓰지 않는다(2026-09-28 Codex 검수 P2)
        from experiments.sql_semantic import age_rerun
        items = [{'notice_id': 'a', 'document_sha256': 'h1'}, {'notice_id': 'b', 'document_sha256': 'NEW'}]
        rows = [{'notice_id': 'a', 'document_sha256': 'h1', 'data': {}},
                {'notice_id': 'b', 'document_sha256': 'OLD', 'data': {}},
                {'notice_id': 'c', 'data': {}}]                       # 해시 없는 옛 줄
        self.assertEqual(set(age_rerun.reusable(rows, items)), {'a'})


class AgeApplyCountTests(unittest.TestCase):
    def test_rows_blocked_by_hash_are_reported_as_missed(self):
        # 실제로 바뀐 행만 센다(Codex 검수 — 계획 수를 반영 수로 보고하던 문제)
        import json
        import shutil
        import tempfile
        from experiments.sql_semantic import age_rerun

        class Cursor:
            def __init__(self, conn):
                self.conn = conn

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, args=None):
                if sql.startswith('SELECT'):
                    return None
                return 0 if args[-2] == 'b' else 1           # b 는 그 사이 공고문이 바뀌어 WHERE 에 걸림

            def fetchall(self):
                return [(n, 'h', None, None, 'x', '근거에 업력 표현이 없음', '[]', 'v') for n in ('a', 'b')]

        class Conn:
            def cursor(self):
                return Cursor(self)

            def commit(self):
                pass

        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'results.jsonl')
            with open(path, 'w', encoding='utf-8') as f:
                for n in ('a', 'b'):
                    f.write(json.dumps({'notice_id': n, 'document_sha256': 'h',
                                        'raw': {'age_years_max': 7, 'age_source_quote': '사업개시일로부터 7년 이내 기업'}},
                                       ensure_ascii=False) + '\n')
            out = age_rerun.apply_to_db(path, dry_run=False, connection=Conn(), backup_dir=tmp, say=lambda *_: None)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual((out['planned'], out['updated'], out['missed']), (2, 1, ['b']))


class AgeApplyPlanTests(unittest.TestCase):
    def test_only_same_document_and_real_age_are_applied(self):
        # C-3 — 공고문이 그대로이고 지금 검사를 통과한 업력만 반영한다. 버전 칸은 건드리지 않는다
        import json
        import shutil
        import tempfile
        from experiments.sql_semantic import age_rerun
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'results.jsonl')
            rows = [
                {'notice_id': 'ok', 'document_sha256': 'h1', 'raw': {'age_years_max': 7, 'age_source_quote': '사업개시일로부터 7년 이내 기업'}},
                {'notice_id': 'changed', 'document_sha256': 'OLD', 'raw': {'age_years_max': 7, 'age_source_quote': '창업 7년 이내'}},
                {'notice_id': 'zero', 'document_sha256': 'h3', 'raw': {'age_years_min': 0, 'age_source_quote': '6개월 이상 운영 중인 기업 1년'}},
                {'notice_id': 'none', 'document_sha256': 'h4', 'raw': {}},
            ]
            with open(path, 'w', encoding='utf-8') as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
            db = {n: {'input_sha256': h, 'age_years_min': None, 'age_years_max': None, 'age_source_quote': 'x',
                      'age_rejected': '근거에 업력 표현이 없음', 'uncertain': json.dumps(['업력 추출 버림: 근거에 업력 표현이 없음'])}
                  for n, h in (('ok', 'h1'), ('changed', 'NEW'), ('zero', 'h3'), ('none', 'h4'))}
            updates, skipped = age_rerun.apply_plan(path, db)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual([u['notice_id'] for u in updates], ['ok'])
        self.assertEqual((skipped['doc_changed'], skipped['zero_only'], skipped['no_age']), (1, 1, 1))
        u = updates[0]
        self.assertEqual((u['age_years_max'], u['age_rejected']), (7, None))
        self.assertTrue(u['uncertain'][-1].startswith('업력 출처: luna 재추출'))
        self.assertFalse(any(x.startswith('업력 추출 버림') for x in u['uncertain']))


if __name__ == '__main__':
    unittest.main()
