"""Private assistant reports; no raw chat snapshot or task-center copies."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now


class WhatsAppAssistantRun(Base):
    __tablename__ = 'ark_whatsapp_assistant_runs'
    __table_args__ = (
        UniqueConstraint('requested_by', 'client_request_uid', name='uk_wa_assistant_request'),
        UniqueConstraint('account_uid', 'requested_by', 'active_slot', name='uk_wa_assistant_active'),
        Index('idx_wa_assistant_owner_account', 'requested_by', 'account_uid', 'created_at'),
        {'comment': '私有WhatsApp时间段分析与内部跟进清单'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='运行记录ID')
    run_uid = Column(String(64), nullable=False, unique=True, comment='分析运行唯一标识')
    account_uid = Column(String(80), ForeignKey('ark_whatsapp_accounts.account_uid'), nullable=False, comment='来源账号唯一标识')
    requested_by = Column(Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql'), ForeignKey('ark_users.id'), nullable=False, comment='请求人方舟用户ID')
    client_request_uid = Column(String(64), nullable=False, comment='客户端幂等请求标识')
    conversation_uid = Column(String(120), nullable=True, comment='单会话范围，空值表示整个账号')
    start_at = Column(DateTime, nullable=False, comment='包含的开始北京时间')
    end_at = Column(DateTime, nullable=False, comment='包含的结束北京时间')
    status = Column(String(20), nullable=False, default='pending', comment='运行状态及失效标记')
    active_slot = Column(Integer, nullable=True, default=1, comment='在途唯一占位，终态为空')
    session_generation = Column(Integer, nullable=False, comment='接纳时账号代次')
    consent_version = Column(Integer, nullable=False, comment='接纳时授权版本')
    message_count = Column(Integer, nullable=False, default=0, comment='范围内完整消息数')
    conversation_count = Column(Integer, nullable=False, default=0, comment='范围内聊天对象数')
    processed_conversations = Column(Integer, nullable=False, default=0, comment='已处理对象数')
    input_manifest = Column(JSON, nullable=False, comment='输入哈希和知识引用元数据，不复制聊天正文')
    result_json = Column(JSON, nullable=True, comment='当前有效逐对象摘要建议及清单')
    task_state = Column(JSON, nullable=False, default=dict, comment='报告内跟进项勾选状态')
    warnings_json = Column(JSON, nullable=False, default=list, comment='覆盖缺口及知识不足提示')
    error_code = Column(String(64), nullable=True, comment='失败或失效分类')
    error_message = Column(String(240), nullable=True, comment='不包含原始聊天的处理提示')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建北京时间')
    started_at = Column(DateTime, nullable=True, comment='开始北京时间')
    finished_at = Column(DateTime, nullable=True, comment='结束北京时间')
