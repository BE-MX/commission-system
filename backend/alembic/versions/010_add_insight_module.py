"""add ark insight module tables: reports, sources, case_library, meeting_minutes, insight_tasks

Revision ID: 010_add_insight_module
Revises: 009_add_ai_module
Create Date: 2026-05-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_add_insight_module"
down_revision: Union[str, None] = "009_add_ai_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ark_insight_reports ──────────────────────────────────────────
    op.create_table(
        "ark_insight_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column(
            "report_type",
            sa.Enum(
                "industry_daily",
                "ai_tools",
                "shop_analysis",
                "competitor_analysis",
                "inquiry_analysis",
                name="insight_report_type",
            ),
            nullable=False,
            comment="报告类型",
        ),
        sa.Column("report_date", sa.Date, nullable=False, comment="报告所属日期"),
        sa.Column("title", sa.String(255), nullable=False, server_default="", comment="报告标题"),
        sa.Column("html_content", sa.dialects.mysql.LONGTEXT, nullable=True, comment="HTML 正文"),
        sa.Column("file_path", sa.String(512), nullable=True, comment="静态 HTML 文件路径"),
        sa.Column("source_data", sa.JSON, nullable=True, comment="原始数据快照"),
        sa.Column("report_metadata", sa.JSON, nullable=True, comment="附加元数据(shop/week 等)"),
        sa.Column(
            "status",
            sa.Enum("pending", "published", "failed", name="insight_report_status"),
            nullable=False,
            server_default="pending",
            comment="生成状态",
        ),
        sa.Column("error_msg", sa.Text, nullable=True, comment="生成失败错误信息"),
        sa.Column("created_by", sa.Integer, nullable=True, comment="操作人ID(定时任务为NULL)"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("idx_insight_report_date", "report_date"),
        sa.Index("idx_insight_report_status", "status"),
        sa.Index("idx_insight_report_created_at", "created_at"),
        sa.Index("idx_insight_report_type_date", "report_type", "report_date"),
        comment="方舟洞见-报告主表",
    )

    # ── ark_insight_sources ──────────────────────────────────────────
    op.create_table(
        "ark_insight_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("name", sa.String(100), nullable=False, comment="信源名称"),
        sa.Column(
            "source_type",
            sa.Enum(
                "google_alerts_rss",
                "pinterest_scrape",
                "google_trends_rss",
                "amazon_bestseller",
                "competitor_rss",
                "competitor_html",
                "aihot_api",
                name="insight_source_type",
            ),
            nullable=False,
            comment="信源类型",
        ),
        sa.Column("url", sa.String(1024), nullable=False, comment="信源URL"),
        sa.Column("keywords", sa.JSON, nullable=True, comment="RSS 关键词过滤"),
        sa.Column("css_selector", sa.String(512), nullable=True, comment="HTML 爬虫 CSS 选择器"),
        sa.Column("request_headers", sa.JSON, nullable=True, comment="自定义请求头"),
        sa.Column(
            "fetch_interval_hours",
            sa.SmallInteger,
            nullable=False,
            server_default="24",
            comment="抓取间隔(小时)",
        ),
        sa.Column("last_fetched_at", sa.DateTime, nullable=True, comment="最近成功抓取时间"),
        sa.Column("last_error", sa.Text, nullable=True, comment="最近抓取错误信息"),
        sa.Column(
            "consecutive_failures",
            sa.SmallInteger,
            nullable=False,
            server_default="0",
            comment="连续失败次数",
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1"), comment="是否启用"),
        sa.Column(
            "pipeline",
            sa.Enum("external", "internal", name="insight_source_pipeline"),
            nullable=False,
            server_default="external",
            comment="所属管线",
        ),
        sa.Column("sort_order", sa.SmallInteger, nullable=False, server_default="0", comment="排序"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("idx_insight_source_type", "source_type"),
        sa.Index("idx_insight_source_is_active", "is_active"),
        sa.Index("idx_insight_source_pipeline", "pipeline"),
        comment="方舟洞见-情报信源配置",
    )

    # ── ark_case_library ──────────────────────────────────────────
    op.create_table(
        "ark_case_library",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("title", sa.String(200), nullable=False, server_default="", comment="案例标题"),
        sa.Column("scenario", sa.Text, nullable=True, comment="场景描述"),
        sa.Column("what_was_done", sa.Text, nullable=True, comment="做了什么"),
        sa.Column("result", sa.Text, nullable=True, comment="结果"),
        sa.Column("customer_name", sa.String(200), nullable=True, comment="客户名称"),
        sa.Column("tags", sa.JSON, nullable=True, comment="标签数组"),
        sa.Column("attachments", sa.JSON, nullable=True, comment="附件数组"),
        sa.Column("highlights", sa.JSON, nullable=True, comment="AI 提取的核心亮点(兼容字段)"),
        sa.Column("customer_type", sa.String(50), nullable=True, comment="客户类型(批发/零售/沙龙)"),
        sa.Column("market", sa.String(50), nullable=True, comment="目标市场"),
        sa.Column("product_type", sa.String(50), nullable=True, comment="产品类型"),
        sa.Column("key_phrases", sa.JSON, nullable=True, comment="关键话术"),
        sa.Column("raw_summary", sa.Text, nullable=True, comment="AI 摘要"),
        sa.Column("original_content", sa.dialects.mysql.MEDIUMTEXT, nullable=True, comment="原始输入内容"),
        sa.Column(
            "source_type",
            sa.Enum("screenshot", "text_paste", "manual", name="insight_case_source_type"),
            nullable=False,
            server_default="manual",
            comment="上传方式",
        ),
        sa.Column("image_path", sa.String(512), nullable=True, comment="截图文件路径"),
        sa.Column("share_person", sa.String(50), nullable=False, server_default="", comment="分享人姓名"),
        sa.Column("share_date", sa.Date, nullable=True, comment="分享日期"),
        sa.Column("uploaded_by", sa.Integer, nullable=False, comment="上传人用户ID"),
        sa.Column(
            "status",
            sa.Enum("draft", "published", "archived", "processing", "failed", name="insight_case_status"),
            nullable=False,
            server_default="draft",
            comment="状态",
        ),
        sa.Column("error_msg", sa.Text, nullable=True, comment="处理失败信息"),
        sa.Column("like_count", sa.Integer, nullable=False, server_default="0", comment="认可数"),
        sa.Column("view_count", sa.Integer, nullable=False, server_default="0", comment="查看次数"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("idx_case_status", "status"),
        sa.Index("idx_case_share_person", "share_person"),
        sa.Index("idx_case_share_date", "share_date"),
        sa.Index("idx_case_market", "market"),
        sa.Index("idx_case_product_type", "product_type"),
        sa.Index("idx_case_uploaded_by", "uploaded_by"),
        comment="方舟洞见-业务员案例库",
    )

    # FULLTEXT 索引(中文 ngram)需要原生 SQL
    op.execute(
        "CREATE FULLTEXT INDEX ft_case_search ON ark_case_library "
        "(title, scenario, what_was_done, result) WITH PARSER ngram"
    )

    # ── ark_meeting_minutes ──────────────────────────────────────────
    op.create_table(
        "ark_meeting_minutes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("meeting_date", sa.Date, nullable=False, comment="会议日期"),
        sa.Column("title", sa.String(200), nullable=False, server_default="", comment="会议主题"),
        sa.Column("duration", sa.String(20), nullable=True, comment="时长(如 '90min')"),
        sa.Column("participants", sa.String(500), nullable=True, comment="参与人姓名串"),
        sa.Column("original_text", sa.dialects.mysql.LONGTEXT, nullable=False, comment="原始转录文本"),
        sa.Column("summary_md", sa.dialects.mysql.MEDIUMTEXT, nullable=True, comment="精要版 Markdown"),
        sa.Column("structured_summary", sa.JSON, nullable=True, comment="结构化精要(topics/decisions/action_items/outcome)"),
        sa.Column("tasks_json", sa.JSON, nullable=True, comment="任务清单冗余JSON"),
        sa.Column("source_url", sa.String(512), nullable=True, comment="原文链接"),
        sa.Column("has_attachment", sa.Boolean, nullable=False, server_default=sa.text("0"), comment="是否含附件"),
        sa.Column("word_count_original", sa.Integer, nullable=True, comment="原文字数"),
        sa.Column("word_count_summary", sa.Integer, nullable=True, comment="精要字数"),
        sa.Column(
            "status",
            sa.Enum("processing", "published", "failed", name="insight_minutes_status"),
            nullable=False,
            server_default="processing",
            comment="处理状态",
        ),
        sa.Column("error_msg", sa.Text, nullable=True, comment="处理失败信息"),
        sa.Column("uploaded_by", sa.Integer, nullable=False, comment="上传人用户ID"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("idx_minutes_meeting_date", "meeting_date"),
        sa.Index("idx_minutes_status", "status"),
        sa.Index("idx_minutes_uploaded_by", "uploaded_by"),
        comment="方舟洞见-周会纪要",
    )

    # ── ark_insight_tasks ──────────────────────────────────────────
    op.create_table(
        "ark_insight_tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column(
            "minutes_id",
            sa.Integer,
            sa.ForeignKey("ark_meeting_minutes.id", ondelete="CASCADE"),
            nullable=False,
            comment="关联会议纪要ID",
        ),
        sa.Column("assignee", sa.String(50), nullable=False, server_default="待定", comment="责任人姓名"),
        sa.Column("description", sa.String(500), nullable=False, comment="任务描述"),
        sa.Column("deadline", sa.Date, nullable=True, comment="截止日期"),
        sa.Column(
            "priority",
            sa.Enum("high", "medium", "low", name="insight_task_priority"),
            nullable=False,
            server_default="medium",
            comment="优先级",
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "in_progress", "completed", "overdue", name="insight_task_status"),
            nullable=False,
            server_default="pending",
            comment="任务状态",
        ),
        sa.Column("source_quote", sa.String(500), nullable=True, comment="原文依据"),
        sa.Column("completed_at", sa.DateTime, nullable=True, comment="完成时间"),
        sa.Column("completed_by", sa.Integer, nullable=True, comment="标记完成的用户ID"),
        sa.Column("notes", sa.Text, nullable=True, comment="跟进备注"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("idx_task_minutes_id", "minutes_id"),
        sa.Index("idx_task_assignee", "assignee"),
        sa.Index("idx_task_deadline", "deadline"),
        sa.Index("idx_task_status", "status"),
        sa.Index("idx_task_priority", "priority"),
        comment="方舟洞见-任务执行清单",
    )


def downgrade() -> None:
    op.drop_table("ark_insight_tasks")
    op.drop_table("ark_meeting_minutes")
    op.execute("DROP INDEX ft_case_search ON ark_case_library")
    op.drop_table("ark_case_library")
    op.drop_table("ark_insight_sources")
    op.drop_table("ark_insight_reports")
