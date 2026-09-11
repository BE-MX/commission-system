"""Persistence models for the mail outreach domain (approved scheduled sending).

表结构唯一来源：docs/2026-09-11-mail-outreach-auto-send-design.md §三。
时间口径：业务时间列存无时区北京时间（default=beijing_now）；
lease/协议列存无时区 UTC（utc_now_naive 跨机器租约契约）。
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.auth.models import ArkUser  # noqa: F401 -- registers FK target
from app.core.database import Base
from app.core.time import beijing_now


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
SHA256 = String(64).with_variant(mysql.CHAR(64), "mysql")

MAILBOX_STATUSES = ("active", "disabled")
MAILBOX_AUTH_STATUSES = ("active", "expired", "unbound", "unknown")
MESSAGE_STATUSES = ("draft", "approved", "rejected", "cancelled", "completed")
RELATIONSHIP_GOALS = ("first_intro", "follow_up", "reactivation")
LANGUAGE_SOURCES = ("recipient", "company", "country", "manual")
APPROVAL_DECISIONS = ("approved", "rejected", "revoked")
JOB_STATUSES = (
    "scheduled",
    "claimed",
    "sending",
    "provider_accepted",
    "failed_safe",
    "ambiguous",
    "blocked",
    "needs_review",
    "cancelled",
)
ATTEMPT_OUTCOMES = ("accepted", "failed_safe", "unknown")
EVENT_CLASSIFICATIONS = ("human_reply", "auto_reply", "bounce", "opt_out", "other", "uncertain")
EVENT_PROCESSED_STATUSES = ("pending", "processed", "ignored", "needs_human")
EVENT_MATCH_BASIS = ("thread_header", "sender_subject_candidate", "manual", "none")
WATCH_HEALTHS = ("ok", "stale", "down", "unknown")


def _in_clause(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class MailMailboxBinding(Base):
    """发件邮箱绑定：worker 身份 ↔ CLI workspace ↔ 发件地址固定映射；只存密钥引用。"""

    __tablename__ = "ark_mail_mailbox_bindings"
    __table_args__ = (
        UniqueConstraint("provider", "sender_email", name="uq_mail_mbb_provider_sender"),
        CheckConstraint(f"status IN {_in_clause(MAILBOX_STATUSES)}", name="ck_mail_mbb_status"),
        CheckConstraint(
            f"auth_status IN {_in_clause(MAILBOX_AUTH_STATUSES)}", name="ck_mail_mbb_auth_status",
        ),
        CheckConstraint("daily_quota > 0", name="ck_mail_mbb_quota"),
        Index("idx_mail_mbb_worker", "worker_identity"),
        {"comment": "发件邮箱绑定与限额；OAuth 凭据只存引用不存本体"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, default="agent_mail", comment="通道提供方")
    sender_email = Column(String(255), nullable=False, comment="发件地址")
    display_name = Column(String(128), nullable=False, default="", comment="发件人展示名")
    owner_user_id = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True,
        comment="邮箱业务归属人",
    )
    worker_identity = Column(String(64), nullable=False, comment="允许操作该邮箱的 worker 身份")
    cli_workspace = Column(String(64), nullable=False, comment="对应 AGENTLY_WORKSPACE")
    auth_status = Column(String(16), nullable=False, default="unknown", comment="通道授权状态")
    daily_quota = Column(Integer, nullable=False, default=50, comment="每日发信额度")
    quota_timezone = Column(String(64), nullable=False, default="Asia/Shanghai", comment="配额重置时区")
    pause_reason = Column(String(255), nullable=True, comment="非空即暂停该邮箱一切发送")
    secret_ref = Column(String(255), nullable=False, default="", comment="凭据保管位置引用")
    status = Column(String(16), nullable=False, default="active", comment="绑定状态")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间",
    )

    owner = relationship("ArkUser", lazy="noload", foreign_keys=[owner_user_id])


class MailOutreachMessage(Base):
    """开发信聚合根：一次触达意图（客户+联系人+邮箱点+关系目标）。"""

    __tablename__ = "ark_mail_outreach_messages"
    __table_args__ = (
        CheckConstraint(f"status IN {_in_clause(MESSAGE_STATUSES)}", name="ck_mail_msg_status"),
        CheckConstraint(
            f"relationship_goal IN {_in_clause(RELATIONSHIP_GOALS)}", name="ck_mail_msg_goal",
        ),
        Index("idx_mail_msg_customer_status", "customer_id", "status"),
        Index("idx_mail_msg_point_status", "contact_point_id", "status"),
        {"comment": "邮件触达聚合根；内容以不可变 revision 追加"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(
        BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=False, comment="统一客户ID",
    )
    contact_id = Column(
        BigInteger, ForeignKey("ark_customer_contacts.id"), nullable=False, comment="联系人ID",
    )
    contact_point_id = Column(
        BigInteger, ForeignKey("ark_customer_contact_points.id"), nullable=False,
        comment="收件邮箱点ID",
    )
    relationship_goal = Column(
        String(24), nullable=False, comment="关系目标：first_intro/follow_up/reactivation",
    )
    status = Column(String(16), nullable=False, default="draft", comment="草稿生命周期")
    current_revision_id = Column(
        BigInteger, nullable=True,
        comment="当前版本ID（逻辑指向 revisions.id，不建 FK 避免循环依赖）",
    )
    created_by = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="创建人",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间",
    )


class MailOutreachRevision(Base):
    """不可变邮件版本：批准后任何关键变化必须产生新 revision 并使旧审批失效。"""

    __tablename__ = "ark_mail_outreach_revisions"
    __table_args__ = (
        UniqueConstraint("message_id", "revision_no", name="uq_mail_rev_message_no"),
        CheckConstraint(
            f"language_source IN {_in_clause(LANGUAGE_SOURCES)}", name="ck_mail_rev_lang_source",
        ),
        Index("idx_mail_rev_content_hash", "content_sha256"),
        {"comment": "邮件不可变版本；claims 逐条绑定客户事实或批准的公司知识版本"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(
        BigInteger, ForeignKey("ark_mail_outreach_messages.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属触达意图",
    )
    revision_no = Column(Integer, nullable=False, comment="版本号，单调递增")
    subject = Column(String(255), nullable=False, comment="主题")
    body_text = Column(Text, nullable=False, comment="正文（首版纯文本）")
    language_tag = Column(String(35), nullable=False, comment="BCP 47 目标语言")
    language_source = Column(String(16), nullable=False, comment="语言依据来源")
    language_basis = Column(String(500), nullable=False, comment="语言选择依据说明")
    meaning_summary_zh = Column(Text, nullable=False, comment="中文核对释义")
    angle = Column(String(255), nullable=False, default="", comment="切入点")
    cta = Column(String(255), nullable=False, default="", comment="行动号召及理由")
    claims_json = Column(JSON, nullable=False, comment="证据账本：claim/来源/允许措辞")
    risk_flags_json = Column(JSON, nullable=False, comment="风险标记列表")
    evidence_snapshot_json = Column(
        JSON, nullable=False, comment="生成时可见事实ID/指纹/画像版本快照",
    )
    recipient_timezone = Column(String(64), nullable=False, comment="收件人 IANA 时区")
    location_evidence = Column(String(500), nullable=False, default="", comment="时区/地点依据")
    schedule_policy_json = Column(JSON, nullable=False, comment="排程政策：办公开始/顺延上限/过期")
    preset_name = Column(String(64), nullable=False, default="", comment="生成 preset")
    preset_prompt_revision = Column(String(32), nullable=False, default="", comment="提示词版本")
    content_sha256 = Column(SHA256, nullable=False, comment="规范化 subject+body+language+claims 哈希")
    created_by_kind = Column(String(16), nullable=False, default="ai", comment="ai/human/edit")
    created_by = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="操作人",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")


class MailOutreachApproval(Base):
    """逐封审批：绑定版本、发件身份、精确收件人、内容哈希与排程政策。"""

    __tablename__ = "ark_mail_outreach_approvals"
    __table_args__ = (
        CheckConstraint(
            f"decision IN {_in_clause(APPROVAL_DECISIONS)}", name="ck_mail_apr_decision",
        ),
        Index("idx_mail_apr_message", "message_id"),
        Index("idx_mail_apr_revision", "revision_id"),
        # 同一 revision 至多一条生效 approved 由服务层事务内校验保证（MySQL 无部分唯一索引）
        {"comment": "邮件审批；approval_sha256 锁定批准载荷，批准后不可变"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(
        BigInteger, ForeignKey("ark_mail_outreach_messages.id", ondelete="CASCADE"),
        nullable=False, comment="所属触达意图",
    )
    revision_id = Column(
        BigInteger, ForeignKey("ark_mail_outreach_revisions.id"), nullable=False, comment="批准版本",
    )
    approver_user_id = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="审核人（必须人类）",
    )
    decision = Column(String(16), nullable=False, comment="approved/rejected/revoked")
    reason = Column(String(500), nullable=False, default="", comment="审批理由")
    mailbox_binding_id = Column(
        BigInteger, ForeignKey("ark_mail_mailbox_bindings.id"), nullable=True, comment="发件邮箱绑定",
    )
    to_contact_point_id = Column(BigInteger, nullable=False, comment="精确收件邮箱点")
    to_email_snapshot = Column(String(255), nullable=False, default="", comment="审批时收件地址快照")
    approval_sha256 = Column(SHA256, nullable=True, comment="批准载荷哈希")
    scheduled_at_utc = Column(DateTime, nullable=True, comment="排程时刻（UTC，协议契约）")
    scheduled_at_local = Column(String(64), nullable=True, comment="客户当地展示时间")
    scheduled_at_beijing = Column(DateTime, nullable=True, comment="排程时刻（北京时间，业务展示）")
    reschedule_policy_json = Column(JSON, nullable=True, comment="允许顺延窗口/次数/过期政策")
    expires_at = Column(DateTime, nullable=True, comment="审批有效期（北京时间）")
    decided_at = Column(DateTime, nullable=False, default=beijing_now, comment="审批时间")
    revoked_at = Column(DateTime, nullable=True, comment="撤销时间")
    revoke_reason = Column(String(500), nullable=True, comment="撤销原因")


class MailOutreachSendJob(Base):
    """唯一待发任务：一个批准只生成一个 job；租约 + fencing 保证单执行器。"""

    __tablename__ = "ark_mail_outreach_send_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_mail_job_idempotency"),
        UniqueConstraint("approval_id", name="uq_mail_job_approval"),
        CheckConstraint(f"status IN {_in_clause(JOB_STATUSES)}", name="ck_mail_job_status"),
        CheckConstraint("fencing_token >= 0", name="ck_mail_job_fencing"),
        Index("idx_mail_job_status_due", "status", "due_at"),
        Index("idx_mail_job_point", "to_contact_point_id", "status"),
        {"comment": "邮件发送队列；方舟数据库是唯一可发送任务源"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(64), nullable=False, comment="由 message+revision 派生的幂等键")
    approval_id = Column(
        BigInteger, ForeignKey("ark_mail_outreach_approvals.id"), nullable=False, comment="来源审批",
    )
    message_id = Column(BigInteger, nullable=False, comment="冗余便于查询")
    revision_id = Column(BigInteger, nullable=False, comment="冗余便于查询")
    mailbox_binding_id = Column(
        BigInteger, ForeignKey("ark_mail_mailbox_bindings.id"), nullable=False, comment="发件邮箱",
    )
    to_contact_point_id = Column(BigInteger, nullable=False, comment="精确收件邮箱点")
    to_email_snapshot = Column(String(255), nullable=False, comment="收件地址快照（发送前仍校验）")
    status = Column(String(24), nullable=False, default="scheduled", comment="发送主状态")
    due_at = Column(DateTime, nullable=False, comment="计划发送时间（北京时间，业务展示/扫描）")
    due_at_utc = Column(DateTime, nullable=False, comment="计划发送时间（UTC，协议契约）")
    lease_owner = Column(String(64), nullable=True, comment="当前认领 worker 身份")
    lease_until_utc = Column(DateTime, nullable=True, comment="租约到期（UTC）")
    fencing_token = Column(Integer, nullable=False, default=0, comment="每次认领 +1 的围栏令牌")
    send_started_at_utc = Column(
        DateTime, nullable=True, comment="已开始外部调用（非空则撤销只能标注太晚）",
    )
    reschedule_count = Column(Integer, nullable=False, default=0, comment="政策内顺延次数")
    last_precheck_json = Column(JSON, nullable=True, comment="最近一次临发复查结果")
    blocked_reason = Column(String(500), nullable=True, comment="阻断/待复核原因")
    cancel_note = Column(String(500), nullable=True, comment="撤销备注")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间",
    )


class MailOutreachSendAttempt(Base):
    """发送留痕：追加-only，无 update 接口。"""

    __tablename__ = "ark_mail_outreach_send_attempts"
    __table_args__ = (
        CheckConstraint(
            f"outcome IN {_in_clause(ATTEMPT_OUTCOMES)}", name="ck_mail_att_outcome",
        ),
        Index("idx_mail_att_job", "job_id"),
        {"comment": "发送尝试留痕；provider 响应脱敏后保存"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(
        BigInteger, ForeignKey("ark_mail_outreach_send_jobs.id", ondelete="CASCADE"),
        nullable=False, comment="所属任务",
    )
    fencing_token = Column(Integer, nullable=False, comment="发起时的 fencing，防旧 worker 上报")
    precheck_result_json = Column(JSON, nullable=True, comment="调用前复查快照")
    provider_message_id = Column(String(128), nullable=True, comment="通道接受凭据")
    provider_response_redacted = Column(JSON, nullable=True, comment="脱敏后的通道响应")
    outcome = Column(String(16), nullable=False, comment="accepted/failed_safe/unknown")
    error_kind = Column(String(64), nullable=True, comment="错误分类")
    started_at_utc = Column(DateTime, nullable=True, comment="调用开始（UTC）")
    finished_at_utc = Column(DateTime, nullable=True, comment="调用结束（UTC）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="记录时间")


class MailEvent(Base):
    """收件事件：按邮箱与 provider message ID 去重；分类低置信度交人工。"""

    __tablename__ = "ark_mail_events"
    __table_args__ = (
        UniqueConstraint(
            "mailbox_binding_id", "provider_message_id", name="uq_mail_event_dedup",
        ),
        CheckConstraint(
            f"classification IN {_in_clause(EVENT_CLASSIFICATIONS)}", name="ck_mail_event_class",
        ),
        CheckConstraint(
            f"processed_status IN {_in_clause(EVENT_PROCESSED_STATUSES)}",
            name="ck_mail_event_processed",
        ),
        CheckConstraint(
            f"match_basis IN {_in_clause(EVENT_MATCH_BASIS)}", name="ck_mail_event_match_basis",
        ),
        Index("idx_mail_event_customer", "matched_customer_id"),
        Index("idx_mail_event_class_status", "classification", "processed_status"),
        {"comment": "收件/退信/退订事件；原始内容按数据分级与保留政策控制"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mailbox_binding_id = Column(
        BigInteger, ForeignKey("ark_mail_mailbox_bindings.id", ondelete="CASCADE"),
        nullable=False, comment="收件邮箱绑定",
    )
    provider_message_id = Column(String(191), nullable=False, comment="通道消息ID（去重键）")
    rfc_message_id = Column(String(255), nullable=True, comment="RFC Message-ID 头")
    in_reply_to = Column(String(255), nullable=True, comment="In-Reply-To 头")
    references_header = Column(Text, nullable=True, comment="References 头")
    from_address = Column(String(255), nullable=False, default="", comment="发件人")
    to_address = Column(String(255), nullable=False, default="", comment="收件人")
    subject = Column(String(500), nullable=False, default="", comment="主题")
    received_at_utc = Column(DateTime, nullable=True, comment="收到时间（UTC）")
    classification = Column(String(24), nullable=False, default="uncertain", comment="事件分类")
    classification_confidence = Column(Numeric(5, 4), nullable=True, comment="分类置信度")
    matched_job_id = Column(BigInteger, nullable=True, comment="关联的发送任务")
    matched_customer_id = Column(BigInteger, nullable=True, comment="关联客户")
    match_basis = Column(String(24), nullable=False, default="none", comment="关联依据")
    processed_status = Column(String(16), nullable=False, default="pending", comment="处理状态")
    payload_redacted = Column(JSON, nullable=True, comment="脱敏后的内容摘要")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="入库时间")


class MailEventCheckpoint(Base):
    """收件监听同步检查点与 watch 健康。"""

    __tablename__ = "ark_mail_event_checkpoints"
    __table_args__ = (
        CheckConstraint(
            f"watch_health IN {_in_clause(WATCH_HEALTHS)}", name="ck_mail_ckpt_health",
        ),
        {"comment": "每个邮箱绑定一行的监听检查点"},
    )

    mailbox_binding_id = Column(
        BigInteger, ForeignKey("ark_mail_mailbox_bindings.id", ondelete="CASCADE"),
        primary_key=True, comment="邮箱绑定",
    )
    last_seen_provider_message_id = Column(String(191), nullable=True, comment="最近处理的消息ID")
    last_polled_at_utc = Column(DateTime, nullable=True, comment="最近轮询（UTC）")
    watch_health = Column(String(16), nullable=False, default="unknown", comment="监听健康")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间",
    )


__all__ = [
    "MailMailboxBinding",
    "MailOutreachMessage",
    "MailOutreachRevision",
    "MailOutreachApproval",
    "MailOutreachSendJob",
    "MailOutreachSendAttempt",
    "MailEvent",
    "MailEventCheckpoint",
]
