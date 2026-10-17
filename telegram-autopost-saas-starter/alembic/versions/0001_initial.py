"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("max_characters", sa.Integer(), nullable=False),
        sa.Column("max_groups", sa.Integer(), nullable=False),
        sa.Column("min_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("max_accounts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_plans_status", "plans", ["status"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"])
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "telegram_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("phone_masked", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DISCONNECTED"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index("ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"])
    op.create_index("ix_telegram_accounts_telegram_user_id", "telegram_accounts", ["telegram_user_id"])
    op.create_index("ix_telegram_accounts_status", "telegram_accounts", ["status"])

    op.create_table(
        "telegram_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("telegram_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encrypted_session", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("account_id"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_expired_at", "subscriptions", ["expired_at"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("entities", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_user_id", "messages", ["user_id"])
    op.create_index("ix_messages_status", "messages", ["status"])

    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.UniqueConstraint("telegram_chat_id"),
    )
    op.create_index("ix_groups_telegram_chat_id", "groups", ["telegram_chat_id"])
    op.create_index("ix_groups_status", "groups", ["status"])

    op.create_table(
        "user_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_user_group"),
    )
    op.create_index("ix_user_groups_user_id", "user_groups", ["user_id"])
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])
    op.create_index("ix_user_groups_status", "user_groups", ["status"])

    op.create_table(
        "autopost_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("telegram_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_autopost_jobs_user_id", "autopost_jobs", ["user_id"])
    op.create_index("ix_autopost_jobs_account_id", "autopost_jobs", ["account_id"])
    op.create_index("ix_autopost_jobs_group_id", "autopost_jobs", ["group_id"])
    op.create_index("ix_autopost_jobs_next_run_at", "autopost_jobs", ["next_run_at"])
    op.create_index("ix_autopost_jobs_status", "autopost_jobs", ["status"])
    op.create_index("ix_autopost_jobs_enabled", "autopost_jobs", ["enabled"])

    # Seed development plans. Owner can later edit these through the admin module.
    plans = sa.table(
        "plans",
        sa.column("name", sa.String()),
        sa.column("price", sa.Integer()),
        sa.column("duration_days", sa.Integer()),
        sa.column("max_characters", sa.Integer()),
        sa.column("max_groups", sa.Integer()),
        sa.column("min_delay_seconds", sa.Integer()),
        sa.column("max_accounts", sa.Integer()),
        sa.column("status", sa.String()),
    )
    op.bulk_insert(
        plans,
        [
            {"name": "Starter", "price": 0, "duration_days": 30, "max_characters": 500, "max_groups": 5, "min_delay_seconds": 3600, "max_accounts": 1, "status": "ACTIVE"},
            {"name": "Basic", "price": 0, "duration_days": 30, "max_characters": 1000, "max_groups": 15, "min_delay_seconds": 1800, "max_accounts": 1, "status": "ACTIVE"},
            {"name": "Pro", "price": 0, "duration_days": 30, "max_characters": 2000, "max_groups": 50, "min_delay_seconds": 900, "max_accounts": 2, "status": "ACTIVE"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_autopost_jobs_enabled", table_name="autopost_jobs")
    op.drop_index("ix_autopost_jobs_status", table_name="autopost_jobs")
    op.drop_index("ix_autopost_jobs_next_run_at", table_name="autopost_jobs")
    op.drop_index("ix_autopost_jobs_group_id", table_name="autopost_jobs")
    op.drop_index("ix_autopost_jobs_account_id", table_name="autopost_jobs")
    op.drop_index("ix_autopost_jobs_user_id", table_name="autopost_jobs")
    op.drop_table("autopost_jobs")
    op.drop_index("ix_user_groups_status", table_name="user_groups")
    op.drop_index("ix_user_groups_group_id", table_name="user_groups")
    op.drop_index("ix_user_groups_user_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_index("ix_groups_status", table_name="groups")
    op.drop_index("ix_groups_telegram_chat_id", table_name="groups")
    op.drop_table("groups")
    op.drop_index("ix_messages_status", table_name="messages")
    op.drop_index("ix_messages_user_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_expired_at", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("telegram_sessions")
    op.drop_index("ix_telegram_accounts_status", table_name="telegram_accounts")
    op.drop_index("ix_telegram_accounts_telegram_user_id", table_name="telegram_accounts")
    op.drop_index("ix_telegram_accounts_user_id", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_plans_status", table_name="plans")
    op.drop_table("plans")
