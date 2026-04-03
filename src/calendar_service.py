import logging
import os
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    creds = None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(GOOGLE_TOKEN_FILE), exist_ok=True)
        with open(GOOGLE_TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def create_event(title: str, date_str: str, time_str: str | None = None, description: str | None = None) -> str:
    service = _get_service()

    if time_str:
        start_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        end_dt = start_dt + timedelta(hours=1)
        event_body = {
            "summary": title,
            "description": description or "",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Moscow"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Moscow"},
        }
    else:
        event_body = {
            "summary": title,
            "description": description or "",
            "start": {"date": date_str},
            "end": {"date": date_str},
        }

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    link = event.get("htmlLink", "")
    logger.info("Created event: %s", event.get("id"))
    return link


def list_events(days: int = 7) -> list[dict]:
    service = _get_service()

    now = datetime.now(timezone.utc).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            timeMax=end,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start = item["start"].get("dateTime") or item["start"].get("date")
        events.append({"title": item.get("summary", "Без названия"), "start": start, "link": item.get("htmlLink", "")})

    return events
