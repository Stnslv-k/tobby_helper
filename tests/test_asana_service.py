import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta


@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "ASANA_PAT", "test_pat")
    monkeypatch.setattr(config, "ASANA_WORKSPACE_GID", "ws_123")


def _resp(data, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = {"data": data}
    m.raise_for_status = MagicMock()
    return m


def test_create_task_returns_gid():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.post.return_value = _resp({"gid": "task_gid_1"})
        gid = asana_service.create_task(
            title="Написать отчёт",
            description="Квартальный",
            due_date="2026-04-20",
            assignee_gid="user_gid_1",
            project_gid="proj_gid_1",
        )
    assert gid == "task_gid_1"
    body = mock_client.post.call_args[1]["json"]["data"]
    assert body["name"] == "Написать отчёт"
    assert body["assignee"] == "user_gid_1"
    assert body["projects"] == ["proj_gid_1"]
    assert body["due_on"] == "2026-04-20"


def test_create_task_without_optional_fields():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.post.return_value = _resp({"gid": "task_gid_2"})
        asana_service.create_task(
            title="Задача без полей",
            description=None,
            due_date=None,
            assignee_gid=None,
            project_gid=None,
        )
    body = mock_client.post.call_args[1]["json"]["data"]
    assert "assignee" not in body
    assert "projects" not in body
    assert "due_on" not in body


def test_search_user_found():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = _resp([
            {"gid": "u1", "name": "Иван Петров"},
            {"gid": "u2", "name": "Петр Иванов"},
        ])
        gid = asana_service.search_user("Иван")
    assert gid == "u1"


def test_search_user_not_found():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = _resp([{"gid": "u1", "name": "Петр Иванов"}])
        gid = asana_service.search_user("Несуществующий")
    assert gid is None


def test_search_project_found():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = _resp([
            {"gid": "p1", "name": "Маркетинг"},
            {"gid": "p2", "name": "Разработка"},
        ])
        gid = asana_service.search_project("Маркетинг")
    assert gid == "p1"


def test_update_task_due_date():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.put.return_value = _resp({"gid": "t1"})
        asana_service.update_task("t1", {"due_date": "2026-05-01"})
    body = mock_client.put.call_args[1]["json"]["data"]
    assert body["due_on"] == "2026-05-01"


def test_get_tasks_due_soon_filters_by_date():
    import asana_service
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    in_five = (today + timedelta(days=5)).isoformat()

    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = _resp([
            {"gid": "t1", "name": "Задача 1", "due_on": tomorrow,
             "assignee": {"gid": "u1", "name": "Иван"}, "completed": False},
            {"gid": "t2", "name": "Задача 2", "due_on": in_five,
             "assignee": None, "completed": False},
        ])
        tasks = asana_service.get_tasks_due_soon([1])

    assert len(tasks) == 1
    assert tasks[0]["gid"] == "t1"


def test_list_projects_returns_all():
    import asana_service
    with patch("asana_service._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get.return_value = _resp([
            {"gid": "p1", "name": "Маркетинг"},
            {"gid": "p2", "name": "Разработка"},
            {"gid": "p3", "name": "Продажи"},
        ])
        projects = asana_service.list_projects()
    assert len(projects) == 3
    assert projects[0]["name"] == "Маркетинг"
