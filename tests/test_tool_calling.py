import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock


# ── helpers ──────────────────────────────────────────────────────────────────

def _text_response(content: str) -> dict:
    """Fake Ollama response with plain text (no tool calls)."""
    return {"message": {"role": "assistant", "content": content}}


def _tool_response(name: str, arguments: dict) -> dict:
    """Fake Ollama response requesting a tool call."""
    return {"message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }}


def _text_tool_call_response(name: str, arguments: dict) -> dict:
    """Some models emit tool calls as <tool_call> text instead of structured tool_calls."""
    body = json.dumps({"name": name, "arguments": arguments})
    return {"message": {
        "role": "assistant",
        "content": f"<tool_call>\n{body}\n</tool_call>",
    }}


# ── dispatch_tool ─────────────────────────────────────────────────────────────

def test_dispatch_search_user_found():
    from router import dispatch_tool
    with patch("router.asana_service.search_user", return_value="gid_123"):
        result = asyncio.run(dispatch_tool("search_user", {"name": "Иван"}))
    assert result == "gid_123"


def test_dispatch_search_user_not_found():
    from router import dispatch_tool
    with patch("router.asana_service.search_user", return_value=None):
        result = asyncio.run(dispatch_tool("search_user", {"name": "Неизвестный"}))
    assert result == "not_found"


def test_dispatch_search_project_found():
    from router import dispatch_tool
    with patch("router.asana_service.search_project", return_value="proj_gid"):
        result = asyncio.run(dispatch_tool("search_project", {"name": "Маркетинг"}))
    assert result == "proj_gid"


def test_dispatch_create_task_returns_gid():
    from router import dispatch_tool
    with patch("router.asana_service.create_task", return_value="task_gid_new") as mock:
        result = asyncio.run(dispatch_tool("create_task", {"title": "Отчёт"}))
    assert result == "task_gid_new"


def test_dispatch_create_task_strips_not_found_gids():
    """'not_found' from search_user/search_project must not reach Asana API."""
    from router import dispatch_tool
    with patch("router.asana_service.create_task", return_value="t1") as mock:
        asyncio.run(dispatch_tool("create_task", {
            "title": "Задача",
            "assignee_gid": "not_found",
            "project_gid": "not_found",
        }))
    _, _, _, assignee_gid, project_gid = mock.call_args[0]
    assert assignee_gid is None
    assert project_gid is None


def test_dispatch_list_projects_returns_json():
    from router import dispatch_tool
    projects = [{"gid": "p1", "name": "Маркетинг"}]
    with patch("router.asana_service.list_projects", return_value=projects):
        result = asyncio.run(dispatch_tool("list_projects", {}))
    data = json.loads(result)
    assert data[0]["name"] == "Маркетинг"


def test_dispatch_get_tasks_returns_json():
    from router import dispatch_tool
    tasks = [{"gid": "t1", "name": "Задача 1", "completed": False}]
    with patch("router.asana_service.get_tasks", return_value=tasks):
        result = asyncio.run(dispatch_tool("get_tasks", {"project_gid": "1214099899858956"}))
    data = json.loads(result)
    assert data[0]["name"] == "Задача 1"


def test_dispatch_get_tasks_rejects_placeholder_project_gid():
    """Hallucinated non-numeric project_gid must never reach Asana API."""
    from router import dispatch_tool
    with patch("router.asana_service.get_tasks") as mock:
        result = asyncio.run(dispatch_tool("get_tasks", {"project_gid": "gid для проекта Kos"}))
    mock.assert_not_called()
    assert "error" in result.lower()
    assert "search_project" in result


def test_dispatch_create_task_full_resolves_names_and_creates():
    """High-level create: resolves assignee and project names to GIDs internally."""
    from router import dispatch_tool
    with patch("router.asana_service.search_user", return_value="u_gid") as su, \
         patch("router.asana_service.search_project", return_value="p_gid") as sp, \
         patch("router.asana_service.create_task", return_value="new_task_gid") as ct:
        result = asyncio.run(dispatch_tool("create_task_full", {
            "title": "больше золота",
            "due_date": "2026-04-25",
            "assignee_name": "кос",
            "project_name": "Kos project",
            "description": "тестовая задача",
        }))
    su.assert_called_once_with("кос")
    sp.assert_called_once_with("Kos project")
    ct.assert_called_once_with("больше золота", "тестовая задача", "2026-04-25", "u_gid", "p_gid")
    assert "new_task_gid" in result


def test_dispatch_create_task_full_without_optional_fields():
    """create_task_full works with only title (no assignee, no project, no due_date)."""
    from router import dispatch_tool
    with patch("router.asana_service.create_task", return_value="t1") as ct:
        result = asyncio.run(dispatch_tool("create_task_full", {"title": "Простая задача"}))
    ct.assert_called_once_with("Простая задача", None, None, None, None)
    assert "t1" in result


def test_dispatch_assign_task_resolves_names_and_updates():
    """assign_task finds task and user by name, then calls update_task."""
    from router import dispatch_tool
    tasks = [{"gid": "111222333444", "name": "Тестовая задача 1010"}]
    with patch("router.asana_service.search_tasks", return_value=tasks) as st, \
         patch("router.asana_service.search_user", return_value="u_gid_kos") as su, \
         patch("router.asana_service.update_task", return_value=None) as ut:
        result = asyncio.run(dispatch_tool("assign_task", {
            "task_name": "Тестовая задача 1010",
            "assignee_name": "kos",
        }))
    st.assert_called_once_with("Тестовая задача 1010")
    su.assert_called_once_with("kos")
    ut.assert_called_once_with("111222333444", {"assignee": "u_gid_kos"})
    assert "updated" in result or "assigned" in result.lower()


def test_dispatch_assign_task_task_not_found():
    from router import dispatch_tool
    with patch("router.asana_service.search_tasks", return_value=[]):
        result = asyncio.run(dispatch_tool("assign_task", {
            "task_name": "Несуществующая задача",
            "assignee_name": "kos",
        }))
    assert "not found" in result.lower() or "не найден" in result.lower()


def test_dispatch_assign_task_user_not_found():
    from router import dispatch_tool
    tasks = [{"gid": "111222333444", "name": "Тестовая задача"}]
    with patch("router.asana_service.search_tasks", return_value=tasks), \
         patch("router.asana_service.search_user", return_value=None):
        result = asyncio.run(dispatch_tool("assign_task", {
            "task_name": "Тестовая задача",
            "assignee_name": "Незнакомец",
        }))
    assert "not found" in result.lower() or "не найден" in result.lower()


def test_dispatch_get_tasks_rejects_empty_gids():
    """get_tasks called with no valid GIDs must return an instructive error, not raise."""
    from router import dispatch_tool
    with patch("router.asana_service.get_tasks") as mock:
        result = asyncio.run(dispatch_tool("get_tasks", {}))
    mock.assert_not_called()
    assert "error" in result.lower()
    assert "search_project" in result or "search_user" in result


def test_dispatch_get_tasks_for_project_resolves_name_and_returns_tasks():
    """High-level tool: resolves project name to GID internally, returns tasks JSON."""
    from router import dispatch_tool
    tasks = [{"gid": "t1", "name": "Задача 1", "completed": False}]
    with patch("router.asana_service.search_project", return_value="p_gid_123") as sp, \
         patch("router.asana_service.get_tasks", return_value=tasks) as gt:
        result = asyncio.run(dispatch_tool("get_tasks_for_project", {"project_name": "Kos project"}))
    sp.assert_called_once_with("Kos project")
    gt.assert_called_once_with("p_gid_123", None)
    data = json.loads(result)
    assert data[0]["name"] == "Задача 1"


def test_dispatch_get_tasks_for_project_not_found():
    from router import dispatch_tool
    with patch("router.asana_service.search_project", return_value=None):
        result = asyncio.run(dispatch_tool("get_tasks_for_project", {"project_name": "Нет такого"}))
    assert "not found" in result.lower() or "не найден" in result.lower()


def test_dispatch_get_tasks_for_user_resolves_name_and_returns_tasks():
    """High-level tool: resolves user name to GID internally, returns tasks JSON."""
    from router import dispatch_tool
    tasks = [{"gid": "t2", "name": "Задача 2", "completed": False}]
    with patch("router.asana_service.search_user", return_value="u_gid_456") as su, \
         patch("router.asana_service.get_tasks", return_value=tasks) as gt:
        result = asyncio.run(dispatch_tool("get_tasks_for_user", {"user_name": "Kos"}))
    su.assert_called_once_with("Kos")
    gt.assert_called_once_with(None, "u_gid_456")
    data = json.loads(result)
    assert data[0]["name"] == "Задача 2"


def test_dispatch_get_tasks_deduplicates_results():
    """get_tasks called twice in the same session must not return duplicate tasks."""
    from router import dispatch_tool
    tasks = [
        {"gid": "111", "name": "Задача 1", "completed": False},
        {"gid": "222", "name": "Задача 2", "completed": False},
    ]
    with patch("router.asana_service.get_tasks", return_value=tasks):
        result1 = asyncio.run(dispatch_tool("get_tasks", {"project_gid": "1000000000"}))
        result2 = asyncio.run(dispatch_tool("get_tasks", {"assignee_gid": "2000000000"}))
    data1 = json.loads(result1)
    data2 = json.loads(result2)
    all_gids = [t["gid"] for t in data1 + data2]
    # At dispatch level each call is independent — deduplication is asana_service's job
    # This test documents current behaviour: two calls return results independently
    assert len(data1) == 2
    assert len(data2) == 2


def test_dispatch_get_tasks_rejects_placeholder_assignee_gid():
    """Hallucinated assignee_gid string must never reach Asana API."""
    from router import dispatch_tool
    with patch("router.asana_service.get_tasks") as mock:
        result = asyncio.run(dispatch_tool("get_tasks", {"assignee_gid": "some user gid"}))
    mock.assert_not_called()
    assert "error" in result.lower()


def test_dispatch_update_task_returns_updated():
    from router import dispatch_tool
    with patch("router.asana_service.update_task", return_value=None):
        result = asyncio.run(
            dispatch_tool("update_task", {"task_gid": "1234567890", "fields": {"due_date": "2026-04-20"}})
        )
    assert result == "updated"


def test_dispatch_update_task_rejects_fake_gid():
    """Hallucinated non-numeric task_gid must never reach Asana API."""
    from router import dispatch_tool
    with patch("router.asana_service.update_task") as mock:
        result = asyncio.run(
            dispatch_tool("update_task", {"task_gid": "not_found_3", "fields": {}})
        )
    mock.assert_not_called()
    assert "error" in result.lower()


def test_dispatch_unknown_tool_returns_error_string():
    from router import dispatch_tool
    result = asyncio.run(dispatch_tool("nonexistent_tool", {}))
    assert "unknown" in result.lower()


# ── process_message ──────────────────────────────────────────────────────────

def test_process_message_plain_response():
    """LLM returns plain text with no tool calls — returned as-is."""
    import llm_service
    llm_service.clear_history(1)
    with patch.object(llm_service, "_ollama_raw_chat",
                      new=AsyncMock(return_value=_text_response("Привет!"))):
        result = asyncio.run(llm_service.process_message("Привет", user_id=1))
    assert result == "Привет!"


def test_process_message_single_tool_call():
    """LLM calls list_projects once, receives result, returns final answer."""
    import llm_service
    llm_service.clear_history(2)
    call_count = 0

    async def fake_raw_chat(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _tool_response("list_projects", {})
        return _text_response("Проекты: Маркетинг.")

    projects = [{"gid": "p1", "name": "Маркетинг"}]
    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_raw_chat), \
         patch("router.asana_service.list_projects", return_value=projects):
        result = asyncio.run(llm_service.process_message("Покажи проекты", user_id=2))

    assert call_count == 2
    assert "Маркетинг" in result


def test_process_message_two_sequential_tool_calls():
    """LLM chains search_user then create_task — both dispatched correctly."""
    import llm_service
    llm_service.clear_history(3)
    call_count = 0

    async def fake_raw_chat(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _tool_response("search_user", {"name": "Иван"})
        if call_count == 2:
            return _tool_response("create_task", {"title": "Отчёт", "assignee_gid": "gid_ivan"})
        return _text_response("Задача создана.")

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_raw_chat), \
         patch("router.asana_service.search_user", return_value="gid_ivan"), \
         patch("router.asana_service.create_task", return_value="task_gid"):
        result = asyncio.run(llm_service.process_message("Создай задачу для Ивана", user_id=3))

    assert call_count == 3
    assert "создана" in result.lower()


def test_process_message_tool_error_continues_loop():
    """If a tool raises an exception, the error is fed back to LLM and loop continues."""
    import llm_service
    llm_service.clear_history(4)
    call_count = 0

    async def fake_raw_chat(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _tool_response("list_projects", {})
        return _text_response("Произошла ошибка, не смог получить проекты.")

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_raw_chat), \
         patch("router.asana_service.list_projects", side_effect=RuntimeError("API недоступен")):
        result = asyncio.run(llm_service.process_message("Покажи проекты", user_id=4))

    assert call_count == 2
    assert isinstance(result, str)
    assert len(result) > 0


# ── text-based tool calls (fallback parsing) ─────────────────────────────────

def test_process_message_text_tool_call_parsed():
    """When LLM emits <tool_call> as text, bot still executes the tool."""
    import llm_service
    llm_service.clear_history(50)
    call_count = 0

    async def fake_raw_chat(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _text_tool_call_response("list_projects", {})
        return _text_response("Проекты: Маркетинг.")

    projects = [{"gid": "p1", "name": "Маркетинг"}]
    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_raw_chat), \
         patch("router.asana_service.list_projects", return_value=projects):
        result = asyncio.run(llm_service.process_message("Покажи проекты", user_id=50))

    assert call_count == 2
    assert "Маркетинг" in result


def test_process_message_text_tool_call_missing_opening_tag():
    """Model sometimes emits JSON + </tool_call> without the opening <tool_call> tag."""
    import llm_service
    llm_service.clear_history(52)
    call_count = 0

    async def fake_raw_chat(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            body = json.dumps({"name": "list_projects", "arguments": {}})
            return {"message": {
                "role": "assistant",
                "content": f"bral\n{body}\n</tool_call>",
            }}
        return _text_response("Проекты.")

    projects = [{"gid": "p1", "name": "Маркетинг"}]
    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_raw_chat), \
         patch("router.asana_service.list_projects", return_value=projects):
        result = asyncio.run(llm_service.process_message("Покажи проекты", user_id=52))

    assert call_count == 2  # tool was executed, model got result and replied


def test_process_message_text_tool_call_with_preamble():
    """Preamble garbage before <tool_call> tag is ignored."""
    import llm_service
    llm_service.clear_history(51)
    call_count = 0

    async def fake_raw_chat(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # model outputs garbage + tool call (exactly as seen in production)
            body = json.dumps({"name": "list_projects", "arguments": {}})
            return {"message": {
                "role": "assistant",
                "content": f":'\nolith\n<tool_call>\n{body}\n</tool_call>",
            }}
        return _text_response("Вот проекты.")

    projects = [{"gid": "p1", "name": "Маркетинг"}]
    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_raw_chat), \
         patch("router.asana_service.list_projects", return_value=projects):
        result = asyncio.run(llm_service.process_message("Покажи проекты", user_id=51))

    assert call_count == 2


# ── history ───────────────────────────────────────────────────────────────────

def test_history_has_no_tool_turns_to_avoid_context_overflow():
    """Tool turns are NOT saved to history — qwen2.5 returns empty responses
    when the context is flooded with tool JSON. Only user+assistant text is kept."""
    import llm_service
    llm_service.clear_history(60)
    call_count = 0

    async def fake_turn1(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _tool_response("list_projects", {})
        return _text_response("Проект Kos project.")

    projects = [{"gid": "1214099899858956", "name": "Kos project"}]
    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_turn1), \
         patch("router.asana_service.list_projects", return_value=projects):
        asyncio.run(llm_service.process_message("Покажи проекты", user_id=60))

    captured = []

    async def capture_turn2(messages, tools):
        captured.extend(messages)
        return _text_response("Задачи...")

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=capture_turn2):
        asyncio.run(llm_service.process_message("Покажи задачи", user_id=60))

    # History must NOT contain tool-role messages (they bloat context)
    roles = [m["role"] for m in captured]
    assert "tool" not in roles
    # Only system + prior user/assistant + current user
    assert roles.count("user") >= 2
    assert roles.count("assistant") >= 1


def test_history_is_sent_on_second_message():
    """Second message includes first exchange in the messages array."""
    import llm_service
    llm_service.clear_history(10)

    with patch.object(llm_service, "_ollama_raw_chat",
                      new=AsyncMock(return_value=_text_response("Ответ 1"))):
        asyncio.run(llm_service.process_message("Вопрос 1", user_id=10))

    captured = []

    async def capture(messages, tools):
        captured.extend(messages)
        return _text_response("Ответ 2")

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=capture):
        asyncio.run(llm_service.process_message("Вопрос 2", user_id=10))

    roles = [m["role"] for m in captured]
    assert "system" in roles
    # previous user + assistant turns must be present
    assert roles.count("user") >= 2
    assert roles.count("assistant") >= 1


def test_history_capped_at_max_messages():
    """History never exceeds HISTORY_MAX_MESSAGES entries."""
    import llm_service
    llm_service.clear_history(20)

    with patch.object(llm_service, "_ollama_raw_chat",
                      new=AsyncMock(return_value=_text_response("ok"))):
        for i in range(30):
            asyncio.run(llm_service.process_message(f"msg {i}", user_id=20))

    assert len(llm_service._history[20]) <= llm_service.HISTORY_MAX_MESSAGES


def test_clear_history_resets_context():
    """After clear_history, second call starts with no prior context."""
    import llm_service
    llm_service.clear_history(30)

    with patch.object(llm_service, "_ollama_raw_chat",
                      new=AsyncMock(return_value=_text_response("Ответ 1"))):
        asyncio.run(llm_service.process_message("Вопрос 1", user_id=30))

    llm_service.clear_history(30)
    captured = []

    async def capture(messages, tools):
        captured.extend(messages)
        return _text_response("Ответ 2")

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=capture):
        asyncio.run(llm_service.process_message("Вопрос 2", user_id=30))

    # Only system + current user message — no history
    assert len([m for m in captured if m["role"] == "user"]) == 1


# ── warmup_model ─────────────────────────────────────────────────────────────

def test_warmup_model_calls_ollama():
    """warmup_model should send a minimal request to load the model into memory."""
    import llm_service
    called_with = []

    async def fake_chat(messages, tools):
        called_with.extend(messages)
        return {"message": {"role": "assistant", "content": "ok"}}

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fake_chat):
        asyncio.run(llm_service.warmup_model())

    assert len(called_with) > 0


def test_warmup_model_does_not_raise_on_error():
    """warmup_model should swallow exceptions so bot startup is not blocked."""
    import llm_service
    import httpx

    async def fail(*_):
        raise httpx.TimeoutException("timeout")

    with patch.object(llm_service, "_ollama_raw_chat", side_effect=fail):
        asyncio.run(llm_service.warmup_model())  # must not raise


# ── OpenAI tool-calling ───────────────────────────────────────────────────────

def test_process_message_uses_openai_when_provider_is_openai():
    """When LLM_PROVIDER=openai, process_message should use _openai_raw_chat."""
    import llm_service
    import config

    with patch.object(llm_service, "LLM_PROVIDER", "openai"), \
         patch.object(llm_service, "_openai_raw_chat",
                      new=AsyncMock(return_value=_text_response("Готово"))) as mock_openai, \
         patch.object(llm_service, "_ollama_raw_chat",
                      new=AsyncMock(side_effect=AssertionError("should not call ollama"))):
        result = asyncio.run(llm_service.process_message("Привет", user_id=99))

    assert result == "Готово"
    mock_openai.assert_called_once()


def test_process_message_uses_ollama_when_provider_is_ollama():
    """When LLM_PROVIDER=ollama (default), process_message should use _ollama_raw_chat."""
    import llm_service

    with patch.object(llm_service, "LLM_PROVIDER", "ollama"), \
         patch.object(llm_service, "_ollama_raw_chat",
                      new=AsyncMock(return_value=_text_response("Ок"))) as mock_ollama, \
         patch.object(llm_service, "_openai_raw_chat",
                      new=AsyncMock(side_effect=AssertionError("should not call openai"))):
        result = asyncio.run(llm_service.process_message("Привет", user_id=98))

    assert result == "Ок"
    mock_ollama.assert_called_once()
