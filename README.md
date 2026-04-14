# Asana Voice Bot

Telegram-бот с голосовым вводом. Принимает голосовые и текстовые сообщения, распознаёт намерение через LLM и управляет задачами в Asana. Ежедневно уведомляет о приближающихся дедлайнах.

## Архитектура

```
Telegram (голос / текст)
    ↓
faster-whisper → текст
    ↓
LLM (Ollama / OpenAI) → JSON-намерение
    ↓
router.py → asana_service.py → Asana REST API
    ↓
scheduler.py → уведомления о дедлайнах
```

---

## Установка на VPS

### Требования к серверу

- Ubuntu 22.04 или 24.04
- 4 GB RAM минимум (8 GB рекомендуется если используешь Ollama)
- Docker + Docker Compose

### Шаг 1. Подключиться к серверу

```bash
ssh root@YOUR_VPS_IP
```

### Шаг 2. Установить Docker

```bash
curl -fsSL https://get.docker.com | sh
```

Проверь:

```bash
docker --version
docker compose version
```

### Шаг 3. Загрузить проект

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /opt/asana-bot
cd /opt/asana-bot
```

Или через SFTP — скопируй папку проекта в `/opt/asana-bot`.

### Шаг 4. Создать .env

```bash
cp .env.example .env
nano .env
```

Заполни обязательные поля (подробнее — в разделе «Переменные окружения»):

```
TELEGRAM_BOT_TOKEN=...
ADMIN_TELEGRAM_ID=...
ASANA_PAT=...
ASANA_WORKSPACE_GID=...
```

Сохрани: `Ctrl+O` → Enter → `Ctrl+X`.

### Шаг 5. Создать папку для данных команды

```bash
mkdir -p /opt/asana-bot/data
```

Docker смонтирует её как том — в ней хранится `team.json`.

### Шаг 6. Запустить бота

```bash
docker compose up -d
```

Первый запуск занимает несколько минут — Docker собирает образ и загружает модель Whisper.

### Шаг 7. Проверить

```bash
docker compose logs -f bot
```

Открой Telegram, напиши боту `/start`. Бот должен ответить приветствием.

---

## Получить токен Asana (PAT)

1. Войди в Asana → нажми аватар в правом верхнем углу → **My settings**
2. Вкладка **Apps** → **Manage Developer Apps**
3. Нажми **+ New access token** → задай название → скопируй токен
4. Вставь в `.env` как `ASANA_PAT=...`

## Найти Workspace GID

1. В браузере открой [app.asana.com/api/1.0/workspaces](https://app.asana.com/api/1.0/workspaces) (залогинься)
2. В ответе найди `"gid"` своего workspace
3. Вставь в `.env` как `ASANA_WORKSPACE_GID=...`

## Узнать свой Telegram ID (для ADMIN_TELEGRAM_ID)

Напиши боту [@userinfobot](https://t.me/userinfobot) в Telegram — он пришлёт твой числовой ID.

---

## Онбординг администратора

После первого запуска бота:

1. Напиши боту `/start` — получишь меню администратора
2. Добавь членов команды командой `/add_member`:

```
/add_member Иван Петров @ivan_tg
```

Бот сам найдёт пользователя в Asana по имени и сохранит его Telegram username. Если имя не найдено — проверь точное написание в Asana.

3. Проверь список командой `/list_members` — увидишь кто уже писал боту (✅) и кто ещё нет (⏳).

4. Чтобы удалить участника: `/remove_member Иван Петров`

### Управление задачами (текст и голос)

Примеры команд:

```
Создай задачу для Ивана в проекте Маркетинг: написать квартальный отчёт до 20 апреля
Покажи задачи проекта Разработка
Обнови задачу 1234567890: перенеси дедлайн на следующую пятницу
```

Голосовые сообщения работают так же.

---

## Онбординг исполнителей

Исполнителю достаточно одного шага:

**Написать боту `/start`** — бот автоматически свяжет его Telegram username с записью в команде и активирует уведомления о дедлайнах.

> Уведомления приходят ежедневно в `NOTIFY_TIME` (по умолчанию 09:00) за `DEADLINE_NOTIFY_DAYS` дней до дедлайна (по умолчанию за 1 и 2 дня).

После этого исполнитель может:
- Просматривать свои задачи голосом или текстом
- Получать ежедневные напоминания о приближающихся дедлайнах

---

## LLM: Ollama или OpenAI

По умолчанию бот использует **локальную Ollama** на хосте (`http://172.20.0.1:11434`).

Чтобы запустить Ollama на VPS вне Docker:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

Чтобы переключиться на **OpenAI** — в `.env`:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

---

## Переменные окружения

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | да | Токен от @BotFather |
| `ADMIN_TELEGRAM_ID` | да | Числовой Telegram ID администратора |
| `ASANA_PAT` | да | Personal Access Token Asana |
| `ASANA_WORKSPACE_GID` | да | GID workspace в Asana |
| `LLM_PROVIDER` | нет | `ollama` (по умолч.) или `openai` |
| `OLLAMA_BASE_URL` | нет | URL Ollama (по умолч. `http://172.20.0.1:11434`) |
| `OLLAMA_MODEL` | нет | Модель Ollama (по умолч. `llama3.2:3b`) |
| `OPENAI_API_KEY` | если openai | Ключ OpenAI |
| `OPENAI_MODEL` | нет | Модель OpenAI (по умолч. `gpt-4o-mini`) |
| `WHISPER_MODEL` | нет | Размер модели Whisper (по умолч. `small`) |
| `WHISPER_LANGUAGE` | нет | Язык транскрипции (по умолч. `ru`) |
| `DEADLINE_NOTIFY_DAYS` | нет | За сколько дней уведомлять (по умолч. `1,2`) |
| `NOTIFY_TIME` | нет | Время уведомлений HH:MM (по умолч. `09:00`) |
| `RATE_LIMIT_SECONDS` | нет | Пауза между запросами (по умолч. `3`) |

---

## Полезные команды на сервере

```bash
# Логи в реальном времени
docker compose logs -f bot

# Перезапустить бота
docker compose restart bot

# Обновить после изменений в коде
docker compose up -d --build bot

# Остановить
docker compose down

# Использование ресурсов
docker stats
```
