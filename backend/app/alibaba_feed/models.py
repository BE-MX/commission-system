"""Private receipt and immutable snapshot storage; no customer projections."""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Computed, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMBLOB, VARCHAR, INTEGER

from app.core.database import Base
from app.core.time import beijing_now

def exact_string(length):
    return String(length).with_variant(VARCHAR(length, collation="utf8mb4_0900_bin"), "mysql")


TIMESTAMP = DateTime().with_variant(DATETIME(fsp=6), "mysql")


ID = BigInteger().with_variant(Integer(), "sqlite")


class AlibabaFeedSource(Base):
    __tablename__ = "ark_alibaba_feed_sources"
    id = Column(ID, primary_key=True, autoincrement=True, comment='主键')
    source_account_uid = Column(exact_string(64), nullable=False, unique=True, comment='来源账号标识')
    integration_app_id = Column(ID, ForeignKey("ark_integration_apps.id"), nullable=False, unique=True, comment='绑定接入应用')
    name = Column(String(100), nullable=False, comment='来源名称')
    ingest_enabled = Column(Boolean, nullable=False, default=False, server_default="0", comment='接收开关')
    consent_state = Column(String(24), nullable=False, default="pending", server_default="pending", comment='来源授权状态')
    private_feed_enabled = Column(Boolean, nullable=False, default=False, server_default="0", comment='私海接入开关')
    collection_generation = Column(Integer, nullable=False, default=1, server_default="1", comment='采集代次')
    crm_shared = Column(Boolean, nullable=False, default=False, server_default="0", comment='客户资料共享许可')
    ai_egress_allowed = Column(Boolean, nullable=False, default=False, server_default="0", comment='模型外发许可')
    owner_aliases = Column(JSON, nullable=True, default=dict, comment="经人工确认的精确负责人显示名映射")
    mapping_version = Column(Integer, nullable=False, default=1, server_default="1", comment="负责人映射版本")
    mapping_updated_by = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=True, comment="映射审核人")
    verified_capabilities = Column(JSON, nullable=True, default=dict, comment="已核验来源能力及依据")
    capability_version = Column(Integer, nullable=False, default=1, server_default="1", comment="能力核验版本")
    legacy_identity_blocked = Column(Boolean, nullable=False, default=False, server_default="0", comment="未能确定撤回影响的旧身份阻断")
    consent_version = Column(Integer, nullable=False, default=1, server_default="1", comment='授权版本')
    version = Column(Integer, nullable=False, default=1, server_default="1", comment='管理并发版本')
    created_at = Column(TIMESTAMP, nullable=False, default=beijing_now, comment='创建时间（北京时间）')
    updated_at = Column(TIMESTAMP, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时间）')


class AlibabaFeedPilot(Base):
    __tablename__ = "ark_alibaba_feed_pilot"
    __table_args__ = (CheckConstraint("id = 1", name="ck_alibaba_feed_pilot_singleton"),)

    id = Column(Integer, primary_key=True, autoincrement=False, comment="试点单例主键")
    source_id = Column(ID, ForeignKey("ark_alibaba_feed_sources.id"), nullable=True, comment="试点店铺来源")
    user_id = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"),
                     ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="试点方舟业务员")
    enabled = Column(Boolean, nullable=False, default=False, server_default="0", comment="管理员手动启用状态")
    version = Column(Integer, nullable=False, default=1, server_default="1", comment="试点配置并发版本")


class AlibabaFeedBatch(Base):
    __tablename__ = "ark_alibaba_feed_batches"
    id = Column(String(36), primary_key=True, comment='主键')
    source_account_uid = Column(exact_string(64), ForeignKey("ark_alibaba_feed_sources.source_account_uid"), nullable=False, comment='来源账号标识')
    run_id = Column(exact_string(96), nullable=False, comment='来源运行幂等标识')
    collection_generation = Column(Integer, nullable=False, comment='采集代次')
    body_hash = Column(String(64), nullable=False, comment='语义规范化摘要')
    raw_hash = Column(String(64), nullable=False, comment='原始字节摘要')
    raw_body = Column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=False, comment='私有原始包')
    max_message_bytes = Column(Integer, nullable=False, default=65536, server_default="65536", comment='接收时单消息字节限额')
    body_bytes = Column(Integer, nullable=False, comment='原始包字节数')
    source_status = Column(String(16), nullable=False, comment='采集状态')
    status = Column(String(32), nullable=False, default="queued", comment='规范化处理状态')
    observed_at = Column(TIMESTAMP, nullable=False, comment='来源观察时刻（北京时间）')
    received_records = Column(Integer, nullable=False, comment='接收记录数')
    received_messages = Column(Integer, nullable=False, comment='接收消息数')
    issues = Column(JSON, nullable=False, default=list, comment='安全质量代码')
    lease_token = Column(String(36), nullable=True, comment='当前工作租约令牌')
    lease_expires_at = Column(TIMESTAMP, nullable=True, comment='租约到期时间（北京时间）')
    attempts = Column(Integer, nullable=False, default=0, comment='领取尝试次数')
    created_at = Column(TIMESTAMP, nullable=False, default=beijing_now, comment='创建时间（北京时间）')
    finished_at = Column(TIMESTAMP, nullable=True, comment='完成时间（北京时间）')
    __table_args__ = (
        UniqueConstraint("source_account_uid", "run_id", name="uq_af_batch_source_run"),
        Index("ix_af_batch_queue", "status", "lease_expires_at"),
        Index("ix_af_batch_source_created", "source_account_uid", "created_at"),
    )


class AlibabaFeedItem(Base):
    __tablename__ = "ark_alibaba_feed_items"
    id = Column(ID, primary_key=True, autoincrement=True, comment='主键')
    batch_id = Column(String(36), ForeignKey("ark_alibaba_feed_batches.id"), nullable=False, comment='接收批次')
    record_index = Column(Integer, nullable=False, comment='包内记录序号')
    source_account_uid = Column(exact_string(64), nullable=False, comment='来源账号标识')
    collection_generation = Column(Integer, nullable=False, comment='采集代次')
    record_type = Column(String(16), nullable=False, comment='来源记录类型')
    inquiry_id = Column(exact_string(128), nullable=False, comment='来源逻辑记录标识')
    observed_at = Column(TIMESTAMP, nullable=False, comment='来源观察时刻（北京时间）')
    schema_version = Column(String(24), nullable=False, default="ark_alibaba_feed_v1", server_default="ark_alibaba_feed_v1", comment="输入协议版本")
    conversation_id = Column(exact_string(128), nullable=True, comment="稳定会话身份")
    snapshot_revision = Column(BigInteger, nullable=True, comment="记录修订版本")
    conversation_revision = Column(BigInteger, nullable=True, comment="会话覆盖版本")
    coverage = Column(JSON, nullable=True, comment="会话覆盖声明")
    snapshot_hash = Column(String(64), nullable=False, comment='快照语义摘要')
    snapshot = Column(JSON, nullable=False, comment='私有记录快照')
    outcome = Column(String(24), nullable=False, comment='本次处理结果')
    is_current = Column(Boolean, nullable=False, default=False, comment='是否当前合格快照')
    window_result = Column(String(24), nullable=False, comment='独立窗口判定')
    issues = Column(JSON, nullable=False, default=list, comment='安全质量代码')
    created_at = Column(TIMESTAMP, nullable=False, default=beijing_now, comment='创建时间（北京时间）')
    __table_args__ = (
        UniqueConstraint("batch_id", "record_index", name="uq_af_item_batch_index"),
        Index("ix_af_item_conversation", "source_account_uid", "collection_generation", "conversation_id", "conversation_revision"),
        Index("ix_af_item_logical", "source_account_uid", "record_type", "inquiry_id", "collection_generation", "observed_at"),
    )


class AlibabaFeedLink(Base):
    """Personal record linkage, independent of WhatsApp identity and permissions."""
    __tablename__ = "ark_alibaba_feed_links"
    id = Column(ID, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=False, comment="关联用户")
    source_account_uid = Column(exact_string(64), ForeignKey("ark_alibaba_feed_sources.source_account_uid"), nullable=False, comment="来源账号")
    collection_generation = Column(Integer, nullable=False, comment="来源代次")
    record_type = Column(String(16), nullable=False, comment="记录类型")
    inquiry_id = Column(exact_string(128), nullable=False, comment="逻辑记录标识")
    item_id = Column(ID, ForeignKey("ark_alibaba_feed_items.id"), nullable=False, comment="人工确认时的快照")
    company_id = Column(BigInteger, nullable=False, comment="本人私海客户")
    mapping_version = Column(Integer, nullable=False, comment="确认时的负责人映射版本")
    version = Column(Integer, nullable=False, default=1, server_default="1", comment="关联并发版本")
    client_request_id = Column(exact_string(96), nullable=False, comment="个人请求幂等键")
    request_hash = Column(String(64), nullable=False, comment="关联请求摘要")
    deleted_at = Column(TIMESTAMP, nullable=True, comment="撤销北京时间")
    active_slot = Column(Integer, Computed("CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END", persisted=True), comment="有效关联唯一槽")
    created_by = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=False, comment="创建人")
    updated_by = Column(Integer().with_variant(INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), nullable=False, comment="修改人")
    created_at = Column(TIMESTAMP, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(TIMESTAMP, nullable=False, default=beijing_now, onupdate=beijing_now, comment="修改北京时间")
    __table_args__ = (
        UniqueConstraint("user_id", "source_account_uid", "collection_generation", "record_type", "inquiry_id", "active_slot", name="uq_af_link_active"),
        UniqueConstraint("user_id", "client_request_id", name="uq_af_link_request"),
        Index("ix_af_link_customer", "user_id", "company_id", "deleted_at"),
    )


class AlibabaFeedMessage(Base):
    __tablename__ = "ark_alibaba_feed_messages"
    id = Column(ID, primary_key=True, autoincrement=True, comment="主键")
    source_account_uid = Column(exact_string(64), ForeignKey("ark_alibaba_feed_sources.source_account_uid"), nullable=False, comment="来源账号")
    collection_generation = Column(Integer, nullable=False, comment="来源代次")
    conversation_id = Column(exact_string(128), nullable=False, comment="稳定会话身份")
    message_id = Column(exact_string(128), nullable=False, comment="稳定消息身份")
    source_order = Column(BigInteger, nullable=True, comment="会话内来源顺序")
    message_revision = Column(BigInteger, nullable=False, comment="消息修订版本")
    latest_conversation_revision = Column(BigInteger, nullable=False, default=0, server_default="0", comment="消息最近会话版本")
    observed_at = Column(TIMESTAMP, nullable=False, comment="消息观察北京时间")
    snapshot_hash = Column(String(64), nullable=False, comment="消息语义摘要")
    content = Column(JSON, nullable=True, comment="当前规范消息正文")
    actor_type = Column(String(16), nullable=False, comment="人工机器人或未知身份")
    sender_external_user_id = Column(exact_string(128), nullable=True, comment="平台发送员工身份")
    deleted_at = Column(TIMESTAMP, nullable=True, comment="消息撤回北京时间")
    tombstone_revision = Column(BigInteger, nullable=True, comment="最高撤回版本")
    version_conflict = Column(Boolean, nullable=False, default=False, server_default="0", comment="消息版本冲突")
    order_conflict = Column(Boolean, nullable=False, default=False, server_default="0", comment="消息顺序冲突")
    first_item_id = Column(ID, ForeignKey("ark_alibaba_feed_items.id"), nullable=False, comment="首次观察快照")
    created_at = Column(TIMESTAMP, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(TIMESTAMP, nullable=False, default=beijing_now, onupdate=beijing_now, comment="修改北京时间")
    __table_args__ = (UniqueConstraint("source_account_uid", "collection_generation", "conversation_id", "message_id", name="uq_af_message_identity"),)
