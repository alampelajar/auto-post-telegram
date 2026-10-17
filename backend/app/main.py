from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from app.api.autopost import router as autopost_router

from app.api.groups import router as groups_router
from app.api.messages import router as messages_router
from app.api.telegram_accounts import (
    router as telegram_accounts_router,
)
from app.core.config import get_settings
from app.db.session import engine


settings = get_settings()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)


# ============================================================
# ROUTERS
# ============================================================

app.include_router(
    telegram_accounts_router
)

app.include_router(
    autopost_router
    )

app.include_router(
    groups_router
)

app.include_router(
    messages_router
)


# ============================================================
# REDIS
# ============================================================

redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root() -> dict[str, str]:

    return {
        "service": settings.app_name,
        "status": "ok",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health() -> dict[str, object]:

    checks: dict[str, str] = {}

    overall = "ok"

    # --------------------------------------------------------
    # POSTGRESQL
    # --------------------------------------------------------

    try:

        async with engine.connect() as conn:

            await conn.execute(
                text("SELECT 1")
            )

        checks["postgres"] = "ok"

    except Exception:

        checks["postgres"] = "error"

        overall = "degraded"

    # --------------------------------------------------------
    # REDIS
    # --------------------------------------------------------

    try:

        await redis.ping()

        checks["redis"] = "ok"

    except Exception:

        checks["redis"] = "error"

        overall = "degraded"

    return {
        "status": overall,
        "checks": checks,
    }


# ============================================================
# SHUTDOWN
# ============================================================

@app.on_event("shutdown")
async def shutdown() -> None:

    await redis.close()

    await engine.dispose()