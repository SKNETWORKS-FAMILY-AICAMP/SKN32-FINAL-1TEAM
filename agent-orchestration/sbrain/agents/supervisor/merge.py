"""합치기 M-1 ~ M-4 — 조율 Agent의 규칙 단계 (기준 문서 시트 2 r18 T-C4 '조율은 실행 중 다음 합치기를 맡는다' ① ~ ④).

규칙 단계라 tools를 받지 않는다(LLM 없음 · 파일을 열지 않음). 함수 모양은 run_mN(inp) -> 출력.

- M-1: 차트 · 표를 계획서에 싣고, 표 항목 문장은 tableSections의 같은 항목으로 바꾸며, 그림 목록은 diagrams로 통째로 바꾼다.
- M-2: 원페이지 인포그래픽 그림 참조를 그대로 진입 파일로 감싼다 — Prototype(kind='svg-onepage', entryFile = 인포그래픽
  imageFile, assetFiles = []). 파일을 열지 않는다(같은 실행 건의 참조).
- M-3: G-04가 만든 안내 문서 참조(readmeFile)를 Prototype에 끼운다.
- M-4: 채택된 문장(adopted)을 계획서에 반영하고 ProofreadLog를 집계한다.
"""
from __future__ import annotations

from ...contracts.tasks import M1In, M1Out, M2In, M2Out, M3In, M3Out, M4In, M4Out
from ...models import ProofreadLog, Prototype


def run_m1(inp: M1In) -> M1Out:
    by_code = {s.section_code: s for s in inp.table_sections}
    sections = [by_code.get(s.section_code, s) for s in inp.plan_doc.sections]
    return M1Out(plan_doc=inp.plan_doc.model_copy(update={
        "charts": inp.charts, "tables": inp.tables, "sections": sections, "diagrams": list(inp.diagrams)}))


def run_m2(inp: M2In) -> M2Out:
    return M2Out(prototype=Prototype(entry_file=inp.infographic.image_file, kind="svg-onepage",
                                     asset_files=[], implemented_features=list(inp.feature_list)))


def run_m3(inp: M3In) -> M3Out:
    return M3Out(prototype=inp.prototype.model_copy(update={"readme_file": inp.readme_file}))


def run_m4(inp: M4In) -> M4Out:
    by_id = {r.sentence_id: r for r in inp.sentence_results}
    sections = [sec.model_copy(update={"sentences": [
        by_id[s.sentence_id].revised if s.sentence_id in by_id and by_id[s.sentence_id].adopted else s
        for s in sec.sentences]}) for sec in inp.plan_doc.sections]
    n = len(inp.target_sentence_ids)
    first_pass = sum(1 for r in inp.sentence_results if r.adopted and r.final_redo_count == 0)
    log = ProofreadLog(
        total_sentences=n, adopted_count=sum(1 for r in inp.sentence_results if r.adopted),
        retained_by_check_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "검증실패"],
        retained_by_call_failure_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "호출실패"],
        early_stopped_sentence_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "조기중단"],
        token_preservation_rate=(first_pass / n) if n else 1.0, model_version=inp.model_version)
    return M4Out(plan_doc=inp.plan_doc.model_copy(update={"sections": sections}), proofread_log=log)


__all__ = ["run_m1", "run_m2", "run_m3", "run_m4"]
