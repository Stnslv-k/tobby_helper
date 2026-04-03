# Voice Assistant Telegram Bot

Telegram-бот с голосовым вводом, транскрипцией через faster-whisper, локальной LLM (Ollama) и интеграциями Google Calendar и Notion.

## Архитектура

```
Telegram Bot (python-telegram-bot)
    ↓
OGG/голос → faster-whisper → текст
    ↓
Ollama (llama3.2:3b) → JSON намерение
    ↓
┌─────────────────────┐
│  Google Calendar    │
│  Notion             │
└─────────────────────┘
    ↓
Ответ пользователю
```

---

## Деплой на Hostinger VPS — пошаговая инструкция

### Шаг 1. Купить и настроить VPS

1. Зайди на [hostinger.com](https://hostinger.com) → раздел **VPS Hosting**
2. Выбери план:
   - **KVM 2** (8 GB RAM) — рекомендуется (Ollama + Whisper работают комфортно)
   - **KVM 1** (4 GB RAM) — минимум, может быть медленно
3. При настройке сервера выбери **Ubuntu 22.04**
4. Задай root-пароль или загрузи SSH-ключ
5. Запомни **IP-адрес** сервера (виден в панели Hostinger)

### Шаг 2. Подключиться к серверу

На своём компьютере открой терминал:

```bash
ssh root@YOUR_VPS_IP
```

Если используешь Windows — скачай [PuTTY](https://putty.org) или используй Windows Terminal.

### Шаг 3. Установить Docker

Выполни на сервере:

```bash
curl -fsSL https://get.docker.com | sh
```

Проверь что установилось:

```bash
docker --version
docker compose version
```

### Шаг 4. Открыть порт 8080 (для Google OAuth)

```bash
ufw allow 8080/tcp
ufw allow 22/tcp
ufw enable
```

> Порт 8080 нужен только для первичной авторизации Google Calendar.
> После получения токена его можно закрыть: `ufw delete allow 8080/tcp`

### Шаг 5. Загрузить проект на сервер

**Вариант А — через Git (рекомендуется)**

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /opt/voicebot
cd /opt/voicebot
```

**Вариант Б — загрузить файлы вручную через SFTP**

С локального компьютера (в отдельном терминале):

```bash
# Скопировать всю папку проекта на сервер
scp -r /путь/к/проекту/* root@YOUR_VPS_IP:/opt/voicebot/
```

Или используй [FileZilla](https://filezilla-project.org) (бесплатный SFTP-клиент с интерфейсом).

### Шаг 6. Создать файл .env

```bash
cd /opt/voicebot
cp .env.example .env
nano .env
```

Заполни обязательные поля:

```
TELEGRAM_BOT_TOKEN=твой_токен_от_BotFather
OAUTH_PUBLIC_HOST=http://YOUR_VPS_IP:8080
```

Сохрани: `Ctrl+O`, Enter, `Ctrl+X`.

### Шаг 7. Добавить credentials.json для Google Calendar

> Пропусти этот шаг если не планируешь использовать Google Calendar.

С **локального компьютера**:

```bash
# Создать папку credentials на сервере
ssh root@YOUR_VPS_IP "mkdir -p /opt/voicebot/credentials"

# Скопировать файл credentials.json
scp /путь/к/credentials.json root@YOUR_VPS_IP:/opt/voicebot/credentials/credentials.json
```

Как получить credentials.json — см. раздел «Настройка Google Calendar» ниже.

### Шаг 8. Запустить бота

```bash
cd /opt/voicebot
docker compose up -d
```

Первый запуск займёт 5–10 минут (скачивается образ Ollama, собирается образ бота, загружается модель Whisper).

### Шаг 9. Скачать языковую модель Ollama

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

Загрузка ~2 GB, займёт несколько минут.

### Шаг 10. Проверить что всё работает

```bash
# Посмотреть логи бота
docker compose logs -f bot

# Проверить что оба контейнера запущены
docker compose ps
```

Открой Telegram, найди своего бота и напиши `/start`.

---

## Настройка Google Calendar (один раз)

### Создать credentials.json в Google Cloud Console

1. Перейди на [console.cloud.google.com](https://console.cloud.google.com)
2. Нажми «Select a project» → «New Project» → задай название → «Create»
3. В меню слева: **APIs & Services** → **Library**
4. Найди **Google Calendar API** → нажми **Enable**
5. Перейди в **APIs & Services** → **Credentials**
6. Нажми **Create Credentials** → **OAuth client ID**
7. Если просит настроить Consent Screen — нажми «Configure», заполни название приложения, свой email, сохрани
8. Вернись в Credentials → Create Credentials → OAuth client ID
9. Тип приложения: **Web application**
10. В поле **Authorised redirect URIs** нажми «Add URI» и введи:
    ```
    http://YOUR_VPS_IP:8080/oauth_callback
    ```
11. Нажми **Create** → скачай JSON-файл → переименуй в `credentials.json`

### Авторизоваться через бота

После запуска бота:
1. Напиши `/start`
2. Нажми кнопку «Подключить Google Calendar»
3. Бот пришлёт ссылку — открой её в браузере
4. Войди в свой аккаунт Google → разреши доступ
5. Тебя перенаправит на страницу «Авторизация успешна!»
6. Бот напишет подтверждение в Telegram

---

## Настройка Notion (через бота)

Напиши `/start` → нажми «Подключить Notion».
Бот проведёт через два шага:
1. Создание Integration и ввод токена
2. Привязка базы данных и ввод её ID

---

## Полезные команды на сервере

```bash
# Перезапустить бота
docker compose restart bot

# Посмотреть логи в реальном времени
docker compose logs -f bot

# Остановить всё
docker compose down

# Обновить бота после изменений в коде
docker compose up -d --build bot

# Посмотреть использование ресурсов
docker stats
```

---

## Переменные окружения

| Переменная | Описание | Обязательно |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather | да |
| `OAUTH_PUBLIC_HOST` | Публичный адрес сервера для OAuth | для Calendar |
| `OLLAMA_MODEL` | Модель Ollama | нет (по умолч. `llama3.2:3b`) |
| `WHISPER_MODEL` | Размер модели Whisper | нет (по умолч. `small`) |
| `WHISPER_LANGUAGE` | Язык транскрипции | нет (по умолч. `ru`) |
| `NOTION_TOKEN` | Можно задать вместо настройки через бота | нет |
| `NOTION_DATABASE_ID` | Можно задать вместо настройки через бота | нет |

---

## Примеры команд боту

- «Создай встречу с командой завтра в 15:00»
- «Запланируй звонок с клиентом на пятницу в 11:00»
- «Добавь в Notion идею: сделать редизайн сайта»
- «Покажи события на эту неделю»
- «Что у меня в Notion?»
