import logging
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional

import httpx

from config import ASANA_PAT, ASANA_PRIORITY_FIELD_GID, ASANA_WORKSPACE_GID

logger = logging.getLogger(__name__)

_BASE = "https://app.asana.com/api/1.0"
_TASK_FIELDS = "name,due_on,assignee,assignee.name,assignee.gid,completed,notes"

_CYR_TO_LAT = str.maketrans(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "abvgdeyezhziyklmnoprstufhtschshch yuya"[:33],
)
# precise one-to-one mapping (33 chars each side)
_CYR_TO_LAT = str.maketrans(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "abvgdeezziyklmnoprstufhccssuueeia",
)


def _transliterate(s: str) -> str:
    return s.lower().translate(_CYR_TO_LAT)


def _fuzzy_score(query: str, name: str) -> float:
    """Return best similarity score between query and name, handling Cyrillic/Latin mix."""
    q, n = query.lower(), name.lower()
    qt, nt = _transliterate(query), _transliterate(name)
    best = 0.0
    for a, b in ((q, n), (qt, nt), (qt, n), (q, nt)):
        if a == b:
            return 1.0
        if a and b and a in b:
            # query is a substring of name — strong signal, but not perfect
            best = max(best, 0.85)
        best = max(best, SequenceMatcher(None, a, b).ratio())
    return best


def _fuzzy_match(query: str, name: str, cutoff: float = 0.6) -> bool:
    return _fuzzy_score(query, name) >= cutoff


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
    client = _get_client()
    seen: dict[str, dict] = {}

    if project_gid:
        resp = client.get(f"{_BASE}/tasks", params={
            "project": project_gid, "opt_fields": _TASK_FIELDS, "limit": limit,
        })
        if not resp.is_success:
            logger.error("get_tasks project=%s → %s %s", project_gid, resp.status_code, resp.text[:300])
        resp.raise_for_status()
        for t in resp.json()["data"]:
            if not t.get("completed"):
                seen[t["gid"]] = t

    if assignee_gid:
        resp = client.get(f"{_BASE}/tasks", params={
            "assignee": assignee_gid, "workspace": ASANA_WORKSPACE_GID,
            "opt_fields": _TASK_FIELDS, "limit": limit,
        })
        if not resp.is_success:
            logger.error("get_tasks assignee=%s → %s %s", assignee_gid, resp.status_code, resp.text[:300])
        resp.raise_for_status()
        for t in resp.json()["data"]:
            if not t.get("completed"):
                seen[t["gid"]] = t

    return list(seen.values())


_PRIORITY_OPTIONS = {"low": "low", "medium": "medium", "high": "high",
                     "низкий": "low", "средний": "medium", "высокий": "high"}


def update_task(task_gid: str, fields: dict) -> None:
    payload: dict = {}
    if "name" in fields:
        payload["name"] = str(fields["name"])[:255]
    if "due_date" in fields:
        payload["due_on"] = fields["due_date"]
    if "assignee" in fields:
        payload["assignee"] = fields["assignee"]
    if "notes" in fields:
        payload["notes"] = str(fields["notes"])[:2000]
    if "priority" in fields and ASANA_PRIORITY_FIELD_GID:
        option = _PRIORITY_OPTIONS.get(str(fields["priority"]).lower())
        if option:
            payload.setdefault("custom_fields", {})[ASANA_PRIORITY_FIELD_GID] = option
    if not payload:
        logger.warning("update_task called with no recognised fields: %s", list(fields.keys()))
        return
    resp = _get_client().put(f"{_BASE}/tasks/{task_gid}", json={"data": payload})
    resp.raise_for_status()


def list_users() -> list[dict]:
    resp = _get_client().get(
        f"{_BASE}/workspaces/{ASANA_WORKSPACE_GID}/users",
        params={"opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    return resp.json()["data"]


def search_user(name: str) -> Optional[str]:
    resp = _get_client().get(
        f"{_BASE}/workspaces/{ASANA_WORKSPACE_GID}/users",
        params={"opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    best_gid, best_score = None, 0.0
    for user in resp.json()["data"]:
        score = _fuzzy_score(name, user["name"])
        if score > best_score:
            best_score, best_gid = score, user["gid"]
    return best_gid if best_score >= 0.6 else None


def list_projects() -> list[dict]:
    resp = _get_client().get(
        f"{_BASE}/projects",
        params={"workspace": ASANA_WORKSPACE_GID, "opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    return resp.json()["data"]


def search_project(name: str) -> Optional[str]:
    resp = _get_client().get(
        f"{_BASE}/projects",
        params={"workspace": ASANA_WORKSPACE_GID, "opt_fields": "name,gid"},
    )
    resp.raise_for_status()
    best_gid, best_score = None, 0.0
    for project in resp.json()["data"]:
        score = _fuzzy_score(name, project["name"])
        if score > best_score:
            best_score, best_gid = score, project["gid"]
    return best_gid if best_score >= 0.6 else None


def search_tasks(text: str, limit: int = 20) -> list[dict]:
    """Search tasks by name substring across the workspace."""
    resp = _get_client().get(
        f"{_BASE}/workspaces/{ASANA_WORKSPACE_GID}/tasks/search",
        params={"text": text, "opt_fields": _TASK_FIELDS, "limit": limit, "completed": "false"},
    )
    resp.raise_for_status()
    return resp.json()["data"]


def delete_task(task_gid: str) -> None:
    resp = _get_client().delete(f"{_BASE}/tasks/{task_gid}")
    resp.raise_for_status()


def add_task_to_project(task_gid: str, project_gid: str) -> None:
    resp = _get_client().post(
        f"{_BASE}/tasks/{task_gid}/addProject",
        json={"data": {"project": project_gid}},
    )
    resp.raise_for_status()


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
