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
                    "name": {"type": "string", "description": "Имя пользователя точно как написал пользователь"}
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
                    "name": {"type": "string", "description": "Название проекта точно как написал пользователь"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task_full",
            "description": (
                "Создать новую задачу в Asana по имени исполнителя и названию проекта. "
                "Используй ВМЕСТО create_task когда пользователь называет исполнителя или проект по имени."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название задачи"},
                    "description": {"type": "string", "description": "Описание задачи"},
                    "due_date": {"type": "string", "description": "Срок выполнения YYYY-MM-DD"},
                    "assignee_name": {"type": "string", "description": "Имя исполнителя точно как написал пользователь"},
                    "project_name": {"type": "string", "description": "Название проекта точно как написал пользователь"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Создать новую задачу в Asana. Используй ТОЛЬКО если уже знаешь числовые GID исполнителя и проекта.",
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
            "name": "get_tasks_for_project",
            "description": "Получить список задач из проекта Asana по названию проекта. Используй этот инструмент когда пользователь просит показать задачи из проекта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Название проекта точно как написал пользователь"},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks_for_user",
            "description": "Получить список задач исполнителя Asana по его имени. Используй этот инструмент когда пользователь просит показать задачи конкретного человека.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string", "description": "Имя пользователя точно как написал пользователь"},
                },
                "required": ["user_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Получить список задач из Asana по GID проекта или исполнителя. Используй только если уже знаешь GID.",
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
            "name": "search_tasks",
            "description": "Найти задачи по части названия в рабочем пространстве Asana. Используй когда нужно найти gid задачи по её имени.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Часть названия задачи для поиска"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task_to_project",
            "description": "Добавить существующую задачу в проект Asana.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_gid":    {"type": "string", "description": "GID задачи"},
                    "project_gid": {"type": "string", "description": "GID проекта"},
                },
                "required": ["task_gid", "project_gid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Обновить поля задачи в Asana (срок, исполнитель, описание, приоритет).",
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
                            "notes": {"type": "string", "description": "Новое описание задачи"},
                            "priority": {"type": "string", "description": "Приоритет: низкий / средний / высокий"},
                        },
                    },
                },
                "required": ["task_gid", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Удалить задачу из Asana по её GID. Используй когда пользователь просит удалить задачу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_gid": {"type": "string", "description": "GID задачи из Asana (числовой)"},
                },
                "required": ["task_gid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task",
            "description": "Назначить исполнителя задаче по имени задачи и имени пользователя. Используй когда нужно указать или сменить исполнителя задачи.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Название задачи точно как написал пользователь"},
                    "assignee_name": {"type": "string", "description": "Имя исполнителя точно как написал пользователь"},
                },
                "required": ["task_name", "assignee_name"],
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
    "5. Если вопрос не про задачи — вежливо объясни, что умеешь.\n"
    "6. Имена пользователей и проекты передавай в инструменты ТОЧНО как написал пользователь — не переводи на другой язык и не изменяй.\n"
    "7. Для показа задач из проекта используй get_tasks_for_project(project_name=...). Для задач пользователя — get_tasks_for_user(user_name=...). Не используй get_tasks напрямую если не знаешь GID.\n"
    "8. Если пользователь говорит 'этот проект', 'эта задача' и т.п. — используй название/GID из контекста диалога, вызови search_project/search_user сам. Никогда не проси пользователя ещё раз назвать то, что уже упоминалось в диалоге.\n"
    "9. Вызывай get_tasks ОДИН раз за запрос — только с project_gid ИЛИ только с assignee_gid (не оба варианта отдельно). Не повторяй один и тот же инструмент с разными параметрами.\n"
    "10. Для назначения исполнителя задаче используй assign_task(task_name, assignee_name). Никогда не выдумывай task_gid или user_gid.\n"
    "11. Для создания задачи с исполнителем или проектом ВСЕГДА используй create_task_full(title, assignee_name, project_name, ...). Никогда не передавай имена в assignee_gid или project_gid — туда идут только числовые GID.\n"
    "12. Для удаления задачи используй delete_task(task_gid). Сначала найди GID через search_tasks, затем удали. Никогда не выдумывай task_gid.\n"
    "13. НИКОГДА не сообщай об успехе операции, если инструмент вернул 'not_supported', 'error' или 'no supported fields'. Честно сообщи пользователю что именно не поддерживается или не удалось.\n"
    "14. ВСЕГДА вызывай инструменты для получения актуальных данных. Никогда не используй данные из предыдущих ответов в диалоге — они могут быть устаревшими. Каждый запрос 'покажи задачи', 'проверь' и т.п. требует нового вызова инструмента."
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
        "keep_alive": -1,  # keep model loaded permanently (never unload)
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _openai_raw_chat(messages: list, tools: list) -> dict:
    """POST to OpenAI /chat/completions with tools, return Ollama-compatible dict."""
    payload: dict = {
        "model": OPENAI_MODEL,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json=payload,
        )
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        # Normalise to Ollama shape: {"message": {...}}
        return {"message": choice["message"]}


_ADMIN_ONLY_TOOL_NAMES = {
    "create_task", "create_task_full", "delete_task",
    "update_task", "assign_task", "add_task_to_project",
}

HISTORY_MAX_MESSAGES = 20  # max user+assistant turns kept per user

_history: dict[int, list] = {}


def clear_history(user_id: int) -> None:
    _history.pop(user_id, None)


_TEXT_TOOL_CALL_RE = re.compile(
    r"(?:<tool_call>\s*)?(\{.*?\})\s*</tool_call>", re.DOTALL
)


def _parse_text_tool_calls(content: str) -> list:
    """Extract tool calls embedded as <tool_call>JSON</tool_call> in text content."""
    calls = []
    for m in _TEXT_TOOL_CALL_RE.finditer(content):
        try:
            data = json.loads(m.group(1))
            calls.append({"function": {"name": data["name"], "arguments": data.get("arguments", {})}})
        except (json.JSONDecodeError, KeyError):
            continue
    return calls


async def warmup_model() -> None:
    """Send a minimal request to load the Ollama model into memory before users arrive.
    No-op when using OpenAI (no cold start there)."""
    if LLM_PROVIDER != "ollama":
        return
    try:
        await _ollama_raw_chat(
            [{"role": "user", "content": "ping"}],
            [],
        )
        logger.info("Ollama model warmed up successfully")
    except Exception as e:
        logger.warning("Ollama warmup failed (non-fatal): %s", e)


async def process_message(text: str, user_id: int = 0, is_admin: bool = False) -> str:
    """Process user message using tool calling loop with per-user history."""
    import router  # late import — avoids circular dependency
    import httpx

    tools = _ASANA_TOOLS if is_admin else [
        t for t in _ASANA_TOOLS if t["function"]["name"] not in _ADMIN_ONLY_TOOL_NAMES
    ]

    prior = _history.get(user_id, [])
    messages: list = [
        {"role": "system", "content": _tool_system()},
        *prior,
        {"role": "user", "content": text},
    ]

    final_reply: str = "Не удалось получить ответ."

    _raw_chat = _openai_raw_chat if LLM_PROVIDER == "openai" else _ollama_raw_chat

    for _ in range(10):  # cap iterations to prevent runaway loops
        try:
            response = await _raw_chat(messages, tools)
        except httpx.TimeoutException:
            logger.error("Ollama request timed out for user %s", user_id)
            return "Модель думала слишком долго. Попробуй сформулировать запрос короче."
        except httpx.HTTPError as e:
            logger.error("Ollama HTTP error: %s", e)
            return "Не удалось связаться с моделью. Попробуй ещё раз."
        msg = response["message"]
        tool_calls = msg.get("tool_calls") or []

        # Fallback: some models emit tool calls as <tool_call> text
        text_fallback = False
        if not tool_calls and msg.get("content"):
            tool_calls = _parse_text_tool_calls(msg["content"])
            text_fallback = bool(tool_calls)

        if not tool_calls:
            final_reply = msg.get("content") or final_reply
            break

        # Append assistant turn (always structured, strip text-fallback garbage)
        if text_fallback:
            messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
        else:
            messages.append(msg)

        # Execute every tool call in this turn
        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            # Ollama returns arguments as a dict; OpenAI returns a JSON string
            args = fn["arguments"] if isinstance(fn["arguments"], dict) else json.loads(fn["arguments"])
            try:
                result = await router.dispatch_tool(name, args, is_admin=is_admin)
            except Exception as e:
                logger.error("Tool %s raised: %s", name, e)
                result = f"error: {e}"

            tool_msg: dict = {"role": "tool", "content": str(result)}
            # OpenAI requires tool_call_id to match the assistant's tool call
            if call.get("id"):
                tool_msg["tool_call_id"] = call["id"]
            messages.append(tool_msg)
    else:
        final_reply = "Достигнуто максимальное число шагов."

    # Persist only plain user/assistant turns — tool-turn JSON floods context
    # and causes qwen2.5 to return empty responses on subsequent messages.
    new_history = prior + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": final_reply},
    ]
    _history[user_id] = new_history[-HISTORY_MAX_MESSAGES:]

    return final_reply
