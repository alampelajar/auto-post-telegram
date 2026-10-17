# Telegram Auto Post SaaS

Project for a Telegram auto-post SaaS built with Python, FastAPI, aiogram, Telethon, PostgreSQL, Redis, Docker Compose, a scheduler, and workers.

## Status

This repository is the source-of-truth location for the project. The initial repository was empty, so this README initializes the repository. Application files should be pushed from the local backup after checking that secrets, `.env`, Telegram sessions, database volumes, and other sensitive files are excluded.

## Local setup

1. Install Docker Desktop with WSL 2.
2. Restore the project source from its backup.
3. Keep real secrets only in a local `.env` file; do not commit it.
4. From the project root, run `docker compose up -d --build`.
5. Verify API health at `http://localhost:8000/health`.

## Data recovery note

The PostgreSQL Docker volume is separate from the source repository. Restoring source files alone does not restore users, Telegram account sessions, messages, groups, subscriptions, or scheduled jobs. Preserve any old database volume or `.sql`/`.dump` backup before resetting storage.
