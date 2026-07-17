"""invoice: add accessory product fields

Revision ID: 073_invoice_accessory_products
Revises: 072_expo_wig_color_images
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "073_invoice_accessory_products"
down_revision = "072_expo_wig_color_images"
branch_labels = None
depends_on = None


def _assert_downgrade_safe(connection) -> None:
    counts = {
        "accessory_std": connection.scalar(sa.text(
            "SELECT COUNT(*) FROM ark_std_prices WHERE product_kind = 'accessory'"
        )),
        "accessory_items": connection.scalar(sa.text(
            "SELECT COUNT(*) FROM ark_invoice_items WHERE product_kind = 'accessory'"
        )),
        "invalid_hair_std": connection.scalar(sa.text(
            "SELECT COUNT(*) FROM ark_std_prices WHERE product_kind = 'hair' "
            "AND (series_grade IS NULL OR length IS NULL OR weight_unit IS NULL OR color_type IS NULL)"
        )),
        "invalid_hair_items": connection.scalar(sa.text(
            "SELECT COUNT(*) FROM ark_invoice_items WHERE product_kind = 'hair' "
            "AND (length IS NULL OR net_weight_grams IS NULL)"
        )),
    }
    counts = {key: int(value or 0) for key, value in counts.items()}
    problems = []
    if counts["accessory_std"] or counts["accessory_items"]:
        problems.append(
            "accessory rows exist: "
            f"ark_std_prices={counts['accessory_std']}, "
            f"ark_invoice_items={counts['accessory_items']}"
        )
    if counts["invalid_hair_std"] or counts["invalid_hair_items"]:
        problems.append(
            "hair rows violate the 072 NOT NULL schema: "
            f"ark_std_prices NULL dimensions={counts['invalid_hair_std']}, "
            "ark_invoice_items NULL length/net_weight_grams="
            f"{counts['invalid_hair_items']}"
        )
    if problems:
        raise RuntimeError(
            "Refusing downgrade 073_invoice_accessory_products: "
            + "; ".join(problems)
            + ". Migrate or repair these rows before downgrading; no schema changes were made."
        )


def upgrade() -> None:
    op.add_column(
        "ark_std_prices",
        sa.Column(
            "product_kind",
            sa.String(16),
            nullable=False,
            server_default="hair",
            comment="hair/accessory",
        ),
    )
    op.add_column(
        "ark_std_prices",
        sa.Column("accessory_name", sa.String(256), nullable=True, comment="Accessory display name"),
    )
    op.add_column(
        "ark_std_prices",
        sa.Column("accessory_model", sa.String(128), nullable=True, comment="Accessory model"),
    )
    op.add_column(
        "ark_std_prices",
        sa.Column("accessory_color", sa.String(128), nullable=True, comment="Accessory color"),
    )
    op.add_column(
        "ark_std_prices",
        sa.Column("product_id", sa.BigInteger(), nullable=True, comment="OKKI product ID"),
    )
    op.add_column(
        "ark_std_prices",
        sa.Column("sku_id", sa.BigInteger(), nullable=True, comment="OKKI SKU ID"),
    )
    op.alter_column(
        "ark_std_prices",
        "series_grade",
        existing_type=sa.String(128),
        existing_nullable=False,
        existing_comment="e.g. Super Double Drawn Genius",
        nullable=True,
    )
    op.alter_column(
        "ark_std_prices",
        "length",
        existing_type=sa.String(32),
        existing_nullable=False,
        existing_comment="normalized, inch mark stripped",
        nullable=True,
    )
    op.alter_column(
        "ark_std_prices",
        "weight_unit",
        existing_type=sa.String(32),
        existing_nullable=False,
        existing_comment="e.g. 20g",
        nullable=True,
    )
    op.alter_column(
        "ark_std_prices",
        "color_type",
        existing_type=sa.String(16),
        existing_nullable=False,
        existing_comment="计价颜色类型 solid/piano/ombre/balayage",
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_ark_std_accessory_sku",
        "ark_std_prices",
        ["product_kind", "product_id", "sku_id"],
    )

    op.add_column(
        "ark_invoice_items",
        sa.Column(
            "product_kind",
            sa.String(16),
            nullable=False,
            server_default="hair",
            comment="hair/accessory",
        ),
    )
    op.alter_column(
        "ark_invoice_items",
        "net_weight_grams",
        existing_type=sa.String(64),
        existing_nullable=False,
        existing_comment="Mapped from okki_products.unit",
        nullable=True,
    )
    op.alter_column(
        "ark_invoice_items",
        "length",
        existing_type=sa.String(128),
        existing_nullable=False,
        existing_comment="Mapped from okki_products.size",
        nullable=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    _assert_downgrade_safe(connection)

    op.drop_constraint("uq_ark_std_accessory_sku", "ark_std_prices", type_="unique")

    op.alter_column(
        "ark_invoice_items",
        "length",
        existing_type=sa.String(128),
        existing_nullable=True,
        existing_comment="Mapped from okki_products.size",
        nullable=False,
    )
    op.alter_column(
        "ark_invoice_items",
        "net_weight_grams",
        existing_type=sa.String(64),
        existing_nullable=True,
        existing_comment="Mapped from okki_products.unit",
        nullable=False,
    )
    op.drop_column("ark_invoice_items", "product_kind")

    op.alter_column(
        "ark_std_prices",
        "color_type",
        existing_type=sa.String(16),
        existing_nullable=True,
        existing_comment="计价颜色类型 solid/piano/ombre/balayage",
        nullable=False,
    )
    op.alter_column(
        "ark_std_prices",
        "weight_unit",
        existing_type=sa.String(32),
        existing_nullable=True,
        existing_comment="e.g. 20g",
        nullable=False,
    )
    op.alter_column(
        "ark_std_prices",
        "length",
        existing_type=sa.String(32),
        existing_nullable=True,
        existing_comment="normalized, inch mark stripped",
        nullable=False,
    )
    op.alter_column(
        "ark_std_prices",
        "series_grade",
        existing_type=sa.String(128),
        existing_nullable=True,
        existing_comment="e.g. Super Double Drawn Genius",
        nullable=False,
    )
    for column_name in (
        "sku_id",
        "product_id",
        "accessory_color",
        "accessory_model",
        "accessory_name",
        "product_kind",
    ):
        op.drop_column("ark_std_prices", column_name)
