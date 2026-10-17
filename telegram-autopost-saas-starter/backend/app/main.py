from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from backend.app.api.routes.plans import router as plans_router
from backend.app.api.routes.users import router as users_router
from backend.app.core.config import get_settings
from backend.app.db.session import engine

settings = get_settings()
redis = Redis.from_url(settings.redis_url, decode_responses=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await redis.aclose()
    await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.include_router(users_router, prefix="/internal")
app.include_router(plans_router, prefix="/internal")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok", "version": "0.2.0"}


@app.get("/health")
async def health() -> dict[str, object]:
    checks: dict[str, str] = {}
    overall = "ok"

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"
        overall = "degraded"

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        overall = "degraded"

    return {"status": overall, "checks": checks}
