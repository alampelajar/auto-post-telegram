# Telegram Auto Post SaaS — Starter

Fondasi Phase 0 untuk layanan Auto Post Telegram yang dapat diskalakan.

## Stack
- FastAPI 0.141.1
- aiogram 3.31.0
- Telethon 1.43.2
- SQLAlchemy 2.0.54 + asyncpg
- Redis 8.1.0
- PostgreSQL 18

## Services
- `api`: REST API + health checks
- `bot`: Telegram Bot controller
- `scheduler`: scheduler heartbeat / future job enqueue point
- `worker`: queue consumer / future Telegram sender
- `postgres`: persistent data
- `redis`: queue, locks, rate limit, cache

## Start
1. Copy `.env.example` to `.env` and fill secrets.
2. Run `docker compose up --build`.
3. Initialize the database: `docker compose exec api python scripts/init_db.py`.
4. Health check: `GET http://localhost:8000/health`.

## Important
User Telegram sessions must be treated as sensitive credentials. Do not put session strings in logs or source control. The account-connection flow is intentionally not implemented in this foundation step; it will be added after the core infrastructure is stable.
