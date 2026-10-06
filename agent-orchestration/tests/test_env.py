""".env 파일 읽기 (sbrain/env.py)와 OpenAI 호출처의 API 키."""
from __future__ import annotations

import os

from sbrain import env
from sbrain.orchestrator.openai_provider import OpenAIProvider


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
