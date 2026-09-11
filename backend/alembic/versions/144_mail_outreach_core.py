"""Mail outreach core schema: mailbox bindings, drafts/revisions, approvals, send jobs, attempts, events.

设计文档：docs/2026-09-11-mail-outreach-auto-send-design.md §三。
时间口径：业务时间列存无时区北京时间（ORM default=beijing_now）；
lease/协议列存无时区 UTC。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "144_mail_outreach_core"
down_revision = "143_whatsapp_reply_inquiries"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
SHA256 = sa.String(64).with_variant(mysql.CHAR(64), "mysql")


def upgrade():
    op.create_table(
        "ark_mail_mailbox_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("owner_user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("worker_identity", sa.String(64), nullable=False),
        sa.Column("cli_workspace", sa.String(64), nullable=False),
        sa.Column("auth_status", sa.String(16), nullable=False),
        sa.Column("daily_quota", sa.Integer(), nullable=False),
        sa.Column("quota_timezone", sa.String(64), nullable=False),
        sa.Column("pause_reason", sa.String(255), nullable=True),
        sa.Column("secret_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "sender_email", name="uq_mail_mbb_provider_sender"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_mail_mbb_status"),
        sa.CheckConstraint(
            "auth_status IN ('active', 'expired', 'unbound', 'unknown')", name="ck_mail_mbb_auth_status",
        ),
        sa.CheckConstraint("daily_quota > 0", name="ck_mail_mbb_quota"),
        mysql_comment="发件邮箱绑定与限额；OAuth 凭据只存引用不存本体",
    )
    op.create_index("idx_mail_mbb_worker", "ark_mail_mailbox_bindings", ["worker_identity"])

    op.create_table(
        "ark_mail_outreach_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("ark_customer_accounts.id"), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), sa.ForeignKey("ark_customer_contacts.id"), nullable=False),
        sa.Column(
            "contact_point_id", sa.BigInteger(),
            sa.ForeignKey("ark_customer_contact_points.id"), nullable=False,
        ),
        sa.Column("relationship_goal", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", USER_ID, sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'cancelled', 'completed')",
            name="ck_mail_msg_status",
        ),
        sa.CheckConstraint(
            "relationship_goal IN ('first_intro', 'follow_up', 'reactivation')",
            name="ck_mail_msg_goal",
        ),
        mysql_comment="邮件触达聚合根；内容以不可变 revision 追加",
    )
    op.create_index(
        "idx_mail_msg_customer_status", "ark_mail_outreach_messages", ["customer_id", "status"],
    )
    op.create_index(
        "idx_mail_msg_point_status", "ark_mail_outreach_messages", ["contact_point_id", "status"],
    )

    op.create_table(
        "ark_mail_outreach_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_outreach_messages.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("language_tag", sa.String(35), nullable=False),
        sa.Column("language_source", sa.String(16), nullable=False),
        sa.Column("language_basis", sa.String(500), nullable=False),
        sa.Column("meaning_summary_zh", sa.Text(), nullable=False),
        sa.Column("angle", sa.String(255), nullable=False),
        sa.Column("cta", sa.String(255), nullable=False),
        sa.Column("claims_json", sa.JSON(), nullable=False),
        sa.Column("risk_flags_json", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("recipient_timezone", sa.String(64), nullable=False),
        sa.Column("location_evidence", sa.String(500), nullable=False),
        sa.Column("schedule_policy_json", sa.JSON(), nullable=False),
        sa.Column("preset_name", sa.String(64), nullable=False),
        sa.Column("preset_prompt_revision", sa.String(32), nullable=False),
        sa.Column("content_sha256", SHA256, nullable=False),
        sa.Column("created_by_kind", sa.String(16), nullable=False),
        sa.Column("created_by", USER_ID, sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("message_id", "revision_no", name="uq_mail_rev_message_no"),
        sa.CheckConstraint(
            "language_source IN ('recipient', 'company', 'country', 'manual')",
            name="ck_mail_rev_lang_source",
        ),
        mysql_comment="邮件不可变版本；claims 逐条绑定客户事实或批准的公司知识版本",
    )
    op.create_index(
        "idx_mail_rev_message", "ark_mail_outreach_revisions", ["message_id"],
    )
    op.create_index(
        "idx_mail_rev_content_hash", "ark_mail_outreach_revisions", ["content_sha256"],
    )

    op.create_table(
        "ark_mail_outreach_approvals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_outreach_messages.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "revision_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_outreach_revisions.id"), nullable=False,
        ),
        sa.Column("approver_user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "mailbox_binding_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_mailbox_bindings.id"), nullable=True,
        ),
        sa.Column("to_contact_point_id", sa.BigInteger(), nullable=False),
        sa.Column("to_email_snapshot", sa.String(255), nullable=False),
        sa.Column("approval_sha256", SHA256, nullable=True),
        sa.Column("scheduled_at_utc", sa.DateTime(), nullable=True),
        sa.Column("scheduled_at_local", sa.String(64), nullable=True),
        sa.Column("scheduled_at_beijing", sa.DateTime(), nullable=True),
        sa.Column("reschedule_policy_json", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(500), nullable=True),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'revoked')", name="ck_mail_apr_decision",
        ),
        mysql_comment="邮件审批；approval_sha256 锁定批准载荷，批准后不可变",
    )
    op.create_index("idx_mail_apr_message", "ark_mail_outreach_approvals", ["message_id"])
    op.create_index("idx_mail_apr_revision", "ark_mail_outreach_approvals", ["revision_id"])

    op.create_table(
        "ark_mail_outreach_send_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column(
            "approval_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_outreach_approvals.id"), nullable=False,
        ),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "mailbox_binding_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_mailbox_bindings.id"), nullable=False,
        ),
        sa.Column("to_contact_point_id", sa.BigInteger(), nullable=False),
        sa.Column("to_email_snapshot", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("due_at_utc", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_until_utc", sa.DateTime(), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("send_started_at_utc", sa.DateTime(), nullable=True),
        sa.Column("reschedule_count", sa.Integer(), nullable=False),
        sa.Column("last_precheck_json", sa.JSON(), nullable=True),
        sa.Column("blocked_reason", sa.String(500), nullable=True),
        sa.Column("cancel_note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_mail_job_idempotency"),
        sa.UniqueConstraint("approval_id", name="uq_mail_job_approval"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'claimed', 'sending', 'provider_accepted', 'failed_safe', "
            "'ambiguous', 'blocked', 'needs_review', 'cancelled')",
            name="ck_mail_job_status",
        ),
        sa.CheckConstraint("fencing_token >= 0", name="ck_mail_job_fencing"),
        mysql_comment="邮件发送队列；方舟数据库是唯一可发送任务源",
    )
    op.create_index("idx_mail_job_status_due", "ark_mail_outreach_send_jobs", ["status", "due_at"])
    op.create_index(
        "idx_mail_job_point", "ark_mail_outreach_send_jobs", ["to_contact_point_id", "status"],
    )

    op.create_table(
        "ark_mail_outreach_send_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_outreach_send_jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("precheck_result_json", sa.JSON(), nullable=True),
        sa.Column("provider_message_id", sa.String(128), nullable=True),
        sa.Column("provider_response_redacted", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error_kind", sa.String(64), nullable=True),
        sa.Column("started_at_utc", sa.DateTime(), nullable=True),
        sa.Column("finished_at_utc", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'failed_safe', 'unknown')", name="ck_mail_att_outcome",
        ),
        mysql_comment="发送尝试留痕；provider 响应脱敏后保存",
    )
    op.create_index("idx_mail_att_job", "ark_mail_outreach_send_attempts", ["job_id"])

    op.create_table(
        "ark_mail_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "mailbox_binding_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_mailbox_bindings.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(191), nullable=False),
        sa.Column("rfc_message_id", sa.String(255), nullable=True),
        sa.Column("in_reply_to", sa.String(255), nullable=True),
        sa.Column("references_header", sa.Text(), nullable=True),
        sa.Column("from_address", sa.String(255), nullable=False),
        sa.Column("to_address", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("received_at_utc", sa.DateTime(), nullable=True),
        sa.Column("classification", sa.String(24), nullable=False),
        sa.Column("classification_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("matched_job_id", sa.BigInteger(), nullable=True),
        sa.Column("matched_customer_id", sa.BigInteger(), nullable=True),
        sa.Column("match_basis", sa.String(24), nullable=False),
        sa.Column("processed_status", sa.String(16), nullable=False),
        sa.Column("payload_redacted", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "mailbox_binding_id", "provider_message_id", name="uq_mail_event_dedup",
        ),
        sa.CheckConstraint(
            "classification IN ('human_reply', 'auto_reply', 'bounce', 'opt_out', 'other', 'uncertain')",
            name="ck_mail_event_class",
        ),
        sa.CheckConstraint(
            "processed_status in ('pending', 'processed', 'ignored', 'needs_human')",
            name="ck_mail_event_processed",
        ),
        sa.CheckConstraint(
            "match_basis IN ('thread_header', 'sender_subject_candidate', 'manual', 'none')",
            name="ck_mail_event_match_basis",
        ),
        mysql_comment="收件/退信/退订事件；原始内容按数据分级与保留政策控制",
    )
    op.create_index("idx_mail_event_customer", "ark_mail_events", ["matched_customer_id"])
    op.create_index(
        "idx_mail_event_class_status", "ark_mail_events", ["classification", "processed_status"],
    )

    op.create_table(
        "ark_mail_event_checkpoints",
        sa.Column(
            "mailbox_binding_id", sa.BigInteger(),
            sa.ForeignKey("ark_mail_mailbox_bindings.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("last_seen_provider_message_id", sa.String(191), nullable=True),
        sa.Column("last_polled_at_utc", sa.DateTime(), nullable=True),
        sa.Column("watch_health", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "watch_health IN ('ok', 'stale', 'down', 'unknown')", name="ck_mail_ckpt_health",
        ),
        mysql_comment="每个邮箱绑定一行的监听检查点",
    )


def downgrade():
    # 邮件触达任务与审计数据必须保留；如需回滚，走单独评审的前向迁移。
    raise RuntimeError("Mail outreach data must be preserved; use a reviewed forward migration")
