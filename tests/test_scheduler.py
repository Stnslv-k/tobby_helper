import asyncio
import pytest
from datetime import date, timedelta
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "DEADLINE_NOTIFY_DAYS", [1, 2])
    monkeypatch.setattr(config, "ADMIN_TELEGRAM_IDS", [12345, 99999])


def _task(name, gid, due_on, assignee_gid=None, assignee_name=None):
    assignee = {"gid": assignee_gid, "name": assignee_name} if assignee_gid else None
    return {"gid": gid, "name": name, "due_on": due_on,
            "assignee": assignee, "completed": False}


def test_notifies_admin_and_assignee():
    import scheduler
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tasks = [_task("Написать отчёт", "t1", tomorrow, "u1", "Иван")]
    sent = []

    async def fake_send(chat_id, text):
        sent.append((chat_id, text))

    fake_member = {"name": "Иван", "asana_gid": "u1",
                   "telegram_id": 77777, "telegram_username": "@ivan"}

    with patch("scheduler.asana_service.get_tasks_due_soon", return_value=tasks), \
         patch("scheduler.team.get_member_by_asana_gid", return_value=fake_member):
        asyncio.run(scheduler._check_deadlines(send_message=fake_send))

    chat_ids = [m[0] for m in sent]
    assert 12345 in chat_ids  # первый админ
    assert 99999 in chat_ids  # второй админ
    assert 77777 in chat_ids  # исполнитель


def test_notifies_only_admins_when_no_telegram_id():
    import scheduler
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tasks = [_task("Задача", "t2", tomorrow, "u2", "Петр")]
    sent = []

    async def fake_send(chat_id, text):
        sent.append((chat_id, text))

    fake_member = {"name": "Петр", "asana_gid": "u2",
                   "telegram_id": None, "telegram_username": "@petr"}

    with patch("scheduler.asana_service.get_tasks_due_soon", return_value=tasks), \
         patch("scheduler.team.get_member_by_asana_gid", return_value=fake_member):
        asyncio.run(scheduler._check_deadlines(send_message=fake_send))

    chat_ids = [m[0] for m in sent]
    assert 12345 in chat_ids
    assert 99999 in chat_ids
    assert len(sent) == 2  # только два админа, без исполнителя


def test_start_scheduler_twice_does_not_duplicate_jobs(monkeypatch):
    """Calling start_scheduler twice must not create two running schedulers."""
    import scheduler
    monkeypatch.setattr("config.NOTIFY_TIME", "09:00")

    async def fake_send(chat_id, text): pass

    async def _run():
        monkeypatch.setattr(scheduler, "_scheduler", None)
        scheduler.start_scheduler(fake_send)
        first = scheduler._scheduler
        jobs_after_first = len(first.get_jobs())

        scheduler.start_scheduler(fake_send)
        second = scheduler._scheduler

        assert first is second, "start_scheduler created a second scheduler"
        assert len(second.get_jobs()) == jobs_after_first, "duplicate job added"

        scheduler.stop_scheduler()

    asyncio.run(_run())


def test_no_notifications_when_no_tasks():
    import scheduler
    sent = []

    async def fake_send(chat_id, text):
        sent.append((chat_id, text))

    with patch("scheduler.asana_service.get_tasks_due_soon", return_value=[]):
        asyncio.run(scheduler._check_deadlines(send_message=fake_send))

    assert len(sent) == 0


def test_notification_message_contains_task_name():
    import scheduler
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tasks = [_task("Уникальное название задачи", "t3", tomorrow)]
    sent = []

    async def fake_send(chat_id, text):
        sent.append((chat_id, text))

    with patch("scheduler.asana_service.get_tasks_due_soon", return_value=tasks), \
         patch("scheduler.team.get_member_by_asana_gid", return_value=None):
        asyncio.run(scheduler._check_deadlines(send_message=fake_send))

    assert any("Уникальное название задачи" in m[1] for m in sent)
