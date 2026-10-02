"""관리자 설정값 공급처 — 웹 verification_policies를 읽어 기본 설정에 덮어쓴다.

| verification_policies | Settings |
|---|---|
| doc_weight | 문서층 배점 (scoring.docLayerMax) |
| code_weight + plan_weight | 산출물층 배점 (scoring.artifactLayerMax) |
| pass_threshold | Threshold (scoring.threshold) |
| rerun_cap | 재수행 횟수 (redo.redoCount) |
| rework_cap | 재작성 횟수 — 묶음마다 (rework.perBundle) |
| token_retry_cap | 검수 재수행 횟수 (redo.proofreadRedoCount) |
| deviation_cap | 확장 필드에 담아만 둔다 (scoring.deviationCap, 검증-1 연동 전, 잠정) |

- 첫 행(policy_id 최솟값)을 쓴다. 웹도 단일 행을 그렇게 읽는다.
- 나머지(재시도 · 재개 · 제한 시간 · 검수 동시 처리 · Agent 모델)는 코드 기본값이다(웹팀 답 대기, 잠정).
- 실행을 시작할 때 snapshot()으로 실행 건에 고정되는 것은 메모리 공급처와 같다.
"""
from __future__ import annotations

from sqlalchemy import Engine

from ..orchestrator.settings import Settings, SettingsProvider
from .web_tables import WebTables


class DbSettingsProvider(SettingsProvider):
    def __init__(self, engine: Engine, base: Settings | None = None, web: WebTables | None = None) -> None:
        super().__init__(base)
        self.engine = engine
        self.web = web or WebTables()

    def current(self) -> Settings:
        with self.engine.connect() as conn:
            row = self.web.first_policy(conn)
        s = self._settings.model_copy(deep=True)
        if row is None:
            return s
        s.scoring.doc_layer_max = float(row["doc_weight"])
        s.scoring.artifact_layer_max = float(row["code_weight"]) + float(row["plan_weight"])
        s.scoring.threshold = float(row["pass_threshold"])
        s.scoring.deviation_cap = float(row["deviation_cap"])
        s.redo.redo_count = int(row["rerun_cap"])
        s.rework.per_bundle = int(row["rework_cap"])
        s.redo.proofread_redo_count = int(row["token_retry_cap"])
        return Settings.model_validate(s.dump())

    def snapshot(self) -> dict:
        return self.current().dump()
