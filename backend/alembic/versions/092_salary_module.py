"""salary_module

薪资计算模块 9 张表：档案/部门映射/职级表/规则参数/调薪台账/批次/考勤/社保导入/公积金导入/工资明细。
（档案 PII 走密文列 + HMAC 哈希列双写，唯一约束建在哈希列上。）

Revision ID: 092_salary_module
Revises: 091_design_image_library_prompt
Create Date: 2026-08-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# ark_users.id 在 MySQL 实际为 INT UNSIGNED；FK 列类型必须与目标列完全一致。
_UID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

_MONEY = sa.Numeric(precision=12, scale=2)
_HOURS = sa.Numeric(precision=8, scale=2)
_DAYS = sa.Numeric(precision=6, scale=2)

revision: str = "092_salary_module"
down_revision: Union[str, None] = "091_design_image_library_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    "ark_salary_record",
    "ark_salary_fund_import",
    "ark_salary_insurance_import",
    "ark_salary_attendance",
    "ark_salary_period",
    "ark_salary_change_logs",
    "ark_salary_rule_param",
    "ark_salary_grade_table",
    "ark_salary_dept_mapping",
    "ark_salary_employee_profile",
)


def upgrade() -> None:
    op.create_table(
        "ark_salary_employee_profile",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", _UID, nullable=True, comment="平台账号 ark_users.id（可空：无账号员工）"),
        sa.Column("emp_no", sa.String(length=32), nullable=False, comment="工号（唯一）"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="姓名"),
        sa.Column("id_card_cipher", sa.String(length=255), nullable=True, comment="身份证密文 AES-GCM"),
        sa.Column("id_card_hash", sa.String(length=64), nullable=True, comment="身份证 HMAC 摘要"),
        sa.Column("bank_card_cipher", sa.String(length=255), nullable=True, comment="银行卡密文 AES-GCM"),
        sa.Column("bank_card_hash", sa.String(length=64), nullable=True, comment="银行卡 HMAC 摘要"),
        sa.Column("bank_name", sa.String(length=64), nullable=True, comment="开户行"),
        sa.Column("hire_date", sa.Date(), nullable=True, comment="入职日期"),
        sa.Column("regular_date", sa.Date(), nullable=True, comment="转正日期"),
        sa.Column("leave_date", sa.Date(), nullable=True, comment="离职日期"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active", comment="active/left"),
        sa.Column("dept_detail", sa.String(length=64), nullable=True, comment="明细部门"),
        sa.Column(
            "dept_group_override",
            sa.String(length=64),
            nullable=True,
            comment="汇总大部门-按人覆盖（优先于 dept_mapping；管理岗挂靠场景）",
        ),
        sa.Column("position", sa.String(length=64), nullable=True, comment="职务（单一真相源）"),
        sa.Column("grade_scheme", sa.String(length=32), nullable=True, comment="职级赛道"),
        sa.Column("grade_code", sa.String(length=16), nullable=True, comment="职级码"),
        sa.Column("base_salary_override", _MONEY, nullable=True, comment="手动定薪"),
        sa.Column("probation_salary", _MONEY, nullable=True, comment="试用期底薪"),
        sa.Column("probation_note", sa.String(length=255), nullable=True, comment="试用期备注文案"),
        sa.Column("guaranteed_salary", _MONEY, nullable=True, comment="保底工资"),
        sa.Column("guaranteed_from", sa.Date(), nullable=True, comment="保底生效起"),
        sa.Column("guaranteed_to", sa.Date(), nullable=True, comment="保底生效止"),
        sa.Column("insurance_entity", sa.String(length=64), nullable=True, comment="参保主体"),
        sa.Column("payroll_included", sa.SmallInteger(), nullable=False, server_default=sa.text("1"), comment="1=发薪"),
        sa.Column("fund_included", sa.SmallInteger(), nullable=False, server_default=sa.text("1"), comment="1=缴公积金"),
        sa.Column("dingtalk_userid", sa.String(length=64), nullable=True, comment="钉钉 userid"),
        sa.Column("mobile", sa.String(length=32), nullable=True, comment="手机号"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["ark_users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("emp_no", name="uk_salary_profile_emp_no"),
        sa.UniqueConstraint("id_card_hash", name="uk_salary_profile_id_card"),
        sa.UniqueConstraint("bank_card_hash", name="uk_salary_profile_bank_card"),
        sa.Index("idx_salary_profile_status", "status"),
        sa.Index("idx_salary_profile_user", "user_id"),
        sa.Index("idx_salary_profile_dingtalk", "dingtalk_userid"),
        sa.Index("idx_salary_profile_name", "name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资档案-员工主数据（PII 密文+哈希双列）",
    )
    op.create_table(
        "ark_salary_dept_mapping",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dept_detail", sa.String(length=64), nullable=False, comment="明细部门名"),
        sa.Column("dept_group", sa.String(length=64), nullable=False, comment="汇总大部门"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="分组排序"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dept_detail", name="uk_salary_dept_mapping_detail"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-部门分组映射",
    )

    op.create_table(
        "ark_salary_grade_table",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scheme", sa.String(length=32), nullable=False, comment="赛道"),
        sa.Column("grade_code", sa.String(length=16), nullable=False, comment="职级码"),
        sa.Column("base_salary", _MONEY, nullable=True, comment="底薪"),
        sa.Column("perf_full", _MONEY, nullable=True, comment="满绩效金额"),
        sa.Column("std_salary", _MONEY, nullable=True, comment="标准工资（管理岗）"),
        sa.Column("perf_target_monthly", _MONEY, nullable=True, comment="月均业绩标准"),
        sa.Column("new_sign_min", sa.Integer(), nullable=True, comment="月均新签下限"),
        sa.Column("team_rate", sa.Numeric(precision=8, scale=4), nullable=True, comment="团队提成参考费率"),
        sa.Column("effective_from", sa.Date(), nullable=False, comment="生效起日"),
        sa.Column("effective_to", sa.Date(), nullable=True, comment="生效止日（NULL=当前版本）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scheme", "grade_code", "effective_from", name="uk_salary_grade_ver"),
        sa.Index("idx_salary_grade_lookup", "scheme", "grade_code", "effective_from"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-职级薪级表（版本化）",
    )

    op.create_table(
        "ark_salary_rule_param",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("param_key", sa.String(length=64), nullable=False, comment="参数键"),
        sa.Column("param_value", sa.String(length=255), nullable=False, comment="参数值（字符串存）"),
        sa.Column("value_type", sa.String(length=16), nullable=False, server_default="decimal", comment="值类型"),
        sa.Column("category", sa.String(length=32), nullable=True, comment="分组"),
        sa.Column("description", sa.String(length=255), nullable=True, comment="含义说明"),
        sa.Column("effective_from", sa.Date(), nullable=False, comment="生效起日"),
        sa.Column("effective_to", sa.Date(), nullable=True, comment="生效止日"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("param_key", "effective_from", name="uk_salary_param_ver"),
        sa.Index("idx_salary_param_lookup", "param_key", "effective_from"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-规则参数（版本化 KV）",
    )
    op.create_table(
        "ark_salary_change_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False, comment="员工档案 id"),
        sa.Column("change_type", sa.String(length=32), nullable=False, comment="raise/grade/regular"),
        sa.Column("effective_date", sa.Date(), nullable=False, comment="生效日"),
        sa.Column("old_value", sa.JSON(), nullable=True, comment="变更前快照"),
        sa.Column("new_value", sa.JSON(), nullable=True, comment="变更后快照"),
        sa.Column("reason", sa.String(length=255), nullable=True, comment="变更原因"),
        sa.Column("created_by", _UID, nullable=True, comment="操作人 ark_users.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["ark_salary_employee_profile.id"], ondelete="CASCADE",
        ),
        sa.Index("idx_salary_change_emp_date", "employee_id", "effective_date"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-调薪调级转正台账",
    )

    op.create_table(
        "ark_salary_period",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False, comment="批次月份 YYYY-MM"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft", comment="状态机"),
        sa.Column("status_version", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="批次级乐观锁"),
        sa.Column("workday_count", sa.Integer(), nullable=True, comment="当月应出勤工作日数"),
        sa.Column("natural_days", sa.Integer(), nullable=True, comment="当月自然日数"),
        sa.Column("param_snapshot", sa.JSON(), nullable=True, comment="冻结的规则参数快照"),
        sa.Column("calculated_at", sa.DateTime(), nullable=True, comment="最近重算时间"),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True, comment="锁定时间"),
        sa.Column("confirmed_by", _UID, nullable=True, comment="锁定人 ark_users.id"),
        sa.Column("unlocked_at", sa.DateTime(), nullable=True, comment="最近解锁时间"),
        sa.Column("unlock_reason", sa.String(length=255), nullable=True, comment="解锁原因"),
        sa.Column("remark", sa.Text(), nullable=True, comment="批次备注"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month", name="uk_salary_period_ym"),
        sa.Index("idx_salary_period_status", "status"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-月度批次",
    )

    op.create_table(
        "ark_salary_attendance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.BigInteger(), nullable=False, comment="批次 id"),
        sa.Column("employee_id", sa.BigInteger(), nullable=False, comment="员工档案 id"),
        sa.Column("due_days", _DAYS, nullable=True, comment="应出勤天数"),
        sa.Column("actual_days", _DAYS, nullable=True, comment="实出勤天数"),
        sa.Column("personal_leave_hours", _HOURS, nullable=True, comment="事假小时"),
        sa.Column("sick_leave_hours", _HOURS, nullable=True, comment="病假小时"),
        sa.Column("annual_leave_days", _DAYS, nullable=True, comment="年假天数"),
        sa.Column("annual_leave_remain", _DAYS, nullable=True, comment="年假剩余额度"),
        sa.Column("late_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="迟到次数"),
        sa.Column("early_leave_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="早退次数"),
        sa.Column("miss_punch_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="漏打卡次数"),
        sa.Column("absent_count", _DAYS, nullable=False, server_default=sa.text("0"), comment="旷工天数"),
        sa.Column("full_attendance", sa.SmallInteger(), nullable=False, server_default=sa.text("0"), comment="1=全勤"),
        sa.Column("sync_source", sa.String(length=16), nullable=False, server_default="manual", comment="来源"),
        sa.Column("raw_payload", sa.JSON(), nullable=True, comment="钉钉原始返回"),
        sa.Column("synced_at", sa.DateTime(), nullable=True, comment="同步时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["period_id"], ["ark_salary_period.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["ark_salary_employee_profile.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("period_id", "employee_id", name="uk_salary_attendance_pe"),
        sa.Index("idx_salary_attendance_period", "period_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-考勤汇总",
    )
    op.create_table(
        "ark_salary_insurance_import",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.BigInteger(), nullable=False, comment="批次 id"),
        sa.Column("employee_id", sa.BigInteger(), nullable=True, comment="匹配到的档案 id"),
        sa.Column("entity", sa.String(length=64), nullable=True, comment="参保主体"),
        sa.Column("name", sa.String(length=64), nullable=True, comment="源表姓名"),
        sa.Column("id_card_hash", sa.String(length=64), nullable=True, comment="身份证 HMAC 摘要（匹配键）"),
        sa.Column("id_card_cipher", sa.String(length=255), nullable=True, comment="身份证密文（留档）"),
        sa.Column("base_amount", _MONEY, nullable=True, comment="缴费基数"),
        sa.Column("personal_total", _MONEY, nullable=True, comment="个人合计"),
        sa.Column("company_total", _MONEY, nullable=True, comment="单位合计"),
        sa.Column("detail_json", sa.JSON(), nullable=True, comment="各险种明细"),
        sa.Column("match_status", sa.String(length=16), nullable=False, server_default="matched", comment="匹配状态"),
        sa.Column("dept_text", sa.String(length=64), nullable=True, comment="源表部门文本"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["period_id"], ["ark_salary_period.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["ark_salary_employee_profile.id"], ondelete="SET NULL",
        ),
        sa.Index("idx_salary_ins_period", "period_id"),
        sa.Index("idx_salary_ins_hash", "period_id", "id_card_hash"),
        sa.Index("idx_salary_ins_match", "period_id", "match_status"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-社保导入行",
    )

    op.create_table(
        "ark_salary_fund_import",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.BigInteger(), nullable=False, comment="批次 id"),
        sa.Column("employee_id", sa.BigInteger(), nullable=True, comment="匹配到的档案 id"),
        sa.Column("name", sa.String(length=64), nullable=True, comment="源表姓名"),
        sa.Column("id_card_hash", sa.String(length=64), nullable=True, comment="身份证 HMAC 摘要（匹配键）"),
        sa.Column("id_card_cipher", sa.String(length=255), nullable=True, comment="身份证密文（留档）"),
        sa.Column("base_amount", _MONEY, nullable=True, comment="缴存基数"),
        sa.Column("personal_amount", _MONEY, nullable=True, comment="个人缴存额"),
        sa.Column("company_amount", _MONEY, nullable=True, comment="单位缴存额"),
        sa.Column("match_status", sa.String(length=16), nullable=False, server_default="matched", comment="匹配状态"),
        sa.Column("dept_text", sa.String(length=64), nullable=True, comment="源表部门文本"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["period_id"], ["ark_salary_period.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["ark_salary_employee_profile.id"], ondelete="SET NULL",
        ),
        sa.Index("idx_salary_fund_period", "period_id"),
        sa.Index("idx_salary_fund_hash", "period_id", "id_card_hash"),
        sa.Index("idx_salary_fund_match", "period_id", "match_status"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-公积金导入行",
    )
    op.create_table(
        "ark_salary_record",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.BigInteger(), nullable=False, comment="批次 id"),
        sa.Column("employee_id", sa.BigInteger(), nullable=False, comment="员工档案 id"),
        sa.Column("seq_no", sa.Integer(), nullable=True, comment="明细表序号"),
        sa.Column("due_days", _DAYS, nullable=True, comment="应出勤"),
        sa.Column("actual_days", _DAYS, nullable=True, comment="实出勤"),
        # 引擎列（单字段 final）。减项列为负数，与 HR 源表口径一致
        sa.Column("base_salary", _MONEY, nullable=True, comment="底薪"),
        sa.Column("seniority_pay", _MONEY, nullable=True, comment="工龄工资"),
        sa.Column("attendance_bonus", _MONEY, nullable=True, comment="全勤奖"),
        sa.Column("social_insurance", _MONEY, nullable=True, comment="社保个人（负数）"),
        sa.Column("housing_fund", _MONEY, nullable=True, comment="公积金个人（负数）"),
        sa.Column("absence_deduction", _MONEY, nullable=True, comment="缺勤扣款（负数）"),
        sa.Column("add_subtotal", _MONEY, nullable=True, comment="增项小计"),
        sa.Column("deduct_subtotal", _MONEY, nullable=True, comment="减项小计（负数）"),
        sa.Column("net_salary", _MONEY, nullable=True, comment="应发/实发"),
        # 三元组列 auto / manual / final
        sa.Column("bonus_auto", _MONEY, nullable=True, comment="奖励-引擎值"),
        sa.Column("bonus_manual", _MONEY, nullable=True, comment="奖励-人工覆盖"),
        sa.Column("bonus_final", _MONEY, nullable=True, comment="奖励-生效值"),
        sa.Column("performance_auto", _MONEY, nullable=True, comment="绩效-引擎值"),
        sa.Column("performance_manual", _MONEY, nullable=True, comment="绩效-人工覆盖"),
        sa.Column("performance_final", _MONEY, nullable=True, comment="绩效-生效值"),
        sa.Column("other_auto", _MONEY, nullable=True, comment="其他款-引擎值"),
        sa.Column("other_manual", _MONEY, nullable=True, comment="其他款-人工覆盖"),
        sa.Column("other_final", _MONEY, nullable=True, comment="其他款-生效值"),
        sa.Column("subsidy_auto", _MONEY, nullable=True, comment="补贴-引擎值"),
        sa.Column("subsidy_manual", _MONEY, nullable=True, comment="补贴-人工覆盖"),
        sa.Column("subsidy_final", _MONEY, nullable=True, comment="补贴-生效值"),
        # 纯手动列
        sa.Column("income_tax_amount", _MONEY, nullable=True, comment="个税（纯手动）"),
        sa.Column("net_after_tax", _MONEY, nullable=True, comment="税后实发"),
        # 档案快照（confirmed 时冻结）
        sa.Column("snap_emp_no", sa.String(length=32), nullable=True, comment="快照-工号"),
        sa.Column("snap_name", sa.String(length=64), nullable=True, comment="快照-姓名"),
        sa.Column("snap_dept_detail", sa.String(length=64), nullable=True, comment="快照-明细部门"),
        sa.Column("snap_dept_group", sa.String(length=64), nullable=True, comment="快照-汇总大部门"),
        sa.Column("snap_position", sa.String(length=64), nullable=True, comment="快照-职务"),
        sa.Column("snap_bank_card_cipher", sa.String(length=255), nullable=True, comment="快照-银行卡密文"),
        sa.Column("snap_bank_name", sa.String(length=64), nullable=True, comment="快照-开户行"),
        sa.Column("snapshot_at", sa.DateTime(), nullable=True, comment="快照冻结时间"),
        sa.Column("remark_summary", sa.String(length=255), nullable=True, comment="汇总表备注（自动）"),
        sa.Column("leave_remark", sa.String(length=255), nullable=True, comment="请假时间文案（自动）"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="行级乐观锁"),
        sa.Column("calculated_at", sa.DateTime(), nullable=True, comment="最近计算时间"),
        sa.Column("modified_by", _UID, nullable=True, comment="最近人工修改人"),
        sa.Column("modify_reason", sa.String(length=255), nullable=True, comment="修改原因"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["period_id"], ["ark_salary_period.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["ark_salary_employee_profile.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("period_id", "employee_id", name="uk_salary_record_pe"),
        sa.Index("idx_salary_record_period", "period_id"),
        sa.Index("idx_salary_record_emp", "employee_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="薪资-工资明细行（含档案快照）",
    )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_table(table)
