"""salary: 批次工作日数来源标记

Revision ID: 095_salary_workday_source
Revises: 094_salary_period_event
Create Date: 2026-08-07

`derive_workday_count` 只按周一~周五推，不含法定节假日与调休，所以对 2026 年的
1/2/4/5/6/9/10 月必然偏大（没扣春节国庆，也没加回调休上班的周末）。这个「不准，
待复核」的判断原先只落在创建事件的 payload 里，批次页要拿到得去翻 /events 解 JSON——
实际上就是发不出去，于是 2 月批次的 20 天会静默成为应出基准，而它是所有月中入离职
人员缺勤扣款的分母。

所以把来源标记持久化到批次行，前端据此渲染「待复核」角标。

单独开一版而不是改 094：094 已在共库执行过（开发/生产同一套 RDS）。
"""

from alembic import op
import sqlalchemy as sa

revision = "095_salary_workday_source"
down_revision = "094_salary_period_event"
branch_labels = None
depends_on = None

_TABLE = "ark_salary_period"


def upgrade() -> None:
    # nullable：老代码 + 新 schema 的过渡期里，已存在的批次行没有这个值，
    # 序列化时会得到 None，前端按「未标记」处理，不会误报待复核。
    op.add_column(
        _TABLE,
        sa.Column("workday_source", sa.String(length=16), nullable=True,
                  comment="工作日数来源 weekday_auto/needs_review/manual"),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "workday_source")
