"""실행별 KIET 검색 연결 — 위치(엔진 밖) · 스위치 격리 (SB-360 spec 3.1 · 3.2 · 3.4). 네트워크 없음.

- 연결 코드는 agents/partner_sw/market_research.py에 있고 엔진(orchestrator/)은 담당자 코드 · requests를 불러오지 않는다.
- 테스트에서는 환경 변수 · .env에 켜는 값이 있어도 스위치가 꺼진다(conftest 자동 장치).
"""
from __future__ import annotations

import pathlib
import re

from conftest import isolate_kiet_search
from worker_helpers import projects

from sbrain import env
from sbrain.agents.partner_sw import market_research
from sbrain.agents.stubs import FakeLLM
from sbrain.bootstrap import build_app

ORCHESTRATOR_DIR = pathlib.Path(__file__).resolve().parents[1] / "sbrain" / "orchestrator"


def test_engine_has_no_kiet_connector_and_no_partner_or_requests_imports():
    assert not (ORCHESTRATOR_DIR / "market_research.py").exists()
    pattern = re.compile(r"^\s*(from|import)\s+(\S*partner_sw\S*|\S*partner_bv\S*|requests)\b", re.M)
    found = [f.name for f in ORCHESTRATOR_DIR.rglob("*.py") if pattern.search(f.read_text(encoding="utf-8"))]
    assert found == []


def test_switch_is_off_in_tests_even_if_env_or_env_file_turns_it_on(monkeypatch, tmp_path, db):
    assert market_research.kiet_search_enabled() is False                         # 자동 장치가 끈 상태로 시작
    env_file = tmp_path / ".env"
    env_file.write_text("SBRAIN_KIET_SEARCH=1\n", encoding="utf-8")
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", env_file)
    assert env.get_env("SBRAIN_KIET_SEARCH") is None                              # .env 값을 없는 것으로 본다
    monkeypatch.setenv("SBRAIN_KIET_SEARCH", "1")                                 # 개발 PC 환경 변수
    isolate_kiet_search(monkeypatch)                                              # 테스트 시작 때 자동 장치가 하는 일
    assert env.get_env("SBRAIN_KIET_SEARCH") is None
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    build_app(url, project_inputs=projects(1), llm=FakeLLM())
    assert market_research.kiet_search_enabled() is False


def test_switch_setter_is_a_process_value():
    market_research.set_kiet_search(True)
    assert market_research.kiet_search_enabled() is True
    market_research.set_kiet_search(False)
    assert market_research.kiet_search_enabled() is False
