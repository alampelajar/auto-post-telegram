import asyncio

from backend.app.db.base import Base
from backend.app.db import models  # noqa: F401
from backend.app.db.session import engine


async def init() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(init())
