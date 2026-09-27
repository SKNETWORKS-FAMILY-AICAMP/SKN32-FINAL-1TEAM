"""S-Brain 워크플로 — 구간 · 대기 지점 · 재작성 경로 · 알림 (시트 2 · 5 · 7, 기획서 4-7).

구간(segment)
  PRE      R-8? → T-C1 → T-C2                         (실행 건 생성 전)
  MORE     T-C2 (offset=10)                           → 3 공고 선택 대기
  GATE     G-01                                       → 5 작성 시작 대기 / 3 공고 선택 대기
  WRITE    T-C3 → T-S1 → T-S2 → T-W1 → T-W2 → T-W3 → M-1 → T-V1 → G-02a   → 6 문서 평가 대기
  PROTO    T-B1* → T-B2 → M-2** → G-04 → M-3 → T-V2 → G-02b              → 8 산출물 확인 대기
  REVIEW   G-03 → T-P1 → T-P2 → M-4 → T-C4                               → 11 완료
  REWORK6 · REWORK8 · REWORK9  재작성 사이클 (rework_queue 참고)
  * 원페이지면 생략  ** 원페이지만
G-02b는 T-V2 직후 계산하고(시트 2 "T-V2 종료 직후"), 화면 8을 거쳐 화면 9에서 보여준다.
"""
from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Callable

from ..contracts import tasks as c
from ..models import Notice, Notification, ReworkInput, ReworkOrder
from ..models.run import RedoState, make_state
from ..orchestrator.context import RunContext
from ..orchestrator.engine import Engine, Outcome
from ..orchestrator.errors import ToolCallExhausted, message
from ..orchestrator.registry import TaskRegistry, TaskSpec
from ..orchestrator.tools import CallSink
from ..orchestrator.trace import FeedbackLink
from .rework_map import DOCUMENT_TASKS

WRITE = ["T-C3", "T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "M-1", "T-V1", "G-02a"]
REVIEW = ["G-03", "T-P1", "T-P2", "M-4", "T-C4"]
CYCLE_END = "CYCLE-END"
SCREEN_STEP = {6: "문서평가", 8: "산출물확인", 9: "종합평가"}
STEP_LABEL = {CYCLE_END: "재작성 전후 비교"}


def proto_queue(category: str) -> list[str]:
    onepage = category == "원페이지"
    return ([] if onepage else ["T-B1"]) + ["T-B2"] + (["M-2"] if onepage else []) + ["G-04", "M-3", "T-V2", "G-02b"]


def rework_queue(screen: int, orders: list[ReworkOrder], category: str) -> list[str]:
    """고른 묶음에 따라 다시 돌릴 단계 (실행 순서대로). 합치기는 모든 경로에 들어간다."""
    tasks = {o.task_id for o in orders}
    onepage = category == "원페이지"
    doc = any(o.layer == "document" for o in orders)
    if screen == 6:
        return [t for t in DOCUMENT_TASKS if t in tasks] + ["M-1", "T-V1", CYCLE_END, "G-02a"]
    q: list[str] = []
    if doc:
        q += [t for t in DOCUMENT_TASKS if t in tasks] + ["M-1", "T-V1"]
    if not onepage and (doc or "T-B1" in tasks):
        q.append("T-B1")  # 화면 9 계획서 재작성은 HTML에도 반영 (재작성 횟수 안 씀)
    if "T-B2" in tasks:
        q.append("T-B2")
        if onepage:
            q.append("M-2")
    q += ["G-04", "M-3", "T-V2", CYCLE_END, "G-02b"]
    return q


def default_instruction_builder(base: str, rework_input: ReworkInput | None) -> str:
    """재작성 · 재수행 때 기존 지시문에 문제가 된 내용을 덧붙인다 (조율 Agent 구현으로 교체 예정)."""
    if rework_input is None:
        return base
    if rework_input.order is not None:
        return f"{base}\n\n[재작성] {rework_input.order.reason}\n{rework_input.order.instruction_delta}"
    return base + "\n\n[" + rework_input.mode + " — 문제가 된 내용]\n- " + "\n- ".join(rework_input.issues)


class SBrainFlow:
    def __init__(
        self,
        registry: TaskRegistry,
        *,
        constants: Callable[[RunContext, str], Any],
        now: Callable[[], datetime] = datetime.now,
        instruction_builder: Callable[[str, ReworkInput | None], str] = default_instruction_builder,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self.registry = registry
        self.constants = constants
        self.now = now
        self.instruction_builder = instruction_builder
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:12])
        self.engine: Engine | None = None

    # ── 엔진이 부르는 것 ───────────────────────────────
    def custom_step(self, step_id: str):
        if step_id == CYCLE_END:
            return self._cycle_end
        if step_id == "T-P2":
            return self._run_tp2
        return None

    def build_instruction(self, base: str, rework_input: ReworkInput | None) -> str:
        return self.instruction_builder(base, rework_input)

    def today(self, ctx: RunContext) -> date:
        return self.now().date()

    def constant(self, ctx: RunContext, name: str) -> Any:
        if name == "topK":
            return 10
        return self.constants(ctx, name)

    def value(self, ctx: RunContext, name: str, spec: TaskSpec) -> Any:
        if name == "rubricVersion":
            return self.constants(ctx, "rubric").version
        if name == "cycleInfo":
            cyc = ctx.run.cycle
            if cyc is None:
                return None
            snap = cyc.snapshot
            prev_doc =ctx.get("docScore", snap["docScore"]) if "document" in cyc.rescored_layers and "docScore" in snap else None
            prev_art = ctx.get("artifactScore", snap["artifactScore"]) if "artifact" in cyc.rescored_layers and "artifactScore" in snap else None
            carried = "document" if cyc.screen in (8, 9) and cyc.rescored_layers == ["artifact"] else None
            return c.ReworkCycleInfo(
                cycle_id=cyc.cycle_id, screen=cyc.screen, comparisons=list(cyc.comparisons),
                rescored_layers=list(cyc.rescored_layers), carried_over_layer=carried,
                reworked_task_ids=list(cyc.orders_by_task), previous_doc_score=prev_doc,
                previous_artifact_score=prev_art)
        raise KeyError(name)

    def initial_redo_state(self, ctx: RunContext, spec: TaskSpec) -> RedoState:
        cyc = ctx.run.cycle
        if cyc is None:
            return RedoState(task_id=spec.task_id, trigger="첫실행")
        tid = spec.task_id
        role = self._role(tid, cyc)
        rs = RedoState(task_id=tid, trigger="재작성", rework_role=role)
        if role == "대상":
            order = ReworkOrder.model_validate(cyc.orders_by_task[tid])
            decision = ctx.get_ref(cyc.selected_orders_ref)
            source_refs = list(decision.get("sourceRefs", [])) + [cyc.selected_orders_ref]
            prev = ctx.ref(spec.outputs[spec.primary_output]) if ctx.has(spec.outputs[spec.primary_output]) else ""
            issues = [order.reason] + ([order.instruction_delta] if order.instruction_delta else [])
            self._attach_rework(ctx, rs, spec, kind="재작성", source_refs=source_refs,
                                ri=dict(mode="재작성", previous_result_ref=prev, issues=issues, order=order),
                                bundle_id=",".join(order.targets))
        elif role == "반영" and tid == "T-B1":
            plan_ref = ctx.ref("planDoc")
            prev = ctx.ref("prototype") if ctx.has("prototype") else ""
            self._attach_rework(ctx, rs, spec, kind="재작성반영", source_refs=[plan_ref],
                                ri=dict(mode="재작성", previous_result_ref=prev,
                                        issues=[f"계획서 재작성 반영 ({plan_ref})"], order=None),
                                bundle_id=None)
        return rs

    def _attach_rework(self, ctx: RunContext, rs: RedoState, spec: TaskSpec, *, kind: str,
                       source_refs: list[str], ri: dict, bundle_id: str | None) -> None:
        fid, next_id = self.new_id(), self.new_id()
        rework_input = ReworkInput(is_final_attempt=False, source_refs=source_refs, feedback_id=fid, **ri)
        ri_ref = ctx.put(f"{spec.task_id}.reworkInput", rework_input, producer=f"orchestrator:{kind}")
        source_exec = self._producer_execution(ctx, source_refs[0]) if source_refs else None
        ctx.add_feedback(FeedbackLink(
            feedback_id=fid, run_id=ctx.run.run_id, kind=kind, source_execution_id=source_exec,
            source_refs=source_refs, target_task_id=spec.task_id, target_execution_id=next_id,
            via_ref=ri_ref, cycle_id=ctx.run.cycle.cycle_id if ctx.run.cycle else None,
            created_at=self.now()))
        rs.rework_input_ref = ri_ref
        rs.pending_execution_id = next_id
        rs.bundle_id = bundle_id

    @staticmethod
    def _producer_execution(ctx: RunContext, ref: str) -> str | None:
        producer = ctx.producer_of(ref)
        return None if ":" in producer else producer

    @staticmethod
    def _role(task_id: str, cyc) -> str:
        if task_id in cyc.orders_by_task:
            return "대상"
        if task_id.startswith("M-"):
            return "합치기"
        if task_id in ("T-V1", "T-V2"):
            return "재채점"
        if task_id in ("G-02a", "G-02b"):
            return "판정"
        return "반영"  # T-B1(계획서 반영) · G-04

    def after_step(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None:
        out = outcome.outputs
        if step_id == "R-8":
            for doc in out.get("reference_docs", []):
                if doc.extract_status == "실패":
                    self._notice(ctx, "E-C1-DOC", 파일명=doc.file_name)
        elif step_id == "T-C2" and out.get("fallback_used"):
            self._notice(ctx, "E-C2-EMBED")

    def on_queue_empty(self, ctx: RunContext) -> None:
        run, seg = ctx.run, ctx.run.segment
        if seg in ("PRE", "MORE"):
            self._wait(ctx, "공고선택", "setup")
        elif seg == "GATE":
            gate = ctx.get("gateResult")
            if gate.passed and not gate.undecidable and not gate.missing_inputs:
                self._wait(ctx, "계획서작성", "setup")
            else:
                if gate.missing_inputs:
                    self._notice(ctx, "E-G1-MISSING")
                elif gate.undecidable:
                    self._notice(ctx, "E-G1-UNPARSED")
                else:
                    self._notice(ctx, "E-G1-REJECT", 사유=", ".join(gate.failed_conditions))
                self._wait(ctx, "공고선택", "setup")
        elif seg == "WRITE":
            self._wait(ctx, "문서평가", "document")
            self._notify(ctx, "문서평가", 6)
        elif seg == "PROTO":
            self._wait(ctx, "산출물확인", "artifact")
            self._notify(ctx, "산출물확인", 8)
        elif seg in ("REWORK6", "REWORK8", "REWORK9"):
            screen = run.cycle.screen
            rescored = list(run.cycle.rescored_layers)
            assert self.engine is not None
            self.engine.end_cycle(ctx)
            self._wait(ctx, SCREEN_STEP[screen], "document" if screen == 6 else "artifact")
            # 재작성으로 검증을 다시 실행한 경우에도 알림. 대상 화면은 요청한 화면 (잠정)
            kind = "문서평가" if screen == 6 or rescored == ["document"] else "산출물확인"
            self._notify(ctx, kind, screen)
        elif seg == "REVIEW":
            run.state = make_state("결과물", "완료")
            run.current_phase = "review"
            run.segment, run.segment_total, run.ended_at = None, 0, self.now()
            self._notify(ctx, "표현검수", 10)
        else:
            raise RuntimeError(f"알 수 없는 구간: {seg}")

    def on_unresumable(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None:
        if ctx.provisional:
            return  # 사전 단계 — 실행 건을 만들지 않고 호출한 쪽이 안내한다
        if step_id == "T-C2":  # 추가 조회 실패 — 다시 시도 안내 (잠정)
            ctx.run.queue = []
            self._notice(ctx, "X-C2-FAIL")
            self._wait(ctx, "공고선택", "setup")

    def on_abort(self, ctx: RunContext) -> None:
        run = ctx.run
        run.queue, run.redo_state, run.cycle, run.rework_screen = [], None, None, None
        run.state = make_state(run.state.step, "중단")
        run.ended_at = self.now()
        ctx.add_event("중단", "사용자 중단 (Task 사이에서 반영)")

    def on_run_failed(self, ctx: RunContext, reason: str) -> None:
        self._notice(ctx, "E-RUN-FAIL")
        self._notify(ctx, "실패", None, scope="실행")

    def on_cycle_failed(self, ctx: RunContext, reason: str) -> None:
        screen = ctx.run.cycle.screen
        assert self.engine is not None
        self.engine.end_cycle(ctx)
        self._wait(ctx, SCREEN_STEP[screen], "document" if screen == 6 else "artifact")
        self._notice(ctx, "E-RUN-ROLLBACK")
        self._notify(ctx, "실패", screen, scope="재작성")

    # ── 재작성 전후 비교 (Orchestrator 내부 단계) ──────────
    def _cycle_end(self, engine: Engine, ctx: RunContext) -> Outcome:
        cyc = ctx.run.cycle
        assert cyc is not None
        snap = cyc.snapshot
        doc_changed = ctx.pointers.get("docScore") != snap.get("docScore")
        art_changed = ctx.pointers.get("artifactScore") != snap.get("artifactScore")

        def total(key: str, version: int | None) -> float:
            return ctx.get(key, version).total if version else 0.0

        doc_b, doc_a = total("docScore", snap.get("docScore")), total("docScore", ctx.pointers.get("docScore"))
        art_b, art_a = total("artifactScore", snap.get("artifactScore")), total("artifactScore", ctx.pointers.get("artifactScore"))
        if doc_changed and art_changed:
            basis, before, after = "total", doc_b + art_b, doc_a + art_a
        elif doc_changed:
            basis, before, after = "document", doc_b, doc_a
        elif art_changed:
            basis, before, after = "artifact", art_b, art_a
        else:
            basis, before, after = "none", 0.0, 0.0
        cyc.rescored_layers = [l for l, ch in (("document", doc_changed), ("artifact", art_changed)) if ch]
        engine.compare_and_keep(ctx, before=before, after=after, basis=basis)
        return Outcome("ok")

    # ── T-P2 문장별 병렬 실행기 ────────────────────────
    def _run_tp2(self, engine: Engine, ctx: RunContext) -> Outcome:
        spec = self.registry.get("T-P2")
        s = ctx.settings
        rs = ctx.run.redo_state if ctx.run.redo_state and ctx.run.redo_state.task_id == "T-P2" else None
        resuming = rs is not None and rs.pending_execution_id is not None
        rs = rs or self.initial_redo_state(ctx, spec)
        rec = engine.open_execution(ctx, spec, rs)
        rec.inputs = [ctx.ref(k) for k in ("targetSentenceIds", "protectedTokens", "formatFindings",
                                           "planDoc", "selectedAnnouncement") if ctx.has(k)]
        targets: list[str] = ctx.get("targetSentenceIds")
        tokens = ctx.get("protectedTokens")

        def finish(results: list[c.SentenceResult], status: str, note: str | None = None) -> Outcome:
            ref = ctx.put("sentenceResults", results, producer=rec.execution_id)
            rec.outputs, rec.result_ref, rec.status, rec.ended_at = [ref], ref, status, self.now()
            rec.output_meta.note = note
            ctx.record_execution(rec)
            ctx.record_attempt(rec)
            ctx.run.redo_state = None
            return Outcome("ok", {"sentence_results": results}, rec)

        if not targets or not tokens:
            # 윤문 대상 0건이면 T-P2를 실행하지 않고, 보호 토큰 0건이면 형식 검수만 하고 윤문을 생략한다
            return finish([], "생략", "윤문 대상 없음" if not targets else "보호 토큰 0건 — 윤문 생략")

        sink = CallSink()
        try:
            cfg = engine.tools_config(ctx, spec)
            rec.model, rec.provider, rec.temperature = cfg.model, cfg.provider, cfg.temperature
            tools = engine.make_tools(ctx, spec, rec, cfg, sink)
            plan = ctx.get("planDoc")
            sentences = {x.sentence_id: x for sec in plan.sections for x in sec.sentences}
            fspec = ctx.get("selectedAnnouncement").form_spec.format_spec
            findings = ctx.get("formatFindings")
            prior = {r.sentence_id: r for r in ctx.get("sentenceResults", default=[])} if resuming else {}
            todo = [sid for sid in targets if sid not in prior or prior[sid].kept_reason == "호출실패"]
            limit = s.redo.proofread_limit

            def one(sid: str) -> c.SentenceResult:
                original = sentences[sid]
                item_tools = tools.for_item(sid)
                hint: list[str] = []
                redo, prev_hash = 0, None
                mine = [f for f in findings if f.sentence_id == sid]
                while True:
                    try:
                        out = spec.fn(c.TP2In(sentence=original, protected_tokens=tokens, format_findings=mine,
                                              format_spec=fspec, redo_hint=list(hint), redo_count=redo), item_tools)
                    except ToolCallExhausted:
                        return c.SentenceResult(sentence_id=sid, adopted=False, kept_reason="호출실패",
                                                final_redo_count=redo)
                    out = out if isinstance(out, c.TP2Out) else c.TP2Out.model_validate(out)
                    if out.adopted and out.token_check.passed:
                        return c.SentenceResult(sentence_id=sid, adopted=True, revised=out.revised,
                                                final_redo_count=redo, token_check=out.token_check)
                    h = hashlib.sha256(out.revised.text.encode("utf-8")).hexdigest()
                    if prev_hash is not None and h == prev_hash:
                        return c.SentenceResult(sentence_id=sid, adopted=False, kept_reason="조기중단",
                                                final_redo_count=redo, token_check=out.token_check)
                    if redo >= limit:
                        return c.SentenceResult(sentence_id=sid, adopted=False, kept_reason="검증실패",
                                                final_redo_count=redo, token_check=out.token_check)
                    hint.extend(x for x in out.next_redo_hint if x not in hint)  # 교체하지 않고 누적
                    prev_hash, redo = h, redo + 1

            with ThreadPoolExecutor(max_workers=max(1, s.proofread.concurrency)) as pool:
                done = dict(zip(todo, pool.map(one, todo)))
            ctx.batch.call_logs.extend(sink.drain())
        except Exception as e:  # Agent 코드 오류 등
            ctx.batch.call_logs.extend(sink.drain())
            return engine.on_step_error(ctx, spec, rec, e)

        merged = {**prior, **done}
        results = [merged[sid] for sid in targets if sid in merged]
        failed = [r for r in results if r.kept_reason == "호출실패"]
        if failed and len(failed) / len(targets) > s.proofread.failure_ratio_threshold:
            if engine.can_resume(ctx) is not None:
                ref = ctx.put("sentenceResults", results, producer=rec.execution_id)
                rec.outputs, rec.result_ref = [ref], ref
                rs.pending_execution_id = rec.execution_id
                return engine.schedule_resume(ctx, rec, rs, "일시")
            ctx.add_event("검수재개상한", "실패 비율이 기준을 넘었으나 재개 상한 초과 — 원문 유지한 채 완료",
                          execution_id=rec.execution_id)
        return finish(results, "성공")

    # ── 도움 함수 ─────────────────────────────────────
    def _wait(self, ctx: RunContext, step: str, phase: str) -> None:
        run = ctx.run
        run.state = make_state(step, "사용자대기")
        run.current_phase = phase
        run.segment, run.segment_total, run.queue = None, 0, []

    def _notice(self, ctx: RunContext, code: str, **slots: str) -> None:
        ctx.run.notices.append(Notice(code=code, message=message(code, **slots), at=self.now()))

    def _notify(self, ctx: RunContext, kind: str, target: int | None, scope: str | None = None) -> None:
        ctx.notify(Notification(run_id=ctx.run.run_id, kind=kind, failure_scope=scope, target_step=target,
                                created_at=self.now(), notification_id=self.new_id()))
