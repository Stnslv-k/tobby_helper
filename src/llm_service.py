import json
import logging
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

_ALLOWED_ACTIONS = {"create_task", "update_task", "read_tasks", "unknown"}

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
  "action": "create_task | update_task | read_tasks | unknown",
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
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


async def _ollama_complete(system: str, user: str) -> str:
    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            headers=headers,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def _openai_complete(system: str, user: str) -> str:
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


async def _complete(system: str, user: str) -> str:
    if LLM_PROVIDER == "openai":
        return await _openai_complete(system, user)
    return await _ollama_complete(system, user)


async def extract_intent(text: str) -> dict:
    for attempt in range(3):
        try:
            raw = await _complete(_intent_system(), text)
            raw = _strip_fences(raw)
            parsed = json.loads(raw)
            if parsed.get("action") not in _ALLOWED_ACTIONS:
                parsed["action"] = "unknown"
            return {**_EMPTY_INTENT, **parsed}
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
