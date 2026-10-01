"""任务中心数据模型。全部按 owner_id 隔离；编号 T-<id> 由自增主键派生，不另建序列。"""
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

USER_ID = mysql.INTEGER(unsigned=True)

PRIORITIES = ("P0", "P1", "P2", "P3")
PRIORITY_LABELS = {"P0": "紧急", "P1": "高", "P2": "中", "P3": "低"}
STATUSES = ("todo", "in_progress", "blocked", "pending_confirm", "done", "shelved")
STATUS_LABELS = {
    "todo": "待办", "in_progress": "进行中", "blocked": "受阻",
    "pending_confirm": "待确认", "done": "已完成", "shelved": "已搁置",
}
OPEN_STATUSES = ("todo", "in_progress", "blocked")
CLOSED_STATUSES = ("done", "shelved")
MODULE_KINDS = ("nav", "infra", "custom")
LINK_KINDS = ("doc", "prototype", "url")  # 二期追加 branch / commit / merge
SOURCES = ("manual", "nav_quick", "header_quick", "ai_split", "mcp")
MAX_DEPTH = 4


class TaskModule(Base):
    __tablename__ = "ark_task_modules"
    __table_args__ = {"comment": "任务中心-模块注册表（nav 条目来自构建期导出的 navigation 清单）"}

    key = Column(String(100), primary_key=True, comment="模块键：nav=前端路由 name；infra.* / custom.*")
    kind = Column(String(10), nullable=False, comment="nav/infra/custom")
    group_key = Column(String(64), nullable=False, default="", comment="分组键")
    group_title = Column(String(64), nullable=False, default="", comment="分组名称")
    title = Column(String(100), nullable=False, comment="模块名称")
    route = Column(String(200), nullable=True, comment="前端路由 path（nav 才有）")
    sort_order = Column(Integer, nullable=False, default=0, comment="组内排序")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="私有分类所有者；公共条目为空")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否有效（清单中消失即置 0，旧任务保留引用）")
    synced_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="最近同步时间")


class TaskItem(Base):
    __tablename__ = "ark_task_items"
    __table_args__ = (
        Index("idx_ark_task_items_owner_status", "owner_id", "status"),
        Index("idx_ark_task_items_owner_parent", "owner_id", "parent_id"),
        {"comment": "任务中心-任务（树形，parent_id 自关联）"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键；编号 T-<id>")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="所有者 ark_users.id")
    parent_id = Column(BigInteger, ForeignKey("ark_task_items.id"), nullable=True, comment="父任务 ark_task_items.id")
    title = Column(String(200), nullable=False, comment="标题")
    description = Column(Text, nullable=True, comment="描述")
    acceptance = Column(JSON, nullable=True, comment="验收标准列表（AI 提议完成的对照依据）")
    priority = Column(String(2), nullable=False, default="P2", comment="P0 紧急/P1 高/P2 中/P3 低")
    status = Column(String(20), nullable=False, default="todo", comment="todo/in_progress/blocked/pending_confirm/done/shelved")
    blocked_reason = Column(String(500), nullable=True, comment="受阻原因（置 blocked 必填）")
    module_key = Column(String(100), ForeignKey("ark_task_modules.key"), nullable=True, comment="关联模块 ark_task_modules.key")
    due_date = Column(Date, nullable=True, comment="截止日期（北京时间）")
    sort_order = Column(Integer, nullable=False, default=0, comment="同级排序")
    source = Column(String(20), nullable=False, default="manual", comment="manual/nav_quick/header_quick/ai_split/mcp")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删时间")
    delete_batch = Column(String(32), nullable=True, comment="软删批次号：同一次删除的子树共用，恢复按批次整体还原")

    @property
    def code(self) -> str:
        return f"T-{self.id}"


class TaskLink(Base):
    __tablename__ = "ark_task_links"
    __table_args__ = (
        UniqueConstraint("task_id", "kind", "ref", name="uq_ark_task_links_task_kind_ref"),
        {"comment": "任务中心-任务关联（一期 doc/prototype/url；二期 git 类）"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(BigInteger, ForeignKey("ark_task_items.id"), nullable=False, comment="任务 ark_task_items.id")
    kind = Column(String(20), nullable=False, comment="doc/prototype/url（二期 branch/commit/merge）")
    ref = Column(String(500), nullable=False, comment="仓库路径 / URL / sha")
    title = Column(String(200), nullable=False, default="", comment="显示名")
    match = Column(String(10), nullable=False, default="exact", comment="exact/suggested")
    status = Column(String(10), nullable=False, default="active", comment="active/pending/rejected")
    payload_json = Column(JSON, nullable=True, comment="附加信息")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")


class TaskEvent(Base):
    __tablename__ = "ark_task_events"
    __table_args__ = (
        Index("idx_ark_task_events_task", "task_id"),
        {"comment": "任务中心-任务时间线"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(BigInteger, ForeignKey("ark_task_items.id"), nullable=False, comment="任务 ark_task_items.id")
    actor = Column(String(10), nullable=False, comment="user/ai/reporter/mcp")
    type = Column(String(30), nullable=False, comment="created/updated/status_changed/moved/deleted/restored/linked/unlinked")
    payload_json = Column(JSON, nullable=True, comment="事件详情")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="发生时间")


class TaskBrief(Base):
    __tablename__ = "ark_task_briefs"
    __table_args__ = (
        UniqueConstraint("owner_id", "brief_date", name="uq_ark_task_briefs_owner_date"),
        {"comment": "任务中心-每日简报"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="所有者 ark_users.id")
    brief_date = Column(Date, nullable=False, comment="简报日期（北京时间）")
    content_json = Column(JSON, nullable=False, comment="简报内容：top/pending_confirm/overdue/blocked")
    source = Column(String(10), nullable=False, comment="ai/template")
    pushed_at = Column(DateTime, nullable=True, comment="钉钉推送时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="生成时间")
