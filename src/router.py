import asyncio
import logging
import re
from datetime import date

from calendar_service import create_event, list_events
from notion_service import create_page, find_page_by_title, list_pages, update_page

logger = logging.getLogger(__name__)


def _format_event(event: dict) -> str:
    start = event["start"]
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(start)
        start = dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        pass
    link = f"\n🔗 {event['link']}" if event.get("link") else ""
    return f"• {event['title']} — {start}{link}"


async def route_action(intent: dict) -> str:
    action = intent.get("action", "unknown")
    title = intent.get("title") or "Без названия"
    event_date = intent.get("date") or date.today().isoformat()
    event_time = intent.get("time")
    description = intent.get("description")

    loop = asyncio.get_event_loop()

    if action == "create_event":
        if not intent.get("title"):
            return "Не удалось определить название события. Уточни, пожалуйста."
        try:
            link = await loop.run_in_executor(
                None, create_event, title, event_date, event_time, description
            )
            time_part = f" в {event_time}" if event_time else ""
            return (
                f"Событие создано в Google Calendar\n"
                f"📅 {title}\n"
                f"🗓 {event_date}{time_part}\n"
                f"🔗 {link}"
            )
        except Exception as e:
            logger.error("Calendar error: %s", e)
            return f"Не удалось создать событие в Calendar: {e}"

    elif action == "add_to_notion":
        if not intent.get("title"):
            return "Не удалось определить название заметки. Уточни, пожалуйста."
        try:
            url = await loop.run_in_executor(
                None, create_page, title, description, intent.get("date")
            )
            return (
                f"Запись добавлена в Notion\n"
                f"📝 {title}\n"
                f"🔗 {url}"
            )
        except Exception as e:
            logger.error("Notion error: %s", e)
            return f"Не удалось добавить запись в Notion: {e}"

    elif action == "update_notion":
        url = intent.get("url")
        # Если URL не содержит 32-символьный ID — ищем по названию
        if url and not re.search(r"[a-f0-9]{32}", url.replace("-", "")):
            url = None
        if not url and title and title != "Без названия":
            url = await loop.run_in_executor(None, find_page_by_title, title)
        if not url:
            return "Не нашёл такую запись в Notion. Уточни название или дай ссылку."
        try:
            new_title = intent.get("title") if intent.get("url") else None
            await loop.run_in_executor(
                None, update_page, url, intent.get("date"), new_title
            )
            return f"Запись обновлена в Notion:\n🔗 {url}"
        except Exception as e:
            logger.error("Notion update error: %s", e)
            return f"Не удалось обновить запись в Notion: {e}"

    elif action == "read_calendar":
        try:
            events = await loop.run_in_executor(None, list_events, 7)
            if not events:
                return "В ближайшие 7 дней событий нет."
            lines = ["Ближайшие события в Calendar:"] + [_format_event(e) for e in events]
            return "\n".join(lines)
        except Exception as e:
            logger.error("Calendar read error: %s", e)
            return f"Не удалось получить события из Calendar: {e}"

    elif action == "read_notion":
        try:
            pages = await loop.run_in_executor(None, list_pages, 5)
            if not pages:
                return "В Notion нет записей."
            lines = ["Последние записи в Notion:"]
            for p in pages:
                lines.append(f"• {p['title']}\n  🔗 {p['url']}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Notion read error: %s", e)
            return f"Не удалось получить записи из Notion: {e}"

    else:
        return (
            "Не понял запрос. Попробуй сформулировать иначе, например:\n"
            "• «Создай встречу завтра в 10:00»\n"
            "• «Добавь в Notion задачу: написать отчёт»\n"
            "• «Покажи события на неделю»"
        )
