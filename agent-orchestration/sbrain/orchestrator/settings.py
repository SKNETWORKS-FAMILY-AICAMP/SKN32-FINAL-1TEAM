"""설정값 — 기능정의서 시트 1 '횟수 · 간격 설정값' 표와 층별 배점 · Threshold, Task별 호출 설정.

- 실행을 시작할 때 전체를 Run.settingsSnapshot에 고정해 끝까지 쓴다.
- PROVISIONAL에 있는 항목은 기준 문서가 값을 정하지 않아 임시로 둔 값이다(잠정).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..models.base import SBModel, ext


class RetrySettings(SBModel):
    retry_count: int = 5                 # 재시도 횟수
    retry_interval_sec: float = 2.0      # 재시도 간격 (잠정)


class ResumeSettings(SBModel):
    first_interval_min: float = 15       # 재개 첫 간격
    multiplier: float = 2                # 재개 간격 배수
    max_count: int = 5                   # 재개 횟수
    total_cap_hours: float = 12          # 재개 총 대기 상한


class RedoSettings(SBModel):
    redo_count: int = 2                  # 재수행 횟수
    proofread_redo_count: int | None = None  # 검수 재수행 횟수. None이면 재수행 횟수와 같음

    @property
    def proofread_limit(self) -> int:
        return self.redo_count if self.proofread_redo_count is None else self.proofread_redo_count


class ReworkSettings(SBModel):
    per_bundle: int = 1                  # 재작성 횟수 (묶음마다)


class ProofreadSettings(SBModel):
    concurrency: int = 4                         # 검수 동시 처리 수 (잠정)
    failure_ratio_threshold: float = 0.3         # 검수 실패 비율 기준 (잠정)
    judge_timing: Literal["전체후"] = "전체후"    # 판단 시점: 모든 문장을 본 뒤 (잠정)


class ScoringSettings(SBModel):
    threshold: float = 80
    doc_layer_max: float = 70
    artifact_layer_max: float = 30
    deviation_cap: float | None = ext(None, note="문서층 재채점 편차 상한 — 웹 verification_policies 값을 담아만 둔다 (검증-1 연동 전)")


# 추론 강도 — OpenAI 추론 모델의 reasoning_effort 값 (모델마다 받는 값이 다르다)
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class AgentSetting(SBModel):
    """옛 Agent 등록부 값 — 옛 설정 사본(Settings.agents)을 읽을 때만 쓴다. 새 실행 건은 Task별 설정(TaskModelSetting)이다.

    temperature가 None이면 호출에 싣지 않는다. 추론 모델은 온도 대신 추론 강도(reasoning_effort, 확장)를 쓴다.
    """
    provider: str
    model: str
    temperature: float | None
    reasoning_effort: ReasoningEffort | None = None


class TaskModelSetting(SBModel):
    """Task별 호출 설정 — 관리자 설정값(기획서 5-2). 키는 Task ID와 '지시문 다시 쓰기'다.

    - temperature가 None이면 호출에 싣지 않는다. reasoning_effort(확장)도 None이면 싣지 않는다(모델 기본값).
    - 이미지 설정(확장): image_model이 None이면 그 Task는 이미지 호출을 쓸 수 없다.
      image_quality · image_size는 이미지 호출이 값을 받지 않았을 때의 기본값이다.
    """
    provider: str
    model: str
    temperature: float | None
    reasoning_effort: ReasoningEffort | None = ext(None, note="추론 강도 — None이면 호출에 싣지 않는다")
    image_provider: str | None = ext(None, note="이미지 호출처")
    image_model: str | None = ext(None, note="이미지 모델 — None이면 이 Task는 이미지 호출을 쓸 수 없다")
    image_quality: str | None = ext(None, note="이미지 품질 기본값")
    image_size: str | None = ext(None, note="이미지 크기 기본값")


# 재작성 · 재수행 때 조율이 대상 Task의 지시문 안내 부분을 다시 쓰는 호출의 설정 키 (Task가 아니다, 결정 0013).
# 흐름이 tools_for(Agent 이름, 이 키)로 넘긴다. 엔진은 이 이름을 모른다
REWRITE_SETTING_KEY = "지시문 다시 쓰기"


def _default_tasks() -> dict[str, TaskModelSetting]:
    # 모델명 · 호출처 · 기본 온도 · 추론 강도는 기준 문서가 정하지 않았다 (잠정).
    # 옛 Agent별 값을 그 Agent의 Task에 옮겼다. 조율은 OpenAI, 검수는 자체 GPU 서버의 파인튜닝 모델(기획서 5-2 · 5-7).
    # 조율 모델은 사용자 지정(2026-09-30): gpt-6-luna, 추론 강도 low. 추론 모델이라 온도를 보내지 않는다.
    # T-B1 · T-B2 · T-V2는 구현 · 검증-2 담당 요청: gpt-6-luna, 추론 강도 기본값(보내지 않음), 온도 보내지 않음.
    # T-B2 이미지: openai · gpt-image-2.5-flare · medium · 1024x1536 (담당 요청).
    def supervisor() -> TaskModelSetting:
        return TaskModelSetting(provider="openai", model="gpt-6-luna", temperature=None, reasoning_effort="low")

    def undecided(temperature: float) -> TaskModelSetting:
        return TaskModelSetting(provider="미정", model="미정", temperature=temperature)

    def luna() -> TaskModelSetting:
        return TaskModelSetting(provider="openai", model="gpt-6-luna", temperature=None)

    tasks: dict[str, TaskModelSetting] = {k: supervisor() for k in ("T-C1", "T-C2", "G-01", "T-C3")}
    tasks.update({k: undecided(0.7) for k in ("T-S1", "T-S2", "T-W1", "T-W2", "T-W3")})
    tasks["T-V1"] = undecided(0.0)
    tasks["T-B1"] = luna()
    tasks["T-B2"] = luna().model_copy(update={
        "image_provider": "openai", "image_model": "gpt-image-2.5-flare",
        "image_quality": "medium", "image_size": "1024x1536"})
    tasks["T-V2"] = luna()
    tasks.update({k: TaskModelSetting(provider="gpu-server", model="미정", temperature=0.2) for k in ("T-P1", "T-P2")})
    tasks["T-C4"] = supervisor()
    tasks[REWRITE_SETTING_KEY] = supervisor()
    return tasks


def _default_timeouts() -> dict[str, float]:
    # 제한 시간 (Task별, 초). 기준 문서: '구현하면서 정함' (잠정)
    base = {tid: 120.0 for tid in (
        "T-C1", "T-C3", "T-S1", "T-S2", "T-W2", "T-W3", "T-V1", "T-V2", "T-P1", "T-C4",
    )}
    base.update({"T-W1": 300.0, "T-B1": 300.0, "T-B2": 300.0, "T-C2": 30.0, "T-P2": 60.0})
    base["G-01"] = 30.0   # 공고 서버 상세 · 판정 호출 — T-C2와 같음 (잠정)
    base[REWRITE_SETTING_KEY] = 120.0   # 지시문 다시 쓰기 호출 한 번 (잠정) — T-C3 값을 빌리지 않는다
    base["T-B2.image"] = 120.0          # T-B2 이미지 호출 한 번 (잠정 · 조정 가능, 실측 13 ~ 16초)
    return base


class Settings(SBModel):
    retry: RetrySettings = Field(default_factory=RetrySettings)
    resume: ResumeSettings = Field(default_factory=ResumeSettings)
    redo: RedoSettings = Field(default_factory=RedoSettings)
    rework: ReworkSettings = Field(default_factory=ReworkSettings)
    proofread: ProofreadSettings = Field(default_factory=ProofreadSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    task_timeouts: dict[str, float] = Field(default_factory=_default_timeouts)
    # Task별 호출 설정. 옛 설정 사본(agents만 있음)을 읽으면 None이다 — 새 기본값으로 채우지 않는다
    tasks: dict[str, TaskModelSetting] | None = Field(default_factory=_default_tasks)
    # 옛 설정 사본의 Agent별 설정 — 읽기 전용. 새 설정 · 새 사본에는 없다(None이면 저장하지 않는다)
    agents: dict[str, AgentSetting] | None = ext(None, note="옛 설정 사본의 Agent별 설정 — tasks가 None일 때만 쓴다")

    @model_validator(mode="before")
    @classmethod
    def _legacy_snapshot(cls, data: Any) -> Any:
        """옛 설정 사본(원본에 tasks 없이 agents만)이면 tasks를 None으로 둔다 — 사본에 적힌 Agent 값 그대로 쓴다."""
        if isinstance(data, dict) and "tasks" not in data and "agents" in data:
            return {**data, "tasks": None}
        return data

    def dump(self) -> dict[str, Any]:
        """None인 tasks · agents는 빼고 저장한다 (새 사본에는 agents가 없고, 옛 사본은 다시 읽어도 옛 사본이다)."""
        exclude = {k for k in ("tasks", "agents") if getattr(self, k) is None}
        return self.model_dump(mode="json", by_alias=True, exclude=exclude)


# 가산점 사용 스위치 (잠정, PROVISIONAL announcement.bonusEnabled) — 실행별 설정(Settings)이 아닌 코드 상수다.
# 실제 T-C2(agents/notice/tc2.py) · 스텁 T-C2(agents/stubs.py) · 웹 조회(flow/reads.py)가 부를 때마다
# settings.BONUS_ENABLED로 읽는다(from-import로 값을 복사하지 않는다 — 테스트가 바꾼 값이 모든 곳에 닿게).
# 꺼져 있으면 가산점을 읽지 · 만들지 · 보이지 않는다. 공고팀이 써도 된다고 하면 이 한 곳만 True로 바꾼다.
BONUS_ENABLED: bool = False


# 기준 문서가 값을 정하지 않아 임시로 둔 항목 (문서 · 화면에 '잠정'으로 표시)
PROVISIONAL: dict[str, str] = {
    "retry.retryIntervalSec": "재시도 간격 — 구현하면서 정함",
    "taskTimeouts": "제한 시간(Task별) — 구현하면서 정함",
    "proofread.concurrency": "검수 동시 처리 수 — 구현하면서 정함",
    "proofread.failureRatioThreshold": "검수 실패 비율 기준 — 구현하면서 정함",
    "proofread.judgeTiming": "검수 실패 비율 판단 시점 — 구현하면서 정함",
    "tasks": "Task별 모델 · 호출처 · 기본 온도 · 추론 강도 · 이미지 설정, 실행 시작 시점 고정 — 기준 문서에 없음 "
             "(조율 Task · 지시문 다시 쓰기 gpt-6-luna · low는 사용자 지정, T-B1 · T-B2 · T-V2 gpt-6-luna(추론 강도 · "
             "온도 보내지 않음)와 T-B2 이미지 openai · gpt-image-2.5-flare · medium · 1024x1536은 구현 · 검증-2 담당 요청, "
             "나머지는 미정). 옛 설정 사본(agents만)은 그 Agent 값 그대로 쓴다",
    f"taskTimeouts.{REWRITE_SETTING_KEY}": "지시문 다시 쓰기 호출 한 번의 제한 시간 120초 — T-C3 값을 빌려 쓰던 것을 따로 둠",
    "taskTimeouts.T-B2.image": "T-B2 이미지 호출 한 번의 제한 시간 120초 — 조정 가능(실측 13 ~ 16초)",
    "scoring.deviationCap": "문서층 재채점 편차 상한 (확장) — 웹 verification_policies.deviation_cap을 담아만 둔다. "
                            "검증-1 연동 전이라 쓰는 곳 없음",
    # 산출물층 검증 · 이미지 관리자 사건 종류 (flow/sbrain_flow.py) — 기준 문서에 없음. 추적 사건으로 남는다(관리자에게 보일 방식 · 조회 함수는 웹팀 결정)
    "event.대조보류": "T-V2 대조 판정 보류(withheld) — 'T-V2 대조 판정 보류 (<보류 사유>) — 0점 합산'. 관리자 알림 표시 방식은 웹팀 몫",
    "event.검증2진단": "T-V2 진단(diagnostics) 한 줄마다 하나 — 관리자 진단 전용, 흐름 제어에 쓰지 않음",
    "event.안내문서자체검사실패": "G-04 자체 검사가 재수행 횟수를 다 쓰고도 불통과 — 기록만 하고 계속 (점수 밖, T-C4 전달을 막지 않음)",
    "event.대체텍스트출처누락": "T-V2 HTML 2번(대체 텍스트) 미충족인데 defect_sources가 비어 있음 — 재작성 사유는 v1.9 매핑대로 "
                               "T-B2로 보내고 기록한다 (담당자는 늘 채운다고 함, 대비용)",
    "event.이미지대체": "T-B2 실행 기록에 최종 실패인 이미지 호출이 있음 — 'T-B2 이미지 호출 실패 — 기본 아이콘으로 계속'. "
                       "사용자 화면에는 알리지 않는다",
    # 공고 연결 (공고 선택 · 자격 확인 G-01) — 기준 문서에 없음
    "taskTimeouts.G-01": "G-01 제한 시간 30초 — 공고 서버의 공고 상세 · 자격 판정 호출, T-C2와 같음",
    "announcement.unknownStatus": "공고 서버 모집 상태가 모름(unknown 등)이면 선택 공고 status를 '모집중'으로 둔다 — "
                                  "그래서 마감 안내(E-RUN-CLOSED)가 붙지 않는다",
    "announcement.bonusEnabled": "가산점 사용 스위치 BONUS_ENABLED 기본 꺼짐 — 공고팀 가산점은 시험 단계(2026-10-06 답변: "
                                 "화면에 쓰지 말 것). 꺼져 있으면 실제 T-C2는 추천 결과의 bonus_score · bonus_items를 "
                                 "읽지도 검사하지도 않고, 스텁은 가산점을 만들지 않으며, 웹 카드(화면 3 · 결과 조회)는 저장된 "
                                 "옛 실행 건까지 늘 bonusScore null · bonusItems []. 공고팀이 정리해 써도 된다고 하면 이 한 곳만 켠다",
    "announcement.formSpec": "선택 공고의 양식 필드(formSpec · evaluationItems)는 자리 표시 값(기본 양식 1-1 · 2-1 · 3-3) — "
                             "뒷 단계는 읽지 않고 작업 분해(T-C3)가 고른 양식 · 평가 항목 · 채점 기준표를 쓴다",
    # 작업 분해 (T-C3, agents/form_defaults.py · agents/supervisor/plan.py) — 실행 건 설정값이 아니라 코드 표다
    "taskPlan.formTable": "신청자 유형별 양식 · 평가 항목 · 채점 기준표 — 예비창업자 '예비창업패키지(잠정)', 개인사업자 · 법인 "
                          "'초기창업패키지-일반형(잠정)'. 섹션은 웹 계획서 태그와 같은 1-1 · 2-1 · 3-1 · 4-1, 평가 항목 · "
                          "채점 기준표는 기본값(문서층 70점 · rubric-stub@stub-1). 담당자 회신 뒤 이 표만 바꾼다",
    "taskPlan.referenceSlots": "참조 조각 대응표(Task → 받는 슬롯) — T-S1 문제 · 필요성 · 목표 고객 · 핵심 기능, T-S2 시장 규모 · "
                               "목표 고객 · 경쟁 · 차별성, T-W1 7개 전부, T-W2 시장 규모 · 수익 모델, T-W3 수익 모델 · 추진 계획, "
                               "T-B1 핵심 기능, T-B2 문제 · 필요성 · 핵심 기능 · 시장 규모 · 수익 모델 · 추진 계획",
    "notice.X-C2-GONE": "공고 없음 안내(확장) 문구 '선택하신 공고를 더 이상 확인할 수 없습니다. 다른 공고를 선택해주세요.'",
    # 공고 서버 연결 (agents/notice) — 실행 건 설정값이 아니라 워커 프로세스 값 · 고정 문장이다
    "announcement.matchReason": "추천 이유 문장 틀 (spec 4.1.4) — 공고 서버의 band(매우 적합 · 적합 · 참고, 없으면 대체 경로 "
                                "'마감임박순'일 때 '마감이 가까운 신청 가능 공고입니다')와 지역(전국 · 희망 지역 일치 · 불일치)으로 "
                                "정해진 문장을 ' · '로 잇는다. AI를 부르지 않는다",
    "noticeServer.serialCalls": "공고 서버 호출을 워커 프로세스 안에서 한 번에 하나씩 보낸다(네 API 모두, 프로세스 공용 잠금). "
                                "프로세스끼리는 막지 않으므로 운영 워커는 1대 — 공고팀이 동시 호출 안전성을 확인하기 전까지",
    # 워커 (sbrain/worker.py · flow/service.py) — 실행 건 설정값이 아니라 워커 프로세스 값이다
    "worker.pollSec": "할 일이 없을 때 쉬는 시간 1초 (SBRAIN_WORKER_POLL_SEC)",
    "worker.threads": "워커 스레드 4 (SBRAIN_WORKER_THREADS)",
    "worker.leaseSec": "점유 시간 120초 (SBRAIN_WORKER_LEASE_SEC) — 워커가 멈추면 이만큼 뒤에 다른 워커가 이어받는다",
    "worker.heartbeatSec": "하트비트 30초 — 점유 시간의 1/4",
    "worker.maxStartClaims": "시작 요청을 가져간 횟수 상한 3 — 넘으면 E-C1-TIMEOUT으로 끝낸다",
    "worker.errorBackoff": "단계 밖 오류 뒤 그 실행 건을 점유 시간만큼 다시 가져가지 않는다",
    # 워커 운영 로그 (orchestrator/runlog.py · sbrain/worker_log.py) — 워커 프로세스 값이다
    "workerLog.actions": "운영 로그 동작 · 키 이름 — 단계시작(run · project · step · exec · trigger · resumed · attempt) · "
                         "단계끝(run · project · step · exec · status · sec · model · tokens · imageTokens · errorKind · "
                         "error) · 대기(run · project · point) · 실행끝(run · project · status) · 재개예약(run · project · "
                         "at · errorKind). 운영하면서 바꿀 수 있다 (orchestrator/runlog.py)",
    "workerLog.errorMax": "단계끝 error 값 길이 상한 200자 (orchestrator/runlog.py ERROR_MAX)",
    "workerLog.maxBytes": "로그 파일 하나의 상한 20MB — 넘게 되면 다음 순번 파일 (sbrain/worker_log.py MAX_BYTES)",
    "workerLog.lockFile": "폴더 하나에 워커 하나 — 폴더 안 worker.lock OS 배타 잠금, 못 잡으면 화면에만 "
                          "(sbrain/worker_log.py LOCK_FILE)",
    "workerLog.writeFailure": "로그 파일 쓰기 실패 안내는 실패가 이어지는 동안 한 번만, 다음 줄부터 다시 파일에 쓰기를 시도한다",
    # 실행 로그 보관 기간 작업 (flow/retention.py · sbrain/worker.py) — 워커 프로세스 값이다
    "retention.batchSize": "보관 기간 작업이 한 번에 가져오는 실행 건 · 시작 요청 수 100 (flow/retention.py BATCH_SIZE)",
    "retention.intervalSec": "보관 기간 작업 간격 24시간 — 마지막으로 끝까지 마친 뒤 이만큼 지나야 다시 시작한다 "
                             "(flow/retention.py INTERVAL_SEC)",
    "retention.checkSec": "워커가 보관 기간 작업을 돌 때인지 확인하는 주기 10분 (sbrain/worker.py JOB_CHECK_SEC)",
    "retention.leaseSec": "보관 기간 작업 점유 시간 = 워커 점유 시간(120초), 하트비트(30초)가 연장한다 — 워커가 멈추면 "
                          "이만큼 뒤에 다른 워커가 이어받는다",
    # 저장소 (orchestrator/store.py) — 메모리 · SQL 저장소가 함께 쓴다
    "store.accountLockTimeoutSec": "계정 잠금 대기 10초 — 넘기면 StoreConflict (orchestrator/store.py "
                                   "ACCOUNT_LOCK_TIMEOUT_SEC)",
    # 재작성 요청 (flow/service.py) — 실행 건 설정값이 아니라 명령 창구 값이다
    "reworkRequest.collectSec": "재작성 요청을 모으는 시간 2초 — 같은 화면에서 첫 요청부터 이 시간 안의 요청을 "
                                "재작성 한 번으로 합친다. 그동안 워커는 그 실행 건을 가져가지 않는다",
    "reworkRequest.leaseRetrySec": "재작성 요청의 점유 재시도 최대 5초 — 그래도 못 잡으면 BUSY",
    # 진행 기다리기 (flow/service.py wait_project) — 명령 창구 값이다
    "waitProject.timeoutSec": "wait_project 기본 제한 시간 60초 — 넘기면 그때의 진행 상태를 그대로 준다",
    "waitProject.pollSec": "wait_project가 DB를 다시 읽는 간격 0.5초",
}


class SettingsProvider:
    """관리자 설정값 공급처. 실행 시작 때 snapshot()으로 고정한다."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def current(self) -> Settings:
        return self._settings

    def update(self, settings: Settings) -> None:
        self._settings = settings

    def snapshot(self) -> dict:
        return self._settings.dump()
