"""오류 코드(기능정의서 시트 6)와 Orchestrator 예외."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.base import CallError, ErrorKind


@dataclass(frozen=True)
class ErrorCode:
    code: str
    where: str
    message: str       # 사용자 노출 문구 ('(노출 없음)'이면 빈 문자열)
    handling: str


ERROR_CODES: dict[str, ErrorCode] = {e.code: e for e in [
    ErrorCode("E-C1-ORDER", "T-C1", "먼저 어떤 아이템인지 알려주세요. 공고는 그다음에 찾아드립니다.", "진입 순서 위반 거절"),
    ErrorCode("E-C1-TIMEOUT", "T-C1", "잠시 문제가 있었습니다. 다시 시도해주세요.", "재시도 소진 시 재개 없이 진입 전 상태로 롤백"),
    ErrorCode("E-C2-NOMATCH", "T-C2", "지금 신청 가능한 공고가 없습니다. 입력한 정보를 확인해주세요.", "빈 배열, 사전 정보 입력으로"),
    ErrorCode("E-C2-STALE", "T-C2", "공고 정보를 갱신하는 중입니다. 갱신 후 다시 확인해주세요.", "매칭 중단, 수집 상태 경고"),
    ErrorCode("E-C2-EMBED", "T-C2", "추천 정확도가 낮아질 수 있습니다.", "폴백 순위 표시"),
    ErrorCode("E-G1-MISSING", "G-01", "신청 가능 여부를 확인하려면 사전 정보의 필수 항목이 필요합니다. 입력한 정보를 확인해주세요.", "판정 보류"),
    # 확인 필요 조건(unknownConditions)이 있으면 화면 4에만 붙는 막지 않는 안내 (기준 문서 v1.10 시트 6, spec 4.3.3)
    ErrorCode("E-G1-UNPARSED", "G-01", "이 공고는 자격요건 자동 확인이 어렵습니다. 공고문을 직접 확인해주세요.",
              "통과로 보고 화면 4에 안내, 진행을 막지 않음"),
    ErrorCode("E-G1-REJECT", "G-01", "이 공고는 {사유}로 신청이 어렵습니다. 다른 공고를 보여드릴까요?",
              "공고 선택으로 돌아감, 그 공고는 이 실행 건에서 막힘"),
    ErrorCode("E-C1-REQUIRED", "T-C1", "필수 항목을 입력해주세요: {누락 항목}", "폼 단계 차단"),
    ErrorCode("E-C1-DOC", "T-C1", "{파일명}의 내용을 읽지 못해 참고 자료에서 제외했습니다. 나머지 정보로 계속 진행합니다.", "해당 문서 제외"),
    ErrorCode("E-C3-FORM", "T-C3", "", "분해 실패로 처리하고 오류 기록"),
    ErrorCode("E-B1-ENTRY", "T-B1", "", "재수행 후 그대로 보냄, 검증-2 통과 필수 조건(entry)으로 산출물층 0"),
    # sandbox API 위반 (기준 문서 v1.10 시트 6, 구현 · 검증-2 담당 개정안 1.3판)
    ErrorCode("E-B1-SANDBOX", "T-B1", "",
              "재수행 후 그대로 보냄. 스토리지 계열은 검증-2 통과 필수 조건(산출물층 0), 나머지는 코드 점검 7번 감점"),
    ErrorCode("E-B1-DEP", "T-B1", "", "재수행 후 그대로 보냄, 점수 반영"),
    ErrorCode("E-V1-EVIDENCE", "T-V1", "", "감점 무효 처리"),
    ErrorCode("E-V1-VARIANCE", "T-V1", "", "varianceFlag=true"),
    ErrorCode("E-V2-PARSE", "T-V2", "", "해당 항목만 미충족"),
    # 사용자 노출 문구는 비워 둔다 (잠정 — 기준 문서 v1.10도 '대조 보류의 화면 문구'를 미확정으로 둠) — 화면 '대조 불가'는 웹이 withheld로 표시
    ErrorCode("E-V2-NOFEATURE", "T-V2", "", "withheld=true, 0점 합산, 화면 '대조 불가', 관리자 알림"),
    ErrorCode("E-P2-TOKEN", "T-P2", "", "redoHint에 실어 재수행"),
    ErrorCode("E-P2-RETRY", "T-P2", "", "원문 유지, 관리자 로그"),
    ErrorCode("E-G2-LIMIT", "G-02a · G-02b · R-6", "이 항목은 다시 만들 수 있는 횟수를 모두 사용했습니다. 다시 만들기 전과 후 중 점수가 높은 결과가 반영되어 있습니다.", "선택 불가 표시"),
    ErrorCode("E-AUTH-CONSENT", "로그인", "필수 항목에 동의해야 계정과 작업 결과를 보관할 수 있습니다.", "진입 중단"),
    ErrorCode("E-AUTH-PROFILE", "로그인 · R-9", "서비스를 이용하려면 먼저 마이페이지에서 프로필을 만들어주세요.", "새 실행 불가"),
    ErrorCode("E-RUN-CONCURRENT", "R-9", "진행 중인 작업이 있습니다. 이어서 진행하거나, 중단하고 새로 시작할 수 있습니다. 중단하면 지금까지의 결과를 다시 볼 수 없습니다.", "blocked=true"),
    ErrorCode("E-G2-UNREACHABLE", "G-02b", "프로토타입만 다시 만들어서는 기준 점수에 이르지 못합니다. 계획서 항목을 함께 선택해주세요.", "버튼을 막지 않음"),
    ErrorCode("E-RUN-FAIL", "R-9 · R-11", "일시적인 문제로 작업을 완료하지 못했습니다. 새 작업으로 다시 시작해주세요.", "progress='실패'"),
    ErrorCode("E-RUN-ROLLBACK", "R-6 · R-11", "일시적인 문제로 다시 만들지 못해 이전 결과로 되돌렸습니다. 다시 만들 기회는 그대로 남아 있습니다.", "되돌림 · 기회 반환"),
    ErrorCode("E-RUN-CLOSED", "R-9", "선택하신 공고의 접수가 마감되었습니다. 계속 진행할지 선택해주세요.", "마감 사실만 알림"),
    ErrorCode("E-W1-REMOVED", "T-W1 · R-6", "입력하지 않은 경력이나 지원 규모를 넘는 금액이 반복해서 작성되어 해당 부분을 지웠습니다. 필요하면 직접 보완해주세요.", "notices로 알림"),
    # 공고 서버 호출 실패 — T-C1과 같이 다시 시도 안내 (기준 문서 v1.10 시트 6)
    ErrorCode("X-C2-FAIL", "T-C2 · G-01", "잠시 문제가 있었습니다. 다시 시도해주세요.",
              "재개 없이 다시 시도 안내 — 사전 단계 · 추가 조회 실패, 자격 확인(G-01) 실패는 고르기 전 대기 지점으로"),
    # 고른 공고가 공고 서버에 없음. 고르기 전 대기 지점으로 돌아가고, 막지 않으므로 다시 고를 수 있다 (기준 문서 v1.10 시트 6)
    ErrorCode("X-C2-GONE", "G-01", "선택하신 공고를 더 이상 확인할 수 없습니다. 다른 공고를 선택해주세요.",
              "공고 없음 — 고르기 전 대기 지점으로"),
]}

# E-C2-EMBED 덧붙임 — 대체 경로가 마감 임박순이면 문구 끝에 붙인다 (기준 문서 T-C2, spec 4.1.3)
EMBED_DEADLINE_SUFFIX = " 마감 임박순으로 보여드립니다."


# CommandError 코드 (확장) — 웹이 받는 명령 · 조회 거절 사유. 시트 6 결과 코드(E-…)는 위 ERROR_CODES에 있다
# (E-G2-LIMIT는 둘 다에 쓴다). 웹은 code로 가르고, detail은 사람이 읽는 설명이다.
COMMAND_ERROR_CODES: dict[str, str] = {
    "PROJECT_NOT_FOUND": "프로젝트가 없거나, 보관됐거나, 다른 계정 것 (구분하지 않음)",
    "PROJECT_ALREADY_STARTED": "끝난 실행 건이 있는 프로젝트 — 새 프로젝트로 시작",
    "NO_PROJECT_SOURCE": "조립 오류 — 웹 DB 입력 공급처가 없음",
    "RUN_NOT_FOUND": "실행 건이 없는 프로젝트에 명령 · 조회",
    "RUN_NOT_VIEWABLE": "실패 · 중단된 실행 건 — 지금까지 결과 · 재작성 결과를 보여 주지 않음 (공고 마감 안내 E-RUN-CLOSED와 다름)",
    "WEB_NOT_ALLOWED": "웹 조립(build_web)에서 부를 수 없는 함수 — 사전 단계 실행(run_start_request)은 워커가 한다",
    "SCREEN_NOT_READY": "그 화면을 여는 대기 지점이 아님",
    "INVALID_SCREEN": "없는 화면 번호",
    "INVALID_STATE": "지금 단계 · 진행 상태에서 받을 수 없는 명령",
    "BUSY": "다른 곳이 그 실행 건을 점유 중 — 잠시 뒤 다시",
    "MORE_LIMIT": "공고 추가 조회 한도 (1회 · 합계 20건)",
    "INVALID_ANNOUNCEMENT": "후보에 없는 공고",
    "ANNOUNCEMENT_BLOCKED": "자격 불통과로 막힌 공고 — 그 실행 건에서 다시 고를 수 없음 (추가 조회에서 내용이 바뀌면 풀림)",
    "NO_SELECTION": "재작성 선택 없음",
    "INVALID_ORDER": "목록에 없는 재작성 지시 · 묶음 이름 · 화면에 맞지 않는 층",
    "INVALID_ACTION": "잘못된 동작",
    "E-G2-LIMIT": "재작성 기회 소진",
    "NOT_ACTIVE": "진행 중이 아닌 실행 건을 중단 (내부 — abort_project가 받는다)",
    # 산출물 파일 (확장, 결정 0023) — 메시지(detail)에 키 · 파일 이름 · 계정을 넣지 않는다
    "FILE_NOT_FOUND": "그 실행 건의 파일이 아님 · 키 규칙 위반 · 저장소에 없음 · 내용이 저장 값(sha256)과 다름 (구분하지 않음)",
    "FILE_STORE_UNAVAILABLE": "파일 저장소 설정 없음 — 웹 조립에 SBRAIN_ARTIFACT_ROOT(절대 경로)가 없음",
    "FILE_DELETION_NOT_FOUND": "없는 파일 삭제 대기열 줄",
}


def message(code: str, **slots: str) -> str:
    text = ERROR_CODES[code].message
    for k, v in slots.items():
        text = text.replace("{" + k + "}", v)
    return text


class OrchestratorError(Exception):
    pass


class FormatError(OrchestratorError):
    """응답 형식 오류. tools가 스키마 검사에서 올리거나 Task의 parse 함수가 올린다. tools가 재시도한다.

    호출처가 응답을 받고도 쓸 수 없어 올릴 때(빈 응답 등)는 그 응답의 토큰 사용량(usage)을 실어 비용을 남긴다.
    """

    def __init__(self, message: str = "", *, usage: Any = None) -> None:
        super().__init__(message)
        self.usage = usage


class ProviderError(OrchestratorError):
    """LLM · 검색 호출처가 올리는 오류. status로 오류 종류를 분류한다."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ToolCallExhausted(OrchestratorError):
    """재시도를 다 쓴 호출. Task가 받아 대체 경로로 가거나(T-C2 · T-V2), Orchestrator가 재개한다.

    partial (확장, 선택): 재시도를 다 쓰기 전까지 Task가 받은 결과. 입력 하나를 PARTIAL로 연결한 Task가 다시 올리며
    싣는다 — 엔진이 재개를 예약할 때만 '<taskId>.partial'로 저장하고, 재개하면 그 입력에 넣는다. 내용이라 예외
    메시지 · str · repr에 넣지 않는다(생성 인자로 super에 넘기지 않음).
    """

    def __init__(self, *, error: CallError, error_kind: ErrorKind, tries: int, call_id: str, detail: str = "",
                 partial: dict[str, Any] | None = None) -> None:
        super().__init__(f"{error}/{error_kind} after {tries} tries: {detail}")
        self.error = error
        self.error_kind = error_kind
        self.tries = tries
        self.call_id = call_id
        self.detail = detail
        self.partial = partial


class ContractError(OrchestratorError):
    """Task가 규격에 맞지 않는 출력을 돌려줌."""


class ResourceNotFound(OrchestratorError):
    """Task가 찾는 외부 대상(예: 고른 공고)이 호출처에 없음 (확장).

    재시도할 오류가 아니라 호출 결과다. 호출 함수는 '없음'을 예외가 아닌 값으로 돌려주어 tools가 성공한 호출로 기록하고
    재시도하지 않게 하며, 그 값을 받은 Task가 이 예외를 올린다. 실패 정책(FailurePolicy.rescue_segments)이 흐름에
    넘기도록 정한 단계면 엔진이 '대상없음'으로 분류해 Flow.on_rescue에 넘기고, 그 밖의 단계에서는 다른 예외처럼 운영
    오류다. 메시지에 주소 · 요청 · 응답 본문 · 입력 값(대상 ID 등)을 넣지 않는다.
    """


class FileRejected(OrchestratorError):
    """파일 창구(tools.files)가 받지 않는 요청 (확장, 입력 오류 — 재시도하지 않는다).

    이름 · 형식 · 크기 규칙 위반(저장소를 부르지 않음), 실행 건이 '실행'이 아닐 때의 넣기, 다른 실행 건 파일 읽기.
    메시지에는 어긴 규칙 종류 · 크기 숫자만 싣는다 — 파일 이름 · 키 · 내용을 넣지 않는다.
    """

    error_kind = "입력"


class CommandError(OrchestratorError):
    """사용자 명령을 받을 수 없음 (상태 불일치 · 선택 불가 등)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class StoreConflict(OrchestratorError):
    """실행 점유(잠금)를 갖지 않은 쪽이 저장하려 함."""


class ProjectRunExists(OrchestratorError):
    """프로젝트에 이미 실행 건이 있음 (확장). 프로젝트 1건에 실행 건은 최대 1건 — 새로 시작은 새 프로젝트로 한다."""


class FileDeletionNotFound(OrchestratorError):
    """없는 파일 삭제 대기열 줄 (확장, 결정 0023). 메시지에 ID를 넣지 않는다."""


class FileDeletionNotGivenUp(OrchestratorError):
    """'포기'가 아닌 파일 삭제 대기열 줄을 다시 시도하려 함 (확장, 결정 0023). 메시지에 ID를 넣지 않는다."""
