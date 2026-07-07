"""add expo AI wig try-on module

Revision ID: 045_expo_tryon
Revises: 044_invoice_module
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "045_expo_tryon"
down_revision = "044_invoice_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_expo_customers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, comment="称呼"),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("wechat_id", sa.String(length=64), nullable=True),
        sa.Column("primary_need", sa.String(length=32), nullable=False, server_default="volume"),
        sa.Column("style_pref", sa.String(length=32), nullable=True),
        sa.Column("consent_at", sa.DateTime(), nullable=True),
        sa.Column("expo_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_customers_phone", "ark_expo_customers", ["phone"])
    op.create_index("idx_ark_expo_customers_expo", "ark_expo_customers", ["expo_code"])

    op.create_table(
        "ark_expo_wigs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_no", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("series", sa.String(length=16), nullable=False, server_default="classic"),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("cover_path", sa.String(length=512), nullable=True),
        sa.Column("angle_photos", sa.JSON(), nullable=True),
        sa.Column("wig_description", sa.Text(), nullable=True),
        sa.Column("composite_prompt", sa.Text(), nullable=True),
        sa.Column("fit_tags", sa.JSON(), nullable=True),
        sa.Column("selling_points", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_no", name="uq_ark_expo_wigs_model_no"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_wigs_active", "ark_expo_wigs", ["is_active"])

    op.create_table(
        "ark_expo_scripts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("script_type", sa.String(length=32), nullable=False),
        sa.Column("track", sa.String(length=16), nullable=False, server_default="emotional"),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("audience_tags", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_points", sa.JSON(), nullable=True),
        sa.Column("source_version", sa.String(length=16), nullable=False, server_default="v4"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_scripts_type", "ark_expo_scripts", ["script_type", "is_active"])

    op.create_table(
        "ark_expo_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("photo_path", sa.String(length=512), nullable=False),
        sa.Column("analysis_json", sa.JSON(), nullable=True),
        sa.Column("matched_wig_ids", sa.JSON(), nullable=True),
        sa.Column("strategy_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("operator_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_expo_customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_sessions_customer", "ark_expo_sessions", ["customer_id"])
    op.create_index("idx_ark_expo_sessions_status", "ark_expo_sessions", ["status"])

    op.create_table(
        "ark_expo_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("wig_id", sa.BigInteger(), nullable=False),
        sa.Column("image_path", sa.String(length=512), nullable=True),
        sa.Column("gen_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("reaction", sa.String(length=16), nullable=True),
        sa.Column("short_code", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["session_id"], ["ark_expo_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wig_id"], ["ark_expo_wigs.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_results_session", "ark_expo_results", ["session_id"])
    op.create_index("idx_ark_expo_results_share", "ark_expo_results", ["short_code"])

    op.create_table(
        "ark_expo_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=True),
        sa.Column("sales_user_id", sa.Integer(), nullable=False),
        sa.Column("intent_level", sa.String(length=4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_action", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_expo_customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_feedback_customer", "ark_expo_feedback", ["customer_id"])
    op.create_index("idx_ark_expo_feedback_intent", "ark_expo_feedback", ["intent_level"])


def downgrade() -> None:
    for idx, table in [
        ("idx_ark_expo_feedback_intent", "ark_expo_feedback"),
        ("idx_ark_expo_feedback_customer", "ark_expo_feedback"),
    ]:
        op.drop_index(idx, table_name=table)
    op.drop_table("ark_expo_feedback")
    op.drop_index("idx_ark_expo_results_share", table_name="ark_expo_results")
    op.drop_index("idx_ark_expo_results_session", table_name="ark_expo_results")
    op.drop_table("ark_expo_results")
    op.drop_index("idx_ark_expo_sessions_status", table_name="ark_expo_sessions")
    op.drop_index("idx_ark_expo_sessions_customer", table_name="ark_expo_sessions")
    op.drop_table("ark_expo_sessions")
    op.drop_index("idx_ark_expo_scripts_type", table_name="ark_expo_scripts")
    op.drop_table("ark_expo_scripts")
    op.drop_index("idx_ark_expo_wigs_active", table_name="ark_expo_wigs")
    op.drop_table("ark_expo_wigs")
    op.drop_index("idx_ark_expo_customers_expo", table_name="ark_expo_customers")
    op.drop_index("idx_ark_expo_customers_phone", table_name="ark_expo_customers")
    op.drop_table("ark_expo_customers")
