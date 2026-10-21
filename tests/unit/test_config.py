from pathlib import Path

import pytest
from pydantic import ValidationError

from aura_agent.config import Settings


def make(**overrides) -> Settings:
    return Settings(_env_file=None, service_key="x" * 32, **overrides)


def test_defaults_match_phase1_plan():
    s = make()
    assert s.llm_provider == "ollama"
    assert s.llm_model == "qwen3.6:35b-a3b"
    assert s.llm_think is False
    assert s.checkpointer == "sqlite"
    assert s.cache == "memory"


def test_service_key_is_required():
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_service_key_too_short():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, service_key="short")


def test_service_key_hidden_in_repr():
    assert "x" * 32 not in repr(make())


def test_openai_compatible_needs_base_url():
    with pytest.raises(ValidationError):
        make(llm_provider="openai_compatible")
    assert make(llm_provider="openai_compatible", llm_base_url="http://gpu:8000/v1").llm_base_url


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        make(llm_provider="gpt")


def test_env_example_parses(tmp_path, monkeypatch):
    # .env.example ต้องโหลดได้จริง รวมถึง comment ท้ายบรรทัด
    monkeypatch.chdir(tmp_path)
    example = (Path(__file__).parents[2] / ".env.example").read_text(encoding="utf-8")
    (tmp_path / ".env").write_text(example, encoding="utf-8")
    s = Settings()
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.llm_think is False
