"""domestic follow-up call recordings transcribed by the office ASR worker

Only creates one table; rolling release safe. FK types match targets:
followups BIGINT, users INT UNSIGNED.

Revision ID: 281_followup_recordings
Revises: 280_domestic_recharge_allocate
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "281_followup_recordings"
down_revision = "280_domestic_recharge_allocate"
branch_labels = None
depends_on = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
_LONG_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade():
    op.create_table(
        "ark_domestic_followup_recordings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("followup_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_followups.id"), nullable=True,
                  comment="所属跟进；上传后未绑定为空"),
        sa.Column("uploader_user_id", _UINT, sa.ForeignKey("ark_users.id"), nullable=False, comment="上传人"),
        sa.Column("seq", sa.SmallInteger(), nullable=False, server_default="0", comment="在记录中的顺序"),
        sa.Column("file_key", sa.String(255), nullable=True, comment="音频在 domestic 存储的相对路径；转写成功删除后置空"),
        sa.Column("file_name", sa.String(255), nullable=True, comment="原始文件名"),
        sa.Column("mime_type", sa.String(64), nullable=True, comment="MIME"),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0", comment="字节数"),
        sa.Column("sha256", sa.String(64), nullable=False, comment="音频 SHA-256，同人重复上传复用"),
        sa.Column("hotwords", sa.String(500), nullable=True, comment="转写热词，逗号分隔"),
        sa.Column("asr_status", sa.String(12), nullable=False, server_default="queued",
                  comment="queued/running/done/failed"),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0", comment="已计次的转写尝试"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False, comment="最早可领取时间（北京时间）"),
        sa.Column("lease_token", sa.String(32), nullable=True, comment="worker 租约令牌"),
        sa.Column("lease_until", sa.DateTime(), nullable=True, comment="租约到期（北京时间）"),
        sa.Column("duration_sec", sa.Integer(), nullable=True, comment="音频时长（秒）"),
        sa.Column("transcript_key", sa.String(255), nullable=True, comment="转写 txt 在 domestic 存储的相对路径"),
        sa.Column("transcript_text", _LONG_TEXT, nullable=True, comment="转写纯文本，AI 整理与引用核对用"),
        sa.Column("segments", sa.JSON(), nullable=True, comment="分段 [{start,end,speaker,text}]"),
        sa.Column("transcript_chars", sa.Integer(), nullable=True, comment="转写字数"),
        sa.Column("asr_engine", sa.String(64), nullable=True, comment="转写引擎"),
        sa.Column("asr_elapsed_sec", sa.Integer(), nullable=True, comment="转写耗时（秒）"),
        sa.Column("error_message", sa.String(255), nullable=True, comment="最近失败原因（不含录音内容）"),
        sa.Column("organize_status", sa.String(12), nullable=False, server_default="none",
                  comment="AI 整理 none/running/done/failed"),
        sa.Column("organize_result", sa.JSON(), nullable=True, comment="AI 整理建议（引用已核对）"),
        sa.Column("organize_error", sa.String(255), nullable=True, comment="AI 整理失败原因"),
        sa.Column("organize_log_id", sa.BigInteger(), nullable=True, comment="AI 整理调用日志ID"),
        sa.Column("organized_at", sa.DateTime(), nullable=True, comment="AI 整理开始时间（北京时间）"),
        sa.Column("audio_deleted_at", sa.DateTime(), nullable=True, comment="原音频删除时间（北京时间）"),
        sa.Column("archived_at", sa.DateTime(), nullable=True, comment="编辑移除时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="上传时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        comment="跟进录音：办公室 ASR 转写为 txt，成功后删除原音频",
    )
    op.create_index("ix_dom_followup_rec_followup", "ark_domestic_followup_recordings", ["followup_id"])
    op.create_index("ix_dom_followup_rec_uploader", "ark_domestic_followup_recordings", ["uploader_user_id", "sha256"])
    op.create_index("ix_dom_followup_rec_queue", "ark_domestic_followup_recordings", ["asr_status", "next_attempt_at"])


def downgrade():
    # Transcripts are business evidence; refuse to drop them silently.
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM ark_domestic_followup_recordings")).scalar()
    if count:
        raise RuntimeError("Follow-up recordings exist; export them before reverting this schema")
    op.drop_table("ark_domestic_followup_recordings")
