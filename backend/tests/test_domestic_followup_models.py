from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.domestic_followup.models import (
    DomesticFollowup, DomesticFollowupTask, DomesticFollowupTaskShipment,
)
from tests.domestic_followup_helpers import make_customer, make_shipment, make_user


def test_task_source_key_is_unique(db):
    user = make_user(db, "fu_model_a")
    customer = make_customer(db, user, "模型测试店A")
    db.add(DomesticFollowupTask(task_type="plan", customer_id=customer.id, assignee_user_id=user.id,
                                source_key="plan:1", title="t", due_date=date(2026, 11, 2)))
    db.flush()
    db.add(DomesticFollowupTask(task_type="plan", customer_id=customer.id, assignee_user_id=user.id,
                                source_key="plan:1", title="t2", due_date=date(2026, 11, 2)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_shipment_links_to_only_one_task(db):
    user = make_user(db, "fu_model_b")
    customer = make_customer(db, user, "模型测试店B")
    shipment = make_shipment(db, customer, user, datetime(2026, 10, 27, 10, 0))
    tasks = []
    for key in ("receipt:a", "receipt:b"):
        task = DomesticFollowupTask(task_type="receipt", customer_id=customer.id, assignee_user_id=user.id,
                                    source_key=key, title="t", due_date=date(2026, 10, 30))
        db.add(task)
        tasks.append(task)
    db.flush()
    db.add(DomesticFollowupTaskShipment(task_id=tasks[0].id, shipment_id=shipment.id))
    db.flush()
    db.add(DomesticFollowupTaskShipment(task_id=tasks[1].id, shipment_id=shipment.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_followup_request_id_is_unique(db):
    user = make_user(db, "fu_model_c")
    for _ in range(2):
        db.add(DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 10, 30), request_id="same"))
    with pytest.raises(IntegrityError):
        db.flush()
