"""S-Brain 명령 창구 — 웹 서버가 부르는 함수.

- 명령은 상태를 확인하고 대기열만 채운다. 실제 진행은 advance(run_id)가 한다.
  웹 서버와 워커는 별도 프로세스이고(웹팀 합의 2026-09-30), 진행 · 재개는 워커가 부른다.
- 사전 단계 시작은 두 조각이다 (확장).
  request_start: 웹 요청 안에서 바로 끝난다 — 입력 확인 · 필수 항목 · 프로필 · 동시 실행 확인 후 '대기' 요청을 넣는다.
  run_start_request: 워커가 부른다 — 사전 단계(R-8? → T-C1 → T-C2)를 돌고 실행 건 생성과 요청 '완료'를 한 번에 저장한다.
  start_run · start_run_for_project는 두 조각을 차례로 부르는 동기 경로다(테스트 · 시연용).
- 사용자 명령은 'decision' 산출물로 남겨 추적 기록에서 참조한다.
- 재작성은 묶음 이름으로 요청받는다(request_rework_for_project, 확장). 같은 화면에서 모으는 시간(잠정 2초) 안의
  요청은 재작성 한 번으로 합치고, 모으는 동안 워커는 그 실행 건을 가져가지 않는다.
- 웹 조립(build_web)은 allow_pre_stage가 거짓이라 사전 단계를 돌지 않는다 — run_start_request(와 동기 경로)를 부르면
  시작 요청을 건드리지 않고 바로 CommandError("WEB_NOT_ALLOWED") (spec 3.4).
- 탈퇴(delete_account_data, 확장): 계정 잠금 안에서 중단 · 취소한 뒤 그 계정의 실행 건 · 시작 요청을 통계 줄로 옮기고 지운다.
- 웹이 쓰는 조회(spec 4): view_project · project_views · missing_projects · wait_project · outputs · rework_result · active_work,
  관리자 admin_runs · admin_score_history · admin_summary · admin_agent_tasks (모양은 flow/reads.py).
- 산출물 파일(확장): 웹 read_artifact_file(파일 내용 · 형식), 관리자 admin_file_deletions(삭제 대기열 목록) ·
  admin_retry_file_deletion(포기한 줄 다시 시도). 웹 조립에서 부를 수 있다. 웹은 파일을 쓰지도 지우지도 않는다.
"""
from __future__ import annotations

import math
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from ..intake import MissingRequired, ProjectInputSource, to_pre_input
from ..models import Notice, Notification, PreInput, ReworkOrder, Run
from ..models.clock import as_utc, kst_today, utc_clock, utc_now
from ..models.run import ACTIVE_PROGRESS, collecting, make_state, progress_percent
from ..orchestrator.context import RunContext
from ..orchestrator.engine import Engine
from ..orchestrator.errors import CommandError, StoreConflict, message
from ..orchestrator.files import FileStore
from ..orchestrator.settings import SettingsProvider
from ..orchestrator.store import FINISHED_REQUEST, PENDING_REQUEST, RunFilter, StartRequest
from . import reads
from .catalog import FORM_SPEC
from .log_stats import start_request_rows
from .retention import gather_run_stats
from .rework_map import BUNDLE_EXECUTABLE, BUNDLE_LAYER, LAYER_SCREENS, TASK_BUNDLE
from .sbrain_flow import (
    CANDIDATE_LIMIT, MORE_BEFORE_POINTERS, REVIEW, SCREEN_STEP, SELECTION_STEPS, STEP_LABEL, STEP_SCREEN, WRITE,
    SBrainFlow, bundle_orders, candidate_lists, proto_queue, rework_queue,
)

MAX_START_CLAIMS = 3   # 시작 요청을 가져간 횟수 상한 — 넘으면 E-C1-TIMEOUT으로 끝낸다 (잠정)
COMMAND_LEASE_SEC = 60   # 명령이 잡는 점유 시간
# 재작성 요청 (잠정 — orchestrator/settings.py PROVISIONAL에도 적는다)
REWORK_COLLECT_SEC = 2.0            # 같은 화면에서 첫 요청부터 이 시간 안의 요청을 재작성 한 번으로 모은다
REWORK_LEASE_RETRY_SEC = 5.0        # 요청이 명령 점유를 다시 시도하는 최대 시간 — 넘으면 BUSY
REWORK_LEASE_RETRY_INTERVAL_SEC = 0.05   # 점유를 다시 시도하는 간격 (내부 조정값, 화면 · 웹과 무관해 PROVISIONAL에는 싣지 않는다)
# 진행 기다리기 (잠정 — orchestrator/settings.py PROVISIONAL에도 적는다)
WAIT_TIMEOUT_SEC = 60.0             # wait_project 기본 제한 시간 — 넘기면 그때의 상태를 그대로 준다
WAIT_POLL_SEC = 0.5                 # wait_project가 DB를 다시 읽는 간격
# 작성 시작 전 공고 다시 고르기 · 추가 조회를 받는 단계 — 공고선택 · 사용자대기, 자격 통과 뒤 계획서작성 · 사용자대기 (3.3)
# G-01이 실패하면 돌아가는 대기 지점과 같은 목록이다 (sbrain_flow.SELECTION_STEPS)
ANNOUNCEMENT_STEPS = SELECTION_STEPS
WITHDRAW_REASON = "탈퇴"   # 탈퇴로 옮긴 통계 줄의 까닭 (log_stats.REASONS)


@dataclass
class StartResult:
    ok: bool
    run_id: str | None = None
    code: str | None = None
    message: str | None = None
    notices: list[Notice] = field(default_factory=list)
    active_run_id: str | None = None


@dataclass
class ActiveWork:
    """진행 중인 작업 (확장) — E-RUN-CONCURRENT 때 함께 돌려준다. 웹의 기존 409 응답 blocked 정보를 대신한다.

    실행 건이 있으면 run_id · 단계 · 복귀 화면 · 화면 상태, 사전 단계 요청이 처리 중이면 request_id만 있다.
    """
    project_id: str | None
    run_id: str | None = None
    request_id: str | None = None
    step: str | None = None
    resume_step: int | None = None
    screen_status: str = "진행 중"


@dataclass
class StartCheck:
    """request_start 결과 (확장). ok면 request_id로 start_status를 조회한다."""
    ok: bool
    request_id: str | None = None
    code: str | None = None
    message: str | None = None
    missing: list[str] = field(default_factory=list)   # E-C1-REQUIRED — 누락 항목 이름
    active: ActiveWork | None = None                    # E-RUN-CONCURRENT — 진행 중인 작업


@dataclass
class StartStatus:
    """시작 요청의 상태 (확장) — start_status · run_start_request 결과.

    status: 대기 · 처리중 · 완료 · 실패 · 취소. 완료면 run_id, 실패면 code · message(시트 6 문구).
    """
    request_id: str
    status: str
    code: str | None = None
    message: str | None = None
    notices: list[Notice] = field(default_factory=list)
    run_id: str | None = None
    active: ActiveWork | None = None


@dataclass
class ProjectView:
    """view_project 결과 (확장). 실행 건이 있으면 run, 없으면 그 프로젝트의 마지막 시작 요청 상태(start)."""
    project_id: str
    run: RunView | None = None
    start: StartStatus | None = None


@dataclass
class AbortResult:
    """abort_project 결과 (확장) — 무엇을 했는지.

    run_action: 중단(바로 반영) · 중단요청(워커가 단계를 도는 중 — 단계 사이에 반영) · 이미끝남 · None(실행 건 없음)
    """
    project_id: str
    cancelled_requests: list[str] = field(default_factory=list)   # 대기 중 시작 요청 → 취소
    cancel_requested: list[str] = field(default_factory=list)     # 처리 중 시작 요청 → 실행 건을 만들기 전에 취소
    run_id: str | None = None
    run_action: str | None = None


@dataclass
class DeleteResult:
    """delete_project_data 결과 (확장). 산출물 · 입력 사본을 지우고 실행 로그는 남긴다."""
    project_id: str
    abort: AbortResult
    run_id: str | None = None
    deleted_artifacts: bool = False       # 실행 건의 산출물(버전 · 포인터)을 지웠는지
    cleared_forms: int = 0                # 입력 사본(form)을 지운 시작 요청 수


@dataclass
class AccountDeleteResult:
    """delete_account_data 결과 (확장) — 탈퇴. 그 계정의 orch_ 데이터를 통계 줄로 옮긴 뒤 지운 결과.

    남은 것이 없으면(다시 부름 · 없는 계정) 목록은 비고 개수는 모두 0이다.
    """
    account_id: str
    cancelled_requests: list[str] = field(default_factory=list)   # 대기 → 취소한 시작 요청 ID
    aborted_runs: list[str] = field(default_factory=list)         # 바로 중단한 실행 건 ID
    deleted_runs: int = 0                                         # 지운 실행 건 줄 수
    deleted_requests: int = 0                                     # 지운 시작 요청 줄 수
    stats_rows: int = 0                                           # 쓴 통계 줄 수 (실행 + 시작요청)


@dataclass
class ReworkAccepted:
    """request_rework_for_project 결과 (확장) — 접수만 하고 바로 돌아온다. 진행 · 결과는 진행 상태 · 재작성 결과로 본다.

    cycle_id: 모으는 재작성 ID. 같은 화면에서 collect_until 전에 들어온 요청은 같은 cycle_id로 합쳐진다.
    bundles: 지금까지 모인 묶음(요청 순서). duplicate: 이미 모은 묶음이라 한 번으로 쳤다(기회를 더 쓰지 않음).
    """
    project_id: str | None
    run_id: str
    cycle_id: str
    screen: int
    bundles: list[str]
    collect_until: datetime
    duplicate: bool = False


@dataclass
class ConfirmationNeeded:
    """미달 상태로 검수에 들어가거나 실행을 중단할 때 확인받을 내용."""
    reason: str
    items: dict[str, Any]


@dataclass
class RunView:
    """실행 건 진행 상태 (view_project · project_views · wait_project 안). 사용자용이라 실패 사유는 싣지 않는다.

    확장(spec 4.1): retry_count · resume_count · next_resume_at · last_error_kind(실행 건 값 그대로),
    rework_screen(재작성 중인 화면), collecting(재작성 요청을 모으는 중), announcement_id(선택 공고).
    """
    run_id: str
    step: str
    progress: str
    screen_status: str
    resume_step: int
    percent: int
    current_label: str | None
    notices: list[Notice]
    notifications: list[Notification]
    retry_count: int = 0
    resume_count: int = 0
    next_resume_at: datetime | None = None
    last_error_kind: str | None = None
    rework_screen: int | None = None
    collecting: bool = False
    announcement_id: str | None = None


class SBrainOrchestrator:
    def __init__(
        self,
        *,
        engine: Engine,
        flow: SBrainFlow,
        settings: SettingsProvider,
        profile_count: Callable[[str], int],
        project_inputs: ProjectInputSource | None = None,
        now: Callable[[], datetime] = utc_now,
        new_id: Callable[[], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        allow_pre_stage: bool = True,
        files: FileStore | None = None,
    ) -> None:
        self.engine = engine
        # 파일 읽기(read_artifact_file)가 쓰는 저장소 (확장) — 주지 않으면 엔진의 것. 웹 조립은 읽기 전용 저장소이거나
        # 없음(SBRAIN_ARTIFACT_ROOT 없음 → FILE_STORE_UNAVAILABLE)
        self.files = files if files is not None else engine.files
        self.flow = flow
        self.store = engine.store
        self.settings = settings
        self.profile_count = profile_count
        self.project_inputs = project_inputs
        self.now = utc_clock(now)   # 시간대 있는 UTC (시간대 없는 시계는 UTC로 본다)
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:12])
        self.sleep = sleep                       # wait_project가 다시 읽기 전에 쉰다 (테스트는 시계를 움직이는 함수)
        self.allow_pre_stage = allow_pre_stage   # 거짓이면(웹 조립) 사전 단계를 돌지 않는다 — WEB_NOT_ALLOWED
        self.rework_collect_sec = REWORK_COLLECT_SEC
        self.rework_lease_retry_sec = REWORK_LEASE_RETRY_SEC

    # ── 진행 ─────────────────────────────────────────
    def advance(self, run_id: str) -> str:
        return self.engine.advance(run_id)

    def tick(self, now: datetime | None = None) -> list[str]:
        """now의 시간대가 없으면 UTC로 본다."""
        return self.engine.tick(as_utc(now))

    # ── 사전 정보 제출 → 공고 후보 ─────────────────────
    def request_start(self, account_id: str, project_id: int | str) -> StartCheck:
        """웹 요청 안에서 부른다 (바로 끝남). 웹이 저장한 사전 정보(create_project)를 DB에서 읽어 확인하고
        시작 요청을 '대기'로 넣는다. 사전 단계는 워커가 run_start_request로 돈다.

        ① 입력 읽기 · 주인 확인 — 없거나 다른 계정이면 CommandError("PROJECT_NOT_FOUND")
        ② 필수 항목 — 비어 있으면 T-C1을 실행하지 않고 E-C1-REQUIRED (폼 단계 차단의 재확인)
        ③ 프로필 — E-AUTH-PROFILE
        ④ 동시 실행 — 계정 잠금 안에서 진행 중 실행 건 또는 대기 · 처리중 요청이 있으면 E-RUN-CONCURRENT
        이미 실행 건이 있는 프로젝트(끝난 것 포함)는 CommandError("PROJECT_ALREADY_STARTED") — 새로 시작은 새 프로젝트로.
        """
        if self.project_inputs is None:
            raise CommandError("NO_PROJECT_SOURCE")
        record = self.project_inputs.load(project_id)
        if record is None or str(record.company.user_id) != str(account_id):
            raise CommandError("PROJECT_NOT_FOUND", str(project_id))
        try:
            form = to_pre_input(record)
        except MissingRequired as e:
            return StartCheck(False, code="E-C1-REQUIRED", missing=list(e.labels),
                              message=message("E-C1-REQUIRED", **{"누락 항목": ", ".join(e.labels)}))
        return self._request(account_id, form, str(project_id))

    def run_start_request(self, request_id: str, owner: str | None = None,
                          lease_sec: float | None = None) -> StartStatus:
        """워커가 부른다. 요청을 점유하고 사전 단계(R-8? → T-C1 → T-C2)를 돈다.

        후보가 1건 이상이면 실행 건 생성과 요청 '완료'(+run_id)를 한 트랜잭션으로 저장한다.
        아니면 요청 '실패'와 코드(E-C1-TIMEOUT · X-C2-FAIL · E-C2-STALE · E-C2-NOMATCH · E-RUN-CONCURRENT).
        실행 건을 만들기 직전에 취소 요청이 있으면 '취소'로 끝내고 만들지 않는다.
        다른 곳이 처리 중이거나 이미 끝난 요청이면 아무것도 하지 않고 지금 상태를 돌려준다.
        웹 조립에서 부르면 요청을 점유하거나 바꾸지 않고 바로 CommandError("WEB_NOT_ALLOWED").
        """
        self._require_pre_stage(request_id)
        owner = owner or f"start-{self.new_id()}"
        if not self.store.acquire_start_request(request_id, owner, lease_sec or self.engine.lease_sec):
            return self._start_status(self.store.get_start_request(request_id))
        req = self.store.get_start_request(request_id)
        if req.cancel_requested:
            self.store.finish_start_request(request_id, owner, status="취소")
            return self._start_status(self.store.get_start_request(request_id))
        if req.claim_count > MAX_START_CLAIMS:
            # 워커가 처리 도중 여러 번 멈춘 요청 — 다시 돌지 않고 다시 시도 안내로 끝낸다 (잠정)
            self.store.finish_start_request(request_id, owner, status="실패", code="E-C1-TIMEOUT",
                                            message=message("E-C1-TIMEOUT"), detail={"reason": "가져간 횟수 초과"})
            return self._start_status(self.store.get_start_request(request_id))
        form = PreInput.model_validate(req.form)
        now = self.now()
        run = Run(run_id=self.new_id(), account_id=req.account_id, state=make_state("공고선택", "실행"),
                  current_phase="setup", settings_snapshot=self.settings.snapshot(),
                  updated_at=now, created_at=now, project_id=req.project_id)
        ctx = self.engine.open_context(run, provisional=True)
        ctx.put("formInput", form, producer="user:start")
        run.queue = (["R-8"] if form.attachments else []) + ["T-C1", "T-C2"]
        run.segment, run.segment_total = "PRE", len(run.queue)
        last = self.engine.drain(ctx)
        code = None
        if last is not None:
            # 아직 실행 건이 없으므로 재개하지 않고 진입 전 상태로 되돌린다 (E-C1-TIMEOUT)
            code = "X-C2-FAIL" if last.record and last.record.task_id == "T-C2" else "E-C1-TIMEOUT"
        elif ctx.get("collectionStatus") != "정상":
            code = "E-C2-STALE"
        elif not ctx.get("candidates"):
            code = "E-C2-NOMATCH"
        # 실행 건이 없으니 실행 실패 안내(E-RUN-FAIL)는 빼고 요청 코드로 안내한다
        notices = [n for n in run.notices if n.code != "E-RUN-FAIL"]
        if code is not None:
            self.store.finish_start_request(request_id, owner, status="실패", code=code, message=message(code),
                                            notices=notices)
        elif self.store.create_run_for_request(ctx.run, ctx.take_provisional(), request_id, owner) == "동시실행":
            active = self.store.find_active_run(req.account_id)
            work = self._active_work(active) if active is not None else None
            self.store.finish_start_request(
                request_id, owner, status="실패", code="E-RUN-CONCURRENT", message=message("E-RUN-CONCURRENT"),
                detail={"active": asdict(work)} if work else None, notices=notices)
        return self._start_status(self.store.get_start_request(request_id))

    def start_status(self, project_id: int | str) -> StartStatus | None:
        """웹이 조회한다. 그 프로젝트의 마지막 시작 요청 상태 (없으면 None)."""
        req = self.store.latest_start_request(project_id)
        return self._start_status(req) if req is not None else None

    def start_run_for_project(self, account_id: str, project_id: int | str) -> StartResult:
        """동기 경로 (테스트 · 시연용) — request_start와 run_start_request를 차례로 부른다. 웹 조립은 WEB_NOT_ALLOWED."""
        self._require_pre_stage(str(project_id))
        return self._run_now(self.request_start(account_id, project_id))

    def start_run(self, account_id: str, form: PreInput, *, project_id: str | None = None) -> StartResult:
        """동기 경로 (테스트 · 시연용) — 폼을 직접 받아 확인(③ · ④)과 사전 단계를 차례로 한다. 웹 조립은 WEB_NOT_ALLOWED."""
        self._require_pre_stage(str(project_id))
        return self._run_now(self._request(account_id, form, project_id))

    def _require_pre_stage(self, what: str) -> None:
        """웹 조립에서는 사전 단계를 돌지 않는다 — 요청을 넣거나 점유하기 전에 거절한다 (spec 3.4)."""
        if not self.allow_pre_stage:
            raise CommandError("WEB_NOT_ALLOWED", f"사전 단계는 워커가 돈다 ({what})")

    def _request(self, account_id: str, form: PreInput, project_id: str | None) -> StartCheck:
        if project_id is not None:
            started = self.store.find_run_by_project(project_id)
            if started is not None and started.state.progress not in ACTIVE_PROGRESS:
                raise CommandError("PROJECT_ALREADY_STARTED", started.run_id)
        if self.profile_count(account_id) <= 0:
            return StartCheck(False, code="E-AUTH-PROFILE", message=message("E-AUTH-PROFILE"))
        now = self.now()
        req = StartRequest(request_id=self.new_id(), project_id=project_id, account_id=account_id, status="대기",
                           form=form.dump(), created_at=now, updated_at=now)
        blocker = self.store.add_start_request(req)
        if blocker is not None:
            return StartCheck(False, code="E-RUN-CONCURRENT", message=message("E-RUN-CONCURRENT"),
                              active=self._active_work(blocker))
        return StartCheck(True, request_id=req.request_id)

    def _run_now(self, check: StartCheck) -> StartResult:
        if not check.ok:
            return StartResult(False, code=check.code, message=check.message,
                               active_run_id=check.active.run_id if check.active else None)
        st = self.run_start_request(check.request_id)
        if st.status != "완료":
            return StartResult(False, code=st.code, message=st.message, notices=st.notices,
                               active_run_id=st.active.run_id if st.active else None)
        return StartResult(True, run_id=st.run_id, notices=st.notices)

    def active_work(self, account_id: str) -> ActiveWork | None:
        """웹이 사전 정보를 저장하기 전에 부르는 동시 실행 확인 (확장). 진행 중인 작업이 없으면 None.

        세는 기준은 request_start와 같다 — 진행 중 · 확인 필요 실행 건(먼저), 대기 · 처리중 시작 요청. 잠금 없이 읽으므로
        최종 확인은 request_start가 계정 잠금 안에서 다시 한다.
        """
        blocker = self.store.find_active_work(account_id)
        return self._active_work(blocker) if blocker is not None else None

    @staticmethod
    def _active_work(blocker: Run | StartRequest) -> ActiveWork:
        if isinstance(blocker, Run):
            return ActiveWork(project_id=blocker.project_id, run_id=blocker.run_id, step=blocker.state.step,
                              resume_step=blocker.state.resume_step, screen_status=blocker.state.screen_status)
        return ActiveWork(project_id=blocker.project_id, request_id=blocker.request_id)

    @staticmethod
    def _start_status(req: StartRequest) -> StartStatus:
        active = (req.result_detail or {}).get("active")
        return StartStatus(request_id=req.request_id, status=req.status, code=req.result_code,
                           message=req.result_message, notices=list(req.notices), run_id=req.run_id,
                           active=ActiveWork(**active) if active else None)

    # ── 화면 3 · 4 · 5 ────────────────────────────────
    def more_candidates(self, run_id: str) -> None:
        """공고 추가 조회 — 공고선택 · 사용자대기, 자격 통과 뒤 작성 시작 전(계획서작성 · 사용자대기)에도 받는다(3.3).

        끝나면 공고선택 · 사용자대기로 돌아간다. 작성을 시작한 뒤에는 INVALID_STATE (워커 점유 중이어도 BUSY 아님).
        한도(1회 · 합계 20건)는 유효한 추가 조회만 센다 — 실패한 추가 조회(어떤 오류 · 수집 상태 비정상)는 기회를 돌려받고
        한도에도 세지 않는다(spec 4.2.3). decision에 조회 전 T-C2 출력 버전을 남겨 실패하면 흐름이 그리로 돌린다.
        """
        def act(ctx: RunContext) -> None:
            first, more = candidate_lists(ctx)
            if ctx.run.more_used or len(first) + len(more) >= CANDIDATE_LIMIT:
                raise CommandError("MORE_LIMIT", "추가 조회는 1회, 최대 20건")
            self._decide(ctx, {"command": "more", "offset": 10,
                               MORE_BEFORE_POINTERS: self.flow.more_lookup_pointers(ctx)})
            ctx.run.more_used = True
            self._enqueue(ctx, ["T-C2"], "MORE", "공고선택")
        self._command(run_id, ANNOUNCEMENT_STEPS, act)

    def select_announcement(self, run_id: str, announcement_id: str) -> None:
        """공고 선택 — 고른 공고 ID와 고르기 전 대기 지점만 남기고 G-01을 넣는다 (spec 4.3.1).

        - 후보(첫 · 추가 조회)에 없는 공고는 INVALID_ANNOUNCEMENT, 그다음 막힌 공고(자격 불통과)는 ANNOUNCEMENT_BLOCKED.
          거절하면 실행 건을 바꾸지 않는다.
        - 선택 공고를 만들지 않고 Run.announcement_id도 바꾸지 않는다. 공고 상세와 자격 판정은 워커의 G-01이 함께 받아
          한 번에 저장하고, 그때 announcement_id가 바뀐다. G-01이 실패하면 decision의 beforeStep으로 돌아간다.
        - 자격 통과 뒤 작성 시작 전(계획서작성 · 사용자대기)에도 같은 처리로 다시 고를 수 있다(3.3). 작성 시작 뒤에는
          INVALID_STATE — 워커가 점유 중이어도 점유를 기다리지 않고 상태로 거절한다(BUSY 아님).
        """
        def act(ctx: RunContext) -> None:
            first, more = candidate_lists(ctx)   # 첫 조회 + 유효한 추가 조회 (실패한 추가 조회의 카드는 고를 수 없다)
            ids = {card.announcement_id for card in first + more}
            if announcement_id not in ids:
                raise CommandError("INVALID_ANNOUNCEMENT", announcement_id)
            if announcement_id in ctx.run.blocked_announcement_ids:
                raise CommandError("ANNOUNCEMENT_BLOCKED", announcement_id)
            self._decide(ctx, {"command": "select", "announcementId": announcement_id,
                               "beforeStep": ctx.run.state.step})
            self._enqueue(ctx, ["G-01"], "GATE", "자격확인")
        self._command(run_id, ANNOUNCEMENT_STEPS, act)

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
        """화면 6 · 8 · 9 '진행' · '재작성'.

        '재작성'은 묶음 요청(request_rework_for_project)과 같은 기준이다(spec 3.2): 산출물층 지시는 그 Task의 묶음
        이름 요청으로 바꿔 처리하고, 문서층 지시는 거절한다(INVALID_ORDER — 문서층은 묶음 이름으로 요청). 웹은 이 경로를
        쓰지 않는다.
        """
        if screen not in SCREEN_STEP:
            raise CommandError("INVALID_SCREEN", str(screen))
        if action == "재작성":
            self._request_rework(run_id, self._order_bundle_names(selected_orders or []), expect_screen=screen)
            return None
        result: list[ConfirmationNeeded] = []

        def act(ctx: RunContext) -> None:
            if action == "진행":
                self._proceed(ctx, screen, confirmed, result)
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

    # ── 재작성 요청 (묶음 이름, 확장 — spec 3.2) ──────────
    def request_rework_for_project(self, project_id: int | str, bundle: str) -> ReworkAccepted:
        """웹 재작성 요청 — 고른 묶음마다 한 번씩 부른다. 받기만 하고 바로 돌아온다(접수 결과).

        - 화면은 실행 건 상태로 정한다: 문서평가 · 사용자대기 → 6, 산출물확인 · 사용자대기 → 8, 종합평가 · 사용자대기 → 9.
          같은 화면에서 모으는 중이면 그 화면으로 받는다.
        - 같은 화면에서 첫 요청부터 모으는 시간(잠정 2초) 안에 들어온 요청은 재작성 한 번으로 합친다. 모으는 동안 실행 건은
          '실행'(화면 '진행 중')이라 '진행' 명령은 받지 않고, 워커는 시간이 지난 뒤 가져가 진행한다.
        - 요청을 받는 순간 그 묶음의 기회를 쓴다. 이미 모은 묶음을 또 요청하면 한 번으로 친다(duplicate).
        오류: RUN_NOT_FOUND · INVALID_STATE(대기 지점이 아님 · 모으는 시간이 끝남 · 진행 중 — 점유를 기다리지 않음) ·
        INVALID_ORDER(표에 없는 이름 · 화면에 맞지 않는 층 · 원페이지 실행 파일) · E-G2-LIMIT(남은 기회 없음) ·
        BUSY(모으는 중 · 대기 지점에서 다른 명령과 점유가 겹쳐 재시도 시간 안에 못 잡음).
        """
        return self._request_rework(self._run_of(project_id), [bundle])

    def _request_rework(self, run_id: str, bundles: list[str], expect_screen: int | None = None) -> ReworkAccepted:
        # 상태는 점유를 잡기 전에 확인한다 — 워커가 진행하며 점유하고 있으면 기다리지 않고 바로 INVALID_STATE
        self._rework_screen(self.store.load_run(run_id), bundles, expect_screen)
        owner = f"cmd-{self.new_id()}"
        self._acquire_for_rework(run_id, owner, bundles, expect_screen)
        try:
            run = self.store.load_run(run_id)
            screen = self._rework_screen(run, bundles, expect_screen)
            ctx = RunContext(self.store, run, owner, self.engine.types, self.now, self.engine.immutable_keys)
            return self._accept_rework(ctx, screen, bundles)
        finally:
            self.store.release(run_id, owner)

    def _acquire_for_rework(self, run_id: str, owner: str, bundles: list[str], expect_screen: int | None) -> None:
        """동시에 들어온 요청이 서로 막히지 않도록 점유를 짧게(잠정 최대 5초) 다시 시도한다. 그래도 못 잡으면 BUSY."""
        deadline = time.monotonic() + self.rework_lease_retry_sec
        while not self.store.acquire(run_id, owner, COMMAND_LEASE_SEC):
            # 기다리는 사이 상태가 바뀌었으면(모으는 시간이 끝남 · 워커가 가져감) 더 기다리지 않고 거절한다
            self._rework_screen(self.store.load_run(run_id), bundles, expect_screen)
            if time.monotonic() >= deadline:
                raise CommandError("BUSY", run_id)
            time.sleep(REWORK_LEASE_RETRY_INTERVAL_SEC)

    def _rework_screen(self, run: Run, bundles: list[str], expect_screen: int | None) -> int:
        """재작성을 받을 화면 — 대기 지점이거나 같은 화면에서 모으는 중일 때만. 묶음 이름 · 층도 확인한다."""
        if run.state.progress == "사용자대기" and run.state.step in STEP_SCREEN:
            screen = STEP_SCREEN[run.state.step]
        elif collecting(run, self.now()):
            assert run.cycle is not None
            screen = run.cycle.screen
        else:
            raise CommandError("INVALID_STATE", f"{run.state.step}/{run.state.progress}")
        if expect_screen is not None and screen != expect_screen:
            raise CommandError("INVALID_STATE", f"화면 {expect_screen} — 지금 {run.state.step}/{run.state.progress}")
        for b in bundles:
            layer = BUNDLE_LAYER.get(b)
            if layer is None:
                raise CommandError("INVALID_ORDER", f"묶음 이름이 아님: {b}")
            if screen not in LAYER_SCREENS[layer]:
                raise CommandError("INVALID_ORDER", f"화면 {screen}은 {b} 묶음을 받지 않음")
        return screen

    def _accept_rework(self, ctx: RunContext, screen: int, bundles: list[str]) -> ReworkAccepted:
        """명령 점유 안에서 접수를 한 번에 저장한다: 기회 차감 · 사용자 명령 기록 · 사이클 열기(또는 더하기) · 대기열."""
        run = ctx.run
        category = ctx.get("category", default=None)
        if category == "원페이지" and BUNDLE_EXECUTABLE in bundles:
            raise CommandError("INVALID_ORDER", "원페이지는 실행 파일(T-B1)이 없음")
        cycle = run.cycle   # 있으면 모으는 중 (_rework_screen이 확인했다)
        collected = list(cycle.counted_bundles) if cycle is not None else []
        new = [b for b in dict.fromkeys(bundles) if b not in collected]
        if not new:   # 이미 모으는 중인 묶음 — 한 번으로 친다 (기회를 더 쓰지 않음)
            assert cycle is not None and cycle.collect_until is not None
            return ReworkAccepted(run.project_id, run.run_id, cycle.cycle_id, screen, collected, cycle.collect_until,
                                  duplicate=True)
        remaining = {u.bundle_id: u.remaining for u in run.rework_usage}
        per_bundle = ctx.settings.rework.per_bundle   # 실행 시작 때 고정한 상한
        for b in new:
            if remaining.get(b, per_bundle) <= 0:
                raise CommandError("E-G2-LIMIT", b)
        merged = collected + new
        judge = "G-02a" if screen == 6 else "G-02b"
        offered = ctx.get(f"{judge}.reworkOrders", default=[])
        # 문서층 묶음은 그 묶음 항목의 종류별 Task만 다시 만든다 — 양식(T-C3 formSpec)과 짝짓기 표로 가른다 (spec 4.11)
        orders = bundle_orders(merged, offered, ctx.get(FORM_SPEC, default=None))
        dref = self._decide(ctx, {
            "command": "rework", "screen": screen, "action": "재작성", "userAction": "재작성",
            "requested": new, "bundles": merged, "selectedOrders": [o.dump() for o in orders.values()],
            "sourceRefs": [ctx.ref(f"{judge}.reworkOrders")] if ctx.has(f"{judge}.reworkOrders") else [],
        })
        by_task = {t: o.dump() for t, o in orders.items()}
        counted = [(b, BUNDLE_LAYER[b]) for b in new]
        layers = sorted({BUNDLE_LAYER[b] for b in merged})
        if cycle is None:
            cycle = self.engine.start_cycle(
                ctx, screen=screen, selected_orders_ref=dref, orders_by_task=by_task, counted_bundles=counted,
                layers=layers, collect_until=self.now() + timedelta(seconds=self.rework_collect_sec))
        else:
            self.engine.extend_cycle(ctx, selected_orders_ref=dref, orders_by_task=by_task,
                                     counted_bundles=counted, layers=layers)
        queue = rework_queue(screen, list(orders.values()), category)   # 묶음들의 합집합, 기준 문서 순서
        run.queue = queue
        run.segment, run.segment_total = f"REWORK{screen}", len(queue)
        run.state = make_state(SCREEN_STEP[screen], "실행", screen)    # 화면 '진행 중', 복귀 화면 = 요청한 화면
        ctx.commit()
        assert cycle.collect_until is not None
        return ReworkAccepted(run.project_id, run.run_id, cycle.cycle_id, screen, list(cycle.counted_bundles),
                              cycle.collect_until)

    @staticmethod
    def _order_bundle_names(selected: list[ReworkOrder]) -> list[str]:
        """기존 decide 재작성 — 산출물층 지시를 그 Task의 묶음 이름으로. 문서층 지시는 INVALID_ORDER."""
        if not selected:
            raise CommandError("NO_SELECTION")
        names: list[str] = []
        for o in selected:
            if o.layer == "document":
                raise CommandError("INVALID_ORDER", "문서층은 묶음 이름으로 요청한다 (request_rework_for_project)")
            name = TASK_BUNDLE.get(o.task_id, o.task_id)
            if name not in names:
                names.append(name)
        return names

    # ── 중단 ─────────────────────────────────────────
    def abort(self, run_id: str, confirmed: bool = False) -> ConfirmationNeeded | None:
        if not confirmed:
            return ConfirmationNeeded("중단 확인", {"안내": "중단하면 지금까지의 결과를 다시 볼 수 없습니다"})
        if self.store.is_locked(run_id, self.now()):
            self.store.request_abort(run_id)  # 진행 중이면 Task 사이에서 반영한다
            return None
        owner = f"cmd-{self.new_id()}"
        if not self.store.acquire(run_id, owner, COMMAND_LEASE_SEC):
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

    # ── project_id로 중단 · 완전 삭제 (확장) ────────────
    def abort_project(self, project_id: int | str) -> AbortResult:
        """프로젝트 중단 (웹 DELETE /projects/{id} — 웹이 사용자 확인을 이미 받았다).

        ① 대기 중 시작 요청 → 취소 ② 처리 중 시작 요청 → 취소 요청(워커가 실행 건을 만들기 직전에 확인)
        ③ 진행 중 실행 건 → abort(confirmed=True). 워커가 단계를 도는 중이면 중단 요청으로 남고 단계 사이에 반영된다.
        이미 끝난 실행 건은 그대로 둔다. 요청을 먼저 보고 실행 건을 나중에 봐서, 그 사이에 생긴 실행 건도 중단한다.
        """
        result = AbortResult(str(project_id))
        for req in self.store.pending_start_requests(project_id):
            outcome = self.store.cancel_start_request(req.request_id)
            if outcome == "취소":
                result.cancelled_requests.append(req.request_id)
            elif outcome == "취소요청":
                result.cancel_requested.append(req.request_id)
        run = self.store.find_run_by_project(project_id)
        if run is None:
            return result
        result.run_id = run.run_id
        if run.state.progress not in ACTIVE_PROGRESS:
            result.run_action = "이미끝남"
            return result
        try:
            self.abort(run.run_id, confirmed=True)
        except CommandError as e:
            if e.code != "NOT_ACTIVE":
                raise
        after = self.store.load_run(run.run_id).state.progress
        result.run_action = "중단요청" if after in ACTIVE_PROGRESS else ("중단" if after == "중단" else "이미끝남")
        return result

    def delete_project_data(self, project_id: int | str) -> DeleteResult:
        """완전 삭제(웹 DELETE /projects/{id}/permanent)용 — 산출물 내용과 입력 사본을 지우고 실행 로그는 남긴다.

        지우는 것: 산출물 버전 · 현재 버전 포인터(입력 사본 formInput, 첨부 추출 텍스트, 계획서 등), 시작 요청의 입력 사본.
        남기는 것: 실행 건 상태 · 실행 기록 · 호출 기록 · 추적 사건 (기획서 6-7, 실행 로그 12개월 보관).
        진행 중이면 먼저 중단한다. 워커가 단계를 도는 중이면(중단 요청만 남음) 지우지 않고 CommandError("BUSY") —
        그 단계가 끝나며 저장하는 산출물이 지운 뒤에 남지 않게 하려는 것이다. 단계가 끝나면 다시 부른다.
        웹은 이 함수 뒤에 projects 행을 지운다(실행 건의 project_id는 비워지고 실행 로그는 남는다).
        """
        abort = self.abort_project(project_id)
        if abort.run_action == "중단요청":
            raise CommandError("BUSY", f"{abort.run_id} 단계 진행 중 — 중단 요청을 남겼다. 단계가 끝난 뒤 다시 부른다")
        result = DeleteResult(str(project_id), abort, run_id=abort.run_id)
        if abort.run_id is not None:
            self.store.delete_artifacts(abort.run_id)
            result.deleted_artifacts = True
        result.cleared_forms = self.store.clear_start_request_forms(project_id)
        return result

    # ── 탈퇴 (확장) ─────────────────────────────────────
    def delete_account_data(self, account_id: str) -> AccountDeleteResult:
        """탈퇴용 — 그 계정의 orch_ 데이터를 식별자 없는 통계 줄(reason '탈퇴')로 옮긴 뒤 모두 지운다.

        웹 순서: 프로젝트마다 abort_project → delete_project_data → 모두 끝나면 이 함수 → 웹 행 삭제.
        ① 계정 잠금(add_start_request와 같은 잠금)을 끝날 때까지 쥔다 — 그동안 그 계정의 시작 요청이 새로 들어오지 않는다.
        ② 대기 시작 요청 → 취소, 처리중 요청 → 취소 요청.
        ③ 진행 중 실행 건(실행 · 재개대기 · 사용자대기) → 중단. 워커가 단계를 도는 중이면 중단 요청만 남는다.
        ④ ② · ③에서 처리중 요청이나 단계를 도는 실행 건이 있으면 아무것도 지우지 않고 CommandError("BUSY")
           (중단 · 취소 요청은 남는다. 웹은 웹 행을 지우지 않고 잠시 뒤 다시 부른다).
        ⑤ 모든 실행 건(끝난 것 · 완전 삭제된 것 포함)마다 점유를 잡고 한 트랜잭션으로: 옮길 기록이 있으면 실행 줄을 쓰고
           산출물 버전 · 포인터 · 여섯 기록 표 · 실행 건 줄을 지운다(완전 삭제를 빠뜨려 남은 산출물도). 점유를 못 잡으면
           BUSY — 이미 처리한 실행 건은 지워진 채로 두고, 다시 부르면 남은 것부터 한다.
        ⑥ 모든 시작 요청(끝난 것)을 시작요청 줄로 세고 같은 트랜잭션에서 지운다.
        여러 번 불러도 안전하다(남은 것이 없으면 모두 0). 웹 표는 건드리지 않고 단계를 돌지 않는다. 계정 주인 확인은
        하지 않는다(웹이 로그인 계정임을 확인한 뒤 부른다). 오류는 BUSY 하나이고 메시지에 식별자를 싣지 않는다.
        """
        account_id = str(account_id)
        result = AccountDeleteResult(account_id)
        try:
            with self.store.account_guard(account_id):
                # 이 안에서 같은 계정의 add_start_request · create_run · create_run_for_request를 부르지 않는다
                # (MySQL은 다른 연결이라 자기 잠금을 기다린다). 중단 · 취소 · 기록 옮기기는 계정 잠금을 잡지 않는다.
                self._withdraw_stop(account_id, result)
                for run in self.store.list_runs(account_id):
                    rows = self._withdraw_run(run.run_id)
                    if rows is not None:
                        result.stats_rows += rows
                        result.deleted_runs += 1
                requests = self.store.list_start_requests(account_id)
                if any(r.status not in FINISHED_REQUEST for r in requests):
                    raise CommandError("BUSY", "탈퇴 — 끝나지 않은 시작 요청이 있다. 잠시 뒤 다시 부른다")
                if requests:
                    rows = start_request_rows(requests, WITHDRAW_REASON)
                    result.deleted_requests = self.store.retire_start_requests([r.request_id for r in requests], rows)
                    result.stats_rows += len(rows)
        except StoreConflict:
            # 계정 잠금 대기 시간 초과 · 점유를 잃음 · 다른 곳이 먼저 지움 — 식별자 없이 BUSY로 바꾼다
            raise CommandError("BUSY", "탈퇴 — 계정 잠금 또는 점유를 얻지 못했다. 잠시 뒤 다시 부른다") from None
        return result

    def _withdraw_stop(self, account_id: str, result: AccountDeleteResult) -> None:
        """② · ③ · ④ — 시작 요청을 먼저 보고 실행 건을 나중에 본다. 아직 처리 중인 것이 남으면 BUSY(지우기 전)."""
        busy = False
        for req in self.store.list_start_requests(account_id):
            if req.status not in PENDING_REQUEST:
                continue
            outcome = self.store.cancel_start_request(req.request_id)
            if outcome == "취소":
                result.cancelled_requests.append(req.request_id)
            elif outcome == "취소요청":
                busy = True
        for run in self.store.list_runs(account_id):
            if run.state.progress not in ACTIVE_PROGRESS:
                continue
            try:
                self.abort(run.run_id, confirmed=True)
            except CommandError as e:
                if e.code != "NOT_ACTIVE":
                    raise
            after = self.store.load_run(run.run_id).state.progress
            if after in ACTIVE_PROGRESS:
                busy = True              # 워커가 단계를 도는 중 — 중단 요청만 남았다
            elif after == "중단":
                result.aborted_runs.append(run.run_id)
        if busy:
            raise CommandError("BUSY", "탈퇴 — 단계 진행 중이거나 처리 중인 시작 요청이 있다. 중단 · 취소 요청을 남겼다")

    def _withdraw_run(self, run_id: str) -> int | None:
        """⑤ 실행 건 하나 — 점유를 잡고 통계 줄(옮길 기록이 있을 때) · 산출물 · 기록 · 실행 건 줄을 한 트랜잭션으로 지운다.

        쓴 통계 줄 수(0 또는 1). 그사이 다른 곳이 먼저 지웠으면 None. 점유를 못 잡거나 다시 진행 중이면 BUSY.
        """
        owner = f"withdraw-{self.new_id()}"
        if not self.store.acquire(run_id, owner, COMMAND_LEASE_SEC):
            try:
                self.store.load_run(run_id)   # SQL 저장소는 없는 실행 건의 점유를 잡지 못한다 — 남아 있는지 본다
            except KeyError:
                return None   # 다른 곳(보관 기간 작업)이 먼저 지웠다 — KeyError에는 실행 건 ID가 있어 올리지 않는다
            raise CommandError("BUSY", "탈퇴 — 실행 건 점유를 얻지 못했다. 잠시 뒤 다시 부른다")
        try:
            try:
                run = self.store.load_run(run_id)
            except KeyError:
                return None   # 다른 곳(보관 기간 작업)이 먼저 지웠다 — KeyError에는 실행 건 ID가 있어 올리지 않는다
            if run.state.progress in ACTIVE_PROGRESS:
                raise CommandError("BUSY", "탈퇴 — 아직 진행 중인 실행 건이 있다. 잠시 뒤 다시 부른다")
            row = gather_run_stats(self.store, run, reason=WITHDRAW_REASON)
            self.store.retire_run(run_id, owner, stats=row, delete_run=True)
            return 0 if row is None else 1
        finally:
            self.store.release(run_id, owner)   # 지웠으면 할 일 없음

    # ── 화면 상태 · 이어하기 ───────────────────────────
    def view(self, run_id: str) -> RunView:
        return self._view(self.store.load_run(run_id))

    def _view(self, run: Run) -> RunView:
        notices = list(run.notices)
        if run.state.progress in ACTIVE_PROGRESS and run.announcement_id:
            # 마감 안내 (spec 4.5) — 마감일이 지났거나(비어 있으면 보지 않음, 오늘은 한국 날짜), G-01이 상세를 받을 때
            # 모집 상태가 '마감'. 알리기만 하고 진행을 막지 않는다
            ctx = self.engine.open_context(run)
            ann = ctx.get("selectedAnnouncement", default=None)
            if ann is not None and ((ann.apply_end is not None and ann.apply_end < kst_today(self.now()))
                                    or ann.status == "마감"):
                notices.append(Notice(code="E-RUN-CLOSED", message=message("E-RUN-CLOSED"), at=self.now()))
        percent = progress_percent(run)
        current = run.queue[0] if run.queue else None
        label = None
        if current:
            label = STEP_LABEL.get(current) or self.engine.registry.get(current).name
        return RunView(run_id=run.run_id, step=run.state.step, progress=run.state.progress,
                       screen_status=run.state.screen_status, resume_step=run.state.resume_step,
                       percent=percent, current_label=label, notices=notices,
                       notifications=self.store.notifications(run.run_id),
                       retry_count=run.retry_count, resume_count=run.resume_count, next_resume_at=run.next_resume_at,
                       last_error_kind=run.last_error_kind, rework_screen=run.rework_screen,
                       collecting=collecting(run, self.now()), announcement_id=run.announcement_id)

    # ── 웹 명령 (project_id로 받는다, 확장) ─────────────
    # 웹은 project_id만 안다. 안에서 실행 건을 찾아 run_id 명령을 부른다. 실행 건이 없으면 RUN_NOT_FOUND.
    def more_candidates_for_project(self, project_id: int | str) -> None:
        self.more_candidates(self._run_of(project_id))

    def select_announcement_for_project(self, project_id: int | str, announcement_id: str) -> None:
        self.select_announcement(self._run_of(project_id), announcement_id)

    def start_writing_for_project(self, project_id: int | str) -> None:
        self.start_writing(self._run_of(project_id))

    def decide_for_project(self, project_id: int | str, screen: int, action: str,
                           selected_orders: list[ReworkOrder] | None = None,
                           confirmed: bool = False) -> ConfirmationNeeded | None:
        return self.decide(self._run_of(project_id), screen, action, selected_orders, confirmed)

    def _run_of(self, project_id: int | str) -> str:
        run = self.store.find_run_by_project(project_id)
        if run is None:
            raise CommandError("RUN_NOT_FOUND", str(project_id))
        return run.run_id

    # ── 웹 조회 (project_id로 받는다, 확장) ─────────────
    def view_project(self, project_id: int | str) -> ProjectView:
        """지금의 view() + 실행 건이 없으면 시작 요청 상태. 둘 다 없으면 run · start가 모두 None."""
        run = self.store.find_run_by_project(project_id)
        if run is not None:
            return ProjectView(str(project_id), run=self._view(run))
        return ProjectView(str(project_id), start=self.start_status(project_id))

    def project_views(self, project_ids: Iterable[int | str]) -> list[ProjectView]:
        """여러 프로젝트의 view_project를 한 번에 (확장) — 넘긴 순서대로. 실행 건 · 마지막 시작 요청은 한 번씩 모아 읽는다."""
        ids = [str(p) for p in project_ids]
        if not ids:
            return []
        runs = {r.project_id: r for r in self.store.query_runs(RunFilter(project_ids=tuple(ids), limit=None))}
        missing = [p for p in ids if p not in runs]
        reqs = self.store.latest_start_requests(missing) if missing else {}
        return [ProjectView(p, run=self._view(runs[p])) if p in runs else
                ProjectView(p, start=self._start_status(reqs[p]) if p in reqs else None) for p in ids]

    def missing_projects(self, project_ids: Iterable[int | str]) -> list[int | str]:
        """넘긴 프로젝트 중 실행 건이 없는 것 (확장) — 웹이 목록에서 실행 건이 없어진 프로젝트를 알아내는 데 쓴다.

        '없음' = 실행 건 줄을 project_id로 찾지 못하고(find_run_by_project와 같은 기준) 끝나지 않은(대기 · 처리중) 시작
        요청도 없음. 시작한 적 없는 프로젝트, 끝난(실패 · 취소) 요청만 있는 프로젝트도 없음이다. 완전 삭제
        (delete_project_data)만으로는 실행 건 줄과 project_id가 남아 '있음'이고, 웹이 projects 행을 지워 공유 DB 외래 키가
        project_id를 비운 뒤부터 '없음'이다. 12개월 처리가 실행 건 줄을 지운 뒤 · 탈퇴(delete_account_data) 뒤에도 '없음'.

        각 값은 정수 또는 숫자 문자열이다 — int()로 한 번 바꾸고, 하나라도 숫자가 아니면 저장소를 읽기 전에 ValueError.
        같은 정수는 한 프로젝트로 보고(7 · "7" · "07") 처음 나온 값을 받은 그대로(int는 int, 문자열은 문자열) 넘긴 순서로
        돌려준다. 빈 목록이면 []. 개수 제한은 없다. 잠금 · 점유 없이 읽기만 하고, 주인 확인을 하지 않으며(계정 ID를 받지
        않는 웹 일괄 함수) 있는지만 알린다. 저장소 오류는 다른 조회처럼 그대로 올라간다.
        """
        wanted: dict[int, int | str] = {}
        for no, value in enumerate(project_ids, 1):
            try:
                key = int(value)
            except (TypeError, ValueError):
                # 값은 메시지에 싣지 않는다 — 몇 번째 값인지만
                raise ValueError(f"project_ids의 {no}번째 값이 정수 또는 숫자 문자열이 아님") from None
            wanted.setdefault(key, value)
        if not wanted:
            return []
        existing = self.store.existing_projects(list(wanted))
        return [value for key, value in wanted.items() if key not in existing]

    def wait_project(self, project_id: int | str, timeout_sec: float = WAIT_TIMEOUT_SEC) -> ProjectView:
        """진행이 멈출 때까지 기다린 뒤 view_project (확장).

        멈춤 = 마지막 시작 요청이 대기 · 처리중이 아니고, 실행 건이 '실행'(재작성 요청을 모으는 중 포함)이 아님.
        재개대기 · 사용자대기 · 끝난 상태면 기다리지 않고 바로 준다. 제한 시간(잠정 기본 60초)을 넘기면 그때의 상태를
        그대로 준다(오류 아님). DB를 잠정 0.5초마다 다시 읽고, 다시 읽는 횟수도 제한 시간 / 간격을 넘지 않는다.
        """
        timeout_sec = max(float(timeout_sec), 0.0)
        deadline = self.now() + timedelta(seconds=timeout_sec)
        for _ in range(max(1, math.ceil(timeout_sec / WAIT_POLL_SEC))):
            if self._settled(project_id) or self.now() >= deadline:
                break
            self.sleep(WAIT_POLL_SEC)
        return self.view_project(project_id)

    def _settled(self, project_id: int | str) -> bool:
        req = self.store.latest_start_request(project_id)
        if req is not None and req.status in PENDING_REQUEST:
            return False
        run = self.store.find_run_by_project(project_id)
        return run is None or run.state.progress != "실행"

    def screen(self, project_id: int | str, screen: int) -> reads.Screen:
        """화면별 내용 (모양은 초안, flow/reads.py). 대기 지점이 아니면 CommandError("SCREEN_NOT_READY")."""
        return reads.screen(self, project_id, screen)

    def outputs(self, project_id: int | str) -> reads.Outputs:
        """지금까지 만든 결과(현재 버전) (확장, flow/reads.py). 실패 · 중단이면 RUN_NOT_VIEWABLE, 실행 건 없으면 RUN_NOT_FOUND."""
        return reads.outputs(self, project_id)

    def rework_result(self, project_id: int | str) -> reads.ReworkResult | None:
        """마지막 재작성 한 건 (확장, flow/reads.py). 재작성한 적 없으면 None. 실패 · 중단 RUN_NOT_VIEWABLE, 없으면 RUN_NOT_FOUND."""
        return reads.rework_result(self, project_id)

    def read_artifact_file(self, project_id: int | str, key: str) -> reads.ArtifactFile:
        """산출물 파일 하나의 내용 · 형식 (확장, flow/reads.py). 웹이 주인 확인을 한 뒤 부른다.

        실행 건 없으면 RUN_NOT_FOUND, 실패 · 중단이면 RUN_NOT_VIEWABLE, 파일 저장소 설정이 없으면 FILE_STORE_UNAVAILABLE,
        그 실행 건의 파일이 아니거나 · 키 규칙 위반 · 없음 · 내용이 저장 값과 다르면 FILE_NOT_FOUND. 읽기만 한다(점유 없음)."""
        return reads.read_artifact_file(self, project_id, key)

    def admin_file_deletions(self, status: str | None = None, limit: int = 50,
                             offset: int = 0) -> list[reads.AdminFileDeletion]:
        """관리자 — 파일 삭제 대기열 목록 (확장). 넣은 시각 최근 순, status로 '대기' · '포기'를 거른다."""
        return reads.admin_file_deletions(self, status=status, limit=limit, offset=offset)

    def admin_retry_file_deletion(self, deletion_id: str, admin_id: str) -> reads.AdminFileDeletion:
        """관리자 — '포기'한 파일 삭제 대기열 줄을 다시 시도 (확장). 누른 관리자 · 시각을 줄에 남긴다.

        없는 줄이면 FILE_DELETION_NOT_FOUND, '대기' 줄이면 INVALID_STATE. 결과는 바뀐 줄."""
        return reads.admin_retry_file_deletion(self, deletion_id, admin_id)

    def admin_executions(self, **filters: Any) -> list[reads.AdminExecution]:
        """관리자 '에이전트 테스크' — 여러 프로젝트의 실행 기록 (메타데이터만). 조건은 reads.admin_executions."""
        return reads.admin_executions(self, **filters)

    def admin_calls(self, execution_id: str) -> list[reads.AdminCall]:
        """관리자 — 실행 하나의 호출 기록 (시도별 결과 · 오류 종류 · 토큰)."""
        return reads.admin_calls(self, execution_id)

    def admin_runs(self, *, progress: str | None = None, step: str | None = None, limit: int = 50,
                   offset: int = 0) -> list[reads.AdminRun]:
        """관리자 — 여러 프로젝트의 실행 건 목록 (메타데이터 · 점수만, 마지막 갱신 최근 순)."""
        return reads.admin_runs(self, progress=progress, step=step, limit=limit, offset=offset)

    def admin_score_history(self, project_id: int | str) -> reads.AdminScoreHistory:
        """관리자 — 층별(문서층 · 코드 점검 · 계획서 대조) 채점 이력. 실행 건 없으면 RUN_NOT_FOUND."""
        return reads.admin_score_history(self, project_id)

    def admin_summary(self) -> reads.AdminSummary:
        """관리자 — 운영 요약 (개수 · 점수 · 토큰). 정의는 reads.admin_summary."""
        return reads.admin_summary(self)

    def admin_agent_tasks(self) -> list[reads.AdminAgentTask]:
        """관리자 — Agent별 등록된 Task 수 · 실행 기록 수 · 가장 최근 실행."""
        return reads.admin_agent_tasks(self)

    # ── 도움 함수 ─────────────────────────────────────
    def _command(self, run_id: str, expect_step: str | tuple[str, ...], act: Callable[[RunContext], None]) -> None:
        """대기 지점 명령 — expect_step(하나 또는 여럿) · 사용자대기일 때만 받는다. 아니면 INVALID_STATE.

        점유를 잡기 전에 상태를 확인한다 — 워커가 단계를 도는 중이거나 재작성을 모으는 중이라 받을 수 없는 상태면 BUSY가
        아니라 바로 INVALID_STATE다. 점유를 못 잡으면 상태를 다시 읽어, 그사이 받을 수 없는 상태가 됐으면 INVALID_STATE,
        아니면 BUSY다(받을 수 있는 상태에서 다른 명령과 점유가 겹칠 때만). 점유를 잡은 뒤에도 다시 확인한다.
        """
        steps = (expect_step,) if isinstance(expect_step, str) else expect_step
        self._check_waiting(self.store.load_run(run_id), steps)
        owner = f"cmd-{self.new_id()}"
        if not self.store.acquire(run_id, owner, COMMAND_LEASE_SEC):
            self._check_waiting(self.store.load_run(run_id), steps)
            raise CommandError("BUSY", run_id)
        try:
            run = self.store.load_run(run_id)
            self._check_waiting(run, steps)
            ctx = RunContext(self.store, run, owner, self.engine.types, self.now, self.engine.immutable_keys)
            act(ctx)
            ctx.commit()
        finally:
            self.store.release(run_id, owner)

    @staticmethod
    def _check_waiting(run: Run, steps: tuple[str, ...]) -> None:
        if run.state.step not in steps or run.state.progress != "사용자대기":
            raise CommandError("INVALID_STATE", f"{run.state.step}/{run.state.progress}")

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
