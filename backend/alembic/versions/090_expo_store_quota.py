"""expo_store_quota

Revision ID: 090_expo_store_quota
Revises: 089_design_image_studio
Create Date: 2026-08-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# ark_users.id 在 MySQL 实际为 INT UNSIGNED；FK 列类型必须与目标列完全一致。
_UID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


revision: str = "090_expo_store_quota"
down_revision: Union[str, None] = "089_design_image_studio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ark_expo_stores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("total_quota", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("used_quota", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("contact_name", sa.String(length=64), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_ark_expo_stores_code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_table(
        "ark_expo_store_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", _UID, nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "user_id", name="uq_ark_expo_store_users_pair"),
        sa.ForeignKeyConstraint(["store_id"], ["ark_expo_stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["ark_users.id"], ondelete="CASCADE"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_table(
        "ark_expo_quota_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_before", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("related_id", sa.Integer(), nullable=True),
        sa.Column("related_type", sa.String(length=32), nullable=True),
        sa.Column("operator_user_id", _UID, nullable=False),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["store_id"], ["ark_expo_stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_user_id"], ["ark_users.id"], ondelete="CASCADE"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.add_column(
        "ark_expo_sessions",
        sa.Column("store_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ark_expo_sessions_store_id",
        "ark_expo_sessions",
        "ark_expo_stores",
        ["store_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "ark_expo_customers",
        sa.Column("store_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ark_expo_customers_store_id",
        "ark_expo_customers",
        "ark_expo_stores",
        ["store_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ark_expo_customers_store_id", "ark_expo_customers", type_="foreignkey")
    op.drop_column("ark_expo_customers", "store_id")

    op.drop_constraint("fk_ark_expo_sessions_store_id", "ark_expo_sessions", type_="foreignkey")
    op.drop_column("ark_expo_sessions", "store_id")

    op.drop_table("ark_expo_quota_records")
    op.drop_table("ark_expo_store_users")
    op.drop_table("ark_expo_stores")
