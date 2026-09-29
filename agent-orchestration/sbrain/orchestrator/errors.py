"""오류 코드(기능정의서 시트 6)와 Orchestrator 예외."""
from __future__ import annotations

from dataclasses import dataclass

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
    ErrorCode("E-G1-UNPARSED", "G-01", "이 공고는 자격요건 자동 확인이 어렵습니다. 공고문을 직접 확인해주세요.", "undecidable=true"),
    ErrorCode("E-G1-REJECT", "G-01", "이 공고는 {사유}로 신청이 어렵습니다. 다른 공고를 보여드릴까요?", "실행 차단"),
    ErrorCode("E-C1-REQUIRED", "T-C1", "필수 항목을 입력해주세요: {누락 항목}", "폼 단계 차단"),
    ErrorCode("E-C1-DOC", "T-C1", "{파일명}의 내용을 읽지 못해 참고 자료에서 제외했습니다. 나머지 정보로 계속 진행합니다.", "해당 문서 제외"),
    ErrorCode("E-C3-FORM", "T-C3", "", "분해 실패로 처리하고 오류 기록"),
    ErrorCode("E-B1-ENTRY", "T-B1", "", "재수행 후 그대로 보냄, codeCheck.total=0"),
    ErrorCode("E-B1-DEP", "T-B1", "", "재수행 후 그대로 보냄, 점수 반영"),
    ErrorCode("E-V1-EVIDENCE", "T-V1", "", "감점 무효 처리"),
    ErrorCode("E-V1-VARIANCE", "T-V1", "", "varianceFlag=true"),
    ErrorCode("E-V2-PARSE", "T-V2", "", "해당 항목만 미충족"),
    ErrorCode("E-V2-NOFEATURE", "T-V2", "", "판정 보류, 오류 기록"),
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
    # 확장(잠정) — 기준 문서에 T-C2 전체 실패 처리가 없다. T-C1과 같이 다시 시도 안내.
    ErrorCode("X-C2-FAIL", "T-C2", "잠시 문제가 있었습니다. 다시 시도해주세요.", "확장(잠정): 사전 단계라 재개 없이 다시 시도 안내"),
]}


def message(code: str, **slots: str) -> str:
    text = ERROR_CODES[code].message
    for k, v in slots.items():
        text = text.replace("{" + k + "}", v)
    return text


class OrchestratorError(Exception):
    pass


class FormatError(OrchestratorError):
    """응답 형식 오류. tools가 스키마 검사에서 올리거나 Task의 parse 함수가 올린다. tools가 재시도한다."""


class ProviderError(OrchestratorError):
    """LLM · 검색 호출처가 올리는 오류. status로 오류 종류를 분류한다."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ToolCallExhausted(OrchestratorError):
    """재시도를 다 쓴 호출. Task가 받아 대체 경로로 가거나(T-C2 · T-V2), Orchestrator가 재개한다."""

    def __init__(self, *, error: CallError, error_kind: ErrorKind, tries: int, call_id: str, detail: str = "") -> None:
        super().__init__(f"{error}/{error_kind} after {tries} tries: {detail}")
        self.error = error
        self.error_kind = error_kind
        self.tries = tries
        self.call_id = call_id
        self.detail = detail


class ContractError(OrchestratorError):
    """Task가 규격에 맞지 않는 출력을 돌려줌."""


class CommandError(OrchestratorError):
    """사용자 명령을 받을 수 없음 (상태 불일치 · 선택 불가 등)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class StoreConflict(OrchestratorError):
    """실행 점유(잠금)를 갖지 않은 쪽이 저장하려 함."""
