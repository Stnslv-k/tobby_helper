import logging
import re
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


def _get_title_property(client: Client, db_id: str) -> str:
    db = client.databases.retrieve(database_id=db_id)
    for name, prop in db["properties"].items():
        if prop["type"] == "title":
            return name
    raise RuntimeError("В базе данных Notion не найдено поле-заголовок.")


def _extract_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            title_list = prop.get("title", [])
            return title_list[0]["plain_text"] if title_list else "Без названия"
    return "Без названия"


def _page_id_from_url(url: str) -> str:
    match = re.search(r"([a-f0-9]{32})(?:[?#]|$)", url.replace("-", ""))
    if match:
        raw = match.group(1)
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    raise ValueError(f"Не удалось извлечь ID страницы из URL: {url}")


def create_page(title: str, description: str | None = None, date_str: str | None = None) -> str:
    client = _get_client()
    db_id = _db_id()
    title_prop = _get_title_property(client, db_id)

    properties: dict = {
        title_prop: {
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
        parent={"database_id": db_id},
        properties=properties,
        children=children,
    )

    page_url = page.get("url", "")
    logger.info("Created Notion page: %s", page.get("id"))
    return page_url


def find_page_by_title(title: str) -> str | None:
    client = _get_client()
    response = client.databases.query(database_id=_db_id())
    for page in response.get("results", []):
        page_title = _extract_title(page)
        if page_title.lower() == title.lower():
            return page.get("url", "")
    return None


def update_page(page_url: str, date_str: str | None = None, title: str | None = None) -> str:
    client = _get_client()
    page_id = _page_id_from_url(page_url)

    properties: dict = {}

    if title:
        title_prop = _get_title_property(client, _db_id())
        properties[title_prop] = {"title": [{"text": {"content": title}}]}

    if date_str:
        properties["Date"] = {"date": {"start": date_str}}

    if not properties:
        raise ValueError("Нечего обновлять.")

    client.pages.update(page_id=page_id, properties=properties)
    logger.info("Updated Notion page: %s", page_id)
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
        title = _extract_title(page)
        pages.append({"title": title, "url": page.get("url", ""), "id": page.get("id", "")})

    return pages
