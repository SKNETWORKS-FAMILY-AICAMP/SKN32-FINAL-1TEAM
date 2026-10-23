"""설정값 — 기능정의서 시트 1 '횟수 · 간격 설정값' 표와 층별 배점 · Threshold, Task별 호출 설정.

- 실행을 시작할 때 전체를 Run.settingsSnapshot에 고정해 끝까지 쓴다.
- PROVISIONAL에 있는 항목은 기준 문서가 값을 정하지 않아 임시로 둔 값이다(잠정).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..models.base import SBModel, ext


def _default_wait_caps() -> dict[str, float]:
    # 설정 키별 한 호출의 재시도 대기 합 상한 — T-C1은 사용자가 화면 앞에서 기다리고 재개하지 않는 단계라 45초(시트 1 재시도 간격).
    # 엔진은 설정 키로 찾기만 한다(제한 시간 task_timeouts와 같은 방식) — Task ID는 여기에만 둔다
    return {"T-C1": 45.0}


class RetrySettings(SBModel):
    retry_count: int = 5                 # 재시도 횟수
    retry_interval_sec: float = 2.0      # 재시도 간격 — 2초부터
    # 일시 오류의 늘리는 간격 · 무작위 지연 · Retry-After · 대기 합 상한 (시트 1 '재시도 간격'). 이 칸이 없는 옛 설정 사본은
    # 기본값으로 읽는다. n번째 재시도 전 대기 = retry_interval_sec × backoff_multiplier^(n−1) × (1 + 무작위[0, jitter_ratio]) —
    # 형식 오류 · 파일 창구 · 늘리지 않게 표시한 검색 호출(공고 서버)은 retry_interval_sec 고정
    backoff_multiplier: float = 2.0      # 늘리는 간격의 배수
    jitter_ratio: float = 0.25           # 무작위 지연 비율 — 계산 값 × [0, 비율]을 더함
    retry_after_cap_sec: float = 60.0    # Retry-After를 따를 때의 대기 상한
    wait_cap_sec: float = 90.0           # 한 호출의 재시도 대기 합 기본 상한 — 넘게 되면 남은 재시도 없이 소진
    wait_cap_by_key: dict[str, float] = Field(default_factory=_default_wait_caps)   # 설정 키별 대기 합 상한 — 없는 키는 waitCapSec


class ResumeSettings(SBModel):
    first_interval_min: float = 15       # 재개 첫 간격
    multiplier: float = 2                # 재개 간격 배수
    max_count: int = 5                   # 재개 횟수
    total_cap_hours: float = 12          # 재개 총 대기 상한


class RedoSettings(SBModel):
    redo_count: int = 2                  # 재수행 횟수
    proofread_redo_count: int | None = None  # 검수 재수행 횟수. None이면 재수행 횟수와 같음
    # 검증-1 재수행 횟수 — 기준 문서 시트 1 '항목마다 1회'. 항목마다 · 사이클마다 센다. 웹 관리자 칸이 없어 코드 기본값으로만
    # 둔다 (잠정, PROVISIONAL redo.verify1RedoCount). 이 칸이 없는 옛 설정 사본은 1로 읽는다
    verify1_redo_count: int = 1

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
    # 산출물층 두 항목의 배점(층별 배점 — 코드 점검 · 계획서 대조) — 검증-2 원점수(코드 점검 0 ~ 15 · 계획서 대조 0 ~ 15)를
    # 이 배점으로 환산한다. 웹 verification_policies.code_weight · plan_weight. 산출물층 배점(artifact_layer_max)은 둘의 합으로
    # 읽는다. 이 칸이 없는 옛 설정 사본은 15 · 15로 읽는다. 환산 · 판정은 artifact_layer_max를 읽지 않고 C + P를 쓴다
    # (flow/score_scale.py) — artifact_layer_max는 웹 설정을 읽을 때(DbSettingsProvider) C + P로 맞춰 두는 표시용 칸이다
    code_check_max: float = 15       # 코드 점검 배점 C — 웹 verification_policies.code_weight
    feature_match_max: float = 15    # 계획서 대조 배점 P — 웹 verification_policies.plan_weight


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
    # 호출 목적별 모델 (확장) — tools.llm(purpose=p)는 p가 여기 있으면 그 모델로, 없으면 model로 부른다.
    # 호출처 · 온도 · 추론 강도 · 제한 시간 · 재시도는 이 항목 그대로다. 엔진은 목적 이름을 모르고 사전을 그대로 옮긴다
    purpose_models: dict[str, str] = ext(
        default_factory=dict, note="호출 목적 → 모델 이름 — 없는 목적은 Task 모델. 이 칸이 없는 옛 사본은 빈 사전")


# 재작성 · 재수행 때 조율이 대상 Task의 지시문 안내 부분을 다시 쓰는 호출의 설정 키 (Task가 아니다).
# 흐름이 tools_for(Agent 이름, 이 키)로 넘긴다. 엔진은 이 이름을 모른다
REWRITE_SETTING_KEY = "지시문 다시 쓰기"


def _default_tasks() -> dict[str, TaskModelSetting]:
    # 모델명 · 호출처 · 기본 온도 · 추론 강도는 기준 문서가 정하지 않았다 (잠정).
    # 옛 Agent별 값을 그 Agent의 Task에 옮겼다. 조율은 OpenAI, 검수는 자체 GPU 서버의 파인튜닝 모델(기획서 5-2 · 5-7).
    # 조율 모델(2026-09-30): gpt-6-luna, 추론 강도 low. 추론 모델이라 온도를 보내지 않는다.
    # T-C1만 추론 강도 medium. T-C1 안의 모든 호출
    # (분류 · 사양)이 이 항목을 쓴다. T-C3 · 지시문 다시 쓰기는 low 그대로.
    # T-B1 · T-B2 · T-V2는 구현 · 검증-2 담당 요청: gpt-6-luna, 추론 강도 기본값(보내지 않음), 온도 보내지 않음.
    # T-B2 이미지: openai · gpt-image-2.5-flare · medium · 1024x1536 (담당 요청).
    # T-S1 · T-S2 · T-W1 · T-W2 · T-V1은 전략 · 작성 · 검증-1 담당자 execution_contract.json의 apiModel(함수별 모델 —
    # Task 모델 + 목적(F번호)별 모델 purposeModels), 호출처 openai, 온도 · 추론 강도 보내지 않음.
    def supervisor(effort: ReasoningEffort = "low") -> TaskModelSetting:
        return TaskModelSetting(provider="openai", model="gpt-6-luna", temperature=None, reasoning_effort=effort)

    def openai(model: str, purposes: dict[str, str] | None = None) -> TaskModelSetting:
        return TaskModelSetting(provider="openai", model=model, temperature=None, purpose_models=dict(purposes or {}))

    def luna() -> TaskModelSetting:
        return openai("gpt-6-luna")

    # LLM을 부르지 않는 Task(T-C2 · G-01 · T-W3 · T-C4, 등록부 uses_llm=False)는 항목을 두지 않는다 — 엔진이 표를 보지 않는다
    tasks: dict[str, TaskModelSetting] = {"T-C1": supervisor("medium"), "T-C3": supervisor()}
    tasks["T-S1"] = openai("gpt-5.6-terra", {   # Task 모델 = F02
        "F01": "gpt-6-luna", "F05": "gpt-6-luna", "F06": "gpt-5.6-sol", "F07": "gpt-6.1-sol", "F08": "gpt-6.1-sol",
        "F09": "gpt-5.6-terra", "F13": "gpt-6-luna", "F14": "gpt-6-luna", "F15": "gpt-6-luna"})
    tasks["T-S2"] = openai("gpt-6.1-sol", {"F04": "gpt-5.6-terra"})   # Task 모델 = F03 · F10 · F11 · F12
    tasks["T-W1"] = openai("gpt-5.6-sol")      # F16
    tasks["T-W2"] = openai("gpt-6-luna")       # F18
    tasks["T-V1"] = openai("gpt-5.6-terra")    # F19
    tasks["T-B1"] = luna()
    tasks["T-B2"] = luna().model_copy(update={
        "image_provider": "openai", "image_model": "gpt-image-2.5-flare",
        "image_quality": "medium", "image_size": "1024x1536"})
    tasks["T-V2"] = luna()
    tasks.update({k: TaskModelSetting(provider="gpu-server", model="미정", temperature=0.2) for k in ("T-P1", "T-P2")})
    tasks[REWRITE_SETTING_KEY] = supervisor()
    return tasks


def _default_timeouts() -> dict[str, float]:
    # 제한 시간 (호출 한 번, 초) — 시트 1 '제한 시간': 기본 120, 요구사항 분석 · 본문 작성 · 실행 파일 · 인포그래픽 300,
    # 공고 매칭 · 자격 확인 30. 흐름 밖 T-P2(검수, 향후 도입)의 60은 잠정.
    # T-S1(요구사항 분석) 300은 운영에서 F07(gpt-6.1-sol, 성공 40 ~ 78초)이 120초에 걸려
    # 처음부터 다시 보내는 일이 생겨(5번 연속 뒤 마지막 시도에 성공한 실행 건도 있음) 본문 작성과 같은 300으로 둔다.
    base = {tid: 120.0 for tid in (
        "T-C1", "T-C3", "T-S2", "T-W2", "T-W3", "T-V1", "T-V2", "T-P1", "T-C4",
    )}
    base.update({"T-S1": 300.0, "T-W1": 300.0, "T-B1": 300.0, "T-B2": 300.0, "T-C2": 30.0, "T-P2": 60.0})
    base["G-01"] = 30.0   # 공고 서버 상세 · 판정 호출 — T-C2와 같음
    base[REWRITE_SETTING_KEY] = 120.0   # 지시문 다시 쓰기 호출 한 번 — T-C3 값을 빌리지 않는다
    base["T-B2.image"] = 120.0          # T-B2 이미지 호출 한 번 (실측 13 ~ 16초)
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


# 가산점 사용 스위치 — 실행별 설정(Settings)이 아닌 코드 상수다. 켠 값이 기준 문서(시트 4 AnnouncementCard.bonusScore ·
# bonusItems — 원문 대조를 마친 공고만, bonusScore = bonusItems 점수의 합)와 같고, 끄는 것은 되돌리기용이다.
# 실제 T-C2(agents/notice/tc2.py) · 스텁 T-C2(agents/stubs.py) · 웹 조회(flow/reads.py)가 부를 때마다
# settings.BONUS_ENABLED로 읽는다(from-import로 값을 복사하지 않는다 — 테스트가 바꾼 값이 모든 곳에 닿게).
# 꺼져 있으면 가산점을 읽지 · 만들지 · 보이지 않는다. 2026-10-19 공고팀이 써도 된다고 해 켰다 — 켜져 있어도
# 실제 T-C2는 공고 서버가 원문 대조를 마친 공고(bonus_verified 참, 공고팀 결정 0018)의 가산점만 카드에 싣는다(agents/notice/tc2.py).
BONUS_ENABLED: bool = True

# 계획서 표 입력(사업비 · 일정) 필수 확인 스위치 — 실행별 설정이 아닌 코드 상수다. 켠 값이 기준 문서(시트 6 E-C1-REQUIRED —
# 사업비 집행계획 1건 이상, 예비창업자는 1단계 · 2단계 각 1건 이상, 추진 일정은 협약기간 내 1건 이상)와 같고, 끄는 것은 되돌리기용이다.
# 시작 요청의 필수 확인이 부를 때마다 settings.PLAN_TABLES_REQUIRED로 읽는다(from-import로 값을 복사하지 않는다 —
# BONUS_ENABLED와 같은 방식). 꺼져 있으면 사업비 · 일정이 비어도 통과한다. 웹 입력 화면 배포와 함께 2026-10-16 배포부터 켰다
# (웹 REQUIRE_BUDGET_SCHEDULE과 같은 시점 — 웹 마이그레이션 004의 phase 컬럼이 있어야 한다)
PLAN_TABLES_REQUIRED: bool = True


# 기준 문서가 값을 정하지 않아 임시로 둔 항목 (문서 · 화면에 '잠정'으로 표시)
PROVISIONAL: dict[str, str] = {
    "taskTimeouts.T-P2": "T-P2(검수 — 흐름 밖, 향후 도입) 제한 시간 60초 — 검수를 도입할 때 정함",
    "proofread.concurrency": "검수 동시 처리 수 — 구현하면서 정함",
    "proofread.failureRatioThreshold": "검수 실패 비율 기준 — 구현하면서 정함",
    "proofread.judgeTiming": "검수 실패 비율 판단 시점 — 구현하면서 정함",
    "tasks": "Task별 모델 · 호출처 · 기본 온도 · 추론 강도 · 이미지 설정, 실행 시작 시점 고정 — Task별로 두는 것과 두는 범위"
             "(LLM을 부르는 Task마다 — T-C2 · G-01 · T-W3 · T-C4 없음)는 기준 문서(시트 1 · Run.settingsSnapshot)에 있고, "
             "값은 기준 문서에 없음 "
             "(LLM을 부르는 조율 Task · 지시문 다시 쓰기 gpt-6-luna — 추론 강도는 T-C1 medium(모델 비교 테스트로 정함) · "
             "T-C3 · 지시문 다시 쓰기 low, LLM을 부르지 않는 T-C2 · G-01 · T-C4는 "
             "항목 없음, T-B1 · T-B2 · T-V2 gpt-6-luna(추론 강도 · "
             "온도 보내지 않음)와 T-B2 이미지 openai · gpt-image-2.5-flare · medium · 1024x1536은 구현 · 검증-2 담당 요청, "
             "T-S1 · T-S2 · T-W1 · T-W2 · T-V1의 Task 모델과 함수별 모델(purposeModels — 호출 목적 F번호 → 모델, 확장)은 "
             "전략 · 작성 · 검증-1 담당자 execution_contract.json의 apiModel(T-S1 gpt-5.6-terra + F01 · F05 · F13 · F14 · "
             "F15 gpt-6-luna · F06 gpt-5.6-sol · F07 · F08 gpt-6.1-sol · F09 gpt-5.6-terra, T-S2 gpt-6.1-sol + F04 "
             "gpt-5.6-terra, T-W1 gpt-5.6-sol, T-W2 gpt-6-luna, T-V1 gpt-5.6-terra — 호출처 openai, 온도 · 추론 강도 "
             "보내지 않음), T-W3는 LLM을 부르지 않아 항목 없음, T-P1 · T-P2는 미정). purposeModels가 없는 사본 · "
             "옛 설정 사본(agents만)은 빈 사전 · 그 Agent 값 그대로 쓴다",
    "redo.verify1RedoCount": "검증-1 재수행 횟수 1(항목마다 · 사이클마다, 기준 문서 시트 1) — 웹 관리자 칸이 없어 코드 "
                             "기본값으로만 둔다",
    "planTables.unknownSection": "추진 일정 row의 section이 feasibility · growth 밖이면 그 row를 버린다. 사업비 row의 "
                                 "phase가 '1단계' · '2단계' 밖이면 None(단계 미지정)으로 본다 (intake/mapping.py)",
    "planTables.missingLabels": "필수 스위치가 켜졌을 때의 결측 이름 글자 '사업비 집행계획' · '사업비 집행계획(1단계)' · "
                                "'사업비 집행계획(2단계)' · '추진 일정(협약기간 내)' (intake/mapping.py LABELS)",
    "scoring.deviationCap": "문서층 재채점 편차 상한 (확장) — 웹 verification_policies.deviation_cap을 담아만 둔다. "
                            "편차 검사를 하지 않아(varianceFlag 늘 거짓) 쓰는 곳 없음",
    # 산출물층 검증 · 이미지 관리자 사건 종류 (flow/sbrain_flow.py) — 기준 문서에 없음. 추적 사건으로 남는다(관리자에게 보일 방식 · 조회 함수는 웹팀 결정)
    "event.대조보류": "T-V2 대조 판정 보류(withheld) — 'T-V2 대조 판정 보류 (<보류 사유>) — 0점 합산'. 관리자 알림 표시 방식은 웹팀 몫",
    "event.검증2진단": "T-V2 진단(diagnostics) 한 줄마다 하나 — 관리자 진단 전용, 흐름 제어에 쓰지 않음",
    "event.안내문서자체검사실패": "G-04 자체 검사가 재수행 횟수를 다 쓰고도 불통과 — 기록만 하고 계속 (점수 밖, T-C4 전달을 막지 않음)",
    "event.대체텍스트출처누락": "T-V2 HTML 2번(대체 텍스트) 미충족인데 defect_sources가 비어 있음 — 재작성 사유는 v1.9 매핑대로 "
                               "T-B2로 보내고 기록한다 (담당자는 늘 채운다고 함, 대비용)",
    "event.이미지대체": "T-B2가 맞춤 아이콘판을 쓰지 못하고 기본 아이콘으로 대신한 세 경우(이미지 호출 실패 · 칸 수 불일치 · "
                       "그림 해석 오류) — T-B2 실행 기록마다 하나(최종 실패인 이미지 호출이 있거나 출력 iconFallback이 "
                       "참). 설명은 이미지 호출 실패면 'T-B2 이미지 호출 실패 — 기본 아이콘으로 계속', 그 밖(칸 수 불일치 · "
                       "그림 해석 오류)이면 둘째 문구 'T-B2 맞춤 아이콘 사용 불가 — 기본 아이콘으로 계속'. 이미지 호출 실패의 "
                       "마지막 시도에 오류 코드가 있으면 첫째 문구 끝에 ' (code=<코드>)'를 붙인다. 결제 · 한도 코드로 끝난 "
                       "이미지 호출은 기본 아이콘으로 대신하지 않고 다시 올려 재개 대기로 가므로 이 사건이 없다. "
                       "사용자 화면에는 알리지 않는다",
    # 구현 · 검증-2 끼우기 · 산출물층 환산 — 기준 문서에 없음
    "g04.templateText": "G-04 안내 문서(README.md) 템플릿 문구와 빈 슬롯 기본 문구(아이템명 · 공고명이 비었을 때, 진입 파일이 "
                        "없을 때 등) (agents/supervisor/)",
    "scoring.scaledRounding": "산출물층 환산 값의 반올림(소수 둘째 자리, 차이는 한 항목에 — 기준 문서 시트 4 "
                              "ScoreReport.codeCheckItems) 중 정하지 않은 방식 — 0.5 올림(Decimal ROUND_HALF_UP), 몰아줄 "
                              "항목은 해당 항목 하나이고 환산 점수 차이는 환산 점수가 환산 배점을 넘지 않는 항목에 "
                              "(flow/ 환산 규칙 모듈)",
    "tv2.fileDecode": "T-V2가 진입 파일 · 안내 문서 · 인포그래픽을 UTF-8로 풀 때 풀 수 없는 바이트는 대체 문자로 바꾼다",
    # 결과 통합 T-C4 실구현 (agents/supervisor/tc4.py) — 기준 문서에 없음
    "tc4.missing": "누락 오류(E-C4-MISSING) 글의 모양 'E-C4-MISSING <경우 번호들>: <빠진 산출물 키 이름들>' — 경우 번호는 "
                   "① 계획서 · 프로토타입 · 인포그래픽 · 점수 보고서 중 없는 것 ② 계획서 항목 0개 ④ 점수 보고서에 검증-2 점수 "
                   "없음(누락 조건 자체는 기준 문서 시트 2 T-C4 L열)",
    "tc4.shortfall": "미달 항목(shortfallItems) 고정 이름 · 사유 — 통과 필수 조건 이름 · 사유(entry '진입 파일' · "
                     "secret '비밀값 노출' · sandbox 'sandbox 제한', 사유는 '… 산출물층이 0점입니다.'), 대조 불가 이름 '계획서 "
                     "대조' · 사유 '계획서 대조를 판정하지 못해 0점으로 합산했습니다(대조 불가).', 빠진 기능 '프로토타입에서 이 "
                     "기능을 찾지 못했습니다.', 부분 인정 기능 '프로토타입에 이 기능의 일부만 있습니다.', detail이 빈 코드 점검 "
                     "'만점을 받지 못했습니다.', issues가 빈 검증-1 fail 'fail'(종류 · 순서는 기준 문서 시트 4 ShortfallItem.kind)",
    "tc4.userMessage": "안내 문구(userMessage) — 미달 항목이 없고 총점 통과면 '계획서 · 프로토타입 · 검증 결과를 내려받을 수 "
                       "있습니다.'(기준 문서 예시). 아니면 그 줄 · 총점 미달이면 '총점 {표시 점수}점으로 기준 점수 {기준}점에 "
                       "미달합니다.' · 층별 머리줄 '계획서에서 보완이 필요한 항목:' · '프로토타입에서 보완이 필요한 항목:' 아래 "
                       "'- 이름 (점수/배점점): 사유' 줄 · 끝 줄 '제출 전 작성자 본인의 검토가 필요합니다.'",
    # 공고 연결 (공고 선택 · 자격 확인 G-01) — 기준 문서에 없음
    "announcement.formSpec": "선택 공고의 양식 필드(formSpec · evaluationItems) 자리 표시 값 — 기본 양식 1-1 · 2-1 · 3-3 "
                             "(자리 표시 값이고 뒷 단계가 읽지 않는 것은 기준 문서 시트 4 Announcement)",
    # 작업 분해 (T-C3, agents/form_defaults.py · agents/supervisor/plan.py) — 실행 건 설정값이 아니라 코드 표다
    "taskPlan.formTable": "신청자 유형별 양식 · 평가 항목 · 채점 기준표(항목 수 · 이름 40자 · 배점 · rubricId · 버전은 기준 문서 "
                          "시트 4) 중 정하지 않은 것 — 담당자 execution_contract.json에서 만든다. 항목 제목은 담당자 계약 "
                          "displayTitle(양식 원래 제목, 없으면 title), 평가 설명 · 채점 기준의 대신 값은 담당자 title(작성 지시), "
                          "점수 구간은 {min 0, max 항목 배점} 하나 (agents/form_defaults.py)",
    "partnerSw.unassignedPhase": "예비창업 사업비 row의 phase가 없으면 1 · 2단계 표 어디에도 넣지 않고 2.5.3 표의 '단계 미지정' "
                                 "줄로 보존, 2.5.3 · 2.5.4를 입력 없음으로 둔다 — 웹 phase 컬럼이 생기면 풀린다 "
                                 "(agents/partner_sw/inputs.py)",
    "partnerSw.inputMissing": "입력 없음(SectionResult.inputMissing — 사업비 · 일정 입력이 비어 생긴 표 항목, 기준 문서 시트 7 "
                              "주석)의 문구 — 판정 warning '입력 확인 필요 — <사업비 집행계획 | 추진 일정>', 점수 보고서 안내 "
                              "'입력 확인 필요 — 사업비 집행계획 · 추진 일정을 입력하면 해당 표가 채워집니다.' "
                              "(agents/partner_sw/verify.py · inputs.py, agents/stubs.py)",
    "partnerSw.inputError": "입력 오류(SectionResult.inputError — 세 기준은 기준 문서 시트 7 주석)를 가르는 담당자 코드와 "
                            "안내 문구 — 최종 fail 판정이고 담당자 F19 inputErrorCodes에 입력 오류 코드"
                            "(AGREEMENT_MONTHS_EXCEEDED · AGREEMENT_SCHEDULE_AFTER_DEADLINE · SUPPORT_LIMIT_EXCEEDED)가 있으면 "
                            "참(담당자 SB-360 — issue 문구와 무관). 점수 보고서 안내 '입력한 협약기간 일정이나 사업비가 "
                            "기준(…)을 벗어나 … 이대로 진행하거나, 입력을 고쳐 새로 만들 수 있습니다.' "
                            "(agents/partner_sw/verify.py, agents/supervisor/judge.py INPUT_ERROR_NOTICE)",
    "partnerSw.kietSearch": "실행별 KIET 자료 검색 스위치 SBRAIN_KIET_SEARCH 기본 꺼짐(워커 환경 변수). 켜면 T-S1이 검색어로 "
                            "KIET를 찾는다 — 재시도 2회(KIET_RETRIES, 처음 포함 최대 3번) · 한 번 25초, 검색어는 기술 분야(비면 아이디어 "
                            "설명 앞 120자). 검색 실패(크롤러 값 failed · 크롤러 밖 예외)는 호출 기록에 '호출실패'로 남고, 재시도를 다 "
                            "쓰면 Task를 멈추지 않고 있는 자료로 계속한다(호출 소진을 받는 예외). 결과 0건은 실패가 아니다 "
                            "(agents/partner_sw/market_research.py, agents/partner_sw/strategy.py, bootstrap.build_app)",
    "partnerSw.outputMapping": "담당자 결과 → RequirementAnalysis · MarketAnalysis 매핑, numericTokens(숫자 + 단위 규칙 추출), "
                               "문장 나누기(줄 · 문장 끝, sentenceId s-<항목>-<순번>) (agents/partner_sw/outputs.py)",
    "intake.startupItemName": "창업아이템명(startupItemName, 첫 줄 · 앞뒤 공백 제거 · 60자 — 기준 문서 시트 4) 중 정하지 "
                              "않은 것 — 설명 전체의 앞뒤 공백을 먼저 지우므로 설명이 빈 줄로 시작하면 첫 글자 있는 줄을 쓴다(웹 규칙 "
                              "확인 전) (intake/mapping.py startup_item_name)",
    "partnerSw.generalStatusFacts": "일반현황 항목(예비창업 2.1.1 · 초기창업 3.1.1)의 F16 · F19 근거 원본 사실에만 '창업아이템명' "
                                    "(없으면 칸 없음) · '팀구성현황'(팀원마다 직위 = 역할 또는 '팀원', 담당업무 = 역할 또는 '-', "
                                    "보유역량 = 경력 또는 '-' — 웹 표 모양, 이름 없음. 팀원이 없으면 '팀원 없음(대표자 단독)', 옛 "
                                    "실행 건(팀원 표 행 None)이면 칸 없음)을 덧붙인다. 사용자 목표 고객이 없으면 원본 사실 · T-S2의 "
                                    "목표 고객은 '확인 필요' (agents/partner_sw/inputs.py)",
    "partnerSw.applicantLines": "teamRoleCareers에서 '역할: 경력' 꼴이 아닌 줄은 역할로 보고, 채용 · 장비 · 협력 계획은 한 줄 "
                                "목록으로 담당자 입력에 싣는다 (agents/partner_sw/inputs.py)",
    "verify1.redoDetails": "검증-1 재수행 T-V1의 unit은 종류가 섞이면 '섹션', 판정 후보의 사유와 보완 지시는 같은 글, "
                           "재작성 사이클 T-V1 피드백 종류 '재채점' (flow/sbrain_flow.py · agents/stubs.py)",
    # 공고 서버 연결 (agents/notice) — 실행 건 설정값이 아니라 워커 프로세스 값 · 고정 문장이다
    "announcement.matchReason": "추천 이유 문장 틀 — 공고 서버의 band(매우 적합 · 적합 · 참고, 없으면 대체 경로 "
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
                         "errorCode · error) · 대기(run · project · point) · 실행끝(run · project · status) · "
                         "재개예약(run · project · at · errorKind · errorCode — errorCode는 엔진이 받은 재시도 소진의 오류 "
                         "코드, 없으면 '-') · 파일삭제(run · deletion) · 파일삭제실패(run · deletion · errorKind · "
                         "error · attempts) · 파일삭제포기(run · deletion · attempts). 운영하면서 바꿀 수 있다 "
                         "(orchestrator/runlog.py)",
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
    # 파일 삭제 대기열 (orchestrator/file_deletion.py) — 워커 프로세스 값이다. 포기 횟수 3은 확정값이라 여기 없다
    "fileDeletion.firstDelaySec": "넣은 뒤 첫 삭제 시도까지 600초(10분) — 워커 점유 시간(120초)보다 길게 두어 삭제 직전 단계의 "
                                  "늦은 쓰기가 끝난 뒤에 지운다 (orchestrator/file_deletion.py FIRST_DELAY_SEC)",
    "fileDeletion.retrySec": "삭제 실패 뒤 다시 시도 간격 · 가져간 줄을 미루는 시간 600초(10분) "
                             "(orchestrator/file_deletion.py RETRY_SEC)",
    "fileDeletion.batchSize": "작업 확인 주기(10분)마다 한 번에 가져가는 대기열 줄 수 20 (orchestrator/file_deletion.py "
                              "BATCH_SIZE)",
    # 저장소 (orchestrator/store.py) — 메모리 · SQL 저장소가 함께 쓴다
    "store.accountLockTimeoutSec": "계정 잠금 대기 10초 — 넘기면 StoreConflict (orchestrator/store.py "
                                   "ACCOUNT_LOCK_TIMEOUT_SEC)",
    # 재작성 요청 (flow/service.py) — 실행 건 설정값이 아니라 명령 창구 값이다(모으는 시간 2초는 기준 문서 시트 1)
    "reworkRequest.leaseRetrySec": "재작성 요청의 점유 재시도 최대 5초 — 그래도 못 잡으면 BUSY",
    # 진행 기다리기 (flow/service.py wait_project) — 명령 창구 값이다
    "waitProject.timeoutSec": "wait_project 기본 제한 시간 60초 — 넘기면 그때의 진행 상태를 그대로 준다",
    "waitProject.pollSec": "wait_project가 DB를 다시 읽는 간격 0.5초",
    # 산출물 파일 읽기 (flow/reads.py read_artifact_file)
    "fileRead.hashMismatch": "읽은 내용의 sha256 · 크기가 저장된 값과 다르면 FILE_NOT_FOUND로 보고 관리자용 사유는 남기지 않는다",
    # 조립 (bootstrap.py · worker.py · 0035)
    "artifactRoot.workerRequired": "SBRAIN_ARTIFACT_ROOT가 없거나 절대 경로 · 형식이 맞는 S3 주소('s3://<버킷>[/<접두어>]')가 "
                                   "아니면 워커가 시작하지 않는다 (SBRAIN_DB_URL · OPENAI_API_KEY 없을 때와 같은 방식, 종료 "
                                   "코드 2)",
    # S3 파일 저장소 (sbrain/store_s3/ · bootstrap.py · worker.py) — 워커 · 웹 프로세스 값이다. 리전을 읽는 순서는 AWS
    # 관례, 리전 필수 · 시작 확인 범위는 확정값, 재시도 간격 · 출력 확인 재시도는 기준 문서 시트 1 값이라 여기 없다
    "s3Store.clientTimeouts": "S3 클라이언트 시간 제한 — 연결 10초 · 읽기 60초(파일 하나 30MB 이하) (store_s3/client.py "
                              "CONNECT_TIMEOUT_SEC · READ_TIMEOUT_SEC)",
    "s3Store.libraryRetries": "AWS 라이브러리 자체 재시도 끔 — 첫 요청 포함 1번(total_max_attempts 1), 재시도 방식 standard "
                              "고정(설정 파일 · 환경 변수가 바꾸지 못하게) — 재시도는 tools · 대기열 · 시작 확인 규칙대로 "
                              "(store_s3/client.py TOTAL_MAX_ATTEMPTS · RETRY_MODE)",
    "s3Store.connectionPool": "S3 클라이언트 연결 수는 라이브러리 기본값(10)을 그대로 쓴다 (store_s3/client.py client_config)",
    "s3Store.temporaryErrorCodes": "일시로 보는 S3 오류 코드 목록 — 설치된 botocore 표준 재시도의 일시 · 속도 제한 코드와 같게 "
                                   "(store_s3/errors.py TRANSIENT_ERROR_CODES · THROTTLING_ERROR_CODES)",
    "s3Store.nameShapes": "버킷 이름 모양(소문자 · 숫자 · '.' · '-', 3 ~ 63자, 소문자 · 숫자로 시작 · 끝, '..' 없음)과 접두어 "
                          "모양(마디는 영문 · 숫자 · '.' · '-' · '_', '.' · '..' · 빈 마디 금지, 정리한 접두어 200자 이하) "
                          "(store_s3/address.py PREFIX_MAX_LEN)",
    "s3Store.contentTypes": "내용 객체의 Content-Type은 넣을 때 정한 형식(mediaType), 메타 객체는 application/json(로컬 폴더 옆 "
                            "파일과 같은 JSON) (store_s3/store.py META_CONTENT_TYPE)",
    "s3Store.startupProbe": "워커 시작 확인의 시험 객체 이름 '<접두어>.probe/<고유값>' · 형식 text/plain (store_s3/probe.py "
                            "PROBE_DIR · PROBE_CONTENT_TYPE)",
    "s3Store.startupTemporaryExit": "시작 확인 일시 실패(연결 · 시간 초과 · 5xx · 속도 제한 · 자격 증명을 얻지 못함)면 워커 "
                                    "종료 코드 1 — systemd가 다시 띄운다(영구 실패 · 설정 오류는 2) (sbrain/worker.py main)",
    # 출력 파일 참조 확인 (orchestrator/tools.py · engine.py)
    "fileCheck.purpose": "엔진의 출력 파일 참조 확인 호출(파일 호출 기록 call_type 'file')의 목적 이름 check — put · get 옆 값 "
                         "(orchestrator/tools.py FILE_CHECK_PURPOSE)",
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
