"""domestic: 报工流水加幂等键 request_id

车间弱网下"服务端已提交、响应丢在路上"是常态，工人按提示再点一次确认
就会重复累加数量（拆批场景尤其容易——还有余量所以校验放行）。
客户端每次确认生成一个 request_id，重复提交返回首次结果而不是再记一笔。

Revision ID: 082_domestic_report_idem
Revises: 081_domestic_orders
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "082_domestic_report_idem"
down_revision = "081_domestic_orders"
branch_labels = None
depends_on = None

TABLE = "ark_domestic_report_logs"
COLUMN = "request_id"
INDEX = "uk_dom_log_request_id"


def _columns() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    if COLUMN in _columns():
        return
    op.add_column(
        TABLE,
        sa.Column("request_id", sa.String(64), nullable=True,
                  comment="客户端幂等键：弱网重试同一个 id 不重复累加数量"),
    )
    # NULL 不参与唯一性判定，历史行与不带幂等键的调用都不受影响
    op.create_unique_constraint(INDEX, TABLE, [COLUMN])


def downgrade():
    if COLUMN not in _columns():
        return
    op.drop_constraint(INDEX, TABLE, type_="unique")
    op.drop_column(TABLE, COLUMN)
