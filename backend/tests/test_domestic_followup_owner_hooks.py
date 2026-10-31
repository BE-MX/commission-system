from datetime import date

from app.domestic_followup.models import DomesticFollowupTask
from tests.domestic_followup_helpers import make_customer, make_user

TODAY = date(2026, 10, 30)


def _tasks(db, owner, customer):
    for key, kind, assignee in (("p", "plan", owner), ("r", "receipt", owner), ("i", "issue", owner)):
        db.add(DomesticFollowupTask(task_type=kind, customer_id=customer.id, assignee_user_id=assignee.id,
                                    source_key=f"{customer.id}:{key}", title=key, due_date=TODAY))
    db.flush()


def test_owner_change_moves_plan_and_receipt_tasks(db):
    old = make_user(db, "fu_hk_a1")
    new = make_user(db, "fu_hk_a2")
    customer = make_customer(db, old, "钩子店A")
    _tasks(db, old, customer)
    customer.owner_user_id = new.id
    db.flush()
    db.expire_all()
    rows = {t.task_type: t.assignee_user_id for t in db.query(DomesticFollowupTask).all()}
    assert rows == {"plan": new.id, "receipt": new.id, "issue": old.id}


def test_release_to_public_sea_cancels_plan_and_receipt(db):
    old = make_user(db, "fu_hk_b")
    customer = make_customer(db, old, "钩子店B")
    _tasks(db, old, customer)
    customer.owner_user_id = None
    db.flush()
    db.expire_all()
    rows = {t.task_type: (t.status, t.closed_reason) for t in db.query(DomesticFollowupTask).all()}
    assert rows == {"plan": ("cancelled", "客户释放"), "receipt": ("cancelled", "客户释放"), "issue": ("todo", None)}


def test_expired_attribute_still_detects_old_owner(db):
    old = make_user(db, "fu_hk_c1")
    new = make_user(db, "fu_hk_c2")
    customer = make_customer(db, old, "钩子店C")
    _tasks(db, old, customer)
    db.commit()
    db.expire(customer, ["owner_user_id"])
    customer.owner_user_id = new.id
    db.commit()
    db.expire_all()
    plan = db.query(DomesticFollowupTask).filter_by(task_type="plan").one()
    assert plan.assignee_user_id == new.id


def test_rollback_discards_changes(db):
    old = make_user(db, "fu_hk_d1")
    new = make_user(db, "fu_hk_d2")
    customer = make_customer(db, old, "钩子店D")
    _tasks(db, old, customer)
    db.commit()
    customer.owner_user_id = new.id
    db.flush()
    db.rollback()
    plan = db.query(DomesticFollowupTask).filter_by(task_type="plan").one()
    assert plan.assignee_user_id == old.id
