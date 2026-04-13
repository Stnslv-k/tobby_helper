import importlib
import sys
import pytest


def _reload_config(monkeypatch, **env):
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    if "config" in sys.modules:
        del sys.modules["config"]
    import config
    return config


def test_required_vars_loaded(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="tok",
        ADMIN_TELEGRAM_ID="12345",
        ASANA_PAT="pat",
        ASANA_WORKSPACE_GID="ws",
    )
    assert cfg.TELEGRAM_BOT_TOKEN == "tok"
    assert cfg.ADMIN_TELEGRAM_ID == 12345
    assert cfg.ASANA_PAT == "pat"
    assert cfg.ASANA_WORKSPACE_GID == "ws"


def test_llm_provider_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="tok",
        ADMIN_TELEGRAM_ID="1",
        ASANA_PAT="p",
        ASANA_WORKSPACE_GID="w",
    )
    assert cfg.LLM_PROVIDER == "ollama"


def test_deadline_notify_days_parsed(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="tok",
        ADMIN_TELEGRAM_ID="1",
        ASANA_PAT="p",
        ASANA_WORKSPACE_GID="w",
        DEADLINE_NOTIFY_DAYS="1,3",
    )
    assert cfg.DEADLINE_NOTIFY_DAYS == [1, 3]


def test_deadline_notify_days_default(monkeypatch):
    monkeypatch.delenv("DEADLINE_NOTIFY_DAYS", raising=False)
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="tok",
        ADMIN_TELEGRAM_ID="1",
        ASANA_PAT="p",
        ASANA_WORKSPACE_GID="w",
    )
    assert cfg.DEADLINE_NOTIFY_DAYS == [1, 2]
