import logging
import os
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from config import TELEGRAM_BOT_TOKEN
from whisper_service import transcribe
from ollama_service import extract_intent, chat_reply
from router import route_action
from user_config import (
    is_calendar_configured,
    is_notion_configured,
    set as config_set,
    get as config_get,
)
from oauth_handler import build_auth_url, register_auth_callback, start_oauth_server

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ConversationHandler states for Notion setup
NOTION_STEP_TOKEN, NOTION_STEP_DB_ID = range(2)

# Filled by the bot instance after Application is built
_app: Application | None = None
_setup_chat_id: int | None = None


# ---------------------------------------------------------------------------
# /start — onboarding
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cal_ok = is_calendar_configured()
    notion_ok = is_notion_configured()

    cal_icon = "✅" if cal_ok else "❌"
    notion_icon = "✅" if notion_ok else "❌"

    text = (
        "Привет! Я голосовой ассистент.\n\n"
        f"{cal_icon} Google Calendar {'подключён' if cal_ok else 'не настроен'}\n"
        f"{notion_icon} Notion {'подключён' if notion_ok else 'не настроен'}\n\n"
    )

    buttons = []
    if not cal_ok:
        buttons.append([InlineKeyboardButton("🔗 Подключить Google Calendar", callback_data="setup_calendar")])
    if not notion_ok:
        buttons.append([InlineKeyboardButton("📝 Подключить Notion", callback_data="setup_notion")])

    if not buttons:
        text += (
            "Всё готово! Отправь голосовое сообщение или текст, например:\n"
            "• «Создай встречу завтра в 15:00»\n"
            "• «Добавь в Notion идею про новый проект»\n"
            "• «Покажи события на неделю»"
        )
    else:
        text += "Для начала работы подключи интеграции:"

    markup = InlineKeyboardMarkup(buttons) if buttons else None
    await update.message.reply_text(text, reply_markup=markup)


# ---------------------------------------------------------------------------
# /setup_calendar — Google OAuth via link
# ---------------------------------------------------------------------------

async def setup_calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_calendar_auth_link(update.effective_chat.id, context)


async def setup_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _send_calendar_auth_link(update.effective_chat.id, context)


async def _send_calendar_auth_link(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _setup_chat_id

    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "/app/credentials/credentials.json")
    if not os.path.exists(credentials_file):
        await context.bot.send_message(
            chat_id,
            "⚠️ Файл credentials.json не найден.\n\n"
            "Попроси администратора разместить его по пути:\n"
            f"`{credentials_file}`",
            parse_mode="Markdown",
        )
        return

    host = os.getenv("OAUTH_PUBLIC_HOST", "http://localhost:8080")
    redirect_uri = f"{host}/oauth_callback"

    try:
        auth_url, _ = build_auth_url(redirect_uri)
        _setup_chat_id = chat_id

        await context.bot.send_message(
            chat_id,
            "Для подключения Google Calendar:\n\n"
            "1. Нажми кнопку ниже\n"
            "2. Войди в свой аккаунт Google\n"
            "3. Разреши доступ к Calendar\n"
            "4. Вернись сюда — бот подтвердит подключение\n\n"
            "🔒 Токен сохраняется только на сервере бота.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Авторизоваться в Google", url=auth_url)
            ]]),
        )
    except FileNotFoundError:
        await context.bot.send_message(
            chat_id,
            "⚠️ Не найден файл credentials.json. Обратись к администратору.",
        )


# ---------------------------------------------------------------------------
# Notion setup — ConversationHandler
# ---------------------------------------------------------------------------

async def setup_notion_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Настройка Notion. Нужно 2 значения.\n\n"
        "*Шаг 1 из 2 — Integration Token*\n\n"
        "1. Перейди на https://www.notion.so/my-integrations\n"
        "2. Нажми «New integration»\n"
        "3. Дай название (например: «Мой бот»)\n"
        "4. Нажми «Submit»\n"
        "5. Скопируй *Internal Integration Token* (начинается с `secret_`)\n\n"
        "Отправь токен сюда:",
        parse_mode="Markdown",
    )
    return NOTION_STEP_TOKEN


async def setup_notion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await context.bot.send_message(
        update.effective_chat.id,
        "Настройка Notion. Нужно 2 значения.\n\n"
        "*Шаг 1 из 2 — Integration Token*\n\n"
        "1. Перейди на https://www.notion.so/my-integrations\n"
        "2. Нажми «New integration»\n"
        "3. Дай название (например: «Мой бот»)\n"
        "4. Нажми «Submit»\n"
        "5. Скопируй *Internal Integration Token* (начинается с `secret_`)\n\n"
        "Отправь токен сюда:",
        parse_mode="Markdown",
    )
    return NOTION_STEP_TOKEN


async def notion_receive_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()
    if not token.startswith("secret_"):
        await update.message.reply_text(
            "Токен должен начинаться с `secret_`. Попробуй ещё раз:",
            parse_mode="Markdown",
        )
        return NOTION_STEP_TOKEN

    context.user_data["notion_token_temp"] = token

    await update.message.reply_text(
        "Токен принят.\n\n"
        "*Шаг 2 из 2 — ID базы данных*\n\n"
        "1. Открой нужную базу данных в Notion\n"
        "2. Нажми «Share» → «Invite» → выбери свою интеграцию\n"
        "3. Скопируй ID из URL:\n"
        "   `https://notion.so/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...`\n"
        "   Это 32 символа после последнего `/` и до `?`\n\n"
        "Отправь ID базы данных:",
        parse_mode="Markdown",
    )
    return NOTION_STEP_DB_ID


async def notion_receive_db_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    # Accept both with and without hyphens
    db_id = raw.replace("-", "")
    if len(db_id) != 32 or not db_id.isalnum():
        await update.message.reply_text(
            "ID должен содержать 32 символа (буквы и цифры). Попробуй ещё раз:",
        )
        return NOTION_STEP_DB_ID

    # Normalise to UUID format
    db_id_formatted = f"{db_id[:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:]}"

    token = context.user_data.pop("notion_token_temp")
    config_set("notion_token", token)
    config_set("notion_database_id", db_id_formatted)

    await update.message.reply_text(
        "Notion успешно подключён!\n\n"
        "Теперь можешь говорить:\n"
        "• «Добавь в Notion задачу: написать отчёт»\n"
        "• «Что у меня в Notion?»"
    )
    return ConversationHandler.END


async def notion_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("notion_token_temp", None)
    await update.message.reply_text("Настройка Notion отменена.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# OAuth completion callback (called from oauth_handler)
# ---------------------------------------------------------------------------

async def _on_oauth_complete(success: bool, message: str) -> None:
    if _app and _setup_chat_id:
        icon = "✅" if success else "❌"
        await _app.bot.send_message(_setup_chat_id, f"{icon} {message}")


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cal_icon = "✅" if is_calendar_configured() else "❌"
    notion_icon = "✅" if is_notion_configured() else "❌"
    await update.message.reply_text(
        f"Статус интеграций:\n\n"
        f"{cal_icon} Google Calendar\n"
        f"{notion_icon} Notion"
    )


# ---------------------------------------------------------------------------
# Main message handlers
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await process_input(update, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Транскрибирую голосовое сообщение...")
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await file.download_to_drive(tmp_path)
        text = await transcribe(tmp_path)
        await update.message.reply_text(f"Распознано: {text}")
        await process_input(update, text)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def process_input(update: Update, text: str) -> None:
    await update.message.reply_text("Обрабатываю запрос...")
    try:
        intent = await extract_intent(text)
        if intent.get("action") == "unknown":
            response = await chat_reply(text)
        else:
            response = await route_action(intent)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error("Error processing input: %s", e)
        await update.message.reply_text("Произошла ошибка при обработке запроса. Попробуй ещё раз.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global _app

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _app = app

    register_auth_callback(_on_oauth_complete)

    # Notion setup conversation
    notion_conv = ConversationHandler(
        entry_points=[
            CommandHandler("setup_notion", setup_notion_command),
            CallbackQueryHandler(setup_notion_callback, pattern="^setup_notion$"),
        ],
        states={
            NOTION_STEP_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, notion_receive_token)],
            NOTION_STEP_DB_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, notion_receive_db_id)],
        },
        fallbacks=[CommandHandler("cancel", notion_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setup_calendar", setup_calendar_command))
    app.add_handler(notion_conv)
    app.add_handler(CallbackQueryHandler(setup_calendar_callback, pattern="^setup_calendar$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    async def post_init(application: Application) -> None:
        await start_oauth_server()

    app.post_init = post_init

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
