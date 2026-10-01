"""A versioned candidate remains distinguishable from the former demo window."""

from datetime import date, datetime

from app.customer.customer_segment_service import classify, prototype_comparison
from app.customer.customer_segment_service import list_customers
from app.customer.models import CustomerSyncCursor
from app.core.time import beijing_now
from tests.test_customer_workbench_lifecycle import _actor, _customer_with_profile


def test_four_real_batches_use_median_window_and_unknown_coverage_is_not_sleep():
    now = datetime(2026, 5, 1, 9)
    dates = [date(2026, 1, 1), date(2026, 1, 31), date(2026, 3, 2), date(2026, 4, 1)]
    assert classify(days=dates, last_interaction=None, covered=True, now=now)[0] == "reorder"
    assert classify(days=dates, last_interaction=None, covered=False, now=now)[0] == "unknown"


def test_three_order_demo_cannot_become_the_company_reorder_label():
    now = datetime(2026, 4, 1, 9)
    dates = [date(2026, 1, 1), date(2026, 1, 31), date(2026, 3, 2)]
    assert prototype_comparison(days=dates, covered=True, now=now) is True
    assert classify(days=dates, last_interaction=None, covered=True, now=now)[0] == "active"


def test_contact_sync_cannot_claim_order_and_message_coverage(db):
    account, owner = _customer_with_profile(db)
    db.add(CustomerSyncCursor(id=99111, source_system="okki", resource_type="contacts",
        scope_key="unrelated-tenant", sync_status="idle", generation=1,
        last_success_at=beijing_now(), last_counts_json={}))
    db.flush()
    result = list_customers(db, _actor(owner), page=1, page_size=10, preview=True)
    row = next(row for row in result["items"] if row["customer_id"] == account.id)
    assert row["source_coverage"] == "unknown"
    assert row["candidate_tier"] == "unknown"


def test_action_completion_without_source_message_is_not_real_interaction(db):
    from tests.test_pcw_workitem_service import _action, _open_item

    account, owner = _customer_with_profile(db)
    now = beijing_now()
    db.add(CustomerSyncCursor(id=99201, source_system="okki", resource_type="orders",
        scope_key="default", sync_status="idle", generation=1, last_success_at=now, last_counts_json={}))
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    action.status = "done"
    action.completed_at = now
    action.channel = "email"
    db.flush()
    row = list_customers(db, _actor(owner), page=1, page_size=10, preview=True)["items"][0]
    assert row["source_coverage"] == "unknown"
    assert row["candidate_tier"] == "unknown"
    assert row["last_interaction_at"] is None


def test_real_order_and_whatsapp_adapter_watermarks_can_prove_coverage(db):
    from app.whatsapp.models import WhatsAppAccount
    from tests.test_pcw_order_analytics import _order
    from tests.test_pcw_evaluation import _conversation, _message

    account, owner = _customer_with_profile(db)
    now = beijing_now()
    _order(db, account, seq=99661, order_date=now.date(), items=[{"color": "1B"}])
    conv = _conversation(db, account, external_id="real-covered-interaction")
    _message(db, account, conv, external_id="real-customer-answer", direction="in",
        sent_at=now, record_id=99662)
    db.add(CustomerSyncCursor(id=99202, source_system="okki", resource_type="orders",
        scope_key="tenant-a", sync_status="idle", generation=1,
        last_success_at=now, last_counts_json={}))
    db.add(WhatsAppAccount(account_uid=conv.source_account_key, ark_user_id=owner.id,
        status="active", last_sync_at=now))
    db.flush()
    row = list_customers(db, _actor(owner), page=1, page_size=10, preview=True)["items"][0]
    assert row["source_coverage"] == "verified"
    assert row["candidate_tier"] == "active"
