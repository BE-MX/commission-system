"""Expand WhatsApp sync identities and explicit body authorization.

192 avoids unpublished 187-191 in the local commerce worktree. Parent is the
current main head; integration must resolve any parallel Alembic heads explicitly.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "192_wa_sync_fencing"
down_revision = "186_domestic_delivery"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("provider", sa.String(30), nullable=False, server_default="whatsapp-web.js", comment="当前接入Provider"),
        sa.Column("session_generation", sa.Integer(), nullable=False, server_default="0", comment="接入代次"),
        sa.Column("consent_version", sa.Integer(), nullable=False, server_default="0", comment="授权版本"),
        sa.Column("consent_state", sa.String(20), nullable=False, server_default="pending", comment="授权 pending/active/paused/revoked"),
        sa.Column("crm_shared", sa.Boolean(), nullable=False, server_default="0", comment="持有人允许客户域共享"),
        sa.Column("ai_egress_allowed", sa.Boolean(), nullable=False, server_default="0", comment="允许已有供应商分析外发"),
    ):
        op.add_column("ark_whatsapp_accounts", column)
    for column in (
        sa.Column("history_state", sa.String(30), nullable=False, server_default="unknown", comment="平台历史覆盖状态"),
        sa.Column("gap_reason", sa.String(120), nullable=True, comment="历史缺口原因"),
        sa.Column("earliest_seen_at", sa.DateTime(), nullable=True, comment="已观察最早北京时间"),
        sa.Column("latest_seen_at", sa.DateTime(), nullable=True, comment="已观察最新北京时间"),
        sa.Column("last_ingested_at", sa.DateTime(), nullable=True, comment="最近入库北京时间"),
    ):
        op.add_column("ark_whatsapp_conversations", column)
    op.add_column("ark_whatsapp_messages", sa.Column("source_revision", sa.BigInteger(), nullable=False, server_default="0", comment="来源消息版本序号"))
    op.add_column("ark_whatsapp_messages", sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="上游撤回北京时间"))
    op.create_table(
        "ark_whatsapp_body_grants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="正文授权ID"),
        sa.Column("account_uid", sa.String(80), nullable=False, comment="账号范围"),
        sa.Column("user_id", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=False, comment="获授权员工"),
        sa.Column("consent_version", sa.Integer(), nullable=False, comment="授权版本"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="授权北京时间"),
        sa.UniqueConstraint("account_uid", "user_id", name="uk_wa_body_grant"),
        comment="WhatsApp正文范围授权，不授予云外发",
    )
    op.create_table(
        "ark_whatsapp_message_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="来源映射ID"),
        sa.Column("account_uid", sa.String(80), nullable=False, comment="账号范围"),
        sa.Column("provider", sa.String(30), nullable=False, comment="接入Provider"),
        sa.Column("source_digest", sa.String(64), nullable=False, comment="完整来源键SHA256"),
        sa.Column("source_key", sa.JSON(), nullable=False, comment="完整来源身份，不含正文"),
        sa.Column("message_uid", sa.String(160), nullable=False, comment="稳定方舟消息ID"),
        sa.Column("match_state", sa.String(30), nullable=False, comment="exact/new/unverified"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建北京时间"),
        sa.UniqueConstraint("account_uid", "provider", "source_digest", name="uk_wa_message_source"),
        comment="WhatsApp跨Provider确定身份映射",
    )
    # QR is ephemeral, not historical business/audit evidence. Keep other payload keys.
    op.execute("UPDATE ark_whatsapp_bind_sessions SET qr_code_url=NULL, last_payload=JSON_REMOVE(last_payload, '$.qr_code_url', '$.qr') WHERE last_payload IS NOT NULL")
    op.execute("UPDATE ark_whatsapp_bind_sessions SET qr_code_url=NULL")


def downgrade():
    raise RuntimeError("WhatsApp source mappings must be retained; roll back code with the expanded schema, never drop business data")
