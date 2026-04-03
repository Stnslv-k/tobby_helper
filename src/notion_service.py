import logging
from datetime import date

from notion_client import Client

import user_config
from config import NOTION_TOKEN, NOTION_DATABASE_ID

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    token = user_config.get("notion_token") or NOTION_TOKEN
    if not token:
        raise RuntimeError("Notion не настроен. Отправь /setup_notion для подключения.")
    return Client(auth=token)


def _db_id() -> str:
    db_id = user_config.get("notion_database_id") or NOTION_DATABASE_ID
    if not db_id:
        raise RuntimeError("Notion не настроен. Отправь /setup_notion для подключения.")
    return db_id


def create_page(title: str, description: str | None = None, date_str: str | None = None) -> str:
    client = _get_client()

    properties: dict = {
        "Name": {
            "title": [{"text": {"content": title}}]
        }
    }

    if date_str:
        properties["Date"] = {"date": {"start": date_str}}

    children = []
    if description:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": description}}]
            },
        })

    page = client.pages.create(
        parent={"database_id": _db_id()},
        properties=properties,
        children=children,
    )

    page_url = page.get("url", "")
    logger.info("Created Notion page: %s", page.get("id"))
    return page_url


def list_pages(limit: int = 5) -> list[dict]:
    client = _get_client()

    response = client.databases.query(
        database_id=_db_id(),
        sorts=[{"timestamp": "created_time", "direction": "descending"}],
        page_size=limit,
    )

    pages = []
    for page in response.get("results", []):
        title_prop = page.get("properties", {}).get("Name", {})
        title_list = title_prop.get("title", [])
        title = title_list[0]["plain_text"] if title_list else "Без названия"
        pages.append({"title": title, "url": page.get("url", ""), "id": page.get("id", "")})

    return pages
