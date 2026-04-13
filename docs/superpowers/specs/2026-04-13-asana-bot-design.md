# Asana Bot — Design Spec
Date: 2026-04-13

## Overview

Refactor the existing Telegram voice/text assistant bot to replace Google Calendar and Notion integrations with Asana task management. The bot accepts Russian voice and text input, extracts structured intent via a local or remote LLM, and performs CRUD operations on Asana tasks with deadline notifications.

---

## Branch

`feature/asana-bot` — forked from `master`

---

## What Changes

### Removed
- `src/calendar_service.py`
- `src/notion_service.py`
- `src/oauth_handler.py`
- `src/user_config.py`

### Kept (unchanged)
- `src/whisper_service.py` — voice-to-text via faster-whisper
- `src/date_parser.py` — Russian date extraction

### New / Rewritten
| File | Purpose |
|------|---------|
| `src/asana_service.py` | Asana REST API wrapper (create/read/update tasks, search users/projects) |
| `src/llm_service.py` | Unified LLM interface over Ollama and OpenAI-compatible APIs (replaces `ollama_service.py`) |
| `src/scheduler.py` | APScheduler cron job for deadline notifications |
| `src/team.py` | Team member registry: name → asana_gid + telegram_id, stored in `data/team.json` |
| `src/router.py` | Rewritten: routes Asana intents, validates fields, applies rate limiting |
| `src/bot.py` | Rewritten: removes Calendar/Notion setup flows, adds `/add_member`, `/list_members`, `/remove_member` |
| `src/config.py` | Updated with new env vars |

---

## Architecture

```
Voice/Text
    │
    ▼
Whisper (if voice)
    │
    ▼
llm_service.extract_intent(text)   ← Ollama or OpenAI
    │
    ▼
router.route_action(intent)
    ├── validate intent fields
    ├── check rate limit
    └── dispatch to asana_service
            │
            ▼
        Asana REST API
            │
            ▼
        reply to user (Russian)

scheduler.py (APScheduler cron, daily 09:00)
    └── asana_service.get_tasks_due_soon()
            └── notify admin + assignee via Telegram
```

---

## Intent Schema

LLM output (JSON):
```json
{
  "action": "create_task | update_task | read_tasks | unknown",
  "title": "...",
  "description": "...",
  "due_date": "YYYY-MM-DD",
  "assignee": "Иван",
  "project": "Маркетинг",
  "task_id": "...",
  "update_fields": {
    "due_date": "YYYY-MM-DD",
    "assignee": "Петр"
  }
}
```

Example inputs:
- _"Создай задачу для Ивана в проекте Маркетинг: написать отчёт до пятницы"_ → `create_task`
- _"Покажи задачи проекта Разработка"_ → `read_tasks`
- _"Перенеси дедлайн задачи написать отчёт на следующую неделю"_ → `update_task`

---

## LLM Service (`llm_service.py`)

Configured via `LLM_PROVIDER` env var:

| Provider | Config |
|----------|--------|
| `ollama` (default) | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` |

Both providers expose the same interface:
```python
async def extract_intent(text: str) -> dict: ...
async def chat_reply(text: str) -> str: ...
```

Router does not know which provider is active.

---

## Asana Service (`asana_service.py`)

Authentication: Personal Access Token (`ASANA_PAT` in `.env`).

Operations:
- `create_task(title, description, due_date, assignee_gid, project_gid) → task_gid`
- `get_tasks(project_gid=None, assignee_gid=None) → list[dict]`
- `update_task(task_gid, fields: dict) → None`
- `search_user(name: str) → asana_gid | None` — searches workspace members
- `search_project(name: str) → asana_gid | None` — searches workspace projects
- `get_tasks_due_soon(days: list[int]) → list[dict]` — for scheduler

All calls are synchronous, wrapped with `asyncio.run_in_executor` in router.

---

## Team Registry (`team.py`)

Stored in `data/team.json` (Docker volume):
```json
{
  "Иван": {
    "asana_gid": "1234567890",
    "telegram_username": "ivan_tg",
    "telegram_id": 456789
  }
}
```

- `asana_gid` resolved at add time via `asana_service.search_user(name)`; if not found, `/add_member` replies with error and does not save the entry
- `telegram_id` populated automatically when the member first messages the bot
- Admin is **not** stored here — defined solely by `ADMIN_TELEGRAM_ID` in `.env`

Bot commands (admin only):
- `/add_member Иван @ivan_tg` — looks up Asana user by name, saves entry
- `/list_members` — shows current team table
- `/remove_member Иван` — removes entry and revokes bot access

---

## Access Control

```
Request received
    │
    ├── user_id == ADMIN_TELEGRAM_ID  → allow all commands
    ├── user_id in team (telegram_id) → allow task commands
    └── else                          → reply "нет доступа"
```

- `ADMIN_TELEGRAM_ID` is fixed in `.env` — cannot be changed through the bot
- Team membership grants access; removal revokes it immediately
- First message from a known-username member auto-registers their `telegram_id`

---

## Security

**Prompt injection mitigation (`router.py`):**
- Whitelist of allowed actions: `create_task`, `update_task`, `read_tasks`, `unknown`
- String fields capped at 255 characters
- `due_date` validated as ISO date; rejected if not parseable
- Unknown action → fallback to `unknown` (no side effects)

**Rate limiting:**
- In-memory dict `{user_id: last_request_timestamp}`
- Limit: 1 request per 3 seconds per user
- Exceeded: polite Russian-language reply, no processing

**Secrets:**
- All tokens in `.env`, never committed to git
- `data/team.json` in Docker volume, not in image

---

## Deadline Notifications (`scheduler.py`)

- APScheduler with `AsyncIOScheduler`, starts with the bot
- Cron trigger: daily at `NOTIFY_TIME` (default `09:00`)
- Checks tasks with `due_date` in `DEADLINE_NOTIFY_DAYS` days from today
- For each task:
  - Notifies admin: _"⏰ Задача «X» для Ивана — дедлайн завтра"_
  - Notifies assignee (if `telegram_id` known): _"⏰ Напоминание: задача «X» — дедлайн завтра"_

---

## Configuration (`.env`)

```
TELEGRAM_BOT_TOKEN=
ADMIN_TELEGRAM_ID=

ASANA_PAT=
ASANA_WORKSPACE_GID=

LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:3b

# Optional — used when LLM_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

DEADLINE_NOTIFY_DAYS=1,2
NOTIFY_TIME=09:00
```

---

## Docker

`docker-compose.yml` services:
- `bot` — Python app, mounts `data/` volume for `team.json`
- `ollama` — local LLM (unchanged)

No OAuth callback server needed (removed with Calendar).

---

## Out of Scope

- Asana OAuth2 (PAT is sufficient)
- Webhook-based notifications from Asana
- Multiple workspaces
- Task comments or attachments
- Web UI
