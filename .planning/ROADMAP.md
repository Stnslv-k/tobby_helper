# Roadmap — Voice Assistant Bot

## Milestone 1: MVP Bot

### Phase 1: Project Skeleton
- [ ] Directory structure
- [ ] requirements.txt
- [ ] .env.example
- [ ] config.py

### Phase 2: Telegram Bot Core
- [ ] bot.py with async handlers (text + voice)
- [ ] Voice download + temp file management

### Phase 3: Whisper Integration
- [ ] whisper_service.py
- [ ] OGG → text transcription

### Phase 4: Ollama Intent Extraction
- [ ] ollama_service.py
- [ ] Prompt engineering for Russian input
- [ ] JSON parsing + retry logic

### Phase 5: Google Calendar Integration
- [ ] calendar_service.py
- [ ] OAuth2 setup + token.json persistence
- [ ] create_event / list_events

### Phase 6: Notion Integration
- [ ] notion_service.py
- [ ] create_page / list_pages

### Phase 7: Action Router
- [ ] router.py — dispatch intent to correct service
- [ ] User-facing response formatting in Russian

### Phase 8: Docker
- [ ] Dockerfile
- [ ] docker-compose.yml (bot + ollama)
- [ ] .dockerignore
- [ ] README.md with Hostinger deploy instructions
