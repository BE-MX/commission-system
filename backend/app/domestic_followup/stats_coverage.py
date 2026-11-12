"""负责客户范围与等级频率覆盖；客户归属不和记录作者混用。"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domestic.models import DomesticCustomer
from app.domestic_followup.collaboration_models import FollowupCollaborationEvent, FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup


def responsible_customers(db: Session, today: date, previous_cutoff: date) -> list[dict]:
    rows = (db.query(DomesticCustomer, FollowupResponsibility)
            .outerjoin(FollowupResponsibility, FollowupResponsibility.customer_id == DomesticCustomer.id)
            .filter(DomesticCustomer.status == 1).order_by(DomesticCustomer.id).all())
    customer_ids = [customer.id for customer, _ in rows]
    last_dates: dict[int, date] = {}
    previous_dates: dict[int, date] = {}
    if customer_ids:
        current_rows = (db.query(DomesticFollowup.customer_id, func.max(DomesticFollowup.followup_date))
                        .filter(DomesticFollowup.customer_id.in_(customer_ids),
                                DomesticFollowup.status == "confirmed",
                                DomesticFollowup.followup_date <= today)
                        .group_by(DomesticFollowup.customer_id).all())
        last_dates = dict(current_rows)
        previous_rows = (db.query(DomesticFollowup.customer_id, func.max(DomesticFollowup.followup_date))
                         .filter(DomesticFollowup.customer_id.in_(customer_ids),
                                 DomesticFollowup.status == "confirmed",
                                 DomesticFollowup.followup_date <= previous_cutoff)
                         .group_by(DomesticFollowup.customer_id).all())
        previous_dates = dict(previous_rows)
    result = []
    assignments = dict(db.query(FollowupCollaborationEvent.customer_id, func.max(FollowupCollaborationEvent.created_at))
                       .join(FollowupResponsibility,
                             FollowupResponsibility.customer_id == FollowupCollaborationEvent.customer_id)
                       .filter(FollowupCollaborationEvent.to_user_id == FollowupResponsibility.owner_user_id,
                               FollowupCollaborationEvent.from_user_id.is_distinct_from(FollowupCollaborationEvent.to_user_id))
                       .group_by(FollowupCollaborationEvent.customer_id).all())
    for customer, responsibility in rows:
        if responsibility is not None:
            if responsibility.status in ("stopped", "unassigned", "open"):
                continue
            owner_id = responsibility.owner_user_id
            anchor = assignments.get(customer.id) or responsibility.created_at or customer.created_at
        else:
            owner_id = customer.owner_user_id
            anchor = customer.created_at
        if owner_id is None:
            continue
        result.append({
            "customer": customer,
            "responsibility": responsibility,
            "owner_id": int(owner_id),
            "anchor_date": anchor.date() if anchor else today,
            "last_date": last_dates.get(customer.id),
            "previous_last_date": previous_dates.get(customer.id),
        })
    return result


def coverage_for(entries: list[dict], owner_id: int, frequencies: dict, today: date, *,
                 previous: bool = False) -> dict:
    owned = [entry for entry in entries if entry["owner_id"] == owner_id]
    totals = {level: {"level": level, "frequency_days": days, "on_track": 0, "total": 0}
              for level, days in frequencies.items()}
    overdue = []
    ungraded = 0
    for entry in owned:
        customer = entry["customer"]
        level = customer.customer_level
        if level not in frequencies:
            ungraded += 1
            continue
        frequency = frequencies[level]
        totals[level]["total"] += 1
        responsibility = entry["responsibility"]
        paused = (responsibility is not None and responsibility.stage == "paused"
                  and responsibility.next_plan_date is not None and responsibility.next_plan_date > today)
        last_date = entry["previous_last_date"] if previous else entry["last_date"]
        reference = last_date or entry["anchor_date"]
        days = 0 if paused else max((today - (reference + timedelta(days=frequency))).days, 0)
        if days:
            overdue.append({
                "customer_id": customer.id, "shop_name": customer.shop_name, "level": level,
                "frequency_days": frequency, "last_followup_date": last_date.isoformat() if last_date else None,
                "overdue_days": days,
            })
        else:
            totals[level]["on_track"] += 1
    overdue.sort(key=lambda row: (-row["overdue_days"], row["shop_name"], row["customer_id"]))
    return {
        "coverage": list(totals.values()), "overdue_customers": overdue,
        "overdue_count": len(overdue), "ungraded_customers": ungraded,
        "owner_customer_count": len(owned),
    }
