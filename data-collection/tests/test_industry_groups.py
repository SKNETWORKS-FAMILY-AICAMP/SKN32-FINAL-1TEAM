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

    def test_f2_official_compound_names_before_split(self):
        # 2026-09-28 F2 — 공식 복합 명칭이 가운뎃점·및에서 쪼개져 M 을 잃던 반례(Codex 2차 후속 F2)
        self.check('전문· 과학·기술', ['M'])
        self.check('전문·과학 및 기술서비스업', ['M'])
        self.check('농업, 임업 및 어업', ['A'])
        self.check('건물 및 산업설비 청소업', ['N'])            # '산업'으로 X 가 되지 않는다
        self.check('기술 시험, 검사 및 분석업', ['M'])
        self.check('창업·경영컨설팅', ['M'])
        self.check('종합 또는 일반테마파크업', ['R'])
        self.check('제조업, 전문·과학 및 기술서비스업', ['C', 'M'])   # 명칭 밖은 평소대로 나눈다
        self.check('전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업', ['C'])   # KSIC 26 — '영상'으로 J 가 붙지 않는다(Codex 재검수)

    def test_f2_fine_ksic_codes(self):
        self.check('390 환경정화 및 복원업', ['E'])
        self.check('714 시장조사 및 여론조사업', ['M'])
        self.check('피자, 햄버거 및 치킨 전문점(5616)', ['I'])
        self.check('47811 중 약국, 한약국', ['G'])
        self.check('협회 및 단체(94110∼94990)', ['S'])
        self.check('3402 전기, 전자 및 정밀기기 수리업', ['?'])   # 번호는 C(34), 이름은 수리(S) — 고르지 않는다
        # 번호가 아닌 숫자는 믿지 않는다
        self.check('건평 330평방미터를 초과하는 영업장을 가진 식당업', ['I'])
        self.check('건설업 본사(산재보험 업종코드 90515)', ['F'])
        self.check('100대 생활업종', [])

    def test_f2_previously_unmapped_values(self):
        for t, want in (('측량업', ['M']), ('농작물 재배업', ['A']), ('편의점', ['G']), ('슈퍼', ['G']),
                        ('노래방', ['R']), ('PC방', ['R']), ('치킨', ['I']), ('카센터', ['S']), ('이발', ['S']),
                        ('금형', ['C']), ('S/W', ['J']), ('S.W', ['J']), ('해상풍력 발전사업자', ['D']),
                        ('렌트카업', ['N']), ('운동강습', ['P']), ('일반유흥 주점업', ['I']), ('약국', ['G']),
                        ('증기탕', ['S']), ('법률', ['M'])):
            self.check(t, want)

    def test_f2_substrings_that_must_not_match(self):
        self.check('스마트공장', ['X'])                          # '마트'(G) 가 아니다
        self.check('청소년 유해업소', [])                        # '청소업'(N) 이 아니다
        self.check('식품위생법 및 건강기능식품에 관한 법률에 의한 영업자', ['C'])   # 법 이름의 '법률'
        self.check('(전력)반도체 적용 부품 및 완제품 제조기업', ['C'])        # 괄호 속 '전력'(D) 을 붙이지 않는다
        self.check('제조기업(S/W포함)', ['C', 'J'])              # 괄호 속 "…포함"은 덧붙인다
        self.check('생산자단체(농업법인 포함)', ['A'])
        self.check('신용보증 기관에서 보증을 제한하고 있는 업종', [])   # '보증기관'의 '증기'(D) 가 아니다
        self.check('전기, 가스, 증기 및 수도사업', ['D'])

    def test_applicant_section(self):
        for t, want in (('제조업', 'C'), ('음식점업', 'I'), ('카페', 'I'), ('정보통신업', 'J'), ('소프트웨어 개발', 'J'),
                        ('농업', 'A'), ('건설업', 'F'), ('도소매업', 'G'), ('온라인 쇼핑몰', 'G'), ('미용실', 'S'),
                        ('학원', 'P'), ('C', 'C'), ('j', 'J')):
            self.assertEqual(g.applicant_section(t), want, t)
        # 하나로 정할 수 없으면 None — 업종으로 순서를 바꾸지 않는다
        for t in ('', '제조 및 무역업', '바이오', '우주관광', '정보서비스업(KSIC 72)'):
            self.assertIsNone(g.applicant_section(t), t)

    def test_allowed_sections(self):
        self.assertEqual(g.allowed_sections(['제조업', '도소매업']), {'C', 'G'})
        self.assertEqual(g.allowed_sections(['건설업 및 제조업']), {'F', 'C'})
        # 하나라도 표준 대분류로 못 바꾸면 비교 불가
        self.assertIsNone(g.allowed_sections(['제조업', '바이오']))
        self.assertIsNone(g.allowed_sections(['제조업', '전∙후방 업종']))
        self.assertIsNone(g.allowed_sections(['정보서비스업(KSIC 72)']))
        self.assertIsNone(g.allowed_sections(['전 업종']))
        self.assertIsNone(g.allowed_sections([]))
        # 범위가 넓은 표현(2026-09-28 업종 순위 안전 확인의 반례)
        for broad in ('IT 서비스·솔루션 분야', '의료·바이오 산업', '재사용 배터리를 활용하는 이차전지산업 관련 기업',
                      '한국 농림축산식품 수출업체', '게임 콘텐츠 관련'):
            self.assertIsNone(g.allowed_sections([broad]), broad)
        self.assertEqual(g.allowed_sections(['수산업종']), {'A'})          # '수산업'은 업종
        # 제조업은 "만든다"는 말이 있어야 한다(Codex 통합 검수 P2 — 식품기업은 유통·외식일 수도)
        for vague in ('식품기업', '의료기기', '국내 섬유ㆍ의류 소재기업', '자동차 부품 업종'):
            self.assertIsNone(g.allowed_sections([vague]), vague)
        for makes in ('제조기업', '농·식품 제조기업', '가구제조업(C32)', '모빌리티 제조', '수산가공품 생산'):
            self.assertIsNotNone(g.allowed_sections([makes]), makes)

    def test_names_cover_codes(self):
        for letter in 'ABCDEFGHIJKLMNOPQRSTU':
            self.assertIn(letter, g.NAMES)
        self.assertIn('ALL', g.NAMES)
        self.assertIn('X', g.NAMES)


if __name__ == '__main__':
    unittest.main()
