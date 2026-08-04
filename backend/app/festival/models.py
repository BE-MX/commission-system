"""采购节大屏事件流（摘要屏滚动记录 + 弹窗触发源）。

事件一经产生永久留档（幂等键去重），大屏重启/翻页不丢历史；
预览窗口的数据只做内存态候选，不落库。
"""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, String, Text, func

from app.core.database import Base


class FestivalEvent(Base):
    __tablename__ = "ark_festival_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(32), nullable=False, comment="事件类型 code（见 events_service.EVENT_META）")
    level = Column(String(4), nullable=False, comment="表现等级 L3=插播条 / L4=全屏弹窗")
    subject_type = Column(String(8), nullable=False, comment="主体类型 person/team/camp/company")
    subject_id = Column(String(64), nullable=False, comment="user_id 或 团队/阵营名")
    subject_name = Column(String(64), nullable=False, comment="展示名（人名/队名/阵营名）")
    amount = Column(Numeric(12, 2), nullable=True, comment="相关金额（大单/超级大单）")
    detail = Column(String(255), nullable=True, comment="补充说明文案")
    dedup_key = Column(String(128), nullable=False, unique=True, comment="幂等键：同一事实只记一次")
    dingtalk_sent_at = Column(DateTime, nullable=True, comment="钉钉群投递成功时间；空=待发送")
    dingtalk_claimed_at = Column(DateTime, nullable=True, comment="钉钉投递租约时间；防并发重复发送")
    dingtalk_next_retry_at = Column(DateTime, nullable=True, comment="钉钉失败后的下次重试时间")
    dingtalk_attempts = Column(Integer, nullable=False, default=0, server_default="0",
                               comment="钉钉投递尝试次数")
    dingtalk_last_error = Column(String(500), nullable=True, comment="最近一次钉钉投递错误")
    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment="事件产生时间")

    __table_args__ = (
        Index("ix_festival_events_created", "created_at"),
        Index("ix_ark_festival_events_event_type", "event_type"),  # 与 084 迁移同构
    )


class FestivalState(Base):
    """状态型事件快照。

    排名与累计值必须跨进程重启保存；只放事件检测所需的最小 JSON，不复制业务事实表。
    """

    __tablename__ = "ark_festival_states"

    state_key = Column(String(96), primary_key=True)
    value_json = Column(Text, nullable=False, comment="事件检测或投递状态 JSON")
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="状态最近更新时间",
    )
