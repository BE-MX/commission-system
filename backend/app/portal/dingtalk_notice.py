"""Internal DingTalk group notices for new portal requests and issued PIs.

Business commands only enqueue a reference row in the same transaction. The
worker renders from current database state at send time, links only to the
authenticated Ark order page, and never auto-resends an uncertain delivery.
"""
import asyncio
import logging
import re
import secrets
from datetime import timedelta

import httpx
from sqlalchemy import and_, or_, select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal.authority import lock_authority
from app.portal.configuration import employee_origin
from app.portal.errors import PortalError
from app.portal.mail_worker import LEASE_SECONDS, MAX_ATTEMPTS, RETRY_MINUTES, close_event, leased_event
from app.portal.models import CustomerAccess, OrderRequest, OutboxEvent

logger = logging.getLogger(__name__)
EVENT = "dingtalk_notice"
SOURCES = {"order_submitted", "order_invoice_created"}


def enabled(settings=None):
    settings = settings or get_settings()
    return bool(settings.PORTAL_DINGTALK_WEBHOOK_URL)


def enqueue(db, source, request_id, now):
    if source not in SOURCES or not enabled():
        return
    db.add(OutboxEvent(event_key=f"dingtalk:{source}:{request_id}", event_type=EVENT,
        aggregate_public_id=request_id, payload_json={"request_id": request_id, "source": source},
        next_attempt_at=now))


def claim(db):
    lock_authority(db, force=True)
    now = beijing_now()
    row = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == EVENT, or_(
        and_(OutboxEvent.status == "pending", OutboxEvent.next_attempt_at <= now),
        and_(OutboxEvent.status == "sending", OutboxEvent.lease_until <= now)))
        .order_by(OutboxEvent.next_attempt_at, OutboxEvent.id).limit(1).with_for_update())
    if row is None:
        return None
    if row.status == "sending":
        # A previous worker may have delivered before losing its lease: never resend.
        close_event(row, "uncertain", "LEASE_LOST_DURING_SEND")
        return None
    if row.attempt_count >= MAX_ATTEMPTS:
        close_event(row, "dead", "ATTEMPTS_EXHAUSTED")
        return None
    row.status, row.attempt_count = "sending", row.attempt_count + 1
    row.lease_token, row.lease_until = secrets.token_hex(32), now + timedelta(seconds=LEASE_SECONDS)
    db.flush()
    return row.public_id, row.lease_token


def _plain(value):
    """Customer-entered text must not become Markdown links, mentions or headings."""
    return " ".join(re.sub(r"[\[\]()*_#>`!\\|@]", "", str(value or "")).split())[:120]


def _amounts(revision):
    if revision.total_amount is not None:
        return f"{revision.currency} {revision.total_amount:.2f}", None
    return f"{revision.currency} {revision.product_amount:.2f}（仅货款）", "运费待业务报价"


def _weight(records):
    weights = [record.unit_weight_grams * record.qty for record in records if record.unit_weight_grams is not None]
    if not weights:
        return "—"
    grams = sum(weights)
    text = f"{grams / 1000:.2f} kg" if grams >= 1000 else f"{grams.normalize():f} g"
    return text if len(weights) == len(records) else text + "（部分商品重量未知）"


def render(db, row):
    """Returns (title, markdown) or None when the order is gone or outside the site."""
    from app.customer.models import CustomerAccount
    from app.portal import order_queries
    from app.portal.models import Account
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == row.aggregate_public_id)
        .execution_options(populate_existing=True))
    if order is None or row.payload_json.get("request_id") != order.public_id:
        return None
    access = db.get(CustomerAccess, order.access_id, populate_existing=True)
    customer = db.get(CustomerAccount, access.customer_id) if access else None
    company = _plain(customer.canonical_company_name or customer.display_name) if customer else "未知客户"
    account = db.get(Account, order.account_id)
    contact = _plain(account.contact_name) if account and account.contact_name else ""
    revision, records = order_queries.load_revision(db, order)
    total, note = _amounts(revision)
    link = employee_origin(get_settings()) + "/portal/orders?request=" + order.public_id
    payment = _plain((revision.payment_terms_snapshot or {}).get("method_label")
                     or (revision.payment_terms_snapshot or {}).get("code"))
    lines = [f"**客户**：{company}" + (f"（{contact}）" if contact else ""),
             f"**请求号**：{order.public_no}", f"**金额**：{total}", f"**总重量**：{_weight(records)}"]
    if payment:
        lines.append(f"**付款方式**：{payment}")
    if row.payload_json["source"] == "order_submitted":
        title = "门户新订单待审核"
        lines.append("**下一步**：" + (note or "核对后在方舟一键审核生成正式 PI"))
        button = "在方舟审核订单"
    else:
        from app.invoice.models import Invoice
        invoice = db.get(Invoice, order.invoice_id) if order.invoice_id else None
        title = "门户订单正式 PI 已生成"
        if invoice is not None:
            lines.insert(1, f"**PI 号**：{_plain(invoice.invoice_no)}")
        lines.append("**下一步**：客户已可在门户下载 PI，可在方舟下载 PI 并安排出库")
        button = "下载 PI / 查看订单"
    text = f"### {title}\n\n" + "\n\n".join(lines) + f"\n\n[{button}]({link})\n\n> 通知不代表锁货或收款。"
    return title, text


def send(title, text, sender=None):
    from app.dingtalk.webhook import WebhookSender
    settings = get_settings()
    notifier = sender or WebhookSender(settings.PORTAL_DINGTALK_WEBHOOK_URL, settings.PORTAL_DINGTALK_WEBHOOK_SECRET)
    return asyncio.run(notifier.send_markdown(title, text))


def run_once(session_factory, sender=None):
    if not (get_settings().PORTAL_ENABLED and enabled()):
        return "disabled"
    with session_factory() as db:
        leased = claim(db)
        db.commit()
    if leased is None:
        return "idle"
    public_id, lease = leased
    with session_factory() as db:
        row = leased_event(db, public_id, lease)
        try:
            message = render(db, row) if row is not None else None
        except PortalError:
            message = None  # Tampered/unavailable revision evidence: do not announce it.
        if row is not None and message is None:
            close_event(row, "cancelled", "NOTIFICATION_OBJECT_INVALID")
        db.commit()
    if message is None:
        return "cancelled" if row is not None else "lease_lost"
    from app.dingtalk.webhook import DingTalkWebhookError
    try:
        result = send(*message, sender=sender)
        outcome = "sent" if result.get("errcode") == 0 else "uncertain"
        error = None if outcome == "sent" else "UNEXPECTED_RESPONSE"
    except Exception as exc:
        definite = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) or (
            isinstance(exc, DingTalkWebhookError) and not exc.delivery_uncertain)
        outcome, error = ("retry", "DINGTALK_SEND_FAILED") if definite else ("uncertain", "DINGTALK_DELIVERY_UNCERTAIN")
        # Never log exception text: network errors may contain the signed webhook URL.
        logger.warning("Portal DingTalk notice %s: type=%s", outcome, type(exc).__name__)
    with session_factory() as db:
        row = leased_event(db, public_id, lease)
        if row is None:
            db.commit()
            return "lease_lost"
        if outcome in {"sent", "uncertain"} or row.attempt_count >= MAX_ATTEMPTS:
            close_event(row, outcome if outcome != "retry" else "dead", error)
        else:
            row.status, row.last_error_code = "pending", error
            row.next_attempt_at = beijing_now() + timedelta(minutes=RETRY_MINUTES[row.attempt_count - 1])
            row.lease_token = row.lease_until = None
        status = row.status
        db.commit()
    return status
