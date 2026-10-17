from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.models import Plan
from backend.app.db.session import get_db

router = APIRouter(prefix="/plans", tags=["plans"])
settings = get_settings()


async def require_internal_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    if not settings.internal_api_secret or x_internal_secret != settings.internal_api_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.get("", dependencies=[Depends(require_internal_secret)])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(select(Plan).where(Plan.status == "ACTIVE").order_by(Plan.price.asc()))
    plans = result.scalars().all()
    return [
        {
            "id": plan.id,
            "name": plan.name,
            "price": plan.price,
            "duration_days": plan.duration_days,
            "max_characters": plan.max_characters,
            "max_groups": plan.max_groups,
            "min_delay_seconds": plan.min_delay_seconds,
            "max_accounts": plan.max_accounts,
        }
        for plan in plans
    ]
