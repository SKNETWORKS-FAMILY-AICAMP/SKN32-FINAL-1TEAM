"""app/pipeline_stages.classify_error_kind — 실제 Agent 예외가 error_kind를 실어 오면 키워드 추측보다 그 값을 쓴다."""
from app import pipeline_stages as ps


def test_classify_error_kind_prefers_declared_error_kind_over_keywords():
    """[2026-09-29 신규, 프론트 요청사항 3차 B-3] 실제 Agent가 붙으면 Orchestration
    tools.llm이 올리는 예외(예: ToolCallExhausted)가 error_kind 속성을 이미 실어서 온다
    — 메시지 키워드로 다시 추측하지 말고 그 값을 그대로 써야 한다. 아래 예외는 메시지에
    '크레딧'(운영 키워드)이 들어있지만 error_kind='입력'을 명시적으로 실어 보냈으므로,
    분류 결과는 '입력'이어야 한다(키워드 추측이 이겼다면 '운영'이 나왔을 것)."""

    class _FakeToolCallExhausted(Exception):
        def __init__(self, message, error_kind):
            super().__init__(message)
            self.error_kind = error_kind

    exc = _FakeToolCallExhausted('크레딧 관련 입력값이 스키마와 안 맞음', ps.ERROR_KIND_INPUT)
    assert ps.classify_error_kind(exc) == ps.ERROR_KIND_INPUT
