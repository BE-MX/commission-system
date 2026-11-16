"""Record when a domestic customer was claimed from the public sea; align C-level follow frequency to 30 days.

The frequency change only rewrites a saved C级 value that is exactly 60 (the old default), so an
admin's deliberate custom value is kept. Downgrade restores 60 only where this migration set 30.

Revision ID: 263_customer_owner_claimed_at
Revises: 262_invoice_customer_sync_log
"""

import json

from alembic import op
import sqlalchemy as sa

from app.core.time import beijing_now

revision = "263_customer_owner_claimed_at"
down_revision = "262_invoice_customer_sync_log"
branch_labels = None
depends_on = None


_CONFIG = sa.table("ark_domestic_followup_config", sa.column("key", sa.String), sa.column("value", sa.JSON),
                   sa.column("updated_at", sa.DateTime))  # updated_at 非空且无库默认值，写入时必须带
_MARK = "_c_level_aligned_by_263"


def _frequencies(bind):
    row = bind.execute(sa.select(_CONFIG.c.value).where(_CONFIG.c.key == "frequency_days")).first()
    if row is None or row[0] is None:
        return None
    value = row[0]
    return json.loads(value) if isinstance(value, str) else dict(value)


def _save(bind, value):
    bind.execute(_CONFIG.update().where(_CONFIG.c.key == "frequency_days").values(value=value, updated_at=beijing_now()))


def upgrade():
    # MySQL DDL 隐式提交：先加列（失败则什么都没改），再改配置数据
    op.add_column(
        "ark_domestic_customers",
        sa.Column("owner_claimed_at", sa.DateTime(), nullable=True,
                  comment="最近一次从公海认领的北京时间；跟进钟从此重新计时，订单钟不受影响"),
    )
    bind = op.get_bind()
    frequencies = _frequencies(bind)
    if frequencies is not None and frequencies.get("C级") == 60:
        frequencies["C级"] = 30
        _save(bind, frequencies)
        bind.execute(_CONFIG.insert().values(key=_MARK, value=True, updated_at=beijing_now()))


def downgrade():
    op.drop_column("ark_domestic_customers", "owner_claimed_at")
    bind = op.get_bind()
    if bind.execute(sa.select(_CONFIG.c.key).where(_CONFIG.c.key == _MARK)).first() is None:
        return
    frequencies = _frequencies(bind)
    if frequencies is not None and frequencies.get("C级") == 30:
        frequencies["C级"] = 60
        _save(bind, frequencies)
    bind.execute(_CONFIG.delete().where(_CONFIG.c.key == _MARK))
