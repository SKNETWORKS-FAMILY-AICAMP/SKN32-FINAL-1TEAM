"""원본 계획서에서 '망가뜨린 변형'을 만든다. 어떤 항목이 깎여야 하는지가 미리 정해져 있어 정답표 역할을 한다.

expect_lower: 원본보다 점수가 낮아져야 하는 평가항목 (비어 있으면 총점만 본다)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures'

OFFTOPIC = ('본 사업은 동네 카페의 신메뉴 개발을 다룬다. 원두는 산지별로 세 가지를 블렌딩하고, 여름에는 과일 음료를 '
            '추가한다. 매장 인테리어는 따뜻한 색감으로 바꾸고 SNS 이벤트로 손님을 늘릴 계획이다.')


def load_plan(plan_id: str) -> dict:
    return json.loads((FIXTURES / 'plans' / ('%s.json' % plan_id)).read_text(encoding='utf-8'))


def load_rubric() -> dict:
    return json.loads((FIXTURES / 'rubric.json').read_text(encoding='utf-8'))


def _sections(plan: dict) -> list[dict]:
    return [dict(s) for s in plan['sections']]


def render(sections: list[dict]) -> str:
    return '\n\n'.join('%s\n%s' % (s['title'], s['text']) for s in sections)


def halve(text: str) -> str:
    """문장 절반만 남긴다(앞쪽 절반, 최소 1문장)."""
    parts = [p for p in re.split(r'(?<=[.!?])\s+', text.strip()) if p]
    return ' '.join(parts[:max(1, len(parts) // 2)])


def build_variants(plan: dict) -> list[dict]:
    """[{variant_id, text, expect_lower, note}] — 첫 항목은 항상 원본."""
    base = _sections(plan)
    item_of = {s['item']: s for s in base}
    out = [{'variant_id': 'original', 'text': render(base), 'expect_lower': [], 'note': '원본(좋은 계획서)', 'short': '원본'}]

    def drop(item: str, vid: str, note: str, short: str) -> None:
        kept = [s for s in base if s['item'] != item]
        out.append({'variant_id': vid, 'text': render(kept), 'expect_lower': [item], 'note': note, 'short': short})

    if 'E3' in item_of:
        drop('E3', 'drop_E3', '시장성 섹션 삭제', '시장성 삭제')
    if 'E5' in item_of:
        drop('E5', 'drop_E5', '팀 역량 섹션 삭제', '팀 역량 삭제')

    if 'E3' in item_of and 'text_unsourced' in item_of['E3']:
        mutated = [dict(s, text=s['text_unsourced']) if s['item'] == 'E3' else s for s in base]
        out.append({'variant_id': 'unsourced_E3', 'text': render(mutated), 'expect_lower': ['E3'],
                    'note': '시장성을 출처 없는 부풀린 수치로 교체', 'short': '시장성 수치 부풀림'})

    if 'E2' in item_of:
        mutated = [dict(s, text=OFFTOPIC) if s['item'] == 'E2' else s for s in base]
        out.append({'variant_id': 'offtopic_E2', 'text': render(mutated), 'expect_lower': ['E2'],
                    'note': '해결 방안을 무관한 내용(카페)으로 교체', 'short': '해결 방안 무관 교체'})

    halved = [dict(s, text=halve(s['text'])) for s in base]
    out.append({'variant_id': 'halved', 'text': render(halved), 'expect_lower': [],
                'note': '모든 섹션을 문장 절반으로 축소(총점만 본다)', 'short': '분량 절반'})
    return out
