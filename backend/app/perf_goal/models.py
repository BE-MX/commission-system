"""Performance goal tables; order facts stay in the read-only OKKI mirror."""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

# The existing MySQL ark_users.id is unsigned, unlike the legacy ORM declaration.
USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

METRICS = ("gmv", "new_sign", "repeat_customers", "repeat_amount")
GRANULARITIES = ("year", "quarter", "month")


class PerfGoalPeriod(Base):
    __tablename__ = "ark_perf_goal_periods"
    __table_args__ = (
        UniqueConstraint("year", "name", name="uq_perf_goal_period_year_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False, index=True, comment="目标年度")
    name = Column(String(100), nullable=False, comment="批次名称，如 2026 年度目标")
    status = Column(String(16), nullable=False, default="draft", comment="draft/active/archived")
    version = Column(Integer, nullable=False, default=1, comment="目标内容版本，每次保存 +1")
    published_by = Column(Integer, nullable=True, comment="发布人方舟账号ID")
    published_at = Column(DateTime, nullable=True, comment="发布时间（北京时间）")
    created_by = Column(Integer, nullable=False, comment="创建人方舟账号ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class PerfGoal(Base):
    __tablename__ = "ark_perf_goals"
    # quarter/month 为空表示上一粒度；MySQL 唯一索引允许多个 NULL，重复由应用层 upsert 拦截。
    __table_args__ = (
        UniqueConstraint("period_id", "user_id", "metric", "granularity", "quarter", "month", name="uq_perf_goal_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("ark_perf_goal_periods.id"), nullable=False, index=True, comment="目标批次ID")
    user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, index=True, comment="方舟用户ID")
    metric = Column(String(24), nullable=False, comment="gmv/new_sign/repeat_customers/repeat_amount")
    granularity = Column(String(8), nullable=False, comment="year/quarter/month")
    quarter = Column(Integer, nullable=True, comment="季度（granularity=quarter 或 month 时必填）")
    month = Column(Integer, nullable=True, comment="月份（granularity=month 时必填）")
    target_value = Column(Numeric(16, 2), nullable=False, comment="目标值（USD 或个）")
    updated_by = Column(Integer, nullable=True, comment="最后修改人方舟账号ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class PerfGoalTeamOverride(Base):
    __tablename__ = "ark_perf_goal_team_overrides"
    __table_args__ = (
        UniqueConstraint("period_id", "department_id", "metric", "granularity", "quarter", "month", name="uq_perf_team_goal_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("ark_perf_goal_periods.id"), nullable=False, index=True, comment="目标批次ID")
    department_id = Column(Integer, nullable=False, comment="战队部门ID（复用 GMV 日报战队配置）")
    metric = Column(String(24), nullable=False, comment="gmv/new_sign/repeat_customers/repeat_amount")
    granularity = Column(String(8), nullable=False, comment="year/quarter/month")
    quarter = Column(Integer, nullable=True, comment="季度")
    month = Column(Integer, nullable=True, comment="月份")
    auto_value = Column(Numeric(16, 2), nullable=True, comment="成员目标汇总值（重算时刷新）")
    factor = Column(Numeric(8, 4), nullable=False, default=1, comment="战队加权系数，默认 1.0")
    override_value = Column(Numeric(16, 2), nullable=True, comment="手工微调值，非空时优先生效")
    effective_value = Column(Numeric(16, 2), nullable=True, comment="生效目标 = override ?? auto*factor")
    stale = Column(Boolean, nullable=False, default=False, comment="成员目标已变更待重算")
    updated_by = Column(Integer, nullable=True, comment="最后修改人方舟账号ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class PerfGoalAudit(Base):
    __tablename__ = "ark_perf_goal_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("ark_perf_goal_periods.id"), nullable=False, index=True, comment="目标批次ID")
    object_type = Column(String(24), nullable=False, comment="person_goal/team_goal")
    object_ref = Column(String(64), nullable=False, comment="对象引用（user_id 或 department_id）")
    object_label = Column(String(200), nullable=False, comment="对象展示名（姓名/战队名）")
    field = Column(String(64), nullable=False, comment="变更字段，如 gmv:year / factor / override_value")
    old_value = Column(String(200), nullable=True, comment="变更前值")
    new_value = Column(String(200), nullable=True, comment="变更后值")
    created_by = Column(Integer, nullable=False, comment="操作人方舟账号ID")
    operator_name = Column(String(64), nullable=False, comment="操作人姓名快照")
    reason = Column(String(500), nullable=False, default="", comment="修改原因")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class PerfSnapshot(Base):
    __tablename__ = "ark_perf_snapshots"
    __table_args__ = (
        UniqueConstraint("period_type", "year", "quarter", "month", "scope", "scope_id", name="uq_perf_snapshot_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_type = Column(String(8), nullable=False, comment="year/quarter/month")
    year = Column(Integer, nullable=False, comment="统计年度")
    quarter = Column(Integer, nullable=True, comment="季度")
    month = Column(Integer, nullable=True, comment="月份")
    as_of = Column(Date, nullable=False, comment="统计截止日期")
    scope = Column(String(16), nullable=False, comment="company/team/person")
    scope_id = Column(String(64), nullable=False, comment="company 固定 company，其余为 department_id/user_id")
    payload = Column(JSON, nullable=False, comment="冻结的四指标完成、pace、排名与预警")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="快照创建时间（北京时间）")


class PerfReport(Base):
    __tablename__ = "ark_perf_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot = Column(Date, nullable=False, index=True, comment="触发日（北京时间，每月 1/10/20 号）")
    scope = Column(String(16), nullable=False, comment="person/leader/company")
    user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, index=True, comment="接收人方舟用户ID")
    department_id = Column(Integer, nullable=True, comment="战队部门ID（leader 报告）")
    snapshot_id = Column(Integer, ForeignKey("ark_perf_snapshots.id"), nullable=True, comment="冻结快照ID")
    ai_preset = Column(String(64), nullable=False, default="perf_report_analyst", comment="AI 预设名快照")
    content_md = Column(Text, nullable=True, comment="报告 Markdown 正文")
    content_json = Column(JSON, nullable=True, comment="结构化内容 {summary, highlights, risks, suggestions}")
    status = Column(String(16), nullable=False, default="generated", comment="generated/failed")
    error = Column(String(500), nullable=True, comment="生成失败原因")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class PerfReportDelivery(Base):
    __tablename__ = "ark_perf_report_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("ark_perf_reports.id"), nullable=False, index=True, comment="报告ID")
    channel = Column(String(24), nullable=False, comment="worknotice/webhook_at/webhook_group")
    destination = Column(String(200), nullable=False, comment="钉钉 userId 或 @ 的姓名/手机号摘要")
    status = Column(String(16), nullable=False, default="pending", comment="pending/sending/sent/failed/uncertain")
    attempts = Column(Integer, nullable=False, default=0, comment="已尝试次数")
    last_error = Column(String(500), nullable=True, comment="最近失败原因（不含凭据）")
    sent_at = Column(DateTime, nullable=True, comment="送达时间（北京时间）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class PerfGoalConfig(Base):
    """单行 JSON 配置：指标开关、投递通道、AI preset、默认系数与人工订单裁定。"""

    __tablename__ = "ark_perf_goal_configs"

    key = Column(String(64), primary_key=True, comment="配置键，当前固定 main")
    payload = Column(JSON, nullable=False, comment="配置内容")
    updated_by = Column(Integer, nullable=True, comment="最后修改人方舟账号ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")
