from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================
# USER
# ============================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user",
    )

    telegram_accounts: Mapped[list["TelegramAccount"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    user_groups: Mapped[list["UserGroup"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ============================================================
# TELEGRAM ACCOUNT
# ============================================================

class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    telegram_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
        index=True,
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Session Telegram harus disimpan dalam bentuk terenkripsi.
    session_data: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        index=True,
    )

    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(
        back_populates="telegram_accounts",
    )


# ============================================================
# PLAN
# ============================================================

class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
    )

    price: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    duration_days: Mapped[int] = mapped_column(
        Integer,
    )

    max_characters: Mapped[int] = mapped_column(
        Integer,
    )

    max_groups: Mapped[int] = mapped_column(
        Integer,
    )

    min_delay_seconds: Mapped[int] = mapped_column(
        Integer,
    )

    max_accounts: Mapped[int] = mapped_column(
        Integer,
        default=1,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
    )


# ============================================================
# SUBSCRIPTION
# ============================================================

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id"),
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )

    expired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
    )

    user: Mapped["User"] = relationship(
        back_populates="subscriptions",
    )


# ============================================================
# MESSAGE
# ============================================================

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
    )

    content: Mapped[str] = mapped_column(
        Text,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


# ============================================================
# GROUP
# ============================================================

class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
    )

    user_groups: Mapped[list["UserGroup"]] = relationship(
        back_populates="group",
    )


# ============================================================
# USER GROUP
# ============================================================

class UserGroup(Base):
    __tablename__ = "user_groups"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id"),
        index=True,
    )

    telegram_account_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_accounts.id"),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(
        back_populates="user_groups",
    )

    group: Mapped["Group"] = relationship(
        back_populates="user_groups",
    )

    telegram_account: Mapped["TelegramAccount"] = relationship()


# ============================================================
# AUTO POST JOB
# ============================================================

class AutoPostJob(Base):
    __tablename__ = "autopost_jobs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    telegram_account_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_accounts.id"),
        index=True,
    )

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"),
    )

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id"),
        index=True,
    )

    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        index=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        index=True,
    )

    delay_seconds: Mapped[int] = mapped_column(
    Integer,
    nullable=False,
    default=60,
)

    telegram_account: Mapped["TelegramAccount"] = relationship()