import asyncio
import logging
import sys
from datetime import datetime, timezone

# ============================================================
# PYTHON PATH
# ============================================================

if "/app/backend" not in sys.path:
    sys.path.insert(0, "/app/backend")


# ============================================================
# IMPORTS
# ============================================================

from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AutoPostJob
from app.db.session import SessionLocal


# ============================================================
# CONFIG
# ============================================================

settings = get_settings()

QUEUE_NAME = "autopost:queue"
ENQUEUE_LOCK_TTL = 120
SCHEDULER_INTERVAL = 5
MAX_JOBS_PER_SCAN = 100


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=getattr(
        logging,
        settings.log_level.upper(),
        logging.INFO,
    ),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# ENQUEUE DUE JOBS
# ============================================================

async def enqueue_due_jobs(redis: Redis) -> int:
    """
    Mencari AutoPostJob yang sudah jatuh tempo,
    kemudian memasukkan job_id ke Redis queue.
    """

    now = datetime.now(timezone.utc)
    enqueued = 0

    async with SessionLocal() as db:

        result = await db.execute(
            select(AutoPostJob)
            .where(
                AutoPostJob.enabled.is_(True),
                AutoPostJob.status == "ACTIVE",
                AutoPostJob.next_run_at <= now,
            )
            .order_by(
                AutoPostJob.next_run_at.asc(),
                AutoPostJob.id.asc(),
            )
            .limit(MAX_JOBS_PER_SCAN)
        )

        jobs = result.scalars().all()

        logger.info(
            "Scheduler scan | due_jobs=%s",
            len(jobs),
        )

        for job in jobs:

            lock_key = f"autopost:enqueue:{job.id}"

            try:
                locked = await redis.set(
                    lock_key,
                    "1",
                    nx=True,
                    ex=ENQUEUE_LOCK_TTL,
                )

                if not locked:
                    logger.debug(
                        "Job #%s sudah memiliki enqueue lock",
                        job.id,
                    )
                    continue

                await redis.rpush(
                    QUEUE_NAME,
                    str(job.id),
                )

                enqueued += 1

                logger.info(
                    "Job #%s queued | account=%s | group=%s | "
                    "message=%s | next_run=%s | delay=%ss",
                    job.id,
                    job.telegram_account_id,
                    job.group_id,
                    job.message_id,
                    job.next_run_at,
                    job.delay_seconds,
                )

            except Exception:

                # Kalau Redis gagal setelah lock dibuat,
                # hapus lock agar bisa dicoba lagi.
                try:
                    await redis.delete(lock_key)
                except Exception:
                    pass

                logger.exception(
                    "Gagal memasukkan job #%s ke Redis",
                    job.id,
                )

    return enqueued


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    logger.info(
        "Scheduler started | queue=%s | interval=%ss",
        QUEUE_NAME,
        SCHEDULER_INTERVAL,
    )

    try:

        while True:

            try:

                # --------------------------------------------
                # Heartbeat
                # --------------------------------------------

                await redis.set(
                    "scheduler:heartbeat",
                    "ok",
                    ex=30,
                )

                # --------------------------------------------
                # Enqueue due jobs
                # --------------------------------------------

                enqueued = await enqueue_due_jobs(
                    redis
                )

                if enqueued > 0:
                    logger.info(
                        "Scheduler queued %s job(s)",
                        enqueued,
                    )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Scheduler loop error"
                )

            await asyncio.sleep(
                SCHEDULER_INTERVAL
            )

    finally:

        try:
            await redis.aclose()
        except Exception:
            pass

        logger.info(
            "Scheduler stopped"
        )


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())