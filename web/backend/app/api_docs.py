"""API 문서 주소(`/docs` · `/redoc` · `/openapi.json`)를 열고 닫는 스위치.

운영에서는 이 주소가 로그인 없이 API 전체 목록(관리자 API 포함)을 보여 주므로 기본값은 **닫힘**이다.
개발 PC에서 Swagger를 쓰려면 환경 변수 `ENABLE_API_DOCS=1`(또는 true · yes · on)로 켠다(.env.example 참고).
"""
import os

_TRUE = {'1', 'true', 'yes', 'on'}


def api_docs_enabled(env=None) -> bool:
    """`ENABLE_API_DOCS`가 켜짐 값(1 · true · yes · on)이면 True. 비어 있거나 없으면 False."""
    source = os.environ if env is None else env
    return str(source.get('ENABLE_API_DOCS', '')).strip().lower() in _TRUE


def docs_kwargs(env=None) -> dict:
    """`FastAPI(**docs_kwargs())`에 넘길 인자 — 닫힘이면 세 주소를 모두 끈다(404)."""
    if api_docs_enabled(env):
        return {}
    return {'docs_url': None, 'redoc_url': None, 'openapi_url': None}
