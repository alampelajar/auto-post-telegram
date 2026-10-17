from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AutoPostJob,
    Group,
    Message,
    TelegramAccount,
    User,
    UserGroup,
)
from app.db.session import get_db


router = APIRouter(
    prefix="/api/autopost",
    tags=["autopost"],
)


# ============================================================
# SCHEMAS
# ============================================================

class AutoPostCreate(BaseModel):
    telegram_user_id: int
    telegram_account_id: int
    message_id: int
    group_ids: list[int] = Field(min_length=1)
    delay_seconds: int = Field(default=60, ge=1)


class AutoPostUpdate(BaseModel):
    telegram_user_id: int
    enabled: Optional[bool] = None
    delay_seconds: Optional[int] = Field(
        default=None,
        ge=1,
    )


# ============================================================
# HELPERS
# ============================================================

async def get_user(
    db: AsyncSession,
    telegram_user_id: int,
) -> User:
    result = await db.execute(
        select(User).where(
            User.telegram_user_id == telegram_user_id
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User tidak ditemukan.",
        )

    return user


async def get_account(
    db: AsyncSession,
    user_id: int,
    account_id: int,
) -> TelegramAccount:
    result = await db.execute(
        select(TelegramAccount).where(
            TelegramAccount.id == account_id,
            TelegramAccount.user_id == user_id,
        )
    )

    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Akun Telegram tidak ditemukan.",
        )

    if account.status != "CONNECTED":
        raise HTTPException(
            status_code=400,
            detail="Akun Telegram belum terhubung.",
        )

    return account


async def get_message(
    db: AsyncSession,
    user_id: int,
    message_id: int,
) -> Message:
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
            Message.status == "ACTIVE",
        )
    )

    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=404,
            detail="Pesan tidak ditemukan atau tidak aktif.",
        )

    return message


# ============================================================
# SERIALIZER
# ============================================================

def serialize_job(job: AutoPostJob) -> dict:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "telegram_account_id": job.telegram_account_id,
        "message_id": job.message_id,
        "group_id": job.group_id,
        "delay_seconds": job.delay_seconds,
        "next_run_at": (
            job.next_run_at.isoformat()
            if job.next_run_at
            else None
        ),
        "last_run_at": (
            job.last_run_at.isoformat()
            if job.last_run_at
            else None
        ),
        "status": job.status,
        "attempt_count": job.attempt_count,
        "enabled": job.enabled,
    }


# ============================================================
# LIST JOBS
# ============================================================

@router.get("/jobs")
async def list_jobs(
    telegram_user_id: int,
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(
        db,
        telegram_user_id,
    )

    result = await db.execute(
        select(AutoPostJob)
        .where(
            AutoPostJob.user_id == user.id
        )
        .order_by(
            AutoPostJob.id.desc()
        )
    )

    jobs = result.scalars().all()

    return {
        "ok": True,
        "items": [
            serialize_job(job)
            for job in jobs
        ],
        "total": len(jobs),
    }


# ============================================================
# GET SINGLE JOB
# ============================================================

@router.get("/jobs/{job_id}")
async def get_job(
    job_id: int,
    telegram_user_id: int,
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(
        db,
        telegram_user_id,
    )

    result = await db.execute(
        select(AutoPostJob).where(
            AutoPostJob.id == job_id,
            AutoPostJob.user_id == user.id,
        )
    )

    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job tidak ditemukan.",
        )

    return {
        "ok": True,
        "item": serialize_job(job),
    }


# ============================================================
# CREATE AUTO POST JOBS
# ============================================================

@router.post("/jobs")
async def create_jobs(
    payload: AutoPostCreate,
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(
        db,
        payload.telegram_user_id,
    )

    # --------------------------------------------------------
    # VALIDATE TELEGRAM ACCOUNT
    # --------------------------------------------------------

    account = await get_account(
        db,
        user.id,
        payload.telegram_account_id,
    )

    # --------------------------------------------------------
    # VALIDATE MESSAGE
    # --------------------------------------------------------

    message = await get_message(
        db,
        user.id,
        payload.message_id,
    )

    # --------------------------------------------------------
    # CREATE JOB FOR EACH GROUP
    # --------------------------------------------------------

    created_jobs: list[AutoPostJob] = []

    now = datetime.now(timezone.utc)

    for group_id in payload.group_ids:

        # ----------------------------------------------------
        # Pastikan group memang terhubung
        # dengan user + account yang dipilih
        # ----------------------------------------------------

        result = await db.execute(
            select(UserGroup).where(
                UserGroup.user_id == user.id,
                UserGroup.group_id == group_id,
                UserGroup.telegram_account_id == account.id,
                UserGroup.status == "ACTIVE",
            )
        )

        user_group = result.scalar_one_or_none()

        if not user_group:
            continue

        # ----------------------------------------------------
        # Pastikan group ada
        # ----------------------------------------------------

        result = await db.execute(
            select(Group).where(
                Group.id == group_id
            )
        )

        group = result.scalar_one_or_none()

        if not group:
            continue

        # ----------------------------------------------------
        # Cek duplicate active job
        # ----------------------------------------------------

        result = await db.execute(
            select(AutoPostJob).where(
                AutoPostJob.user_id == user.id,
                AutoPostJob.telegram_account_id == account.id,
                AutoPostJob.message_id == message.id,
                AutoPostJob.group_id == group.id,
                AutoPostJob.enabled.is_(True),
            )
        )

        existing_job = result.scalar_one_or_none()

        if existing_job:
            continue

        # ----------------------------------------------------
        # CREATE JOB
        # ----------------------------------------------------

        job = AutoPostJob(
            user_id=user.id,
            telegram_account_id=account.id,
            message_id=message.id,
            group_id=group.id,
            delay_seconds=payload.delay_seconds,
            next_run_at=now,
            last_run_at=None,
            status="ACTIVE",
            attempt_count=0,
            enabled=True,
        )

        db.add(job)
        created_jobs.append(job)

    # --------------------------------------------------------
    # COMMIT
    # --------------------------------------------------------

    await db.commit()

    # --------------------------------------------------------
    # REFRESH CREATED JOBS
    # --------------------------------------------------------

    for job in created_jobs:
        await db.refresh(job)

    return {
        "ok": True,
        "message": "Auto post berhasil dibuat.",
        "created": len(created_jobs),
        "skipped": len(payload.group_ids) - len(created_jobs),
        "jobs": [
            serialize_job(job)
            for job in created_jobs
        ],
    }


# ============================================================
# UPDATE JOB
# ============================================================

@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: int,
    payload: AutoPostUpdate,
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(
        db,
        payload.telegram_user_id,
    )

    result = await db.execute(
        select(AutoPostJob).where(
            AutoPostJob.id == job_id,
            AutoPostJob.user_id == user.id,
        )
    )

    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job tidak ditemukan.",
        )

    # --------------------------------------------------------
    # UPDATE ENABLED
    # --------------------------------------------------------

    if payload.enabled is not None:
        job.enabled = payload.enabled

        if payload.enabled:
            job.status = "ACTIVE"

            # Saat diaktifkan kembali,
            # jadwalkan mulai dari sekarang
            job.next_run_at = datetime.now(timezone.utc)

        else:
            job.status = "PAUSED"

    # --------------------------------------------------------
    # UPDATE DELAY
    # --------------------------------------------------------

    if payload.delay_seconds is not None:
        job.delay_seconds = payload.delay_seconds

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    await db.commit()
    await db.refresh(job)

    return {
        "ok": True,
        "message": "Job berhasil diperbarui.",
        "item": serialize_job(job),
    }


# ============================================================
# DELETE / STOP JOB
# ============================================================

@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: int,
    telegram_user_id: int,
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(
        db,
        telegram_user_id,
    )

    result = await db.execute(
        select(AutoPostJob).where(
            AutoPostJob.id == job_id,
            AutoPostJob.user_id == user.id,
        )
    )

    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job tidak ditemukan.",
        )

    job.enabled = False
    job.status = "DELETED"

    await db.commit()

    return {
        "ok": True,
        "message": "Auto post berhasil dihentikan.",
    }