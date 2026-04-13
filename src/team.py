import json
import os
from typing import Optional

# Overridable by tests via monkeypatch
TEAM_FILE = "data/team.json"


def _load() -> dict:
    if not os.path.exists(TEAM_FILE):
        return {}
    with open(TEAM_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(TEAM_FILE)), exist_ok=True)
    with open(TEAM_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_member(name: str, asana_gid: str, telegram_username: str) -> None:
    data = _load()
    data[name] = {
        "asana_gid": asana_gid,
        "telegram_username": telegram_username,
        "telegram_id": None,
    }
    _save(data)


def remove_member(name: str) -> bool:
    data = _load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True


def get_member(name: str) -> Optional[dict]:
    entry = _load().get(name)
    if entry is None:
        return None
    return {"name": name, **entry}


def get_member_by_telegram_id(telegram_id: int) -> Optional[dict]:
    for name, entry in _load().items():
        if entry.get("telegram_id") == telegram_id:
            return {"name": name, **entry}
    return None


def get_member_by_asana_gid(asana_gid: str) -> Optional[dict]:
    for name, entry in _load().items():
        if entry.get("asana_gid") == asana_gid:
            return {"name": name, **entry}
    return None


def set_telegram_id(name: str, telegram_id: int) -> bool:
    data = _load()
    if name not in data:
        return False
    data[name]["telegram_id"] = telegram_id
    _save(data)
    return True


def is_allowed(telegram_id: int, admin_id: int) -> bool:
    if telegram_id == admin_id:
        return True
    return get_member_by_telegram_id(telegram_id) is not None


def list_members() -> list[dict]:
    return [{"name": name, **entry} for name, entry in _load().items()]
