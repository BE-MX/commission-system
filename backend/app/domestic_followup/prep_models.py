from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, SmallInteger, String
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DomesticFollowupPrep(Base):
    __tablename__ = "ark_dom_followup_preps"
    __table_args__ = (
        Index("ix_dom_fu_prep_customer", "customer_id", "status", "created_at"),
        Index("ix_dom_fu_prep_author", "author_user_id", "status"),
        {"comment": "内贸跟进准备卡：背调、策略与一次性使用绑定"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=False, comment="客户ID")
    author_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="准备卡作者")
    template_code = Column(String(8), nullable=False, comment="场景模板代码")
    template_version = Column(Integer, nullable=False, comment="场景模板版本")
    goal = Column(String(200), nullable=False, comment="本次唯一目标")
    contact_reason = Column(String(300), nullable=True, comment="联系依据说明")
    reason_source = Column(String(16), nullable=True, comment="依据类型：上次记录/客户询问/公开动态/其他")
    reason_date = Column(Date, nullable=True, comment="依据观察日期")
    known_facts = Column(JSON, nullable=False, default=list, comment="已知事实及来源，最多8条")
    to_confirm = Column(JSON, nullable=False, default=list, comment="待确认事项，最多5条")
    answers = Column(JSON, nullable=False, default=dict, comment="准备字段答案")
    status = Column(String(10), nullable=False, default="draft", comment="draft/ready/used/abandoned/expired")
    strategy_status = Column(String(10), nullable=False, default="none", comment="none/running/done/failed")
    strategy = Column(JSON, nullable=True, comment="归一化策略、证据版本与反馈")
    strategy_count = Column(SmallInteger, nullable=False, default=0, comment="策略生成次数，最多5次")
    strategy_log_id = Column(BigInteger, nullable=True, comment="AI 调用日志ID")
    strategy_error = Column(String(255), nullable=True, comment="策略失败异常类型")
    source_task_id = Column(BigInteger, nullable=True, comment="来源待办ID")
    followup_id = Column(BigInteger, nullable=True, unique=True, comment="唯一绑定的已确认跟进ID")
    request_id = Column(String(64), nullable=False, unique=True, comment="客户端幂等键")
    version = Column(Integer, nullable=False, default=1, comment="乐观锁版本")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")
