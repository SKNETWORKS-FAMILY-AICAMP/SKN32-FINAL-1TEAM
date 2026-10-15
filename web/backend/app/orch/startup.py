"""서버 시작 때 오케스트레이터 gateway를 만든다."""
from .gateway import build_gateway, init_gateway


def init_orchestrator() -> bool:
    """MySQL 모드에서만 만든다(오케스트레이터는 SQLite를 지원하지 않는다). 만들었으면 True.

    만들지 못한 채(예: SQLite 개발 모드) 라우터가 gateway를 쓰면 require_gateway가 503으로 답한다.
    """
    from app.database import IS_SQLITE, SessionLocal
    from app.routers.profile import compute_has_profile

    if IS_SQLITE:
        return False

    def profile_count(account_id: str) -> int:
        with SessionLocal() as db:
            return 1 if compute_has_profile(db, int(account_id)) else 0

    init_gateway(build_gateway(profile_count=profile_count))
    return True
