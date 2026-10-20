"""구성 조립 — 저장소 · 등록부 · 워크플로 · 엔진 · 명령 창구를 한곳에서 묶는다.

| 함수 | 쓰는 곳 | 저장소 · 입력 · 설정 | Agent |
|---|---|---|---|
| build_stub_app | 테스트 · 시연 | 메모리(또는 주어진 저장소) · 기본 설정 | Task는 스텁, 규칙 단계(G-02a · G-02b · G-04 · M-1 ~ M-4)는 조율 실구현 + 테스트용 실패 흉내, 가짜 LLM · 가짜 이미지 호출처, 지시문 다시 쓰기 없음(덧붙이기만) |
| build_app | 워커 (sbrain/worker.py) | 공유 MySQL — SqlStore · SqlProjectInputSource · DbSettingsProvider | 조율 T-C1 · T-C3 실구현과 재작성 · 재수행 지시문 다시 쓰기(OpenAI), 조율 규칙 단계 G-02a · G-02b · G-04 · M-1 ~ M-4 실구현(LLM 없음), 전략 · 작성 · 검증-1 T-S1 · T-S2 · T-W1 · T-W2 · T-W3 · T-V1 실구현(담당자 코드 — OpenAI, T-W3는 LLM 없음, T-S1 실행별 KIET 검색은 SBRAIN_KIET_SEARCH가 켜는 값일 때만), 구현 · 검증-2 T-B1 · T-B2 · T-V2 실구현(담당자 코드 — OpenAI), T-C2 · G-01은 SBRAIN_NOTICE_API_URL이 있으면 공고 서버 연결(실제 모드) · 없으면 스텁, 나머지 스텁. 이미지 호출도 구현이 들어온 Task(T-B2 아이콘판)만 실제(OpenAI) |
| build_web | 웹 서버 | 공유 MySQL — 같음 | 단계를 돌지 않는다 (명령 · 조회만). 공고 서버 · 이미지 호출처를 부르지 않는다 |

파일 저장소 (확장 · 0035 — SBRAIN_ARTIFACT_ROOT 하나, 기본값 없음, 값 확인은 artifact_root_problem 한 곳):
- 값 모양: 절대 경로 → 로컬 폴더, 's3://<버킷>' · 's3://<버킷>/<접두어>'(스킴은 소문자만, 모양 검사는 store_s3 주소 함수) → S3
  (버킷 안 접두어 아래). 그 밖(상대 경로 · S3 주소 형식이 틀림)은 쓸 수 없는 값이다.
- S3면 리전이 필수다 — AWS_REGION, 없으면 AWS_DEFAULT_REGION(get_env — 환경 변수 → .env, AWS 관례 순서)을 S3 클라이언트에 직접
  넘긴다. 자격 증명은 AWS 기본 순서 그대로다(우리 코드는 AWS 키를 읽거나 넘기지 않는다).
- AWS 라이브러리(boto3 · botocore)는 S3 저장소를 만들 때만 불러온다 — 로컬 값으로 도는 조립은 불러오지 않는다.
- 값(경로 · 버킷 · 접두어 · 리전)은 오류 메시지 · 예외 · 워커 화면 줄에 싣지 않는다 — 문제 종류 · 상태 · 오류 코드만.
| 조립 | 파일 저장소 |
|---|---|
| build_stub_app | 메모리(MemoryFileStore) — 값과 관계없다 |
| build_app | 필수. 로컬 폴더(없으면 만든다) 또는 S3(쓰기 가능 — 조립할 때 시작 확인 check_s3_store를 한 번 한다). 없음 · 상대 경로 · S3 주소 형식 오류 · 리전 없음 · S3 저장소를 만들지 못함(AWS 라이브러리 없음 · 리전 모양)이면 DB에 닿기 전에 RuntimeError, 시작 확인 실패는 S3StartupCheckFailed(RuntimeError — permanent면 워커 종료 코드 2, 아니면 1). 시작 확인을 다시 부르거나 기다리지 않는다 |
| build_web | 선택 · 읽기 전용 — 로컬 폴더(만들지 않는다) 또는 S3(형식 · 리전이 맞을 때). 엔진에 넘기지 않고 파일 읽기(read_artifact_file)에만 쓴다. 없음 · 상대 경로 · S3 주소 형식 오류 · 리전 없음 · AWS 라이브러리 없음 · S3 저장소를 만들지 못함이면 조립은 되고 그 함수만 FILE_STORE_UNAVAILABLE. 시작 확인을 하지 않고 조립할 때 S3를 부르지 않는다(클라이언트는 처음 읽을 때). 쓰지도 지우지도 않는다(FileStoreReadOnly) |
웹과 모든 워커는 같은 값을 봐야 한다(같은 폴더 — 같은 서버 또는 공유 폴더, 또는 같은 버킷 · 접두어).

실제 Agent 구현이 나오면 registry.bind(task_id, fn)로 스텁을 교체한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .agents.notice import NoticeClient, Transport, bind_notice
from .agents.partner_bv.tasks import IMAGE_TASKS as BV_IMAGE_TASKS
from .agents.partner_bv.tasks import IMPLEMENTED_TASKS as BV_TASKS
from .agents.partner_bv.tasks import bind_partner_bv
from .agents.partner_sw.market_research import set_kiet_search
from .agents.partner_sw.tasks import IMPLEMENTED_TASKS as PARTNER_TASKS
from .agents.partner_sw.tasks import bind_partner_sw
from .agents.stubs import FakeImage, FakeLLM, StubScenario, bind_stubs, make_constants
from .agents.supervisor import IMPLEMENTED_TASKS, bind_supervisor
from .agents.supervisor.plan import PURPOSE_REWRITE
from .agents.supervisor.rewrite import rewrite_guidance
from .env import get_env
from .flow import IMMUTABLE_KEYS, SBrainFlow, SBrainOrchestrator, artifact_types, build_registry
from .flow.sbrain_flow import REWRITE_AGENT, GuidanceRewriter
from .intake import ProjectInputSource
from .models.clock import utc_clock, utc_now
from .orchestrator import ArtifactTypes, Engine, MemoryStore, Settings, SettingsProvider
from .orchestrator.files import FileStore, LocalFolderFileStore, MemoryFileStore
from .orchestrator.registry import TaskRegistry
from .orchestrator.store import Store
from .orchestrator.tools import ImageProvider, ImageRequest, LLMProvider, LLMRequest
from .store_s3.address import is_s3_address, s3_address_problem   # 주소 함수 — AWS 라이브러리를 불러오지 않는다

ARTIFACT_ROOT_ENV = "SBRAIN_ARTIFACT_ROOT"   # 파일 저장소 (확장 · 0035) — 절대 경로 또는 s3://, 기본값 없음
KIET_SEARCH_ENV = "SBRAIN_KIET_SEARCH"       # 실행별 KIET 검색 스위치 (SB-360, 잠정) — 켜는 값이 없으면 꺼짐
KIET_SEARCH_ON = frozenset({"1", "true", "yes", "on"})   # (잠정) 켜는 값 — 대소문자 · 앞뒤 공백 무시

# SBRAIN_ARTIFACT_ROOT 값의 문제 종류 (artifact_root_problem이 돌려준다 — 값이 없는 글)
ROOT_MISSING = "없음"
ROOT_NOT_ABSOLUTE = "절대 경로가 아님"
ROOT_NOT_S3_ADDRESS = "S3 주소 형식이 아님"
# S3 리전을 읽는 환경 변수 — 앞에서부터 (AWS 관례 순서). 값은 S3 클라이언트에 직접 넘긴다
S3_REGION_ENVS = ("AWS_REGION", "AWS_DEFAULT_REGION")
S3_REGION_MISSING = f"{ARTIFACT_ROOT_ENV}가 S3인데 AWS_REGION(또는 AWS_DEFAULT_REGION)이 없음"


def switch_on(value: str | None) -> bool:
    """스위치 값이 켜는 값(1 · true · yes · on, 대소문자 무시)인가. 없거나 그 밖의 값은 꺼짐."""
    return (value or "").strip().lower() in KIET_SEARCH_ON


def artifact_root_problem(value: str | None) -> str | None:
    """SBRAIN_ARTIFACT_ROOT 값의 문제 — '없음' · '절대 경로가 아님' · 'S3 주소 형식이 아님', 맞으면 None. 문구에 값을 넣지 않는다.

    's3://'(소문자)로 시작하면 S3 주소로 보고 모양을 store_s3 주소 함수(s3_address_problem)로 본다. 그 밖은 절대 경로여야 한다 —
    상대 경로는 프로세스를 띄운 폴더 기준으로 풀려 웹과 워커가 서로 다른 폴더를 볼 수 있어 '값 없음'과 같게 다룬다.
    S3일 때의 리전 없음은 여기서 보지 않는다(s3_region — 조립이 따로 본다)."""
    if not value:
        return ROOT_MISSING
    if is_s3_address(value):
        return ROOT_NOT_S3_ADDRESS if s3_address_problem(value) is not None else None
    if not Path(value).is_absolute():
        return ROOT_NOT_ABSOLUTE
    return None


def s3_region() -> str | None:
    """S3 리전 — AWS_REGION, 없으면 AWS_DEFAULT_REGION(get_env — 환경 변수 → .env). 둘 다 없으면 None(리전 없음)."""
    for name in S3_REGION_ENVS:
        value = get_env(name)
        if value:
            return value
    return None


@dataclass
class App:
    orchestrator: SBrainOrchestrator
    engine: Engine
    store: Store
    registry: TaskRegistry
    llm: FakeLLM
    scenario: StubScenario
    settings: SettingsProvider
    image: FakeImage | None = None   # 가짜 이미지 호출처 (확장) — 웹 조립은 없다


class TaskRoutedProvider:
    """구현이 들어온 호출만 실제 호출처로, 나머지(스텁 Task)는 가짜 호출처로 보낸다 (잠정).

    호출처는 Agent마다 정해지므로, 그대로 두면 스텁 Task도 실제 OpenAI를 부른다. 실제 호출처로 보내는 규칙:
    - 호출 기록의 task_id가 real_tasks(구현 Task — 조율 T-C1 · T-C3, 전략 · 작성 · 검증-1 T-S1 ~ T-V1,
      구현 · 검증-2 T-B1 · T-B2 · T-V2)에 있으면 실제.
    - 조율 Agent의 지시문 다시 쓰기(agent = 조율, purpose = PURPOSE_REWRITE)면 실제. 다시 쓰기는 대상 Task의 실행 기록
      안에서 불려 task_id가 대상 Task(스텁 T-W1 등)이므로, Task ID만으로는 나눌 수 없어 agent · purpose로 본다.
    - 그 밖(스텁 Task 자신의 호출)은 가짜.
    각 Task 구현이 들어오면 real_tasks가 늘어난다.
    """

    def __init__(self, real: LLMProvider, fake: LLMProvider, real_tasks: frozenset[str]) -> None:
        self.real, self.fake, self.real_tasks = real, fake, real_tasks

    def is_real(self, request: LLMRequest) -> bool:
        meta = request.metadata
        if meta.get("task_id") in self.real_tasks:
            return True
        return meta.get("agent") == REWRITE_AGENT and meta.get("purpose") == PURPOSE_REWRITE

    def complete(self, request: LLMRequest):
        return (self.real if self.is_real(request) else self.fake).complete(request)


class TaskRoutedImageProvider:
    """이미지 호출도 구현이 들어온 Task만 실제 호출처로, 나머지(스텁 Task)는 가짜로 보낸다 (확장, 잠정).

    호출 기록의 task_id가 real_tasks에 있으면 실제. 지시문 다시 쓰기는 글 호출이라 이미지 호출에는 그 길이 없다.
    워커 조립의 real_tasks는 이미지 호출을 하는 실구현 Task(T-B2 아이콘판 — 한 번 약 35원)다.
    """

    def __init__(self, real: ImageProvider, fake: ImageProvider, real_tasks: frozenset[str]) -> None:
        self.real, self.fake, self.real_tasks = real, fake, real_tasks

    def is_real(self, request: ImageRequest) -> bool:
        return request.metadata.get("task_id") in self.real_tasks

    def create(self, request: ImageRequest):
        return (self.real if self.is_real(request) else self.fake).create(request)


class NoProvider:
    """웹 프로세스용 — LLM을 부르지 않는다. 단계 진행은 워커가 한다."""

    def complete(self, request: LLMRequest):
        raise RuntimeError("웹 프로세스는 LLM을 부르지 않는다 — 사전 단계 · 진행 · 재개는 워커가 한다")


def build_stub_app(
    scenario: StubScenario | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], datetime] = utc_now,
    profile_count: Callable[[str], int] = lambda account_id: 1,
    project_inputs: ProjectInputSource | None = None,
    store: Store | None = None,
) -> App:
    """스텁 Agent와 메모리 저장소로 뼈대 전체를 조립한다 (테스트 · 시연용).

    규칙 단계(G-02a · G-02b · G-04 · M-1 ~ M-4)와 결과 통합 T-C4는 스텁이 없고 조율 실구현에 테스트용 실패 흉내(raise_in ·
    G-04 check_fail_times)만 감싼다 — 흐름 테스트가 워커와 같은 규칙을 검사한다 (bind_stubs).

    project_inputs를 주면 start_run_for_project로 웹 DB에 저장된 사전 정보를 읽어 시작할 수 있다.
    store를 주면 그 저장소를 쓴다(예: SqlStore). 없으면 메모리 저장소.
    """
    return _assemble(
        store=store if store is not None else MemoryStore(now=now), settings=SettingsProvider(settings),
        scenario=scenario or StubScenario(), now=now, sleep=lambda s: None, profile_count=profile_count,
        project_inputs=project_inputs, stubs=True, files=MemoryFileStore())


def build_app(
    db_url: str | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], datetime] = utc_now,
    project_inputs: ProjectInputSource | None = None,
    llm: LLMProvider | None = None,
    notice_api_url: str | None = None,
    notice_transport: Transport | None = None,
    image: ImageProvider | None = None,
    artifact_root: str | None = None,
    kiet_search: bool | None = None,
    s3_client: Any = None,
) -> App:
    """워커 조립 — 공유 MySQL(SqlStore · SqlProjectInputSource · DbSettingsProvider), 조율 T-C1 · T-C3 실구현, OpenAI 호출처.

    - 조율 규칙 단계(판정 G-02a · G-02b, 안내 문서 G-04, 합치기 M-1 ~ M-4)와 결과 통합 T-C4도 실구현이다
      (bind_supervisor — 실패 흉내 없이 그대로). LLM을 부르지 않아 호출처 나누기 대상이 아니다.

    - db_url이 없으면 SBRAIN_DB_URL(환경 변수 → .env)을 쓴다.
    - 파일 저장소(확장 · 0035): artifact_root, 주지 않으면(None) SBRAIN_ARTIFACT_ROOT(환경 변수 → .env). 필수다.
      DB에 닿기 전에 값을 보고 저장소를 만든다(_worker_files) — 값은 메시지에 싣지 않는다.
      - 절대 경로면 로컬 폴더(없으면 만든다 — 만들지 못하면 RuntimeError).
      - 's3://<버킷>[/<접두어>]'면 리전(s3_region — AWS_REGION → AWS_DEFAULT_REGION)을 넣은 쓰기 가능 S3 저장소를 만들고 시작 확인
        (store_s3.check_s3_store)을 한 번 한다. 리전 없음 · 저장소를 만들지 못함(S3StoreError — AWS 라이브러리 없음 · 리전 모양)은
        RuntimeError, 시작 확인 실패는 S3StartupCheckFailed(RuntimeError — .permanent: 참이면 설정 오류, 거짓이면 일시). 다시
        부르거나 기다리지 않는다 — 일시면 워커가 종료 코드 1로 끝나고 systemd가 다시 띄운다.
      - 없음 · 상대 경로 · S3 주소 형식이 틀림이면 RuntimeError.
    - s3_client는 시험용 가짜 S3 클라이언트(tests/s3_fake.py)를 끼울 때만 준다. 주면 AWS 라이브러리를 부르지 않는다. 없으면 저장소가
      처음 쓸 때(시작 확인) store_s3.client.make_s3_client로 만든다.
    - 흐름의 지시문 만들기에 조율 다시 쓰기(rewrite_guidance)를 끼운다 — 재작성 · 재수행 대상의 안내를 다시 쓴다.
    - 전략 · 작성 · 검증-1(T-S1 · T-S2 · T-W1 · T-W2 · T-W3 · T-V1)은 담당자 코드 실구현(agents/partner_sw, bind_partner_sw)이고
      그 LLM 호출도 실제 호출처로 간다.
    - 구현 · 검증-2(T-B1 · T-B2 · T-V2)도 담당자 코드 실구현(agents/partner_bv, bind_partner_bv)이고 그 LLM 호출은 실제 호출처로,
      T-B2의 이미지 호출(아이콘판)은 실제 이미지 호출처로 간다.
    - 나머지 Agent는 스텁이다. 스텁 Task는 실제 호출처를 부르지 않는다(TaskRoutedProvider). 다시 쓰기 호출은 대상이
      스텁 Task여도 실제 호출처로 간다.
    - 공고 매칭(T-C2) · 자격 확인(G-01): 공고 서버 주소가 있으면 공고 서버 연결(agents/notice, 실제 모드), 없으면 스텁
      (스텁 모드 — 스텁 G-01이 스텁 공고를 만들고 판정한다).
      주소는 notice_api_url, 주지 않으면(None) SBRAIN_NOTICE_API_URL(환경 변수 → .env). 빈 문자열이면 스텁이다.
      주소 형식이 틀리면 조립할 때 ValueError다(메시지에 주소를 싣지 않는다).
    - 실행별 KIET 검색(SB-360, 기본 꺼짐): kiet_search, 주지 않으면(None) SBRAIN_KIET_SEARCH(환경 변수 → .env)가 켜는 값
      (1 · true · yes · on, 대소문자 무시)인지. 연결 코드의 스위치(partner_sw.market_research.set_kiet_search — 워커 프로세스
      값)로 넘긴다. bind_partner_sw를 부르는 모양은 그대로다(웹 E2E · stub_worker가 바꿔 끼운다). 꺼져 있으면 T-S1이 KIET를 부르지 않는다.
    - project_inputs · llm · notice_transport · image는 시험용으로 바꿔 끼울 때만 준다. llm이 없으면 OpenAIProvider(OPENAI_API_KEY),
      notice_transport가 없으면 표준 라이브러리 HTTP 전송, image가 없으면 OpenAIImageProvider(첫 호출 때 클라이언트를 만든다).
    - 이미지 호출(확장)도 TaskRoutedImageProvider로 나눈다 — 구현이 들어온 Task(T-B2)만 실제, 나머지는 가짜.
    """
    from .intake.sql_source import SqlProjectInputSource
    from .orchestrator.openai_image import OpenAIImageProvider
    from .orchestrator.openai_provider import OpenAIProvider
    from .store_sql import DbSettingsProvider, SqlStore, create_db_engine

    files = _worker_files(get_env(ARTIFACT_ROOT_ENV) if artifact_root is None else artifact_root, s3_client)
    db = create_db_engine(_db_url(db_url))
    app = _assemble(
        store=SqlStore(db, now=now), settings=DbSettingsProvider(db, settings), scenario=StubScenario(), now=now,
        sleep=time.sleep, profile_count=lambda account_id: 1,   # 워커는 시작 확인(request_start)을 하지 않는다
        project_inputs=project_inputs or SqlProjectInputSource(db), stubs=True, rewriter=rewrite_guidance,
        files=files)
    bind_supervisor(app.registry)
    bind_partner_sw(app.registry)   # 전략 · 작성 · 검증-1 실구현
    bind_partner_bv(app.registry)   # 구현 · 검증-2 실구현 T-B1 · T-B2 · T-V2
    # 실행별 KIET 검색 스위치 (SB-360) — T-S1 등록은 그대로 두고 연결 코드의 프로세스 값만 정한다
    set_kiet_search(switch_on(get_env(KIET_SEARCH_ENV)) if kiet_search is None else kiet_search)
    notice_url = get_env("SBRAIN_NOTICE_API_URL") if notice_api_url is None else notice_api_url
    if notice_url:   # 실제 모드 — 공고 서버 연결로 스텁 T-C2 · G-01을 바꾼다
        bind_notice(app.registry, NoticeClient(notice_url, transport=notice_transport))
    app.engine.providers["openai"] = TaskRoutedProvider(llm or OpenAIProvider(), app.llm,
                                                        IMPLEMENTED_TASKS | PARTNER_TASKS | BV_TASKS)
    app.engine.image_providers["openai"] = TaskRoutedImageProvider(
        image or OpenAIImageProvider(), app.image, IMPLEMENTED_TASKS | BV_IMAGE_TASKS)
    return app


def build_web(
    db_url: str | None = None,
    *,
    profile_count: Callable[[str], int],
    settings: Settings | None = None,
    now: Callable[[], datetime] = utc_now,
    project_inputs: ProjectInputSource | None = None,
    artifact_root: str | None = None,
    s3_client: Any = None,
) -> App:
    """웹 서버 조립 — 명령 · 조회 함수만 쓰는 SBrainOrchestrator. LLM 호출처가 없고 단계를 돌지 않는다.

    파일 저장소(확장 · 0035): artifact_root, 주지 않으면(None) SBRAIN_ARTIFACT_ROOT. 선택이다 — 절대 경로면 로컬 폴더,
    's3://<버킷>[/<접두어>]'이고 리전(AWS_REGION → AWS_DEFAULT_REGION)이 있으면 S3를 읽기 전용으로 열어 파일 읽기
    (read_artifact_file)에만 쓴다(엔진에는 넘기지 않는다, 폴더를 만들지 않는다, 시작 확인을 하지 않고 조립할 때 S3를 부르지
    않는다 — 클라이언트는 처음 읽을 때 만든다). 없음 · 상대 경로 · S3 주소 형식이 틀림 · 리전 없음 · AWS 라이브러리 없음 · S3
    저장소를 만들지 못함이면 조립은 되고(웹 서버는 뜬다) read_artifact_file만 FILE_STORE_UNAVAILABLE이다. 웹은 파일을 쓰지도
    지우지도 않는다(읽기 전용 저장소의 쓰기 · 지우기는 FileStoreReadOnly) — 삭제는 모두 워커가 한다.
    s3_client는 시험용 가짜 S3 클라이언트를 끼울 때만 준다(build_app과 같음).

    profile_count: 계정의 필수 항목을 채운 프로필 수 (0이면 E-AUTH-PROFILE). 웹은 compute_has_profile을 넘긴다(참 = 1).
    웹은 request_start · start_status · 명령 · 조회 · 중단만 부른다. run_start_request · advance · tick은 워커가 부른다.
    사전 단계를 막는 장치: run_start_request(와 동기 경로 start_run · start_run_for_project)는 시작 요청을 건드리지 않고
    바로 CommandError("WEB_NOT_ALLOWED")다 (allow_pre_stage = False).
    """
    from .intake.sql_source import SqlProjectInputSource
    from .store_sql import DbSettingsProvider, SqlStore, create_db_engine

    reader = _web_file_reader(get_env(ARTIFACT_ROOT_ENV) if artifact_root is None else artifact_root, s3_client)
    db = create_db_engine(_db_url(db_url))
    app = _assemble(
        store=SqlStore(db, now=now), settings=DbSettingsProvider(db, settings), scenario=StubScenario(), now=now,
        sleep=time.sleep, profile_count=profile_count, project_inputs=project_inputs or SqlProjectInputSource(db),
        stubs=False, files=None, file_reader=reader)
    app.engine.stop_requested = lambda: True   # 실수로 advance를 불러도 단계를 돌지 않는다
    app.orchestrator.allow_pre_stage = False   # 사전 단계(run_start_request)는 WEB_NOT_ALLOWED — 워커가 돈다
    return app


def _worker_files(root: str | None, s3_client: Any) -> FileStore:
    """워커 조립의 파일 저장소 (0035) — DB에 닿기 전에 부른다. 메시지에 값(경로 · 버킷 · 접두어 · 리전)을 싣지 않는다."""
    problem = artifact_root_problem(root)
    if problem == ROOT_NOT_S3_ADDRESS:   # 문제 종류(s3_address_problem)도 값 없는 글이다
        raise RuntimeError(f"{ARTIFACT_ROOT_ENV}가 {problem}: {s3_address_problem(root)} — 's3://<버킷>' 또는 "
                           "'s3://<버킷>/<접두어>'를 넣는다 (웹과 모든 워커가 같은 값)")
    if problem is not None or root is None:
        raise RuntimeError(f"{ARTIFACT_ROOT_ENV}가 {problem} — 환경 변수 또는 agent-orchestration/.env에 파일 저장소 폴더의 절대 경로 "
                           "또는 소문자 's3://<버킷>[/<접두어>]'를 넣는다 (웹과 모든 워커가 같은 값)")
    if is_s3_address(root):
        return _worker_s3_store(root, s3_client)
    try:
        return LocalFolderFileStore(root, create=True)
    except OSError as e:   # 경로가 든 디스크 오류 메시지를 싣지 않는다 — 종류만
        raise RuntimeError(f"{ARTIFACT_ROOT_ENV} 폴더를 만들지 못함 — {type(e).__name__}") from None


def _worker_s3_store(address: str, s3_client: Any) -> FileStore:
    """워커의 S3 저장소(쓰기 가능) + 시작 확인 한 번. AWS 라이브러리는 여기서(저장소를 만들 때) 불러온다.

    - 리전 없음 → RuntimeError(S3_REGION_MISSING).
    - 저장소를 만들지 못함 → S3StoreError(RuntimeError) 그대로 — AWS 라이브러리 없음('패키지를 다시 설치') · 리전 값 모양.
    - 시작 확인 실패 → S3StartupCheckFailed(RuntimeError, .permanent) — 메시지는 시작 확인이 만든 그대로('설정 오류: …' ·
      'S3 시작 확인 실패(일시) — <종류>'). 클라이언트를 만들지 못함 · AWS 라이브러리 없음도 시작 확인이 영구로 돌려준다.
    다시 부르거나 기다리지 않는다(재시도 규칙은 tools 한 곳 — 워커는 일시면 종료 코드 1로 끝나고 systemd가 다시 띄운다)."""
    region = s3_region()
    if region is None:
        raise RuntimeError(S3_REGION_MISSING)
    from .store_s3 import S3FileStore, check_s3_store

    store = S3FileStore.from_address(address, region, client=s3_client)
    check_s3_store(store).raise_if_failed()
    return store


def _web_file_reader(root: str | None, s3_client: Any) -> FileStore | None:
    """웹 조립의 읽기 전용 파일 저장소 (0035). 쓸 수 없는 값이면 None — read_artifact_file만 FILE_STORE_UNAVAILABLE이고
    웹 서버는 뜬다. 시작 확인을 하지 않고 S3를 부르지 않는다(클라이언트는 처음 읽을 때 만든다)."""
    if not root or artifact_root_problem(root) is not None:
        return None
    if not is_s3_address(root):
        return LocalFolderFileStore(root, read_only=True)
    region = s3_region()
    if region is None:
        return None
    from .store_s3 import S3FileStore, S3StoreError

    try:
        return S3FileStore.from_address(root, region, read_only=True, client=s3_client)
    except S3StoreError:   # AWS 라이브러리 없음 · 리전 값 모양 등 — 저장소를 만들지 못함
        return None


def _db_url(db_url: str | None) -> str:
    url = db_url or get_env("SBRAIN_DB_URL")
    if not url:
        raise RuntimeError("SBRAIN_DB_URL이 없다 — 환경 변수 또는 agent-orchestration/.env에 공유 MySQL 접속 URL을 넣는다")
    return url


def _assemble(*, store: Store, settings: SettingsProvider, scenario: StubScenario, now: Callable[[], datetime],
              sleep: Callable[[float], None], profile_count: Callable[[str], int],
              project_inputs: ProjectInputSource | None, stubs: bool,
              files: FileStore | None, file_reader: FileStore | None = None,
              rewriter: GuidanceRewriter | None = None) -> App:
    """files: 엔진의 파일 저장소(tools.files · 출력 참조 확인 · 워커 파일 삭제). file_reader: 파일 읽기 함수가 쓰는 저장소 —
    주지 않으면 files를 쓴다(웹 조립은 files 없이 읽기 전용 저장소만 준다)."""
    now = utc_clock(now)   # 모든 구성 요소가 같은 UTC 시계를 쓴다 (시간대 없는 시계는 UTC로 본다)
    registry = build_registry()
    llm = FakeLLM()
    fake_image: FakeImage | None = None
    image_providers: dict[str, ImageProvider] = {}   # 웹 조립은 이미지 호출처를 두지 않는다
    if stubs:
        bind_stubs(registry, scenario, now=now)
        providers: dict[str, LLMProvider] = {name: llm for name in ("openai", "gpu-server", "미정")}
        fake_image = FakeImage()
        image_providers = {"openai": fake_image}
    else:
        providers = {name: NoProvider() for name in ("openai", "gpu-server", "미정")}
    # 지시문 다시 쓰기는 워커 조립만 끼운다. 없으면(스텁 · 웹 조립) 재작성 · 재수행 문제를 덧붙이기만 한다
    flow = SBrainFlow(registry, constants=make_constants(), now=now, rewriter=rewriter)
    exact, suffix = artifact_types(registry)
    # 파일 저장소 (확장) — 스텁 조립은 메모리, 워커 조립은 로컬 폴더, 웹 조립은 엔진에 없음(읽기 전용은 file_reader)
    engine = Engine(store=store, registry=registry, flow=flow, providers=providers,
                    types=ArtifactTypes(exact, suffix), immutable_keys=IMMUTABLE_KEYS, now=now, sleep=sleep,
                    image_providers=image_providers, files=files)
    flow.engine = engine
    # 공고 선택 명령은 고른 ID만 남긴다 — 공고 상세는 워커의 G-01이 받는다 (명령 창구에 공고 공급처가 없다)
    orch = SBrainOrchestrator(
        engine=engine, flow=flow, settings=settings,
        profile_count=profile_count, project_inputs=project_inputs, now=now, sleep=sleep,
        files=file_reader if file_reader is not None else files)
    return App(orch, engine, store, registry, llm, scenario, settings, fake_image)
