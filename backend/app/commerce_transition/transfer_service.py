"""Freeze and transfer the complete shared economic responsibility closure."""
from sqlalchemy import select

from app.commerce_transition.models import (
    InvoiceAuthority, ResponsibilityGroup, ResponsibilityMember, SendingClaim,
    TransferPreparation,
)
from app.commerce_transition import service as gates
from app.core.time import beijing_now

VERIFICATION_PARTS = ("contract", "funds", "fulfillment", "inventory", "production", "media", "commission")


def _pending_original_requests(db, invoice_ids):
    from app.invoice.models import Invoice, InvoiceLinkedSync, OkkiOutboundTask
    from app.receipt.models import Receipt
    return bool(
        db.query(SendingClaim.id).filter(SendingClaim.invoice_id.in_(invoice_ids),
                                         SendingClaim.state.notin_(gates.TERMINAL)).with_for_update().first()
        or db.query(OkkiOutboundTask.id).filter(OkkiOutboundTask.invoice_id.in_(invoice_ids),
                                               OkkiOutboundTask.status.in_(["running", "uncertain"])).with_for_update().first()
        or db.query(Receipt.id).filter(Receipt.invoice_id.in_(invoice_ids),
                                       Receipt.sync_status.in_(["syncing", "uncertain"])).with_for_update().first()
        or db.query(InvoiceLinkedSync.id).filter(InvoiceLinkedSync.invoice_id.in_(invoice_ids),
                                                 InvoiceLinkedSync.status.in_(["running", "uncertain"])).with_for_update().first()
        or db.query(Invoice.id).filter(Invoice.id.in_(invoice_ids),
                                       Invoice.sync_status.in_(["syncing", "sync_uncertain", "uncertain"])).with_for_update().first())


def register_responsibility(db, *, kind, responsibility_key, members, complete, evidence):
    """Persist known relationships. Corrections expand, never truncate the set.

    Call from original ledger/import transactions. `complete` is a checkpoint
    inventory attestation; an order ID supplied by the transfer client cannot
    manufacture completeness of a shared payment or production batch.
    """
    gates._lock_policy(db)
    gates._key(responsibility_key, "共享责任身份")
    if kind not in {"payment", "production", "reservation", "commission"} or not members:
        raise gates.TransitionError("共享责任类型或完整对象清单无效")
    evidence = gates._evidence(evidence)
    ids = {int(invoice_id) for invoice_id in members}
    authorities = [gates._lock_authority(db, invoice_id) for invoice_id in sorted(ids)]
    if any(a.state != "active" for a in authorities) or len({a.route for a in authorities}) != 1:
        raise gates.TransitionError("共享责任不得跨正式路线或在冻结期间改变")
    row = db.query(ResponsibilityGroup).filter_by(kind=kind, responsibility_key=responsibility_key).populate_existing().with_for_update().first()
    if row is None:
        row = ResponsibilityGroup(kind=kind, responsibility_key=responsibility_key,
                                   complete=bool(complete), evidence=evidence)
        db.add(row)
        db.flush()
    else:
        existing = {m.invoice_id for m in db.query(ResponsibilityMember).filter_by(group_id=row.id).populate_existing().with_for_update()}
        if not existing.issubset(ids):
            raise gates.TransitionError("不能截断已登记的共享责任闭包")
        row.complete, row.evidence = bool(complete), evidence
    by_id = {m.invoice_id: m for m in db.query(ResponsibilityMember).filter_by(group_id=row.id).populate_existing().with_for_update()}
    for invoice_id, amount in members.items():
        invoice_id = int(invoice_id)
        if invoice_id in by_id:
            if amount is not None and by_id[invoice_id].amount != amount:
                raise gates.TransitionError("原已消费责任金额不可覆盖，请登记关联调整")
        else:
            db.add(ResponsibilityMember(group_id=row.id, invoice_id=invoice_id, amount=amount))
    db.flush()
    return row


def responsibility_closure(db, invoice_ids):
    gates._lock_policy(db)
    ids, group_ids = set(map(int, invoice_ids)), set()
    while ids:
        found = set(db.scalars(select(ResponsibilityMember.group_id).where(
            ResponsibilityMember.invoice_id.in_(ids)).with_for_update()))
        new_groups = found - group_ids
        original_ids = set(ids)
        group_ids |= new_groups
        if new_groups:
            ids |= set(db.scalars(select(ResponsibilityMember.invoice_id).where(
                ResponsibilityMember.group_id.in_(new_groups)).with_for_update()))
        # Existing ledgers remain authoritative even if a new relationship
        # registrar has not yet observed their historical rows. Never accept
        # a client-declared group that hides another use of the same payment.
        from app.receipt.models import Receipt
        batches = set(db.scalars(select(Receipt.batch_id).where(
            Receipt.invoice_id.in_(ids), Receipt.batch_id.isnot(None)).with_for_update()))
        if batches:
            ids |= set(db.scalars(select(Receipt.invoice_id).where(Receipt.batch_id.in_(batches)).with_for_update()))
        from app.invoice.models import InvoiceItem
        from app.production.local_models import ProductionSupply
        from app.stock.models import ProductionOrderItem
        production_orders = set(db.scalars(select(ProductionOrderItem.order_id).join(
            ProductionSupply, ProductionSupply.production_item_id == ProductionOrderItem.id).join(
            InvoiceItem, InvoiceItem.id == ProductionSupply.invoice_item_id).where(InvoiceItem.invoice_id.in_(ids)).with_for_update()))
        if production_orders:
            ids |= set(db.scalars(select(InvoiceItem.invoice_id).join(
                ProductionSupply, ProductionSupply.invoice_item_id == InvoiceItem.id).join(
                ProductionOrderItem, ProductionOrderItem.id == ProductionSupply.production_item_id).where(
                    ProductionOrderItem.order_id.in_(production_orders)).with_for_update()))
        if ids == original_ids and not new_groups:
            break
    groups = db.query(ResponsibilityGroup).filter(ResponsibilityGroup.id.in_(group_ids)).populate_existing().with_for_update().all() if group_ids else []
    if any(not group.complete for group in groups):
        raise gates.TransitionError("共享付款、生产或提成责任清单尚未完整核验")
    return sorted(ids), sorted(group_ids)


def prepare_transfer(db, *, invoice_ids, target_route, request_key, checkpoint, evidence):
    current = gates._lock_policy(db)
    if target_route != "local":
        raise gates.TransitionError("首期仅支持旧责任核验后承接至独立路线")
    gates._phase_allows(db, current, target_route)
    gates._key(request_key, "移交请求键")
    gates._key(checkpoint, "一致检查点")
    gates._evidence(evidence)
    requested = sorted(set(map(int, invoice_ids)))
    if not requested:
        raise gates.TransitionError("移交对象不能为空")
    existing = db.query(TransferPreparation).filter_by(request_key=request_key).populate_existing().with_for_update().first()
    if existing:
        if (existing.manifest["invoice_ids"] != requested or existing.target_route != target_route
                or existing.manifest["checkpoint"] != checkpoint
                or gates.digest(existing.manifest["evidence"]) != gates.digest(evidence)):
            raise gates.TransitionError("移交请求键已用于不同清单或检查点")
        return existing
    closure, group_ids = responsibility_closure(db, requested)
    if requested != closure:
        raise gates.TransitionError(f"必须整体冻结和移交共享责任闭包，完整订单为{closure}")
    authorities = [gates._lock_authority(db, invoice_id) for invoice_id in closure]
    source_routes = {row.route for row in authorities}
    if len(source_routes) != 1 or target_route in source_routes:
        raise gates.TransitionError("移交必须具有唯一且不同于目标的原正式路线")
    if any(row.state != "active" or row.confirmed_at is None for row in authorities):
        raise gates.TransitionError("订单未生效或已属于其他冻结移交")
    source_route = next(iter(source_routes))
    manifest = {"invoice_ids": closure, "group_ids": group_ids, "checkpoint": checkpoint,
                "epochs": {str(row.invoice_id): row.epoch for row in authorities}, "evidence": evidence}
    for row in authorities:
        row.state = "frozen"
        gates._event(db, row, "freeze", {"request_key": request_key, "checkpoint": checkpoint})
    # Freeze persists even while a worker is paused before HTTP or its result
    # is unknown. Returning waiting never releases or reclaims that identity.
    pending = _pending_original_requests(db, closure)
    row = TransferPreparation(request_key=request_key, source_route=source_route,
        target_route=target_route, state="waiting" if pending else "ready",
        manifest=manifest, manifest_hash=gates.digest(manifest))
    db.add(row)
    db.flush()
    return row


def complete_transfer(db, preparation_id, *, verification, apply_opening=None):
    """Atomically apply a verified opening through a trusted ledger adapter.

    The adapter is required: changing authority without ledger continuation is
    forbidden. It must perform only local DB work in this caller transaction,
    return a durable opening receipt, and never create replacement principal
    for already consumed money. The service itself has no ledger ownership.
    """
    current = gates._lock_policy(db)
    row = db.query(TransferPreparation).filter_by(id=preparation_id).populate_existing().with_for_update().first()
    if row is None:
        raise gates.TransitionError("冻结移交记录不存在")
    if row.state == "completed":
        return row
    gates._phase_allows(db, current, row.target_route)
    if row.manifest_hash != gates.digest(row.manifest):
        raise gates.TransitionError("移交检查点清单已变化")
    if not isinstance(verification, dict) or not all(verification.get(k) for k in VERIFICATION_PARTS):
        raise gates.TransitionError("合同、资金、履约、库存、生产、媒体及提成核验缺项")
    closure, groups = responsibility_closure(db, row.manifest["invoice_ids"])
    if closure != row.manifest["invoice_ids"] or groups != row.manifest["group_ids"]:
        raise gates.TransitionError("共享责任闭包已变化，必须重新核验")
    authorities = [gates._lock_authority(db, invoice_id) for invoice_id in closure]
    if any(a.state != "frozen" or a.route != row.source_route or
           a.epoch != row.manifest["epochs"][str(a.invoice_id)] for a in authorities):
        raise gates.TransitionError("冻结办理权或原版本已变化")
    if _pending_original_requests(db, closure):
        raise gates.TransitionError("在途或unknown结果未核清，禁止移交和释放")
    if apply_opening is None:
        raise gates.TransitionError("缺少已核验的正式期初原子承接适配器")
    receipt = apply_opening(db, row, verification)
    gates._evidence(receipt)
    from app.invoice.models import Invoice
    for authority in authorities:
        original = authority.epoch
        authority.route, authority.epoch, authority.state = row.target_route, original + 1, "active"
        invoice = db.get(Invoice, authority.invoice_id)
        invoice.transaction_mode = row.target_route
        gates._event(db, authority, "transfer", {"preparation_id": row.id,
                      "previous_epoch": original, "opening_receipt": receipt})
    row.state, row.completed_at = "completed", beijing_now()
    row.verification = {**verification, "opening_receipt": receipt}
    if row.target_route == "local":
        current.local_ever_effective = True
    db.flush()
    return row
