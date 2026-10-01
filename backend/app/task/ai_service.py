"""一句话建任务：AI 生成草稿，用户确认后才写库。

值域全部运行时注入 user message（模块来自 ark_task_modules，优先级来自代码常量，
候选父任务/重复任务来自该 owner 的未结束任务）；preset 的 system prompt 只描述输出格式。
AI 输出逐字段校验，越界值回落到预填值；调用失败整体降级为原文标题。
"""
import json
import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from app.core.time import beijing_today
from app.task import module_service
from app.task.errors import TaskInvalid
from app.task.models import CLOSED_STATUSES, PRIORITIES, PRIORITY_LABELS, TaskItem

logger = logging.getLogger("commission")

DRAFT_PRESET = "task_draft"
MAX_TEXT = 1000
MAX_CANDIDATES = 30


def parse_json(content: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("AI 返回内容不是 JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("AI 返回内容不是 JSON 对象")
    return data


def _open_candidates(db: Session, owner_id: int, module_key: str | None) -> list[TaskItem]:
    q = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.is_(None),
                                  TaskItem.status.notin_(CLOSED_STATUSES))
    if module_key:
        q = q.filter(TaskItem.module_key == module_key)
    return q.order_by(TaskItem.updated_at.desc()).limit(MAX_CANDIDATES).all()


def _fallback(text: str, module_key, parent_id, notice: str) -> dict:
    return {"title": text[:200], "priority": "P2", "acceptance": [], "module_key": module_key,
            "parent_id": parent_id, "due_date": None, "duplicates": [], "degraded": True, "notice": notice}


def draft_task(db: Session, owner_id: int, text: str, *, module_key: str | None = None,
               parent_id: int | None = None, today: date | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise TaskInvalid("先写一句话说明要做什么")
    text = text[:MAX_TEXT]
    today = today or beijing_today()
    module_key = module_service.ensure_usable(db, owner_id, module_key)
    modules = module_service.list_modules(db, owner_id)
    candidates = _open_candidates(db, owner_id, module_key)
    candidate_ids = {t.id for t in candidates}
    if parent_id is not None and parent_id not in candidate_ids:
        parent = db.query(TaskItem).filter(TaskItem.id == parent_id, TaskItem.owner_id == owner_id,
                                           TaskItem.deleted_at.is_(None)).first()
        if parent is None:
            parent_id = None
        else:
            candidates.append(parent)
            candidate_ids.add(parent.id)

    user_payload = {
        "text": text,
        "today": today.isoformat(),
        "preset_module": module_key,
        "preset_parent_id": parent_id,
        "modules": [{"key": m["key"], "title": m["title"], "group": m["group_title"]} for m in modules],
        "priorities": dict(PRIORITY_LABELS),
        "open_tasks": [{"id": t.id, "title": t.title, "module_key": t.module_key} for t in candidates],
    }
    try:
        from app.ai.service import chat
        result = chat(db=db, preset_name=DRAFT_PRESET, caller_module="task", caller_user_id=owner_id,
                      messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}])
        raw = parse_json(result.get("content", ""))
    except Exception as exc:  # noqa: BLE001 — AI 失败一律降级，不阻断建任务
        logger.warning("task draft degraded: %s", type(exc).__name__)
        print(f"[task] draft degraded: {type(exc).__name__}: {exc}", flush=True)
        return _fallback(text, module_key, parent_id, "AI 暂不可用，已按原文生成草稿")

    module_keys = {m["key"] for m in modules}
    raw_title = raw.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else text
    acceptance = raw.get("acceptance") if isinstance(raw.get("acceptance"), list) else []
    ai_parent = raw.get("parent_id")
    try:
        due = date.fromisoformat(str(raw.get("due_date"))).isoformat() if raw.get("due_date") else None
    except ValueError:
        due = None
    raw_duplicates = raw.get("duplicate_ids") or []
    priority = raw.get("priority")
    ai_module = raw.get("module_key")
    if not isinstance(raw_duplicates, list) or (priority is not None and not isinstance(priority, str)) or (ai_module is not None and not isinstance(ai_module, str)):
        logger.warning("task draft degraded: malformed AI field types")
        print("[task] draft degraded: malformed AI field types", flush=True)
        return _fallback(text, module_key, parent_id, "AI 草稿格式异常，已按原文生成草稿")
    dup_ids = [i for i in raw_duplicates if type(i) is int and i in candidate_ids][:3]
    by_id = {t.id: t for t in candidates}
    return {
        "title": title[:200],
        "priority": priority if priority in PRIORITIES else "P2",
        "acceptance": [a.strip()[:200] for a in acceptance if isinstance(a, str) and a.strip()][:5],
        "module_key": ai_module if ai_module in module_keys else module_key,
        "parent_id": ai_parent if isinstance(ai_parent, int) and ai_parent in candidate_ids else parent_id,
        "due_date": due,
        "duplicates": [{"id": i, "code": by_id[i].code, "title": by_id[i].title} for i in dup_ids],
        "degraded": False,
        "notice": None,
    }
