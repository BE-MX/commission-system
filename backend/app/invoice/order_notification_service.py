"""Detect daily Ark order celebrations independently of festival dates and rosters."""

import json
import logging
from decimal import Decimal

from sqlalchemy import and_, bindparam, select, text

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.festival import events_service
from app.festival.models import FestivalState
from app.invoice.models import Invoice, InvoiceSyncLog

_BASELINE_KEY = "baseline:daily:ark:invoice_orders"
_SHARD_SIZE = 1000
logger = logging.getLogger(__name__)


def _customer_countries(db, company_ids):
    if not company_ids:
        return {}
    # Reuse the invoice picker contract for manual overlays versus mirror freshness.
    from app.invoice.customer_picker_service import _effective_customers
    sql, params, expanding = _effective_customers(db, None)
    query = text(f"SELECT ci.company_id, ci.country_name FROM ({sql}) ci WHERE ci.company_id IN :notice_ids")
    for name in [*expanding, "notice_ids"]:
        query = query.bindparams(bindparam(name, expanding=True))
    return {str(row.company_id): row.country_name for row in db.execute(
        query, {**params, "notice_ids": sorted(company_ids)},
    )}


def _sales_teams(db, user_ids):
    ids = sorted({str(value) for value in user_ids if value and not str(value).startswith("ark:")})
    if not ids:
        return {}
    query = text("SELECT user_id, Team FROM lsordertest.user_rel_team WHERE user_id IN :ids")
    return {str(row.user_id): row.Team for row in db.execute(
        query.bindparams(bindparam("ids", expanding=True)), {"ids": ids},
    )}


def _notice_detail(name, team, country, new_sign, currency="USD", amount=0):
    team = " ".join(str(team or "").split()) or "未分队"
    country = " ".join(str(country or "").split()) or "国家未知"
    name = " ".join(str(name or "").split()) or "业务员"
    action = "新签" if new_sign else "成交"
    detail = f"恭喜{team}的{name}{action}{country}的客户！"[:220]
    if currency != "USD":
        detail += f"\n{currency} {amount:,.0f}"
    return detail


def delivery_order_detail(db, event):
    """Rebuild delivery copy from business fields, never reuse stored customer text."""
    reference = event["dedup_key"].split(":", 1)[-1]
    criterion = (Invoice.invoice_no == reference[4:] if reference.startswith("ark:")
                 else Invoice.xiaoman_order_id == reference)
    invoice = db.scalar(select(Invoice).where(criterion).limit(1))
    team_id = event["subject_id"]
    country = None
    new_sign = event["event_type"] == "new_sign_order"
    currency, amount = "USD", 0
    if invoice:
        team_id = db.scalar(select(ArkUserExternalBinding.external_account_id).where(
            ArkUserExternalBinding.ark_user_id == invoice.sales_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ).limit(1))
        country = _customer_countries(db, {str(invoice.customer_id)}).get(str(invoice.customer_id))
        new_sign = new_sign or _is_new_sign(db, {"id": invoice.id, "okki_new_deal": invoice.okki_new_deal})
        currency = str(invoice.currency or "USD").upper()
        amount = Decimal(invoice.total_amount or 0) - Decimal(invoice.surcharge_amount or 0)
    teams = _sales_teams(db, [team_id])
    return _notice_detail(event["subject_name"], teams.get(str(team_id)),
                          country, new_sign, currency, amount)


def _is_new_sign(db, row) -> bool:
    if row["okki_new_deal"] is not None:
        return row["okki_new_deal"] == 1
    # A blank flag is resolved during push without being written back to the invoice.
    # Read the actual successful payload instead of inferring from today's customer history.
    from app.invoice.xiaoman_service import FIELD_NEW_DEAL

    raw = db.scalar(select(InvoiceSyncLog.request_digest).where(
        InvoiceSyncLog.invoice_id == row["id"],
        InvoiceSyncLog.success == 1,
        InvoiceSyncLog.request_digest.is_not(None),
        InvoiceSyncLog.action.in_(("create", "update", "retry")),
    ).order_by(InvoiceSyncLog.id.desc()).limit(1))
    if not raw:
        return False
    try:
        payload = json.loads(raw)
        return isinstance(payload, dict) and payload.get(FIELD_NEW_DEAL) == "是"
    except (TypeError, ValueError):
        logger.warning("Order notification has invalid push evidence invoice=%s", row["id"])
        print(f"[invoice] Invalid notification push evidence invoice={row['id']}", flush=True)
        return False


def detect_order_events(db) -> int:
    """Observe successful pushes once; first enable baselines history without sending it."""
    events_service.acquire_detector_lock(db)
    rows = db.execute(
        select(
            Invoice.id, Invoice.invoice_no, Invoice.xiaoman_order_id,
            Invoice.customer_id,
            Invoice.sales_user_id, Invoice.sales_user_name, Invoice.okki_new_deal,
            Invoice.total_amount, Invoice.surcharge_amount, Invoice.currency,
            ArkUser.real_name, ArkUserExternalBinding.external_account_id,
        )
        .outerjoin(ArkUser, ArkUser.id == Invoice.sales_user_id)
        .outerjoin(ArkUserExternalBinding, and_(
            ArkUserExternalBinding.ark_user_id == Invoice.sales_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ))
        .where(
            Invoice.sync_status == "synced",
            Invoice.status.notin_(("cancelled", "cancel_pending")),
        )
        .order_by(Invoice.id)
    ).mappings().all()
    initialized = events_service._read_state(db, _BASELINE_KEY) is not None
    shards = {}
    for row in rows:
        key = f"{_BASELINE_KEY}:{int(row['id']) // _SHARD_SIZE}"
        shards.setdefault(key, []).append(row)
    # Preload existing states into the session to avoid one SELECT per historical invoice.
    states = db.query(FestivalState).filter(FestivalState.state_key.in_(tuple(shards))).all()
    seen_by_shard = {}
    for key in shards:
        previous = events_service._read_state(db, key)
        seen_by_shard[key] = set(previous.get("invoice_ids", [])) if previous else set()
    unseen_customers = {str(row["customer_id"]) for row in rows
                        if initialized and int(row["id"]) not in seen_by_shard[
                            f"{_BASELINE_KEY}:{int(row['id']) // _SHARD_SIZE}"]}
    countries = _customer_countries(db, unseen_customers)
    teams = _sales_teams(db, {row["external_account_id"] for row in rows
                            if initialized and int(row["id"]) not in seen_by_shard[
                                f"{_BASELINE_KEY}:{int(row['id']) // _SHARD_SIZE}"]})
    candidates = []
    for row in rows:
        invoice_id = int(row["id"])
        key = f"{_BASELINE_KEY}:{invoice_id // _SHARD_SIZE}"
        seen = seen_by_shard[key]
        if invoice_id in seen:
            continue
        seen.add(invoice_id)
        if not initialized:
            continue
        order_ref = str(row["xiaoman_order_id"] or f"ark:{row['invoice_no']}")
        subject_id = str(row["external_account_id"] or f"ark:{row['sales_user_id']}")
        name = row["sales_user_name"] or row["real_name"] or "业务员"
        amount = Decimal(row["total_amount"] or 0) - Decimal(row["surcharge_amount"] or 0)
        currency = str(row["currency"] or "USD").upper()
        # USD thresholds must never be applied directly to amounts in another currency.
        image_amount = amount if currency == "USD" else None
        new_sign = _is_new_sign(db, row)
        detail = _notice_detail(name, teams.get(subject_id),
                                countries.get(str(row["customer_id"])), new_sign, currency, amount)
        if new_sign:
            candidates.append(events_service._cand(
                "new_sign_order", "person", subject_id, name, f"new_sign:{order_ref}",
                amount=image_amount, detail=detail,
            ))
        if currency == "USD" and amount >= events_service.BIG_DEAL_USD:
            kind = ("super_deal" if amount >= events_service.SUPER_DEAL_USD else "big_deal")
            candidates.append(events_service._cand(
                kind, "person", subject_id, name, f"deal:{order_ref}",
                amount=amount, detail=detail,
            ))
    old_values = {row.state_key: row.value_json for row in states}
    for key, seen in seen_by_shard.items():
        value = {"invoice_ids": sorted(seen)}
        if old_values.get(key) != json.dumps(value, separators=(",", ":")):
            events_service._write_state(db, key, value)
    if not initialized:
        events_service._write_state(db, _BASELINE_KEY, {"initialized": True})
    added = events_service.persist_new(db, candidates)
    db.commit()  # Baselines also survive restart when no event was created.
    return added
