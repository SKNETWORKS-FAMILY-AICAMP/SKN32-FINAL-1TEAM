"""기능정의서 v1.10 시트 4 공통 타입 (Agent 간 계약).

확장 새 타입: FileRef, BudgetItem · ScheduleItem · DiagramSpec · SectionResult(domain) · Verify1State(run)
(전략 · 작성 · 검증-1 연동). 모두 아래 모듈 전체 가져오기로 노출된다.
"""
from .base import SBModel, ext, extension_fields  # noqa: F401
from .domain import *  # noqa: F401,F403
from .files import *  # noqa: F401,F403
from .rework import *  # noqa: F401,F403
from .run import *  # noqa: F401,F403
from .scoring import *  # noqa: F401,F403
