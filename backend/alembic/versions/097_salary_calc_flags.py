"""salary: 特殊计薪标记 / 工龄钉值 / 应出天数手动钉值

Revision ID: 097_salary_calc_flags
Revises: 096_salary_dingtalk_uniq
Create Date: 2026-08-07

M3 计算引擎落地前的三个档案/考勤缺口，全部来自 3 月真值复算实证：

1. `special_calc`（特殊计薪）：姜妮妮、刘德明这类部门「-」人员不发卡里的
   全勤奖（3 月表两人 31/31 出勤但全勤奖都是 0，§9.5 开放问题的兜底：
   HR 在档案上确认标记，引擎据此跳过全勤/工龄规则）。
2. `seniority_override`（工龄手动钉值）：刘德明 3 月工龄 1000 与
   「200×周年数」规则值（200）对不上，属 HR 手工口径。钉值优先于规则，
   不钉（NULL）就按规则——姜妮妮钉 0、刘德明钉 1000 后 3 月可全量复算。
3. `due_days_manual`（应出天数手动钉值）：李晓雨 3 月应出 21.75 天，
   无法从任何规则复原（§8.3 第 10 条明确「按 3 月真值填入」）。
   同步/规则只写 due_days（阶段一基准），这列是 HR 的手动钉值，
   引擎优先采用；独立成列而不是复用 due_days，是因为同步每轮都会
   重写 due_days，钉值混在里面会被静默冲掉。

三列全部可空/带默认，纯新增，老代码+新 schema 天然兼容。
"""

from alembic import op
import sqlalchemy as sa

revision = "097_salary_calc_flags"
down_revision = "096_salary_dingtalk_uniq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_salary_employee_profile",
        sa.Column("special_calc", sa.SmallInteger(), nullable=False, server_default="0",
                  comment="1=特殊计薪：只算底薪±手动项，不发全勤/工龄（§9.5 HR 确认标记）"),
    )
    op.add_column(
        "ark_salary_employee_profile",
        sa.Column("seniority_override", sa.Numeric(12, 2), nullable=True,
                  comment="工龄工资手动钉值（特殊人员）；NULL=按规则计算"),
    )
    op.add_column(
        "ark_salary_attendance",
        sa.Column("due_days_manual", sa.Numeric(6, 2), nullable=True,
                  comment="应出天数手动钉值（如李晓雨 21.75）；NULL=按规则推导"),
    )
    # 引擎判定标记：负数实发/保底触发/月中加权等，异常面板记录级检查直接读
    op.add_column(
        "ark_salary_record",
        sa.Column("calc_flags", sa.JSON(), nullable=True,
                  comment="引擎判定标记（negative_net/guaranteed_topup/mid_month_weighted…）"),
    )


def downgrade() -> None:
    op.drop_column("ark_salary_record", "calc_flags")
    op.drop_column("ark_salary_attendance", "due_days_manual")
    op.drop_column("ark_salary_employee_profile", "seniority_override")
    op.drop_column("ark_salary_employee_profile", "special_calc")
