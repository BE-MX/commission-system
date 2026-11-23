"""开发动态的事项、证据、状态事件、全局发布账本与采集同步记录。

状态只由采集器按 Git 证据计算后上报，服务端不推断；证据只存结构化标识，不存任何原文。
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now

ITEM_STATUSES = ("dev", "pending_merge", "pending_push", "pending_release", "released")
GLOBAL_SCOPE = "office-and-cloud"


class DevlogItem(Base):
    __tablename__ = "ark_devlog_items"
    __table_args__ = {"comment": "开发动态事项（一件事）"}

    id = Column(Integer, primary_key=True, comment="事项主键")
    item_key = Column(String(191), nullable=False, unique=True, comment="采集器稳定键，如 branch:codex/x、merge:<sha>、commit:<sha>")
    title = Column(String(80), nullable=False, comment="去敏后的标题")
    item_type = Column(String(16), nullable=False, comment="feature/improve/bug/data/ops/docs")
    module = Column(String(40), nullable=False, default="", comment="影响模块标识，取源码领域目录名")
    agent = Column(String(16), nullable=False, default="unknown", comment="codex/claude/kimi/accio/unknown")
    status = Column(String(16), nullable=False, comment="dev/pending_merge/pending_push/pending_release/released")
    status_at = Column(DateTime, nullable=False, comment="进入当前状态的北京时间（采集器按证据估计）")
    last_activity_at = Column(DateTime, nullable=False, comment="最后一条证据的北京时间")
    stale = Column(Boolean, nullable=False, default=False, comment="未发布且 14 天无新证据")
    superseded = Column(Boolean, nullable=False, default=False, comment="在完整快照中已不存在（分支清理等），默认不展示，不删除")
    unmerged_hotfix = Column(Boolean, nullable=False, default=False, comment="已进全局发布但内容未回合 main")
    released_revision = Column(String(40), nullable=True, comment="首次覆盖本事项的全局发布 revision")
    preconditions = Column(JSON, nullable=False, comment="上线前提：migrations/config_keys/permissions")
    fingerprint = Column(String(64), nullable=False, comment="证据与状态指纹，相同则跳过更新")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="首次采集北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="最后更新北京时间")


class DevlogEvidence(Base):
    __tablename__ = "ark_devlog_evidences"
    __table_args__ = (
        UniqueConstraint("item_id", "kind", "ref", name="uq_devlog_evidence"),
        {"comment": "开发动态事项的结构化证据（只存标识，不存原文）"},
    )

    id = Column(Integer, primary_key=True, comment="证据主键")
    item_id = Column(Integer, ForeignKey("ark_devlog_items.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属事项")
    kind = Column(String(16), nullable=False, comment="branch/commit/release/worktree")
    ref = Column(String(120), nullable=False, comment="分支名、commit sha、发布 revision 或 worktree 标识")
    occurred_at = Column(DateTime, nullable=False, comment="证据发生北京时间")


class DevlogItemEvent(Base):
    __tablename__ = "ark_devlog_item_events"
    __table_args__ = (
        Index("idx_devlog_event_time", "occurred_at"),
        {"comment": "开发动态事项状态变化事件，统计按事件时间落桶"},
    )

    id = Column(Integer, primary_key=True, comment="事件主键")
    item_id = Column(Integer, ForeignKey("ark_devlog_items.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属事项")
    from_status = Column(String(16), nullable=True, comment="变化前状态，首次出现为空")
    to_status = Column(String(16), nullable=False, comment="变化后状态")
    occurred_at = Column(DateTime, nullable=False, comment="状态发生北京时间")
    recorded_at = Column(DateTime, nullable=False, default=beijing_now, comment="服务端记录北京时间")


class DevlogRelease(Base):
    __tablename__ = "ark_devlog_releases"
    __table_args__ = {"comment": "方舟发布账本（部署器写入或人工回填）"}

    id = Column(Integer, primary_key=True, comment="账本主键")
    revision = Column(String(40), nullable=False, index=True, comment="实际发布的完整 commit")
    release_id = Column(String(64), nullable=False, unique=True, comment="部署器发布身份或回填标识")
    scope = Column(String(20), nullable=False, comment="office-and-cloud 为全局发布；cloud-only 等为专项")
    released_at = Column(DateTime, nullable=False, comment="发布验收通过北京时间")
    source = Column(String(16), nullable=False, comment="deployer/backfill")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="写入北京时间")


class DevlogSyncRun(Base):
    __tablename__ = "ark_devlog_sync_runs"
    __table_args__ = {"comment": "开发机采集器每次上报记录"}

    id = Column(Integer, primary_key=True, comment="同步记录主键")
    started_at = Column(DateTime, nullable=False, comment="采集开始北京时间")
    finished_at = Column(DateTime, nullable=False, comment="采集结束北京时间")
    sources = Column(JSON, nullable=False, comment="各来源读取结果 [{name, ok, detail}]")
    item_count = Column(Integer, nullable=False, comment="本次上报事项数")
    failed_keys = Column(JSON, nullable=False, comment="服务端写入失败的事项键")
    snapshot_complete = Column(Boolean, nullable=False, default=False, comment="全量快照且所有来源与事项写入成功")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="服务端接收北京时间")
