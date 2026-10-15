# -*- coding: utf-8 -*-
"""신청자별 가산점 계산 — 03_bonus 3-3 (2026-10-06). DB·LLM 없음."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search import bonus  # noqa: E402


def req(**kw):
    base = {'gender': '', 'certifications': [], 'region': '', 'district': '', 'birth_date': '', 'first_startup': None}
    base.update(kw)
    return SimpleNamespace(**base)


def it(kind, points=None, name='항목', certs=(), regions=(), detail=None, quote='', group=None, program=None,
       extra=None, source=None):
    # 근거 문장이 없으면 "이름 N점"으로 둔다 — 점수는 근거에 "N점"이 직접 있어야 인정된다(2026-10-07)
    if not quote and points is not None:
        quote = '%s %g점' % (name, points)
    return {'kind': kind, 'points': points, 'name': name, 'points_source': source, 'certs': list(certs), 'regions': list(regions),
            'detail': detail, 'quote': quote, 'group': group, 'program': program, 'extra_conditions': extra}


def found(*items, cap=None, uncertain=()):
    return {'status': 'found', 'max_total_points': cap, 'bonus_info': 'x', 'items': list(items),
            'uncertain': list(uncertain)}


class ItemHitTests(unittest.TestCase):
    def test_female(self):
        plain, cert = it('여성', name='여성 대표자'), it('여성', certs=['여성기업'])
        self.assertTrue(bonus.item_hit(plain, req(gender='여성')))
        self.assertFalse(bonus.item_hit(plain, req(gender='남성')))
        self.assertIsNone(bonus.item_hit(plain, req()))
        self.assertFalse(bonus.item_hit(cert, req(gender='여성')))          # 인증을 요구하는데 없다
        self.assertTrue(bonus.item_hit(cert, req(certifications=['여성기업'])))
        # 대표자 성별이 아닌 여성 조건(연구자 비율 등)은 성별로 알 수 없다
        self.assertIsNone(bonus.item_hit(it('여성', name='여성연구자', quote='여성연구자가 10% 이상'), req(gender='여성')))
        self.assertFalse(bonus.item_hit(it('여성', name='여성 기업'), req(gender='여성')))        # 인증이 필요
        # 이름이 '여성기업'이어도 근거가 '대표이사가 여성인 기업'이면 성별로 본다
        ceo = it('여성', name='여성기업', certs=['여성기업'], quote='주관기관의 대표이사가 여성인 기업(1점)')
        self.assertTrue(bonus.item_hit(ceo, req(gender='여성')))
        self.assertFalse(bonus.item_hit(ceo, req(gender='남성')))

    def test_disabled(self):
        cert = it('장애인', certs=['장애인기업'], name='장애인기업')
        self.assertTrue(bonus.item_hit(cert, req(certifications=['장애인기업'])))
        self.assertFalse(bonus.item_hit(cert, req()))
        self.assertIsNone(bonus.item_hit(it('장애인', name='장애인 대표자'), req()))
        # 장애인표준사업장은 장애인기업 인증과 다른 제도 — 인증이 있어도 모름
        self.assertIsNone(bonus.item_hit(it('장애인', name='장애인표준사업장'), req(certifications=['장애인기업'])))

    def test_region_with_extra_requirement(self):
        lab = it('지역', regions=['서울'], name='서울시 소재 기업부설연구소 보유 기업')
        self.assertIsNone(bonus.item_hit(lab, req(region='서울')))                 # 지역만 맞다
        self.assertTrue(bonus.item_hit(lab, req(region='서울', certifications=['기업부설연구소'])))
        self.assertFalse(bonus.item_hit(lab, req(region='부산')))

    def test_certification_known_and_unknown(self):
        self.assertTrue(bonus.item_hit(it('인증', certs=['벤처기업', '이노비즈']), req(certifications=['이노비즈'])))
        self.assertFalse(bonus.item_hit(it('인증', certs=['벤처기업']), req(certifications=['메인비즈'])))
        self.assertIsNone(bonus.item_hit(it('인증', name='명문장수기업'), req(certifications=['벤처기업'])))

    def test_region_and_district(self):
        sido = it('지역', regions=['전남'], name='전라남도 소재 기업')
        # 글에 지역이 없는 항목(LLM 이 공고 소재지를 붙인 것)은 시·도만으로 주지 않는다
        self.assertIsNone(bonus.item_hit(it('지역', regions=['광주'], name='도시철도2호선 공사현장 인근 상가'), req(region='전남광주')))
        self.assertTrue(bonus.item_hit(it('지역', regions=['충남'], name='도내 소재 기업'), req(region='충남')))
        # 전남광주로 묶인 신청자: '전남'만 주는 가점은 시·군·구로 전남인지 확인해야 한다(2026-10-06 Codex 검수 P2-1)
        self.assertIsNone(bonus.item_hit(sido, req(region='전남광주')))
        self.assertTrue(bonus.item_hit(sido, req(region='전남광주', district='순천시')))
        self.assertFalse(bonus.item_hit(sido, req(region='전남광주', district='광산구')))
        both = it('지역', regions=['전남', '광주'], name='광주·전남 소재 기업')
        self.assertTrue(bonus.item_hit(both, req(region='전남광주')))
        self.assertFalse(bonus.item_hit(sido, req(region='서울')))
        self.assertIsNone(bonus.item_hit(sido, req()))
        city = it('지역', regions=['경남'], name='창원특례시 소재기업')
        self.assertTrue(bonus.item_hit(city, req(region='경남', district='창원시 성산구')))
        self.assertFalse(bonus.item_hit(city, req(region='경남', district='김해시')))
        self.assertIsNone(bonus.item_hit(city, req(region='경남')))         # 시·군·구를 모른다
        self.assertFalse(bonus.item_hit(city, req(region='부산', district='해운대구')))

    def test_extra_conditions_turn_hit_into_unknown(self):
        # "최근 3년 이내·주관기관" 같은 추가 조건은 입력으로 확인할 수 없다 — 해당이 모름으로, 해당 아님은 그대로
        fam = it('인증', 3, '가족친화인증', certs=['가족친화기업'], extra='최근 3년 이내 취득, 주관연구개발기관')
        self.assertIsNone(bonus.item_hit(fam, req(certifications=['가족친화기업'])))
        self.assertFalse(bonus.item_hit(fam, req(certifications=[])))
        local = it('지역', 5, '도내 본사', regions=['충남'], quote='도내 본사 및 사업장(개인사업자 제외)',
                   extra='개인사업자 제외')
        self.assertIsNone(bonus.item_hit(local, req(region='충남')))

    def test_youth_needs_birth_date(self):
        youth = it('청년', detail='만 39세 이하 대표자')
        self.assertIsNone(bonus.item_hit(youth, req()))
        self.assertTrue(bonus.item_hit(youth, req(birth_date='1995-01-01')))
        self.assertFalse(bonus.item_hit(youth, req(birth_date='1970-01-01')))

    def test_restart_and_unknown_kinds(self):
        self.assertTrue(bonus.item_hit(it('재창업'), req(first_startup=False)))
        self.assertFalse(bonus.item_hit(it('재창업'), req(first_startup=True)))
        for kind in ('고용', '수출', '특허', '이전실적', '업종', '기타'):
            self.assertIsNone(bonus.item_hit(it(kind, 3), req(gender='여성', certifications=list(bonus.KNOWN_CERTS))))


class ScoreTests(unittest.TestCase):
    def test_no_row_or_unverified_is_null(self):
        self.assertEqual(bonus.score(None, req()), (None, []))
        self.assertEqual(bonus.score({'status': 'unverified', 'items': []}, req()), (None, []))

    def test_no_bonus_is_zero(self):
        self.assertEqual(bonus.score({'status': 'none', 'items': []}, req()), (0, []))
        self.assertEqual(bonus.score({'status': 'no_mention', 'items': []}, req()), (0, []))

    def test_sum_of_hit_items_with_points(self):
        entry = found(it('여성', 2, '여성 대표'), it('인증', 1, '벤처', certs=['벤처기업']), it('수출', 3, '수출 실적'),
                      it('인증', 1, '벤처', certs=['벤처기업']))                                    # 중복 항목은 한 번만
        self.assertEqual(bonus.score(entry, req(gender='여성', certifications=['벤처기업'])),
                         (3.0, [{'name': '여성 대표', 'points': 2.0}, {'name': '벤처', 'points': 1.0}]))

    def test_all_not_applicable_is_zero_but_unknown_is_null(self):
        entry = found(it('여성', 2, '여성 대표'), it('인증', 1, certs=['벤처기업']))
        self.assertEqual(bonus.score(entry, req(gender='남성')), (0, []))
        self.assertEqual(bonus.score(found(it('여성', 2, '여성 대표'), it('수출', 3)), req(gender='남성')), (None, []))
        self.assertEqual(bonus.score(found(it('여성', None, '여성 대표')), req(gender='여성')), (None, []))   # 해당이지만 점수 모름

    def test_choice_row_counts_once(self):
        # F19: "벤처, 이노비즈, 메인비즈 기업 : 10점" 한 행 — 인증이 몇 개든 10점(2026-10-06 Codex 검수 P1-1)
        q = '벤처, 이노비즈, 메인비즈 기업 : 10점'
        # 선택 관계는 추출기가 준 group 으로만 묶는다(2026-10-07 — 같은 근거 문장만으로는 묶지 않음)
        entry = found(it('인증', 10, '벤처기업', certs=['벤처기업'], quote=q, group='g1'),
                      it('인증', 10, '이노비즈', certs=['이노비즈'], quote=q, group='g1'),
                      it('인증', 10, '메인비즈', certs=['메인비즈'], quote=q, group='g1'), cap=15)
        for certs in (['벤처기업'], ['벤처기업', '이노비즈'], ['벤처기업', '이노비즈', '메인비즈']):
            total, items = bonus.score(entry, req(certifications=certs))
            self.assertEqual(total, 10)
            self.assertEqual(len(items), 1)
        # 같은 group 이름이면 근거가 달라도 한 번만
        g = found(it('여성', 2, '여성기업', certs=['여성기업'], quote='여성기업 2점', group='g1'),
                  it('장애인', 2, '장애인기업', certs=['장애인기업'], quote='장애인기업 2점', group='g1'),
                  it('인증', 1, '벤처', certs=['벤처기업'], quote='벤처 1점', group='g2'))
        self.assertEqual(bonus.score(g, req(certifications=['여성기업', '장애인기업', '벤처기업']))[0], 3)
        # 다른 group 이 하나라도 모름이고 해당이 없으면 null, 모두 해당 아님이면 0
        self.assertEqual(bonus.score(g, req(certifications=[]))[0], 0)

    def test_programs_differ_is_null(self):
        # 세부사업마다 결과가 다르면 신청자가 어디에 내는지 몰라 null(2026-10-07 R-P2-4). 모두 0이면 0
        entry = found(it('여성', 2, '여성기업', certs=['여성기업'], quote='A 여성기업 2점', program='A사업'),
                      it('여성', 3, '여성기업', certs=['여성기업'], quote='B 여성기업 3점', program='B사업'),
                      it('인증', 1, '벤처', certs=['벤처기업'], quote='공통 벤처 1점'))
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업', '벤처기업'])), (None, []))
        self.assertEqual(bonus.score(entry, req(certifications=[]))[0], 0)
        # 세부사업 결과가 모두 같고 공통 항목만으로 그 점수면 꼬리표 없이 낸다
        self.assertEqual(bonus.score(entry, req(certifications=['벤처기업'])), (1.0, [{'name': '벤처', 'points': 1.0}]))

    def test_cap_exceeded_is_null(self):
        # 한도가 전체 한도인지 항목 한도인지 확인할 수 없어 합이 한도를 넘으면 null(2026-10-07 R-P2-5)
        entry = found(it('여성', 3, 'A 여성 대표'), it('인증', 3, 'B', certs=['벤처기업']), cap=5)
        self.assertEqual(bonus.score(entry, req(gender='여성', certifications=['벤처기업'])), (None, []))
        self.assertEqual(bonus.score(entry, req(gender='여성')), (3.0, [{'name': 'A 여성 대표', 'points': 3.0}]))
        # 점수가 큰 항목부터 정렬 — 추출 순서가 달라도 같은 결과(Codex 검수 P3-3)
        a = found(it('인증', 2, '작은', certs=['벤처기업']), it('여성', 4, '큰 여성 대표'), cap=10)
        b = found(it('여성', 4, '큰 여성 대표'), it('인증', 2, '작은', certs=['벤처기업']), cap=10)
        r = req(gender='여성', certifications=['벤처기업'])
        self.assertEqual(bonus.score(a, r), bonus.score(b, r))
        self.assertEqual(bonus.score(a, r)[1][0], {'name': '큰 여성 대표', 'points': 4.0})



class ConservativeTests(unittest.TestCase):
    """확실한 것만 남기기(2026-10-07) — Codex 재검수(10/6) 재현 입력."""

    def test_points_from_other_cell_or_serial_number_are_not_trusted(self):
        # R-P1-1: "여성기업 가점 2점. 벤처기업 가점 10점." 에서 다른 항목 배점(points_source)으로 10점
        far = it('여성', 10, '여성기업', certs=['여성기업'], quote='여성기업 가점 2점', source='벤처기업 가점 10점')
        self.assertFalse(bonus.points_supported(far))
        self.assertEqual(bonus.score(found(far), req(certifications=['여성기업'])), (None, []))
        # "1 여성기업 가점 2점" — 연번 1이 점수로 읽힘
        serial = it('여성', 1, '여성기업', certs=['여성기업'], quote='1 여성기업 가점')
        self.assertFalse(bonus.points_supported(serial))
        self.assertTrue(bonus.points_supported(it('여성', 2, '여성기업', quote='여성기업 가점 2점')))
        self.assertTrue(bonus.points_supported(it('여성', 0.5, '여성기업', quote='여성기업 0.5 점')))
        self.assertFalse(bonus.points_supported(it('여성', 2, '여성기업', quote='여성기업 12점')))

    def test_independent_bonuses_in_one_sentence(self):
        # R-P2-1: 123858 "※ (가점) 벤처·이노비즈·메인비즈 각 1점, 여성기업 3점 ※" — 10/7 오전에는 4점이었다.
        # 10/7 오후(Codex 재검수 B-P1-1·B-P1-2): 한 근거에 1점·3점이 섞여 어느 항목 점수인지 문장만으로 확정할 수 없고,
        # "각"인데 세 인증이 한 묶음(g1)이라 원문 배점 합(6점)과도 어긋난다 → null
        q = '※ (가점) 벤처·이노비즈·메인비즈 각 1점, 여성기업 3점 ※'
        entry = found(it('인증', 1, '벤처기업', certs=['벤처기업'], quote=q, group='g1'),
                      it('인증', 1, '이노비즈', certs=['이노비즈'], quote=q, group='g1'),
                      it('인증', 1, '메인비즈', certs=['메인비즈'], quote=q, group='g1'),
                      it('여성', 3, '여성기업', certs=['여성기업'], quote=q, group='g2'))
        self.assertEqual(bonus.score(entry, req(certifications=['벤처기업', '여성기업'])), (None, []))
        self.assertEqual(bonus.score(entry, req(certifications=[]))[0], 0)          # 해당 없음은 그대로 0

    def test_future_condition_is_unknown(self):
        # R-P2-2: 117751 "과밀억제권역에서 도내로 공장을 이전하는 중소기업" — 충남 소재만으로 5점을 주지 않는다
        move = it('지역', 5, '공장 이전 기업', regions=['충남'], quote='과밀억제권역에서 도내로 공장을 이전하는 중소기업 5점')
        self.assertIsNone(bonus.item_hit(move, req(region='충남', district='천안시')))
        self.assertTrue(bonus.item_hit(it('지역', 5, '도내 소재 기업', regions=['충남'], quote='도내 소재 기업 5점'),
                                       req(region='충남')))

    def test_uncertain_reading(self):
        # R-P2-3: '가점 없음'이라고 봤지만 불확실 사항이 있으면 0 대신 null
        self.assertEqual(bonus.score({'status': 'none', 'items': [], 'uncertain': ['구체적인 점수가 없음']}, req()),
                         (None, []))
        self.assertEqual(bonus.score({'status': 'none', 'items': [], 'uncertain': []}, req()), (0, []))
        women = it('여성', 3, '여성기업', certs=['여성기업'])
        r = req(certifications=['여성기업', '벤처기업'])
        self.assertEqual(bonus.score(found(women, uncertain=['가점표 일부가 발췌에서 누락']), r), (None, []))
        venture = it('인증', 1, '벤처기업', certs=['벤처기업'])
        self.assertEqual(bonus.score(found(women, venture, uncertain=['중복 인정 여부']), r), (None, []))
        # 10/7 오후(B-P1-3): found 인데 불확실 메모가 하나라도 있으면 묶음 수와 관계없이 null(전에는 1묶음이면 3점)
        self.assertEqual(bonus.score(found(women, uncertain=['중복 인정 여부']), r), (None, []))
        self.assertEqual(bonus.score(found(women), r)[0], 3)

    def test_same_points_choice_by_name(self):
        # R-P3-2: 같은 점수 선택지는 이름순 — 입력 순서와 관계없이 같은 항목
        a = found(it('인증', 2, '이노비즈', certs=['이노비즈'], group='g'), it('인증', 2, '벤처기업', certs=['벤처기업'], group='g'))
        b = found(it('인증', 2, '벤처기업', certs=['벤처기업'], group='g'), it('인증', 2, '이노비즈', certs=['이노비즈'], group='g'))
        r = req(certifications=['벤처기업', '이노비즈'])
        self.assertEqual(bonus.score(a, r), bonus.score(b, r))
        self.assertEqual(bonus.score(a, r)[1][0]['name'], '벤처기업')


class RecheckTests(unittest.TestCase):
    """Codex 재검수(2026-10-07, CODEX_BONUS_RECHECK_20261007.md) 재현 입력 — 모두 양수 대신 null 이어야 한다."""

    def test_b_p1_1_other_items_points_in_quote(self):
        doc = '여성기업 가점 2점. 벤처기업 가점 10점.'
        women = req(certifications=['여성기업'])
        # 근거가 원문 전체 — 2점·10점이 섞여 어느 항목 점수인지 모른다
        whole = it('여성', 10, '여성기업', certs=['여성기업'], quote=doc)
        self.assertFalse(bonus.points_supported(whole))
        self.assertEqual(bonus.score(found(whole), women), (None, []))
        # 근거를 이어 붙임("2점. 벤처기업"을 건너뜀) — 원문에 그대로 없다
        glued = dict(it('여성', 10, '여성기업', certs=['여성기업'], quote='여성기업 가점 10점'), in_document=False)
        self.assertIsNone(bonus.item_hit(glued, women))
        self.assertEqual(bonus.score(found(glued), women), (None, []))
        # 같은 값이 되풀이되는 것은 괜찮다
        self.assertTrue(bonus.points_supported(it('인증', 1, '벤처', quote='벤처 1점, 이노비즈 1점')))

    def test_b_p1_2_group_split_or_each(self):
        q = '벤처, 이노비즈, 메인비즈 기업 : 10점'
        split = found(it('인증', 10, '벤처기업', certs=['벤처기업'], quote=q, group='g1'),
                      it('인증', 10, '이노비즈', certs=['이노비즈'], quote=q, group='g2'))
        # 10/7 오전에는 20점 — group 이 다른데 근거·점수가 같으면 선택 가점을 나눈 것일 수 있다
        self.assertEqual(bonus.score(split, req(certifications=['벤처기업', '이노비즈'])), (None, []))
        self.assertEqual(bonus.score(split, req(certifications=['벤처기업']))[0], 10)   # 하나만 해당이면 겹치지 않는다
        # 122309 "여성, 장애인, 사회적, 녹색 기업 : 각 1점"을 한 group 으로 묶음 — 독립 가점을 묶었을 수 있다
        each = '❍ 여성, 장애인, 사회적, 녹색 기업 : 각 1점'
        joined = found(it('여성', 1, '여성기업', certs=['여성기업'], quote=each, group='g2'),
                       it('장애인', 1, '장애인기업', certs=['장애인기업'], quote=each, group='g2'))
        self.assertEqual(bonus.score(joined, req(certifications=['여성기업', '장애인기업'])), (None, []))
        self.assertEqual(bonus.score(joined, req())[0], 0)
        self.assertIsNone(bonus._EACH.search('각종 인증 기업 1점'))            # '각종'은 "각"이 아니다

    def test_b_p1_3_uncertain_cap(self):
        # 117356: 한도 확인 불가 메모 — 여성기업 5점 + 벤처 3점 = 8점을 확정하지 않는다
        entry = found(it('여성', 5, '여성기업', certs=['여성기업'], quote='여성기업 및 장애인 기업(5점)', group='g8'),
                      it('인증', 3, '벤처기업 확인기업', certs=['벤처기업'], quote='벤처기업 확인기업(3점)', group='g14'),
                      uncertain=['평가기준의 ‘가점(5점)’이 가점 합계 한도인지 여부가 명시적으로 확인되지 않음'])
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업', '벤처기업'])), (None, []))
        miss = found(it('인증', 3, '벤처기업', certs=['벤처기업']), uncertain=['가점표를 파악하지 못했음'])
        self.assertEqual(bonus.score(miss, req(certifications=['벤처기업'])), (None, []))

    def test_b_p2_1_hidden_conditions(self):
        r = req(region='전북', district='전주시')
        both = it('지역', 5, '전북 본사 및 사업장', regions=['전북'],
                  quote='전북특별자치도 안에 본사 및 사업장(생산공장)모두를 두는 기업(5점)')
        self.assertIsNone(bonus.item_hit(both, r))
        recent = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='최근 3년 이내 벤처기업 확인을 받은 기업은 가점 3점')
        self.assertIsNone(bonus.item_hit(recent, req(certifications=['벤처기업'])))
        self.assertFalse(bonus.item_hit(recent, req()))                          # 해당 아님은 그대로
        for q in ('도내 소재 기업(5점)', '전라북도 소재 기업 5점'):
            self.assertTrue(bonus.item_hit(it('지역', 5, '소재 기업', regions=['전북'], quote=q), r))
        # 청년 나이 구절의 "이하"는 조건 말로 보지 않는다
        self.assertTrue(bonus.item_hit(it('청년', 2, '청년 대표', quote='만 39세 이하 대표자 2점'), req(birth_date='1995-01-01')))
        self.assertIsNone(bonus.item_hit(it('청년', 2, '청년 대표', quote='만 39세 이하이고 창업 3년 이내 대표자 2점'),
                                         req(birth_date='1995-01-01')))

    def test_only_moves_toward_null(self):
        # 새 규칙은 양수를 null 로만 바꾼다 — 해당 아님(0)·해당(점수)이 바뀌지 않는 깨끗한 공고
        clean = found(it('여성', 2, '여성기업', certs=['여성기업'], quote='여성기업 2점', group='a'),
                      it('인증', 1, '벤처기업', certs=['벤처기업'], quote='벤처기업 1점', group='b'))
        self.assertEqual(bonus.score(clean, req(certifications=['여성기업', '벤처기업'])),
                         (3.0, [{'name': '여성기업', 'points': 2.0}, {'name': '벤처기업', 'points': 1.0}]))
        self.assertEqual(bonus.score(clean, req())[0], 0)


class LoadTests(unittest.TestCase):
    def conn(self, rows, notices=(), files=(), fail=False):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, args=None):
                self.sql = sql
                if fail and 'FROM notice_bonus' not in sql:
                    raise RuntimeError('db down')

            def fetchall(self):
                if 'FROM notice_bonus' in self.sql:
                    return rows
                if 'attachment_texts' in self.sql:
                    return list(files)
                return list(notices)

        class Conn:
            def cursor(self):
                return Cursor()
        return Conn()

    def test_document_check(self):
        # found 행은 근거가 지금 원문(본문·지원대상·첨부)에 공백만 다르고 그대로 있는지 확인한다(B-P1-1)
        items = '[{"name": "여성기업", "quote": "여성기업  가점 2점"}, {"name": "벤처", "quote": "벤처기업 가점 10점"},' \
                ' {"name": "이어붙임", "quote": "여성기업 가점 10점"}]'
        rows = [('a', 'found', None, 'x', items, 'cv', 'v4', '[]'), ('b', 'none', None, None, '[]', 'cv', 'v4', '[]')]
        out = bonus.load(self.conn(rows, notices=[('a', '공고 본문', None)], files=[('a', '여성기업 가점\n2점. 벤처기업 가점 10점.')]))
        self.assertEqual(out['a']['document_check'], 'ok')
        self.assertEqual([i['in_document'] for i in out['a']['items']], [True, True, False])
        self.assertNotIn('document_check', out['b'])
        # 원문 조각의 경계를 넘는 일치는 인정하지 않는다
        out = bonus.load(self.conn([('a', 'found', None, 'x', '[{"quote": "본문끝첨부"}]', 'cv', 'v4', '[]')],
                                   notices=[('a', '본문끝', None)], files=[('a', '첨부')]))
        self.assertFalse(out['a']['items'][0]['in_document'])

    def test_document_read_failure_makes_found_null(self):
        rows = [('a', 'found', None, 'x', '[{"kind": "인증", "points": 1, "name": "벤처", "certs": ["벤처기업"], '
                                          '"quote": "벤처 1점"}]', 'cv', 'v4', '[]'),
                ('b', 'none', None, None, '[]', 'cv', 'v4', '[]')]
        errors = []
        out = bonus.load(self.conn(rows, fail=True), errors=errors)
        self.assertEqual(out['a']['document_check'], 'failed')
        self.assertEqual(len(errors), 1)
        self.assertIn('db down', errors[0])
        self.assertEqual(bonus.score(out['a'], req(certifications=['벤처기업'])), (None, []))
        self.assertEqual(bonus.score(out['b'], req()), (0, []))                  # 가점 없음은 원문 확인과 관계없다

    def test_stale_rows_are_dropped(self):
        # 공고문이 바뀌었는데 다시 뽑지 않은 가점, 추출기 버전이 다른 가점은 쓰지 않는다(2026-10-06 Codex 검수 P2-4)
        rows = [('a', 'found', 5, 'x', '[]', 'cv2-a', 'v4', '["중복 인정 여부"]'),
                ('b', 'found', None, 'x', '[]', 'cv2-old', 'v4', '[]'),
                ('c', 'none', None, None, '[]', 'cv2-c', 'v3', None), ('d', 'none', None, None, '[]', None, 'v4', '[]')]
        stale = {}
        out = bonus.load(self.conn(rows), versions={'a': 'cv2-a', 'b': 'cv2-b', 'c': 'cv2-c', 'd': 'cv2-d'},
                         extractor_version='v4', stale=stale)
        self.assertEqual(list(out), ['a'])
        self.assertEqual(stale, {'content': 2, 'version': 1})
        self.assertEqual(out['a']['uncertain'], ['중복 인정 여부'])        # 불확실 사항도 읽는다(2026-10-07)
        self.assertEqual(len(bonus.load(self.conn(rows))), 4)                # 기준을 안 주면 모두



class BenignExtraTests(unittest.TestCase):
    """뜻이 안 바뀌는 추가 조건은 모름으로 내리지 않는다(2026-10-08 결정 0014)."""

    def test_paper_validity_and_sme_are_allowed(self):
        mine = req(certifications=['벤처기업'])
        for extra in ('해당인증서 첨부', '벤처기업 확인서 제출', '인증 유효기간이 남아있는', '유효기간 내',
                      '접수 마감일 기준 인증서가 유효한 경우에 한함', '중소기업', '유효기간 내; 신청일 기준 지정이 유효한 기업'):
            item = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 3점', extra=extra)
            self.assertTrue(bonus.item_hit(item, mine), extra)

    def test_meaning_changing_extras_stay_unknown(self):
        mine = req(certifications=['벤처기업'])
        for extra in ('최근 3년 이내', '발표평가 시 평가위원 평균점수가 60점 이상인 과제에 한하여', '법인의 경우',
                      '개인사업자 제외', '협약 기간 동안 해당 지역에 잔류를 확약하는 경우(확약서 제출)',
                      '특화사업 참여, 지자체 추천', '해당인증서 첨부; 최근 3년 이내'):
            item = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 3점', extra=extra)
            self.assertIsNone(bonus.item_hit(item, mine), extra)

    def test_not_applicable_stays_false(self):
        item = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 3점', extra='해당인증서 첨부')
        self.assertFalse(bonus.item_hit(item, req()))

    def test_condition_words_inside_benign_phrase_are_ignored(self):
        mine = req(certifications=['벤처기업'])
        ok = it('인증', 1, '벤처기업', certs=['벤처기업'], quote='벤처기업 1점(유효기간 내 인증서에 한함)')
        self.assertTrue(bonus.item_hit(ok, mine))
        # 증빙 말과 기간 조건이 한 구절에 있으면 그대로 모름
        mixed = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='최근 3년 이내 벤처기업 확인서 제출 기업 3점')
        self.assertIsNone(bonus.item_hit(mixed, mine))

    def test_score_counts_benign_item(self):
        entry = found(it('여성', 5, '여성기업', certs=['여성기업'], quote='여성기업(5점)', extra='여성기업 확인서 첨부'))
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (5, [{'name': '여성기업', 'points': 5}]))


class Recheck2Tests(unittest.TestCase):
    """Codex 재재검수(2026-10-08, CODEX_BONUS_RECHECK2_20261007.md) — 결정 0016. 모름이 되어야 할 것과 그대로여야 할 것."""

    def test_r2_p1_1_joined_condition(self):
        # 120238 "(1점) 가족친화인증 & 대한민국 일·생활균형 우수기업" — 일·생활균형은 입력으로 확인할 수 없다
        q = '(1점) 가족친화인증 & 대한민국 일생활균형 우수기업'
        fam = found(it('인증', 1, '가족친화인증', certs=['가족친화기업'], quote=q, group='g13'),
                    it('인증', 1, '대한민국 일·생활균형 우수기업', quote=q, group='g13'))
        self.assertEqual(bonus.score(fam, req(certifications=['가족친화기업'])), (None, []))
        # "일자리 으뜸기업 및 청년친화 강소기업 5점" — 짝(일자리 으뜸기업)을 확인할 수 없으니 "및"이어도 모름(사용자 결정)
        q2 = '(5점) 일자리 으뜸기업 및 청년친화 강소기업'
        youth = found(it('고용', 5, '일자리 으뜸기업', quote=q2, group='g8'),
                      it('인증', 5, '청년친화 강소기업', certs=['청년친화강소기업'], quote=q2, group='g8'))
        self.assertEqual(bonus.score(youth, req(certifications=['청년친화강소기업'])), (None, []))
        # 117356 "여성기업 및 장애인 기업(5점)" — 짝을 안 가진 것이 확실하면 "둘 중 하나"로 보고 5점(사용자 결정)
        q3 = '⑧ 여성기업 및 장애인 기업(5점)'
        both = found(it('여성', 5, '여성기업', certs=['여성기업'], quote=q3, group='g9'),
                     it('장애인', 5, '장애인기업', certs=['장애인기업'], quote=q3, group='g9'))
        self.assertEqual(bonus.score(both, req(certifications=['여성기업'])), (5.0, [{'name': '여성기업', 'points': 5.0}]))
        # '&'인데 짝이 따로 뽑히지 않았으면 모름. 쉼표·"등"·"또는" 나열은 건드리지 않는다
        alone = found(it('인증', 1, '가족친화인증', certs=['가족친화기업'], quote='가족친화인증 & 일생활균형 우수기업 1점'))
        self.assertEqual(bonus.score(alone, req(certifications=['가족친화기업'])), (None, []))
        q4 = '(사회적가치 기업) 사회적경제기업, 장애인표준사업장, 장애인기업, 여성기업 등 5점'
        listed = found(it('장애인', 5, '장애인표준사업장', quote=q4, group='g3'),
                       it('여성', 5, '여성기업', certs=['여성기업'], quote=q4, group='g3'))
        self.assertEqual(bonus.score(listed, req(certifications=['여성기업']))[0], 5)

    def test_r2_p1_2_period_line_outside_quote(self):
        # 126819 — 표 아래 "※ 모든 인증서는 최근 2년간(2024~2025년) 증빙서류로 제출된 서류만 인정"
        self.assertEqual(bonus.period_lines(['표 제목\n※ 모든 인증서는 최근 2년간(2024~2025년) 증빙서류로 제출된 서류만 인정']),
                         ['※ 모든 인증서는 최근 2년간(2024~2025년) 증빙서류로 제출된 서류만 인정'])
        # "가점·인정"이 없는 제출서류 안내 줄은 보지 않는다(사용자 결정 — 가점·인정 줄만)
        self.assertEqual(bonus.period_lines(['※ 필수 제출서류: 중소기업확인서, 최근 3개년 표준재무제표증명']), [])
        women = dict(it('여성', 5, '여성기업', certs=['여성기업'], quote='여성기업 또는 장애인기업 가점(5점)'), period_condition=True)
        self.assertIsNone(bonus.item_hit(women, req(certifications=['여성기업'])))
        self.assertFalse(bonus.item_hit(women, req()))                                  # 해당 아님은 그대로
        local = dict(it('지역', 5, '도내 소재 기업', regions=['충남'], quote='도내 소재 기업 5점'), period_condition=True)
        self.assertTrue(bonus.item_hit(local, req(region='충남')))                      # 인증으로 받는 항목만

    def test_r2_p1_3_paper_exception_only_for_same_cert(self):
        mine = req(certifications=['벤처기업'])
        award = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 인증서 및 대통령 표창장 제출 시 가점 3점',
                   extra='벤처기업 인증서 및 대통령 표창장 제출')
        self.assertIsNone(bonus.item_hit(award, mine))
        plain = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 인증서 제출 시 가점 3점', extra='벤처기업 인증서 제출')
        self.assertTrue(bonus.item_hit(plain, mine))                                    # 결정 0014 의도 그대로
        other = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 3점', extra='이노비즈 인증서 사본 제출')
        self.assertIsNone(bonus.item_hit(other, mine))                                  # 다른 인증의 서류
        valid = it('여성', 1, '여성기업', certs=['여성기업'], quote='여성기업 1점', extra='확인서의 유효기간이 접수 마감일 기준 유효해야 함')
        self.assertTrue(bonus.item_hit(valid, req(certifications=['여성기업'])))       # 125997 — 그대로
        self.assertTrue(bonus.same_cert_paper('확인서 필수 제출', valid))

    def test_r2_p1_4_points_must_belong_to_item(self):
        doc = '여성기업 우대 안내. 벤처기업 가점 10점'
        women = it('여성', 10, '여성기업', certs=['여성기업'], quote=doc)
        self.assertTrue(bonus.points_supported(women))                                  # 숫자는 하나뿐이라 전 규칙은 통과
        self.assertIsNone(bonus.item_hit(women, req(certifications=['여성기업'])))
        self.assertEqual(bonus.score(found(women), req(certifications=['여성기업'])), (None, []))
        venture = it('인증', 10, '벤처기업', certs=['벤처기업'], quote=doc)
        self.assertTrue(bonus.item_hit(venture, req(certifications=['벤처기업'])))
        listed = it('인증', 10, '이노비즈', certs=['이노비즈'], quote='벤처, 이노비즈, 메인비즈 기업 : 10점')
        self.assertTrue(bonus.item_hit(listed, req(certifications=['이노비즈'])))      # 120481 — 그대로

    def test_r2_p1_5_choose_one(self):
        entry = found(it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 가점 3점.', group='g1'),
                      it('인증', 2, '이노비즈', certs=['이노비즈'], quote='이노비즈기업 가점 2점.', group='g2'))
        both = req(certifications=['벤처기업', '이노비즈'])
        self.assertEqual(bonus.score(entry, both)[0], 5)                                # 택1 말이 없으면 지금처럼
        entry['selection'] = True                                                       # 원문 "두 항목은 택1이며 합산하지 않음"
        self.assertEqual(bonus.score(entry, both), (None, []))
        self.assertEqual(bonus.score(entry, req(certifications=['벤처기업']))[0], 3)   # 한 묶음만 고르면 영향 없음
        self.assertTrue(bonus.SELECT_WORDS.search('두 항목은 택1이며 합산하지 않음'))
        self.assertTrue(bonus.SELECT_WORDS.search('※ 해당 항목 중복 시 1개만 인정'))
        self.assertIsNone(bonus.SELECT_WORDS.search('타 사업과 중복 지원 불가'))       # 흔한 중복 지원 안내는 아니다

    def test_r2_p2_1_age_clause_only_for_youth(self):
        ceo = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='만 39세 이하 대표자의 벤처기업 가점 3점')
        self.assertIsNone(bonus.item_hit(ceo, req(certifications=['벤처기업'], birth_date='1960-01-01')))
        youth = it('청년', 2, '청년 대표', quote='만 39세 이하 대표자 2점')
        self.assertTrue(bonus.item_hit(youth, req(birth_date='1995-01-01')))           # 청년은 그대로

    def test_new_rules_never_release_null(self):
        # 120238 한도 10: 사회적기업 5 + 청년친화 5 + 가족친화 1 = 11 → 이전 계산 null. ① 뒤에도 null(5로 풀리지 않는다)
        q8, q13 = '(5점) 일자리 으뜸기업 및 청년친화 강소기업', '(1점) 가족친화인증 & 대한민국 일생활균형 우수기업'
        entry = found(it('인증', 5, '사회적기업', certs=['사회적기업'], quote='(5점) 사회적 경제기업(사회적기업)', group='g10'),
                      it('고용', 5, '일자리 으뜸기업', quote=q8, group='g8'),
                      it('인증', 5, '청년친화 강소기업', certs=['청년친화강소기업'], quote=q8, group='g8'),
                      it('인증', 1, '가족친화인증', certs=['가족친화기업'], quote=q13, group='g13'),
                      it('인증', 1, '일생활균형', quote=q13, group='g13'), cap=10)
        three = req(certifications=['사회적기업', '청년친화강소기업', '가족친화기업'])
        self.assertIsNone(bonus._score(entry, three, strict=False)[0])
        self.assertEqual(bonus._score(entry, three, strict=True)[0], 5)
        self.assertEqual(bonus.score(entry, three), (None, []))
        self.assertEqual(bonus.score(entry, req(certifications=['사회적기업']))[0], 5)   # 확실한 것은 그대로

    def test_review_gaps(self):
        # 최종 점검 지적 — 추가 조건 칸이 비어도 근거의 다른 자격 서류는 모름, 같은 이름·다른 종류 짝, 고르기 말 보강
        mine = req(certifications=['벤처기업'])
        quote_only = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 인증서 및 대통령 표창장 제출 시 가점 3점')
        self.assertIsNone(bonus.item_hit(quote_only, mine))
        self.assertTrue(bonus.item_hit(it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 인증서 제출 시 가점 3점'), mine))
        q = '벤처기업 및 일자리 으뜸기업 3점'
        same_name = found(it('인증', 3, '벤처기업', certs=['벤처기업'], quote=q), it('고용', 3, '벤처기업', quote=q))
        self.assertEqual(bonus.score(same_name, mine), (None, []))
        for text in ('최대 1개 항목만 인정', '중복 수혜 불가', '높은 점수 1개만 적용'):
            self.assertTrue(bonus.SELECT_WORDS.search(text), text)
        self.assertNotIn('세', bonus.subject_words(it('청년', 2, '청년 대표')))

    def test_load_marks_period_and_selection(self):
        rows = [('a', 'found', None, 'x', '[{"kind": "여성", "points": 5, "name": "여성기업", "certs": ["여성기업"], '
                                          '"quote": "여성기업 가점(5점)"}]', 'cv', 'v4', '[]')]
        conn = LoadTests().conn(rows, notices=[('a', '여성기업 가점(5점)\n※ 모든 인증서는 최근 2년간 증빙서류만 인정\n택1', None)])
        out = bonus.load(conn)
        self.assertEqual(out['a']['period_lines'], ['※ 모든 인증서는 최근 2년간 증빙서류만 인정'])
        self.assertTrue(out['a']['selection'])
        self.assertTrue(out['a']['items'][0]['period_condition'])
        self.assertEqual(bonus.score(out['a'], req(certifications=['여성기업'])), (None, []))


class Recheck3Tests(unittest.TestCase):
    """Codex 3차 검수(2026-10-08, CODEX_BONUS_RECHECK3_20261008.md) — 결정 0017. 원문 읽기는 load() 를 거쳐 재현한다."""

    def load_one(self, item_json, doc):
        conn = LoadTests().conn([('a', 'found', None, 'x', item_json, 'cv', 'v4', '[]')], notices=[('a', doc, None)])
        return bonus.load(conn)['a']

    def test_r3_p1_1_line_break_inside_quote(self):
        # 원문은 두 줄인데 추출이 줄바꿈을 지워 한 문장으로 저장 — 여성기업 10점을 인정하지 않는다
        entry = self.load_one('[{"kind": "여성", "points": 10, "name": "여성기업", "certs": ["여성기업"], '
                              '"quote": "여성기업 우대 안내 벤처기업 가점 10점"}]', '여성기업 우대 안내\n벤처기업 가점 10점')
        self.assertEqual(entry['items'][0]['quote_lines'], ['여성기업 우대 안내', '벤처기업 가점 10점'])
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (None, []))
        star = self.load_one('[{"kind": "여성", "points": 10, "name": "여성기업", "certs": ["여성기업"], '
                             '"quote": "여성기업 우대 안내 *벤처기업 가점 10점"}]', '여성기업 우대 안내\n*벤처기업 가점 10점')
        self.assertEqual(bonus.score(star, req(certifications=['여성기업'])), (None, []))      # 배점 든 * 줄은 붙이지 않는다
        table = self.load_one('[{"kind": "인증", "points": 1, "name": "이노비즈", "certs": ["이노비즈"], '
                              '"quote": "ㅇ 혁신형 중소기업 1점 * 이노비즈, 메인비즈"}]', 'ㅇ 혁신형 중소기업\n1점\n* 이노비즈, 메인비즈')
        self.assertEqual(bonus.score(table, req(certifications=['이노비즈']))[0], 1)        # 표 배점 칸·설명 줄은 앞줄에
        # 한 줄 안에 있는 정상 항목은 그대로
        ok = self.load_one('[{"kind": "여성", "points": 5, "name": "여성기업", "certs": ["여성기업"], '
                           '"quote": "여성기업 가점 5점"}]', '가점 표\n여성기업 가점 5점\n끝')
        self.assertNotIn('quote_lines', ok['items'][0])
        self.assertEqual(bonus.score(ok, req(certifications=['여성기업']))[0], 5)

    def test_r3_p1_2_name_words_are_not_confirmed(self):
        mine = req(certifications=['벤처기업'])
        named = it('인증', 3, '벤처기업 및 대통령 표창장 보유기업', certs=['벤처기업'],
                   quote='벤처기업 인증서 및 대통령 표창장 제출 시 가점 3점', extra='벤처기업 인증서 및 대통령 표창장 제출')
        self.assertIsNone(bonus.item_hit(named, mine))
        self.assertNotIn('표창장', bonus.cert_words(named))
        plain = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 인증서 제출 시 가점 3점', extra='벤처기업 인증서 제출')
        self.assertTrue(bonus.item_hit(plain, mine))

    def test_r3_p1_3_and_without_extracted_mate(self):
        mine = req(certifications=['벤처기업'])
        lone = found(it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업 및 일자리 으뜸기업 가점 3점'))
        self.assertEqual(bonus.score(lone, mine), (None, []))
        q = '⑧ 여성기업 및 장애인 기업(5점)'                                            # 짝이 뽑혔고 False — 그대로 5점
        pair = found(it('여성', 5, '여성기업', certs=['여성기업'], quote=q, group='g9'),
                     it('장애인', 5, '장애인기업', certs=['장애인기업'], quote=q, group='g9'))
        self.assertEqual(bonus.score(pair, req(certifications=['여성기업']))[0], 5)

    def test_r3_p2_1_footnote_split_over_lines(self):
        two = ['여성기업 가점 5점\n※ 모든 인증서는 최근 2년간(2024~2025년)\n증빙서류로 제출된 서류만 인정']
        self.assertEqual(bonus.period_lines(two), ['※ 모든 인증서는 최근 2년간(2024~2025년) 증빙서류로 제출된 서류만 인정'])
        # 다음 줄에 가점·인정이 없는 제출서류 안내, 새 머리 기호가 시작되는 줄은 합치지 않는다
        self.assertEqual(bonus.period_lines(['※ 필수 제출서류: 중소기업확인서, 최근 3개년 표준재무제표증명\n사업자등록증']), [])
        self.assertEqual(bonus.period_lines(['※ 모든 인증서는 최근 2년간\n※ 가점은 인정 범위 안에서']), [])
        entry = self.load_one('[{"kind": "여성", "points": 5, "name": "여성기업", "certs": ["여성기업"], '
                              '"quote": "여성기업 가점 5점"}]', two[0])
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (None, []))

    def test_row_fingerprint(self):
        entry = self.load_one('[{"kind": "여성", "points": 5, "name": "여성기업", "certs": ["여성기업"], '
                              '"quote": "여성기업 가점 5점"}]', '여성기업 가점 5점')
        fp = entry['row_fingerprint']
        self.assertTrue(fp.startswith('bf1-'))
        self.assertEqual(bonus.row_fingerprint(entry), fp)                        # 원문 확인 칸은 지문에 안 들어간다
        changed = dict(entry, items=[dict(entry['items'][0], points=3)])
        self.assertNotEqual(bonus.row_fingerprint(changed), fp)


class ReviewedTests(unittest.TestCase):
    """원문 대조를 마친 공고 목록 읽기·판단(결정 0017)."""

    def test_load_and_check(self):
        import json
        import tempfile
        good = {'version': 1, 'notices': {'n': {'content_version': 'cv', 'row_fingerprint': 'bf1-a', 'evidence_fingerprint': 'ev1-a',
                                                'approved_items': [{'name': '여성기업', 'points': 5}]}}}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'r.json')
            json.dump(good, open(path, 'w', encoding='utf-8'))
            reviewed = bonus.load_reviewed(path)
            for bad in ({'notices': []}, {'notices': {'n': {'content_version': 'cv'}}},
                        {'notices': {'n': dict(good['notices']['n'], approved_items=[{'name': 'x'}])}}):
                json.dump(bad, open(path, 'w', encoding='utf-8'))
                with self.assertRaises(ValueError):
                    bonus.load_reviewed(path)
            with self.assertRaises(FileNotFoundError):
                bonus.load_reviewed(os.path.join(d, 'none.json'))
        entry = {'row_fingerprint': 'bf1-a', 'evidence_fingerprint': 'ev1-a'}
        five = [{'name': '여성기업', 'points': 5.0}]
        self.assertTrue(bonus.reviewed_ok(reviewed, 'n', entry, 'cv', five))
        self.assertFalse(bonus.reviewed_ok(reviewed, 'other', entry, 'cv', five))                  # 목록 밖
        self.assertFalse(bonus.reviewed_ok(reviewed, 'n', entry, 'cv-new', five))                  # 공고 내용이 바뀜
        self.assertFalse(bonus.reviewed_ok(reviewed, 'n', {'row_fingerprint': 'bf1-b', 'evidence_fingerprint': 'ev1-a'}, 'cv', five))   # 가점 행이 바뀜
        self.assertFalse(bonus.reviewed_ok(reviewed, 'n', entry, 'cv', five + [{'name': '벤처', 'points': 3.0}]))
        self.assertFalse(bonus.reviewed_ok(reviewed, 'n', entry, 'cv', [{'name': '여성기업', 'points': 3.0}]))  # 같은 이름 다른 점수
        self.assertFalse(bonus.reviewed_ok(reviewed, 'n', entry, 'cv', []))


class Recheck4Tests(unittest.TestCase):
    """Codex 4차 검수(2026-10-08, CODEX_BONUS_RECHECK4_20261008.md) — 결정 0018."""

    def load_one(self, item_json, doc, files=()):
        conn = LoadTests().conn([('a', 'found', None, 'x', item_json, 'cv', 'v4', '[]')], notices=[('a', doc, None)],
                                files=files)
        return bonus.load(conn)['a']

    def test_r4_p2_1_star_line_after_named_row(self):
        # "벤처기업 가점 10점 / * 여성기업 우대 안내" — 앞줄에 자격 이름(벤처)이 있으면 "*" 줄을 붙이지 않는다
        entry = self.load_one('[{"kind": "여성", "points": 10, "name": "여성기업", "certs": ["여성기업"], '
                              '"quote": "벤처기업 가점 10점 * 여성기업 우대 안내"}]', '벤처기업 가점 10점\n* 여성기업 우대 안내')
        self.assertEqual(entry['items'][0]['quote_lines'], ['벤처기업 가점 10점', '* 여성기업 우대 안내'])
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (None, []))
        # 앞줄이 일반 이름("혁신형 중소기업")이면 "*" 정의 줄을 붙인다 — 127009 그대로
        ok = self.load_one('[{"kind": "인증", "points": 1, "name": "이노비즈", "certs": ["이노비즈"], '
                           '"quote": "ㅇ 혁신형 중소기업 1점 * 이노비즈, 메인비즈"}]', 'ㅇ 혁신형 중소기업\n1점\n* 이노비즈, 메인비즈')
        self.assertEqual(bonus.score(ok, req(certifications=['이노비즈']))[0], 1)

    def test_r4_p2_2_bad_list_values_reject_whole_list(self):
        import json
        import tempfile
        base = {'content_version': 'cv', 'row_fingerprint': 'bf1-a', 'evidence_fingerprint': 'ev1-a',
                'approved_items': [{'name': '여성기업', 'points': 5}]}
        bad_items = [{'name': '여성기업', 'points': '오점'}, {'name': '여성기업', 'points': None},
                     {'name': '여성기업', 'points': {}}, {'name': '여성기업', 'points': True},
                     {'name': '여성기업', 'points': -1}, {'name': '여성기업', 'points': float('inf')},
                     {'name': '', 'points': 5}, {'name': 3, 'points': 5}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'r.json')
            for item in bad_items:
                json.dump({'notices': {'n': dict(base, approved_items=[item])}}, open(path, 'w', encoding='utf-8'))
                with self.assertRaises(ValueError, msg=str(item)):
                    bonus.load_reviewed(path)
            for key in ('evidence_fingerprint', 'row_fingerprint', 'content_version'):
                json.dump({'notices': {'n': dict(base, **{key: ''})}}, open(path, 'w', encoding='utf-8'))
                with self.assertRaises(ValueError, msg=key):
                    bonus.load_reviewed(path)
            json.dump({'notices': {'n': base}}, open(path, 'w', encoding='utf-8'))
            self.assertIn('n', bonus.load_reviewed(path))

    def test_r4_p2_3_evidence_fingerprint(self):
        a = bonus.evidence_fingerprint(['본문', '첨부1 여성기업 가점 5점', '첨부2'])
        self.assertEqual(a, bonus.evidence_fingerprint(['첨부2', '본문', '첨부1 여성기업 가점 5점']))     # 순서가 달라도 같다
        self.assertEqual(bonus.evidence_fingerprint(['줄1\r\n줄2']), bonus.evidence_fingerprint(['줄1\n줄2']))
        self.assertNotEqual(a, bonus.evidence_fingerprint(['본문', '첨부1 여성기업 가점 5점\n※ 대통령 표창장 보유 기업에만 적용',
                                                           '첨부2']))                                        # 첨부 글이 바뀜
        self.assertNotEqual(bonus.evidence_fingerprint(['ab', 'c']), bonus.evidence_fingerprint(['a', 'bc']))  # 조각 경계
        item = '[{"kind": "여성", "points": 5, "name": "여성기업", "certs": ["여성기업"], "quote": "여성기업 가점 5점"}]'
        before = self.load_one(item, '공고 본문', files=[('a', '여성기업 가점 5점')])
        after = self.load_one(item, '공고 본문', files=[('a', '여성기업 가점 5점\n※ 해당 가점은 대통령 표창장 보유 기업에만 적용')])
        self.assertEqual(before['row_fingerprint'], after['row_fingerprint'])                   # 가점 행은 같지만
        self.assertNotEqual(before['evidence_fingerprint'], after['evidence_fingerprint'])        # 원문 지문은 다르다
        reviewed = {'a': {'content_version': 'cv', 'row_fingerprint': before['row_fingerprint'],
                          'evidence_fingerprint': before['evidence_fingerprint'],
                          'approved_items': [{'name': '여성기업', 'points': 5}]}}
        five = [{'name': '여성기업', 'points': 5.0}]
        self.assertTrue(bonus.reviewed_ok(reviewed, 'a', before, 'cv', five))
        self.assertFalse(bonus.reviewed_ok(reviewed, 'a', after, 'cv', five))
        none_row = bonus.load(LoadTests().conn([('b', 'none', None, None, '[]', 'cv', 'v4', '[]')]))['b']
        self.assertNotIn('evidence_fingerprint', none_row)                                         # found 행에만


class TableScoreCellTests(unittest.TestCase):
    """표 배점 칸의 숫자를 점수로 인정(2026-10-08 결정 0019) — 괴산군 117554 "여성기업 및 / 장애인 기업 | 10"."""

    HEAD = '구분 가점 항목 배점\n'
    GOESAN_BODY = '여성기업 및\n장애인 기업\n10\n․ 여성기업 또는 장애인기업\n으로 인증받은 기업'

    def load_items(self, items, doc):
        import json
        conn = LoadTests().conn([('a', 'found', None, 'x', json.dumps(items, ensure_ascii=False), 'cv', 'v4', '[]')],
                                notices=[('a', doc, None)])
        return bonus.load(conn)['a']

    def one(self, points, quote, doc):
        return self.load_items([{'kind': '여성', 'points': points, 'name': '여성기업', 'certs': ['여성기업'], 'quote': quote}], doc)

    def goesan(self, doc=None):
        quote = '여성기업 및 장애인 기업 10 ․ 여성기업 또는 장애인기업 으로 인증받은 기업'
        doc = doc if doc is not None else self.HEAD + self.GOESAN_BODY
        return self.load_items([{'kind': '여성', 'points': 10, 'name': '여성기업', 'certs': ['여성기업'], 'quote': quote},
                                {'kind': '장애인', 'points': 10, 'name': '장애인기업', 'certs': ['장애인기업'], 'quote': quote}], doc)

    def test_goesan_two_line_label_scores(self):
        entry = self.goesan()
        self.assertTrue(entry['items'][0]['score_header'])
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (10, [{'name': '여성기업', 'points': 10.0}]))
        self.assertEqual(bonus.score(entry, req(certifications=['장애인기업'])), (10, [{'name': '장애인기업', 'points': 10.0}]))
        # 둘 다 가진 신청자 — 같은 근거·같은 점수가 두 묶음에서 나온다(B-P1-2) → 모름
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업', '장애인기업'])), (None, []))

    def test_no_header_or_far_header_stays_unknown(self):
        self.assertEqual(bonus.score(self.goesan('가점 항목\n' + self.GOESAN_BODY), req(certifications=['여성기업'])), (None, []))
        far = self.goesan('배점\n' + '가' * (bonus.SCORE_HEADER_WINDOW + 10) + '\n' + self.GOESAN_BODY)
        self.assertFalse(far['items'][0]['score_header'])
        self.assertEqual(bonus.score(far, req(certifications=['여성기업'])), (None, []))

    def test_unmatched_qualification_in_label_stays_unknown(self):
        # "벤처기업 및 / 여성기업 | 10"에서 여성기업만 뽑혔다 — 행 이름에 짝 아닌 자격(벤처)이 섞임 → 모름
        entry = self.one(10, '벤처기업 및 여성기업 10', self.HEAD + '벤처기업 및\n여성기업\n10')
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (None, []))
        self.assertFalse(bonus.points_owned(entry['items'][0]))         # "및" 규칙과 따로 점수 주인 검사도 막는다
        bare = self.one(10, '벤처기업 여성기업 10', self.HEAD + '벤처기업\n여성기업\n10')    # "및" 없이도
        self.assertFalse(bonus.points_owned(bare['items'][0]))
        self.assertEqual(bonus.score(bare, req(certifications=['여성기업'])), (None, []))

    def test_serial_number_under_score_header_stays_unknown(self):
        # 표 머리 "배점"이 있어도 숫자가 대상 말보다 앞이면 연번일 수 있다 → 모름
        serial = self.one(1, '1 여성기업 가점', self.HEAD + '1 여성기업 가점')
        self.assertFalse(bonus.points_owned(serial['items'][0]))
        self.assertEqual(bonus.score(serial, req(certifications=['여성기업'])), (None, []))

    def test_spaced_unit_needs_word_end(self):
        # "10⏎일자리"(근거에서는 "10 일자리") — 다음 칸 글자는 단위가 아니다(배점 10이 남는다). 붙은 "3년간"·띄운 "3 년 이상"은 단위
        cell = self.one(10, '여성기업 10 일자리 창출 기업 우대', self.HEAD + '여성기업 10\n일자리 창출 기업 우대')
        self.assertTrue(bonus._table_cell(cell['items'][0]))
        self.assertEqual(bonus._BARE_NUMBER.findall('3 년 이상\n10\n일자리'), ['10'])
        self.assertEqual(bonus._BARE_NUMBER.findall('3년간 5억 10 %'), [])

    def test_two_numbers_stay_unknown_and_units_are_ignored(self):
        two = self.one(3, '여성기업 3 장애인기업 5', self.HEAD + '여성기업\n3\n장애인기업\n5')
        self.assertEqual(bonus.score(two, req(certifications=['여성기업'])), (None, []))
        unit = self.one(2, '여성기업 인증 3년 이상 2', self.HEAD + '여성기업 인증 3년 이상\n2')
        self.assertTrue(bonus._table_cell(unit['items'][0]))      # '3년'은 숫자로 치지 않는다(조건 말 "이상"으로 모름은 따로)

    def test_parenthesized_number(self):
        quote = '여성기업(2) : 여성기업지원에 관한 법률에 따른 여성기업'
        entry = self.one(2, quote, self.HEAD + quote)
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업']))[0], 2)

    def test_points_word_path_and_serial_number_unchanged(self):
        # "N점" 근거는 지금 판단 그대로 — 표 경로를 쓰지 않는다
        five = self.one(5, '여성기업 5점', self.HEAD + '여성기업 5점')
        self.assertFalse(bonus._table_cell(five['items'][0]))
        self.assertEqual(bonus.score(five, req(certifications=['여성기업']))[0], 5)
        # 연번이 점수로 읽힌 경우("1 여성기업 가점") — 표 머리가 없으면 그대로 모름
        serial = self.one(1, '1 여성기업 가점', '가점 항목\n1 여성기업 가점')
        self.assertEqual(bonus.score(serial, req(certifications=['여성기업'])), (None, []))
        # load() 를 거치지 않은 항목(표 머리 표시 없음)은 표 경로를 쓰지 않는다
        self.assertFalse(bonus.points_supported(it('여성', 10, name='여성기업', certs=['여성기업'], quote='여성기업 10')))

    def test_added_marks_do_not_change_row_fingerprint(self):
        entry = self.goesan()
        bare = dict(entry, items=[{k: v for k, v in i.items() if k not in ('score_header', 'table_mates')}
                                  for i in entry['items']])
        self.assertEqual(bonus.row_fingerprint(entry), bonus.row_fingerprint(bare))
        self.assertEqual(entry['items'][0]['table_mates'], sorted(entry['items'][0]['table_mates']))


class Relax0020Tests(unittest.TestCase):
    """가산점 계산 완화 R1~R5와 Codex 6차 조이기 K1·K2(2026-10-08 결정 0020)."""

    HEAD = TableScoreCellTests.HEAD
    load_items = TableScoreCellTests.load_items
    one = TableScoreCellTests.one

    def test_r1_memo_naming_other_item_keeps_the_rest(self):
        women = it('여성', 5, '여성기업', certs=['여성기업'], quote='② 여성이 소유하거나 경영하는 중소기업(여성기업 확인서 첨부)(5점)')
        venture = it('인증', 3, '벤처기업', certs=['벤처기업'], quote='벤처기업(3점)')
        r = req(certifications=['여성기업', '벤처기업'])
        local = found(women, venture, uncertain=["⑱ 녹색기업 인증 항목은 발췌문이 '(5'에서 끊겨 있어 점수 표기가 완전하지 않습니다.",
                                                 '지역인재 신규채용 항목의 3명 미만 조건은 발췌 앞부분이 누락되어 있어 포함하지 않았습니다.'])
        self.assertEqual(bonus.score(local, r)[0], 8)
        # 번호로 집은 항목("⑮·⑯ 항목")도 대상 — 124915 대전
        self.assertFalse(bonus.memo_is_global('발췌문이 ⑭에서 끊긴 뒤 지역인재 조건으로 이어져 ⑮·⑯ 항목 내용이 누락된 것으로 보입니다.'))
        # 메모가 가리키는 항목만 모름 — 벤처기업 3점은 남고 여성기업은 빠진다
        named = found(women, venture, uncertain=['‘여성기업’ 항목의 증빙 조건이 발췌에서 잘렸습니다.'])
        self.assertIsNone(bonus.score(named, req(certifications=['여성기업']))[0])
        self.assertEqual(bonus.score(named, req(certifications=['벤처기업']))[0], 3)
        # 전체를 흔드는 메모·대상이 없는 메모는 지금처럼 공고 전체 모름
        for memo in ('가점 최대 한도가 공고 전체인지 확인 어려움', '표 일부가 깨져 있음', '‘여성기업’과 벤처기업은 중복 인정 여부 불명확',
                     '가점 항목 일부가 발췌에서 누락', "'우대' 조건 해석 불명", '⑱ 근거가 끊김'):          # 일반 말만 가리키는 메모(최종 점검)
            self.assertTrue(bonus.memo_is_global(memo), memo)
            self.assertEqual(bonus.score(found(women, venture, uncertain=[memo]), r), (None, []), memo)

    def test_r2_qualification_only_case_clause(self):
        q = '벤처기업 인증 또는 이노비즈 인증을 받은 경우 1점'
        entry = found(it('인증', 1, '벤처기업 인증', certs=['벤처기업'], quote=q, group='g1'),
                      it('인증', 1, '이노비즈 인증', certs=['이노비즈'], quote=q, group='g1'))
        self.assertEqual(bonus.score(entry, req(certifications=['벤처기업']))[0], 1)
        self.assertEqual(bonus.score(found(it('여성', 1, '여성기업', certs=['여성기업'], quote='기관이 여성기업인 경우 1점')),
                                     req(certifications=['여성기업']))[0], 1)
        # 자격 밖의 말이 남는 "경우"는 그대로 조건 — 법인의 경우, 다른 조건 말(이상)이 함께 걸린 경우
        for quote in ('법인의 경우 벤처기업 1점', '벤처기업 인증을 받고 매출 10억 이상인 경우 1점', '협약 기간 동안 잔류를 확약하는 경우 벤처기업 1점'):
            self.assertIsNone(bonus.score(found(it('인증', 1, '벤처기업', certs=['벤처기업'], quote=quote)),
                                          req(certifications=['벤처기업']))[0], quote)

    def test_r3_repeated_number_and_no_zero(self):
        rep = self.one(5, '여성기업 (5) 우대기업 : 5', self.HEAD + '여성기업 (5) 우대기업 : 5')
        self.assertEqual(bonus.score(rep, req(certifications=['여성기업']))[0], 5)
        yes = self.one(1, '여성기업 예(1) 아니오(0)', self.HEAD + '여성기업\n예(1)\n아니오(0)')
        self.assertEqual(bonus.bare_numbers('여성기업 예(1) 아니오(0)'), [1.0])
        self.assertEqual(bonus.score(yes, req(certifications=['여성기업']))[0], 1)
        # 다른 값이 섞이면 그대로 모름
        mixed = self.one(5, '여성기업 (5) 장애인기업 : 3', self.HEAD + '여성기업 (5) 장애인기업 : 3')
        self.assertEqual(bonus.score(mixed, req(certifications=['여성기업'])), (None, []))

    def test_r4_owner_of_each_point_in_one_sentence(self):
        q = '※ (가점) 벤처·이노비즈·메인비즈 각 1점, 여성기업 3점 ※'
        entry = found(it('인증', 1, '벤처기업', certs=['벤처기업'], quote=q, group='g1'),
                      it('인증', 1, '이노비즈', certs=['이노비즈'], quote=q, group='g1'),
                      it('인증', 1, '메인비즈', certs=['메인비즈'], quote=q, group='g1'),
                      it('여성', 3, '여성기업', certs=['여성기업'], quote=q, group='g2'))
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (3, [{'name': '여성기업', 'points': 3.0}]))
        # 세 인증을 한 묶음으로 뽑은 "각" — 그대로 모름(B-P1-2)
        self.assertEqual(bonus.score(entry, req(certifications=['벤처기업', '여성기업'])), (None, []))
        # 항목 점수가 조각의 점수와 다르면 인정하지 않는다
        wrong = it('여성', 1, '여성기업', certs=['여성기업'], quote='벤처기업 1점, 여성기업 3점')
        self.assertFalse(bonus.points_supported(wrong))
        # 조각에 자격 말 밖의 말(법인)이 남으면 그 점수의 조건일 수 있다 — 인정하지 않는다
        self.assertFalse(bonus.points_supported(it('여성', 3, '여성기업', certs=['여성기업'], quote='여성기업 (법인 3점, 개인 1점)')))

    def test_r5_each_points_are_independent(self):
        each = '❍ 여성, 장애인, 사회적, 녹색 기업 : 각 1점'
        entry = found(it('여성', 1, '여성기업', certs=['여성기업'], quote=each, group='g2'),
                      it('장애인', 1, '장애인기업', certs=['장애인기업'], quote=each, group='g3'))
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업', '장애인기업']))[0], 2)
        # "각"이 없으면 그대로 — 다른 묶음 같은 근거·점수는 선택 가점일 수 있다
        q = '벤처기업 또는 이노비즈 10점'
        split = found(it('인증', 10, '벤처기업', certs=['벤처기업'], quote=q, group='g1'),
                      it('인증', 10, '이노비즈', certs=['이노비즈'], quote=q, group='g2'))
        self.assertEqual(bonus.score(split, req(certifications=['벤처기업', '이노비즈'])), (None, []))

    def test_k1_other_row_name_is_not_the_label(self):
        # Codex R6-P2-1: "배점 / 여성기업 우대 안내 / 벤처기업 / 10" — 10점은 벤처기업 행
        quote = '여성기업 우대 안내 벤처기업 10'
        entry = self.load_items([{'kind': '여성', 'points': 10, 'name': '여성기업', 'certs': ['여성기업'], 'quote': quote, 'group': 'g1'},
                                 {'kind': '인증', 'points': 10, 'name': '벤처기업', 'certs': ['벤처기업'], 'quote': quote, 'group': 'g2'}],
                                '배점\n여성기업 우대 안내\n벤처기업\n10')
        self.assertEqual(bonus.score(entry, req(certifications=['여성기업'])), (None, []))
        self.assertEqual(bonus.score(entry, req(certifications=['벤처기업']))[0], 10)
        # 항목 이름 낱말(AI가 지은 이름)은 짝 자격이 아니다
        renamed = self.one(10, quote, '배점\n여성기업 우대 안내\n벤처기업\n10')
        renamed['items'][0]['name'] = '여성기업 벤처기업'
        self.assertEqual(bonus.score(renamed, req(certifications=['여성기업'])), (None, []))
        # 뜻 없는 "해당" 줄은 건너뛴다 — 대구 식품박람회 한 행
        row = 'ㆍ여성기업, 장애인기업, 사회적기업 해당 10'
        daegu = self.load_items([{'kind': '여성', 'points': 10, 'name': '여성기업', 'certs': ['여성기업'], 'quote': row, 'group': 'g1'},
                                 {'kind': '장애인', 'points': 10, 'name': '장애인기업', 'certs': ['장애인기업'], 'quote': row, 'group': 'g1'},
                                 {'kind': '인증', 'points': 10, 'name': '사회적기업', 'certs': ['사회적기업'], 'quote': row, 'group': 'g1'}],
                                self.HEAD + 'ㆍ여성기업, 장애인기업, 사회적기업\n해당\n10')
        self.assertEqual(bonus.score(daegu, req(certifications=['여성기업', '사회적기업']))[0], 10)
        # 띄어쓰기를 지우고 찾지 않는다 — "소재 기업"은 "재기(재창업)"가 아니다
        self.assertEqual(bonus.qualification_words('가점 부산 본사 소재 기업'), set())

    def test_k2_header_must_belong_to_the_same_table(self):
        # Codex R6-P2-2: 앞 표의 "배점", 일반 문장의 "배점", 등록번호 숫자
        other = self.one(10, '여성기업 등록번호 10', '평가 항목 배점\n사업계획 평가\n표 끝\n별도 안내\n여성기업 등록번호 10')
        self.assertEqual(bonus.score(other, req(certifications=['여성기업'])), (None, []))
        prose = self.one(10, '여성기업 등록번호 10', '배점에 관한 문의는 담당자에게 연락\n여성기업 등록번호 10')
        self.assertFalse(prose['items'][0]['score_header'])
        self.assertEqual(bonus.score(prose, req(certifications=['여성기업'])), (None, []))
        self.assertEqual(bonus.bare_numbers('여성기업 등록번호 10'), [])
        # 번호 숫자 규칙과 따로 — 근거가 "여성기업 10"이어도 숫자 없는 다른 글 뒤면 다른 표
        apart = self.one(10, '여성기업 10', '평가 항목 배점\n사업계획 평가\n표 끝\n별도 안내\n여성기업 10')
        self.assertFalse(apart['items'][0]['score_header'])
        # 줄바꿈 너머 다음 줄 첫 글자는 조사가 아니다("배점⏎이노비즈")
        self.assertTrue(self.one(1, '이노비즈 1', '가점 항목 배점\n이노비즈\n1')['items'][0]['score_header'])
        # 정상 표 — 머리 바로 아래, 머리 줄에 다른 칸 글자가 붙어도("배점 비고")
        for doc in ('가점 항목 배점\n여성기업\n10', '구분 배점 비고\n여성기업\n10', '평가 항목 배점\n사업계획\n30\n여성기업\n10'):
            self.assertEqual(bonus.score(self.one(10, '여성기업 10', doc), req(certifications=['여성기업']))[0], 10, doc)


if __name__ == '__main__':
    unittest.main()
