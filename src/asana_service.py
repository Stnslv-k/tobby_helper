import logging
from datetime import date, timedelta
from typing import Optional

import httpx

from config import ASANA_PAT, ASANA_WORKSPACE_GID

logger = logging.getLogger(__name__)

_BASE = "https://app.asana.com/api/1.0"
_TASK_FIELDS = "name,due_on,assignee,assignee.name,assignee.gid,completed,notes"

def _get_client() -> httpx.Client:
    return httpx.Client(
        headers={"Authorization": f"Bearer {ASANA_PAT}"},
        timeout=30,
    )


def create_task(
    title: str,
    description: Optional[str],
    due_date: Optional[str],
    assignee_gid: Optional[str],
    project_gid: Optional[str],
) -> str:
    payload: dict = {"name": title[:255], "workspace": ASANA_WORKSPACE_GID}
    if description:
        payload["notes"] = description[:2000]
    if due_date:
        payload["due_on"] = due_date
    if assignee_gid:
        payload["assignee"] = assignee_gid
    if project_gid:
        payload["projects"] = [project_gid]
    resp = _get_client().post(f"{_BASE}/tasks", json={"data": payload})
    resp.raise_for_status()
    return resp.json()["data"]["gid"]


def get_tasks(
    project_gid: Optional[str] = None,
    assignee_gid: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    if not project_gid and not assignee_gid:
        raise ValueError("get_tasks requires at least one of project_gid or assignee_gid")
    params: dict = {"opt_fields": _TASK_FIELDS, "limit": limit}
    if project_gid:
        params["project"] = project_gid
    if assignee_gid:
        params["assignee"] = assignee_gid
        params["workspace"] = ASANA_WORKSPACE_GID
    resp = _get_client().get(f"{_BASE}/tasks", params=params)
    resp.raise_for_status()
    return [t for t in resp.json()["data"] if not t.get("completed")]


def update_task(task_gid: str, fields: dict) -> None:
    payload: dict = {}
    if "due_date" in fields:
        payload["due_on"] = fields["due_date"]
    if "assignee" in fields:
        payload["assignee"] = fields["assignee"]
    if not payload:
        logger.warning("update_task called with no recognised fields: %s", list(fields.keys()))
        return
    resp = _get_client().put(f"{_BASE}/tasks/{task_gid}", json={"data": payload})
    resp.raise_for_status()


def search_user(name: str) -> Optional[str]:
    # Note: returns only the first page (~20 results). Sufficient for small workspaces.
    resp = _get_client().get(
        f"{_BASE}/workspaces/{ASANA_WORKSPACE_GID}/users",
        params={"opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    name_lower = name.lower()
    for user in resp.json()["data"]:
        if name_lower in user["name"].lower():
            return user["gid"]
    return None


def list_projects() -> list[dict]:
    resp = _get_client().get(
        f"{_BASE}/projects",
        params={"workspace": ASANA_WORKSPACE_GID, "opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    return resp.json()["data"]


def search_project(name: str) -> Optional[str]:
    # Note: returns only the first page (~20 results). Sufficient for small workspaces.
    resp = _get_client().get(
        f"{_BASE}/projects",
        params={"workspace": ASANA_WORKSPACE_GID, "opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    name_lower = name.lower()
    for project in resp.json()["data"]:
        if name_lower in project["name"].lower():
            return project["gid"]
    return None


def get_tasks_due_soon(days: list[int]) -> list[dict]:
    today = date.today()
    target_dates = {(today + timedelta(days=d)).isoformat() for d in days}
    sorted_dates = sorted(target_dates)
    params = {
        "workspace": ASANA_WORKSPACE_GID,
        "opt_fields": _TASK_FIELDS,
        "due_on.after": (date.fromisoformat(sorted_dates[0]) - timedelta(days=1)).isoformat(),
        "due_on.before": (date.fromisoformat(sorted_dates[-1]) + timedelta(days=1)).isoformat(),
        "completed": "false",
    }
    resp = _get_client().get(
        f"{_BASE}/workspaces/{ASANA_WORKSPACE_GID}/tasks/search",
        params=params,
    )
    resp.raise_for_status()
    return [t for t in resp.json()["data"] if t.get("due_on") in target_dates]
