"""Task center phase 1: modules, items, links, events, daily briefs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "173_task_center"
down_revision = "172_workbench_lifecycle"
branch_labels = None
depends_on = None

USER_ID = mysql.INTEGER(unsigned=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade():
    op.create_table(
        "ark_task_modules",
        sa.Column("key", sa.String(100), primary_key=True, comment="模块键：nav=前端路由 name；infra.* / custom.*"),
        sa.Column("kind", sa.String(10), nullable=False, comment="nav/infra/custom"),
        sa.Column("group_key", sa.String(64), nullable=False, server_default="", comment="分组键"),
        sa.Column("group_title", sa.String(64), nullable=False, server_default="", comment="分组名称"),
        sa.Column("title", sa.String(100), nullable=False, comment="模块名称"),
        sa.Column("route", sa.String(200), nullable=True, comment="前端路由 path（nav 才有）"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="组内排序"),
        sa.Column("owner_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=True, comment="私有分类所有者；公共条目为空"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), comment="是否有效"),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="最近同步时间"),
        comment="任务中心-模块注册表（nav 条目来自构建期导出的 navigation 清单）",
    )
    op.create_table(
        "ark_task_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键；编号 T-<id>"),
        sa.Column("owner_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="所有者 ark_users.id"),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("ark_task_items.id"), nullable=True, comment="父任务"),
        sa.Column("title", sa.String(200), nullable=False, comment="标题"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("acceptance", sa.JSON(), nullable=True, comment="验收标准列表"),
        sa.Column("priority", sa.String(2), nullable=False, server_default="P2", comment="P0/P1/P2/P3"),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo", comment="任务状态"),
        sa.Column("blocked_reason", sa.String(500), nullable=True, comment="受阻原因"),
        sa.Column("module_key", sa.String(100), sa.ForeignKey("ark_task_modules.key"), nullable=True, comment="关联模块"),
        sa.Column("due_date", sa.Date(), nullable=True, comment="截止日期（北京时间）"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="同级排序"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual", comment="创建来源"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="更新时间"),
        sa.Column("completed_at", sa.DateTime(), nullable=True, comment="完成时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删时间"),
        sa.Column("delete_batch", sa.String(32), nullable=True, comment="软删批次号：同一次删除的子树共用"),
        comment="任务中心-任务（树形，parent_id 自关联）",
    )
    op.create_index("idx_ark_task_items_owner_status", "ark_task_items", ["owner_id", "status"])
    op.create_index("idx_ark_task_items_owner_parent", "ark_task_items", ["owner_id", "parent_id"])
    op.create_table(
        "ark_task_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("ark_task_items.id"), nullable=False, comment="任务"),
        sa.Column("kind", sa.String(20), nullable=False, comment="doc/prototype/url"),
        sa.Column("ref", sa.String(500), nullable=False, comment="仓库路径 / URL / sha"),
        sa.Column("title", sa.String(200), nullable=False, server_default="", comment="显示名"),
        sa.Column("match", sa.String(10), nullable=False, server_default="exact", comment="exact/suggested"),
        sa.Column("status", sa.String(10), nullable=False, server_default="active", comment="active/pending/rejected"),
        sa.Column("payload_json", sa.JSON(), nullable=True, comment="附加信息"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="创建时间"),
        sa.UniqueConstraint("task_id", "kind", "ref", name="uq_ark_task_links_task_kind_ref"),
        comment="任务中心-任务关联",
    )
    op.create_table(
        "ark_task_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("ark_task_items.id"), nullable=False, comment="任务"),
        sa.Column("actor", sa.String(10), nullable=False, comment="user/ai/reporter/mcp"),
        sa.Column("type", sa.String(30), nullable=False, comment="事件类型"),
        sa.Column("payload_json", sa.JSON(), nullable=True, comment="事件详情"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="发生时间"),
        comment="任务中心-任务时间线",
    )
    op.create_index("idx_ark_task_events_task", "ark_task_events", ["task_id"])
    op.create_table(
        "ark_task_briefs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("owner_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="所有者"),
        sa.Column("brief_date", sa.Date(), nullable=False, comment="简报日期（北京时间）"),
        sa.Column("content_json", sa.JSON(), nullable=False, comment="简报内容"),
        sa.Column("source", sa.String(10), nullable=False, comment="ai/template"),
        sa.Column("pushed_at", sa.DateTime(), nullable=True, comment="钉钉推送时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="生成时间"),
        sa.UniqueConstraint("owner_id", "brief_date", name="uq_ark_task_briefs_owner_date"),
        comment="任务中心-每日简报",
    )


def downgrade():
    op.drop_table("ark_task_briefs")
    op.drop_index("idx_ark_task_events_task", table_name="ark_task_events")
    op.drop_table("ark_task_events")
    op.drop_table("ark_task_links")
    op.drop_index("idx_ark_task_items_owner_parent", table_name="ark_task_items")
    op.drop_index("idx_ark_task_items_owner_status", table_name="ark_task_items")
    op.drop_table("ark_task_items")
    op.drop_table("ark_task_modules")
