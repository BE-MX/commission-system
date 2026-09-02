"""Finalize domestic member pricing snapshots and constraints.

Revision ID: 131_domestic_member_pricing_b
Revises: 130_domestic_member_pricing_a
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "131_domestic_member_pricing_b"
down_revision = "130_domestic_member_pricing_a"
branch_labels = None
depends_on = None


MONEY = sa.Numeric(14, 2)
TABLE_NAME = "ark_domestic_order_items"

REQUIRED_COLUMNS = (
    ("original_price", MONEY, "原价快照（人民币）"),
    ("discount_amount", MONEY, "优惠金额快照（人民币）"),
    ("pricing_rule", sa.String(24), "定价规则"),
    ("pricing_version", sa.String(32), "定价算法版本"),
    ("base_price_version_snapshot", sa.Integer(), "基础价格版本快照"),
)

CHECKS = (
    ("ck_dom_item_unit_price_nonnegative", "unit_price >= 0"),
    ("ck_dom_item_discount_nonnegative", "discount_amount >= 0"),
    (
        "ck_dom_item_unit_not_above_original",
        "unit_price <= original_price",
    ),
    (
        "ck_dom_item_original_price_valid",
        "original_price > 0 OR pricing_rule = 'legacy_manual'",
    ),
    (
        "ck_dom_item_base_price_version_nonnegative",
        "base_price_version_snapshot >= 0",
    ),
    (
        "ck_dom_item_membership_snapshot",
        "membership_level_snapshot IS NULL OR membership_level_snapshot IN "
        "('silver', 'black', 'supreme')",
    ),
    (
        "ck_dom_item_pricing_rule",
        "pricing_rule IN ('base_price', 'member_fixed', "
        "'member_fixed_capped', 'member_reduction', 'legacy_manual')",
    ),
)


def _validate_existing_snapshots(connection) -> None:
    invalid = connection.execute(
        sa.text(
            "SELECT id FROM ark_domestic_order_items WHERE "
            "unit_price IS NULL OR unit_price < 0 "
            "OR original_price IS NULL "
            "OR discount_amount IS NULL OR discount_amount < 0 "
            "OR pricing_rule IS NULL "
            "OR pricing_version IS NULL "
            "OR base_price_version_snapshot IS NULL "
            "OR base_price_version_snapshot < 0 "
            "OR unit_price > original_price "
            "OR NOT (original_price > 0 OR pricing_rule = 'legacy_manual') "
            "OR (membership_level_snapshot IS NOT NULL AND "
            "membership_level_snapshot NOT IN ('silver', 'black', 'supreme')) "
            "OR pricing_rule NOT IN ('base_price', 'member_fixed', "
            "'member_fixed_capped', 'member_reduction', 'legacy_manual') "
            "ORDER BY id LIMIT 1"
        )
    ).first()
    if invalid is not None:
        raise RuntimeError(
            "ark_domestic_order_items 存在非法价格快照，"
            f"首条 id={invalid.id}；请修复数据后重试迁移"
        )


def upgrade() -> None:
    if not op.get_context().as_sql:
        _validate_existing_snapshots(op.get_bind())

    op.alter_column(
        TABLE_NAME,
        "unit_price",
        existing_type=MONEY,
        nullable=False,
        existing_server_default=sa.text("0.00"),
        server_default=None,
        existing_comment="产品单价",
    )

    for column_name, column_type, comment in REQUIRED_COLUMNS:
        op.alter_column(
            TABLE_NAME,
            column_name,
            existing_type=column_type,
            nullable=False,
            existing_comment=comment,
        )

    for constraint_name, condition in CHECKS:
        op.create_check_constraint(
            constraint_name,
            TABLE_NAME,
            condition,
        )


def downgrade() -> None:
    for constraint_name, _condition in reversed(CHECKS):
        op.drop_constraint(constraint_name, TABLE_NAME, type_="check")

    for column_name, column_type, comment in REQUIRED_COLUMNS:
        op.alter_column(
            TABLE_NAME,
            column_name,
            existing_type=column_type,
            nullable=True,
            existing_comment=comment,
        )

    op.alter_column(
        TABLE_NAME,
        "unit_price",
        existing_type=MONEY,
        nullable=False,
        existing_server_default=None,
        server_default=sa.text("0.00"),
        existing_comment="产品单价",
    )
