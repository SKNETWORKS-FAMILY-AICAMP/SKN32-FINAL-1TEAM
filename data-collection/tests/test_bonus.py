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
       extra=None):
    return {'kind': kind, 'points': points, 'name': name, 'certs': list(certs), 'regions': list(regions),
            'detail': detail, 'quote': quote, 'group': group, 'program': program, 'extra_conditions': extra}


def found(*items, cap=None):
    return {'status': 'found', 'max_total_points': cap, 'bonus_info': 'x', 'items': list(items)}


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
        entry = found(it('인증', 10, '벤처기업', certs=['벤처기업'], quote=q),
                      it('인증', 10, '이노비즈', certs=['이노비즈'], quote=q),
                      it('인증', 10, '메인비즈', certs=['메인비즈'], quote=q), cap=15)
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

    def test_programs_are_scored_separately(self):
        # 세부사업마다 가점이 다르면 더하지 않는다 — 세부사업별로 계산해 가장 큰 값, 이름에 세부사업
        entry = found(it('여성', 2, '여성기업', certs=['여성기업'], quote='A 여성기업 2점', program='A사업'),
                      it('여성', 3, '여성기업', certs=['여성기업'], quote='B 여성기업 3점', program='B사업'),
                      it('인증', 1, '벤처', certs=['벤처기업'], quote='공통 벤처 1점'))
        total, items = bonus.score(entry, req(certifications=['여성기업', '벤처기업']))
        self.assertEqual(total, 4)
        self.assertEqual(items, [{'name': '여성기업 [B사업]', 'points': 3.0}, {'name': '벤처 [B사업]', 'points': 1.0}])
        self.assertEqual(bonus.score(entry, req(certifications=[]))[0], 0)

    def test_cap_keeps_items_summing_to_total(self):
        entry = found(it('여성', 3, 'A 여성 대표'), it('인증', 3, 'B', certs=['벤처기업']), cap=5)
        total, items = bonus.score(entry, req(gender='여성', certifications=['벤처기업']))
        self.assertEqual(total, 5)
        self.assertEqual(sum(i['points'] for i in items), total)
        self.assertEqual(items[1], {'name': 'B (합계 한도 5점 적용)', 'points': 2.0})
        # 점수가 큰 항목부터 남긴다 — 추출 순서가 달라도 같은 결과(Codex 검수 P3-3)
        a = found(it('인증', 2, '작은', certs=['벤처기업'], quote='x'), it('여성', 4, '큰 여성 대표', quote='y'), cap=5)
        b = found(it('여성', 4, '큰 여성 대표', quote='y'), it('인증', 2, '작은', certs=['벤처기업'], quote='x'), cap=5)
        r = req(gender='여성', certifications=['벤처기업'])
        self.assertEqual(bonus.score(a, r), bonus.score(b, r))
        self.assertEqual(bonus.score(a, r)[1][0], {'name': '큰 여성 대표', 'points': 4.0})


class LoadTests(unittest.TestCase):
    def conn(self, rows):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                self.sql = sql

            def fetchall(self):
                return rows

        class Conn:
            def cursor(self):
                return Cursor()
        return Conn()

    def test_stale_rows_are_dropped(self):
        # 공고문이 바뀌었는데 다시 뽑지 않은 가점, 추출기 버전이 다른 가점은 쓰지 않는다(2026-10-06 Codex 검수 P2-4)
        rows = [('a', 'found', 5, 'x', '[]', 'cv2-a', 'v4'), ('b', 'found', None, 'x', '[]', 'cv2-old', 'v4'),
                ('c', 'none', None, None, '[]', 'cv2-c', 'v3'), ('d', 'none', None, None, '[]', None, 'v4')]
        stale = {}
        out = bonus.load(self.conn(rows), versions={'a': 'cv2-a', 'b': 'cv2-b', 'c': 'cv2-c', 'd': 'cv2-d'},
                         extractor_version='v4', stale=stale)
        self.assertEqual(list(out), ['a'])
        self.assertEqual(stale, {'content': 2, 'version': 1})
        self.assertEqual(len(bonus.load(self.conn(rows))), 4)                # 기준을 안 주면 모두


if __name__ == '__main__':
    unittest.main()
