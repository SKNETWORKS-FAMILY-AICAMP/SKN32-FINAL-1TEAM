"""S-Brain 명령 창구 — 웹 서버가 부르는 함수.

- 명령은 상태를 확인하고 대기열만 채운다. 실제 진행은 advance(run_id)가 한다.
  (누가 advance · tick을 부를지 — 웹 서버 스레드 · 별도 워커 · 작업 큐 — 는 웹팀 연동 때 정한다)
- 사용자 명령은 'decision' 산출물로 남겨 추적 기록에서 참조한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..models import Announcement, Notice, Notification, PreInput, ReworkOrder, Run
from ..models.run import ACTIVE_PROGRESS, make_state
from ..orchestrator.context import RunContext
from ..orchestrator.engine import Engine
from ..orchestrator.errors import CommandError, message
from ..orchestrator.settings import SettingsProvider
from .rework_map import TASK_BUNDLE
from .sbrain_flow import REVIEW, SCREEN_STEP, STEP_LABEL, WRITE, SBrainFlow, proto_queue, rework_queue


@dataclass
class StartResult:
    ok: bool
    run_id: str | None = None
    code: str | None = None
    message: str | None = None
    notices: list[Notice] = field(default_factory=list)
    active_run_id: str | None = None


@dataclass
class ConfirmationNeeded:
    """미달 상태로 검수에 들어가거나 실행을 중단할 때 확인받을 내용."""
    reason: str
    items: dict[str, Any]


@dataclass
class RunView:
    run_id: str
    step: str
    progress: str
    screen_status: str
    resume_step: int
    percent: int
    current_label: str | None
    notices: list[Notice]
    notifications: list[Notification]


class SBrainOrchestrator:
    def __init__(
        self,
        *,
        engine: Engine,
        flow: SBrainFlow,
        settings: SettingsProvider,
        announcements: Callable[[str], Announcement],
        profile_count: Callable[[str], int],
        now: Callable[[], datetime] = datetime.now,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self.engine = engine
        self.flow = flow
        self.store = engine.store
        self.settings = settings
        self.announcements = announcements
        self.profile_count = profile_count
        self.now = now
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:12])

    # ── 진행 ─────────────────────────────────────────
    def advance(self, run_id: str) -> str:
        return self.engine.advance(run_id)

    def tick(self, now: datetime | None = None) -> list[str]:
        return self.engine.tick(now)

    # ── 사전 정보 제출 → 공고 후보 ─────────────────────
    def start_run(self, account_id: str, form: PreInput) -> StartResult:
        if self.profile_count(account_id) <= 0:
            return StartResult(False, code="E-AUTH-PROFILE", message=message("E-AUTH-PROFILE"))
        active = self.store.find_active_run(account_id)
        if active is not None:
            return StartResult(False, code="E-RUN-CONCURRENT", message=message("E-RUN-CONCURRENT"),
                               active_run_id=active.run_id)
        now = self.now()
        run = Run(run_id=self.new_id(), account_id=account_id, state=make_state("공고선택", "실행"),
                  current_phase="setup", settings_snapshot=self.settings.snapshot(),
                  updated_at=now, created_at=now)
        ctx = self.engine.open_context(run, provisional=True)
        ctx.put("formInput", form, producer="user:start")
        run.queue = (["R-8"] if form.attachments else []) + ["T-C1", "T-C2"]
        run.segment, run.segment_total = "PRE", len(run.queue)
        last = self.engine.drain(ctx)
        if last is not None:
            # 아직 실행 건이 없으므로 재개하지 않고 진입 전 상태로 되돌린다 (E-C1-TIMEOUT)
            code = "X-C2-FAIL" if last.record and last.record.task_id == "T-C2" else "E-C1-TIMEOUT"
            return StartResult(False, code=code, message=message(code))
        if ctx.get("collectionStatus") != "정상":
            return StartResult(False, code="E-C2-STALE", message=message("E-C2-STALE"))
        if not ctx.get("candidates"):
            return StartResult(False, code="E-C2-NOMATCH", message=message("E-C2-NOMATCH"))
        if not self.store.create_run(ctx.run, ctx.take_provisional()):
            active = self.store.find_active_run(account_id)
            return StartResult(False, code="E-RUN-CONCURRENT", message=message("E-RUN-CONCURRENT"),
                               active_run_id=active.run_id if active else None)
        return StartResult(True, run_id=run.run_id, notices=list(run.notices))

    # ── 화면 3 · 4 · 5 ────────────────────────────────
    def more_candidates(self, run_id: str) -> None:
        def act(ctx: RunContext) -> None:
            total = sum(len(ctx.get("candidates", v)) for v in range(1, ctx.latest.get("candidates", 0) + 1))
            if ctx.run.more_used or total >= 20:
                raise CommandError("MORE_LIMIT", "추가 조회는 1회, 최대 20건")
            self._decide(ctx, {"command": "more", "offset": 10})
            ctx.run.more_used = True
            self._enqueue(ctx, ["T-C2"], "MORE", "공고선택")
        self._command(run_id, "공고선택", act)

    def select_announcement(self, run_id: str, announcement_id: str) -> None:
        def act(ctx: RunContext) -> None:
            ids = {card.announcement_id
                   for v in range(1, ctx.latest.get("candidates", 0) + 1) for card in ctx.get("candidates", v)}
            if announcement_id not in ids:
                raise CommandError("INVALID_ANNOUNCEMENT", announcement_id)
            dref = self._decide(ctx, {"command": "select", "announcementId": announcement_id})
            ctx.put("selectedAnnouncement", self.announcements(announcement_id), producer=f"user:{dref}")
            ctx.run.announcement_id = announcement_id
            self._enqueue(ctx, ["G-01"], "GATE", "자격확인")
        self._command(run_id, "공고선택", act)

    def start_writing(self, run_id: str) -> None:
        def act(ctx: RunContext) -> None:
            self._decide(ctx, {"command": "start_writing"})
            ctx.run.check_refs = {}
            ctx.run.current_phase = "document"
            self._enqueue(ctx, list(WRITE), "WRITE", "계획서작성")
        self._command(run_id, "계획서작성", act)

    # ── 화면 6 · 8 · 9 ────────────────────────────────
    def decide(self, run_id: str, screen: int, action: str, selected_orders: list[ReworkOrder] | None = None,
               confirmed: bool = False) -> ConfirmationNeeded | None:
        if screen not in SCREEN_STEP:
            raise CommandError("INVALID_SCREEN", str(screen))
        result: list[ConfirmationNeeded] = []

        def act(ctx: RunContext) -> None:
            if action == "진행":
                self._proceed(ctx, screen, confirmed, result)
            elif action == "재작성":
                self._rework(ctx, screen, selected_orders or [])
            else:
                raise CommandError("INVALID_ACTION", action)
        self._command(run_id, SCREEN_STEP[screen], act)
        return result[0] if result else None

    def _proceed(self, ctx: RunContext, screen: int, confirmed: bool, result: list) -> None:
        run = ctx.run
        if screen == 6:
            self._decide(ctx, {"command": "decide", "screen": 6, "action": "진행"})
            run.check_refs = {}
            run.current_phase = "artifact"
            self._enqueue(ctx, proto_queue(ctx.get("category")), "PROTO", "프로토타입제작")
        elif screen == 8:
            self._decide(ctx, {"command": "decide", "screen": 8, "action": "진행"})
            run.state = make_state("종합평가", "사용자대기")
        else:
            report = ctx.get("scoreReport.overall")
            if ctx.get("G-02b.nextAction") != "진행가능" and not confirmed:
                # 미달 상태로 진행 — 현재 점수 · 남는 미달 항목 · 되돌릴 수 없음을 확인받는다 (4-7)
                result.append(ConfirmationNeeded("검수 진입 확인", {
                    "현재 점수": report.total, "기준": report.threshold,
                    "남는 미달 항목": [o.reason for o in ctx.get("G-02b.reworkOrders")],
                    "되돌릴 수 없음": "진행 후에는 다시 만들 수 없습니다",
                }))
                return
            self._decide(ctx, {"command": "decide", "screen": 9, "action": "진행", "confirmed": confirmed})
            run.check_refs = {}
            run.current_phase = "review"
            self._enqueue(ctx, list(REVIEW), "REVIEW", "표현검수")

    def _rework(self, ctx: RunContext, screen: int, selected: list[ReworkOrder]) -> None:
        if not selected:
            raise CommandError("NO_SELECTION")
        judge = "G-02a" if screen == 6 else "G-02b"
        if ctx.get(f"{judge}.nextAction") == "상한도달":
            raise CommandError("E-G2-LIMIT", "미달 항목의 묶음이 모두 기회를 다 씀 — 진행만 가능")
        offered = ctx.get(f"{judge}.reworkOrders")
        if screen == 8:
            offered = [o for o in offered if o.layer == "artifact"]
        keyset = {(o.task_id, tuple(o.targets), o.layer) for o in offered}
        category = ctx.get("category")
        usage = {u.bundle_id: u for u in ctx.run.rework_usage}
        bundles: list[tuple[str, str]] = []
        for o in selected:
            if (o.task_id, tuple(o.targets), o.layer) not in keyset:
                raise CommandError("INVALID_ORDER", f"{o.task_id} {o.targets}")
            if o.task_id == "T-B1" and category == "원페이지":
                raise CommandError("INVALID_ORDER", "원페이지는 T-B1이 실행 목록에 없음")
            names = o.targets if o.layer == "document" else [TASK_BUNDLE.get(o.task_id, o.task_id)]
            for b in names:
                if b in usage and usage[b].remaining <= 0:
                    raise CommandError("E-G2-LIMIT", b)
                if (b, o.layer) not in bundles:
                    bundles.append((b, o.layer))
        orders_by_task: dict[str, dict] = {}
        for o in selected:  # 같은 Task를 고른 묶음은 한 호출로 합친다
            if o.task_id in orders_by_task:
                prev = ReworkOrder.model_validate(orders_by_task[o.task_id])
                o = prev.model_copy(update={
                    "targets": prev.targets + [t for t in o.targets if t not in prev.targets],
                    "reason": f"{prev.reason}; {o.reason}",
                    "instruction_delta": f"{prev.instruction_delta}\n{o.instruction_delta}"})
            orders_by_task[o.task_id] = o.dump()
        dref = self._decide(ctx, {
            "command": "decide", "screen": screen, "action": "재작성", "userAction": "재작성",
            "selectedOrders": [o.dump() for o in selected], "sourceRefs": [ctx.ref(f"{judge}.reworkOrders")],
        })
        queue = rework_queue(screen, selected, category)
        self.engine.start_cycle(ctx, screen=screen, selected_orders_ref=dref, orders_by_task=orders_by_task,
                                counted_bundles=bundles, layers=sorted({o.layer for o in selected}))
        ctx.run.queue = queue
        ctx.run.segment, ctx.run.segment_total = f"REWORK{screen}", len(queue)
        ctx.run.state = make_state(SCREEN_STEP[screen], "실행", screen)

    # ── 중단 ─────────────────────────────────────────
    def abort(self, run_id: str, confirmed: bool = False) -> ConfirmationNeeded | None:
        if not confirmed:
            return ConfirmationNeeded("중단 확인", {"안내": "중단하면 지금까지의 결과를 다시 볼 수 없습니다"})
        if self.store.is_locked(run_id, self.now()):
            self.store.request_abort(run_id)  # 진행 중이면 Task 사이에서 반영한다
            return None
        owner = f"cmd-{self.new_id()}"
        if not self.store.acquire(run_id, owner, 60):
            self.store.request_abort(run_id)
            return None
        try:
            run = self.store.load_run(run_id)
            if run.state.progress not in ACTIVE_PROGRESS:
                raise CommandError("NOT_ACTIVE", run.state.progress)
            ctx = RunContext(self.store, run, owner, self.engine.types, self.now, self.engine.immutable_keys)
            self.flow.on_abort(ctx)
            ctx.commit()
        finally:
            self.store.release(run_id, owner)
        return None

    # ── 화면 상태 · 이어하기 ───────────────────────────
    def view(self, run_id: str) -> RunView:
        run = self.store.load_run(run_id)
        notices = list(run.notices)
        if run.state.progress in ACTIVE_PROGRESS and run.announcement_id:
            ctx = self.engine.open_context(run)
            ann = ctx.get("selectedAnnouncement", default=None)
            if ann is not None and ann.apply_end < self.now().date():
                notices.append(Notice(code="E-RUN-CLOSED", message=message("E-RUN-CLOSED"), at=self.now()))
        total = run.segment_total
        percent = int(round((total - len(run.queue)) / total * 100)) if total else (100 if run.state.progress == "완료" else 0)
        current = run.queue[0] if run.queue else None
        label = None
        if current:
            label = STEP_LABEL.get(current) or self.engine.registry.get(current).name
        return RunView(run_id=run.run_id, step=run.state.step, progress=run.state.progress,
                       screen_status=run.state.screen_status, resume_step=run.state.resume_step,
                       percent=percent, current_label=label, notices=notices,
                       notifications=self.store.notifications(run_id))

    # ── 도움 함수 ─────────────────────────────────────
    def _command(self, run_id: str, expect_step: str, act: Callable[[RunContext], None]) -> None:
        owner = f"cmd-{self.new_id()}"
        if not self.store.acquire(run_id, owner, 60):
            raise CommandError("BUSY", run_id)
        try:
            run = self.store.load_run(run_id)
            if run.state.step != expect_step or run.state.progress != "사용자대기":
                raise CommandError("INVALID_STATE", f"{run.state.step}/{run.state.progress}")
            ctx = RunContext(self.store, run, owner, self.engine.types, self.now, self.engine.immutable_keys)
            act(ctx)
            ctx.commit()
        finally:
            self.store.release(run_id, owner)

    def _decide(self, ctx: RunContext, payload: dict[str, Any]) -> str:
        payload = {**payload, "at": self.now().isoformat()}
        ref = ctx.put("decision", payload, producer=f"user:{payload['command']}")
        ctx.run.decision_ref = ref
        return ref

    @staticmethod
    def _enqueue(ctx: RunContext, queue: list[str], segment: str, step: str) -> None:
        ctx.run.queue = queue
        ctx.run.segment, ctx.run.segment_total = segment, len(queue)
        ctx.run.state = make_state(step, "실행")
