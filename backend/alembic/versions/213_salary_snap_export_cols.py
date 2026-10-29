"""salary: 明细快照补入职日期与参保主体 + 批次导出计数（M4 导出）

Revision ID: 213_salary_snap_export_cols
Revises: 212_portal_customer_settings
Create Date: 2026-10-29

M4 导出的硬规则是「confirmed 批次只读 snap_* 快照，不回查活档案」。原快照列
（工号/姓名/部门/大部门/职务/银行卡密文/开户行）缺两样导出离不开的东西：
- 入职日期：汇总表「入职日期」与明细表「入职时间」两列都要；
- 参保主体：银行代发盘默认按参保主体拆两盘（§8.3 第 12 条）。
缺了它们，导出要么回查活档案（锁定后有人改档案就污染历史批次），要么留空。

存量回填：只回填已冻结（snapshot_at 非空）的行，取当前档案值。这批行是在本迁移之前
锁定的，锁定后若档案已改，回填值会与锁定当时不同——但不回填的话这些批次导出就缺列，
只能解锁重锁才能补上；两害取其轻，且上线前生产库尚无 M4 之前冻结的批次。
未冻结的行不回填：下次锁定时 confirm 会一起冻。

批次导出计数 export_seq：导出编号印在文件底部、写进留痕，必须唯一。在批次行上
UPDATE 自增拿行锁，比「数 export 事件 +1」可靠（后者两个并发请求会撞号）。

每列加列前先查是否已存在：MySQL DDL 不可回滚，半途失败后重跑不能撞 duplicate column。
"""

from alembic import op
import sqlalchemy as sa

revision = "213_salary_snap_export_cols"
down_revision = "212_portal_customer_settings"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    record_cols = _columns("ark_salary_record")
    if "snap_hire_date" not in record_cols:
        op.add_column(
            "ark_salary_record",
            sa.Column("snap_hire_date", sa.Date(), nullable=True, comment="快照-入职日期"),
        )
    if "snap_insurance_entity" not in record_cols:
        op.add_column(
            "ark_salary_record",
            sa.Column("snap_insurance_entity", sa.String(64), nullable=True,
                      comment="快照-参保主体（银行盘拆盘依据）"),
        )
    if "export_seq" not in _columns("ark_salary_period"):
        op.add_column(
            "ark_salary_period",
            sa.Column("export_seq", sa.Integer(), nullable=False, server_default="0",
                      comment="导出计数（每导出一次 +1，即导出编号）"),
        )
    # 回填幂等：只补仍为空的快照列，重跑不覆盖已冻结的值
    op.execute(
        """
        UPDATE ark_salary_record
        SET snap_hire_date = COALESCE(snap_hire_date, (
                SELECT p.hire_date FROM ark_salary_employee_profile p
                WHERE p.id = ark_salary_record.employee_id)),
            snap_insurance_entity = COALESCE(snap_insurance_entity, (
                SELECT p.insurance_entity FROM ark_salary_employee_profile p
                WHERE p.id = ark_salary_record.employee_id))
        WHERE snapshot_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("ark_salary_period", "export_seq")
    op.drop_column("ark_salary_record", "snap_insurance_entity")
    op.drop_column("ark_salary_record", "snap_hire_date")
