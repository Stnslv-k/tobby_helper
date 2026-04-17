import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
_admin_raw: str = os.environ["ADMIN_TELEGRAM_IDS"]
ADMIN_TELEGRAM_IDS: list[int] = [int(x.strip()) for x in _admin_raw.split(",")]

ASANA_PAT: str = os.environ["ASANA_PAT"]
ASANA_WORKSPACE_GID: str = os.environ["ASANA_WORKSPACE_GID"]

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
if LLM_PROVIDER not in {"ollama", "openai"}:
    raise ValueError(f"LLM_PROVIDER must be 'ollama' or 'openai', got: {LLM_PROVIDER!r}")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")
WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "ru")

_days_raw: str = os.getenv("DEADLINE_NOTIFY_DAYS", "1,2")
DEADLINE_NOTIFY_DAYS: list[int] = [int(d.strip()) for d in _days_raw.split(",")]
NOTIFY_TIME: str = os.getenv("NOTIFY_TIME", "09:00")

TEAM_FILE: str = os.getenv("TEAM_FILE", "data/team.json")
RATE_LIMIT_SECONDS: int = int(os.getenv("RATE_LIMIT_SECONDS", "3"))
