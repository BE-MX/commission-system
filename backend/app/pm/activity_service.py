"""PM Hub 全站动态（审计日志的用户侧呈现）+ 总览仪表盘聚合。"""

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.pm.material_service import list_materials
from app.pm.models import PmActivityLog, PmMaterial, PmMaterialVersion, PmTask, bj_now
from app.pm.service import DONE_STATUSES

logger = logging.getLogger("commission")

ACTION_LABELS = {
    "entry": "进入了站点",
    "create_material": "新增资料",
    "update_material": "更新了资料",
    "delete_material": "删除了资料",
    "upload_version": "上传了新版本",
    "edit_version": "在线编辑保存了新版本",
    "delete_version": "删除了版本",
    "retry_diff": "重试差异概要",
    "create_task": "创建了任务",
    "update_task": "更新了任务",
    "delete_task": "删除了任务",
}


def _display_names(db: Session) -> dict[str, str]:
    from app.pm.models import PmMember
    return {m.username: m.display_name for m in db.query(PmMember).all()}


def log_to_dict(log: PmActivityLog, display_names: dict[str, str],
                diff_hint: Optional[str] = None) -> dict:
    detail = None
    if log.detail:
        try:
            detail = json.loads(log.detail)
        except (json.JSONDecodeError, TypeError):
            detail = {"raw": log.detail}
    return {
        "id": log.id,
        "username": log.username,
        "display_name": display_names.get(log.username, log.username),
        "action": log.action,
        "action_label": ACTION_LABELS.get(log.action, log.action),
        "object_type": log.object_type,
        "object_id": log.object_id,
        "object_name": log.object_name,
        "detail": detail,
        "diff_hint": diff_hint,
        "created_at": log.created_at.isoformat(sep=" ") if log.created_at else None,
    }


def list_activity(db: Session, project_id: int, username: Optional[str] = None,
                  object_type: Optional[str] = None, limit: int = 50,
                  offset: int = 0) -> dict:
    q = db.query(PmActivityLog).filter(PmActivityLog.project_id == project_id)
    if username:
        q = q.filter(PmActivityLog.username == username)
    if object_type:
        q = q.filter(PmActivityLog.object_type == object_type)
    total = q.count()
    logs = q.order_by(PmActivityLog.id.desc()).offset(offset).limit(limit).all()
    names = _display_names(db)
    hints = _diff_hints(db, [l for l in logs if l.object_type == "version" and l.action in ("upload_version", "edit_version")])
    return {
        "total": total,
        "items": [log_to_dict(l, names, hints.get(l.object_id)) for l in logs],
    }


def _diff_hints(db: Session, logs: list[PmActivityLog]) -> dict[int, str]:
    """上传类动态附 AI 差异的一句话摘要（取概要首行要点）。"""
    version_ids = [l.object_id for l in logs if l.object_id]
    if not version_ids:
        return {}
    versions = (
        db.query(PmMaterialVersion)
        .filter(PmMaterialVersion.id.in_(version_ids))
        .all()
    )
    hints: dict[int, str] = {}
    for v in versions:
        if v.diff_status == "done" and v.diff_summary:
            first = next(
                (ln.strip(" ·-") for ln in v.diff_summary.splitlines()
                 if ln.strip().startswith(("·", "-", "新", "修", "删")) and len(ln.strip()) > 2),
                v.diff_summary.strip().splitlines()[0] if v.diff_summary.strip() else "",
            )
            hints[v.id] = first[:120]
        elif v.diff_status == "pending":
            hints[v.id] = "AI 差异概要生成中…"
    return hints


# ── 仪表盘 ───────────────────────────────────────────────────────────

def dashboard(db: Session, project_id: int) -> dict:
    materials = list_materials(db, project_id)
    tasks = (
        db.query(PmTask)
        .filter(PmTask.project_id == project_id, PmTask.deleted_at.is_(None))
        .all()
    )

    def mat_done(m: dict) -> bool:
        return m["status"] in DONE_STATUSES

    total = len(materials)
    done = sum(1 for m in materials if mat_done(m))
    required = [m for m in materials if m["importance"] == "required"]
    required_done = sum(1 for m in required if mat_done(m))

    # 按重要级分组的状态统计（点击穿透到资料库对应筛选）
    by_importance: dict[str, dict] = {}
    for imp in ("required", "important", "optional"):
        group = [m for m in materials if m["importance"] == imp]
        status_counts: dict[str, int] = {}
        for m in group:
            status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1
        by_importance[imp] = {
            "total": len(group),
            "done": sum(1 for m in group if mat_done(m)),
            "status_counts": status_counts,
        }

    # 按顾问 Phase 1-4 的分段进度
    phases: list[dict] = []
    for p in (1, 2, 3, 4):
        group = [m for m in materials if m["phase"] == p]
        phases.append({
            "phase": p,
            "total": len(group),
            "done": sum(1 for m in group if mat_done(m)),
            "required_total": sum(1 for m in group if m["importance"] == "required"),
            "required_done": sum(1 for m in group if m["importance"] == "required" and mat_done(m)),
        })

    task_total = len(tasks)
    task_done = sum(1 for t in tasks if t.status == "done")
    task_counts: dict[str, int] = {}
    for t in tasks:
        task_counts[t.status] = task_counts.get(t.status, 0) + 1

    today = bj_now().date()  # 与全模块北京时间口径一致，不用服务器本地时区
    overdue = [
        {"id": t.id, "title": t.title, "assignee": t.assignee, "due_date": t.due_date.isoformat()}
        for t in tasks
        if t.due_date and t.due_date < today and t.status not in ("done",)
    ]
    # Phase 1 未齐的必须材料（不齐则核心链路跑不起来）
    phase1_gaps = [
        {"id": m["id"], "name": m["name"], "status": m["status"], "owner": m["owner"]}
        for m in materials
        if m["phase"] == 1 and m["importance"] == "required" and not mat_done(m)
    ]

    names = _display_names(db)
    logs = (
        db.query(PmActivityLog)
        .filter(PmActivityLog.project_id == project_id, PmActivityLog.action != "entry")
        .order_by(PmActivityLog.id.desc())
        .limit(10)
        .all()
    )
    hints = _diff_hints(db, [l for l in logs if l.object_type == "version" and l.action in ("upload_version", "edit_version")])

    return {
        "materials": {
            "total": total,
            "done": done,
            "rate": round(done / total, 4) if total else 0,
            "required_total": len(required),
            "required_done": required_done,
            "required_rate": round(required_done / len(required), 4) if required else 0,
            "by_importance": by_importance,
        },
        "tasks": {
            "total": task_total,
            "done": task_done,
            "rate": round(task_done / task_total, 4) if task_total else 0,
            "status_counts": task_counts,
        },
        "phases": phases,
        "risks": {"overdue_tasks": overdue, "phase1_required_gaps": phase1_gaps},
        "recent": [log_to_dict(l, names, hints.get(l.object_id)) for l in logs],
    }
