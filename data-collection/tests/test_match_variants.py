# -*- coding: utf-8 -*-
"""eval/match_variants.py 의 순수 함수 — 스위치 A(단어 검색 질의)·C(비슷한 공고 묶기). DB·모델 없음."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'eval')):
    if p not in sys.path:
        sys.path.insert(0, p)

import match_variants as mv  # noqa: E402
from search import app  # noqa: E402


class LexicalQueryTests(unittest.TestCase):
    def test_아이디어와_업종만_남긴다(self):
        req = app.MatchRequest(applicant_type='법인', founded_at='2019-01-01', idea=' 노후 주택 리모델링 시공사 ',
                               revenue=[{'item': '리모델링 시공'}], team=[{'career': '항공기계 엔지니어'}],
                               main_industry='건설업')
        self.assertEqual(mv.lexical_query(req), '노후 주택 리모델링 시공사. 업종: 건설업')
        full = app.build_query(req)
        self.assertIn('엔지니어', full)                       # 서비스 질의에는 그대로 남아 있다
        self.assertIn('창업', full)

    def test_덧붙일_것이_없으면_아이디어만(self):
        req = app.MatchRequest(applicant_type='예비창업자', idea='원두 도매')
        self.assertEqual(mv.lexical_query(req), '원두 도매')


class CollapseTests(unittest.TestCase):
    TITLES = {
        'a': '[경북] 포항시 2026년 소상공인 카드수수료 지원사업 참여업체 모집 공고',
        'b': '[울산] 남구 2026년 소상공인 온라인 플랫폼 지원사업 모집 공고',
        'c': '[경북] 구미시 2026년 소상공인 카드수수료 지원사업 참여 점포 모집 변경 공고',
        'd': '2026년 하반기 온라인 K-SEAFOOD 판매 전용관 운영 사업 입점 제품 모집 공고',
        'e': '2026년 하반기 온라인 K-SEAFOOD 판매 전용관 운영 사업 입점 제품 모집 공고',
        'f': '2026년 소상공인(개인사업자) 비즈플러스카드 지원사업 시행 공고',
    }

    def test_같은_계열은_첫_건만_제자리(self):
        ranked = ['a', 'b', 'c', 'd', 'e', 'f']
        self.assertEqual(mv.collapse(ranked, self.TITLES.get), ['a', 'b', 'd', 'f', 'c', 'e'])

    def test_시군_수정공고_연도를_지운다(self):
        self.assertEqual(mv.family_key(self.TITLES['a']), mv.family_key(self.TITLES['c']))
        self.assertNotEqual(mv.family_key(self.TITLES['a']), mv.family_key(self.TITLES['f']))

    def test_빼지_않고_순서만_바꾼다(self):
        ranked = list(self.TITLES)
        out = mv.collapse(ranked, self.TITLES.get)
        self.assertEqual(sorted(out), sorted(ranked))

    def test_짧은_사업_이름은_묶지_않는다(self):
        self.assertEqual(mv.family_key('[서울] 강남구 창업지원사업 공고'), '')
        self.assertEqual(mv.collapse(['x', 'y'], {'x': '[서울] 창업지원사업', 'y': '[부산] 창업지원사업'}.get), ['x', 'y'])

    def test_제목이_비면_묶지_않는다(self):
        self.assertEqual(mv.collapse(['x', 'y'], lambda n: ''), ['x', 'y'])


class SwitchableBM25Tests(unittest.TestCase):
    def test_override_가_있을_때만_질의를_바꾼다(self):
        class Inner:
            docs = 3

            def search(self, query, top=10, allowed=None):
                return [(query, top)]
        s = mv.SwitchableBM25(Inner())
        self.assertEqual(s.search('원래', top=5), [('원래', 5)])
        s.override = '줄인'
        self.assertEqual(s.search('원래', top=5), [('줄인', 5)])
        self.assertEqual(s.docs, 3)


if __name__ == '__main__':
    unittest.main()
