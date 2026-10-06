"""공고 서버 연결 — 실제 T-C2(공고 매칭) · G-01(자격 확인) (spec 3 · 4.1 · 4.3.2 · 4.4).

공고팀 공고 서버의 HTTP API를 부른다. 공고팀 코드를 import하지 않고, 공유 DB의 공고 표를 읽지 않는다.
패키지 이름은 공고팀 패키지(search · shared)와 겹치지 않게 notice로 둔다.

| 모듈 | 내용 |
|---|---|
| `client` | `NoticeClient`(네 API) · `UrllibTransport`(표준 라이브러리 전송) · `NOT_FOUND`(공고 없음 값) |
| `tc2` | `make_tc2(client)` — 수집 상태 → 공고 추천 → 카드, 보내는 칸 `match_request` · 시 · 도 바꾸기 `region_fields` |
| `g01` | `make_g01(client)` — 공고 상세 → Announcement, 자격 판정 → GateResult · 업력 `business_age_years` |
| `convert` | 응답 값 검사 · 변환 도움 (약속 밖이면 FormatError) |

워커 조립(`bootstrap.build_app`)이 SBRAIN_NOTICE_API_URL이 있을 때 `bind_notice`로 스텁을 바꿔 끼운다.
"""
from __future__ import annotations

from ...orchestrator.registry import TaskRegistry
from .client import NOT_FOUND, NoticeClient, NotFound, Transport, UrllibTransport
from .g01 import business_age_years, eligibility_request, make_g01, to_announcement, to_gate
from .tc2 import REGION_MAP, make_tc2, match_reason, match_request, region_fields, to_card

__all__ = [
    "NOT_FOUND", "NotFound", "NoticeClient", "REGION_MAP", "Transport", "UrllibTransport", "bind_notice",
    "business_age_years", "eligibility_request", "make_g01", "make_tc2", "match_reason", "match_request",
    "region_fields", "to_announcement", "to_card", "to_gate",
]


def bind_notice(registry: TaskRegistry, client: NoticeClient) -> None:
    """T-C2 · G-01에 공고 서버 연결 구현을 끼운다 (스텁을 바꾼다)."""
    registry.bind("T-C2", make_tc2(client))
    registry.bind("G-01", make_g01(client))
