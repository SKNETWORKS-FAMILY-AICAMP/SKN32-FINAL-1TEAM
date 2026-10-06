"""사전 정보 입력 연동 — 웹 DB에 저장된 폼 값을 읽어 T-C1 입력(PreInput)으로 옮긴다.

- record: 웹 DB 행 그릇 (잠정 규격)
- mapping: 행 → PreInput, 필수 항목 확인 (E-C1-REQUIRED)
- source: 공급처 인터페이스와 메모리 구현
- sql_source: 공유 MySQL 구현 (SQLAlchemy) — sqlalchemy가 필요해 여기서 불러오지 않는다
"""
from .mapping import LABELS, MissingRequired, to_pre_input  # noqa: F401
from .record import (  # noqa: F401
    CompanyRow, PlanInputRow, PricingItemRow, ProjectInputRecord, ProjectRow, TeamMemberRow,
)
from .source import MemoryProjectInputSource, ProjectInputSource  # noqa: F401
