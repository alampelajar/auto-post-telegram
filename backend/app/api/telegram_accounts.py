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
# LEGACY OTP LOGIN DISABLED
# ============================================================

@router.post("/connect/request")
async def request_connection(payload: ConnectRequest):
    raise HTTPException(
        status_code=410,
        detail=(
            "Login menggunakan kode OTP dinonaktifkan untuk keamanan. "
            "Gunakan koneksi QR Telegram."
        ),
    )


# ============================================================
# LEGACY OTP VERIFICATION DISABLED
# ============================================================

@router.post("/connect/verify")
async def verify_connection(payload: ConnectVerify):
    raise HTTPException(
        status_code=410,
        detail=(
            "Login menggunakan kode OTP dinonaktifkan untuk keamanan. "
            "Gunakan koneksi QR Telegram."
        ),
    )


# ============================================================
# LEGACY OTP-BASED 2FA DISABLED
# ============================================================

@router.post("/connect/2fa")
async def verify_two_factor(payload: ConnectPassword):
    raise HTTPException(
        status_code=410,
        detail=(
            "Endpoint 2FA login berbasis OTP dinonaktifkan. "
            "Mulai koneksi QR Telegram dan gunakan alur verifikasi QR."
        ),
    )


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