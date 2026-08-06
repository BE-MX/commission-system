"""salary: 批次事件留痕表

Revision ID: 094_salary_period_event
Revises: 093_salary_bank_card_idx
Create Date: 2026-08-07

为什么不复用 `ark_salary_change_logs`：那张表是**调薪/调级/转正台账**，M3 计算引擎
要按 `employee_id + effective_date` 读它来做月中加权（陈佳乐 3775 案例）。把「批次
从 draft 变成 attendance_synced」这类事件混进去，会让引擎的查询多出一堆 employee_id
为空的噪音行；而且那张表的 employee_id 是 NOT NULL，批次级事件根本没有员工可填。

所以另起一张纯审计表：只写不读（除审计面板外），字段按「谁、什么时候、把哪个批次
从什么状态改成了什么状态、为什么」组织。解锁原因落在这里，是 A4 作废水印的依据。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "094_salary_period_event"
down_revision = "093_salary_bank_card_idx"
branch_labels = None
depends_on = None

_TABLE = "ark_salary_period_event"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("period_id", sa.BigInteger(), nullable=False, comment="批次 id"),
        sa.Column("event_type", sa.String(length=32), nullable=False,
                  comment="create/transition/unlock/workday_update/import/attendance_sync"),
        sa.Column("from_status", sa.String(length=24), nullable=True, comment="跃迁前状态"),
        sa.Column("to_status", sa.String(length=24), nullable=True, comment="跃迁后状态"),
        sa.Column("status_version", sa.Integer(), nullable=True, comment="跃迁后的乐观锁版本"),
        sa.Column("reason", sa.String(length=255), nullable=True, comment="原因（解锁必填）"),
        sa.Column("payload", sa.JSON(), nullable=True, comment="事件附加数据"),
        # ark_users.id 是 INT UNSIGNED，操作人列必须同型（红线：FK 类型完全一致）
        sa.Column("created_by",
                  sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                  nullable=True, comment="操作人 ark_users.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"), comment="发生时间"),
        sa.ForeignKeyConstraint(["period_id"], ["ark_salary_period.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 索引并进建表：MySQL 的 DDL 不可回滚，拆成 create_table + create_index 两条时
        # 若第二条失败（比如索引重名），表已建好而版本号没推进，重跑 upgrade 会在
        # create_table 上炸 "table exists"，得人工 drop。一条 DDL 就没这个中间态。
        sa.Index("idx_salary_period_event_pid", "period_id", "id"),
        comment="薪资-批次事件留痕",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    # drop_table 会连带删掉表上的索引，不需要单独 drop_index
    op.drop_table(_TABLE)
