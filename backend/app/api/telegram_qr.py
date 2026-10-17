from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from telethon import TelegramClient
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.core.crypto import decrypt_session, encrypt_session
from app.db.models import TelegramAccount, User
from app.db.session import SessionLocal


router = APIRouter(
    prefix="/api/telegram/accounts",
    tags=["Telegram Account QR Login"],
)

logger = logging.getLogger(__name__)
settings = get_settings()

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
)

QR_STATUS_PREFIX = "telegram_login_qr_status:"
QR_SESSION_PREFIX = "telegram_login_qr_session:"
QR_LOGIN_TTL = 600

# QRLogin needs to remain active while Telegram approves the login.
# Keep the client/task in this API process for the lifetime of the QR attempt.
qr_tasks: dict[int, asyncio.Task] = {}


class QRConnectRequest(BaseModel):
    telegram_user_id: int


class QRConnectPassword(BaseModel):
    telegram_user_id: int
    password: str = Field(min_length=1, max_length=512)


def status_key(telegram_user_id: int) -> str:
    return f"{QR_STATUS_PREFIX}{telegram_user_id}"


def session_key(telegram_user_id: int) -> str:
    return f"{QR_SESSION_PREFIX}{telegram_user_id}"


def ensure_telegram_config() -> None:
    if not settings.telegram_api_id:
        raise HTTPException(
            status_code=500,
            detail="TELEGRAM_API_ID belum dikonfigurasi.",
        )

    if not settings.telegram_api_hash:
        raise HTTPException(
            status_code=500,
            detail="TELEGRAM_API_HASH belum dikonfigurasi.",
        )


async def get_or_create_user(telegram_user_id: int) -> User:
    async with SessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.telegram_user_id == telegram_user_id
            )
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                status="ACTIVE",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        return user


async def write_status(
    telegram_user_id: int,
    status: str,
    *,
    message: str,
    account: dict | None = None,
    login_url: str | None = None,
) -> None:
    payload = {
        "status": status,
        "message": message,
    }
    if account is not None:
        payload["account"] = account
    if login_url is not None and status == "WAITING":
        payload["login_url"] = login_url

    await redis_client.setex(
        status_key(telegram_user_id),
        QR_LOGIN_TTL,
        json.dumps(payload),
    )


async def save_account(
    user_id: int,
    me,
    session_string: str,
) -> dict:
    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.user_id == user_id,
                TelegramAccount.telegram_user_id == me.id,
            )
        )
        account = result.scalar_one_or_none()

        if account is None:
            account = TelegramAccount(
                user_id=user_id,
                telegram_user_id=me.id,
            )
            db.add(account)

        account.username = getattr(me, "username", None)
        account.phone_number = getattr(me, "phone", None)
        account.session_data = encrypt_session(session_string)
        account.status = "CONNECTED"
        account.last_connected_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(account)

        return {
            "id": account.id,
            "telegram_user_id": account.telegram_user_id,
            "username": account.username,
            "phone_number": account.phone_number,
            "status": account.status,
            "last_connected_at": (
                account.last_connected_at.isoformat()
                if account.last_connected_at
                else None
            ),
        }


async def monitor_qr_login(
    telegram_user_id: int,
    user_id: int,
    client: TelegramClient,
    qr_login,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + QR_LOGIN_TTL

    try:
        # Telegram QR login tokens expire quickly (typically ~30 seconds).
        # Keep wait() active and refresh the link before each token expires.
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await write_status(
                    telegram_user_id,
                    "EXPIRED",
                    message="Waktu login habis. Mulai koneksi baru.",
                )
                return

            try:
                me = await qr_login.wait(
                    timeout=min(20.0, remaining)
                )
                if me is None:
                    me = await client.get_me()
                break

            except asyncio.TimeoutError:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    await write_status(
                        telegram_user_id,
                        "EXPIRED",
                        message="Waktu login habis. Mulai koneksi baru.",
                    )
                    return

                await qr_login.recreate()
                await write_status(
                    telegram_user_id,
                    "WAITING",
                    message=(
                        "Link login diperbarui. Kembali ke bot "
                        "dan tekan Cek Status Koneksi untuk mendapatkan link terbaru."
                    ),
                    login_url=qr_login.url,
                )
                logger.info(
                    "QR token refreshed for bot_user_id=%s",
                    telegram_user_id,
                )

        if me is None:
            raise RuntimeError("Telegram tidak mengembalikan profil akun.")

        account = await save_account(
            user_id,
            me,
            client.session.save(),
        )

        await redis_client.delete(session_key(telegram_user_id))
        await write_status(
            telegram_user_id,
            "CONNECTED",
            message="Akun Telegram berhasil terhubung.",
            account=account,
        )

        logger.info(
            "QR login successful for bot_user_id=%s; connected account id=%s",
            telegram_user_id,
            account["id"],
        )

    except SessionPasswordNeededError:
        # Keep a short-lived encrypted copy so the user can finish 2FA.
        encrypted_session = encrypt_session(client.session.save())
        await redis_client.setex(
            session_key(telegram_user_id),
            QR_LOGIN_TTL,
            json.dumps({
                "user_id": user_id,
                "session": encrypted_session,
            }),
        )
        await write_status(
            telegram_user_id,
            "REQUIRES_PASSWORD",
            message=(
                "Telegram meminta password verifikasi dua langkah "
                "untuk menyelesaikan koneksi."
            ),
        )
        logger.info(
            "QR login requires 2FA for bot_user_id=%s",
            telegram_user_id,
        )

    except asyncio.CancelledError:
        await write_status(
            telegram_user_id,
            "CANCELLED",
            message="Proses koneksi QR dibatalkan.",
        )
        raise

    except Exception:
        logger.exception(
            "QR login failed for bot_user_id=%s",
            telegram_user_id,
        )
        await write_status(
            telegram_user_id,
            "FAILED",
            message=(
                "Koneksi QR gagal. Mulai koneksi baru. "
                "Periksa log API untuk detail teknis; jangan membagikan OTP."
            ),
        )

    finally:
        try:
            await client.disconnect()
        except Exception:
            logger.exception(
                "Failed to disconnect QR client for bot_user_id=%s",
                telegram_user_id,
            )

        current_task = asyncio.current_task()
        if qr_tasks.get(telegram_user_id) is current_task:
            qr_tasks.pop(telegram_user_id, None)


@router.post("/connect/qr/request")
async def request_qr_connection(payload: QRConnectRequest):
    ensure_telegram_config()

    bot_user_id = payload.telegram_user_id

    existing_task = qr_tasks.get(bot_user_id)
    if existing_task and not existing_task.done():
        raw = await redis_client.get(status_key(bot_user_id))
        if raw:
            current = json.loads(raw)
            if current.get("status") == "WAITING":
                return {
                    "ok": True,
                    "status": "WAITING",
                    "login_url": current.get("login_url"),
                    "expires_in": QR_LOGIN_TTL,
                    "message": "Koneksi QR masih menunggu persetujuan.",
                }
        raise HTTPException(
            status_code=409,
            detail="Proses koneksi akun masih berjalan. Periksa status terlebih dahulu.",
        )

    user = await get_or_create_user(bot_user_id)

    # Discard any stale 2FA session from an older QR attempt.
    await redis_client.delete(session_key(bot_user_id))

    client = TelegramClient(
        StringSession(),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()
        qr_login = await client.qr_login()

        # Store only the short-lived approval URI and status.
        # Never store or log the raw OTP because this flow does not use one.
        await redis_client.setex(
            status_key(bot_user_id),
            QR_LOGIN_TTL,
            json.dumps({
                "status": "WAITING",
                "message": "Menunggu persetujuan login di aplikasi Telegram.",
                "login_url": qr_login.url,
            }),
        )

        task = asyncio.create_task(
            monitor_qr_login(
                bot_user_id,
                user.id,
                client,
                qr_login,
            ),
            name=f"telegram-qr-login-{bot_user_id}",
        )
        qr_tasks[bot_user_id] = task

        logger.info(
            "QR login started for bot_user_id=%s",
            bot_user_id,
        )

        return {
            "ok": True,
            "status": "WAITING",
            "login_url": qr_login.url,
            "expires_in": QR_LOGIN_TTL,
            "message": (
                "Buka link Telegram untuk menyetujui login. "
                "Jangan kirim kode login kepada bot."
            ),
        }

    except HTTPException:
        await client.disconnect()
        raise

    except Exception as exc:
        try:
            await client.disconnect()
        except Exception:
            pass

        logger.exception(
            "Could not start QR login for bot_user_id=%s",
            bot_user_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Gagal membuat login QR Telegram. Periksa konfigurasi API.",
        ) from exc


@router.get("/connect/qr/status")
async def get_qr_status(telegram_user_id: int):
    raw = await redis_client.get(
        status_key(telegram_user_id)
    )

    if not raw:
        return {
            "ok": True,
            "status": "NOT_FOUND",
            "message": "Tidak ada proses login QR aktif. Mulai koneksi baru.",
        }

    data = json.loads(raw)

    # Never return login_url or the encrypted session from status polling.
    response = {
        "ok": True,
        "status": data.get("status", "UNKNOWN"),
        "message": data.get("message", ""),
    }

    # QR login links are short-lived and must be refreshed regularly.
    if data.get("status") == "WAITING" and data.get("login_url"):
        response["login_url"] = data["login_url"]

    if data.get("account") is not None:
        response["account"] = data["account"]

    return response


@router.post("/connect/qr/2fa")
async def verify_qr_two_factor(payload: QRConnectPassword):
    ensure_telegram_config()

    raw = await redis_client.get(
        session_key(payload.telegram_user_id)
    )
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="Sesi QR tidak ditemukan atau sudah kedaluwarsa. Mulai koneksi baru.",
        )

    pending = json.loads(raw)
    session_string = decrypt_session(pending["session"])

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()

        try:
            await client.sign_in(password=payload.password)
        except PasswordHashInvalidError as exc:
            raise HTTPException(
                status_code=400,
                detail="Password 2FA tidak valid.",
            ) from exc

        me = await client.get_me()
        if me is None:
            raise HTTPException(
                status_code=400,
                detail="Gagal mendapatkan profil Telegram.",
            )

        account = await save_account(
            pending["user_id"],
            me,
            client.session.save(),
        )

        await redis_client.delete(
            session_key(payload.telegram_user_id)
        )
        await write_status(
            payload.telegram_user_id,
            "CONNECTED",
            message="Akun Telegram berhasil terhubung.",
            account=account,
        )

        logger.info(
            "QR login completed after 2FA for bot_user_id=%s account_id=%s",
            payload.telegram_user_id,
            account["id"],
        )

        return {
            "ok": True,
            "message": "Akun Telegram berhasil terhubung.",
            "account": account,
        }

    except HTTPException:
        raise

    except Exception as exc:
        # Do not log request payloads or the 2FA password.
        logger.exception(
            "QR 2FA verification failed for bot_user_id=%s",
            payload.telegram_user_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Gagal menyelesaikan verifikasi 2FA. Periksa password atau mulai koneksi baru.",
        ) from exc

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
