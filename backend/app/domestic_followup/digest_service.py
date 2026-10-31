"""跟进推送发件箱：每日汇总 + 紧急异常（规格 4.5）。

准备与标记是同步 DB 操作（线程池）；send 是 async，在主事件循环里调钉钉。
"""
import logging
from collections import defaultdict
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today
from app.domestic_followup import config_service
from app.domestic_followup.constants import TRACKED_KINDS, URGENT, URGENT_MAX_ATTEMPTS
from app.domestic_followup.date_parser import weekday_label
from app.domestic_followup.models import DomesticFollowupDigest, DomesticFollowupTask

logger = logging.getLogger("commission")
Digest = DomesticFollowupDigest
SECTION_NAMES = 5  # 每类最多列几个店名


def workbench_url(customer_id: int | None = None) -> str:
    base = get_settings().DOMESTIC_REVIEW_NOTICE_BASE_URL.rstrip("/") + "/domestic/followups"
    return f"{base}?customer={customer_id}" if customer_id else base


def _insert(db: Session, digest: Digest) -> bool:
    exists = db.query(Digest.id).filter(
        Digest.user_id == digest.user_id, Digest.digest_date == digest.digest_date,
        Digest.kind == digest.kind, Digest.ref_key == digest.ref_key,
    ).first()
    if exists:  # 同人同日同类已有一条：09:05/09:15 补发每次都会走到这里，属正常路径
        return False
    savepoint = db.begin_nested()
    try:
        db.add(digest)
        db.flush()
        savepoint.commit()
        return True
    except IntegrityError as exc:
        savepoint.rollback()  # 并发下另一实例先写了同一条
        logger.warning("followup digest insert conflict user=%s kind=%s ref=%s: %s", digest.user_id, digest.kind,
                       digest.ref_key, type(exc.orig).__name__)
        print(f"[domestic_followup] digest insert conflict user={digest.user_id} kind={digest.kind}", flush=True)
        return False


def _shop(title: str) -> str:
    return title.split("：", 1)[0]


def _section(label: str, tasks: list, extra: str = "") -> str:
    names = list(dict.fromkeys(_shop(t.title) for t in tasks))
    shown = "、".join(names[:SECTION_NAMES]) + ("等" if len(names) > SECTION_NAMES else "")
    return f"- **{label} {len(tasks)}{extra}**：{shown}"


def render_daily(tasks: list[DomesticFollowupTask], today: date) -> tuple[str, str]:
    receipt = [t for t in tasks if t.task_type == "receipt"]
    plan = [t for t in tasks if t.task_type == "plan"]
    issue = [t for t in tasks if t.task_type in TRACKED_KINDS]
    lines = [f"### 今日客户跟进（{today.month}月{today.day}日 {weekday_label(today)}）"]
    if receipt:
        lines.append(_section("收货回访", receipt))
    if plan:
        overdue = sum(1 for t in plan if t.due_date < today)
        lines.append(_section("约定跟进", plan, f"（逾期 {overdue}）" if overdue else ""))
    if issue:
        urgent = sum(1 for t in issue if (t.payload or {}).get("severity") == URGENT)
        lines.append(_section("异常意见", issue, f"（紧急 {urgent}）" if urgent else ""))
    lines.append(f"\n[打开跟进工作台]({workbench_url()})")
    return f"今日客户跟进 {len(tasks)} 项", "\n".join(lines)


def build_daily(db: Session, today: date) -> int:
    rows = (db.query(DomesticFollowupTask)
            .filter(DomesticFollowupTask.status == "todo", DomesticFollowupTask.due_date <= today)
            .order_by(DomesticFollowupTask.due_date, DomesticFollowupTask.id).all())
    by_user: dict[int, list] = defaultdict(list)
    for task in rows:
        by_user[task.assignee_user_id].append(task)
    created = 0
    for user_id, tasks in by_user.items():
        title, markdown = render_daily(tasks, today)
        created += _insert(db, Digest(user_id=user_id, digest_date=today, kind="daily", ref_key="",
                                      title=title[:100], markdown=markdown))
    return created


def enqueue_urgent(db: Session, item, customer, followup, *, today: date | None = None) -> int:
    receivers = config_service.get_config(db)["urgent_receiver_user_ids"] or []
    if not receivers:
        logger.warning("urgent followup item=%s has no receiver configured", item.id)
        print(f"[domestic_followup] urgent item={item.id}: no receiver configured", flush=True)
        return 0
    author = db.get(ArkUser, followup.author_user_id)
    markdown = "\n".join([
        f"### 紧急异常：{customer.shop_name}",
        f"- **{item.category or '其他'}**：{item.text}",
        f"- 录入：{author.real_name if author else followup.author_user_id}，{followup.followup_date.isoformat()}",
        f"\n[查看客户跟进]({workbench_url(customer.id)})",
    ])
    created = 0
    for user_id in dict.fromkeys(receivers):
        created += _insert(db, Digest(user_id=user_id, digest_date=today or beijing_today(), kind="urgent",
                                      ref_key=f"item:{item.id}", title=f"紧急异常·{customer.shop_name}"[:100],
                                      markdown=markdown))
    return created


def pending(db: Session, kind: str, today: date) -> list[dict]:
    query = (db.query(Digest, ArkUser.dingtalk_id).join(ArkUser, ArkUser.id == Digest.user_id)
             .filter(Digest.kind == kind, Digest.pushed_at.is_(None), Digest.attempts < URGENT_MAX_ATTEMPTS))
    if kind == "daily":
        query = query.filter(Digest.digest_date == today)  # 错过的旧汇总不补发
    pushes = []
    for digest, dingtalk_id in query.order_by(Digest.id).limit(200).all():
        if not dingtalk_id:
            digest.attempts = URGENT_MAX_ATTEMPTS
            digest.last_error = "接收人未绑定钉钉"
            logger.warning("followup digest=%s skipped: user %s has no dingtalk_id", digest.id, digest.user_id)
            print(f"[domestic_followup] digest={digest.id} skipped: no dingtalk_id", flush=True)
            continue
        pushes.append({"digest_id": digest.id, "dingtalk_id": dingtalk_id,
                       "title": digest.title, "markdown": digest.markdown})
    db.flush()
    return pushes


async def send(pushes: list[dict]) -> tuple[list[int], list[int]]:
    from app.dingtalk.work_notify import get_work_notifier

    notifier, ok_ids, failed = get_work_notifier(), [], []
    for p in pushes:
        try:
            sent = await notifier.send_to_users(user_ids=[p["dingtalk_id"]], title=p["title"],
                                                markdown_text=p["markdown"])
        except Exception as exc:  # noqa: BLE001 — 单条失败计次重试
            sent = False
            logger.warning("followup digest send failed id=%s: %s", p["digest_id"], type(exc).__name__)
            print(f"[domestic_followup] digest send failed id={p['digest_id']}: {type(exc).__name__}", flush=True)
        (ok_ids if sent else failed).append(p["digest_id"])
    return ok_ids, failed


def mark(db: Session, *, ok_ids: list[int], failed_ids: list[int]) -> None:
    now = beijing_now()
    for digest in db.query(Digest).filter(Digest.id.in_(list(ok_ids) + list(failed_ids) or [0])).all():
        if digest.id in ok_ids:
            digest.pushed_at = now
        else:
            digest.attempts += 1
            digest.last_error = "钉钉发送失败"
    db.flush()
