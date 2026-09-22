"""Battle reports own goals and roster snapshots; source orders remain read-only."""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

# The existing MySQL ark_users.id is unsigned, unlike the legacy ORM declaration.
USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class BattleReport(Base):
    __tablename__ = "ark_battle_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="战报名称")
    start_date = Column(Date, nullable=False, comment="开始日期（北京时间）")
    end_date = Column(Date, nullable=False, comment="结束日期（含当日）")
    target_deadline = Column(DateTime, nullable=False, comment="目标填报截止时间（北京时间）")
    status = Column(String(16), nullable=False, default="draft", comment="草稿、已发布、归档状态")
    visibility = Column(String(16), nullable=False, default="activity", comment="汇总可见范围")
    currency = Column(String(3), nullable=False, default="USD", comment="统计币种")
    basis_version = Column(String(32), nullable=False, default="order_gmv_roster_v1", comment="统计口径版本")
    version = Column(Integer, nullable=False, default=1, comment="并发修改版本")
    work_dates = Column(JSON, nullable=True, comment="北京时间计时工作日，ISO 日期数组")
    poster_push_enabled = Column(Boolean, nullable=False, default=False, comment="13:00/17:00 群海报开关")
    created_by = Column(Integer, nullable=False, comment="创建人方舟账号ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class BattleReportMember(Base):
    __tablename__ = "ark_battle_report_members"
    __table_args__ = (
        UniqueConstraint("report_id", "okki_user_id", name="uq_battle_report_okki"),
        UniqueConstraint("report_id", "ark_user_id", name="uq_battle_report_ark"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("ark_battle_reports.id"), nullable=False, index=True, comment="战报ID")
    ark_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="方舟用户ID")
    okki_user_id = Column(String(100), nullable=False, comment="订单负责人OKKI稳定ID快照")
    user_name = Column(String(100), nullable=False, comment="姓名快照")
    team = Column(String(100), nullable=False, comment="活动小组快照")
    is_captain = Column(Boolean, nullable=False, default=False, comment="是否组长，可查看本组订单")
    target_usd = Column(Numeric(16, 2), nullable=True, comment="周期美元目标，空值表示未填报")
    version = Column(Integer, nullable=False, default=1, comment="并发修改版本")
    target_updated_at = Column(DateTime, nullable=True, comment="目标更新时间（北京时间）")


class BattleReportAudit(Base):
    __tablename__ = "ark_battle_report_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("ark_battle_reports.id"), nullable=False, index=True, comment="战报ID")
    actor_id = Column(Integer, nullable=False, comment="操作人方舟账号ID")
    action = Column(String(32), nullable=False, comment="审计动作")
    before = Column(JSON, nullable=True, comment="修改前内容")
    after = Column(JSON, nullable=True, comment="修改后内容")
    reason = Column(String(500), nullable=False, default="", comment="修改原因")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class BattleReportDelivery(Base):
    __tablename__ = "ark_battle_report_deliveries"
    __table_args__ = (UniqueConstraint("report_id", "report_date", "slot", name="uq_battle_delivery_slot"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("ark_battle_reports.id"), nullable=False, index=True, comment="战报ID")
    report_date = Column(Date, nullable=False, comment="投递日期（北京时间）")
    slot = Column(String(5), nullable=False, comment="投递时段：13:00 或 17:00")
    snapshot = Column(JSON, nullable=False, comment="两张海报共同的不可变业务快照")
    destination_hash = Column(String(64), nullable=False, comment="Webhook 指纹，不存凭据")
    deliveries = Column(JSON, nullable=False, comment="两张图独立状态；不确定送达不自动重试")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="快照创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="状态更新时间（北京时间）")
