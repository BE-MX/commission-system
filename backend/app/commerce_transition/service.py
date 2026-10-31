"""Short transaction gates. Callers own commit, live authorization and ledgers.

Lock order: portal employee barrier (caller), policy, invoice authority by ID,
then claim/resource/bank/closure records, then the existing business locks.
No function commits or performs network I/O. A sending claim must be committed
before HTTP; its terminal evidence, ledger receipt and outbox commit together.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json

from sqlalchemy import update
from sqlalchemy.orm.attributes import set_committed_value

from app.core.time import beijing_now
from app.commerce_transition.models import (
    AuthorityEvent, BankAccountDomain, BankIdentity, ClaimEvidence,
    InvoiceAuthority, PlatformPolicy, ResourceScope, SendingClaim, WriterReceipt,
)

ROUTES = {"legacy", "local"}
PHASES = {"legacy_only", "transition", "local_only"}
TERMINAL = {"succeeded", "failed", "not_sent"}


class TransitionError(ValueError):
    """A concrete ownership/capability conflict; never an implicit legacy fallback."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()


def _evidence(value):
    if not isinstance(value, dict) or not any(k != "recorded_by" for k in value):
        raise TransitionError("必须提供可核验的事实依据")
    return value


def _key(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise TransitionError(f"{name}必须为完整稳定身份")
    return value


def policy(db):
    row = db.get(PlatformPolicy, 1)
    if row is None or row.phase not in PHASES or row.version < 1:
        raise TransitionError("交易办理权策略未安装或无效，禁止发送")
    return row


def _lock_policy(db):
    # SQLite ignores FOR UPDATE. This write takes its transaction writer lock;
    # MySQL takes the same singleton row lock as every coordinator mutation.
    db.flush()
    db.execute(update(PlatformPolicy).where(PlatformPolicy.id == 1).values(
        version=PlatformPolicy.version).execution_options(synchronize_session=False))
    row = db.query(PlatformPolicy).filter_by(id=1).populate_existing().with_for_update().first()
    if row is None or row.phase not in PHASES or row.version < 1:
        raise TransitionError("交易办理权策略未安装或无效，禁止发送")
    return row


def lock_policy(db):
    """Acquire before finance-book/invoice locks; does not commit or send."""
    return _lock_policy(db)


def _writers_ready(db, current):
    writers = db.query(WriterReceipt).populate_existing().with_for_update().all()
    if not current.writer_inventory_verified or not current.inventory_evidence or not writers:
        raise TransitionError("全部交易writer清单及强制兼容回执尚未核验")
    if any(w.state != "revoked" and (w.state != "compatible" or
           w.protocol_version < current.min_writer_version) for w in writers):
        raise TransitionError("存在未兼容或未撤权的交易writer")


def _phase_allows(db, current, route):
    if route not in ROUTES:
        raise TransitionError("正式办理路线只能为legacy或local")
    if current.phase != "transition" and current.phase != f"{route}_only":
        raise TransitionError("平台阶段不允许此正式办理路线")
    if current.phase != "legacy_only":
        _writers_ready(db, current)


def require_phase(db, route):
    """Gate non-invoice operations with the same locked writer capability."""
    current = _lock_policy(db)
    _phase_allows(db, current, route)
    return current


def set_writer_receipt(db, writer_key, protocol_version, state, evidence):
    current = _lock_policy(db)
    _key(writer_key, "writer")
    if state not in {"compatible", "revoked", "unknown"} or protocol_version < 1:
        raise TransitionError("writer回执状态或版本无效")
    row = db.query(WriterReceipt).filter_by(writer_key=writer_key).populate_existing().with_for_update().first()
    if row is None:
        row = WriterReceipt(writer_key=writer_key)
        db.add(row)
        # Adding a writer invalidates the prior complete inventory attestation.
        current.writer_inventory_verified = False
    row.protocol_version, row.state, row.evidence = protocol_version, state, _evidence(evidence)
    current.version += 1
    db.flush()
    return row


def set_policy(db, *, phase, expected_version, min_writer_version=1,
               inventory_evidence=None):
    current = _lock_policy(db)
    if current.version != expected_version or phase not in PHASES or min_writer_version < 1:
        raise TransitionError("平台策略版本冲突或阶段无效")
    if phase == "legacy_only" and (current.local_ever_effective or
            db.query(InvoiceAuthority.invoice_id).filter_by(route="local").with_for_update().first() or
            db.query(BankIdentity.id).filter_by(route="local").with_for_update().first() or
            db.query(ResourceScope.id).filter_by(route="local").with_for_update().first()):
        raise TransitionError("已有本地正式责任，禁止退回旧路线模式")
    if phase == "local_only":
        from app.finance.transition_identity import unmapped_legacy_money
        if unmapped_legacy_money(db):
            raise TransitionError("仍有账户身份不明的旧款，不能完成全量切换")
        if (db.query(InvoiceAuthority.invoice_id).filter(
                InvoiceAuthority.route == "legacy", InvoiceAuthority.settled_evidence.is_(None)).with_for_update().first()
                or db.query(SendingClaim.id).filter(SendingClaim.state.notin_(TERMINAL)).with_for_update().first()
                or db.query(BankIdentity.id).filter(BankIdentity.route == "legacy",
                                                     BankIdentity.settled_evidence.is_(None)).with_for_update().first()):
            raise TransitionError("旧路线责任或在途请求尚未核清，不能完成全量切换")
    current.min_writer_version = min_writer_version
    if inventory_evidence is not None:
        current.inventory_evidence = _evidence(inventory_evidence)
        current.writer_inventory_verified = True
    if phase != "legacy_only":
        _writers_ready(db, current)
    current.phase, current.version = phase, current.version + 1
    db.flush()
    return current


def _invoice_id(invoice):
    return int(invoice if isinstance(invoice, int) else invoice.id)


def _lock_authority(db, invoice):
    invoice_id = _invoice_id(invoice)
    row = db.query(InvoiceAuthority).filter_by(invoice_id=invoice_id).populate_existing().with_for_update().first()
    if row is None:
        raise TransitionError("订单办理权未登记，请先核验明确来源")
    old = row.lock_version
    result = db.execute(update(InvoiceAuthority).where(
        InvoiceAuthority.invoice_id == invoice_id, InvoiceAuthority.lock_version == old
    ).values(lock_version=old + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise TransitionError("订单办理权发生并发变化，请重新读取")
    set_committed_value(row, "lock_version", old + 1)
    return row


def _event(db, authority, action, payload):
    db.add(AuthorityEvent(invoice_id=authority.invoice_id, epoch=authority.epoch,
                          action=action, payload=payload))


def ensure_authority(db, invoice, *, source_evidence, route=None, confirmed=False):
    current = _lock_policy(db)
    old = db.query(InvoiceAuthority).filter_by(invoice_id=invoice.id).populate_existing().with_for_update().first()
    if old is not None:
        if route is not None and old.route != route:
            raise TransitionError("既有办理权与请求来源冲突")
        return old
    source_evidence = _evidence(source_evidence)
    route = route or getattr(invoice, "transaction_mode", None)
    _phase_allows(db, current, route)
    if getattr(invoice, "transaction_mode", route) != route:
        raise TransitionError("订单明确来源与办理路线冲突")
    row = InvoiceAuthority(invoice_id=invoice.id, route=route, epoch=1, lock_version=1,
                           state="active", source_evidence=source_evidence,
                           confirmed_at=beijing_now() if confirmed else None)
    db.add(row)
    db.flush()
    _event(db, row, "initialize", source_evidence)
    if route == "local" and confirmed:
        current.local_ever_effective = True
    return row


def require_route(db, invoice, route, expected_epoch=None):
    current = _lock_policy(db)
    _phase_allows(db, current, route)
    row = _lock_authority(db, invoice)
    if row.route != route or row.state != "active":
        raise TransitionError("当前入口无此订单办理权，或订单已冻结")
    if expected_epoch is not None and row.epoch != expected_epoch:
        raise TransitionError("订单办理权版本已变化，请重新读取")
    return row


def _no_draft_facts(db, invoice):
    from app.invoice.models import Invoice, InvoiceCommerceEvent, InvoiceItem, InvoiceLinkedSync, OkkiOutboundTask
    from app.invoice.settlement_models import Receivable, ShipmentOutbound, ShipmentSettlement
    from app.receipt.models import Receipt
    invoice = db.query(Invoice).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    if (getattr(invoice, "commerce_status", "draft") != "draft" or invoice.status != "draft"
            or getattr(invoice, "xiaoman_order_id", None)
            or getattr(invoice, "sync_status", None) in {"syncing", "sync_uncertain", "uncertain"}):
        raise TransitionError("仅无经济事实的未生效草稿可调整办理路线")
    for model in (Receipt, Receivable, ShipmentOutbound, ShipmentSettlement, OkkiOutboundTask, InvoiceLinkedSync):
        if db.query(model).filter_by(invoice_id=invoice.id).with_for_update().first():
            raise TransitionError("草稿已有资金、发货或在途事实，禁止改线")
    if db.query(InvoiceItem.id).filter(InvoiceItem.invoice_id == invoice.id,
            (InvoiceItem.stock_reserved_quantity > 0) | (InvoiceItem.stock_shipped_quantity > 0)).with_for_update().first():
        raise TransitionError("草稿已有库存责任，禁止改线")
    if db.query(InvoiceCommerceEvent.id).filter(InvoiceCommerceEvent.invoice_id == invoice.id,
            InvoiceCommerceEvent.action.notin_(["create", "edit_draft", "update"])).with_for_update().first():
        raise TransitionError("草稿已有正式生命周期事实，禁止改线")
    from app.inventory.models import StockReservation
    from app.production.local_models import ProductionSupply
    from app.semifinished.models import InvoiceAllocation
    if (db.query(StockReservation.id).join(InvoiceItem, InvoiceItem.id == StockReservation.invoice_item_id)
            .filter(InvoiceItem.invoice_id == invoice.id).with_for_update().first()
            or db.query(ProductionSupply.id).join(InvoiceItem, InvoiceItem.id == ProductionSupply.invoice_item_id)
            .filter(InvoiceItem.invoice_id == invoice.id).with_for_update().first()
            or db.query(InvoiceAllocation.id).filter_by(invoice_id=invoice.id).with_for_update().first()):
        raise TransitionError("草稿已有库存、生产或物料责任，禁止改线")
    if db.query(SendingClaim.id).filter_by(invoice_id=invoice.id).with_for_update().first():
        raise TransitionError("草稿已有外部请求历史，禁止改线")
    from app.commerce_transition.models import ResponsibilityMember
    if db.query(ResponsibilityMember.id).filter_by(invoice_id=invoice.id).with_for_update().first():
        raise TransitionError("草稿已有共享责任，禁止改线")


def set_draft_route(db, invoice, route, expected_epoch, evidence):
    current = _lock_policy(db)
    _phase_allows(db, current, route)
    row = _lock_authority(db, invoice)
    if row.confirmed_at or row.state != "active" or row.epoch != expected_epoch:
        raise TransitionError("已生效、冻结或版本变化的订单不能直接改线")
    _no_draft_facts(db, invoice)
    _evidence(evidence)
    if row.route != route:
        original = row.route
        row.route, row.epoch = route, row.epoch + 1
        invoice.transaction_mode = route
        _event(db, row, "draft_route", {"from": original, "to": route, "evidence": evidence})
    db.flush()
    return row


def confirm_authority(db, invoice, route, expected_epoch, evidence):
    row = require_route(db, invoice, route, expected_epoch)
    if row.confirmed_at is None:
        row.confirmed_at = beijing_now()
        _event(db, row, "confirm", _evidence(evidence))
        if row.route == "local":
            policy(db).local_ever_effective = True
    db.flush()
    return row


@dataclass(frozen=True)
class SendClaimResult:
    claim: SendingClaim
    created: bool


def begin_send(db, invoice, request_key, operation, payload, expected_epoch,
               *, route="legacy", responsibilities=None, lease_until=None):
    _lock_policy(db)
    _key(request_key, "请求键")
    _key(operation, "操作")
    content_hash = digest(payload)
    existing = db.query(SendingClaim).filter_by(request_key=request_key).populate_existing().with_for_update().first()
    if existing:
        if (existing.invoice_id != _invoice_id(invoice) or existing.operation != operation or
                existing.payload_hash != content_hash or existing.route != route or
                existing.epoch != expected_epoch or
                digest(existing.responsibilities) != digest(responsibilities or {})):
            raise TransitionError("原发送请求身份已用于不同内容")
        # Recovery of the original identity remains readable while frozen or
        # after transfer, but never authorizes a new HTTP send.
        return SendClaimResult(existing, False)
    row = require_route(db, invoice, route, expected_epoch)
    if row.confirmed_at is None:
        raise TransitionError("合同办理路线尚未正式固化")
    if db.query(SendingClaim.id).filter(SendingClaim.invoice_id == row.invoice_id,
                                       SendingClaim.state.notin_(TERMINAL)).with_for_update().first():
        raise TransitionError("原请求正在发送或结果未知，只能核对原请求")
    claim = SendingClaim(invoice_id=row.invoice_id, request_key=request_key,
        operation=operation, route=route, epoch=row.epoch, payload_hash=content_hash,
        responsibilities=responsibilities or {}, state="sending",
        active_invoice_key=row.invoice_id, lease_until=lease_until)
    db.add(claim)
    db.flush()
    return SendClaimResult(claim, True)


def finish_send(db, claim_id, outcome, evidence, external_id=None):
    _lock_policy(db)
    original_invoice_id = db.query(SendingClaim.invoice_id).filter_by(id=claim_id).scalar()
    if original_invoice_id is None or outcome not in TERMINAL | {"unknown"}:
        raise TransitionError("发送责任或结果状态无效")
    _lock_authority(db, original_invoice_id)  # Immutable locator; authority before claim.
    claim = db.query(SendingClaim).filter_by(id=claim_id).populate_existing().with_for_update().one()
    evidence = _evidence(evidence)
    if external_id is not None:
        _key(external_id, "远端经济身份")
    if outcome == "succeeded" and not external_id:
        raise TransitionError("成功结果必须有原请求远端身份")
    # Terminal failure / definitely-unsent requires a conclusive original
    # request readback. A timeout, lease expiry or absence of local outbox is
    # expressly insufficient to release the responsibility.
    if outcome in {"failed", "not_sent"} and not evidence.get("definitive_original_request_result"):
        raise TransitionError("未证明原请求终局，必须保留unknown责任")
    db.add(ClaimEvidence(claim_id=claim.id, outcome=outcome,
                         evidence=evidence, external_id=external_id))
    if claim.state in TERMINAL:
        if outcome != "unknown" and (claim.state != outcome or (external_id and claim.external_id != external_id)):
            # Persist contradictions without erasing the terminal observation.
            # Re-open the responsibility only if another claim has not begun;
            # the caller must freeze/alert on returned conflict evidence.
            authority = db.get(InvoiceAuthority, claim.invoice_id)
            authority.state = "frozen"
            claim.state = "unknown"
            _event(db, authority, "evidence_conflict", {"claim_id": claim.id, "outcome": outcome})
    else:
        claim.state = outcome
        if external_id:
            claim.external_id = external_id
        if outcome in TERMINAL:
            claim.active_invoice_key, claim.terminal_at = None, beijing_now()
    db.flush()
    return claim


def authority_view(db, invoice_id):
    row = db.get(InvoiceAuthority, invoice_id)
    if row is None:
        raise TransitionError("订单办理权未登记，请先核验明确来源")
    return {"invoice_id": row.invoice_id, "route": row.route, "authority_epoch": row.epoch,
            "state": row.state, "confirmed": row.confirmed_at is not None,
            "confirmed_at": row.confirmed_at,
            "can_change_route": row.confirmed_at is None and row.state == "active",
            "pending_claims": db.query(SendingClaim).filter(SendingClaim.invoice_id == invoice_id,
                                                            SendingClaim.state.notin_(TERMINAL)).count()}


def require_no_legacy_physical_inflight(db):
    """No unproved old physical effect may survive assigning a new pilot scope.

    Original requests do not all have verified local SKU/warehouse references.
    Conservatively wait for their exact outcomes instead of guessing a bucket.
    """
    _lock_policy(db)
    if db.query(SendingClaim.id).filter(SendingClaim.route == 'legacy',
            SendingClaim.operation.contains('outbound'),
            SendingClaim.state.notin_(TERMINAL)).with_for_update().first():
        raise TransitionError('原出库请求仍在途或结果未知，核清原责任后才能分配本地实物范围')
    from app.invoice.models import Invoice, OkkiOutboundTask
    if (db.query(OkkiOutboundTask.id).join(Invoice, Invoice.id == OkkiOutboundTask.invoice_id).filter(
            Invoice.transaction_mode == 'legacy', OkkiOutboundTask.status.in_(['running', 'uncertain']))
            .with_for_update().first()):
        raise TransitionError('原自动出库任务尚未核清，不能分配本地实物范围')
    from app.shipping_inspection.models import ShippingOperationEvent
    if (db.query(ShippingOperationEvent.id).filter(
            ShippingOperationEvent.scope == 'outbound-invoice-sync',
            ShippingOperationEvent.action.in_(['sync_pending', 'sync_sending', 'sync_uncertain']))
            .with_for_update().first()):
        raise TransitionError('原出库同步尚未核清，不能分配本地实物范围')


def register_resource_scope(db, *, route, resource_kind, resource_key, warehouse_key, evidence):
    current = _lock_policy(db)
    _phase_allows(db, current, route)
    _key(resource_key, "实物身份")
    _key(warehouse_key, "库存桶")
    if resource_kind not in {"sku", "material", "production"}:
        raise TransitionError("资源责任类型无效")
    if not all(_evidence(evidence).get(k) for k in ("checkpoint", "old_responsibilities_cleared", "writers_enforced")):
        raise TransitionError("盘点、旧在途责任和全部writer排他证据不完整")
    existing = db.query(ResourceScope).filter_by(resource_kind=resource_kind, resource_key=resource_key).populate_existing().with_for_update().all()
    for row in existing:
        if row.warehouse_key == warehouse_key:
            if row.route == route and digest(row.evidence) == digest(evidence):
                return row
            raise TransitionError("活动资源范围只能通过冻结移交改变")
        if row.warehouse_key == "*" or warehouse_key == "*":
            raise TransitionError("排他实物范围交叉，禁止重复登记")
    if route == 'local':
        require_no_legacy_physical_inflight(db)
        if resource_kind == 'material':
            from app.inventory.legacy_scope import require_material_scope_ready
            require_material_scope_ready(db, resource_key)
    row = ResourceScope(route=route, resource_kind=resource_kind, resource_key=resource_key,
                        warehouse_key=warehouse_key, state="active", evidence=evidence)
    db.add(row)
    db.flush()
    return row


def require_resource_scope(db, route, resource_kind, resource_key, warehouse_key=None):
    current = _lock_policy(db)
    _phase_allows(db, current, route)
    rows = db.query(ResourceScope).filter_by(resource_kind=resource_kind, resource_key=str(resource_key)).populate_existing().with_for_update().all()
    matches = [r for r in rows if r.warehouse_key == "*" or (warehouse_key is not None and r.warehouse_key == str(warehouse_key))]
    if warehouse_key is None and any(r.warehouse_key != "*" for r in rows):
        raise TransitionError("缺少真实仓库/库存桶维度，不能证明资源排他")
    if not matches:
        if route == "legacy":
            return None  # Unassigned physical resources remain on the old route.
        if current.phase == "local_only" and not any(r.route == "legacy" or r.state != "active" for r in rows):
            return None  # Completed cutover owns all otherwise unassigned stock.
        raise TransitionError("资源未完成独立路线排他核验")
    if len(matches) != 1 or matches[0].state != "active" or matches[0].route != route:
        raise TransitionError("该库存或物料责任不归当前路线，或已冻结")
    return matches[0]


def register_bank_domain(db, *, subject_key, account_key, channel,
                         legacy_identity_complete, enforced, evidence, exclusive_route=None, bank_account_ids=None):
    _lock_policy(db)
    for value, label in ((subject_key, "主体"), (account_key, "账户"), (channel, "渠道")):
        _key(value, label)
    if exclusive_route is not None and exclusive_route not in ROUTES:
        raise TransitionError("账户域排他路线无效")
    row = db.query(BankAccountDomain).filter_by(subject_key=subject_key,
                           account_key=account_key, channel=channel).populate_existing().with_for_update().first()
    evidence = dict(_evidence(evidence))
    if bank_account_ids is not None:
        from app.finance.models import BankAccount
        ids = sorted(set(bank_account_ids))
        if any(type(identity) is not int or identity < 1 for identity in ids):
            raise TransitionError('银行账户关联身份无效')
        accounts = db.query(BankAccount).filter(BankAccount.id.in_(ids)).with_for_update().all()
        if len(accounts) != len(ids):
            raise TransitionError('所关联的银行账户不存在')
        others = db.query(BankAccountDomain).populate_existing().with_for_update().all()
        if any(other.id != getattr(row, 'id', None)
                and set((other.evidence or {}).get('bank_account_ids', [])) & set(ids) for other in others):
            raise TransitionError('同一银行账户不能关联多个真实结算账户域')
        old_ids = set((row.evidence or {}).get('bank_account_ids', [])) if row else set()
        if old_ids - set(ids) and db.query(BankIdentity.id).filter_by(domain_id=row.id).with_for_update().first():
            raise TransitionError('已有资金责任的银行账户关联不可删除')
        evidence['bank_account_ids'] = ids
    elif row and (row.evidence or {}).get('bank_account_ids'):
        evidence['bank_account_ids'] = row.evidence['bank_account_ids']
    if row is None:
        row = BankAccountDomain(subject_key=subject_key, account_key=account_key, channel=channel, version=1)
        db.add(row)
    elif row.exclusive_route != exclusive_route and db.query(BankIdentity.id).filter_by(domain_id=row.id).with_for_update().first():
        raise TransitionError("已有资金责任的账户域不能直接改变排他路线")
    else:
        row.version += 1
    row.legacy_identity_complete, row.enforced = bool(legacy_identity_complete), bool(enforced)
    row.exclusive_route, row.evidence = exclusive_route, evidence
    db.flush()
    return row


@dataclass(frozen=True)
class BankIdentityResult:
    identity: BankIdentity
    created: bool


def claim_bank_identity(db, *, domain_id, transaction_id, route, currency, amount,
                        payer_evidence, historical=False):
    current = _lock_policy(db)
    _phase_allows(db, current, route)
    domain = db.query(BankAccountDomain).filter_by(id=domain_id).populate_existing().with_for_update().first()
    if domain is None:
        raise TransitionError("收款账户域未登记核验")
    if domain.exclusive_route and domain.exclusive_route != route:
        raise TransitionError("账户域不归当前正式路线")
    # Historical registration is only old-money identity reconciliation. It
    # cannot create local principal before the complete-domain attestation.
    if route == "local" and (not domain.legacy_identity_complete or not domain.enforced):
        raise TransitionError("账户域旧款身份未核清或旧入口未强制约束，禁止本地登记")
    if historical and route != "legacy":
        raise TransitionError("历史核验不得绕过本地账户域门禁")
    _key(transaction_id, "银行交易唯一标识")
    _key(currency, "原币")
    payer_evidence = _evidence(payer_evidence)
    if not payer_evidence.get("bank_identity_verified"):
        raise TransitionError("银行交易身份尚未核验，凭证名或随机号不构成身份")
    try:
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise TransitionError("银行原币总额必须为正且精确到分") from None
    existing = db.query(BankIdentity).filter_by(domain_id=domain_id, transaction_id=transaction_id).populate_existing().with_for_update().first()
    if existing:
        if existing.route != route or existing.currency != currency or existing.amount != amount:
            raise TransitionError("同一银行款已归属正式路线，禁止重复本金或跨线使用")
        return BankIdentityResult(existing, False)
    row = BankIdentity(domain_id=domain_id, transaction_id=transaction_id, route=route,
                       currency=currency, amount=amount, payer_evidence=payer_evidence)
    db.add(row)
    if route == "local":
        current.local_ever_effective = True
    db.flush()
    return BankIdentityResult(row, True)


def bind_bank_payment(db, identity_id, payment_ref):
    _lock_policy(db)
    row = db.query(BankIdentity).filter_by(id=identity_id).populate_existing().with_for_update().first()
    if row is None:
        raise TransitionError("银行款身份未登记")
    _key(payment_ref, "正式付款账本身份")
    if row.payment_ref is not None and row.payment_ref != payment_ref:
        raise TransitionError("同一真实付款不能创建第二份可用本金")
    if db.query(BankIdentity.id).filter(BankIdentity.payment_ref == payment_ref,
            BankIdentity.id != identity_id).populate_existing().with_for_update().first():
        raise TransitionError('原付款已绑定另一银行身份，请核验原流水，禁止重复登记')
    row.payment_ref = payment_ref
    db.flush()
    return row
