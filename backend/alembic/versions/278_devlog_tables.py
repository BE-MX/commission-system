"""方舟开发动态：事项、证据、状态事件、发布账本、同步记录。"""
from alembic import op
import sqlalchemy as sa

revision = "278_devlog_tables"
down_revision = "277_cross_border_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_devlog_items",
        sa.Column("id", sa.Integer(), nullable=False, comment="事项主键"),
        sa.Column("item_key", sa.String(191), nullable=False, comment="采集器稳定键，如 branch:codex/x、merge:<sha>、commit:<sha>"),
        sa.Column("title", sa.String(80), nullable=False, comment="去敏后的标题"),
        sa.Column("item_type", sa.String(16), nullable=False, comment="feature/improve/bug/data/ops/docs"),
        sa.Column("module", sa.String(40), nullable=False, comment="影响模块标识，取源码领域目录名"),
        sa.Column("agent", sa.String(16), nullable=False, comment="codex/claude/kimi/accio/unknown"),
        sa.Column("status", sa.String(16), nullable=False, comment="dev/pending_merge/pending_push/pending_release/released"),
        sa.Column("status_at", sa.DateTime(), nullable=False, comment="进入当前状态的北京时间（采集器按证据估计）"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False, comment="最后一条证据的北京时间"),
        sa.Column("stale", sa.Boolean(), nullable=False, comment="未发布且 14 天无新证据"),
        sa.Column("superseded", sa.Boolean(), nullable=False, comment="在完整快照中已不存在（分支清理等），默认不展示，不删除"),
        sa.Column("unmerged_hotfix", sa.Boolean(), nullable=False, comment="已进全局发布但内容未回合 main"),
        sa.Column("released_revision", sa.String(40), nullable=True, comment="首次覆盖本事项的全局发布 revision"),
        sa.Column("preconditions", sa.JSON(), nullable=False, comment="上线前提：migrations/config_keys/permissions"),
        sa.Column("fingerprint", sa.String(64), nullable=False, comment="证据与状态指纹，相同则跳过更新"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="首次采集北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="最后更新北京时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_key"),
        comment="开发动态事项（一件事）",
    )
    op.create_table(
        "ark_devlog_evidences",
        sa.Column("id", sa.Integer(), nullable=False, comment="证据主键"),
        sa.Column("item_id", sa.Integer(), nullable=False, comment="所属事项"),
        sa.Column("kind", sa.String(16), nullable=False, comment="branch/commit/release/worktree"),
        sa.Column("ref", sa.String(120), nullable=False, comment="分支名、commit sha、发布 revision 或 worktree 标识"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, comment="证据发生北京时间"),
        sa.ForeignKeyConstraint(["item_id"], ["ark_devlog_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "kind", "ref", name="uq_devlog_evidence"),
        comment="开发动态事项的结构化证据（只存标识，不存原文）",
    )
    op.create_index("ix_ark_devlog_evidences_item_id", "ark_devlog_evidences", ["item_id"])
    op.create_table(
        "ark_devlog_item_events",
        sa.Column("id", sa.Integer(), nullable=False, comment="事件主键"),
        sa.Column("item_id", sa.Integer(), nullable=False, comment="所属事项"),
        sa.Column("from_status", sa.String(16), nullable=True, comment="变化前状态，首次出现为空"),
        sa.Column("to_status", sa.String(16), nullable=False, comment="变化后状态"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, comment="状态发生北京时间"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, comment="服务端记录北京时间"),
        sa.ForeignKeyConstraint(["item_id"], ["ark_devlog_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="开发动态事项状态变化事件，统计按事件时间落桶",
    )
    op.create_index("ix_ark_devlog_item_events_item_id", "ark_devlog_item_events", ["item_id"])
    op.create_index("idx_devlog_event_time", "ark_devlog_item_events", ["occurred_at"])
    op.create_table(
        "ark_devlog_releases",
        sa.Column("id", sa.Integer(), nullable=False, comment="账本主键"),
        sa.Column("revision", sa.String(40), nullable=False, comment="实际发布的完整 commit"),
        sa.Column("release_id", sa.String(64), nullable=False, comment="部署器发布身份或回填标识"),
        sa.Column("scope", sa.String(20), nullable=False, comment="office-and-cloud 为全局发布；cloud-only 等为专项"),
        sa.Column("released_at", sa.DateTime(), nullable=False, comment="发布验收通过北京时间"),
        sa.Column("source", sa.String(16), nullable=False, comment="deployer/backfill"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="写入北京时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id"),
        comment="方舟发布账本（部署器写入或人工回填）",
    )
    op.create_index("ix_ark_devlog_releases_revision", "ark_devlog_releases", ["revision"])
    op.create_table(
        "ark_devlog_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False, comment="同步记录主键"),
        sa.Column("started_at", sa.DateTime(), nullable=False, comment="采集开始北京时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=False, comment="采集结束北京时间"),
        sa.Column("sources", sa.JSON(), nullable=False, comment="各来源读取结果 [{name, ok, detail}]"),
        sa.Column("item_count", sa.Integer(), nullable=False, comment="本次上报事项数"),
        sa.Column("failed_keys", sa.JSON(), nullable=False, comment="服务端写入失败的事项键"),
        sa.Column("snapshot_complete", sa.Boolean(), nullable=False, comment="全量快照且所有来源与事项写入成功"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="服务端接收北京时间"),
        sa.PrimaryKeyConstraint("id"),
        comment="开发机采集器每次上报记录",
    )


def downgrade():
    op.drop_table("ark_devlog_sync_runs")
    op.drop_index("ix_ark_devlog_releases_revision", table_name="ark_devlog_releases")
    op.drop_table("ark_devlog_releases")
    op.drop_index("idx_devlog_event_time", table_name="ark_devlog_item_events")
    op.drop_index("ix_ark_devlog_item_events_item_id", table_name="ark_devlog_item_events")
    op.drop_table("ark_devlog_item_events")
    op.drop_index("ix_ark_devlog_evidences_item_id", table_name="ark_devlog_evidences")
    op.drop_table("ark_devlog_evidences")
    op.drop_table("ark_devlog_items")
