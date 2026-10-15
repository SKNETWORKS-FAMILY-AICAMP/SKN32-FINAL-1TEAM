# -*- coding: utf-8 -*-
"""신청자 유형 LLM 추출의 코드 검사(verify) — DB·LLM 없음 (2026-09-28)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiments.sql_semantic import applicant_type_llm as atl  # noqa: E402

DOC = ('[공고 개요] 수출 지원 사업 □ 지원대상: 공고일 현재 법인사업자로 등록된 도내 중소기업(개인사업자 제외) '
       '□ 지원내용: 예비창업자 교육 포함 해외 전시 참가 지원 □ 제출서류: 법인등기부등본(법인에 한함) 1부')


def raw(pre=('not_mentioned', None), sole=('not_mentioned', None), corp=('not_mentioned', None), varies=False):
    cell = lambda s: {'status': s[0], 'evidence': s[1]}
    return {'pre_founder': cell(pre), 'sole_proprietor': cell(sole), 'corporation': cell(corp),
            'varies': varies, 'reason': ''}


class VerifyTests(unittest.TestCase):
    def test_eligibility_evidence_is_kept_strong(self):
        v = atl.verify(raw(sole=('not_allowed', '법인사업자로 등록된 도내 중소기업(개인사업자 제외)'),
                           corp=('allowed', '공고일 현재 법인사업자로 등록된 도내 중소기업')), DOC)
        self.assertEqual(v['sole_proprietor']['status'], 'not_allowed')
        self.assertEqual(v['sole_proprietor']['strength'], 'strong')
        self.assertEqual(atl.gate_view(v), {'sole_proprietor': 'not_allowed'})

    def test_document_list_is_not_eligibility(self):
        v = atl.verify(raw(sole=('not_allowed', '법인등기부등본(법인에 한함) 1부')), DOC)
        self.assertEqual(v['sole_proprietor']['status'], 'not_mentioned')
        self.assertEqual(v['sole_proprietor']['dropped'], '제출 서류 설명')

    def test_support_context_is_dropped(self):
        v = atl.verify(raw(pre=('allowed', '예비창업자 교육 포함 해외 전시 참가 지원')), DOC)
        self.assertEqual(v['pre_founder']['status'], 'not_mentioned')
        self.assertEqual(v['pre_founder']['dropped'], '지원 내용 문맥')

    def test_invented_evidence_is_dropped(self):
        v = atl.verify(raw(pre=('not_allowed', '예비창업자는 신청할 수 없습니다')), DOC)
        self.assertEqual(v['pre_founder']['dropped'], '근거가 원문에 없음')

    def test_varies_blocks_gate_and_implied_is_not_gated(self):
        ev = '법인사업자로 등록된 도내 중소기업(개인사업자 제외)'
        self.assertEqual(atl.gate_view(atl.verify(raw(sole=('not_allowed', ev), varies=True), DOC)), {})
        v = atl.verify(raw(pre=('implied_no', '공고일 현재 법인사업자로 등록된 도내 중소기업')), DOC)
        self.assertEqual(v['pre_founder']['status'], 'implied_no')
        self.assertEqual(atl.gate_view(v), {})             # 추정은 탈락 근거로 쓰지 않는다


class ResumeTests(unittest.TestCase):
    """Codex 통합 검수 P1 — 전량 폴더를 표본 모드로 재개하면 결과를 쓰기 전에 멈춘다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_full_folder_without_all_is_refused_by_name(self):
        full = os.path.join(self.tmp, 'applicant_type_llm_full_20260928T023916Z')
        os.makedirs(full)
        with self.assertRaises(SystemExit):
            atl.check_resume(full, False, ['a'])
        atl.check_resume(full, True, ['a'])                     # --all 이면 통과

    def test_spec_mode_and_ids_must_match(self):
        folder = os.path.join(self.tmp, 'applicant_type_llm_20260928T000000Z')
        os.makedirs(folder)
        with io.open(os.path.join(folder, 'run_spec.json'), 'w', encoding='utf-8') as f:
            json.dump({'take_all': False, 'notice_ids': ['a', 'b']}, f)
        atl.check_resume(folder, False, ['a', 'b'])
        with self.assertRaises(SystemExit):
            atl.check_resume(folder, True, ['a', 'b'])
        with self.assertRaises(SystemExit):
            atl.check_resume(folder, False, ['a', 'c'])


if __name__ == '__main__':
    unittest.main()
