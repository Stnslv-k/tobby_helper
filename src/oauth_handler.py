"""
Lightweight aiohttp server that handles Google OAuth2 callback.
Runs alongside the Telegram bot in the same process.

Flow:
  1. /setup_calendar → bot sends OAuth URL to user
  2. User clicks → Google redirects to http://YOUR_HOST:8080/oauth_callback?code=...
  3. This handler exchanges code for token, saves token.json
  4. Bot notifies user that Calendar is ready
"""
import asyncio
import logging
import os
from typing import Callable, Awaitable

from aiohttp import web
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
OAUTH_PORT = int(os.getenv("OAUTH_PORT", "8080"))
OAUTH_CALLBACK_PATH = "/oauth_callback"

# Callback registered by the bot to notify user when auth completes
_on_auth_complete: Callable[[bool, str], Awaitable[None]] | None = None
_pending_state: str | None = None


def register_auth_callback(cb: Callable[[bool, str], Awaitable[None]]) -> None:
    global _on_auth_complete
    _on_auth_complete = cb


def build_auth_url(redirect_uri: str) -> tuple[str, str]:
    """Returns (authorization_url, state)."""
    global _pending_state
    flow = Flow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _pending_state = state
    return auth_url, state


async def _handle_callback(request: web.Request) -> web.Response:
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")

    if error:
        logger.warning("OAuth error: %s", error)
        if _on_auth_complete:
            await _on_auth_complete(False, f"Ошибка авторизации: {error}")
        return web.Response(
            text="<h2>Ошибка авторизации.</h2><p>Вернись в Telegram и попробуй снова.</p>",
            content_type="text/html",
        )

    if not code:
        return web.Response(text="Bad request: missing code", status=400)

    redirect_uri = str(request.url.with_query(None))

    try:
        flow = Flow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_FILE, scopes=SCOPES, state=state
        )
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        creds: Credentials = flow.credentials

        os.makedirs(os.path.dirname(GOOGLE_TOKEN_FILE), exist_ok=True)
        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

        logger.info("OAuth token saved to %s", GOOGLE_TOKEN_FILE)

        if _on_auth_complete:
            await _on_auth_complete(True, "Google Calendar успешно подключён!")

        return web.Response(
            text=(
                "<h2>Авторизация успешна!</h2>"
                "<p>Google Calendar подключён. Можешь закрыть эту страницу и вернуться в Telegram.</p>"
            ),
            content_type="text/html",
        )
    except Exception as e:
        logger.error("OAuth token exchange failed: %s", e)
        if _on_auth_complete:
            await _on_auth_complete(False, f"Не удалось завершить авторизацию: {e}")
        return web.Response(text=f"<h2>Ошибка</h2><p>{e}</p>", content_type="text/html")


async def start_oauth_server() -> None:
    app = web.Application()
    app.router.add_get(OAUTH_CALLBACK_PATH, _handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", OAUTH_PORT)
    await site.start()
    logger.info("OAuth callback server listening on port %d", OAUTH_PORT)
