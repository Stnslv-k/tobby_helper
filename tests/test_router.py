import asyncio
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    import router
    router._rate_limit_store.clear()
    yield
    router._rate_limit_store.clear()


@pytest.fixture(autouse=True)
def fast_rate_limit(monkeypatch):
    import config
    monkeypatch.setattr(config, "RATE_LIMIT_SECONDS", 3)


def test_rate_limit_blocks_immediate_second_request():
    import router
    assert router.check_rate_limit(111) is True
    assert router.check_rate_limit(111) is False


def test_rate_limit_allows_different_users():
    import router
    assert router.check_rate_limit(111) is True
    assert router.check_rate_limit(222) is True


def test_rate_limit_allows_after_cooldown(monkeypatch):
    import config
    monkeypatch.setattr(config, "RATE_LIMIT_SECONDS", 0)
    import router
    assert router.check_rate_limit(333) is True
    assert router.check_rate_limit(333) is True


def _intent(action, **kwargs):
    base = {
        "action": action, "title": None, "description": None,
        "due_date": None, "assignee": None, "project": None,
        "task_id": None, "update_fields": None,
    }
    return {**base, **kwargs}


def test_create_task_calls_asana():
    import router
    with patch("router.asana_service.search_user", return_value="user_gid_1"), \
         patch("router.asana_service.search_project", return_value="proj_gid_1"), \
         patch("router.asana_service.create_task", return_value="task_gid_new"):
        result = asyncio.run(router.route_action(
            _intent("create_task", title="Отчёт", assignee="Иван", project="Маркетинг"),
            user_id=12345,
        ))
    assert "Отчёт" in result


def test_create_task_title_truncated_to_255():
    import router
    long_title = "А" * 300
    with patch("router.asana_service.search_user", return_value=None), \
         patch("router.asana_service.search_project", return_value=None), \
         patch("router.asana_service.create_task", return_value="t1") as mock_create:
        asyncio.run(router.route_action(
            _intent("create_task", title=long_title), user_id=1
        ))
    passed_title = mock_create.call_args[0][0]
    assert len(passed_title) <= 255


def test_create_task_invalid_due_date_becomes_none():
    import router
    with patch("router.asana_service.search_user", return_value=None), \
         patch("router.asana_service.search_project", return_value=None), \
         patch("router.asana_service.create_task", return_value="t1") as mock_create:
        asyncio.run(router.route_action(
            _intent("create_task", title="Задача", due_date="не_дата"), user_id=1
        ))
    passed_due_date = mock_create.call_args[0][2]
    assert passed_due_date is None


def test_unknown_action_returns_help_text():
    import router
    result = asyncio.run(router.route_action(_intent("unknown"), user_id=1))
    assert "Не понял" in result


def test_list_projects_returns_names():
    import router
    projects = [
        {"gid": "p1", "name": "Маркетинг"},
        {"gid": "p2", "name": "Разработка"},
    ]
    with patch("router.asana_service.list_projects", return_value=projects):
        result = asyncio.run(router.route_action(_intent("list_projects"), user_id=1))
    assert "Маркетинг" in result
    assert "Разработка" in result


def test_read_tasks_returns_list():
    import router
    tasks = [
        {"gid": "t1", "name": "Задача 1", "due_on": "2026-04-20",
         "assignee": {"name": "Иван"}, "completed": False},
    ]
    with patch("router.asana_service.search_project", return_value="p1"), \
         patch("router.asana_service.search_user", return_value=None), \
         patch("router.asana_service.get_tasks", return_value=tasks):
        result = asyncio.run(router.route_action(
            _intent("read_tasks", project="Маркетинг"), user_id=1
        ))
    assert "Задача 1" in result
