"""add production module (orders + order_items + cart + audit_log)

Revision ID: 025_add_production_module
Revises: 024_add_asset_tag_filter_index
Create Date: 2026-05-26 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_add_production_module"
down_revision: Union[str, None] = "024_add_asset_tag_filter_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 状态枚举值说明:
# 0 = 已提交, 1 = 已终止, 2 = 已完成


def upgrade() -> None:
    # ── 表1: 生产订单主表 ───────────────────────────────────
    op.create_table(
        "ark_production_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column("order_no", sa.String(32), nullable=False, comment="生产单号,如 PO20250526-001"),
        sa.Column("batch_no", sa.String(64), nullable=False, comment="生产批次号"),
        sa.Column("remark", sa.String(500), nullable=True, comment="生产单备注"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0", comment="0=已提交,1=已终止,2=已完成"),
        sa.Column("created_by", sa.Integer(), nullable=False, comment="创建人 user_id"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建时间"),
        sa.Column("updated_by", sa.Integer(), nullable=True, comment="最后修改人 user_id"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="最后修改时间"),
        sa.Column("deleted_flag", sa.SmallInteger(), nullable=False, server_default="0", comment="0=正常,1=已删除(软删)"),
        sa.UniqueConstraint("order_no", name="uk_order_no"),
        sa.UniqueConstraint("batch_no", name="uk_batch_no"),
        sa.Index("idx_production_orders_status", "status"),
        sa.Index("idx_production_orders_created_by", "created_by"),
        comment="生产订单主表",
    )

    # ── 表2: 生产订单明细表 ─────────────────────────────────
    op.create_table(
        "ark_production_order_items",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column("order_id", sa.Integer(), nullable=False, comment="关联生产订单ID"),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品ID"),
        sa.Column("product_name", sa.String(255), nullable=False, comment="产品名称"),
        sa.Column("model", sa.String(100), nullable=True, comment="型号"),
        sa.Column("spec_info", sa.String(255), nullable=True, comment="规格属性"),
        sa.Column("order_qty", sa.Integer(), nullable=False, comment="生产下单数量"),
        sa.Column("received_qty", sa.Integer(), nullable=False, server_default="0", comment="已入库数量"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0", comment="0=已提交,1=已终止,2=已完成"),
        sa.Column("remark", sa.String(500), nullable=True, comment="明细备注"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="最后修改时间"),
        sa.ForeignKeyConstraint(["order_id"], ["ark_production_orders.id"], ondelete="CASCADE"),
        sa.Index("idx_production_items_order_id", "order_id"),
        sa.Index("idx_production_items_product_id", "product_id"),
        sa.Index("idx_production_items_status", "status"),
        comment="生产订单产品明细表",
    )

    # ── 表3: 生产单购物车 ───────────────────────────────────
    op.create_table(
        "ark_production_cart",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品ID"),
        sa.Column("product_name", sa.String(255), nullable=False, comment="产品名称"),
        sa.Column("model", sa.String(100), nullable=True, comment="型号"),
        sa.Column("spec_info", sa.String(255), nullable=True, comment="规格属性"),
        sa.Column("order_qty", sa.Integer(), nullable=False, comment="生产下单数量"),
        sa.Column("remark", sa.String(500), nullable=True, comment="备注"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="最后修改时间"),
        sa.UniqueConstraint("user_id", "product_id", name="uk_cart_user_product"),
        sa.Index("idx_production_cart_user_id", "user_id"),
        comment="生产单购物车,按用户隔离",
    )

    # ── 表4: 生产订单审计日志表 ─────────────────────────────
    op.create_table(
        "ark_production_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column("order_id", sa.Integer(), nullable=False, comment="关联生产订单ID"),
        sa.Column("item_id", sa.Integer(), nullable=True, comment="关联明细ID,可为空"),
        sa.Column("operator_id", sa.Integer(), nullable=False, comment="操作人 user_id"),
        sa.Column("operator_name", sa.String(64), nullable=False, comment="操作人姓名"),
        sa.Column("action", sa.String(32), nullable=False, comment="操作动作: create/update/delete/update_status/update_received"),
        sa.Column("from_status", sa.SmallInteger(), nullable=True, comment="原状态"),
        sa.Column("to_status", sa.SmallInteger(), nullable=True, comment="目标状态"),
        sa.Column("comment", sa.String(500), nullable=True, comment="操作备注"),
        sa.Column("snapshot", sa.JSON(), nullable=True, comment="变更快照JSON"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="操作时间"),
        sa.Index("idx_production_audit_order_id", "order_id"),
        sa.Index("idx_production_audit_created_at", "created_at"),
        comment="生产订单审计日志",
    )


def downgrade() -> None:
    op.drop_table("ark_production_audit_log")
    op.drop_table("ark_production_cart")
    op.drop_table("ark_production_order_items")
    op.drop_table("ark_production_orders")
