import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.core.crypto import decrypt_session, encrypt_session
from app.db.models import TelegramAccount, User
from app.db.session import SessionLocal


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/telegram/accounts",
    tags=["Telegram Accounts"],
)


# ============================================================
# CONFIG
# ============================================================

logger = logging.getLogger(__name__)
settings = get_settings()

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
)

PENDING_KEY_PREFIX = "telegram_login:"
PENDING_TTL = 600


# ============================================================
# REQUEST MODELS
# ============================================================

class ConnectRequest(BaseModel):
    telegram_user_id: int
    phone_number: str = Field(
        min_length=5,
        max_length=32,
    )


class ConnectVerify(BaseModel):
    telegram_user_id: int

    code: str = Field(
        min_length=3,
        max_length=32,
    )

    password: str | None = Field(
        default=None,
        max_length=512,
    )


class ConnectPassword(BaseModel):
    telegram_user_id: int

    password: str = Field(
        min_length=1,
        max_length=512,
    )


# ============================================================
# HELPERS
# ============================================================

def pending_key(
    telegram_user_id: int,
) -> str:
    return (
        f"{PENDING_KEY_PREFIX}"
        f"{telegram_user_id}"
    )


async def get_or_create_user(
    telegram_user_id: int,
) -> User:
    async with SessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.telegram_user_id
                == telegram_user_id
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


def ensure_telegram_config() -> None:
    if not settings.telegram_api_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "TELEGRAM_API_ID belum "
                "dikonfigurasi."
            ),
        )

    if not settings.telegram_api_hash:
        raise HTTPException(
            status_code=500,
            detail=(
                "TELEGRAM_API_HASH belum "
                "dikonfigurasi."
            ),
        )


# ============================================================
# REQUEST LOGIN CODE
# ============================================================

@router.post("/connect/request")
async def request_connection(
    payload: ConnectRequest,
):
    ensure_telegram_config()

    phone = payload.phone_number.strip()

    if not phone:
        raise HTTPException(
            status_code=400,
            detail="Nomor Telegram wajib diisi.",
        )

    user = await get_or_create_user(
        payload.telegram_user_id
    )

    # --------------------------------------------------------
    # Check existing account
    # --------------------------------------------------------

    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.user_id
                == user.id,
                TelegramAccount.phone_number
                == phone,
            )
        )

        existing = result.scalar_one_or_none()

        if (
            existing is not None
            and existing.status == "CONNECTED"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Akun Telegram ini "
                    "sudah terhubung."
                ),
            )

    client = TelegramClient(
        StringSession(),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()

        sent = await client.send_code_request(
            phone
        )

        session_string = client.session.save()

        pending_payload = {
            "user_id": user.id,
            "phone_number": phone,
            "phone_code_hash": sent.phone_code_hash,
            "session": encrypt_session(
                session_string
            ),
            "two_factor_required": False,
        }

        await redis_client.setex(
            pending_key(
                payload.telegram_user_id
            ),
            PENDING_TTL,
            json.dumps(pending_payload),
        )

        return {
            "ok": True,
            "message": (
                "Kode login Telegram "
                "sudah dikirim."
            ),
            "expires_in": PENDING_TTL,
        }

    except Exception as exc:
        logger.exception(
            "Gagal mengirim kode Telegram"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Gagal mengirim kode Telegram: "
                f"{exc}"
            ),
        ) from exc

    finally:
        await client.disconnect()


# ============================================================
# VERIFY CODE
# ============================================================

@router.post("/connect/verify")
async def verify_connection(
    payload: ConnectVerify,
):
    ensure_telegram_config()

    raw = await redis_client.get(
        pending_key(
            payload.telegram_user_id
        )
    )

    if not raw:
        raise HTTPException(
            status_code=400,
            detail=(
                "Sesi login tidak ditemukan "
                "atau sudah kedaluwarsa."
            ),
        )

    pending = json.loads(raw)

    session_string = decrypt_session(
        pending["session"]
    )

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()

        try:
            await client.sign_in(
                phone=pending["phone_number"],
                code=payload.code,
                phone_code_hash=pending[
                    "phone_code_hash"
                ],
            )

        except SessionPasswordNeededError:
            pending["session"] = encrypt_session(
                client.session.save()
            )

            pending[
                "two_factor_required"
            ] = True

            await redis_client.setex(
                pending_key(
                    payload.telegram_user_id
                ),
                PENDING_TTL,
                json.dumps(pending),
            )

            return {
                "ok": False,
                "requires_password": True,
                "message": (
                    "Akun menggunakan "
                    "verifikasi 2 langkah."
                ),
            }

        except PhoneCodeInvalidError as exc:
            raise HTTPException(
                status_code=400,
                detail="Kode Telegram tidak valid.",
            ) from exc

        except PhoneCodeExpiredError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Kode Telegram "
                    "sudah kedaluwarsa."
                ),
            ) from exc

        me = await client.get_me()

        if me is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Gagal mendapatkan "
                    "profil Telegram."
                ),
            )

        account = await save_account(
            pending,
            me,
            client.session.save(),
        )

        await redis_client.delete(
            pending_key(
                payload.telegram_user_id
            )
        )

        return {
            "ok": True,
            "message": (
                "Akun Telegram "
                "berhasil terhubung."
            ),
            "account": account,
        }

    finally:
        await client.disconnect()


# ============================================================
# VERIFY 2FA
# ============================================================

@router.post("/connect/2fa")
async def verify_two_factor(
    payload: ConnectPassword,
):
    ensure_telegram_config()

    raw = await redis_client.get(
        pending_key(
            payload.telegram_user_id
        )
    )

    if not raw:
        raise HTTPException(
            status_code=400,
            detail=(
                "Sesi login tidak ditemukan "
                "atau sudah kedaluwarsa."
            ),
        )

    pending = json.loads(raw)

    if not pending.get(
        "two_factor_required"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Login tidak sedang "
                "menunggu password 2FA."
            ),
        )

    session_string = decrypt_session(
        pending["session"]
    )

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()

        try:
            await client.sign_in(
                password=payload.password
            )

        except Exception as exc:
            logger.warning(
                "2FA Telegram gagal: %s",
                exc,
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Password 2FA tidak valid."
                ),
            ) from exc

        me = await client.get_me()

        if me is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Gagal mendapatkan "
                    "profil Telegram."
                ),
            )

        account = await save_account(
            pending,
            me,
            client.session.save(),
        )

        await redis_client.delete(
            pending_key(
                payload.telegram_user_id
            )
        )

        return {
            "ok": True,
            "message": (
                "Akun Telegram "
                "berhasil terhubung."
            ),
            "account": account,
        }

    finally:
        await client.disconnect()


# ============================================================
# SAVE ACCOUNT
# ============================================================

async def save_account(
    pending: dict,
    me,
    session_string: str,
) -> dict:

    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.user_id
                == pending["user_id"],
                TelegramAccount.telegram_user_id
                == me.id,
            )
        )

        account = result.scalar_one_or_none()

        if account is None:
            account = TelegramAccount(
                user_id=pending["user_id"],
                telegram_user_id=me.id,
                phone_number=pending[
                    "phone_number"
                ],
            )

            db.add(account)

        account.username = getattr(
            me,
            "username",
            None,
        )

        account.phone_number = pending[
            "phone_number"
        ]

        account.session_data = encrypt_session(
            session_string
        )

        account.status = "CONNECTED"

        account.last_connected_at = (
            datetime.now(timezone.utc)
        )

        await db.commit()
        await db.refresh(account)

        return {
            "id": account.id,
            "telegram_user_id": (
                account.telegram_user_id
            ),
            "username": account.username,
            "phone_number": (
                account.phone_number
            ),
            "status": account.status,
            "last_connected_at": (
                account.last_connected_at
            ),
        }


# ============================================================
# LIST ACCOUNTS
# ============================================================

@router.get("")
async def list_accounts(
    telegram_user_id: int,
):
    user = await get_or_create_user(
        telegram_user_id
    )

    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramAccount)
            .where(
                TelegramAccount.user_id
                == user.id
            )
            .order_by(
                TelegramAccount.id.desc()
            )
        )

        accounts = result.scalars().all()

        return {
            "ok": True,
            "accounts": [
                {
                    "id": account.id,
                    "telegram_user_id": (
                        account.telegram_user_id
                    ),
                    "username": (
                        account.username
                    ),
                    "phone_number": (
                        account.phone_number
                    ),
                    "status": account.status,
                    "last_connected_at": (
                        account.last_connected_at
                    ),
                }
                for account in accounts
            ],
        }