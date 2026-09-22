# -*- coding: utf-8 -*-
"""업종 LLM 표본(`experiments/sql_semantic/industry_llm_sample.py`) 회귀 테스트. DB·API 없이 돈다.

2026-09-22 Codex 리뷰(docs/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md)의 반례를 그대로 고정한다.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import industry_llm_sample as s  # noqa: E402


def v3(status='known', allowed=(), excluded=(), no_limit_text='', complete=True, quote='', reason=''):
    """allowed: (text, label[, evidence]) — evidence 를 안 주면 quote 로 둔다.
    excluded: text 또는 (text, evidence)."""
    def a(entry):
        text, label = entry[0], entry[1]
        return dict(text=text, label=label, evidence=entry[2] if len(entry) > 2 else quote)

    def e(entry):
        return dict(text=entry, evidence='') if isinstance(entry, str) else dict(text=entry[0], evidence=entry[1])
    return {'status': status, 'allowed': [a(x) for x in allowed], 'excluded': [e(x) for x in excluded],
            'no_limit_text': no_limit_text, 'list_complete': complete, 'quote': quote, 'reason': reason}


class NoLimitTests(unittest.TestCase):
    def test_no_limit_without_phrase_is_downgraded(self):
        # 리뷰 반례: quote '제조업 지원사업' 으로 no_limit 이 통과하던 문제
        doc = '[지원대상] 제조업 지원사업 참여기업'
        out = s.verify_v3(v3('no_limit', quote='제조업 지원사업'), doc)
        self.assertEqual(out['status'], 'unknown')
        self.assertIn('no_limit', out['downgraded'])

    def test_no_limit_phrase_about_region_is_not_industry(self):
        doc = '지역 제한 없음. 누구나 신청'
        out = s.verify_v3(v3('no_limit', no_limit_text='지역 제한 없음', quote='지역 제한 없음'), doc)
        self.assertEqual(out['status'], 'unknown')

    def test_explicit_industry_no_limit_passes(self):
        doc = '신청대상: 업종 제한 없음, 도내 중소기업'
        out = s.verify_v3(v3('no_limit', no_limit_text='업종 제한 없음', quote='업종 제한 없음'), doc)
        self.assertEqual(out['status'], 'no_limit')
        self.assertEqual(out['no_limit_text'], '업종 제한 없음')

    def test_no_limit_text_not_in_document(self):
        out = s.verify_v3(v3('no_limit', no_limit_text='전 업종', quote='전 업종'), '도내 중소기업')
        self.assertEqual(out['status'], 'unknown')


class AliasAndLabelTests(unittest.TestCase):
    def test_farm_household_is_alias_not_exact(self):
        # 리뷰 반례: '도내 농가 대상' 이 넓은 별칭으로 known/농업 이 되던 문제
        doc = '모집대상: 도내 농가 대상'
        out = s.verify_v3(v3(allowed=[('농가', '농업')], quote='도내 농가 대상'), doc)
        a = out['allowed'][0]
        self.assertEqual(a['label'], '')
        self.assertEqual(a['label_suggested'], '농업')
        self.assertEqual(a['label_basis'], 'alias')

    def test_label_basis(self):
        self.assertEqual(s.label_basis('제조업', '제조업'), 'exact')
        self.assertEqual(s.label_basis('제조 및 무역업', '제조업'), 'exact')     # 어간 '제조'
        self.assertEqual(s.label_basis('농식품', '농업'), 'alias')               # 어간 '농' 한 글자는 쓰지 않는다
        self.assertEqual(s.label_basis('무역업', ''), '')

    def test_raw_text_kept_even_without_vocab_label(self):
        # v2 가 '지식·정보 관련업'·'무역업'·'여행사' 를 잃던 문제 — 원문 표현은 라벨이 없어도 남는다
        doc = '지원가능 업종 ①제조업 ②지식·정보 관련업 ③무역업 ④여행사'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업'), ('지식·정보 관련업', ''), ('무역업', ''), ('여행사', '')],
                             quote='지원가능 업종 ①제조업 ②지식·정보 관련업 ③무역업 ④여행사'), doc)
        self.assertEqual([a['text'] for a in out['allowed']], ['제조업', '지식·정보 관련업', '무역업', '여행사'])
        self.assertEqual(out['status'], 'known')
        self.assertTrue(out['list_complete'])


class SizeRuleTests(unittest.TestCase):
    def test_real_compound_condition_is_kept(self):
        # 리뷰 반례: '상시근로자' 한 단어로 실제 업종 제한을 내리던 문제
        q = '제조업을 영위하는 상시근로자 10인 이상 기업만 신청'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=q), '[신청자격] ' + q)
        self.assertEqual(out['status'], 'known')
        self.assertEqual(out['allowed'][0]['label_basis'], 'exact')

    def test_size_definition_is_downgraded(self):
        q = '소상공인기본법 제2조(정의)에 의한 소상공인 - 제조업, 건설업, 운수업: 상시근로자 10인 미만'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업'), ('건설업', '건설업')], quote=q), q)
        self.assertEqual(out['status'], 'unknown')
        self.assertIn('규모 정의', out['downgraded'])


class ValueCheckTests(unittest.TestCase):
    def test_excluded_not_in_document_is_dropped(self):
        doc = '지원제외: 유흥업. 신청대상: 음식점업 소상공인에 한함'
        out = s.verify_v3(v3(allowed=[('음식점업', '음식점업')],
                             excluded=[('유흥업', '지원제외: 유흥업'), ('도박업', '지원제외: 도박업')],
                             quote='신청대상: 음식점업 소상공인에 한함'), doc)
        self.assertEqual([e['text'] for e in out['excluded']], ['유흥업'])
        dropped = {d['text']: d['why'] for d in out['dropped']}
        self.assertEqual(dropped['도박업'], '근거가 원문에 없음')

    def test_allowed_not_in_document_is_dropped_and_list_incomplete(self):
        doc = '신청대상: 제조업을 영위하는 중소기업'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업'), ('정보통신업', '정보통신업')], complete=True,
                             quote='제조업을 영위하는 중소기업'), doc)
        self.assertEqual([a['text'] for a in out['allowed']], ['제조업'])
        self.assertFalse(out['list_complete'])

    def test_quote_not_in_document(self):
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote='지어낸 문장'), '제조업 기업만')
        self.assertEqual(out['status'], 'unknown')

    def test_known_without_allowed_is_downgraded(self):
        out = s.verify_v3(v3(allowed=[], quote='중소기업'), '중소기업')
        self.assertEqual(out['status'], 'unknown')

    def test_open_list_with_etc_is_not_complete(self):
        # 실제 v2 오판 사례 유형 — '기업·농가·소상공인 등' 은 전체 목록이 아니다
        q = '모집대상 : 도내 주소지를 둔 기업·농가·소상공인 등'
        out = s.verify_v3(v3(allowed=[('농가', '농업')], complete=True, quote=q), q)
        self.assertFalse(out['list_complete'])

    def test_appendix_reference_is_not_complete(self):
        q = '지원대상 업종[별표1]에 해당하는 소상공인, 택시 및 화물자동차 운송업'
        out = s.verify_v3(v3(allowed=[('택시 및 화물자동차 운송업', '')], complete=True, quote=q), q)
        self.assertFalse(out['list_complete'])

    def test_never_filter_ready(self):
        q = '제조업을 영위하는 기업만 신청 가능'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=q), q)
        self.assertEqual(out['status'], 'known')
        self.assertFalse(out['filter_ready'])


class EvidenceTests(unittest.TestCase):
    """후속 리뷰 F1 — 값마다 원문 근거가 있어야 하고, 허용 값은 신청 자격 quote 안에 있어야 한다."""

    def test_support_content_industries_do_not_pass_as_eligibility(self):
        # 리뷰 재현 입력 그대로
        content = '제조업 디지털 전환 및 유흥업 관리'
        doc = '지원내용: %s\n신청대상은 도내 중소기업' % content
        out = s.verify_v3(v3(allowed=[('제조업', '제조업', content)], excluded=[('유흥업', content)],
                             quote='신청대상은 도내 중소기업'), doc)
        self.assertEqual(out['status'], 'unknown')
        self.assertEqual(out['allowed'], [])
        self.assertEqual(out['excluded'], [])
        why = {(d['kind'], d['text']): d['why'] for d in out['dropped']}
        self.assertEqual(why[('allowed', '제조업')], '신청 자격 근거(quote) 밖의 업종')
        self.assertTrue(why[('excluded', '유흥업')].startswith('제외 표현과 연결되지 않음'))
        self.assertFalse(out['list_complete'])

    def test_missing_evidence_is_dropped(self):
        q = '제조업을 영위하는 기업만 신청 가능'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업', '')], quote=q), q)
        self.assertEqual(out['dropped'][0]['why'], '근거(evidence) 없음')
        self.assertEqual(out['status'], 'unknown')

    def test_value_outside_its_evidence_is_dropped(self):
        doc = '신청대상: 제조업을 영위하는 기업. 건설업 현장 안전 교육 포함'
        out = s.verify_v3(v3(allowed=[('건설업', '건설업', '신청대상: 제조업을 영위하는 기업')],
                             quote='신청대상: 제조업을 영위하는 기업'), doc)
        self.assertEqual(out['dropped'][0]['why'], '값이 근거 문장 안에 없음')

    def test_quote_without_eligibility_cue_is_downgraded(self):
        q = '제조업 디지털 전환 비용 지원'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=q), '[지원내용] ' + q)
        self.assertEqual(out['status'], 'unknown')
        self.assertIn('신청 자격 문장', out['downgraded'])

    def test_excluded_with_exclusion_cue_is_kept_with_evidence(self):
        doc = '신청대상: 도내 소상공인. 단, 유흥주점업은 지원 제외'
        out = s.verify_v3(v3(allowed=[], excluded=[('유흥주점업', '단, 유흥주점업은 지원 제외')], status='unknown',
                             quote=''), doc)
        self.assertEqual(out['excluded'], [{'text': '유흥주점업', 'evidence': '단, 유흥주점업은 지원 제외',
                                            'linked_by': 'clause'}])

    def test_support_content_quote_with_target_word_is_not_eligibility(self):
        # 2차 후속 리뷰 F1 반례 — '대상' 한 단어로 지원 내용이 신청 자격이 되던 문제
        q = '지원내용: 제조업을 대상으로 디지털 전환 비용 지원'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=q), q)
        self.assertEqual(out['status'], 'unknown')
        self.assertIn('지원 내용 문맥', out['downgraded'])

    def test_header_just_before_quote_counts(self):
        # quote 가 머리말 없이 잘려도 원문 바로 앞이 '지원대상' 이면 자격 문장이다
        doc = '□ 지원대상 : 안동시 소재 제조 및 무역업 중소기업\n□ 지원내용 : 해외마케팅'
        q = '안동시 소재 제조 및 무역업 중소기업'
        out = s.verify_v3(v3(allowed=[('제조', '제조업'), ('무역업', '')], quote=q), doc)
        self.assertEqual(out['status'], 'known')
        self.assertEqual(out['quote_role'], 'eligibility')

    def test_support_header_nearer_than_eligibility_header(self):
        doc = '지원대상: 도내 중소기업\n지원내용: 제조업 스마트공장 구축비'
        q = '제조업 스마트공장 구축비'
        self.assertEqual(s.quote_role(q, doc)[0], 'support')

    def test_bizinfo_first_arrow_segment_is_eligibility(self):
        # 기업마당 요약 형식 "개요 ☞ 지원대상 ☞ 지원내용" (실제 bizinfo:PBLN_000000000125687 모양)
        doc = ('[공고 개요]\n안동시 수출기업 역량강화 지원사업 참여 기업을 모집하오니 많은 참여를 바랍니다. '
               '☞ 안동시 소재 제조 및 무역업 중소기업 ☞ 해외마케팅 비용 지원')
        self.assertEqual(s.quote_role('안동시 소재 제조 및 무역업 중소기업', doc)[0], 'eligibility')
        self.assertEqual(s.quote_role('☞ 안동시 소재 제조 및 무역업 중소기업', doc)[0], 'eligibility')

    def test_bizinfo_second_arrow_segment_is_support(self):
        doc = '개요 문장. ☞ 도내 중소기업 ☞ 제조업 스마트공장 구축 비용 지원'
        self.assertEqual(s.quote_role('제조업 스마트공장 구축 비용 지원', doc)[0], 'support')

    def test_bizinfo_intro_before_first_arrow_is_unclear(self):
        # 실제 bizinfo:PBLN_000000000122801 모양 — 개요의 인사 문장은 자격이 아니다
        doc = ('[공고 개요]\n농식품 수출 확대 도모하기 위한 사업입니다. 농식품 수출기업 및 농가 관계자 여러분의 많은 참여 바랍니다. '
               '☞ 수출 실적이 있는 기업 ☞ 해외 시장조사 지원')
        self.assertEqual(s.quote_role('농식품 수출기업 및 농가', doc)[0], 'unclear')

    def test_single_arrow_document_is_not_bizinfo_layout(self):
        doc = '안내 ☞ 제조업 기술개발 지원'
        self.assertEqual(s.quote_role('제조업 기술개발 지원', doc)[0], 'unclear')

    def test_consortium_participant_label_is_eligibility(self):
        doc = 'ㅇ (공급기업) AI 역량 보유 중소기업 ㅇ (수요기업) 연구성과물을 공정에 적용하는 제조기업'
        self.assertEqual(s.quote_role('연구성과물을 공정에 적용하는 제조기업', doc)[0], 'eligibility')

    def test_unregistered_section_header_breaks_context(self):
        # 3차 후속 리뷰 F1 반례 1 — '기타 안내' 구역이 앞 '지원대상' 을 이어받던 문제
        doc = '지원대상: 도내 중소기업. 기타 안내: 제조업 기업 우대 프로그램'
        q = '제조업 기업 우대 프로그램'
        self.assertEqual(s.quote_role(q, doc)[0], 'unclear')
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=q), doc)
        self.assertEqual(out['status'], 'unknown')

    def test_repeated_quote_in_different_sections_is_unclear(self):
        # 3차 후속 리뷰 F1 반례 2 — 같은 문자열이 자격·지원내용 두 구역에 있으면 어느 쪽인지 모른다
        doc = '지원대상: 제조업 기업. 지원내용: 제조업 기업 디지털 전환 비용 지원'
        role, why = s.quote_role('제조업 기업', doc)
        self.assertEqual(role, 'unclear')
        self.assertIn('여러 구역', why)

    def test_repeated_quote_in_same_role_is_kept(self):
        doc = '지원대상: 제조업 기업만 신청. 신청자격: 제조업 기업만 신청'
        self.assertEqual(s.quote_role('제조업 기업만 신청', doc)[0], 'eligibility')

    def test_section_bullet_breaks_context(self):
        doc = '□ 지원대상 도내 중소기업 □ 제조업 기업 우대 안내'
        self.assertEqual(s.quote_role('제조업 기업 우대 안내', doc)[0], 'unclear')

    def test_sub_bullet_keeps_context(self):
        doc = '□ 지원대상 ○ 도내 제조업 영위 기업 ○ 본사 소재지 기준'
        self.assertEqual(s.quote_role('도내 제조업 영위 기업', doc)[0], 'eligibility')

    def test_colon_label_with_eligibility_word(self):
        doc = '□ 참여업종: 제조업, 정보통신업'
        self.assertEqual(s.quote_role('제조업, 정보통신업', doc)[0], 'eligibility')

    def test_exclusion_headers_are_not_eligibility(self):
        # 4차 후속 리뷰 F1 반례 세 건 — 제외 목록을 허용으로 뒤집지 않는다
        for doc, value in (('제외업종: 유흥업', '유흥업'),
                           ('지원제외 업종: 금융ㆍ보험업', '금융ㆍ보험업'),
                           ('비대상 업종: 도박업', '도박업')):
            with self.subTest(doc=doc):
                self.assertEqual(s.quote_role(value, doc)[0], 'exclusion')
                out = s.verify_v3(v3(allowed=[(value, '')], quote=value), doc)
                self.assertEqual(out['status'], 'unknown')
                self.assertIn('제외 목록', out['downgraded'])

    def test_eligibility_then_exclusion_header(self):
        doc = '신청대상: 도내 제조업 영위 기업. 제외업종: 유흥업'
        self.assertEqual(s.quote_role('도내 제조업 영위 기업', doc)[0], 'eligibility')
        self.assertEqual(s.quote_role('유흥업', doc)[0], 'exclusion')

    def test_restriction_phrase_without_header(self):
        self.assertEqual(s.quote_role('제조업을 영위하는 기업만 신청', '제조업을 영위하는 기업만 신청')[0],
                         'eligibility')
        self.assertEqual(s.quote_role('도내 제조업 기업', '도내 제조업 기업')[0], 'unclear')

    def test_schema_requires_evidence(self):
        props = s.schema_v3()['schema']['properties']
        self.assertIn('evidence', props['allowed']['items']['required'])
        self.assertIn('evidence', props['excluded']['items']['required'])


class ExclusionLinkTests(unittest.TestCase):
    """2차 후속 리뷰 F2 — 제외 표현이 그 값에 붙어 있어야 한다."""

    def keep(self, text, evidence):
        return s.excluded_linked(text, evidence)[0]

    def test_review_counterexample_order_a(self):
        ev = '유흥업 교육 포함, 제조업은 지원 제외'
        self.assertFalse(self.keep('유흥업', ev))
        self.assertTrue(self.keep('제조업', ev))

    def test_review_counterexample_order_b(self):
        ev = '유흥업은 지원 제외, 제조업 교육 포함'
        self.assertTrue(self.keep('유흥업', ev))
        self.assertFalse(self.keep('제조업', ev))

    def test_comma_list_ending_with_exclusion(self):
        ev = '유흥업, 도박업 등은 지원 제외'
        self.assertTrue(self.keep('유흥업', ev))
        self.assertTrue(self.keep('도박업', ev))

    def test_exclusion_header_then_list(self):
        ev = '지원제외 업종: 유흥업, 도박업'
        self.assertTrue(self.keep('유흥업', ev))
        self.assertTrue(self.keep('도박업', ev))

    def test_middle_dot_list(self):
        self.assertTrue(self.keep('도박업', '유흥업·도박업 제외'))

    def test_general_phrase_before_comma_is_not_a_list_item(self):
        # 3차 후속 리뷰 F1 반례 — '포함' 이 빠지면 다시 통과하던 문제
        self.assertFalse(self.keep('유흥업', '유흥업 교육, 제조업은 지원 제외'))
        self.assertFalse(self.keep('유흥업', '유흥업 관련 사업, 제조업은 지원 제외'))
        self.assertTrue(self.keep('제조업', '유흥업 관련 사업, 제조업은 지원 제외'))

    def test_new_subject_in_final_clause_stops_list(self):
        # "A, B는 제외" 는 새 주어 때문에 A 를 인정하지 않는다 — 보수적으로 놓치는 쪽
        self.assertFalse(self.keep('유흥업', '유흥업, 제조업은 지원 제외'))

    def test_value_with_internal_separator(self):
        # 3차 후속 리뷰 F2 — 값 안의 ㆍ·· 로 값이 잘리던 문제
        self.assertTrue(self.keep('금융ㆍ보험업', '금융ㆍ보험업은 지원 제외'))
        self.assertTrue(self.keep('숙박·음식점업', '숙박·음식점업은 지원 불가'))
        self.assertTrue(self.keep('금융ㆍ보험업', '지원제외 업종: 금융ㆍ보험업, 사행산업'))
        self.assertTrue(self.keep('사행산업', '지원제외 업종: 금융ㆍ보험업, 사행산업'))

    def test_value_with_spaces_inside(self):
        self.assertTrue(self.keep('금융ㆍ보험업', '금융ㆍ 보험업은 지원 제외'))

    def test_exclusion_predicate_is_not_a_header(self):
        # '지원 제외' 뒤에 콜론이 없으면 목록 머리말이 아니다 — 뒤 절의 값에 붙이지 않는다
        self.assertFalse(self.keep('제조업', '유흥업은 지원 제외, 제조업 우대'))

    def test_header_list_interrupted_by_other_statement(self):
        ev = '지원제외 업종: 유흥업, 단 관광 관련 교육 프로그램은 신청 가능, 제조업'
        self.assertTrue(self.keep('유흥업', ev))
        self.assertFalse(self.keep('제조업', ev))

    def test_verify_drops_unlinked_excluded(self):
        doc = '지원대상: 도내 중소기업. 유흥업 교육 포함, 제조업은 지원 제외'
        ev = '유흥업 교육 포함, 제조업은 지원 제외'
        out = s.verify_v3(v3(status='unknown', excluded=[('유흥업', ev), ('제조업', ev)], quote=''), doc)
        self.assertEqual([e['text'] for e in out['excluded']], ['제조업'])
        self.assertIn('제외 표현과 연결되지 않음', out['dropped'][0]['why'])


class PromptArgTests(unittest.TestCase):
    def test_prompt_is_required(self):
        with self.assertRaises(SystemExit):
            s.main([])

    def test_legacy_needs_explicit_permission(self):
        for p in ('v1', 'v2'):
            with self.assertRaises(SystemExit):
                s.check_prompt_args(p, allow_legacy=False)
            s.check_prompt_args(p, allow_legacy=True)
        s.check_prompt_args('v3', allow_legacy=False)

    def test_prompt_and_schema_hashes_differ_by_version(self):
        self.assertNotEqual(s.prompt_sha256('v2'), s.prompt_sha256('v3'))
        self.assertNotEqual(s.schema_sha256('v2'), s.schema_sha256('v3'))
        self.assertEqual(s.schema_sha256('v1'), s.schema_sha256('v2'))

    def test_legacy_verify_alias_unchanged(self):
        self.assertIs(s.verify, s.verify_legacy)


def make_item(nid, body='본문', target='신청대상: 제조업 기업'):
    return s.prepare({'notice_id': nid, 'title': nid, 'body': body, 'target_text': target, 'attachments': []})


class FingerprintTests(unittest.TestCase):
    def test_document_hash(self):
        it = make_item('a')
        self.assertEqual(it['document_sha256'], s.sha256_text(it['document']))

    def test_resume_key_changes_with_document_and_prompt(self):
        a, b = make_item('a'), make_item('a', body='다른 본문')
        self.assertNotEqual(s.resume_key('a', a['document_sha256'], 'v3'),
                            s.resume_key('a', b['document_sha256'], 'v3'))
        self.assertNotEqual(s.resume_key('a', a['document_sha256'], 'v2'),
                            s.resume_key('a', a['document_sha256'], 'v3'))

    def test_resume_key_includes_schema_hash(self):
        key = s.resume_key('a', 'd' * 64, 'v3')
        self.assertIn(s.schema_sha256('v3'), key)
        self.assertIn(s.prompt_sha256('v3'), key)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_results(self, rows, meta=None):
        with io.open(os.path.join(self.dir, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        if meta:
            with io.open(os.path.join(self.dir, 'meta.json'), 'w', encoding='utf-8') as f:
                json.dump(meta, f)


class PreviousRunTests(TempDirCase):
    def test_old_run_without_hash_is_limited(self):
        items = [make_item('a')]
        self.write_results([{'notice_id': 'a', 'llm': {'status': 'known'},
                             'doc_chars': len(items[0]['document']), 'attachments_count': 0}])
        _prev, prompt, grade = s.load_previous(self.dir, items)
        self.assertEqual(grade, 'limited')
        self.assertEqual(prompt, 'v1')

    def test_same_hash_is_exact(self):
        items = [make_item('a')]
        self.write_results([{'notice_id': 'a', 'llm': {}, 'document_sha256': items[0]['document_sha256']}],
                           meta={'prompt': 'v2'})
        _prev, prompt, grade = s.load_previous(self.dir, items)
        self.assertEqual((prompt, grade), ('v2', 'exact'))

    def test_different_hash_is_refused(self):
        items = [make_item('a')]
        self.write_results([{'notice_id': 'a', 'llm': {}, 'document_sha256': 'x' * 64}])
        with self.assertRaises(SystemExit):
            s.load_previous(self.dir, items)

    def test_old_run_with_different_length_is_refused(self):
        items = [make_item('a')]
        self.write_results([{'notice_id': 'a', 'llm': {}, 'doc_chars': 1, 'attachments_count': 0}])
        with self.assertRaises(SystemExit):
            s.load_previous(self.dir, items)


class CheckpointTests(TempDirCase):
    def test_partial_failure_keeps_successes_and_resume_calls_only_failed(self):
        items = [make_item('a'), make_item('b'), make_item('c')]
        answer = (v3(allowed=[('제조업', '제조업')], quote='제조업 기업'), {'in': 10, 'out': 2, 'ms': 1, 'model': 'm'})

        def flaky(it):
            if it['notice_id'] == 'b':
                raise RuntimeError('rate limit')
            return answer

        done, failures, called = s.run_calls(items, 'v3', self.dir, flaky, workers=2)
        self.assertEqual(called, 3)
        self.assertEqual([f['notice_id'] for f in failures], ['b'])
        self.assertEqual(len(done), 2)
        self.assertEqual(len(s.load_checkpoint(self.dir)), 2)     # 성공은 파일에 남았다

        seen = []

        def ok(it):
            seen.append(it['notice_id'])
            return answer

        done, failures, called = s.run_calls(items, 'v3', self.dir, ok, workers=2)
        self.assertEqual(seen, ['b'])
        self.assertEqual((called, len(failures), len(done)), (1, 0, 3))

    def test_other_prompt_is_not_reused(self):
        items = [make_item('a')]
        answer = (v3(), {'in': 1, 'out': 1, 'ms': 1, 'model': 'm'})
        s.run_calls(items, 'v3', self.dir, lambda it: answer)
        seen = []
        s.run_calls(items, 'v2', self.dir, lambda it: seen.append(1) or answer)
        self.assertEqual(seen, [1])


class ResumeRunTests(TempDirCase):
    """후속 리뷰 F2 — main 수준에서 일부 실패 → 안내된 재개 명령 → 이전 실행 비교 열·등급 보존."""

    def setUp(self):
        super().setUp()
        self.items = [make_item('a'), make_item('b')]
        self.ids = ['a', 'b']
        self.prev = os.path.join(self.dir, 'prev')
        self.out = os.path.join(self.dir, 'run')
        os.makedirs(self.prev)
        with io.open(os.path.join(self.prev, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for it in self.items:
                f.write(json.dumps({'notice_id': it['notice_id'], 'llm': {'status': 'known'},
                                    'document_sha256': it['document_sha256']}) + '\n')
        with io.open(os.path.join(self.prev, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'prompt': 'v2'}, f)

    def answer(self, model='m'):
        return (v3(allowed=[('제조업', '제조업')], quote='신청대상: 제조업 기업'),
                {'in': 10, 'out': 2, 'ms': 1, 'model': model})

    def args(self, *argv):
        return s.build_parser().parse_args(['--prompt', 'v3', '--workers', '1'] + list(argv))

    def first_run_with_failure(self):
        def flaky(it):
            if it['notice_id'] == 'b':
                raise RuntimeError('timeout')
            return self.answer()
        code = s.run_experiment(self.args('--previous', self.prev, '--out', self.out),
                                self.items, self.ids, 2, lambda: flaky)
        self.assertEqual(code, 3)

    def fresh_items(self):
        return [make_item('a'), make_item('b')]     # 재개는 새 프로세스라 항목을 다시 만든다

    def test_resume_keeps_previous_comparison(self):
        self.first_run_with_failure()
        meta = s.read_json(os.path.join(self.out, 'meta.json'))
        self.assertEqual((meta['previous'], meta['previous_grade']), (self.prev, 'exact'))

        seen = []

        def ok(it):
            seen.append(it['notice_id'])
            return self.answer()
        code = s.run_experiment(self.args('--resume', self.out), self.fresh_items(), self.ids, 2, lambda: ok)
        self.assertEqual(code, 0)
        self.assertEqual(seen, ['b'])
        meta = s.read_json(os.path.join(self.out, 'meta.json'))
        self.assertEqual(meta['previous'], self.prev)
        self.assertEqual(meta['previous_prompt'], 'v2')
        self.assertEqual(meta['previous_grade'], 'exact')
        self.assertEqual(meta['resume_count'], 1)
        self.assertFalse(meta['mixed_models'])
        with io.open(os.path.join(self.out, 'summary.md'), encoding='utf-8') as f:
            summary = f.read()
        self.assertIn('LLM 이전 실행 (v2)', summary)
        self.assertIn('비교 등급: **exact**', summary)

    def test_resume_with_other_previous_is_refused(self):
        self.first_run_with_failure()
        other = os.path.join(self.dir, 'other')
        with self.assertRaises(SystemExit):
            s.run_experiment(self.args('--resume', self.out, '--previous', other),
                             self.fresh_items(), self.ids, 2, lambda: (lambda it: self.answer()))

    def test_resume_with_changed_schema_hash_is_refused(self):
        self.first_run_with_failure()
        path = os.path.join(self.out, 'meta.json')
        meta = s.read_json(path)
        meta['schema_sha256'] = '0' * 64
        with io.open(path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        with self.assertRaises(SystemExit):
            s.run_experiment(self.args('--resume', self.out), self.fresh_items(), self.ids, 2,
                             lambda: (lambda it: self.answer()))

    def test_mixed_models_are_flagged(self):
        self.first_run_with_failure()
        s.run_experiment(self.args('--resume', self.out), self.fresh_items(), self.ids, 2,
                         lambda: (lambda it: self.answer(model='m2')))
        meta = s.read_json(os.path.join(self.out, 'meta.json'))
        self.assertTrue(meta['mixed_models'])
        with io.open(os.path.join(self.out, 'summary.md'), encoding='utf-8') as f:
            self.assertIn('혼합 실행', f.read())

    def test_plan_does_not_call(self):
        def boom():
            raise AssertionError('plan 은 호출 함수를 만들지 않는다')
        self.assertEqual(s.run_experiment(self.args('--plan', '--out', self.out), self.items, self.ids, 2, boom), 0)
        self.assertFalse(os.path.exists(self.out))


class ModelOptionTests(TempDirCase):
    """모델 선택(2026-09-22 사용자 요청 — gpt-5.6-sol 시험)."""

    def test_request_options(self):
        self.assertEqual(s.request_options('gpt-4o-mini'), {'temperature': 0})
        self.assertEqual(s.request_options('gpt-5.6-sol'), {})                     # 추론 모델은 temperature 없음
        self.assertEqual(s.request_options('gpt-5.6-sol', 'low'), {'reasoning_effort': 'low'})
        with self.assertRaises(SystemExit):
            s.request_options('gpt-4o-mini', 'low')

    def test_engine_separates_checkpoints(self):
        items = [make_item('a')]
        answer = (v3(), {'in': 1, 'out': 1, 'ms': 1, 'model': 'm'})
        s.run_calls(items, 'v3', self.dir, lambda it: answer, engine='gpt-4o-mini')
        seen = []
        s.run_calls(items, 'v3', self.dir, lambda it: seen.append(1) or answer, engine='gpt-5.6-sol@low')
        self.assertEqual(seen, [1])

    def test_plan_uses_model_price_and_default_is_unchanged(self):
        args = s.build_parser().parse_args(['--prompt', 'v3'])
        self.assertEqual((args.model, args.reasoning_effort), ('gpt-4o-mini', None))
        args = s.build_parser().parse_args(['--prompt', 'v3', '--model', 'gpt-5.6-sol', '--reasoning-effort', 'low',
                                            '--plan', '--out', os.path.join(self.dir, 'o')])
        self.assertEqual(s.run_experiment(args, [make_item('a')], ['a'], 1, lambda: None), 0)

    def test_all_flag_and_resume_must_match(self):
        self.assertFalse(s.build_parser().parse_args(['--prompt', 'v3']).take_all)
        self.assertTrue(s.build_parser().parse_args(['--prompt', 'v3', '--all']).take_all)
        out = os.path.join(self.dir, 'full')
        os.makedirs(out)
        with io.open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'prompt': 'v3', 'run_at': '2026-09-22T00:00:00+00:00', 'engine': 'gpt-4o-mini',
                       'take_all': True}, f)
        with self.assertRaises(SystemExit):     # 전량 실행을 표본으로 재개하면 안 된다
            s.resume_settings(s.build_parser().parse_args(['--prompt', 'v3', '--resume', out]))
        s.resume_settings(s.build_parser().parse_args(['--prompt', 'v3', '--resume', out, '--all']))

    def test_all_with_previous_is_refused(self):
        with self.assertRaises(SystemExit):
            s.main(['--prompt', 'v3', '--all', '--previous', self.dir])

    def test_resume_with_other_model_is_refused(self):
        out = os.path.join(self.dir, 'run')
        os.makedirs(out)
        with io.open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'prompt': 'v3', 'run_at': '2026-09-22T00:00:00+00:00', 'engine': 'gpt-4o-mini'}, f)
        args = s.build_parser().parse_args(['--prompt', 'v3', '--resume', out, '--model', 'gpt-5.6-sol'])
        with self.assertRaises(SystemExit):
            s.resume_settings(args)


class ProfileTests(unittest.TestCase):
    """검사 강도 strict / rough (2026-09-22 사용자 요청) 와 Codex 전량 리뷰 F1 불변식."""

    def test_rough_ignores_whitespace_bullet_and_dot_differences(self):
        # 안동 유형 — LLM 이 머리말·공백을 다르게 옮겨 strict 에서 '근거 문장이 원문에 없음'
        doc = '○ 지 원 대 상 : 안동시 소재 제조 및 무역업 중소기업'
        q = '□ (지원대상) 안동시 소재 제조 및 무역업 중소기업'
        data = v3(allowed=[('제조', '제조업'), ('무역업', '')], quote=q)
        self.assertEqual(s.verify_v3(data, doc, 'strict')['status'], 'unknown')
        out = s.verify_v3(data, doc, 'rough')
        self.assertEqual(out['status'], 'known')
        self.assertEqual([a['text'] for a in out['allowed']], ['제조', '무역업'])

    def test_rough_accepts_unclear_role_but_not_support(self):
        doc = '대구 지역 법인기업 중 대구 5대 신산업 분야 기업'
        q = '대구 5대 신산업 분야 기업'
        data = v3(allowed=[('신산업 분야', '')], quote=q)
        self.assertEqual(s.quote_role(q, doc)[0], 'unclear')
        self.assertEqual(s.verify_v3(data, doc, 'strict')['status'], 'unknown')
        self.assertEqual(s.verify_v3(data, doc, 'rough')['status'], 'known')
        support = '지원내용: 제조업을 대상으로 디지털 전환 비용 지원'
        self.assertEqual(s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=support), support, 'rough')['status'],
                         'unknown')

    def test_rough_keeps_size_word_and_no_limit_rules(self):
        q = '신청대상: 도내 중소기업'
        out = s.verify_v3(v3(allowed=[('중소기업', '')], quote=q), q, 'rough')
        self.assertEqual(out['status'], 'unknown')
        nl = s.verify_v3(v3('no_limit', no_limit_text='누구나', quote='누구나'), '참가자 누구나', 'rough')
        self.assertEqual(nl['status'], 'unknown')

    def test_size_form_values_are_dropped_in_both_profiles(self):
        # Codex 전량 리뷰 F2 — '사회적기업' 이 허용 업종에 섞이던 문제
        q = '지원대상: 제조업, 문화산업, 사회적기업'
        for profile in s.PROFILES:
            out = s.verify_v3(v3(allowed=[('제조업', '제조업'), ('문화산업', ''), ('사회적기업', '')], quote=q), q, profile)
            self.assertEqual([a['text'] for a in out['allowed']], ['제조업', '문화산업'])

    def test_rough_value_must_still_be_in_document(self):
        q = '신청대상: 도내 제조업 영위 기업'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업'), ('정보통신업', '정보통신업', q)], quote=q), q, 'rough')
        self.assertEqual([a['text'] for a in out['allowed']], ['제조업'])

    def test_invariant_final_unknown_has_no_allowed(self):
        # Codex 전량 리뷰 F1 — 최종 unknown 인데 allowed 가 남던 111건
        doc = '지원내용: 제조업 스마트공장 구축비'
        for profile in s.PROFILES:
            out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote='제조업 스마트공장 구축비'), doc, profile)
            self.assertEqual(out['status'], 'unknown')
            self.assertEqual(out['allowed'], [])
            self.assertEqual([a['text'] for a in out['raw_allowed']], ['제조업'])
        raw_unknown = s.verify_v3(v3('unknown', allowed=[('제조업', '제조업')], quote='신청대상: 제조업 기업'),
                                  '신청대상: 제조업 기업')
        self.assertEqual(raw_unknown['allowed'], [])
        nl = s.verify_v3(v3('known', allowed=[('제조업', '제조업')], no_limit_text='업종 제한 없음',
                            quote='신청대상: 제조업 기업'), '신청대상: 제조업 기업')
        self.assertEqual(nl['no_limit_text'], '')

    def test_loose_found_fuzzy(self):
        doc = '신청대상 : 태백시 소재 중소기업 중 아래 요건을 충족하는 기업 지원가능 업종 ①제조업 ②지식ㆍ정보 관련업'
        self.assertTrue(s.loose_found('❑ 지원대상: 태백시 소재 중소기업 중 아래 요건을 충족하는 기업', doc))
        self.assertFalse(s.loose_found('전혀 다른 문장으로 된 근거입니다', doc))


class IndustryStatusTests(unittest.TestCase):
    """매칭용 판정 나누기 (2026-09-22 사용자 결정)."""

    def status(self, data, doc, cap=None):
        out = s.verify_v3(data, doc, 'rough', cap)
        return out['industry_status'], out['industry_status_why']

    def test_known_and_no_limit_pass_through(self):
        q = '신청대상: 제조업을 영위하는 기업만 신청'
        self.assertEqual(self.status(v3(allowed=[('제조업', '제조업')], quote=q), q)[0], 'known')
        self.assertEqual(self.status(v3('no_limit', no_limit_text='업종 제한 없음', quote='업종 제한 없음'),
                                     '신청대상: 업종 제한 없음')[0], 'no_limit')

    def test_eligibility_found_without_industry_is_not_mentioned(self):
        q = '신청대상: 도내 소재 중소기업'
        self.assertEqual(self.status(v3('unknown', quote=q), q), ('not_mentioned', ''))

    def test_excluded_only(self):
        doc = '신청대상: 도내 소상공인. 단, 유흥업은 지원 제외'
        data = v3('unknown', excluded=[('유흥업', '단, 유흥업은 지원 제외')], quote='신청대상: 도내 소상공인')
        self.assertEqual(self.status(data, doc)[0], 'excluded_only')

    def test_true_unknowns(self):
        self.assertEqual(self.status(v3('unknown', quote=''), '공고 개요')[0], 'unknown')
        support = '지원내용: 제조업 스마트공장 구축비'
        st, why = self.status(v3(allowed=[('제조업', '제조업')], quote=support), support)
        self.assertEqual(st, 'unknown')
        self.assertIn('검사가 내림', why)

    def test_truncated_excerpt_stays_unknown(self):
        q = '신청대상: 도내 소재 중소기업'
        doc = q + ' ' + '가' * 6000
        st, why = self.status(v3('unknown', quote=q), doc, cap=6000)
        self.assertEqual(st, 'unknown')
        self.assertIn('잘림', why)
        self.assertEqual(self.status(v3('unknown', quote=q), doc, cap=18000)[0], 'not_mentioned')

    def test_every_code_has_label(self):
        self.assertEqual(set(s.INDUSTRY_STATUS),
                         {'known', 'no_limit', 'not_mentioned', 'excluded_only', 'conditional', 'unknown'})

    def test_dropped_excluded_is_not_not_mentioned(self):
        # Codex 후속 리뷰 F1 — 제외 업종을 찾았지만 연결 검사에서 빠진 244건이 "언급 없음"이 되던 문제
        doc = '신청대상: 도내 소상공인. 금융·보험업 등 보증제한업종 해당 기업'
        data = v3('unknown', excluded=[('금융·보험업', '금융·보험업 등 보증제한업종 해당 기업')], quote='신청대상: 도내 소상공인')
        out = s.verify_v3(data, doc, 'rough')
        self.assertEqual(out['excluded'], [])                           # 연결 검사는 통과 못 한다
        self.assertEqual(out['industry_status'], 'unknown')
        self.assertIn('제외 업종 후보', out['industry_status_why'])

    def test_raw_unknown_with_allowed_candidates_is_unknown(self):
        q = '신청대상: 제조업 기업'
        out = s.verify_v3(v3('unknown', allowed=[('제조업', '제조업')], quote=q), q, 'rough')
        self.assertEqual(out['industry_status'], 'unknown')
        self.assertIn('허용 업종 후보', out['industry_status_why'])

    def test_umbrella_notice_is_conditional(self):
        q = '신청대상: K-수출전략품목 분야 제조 중소기업만 신청'
        out = s.verify_v3(v3(allowed=[('제조', '제조업')], quote=q), q, 'rough',
                          title='2026년 중소기업 수출지원사업 통합공고')
        self.assertEqual(out['status'], 'known')
        self.assertEqual(out['industry_status'], 'conditional')
        self.assertEqual(s.verify_v3(v3(allowed=[('제조', '제조업')], quote=q), q, 'rough',
                                     title='2026년 수출 바우처')['industry_status'], 'known')

    def test_all_mixed_with_specific_is_conditional(self):
        q = '신청대상: 제조업 영위 기업, 중점 육성기업은 전업종'
        out = s.verify_v3(v3(allowed=[('제조업', '제조업'), ('전업종', '')], quote=q), q, 'rough')
        self.assertEqual(out['industry_status'], 'conditional')

    def test_truncated_known_is_flagged_and_not_complete(self):
        # Codex 후속 리뷰 F2 — 잘린 known 을 list_complete=True 로 두던 문제
        q = '신청대상: 제조업을 영위하는 기업만 신청'
        doc = q + ' ' + '가' * 6000
        out = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote=q, complete=True), doc, 'rough', 6000)
        self.assertEqual(out['industry_status'], 'known')
        self.assertTrue(out['truncated'])
        self.assertFalse(out['list_complete'])
        self.assertIn('잘려', out['industry_status_why'])


class ExclusionHeaderTests(unittest.TestCase):
    """제외 목록 머리말이 윗줄에 있는 경우 (2026-09-22 사용자 요청, rough 만)."""

    DOC = ('□ 신청대상: 도내 소재 중소기업 및 소상공인\n'
           '□ 지원 제외 대상\n - 사치향락업종(골프장, 무도장)\n - 주점업 등 소비향락업체, 부동산업, 갬블링업 등\n'
           '□ 지원내용: 운전자금 융자')

    def data(self, excluded):
        return v3('unknown', excluded=excluded, quote='신청대상: 도내 소재 중소기업 및 소상공인')

    def test_list_line_under_exclusion_header_is_excluded(self):
        out = s.verify_v3(self.data([('골프장', '사치향락업종(골프장, 무도장)'),
                                     ('부동산업', '주점업 등 소비향락업체, 부동산업, 갬블링업 등')]), self.DOC, 'rough')
        self.assertEqual([e['text'] for e in out['excluded']], ['골프장', '부동산업'])
        self.assertEqual({e['linked_by'] for e in out['excluded']}, {'header'})
        self.assertEqual(out['industry_status'], 'excluded_only')

    def test_strict_does_not_use_header_rule(self):
        out = s.verify_v3(self.data([('골프장', '사치향락업종(골프장, 무도장)')]), self.DOC, 'strict')
        self.assertEqual(out['excluded'], [])

    def test_other_section_between_blocks_header(self):
        doc = '□ 지원 제외 대상: 유흥업\n□ 지원내용\n - 제조업 스마트화 비용'
        out = s.verify_v3(self.data([('제조업', '제조업 스마트화 비용')]), doc, 'rough')
        self.assertEqual(out['excluded'], [])

    def test_positive_marker_blocks_header(self):
        # Codex 2차 후속 반례 유형 — 포함 표현이 있으면 머리말이 위에 있어도 인정하지 않는다
        doc = '□ 지원 제외 대상\n - 유흥업 교육 포함, 제조업은 지원 제외'
        out = s.verify_v3(self.data([('유흥업', '유흥업 교육 포함, 제조업은 지원 제외')]), doc, 'rough')
        self.assertEqual(out['excluded'], [])

    def test_eligibility_header_nearest_is_not_exclusion(self):
        doc = '□ 지원 제외 대상: 유흥업\n□ 신청대상\n - 제조업, 정보통신업 영위 기업'
        out = s.verify_v3(self.data([('제조업', '제조업, 정보통신업 영위 기업')]), doc, 'rough')
        self.assertEqual(out['excluded'], [])

    def test_restriction_header_words(self):
        for head in ('보증 제한 업종', '제외업종', '참여 제한 대상', '융자 제외'):
            ok, _ = s.exclusion_by_header('도박업, 유흥업', '□ ' + head + '\n - 도박업, 유흥업')
            self.assertTrue(ok, head)
        ok, _ = s.exclusion_by_header('제조업', '업력 제한 없음. 제조업')
        self.assertFalse(ok)


class MergeAndIdsTests(TempDirCase):
    def write_run(self, name, rows, meta):
        d = os.path.join(self.dir, name)
        os.makedirs(d)
        with io.open(os.path.join(d, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        with io.open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        return d

    def row(self, nid, status):
        return {'notice_id': nid, 'title': nid, 'regex': {'status': 'unknown'},
                'llm': {'status': status, 'industry_status': status, 'allowed': [], 'excluded': [],
                        'list_complete': False, 'quote': ''}}

    def test_merge_replaces_only_override_ids(self):
        base = self.write_run('base', [self.row('a', 'unknown'), self.row('b', 'not_mentioned')],
                              {'prompt': 'v3', 'reverified_from': 'x', 'source_cost_usd': 2.0,
                               'tokens_in': 100, 'tokens_out': 10, 'response_models': ['m']})
        over = self.write_run('over', [self.row('a', 'known')], {'prompt': 'v3', 'cost_usd': 0.3, 'max_chars': 18000,
                                                               'tokens_in': 50, 'tokens_out': 5,
                                                               'response_models': ['m']})
        out = os.path.join(self.dir, 'merged')
        meta, _ = s.merge_runs(base, over, out)
        self.assertEqual((meta['tokens_in'], meta['tokens_out'], meta['mixed_models']), (150, 15, False))
        rows = {r['notice_id']: r for r in s.read_jsonl(os.path.join(out, 'results.jsonl'))}
        self.assertEqual(rows['a']['llm']['status'], 'known')
        self.assertEqual(rows['a']['source_run'], 'over')
        self.assertEqual(rows['b']['source_run'], 'base')
        self.assertEqual((meta['source_cost_usd'], meta['called_this_run']), (2.3, 0))
        self.assertEqual(meta['merged_from']['override_max_chars'], 18000)

    def test_second_merge_keeps_history_and_sources(self):
        base = self.write_run('base', [self.row('a', 'unknown'), self.row('b', 'unknown')],
                              {'prompt': 'v3', 'tokens_in': 1, 'tokens_out': 1})
        long1 = self.write_run('long1', [self.row('a', 'known')], {'prompt': 'v3', 'max_chars': 18000})
        m1 = os.path.join(self.dir, 'm1')
        s.merge_runs(base, long1, m1)
        long2 = self.write_run('long2', [self.row('b', 'known')], {'prompt': 'v3', 'max_chars': 18000})
        m2 = os.path.join(self.dir, 'm2')
        meta, _ = s.merge_runs(m1, long2, m2)
        rows = {r['notice_id']: r for r in s.read_jsonl(os.path.join(m2, 'results.jsonl'))}
        self.assertEqual((rows['a']['source_run'], rows['b']['source_run']), ('long1', 'long2'))
        self.assertEqual([h['override'] for h in meta['merge_history']], ['long1', 'long2'])

    def test_merge_refuses_stray_ids_and_other_prompt(self):
        base = self.write_run('base', [self.row('a', 'unknown')], {'prompt': 'v3'})
        stray = self.write_run('stray', [self.row('zzz', 'known')], {'prompt': 'v3'})
        with self.assertRaises(SystemExit):
            s.merge_runs(base, stray, os.path.join(self.dir, 'm1'))
        other = self.write_run('other', [self.row('a', 'known')], {'prompt': 'v2'})
        with self.assertRaises(SystemExit):
            s.merge_runs(base, other, os.path.join(self.dir, 'm2'))
        base2 = self.write_run('base2', [self.row('a', 'unknown')], {'prompt': 'v3', 'model': 'gpt-5.6-luna'})
        other_model = self.write_run('om', [self.row('a', 'known')], {'prompt': 'v3', 'model': 'gpt-4o-mini'})
        with self.assertRaises(SystemExit):
            s.merge_runs(base2, other_model, os.path.join(self.dir, 'm3'))

    def test_read_ids(self):
        p = os.path.join(self.dir, 'ids.txt')
        with io.open(p, 'w', encoding='utf-8') as f:
            f.write('# 잘린 공고\na\n\nb\na\n')
        self.assertEqual(s.read_ids(p), ['a', 'b'])

    def test_resume_requires_same_max_chars(self):
        out = os.path.join(self.dir, 'long')
        os.makedirs(out)
        with io.open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'prompt': 'v3', 'run_at': '2026-09-22T00:00:00+00:00', 'engine': 'gpt-4o-mini',
                       'max_chars': 18000}, f)
        with self.assertRaises(SystemExit):
            s.resume_settings(s.build_parser().parse_args(['--prompt', 'v3', '--resume', out]))
        s.resume_settings(s.build_parser().parse_args(['--prompt', 'v3', '--resume', out, '--max-chars', '18000']))


class ReverifyAndFolderTests(TempDirCase):
    def make_source(self, items, prompt='v3'):
        src = os.path.join(self.dir, 'src')
        os.makedirs(src)
        with io.open(os.path.join(src, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'prompt': prompt, 'engine': 'gpt-5.6-luna@medium', 'run_at': '2026-09-22T00:00:00+00:00',
                       'cost_usd': 1.0, 'notice_ids': [it['notice_id'] for it in items]}, f)
        for it in items:
            s.append_jsonl(os.path.join(src, 'checkpoint.jsonl'), {
                'key': 'k' + it['notice_id'], 'notice_id': it['notice_id'], 'document_sha256': it['document_sha256'],
                'data': v3(allowed=[('제조업', '제조업')], quote='신청대상: 제조업 기업'),
                'usage': {'in': 10, 'out': 2, 'model': 'gpt-5.6-luna'}})
        return src

    def test_reverify_uses_saved_answers_without_calls(self):
        items = [make_item('a'), make_item('b')]
        src = self.make_source(items)
        out = os.path.join(self.dir, 'rough')
        meta, _lines = s.reverify(src, items, 'rough', out, counterpart='strict_run')
        self.assertEqual((meta['called_this_run'], meta['cost_usd'], meta['profile']), (0, 0.0, 'rough'))
        self.assertEqual(meta['source_cost_usd'], 1.0)
        rows = s.read_jsonl(os.path.join(out, 'results.jsonl'))
        self.assertEqual([r['llm']['status'] for r in rows], ['known', 'known'])

    def test_reverify_refuses_changed_document(self):
        items = [make_item('a')]
        src = self.make_source(items)
        with self.assertRaises(SystemExit):
            s.reverify(src, [make_item('a', body='바뀐 본문')], 'rough', os.path.join(self.dir, 'o'))

    def test_new_run_refuses_existing_output_folder(self):
        # Codex 전량 리뷰 F2 — --resume 없이 기존 폴더를 쓰면 옛 체크포인트가 조용히 섞였다
        out = os.path.join(self.dir, 'used')
        os.makedirs(out)
        s.append_jsonl(os.path.join(out, 'checkpoint.jsonl'), {'key': 'x', 'notice_id': 'a'})
        args = s.build_parser().parse_args(['--prompt', 'v3', '--out', out])
        with self.assertRaises(SystemExit):
            s.run_experiment(args, [make_item('a')], ['a'], 1, lambda: (lambda it: None))

    def test_run_calls_without_reuse_ignores_checkpoint(self):
        items = [make_item('a')]
        answer = (v3(), {'in': 1, 'out': 1, 'ms': 1, 'model': 'm'})
        s.run_calls(items, 'v3', self.dir, lambda it: answer)
        seen = []
        s.run_calls(items, 'v3', self.dir, lambda it: seen.append(1) or answer, reuse=False)
        self.assertEqual(seen, [1])


class ReportTests(TempDirCase):
    def test_v3_report_marks_failures_and_no_filter(self):
        items = [make_item('a'), make_item('b')]
        items[0]['llm'] = s.verify_v3(v3(allowed=[('제조업', '제조업')], quote='신청대상: 제조업 기업'),
                                      items[0]['document'])
        items[1]['llm'] = None
        meta = {'run_at': '2026-09-22T00:00:00+00:00', 'prompt': 'v3', 'failures': 1, 'downgraded': 0,
                'tokens_in': 10, 'tokens_out': 2, 'cost_usd': 0.0}
        lines = '\n'.join(s.write_report(self.dir, items, meta))
        self.assertIn('미완료: 실패 1건', lines)
        self.assertIn('탈락 필터 사용 가능 0건', lines)
        self.assertIn('청구액 아님', lines)
        rows = s.read_jsonl(os.path.join(self.dir, 'results.jsonl'))
        self.assertEqual(rows[0]['document_sha256'], items[0]['document_sha256'])
        self.assertEqual(rows[0]['run_at'], meta['run_at'])


if __name__ == '__main__':
    unittest.main()
