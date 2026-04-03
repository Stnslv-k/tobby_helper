import json
import logging
import re
from datetime import date

import httpx

from config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты помощник-парсер команд. Из текста пользователя извлеки намерение и верни ТОЛЬКО валидный JSON без дополнительного текста.

Поле "action" — одно из:
- "create_event"    — создать событие в Google Calendar
- "add_to_notion"   — добавить запись/заметку в Notion
- "read_calendar"   — показать ближайшие события календаря
- "read_notion"     — показать записи из Notion
- "unknown"         — непонятное намерение

Формат ответа:
{
  "action": "<action>",
  "title": "<название события или заметки, или null>",
  "date": "<дата в формате YYYY-MM-DD, или null>",
  "time": "<время в формате HH:MM, или null>",
  "description": "<описание, или null>"
}

Если дата относительная (завтра, послезавтра, в пятницу), вычисли абсолютную дату относительно сегодня: {today}.
Отвечай ТОЛЬКО JSON, без markdown, без объяснений."""


def _build_prompt(text: str) -> str:
    today = date.today().isoformat()
    return SYSTEM_PROMPT.replace("{today}", today)


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {raw[:200]}")
    return json.loads(match.group())


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
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload,
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
