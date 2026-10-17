from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.models import Plan, Subscription, User
from backend.app.db.session import get_db

router = APIRouter(prefix="/users", tags=["users"])
settings = get_settings()


class UpsertUserRequest(BaseModel):
    telegram_user_id: int = Field(gt=0)
    username: str | None = None
    first_name: str | None = None


class UserResponse(BaseModel):
    id: int
    telegram_user_id: int
    username: str | None
    first_name: str | None
    status: str


async def require_internal_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    if not settings.internal_api_secret or x_internal_secret != settings.internal_api_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.post("/upsert", response_model=UserResponse, dependencies=[Depends(require_internal_secret)])
async def upsert_user(payload: UpsertUserRequest, db: AsyncSession = Depends(get_db)) -> User:
    result = await db.execute(select(User).where(User.telegram_user_id == payload.telegram_user_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            first_name=payload.first_name,
        )
        db.add(user)
    else:
        user.username = payload.username
        user.first_name = payload.first_name

    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{telegram_user_id}", response_model=UserResponse, dependencies=[Depends(require_internal_secret)])
async def get_user(telegram_user_id: int, db: AsyncSession = Depends(get_db)) -> User:
    result = await db.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{telegram_user_id}/subscription", dependencies=[Depends(require_internal_secret)])
async def get_current_subscription(telegram_user_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    sub_result = await db.execute(
        select(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.expired_at.desc())
        .limit(1)
    )
    row = sub_result.first()
    if row is None:
        return {"active": False, "subscription": None}

    subscription, plan = row
    return {
        "active": subscription.status == "ACTIVE",
        "subscription": {
            "id": subscription.id,
            "plan_name": plan.name,
            "status": subscription.status,
            "started_at": subscription.started_at,
            "expired_at": subscription.expired_at,
        },
    }
