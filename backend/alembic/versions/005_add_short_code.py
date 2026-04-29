"""add short_code to shipment_tracking

Revision ID: 005_add_short_code
Revises: 004_add_half_day_period
Create Date: 2026-04-28

"""
import secrets
import string
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_add_short_code"
down_revision: Union[str, None] = "004_add_half_day_period"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALPHABET = string.ascii_letters + string.digits


def _random_code(length=8):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def upgrade() -> None:
    op.add_column(
        "shipment_tracking",
        sa.Column("short_code", sa.String(8), comment="短链接编码"),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM shipment_tracking WHERE short_code IS NULL")).fetchall()
    used_codes: set[str] = set()
    for (row_id,) in rows:
        code = _random_code()
        while code in used_codes:
            code = _random_code()
        used_codes.add(code)
        conn.execute(
            sa.text("UPDATE shipment_tracking SET short_code = :code WHERE id = :id"),
            {"code": code, "id": row_id},
        )

    op.create_index("uk_short_code", "shipment_tracking", ["short_code"], unique=True)


def downgrade() -> None:
    op.drop_index("uk_short_code", table_name="shipment_tracking")
    op.drop_column("shipment_tracking", "short_code")
