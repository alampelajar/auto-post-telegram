import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
from telethon.utils import get_peer_id

from app.core.config import get_settings
from app.core.crypto import decrypt_session
from app.db.models import (
    Group,
    TelegramAccount,
    User,
    UserGroup,
)
from app.db.session import SessionLocal


router = APIRouter(
    prefix="/api/groups",
    tags=["Groups"],
)

logger = logging.getLogger(__name__)

settings = get_settings()


# ============================================================
# REQUEST MODELS
# ============================================================

class ImportGroupRequest(BaseModel):
    telegram_user_id: int
    account_id: int
    telegram_chat_id: int


# ============================================================
# SERIALIZER
# ============================================================

def serialize_group(
    group: Group,
    user_group: UserGroup | None = None,
) -> dict:
    return {
        "id": group.id,
        "telegram_chat_id": group.telegram_chat_id,
        "title": group.title,
        "username": group.username,
        "category": group.category,
        "status": (
            user_group.status
            if user_group is not None
            else group.status
        ),
        "user_group_id": (
            user_group.id
            if user_group is not None
            else None
        ),
        "telegram_account_id": (
            user_group.telegram_account_id
            if user_group is not None
            else None
        ),
    }


# ============================================================
# USER
# ============================================================

async def get_user(
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
            raise HTTPException(
                status_code=404,
                detail="User belum terdaftar.",
            )

        if user.status != "ACTIVE":
            raise HTTPException(
                status_code=403,
                detail="User tidak aktif.",
            )

        return user


# ============================================================
# CONNECTED ACCOUNT
# ============================================================

async def get_connected_account(
    telegram_user_id: int,
    account_id: int,
) -> TelegramAccount:

    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.id == account_id,
                TelegramAccount.user_id == user.id,
                TelegramAccount.status == "CONNECTED",
            )
        )

        account = result.scalar_one_or_none()

        if account is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Akun Telegram tidak ditemukan "
                    "atau belum terhubung."
                ),
            )

        return account


# ============================================================
# LIST USER GROUPS
# ============================================================

@router.get("")
async def list_groups(
    telegram_user_id: int,
    status: str = "ACTIVE",
):
    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        query = (
            select(Group, UserGroup)
            .join(
                UserGroup,
                UserGroup.group_id == Group.id,
            )
            .where(
                UserGroup.user_id == user.id,
                Group.status == "ACTIVE",
            )
            .order_by(
                UserGroup.id.desc()
            )
        )

        if status:
            query = query.where(
                UserGroup.status == status
            )

        result = await db.execute(
            query
        )

        rows = result.all()

        return {
            "ok": True,
            "groups": [
                serialize_group(
                    group,
                    user_group,
                )
                for group, user_group in rows
            ],
        }


# ============================================================
# AVAILABLE GROUPS
# ============================================================

@router.get("/available")
async def available_groups(
    telegram_user_id: int,
    account_id: int,
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    search: str | None = None,
):
    account = await get_connected_account(
        telegram_user_id,
        account_id,
    )

    if settings.telegram_api_id is None:
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

    if not account.session_data:
        raise HTTPException(
            status_code=400,
            detail=(
                "Session Telegram tidak tersedia."
            ),
        )

    session_string = decrypt_session(
        account.session_data
    )

    # --------------------------------------------------------
    # Get groups already selected by this user
    # --------------------------------------------------------

    async with SessionLocal() as db:

        result = await db.execute(
            select(Group.telegram_chat_id)
            .join(
                UserGroup,
                UserGroup.group_id == Group.id,
            )
            .where(
                UserGroup.user_id
                == account.user_id,
                UserGroup.status
                == "ACTIVE",
            )
        )

        selected_ids = {
            row[0]
            for row in result.all()
        }

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    groups: list[dict] = []

    try:

        await client.connect()

        if not await client.is_user_authorized():
            raise HTTPException(
                status_code=401,
                detail=(
                    "Session Telegram sudah "
                    "tidak terotorisasi. "
                    "Hubungkan ulang akun."
                ),
            )

        dialogs = await client.get_dialogs(
            limit=limit + len(selected_ids) + 20
        )

        search_value = (
            search.strip().lower()
            if search
            else None
        )

        for dialog in dialogs:

            entity = dialog.entity

            # ------------------------------------------------
            # Basic group
            # ------------------------------------------------

            is_basic_group = isinstance(
                entity,
                Chat,
            )

            # ------------------------------------------------
            # Telegram supergroup
            # ------------------------------------------------

            is_supergroup = (
                isinstance(entity, Channel)
                and bool(
                    getattr(
                        entity,
                        "megagroup",
                        False,
                    )
                )
            )

            if not (
                is_basic_group
                or is_supergroup
            ):
                continue

            chat_id = get_peer_id(
                entity
            )

            if chat_id in selected_ids:
                continue

            title = (
                getattr(
                    entity,
                    "title",
                    None,
                )
                or dialog.name
                or "Unnamed Group"
            )

            username = getattr(
                entity,
                "username",
                None,
            )

            if search_value:

                searchable = (
                    f"{title} "
                    f"{username or ''}"
                ).lower()

                if search_value not in searchable:
                    continue

            groups.append(
                {
                    "telegram_chat_id": chat_id,
                    "title": title,
                    "username": username,
                }
            )

            if len(groups) >= limit:
                break

        return {
            "ok": True,
            "account": {
                "id": account.id,
                "username": account.username,
                "phone_number": account.phone_number,
            },
            "groups": groups,
            "count": len(groups),
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "Gagal mengambil daftar grup Telegram"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Gagal mengambil daftar grup: {exc}"
            ),
        ) from exc

    finally:

        await client.disconnect()


# ============================================================
# IMPORT GROUP
# ============================================================

@router.post("/import")
async def import_group(
    payload: ImportGroupRequest,
):
    account = await get_connected_account(
        payload.telegram_user_id,
        payload.account_id,
    )

    if settings.telegram_api_id is None:
        raise HTTPException(
            status_code=500,
            detail="TELEGRAM_API_ID belum dikonfigurasi.",
        )

    if not settings.telegram_api_hash:
        raise HTTPException(
            status_code=500,
            detail="TELEGRAM_API_HASH belum dikonfigurasi.",
        )

    if not account.session_data:
        raise HTTPException(
            status_code=400,
            detail="Session Telegram tidak tersedia.",
        )

    session_string = decrypt_session(
        account.session_data
    )

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:

        await client.connect()

        if not await client.is_user_authorized():
            raise HTTPException(
                status_code=401,
                detail=(
                    "Session Telegram sudah "
                    "tidak terotorisasi."
                ),
            )

        try:
            entity = await client.get_entity(
                payload.telegram_chat_id
            )

        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Grup tidak dapat diakses "
                    "oleh akun Telegram tersebut."
                ),
            ) from exc

        is_basic_group = isinstance(
            entity,
            Chat,
        )

        is_supergroup = (
            isinstance(entity, Channel)
            and bool(
                getattr(
                    entity,
                    "megagroup",
                    False,
                )
            )
        )

        if not (
            is_basic_group
            or is_supergroup
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Target bukan grup Telegram."
                ),
            )

        canonical_chat_id = get_peer_id(
            entity
        )

        title = (
            getattr(
                entity,
                "title",
                None,
            )
            or "Unnamed Group"
        )

        username = getattr(
            entity,
            "username",
            None,
        )

        async with SessionLocal() as db:

            # ------------------------------------------------
            # Find/create global group
            # ------------------------------------------------

            result = await db.execute(
                select(Group).where(
                    Group.telegram_chat_id
                    == canonical_chat_id
                )
            )

            group = result.scalar_one_or_none()

            if group is None:

                group = Group(
                    telegram_chat_id=canonical_chat_id,
                    title=title,
                    username=username,
                    category="Umum",
                    status="ACTIVE",
                )

                db.add(group)

                await db.flush()

            else:

                group.title = title
                group.username = username
                group.status = "ACTIVE"

            # ------------------------------------------------
            # Find user-group relation
            # ------------------------------------------------

            result = await db.execute(
                select(UserGroup).where(
                    UserGroup.user_id
                    == account.user_id,

                    UserGroup.group_id
                    == group.id,
                )
            )

            user_group = (
                result.scalar_one_or_none()
            )

            if user_group is None:

                user_group = UserGroup(
                    user_id=account.user_id,
                    group_id=group.id,
                    telegram_account_id=account.id,
                    status="ACTIVE",
                )

                db.add(user_group)

            else:

                if user_group.status == "ACTIVE":
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Grup ini sudah "
                            "ditambahkan."
                        ),
                    )

                user_group.telegram_account_id = (
                    account.id
                )

                user_group.status = "ACTIVE"

            await db.commit()

            await db.refresh(
                group
            )

            await db.refresh(
                user_group
            )

            return {
                "ok": True,
                "message": (
                    "Grup berhasil ditambahkan."
                ),
                "group": serialize_group(
                    group,
                    user_group,
                ),
            }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "Gagal import group"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Gagal menambahkan grup: {exc}"
            ),
        ) from exc

    finally:

        await client.disconnect()


# ============================================================
# GROUP DETAIL
# ============================================================

@router.get("/{group_id}")
async def get_group(
    group_id: int,
    telegram_user_id: int,
):
    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(Group, UserGroup)
            .join(
                UserGroup,
                UserGroup.group_id == Group.id,
            )
            .where(
                Group.id == group_id,
                UserGroup.user_id == user.id,
                UserGroup.status == "ACTIVE",
            )
        )

        row = result.one_or_none()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Grup tidak ditemukan.",
            )

        group, user_group = row

        return {
            "ok": True,
            "group": serialize_group(
                group,
                user_group,
            ),
        }


# ============================================================
# REMOVE GROUP FROM USER
# ============================================================

@router.delete("/{group_id}")
async def remove_group(
    group_id: int,
    telegram_user_id: int,
):
    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(UserGroup).where(
                UserGroup.user_id == user.id,
                UserGroup.group_id == group_id,
                UserGroup.status == "ACTIVE",
            )
        )

        user_group = (
            result.scalar_one_or_none()
        )

        if user_group is None:
            raise HTTPException(
                status_code=404,
                detail="Grup tidak ditemukan.",
            )

        user_group.status = "INACTIVE"

        await db.commit()

        return {
            "ok": True,
            "message": (
                "Grup berhasil dihapus "
                "dari daftar kamu."
            ),
        }