# -*- coding: utf-8 -*-
"""공고 본문의 신청자 유형을 매칭·자격 확인에 쓰기 (2026-09-28 G). DB·모델 없음."""
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

from search import app, applicant_types as at  # noqa: E402
from test_match_rules import notice, state  # noqa: E402


def cell(status, strength=None, evidence=None):
    return {'status': status, 'strength': strength, 'evidence': evidence}


def info(pre, varies=False, sole=None, corp=None):
    return {'varies': varies, 'pre_founder': cell(*pre),
            'sole_proprietor': cell(*(sole or ('not_mentioned',))), 'corporation': cell(*(corp or ('not_mentioned',)))}


TABLE = {'active': True, 'source': 'test', 'notices': {
    '불가': info(('not_allowed', 'strong', '사업자등록증 보유')),
    '약한불가': info(('not_allowed', 'weak', '사업자 등록 업체')),
    '세부별불가': info(('not_allowed', 'strong', '과제2는 법인'), varies=True),
    '추정': info(('implied_no', 'strong', '도내 제조기업')),
    '가능': info(('allowed', 'strong', '여성 예비창업자')),
}}


class RegisteredOnlyTests(unittest.TestCase):
    """등록 사업자 규칙 — 원문 대조에서 놓친 6건(2026-09-28)과 올리면 안 되는 문장."""

    def test_missed_cases_are_caught(self):
        for text in ('관내 사업장을 두고(사업자등록증명원 상의 소재지) 정상가동 중인 중소기업',          # P084
                     '수급인(원도급사)은 「건설산업기본법에 따라 적법하게 건설업을 등록해야 할 것',          # P085
                     '구미시에 사업장(사업자등록증명원의 소재지, 매출액)을 둔 중소기업',                    # P086
                     '그린바이오기업 신고서가 제출 완료된 중소벤처기업',                                   # P089
                     '공고일 기준 영업활동을 하고 있는 법인기업',                                         # P044
                     '신청일 현재 사업자등록을 하지 않거나 휴업 또는 폐업',                               # P047
                     '사업자 미등록 업체',
                     # 예비창업자를 빼는 말은 "예비" 가 있어도 막지 않는다(2026-09-28 Codex 통합 검수 P2)
                     '예비창업자 제외. 사업자등록증 보유 업체만 가능',
                     '지원대상: 사업자등록증 보유 기업(예비창업자 신청 불가)'):
            self.assertIsNotNone(at.registered_only(text), text)

    def test_document_lists_are_not_qualifications(self):
        # 제출 서류 설명은 신청 자격이 아니다(판정 지시서 3절, Codex 통합 검수 P2)
        for text in ('제출서류: 사업자등록증 보유 확인 서류', '사업자등록증 사본 1부(등록증 보유 시)',
                     '구비서류 — 사업자등록증 보유 기업은 사업자등록증명원'):
            self.assertIsNone(at.registered_only(text), text)
        # 자격 문장에 서류 말이 섞이면 자격으로 본다
        self.assertIsNotNone(at.registered_only('신청자격: 사업자등록증 보유 기업(확인 서류 제출)'))

    def test_not_raised_for_open_or_prefounder_text(self):
        for text in ('사업자등록 없이도 신청 가능', '예비창업자 또는 사업자등록을 완료한 기업',
                     '업종 무관, 사업자등록증 보유 여부 관계없음', '도내 제조기업',
                     '공고 마감일 내 사업자등록 완료한 콘텐츠 관련 기업',        # 신청 뒤 등록해도 된다
                     '협약 체결 전까지 사업자등록을 완료한 자', '', None):
            self.assertIsNone(at.registered_only(text), text)

    def test_load_upgrades_only_unknown_or_weak(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'run', 'results.jsonl')
            os.makedirs(os.path.dirname(path))
            ev = '관내 사업장을 두고(사업자등록증명원 상의 소재지) 정상가동 중인 중소기업'
            rows_ = [('언급없음', cell('not_mentioned', None, ev), False),
                     ('약한불가', cell('not_allowed', 'weak', '사업자 미등록 업체'), False),
                     ('가능', cell('allowed', 'strong', ev), False),
                     ('세부별', cell('not_mentioned', None, ev), True)]
            with io.open(path, 'w', encoding='utf-8') as f:
                for nid, pre, varies in rows_:
                    f.write(json.dumps({'notice_id': nid, 'llm': {'pre_founder': pre, 'varies': varies}},
                                       ensure_ascii=False) + '\n')
            t = at.load(path)
            self.assertEqual(at.pre_founder(t, '언급없음'), 'implied_no')
            self.assertEqual(at.pre_founder(t, '약한불가'), 'implied_no')     # 빼지 않고 뒤로만
            self.assertEqual(at.pre_founder(t, '가능'), 'allowed')            # 가능은 절대 바꾸지 않는다
            self.assertIsNone(at.pre_founder(t, '세부별'))
            verdict, need, _why = at.type_check(t, '언급없음', '예비창업자')
            self.assertIsNone(verdict)
            self.assertIn('등록 사업자', need)
        finally:
            shutil.rmtree(tmp)


class VerdictTests(unittest.TestCase):
    def test_only_strong_non_varies_blocks(self):
        self.assertEqual(at.pre_founder(TABLE, '불가'), 'blocked')
        self.assertIsNone(at.pre_founder(TABLE, '약한불가'))          # Codex 13/17 — 쓰지 않는다
        self.assertIsNone(at.pre_founder(TABLE, '세부별불가'))
        self.assertEqual(at.pre_founder(TABLE, '추정'), 'implied_no')
        self.assertEqual(at.pre_founder(TABLE, '가능'), 'allowed')
        self.assertIsNone(at.pre_founder(TABLE, '없는공고'))
        self.assertIsNone(at.pre_founder({}, '불가'))

    def test_load_and_missing_file(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'run', 'results.jsonl')
            os.makedirs(os.path.dirname(path))
            with io.open(path, 'w', encoding='utf-8') as f:
                f.write(json.dumps({'notice_id': 'a', 'llm': {'pre_founder': cell('allowed', 'strong', 'x'),
                                                              'varies': False}}, ensure_ascii=False) + '\n')
                f.write(json.dumps({'notice_id': 'b', 'llm': None}) + '\n')
            t = at.load(path)
            self.assertTrue(t['active'])
            self.assertEqual(list(t['notices']), ['a'])
            self.assertFalse(at.load(os.path.join(tmp, 'none.jsonl'))['active'])
        finally:
            shutil.rmtree(tmp)


def rows():
    # 업력 칸(API)을 비워 둔다 — 비어 있으면 게이트가 모름으로 두고 빼지 않는다. 본문 판정의 효과만 보려는 것이다
    blank = {'age_condition_raw': ''}
    return {
        '불가': notice('사업자 전용', **blank),
        '약한불가': notice('약한 근거', **blank),
        '추정': notice('기존 기업 대상', **blank),
        '보통': notice('일반 공고', **blank),
        # K-Startup API 업력 칸이 '3년미만'(예비 불가)인데 본문은 예비창업자 가능
        '가능': notice('여성창업보육센터', age_condition_raw='3년미만'),
        'API불가': notice('API 만 불가', age_condition_raw='3년미만'),
    }


def match(applicant_type='예비창업자', table=TABLE, rows_=None, **kw):
    kw.setdefault('search', 'dense')
    req = app.MatchRequest(applicant_type=applicant_type, founded_at='' if applicant_type == '예비창업자' else '2025-01-01',
                           idea='창업 지원', top=20, **kw)
    st = dict(state(rows_ or rows()), applicant_types=table)
    with patch.dict(app.STATE, st, clear=True), patch.object(app, '_encode', lambda t: [0.0] * 4):
        return app.match(req)


def ids(out):
    return [r['notice_id'] for r in out['results']]


class MatchTests(unittest.TestCase):
    def test_pre_founder_filter_blocks_restores_and_demotes(self):
        out = match()
        got = ids(out)
        self.assertNotIn('불가', got)                          # 본문 명시 불가(강한 근거) → 뺀다
        self.assertIn('가능', got)                             # API 는 불가지만 본문 가능 → 되살린다
        self.assertNotIn('API불가', got)                       # 본문 정보 없는 API 불가는 그대로 뺀다
        self.assertIn('약한불가', got)                          # 약한 근거는 쓰지 않는다
        self.assertEqual(got[-1], '추정')                       # 불가 추정은 빼지 않고 맨 뒤
        self.assertTrue(out['results'][-1]['rules']['pre_founder_implied_no'])
        t = out['applicant_types']
        self.assertTrue(t['active'])
        self.assertEqual((t['blocked'], t['restored'], t['implied_demoted']), (1, 1, 1))
        self.assertEqual(out['filter']['excluded'].get('예비창업자 불가(공고 본문)'), 1)

    def test_business_applicants_are_untouched(self):
        # 2026-10-13(결정 0021)부터 개인·법인도 판정표를 쓰지만, 그 유형의 '불가' strong 이 없는 공고는 그대로다
        out = match(applicant_type='법인사업자')
        t = out['applicant_types']
        self.assertEqual((t['active'], t['blocked'], t['restored'], t['implied_demoted']), (True, 0, 0, 0))
        self.assertIn('불가', ids(out))
        self.assertIn('추정', ids(out))
        self.assertEqual(ids(out)[:2], ['불가', '약한불가'])     # 순서도 그대로 — 예비창업자 '불가 추정' 뒤로 보내기는 예비창업자만
        self.assertFalse(any(r['rules']['pre_founder_implied_no'] for r in out['results']))

    def test_switch_off_and_missing_table(self):
        for out in (match(use_applicant_types=False), match(table={})):
            self.assertIn('불가', ids(out))
            self.assertNotIn('가능', ids(out))                  # 예전처럼 API 업력 칸으로 빠진다
            self.assertFalse(out['applicant_types']['active'])


class EligibilityTests(unittest.TestCase):
    def gate(self, nid, applicant_type='예비창업자', table=TABLE):
        req = app.GateRequest(notice_id=nid, applicant_type=applicant_type,
                              founded_at='' if applicant_type == '예비창업자' else '2025-01-01')
        st = dict(state(rows()), applicant_types=table)
        with patch.dict(app.STATE, st, clear=True):
            out = app.eligibility(req)
        return out, {c['조건']: c for c in out['checks']}

    def test_blocked_is_failure_with_evidence(self):
        out, c = self.gate('불가')
        self.assertIs(c['지원대상 유형']['판정'], False)
        self.assertIn('사업자등록증 보유', c['지원대상 유형']['설명'])
        self.assertFalse(out['passed'])

    def test_text_allowed_overrides_api_age(self):
        out, c = self.gate('가능')
        self.assertIs(c['지원대상 유형']['판정'], True)
        self.assertIs(c['업력']['판정'], True)                 # API 업력 칸의 미달을 본문이 덮는다
        self.assertIn('본문', c['업력']['설명'])
        self.assertTrue(out['passed'])

    def test_implied_and_business_types_stay_unknown(self):
        _out, c = self.gate('추정')
        self.assertIsNone(c['지원대상 유형']['판정'])
        self.assertIn('추정', c['지원대상 유형']['요구'])
        _out, c = self.gate('불가', applicant_type='법인사업자')
        self.assertIsNone(c['지원대상 유형']['판정'])           # 개인/법인은 자동 판정하지 않는다

    def test_notice_without_data_is_as_before(self):
        _out, c = self.gate('보통', table={})
        self.assertIsNone(c['지원대상 유형']['판정'])
        self.assertIn('원문을 확인', c['지원대상 유형']['설명'])


# ── 개인사업자·법인 '불가' strong(2026-10-13 결정 0021) ─────────────────────
ENTITY_TABLE = {'active': True, 'source': 'test', 'notices': {
    '법인불가': info(('not_mentioned',), corp=('not_allowed', 'strong', '도내 소상공인(법인 제외)')),
    '개인불가': info(('not_mentioned',), sole=('not_allowed', 'strong', '국내 법인사업자')),
    '법인약한불가': info(('not_mentioned',), corp=('not_allowed', 'weak', '개인사업자 우대')),
    '법인세부별': info(('not_mentioned',), varies=True, corp=('not_allowed', 'strong', '2트랙은 개인사업자만')),
    '법인확인필요': dict(info(('not_mentioned',), corp=('not_allowed', 'strong', '법인 제외')),
                       unread_corporation='제출서류: 법인인 경우 법인등기부등본'),
    '법인원문없음': dict(info(('not_mentioned',), corp=('not_allowed', 'strong', '법인 제외')), unverified_corporation=True),
    '법인가능': info(('not_mentioned',), corp=('allowed', 'strong', '법인 신청 가능')),
    '추정': info(('implied_no', 'strong', '도내 제조기업')),
}}


def entity_rows():
    return {nid: notice(nid, age_condition_raw='') for nid in ENTITY_TABLE['notices']}


def ematch(applicant_type, table=ENTITY_TABLE, **kw):
    return match(applicant_type, table=table, rows_=entity_rows(), **kw)


class EntityTests(unittest.TestCase):
    def test_only_strong_common_checked_blocks(self):
        self.assertEqual(at.entity(ENTITY_TABLE, '법인불가', '법인'), 'blocked')
        self.assertEqual(at.entity(ENTITY_TABLE, '법인불가', '법인사업자'), 'blocked')     # 예전 화면·시험 값
        self.assertEqual(at.entity(ENTITY_TABLE, '개인불가', '개인사업자'), 'blocked')
        self.assertIsNone(at.entity(ENTITY_TABLE, '법인불가', '개인사업자'))               # 다른 유형은 건드리지 않는다
        for nid in ('법인약한불가', '법인세부별', '법인확인필요', '법인원문없음', '법인가능', '추정', '없는공고'):
            self.assertIsNone(at.entity(ENTITY_TABLE, nid, '법인'), nid)
        self.assertIsNone(at.entity(ENTITY_TABLE, '법인불가', '예비창업자'))
        self.assertIsNone(at.entity(ENTITY_TABLE, '법인불가', '사업자'))                    # 알 수 없는 유형
        self.assertIsNone(at.entity({}, '법인불가', '법인'))
        self.assertEqual((at.entity_key('법인'), at.entity_key('법인사업자'), at.entity_key('개인사업자'),
                          at.entity_key('예비창업자'), at.entity_key('')), ('corporation', 'corporation', 'sole_proprietor',
                                                                         None, None))

    def test_match_filters_only_that_type(self):
        out = ematch('법인')
        got = ids(out)
        self.assertNotIn('법인불가', got)
        for nid in ('개인불가', '법인약한불가', '법인세부별', '법인확인필요', '법인원문없음', '법인가능', '추정'):
            self.assertIn(nid, got, nid)
        self.assertEqual(out['filter']['excluded'].get('법인 불가(공고 본문)'), 1)
        t = out['applicant_types']
        self.assertEqual((t['active'], t['blocked'], t['restored'], t['implied_demoted']), (True, 1, 0, 0))
        out = ematch('개인사업자')
        self.assertNotIn('개인불가', ids(out))
        self.assertIn('법인불가', ids(out))
        self.assertEqual(out['filter']['excluded'].get('개인사업자 불가(공고 본문)'), 1)
        # 예비창업자에게는 개인·법인 판정을 쓰지 않는다(예비창업자 규칙만)
        got = ids(ematch('예비창업자'))
        self.assertIn('법인불가', got)
        self.assertIn('개인불가', got)

    def test_switch_off_and_missing_table(self):
        for out in (ematch('법인', use_applicant_types=False), ematch('법인', table={})):
            self.assertIn('법인불가', ids(out))
            self.assertFalse(out['applicant_types']['active'])

    def gate(self, nid, applicant_type):
        req = app.GateRequest(notice_id=nid, applicant_type=applicant_type, founded_at='2020-01-01')
        st = dict(state(entity_rows()), applicant_types=ENTITY_TABLE)
        with patch.dict(app.STATE, st, clear=True):
            out = app.eligibility(req)
        return out, {c['조건']: c for c in out['checks']}['지원대상 유형']

    def test_eligibility_screen(self):
        out, c = self.gate('법인불가', '법인')
        self.assertIs(c['판정'], False)
        self.assertIn('법인 신청 불가', c['요구'])
        self.assertIn('도내 소상공인(법인 제외)', c['설명'])
        self.assertFalse(out['passed'])
        _out, c = self.gate('법인불가', '개인사업자')
        self.assertIsNone(c['판정'])
        _out, c = self.gate('법인확인필요', '법인')
        self.assertIsNone(c['판정'])
        self.assertIn('확인 필요', c['요구'])
        self.assertIn('법인등기부등본', c['설명'])
        _out, c = self.gate('법인원문없음', '법인')
        self.assertIsNone(c['판정'])
        self.assertIn('확인하지 못했습니다', c['설명'])
        for nid in ('법인약한불가', '법인세부별', '법인가능'):
            _out, c = self.gate(nid, '법인')
            self.assertIsNone(c['판정'], nid)                                   # 가능도 True 로 올리지 않는다
            self.assertIn('참고', c['요구'], nid)

    def test_filter_and_eligibility_agree(self):
        # 정형 필터와 자격 판정(지원대상 유형)이 같은 결론 — 공고 × 세 유형 전부
        from datetime import date
        from search import eligibility, gate
        today = date(2026, 10, 13)
        for nid, row in entity_rows().items():
            for kind in ('예비창업자', '개인사업자', '법인'):
                founded = '' if kind == '예비창업자' else '2020-01-01'
                age = gate.applicant_age(kind, founded, today)
                keep, _why, _ = app.eligible_with_types(nid, row, age, today, False, ENTITY_TABLE, kind)
                checks, _ = eligibility.conditions(row, nid, kind, founded, types_table=ENTITY_TABLE, today=today)
                failed = any(c['판정'] is False for c in checks if c['조건'] in ('지원대상 유형', '업력'))
                self.assertEqual(keep, not failed, (nid, kind))


if __name__ == '__main__':
    unittest.main()
