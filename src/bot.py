import asyncio
import logging
import os
import tempfile

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import asana_service
from config import ADMIN_TELEGRAM_IDS, TELEGRAM_BOT_TOKEN
from llm_service import process_message
from router import check_rate_limit
import scheduler
import team
from whisper_service import transcribe

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_app: Application | None = None


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TELEGRAM_IDS


async def _check_access(update: Update) -> bool:
    user = update.effective_user
    # Auto-register telegram_id for known team members by username
    if user.username:
        uname = f"@{user.username}"
        for member in team.list_members():
            if member.get("telegram_username") == uname and not member.get("telegram_id"):
                team.set_telegram_id(member["name"], user.id)
                logger.info("Registered telegram_id %d for %s", user.id, member["name"])
    if team.is_allowed(user.id, ADMIN_TELEGRAM_IDS):
        return True
    await update.effective_message.reply_text("У вас нет доступа к этому боту.")
    return False


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if _is_admin(update.effective_user.id):
        text = (
            "Привет, Админ!\n\n"
            "Управление командой:\n"
            "• /add_member Иван @ivan_tg\n"
            "• /list_members\n"
            "• /remove_member Иван\n\n"
            "Или отправь голосовое/текстовое сообщение с задачей."
        )
    else:
        text = (
            "Привет! Отправь голосовое или текстовое сообщение, например:\n"
            "• «Создай задачу для Ивана в проекте Маркетинг: написать отчёт до пятницы»\n"
            "• «Покажи задачи проекта Разработка»"
        )
    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Team management commands (admin only)
# ---------------------------------------------------------------------------

async def cmd_add_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда только для администратора.")
        return
    args = context.args or []
    if len(args) < 2 or not args[-1].startswith("@"):
        await update.message.reply_text("Использование: /add_member Имя @username")
        return
    username = args[-1]
    name = " ".join(args[:-1])
    await update.message.reply_text(f"Ищу «{name}» в Asana...")
    loop = asyncio.get_event_loop()
    asana_gid = await loop.run_in_executor(None, asana_service.search_user, name)
    if not asana_gid:
        await update.message.reply_text(
            f"Пользователь «{name}» не найден в Asana. Проверь написание имени."
        )
        return
    team.add_member(name, asana_gid, username)
    await update.message.reply_text(
        f"Участник добавлен:\n👤 {name}\n📱 {username}\n\n"
        f"Как только {username} напишет боту — уведомления активируются."
    )


async def cmd_list_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда только для администратора.")
        return
    members = team.list_members()
    if not members:
        await update.message.reply_text("Команда пуста. Добавь участников: /add_member Имя @username")
        return
    lines = ["Члены команды:"]
    for m in members:
        if m.get("telegram_id"):
            tg = f"✅ {m['telegram_username']}"
        else:
            tg = f"⏳ {m.get('telegram_username', '—')} (ещё не писал боту)"
        lines.append(f"• {m['name']} — {tg}")
    await update.message.reply_text("\n".join(lines))


async def cmd_remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда только для администратора.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /remove_member Имя")
        return
    name = " ".join(context.args)
    if team.remove_member(name):
        await update.message.reply_text(f"Участник «{name}» удалён.")
    else:
        await update.message.reply_text(f"Участник «{name}» не найден.")


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text("Подожди пару секунд перед следующим запросом.")
        return
    await _process_input(update, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text("Подожди пару секунд перед следующим запросом.")
        return
    await update.message.reply_text("Транскрибирую голосовое сообщение...")
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        await file.download_to_drive(tmp_path)
        text = await transcribe(tmp_path)
        await update.message.reply_text(f"Распознано: {text}")
        await _process_input(update, text)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def _process_input(update: Update, text: str) -> None:
    await update.message.reply_text("Обрабатываю запрос...")
    try:
        response = await process_message(text)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error("Error processing input: %s", e)
        await update.message.reply_text("Произошла ошибка. Попробуй ещё раз.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _send_notification(chat_id: int, text: str) -> None:
    if _app:
        await _app.bot.send_message(chat_id, text)


def main() -> None:
    global _app
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _app = app

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_member", cmd_add_member))
    app.add_handler(CommandHandler("list_members", cmd_list_members))
    app.add_handler(CommandHandler("remove_member", cmd_remove_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    async def post_init(application: Application) -> None:
        scheduler.start_scheduler(_send_notification)

    app.post_init = post_init
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
