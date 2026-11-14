"""客户归属变更流水的只读查询（事件由 event_hooks 在每次 flush 时写入）。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.domestic_decision.models import DecisionEvent


def latest_releases(db: Session, customer_ids: list[int], since: datetime) -> dict[int, dict]:
    """每个客户在 since 之后最近一次「归属从有到无」的事件：{customer_id: {at, previous_owner_id}}。

    事件表只有 (customer_id, id) 索引，所以必须先给出客户范围，不按时间全表扫描。
    """
    if not customer_ids:
        return {}
    rows = (db.query(DecisionEvent.customer_id, DecisionEvent.before, DecisionEvent.after, DecisionEvent.occurred_at)
            .filter(DecisionEvent.customer_id.in_(customer_ids), DecisionEvent.entity_type == "customer",
                    DecisionEvent.event_type == "changed", DecisionEvent.occurred_at >= since)
            .order_by(DecisionEvent.customer_id, DecisionEvent.id).all())
    result: dict[int, dict] = {}
    for customer_id, before, after, occurred_at in rows:
        previous = (before or {}).get("owner_user_id")
        if previous is not None and (after or {}).get("owner_user_id") is None:
            result[customer_id] = {"at": occurred_at, "previous_owner_id": int(previous)}
    return result
