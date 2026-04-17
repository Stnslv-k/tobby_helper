import asyncio
import logging
import time
from datetime import date
from typing import Optional

import asana_service
import config

logger = logging.getLogger(__name__)

_rate_limit_store: dict[int, float] = {}


def check_rate_limit(user_id: int) -> bool:
    now = time.monotonic()
    if now - _rate_limit_store.get(user_id, 0) < config.RATE_LIMIT_SECONDS:
        return False
    _rate_limit_store[user_id] = now
    return True


def _clean(value: Optional[str], max_len: int = 255) -> Optional[str]:
    if not value:
        return None
    return str(value)[:max_len]


def _valid_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        return None


async def route_action(intent: dict, user_id: int) -> str:
    loop = asyncio.get_event_loop()
    action = intent.get("action", "unknown")
    title = _clean(intent.get("title"))
    description = _clean(intent.get("description"), 2000)
    due_date = _valid_date(intent.get("due_date"))
    assignee_name = _clean(intent.get("assignee"))
    project_name = _clean(intent.get("project"))
    task_id = _clean(intent.get("task_id"))
    update_fields = intent.get("update_fields") or {}

    if action == "create_task":
        if not title:
            return "Не понял название задачи. Уточни, пожалуйста."
        assignee_gid = (
            await loop.run_in_executor(None, asana_service.search_user, assignee_name)
            if assignee_name else None
        )
        project_gid = (
            await loop.run_in_executor(None, asana_service.search_project, project_name)
            if project_name else None
        )
        try:
            await loop.run_in_executor(
                None, asana_service.create_task,
                title, description, due_date, assignee_gid, project_gid,
            )
            parts = [f"Задача создана в Asana\n📋 {title}"]
            if assignee_name:
                label = f"✅ {assignee_name}" if assignee_gid else f"⚠️ {assignee_name} (не найден в Asana)"
                parts.append(f"👤 {label}")
            if project_name:
                label = f"✅ {project_name}" if project_gid else f"⚠️ {project_name} (проект не найден)"
                parts.append(f"📁 {label}")
            if due_date:
                parts.append(f"📅 {due_date}")
            return "\n".join(parts)
        except Exception as e:
            logger.error("Create task error: %s", e)
            return f"Не удалось создать задачу: {e}"

    elif action == "read_tasks":
        project_gid = (
            await loop.run_in_executor(None, asana_service.search_project, project_name)
            if project_name else None
        )
        assignee_gid = (
            await loop.run_in_executor(None, asana_service.search_user, assignee_name)
            if assignee_name else None
        )
        if not project_gid and not assignee_gid:
            return (
                "Уточни запрос, например:\n"
                "• «Покажи задачи проекта Маркетинг»\n"
                "• «Покажи задачи Ивана»"
            )
        try:
            tasks = await loop.run_in_executor(
                None, asana_service.get_tasks, project_gid, assignee_gid
            )
            if not tasks:
                return "Задач не найдено."
            lines = ["Задачи:"]
            for t in tasks[:10]:
                due = f" — {t['due_on']}" if t.get("due_on") else ""
                who = f" ({t['assignee']['name']})" if t.get("assignee") else ""
                lines.append(f"• {t['name']}{who}{due}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Read tasks error: %s", e)
            return f"Не удалось получить задачи: {e}"

    elif action == "list_projects":
        try:
            projects = await loop.run_in_executor(None, asana_service.list_projects)
            if not projects:
                return "Проектов не найдено."
            lines = ["Проекты в Asana:"]
            for p in projects:
                lines.append(f"• {p['name']}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("List projects error: %s", e)
            return f"Не удалось получить список проектов: {e}"

    elif action == "update_task":
        if not task_id:
            return "Для обновления задачи укажи её ID (gid из Asana)."
        clean_fields: dict = {}
        if "due_date" in update_fields:
            v = _valid_date(update_fields["due_date"])
            if v:
                clean_fields["due_date"] = v
        if "assignee" in update_fields:
            new_name = _clean(update_fields["assignee"])
            if new_name:
                gid = await loop.run_in_executor(
                    None, asana_service.search_user, new_name
                )
                if not gid:
                    return f"Пользователь «{new_name}» не найден в Asana."
                clean_fields["assignee"] = gid
        if not clean_fields:
            return "Нет распознанных полей для обновления."
        try:
            await loop.run_in_executor(None, asana_service.update_task, task_id, clean_fields)
            return "Задача обновлена."
        except Exception as e:
            logger.error("Update task error: %s", e)
            return f"Не удалось обновить задачу: {e}"

    else:
        return (
            "Не понял запрос. Попробуй:\n"
            "• «Создай задачу для Ивана в проекте Маркетинг: написать отчёт до пятницы»\n"
            "• «Покажи задачи проекта Разработка»\n"
            "• «Обнови задачу [ID]: перенеси дедлайн на следующую неделю»"
        )
