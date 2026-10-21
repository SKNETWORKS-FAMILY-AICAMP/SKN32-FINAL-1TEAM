"""관리자 표시 상태. 원본 모집 상태는 변경하지 않는다."""
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))


def korea_today() -> datetime.date:
    return datetime.datetime.now(KST).date()


def notice_display_status(
    recruitment_status: str, apply_start: datetime.date | None,
    apply_end: datetime.date | None, apply_period_type: str | None,
    *, today: datetime.date,
) -> str:
    if apply_start and apply_end and apply_start > apply_end:
        return '확인 필요'
    if apply_end and apply_end < today:
        return '마감'
    if apply_start and apply_start > today:
        return '접수 예정'
    if recruitment_status == 'closed':
        return '마감'
    if recruitment_status == 'open':
        return '모집중'
    if (apply_start and apply_end and apply_start <= today <= apply_end
            and apply_period_type not in ('budget_exhaustion', 'rolling', 'until_filled')):
        return '접수기간 내 · 원문 확인'
    return '확인 필요'
