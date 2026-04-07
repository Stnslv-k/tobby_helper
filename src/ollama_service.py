import json
import logging
import re
from datetime import date

import httpx

from config import OLLAMA_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты парсер команд. Извлеки намерение из текста и верни ТОЛЬКО валидный JSON.

Правила выбора action:
- "create_event"    — встреча/событие/звонок в Google Calendar (слова: встреча, событие, звонок, созвон)
- "add_to_notion"   — задача/заметка/запись в Notion (слова: задача, заметка, запись, добавь в notion)
- "update_notion"   — изменить существующую запись Notion (есть URL notion.so или слова: измени, обнови)
- "get_notion_page" — узнать детали конкретной записи Notion (спрашивают о конкретной задаче по названию)
- "read_calendar"   — показать события календаря
- "read_notion"     — показать список задач/записей Notion
- "unknown"         — всё остальное

Формат ответа:
{
  "action": "<action>",
  "title": "<название ДОСЛОВНО как написал пользователь, без перевода и изменений, или null>",
  "date": "<дата YYYY-MM-DD, или null>",
  "time": "<время HH:MM, или null>",
  "description": "<только если пользователь явно дал текст описания, иначе null>",
  "url": "<URL notion.so если есть в тексте, иначе null>"
}

Сегодня: {today}.
Относительные даты: завтра=+1 день, послезавтра=+2 дня, вычисли от сегодня.
ЗАПРЕЩЕНО: переводить title, добавлять слова от себя, менять регистр или написание title.
Название бота: Tobby Helper.
Отвечай ТОЛЬКО JSON, без markdown, без пояснений."""


def _build_prompt(text: str) -> str:
    today = date.today().isoformat()
    return SYSTEM_PROMPT.replace("{today}", today)


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {raw[:200]}")
    return json.loads(match.group())


async def chat_reply(text: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "Ты дружелюбный помощник. Отвечай по-русски, кратко и по делу."},
            {"role": "user", "content": text},
        ],
        "stream": False,
    }
    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


async def extract_intent(text: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _build_prompt(text)},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "format": "json",
    }

    for attempt in range(3):
        try:
            headers = {}
            if OLLAMA_API_KEY:
                headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                raw = response.json()["message"]["content"]
                intent = _extract_json(raw)
                logger.info("Intent extracted: %s", intent)
                return intent
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Attempt %d failed to parse intent: %s", attempt + 1, e)
            if attempt == 2:
                return {"action": "unknown", "title": None, "date": None, "time": None, "description": None}
        except httpx.HTTPError as e:
            logger.error("Ollama HTTP error: %s", e)
            raise RuntimeError(f"Ollama недоступен: {e}") from e
