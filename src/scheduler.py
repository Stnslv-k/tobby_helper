import logging
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import asana_service
import team
from config import ADMIN_TELEGRAM_IDS, DEADLINE_NOTIFY_DAYS, NOTIFY_TIME

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _check_deadlines(
    send_message: Callable[[int, str], Awaitable[None]],
) -> None:
    try:
        tasks = asana_service.get_tasks_due_soon(DEADLINE_NOTIFY_DAYS)
    except Exception as e:
        logger.error("Deadline check failed: %s", e)
        return

    for task in tasks:
        name = task.get("name", "Без названия")
        due_on = task.get("due_on", "")
        assignee = task.get("assignee") or {}
        assignee_name = assignee.get("name", "")
        assignee_gid = assignee.get("gid", "")

        admin_text = f"⏰ Задача «{name}»"
        if assignee_name:
            admin_text += f" для {assignee_name}"
        admin_text += f" — дедлайн {due_on}"
        for admin_id in ADMIN_TELEGRAM_IDS:
            await send_message(admin_id, admin_text)

        if assignee_gid:
            member = team.get_member_by_asana_gid(assignee_gid)
            if member and member.get("telegram_id"):
                assignee_text = f"⏰ Напоминание: задача «{name}» — дедлайн {due_on}"
                await send_message(member["telegram_id"], assignee_text)


def start_scheduler(
    send_message: Callable[[int, str], Awaitable[None]],
) -> None:
    global _scheduler
    hour, minute = NOTIFY_TIME.split(":")

    async def _job() -> None:
        await _check_deadlines(send_message)

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_job, CronTrigger(hour=int(hour), minute=int(minute)))
    _scheduler.start()
    logger.info("Deadline scheduler started (daily at %s)", NOTIFY_TIME)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
