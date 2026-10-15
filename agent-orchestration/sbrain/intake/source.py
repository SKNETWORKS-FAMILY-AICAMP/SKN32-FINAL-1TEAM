"""사전 정보 입력 공급처 — 프로젝트 ID로 웹 DB에 저장된 입력을 읽는다.

Task는 DB에 직접 접근하지 않는다(연동 규격 3절). 명령 창구가 여기서 읽어 formInput 산출물로 넘긴다.
"""
from __future__ import annotations

from typing import Protocol

from .record import ProjectInputRecord


class ProjectInputSource(Protocol):
    def load(self, project_id: int | str) -> ProjectInputRecord | None:
        """보관(삭제) 처리되지 않은 프로젝트의 입력. 없으면 None."""
        ...


class MemoryProjectInputSource:
    """테스트 · 시연용."""

    def __init__(self, records: list[ProjectInputRecord] | None = None) -> None:
        self._records: dict[str, ProjectInputRecord] = {}
        for r in records or []:
            self.add(r)

    def add(self, record: ProjectInputRecord) -> None:
        self._records[str(record.project.project_id)] = record

    def load(self, project_id: int | str) -> ProjectInputRecord | None:
        record = self._records.get(str(project_id))
        if record is None or record.project.archived_at is not None:
            return None
        return record
