"""공통 모델 기반과 열거형.

- 파이썬 필드는 snake_case, JSON은 기준 문서의 camelCase 이름을 그대로 쓴다.
- 기준 문서에 없는 필드는 ext()로 선언해 JSON 스키마에 x-extension 표시를 남긴다.
- 시각(datetime) 필드는 모두 시간대 있는 UTC로 맞춘다. 시간대 없는 값(옛 JSON · DB 값 · 테스트 값)은 UTC로 본다.
  JSON(.dump())에는 시간대 표시(Z)가 붙는다. 필드 이름 · JSON 이름은 그대로다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .clock import as_utc


class SBModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        protected_namespaces=(),
    )

    @field_validator("*", mode="after")
    @classmethod
    def _utc_datetime(cls, v: Any) -> Any:
        """시각 필드(선택 필드 포함)를 시간대 있는 UTC로 — 시간대가 없으면 UTC로 본다."""
        return as_utc(v) if isinstance(v, datetime) else v

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def ext(default: Any = ..., *, note: str = "", **kwargs: Any) -> Any:
    """기준 문서에 없는 확장 필드."""
    extra: dict[str, Any] = {"x-extension": True}
    if note:
        extra["x-note"] = note
    return Field(default, json_schema_extra=extra, **kwargs)


def extension_fields(model: type[BaseModel]) -> list[str]:
    """모델에서 확장으로 표시된 필드 이름(JSON 이름)."""
    names = []
    for name, info in model.model_fields.items():
        extra = info.json_schema_extra
        if isinstance(extra, dict) and extra.get("x-extension"):
            names.append(info.alias or name)
    return names


# ── 열거형 (시트 4 표기 그대로) ──────────────────────────────
Category = Literal["원페이지", "웹개발", "AI_API"]
ApplicantType = Literal["예비창업자", "개인사업자", "법인"]
AgentName = Literal["조율", "전략", "작성", "구현", "검증-1", "검증-2", "검수"]
FileFormat = Literal["docx", "hwp", "hwpx"]
ExtractStatus = Literal["성공", "부분", "실패"]
CollectionStatus = Literal["정상", "지연", "실패"]
FallbackMode = Literal["BM25단독", "임베딩단독", "마감임박순"]
Layer = Literal["document", "artifact"]
Phase = Literal["document", "overall"]
NextAction = Literal["진행가능", "재작성권유", "상한도달"]
UserAction = Literal["재작성", "진행"]
ReworkMode = Literal["재작성", "재수행"]
ReworkUnit = Literal["묶음", "Task", "섹션", "차트 1건", "표 1건", "부분", "안내 문서"]
Trigger = Literal["첫실행", "재작성", "재수행"]
KeptSide = Literal["전", "후"]
PrototypeKind = Literal["html", "svg-onepage"]
ImageFormat = Literal["png", "svg"]
JudgedBy = Literal["htmlParse", "svgTextParse"]
TokenType = Literal["수치금액", "날짜", "고유명사", "기능명"]
KeptReason = Literal["검증실패", "호출실패", "조기중단"]
ViolationType = Literal["서술형", "종결형", "금지표현", "분량초과"]
StyleType = Literal["개조식", "서술형"]
EndingRule = Literal["단정형", "평서형"]
ChartType = Literal["bar", "line", "pie"]
RunStep = Literal[
    "공고선택", "자격확인", "계획서작성", "문서평가", "프로토타입제작",
    "산출물확인", "종합평가", "표현검수", "결과물",
]
RunProgress = Literal["실행", "재개대기", "사용자대기", "실패", "완료", "중단"]
ScreenStatus = Literal["진행 중", "확인 필요", "문제 발생", "완료", "중단됨"]
RunPhase = Literal["setup", "document", "artifact", "review"]
CallError = Literal["호출실패", "응답지연", "형식오류"]
ErrorKind = Literal["일시", "입력", "운영"]
NotificationKind = Literal["문서평가", "산출물확인", "표현검수", "실패"]
FailureScope = Literal["실행", "재작성"]
