"""One signed, independently dated projection for every net-GMV consumer.

Return effects are adjustments, never replacement orders or countable customers.
"""
from datetime import date
from decimal import Decimal

from app.sales_return.models import ReturnEffect


def adjustments(db, start: date | str, end: date | str, owners=None) -> list[dict]:
    start = date.fromisoformat(start) if isinstance(start, str) else start
    end = date.fromisoformat(end) if isinstance(end, str) else end
    query = db.query(ReturnEffect).filter(ReturnEffect.gmv_eligible == 1,
                                         ReturnEffect.effective_date >= start,
                                         ReturnEffect.effective_date <= end)
    if owners is not None:
        query = query.filter(ReturnEffect.owner_okki_user_id.in_([str(o) for o in owners]))
    result = []
    for effect in query.order_by(ReturnEffect.effective_date, ReturnEffect.id).all():
        snapshot = effect.snapshot or {}
        source = snapshot.get("source", snapshot)
        original_order = ({key: source.get(key) for key in
            ("order_id", "order_no", "customer_id", "owner_okki_user_id", "account_date", "raw_new_deal")}
            if "raw_new_deal" in source and source.get("account_date") else None)
        result.append({"fact_key": f"sales_return:{effect.return_id}:{effect.effect_kind}",
                       "source_type": "sales_return", "return_id": effect.return_id,
                       "effect_kind": effect.effect_kind, "order_id": effect.order_id,
                       "order_no": source.get("order_no", effect.order_id),
                       "owner": effect.owner_okki_user_id, "user_id": effect.owner_okki_user_id,
                       "company_id": effect.customer_id,
                       "customer_name": source.get("customer_name", source.get("company_name", "")),
                       "country": source.get("country_name", ""), "order_name": source.get("order_name", ""),
                       "day": effect.effective_date, "account_date": effect.effective_date,
                       "amount": Decimal(str(effect.amount_usd)), "amount_usd": Decimal(str(effect.amount_usd)),
                       "role": effect.order_role, "departments": effect.departments,
                       "original_order": original_order,
                       "flags": ["sales_return", effect.effect_kind]})
    return result


def total_adjustment(db, start, end, owners=None):
    return sum((fact["amount"] for fact in adjustments(db, start, end, owners)), Decimal(0))


def department_adjustments(db, start, end, department_id):
    """Respect frozen department rates even after the owner transfers teams."""
    from app.dingtalk.gmv_daily_service import _parse_allocations
    facts, issues = [], []
    for fact in adjustments(db, start, end):
        allocations, anomalies, _ = _parse_allocations(fact["amount"], fact["departments"], fact["order_no"])
        issues.extend(anomalies)
        for allocation in allocations:
            if allocation["department_id"] == int(department_id):
                facts.append({**fact, "amount": allocation["amount"], "amount_usd": allocation["amount"]})
    return facts, issues


def order_adjustments(db, order_ids, through=None):
    query = db.query(ReturnEffect).filter(ReturnEffect.gmv_eligible == 1,
                                         ReturnEffect.order_id.in_([str(o) for o in order_ids]))
    if through:
        query = query.filter(ReturnEffect.effective_date <= through)
    result = {}
    for effect in query.all():
        result[effect.order_id] = result.get(effect.order_id, Decimal(0)) + Decimal(str(effect.amount_usd))
    return result


def breakdown(facts, amount_key="amount"):
    sales = sum((Decimal(str(f[amount_key])) for f in facts if f.get("source_type") != "sales_return"), Decimal(0))
    returns = sum((Decimal(str(f[amount_key])) for f in facts if f.get("source_type") == "sales_return"), Decimal(0))
    return {"sales_gmv": sales, "return_adjustment_gmv": returns, "net_gmv": sales + returns}
