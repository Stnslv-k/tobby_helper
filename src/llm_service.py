import json
import logging
import re
from datetime import date

import httpx

from config import (
    LLM_PROVIDER,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = {"create_task", "update_task", "read_tasks", "list_projects", "unknown"}

_EMPTY_INTENT: dict = {
    "action": "unknown",
    "title": None,
    "description": None,
    "due_date": None,
    "assignee": None,
    "project": None,
    "task_id": None,
    "update_fields": None,
}

_INTENT_SYSTEM = """\
Ты парсер команд для управления задачами в Asana.
Извлеки намерение и верни ТОЛЬКО валидный JSON:
{{
  "action": "create_task | update_task | read_tasks | list_projects | unknown",
  "title": "название задачи или null",
  "description": "описание или null",
  "due_date": "YYYY-MM-DD или null",
  "assignee": "имя исполнителя на русском или null",
  "project": "название проекта на русском или null",
  "task_id": "gid задачи для обновления или null",
  "update_fields": {{"due_date": "...", "assignee": "..."}} или null
}}
Сегодня: {today}.
Относительные даты: завтра=+1 день, послезавтра=+2 дня — вычисляй от сегодня.
Отвечай ТОЛЬКО JSON без markdown и пояснений."""

_CHAT_SYSTEM = (
    "Ты помощник команды. Отвечай кратко, по-русски. "
    "Ты умеешь создавать, читать и обновлять задачи в Asana. "
    "Если вопрос не про задачи — вежливо объясни, что умеешь."
)


def _intent_system() -> str:
    return _INTENT_SYSTEM.format(today=date.today().isoformat())


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    # Remove opening fence (```json or ```) with optional newline
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    # Remove closing fence
    raw = re.sub(r"\n?```\s*$", "", raw)
    return raw.strip()


async def _ollama_complete(system: str, user: str, json_mode: bool = False) -> str:
    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    payload: dict = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def _openai_complete(system: str, user: str, json_mode: bool = False) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _complete(system: str, user: str, json_mode: bool = False) -> str:
    if LLM_PROVIDER == "openai":
        return await _openai_complete(system, user, json_mode)
    return await _ollama_complete(system, user, json_mode)


async def extract_intent(text: str) -> dict:
    for attempt in range(3):
        try:
            raw = await _complete(_intent_system(), text, json_mode=True)
            raw = _strip_fences(raw)
            parsed = json.loads(raw)
            if parsed.get("action") not in _ALLOWED_ACTIONS:
                parsed["action"] = "unknown"
            return {k: parsed.get(k, v) for k, v in _EMPTY_INTENT.items()}
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Intent parse attempt %d failed: %s", attempt + 1, e)
        except Exception as e:
            logger.error("LLM error: %s", e)
            break
    return {**_EMPTY_INTENT}


async def chat_reply(text: str) -> str:
    try:
        return await _complete(_CHAT_SYSTEM, text)
    except Exception as e:
        logger.error("Chat reply failed: %s", e)
        return "Не удалось получить ответ. Попробуй ещё раз."


# ── Tool calling (Ollama) ────────────────────────────────────────────────────

_ASANA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_user",
            "description": "Найти пользователя в Asana по имени. Возвращает gid или 'not_found'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Имя пользователя по-русски"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project",
            "description": "Найти проект в Asana по названию. Возвращает gid или 'not_found'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название проекта по-русски"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Создать новую задачу в Asana.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название задачи"},
                    "description": {"type": "string", "description": "Описание задачи"},
                    "due_date": {"type": "string", "description": "Срок выполнения YYYY-MM-DD"},
                    "assignee_gid": {"type": "string", "description": "GID исполнителя из search_user"},
                    "project_gid": {"type": "string", "description": "GID проекта из search_project"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Получить список задач из Asana по проекту или исполнителю.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_gid": {"type": "string", "description": "GID проекта"},
                    "assignee_gid": {"type": "string", "description": "GID исполнителя"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "Получить список всех проектов в рабочем пространстве Asana.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_users",
            "description": "Получить список всех пользователей в рабочем пространстве Asana с их именами и gid.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Обновить поля задачи в Asana (срок, исполнитель).",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_gid": {"type": "string", "description": "GID задачи"},
                    "fields": {
                        "type": "object",
                        "description": "Поля для обновления",
                        "properties": {
                            "due_date": {"type": "string", "description": "Новый срок YYYY-MM-DD"},
                            "assignee": {"type": "string", "description": "GID нового исполнителя"},
                        },
                    },
                },
                "required": ["task_gid", "fields"],
            },
        },
    },
]

_TOOL_SYSTEM = (
    "Ты помощник команды для управления задачами в Asana. "
    "Сегодня: {today}. "
    "Отвечай кратко по-русски. "
    "ПРАВИЛА:\n"
    "1. Никогда не выдумывай GID — используй только те, что вернули инструменты.\n"
    "2. Если search_user вернул 'not_found' — создай задачу без исполнителя и сообщи об этом.\n"
    "3. Если search_project вернул 'not_found' — создай задачу без проекта и сообщи об этом.\n"
    "4. Для update_task task_gid должен быть числом из Asana — не придумывай его.\n"
    "5. Если вопрос не про задачи — вежливо объясни, что умеешь."
)


def _tool_system() -> str:
    return _TOOL_SYSTEM.format(today=date.today().isoformat())


async def _ollama_raw_chat(messages: list, tools: list) -> dict:
    """POST to Ollama /api/chat with tools, return raw response dict."""
    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    payload: dict = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "tools": tools,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


HISTORY_MAX_MESSAGES = 20  # max user+assistant turns kept per user

_history: dict[int, list] = {}


def clear_history(user_id: int) -> None:
    _history.pop(user_id, None)


async def process_message(text: str, user_id: int = 0) -> str:
    """Process user message using Ollama tool calling loop with per-user history."""
    import router  # late import — avoids circular dependency

    prior = _history.get(user_id, [])
    messages: list = [
        {"role": "system", "content": _tool_system()},
        *prior,
        {"role": "user", "content": text},
    ]

    final_reply: str = "Не удалось получить ответ."

    for _ in range(10):  # cap iterations to prevent runaway loops
        response = await _ollama_raw_chat(messages, _ASANA_TOOLS)
        msg = response["message"]
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            final_reply = msg.get("content") or final_reply
            break

        # Append the assistant turn (with tool_calls) to the working messages
        messages.append(msg)

        # Execute every tool call in this turn
        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            # Ollama returns arguments as a dict; OpenAI returns a JSON string
            args = fn["arguments"] if isinstance(fn["arguments"], dict) else json.loads(fn["arguments"])
            try:
                result = await router.dispatch_tool(name, args)
            except Exception as e:
                logger.error("Tool %s raised: %s", name, e)
                result = f"error: {e}"

            messages.append({"role": "tool", "content": str(result)})
    else:
        final_reply = "Достигнуто максимальное число шагов."

    # Persist only plain user/assistant turns (skip system, tool, tool_calls turns)
    new_history = prior + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": final_reply},
    ]
    _history[user_id] = new_history[-HISTORY_MAX_MESSAGES:]

    return final_reply
