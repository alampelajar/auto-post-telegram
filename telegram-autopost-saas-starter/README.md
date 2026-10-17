# Telegram Auto Post SaaS — Phase 1

Fondasi SaaS Telegram Auto Post dengan pemisahan API, Bot, Scheduler, Worker, PostgreSQL, dan Redis.

## Stack
- FastAPI
- aiogram
- Telethon (Phase 2: user-account connection)
- SQLAlchemy + asyncpg
- Redis
- PostgreSQL
- Alembic

## Services
- `api`: REST API + health checks + internal bot API
- `bot`: Telegram Bot controller
- `scheduler`: future due-job scheduler
- `worker`: future Telegram user-account sender
- `postgres`: persistent database
- `redis`: queue, locks, rate-limit/cache foundation

## Phase 1 yang aktif
- User auto-registration dari `/start`
- Internal API dengan `INTERNAL_API_SECRET`
- Plan catalog
- Subscription lookup
- Bot menu yang membaca data dari backend
- Alembic initial migration + seed plan development

## Jalankan
1. Copy `.env.example` menjadi `.env`.
2. Isi `BOT_TOKEN` dan `INTERNAL_API_SECRET` dengan secret yang aman.
3. Jalankan:
   `docker compose up --build`
4. Jalankan migration:
   `docker compose exec api alembic upgrade head`
5. Cek:
   `http://localhost:8000/health`

## Catatan
`telegram_sessions.encrypted_session` adalah credential sensitif. Jangan memasukkan session string/password ke log, Git, issue tracker, atau chat.

Gunakan Alembic untuk staging/production. `scripts/init_db.py` hanya helper development.
