"""가짜 호출처가 돌려줄 응답 — 여러 테스트 파일이 함께 쓴다.

ITEM · item_json: 실제 T-C1이 받는 LLM 응답(ItemDraft JSON).
"""
from __future__ import annotations

import json

ITEM = dict(item_name="헬스장 회원관리", one_line_summary="동네 헬스장의 회원 · 수업 예약을 관리하는 웹 서비스",
            target_customer="소규모 헬스장 운영자", core_features=["회원 등록", "수업 예약", "회원 등록"],
            keywords=["헬스장", "회원관리"], category="웹개발", category_reason="회원 관리 화면 중심", confidence=0.82)


def item_json(**over) -> str:
    return json.dumps({**ITEM, **over}, ensure_ascii=False)
