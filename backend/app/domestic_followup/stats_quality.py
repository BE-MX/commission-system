"""行为质量与待办纪律：只呈现可核对的事实，不合成评分。"""
from datetime import date

from sqlalchemy.orm import Session

from app.domestic_followup.constants import OPEN_ITEM_STATES, TRACKED_KINDS
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def quality_stats(db: Session, user_id: int, records: list[DomesticFollowup], start: date, end: date,
                  today: date) -> dict:
    resulted = [row for row in records if row.result_code]
    next_count = sum(row.next_date is not None for row in records)
    progress_count = sum(bool(row.effective_progress) for row in resulted)
    plans = (db.query(DomesticFollowupTask)
             .filter(DomesticFollowupTask.assignee_user_id == user_id,
                     DomesticFollowupTask.task_type == "plan",
                     DomesticFollowupTask.due_date >= start, DomesticFollowupTask.due_date <= end,
                     DomesticFollowupTask.due_date <= today).all())
    on_time = sum(task.status == "done" and task.snooze_count == 0 and task.closed_at is not None
                  and task.closed_at.date() <= task.due_date for task in plans)
    receipts = (db.query(DomesticFollowupTask)
                .filter(DomesticFollowupTask.assignee_user_id == user_id,
                        DomesticFollowupTask.task_type == "receipt",
                        DomesticFollowupTask.due_date >= start, DomesticFollowupTask.due_date <= end).all())
    receipt_done = sum(task.status == "done" for task in receipts)
    receipt_closed = receipt_done + sum(task.status == "expired" for task in receipts)
    open_tasks = (db.query(DomesticFollowupTask)
                  .filter(DomesticFollowupTask.assignee_user_id == user_id,
                          DomesticFollowupTask.task_type.in_(TRACKED_KINDS),
                          DomesticFollowupTask.status == "todo").all())
    longest = max((max((today - task.due_date).days, 0) for task in open_tasks), default=0)

    all_records = (db.query(DomesticFollowup)
                   .filter(DomesticFollowup.author_user_id == user_id, DomesticFollowup.status == "confirmed",
                           DomesticFollowup.followup_date <= today)
                   .order_by(DomesticFollowup.customer_id, DomesticFollowup.followup_date, DomesticFollowup.id).all())
    by_customer = {}
    for row in all_records:
        by_customer.setdefault(row.customer_id, []).append(row)
    gaps = []
    for row in records:
        if row.result_code != "未回复":
            continue
        later = next((candidate for candidate in by_customer.get(row.customer_id, [])
                      if candidate.followup_date > row.followup_date), None)
        if later:
            gaps.append((later.followup_date - row.followup_date).days)
    return {
        "quality": {
            "next_step": {"label": "留下一步", "numerator": next_count, "denominator": len(records),
                          "value": _ratio(next_count, len(records))},
            "commitment": {"label": "约定兑现", "numerator": on_time, "denominator": len(plans),
                           "value": _ratio(on_time, len(plans))},
            "effective_progress": {"label": "有效推进", "numerator": progress_count, "denominator": len(resulted),
                                   "value": _ratio(progress_count, len(resulted))},
        },
        "average_recontact_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
        "average_snooze": round(sum(task.snooze_count for task in plans) / len(plans), 1) if plans else 0,
        "discipline": {
            "receipt_rate": _ratio(receipt_done, receipt_closed),
            "receipt_done": receipt_done, "receipt_total": receipt_closed,
            "open_issues": len(open_tasks), "longest_open_days": longest,
        },
    }


def open_issue_rows(db: Session, start: date, end: date) -> list[DomesticFollowupItem]:
    return (db.query(DomesticFollowupItem)
            .filter(DomesticFollowupItem.kind.in_(TRACKED_KINDS),
                    DomesticFollowupItem.status.in_(OPEN_ITEM_STATES + ("resolved", "closed_no_action")),
                    DomesticFollowupItem.created_at >= start, DomesticFollowupItem.created_at < end)
            .all())
