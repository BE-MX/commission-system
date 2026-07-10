"""add customer after-sales management

Revision ID: 057_add_aftersales
Revises: 056_tracking_deleted_at
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "057_add_aftersales"
down_revision = "056_tracking_deleted_at"
branch_labels = None
depends_on = None


USER_ID = mysql.INTEGER(unsigned=True)
BIG_ID = mysql.BIGINT(unsigned=True)


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    ]


def upgrade():
    op.create_table(
        "ark_aftersales_sop_versions",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("version_no", sa.String(40), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("parse_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("structured_content_json", sa.JSON()),
        sa.Column("issue_mapping_json", sa.JSON()),
        sa.Column("clause_count", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("activated_at", sa.DateTime()),
        sa.Column("uploaded_by_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("version_no", name="uq_aftersales_sop_version"),
        comment="售后 SOP 版本",
    )
    op.create_index("ix_aftersales_sop_active", "ark_aftersales_sop_versions", ["is_active"])

    op.create_table(
        "ark_aftersales_cases",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("case_no", sa.String(40), nullable=False),
        sa.Column("creator_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("creator_name_snapshot", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(256), nullable=False),
        sa.Column("customer_grade", sa.String(1), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("order_no_snapshot", sa.String(64), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("feedback_date", sa.Date(), nullable=False),
        sa.Column("feedback_channel", sa.String(32)),
        sa.Column("product_id", BIG_ID),
        sa.Column("product_name_snapshot", sa.String(256), nullable=False),
        sa.Column("is_custom_product", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("batch_no", sa.String(128)),
        sa.Column("color_value", sa.String(128), nullable=False),
        sa.Column("length_value", sa.String(128), nullable=False),
        sa.Column("weight_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("weight_unit", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("primary_issue_type", sa.String(32), nullable=False),
        sa.Column("secondary_issue_types_json", sa.JSON()),
        sa.Column("problem_description", sa.Text(), nullable=False),
        sa.Column("occurred_stage", sa.String(32), nullable=False),
        sa.Column("care_storage_note", sa.Text()),
        sa.Column("affects_end_customer", sa.String(16), nullable=False),
        sa.Column("affected_goods_value", sa.Numeric(15, 2), nullable=False),
        sa.Column("affected_goods_currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("sales_evidence_confirmed", sa.Boolean()),
        sa.Column("sales_evidence_note", sa.Text()),
        sa.Column("evidence_score", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
        sa.Column("evidence_is_sufficient", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("evidence_missing_items_json", sa.JSON()),
        sa.Column("responsibility_class", sa.String(1)),
        sa.Column("responsibility_reason", sa.Text()),
        sa.Column("responsibility_override_reason", sa.Text()),
        sa.Column("selected_actions_json", sa.JSON()),
        sa.Column("has_compensation", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("estimated_compensation_usd", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("requires_return", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("customer_reply_draft", sa.Text()),
        sa.Column("execution_result", sa.Text()),
        sa.Column("customer_feedback", sa.Text()),
        sa.Column("sop_version_id", BIG_ID, sa.ForeignKey("ark_aftersales_sop_versions.id")),
        sa.Column("current_status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("current_owner_user_id", USER_ID, sa.ForeignKey("ark_users.id")),
        sa.Column("supervisor_user_id_snapshot", USER_ID, sa.ForeignKey("ark_users.id")),
        sa.Column("director_user_id_snapshot", USER_ID, sa.ForeignKey("ark_users.id")),
        sa.Column("workflow_round", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime()),
        *_timestamps(),
        sa.UniqueConstraint("case_no", name="uq_aftersales_case_no"),
        comment="客户售后单",
    )
    op.create_index("ix_aftersales_case_creator", "ark_aftersales_cases", ["creator_user_id", "current_status"])
    op.create_index("ix_aftersales_case_owner", "ark_aftersales_cases", ["current_owner_user_id", "current_status"])
    op.create_index("ix_aftersales_case_customer", "ark_aftersales_cases", ["customer_id"])
    op.create_index("ix_aftersales_case_created", "ark_aftersales_cases", ["created_at"])

    op.create_table(
        "ark_aftersales_evidence",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("case_id", BIG_ID, sa.ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", BIG_ID, nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("uploaded_by_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        *_timestamps(),
        comment="售后证据文件",
    )
    op.create_index("ix_aftersales_evidence_case", "ark_aftersales_evidence", ["case_id", "evidence_type"])

    op.create_table(
        "ark_aftersales_ai_runs",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("case_id", BIG_ID, sa.ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sop_version_id", BIG_ID, sa.ForeignKey("ark_aftersales_sop_versions.id"), nullable=False),
        sa.Column("run_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("preset_code", sa.String(64), nullable=False, server_default="aftersales_solution_advice"),
        sa.Column("input_summary_json", sa.JSON()),
        sa.Column("output_json", sa.JSON()),
        sa.Column("model_snapshot", sa.String(128)),
        sa.Column("duration_ms", mysql.INTEGER(unsigned=True)),
        sa.Column("error_summary", sa.String(500)),
        sa.Column("created_by_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        *_timestamps(),
        sa.UniqueConstraint("case_id", "run_no", name="uq_aftersales_ai_run"),
        comment="售后 AI 分析运行记录",
    )

    op.create_table(
        "ark_aftersales_reviews",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("case_id", BIG_ID, sa.ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_round", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("reviewer_role", sa.String(24), nullable=False),
        sa.Column("reviewer_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("reviewer_name_snapshot", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("compensation_snapshot_json", sa.JSON()),
        sa.Column("idempotency_key", sa.String(64)),
        *_timestamps(),
        sa.UniqueConstraint("case_id", "workflow_round", "reviewer_role", name="uq_aftersales_review_round_role"),
        sa.UniqueConstraint("idempotency_key", name="uq_aftersales_review_idempotency"),
        comment="售后审核记录",
    )

    op.create_table(
        "ark_aftersales_events",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("case_id", BIG_ID, sa.ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_user_id", USER_ID, sa.ForeignKey("ark_users.id")),
        sa.Column("actor_name_snapshot", sa.String(64)),
        sa.Column("workflow_round", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
        sa.Column("detail_json", sa.JSON()),
        *_timestamps(),
        comment="售后不可变审计事件",
    )
    op.create_index("ix_aftersales_event_case", "ark_aftersales_events", ["case_id", "created_at"])

    op.create_table(
        "ark_aftersales_notification_logs",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("case_id", BIG_ID, sa.ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_event_key", sa.String(128), nullable=False),
        sa.Column("recipient_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("recipient_dingtalk_id", sa.String(100), nullable=False),
        sa.Column("template_code", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime()),
        sa.Column("last_error_summary", sa.String(500)),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        *_timestamps(),
        sa.UniqueConstraint("business_event_key", "recipient_dingtalk_id", name="uq_aftersales_notify_event_recipient"),
        comment="售后钉钉通知日志",
    )
    op.create_index("ix_aftersales_notify_retry", "ark_aftersales_notification_logs", ["status", "next_retry_at"])


def downgrade():
    op.drop_table("ark_aftersales_notification_logs")
    op.drop_table("ark_aftersales_events")
    op.drop_table("ark_aftersales_reviews")
    op.drop_table("ark_aftersales_ai_runs")
    op.drop_table("ark_aftersales_evidence")
    op.drop_table("ark_aftersales_cases")
    op.drop_table("ark_aftersales_sop_versions")
