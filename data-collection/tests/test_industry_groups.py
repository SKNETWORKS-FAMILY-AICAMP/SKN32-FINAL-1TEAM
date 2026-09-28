# -*- coding: utf-8 -*-
"""업종 원문 표현 → KSIC 대분류 큰 묶음 규칙 테스트."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import industry_groups as g  # noqa: E402


class GroupRuleTests(unittest.TestCase):
    def check(self, text, expected):
        self.assertEqual(g.group_of(text), expected, text)

    def test_same_meaning_spellings(self):
        for t in ('제조업', '제조기업', '제조', '제조업체', '중소 제조기업', '제조업종'):
            self.check(t, ['C'])
        for t in ('도·소매업', '도․소매업', '도소매업', '도매 및 소매업', '무역업', '유통'):
            self.check(t, ['G'])
        for t in ('외식업', '음식점', '일반·휴게음식점', '제과점', '호텔업', '휴양 콘도미니엄업', '관광숙박업'):
            self.check(t, ['I'])

    def test_names_that_mislead(self):
        self.check('정보통신공사업', ['F'])          # 이름은 정보통신이지만 KSIC 건설업
        self.check('전기공사업', ['F'])
        self.check('소방시설업', ['F'])
        self.check('의료기기', ['C'])                # 의료(Q)가 아니라 제조
        self.check('폐기물 수집, 운반, 처리 및 원료 재생업', ['E'])   # '운반'을 운수로 보지 않는다
        self.check('자동차 정비업', ['S'])
        self.check('부동산임대업', ['L'])
        self.check('건축기술, 엔지니어링 및 기타 과학기술 서비스업체', ['M'])
        self.check('식품접객업소', ['I'])
        self.check('제조업 관련 서비스업', ['X'])

    def test_explicit_codes_win(self):
        self.check('1차 금속 제조업(24)', ['C'])
        self.check('산업용 기계 및 장비 수리업(34)', ['C'])       # KSIC 34 는 제조업
        self.check('도‧소매업(분류번호 G 45~47)', ['G'])
        self.check('철강산업(C24)', ['C'])

    def test_multiple_sections(self):
        self.check('제조 및 무역업', ['C', 'G'])
        self.check('숙박 및 음식점업', ['I'])
        self.check('국내 수산물 및 수산가공품 생산·제조 기업', ['A', 'C'])

    def test_others(self):
        self.check('여행사', ['N'])
        self.check('소프트웨어 개발 및 공급업', ['J'])
        self.check('영화, 비디오물 및 방송프로그램 제작업', ['J'])
        self.check('이·미용업', ['S'])
        self.check('세탁업', ['S'])
        self.check('핀테크 기업', ['K'])
        self.check('관광유람선업', ['H'])
        self.check('축산농가', ['A'])
        self.check('전문휴양업', ['R'])

    def test_all_and_fields(self):
        for t in ('全 업종', '전업종', '업종 무관'):
            self.check(t, ['ALL'])
        for t in ('바이오 분야', '로봇', '지식기반산업', '서비스업', '지역 주력산업'):
            self.check(t, ['X'])
        self.check('양식업', ['A'])
        self.check('양식', ['I'])

    def test_codex_followup_counterexamples(self):
        # 2026-09-22 Codex 후속 리뷰 F1 — 괄호 숫자를 KSIC 로 오해, 수산 양식을 음식으로, 복합 표현 누락
        self.check('정보서비스업(72)', ['J'])
        self.check('컴퓨터 프로그래밍, 시스템 통합 및 관리업(72)', ['J'])
        self.check('양식장', ['A'])
        self.check('패류 양식 어가', ['A'])
        self.check('음식료품 도매업', ['G'])
        self.check('건설업 및 제조업', ['F', 'C'])

    def test_codes_need_ksic_context_and_conflict_is_ambiguous(self):
        self.check('정보서비스업(KSIC 72)', ['?'])          # 번호는 M, 이름은 J — 한쪽을 고르지 않는다
        self.check('제조업(한국표준산업분류 24)', ['C'])
        self.check('관리업(72)', [])                         # 체계 없는 괄호 숫자만으로는 묶지 않는다

    def test_head_keyword_decides_part(self):
        self.check('여객자동차운송업체', ['H'])              # 자동차(C)가 아니라 운송(H)
        self.check('농·식품 제조기업', ['C'])

    def test_unmapped_and_union(self):
        self.check('전∙후방 업종', [])
        self.check('', [])
        self.assertEqual(g.groups_of(['제조업', '무역업', '제조기업']), ['C', 'G'])

    def test_names_cover_codes(self):
        for letter in 'ABCDEFGHIJKLMNOPQRSTU':
            self.assertIn(letter, g.NAMES)
        self.assertIn('ALL', g.NAMES)
        self.assertIn('X', g.NAMES)


if __name__ == '__main__':
    unittest.main()
