# Requirements

## Functional

### R1 — Telegram Bot
- Accept text messages
- Accept voice messages (OGG format)
- Download voice as temp file
- Send transcription status feedback to user

### R2 — Voice Transcription
- Use faster-whisper with model `small` or `medium`
- Language: `ru` (Russian)
- Transcribe OGG file to plain text
- Run in same Python process (not separate service)

### R3 — Intent Extraction
- Send transcribed/input text to Ollama via HTTP POST
- Model: configurable (default: llama3.2:3b)
- Return valid JSON: action, title, date, time, description
- Handle invalid JSON response gracefully (retry or fallback)

### R4 — Google Calendar
- OAuth2 flow (one-time, stores token.json)
- Create event with title, date/time, description
- Read upcoming events (next 7 days)
- Return confirmation with event link

### R5 — Notion
- Integration Token auth
- Create page in database with title, description, date
- Read recent entries
- Return confirmation with page URL

### R6 — Docker
- Single `docker-compose.yml` with: bot service + ollama service
- `.env` file for all secrets
- Volume for token.json persistence
- Health check on ollama service
- README with setup instructions

## Non-Functional
- No GPU required
- Startup time < 30s (excluding model pull)
- Handle concurrent users (async handlers)
- Graceful error messages to user in Russian
