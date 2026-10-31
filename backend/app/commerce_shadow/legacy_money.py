"""Reviewed old bank identity -> real candidate register/confirm/allocation."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.commerce_shadow.dispatcher import UnsupportedCommand
from app.commerce_shadow.legacy_adapter import _key, invoice_target, customer


class ReceiptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    batch_id: int | None = None
    purpose: str
    amount: Decimal = Field(gt=0)
    currency: str
    collection_date: date
    payment_type: str
    bank_charge: Decimal = Field(ge=0)


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gross_amount: Decimal = Field(gt=0)
    actual_bank_fee: Decimal = Field(ge=0)
    currency: str
    collection_date: date
    payment_type: str
    rate_to_cny: Decimal | None = None
    rate_to_usd: Decimal | None = None


def expected(raw):
    row = ReceiptInput.model_validate(raw["receipt"])
    payment = PaymentInput.model_validate(raw["payment"])
    return {"metrics": {"allocation_amount": str(row.amount), "currency": row.currency,
        "gross_amount": str(payment.gross_amount), "actual_bank_fee": str(payment.actual_bank_fee),
        "net_amount": str(payment.gross_amount - payment.actual_bank_fee)},
        "identities": {"id": row.id}}


def _bank(db, raw, payment, checkpoint):
    from app.commerce_transition.models import BankAccountDomain
    from app.finance.models import BankAccount, Currency
    bank = raw.get("bank") or checkpoint.get("legacy_bank_map", {}).get(raw["bank_reference_key"])
    if not bank or not bank.get("statement_reference"):
        raise UnsupportedCommand("legacy_canonical_bank_identity_missing")
    keys = ("subject_key", "account_key", "channel", "bank_account_code", "transaction_id", "gross_amount", "currency")
    if any(bank.get(key) in (None, "") for key in keys):
        raise UnsupportedCommand("legacy_canonical_bank_identity_incomplete")
    if Decimal(bank["gross_amount"]) != payment.gross_amount or bank["currency"] != payment.currency:
        raise UnsupportedCommand("legacy_original_principal_identity_mismatch")
    domain = db.scalar(select(BankAccountDomain).where(BankAccountDomain.subject_key == bank["subject_key"],
        BankAccountDomain.account_key == bank["account_key"], BankAccountDomain.channel == bank["channel"]))
    account = db.scalar(select(BankAccount).where(BankAccount.code == bank["bank_account_code"],
        BankAccount.currency == payment.currency))
    if not domain or not account or account.id not in (domain.evidence or {}).get("bank_account_ids", []):
        raise UnsupportedCommand("legacy_bank_account_domain_checkpoint_missing")
    rates = checkpoint.get("legacy_rate_map", {}).get(raw["bank_reference_key"], {})
    cny = rates.get("rate_to_cny", payment.rate_to_cny)
    usd = rates.get("rate_to_usd", payment.rate_to_usd)
    if payment.currency == "USD" and usd is None:
        usd = Decimal(1)
    currency = db.get(Currency, payment.currency)
    dollar = db.get(Currency, "USD")
    if (cny is None or usd is None or currency is None or dollar is None or dollar.rate_to_cny <= 0
            or Decimal(cny) != currency.rate_to_cny or Decimal(usd) !=
                (currency.rate_to_cny / dollar.rate_to_cny).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)):
        raise UnsupportedCommand("legacy_historical_rate_checkpoint_mismatch")
    payment_type = checkpoint.get("payment_type_map", {}).get(payment.payment_type, payment.payment_type)
    if payment_type not in {"bank_transfer", "cash", "card", "online"}:
        raise UnsupportedCommand("legacy_payment_type_mapping_missing")
    return bank, account, payment_type


def execute(db, *, dataset_id, command, actor_id, checkpoint):
    from app.finance import service as finance
    from app.finance.schemas import PaymentCreate, FinanceAction, AllocationCreate
    from app.finance.models import FinanceEvent
    from app.invoice.settlement_models import Receivable
    from app.commerce_shadow.dispatcher import verify_conservation
    raw, actor = command["body"], command["actor"]
    if str(actor.get("sub")) != str(actor_id) or not actor.get("roles"):
        raise UnsupportedCommand("legacy_authorization_snapshot_missing")
    from app.commerce_shadow.dispatcher import require_permissions
    require_permissions(actor, "receipt:write", "receipt:admin")
    row = ReceiptInput.model_validate(raw["receipt"])
    payment = PaymentInput.model_validate(raw["payment"])
    if row.purpose != "ordinary":
        raise UnsupportedCommand("legacy_presale_allocation_plan_required")
    if row.currency != payment.currency or row.amount > payment.gross_amount:
        raise UnsupportedCommand("legacy_receipt_original_principal_mismatch")
    original = raw.get("original_payload", {})
    if (str(original.get("collection_date")) != row.collection_date.isoformat()
            or Decimal(str(original.get("amount", -1))) != row.amount - row.bank_charge):
        raise UnsupportedCommand("legacy_receipt_frozen_payload_mismatch")
    invoice_id, _ = invoice_target(db, dataset_id, raw["source_invoice_id"], checkpoint)
    if invoice_id is None:
        raise UnsupportedCommand("legacy_receipt_contract_checkpoint_missing")
    customer_id = customer(db, raw["source_namespace"], raw["tenant"], raw["customer_external_id"])
    bank, account, payment_type = _bank(db, raw, payment, checkpoint)
    money_key = ":".join((bank["subject_key"], bank["account_key"], bank["channel"], bank["transaction_id"]))
    batch = finance.register(db, PaymentCreate(request_key=_key(dataset_id, money_key, "register"),
        local_customer_id=customer_id, bank_account_id=account.id, bank_reference=bank["transaction_id"],
        currency=payment.currency, gross_amount=payment.gross_amount, actual_bank_fee=payment.actual_bank_fee,
        collection_date=payment.collection_date, payment_type=payment_type), actor)
    if batch.finance_status == "registered":
        finance.confirm(db, batch.id, FinanceAction(request_key=_key(dataset_id, money_key, "confirm"),
            expected_version=batch.version, business_date=row.collection_date, reason="Independent original bank input verification"), actor)
    targets = list(db.scalars(select(Receivable).where(Receivable.invoice_id == invoice_id,
        Receivable.amount + Receivable.adjustment_amount > 0).order_by(Receivable.id)))
    plan = checkpoint.get("legacy_allocation_plans", {}).get(f"legacy-receipt:{row.id}")
    if plan is None:
        if len(targets) != 1:
            raise UnsupportedCommand("legacy_multi_target_allocation_plan_required")
        plan = [{"kind": targets[0].kind, "amount": str(row.amount)}]
    if sum((Decimal(item["amount"]) for item in plan), Decimal(0)) != row.amount:
        raise UnsupportedCommand("legacy_allocation_plan_not_conserved")
    allocations = []
    for index, component in enumerate(plan):
        matches = [target for target in targets if target.kind == component["kind"]]
        if len(matches) != 1:
            raise UnsupportedCommand("legacy_allocation_target_mapping_ambiguous")
        key = _key(dataset_id, raw["request_key"], f"allocate:{index}")
        prior = db.scalar(select(FinanceEvent).where(FinanceEvent.request_key == key))
        version = prior.payload["body"]["expected_version"] if prior else batch.version
        allocation = finance.allocate(db, batch.id, AllocationCreate(request_key=key, expected_version=version,
            invoice_id=invoice_id, receivable_id=matches[0].id, amount=component["amount"],
            business_date=row.collection_date), actor)
        allocations.append(allocation)
    return {"metrics": {"allocation_amount": str(sum((item.amount for item in allocations), Decimal(0))), "currency": row.currency,
        "gross_amount": str(batch.gross_amount), "actual_bank_fee": str(batch.actual_bank_fee), "net_amount": str(batch.net_amount)},
        "identities": {"id": allocations[0].id, "payment_id": batch.id}, "domain_type": "allocation",
        "invariants": verify_conservation(db, checkpoint=checkpoint), "adapter": "legacy.receipt.remote"}
