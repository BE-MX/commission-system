"""salary: 考勤行加 leave_source 归属列

Revision ID: 098_salary_leave_source
Revises: 097_salary_calc_flags
Create Date: 2026-08-07

请假自动拉取（getleavestatus + vacation/type/list + vacation/quota/list，
2026-08-07 钉钉权限开通）落地的前提：请假四列（事假/病假小时、年假天/余额）
原来是「只能人工录」，同步绝不写；现在同步能写了，就必须回答「这列归谁」。

`leave_source`：NULL=从未写过（同步可填）/ 'dingtalk'=同步在管（重同步可刷新）/
'manual'=人工改过（同步永远让路）。红线 1「人工录入的值永不被同步覆盖」
从「整列禁写」改成「按归属让路」，语义不变，只是更精确。

存量行全是人工录的，但列全为 NULL 的行等于没录过——升级时不回填，
让同步规则自己按「四列全空即可填」判断，不动存量数据。
"""

from alembic import op
import sqlalchemy as sa

revision = "098_salary_leave_source"
down_revision = "097_salary_calc_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_salary_attendance",
        sa.Column("leave_source", sa.String(16), nullable=True,
                  comment="请假四列归属：NULL=未写过/dingtalk=同步在管/manual=人工改过"),
    )


def downgrade() -> None:
    op.drop_column("ark_salary_attendance", "leave_source")
