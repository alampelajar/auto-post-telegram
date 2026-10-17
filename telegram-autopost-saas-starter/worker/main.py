import asyncio
import logging

from redis.asyncio import Redis

from backend.app.core.config import get_settings

logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)
settings = get_settings()


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        logger.info("Worker started")
        while True:
            await redis.set("worker:heartbeat", "ok", ex=30)
            await asyncio.sleep(10)
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
