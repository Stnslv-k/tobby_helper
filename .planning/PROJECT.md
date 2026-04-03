# Voice Assistant Telegram Bot

## Overview
A Telegram bot that accepts voice and text messages, transcribes voice to text via faster-whisper, extracts structured intent via Ollama (local LLM), and routes actions to Google Calendar and Notion APIs. Deployable as a Docker container on Hostinger.

## Stack
- **Bot**: python-telegram-bot v20+ (async)
- **STT**: faster-whisper (CPU, model: small/medium, Russian language)
- **LLM**: Ollama via HTTP API (llama3.2:3b or mistral)
- **Calendar**: google-api-python-client (OAuth2)
- **Notion**: notion-client (Integration Token)
- **Infra**: Docker + docker-compose, deployable on Hostinger VPS

## Intent Schema
```json
{
  "action": "create_event|add_to_notion|read_calendar|read_notion|unknown",
  "title": "...",
  "date": "...",
  "description": "...",
  "time": "..."
}
```

## Key Constraints
- Runs on CPU (no GPU required)
- Russian language primary
- Ollama runs as a separate container
- OAuth2 token stored in volume (token.json)
- Secrets via .env file

## Milestone 1: MVP Bot
Fully working bot with all integrations in Docker.
