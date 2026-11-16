from datetime import date

from app.domestic_followup import strategy_service
from app.domestic_followup.models import DomesticFollowupItem
from app.domestic_followup.prep_models import DomesticFollowupPrep
from app.domestic_followup.template_models import DomesticFollowupTemplate
from tests.domestic_followup_helpers import make_customer, make_user


def test_urgent_issue_forces_handle_first_even_if_model_would_push_sale(db):
    user = make_user(db, "strategy_handle")
    customer = make_customer(db, user, "紧急售后店")
    db.add(DomesticFollowupItem(followup_id=1, customer_id=customer.id, seq=1, kind="issue", text="整批问题",
                                severity="紧急", status="open"))
    template = DomesticFollowupTemplate(code="T08", version=1, name="复购", status="active", prep_fields=[],
                                        record_fields=[], params={}, avoid=[])
    prep = DomesticFollowupPrep(customer_id=customer.id, author_user_id=user.id, template_code="T08",
                                template_version=1, goal="谈补货", request_id="strategy-handle")
    db.add_all([template, prep])
    db.flush()
    mode, _ = strategy_service._mode(db, prep)
    assert mode == "handle_first"
