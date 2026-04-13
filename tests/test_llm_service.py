import json
import sys
import pytest
from unittest.mock import AsyncMock, patch


def _reload(monkeypatch, provider="ollama"):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    for mod in ["config", "llm_service"]:
        if mod in sys.modules:
            del sys.modules[mod]
    import llm_service
    return llm_service


def test_extract_intent_ollama_returns_parsed_dict(monkeypatch):
    lm = _reload(monkeypatch, "ollama")
    expected = {
        "action": "create_task", "title": "Написать отчёт",
        "description": None, "due_date": "2026-04-20",
        "assignee": "Иван", "project": "Маркетинг",
        "task_id": None, "update_fields": None,
    }
    with patch.object(lm, "_ollama_complete", new=AsyncMock(return_value=json.dumps(expected))):
        import asyncio
        result = asyncio.run(lm.extract_intent("создай задачу для Ивана"))
    assert result["action"] == "create_task"
    assert result["assignee"] == "Иван"


def test_extract_intent_invalid_json_returns_unknown(monkeypatch):
    lm = _reload(monkeypatch, "ollama")
    with patch.object(lm, "_ollama_complete", new=AsyncMock(return_value="не JSON вообще")):
        import asyncio
        result = asyncio.run(lm.extract_intent("что-то"))
    assert result["action"] == "unknown"


def test_extract_intent_unknown_action_normalised(monkeypatch):
    lm = _reload(monkeypatch, "ollama")
    payload = {"action": "delete_everything", "title": None,
               "description": None, "due_date": None, "assignee": None,
               "project": None, "task_id": None, "update_fields": None}
    with patch.object(lm, "_ollama_complete", new=AsyncMock(return_value=json.dumps(payload))):
        import asyncio
        result = asyncio.run(lm.extract_intent("удали всё"))
    assert result["action"] == "unknown"


def test_extract_intent_openai_provider(monkeypatch):
    lm = _reload(monkeypatch, "openai")
    expected = {"action": "read_tasks", "title": None, "description": None,
                "due_date": None, "assignee": None, "project": "Разработка",
                "task_id": None, "update_fields": None}
    with patch.object(lm, "_openai_complete", new=AsyncMock(return_value=json.dumps(expected))):
        import asyncio
        result = asyncio.run(lm.extract_intent("задачи разработки"))
    assert result["action"] == "read_tasks"
    assert result["project"] == "Разработка"


def test_extract_intent_strips_markdown_fences(monkeypatch):
    lm = _reload(monkeypatch, "ollama")
    payload = {"action": "create_task", "title": "X", "description": None,
               "due_date": None, "assignee": None, "project": None,
               "task_id": None, "update_fields": None}
    wrapped = f"```json\n{json.dumps(payload)}\n```"
    with patch.object(lm, "_ollama_complete", new=AsyncMock(return_value=wrapped)):
        import asyncio
        result = asyncio.run(lm.extract_intent("создай задачу"))
    assert result["action"] == "create_task"
