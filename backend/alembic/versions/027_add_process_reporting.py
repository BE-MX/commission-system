"""add production process reporting tables

Revision ID: 027_add_process_reporting
Revises: 026_add_urgent_and_delivery_date
Create Date: 2026-06-01 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027_add_process_reporting"
down_revision: Union[str, None] = "026_add_urgent_and_delivery_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. ark_users 新增 wx_id 字段 ──────────────────────
    op.add_column(
        "ark_users",
        sa.Column("wx_id", sa.String(100), nullable=True, comment="微信原始ID（FromUserName），用于报工时匹配方舟账号"),
    )
    op.create_unique_constraint("uk_users_wx_id", "ark_users", ["wx_id"])

    # ── 2. process 工序表 ─────────────────────────────────
    op.create_table(
        "process",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False, comment="工序名称"),
        sa.Column("description", sa.String(500), nullable=True, comment="工序描述/备注"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="展示排序权重"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1", comment="0=禁用,1=启用"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uk_process_name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="工序基础表",
    )
    op.create_index("idx_process_status", "process", ["status"])

    # ── 3. process_route 工序路线表 ────────────────────────
    op.create_table(
        "process_route",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False, comment="路线名称"),
        sa.Column("description", sa.String(500), nullable=True, comment="路线描述"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1", comment="0=禁用,1=启用"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uk_route_name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="工序路线表",
    )
    op.create_index("idx_route_status", "process_route", ["status"])

    # ── 4. process_route_step 路线明细表 ───────────────────
    op.create_table(
        "process_route_step",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False, comment="关联 process_route.id"),
        sa.Column("process_id", sa.Integer(), nullable=False, comment="关联 process.id"),
        sa.Column("step_order", sa.SmallInteger(), nullable=False, comment="执行顺序,从1开始"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_id", "step_order", name="uk_route_step"),
        sa.UniqueConstraint("route_id", "process_id", name="uk_route_process"),
        sa.ForeignKeyConstraint(["route_id"], ["process_route.id"], ondelete="CASCADE", name="fk_step_route"),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT", name="fk_step_process"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="工序路线明细表",
    )
    op.create_index("idx_step_route_id", "process_route_step", ["route_id"])
    op.create_index("idx_step_process_id", "process_route_step", ["process_id"])

    # ── 5. product_process_route 产品路线绑定表 ─────────────
    op.create_table(
        "product_process_route",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品ID"),
        sa.Column("route_id", sa.Integer(), nullable=False, comment="关联 process_route.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uk_product_route"),
        sa.ForeignKeyConstraint(["route_id"], ["process_route.id"], ondelete="RESTRICT", name="fk_ppr_route"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="产品工序路线绑定表",
    )
    op.create_index("idx_ppr_route_id", "product_process_route", ["route_id"])

    # ── 6. order_product_process_progress 工序进度表 ────────
    op.create_table(
        "order_product_process_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_product_id", sa.Integer(), nullable=False, comment="关联 ark_production_order_items.id"),
        sa.Column("process_id", sa.Integer(), nullable=False, comment="关联 process.id"),
        sa.Column("route_id", sa.Integer(), nullable=False, comment="冗余路线ID"),
        sa.Column("step_order", sa.SmallInteger(), nullable=False, comment="工序顺序"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0", comment="0=待完成,1=已完成"),
        sa.Column("completed_at", sa.DateTime(), nullable=True, comment="完成时间"),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True, comment="完成操作人方舟用户ID"),
        sa.Column("completed_by_wx_id", sa.String(100), nullable=True, comment="完成操作人微信原始ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_product_id", "step_order", name="uk_progress_order_product_step"),
        sa.ForeignKeyConstraint(["order_product_id"], ["ark_production_order_items.id"], ondelete="CASCADE", name="fk_progress_order_product"),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT", name="fk_progress_process"),
        sa.ForeignKeyConstraint(["route_id"], ["process_route.id"], ondelete="RESTRICT", name="fk_progress_route"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="订单产品工序进度表",
    )
    op.create_index("idx_progress_order_product_id", "order_product_process_progress", ["order_product_id"])
    op.create_index("idx_progress_process_id", "order_product_process_progress", ["process_id"])
    op.create_index("idx_progress_status", "order_product_process_progress", ["status"])
    op.create_index("idx_progress_order_status", "order_product_process_progress", ["order_product_id", "status"])

    # ── 7. user_process_binding 用户工序绑定表 ──────────────
    op.create_table(
        "user_process_binding",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="方舟用户ID"),
        sa.Column("process_id", sa.Integer(), nullable=False, comment="工序ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "process_id", name="uk_user_process"),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="CASCADE", name="fk_upb_process"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="用户工序绑定表",
    )
    op.create_index("idx_upb_user_id", "user_process_binding", ["user_id"])
    op.create_index("idx_upb_process_id", "user_process_binding", ["process_id"])


def downgrade() -> None:
    op.drop_table("user_process_binding")
    op.drop_table("order_product_process_progress")
    op.drop_table("product_process_route")
    op.drop_table("process_route_step")
    op.drop_table("process_route")
    op.drop_table("process")
    op.drop_constraint("uk_users_wx_id", "ark_users", type_="unique")
    op.drop_column("ark_users", "wx_id")
