"""파일 삭제 대기열 처리 (확장) — 워커가 작업 확인 주기마다 한 번 부른다.

- 대기열 줄(orch_file_deletions)은 산출물을 지우는 같은 트랜잭션에서 저장소가 넣는다(delete_artifacts ·
  retire_run(delete_run=True) — 완전 삭제 · 12개월 처리의 완전 삭제된 실행 건 정리 · 탈퇴). 파일은 여기서만 지운다.
  웹 프로세스는 파일을 지우지 않는다.
- 한 번 처리: next_at이 지난 '대기' 줄을 묶음으로 가져가(줄마다 next_at을 미뤄 한 워커만) 실행 건 키 접두어('<runId>/')
  아래를 통째로 지운다. 이미 없으면 성공이다.
  - 성공하면 줄을 지운다.
  - 실패하면 attempts +1, next_at을 다시 시도 간격 뒤로 미룬다. attempts가 MAX_ATTEMPTS(3)에 이르면 '포기'.
- 첫 시도는 넣은 시각 + FIRST_DELAY_SEC 뒤다(저장소가 next_at에 넣는다). 워커 점유 시간(120초)보다 길게 두어, 삭제 직전에
  돌던 단계의 늦은 쓰기가 끝난 뒤에 지운다.
- 범용이다 — 실행 건 ID와 파일 저장소 창구만 안다. 운영 로그(sbrain.run)에 파일삭제 · 파일삭제실패 · 파일삭제포기 줄을
  남긴다(실행 건 · 대기열 줄 번호까지, 키 · 파일 이름 · 오류 메시지 없음).
- 잠정 값: FIRST_DELAY_SEC · RETRY_SEC · BATCH_SIZE (PROVISIONAL fileDeletion.*). MAX_ATTEMPTS 3은 사용자가 정한 값이라
  잠정이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models.base import ErrorKind
from . import runlog
from .files import FileStore
from .store import Store

FIRST_DELAY_SEC = 600.0   # 넣은 뒤 첫 시도까지 (10분, 잠정) — 워커 점유 시간 120초보다 길게
RETRY_SEC = 600.0         # 실패 뒤 다시 시도 간격 · 가져간 줄을 미루는 시간 (10분, 잠정)
BATCH_SIZE = 20           # 한 번에 가져가는 줄 수 (잠정)
MAX_ATTEMPTS = 3          # 이만큼 실패하면 '포기'(잠정 아님)


@dataclass
class DeletionSummary:
    """한 번 처리의 개수 — 지움 · 실패(다시 시도 예정) · 포기 · 가져갔지만 다른 워커에 넘어감."""
    deleted: int = 0
    failed: int = 0
    gave_up: int = 0
    lost: int = 0

    @property
    def total(self) -> int:
        return self.deleted + self.failed + self.gave_up + self.lost


def error_kind_of(e: BaseException) -> ErrorKind:
    """지우기 실패의 오류 종류 — tools의 분류와 같은 값. 디스크 오류는 일시, 키 규칙 위반은 입력, 나머지는 운영."""
    if isinstance(e, (OSError, TimeoutError)):
        return "일시"
    if isinstance(e, (ValueError, LookupError)):
        return "입력"
    return "운영"


def process_file_deletions(store: Store, files: FileStore, *, batch_size: int = BATCH_SIZE,
                           retry_sec: float = RETRY_SEC, max_attempts: int = MAX_ATTEMPTS,
                           stop: Callable[[], bool] | None = None) -> DeletionSummary:
    """대기열을 한 번 처리한다. 가져가기 자체의 오류(DB 오류 등)는 올린다 — 부른 쪽(워커)이 종류만 남긴다.

    stop이 참이면 다음 줄로 넘어가지 않는다. 가져갔지만 처리하지 않은 줄은 미룬 next_at이 지나면 다시 가져가진다.
    """
    summary = DeletionSummary()
    for row in store.claim_file_deletions(batch_size, retry_sec):
        if stop is not None and stop():
            break
        try:
            files.delete_prefix(row.key_prefix)
        except Exception as e:   # 지우기 실패 — 종류만 적고 다시 시도 · 포기 (메시지는 키 · 경로가 들 수 있어 남기지 않는다)
            updated = store.fail_file_deletion(row.deletion_id, row.next_at, error_kind_of(e), retry_sec=retry_sec,
                                               max_attempts=max_attempts)
            if updated is None:
                summary.lost += 1
                continue
            runlog.file_delete_failed(updated, type(e).__name__)
            if updated.status == "포기":
                runlog.file_delete_gave_up(updated)
                summary.gave_up += 1
            else:
                summary.failed += 1
            continue
        if store.finish_file_deletion(row.deletion_id, row.next_at):
            runlog.file_deleted(row)
            summary.deleted += 1
        else:
            summary.lost += 1
    return summary
