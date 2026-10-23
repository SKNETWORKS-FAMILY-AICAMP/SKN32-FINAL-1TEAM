"""API 문서 주소(/docs · /redoc · /openapi.json)와 /test-db가 운영 기본값에서 닫혀 있는지 시험한다.

운영 서버에서 이 주소들이 로그인 없이 열려 있어 API 전체 목록(관리자 API 포함)이 공개되던 문제(2026-10-21 배포 후 점검)의 재발 방지.
ENABLE_API_DOCS=1일 때만 열리고, 닫혀 있어도 서비스(/health · 로그인 흐름)에는 영향이 없다.
"""
import pytest

from app import api_docs


@pytest.mark.parametrize('path', ['/docs', '/redoc', '/openapi.json', '/test-db'])
def test_docs_and_test_db_are_closed_by_default(client, path):
    assert client.get(path).status_code == 404


def test_health_still_works_when_docs_are_closed(client):
    res = client.get('/health')
    assert res.status_code == 200 and res.json() == {'status': 'ok'}


@pytest.mark.parametrize('value', ['', '0', 'false', 'no', 'off', ' ', 'nope'])
def test_docs_are_closed_unless_explicitly_enabled(value):
    env = {'ENABLE_API_DOCS': value}
    assert api_docs.api_docs_enabled(env) is False
    assert api_docs.docs_kwargs(env) == {'docs_url': None, 'redoc_url': None, 'openapi_url': None}
    assert api_docs.docs_kwargs({}) == {'docs_url': None, 'redoc_url': None, 'openapi_url': None}


@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', 'Yes', 'on', ' 1 '])
def test_docs_open_when_enabled(value):
    env = {'ENABLE_API_DOCS': value}
    assert api_docs.api_docs_enabled(env) is True
    assert api_docs.docs_kwargs(env) == {}   # FastAPI 기본값(/docs · /redoc · /openapi.json)을 그대로 둔다


def test_enabled_app_really_serves_docs(monkeypatch):
    """켜짐 값으로 만든 앱은 문서가 실제로 열린다(스위치가 FastAPI 인자까지 이어지는지)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv('ENABLE_API_DOCS', '1')
    open_app = FastAPI(**api_docs.docs_kwargs())
    assert TestClient(open_app).get('/openapi.json').status_code == 200

    monkeypatch.delenv('ENABLE_API_DOCS')
    closed_app = FastAPI(**api_docs.docs_kwargs())
    assert TestClient(closed_app).get('/openapi.json').status_code == 404
