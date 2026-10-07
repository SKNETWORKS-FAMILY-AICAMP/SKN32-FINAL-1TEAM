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


if __name__ == '__main__':
    unittest.main()
