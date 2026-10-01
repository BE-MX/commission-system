"""任务中心模块注册表。

nav 条目的唯一来源是前端 navigation.js：构建期由 vite 插件导出 dist/nav-manifest.json，
后端启动时读取同步（见 bootstrap/seed_task.py）。浏览器不参与同步，避免多环境版本来回翻转。
"""
import json
import logging
import secrets
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.task.errors import TaskInvalid
from app.task.models import TaskModule

logger = logging.getLogger("commission")

# (key, kind, group_key, group_title, title, sort)
DEFAULT_MODULES = (
    ("infra.backend", "infra", "infra", "工程域", "后端基建", 1),
    ("infra.deploy", "infra", "infra", "工程域", "部署发布", 2),
    ("infra.mini", "infra", "infra", "工程域", "微信小程序", 3),
    ("infra.docs", "infra", "infra", "工程域", "文档与规范", 4),
    ("custom.report", "custom", "custom", "方舟外", "汇报材料", 1),
    ("custom.research", "custom", "custom", "方舟外", "调研", 2),
    ("custom.admin", "custom", "custom", "方舟外", "部门行政", 3),
)
_KIND_ORDER = {"nav": 0, "infra": 1, "custom": 2}


def seed_default_modules(db: Session) -> None:
    for key, kind, group_key, group_title, title, sort in DEFAULT_MODULES:
        row = db.get(TaskModule, key)
        if row is None:
            db.add(TaskModule(key=key, kind=kind, group_key=group_key, group_title=group_title,
                              title=title, sort_order=sort, is_active=True))
    db.flush()


def load_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sync_nav_manifest(db: Session, manifest: dict) -> dict:
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not entries:
        raise ValueError("导航清单为空，保留现有模块注册表")
    now = beijing_now()
    seen = set()
    for entry in entries:
        key = str(entry["key"])[:100]
        seen.add(key)
        row = db.get(TaskModule, key)
        if row is None:
            row = TaskModule(key=key, kind="nav")
            db.add(row)
        row.kind = "nav"
        row.title = str(entry.get("title") or key)[:100]
        row.group_key = str(entry.get("group_key") or "")[:64]
        row.group_title = str(entry.get("group_title") or "")[:64]
        row.route = entry.get("route")
        row.sort_order = int(entry.get("sort") or 0)
        row.is_active = True
        row.synced_at = now
    stale = db.query(TaskModule).filter(TaskModule.kind == "nav", TaskModule.is_active.is_(True),
                                        TaskModule.key.notin_(seen)).all()
    for row in stale:
        row.is_active = False
        row.synced_at = now
    db.flush()
    return {"upserted": len(seen), "deactivated": len(stale)}


def _visible_query(db: Session, owner_id: int):
    return db.query(TaskModule).filter(or_(TaskModule.owner_id.is_(None), TaskModule.owner_id == owner_id))


def serialize_module(row: TaskModule) -> dict:
    return {"key": row.key, "kind": row.kind, "group_key": row.group_key, "group_title": row.group_title,
            "title": row.title, "route": row.route, "is_active": row.is_active, "is_private": row.owner_id is not None}


def list_modules(db: Session, owner_id: int, include_inactive: bool = False) -> list[dict]:
    q = _visible_query(db, owner_id)
    if not include_inactive:
        q = q.filter(TaskModule.is_active.is_(True))
    # nav 的 sort_order 由清单编码为「分组序号*1000 + 组内序号」，因此直接按 sort_order 排序即可保持导航顺序
    rows = sorted(q.all(), key=lambda m: (_KIND_ORDER.get(m.kind, 9), m.sort_order, m.key))
    return [serialize_module(r) for r in rows]


def ensure_usable(db: Session, owner_id: int, key: str | None) -> str | None:
    """新建/改关联时校验模块可用；None 表示不关联模块。已停用模块不允许新关联。"""
    if key is None:
        return None
    row = db.get(TaskModule, key)
    if row is None or not row.is_active or (row.owner_id is not None and row.owner_id != owner_id):
        raise TaskInvalid("关联的模块不存在或已停用")
    return key


def add_custom(db: Session, owner_id: int, title: str) -> str:
    title = (title or "").strip()
    if not title or len(title) > 100:
        raise TaskInvalid("分类名称需为 1~100 个字")
    key = f"custom.u{owner_id}.{secrets.token_hex(4)}"
    db.add(TaskModule(key=key, kind="custom", group_key="custom", group_title="方舟外", title=title,
                      sort_order=100, owner_id=owner_id, is_active=True))
    db.flush()
    return key


def deactivate_custom(db: Session, owner_id: int, key: str) -> None:
    row = db.get(TaskModule, key)
    if row is None or row.owner_id != owner_id:
        raise TaskInvalid("只能停用自己新建的分类")
    row.is_active = False
    db.flush()
