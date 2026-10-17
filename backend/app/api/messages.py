import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import Message as MessageModel
from app.db.models import User
from app.db.session import SessionLocal


router = APIRouter(
    prefix="/api/messages",
    tags=["Messages"],
)

logger = logging.getLogger(__name__)


# ============================================================
# REQUEST MODELS
# ============================================================

class MessageCreate(BaseModel):
    telegram_user_id: int

    title: str = Field(
        min_length=1,
        max_length=255,
    )

    content: str = Field(
        min_length=1,
    )


class MessageUpdate(BaseModel):
    telegram_user_id: int

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )

    content: str | None = Field(
        default=None,
        min_length=1,
    )

    status: str | None = Field(
        default=None,
        max_length=32,
    )


# ============================================================
# HELPER
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


def serialize_message(
    message: MessageModel,
) -> dict:

    return {
        "id": message.id,
        "user_id": message.user_id,
        "title": message.title,
        "content": message.content,
        "status": message.status,
        "created_at": message.created_at,
    }


# ============================================================
# LIST MESSAGES
# ============================================================

@router.get("")
async def list_messages(
    telegram_user_id: int,
):
    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(MessageModel)
            .where(
                MessageModel.user_id
                == user.id
            )
            .order_by(
                MessageModel.id.desc()
            )
        )

        messages = result.scalars().all()

        return {
            "ok": True,
            "messages": [
                serialize_message(message)
                for message in messages
            ],
        }


# ============================================================
# GET MESSAGE
# ============================================================

@router.get("/{message_id}")
async def get_message(
    message_id: int,
    telegram_user_id: int,
):
    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(MessageModel).where(
                MessageModel.id == message_id,
                MessageModel.user_id == user.id,
            )
        )

        message = result.scalar_one_or_none()

        if message is None:

            raise HTTPException(
                status_code=404,
                detail="Pesan tidak ditemukan.",
            )

        return {
            "ok": True,
            "message": serialize_message(
                message
            ),
        }


# ============================================================
# CREATE MESSAGE
# ============================================================

@router.post("")
async def create_message(
    payload: MessageCreate,
):
    user = await get_user(
        payload.telegram_user_id
    )

    title = payload.title.strip()
    content = payload.content.strip()

    if not title:

        raise HTTPException(
            status_code=400,
            detail="Judul pesan tidak boleh kosong.",
        )

    if not content:

        raise HTTPException(
            status_code=400,
            detail="Isi pesan tidak boleh kosong.",
        )

    async with SessionLocal() as db:

        message = MessageModel(
            user_id=user.id,
            title=title,
            content=content,
            status="ACTIVE",
        )

        db.add(message)

        await db.commit()

        await db.refresh(message)

        return {
            "ok": True,
            "message": "Pesan berhasil dibuat.",
            "data": serialize_message(
                message
            ),
        }


# ============================================================
# UPDATE MESSAGE
# ============================================================

@router.patch("/{message_id}")
async def update_message(
    message_id: int,
    payload: MessageUpdate,
):
    user = await get_user(
        payload.telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(MessageModel).where(
                MessageModel.id == message_id,
                MessageModel.user_id == user.id,
            )
        )

        message = result.scalar_one_or_none()

        if message is None:

            raise HTTPException(
                status_code=404,
                detail="Pesan tidak ditemukan.",
            )

        if payload.title is not None:

            title = payload.title.strip()

            if not title:

                raise HTTPException(
                    status_code=400,
                    detail="Judul tidak boleh kosong.",
                )

            message.title = title

        if payload.content is not None:

            content = payload.content.strip()

            if not content:

                raise HTTPException(
                    status_code=400,
                    detail="Isi pesan tidak boleh kosong.",
                )

            message.content = content

        if payload.status is not None:

            allowed_statuses = {
                "ACTIVE",
                "INACTIVE",
            }

            if payload.status not in allowed_statuses:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Status harus ACTIVE "
                        "atau INACTIVE."
                    ),
                )

            message.status = payload.status

        await db.commit()

        await db.refresh(message)

        return {
            "ok": True,
            "message": "Pesan berhasil diperbarui.",
            "data": serialize_message(
                message
            ),
        }


# ============================================================
# DELETE MESSAGE
# ============================================================

@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    telegram_user_id: int,
):
    user = await get_user(
        telegram_user_id
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(MessageModel).where(
                MessageModel.id == message_id,
                MessageModel.user_id == user.id,
            )
        )

        message = result.scalar_one_or_none()

        if message is None:

            raise HTTPException(
                status_code=404,
                detail="Pesan tidak ditemukan.",
            )

        # Soft delete
        message.status = "INACTIVE"

        await db.commit()

        return {
            "ok": True,
            "message": (
                "Pesan berhasil dinonaktifkan."
            ),
        }