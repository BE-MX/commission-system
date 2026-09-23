"""OKKI 销售出库单自动生成任务队列（发票首推小满成功后的下游触发）。

发票首推成功后由 xiaoman_service.sync_invoice 落一行任务（ark_okki_outbound_tasks），
singapore 主机 okki-sync 的轮询器（deploy/okki_outbound_poller.js）消费并执行
okki_outbound_creator.mjs。任务表是跨系统唯一事实来源：

- 同一 OKKI order_id 仅一行（唯一约束），并由执行端实时核查 OKKI 关联出库单、持久提交意图与台账防重；
- 含未建品非标合并行的发票落 skipped（通用产品出库无拣货意义），人工在 OKKI 处理；
- 首推部分受理（okki_accepted）不会走到这里——sync_invoice 只在大成功收尾时入队；
- 入队/对账均为尽力而为：异常只记日志，绝不阻断同步主流程。
"""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.invoice.models import CustomProduct, Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.invoice.time_utils import beijing_now

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"

RECONCILE_LIMIT = 200

SKIP_REASON_GENERIC_MERGE = "含未建品非标行（合并通用产品推送），不自动生成出库单"


def has_unbackfilled_custom_lines(db: Session, invoice: Invoice) -> bool:
    """存在未回填 OKKI 产品/SKU 的非标行（推单时合并为一条通用产品行）。

    与 xiaoman_service._build_product_rows 的合并口径一致：custom 行的
    CustomProduct 已回填 okki_product_id + okki_sku_id 即视为真实产品行。
    """
    for item in invoice.items:
        if item.item_type != "custom":
            continue
        custom = db.get(CustomProduct, item.custom_product_id) if item.custom_product_id else None
        if not (custom and custom.okki_product_id and custom.okki_sku_id):
            return True
    return False


def enqueue_outbound_task(db: Session, invoice: Invoice) -> OkkiOutboundTask | None:
    """为首推成功的发票入队出库任务；同 order_id 幂等（重复调用返回既有行）。

    只 flush，commit 由调用方负责——同步钩子路径上任务行与同步状态同事务落库，
    上层回滚（如半成品 finalize 失败）会连带丢弃任务行，不会产生孤儿任务。
    """
    if invoice.order_type == "presale":
        return None
    order_id = str(invoice.xiaoman_order_id or "").strip()
    if not order_id:
        return None
    existing = (
        db.query(OkkiOutboundTask)
        .filter(OkkiOutboundTask.order_id == order_id)
        .first()
    )
    if existing:
        return existing
    skipped = has_unbackfilled_custom_lines(db, invoice)
    row = OkkiOutboundTask(
        invoice_id=invoice.id,
        order_id=order_id,
        status=STATUS_SKIPPED if skipped else STATUS_PENDING,
        reason=SKIP_REASON_GENERIC_MERGE if skipped else None,
    )
    try:
        # 唯一约束是并发入队的最终防线：撞约束即读赢家行。add 必须放进 savepoint
        # 块内（块退出时随 RELEASE 落盘）——在块外 add + 块内 flush 的写法撞约束后
        # 会话会被毒化（PendingRollbackError），兜底重查和后续 commit 全失败。
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        row = (
            db.query(OkkiOutboundTask)
            .filter(OkkiOutboundTask.order_id == order_id)
            .first()
        )
    return row


def reconcile_missing_outbound_tasks(
    db: Session,
    *,
    limit: int = RECONCILE_LIMIT,
) -> dict:
    """对账补入队：已登记自动出库、首推成功、当前 synced、但无任务行的发票。

    「首推」按首张 action=create 且 success=1 的同步日志时间判定——历史订单
    编辑重推（update）不补，避免给功能上线前的老订单回头建出库单。首推部分
    受理（sync_status≠synced）由人工核对重推，成功后自然进入本口径。
    """
    first_create = (
        db.query(
            InvoiceSyncLog.invoice_id.label("invoice_id"),
            func.min(InvoiceSyncLog.created_at).label("first_at"),
        )
        .filter(InvoiceSyncLog.action == "create", InvoiceSyncLog.success == 1)
        .group_by(InvoiceSyncLog.invoice_id)
        .subquery()
    )
    invoices = (
        db.query(Invoice)
        .join(first_create, first_create.c.invoice_id == Invoice.id)
        .outerjoin(OkkiOutboundTask, OkkiOutboundTask.order_id == Invoice.xiaoman_order_id)
        .filter(
            Invoice.sync_status == "synced",
            Invoice.xiaoman_order_id.isnot(None),
            Invoice.xiaoman_order_id != "",
            Invoice.outbound_auto_requested == 1,
            Invoice.order_type != "presale",
            Invoice.status.notin_(["cancel_pending", "cancelled"]),
            OkkiOutboundTask.id.is_(None),
        )
        .order_by(Invoice.id)
        .limit(limit)
        .all()
    )
    enqueued = skipped = 0
    for invoice in invoices:
        # 逐行隔离：单张发票数据异常（如 order_id 超长）只记日志，不拖垮整批
        try:
            row = enqueue_outbound_task(db, invoice)
        except Exception as exc:  # noqa: BLE001 - 对账是兜底通道，逐行容错
            logger.warning("okki outbound reconcile enqueue failed invoice=%s: %s", invoice.id, exc)
            print(f"[outbound] reconcile enqueue failed invoice={invoice.id}: {exc}", flush=True)
            continue
        if row is None:
            continue
        if row.status == STATUS_SKIPPED:
            skipped += 1
        elif row.status == STATUS_PENDING:
            enqueued += 1
    stats = {"scanned": len(invoices), "enqueued": enqueued, "skipped": skipped}
    if invoices:
        logger.info("okki outbound reconcile: %s", stats)
        print(f"[outbound] reconcile missing tasks: {stats}", flush=True)
    return stats


def retry_reviewed(db, invoice, actor, reason, expected_version):
    """Explicitly recover a missed or definitively unsent task; never replay uncertainty."""
    if invoice.order_type == "presale":
        raise ValueError("预售单请处理原发货结算，不补建整单出库")
    from app.invoice import linked_outbound_service, service
    from app.invoice.linked_sync_service import ensure_idle, edit_version
    from app.invoice.lifecycle_guard import ensure_mutable
    from app.invoice.cancellation_service import audit
    from app.receipt import remote
    ensure_idle(invoice)
    ensure_mutable(db, invoice)
    if invoice.sync_status != "synced" or edit_version(invoice) != expected_version:
        raise ValueError("订单未同步或已变化，请刷新后处理")
    remote.order_snapshot(db, invoice)
    order = remote.read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
    if linked_outbound_service.find_related(db, order):
        raise ValueError("已有出库单，请在小满办理补发或退货，不能整单重建")
    invoice = service.get_invoice(db, invoice.id, for_update=True)
    ensure_mutable(db, invoice)
    if edit_version(invoice) != expected_version or invoice.sync_status != "synced":
        raise ValueError("核对期间订单已变化，请重新处理")
    if has_unbackfilled_custom_lines(db, invoice):
        raise ValueError("非标产品尚未补齐真实产品与SKU，请先建品并重新同步订单")
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).with_for_update().first()
    if task and not (task.status == "failed" or
                     (task.status == "skipped" and task.reason == SKIP_REASON_GENERIC_MERGE)):
        raise ValueError("仅明确未发送、非标建品后或漏建任务可恢复；已创建、已删除及待核对任务请人工处理")
    invoice.outbound_auto_requested = 1
    task = task or enqueue_outbound_task(db, invoice)
    task.status, task.reason, task.last_error, task.attempts = "pending", None, None, 0
    audit(db, invoice, "outbound_retry", actor, {"reason": reason, "task_id": task.id})
    return {"status": "pending", "message": "已核实无关联出库单，恢复自动出库；执行端仍会实时查重"}
