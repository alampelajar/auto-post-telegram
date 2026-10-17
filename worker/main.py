import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

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

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.core.crypto import decrypt_session
from app.db.models import (
    AutoPostJob,
    Group,
    Message,
    TelegramAccount,
)
from app.db.session import SessionLocal


# ============================================================
# CONFIG
# ============================================================

settings = get_settings()

QUEUE_NAME = "autopost:queue"

JOB_LOCK_TTL = 300
ACCOUNT_LOCK_TTL = 120

WORKER_HEARTBEAT_TTL = 30
QUEUE_TIMEOUT = 10

MIN_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 300


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
# TELEGRAM CLIENT CACHE
# ============================================================

clients: dict[int, TelegramClient] = {}


# ============================================================
# TELEGRAM CLIENT
# ============================================================

async def get_telegram_client(
    account: TelegramAccount,
) -> TelegramClient:
    """
    Mengambil client Telethon berdasarkan session
    terenkripsi yang tersimpan di database.
    """

    # --------------------------------------------------------
    # Validate session
    # --------------------------------------------------------

    if not account.session_data:
        raise RuntimeError(
            f"Akun Telegram #{account.id} "
            "tidak memiliki session_data."
        )

    # --------------------------------------------------------
    # Validate Telegram API config
    # --------------------------------------------------------

    if not settings.telegram_api_id:
        raise RuntimeError(
            "TELEGRAM_API_ID belum dikonfigurasi."
        )

    if not settings.telegram_api_hash:
        raise RuntimeError(
            "TELEGRAM_API_HASH belum dikonfigurasi."
        )

    # --------------------------------------------------------
    # Reuse existing client
    # --------------------------------------------------------

    existing_client = clients.get(account.id)

    if existing_client is not None:

        if existing_client.is_connected():

            try:

                if await existing_client.is_user_authorized():
                    return existing_client

            except Exception:
                logger.exception(
                    "Gagal mengecek authorization "
                    "account=%s",
                    account.id,
                )

        # Client tidak valid lagi.
        try:
            await existing_client.disconnect()
        except Exception:
            pass

        clients.pop(
            account.id,
            None,
        )

    # --------------------------------------------------------
    # Decrypt session
    # --------------------------------------------------------

    try:
        session_string = decrypt_session(
            account.session_data
        )
    except Exception as exc:
        raise RuntimeError(
            f"Gagal decrypt session "
            f"account #{account.id}: {exc}"
        ) from exc

    if not session_string:
        raise RuntimeError(
            f"Session account #{account.id} kosong."
        )

    # --------------------------------------------------------
    # Create Telethon client
    # --------------------------------------------------------

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    # --------------------------------------------------------
    # Connect
    # --------------------------------------------------------

    await client.connect()

    # --------------------------------------------------------
    # Check authorization
    # --------------------------------------------------------

    authorized = await client.is_user_authorized()

    if not authorized:

        await client.disconnect()

        raise RuntimeError(
            f"Session akun Telegram #{account.id} "
            "sudah tidak terotorisasi. "
            "Akun perlu dihubungkan ulang."
        )

    # --------------------------------------------------------
    # Cache client
    # --------------------------------------------------------

    clients[account.id] = client

    logger.info(
        "Telegram client connected | "
        "account=%s | telegram_user=%s",
        account.id,
        account.telegram_user_id,
    )

    return client


# ============================================================
# CLOSE TELEGRAM CLIENTS
# ============================================================

async def close_clients() -> None:
    """
    Disconnect seluruh Telethon client saat worker shutdown.
    """

    account_ids = list(
        clients.keys()
    )

    for account_id in account_ids:

        client = clients.get(account_id)

        if client is None:
            continue

        try:

            if client.is_connected():
                await client.disconnect()

        except Exception:

            logger.exception(
                "Gagal disconnect Telegram client "
                "account=%s",
                account_id,
            )

        finally:

            clients.pop(
                account_id,
                None,
            )


# ============================================================
# LOAD JOB
# ============================================================

async def load_job(
    db,
    job_id: int,
) -> AutoPostJob | None:

    result = await db.execute(
        select(AutoPostJob).where(
            AutoPostJob.id == job_id
        )
    )

    return result.scalar_one_or_none()


# ============================================================
# PROCESS JOB
# ============================================================

async def process_job(
    redis: Redis,
    job_id: int,
) -> None:
    """
    Memproses satu AutoPostJob.
    """

    job_lock_key = (
        f"autopost:processing:{job_id}"
    )

    account_lock_key: str | None = None

    # --------------------------------------------------------
    # Job lock
    # --------------------------------------------------------

    locked = await redis.set(
        job_lock_key,
        "1",
        nx=True,
        ex=JOB_LOCK_TTL,
    )

    if not locked:

        logger.warning(
            "Job #%s sedang diproses worker lain",
            job_id,
        )

        return

    try:

        async with SessionLocal() as db:

            # ------------------------------------------------
            # Load job
            # ------------------------------------------------

            job = await load_job(
                db,
                job_id,
            )

            if job is None:

                logger.warning(
                    "Job #%s tidak ditemukan",
                    job_id,
                )

                return

            # ------------------------------------------------
            # Validate state
            # ------------------------------------------------

            if not job.enabled:

                logger.info(
                    "Job #%s disabled",
                    job_id,
                )

                return

            if job.status != "ACTIVE":

                logger.info(
                    "Job #%s status=%s",
                    job_id,
                    job.status,
                )

                return

            # ------------------------------------------------
            # Validate schedule
            # ------------------------------------------------

            now = datetime.now(
                timezone.utc
            )

            if job.next_run_at > now:

                logger.info(
                    "Job #%s belum jatuh tempo | next_run=%s",
                    job_id,
                    job.next_run_at,
                )

                return

            # ------------------------------------------------
            # Load Telegram account
            # ------------------------------------------------

            result = await db.execute(
                select(TelegramAccount).where(
                    TelegramAccount.id
                    == job.telegram_account_id
                )
            )

            account = result.scalar_one_or_none()

            if account is None:

                raise RuntimeError(
                    f"Telegram account "
                    f"#{job.telegram_account_id} "
                    "tidak ditemukan."
                )

            if account.status != "CONNECTED":

                raise RuntimeError(
                    f"Telegram account "
                    f"#{account.id} status="
                    f"{account.status}"
                )

            # ------------------------------------------------
            # Load message
            # ------------------------------------------------

            result = await db.execute(
                select(Message).where(
                    Message.id == job.message_id,
                    Message.user_id == job.user_id,
                )
            )

            message = result.scalar_one_or_none()

            if message is None:

                raise RuntimeError(
                    f"Message #{job.message_id} "
                    "tidak ditemukan."
                )

            if message.status != "ACTIVE":

                raise RuntimeError(
                    f"Message #{message.id} "
                    f"status={message.status}"
                )

            if not message.content:

                raise RuntimeError(
                    f"Message #{message.id} "
                    "content kosong."
                )

            # ------------------------------------------------
            # Load group
            # ------------------------------------------------

            result = await db.execute(
                select(Group).where(
                    Group.id == job.group_id
                )
            )

            group = result.scalar_one_or_none()

            if group is None:

                raise RuntimeError(
                    f"Group #{job.group_id} "
                    "tidak ditemukan."
                )

            if group.status != "ACTIVE":

                raise RuntimeError(
                    f"Group #{group.id} "
                    f"status={group.status}"
                )

            if not group.telegram_chat_id:

                raise RuntimeError(
                    f"Group #{group.id} "
                    "telegram_chat_id kosong."
                )

            # ------------------------------------------------
            # Account lock
            # ------------------------------------------------

            account_lock_key = (
                f"autopost:account:{account.id}"
            )

            account_locked = await redis.set(
                account_lock_key,
                "1",
                nx=True,
                ex=ACCOUNT_LOCK_TTL,
            )

            if not account_locked:

                logger.info(
                    "Account #%s sedang digunakan "
                    "job lain. Job #%s dilewati "
                    "untuk sementara.",
                    account.id,
                    job.id,
                )

                return

            try:

                # --------------------------------------------
                # Get Telegram client
                # --------------------------------------------

                client = await get_telegram_client(
                    account
                )

                # --------------------------------------------
                # Log
                # --------------------------------------------

                logger.info(
                    "Sending job #%s | "
                    "account=%s | "
                    "telegram_user=%s | "
                    "group=%s | "
                    "chat_id=%s | "
                    "message_id=%s",
                    job.id,
                    account.id,
                    account.telegram_user_id,
                    group.id,
                    group.telegram_chat_id,
                    message.id,
                )

                # --------------------------------------------
                # Send message
                # --------------------------------------------

                await client.send_message(
                    entity=group.telegram_chat_id,
                    message=message.content,
                )

                # --------------------------------------------
                # Success state
                # --------------------------------------------

                sent_at = datetime.now(
                    timezone.utc
                )

                job.last_run_at = sent_at

                job.next_run_at = (
                    sent_at
                    + timedelta(
                        seconds=job.delay_seconds
                    )
                )

                job.attempt_count = 0
                job.status = "ACTIVE"
                job.enabled = True

                await db.commit()

                logger.info(
                    "Job #%s berhasil dikirim | "
                    "last_run=%s | "
                    "next_run=%s | "
                    "delay=%ss",
                    job.id,
                    job.last_run_at,
                    job.next_run_at,
                    job.delay_seconds,
                )

            finally:

                if account_lock_key:

                    await redis.delete(
                        account_lock_key
                    )

    except asyncio.CancelledError:
        raise

    except Exception:

        logger.exception(
            "Job #%s gagal diproses",
            job_id,
        )

        # ----------------------------------------------------
        # Save retry state
        # ----------------------------------------------------

        try:

            async with SessionLocal() as db:

                job = await load_job(
                    db,
                    job_id,
                )

                if job is not None:

                    job.attempt_count += 1

                    retry_seconds = max(
                        MIN_RETRY_SECONDS,
                        min(
                            job.delay_seconds,
                            MAX_RETRY_SECONDS,
                        ),
                    )

                    job.next_run_at = (
                        datetime.now(
                            timezone.utc
                        )
                        + timedelta(
                            seconds=retry_seconds
                        )
                    )

                    # Tetap ACTIVE agar scheduler bisa
                    # mencoba ulang setelah retry time.
                    job.status = "ACTIVE"

                    await db.commit()

                    logger.warning(
                        "Job #%s retry | "
                        "retry_in=%ss | attempts=%s | "
                        "next_run=%s",
                        job.id,
                        retry_seconds,
                        job.attempt_count,
                        job.next_run_at,
                    )

        except Exception:

            logger.exception(
                "Gagal menyimpan retry state "
                "job #%s",
                job_id,
            )

    finally:

        # ----------------------------------------------------
        # Release processing lock
        # ----------------------------------------------------

        try:
            await redis.delete(
                job_lock_key
            )
        except Exception:
            pass

        # ----------------------------------------------------
        # Release scheduler enqueue lock
        # ----------------------------------------------------

        try:
            await redis.delete(
                f"autopost:enqueue:{job_id}"
            )
        except Exception:
            pass


# ============================================================
# WORKER LOOP
# ============================================================

async def main() -> None:

    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    logger.info(
        "Worker started | queue=%s",
        QUEUE_NAME,
    )

    try:

        while True:

            try:

                # --------------------------------------------
                # Heartbeat
                # --------------------------------------------

                await redis.set(
                    "worker:heartbeat",
                    "ok",
                    ex=WORKER_HEARTBEAT_TTL,
                )

                # --------------------------------------------
                # Wait for queue item
                # --------------------------------------------

                item = await redis.blpop(
                    QUEUE_NAME,
                    timeout=QUEUE_TIMEOUT,
                )

                if not item:
                    continue

                # BLPOP returns:
                #
                # (
                #   queue_name,
                #   value
                # )

                queue_name, job_id_raw = item

                logger.debug(
                    "Queue item received | "
                    "queue=%s | value=%s",
                    queue_name,
                    job_id_raw,
                )

                # --------------------------------------------
                # Validate job ID
                # --------------------------------------------

                try:

                    job_id = int(
                        job_id_raw
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    logger.error(
                        "Invalid job_id: %r",
                        job_id_raw,
                    )

                    continue

                # --------------------------------------------
                # Process
                # --------------------------------------------

                logger.info(
                    "Received job #%s from queue",
                    job_id,
                )

                await process_job(
                    redis,
                    job_id,
                )

            except asyncio.CancelledError:
                raise

            except Exception:

                logger.exception(
                    "Worker loop error"
                )

                await asyncio.sleep(2)

    finally:

        await close_clients()

        try:
            await redis.aclose()
        except Exception:
            pass

        logger.info(
            "Worker stopped"
        )


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())