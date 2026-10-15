"""app/pipeline_stages.py의 순수 함수(상태 표시 변환, 오류 분류) 단위 테스트."""
from app import pipeline_stages as ps


def test_classify_error_kind_defaults_to_transient():
    assert ps.classify_error_kind(RuntimeError('그냥 실패했음')) == ps.ERROR_KIND_TRANSIENT


def test_classify_error_kind_detects_operational_keywords():
    assert ps.classify_error_kind(RuntimeError('API 연결이 끊어졌습니다')) == ps.ERROR_KIND_OPERATIONAL
    assert ps.classify_error_kind(RuntimeError('API 키 만료')) == ps.ERROR_KIND_OPERATIONAL
    assert ps.classify_error_kind(RuntimeError('크레딧이 부족합니다')) == ps.ERROR_KIND_OPERATIONAL
    assert ps.classify_error_kind(RuntimeError('401 Unauthorized')) == ps.ERROR_KIND_OPERATIONAL


def test_classify_error_kind_detects_input_keywords():
    assert ps.classify_error_kind(RuntimeError('입력값이 올바르지 않습니다')) == ps.ERROR_KIND_INPUT
    assert ps.classify_error_kind(RuntimeError('response validation failed')) == ps.ERROR_KIND_INPUT


def test_status_to_display_returns_none_for_missing_or_unknown_status():
    assert ps.status_to_display(None) is None
    assert ps.status_to_display('nonexistent_status') is None
    assert ps.status_to_display(ps.GENERATION_STATUS_FAILED) == '문제가 생겨 멈췄다'
