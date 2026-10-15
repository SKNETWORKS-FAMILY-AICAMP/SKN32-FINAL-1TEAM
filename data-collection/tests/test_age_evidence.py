# -*- coding: utf-8 -*-
"""자격 확인의 업력 줄 — A(예비창업자 본문 가능) · B(공고문 추출 업력을 근거로만) (2026-09-28). DB·LLM 없음.

사례: 기업마당 "2026년 제2회 반려동물 창업 아이디어 경진대회" — API 업력 칸이 없고, 본문은
"예비창업자(개인·팀) 또는 창업 10년 미만 기업". 예비창업자에게 업력이 "확인 필요"로 나왔다.
"""
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

from search import age_evidence, app  # noqa: E402
from test_match_rules import notice, state  # noqa: E402


def info(pre_status, evidence='', strength='strong'):
    cell = lambda s=None, e=None: {'status': s or 'not_mentioned', 'strength': None, 'evidence': e}   # noqa: E731
    return {'varies': False, 'pre_founder': {'status': pre_status, 'strength': strength, 'evidence': evidence},
            'sole_proprietor': cell(), 'corporation': cell(), 'registered_only': None}


TYPES = {'active': True, 'source': 'test', 'notices': {
    '반려동물': info('allowed', '전국의 예비창업자(개인·팀) 또는 창업 10년 미만 기업(개인·법인)'),
    '세부별': dict(info('allowed', '예비창업자(장인대학 운영사업에 한함)'), varies=True),
    '세부별K': dict(info('allowed', '예비창업자(1트랙에 한함)'), varies=True),
}}
EVIDENCE = {'sources': ['test'], 'error': None, 'notices': {
    '반려동물': {'min': None, 'max': 10, 'quote': '사업자등록 후 1년 이상 10년 미만인 개인사업자 또는 법인사업자',
               'pre_allowed': True, 'source': '업력 재추출(luna)'},
    '제조': {'min': 1, 'max': None, 'quote': '1년 이상 정상 가동 중인 제조업체', 'pre_allowed': False,
           'source': '자격요건 추출(10단계)'},
}}


def rows():
    blank = {'age_condition_raw': ''}                      # 기업마당처럼 API 업력 칸이 없다
    return {'반려동물': notice('반려동물 창업 아이디어 경진대회', **blank),
            '제조': notice('제조업 육성자금', **blank),
            '근거없음': notice('일반 공고', **blank),
            '세부별': notice('장인대학 등 세부사업 공고', **blank),
            # K-Startup 처럼 API 업력 칸이 "예비창업자, …년미만"이라 업력이 이미 True 인 세부사업 공고
            '세부별K': notice('K-Startup 세부사업 공고', age_condition_raw='예비창업자,3년미만')}


def gate(nid, applicant_type='예비창업자', founded_at='', evidence=EVIDENCE):
    req = app.GateRequest(notice_id=nid, applicant_type=applicant_type, founded_at=founded_at)
    st = dict(state(rows()), applicant_types=TYPES, age_evidence=evidence)
    with patch.dict(app.STATE, st, clear=True):
        out = app.eligibility(req)
    return out, {c['조건']: c for c in out['checks']}


class PreFounderAgeTests(unittest.TestCase):
    """A — 본문에 예비창업자 가능이 있으면 업력 칸이 없어도 예비창업자의 업력 줄은 통과."""

    def test_pet_contest_prefounder_passes_age(self):
        out, c = gate('반려동물')
        self.assertIs(c['지원대상 유형']['판정'], True)
        self.assertIs(c['업력']['판정'], True)
        self.assertIn('이미 창업한 기업', c['업력']['요구'])
        self.assertIn('예비창업자(개인·팀)', c['업력']['설명'])

    def test_business_applicant_is_not_auto_passed(self):
        # 사업자에게는 A 를 쓰지 않는다 — B 의 근거만 보여 주고 판정은 확인 필요
        _out, c = gate('반려동물', applicant_type='법인사업자', founded_at='2020-01-01')
        self.assertIsNone(c['업력']['판정'])


    def test_varies_notice_is_not_auto_passed(self):
        # 세부사업별로 예비창업자 허용이 갈리면 유형·업력 모두 확인 필요(Codex 검수 P2, 예: 126769)
        _out, c = gate('세부별')
        self.assertIsNone(c['지원대상 유형']['판정'])
        self.assertIn('일부 세부사업', c['지원대상 유형']['요구'])
        self.assertIsNone(c['업력']['판정'])
        self.assertIn('세부사업별로 확인', c['업력']['요구'])


    def test_varies_notice_with_api_age_true_is_also_unknown(self):
        # 업력이 이미 True 여도 세부사업별 허용이면 확인 필요로 바꾼다(Codex 재검수 P2 — kstartup 176208 등 5건)
        _out, c = gate('세부별K')
        self.assertIsNone(c['지원대상 유형']['판정'])
        self.assertIsNone(c['업력']['판정'])
        self.assertIn('세부사업별로 확인', c['업력']['요구'])


class AgeEvidenceTests(unittest.TestCase):
    def test_boundary_is_not_called_inside(self):
        # "10년 미만" 인데 업력 10년 0개월 — 안/밖을 말하지 않는다(Codex 검수 P2)
        ev = {'min': None, 'max': 10}
        self.assertIn('경계', age_evidence.compare(ev, 120))
        self.assertIn('경계', age_evidence.compare(ev, 126))
        self.assertIn('밖으로 보입니다', age_evidence.compare(ev, 132))
        self.assertIn('안으로 보입니다', age_evidence.compare(ev, 119))
        self.assertIn('경계', age_evidence.compare({'min': 1, 'max': None}, 12))
        self.assertIn('안으로 보입니다', age_evidence.compare({'min': 1, 'max': None}, 13))

    """B — 공고문 추출 업력은 근거로만. 판정은 바꾸지 않는다."""

    def test_evidence_shown_without_verdict(self):
        _out, c = gate('제조', applicant_type='법인사업자', founded_at='2020-01-01')
        self.assertIsNone(c['업력']['판정'])
        self.assertIn('공고문 추출(추정): 업력 1년 이상', c['업력']['요구'])
        self.assertIn('가동 중인 제조업체', c['업력']['설명'])
        self.assertIn('범위 안으로 보입니다(참고)', c['업력']['설명'])

    def test_out_of_range_is_only_a_hint(self):
        _out, c = gate('반려동물', applicant_type='법인사업자', founded_at='2010-01-01')
        self.assertIsNone(c['업력']['판정'])                      # 범위 밖이어도 미달로 바꾸지 않는다
        self.assertIn('최대 10년', c['업력']['요구'])
        self.assertIn('범위 밖으로 보입니다(참고)', c['업력']['설명'])

    def test_unknown_founding_date_still_shows_evidence(self):
        _out, c = gate('제조', applicant_type='법인사업자', founded_at='')
        self.assertIsNone(c['업력']['판정'])
        self.assertIn('설립일이 없어 비교하지 못했습니다', c['업력']['설명'])

    def test_no_evidence_is_as_before(self):
        _out, c = gate('근거없음', applicant_type='법인사업자', founded_at='2020-01-01')
        self.assertEqual(c['업력']['요구'], '업력 조건 알 수 없음')
        _out, c = gate('제조', applicant_type='법인사업자', founded_at='2020-01-01', evidence=None)
        self.assertEqual(c['업력']['요구'], '업력 조건 알 수 없음')


class LoadTests(unittest.TestCase):
    def test_broken_file_does_not_raise_and_keeps_db(self):
        # 결과 파일 한 줄이 깨져도 예외를 내지 않는다 — 파일 쪽만 비우고 error 에 적는다(Codex 검수 P1)
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a):
                pass

            def fetchall(self):
                return [('a', 1, None, '업력 1년 이상 기업', 0, 'ha')]

        class Conn:
            def cursor(self):
                return Cursor()

        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'results.jsonl')
            with io.open(path, 'w', encoding='utf-8') as f:
                f.write(json.dumps({'notice_id': 'b', 'raw': {'age_years_max': 5, 'age_source_quote': '창업 5년 이내'}},
                                   ensure_ascii=False) + '\n{broken\n')
            table = age_evidence.load(Conn(), rerun=path)
            only_file = age_evidence.load(None, rerun=path)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(set(table['notices']), {'a'})                    # 파일 행은 하나도 섞지 않는다
        self.assertIn('JSONDecodeError', table['error'])
        self.assertEqual(only_file['notices'], {})

    def test_file_values_are_rechecked_with_current_rule(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'results.jsonl')
            with io.open(path, 'w', encoding='utf-8') as f:
                # 저장된 new 는 비어 있어도(옛 검사로 버림) 원답이 지금 검사를 통과하면 쓴다
                f.write(json.dumps({'notice_id': 'm', 'new': {}, 'raw': {
                    'age_years_min': 1, 'age_years_max': None,
                    'age_source_quote': '진안군에 주민등록을 두고 실제 거주하며, 1년 이상 해당사업을 운영 중인 소상공인'}},
                    ensure_ascii=False) + '\n')
            table = age_evidence.load(None, rerun=path)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(table['notices']['m']['min'], 1)

    def test_rerun_path_ignores_sample_runs(self):
        tmp = tempfile.mkdtemp()
        try:
            for name in ('age_rerun_luna_20260928T054509Z', 'age_rerun_luna_missing_20260928T061903Z'):
                os.makedirs(os.path.join(tmp, 'reports', name))
                io.open(os.path.join(tmp, 'reports', name, 'results.jsonl'), 'w').close()
            with patch.object(age_evidence, 'ROOT', tmp), patch.dict(os.environ, {}, clear=False):
                os.environ.pop(age_evidence.ENV, None)
                self.assertIn('age_rerun_luna_20260928T054509Z', age_evidence.rerun_path())
        finally:
            shutil.rmtree(tmp)

    def test_db_wins_and_file_needs_same_document(self):
        # DB 업력이 우선이고, 파일 값은 DB 에 업력이 없고 공고문 해시가 같을 때만 쓴다(Codex 재검수 P2)
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a):
                pass

            def fetchall(self):
                return [('a', 1, None, '업력 1년 이상 기업', 0, 'ha'),
                        ('b', None, 7, '창업 7년 이내 기업', None, 'hb'),        # DB 에 업력 있음 → 파일이 못 덮음
                        ('d', None, None, None, None, 'hd'),                     # DB 업력 없음·해시 같음 → 파일 사용
                        ('e', None, None, None, None, 'NEW'),                    # 해시 다름 → 옛 파일 값 버림
                        ('w', None, 3, '우선선정기업 사업개시 3년 이내의 신생기업', None, 'hw')]   # 지금 검사에 걸림

        class Conn:
            def cursor(self):
                return Cursor()

        def raw(n):
            return {'age_years_min': None, 'age_years_max': n, 'age_source_quote': '창업 %d년 이내' % n}

        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'results.jsonl')
            with io.open(path, 'w', encoding='utf-8') as f:
                for row in ({'notice_id': 'b', 'document_sha256': 'hb', 'raw': raw(5)},
                            {'notice_id': 'd', 'document_sha256': 'hd', 'raw': raw(4)},
                            {'notice_id': 'e', 'document_sha256': 'OLD', 'raw': raw(10)},
                            {'notice_id': 'c', 'document_sha256': 'hc', 'raw': {}}):
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
            table = age_evidence.load(Conn(), rerun=path)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(set(table['notices']), {'a', 'b', 'd'})
        self.assertEqual(table['notices']['b']['max'], 7)                 # DB 우선
        self.assertEqual(table['notices']['d']['source'], '업력 재추출(luna)')
        self.assertEqual(table['hidden'], 1)                               # 우선선정(우대) 은 숨긴다
        self.assertEqual(table['file_skipped'], 3)                         # b(DB 있음)·e(해시 다름)·c(DB 없음)
        self.assertFalse(table['notices']['a']['pre_allowed'])

if __name__ == '__main__':
    unittest.main()
