""".env 파일 읽기 (sbrain/env.py), OpenAI 호출처의 API 키, 테스트의 공고 서버 주소 격리, 설치 의존성(pyproject = requirements)."""
from __future__ import annotations

import os

from conftest import isolate_notice_api
from notice_fake import FAKE_URL
from webdb import create_web_tables
from worker_helpers import STUB_MODULE, notice_fns, projects

from sbrain import env
from sbrain.agents.stubs import FakeLLM
from sbrain.bootstrap import build_app
from sbrain.orchestrator.openai_provider import OpenAIProvider
from sbrain.store_sql import create_orchestrator_tables, create_sqlite_engine


def write_env(tmp_path, text: str, encoding: str = "utf-8"):
    p = tmp_path / ".env"
    p.write_text(text, encoding=encoding)
    return p


def test_reads_values_as_written(tmp_path):
    p = write_env(tmp_path, "\n".join([
        "# 주석",
        "export A=1",
        'B="두 단어 # 주석 아님"',
        "C=pa$$word${X}",          # 치환하지 않는다
        "D=",                      # 빈 값은 없는 것으로
        "E=값  # 줄 끝 주석",
    ]))
    assert env.read_env_file(p) == {"A": "1", "B": "두 단어 # 주석 아님", "C": "pa$$word${X}", "E": "값"}


def test_bom_does_not_stick_to_first_key(tmp_path):
    p = write_env(tmp_path, "FIRST=1\n", encoding="utf-8-sig")
    assert env.read_env_file(p) == {"FIRST": "1"}


def test_missing_file_is_empty(tmp_path):
    assert env.read_env_file(tmp_path / "없음.env") == {}
    assert env.get_env("SBRAIN_ENV_TEST_KEY", "기본", path=tmp_path / "없음.env") == "기본"


def test_environment_wins_over_file(tmp_path, monkeypatch):
    p = write_env(tmp_path, "SBRAIN_ENV_TEST_KEY=파일\n")
    monkeypatch.delenv("SBRAIN_ENV_TEST_KEY", raising=False)
    assert env.get_env("SBRAIN_ENV_TEST_KEY", path=p) == "파일"
    monkeypatch.setenv("SBRAIN_ENV_TEST_KEY", "환경")
    assert env.get_env("SBRAIN_ENV_TEST_KEY", path=p) == "환경"
    monkeypatch.setenv("SBRAIN_ENV_TEST_KEY", "")            # 빈 환경 변수는 없는 것으로
    assert env.get_env("SBRAIN_ENV_TEST_KEY", path=p) == "파일"


def test_get_env_does_not_touch_environ(tmp_path, monkeypatch):
    p = write_env(tmp_path, "SBRAIN_ENV_TEST_KEY=파일\n")
    monkeypatch.delenv("SBRAIN_ENV_TEST_KEY", raising=False)
    env.get_env("SBRAIN_ENV_TEST_KEY", path=p)
    assert "SBRAIN_ENV_TEST_KEY" not in os.environ


def test_openai_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", write_env(tmp_path, "OPENAI_API_KEY=sk-test-from-file\n"))
    assert OpenAIProvider()._client.api_key == "sk-test-from-file"     # 클라이언트만 만든다. 호출하지 않음
    assert OpenAIProvider(api_key="sk-test-given")._client.api_key == "sk-test-given"


# ── 테스트 격리 · 설치 설정 ─────────────────────────────
def test_tests_never_see_notice_url_from_environment_or_env_file(monkeypatch, tmp_path):
    """개발 PC의 환경 변수나 agent-orchestration/.env에 SBRAIN_NOTICE_API_URL이 있어도 테스트는 실제 공고 서버를 부르지 않는다.

    conftest의 자동 장치(isolate_notice_api)가 이 키만 없는 것으로 본다. 다른 키는 그대로 읽는다.
    """
    db_url = f"sqlite:///{(tmp_path / 'from-file.db').as_posix()}"
    engine = create_sqlite_engine(tmp_path / "from-file.db", fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    env_file = tmp_path / ".env"
    env_file.write_text(f"SBRAIN_NOTICE_API_URL={FAKE_URL}\nSBRAIN_DB_URL={db_url}\n"
                        "SBRAIN_ENV_TEST_KEY=파일\n", encoding="utf-8")
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", env_file)
    for key in ("SBRAIN_DB_URL", "SBRAIN_ENV_TEST_KEY"):                          # 이 시험의 .env 값만 보이게
        monkeypatch.delenv(key, raising=False)
    assert env.get_env("SBRAIN_NOTICE_API_URL") is None                          # 자동 장치가 이미 켜져 있다
    monkeypatch.setenv("SBRAIN_NOTICE_API_URL", FAKE_URL)                         # 개발 PC 환경 변수
    isolate_notice_api(monkeypatch)                                               # 테스트 시작 때 자동 장치가 하는 일
    assert env.get_env("SBRAIN_NOTICE_API_URL") is None
    assert env.get_env("SBRAIN_DB_URL") == db_url and env.get_env("SBRAIN_ENV_TEST_KEY") == "파일"
    assert env.read_env_file(env_file) == {"SBRAIN_DB_URL": db_url, "SBRAIN_ENV_TEST_KEY": "파일"}
    app = build_app(project_inputs=projects(1), llm=FakeLLM())                    # DB 주소는 .env에서 읽는다
    assert notice_fns(app) == (STUB_MODULE, STUB_MODULE)


def test_pyproject_matches_requirements():
    """웹 프로세스가 설치하는 패키지 의존성 = requirements.txt (pytest는 test 선택 의존성)."""
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = [ln.strip() for ln in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]
    assert sorted(project["dependencies"] + project["optional-dependencies"]["test"]) == sorted(pins)
