"""
Dynamic config stored in a JSON file (persisted via Docker volume).
Supplements static .env — values here override env for integrations
that users set up through the bot's onboarding flow.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_FILE = os.getenv("USER_CONFIG_FILE", "/app/credentials/user_config.json")


def _load() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get(key: str, fallback: str = "") -> str:
    return _load().get(key, fallback)


def set(key: str, value: str) -> None:
    data = _load()
    data[key] = value
    _save(data)
    logger.info("user_config: saved key '%s'", key)


def is_calendar_configured() -> bool:
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "/app/credentials/token.json")
    return os.path.exists(token_file)


def is_notion_configured() -> bool:
    token = get("notion_token") or os.getenv("NOTION_TOKEN", "")
    db_id = get("notion_database_id") or os.getenv("NOTION_DATABASE_ID", "")
    return bool(token and db_id)
