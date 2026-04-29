"""钉钉集成数据模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean

from app.core.database import Base


class DingTalkCallbackLog(Base):
    """钉钉回调日志（幂等处理基础）"""

    __tablename__ = "dingtalk_callback_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, comment="事件类型")
    raw_data = Column(Text, nullable=False, comment="原始回调数据")
    processed = Column(Boolean, nullable=False, default=False, comment="是否已处理")
    process_result = Column(String(255), nullable=True, comment="处理结果")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="接收时间")
    processed_at = Column(DateTime, nullable=True, comment="处理时间")


class DingTalkMessageLog(Base):
    """钉钉消息发送日志"""

    __tablename__ = "dingtalk_message_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_type = Column(String(32), nullable=False, comment="消息类型: markdown/action_card/text")
    title = Column(String(128), nullable=False, comment="消息标题")
    content = Column(Text, nullable=False, comment="消息内容")
    at_mobiles = Column(String(255), nullable=True, comment="@的手机号(逗号分隔)")
    send_status = Column(String(16), nullable=False, default="pending", comment="发送状态: pending/success/failed")
    error_msg = Column(Text, nullable=True, comment="错误信息")
    related_type = Column(String(32), nullable=True, comment="关联业务类型")
    related_id = Column(String(64), nullable=True, comment="关联业务ID")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    sent_at = Column(DateTime, nullable=True, comment="发送时间")
