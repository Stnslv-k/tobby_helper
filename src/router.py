import asyncio
import json
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


_ADMIN_ONLY_TOOLS = {
    "create_task", "create_task_full", "delete_task",
    "update_task", "assign_task", "add_task_to_project",
}


async def dispatch_tool(name: str, arguments: dict, is_admin: bool = False) -> str:
    """Execute an Asana tool by name and return a string result for the LLM."""
    loop = asyncio.get_event_loop()
    logger.info("dispatch_tool: %s %s", name, arguments)

    if name in _ADMIN_ONLY_TOOLS and not is_admin:
        return "error: permission denied — this action requires admin rights"

    if name == "search_user":
        result = await loop.run_in_executor(None, asana_service.search_user, arguments["name"])
        return result or "not_found"

    elif name == "search_project":
        result = await loop.run_in_executor(None, asana_service.search_project, arguments["name"])
        return result or "not_found"

    elif name == "create_task":
        def _valid_gid(v) -> Optional[str]:
            return v if v and str(v).isdigit() else None

        gid = await loop.run_in_executor(
            None, asana_service.create_task,
            arguments["title"],
            arguments.get("description"),
            arguments.get("due_date"),
            _valid_gid(arguments.get("assignee_gid")),
            _valid_gid(arguments.get("project_gid")),
        )
        return gid

    elif name == "get_tasks":
        project_gid = arguments.get("project_gid")
        assignee_gid = arguments.get("assignee_gid")
        if project_gid and not str(project_gid).isdigit():
            return "error: project_gid must be a numeric Asana GID — call search_project first to get it"
        if assignee_gid and not str(assignee_gid).isdigit():
            return "error: assignee_gid must be a numeric Asana GID — call search_user first to get it"
        if not project_gid and not assignee_gid:
            return "error: get_tasks requires project_gid or assignee_gid — call search_project or search_user first"
        tasks = await loop.run_in_executor(
            None, asana_service.get_tasks,
            project_gid,
            assignee_gid,
        )
        return json.dumps(tasks, ensure_ascii=False)

    elif name == "assign_task":
        task_name = arguments.get("task_name", "")
        assignee_name = arguments.get("assignee_name", "")
        tasks = await loop.run_in_executor(None, asana_service.search_tasks, task_name)
        if not tasks:
            return f"error: task '{task_name}' not found in Asana"
        task_gid = tasks[0]["gid"]
        user_gid = await loop.run_in_executor(None, asana_service.search_user, assignee_name)
        if not user_gid:
            return f"error: user '{assignee_name}' not found in Asana"
        await loop.run_in_executor(None, asana_service.update_task, task_gid, {"assignee": user_gid})
        return f"updated: assigned '{tasks[0]['name']}' to {assignee_name}"

    elif name == "get_tasks_for_project":
        project_name = arguments.get("project_name", "")
        project_gid = await loop.run_in_executor(None, asana_service.search_project, project_name)
        if not project_gid:
            return f"error: project '{project_name}' not found in Asana"
        tasks = await loop.run_in_executor(None, asana_service.get_tasks, project_gid, None)
        return json.dumps(tasks, ensure_ascii=False)

    elif name == "get_tasks_for_user":
        user_name = arguments.get("user_name", "")
        user_gid = await loop.run_in_executor(None, asana_service.search_user, user_name)
        if not user_gid:
            return f"error: user '{user_name}' not found in Asana"
        tasks = await loop.run_in_executor(None, asana_service.get_tasks, None, user_gid)
        return json.dumps(tasks, ensure_ascii=False)

    elif name == "create_task_full":
        title = arguments.get("title", "")
        description = arguments.get("description")
        due_date = arguments.get("due_date")
        assignee_name = arguments.get("assignee_name")
        project_name = arguments.get("project_name")
        assignee_gid = (
            await loop.run_in_executor(None, asana_service.search_user, assignee_name)
            if assignee_name else None
        )
        project_gid = (
            await loop.run_in_executor(None, asana_service.search_project, project_name)
            if project_name else None
        )
        task_gid = await loop.run_in_executor(
            None, asana_service.create_task,
            title, description, due_date, assignee_gid, project_gid,
        )
        return f"created: {task_gid}"

    elif name == "list_projects":
        projects = await loop.run_in_executor(None, asana_service.list_projects)
        return json.dumps(projects, ensure_ascii=False)

    elif name == "list_users":
        users = await loop.run_in_executor(None, asana_service.list_users)
        return json.dumps(users, ensure_ascii=False)

    elif name == "search_tasks":
        tasks = await loop.run_in_executor(None, asana_service.search_tasks, arguments["text"])
        return json.dumps(tasks, ensure_ascii=False)

    elif name == "add_task_to_project":
        task_gid = arguments.get("task_gid", "")
        project_gid = arguments.get("project_gid", "")
        if not str(task_gid).isdigit() or not str(project_gid).isdigit():
            return f"error: task_gid and project_gid must be numeric Asana GIDs"
        await loop.run_in_executor(None, asana_service.add_task_to_project, task_gid, project_gid)
        return "added"

    elif name == "update_task":
        task_gid = arguments.get("task_gid", "")
        if not str(task_gid).isdigit():
            return f"error: task_gid must be a numeric Asana GID, got '{task_gid}'"
        fields = dict(arguments.get("fields", {}))
        if "assignee" in fields and not str(fields["assignee"]).isdigit():
            del fields["assignee"]
        supported = {k for k in fields if k in ("due_date", "assignee", "notes", "priority")}
        unsupported = set(fields.keys()) - supported
        if supported:
            await loop.run_in_executor(
                None, asana_service.update_task,
                task_gid,
                {k: fields[k] for k in supported},
            )
        parts = []
        if supported:
            parts.append(f"updated: {', '.join(supported)}")
        if unsupported:
            parts.append(f"not_supported (ignored): {', '.join(unsupported)}")
        if not supported:
            parts.append("no supported fields to update")
        return "; ".join(parts)

    elif name == "delete_task":
        task_gid = arguments.get("task_gid", "")
        if not str(task_gid).isdigit():
            return f"error: task_gid must be a numeric Asana GID, got '{task_gid}'"
        await loop.run_in_executor(None, asana_service.delete_task, task_gid)
        return "deleted"

    else:
        return f"unknown tool: {name}"
