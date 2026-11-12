"""AI 洞见快照与条目；证据只存跟进记录 ID，不存原文。"""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DomesticFollowupInsightSnapshot(Base):
    __tablename__ = "ark_dom_followup_insight_snapshots"
    __table_args__ = (
        Index("ix_dom_fu_insight_snapshot_read", "scope", "user_id", "status", "id"),
        Index("ix_dom_fu_insight_refresh_quota", "requested_by_user_id", "request_day", "trigger"),
        {"comment": "客户跟进 AI 洞见快照；失败时保留上一份完成快照"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    scope = Column(String(16), nullable=False, comment="personal/company")
    user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="个人层目标业务员")
    status = Column(String(12), nullable=False, default="running", comment="queued/running/done/failed")
    trigger = Column(String(20), nullable=False, comment="daily/weekly/manual/manual_linked/test")
    period_start = Column(Date, nullable=False, comment="分析开始日期")
    period_end = Column(Date, nullable=False, comment="分析结束日期")
    record_count = Column(Integer, nullable=False, default=0, comment="分析记录数")
    payload = Column(JSON, nullable=True, comment="确定性摘要与空分类，不含证据原文")
    error = Column(String(255), nullable=True, comment="失败类型，不存提示词或原文")
    run_token = Column(String(36), nullable=True, comment="执行认领标识；阻止过期执行器覆盖结果")
    requested_by_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="手动生成请求人")
    request_day = Column(Date, nullable=True, comment="手动刷新的北京日期配额")
    generated_at = Column(DateTime, nullable=True, comment="完成时间（北京时间）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class DomesticFollowupInsight(Base):
    __tablename__ = "ark_dom_followup_insights"
    __table_args__ = (
        Index("ix_dom_fu_insight_snapshot_category", "snapshot_id", "category"),
        Index("ix_dom_fu_insight_customer", "customer_id"),
        {"comment": "客户跟进 AI 建议；数字已填槽，证据仅保存记录 ID"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    snapshot_id = Column(BigInteger, ForeignKey("ark_dom_followup_insight_snapshots.id"), nullable=False, comment="所属快照")
    category = Column(String(20), nullable=False, comment="deal/cold/rhythm/method/common/single/practice/frequency")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=True, comment="建议关联客户")
    theme_key = Column(String(80), nullable=True, comment="公司层确定性预聚合主题键")
    title = Column(String(500), nullable=False, comment="建议标题")
    body = Column(Text, nullable=False, comment="建议正文")
    suggested_action = Column(Text, nullable=True, comment="建议动作")
    suggested_date = Column(Date, nullable=True, comment="建议跟进日期")
    signals = Column(JSON, nullable=True, comment="证据信号")
    evidence_followup_ids = Column(JSON, nullable=False, comment="1~5 个原始跟进记录 ID")
    evidence_versions = Column(JSON, nullable=False, default=dict, comment="生成时的证据版本，修改后不继续显示旧判断")
    public_summary = Column(JSON, nullable=True, comment="仅聚合输入生成的公司建议，不接触客户原文")
    sample_customer_ids = Column(JSON, nullable=True, comment="实际成交分析样本ID，仅后端用于复核")
    numeric_values = Column(JSON, nullable=True, comment="后端填槽所用数字")
    sample_size = Column(Integer, nullable=False, default=0, comment="实际样本客户数")
    source_insight_id = Column(BigInteger, ForeignKey("ark_dom_followup_insights.id"), nullable=True, comment="每日沿用评语的原始建议ID")
    feedbacks = Column(JSON, nullable=False, default=dict, comment="按反馈人保存有用或不准及北京时间")
    task_id = Column(BigInteger, ForeignKey("ark_domestic_followup_tasks.id"), nullable=True, unique=True, comment="已生成的待办")
    adopted_by_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="采纳人")
    adopted_at = Column(DateTime, nullable=True, comment="采纳时间（北京时间）")
    adoption_note = Column(String(500), nullable=True, comment="采纳说明")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
