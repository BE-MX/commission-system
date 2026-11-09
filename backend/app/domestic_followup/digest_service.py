"""跟进推送发件箱：每日汇总 + 紧急异常（规格 4.5）。

准备与标记是同步 DB 操作（线程池）；send 是 async，在主事件循环里调钉钉。
"""
import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import config_service
from app.domestic_followup.constants import OPEN_ITEM_STATES, TRACKED_KINDS, URGENT, URGENT_MAX_ATTEMPTS
from app.domestic_followup.date_parser import weekday_label
from app.domestic_followup.models import DomesticFollowupDigest, DomesticFollowupItem, DomesticFollowupTask

logger = logging.getLogger("commission")
Digest = DomesticFollowupDigest
SECTION_NAMES = 5  # 每类最多列几个店名
NO_DUE_TASKS = "待办转移或结束后无可推送事项"


def workbench_url(customer_id: int | None = None) -> str:
    base = get_settings().DOMESTIC_REVIEW_NOTICE_BASE_URL.rstrip("/") + "/domestic/followups"
    return f"{base}?customer={customer_id}" if customer_id else f"{base}?tab=tasks"


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


def _active_user_filter():
    return ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)


def _warn_skipped_inactive(db: Session, today: date) -> None:
    """停用/删除员工名下的到期待办不推送：记下条数，提醒管理员在客户档案里改归属。"""
    active_ids = select(ArkUser.id).where(*_active_user_filter())
    skipped = (db.query(func.count(DomesticFollowupTask.id))
               .filter(DomesticFollowupTask.status == "todo", DomesticFollowupTask.due_date <= today,
                       DomesticFollowupTask.assignee_user_id.not_in(active_ids))
               .scalar()) or 0
    if skipped:
        logger.warning("followup daily digest skipped %s due task(s) of inactive assignees", skipped)
        print(f"[domestic_followup] daily digest skipped {skipped} due task(s) of inactive assignees", flush=True)


def build_daily(db: Session, today: date) -> int:
    rows = (db.query(DomesticFollowupTask)
            .join(ArkUser, ArkUser.id == DomesticFollowupTask.assignee_user_id)
            .filter(DomesticFollowupTask.status == "todo", DomesticFollowupTask.due_date <= today,
                    *_active_user_filter())
            .order_by(DomesticFollowupTask.due_date, DomesticFollowupTask.id).all())
    _warn_skipped_inactive(db, today)
    by_user: dict[int, list] = defaultdict(list)
    for task in rows:
        by_user[task.assignee_user_id].append(task)
    created = 0
    for user_id, tasks in by_user.items():
        title, markdown = render_daily(tasks, today)
        suppressed = db.query(Digest).filter(
            Digest.user_id == user_id, Digest.digest_date == today, Digest.kind == "daily",
            Digest.ref_key == "", Digest.pushed_at.is_(None), Digest.last_error == NO_DUE_TASKS,
        ).populate_existing().with_for_update().first()
        if suppressed:
            suppressed.attempts, suppressed.last_error = 0, None
            suppressed.title, suppressed.markdown = title[:100], markdown
            continue
        created += _insert(db, Digest(user_id=user_id, digest_date=today, kind="daily", ref_key="",
                                      title=title[:100], markdown=markdown))
    return created


def enqueue_urgent(db: Session, item, customer, followup, *, today: date | None = None) -> int:
    receivers = config_service.get_config(db)["urgent_receiver_user_ids"] or []
    if not receivers:
        logger.warning("urgent followup item=%s has no receiver configured", item.id)
        print(f"[domestic_followup] urgent item={item.id}: no receiver configured", flush=True)
        return 0
    configured = list(dict.fromkeys(receivers))
    active = {row[0] for row in db.query(ArkUser.id).filter(ArkUser.id.in_(configured), *_active_user_filter())}
    skipped = [user_id for user_id in configured if user_id not in active]
    if skipped:
        logger.warning("urgent followup item=%s skips missing/inactive receivers %s", item.id, skipped)
        print(f"[domestic_followup] urgent item={item.id}: skip missing/inactive receivers {skipped}", flush=True)
    author = db.get(ArkUser, followup.author_user_id)
    markdown = "\n".join([
        f"### 紧急异常：{customer.shop_name}",
        f"- **{item.category or '其他'}**：{item.text}",
        f"- 录入：{author.real_name if author else followup.author_user_id}，{followup.followup_date.isoformat()}",
        f"\n[查看客户跟进]({workbench_url(customer.id)})",
    ])
    created = 0
    for user_id in (u for u in configured if u in active):
        created += _insert(db, Digest(user_id=user_id, digest_date=today or beijing_today(), kind="urgent",
                                      ref_key=f"item:{item.id}", title=f"紧急异常·{customer.shop_name}"[:100],
                                      markdown=markdown))
    return created


SEND_LEASE_MINUTES = 5


def available_claim():
    return or_(Digest.send_claimed_at.is_(None),
               Digest.send_claimed_at < beijing_now() - timedelta(minutes=SEND_LEASE_MINUTES))


def pending(db: Session, kind: str, today: date) -> list[dict]:
    query = (db.query(Digest, ArkUser.dingtalk_id).join(ArkUser, ArkUser.id == Digest.user_id)
             .filter(Digest.kind == kind, Digest.pushed_at.is_(None), Digest.attempts < URGENT_MAX_ATTEMPTS,
                     available_claim(), *_active_user_filter()))
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


def claim(db: Session, digest_id: int) -> dict | None:
    pair = (db.query(Digest, ArkUser.dingtalk_id).join(ArkUser, ArkUser.id == Digest.user_id)
            .filter(Digest.id == digest_id, Digest.pushed_at.is_(None), Digest.attempts < URGENT_MAX_ATTEMPTS,
                    available_claim(), *_active_user_filter()).populate_existing().with_for_update().first())
    if pair is None or not pair[1]:
        return None
    row, dingtalk_id = pair
    if row.kind == "daily":
        tasks = (db.query(DomesticFollowupTask)
                 .filter(DomesticFollowupTask.assignee_user_id == row.user_id,
                         DomesticFollowupTask.status == "todo", DomesticFollowupTask.due_date <= row.digest_date)
                 .order_by(DomesticFollowupTask.due_date, DomesticFollowupTask.id)
                 .populate_existing().with_for_update().all())
        if not tasks:
            row.attempts, row.last_error = URGENT_MAX_ATTEMPTS, NO_DUE_TASKS
            db.flush()
            return None
        title, row.markdown = render_daily(tasks, row.digest_date)
        row.title = title[:100]
    elif row.kind == "urgent":
        # A previous in-flight attempt may have failed while an edit changed the item.
        item_id = int(row.ref_key.split(":", 1)[1]) if row.ref_key.startswith("item:") else None
        item = (db.query(DomesticFollowupItem).filter(DomesticFollowupItem.id == item_id)
                .populate_existing().first()) if item_id else None
        if item is None or item.status not in OPEN_ITEM_STATES or item.severity != "紧急":
            row.attempts, row.last_error = URGENT_MAX_ATTEMPTS, "跟进修改后取消紧急提醒"
            db.flush()
            return None
        customer = db.get(DomesticCustomer, item.customer_id)
        row.markdown = (f"### 紧急异常：{customer.shop_name}\n- **{item.category or '其他'}**：{item.text}"
                        f"\n[查看客户跟进]({workbench_url(customer.id)})")
    row.send_claimed_at = beijing_now()
    db.flush()
    return {"digest_id": row.id, "dingtalk_id": dingtalk_id, "title": row.title, "markdown": row.markdown}


async def send(pushes: list[dict], claim_message) -> tuple[list[int], list[int]]:
    from app.dingtalk.work_notify import get_work_notifier

    notifier, ok_ids, failed = get_work_notifier(), [], []
    for p in pushes:
        # Re-read and claim after prepare; an intervening edit can cancel or change this message.
        p = await claim_message(p)
        if p is None:
            continue
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
        digest.send_claimed_at = None
        if digest.id in ok_ids:
            digest.pushed_at = now
        else:
            digest.attempts += 1
            digest.last_error = "钉钉发送失败"
    db.flush()
