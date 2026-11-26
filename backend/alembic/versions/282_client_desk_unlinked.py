"""Private-sea B track: unlinked lead threads, daily runs and weekly reviews."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "282_client_desk_unlinked"
down_revision = "281_followup_recordings"
branch_labels = None
depends_on = None

USER = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def _audit():
    return [
        sa.Column("status", sa.String(24), nullable=False, server_default="active", comment="状态"),
        sa.Column("remark", sa.Text(), nullable=True, comment="人工备注"),
        sa.Column("created_by", USER, sa.ForeignKey("ark_users.id"), nullable=True, comment="创建人"),
        sa.Column("updated_by", USER, sa.ForeignKey("ark_users.id"), nullable=True, comment="修改人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="修改北京时间"),
    ]


def upgrade():
    op.add_column("ark_alibaba_feed_pilot", sa.Column(
        "unlinked_ai_allowed", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="允许试点未绑定线索使用模型分析",
    ))
    op.create_table(
        "ark_client_desk_unlinked_threads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("user_id", USER, sa.ForeignKey("ark_users.id"), nullable=False, comment="归属业务员"),
        sa.Column("channel", sa.String(24), nullable=False, comment="渠道：alibaba_tm / whatsapp"),
        sa.Column("source_account_uid", sa.String(64), nullable=False, comment="来源账号标识"),
        sa.Column("thread_key", sa.String(160), nullable=False, comment="逻辑会话标识"),
        sa.Column("item_id", sa.BigInteger(), nullable=True, comment="当前合格快照记录ID"),
        sa.Column("display_name", sa.String(160), nullable=True, comment="买家或联系人展示名"),
        sa.Column("country_code", sa.String(8), nullable=True, comment="买家国家代码"),
        sa.Column("last_message_at", sa.DateTime(), nullable=True, comment="最近有效消息北京时间"),
        sa.Column("last_direction", sa.String(16), nullable=True, comment="最近消息方向 inbound/outbound/unknown"),
        sa.Column("seen_watermark", sa.JSON(), nullable=True, comment="已观察到的最新入站水位"),
        sa.Column("done_watermark", sa.JSON(), nullable=True, comment="已分析或已处理的水位"),
        sa.Column("handled_at", sa.DateTime(), nullable=True, comment="最近一次已在其他渠道处理的北京时间"),
        sa.Column("next_followup_date", sa.Date(), nullable=True, comment="潜客下次跟进日"),
        sa.Column("next_followup_remark", sa.Text(), nullable=True, comment="潜客跟进说明（承诺事项）"),
        sa.Column("linked_company_id", sa.BigInteger(), nullable=True, comment="绑定的 OKKI 公司，仅留痕"),
        sa.Column("source_dependencies", sa.JSON(), nullable=True, comment="最近一次授权与映射依赖"),
        *_audit(),
        sa.UniqueConstraint("user_id", "channel", "source_account_uid", "thread_key",
                            name="uq_client_desk_unlinked_thread"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="私海B轨未绑定线索会话表",
    )
    op.create_index("ix_client_desk_unlinked_user_status", "ark_client_desk_unlinked_threads",
                    ["user_id", "status", "last_message_at"])

    op.create_table(
        "ark_client_desk_unlinked_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("thread_id", sa.BigInteger(), sa.ForeignKey("ark_client_desk_unlinked_threads.id"),
                  nullable=False, comment="线索ID"),
        sa.Column("user_id", USER, sa.ForeignKey("ark_users.id"), nullable=False, comment="归属业务员"),
        sa.Column("biz_date", sa.Date(), nullable=False, comment="运行当天北京业务日"),
        sa.Column("trigger_type", sa.String(16), nullable=False, comment="daily 例行 / manual 手动"),
        sa.Column("run_seq", sa.Integer(), nullable=False, server_default="0", comment="同日同类序号"),
        sa.Column("lease_token", sa.String(64), nullable=True, comment="租约令牌"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True, comment="租约到期北京时间"),
        sa.Column("call_started_at", sa.DateTime(), nullable=True, comment="模型调用开始北京时间"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0", comment="调用次数"),
        sa.Column("protocol_version", sa.String(32), nullable=True, comment="协议版本"),
        sa.Column("pack_hash", sa.String(64), nullable=True, comment="资料包哈希"),
        sa.Column("watermark", sa.JSON(), nullable=True, comment="本次分析所基于的入站水位"),
        sa.Column("source_dependencies", sa.JSON(), nullable=True, comment="运行时授权依赖"),
        sa.Column("token_usage", sa.JSON(), nullable=True, comment="token 用量"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="无正文错误码"),
        sa.Column("is_business_lead", sa.Boolean(), nullable=True, comment="是否外贸业务线索"),
        sa.Column("intent_stage", sa.String(32), nullable=True, comment="意向阶段代码"),
        sa.Column("urgency", sa.String(16), nullable=True, comment="紧急度 high/medium/low"),
        sa.Column("one_line_summary", sa.String(200), nullable=True, comment="一句话前情"),
        sa.Column("missing_or_next_action", sa.Text(), nullable=True, comment="遗漏问题与下一步"),
        sa.Column("breakthrough_angle", sa.String(200), nullable=True, comment="沟通突破点"),
        sa.Column("draft_message", sa.Text(), nullable=True, comment="草稿"),
        sa.Column("extracted_clues", sa.JSON(), nullable=True, comment="提取的线索"),
        sa.Column("cites", sa.JSON(), nullable=True, comment="引用键"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default="0", comment="含报价交期需核对"),
        *_audit(),
        sa.UniqueConstraint("thread_id", "biz_date", "trigger_type", "run_seq", name="uq_client_desk_unlinked_run"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="私海B轨线索日分析与队列表",
    )
    op.create_index("ix_client_desk_unlinked_run_queue", "ark_client_desk_unlinked_runs",
                    ["status", "lease_expires_at"])
    op.create_index("ix_client_desk_unlinked_run_user_date", "ark_client_desk_unlinked_runs",
                    ["user_id", "biz_date"])

    op.create_table(
        "ark_client_desk_unlinked_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("user_id", USER, sa.ForeignKey("ark_users.id"), nullable=False, comment="归属业务员"),
        sa.Column("week_start_date", sa.Date(), nullable=False, comment="北京周一日期"),
        sa.Column("window_start", sa.DateTime(), nullable=False, comment="覆盖窗口开始北京时间"),
        sa.Column("window_end", sa.DateTime(), nullable=False, comment="覆盖窗口结束北京时间"),
        sa.Column("lease_token", sa.String(64), nullable=True, comment="租约令牌"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True, comment="租约到期北京时间"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0", comment="调用次数"),
        sa.Column("included_thread_ids", sa.JSON(), nullable=True, comment="纳入汇总的线索ID"),
        sa.Column("source_dependencies", sa.JSON(), nullable=True, comment="纳入线索的授权依赖"),
        sa.Column("token_usage", sa.JSON(), nullable=True, comment="token 用量"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="无正文错误码"),
        sa.Column("overview_md", sa.Text(), nullable=True, comment="本周总览"),
        sa.Column("missed_tasks", sa.JSON(), nullable=True, comment="遗漏任务"),
        sa.Column("breakthrough_leads", sa.JSON(), nullable=True, comment="突破点"),
        sa.Column("likely_existing_customers", sa.JSON(), nullable=True, comment="疑似老客"),
        sa.Column("cleanup_candidates", sa.JSON(), nullable=True, comment="可清理项"),
        *_audit(),
        sa.UniqueConstraint("user_id", "week_start_date", name="uq_client_desk_unlinked_review_week"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        comment="私海B轨每周集中梳理报告表",
    )


def downgrade():
    # Rollback is guarded by live data and must run through an online migration.
    if op.get_context().as_sql:
        raise RuntimeError("B-track downgrade requires an online data check")
    has_data = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM ark_client_desk_unlinked_threads) "
        "OR EXISTS (SELECT 1 FROM ark_client_desk_unlinked_runs) "
        "OR EXISTS (SELECT 1 FROM ark_client_desk_unlinked_reviews)"
    )).scalar()
    if has_data:
        raise RuntimeError("B-track data exists; export it and empty the tables before reverting this schema")
    op.drop_table("ark_client_desk_unlinked_reviews")
    op.drop_table("ark_client_desk_unlinked_runs")
    op.drop_table("ark_client_desk_unlinked_threads")
    op.drop_column("ark_alibaba_feed_pilot", "unlinked_ai_allowed")
