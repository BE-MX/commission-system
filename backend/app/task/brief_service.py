"""每日简报（一期不含 git）：未结束叶子任务确定性排序 → AI 从前 12 个候选里挑 3 个并给理由；
AI 失败或越界则用模板理由。同一 owner 同一天只生成一次、只推送一次。本模块只 flush，提交由调用方负责。"""
import json
import logging
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.task.ai_service import parse_json
from app.task.models import CLOSED_STATUSES, PRIORITIES, PRIORITY_LABELS, TaskBrief, TaskItem

logger = logging.getLogger("commission")

BRIEF_PRESET = "task_brief"
TOP_N = 3
AI_CANDIDATES = 12


def _open_tasks(db: Session, owner_id: int) -> list[TaskItem]:
    return db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.is_(None),
                                     TaskItem.status.notin_(CLOSED_STATUSES)).all()


def rank_candidates(db: Session, owner_id: int, today: date) -> list[TaskItem]:
    tasks = _open_tasks(db, owner_id)
    parent_ids = {t.parent_id for t in tasks if t.parent_id}
    leaves = [t for t in tasks if t.id not in parent_ids and t.status != "pending_confirm"]

    def key(t: TaskItem):
        overdue = bool(t.due_date and t.due_date < today)
        return (t.priority != "P0", not overdue, t.due_date or date.max, PRIORITIES.index(t.priority), t.id)

    return sorted(leaves, key=key)


def _template_reason(t: TaskItem, today: date) -> str:
    if t.priority == "P0":
        return "P0 紧急"
    if t.due_date and t.due_date < today:
        return f"已逾期 {(today - t.due_date).days} 天"
    if t.due_date == today:
        return "今天到期"
    if t.due_date:
        return f"{(t.due_date - today).days} 天后到期"
    return f"重要性 {t.priority} {PRIORITY_LABELS[t.priority]}"


def _counts(db: Session, owner_id: int, today: date) -> dict:
    tasks = _open_tasks(db, owner_id)
    return {
        "pending_confirm": sum(1 for t in tasks if t.status == "pending_confirm"),
        "overdue": sum(1 for t in tasks if t.due_date and t.due_date < today),
        "blocked": sum(1 for t in tasks if t.status == "blocked"),
    }


def _item(t: TaskItem, reason: str) -> dict:
    return {"id": t.id, "code": t.code, "title": t.title, "priority": t.priority, "reason": reason[:120]}


def build_template(db: Session, owner_id: int, today: date) -> dict:
    top = [_item(t, _template_reason(t, today)) for t in rank_candidates(db, owner_id, today)[:TOP_N]]
    return {"top": top, **_counts(db, owner_id, today)}


def build_content(db: Session, owner_id: int, today: date) -> tuple[dict, str]:
    ranked = rank_candidates(db, owner_id, today)[:AI_CANDIDATES]
    if not ranked:
        return build_template(db, owner_id, today), "template"
    payload = {
        "today": today.isoformat(),
        "priorities": dict(PRIORITY_LABELS),
        "candidates": [{"id": t.id, "title": t.title, "priority": t.priority, "status": t.status,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "blocked_reason": t.blocked_reason} for t in ranked],
    }
    try:
        from app.ai.service import chat
        result = chat(db=db, preset_name=BRIEF_PRESET, caller_module="task", caller_user_id=owner_id,
                      messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        picks = parse_json(result.get("content", "")).get("top") or []
        by_id = {t.id: t for t in ranked}
        top, seen = [], set()
        for p in picks:
            if not isinstance(p, dict):
                continue
            tid, reason = p.get("id"), str(p.get("reason") or "").strip()
            if tid in by_id and tid not in seen and reason:
                top.append(_item(by_id[tid], reason))
                seen.add(tid)
            if len(top) == TOP_N:
                break
        if not top:
            raise ValueError("AI 没有给出有效候选")
        return {"top": top, **_counts(db, owner_id, today)}, "ai"
    except Exception as exc:  # noqa: BLE001 — 简报失败降级为模板，不影响推送
        logger.warning("task brief degraded: %s", type(exc).__name__)
        print(f"[task] brief degraded: {type(exc).__name__}: {exc}", flush=True)
        return build_template(db, owner_id, today), "template"


def get_or_create_brief(db: Session, owner_id: int, today: date | None = None) -> TaskBrief:
    today = today or beijing_today()
    row = db.query(TaskBrief).filter_by(owner_id=owner_id, brief_date=today).first()
    if row:
        return row
    content, source = build_content(db, owner_id, today)
    row = TaskBrief(owner_id=owner_id, brief_date=today, content_json=content, source=source)
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # 页面请求与定时任务并发生成：以先写入的为准
        return db.query(TaskBrief).filter_by(owner_id=owner_id, brief_date=today).one()
    return row


def serialize_brief(row: TaskBrief) -> dict:
    return {"brief_date": row.brief_date.isoformat(), "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "pushed_at": row.pushed_at.isoformat() if row.pushed_at else None, **row.content_json}


def render_markdown(content: dict, today: date) -> str:
    lines = [f"### 任务简报 {today.strftime('%m/%d')}", "", "**今天建议先做：**"]
    for i, t in enumerate(content.get("top") or [], 1):
        lines.append(f"{i}. **{t['code']}** {t['title']} —— {t['reason']}")
    if not content.get("top"):
        lines.append("没有未结束的任务。")
    lines += ["", f"待确认 {content.get('pending_confirm', 0)} · 逾期 {content.get('overdue', 0)} · "
                  f"受阻 {content.get('blocked', 0)}"]
    return "\n".join(lines)


def owners_with_open_tasks(db: Session) -> list[int]:
    return [r[0] for r in db.query(TaskItem.owner_id).filter(
        TaskItem.deleted_at.is_(None), TaskItem.status.notin_(CLOSED_STATUSES)).distinct().all()]


def prepare_pushes(db: Session, today: date, commit=None) -> list[dict]:
    """同步：为每个有未结束任务的 owner 生成当日简报，返回待推送清单（已推送或无钉钉 ID 的跳过）。
    会调用 AI，必须在线程池里执行。commit 由调用方传入（scheduler 传 db.commit）。"""
    from app.auth.models import ArkUser

    pushes = []
    for owner_id in owners_with_open_tasks(db):
        try:
            brief = get_or_create_brief(db, owner_id, today)
            if commit:
                commit()
            user = db.get(ArkUser, owner_id)
            if brief.pushed_at or not (user and user.dingtalk_id):
                continue
            pushes.append({"brief_id": brief.id, "dingtalk_id": user.dingtalk_id,
                           "title": f"任务简报 {today.strftime('%m/%d')}",
                           "markdown": render_markdown(brief.content_json, today)})
        except Exception as exc:  # noqa: BLE001 — 单个 owner 失败不影响其他人
            db.rollback()
            logger.warning("task brief prepare failed owner=%s: %s", owner_id, type(exc).__name__)
            print(f"[task] brief prepare failed owner={owner_id}: {type(exc).__name__}: {exc}", flush=True)
    return pushes


async def send_pushes(pushes: list[dict]) -> list[int]:
    """异步：在主事件循环里调钉钉工作通知，返回发送成功的 brief_id。"""
    from app.dingtalk.work_notify import get_work_notifier

    notifier, ok_ids = get_work_notifier(), []
    for p in pushes:
        try:
            if await notifier.send_to_users(user_ids=[p["dingtalk_id"]], title=p["title"], markdown_text=p["markdown"]):
                ok_ids.append(p["brief_id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("task brief send failed brief=%s: %s", p["brief_id"], type(exc).__name__)
            print(f"[task] brief send failed brief={p['brief_id']}: {type(exc).__name__}: {exc}", flush=True)
    return ok_ids


def mark_pushed(db: Session, brief_ids: list[int]) -> None:
    if brief_ids:
        db.query(TaskBrief).filter(TaskBrief.id.in_(brief_ids)).update(
            {TaskBrief.pushed_at: beijing_now()}, synchronize_session="fetch")
        db.flush()
