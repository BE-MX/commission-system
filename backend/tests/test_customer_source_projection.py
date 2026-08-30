from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.time import beijing_now
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactRelationship,
    CustomerConversation,
    CustomerEvent,
    CustomerExternalIdentity,
    CustomerFact,
    CustomerMessage,
    CustomerOpportunity,
    CustomerOpportunityEvent,
    CustomerOrder,
    CustomerOrderItem,
    CustomerResearchTask,
    CustomerSourceRecord,
    CustomerSyncCursor,
)
from app.customer.projection_service import (
    ProjectionError,
    ProjectionRetryRequired,
    claim_sync_scope,
    project_alibaba_inquiry,
    project_okki_contact,
    project_okki_customer,
    project_okki_order,
    project_sync_batch,
)
from app.customer.projection_common import insert_or_load_expected_unique
from app.customer.workflow_service import append_opportunity_event, upsert_opportunity


def _alibaba_payload(*, inquiry_id="INQ-1", conversation_id="CONV-1"):
    return {
        "inquiry_id": inquiry_id,
        "conversation_id": conversation_id,
        "buyer_id": "BUYER-1",
        "member_id": "MEMBER-1",
        "contact_name": "Alice",
        "contact_email": "alice@gmail.com",
        "company_name": "Alice",
        "occurred_at": "2026-08-29T22:00:00Z",
        "messages": [
            {
                "message_id": "MSG-2",
                "direction": "out",
                "sender_type": "external_user",
                "content_type": "text",
                "content_text": "Thanks",
                "sent_at": "2026-08-30T08:10:00+08:00",
                "attachments": [],
            },
            {
                "message_id": "MSG-1",
                "direction": "in",
                "sender_type": "customer_contact",
                "content_type": "mixed",
                "content_text": " Need 100 pieces\n",
                "sent_at": "2026-08-30T08:00:00+08:00",
                "attachments": [{
                    "file_name": "brief.pdf",
                    "mime_type": "application/pdf",
                    "size": 1234,
                    "source_ref": "alibaba://attachment/A-1",
                    "content_base64": "must-not-enter-projection",
                }],
            },
        ],
    }


def _okki_customer_payload(company_id="COMP-1", company_name="Acme Hair"):
    return {
        "company_id": company_id,
        "company_name": company_name,
        "updated_at": "2026-08-30T09:00:00+08:00",
    }


def _project_okki_customer(db, *, account="tenant-a", company_id="COMP-1"):
    receipt = project_okki_customer(
        db,
        source_account_key=account,
        payload=_okki_customer_payload(company_id),
        sync_cursor="customer:1",
    )
    assert receipt.status == "processed"
    return receipt


def _okki_order_payload(*, order_id="ORDER-1", company_id="COMP-1", items=None):
    return {
        "order_id": order_id,
        "company_id": company_id,
        "status": "13972831656",
        "status_name": "已结束",
        "account_date": "2026-08-30",
        "amount_usd": "10",
        "items": [] if items is None else items,
    }


def test_alibaba_inquiry_projects_namespaced_contact_conversation_messages_and_pending_opportunity(db):
    receipt = project_alibaba_inquiry(
        db,
        source_account_key="shop-a",
        payload=_alibaba_payload(),
        sync_cursor="inquiry:1",
        captured_at=datetime(2026, 8, 30, 9, 0),
    )

    assert receipt.status == "processed"
    customer = db.get(CustomerAccount, receipt.customer_id)
    assert customer.canonical_company_name is None
    assert customer.identity_status == "provisional"
    assert customer.relationship_stage == "discovered"

    identities = db.query(CustomerExternalIdentity).order_by(CustomerExternalIdentity.id).all()
    assert {(row.identifier_type, row.contact_id is not None, row.customer_id) for row in identities} == {
        ("buyer_id", True, None),
        ("member_id", True, None),
    }
    assert all(row.raw_value != "Alice" for row in identities)

    messages = db.query(CustomerMessage).order_by(CustomerMessage.sent_at).all()
    assert [row.external_message_id for row in messages] == ["MSG-1", "MSG-2"]
    assert messages[0].sent_at == datetime(2026, 8, 30, 8, 0)
    assert messages[0].content_text == " Need 100 pieces\n"
    assert messages[0].attachment_meta_json == [{
        "file_name": "brief.pdf",
        "mime_type": "application/pdf",
        "size": 1234,
        "source_ref": "alibaba://attachment/A-1",
    }]
    assert db.query(CustomerSourceRecord).count() == 3
    assert "content_base64" not in str([
        row.payload_json for row in db.query(CustomerSourceRecord).all()
    ])

    opportunity = db.query(CustomerOpportunity).one()
    assert opportunity.customer_id == customer.id
    assert opportunity.source_system == "alibaba"
    assert opportunity.source_account_key == "shop-a"
    assert opportunity.source_key == "inquiry:INQ-1"
    assert opportunity.status == "pending"
    assert opportunity.owner_user_id is None
    assert db.query(CustomerResearchTask).filter_by(
        customer_id=customer.id,
        task_type="identity_enrichment",
    ).count() == 1


def test_alibaba_duplicate_and_out_of_order_replay_are_idempotent_but_account_namespaces_do_not_collide(db):
    first = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=_alibaba_payload(),
    )
    first_message_captured_at = db.get(
        CustomerMessage, first.message_ids[0],
    ).captured_at
    replay = project_alibaba_inquiry(
        db,
        source_account_key="shop-a",
        payload=_alibaba_payload(),
        captured_at=beijing_now() + timedelta(hours=1),
    )
    other_account = project_alibaba_inquiry(
        db, source_account_key="shop-b", payload=_alibaba_payload(),
    )

    assert replay.customer_id == first.customer_id
    assert replay.conversation_id == first.conversation_id
    assert replay.opportunity_id == first.opportunity_id
    assert db.get(CustomerMessage, first.message_ids[0]).captured_at == first_message_captured_at
    assert other_account.customer_id != first.customer_id
    assert db.query(CustomerAccount).count() == 2
    assert db.query(CustomerMessage).count() == 4
    assert db.query(CustomerOpportunity).count() == 2
    assert db.query(CustomerSourceRecord).count() == 6


def test_alibaba_invalid_identity_preserves_raw_source_and_quarantines_without_partial_projection(db):
    payload = _alibaba_payload()
    payload["contact_email"] = "not-an-email"

    receipt = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=payload,
    )

    assert receipt.status == "quarantined"
    assert receipt.error_code == "CONTACT_POINT_INVALID"
    sources = db.query(CustomerSourceRecord).all()
    assert len(sources) == 3
    assert all(row.processing_status == "quarantined" for row in sources)
    assert db.query(CustomerAccount).count() == 0
    assert db.query(CustomerMessage).count() == 0
    assert db.query(CustomerOpportunity).count() == 0


def test_invalid_external_identifier_is_saved_under_safe_key_then_quarantined(db):
    payload = _alibaba_payload(inquiry_id="BAD\x00ID")

    receipt = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=payload,
    )

    assert receipt.status == "quarantined"
    assert receipt.error_code == "INQUIRY_ID_INVALID"
    source = db.query(CustomerSourceRecord).filter_by(
        source_entity_type="inquiry",
    ).one()
    assert source.external_record_id.startswith("invalid:inquiry:")
    assert source.payload_json["inquiry_id"] == "BAD\x00ID"


def test_okki_customer_and_contact_projection_use_company_identity_and_stable_contact_replay(db):
    customer_receipt = _project_okki_customer(db)
    contact_payload = {
        "contact_id": "CONTACT-1",
        "company_id": "COMP-1",
        "contact_name": "Bob",
        "email": "bob@example.com",
        "job_title": "Buyer",
        "updated_at": "2026-08-30T10:00:00+08:00",
    }
    first = project_okki_contact(
        db, source_account_key="tenant-a", payload=contact_payload,
    )
    changed = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={**contact_payload, "job_title": "Purchasing Manager"},
    )

    assert first.customer_id == changed.customer_id == customer_receipt.customer_id
    assert first.contact_id == changed.contact_id
    assert db.query(CustomerContact).count() == 1
    relation = db.query(CustomerContactRelationship).one()
    assert relation.job_title == "Purchasing Manager"
    identity = db.query(CustomerExternalIdentity).filter_by(
        identifier_type="company_id",
        source_account_key="tenant-a",
    ).one()
    assert identity.customer_id == customer_receipt.customer_id
    assert db.query(CustomerSourceRecord).filter_by(source_entity_type="contact").count() == 2


def test_okki_contact_identity_is_namespaced_and_company_move_reuses_contact_and_ends_old_relation(db):
    customer_a = _project_okki_customer(db, company_id="COMP-A")
    customer_b = _project_okki_customer(db, company_id="COMP-B")
    customer_other_tenant = _project_okki_customer(
        db, account="tenant-b", company_id="COMP-A",
    )
    base = {
        "contact_id": "CONTACT-SHARED",
        "contact_name": "Taylor",
        "email": "taylor@example.com",
        "updated_at": "2026-08-30T10:00:00+08:00",
    }
    at_a = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={**base, "company_id": "COMP-A"},
    )
    moved_to_b = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            **base,
            "company_id": "COMP-B",
            "updated_at": "2026-08-31T10:00:00+08:00",
        },
    )
    other_tenant = project_okki_contact(
        db,
        source_account_key="tenant-b",
        payload={**base, "company_id": "COMP-A"},
    )

    assert at_a.customer_id == customer_a.customer_id
    assert moved_to_b.customer_id == customer_b.customer_id
    assert moved_to_b.contact_id == at_a.contact_id
    assert other_tenant.customer_id == customer_other_tenant.customer_id
    assert other_tenant.contact_id != at_a.contact_id
    assert db.query(CustomerContact).count() == 2
    old_relation = db.query(CustomerContactRelationship).filter_by(
        customer_id=customer_a.customer_id,
        contact_id=at_a.contact_id,
    ).one()
    new_relation = db.query(CustomerContactRelationship).filter_by(
        customer_id=customer_b.customer_id,
        contact_id=at_a.contact_id,
    ).one()
    assert old_relation.effective_to == datetime(2026, 8, 31, 10, 0)
    assert new_relation.effective_to is None


def test_okki_valid_order_and_items_project_atomically_link_exact_opportunity_and_activate_customer(db):
    customer_receipt = _project_okki_customer(db)
    opportunity = upsert_opportunity(
        db,
        customer_id=customer_receipt.customer_id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_key="inquiry:INQ-77",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title="Inquiry 77",
    )
    receipt = project_okki_order(
        db,
        source_account_key="tenant-a",
        payload={
            "order_id": "ORDER-1",
            "company_id": "COMP-1",
            "order_no": "SO-1",
            "status": "13972831656",
            "status_name": "已结束",
            "trail": None,
            "account_date": "2026-08-30",
            "currency": "USD",
            "amount_original": "500.00",
            "amount_usd": "500.00",
            "opportunity_ref": {
                "source_system": "alibaba",
                "source_account_key": "shop-a",
                "source_key": "inquiry:INQ-77",
            },
            "items": [{
                "item_id": "ITEM-1",
                "product_id": "P-1",
                "sku_id": "SKU-1",
                "product_name": "Hair extension",
                "product_family": "hair_extension",
                "model": "M-1",
                "color": "1B",
                "length": "18in",
                "quantity": "100",
                "quantity_unit": "pcs",
                "unit_price": "5",
                "line_amount": "500",
                "item_type": "bulk",
            }],
        },
    )

    assert receipt.status == "processed"
    order = db.get(CustomerOrder, receipt.order_id)
    assert order.customer_id == customer_receipt.customer_id
    assert order.is_valid_business_order is True
    assert db.query(CustomerOrderItem).filter_by(order_id=order.id).count() == 1
    assert db.query(CustomerFact).filter_by(
        customer_id=customer_receipt.customer_id,
        fact_key="commercial.has_valid_order",
    ).one().value_json == {"value": True}
    assert db.get(CustomerOpportunity, opportunity.id).linked_order_id == order.id
    assert db.get(CustomerAccount, customer_receipt.customer_id).relationship_stage == "active_customer"
    assert db.query(CustomerEvent).filter_by(event_type="order.placed").count() == 1


def test_okki_invalid_order_does_not_activate_and_cross_customer_opportunity_ref_quarantines(db):
    customer_a = _project_okki_customer(db, company_id="COMP-A")
    customer_b = _project_okki_customer(db, company_id="COMP-B")
    opportunity_b = upsert_opportunity(
        db,
        customer_id=customer_b.customer_id,
        source_system="alibaba",
        source_account_key="shop-b",
        source_key="inquiry:B",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title="B",
    )
    invalid = project_okki_order(
        db,
        source_account_key="tenant-a",
        payload={
            "order_id": "ORDER-INVALID",
            "company_id": "COMP-A",
            "status": "13972831654",
            "status_name": "未结清",
            "account_date": "2026-08-30",
            "amount_usd": "10",
            "items": [],
        },
    )
    mismatch = project_okki_order(
        db,
        source_account_key="tenant-a",
        payload={
            "order_id": "ORDER-MISMATCH",
            "company_id": "COMP-A",
            "status": "13972831656",
            "status_name": "已结束",
            "account_date": "2026-08-30",
            "amount_usd": "10",
            "opportunity_ref": {
                "source_system": opportunity_b.source_system,
                "source_account_key": opportunity_b.source_account_key,
                "source_key": opportunity_b.source_key,
            },
            "items": [],
        },
    )

    assert invalid.status == "processed"
    assert db.get(CustomerOrder, invalid.order_id).is_valid_business_order is False
    assert db.get(CustomerAccount, customer_a.customer_id).relationship_stage == "discovered"
    assert mismatch.status == "quarantined"
    assert mismatch.error_code == "OPPORTUNITY_CUSTOMER_MISMATCH"
    assert db.query(CustomerOrder).filter_by(external_order_id="ORDER-MISMATCH").count() == 0
    source = db.query(CustomerSourceRecord).filter_by(
        source_entity_type="order",
        external_record_id="ORDER-MISMATCH",
    ).one()
    assert source.processing_status == "quarantined"


def test_order_projection_rolls_back_all_derived_rows_when_one_item_is_invalid(db):
    customer = _project_okki_customer(db)
    receipt = project_okki_order(
        db,
        source_account_key="tenant-a",
        payload={
            "order_id": "ORDER-BAD-ITEM",
            "company_id": "COMP-1",
            "status": "13972831656",
            "status_name": "已结束",
            "account_date": "2026-08-30",
            "amount_usd": "10",
            "items": [{"item_id": "BAD", "quantity": "not-a-number"}],
        },
    )

    assert receipt.status == "quarantined"
    assert receipt.error_code == "ORDER_ITEM_INPUT_INVALID"
    assert db.query(CustomerOrder).filter_by(external_order_id="ORDER-BAD-ITEM").count() == 0
    assert db.query(CustomerOrderItem).count() == 0
    assert db.query(CustomerFact).filter_by(
        customer_id=customer.customer_id,
        fact_key="commercial.has_valid_order",
    ).count() == 0
    assert db.query(CustomerEvent).filter_by(event_type="order.placed").count() == 0
    assert db.query(CustomerSourceRecord).filter(
        CustomerSourceRecord.external_record_id.in_(("ORDER-BAD-ITEM", "ORDER-BAD-ITEM:BAD")),
        CustomerSourceRecord.processing_status == "quarantined",
    ).count() == 2


def test_sync_cursor_advances_only_contiguous_success_prefix_and_rejects_stale_generation(db):
    now = beijing_now()
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-a",
        lease_seconds=60,
        now=now,
    )
    result = project_sync_batch(
        db,
        lease=lease,
        source_account_key="tenant-a",
        expected_cursor_value=None,
        records=[
            {"previous_cursor_value": None, "cursor_value": "1", "payload": {"company_name": "missing id"}},
            {"previous_cursor_value": "1", "cursor_value": "2", "payload": _okki_customer_payload("COMP-2")},
        ],
    )
    cursor = db.get(CustomerSyncCursor, lease.cursor_id)
    assert [item.status for item in result.receipts] == ["quarantined", "processed"]
    assert cursor.cursor_value is None
    assert cursor.sync_status == "degraded"
    assert cursor.last_counts_json["quarantined"] == 1
    assert db.query(CustomerExternalIdentity).filter_by(
        source_account_key="tenant-a",
        identifier_type="company_id",
        normalized_value="COMP-2",
    ).count() == 1

    newer = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-b",
        lease_seconds=60,
        now=beijing_now(),
    )
    with pytest.raises(ProjectionError) as stale:
        project_sync_batch(
            db,
            lease=lease,
            source_account_key="tenant-a",
            expected_cursor_value=None,
            records=[],
        )
    assert stale.value.error_code == "SYNC_CURSOR_FENCE_REJECTED"
    assert newer.generation == lease.generation + 1

    repaired = project_sync_batch(
        db,
        lease=newer,
        source_account_key="tenant-a",
        expected_cursor_value=None,
        records=[
            {"previous_cursor_value": None, "cursor_value": "1", "payload": _okki_customer_payload("COMP-1")},
            {"previous_cursor_value": "1", "cursor_value": "2", "payload": _okki_customer_payload("COMP-2")},
        ],
    )
    assert repaired.committed_cursor == "2"
    assert db.get(CustomerSyncCursor, newer.cursor_id).cursor_value == "2"


def test_expired_sync_lease_cannot_project_or_advance_cursor(db):
    now = beijing_now()
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-expired",
        claimed_by="worker-a",
        lease_seconds=60,
        now=now,
    )
    db.get(CustomerSyncCursor, lease.cursor_id).lease_expires_at = now - timedelta(seconds=1)
    db.flush()

    with pytest.raises(ProjectionError) as expired:
        project_sync_batch(
            db,
            lease=lease,
            source_account_key="tenant-expired",
            expected_cursor_value=None,
            records=[{
                "previous_cursor_value": None,
                "cursor_value": "1",
                "payload": _okki_customer_payload("COMP-EXPIRED"),
            }],
        )

    assert expired.value.error_code == "SYNC_CURSOR_FENCE_REJECTED"
    assert db.query(CustomerSourceRecord).count() == 0


def test_retryable_raw_source_deadlock_uses_stable_new_transaction_error(db, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def deadlock(*_args, **_kwargs):
        raise OperationalError("insert", {}, Exception(1213, "deadlock"))

    monkeypatch.setattr("app.customer.projection_common.append_source_record", deadlock)
    with pytest.raises(ProjectionRetryRequired) as raised:
        project_okki_customer(
            db,
            source_account_key="tenant-a",
            payload=_okki_customer_payload(),
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert db.query(CustomerSourceRecord).count() == 0


def test_raw_source_unique_race_requests_fresh_transaction(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    def duplicate(*_args, **_kwargs):
        raise IntegrityError(
            "insert",
            {},
            Exception(
                1062,
                "Duplicate entry 'x' for key 'uq_customer_source_record_content'",
            ),
        )

    monkeypatch.setattr("app.customer.projection_common.append_source_record", duplicate)
    with pytest.raises(ProjectionRetryRequired) as raised:
        project_okki_customer(
            db,
            source_account_key="tenant-a",
            payload=_okki_customer_payload(),
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert db.query(CustomerSourceRecord).count() == 0


def test_retryable_identity_failure_rolls_back_raw_record_and_requests_new_transaction(db, monkeypatch):
    from app.customer.identity_service import CustomerTransactionRetryRequired

    def retry(*_args, **_kwargs):
        raise CustomerTransactionRetryRequired()

    monkeypatch.setattr("app.customer.projection_alibaba.resolve_business_context", retry)
    with pytest.raises(ProjectionRetryRequired) as raised:
        project_alibaba_inquiry(
            db,
            source_account_key="shop-a",
            payload=_alibaba_payload(),
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert db.query(CustomerSourceRecord).count() == 0


def test_projection_adapters_are_ark_writers_only_and_customer_timeline_has_no_external_db_dependency():
    import inspect

    from app.customer import (
        projection_alibaba,
        projection_common,
        projection_okki,
        projection_okki_order,
        projection_service,
    )
    from app.insight import customer_source_service

    projection_source = "\n".join(
        inspect.getsource(module).lower()
        for module in (
            projection_service,
            projection_common,
            projection_alibaba,
            projection_okki,
            projection_okki_order,
        )
    )
    timeline_source = inspect.getsource(customer_source_service).lower()
    assert "business_db_name" not in projection_source
    assert ".execute(" not in projection_source
    assert "requests." not in projection_source
    assert "httpx." not in projection_source
    assert "business_db_name" not in timeline_source
    assert "lsordertest" not in timeline_source


def test_insight_timeline_reads_projected_messages_and_orders_from_ark(db):
    from app.customer.access_service import CustomerAccess
    from app.insight.customer_source_service import get_source_records

    inquiry = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=_alibaba_payload(),
    )
    access = CustomerAccess(
        customer_id=inquiry.customer_id,
        actor_user_id=1,
        can_manage=True,
        max_data_classification="restricted_internal",
        max_visibility_scope="management",
        run_id=None,
    )
    messages = get_source_records(
        db, inquiry.customer_id, "message", access=access,
    )
    assert {row["message_id"] for row in messages} == set(inquiry.message_ids)
    assert {row["type_code"] for row in messages} == {"message"}

    customer = _project_okki_customer(db, account="tenant-orders", company_id="COMP-O")
    order = project_okki_order(
        db,
        source_account_key="tenant-orders",
        payload={
            "order_id": "ORDER-O",
            "company_id": "COMP-O",
            "status": "13972831656",
            "status_name": "已结束",
            "account_date": "2026-08-30",
            "amount_usd": "10",
            "items": [],
        },
    )
    order_access = CustomerAccess(
        customer_id=customer.customer_id,
        actor_user_id=1,
        can_manage=True,
        max_data_classification="restricted_internal",
        max_visibility_scope="management",
        run_id=None,
    )
    orders = get_source_records(
        db, customer.customer_id, "order", access=order_access,
    )
    assert [row["order_id"] for row in orders] == [order.order_id]
    assert orders[0]["is_valid_business_order"] is True


def test_sync_lease_rejects_cross_account_projection_without_writing(db):
    now = beijing_now()
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-a",
        now=now,
    )

    with pytest.raises(ProjectionError) as raised:
        project_sync_batch(
            db,
            lease=lease,
            source_account_key="tenant-b",
            expected_cursor_value=None,
            records=[{
                "previous_cursor_value": None,
                "cursor_value": "1",
                "payload": _okki_customer_payload("COMP-B"),
            }],
        )

    assert raised.value.error_code == "SYNC_SCOPE_SOURCE_ACCOUNT_MISMATCH"
    assert db.query(CustomerSourceRecord).count() == 0
    assert db.get(CustomerSyncCursor, lease.cursor_id).cursor_value is None


def test_sync_cursor_requires_frozen_opaque_predecessor_chain(db):
    now = beijing_now()
    first = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-a",
        now=now,
    )
    project_sync_batch(
        db,
        lease=first,
        source_account_key="tenant-a",
        expected_cursor_value=None,
        records=[{
            "previous_cursor_value": None,
            "cursor_value": "100",
            "payload": _okki_customer_payload("COMP-100"),
        }],
    )
    later = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-b",
        now=beijing_now(),
    )

    with pytest.raises(ProjectionError) as raised:
        project_sync_batch(
            db,
            lease=later,
            source_account_key="tenant-a",
            expected_cursor_value="100",
            records=[{
                "previous_cursor_value": "49",
                "cursor_value": "50",
                "payload": _okki_customer_payload("COMP-50"),
            }],
        )

    assert raised.value.error_code == "CURSOR_SEQUENCE_CONFLICT"
    assert db.get(CustomerSyncCursor, later.cursor_id).cursor_value == "100"
    assert db.query(CustomerSourceRecord).filter_by(
        external_record_id="COMP-50"
    ).count() == 0


def test_exact_processed_replay_is_unchanged_and_cannot_be_quarantined_by_other_customer(db):
    first_payload = _alibaba_payload(inquiry_id="INQ-A", conversation_id="CONV-A")
    first_payload["company_id"] = "COMP-A"
    first = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=first_payload,
    )
    protected_message = db.query(CustomerSourceRecord).filter_by(
        source_entity_type="message",
        external_record_id="MSG-1",
    ).one()
    assert protected_message.customer_id == first.customer_id
    assert protected_message.processing_status == "processed"

    second_payload = _alibaba_payload(inquiry_id="INQ-B", conversation_id="CONV-B")
    second_payload["company_id"] = "COMP-B"
    rejected = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=second_payload,
    )

    assert rejected.status == "quarantined"
    assert db.get(CustomerSourceRecord, protected_message.id).processing_status == "processed"
    replay = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=first_payload,
    )
    assert replay.status == "processed"
    assert replay.outcome == "unchanged"


def test_same_alibaba_conversation_reuses_customer_across_distinct_inquiries(db):
    first = project_alibaba_inquiry(
        db,
        source_account_key="shop-a",
        payload=_alibaba_payload(inquiry_id="INQ-1", conversation_id="CONV-X"),
    )
    second_payload = _alibaba_payload(inquiry_id="INQ-2", conversation_id="CONV-X")
    second_payload["messages"] = [{
        **second_payload["messages"][0],
        "message_id": "MSG-3",
    }]
    second = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=second_payload,
    )

    assert second.status == "processed"
    assert second.customer_id == first.customer_id
    assert second.conversation_id == first.conversation_id
    assert db.query(CustomerConversation).count() == 1
    assert db.query(CustomerOpportunity).count() == 2


def test_same_alibaba_conversation_adds_late_company_identity_to_existing_customer(db):
    first_payload = _alibaba_payload(
        inquiry_id="INQ-PERSONAL",
        conversation_id="CONV-LATE-COMPANY",
    )
    first = project_alibaba_inquiry(
        db,
        source_account_key="shop-a",
        payload=first_payload,
    )
    second_payload = _alibaba_payload(
        inquiry_id="INQ-COMPANY",
        conversation_id="CONV-LATE-COMPANY",
    )
    second_payload.update({
        "company_id": "COMP-LATE",
        "company_name": "Late Identified Company",
        "messages": [{
            **second_payload["messages"][0],
            "message_id": "MSG-LATE-COMPANY",
        }],
    })

    second = project_alibaba_inquiry(
        db,
        source_account_key="shop-a",
        payload=second_payload,
    )

    assert second.status == "processed"
    assert second.customer_id == first.customer_id
    assert second.conversation_id == first.conversation_id
    assert db.query(CustomerAccount).count() == 1
    company_identity = db.query(CustomerExternalIdentity).filter_by(
        source_system="alibaba",
        source_account_key="shop-a",
        identifier_type="company_id",
        normalized_value="COMP-LATE",
        status="active",
    ).one()
    assert company_identity.customer_id == first.customer_id


def test_same_alibaba_conversation_rejects_conflicting_late_company_identity(db):
    first_payload = _alibaba_payload(
        inquiry_id="INQ-ANCHORED",
        conversation_id="CONV-ANCHORED",
    )
    first_payload["company_id"] = "COMP-A"
    first = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=first_payload,
    )
    other_payload = _alibaba_payload(
        inquiry_id="INQ-OTHER",
        conversation_id="CONV-OTHER",
    )
    other_payload.update({
        "company_id": "COMP-B",
        "buyer_id": "BUYER-B",
        "member_id": "MEMBER-B",
        "messages": [{
            **other_payload["messages"][0],
            "message_id": "MSG-OTHER",
        }],
    })
    other = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=other_payload,
    )
    conflict_payload = _alibaba_payload(
        inquiry_id="INQ-CONFLICT",
        conversation_id="CONV-ANCHORED",
    )
    conflict_payload.update({
        "company_id": "COMP-B",
        "buyer_id": "BUYER-B",
        "member_id": "MEMBER-B",
        "messages": [{
            **conflict_payload["messages"][0],
            "message_id": "MSG-CONFLICT",
        }],
    })

    conflict = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=conflict_payload,
    )

    assert conflict.status == "quarantined"
    assert conflict.error_code in {
        "CONVERSATION_CUSTOMER_MISMATCH",
        "IDENTITY_RESOLUTION_CONFLICT",
    }
    assert db.get(CustomerConversation, first.conversation_id).customer_id == first.customer_id
    assert first.customer_id != other.customer_id


def test_projection_resolves_alibaba_and_okki_owner_bindings(db):
    user = ArkUser(
        username="source-owner", password_hash="x", real_name="Source Owner",
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add_all([
        ArkUserExternalBinding(
            ark_user_id=user.id,
            provider="alibaba_icbu",
            external_account_id="ALI-OWNER",
            binding_status="active",
        ),
        ArkUserExternalBinding(
            ark_user_id=user.id,
            provider="okki",
            external_account_id="OKKI-OWNER",
            binding_status="active",
        ),
    ])
    db.flush()
    ali_payload = _alibaba_payload()
    ali_payload["owner_external_user_id"] = "ALI-OWNER"
    ali = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=ali_payload,
    )
    conversation = db.get(CustomerConversation, ali.conversation_id)
    customer = _project_okki_customer(db)
    order_payload = _okki_order_payload()
    order_payload["owner_external_user_id"] = "OKKI-OWNER"
    order = project_okki_order(
        db, source_account_key="tenant-a", payload=order_payload,
    )

    assert conversation.owner_user_id == user.id
    assert db.get(CustomerOrder, order.order_id).owner_user_id == user.id
    assert customer.customer_id == order.customer_id


def test_order_item_fallback_keeps_duplicate_sku_lines_and_full_snapshot_removes_missing(db):
    _project_okki_customer(db)
    base_line = {
        "sku_id": "SKU-1",
        "product_name": "Hair",
        "quantity": "1",
        "unit_price": "5",
        "line_amount": "5",
        "item_type": "bulk",
    }
    first_payload = _okki_order_payload(
        items=[base_line, {**base_line, "quantity": "2", "line_amount": "10"}],
    )
    first_payload["item_snapshot_mode"] = "full"
    first = project_okki_order(
        db, source_account_key="tenant-a", payload=first_payload,
    )
    assert len(set(first.item_ids)) == 2
    assert db.query(CustomerOrderItem).filter_by(order_id=first.order_id).count() == 2

    reduced_payload = _okki_order_payload(items=[base_line])
    reduced_payload["item_snapshot_mode"] = "full"
    second = project_okki_order(
        db, source_account_key="tenant-a", payload=reduced_payload,
    )

    assert second.order_id == first.order_id
    assert db.query(CustomerOrderItem).filter_by(order_id=first.order_id).count() == 1


@pytest.mark.parametrize(
    ("projector", "payload", "entity_type"),
    [
        (
            project_alibaba_inquiry,
            {**_alibaba_payload(), "occurred_at": "not-a-time"},
            "inquiry",
        ),
        (
            project_okki_customer,
            {**_okki_customer_payload(), "updated_at": "not-a-time"},
            "customer",
        ),
    ],
)
def test_invalid_declared_business_time_is_quarantined_without_projection(
    db, projector, payload, entity_type,
):
    receipt = projector(db, source_account_key="tenant-a", payload=payload)

    assert receipt.status == "quarantined"
    assert receipt.error_code == "SOURCE_BUSINESS_TIME_INVALID"
    source = db.query(CustomerSourceRecord).filter_by(
        source_entity_type=entity_type,
    ).one()
    assert source.processing_status == "quarantined"
    assert source.occurred_at is None


def test_invalid_okki_contact_and_order_business_times_are_quarantined(db):
    _project_okki_customer(db)
    contact = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            "contact_id": "CONTACT-BAD-TIME",
            "company_id": "COMP-1",
            "contact_name": "Bad Time",
            "updated_at": "not-a-time",
        },
    )
    order = project_okki_order(
        db,
        source_account_key="tenant-a",
        payload={
            **_okki_order_payload(order_id="ORDER-BAD-TIME"),
            "account_date": "not-a-date",
        },
    )

    assert contact.status == order.status == "quarantined"
    assert contact.error_code == order.error_code == "SOURCE_BUSINESS_TIME_INVALID"
    assert db.query(CustomerContact).count() == 0
    assert db.query(CustomerOrder).count() == 0


def test_alibaba_inquiry_source_does_not_duplicate_messages_and_uses_highest_classification(db):
    project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=_alibaba_payload(),
    )

    source = db.query(CustomerSourceRecord).filter_by(
        source_entity_type="inquiry",
    ).one()
    assert "messages" not in source.payload_json
    assert source.data_classification == "restricted_internal"
    assert source.payload_json["contact_email"] == "alice@gmail.com"


def test_sync_batch_reports_inserted_updated_and_unchanged_outcomes(db):
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-1",
    )
    project_sync_batch(
        db,
        lease=lease,
        source_account_key="tenant-a",
        expected_cursor_value=None,
        records=[{
            "previous_cursor_value": None,
            "cursor_value": "1",
            "payload": _okki_customer_payload(),
        }],
    )
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-2",
    )
    replay = project_sync_batch(
        db,
        lease=lease,
        source_account_key="tenant-a",
        expected_cursor_value="1",
        records=[{
            "previous_cursor_value": "1",
            "cursor_value": "2",
            "payload": _okki_customer_payload(),
        }],
    )

    assert replay.receipts[0].outcome == "unchanged"
    assert db.get(CustomerSyncCursor, lease.cursor_id).last_counts_json == {
        "fetched": 1,
        "inserted": 0,
        "updated": 0,
        "unchanged": 1,
        "quarantined": 0,
    }
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-3",
    )
    updated = project_sync_batch(
        db,
        lease=lease,
        source_account_key="tenant-a",
        expected_cursor_value="2",
        records=[{
            "previous_cursor_value": "2",
            "cursor_value": "3",
            "payload": _okki_customer_payload("COMP-1", "Renamed Company"),
        }],
    )
    assert updated.receipts[0].outcome == "updated"
    assert db.get(CustomerSyncCursor, lease.cursor_id).last_counts_json["updated"] == 1


def test_alibaba_receipt_aggregates_new_and_revised_message_outcomes(db):
    base = _alibaba_payload(inquiry_id="INQ-OUTCOME", conversation_id="CONV-OUTCOME")
    first = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=base,
    )
    with_new_message = {
        **base,
        "messages": [
            *base["messages"],
            {
                "message_id": "MSG-NEW",
                "direction": "in",
                "sender_type": "customer_contact",
                "content_type": "text",
                "content_text": "new message",
                "sent_at": "2026-08-30T09:00:00+08:00",
                "attachments": [],
            },
        ],
    }
    inserted = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=with_new_message,
    )
    revised = {
        **with_new_message,
        "messages": [
            *with_new_message["messages"][:-1],
            {
                **with_new_message["messages"][-1],
                "content_text": "revised message",
            },
        ],
    }
    updated = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=revised,
    )
    replay = project_alibaba_inquiry(
        db, source_account_key="shop-a", payload=revised,
    )

    assert first.outcome == "inserted"
    assert inserted.outcome == "inserted"
    assert updated.outcome == "updated"
    assert replay.outcome == "unchanged"


def test_alibaba_batch_counts_new_message_as_inserted(db):
    first_lease = claim_sync_scope(
        db,
        source_system="alibaba",
        resource_type="inquiries",
        scope_key="shop-a",
        claimed_by="worker-1",
    )
    base = _alibaba_payload(inquiry_id="INQ-BATCH", conversation_id="CONV-BATCH")
    project_sync_batch(
        db,
        lease=first_lease,
        source_account_key="shop-a",
        expected_cursor_value=None,
        records=[{
            "previous_cursor_value": None,
            "cursor_value": "1",
            "payload": base,
        }],
    )
    second_lease = claim_sync_scope(
        db,
        source_system="alibaba",
        resource_type="inquiries",
        scope_key="shop-a",
        claimed_by="worker-2",
    )
    changed = {
        **base,
        "messages": [
            *base["messages"],
            {
                "message_id": "MSG-BATCH-NEW",
                "direction": "in",
                "sender_type": "customer_contact",
                "content_type": "text",
                "content_text": "new in later fetch",
                "sent_at": "2026-08-30T09:00:00+08:00",
                "attachments": [],
            },
        ],
    }

    result = project_sync_batch(
        db,
        lease=second_lease,
        source_account_key="shop-a",
        expected_cursor_value="1",
        records=[{
            "previous_cursor_value": "1",
            "cursor_value": "2",
            "payload": changed,
        }],
    )

    assert result.receipts[0].outcome == "inserted"
    counts = db.get(CustomerSyncCursor, second_lease.cursor_id).last_counts_json
    assert counts["inserted"] == 1
    assert counts["unchanged"] == 0


def test_okki_contact_stale_move_replay_does_not_reopen_old_company(db):
    customer_a = _project_okki_customer(db, company_id="COMP-A")
    customer_b = _project_okki_customer(db, company_id="COMP-B")
    base = {
        "contact_id": "CONTACT-MOVE",
        "contact_name": "Taylor",
        "email": "taylor@example.com",
    }
    contact = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            **base,
            "company_id": "COMP-A",
            "job_title": "Buyer",
            "updated_at": "2026-08-30T10:00:00+08:00",
        },
    )
    project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            **base,
            "company_id": "COMP-B",
            "job_title": "Purchasing Manager",
            "updated_at": "2026-08-31T10:00:00+08:00",
        },
    )
    stale = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            **base,
            "company_id": "COMP-A",
            "job_title": "Historical Buyer",
            "updated_at": "2026-08-30T11:00:00+08:00",
        },
    )

    assert stale.status == "processed"
    assert stale.customer_id == customer_a.customer_id
    live = db.query(CustomerContactRelationship).filter_by(
        contact_id=contact.contact_id,
        effective_to=None,
    ).one()
    assert live.customer_id == customer_b.customer_id
    assert live.job_title == "Purchasing Manager"


def test_okki_contact_same_time_cross_company_conflict_is_quarantined(db):
    customer_a = _project_okki_customer(db, company_id="COMP-A")
    customer_b = _project_okki_customer(db, company_id="COMP-B")
    at = "2026-08-30T10:00:00+08:00"
    first = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            "contact_id": "CONTACT-CONFLICT",
            "company_id": "COMP-A",
            "contact_name": "Taylor",
            "updated_at": at,
        },
    )
    conflict = project_okki_contact(
        db,
        source_account_key="tenant-a",
        payload={
            "contact_id": "CONTACT-CONFLICT",
            "company_id": "COMP-B",
            "contact_name": "Taylor",
            "job_title": "Buyer",
            "updated_at": at,
        },
    )

    assert conflict.status == "quarantined"
    assert conflict.error_code == "CONTACT_RELATIONSHIP_TIME_CONFLICT"
    live = db.query(CustomerContactRelationship).filter_by(
        contact_id=first.contact_id,
        effective_to=None,
    ).one()
    assert live.customer_id == customer_a.customer_id
    assert live.customer_id != customer_b.customer_id


def test_deterministic_projection_integrity_error_quarantines_instead_of_retrying(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    def deterministic_constraint(*_args, **_kwargs):
        raise IntegrityError("insert", {}, Exception(3819, "check constraint"))

    monkeypatch.setattr(
        "app.customer.projection_okki.resolve_business_context",
        deterministic_constraint,
    )
    receipt = project_okki_customer(
        db, source_account_key="tenant-a", payload=_okki_customer_payload(),
    )

    assert receipt.status == "quarantined"
    assert receipt.error_code == "PROJECTION_CONSTRAINT_INVALID"
    assert db.query(CustomerSourceRecord).one().processing_status == "quarantined"


def test_expected_unique_races_load_winners_for_every_projected_entity(db):
    from sqlalchemy import inspect

    ali = project_alibaba_inquiry(
        db,
        source_account_key="shop-race",
        payload=_alibaba_payload(
            inquiry_id="INQ-RACE",
            conversation_id="CONV-RACE",
        ),
    )
    _project_okki_customer(db, account="tenant-race", company_id="COMP-RACE")
    okki = project_okki_order(
        db,
        source_account_key="tenant-race",
        payload=_okki_order_payload(
            order_id="ORDER-RACE",
            company_id="COMP-RACE",
            items=[{
                "item_id": "ITEM-RACE",
                "product_name": "Race Item",
                "quantity": "1",
                "item_type": "bulk",
            }],
        ),
    )
    winners = {
        "source_record": db.get(CustomerSourceRecord, ali.source_record_id),
        "conversation": db.get(CustomerConversation, ali.conversation_id),
        "message": db.get(CustomerMessage, ali.message_ids[0]),
        "order": db.get(CustomerOrder, okki.order_id),
        "order_item": db.get(CustomerOrderItem, okki.item_ids[0]),
    }

    for entity_type, winner in winners.items():
        mapper = inspect(type(winner))
        values = {
            column.key: getattr(winner, column.key)
            for column in mapper.columns
            if not column.primary_key
        }
        loser = type(winner)(**values)

        def insert_duplicate(loser=loser):
            db.add(loser)
            db.flush()
            return loser

        recovered, inserted = insert_or_load_expected_unique(
            db,
            entity_type=entity_type,
            insert=insert_duplicate,
            load_winner=lambda winner=winner: db.get(type(winner), winner.id),
        )

        assert inserted is False
        assert recovered.id == winner.id


def test_unknown_mysql_duplicate_constraint_is_not_treated_as_expected_race(db):
    from sqlalchemy.exc import IntegrityError

    def unknown_duplicate():
        raise IntegrityError(
            "insert",
            {},
            Exception(1062, "Duplicate entry 'x' for key 'uq_unrelated_table'"),
        )

    with pytest.raises(IntegrityError):
        insert_or_load_expected_unique(
            db,
            entity_type="conversation",
            insert=unknown_duplicate,
            load_winner=lambda: None,
        )


@pytest.mark.parametrize("entity_type", ["conversation", "message"])
def test_alibaba_invisible_unique_winner_retries_and_rolls_back_everything(
    db, monkeypatch, entity_type,
):
    from app.customer import projection_alibaba

    original = projection_alibaba.insert_or_load_expected_unique

    def invisible_winner(*args, **kwargs):
        if kwargs["entity_type"] == entity_type:
            raise ProjectionRetryRequired()
        return original(*args, **kwargs)

    monkeypatch.setattr(
        projection_alibaba,
        "insert_or_load_expected_unique",
        invisible_winner,
    )

    with pytest.raises(ProjectionRetryRequired) as raised:
        project_alibaba_inquiry(
            db,
            source_account_key="shop-invisible",
            payload=_alibaba_payload(
                inquiry_id=f"INQ-{entity_type}",
                conversation_id=f"CONV-{entity_type}",
            ),
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert db.query(CustomerSourceRecord).count() == 0
    assert db.query(CustomerAccount).count() == 0
    assert db.query(CustomerConversation).count() == 0
    assert db.query(CustomerMessage).count() == 0


@pytest.mark.parametrize("entity_type", ["order", "order_item"])
def test_okki_invisible_unique_winner_retries_and_rolls_back_order_projection(
    db, monkeypatch, entity_type,
):
    from app.customer import projection_okki_order

    _project_okki_customer(db, account="tenant-invisible", company_id="COMP-I")
    db.commit()
    baseline_sources = db.query(CustomerSourceRecord).count()
    original = projection_okki_order.insert_or_load_expected_unique

    def invisible_winner(*args, **kwargs):
        if kwargs["entity_type"] == entity_type:
            raise ProjectionRetryRequired()
        return original(*args, **kwargs)

    monkeypatch.setattr(
        projection_okki_order,
        "insert_or_load_expected_unique",
        invisible_winner,
    )

    with pytest.raises(ProjectionRetryRequired) as raised:
        project_okki_order(
            db,
            source_account_key="tenant-invisible",
            payload=_okki_order_payload(
                order_id=f"ORDER-{entity_type}",
                company_id="COMP-I",
                items=[{
                    "item_id": "ITEM-I",
                    "product_name": "Invisible winner item",
                    "quantity": "1",
                    "item_type": "bulk",
                }],
            ),
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert db.query(CustomerSourceRecord).count() == baseline_sources
    assert db.query(CustomerOrder).count() == 0
    assert db.query(CustomerOrderItem).count() == 0


def test_alibaba_second_message_source_invisible_winner_rolls_back_prior_raw(
    db, monkeypatch,
):
    from app.customer import projection_common

    original = projection_common.insert_or_load_expected_unique
    source_calls = 0

    def invisible_second_message_source(*args, **kwargs):
        nonlocal source_calls
        if kwargs["entity_type"] == "source_record":
            source_calls += 1
            if source_calls == 3:
                raise ProjectionRetryRequired()
        return original(*args, **kwargs)

    monkeypatch.setattr(
        projection_common,
        "insert_or_load_expected_unique",
        invisible_second_message_source,
    )

    with pytest.raises(ProjectionRetryRequired) as raised:
        project_alibaba_inquiry(
            db,
            source_account_key="shop-source-invisible",
            payload=_alibaba_payload(
                inquiry_id="INQ-SOURCE-INVISIBLE",
                conversation_id="CONV-SOURCE-INVISIBLE",
            ),
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert db.query(CustomerSourceRecord).count() == 0
    assert db.query(CustomerAccount).count() == 0


def test_sync_lease_expiring_between_records_preserves_completed_prefix(db, monkeypatch):
    from app.customer import projection_service

    started = beijing_now()
    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-a",
        lease_seconds=60,
        now=started,
    )
    valid_time = started + timedelta(seconds=1)
    expired_time = started + timedelta(seconds=61)
    calls = iter([
        valid_time,
        valid_time,
        valid_time,
        valid_time,
        expired_time,
    ])
    monkeypatch.setattr(projection_service, "beijing_now", lambda: next(calls))

    with pytest.raises(ProjectionError) as raised:
        project_sync_batch(
            db,
            lease=lease,
            source_account_key="tenant-a",
            expected_cursor_value=None,
            records=[
                {
                    "previous_cursor_value": None,
                    "cursor_value": "1",
                    "payload": _okki_customer_payload("COMP-1"),
                },
                {
                    "previous_cursor_value": "1",
                    "cursor_value": "2",
                    "payload": _okki_customer_payload("COMP-2"),
                },
            ],
        )

    assert raised.value.error_code == "SYNC_CURSOR_FENCE_REJECTED"
    assert db.get(CustomerSyncCursor, lease.cursor_id).cursor_value == "1"
    assert db.query(CustomerSourceRecord).filter_by(
        external_record_id="COMP-1",
        processing_status="processed",
    ).count() == 1
    assert db.query(CustomerSourceRecord).filter_by(
        external_record_id="COMP-2",
    ).count() == 0


def test_valid_order_becoming_invalid_corrects_fact_and_order_confirmed_opportunity(db):
    customer = _project_okki_customer(db)
    opportunity = upsert_opportunity(
        db,
        customer_id=customer.customer_id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_key="inquiry:ORDER-CORRECTION",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title="Order correction",
    )
    valid_payload = _okki_order_payload(order_id="ORDER-CORRECTION")
    valid_payload["opportunity_ref"] = {
        "source_system": opportunity.source_system,
        "source_account_key": opportunity.source_account_key,
        "source_key": opportunity.source_key,
    }
    valid = project_okki_order(
        db, source_account_key="tenant-a", payload=valid_payload,
    )
    opportunity.status = "won"
    opportunity.close_reason_code = "order_confirmed"
    opportunity.close_reason_text = None
    append_opportunity_event(
        db,
        opportunity=opportunity,
        event_type="closed",
        actor_user_id=None,
        event_payload={
            "linked_order_id": valid.order_id,
            "close_reason_code": "order_confirmed",
            "reason": "order confirmed",
        },
        from_status="quoted",
        to_status="won",
        occurred_at=beijing_now(),
    )
    db.flush()

    invalid_payload = {
        **valid_payload,
        "status": "13972831654",
        "status_name": "未结清",
    }
    invalid = project_okki_order(
        db, source_account_key="tenant-a", payload=invalid_payload,
    )

    assert invalid.status == "processed"
    assert db.get(CustomerOrder, valid.order_id).is_valid_business_order is False
    corrected_opportunity = db.get(CustomerOpportunity, opportunity.id)
    assert corrected_opportunity.status == "quoted"
    assert corrected_opportunity.linked_order_id is None
    assert corrected_opportunity.close_reason_code is None
    correction = db.query(CustomerOpportunityEvent).filter_by(
        opportunity_id=opportunity.id,
        event_type="order_validity_revoked",
    ).one()
    assert correction.from_status == "won"
    assert correction.to_status == "quoted"
    facts = db.query(CustomerFact).filter_by(
        customer_id=customer.customer_id,
        fact_key="commercial.has_valid_order",
    ).order_by(CustomerFact.id).all()
    assert [row.value_json for row in facts] == [{"value": True}, {"value": False}]
    assert facts[0].verification_status == "superseded"
    assert facts[1].supersedes_fact_id == facts[0].id
    account = db.get(CustomerAccount, customer.customer_id)
    assert account.relationship_stage == "active_customer"
    event = db.query(CustomerEvent).filter_by(
        customer_id=customer.customer_id,
        event_type="order.validity_revoked",
    ).one()
    assert event.event_payload["customer_stage_review_required"] is True
    assert event.event_payload["affected_opportunity_ids"] == [opportunity.id]


def test_invalidated_order_keeps_customer_valid_fact_true_when_other_valid_order_exists(db):
    customer = _project_okki_customer(db)
    first = project_okki_order(
        db,
        source_account_key="tenant-a",
        payload=_okki_order_payload(order_id="ORDER-A"),
    )
    project_okki_order(
        db,
        source_account_key="tenant-a",
        payload=_okki_order_payload(order_id="ORDER-B"),
    )
    invalid = _okki_order_payload(order_id="ORDER-A")
    invalid.update({"status": "13972831654", "status_name": "未结清"})
    project_okki_order(db, source_account_key="tenant-a", payload=invalid)

    current_fact = db.query(CustomerFact).filter(
        CustomerFact.customer_id == customer.customer_id,
        CustomerFact.fact_key == "commercial.has_valid_order",
        CustomerFact.verification_status == "verified",
        CustomerFact.effective_to.is_(None),
    ).one()
    assert current_fact.value_json == {"value": True}
    assert db.get(CustomerOrder, first.order_id).is_valid_business_order is False
    event = db.query(CustomerEvent).filter_by(
        event_type="order.validity_revoked",
    ).one()
    assert event.event_payload["customer_stage_review_required"] is False


def test_quarantine_flush_deadlock_rolls_back_and_requires_new_transaction(db, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.customer.fact_service import append_source_record
    from app.customer.projection_common import quarantine

    source = append_source_record(
        db,
        customer_id=None,
        source_system="okki",
        source_account_key="tenant-a",
        source_entity_type="customer",
        external_record_id="DEADLOCK-QUARANTINE",
        payload_schema_version="okki_customer_v1",
        payload_json={"company_id": "DEADLOCK-QUARANTINE"},
    )
    source._projection_entry_status = "pending"

    original_flush = db.flush
    def deadlock_on_dirty(*args, **kwargs):
        if db.dirty:
            raise OperationalError("update", {}, Exception(1213, "deadlock"))
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", deadlock_on_dirty)
    with pytest.raises(ProjectionRetryRequired) as raised:
        quarantine(db, [source], "COMPANY_ID_INVALID")

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    monkeypatch.setattr(db, "flush", original_flush)
    assert db.get(CustomerSourceRecord, source.id) is None


def test_final_cursor_flush_deadlock_rolls_back_and_requires_new_transaction(db, monkeypatch):
    from sqlalchemy.exc import OperationalError

    lease = claim_sync_scope(
        db,
        source_system="okki",
        resource_type="customers",
        scope_key="tenant-a",
        claimed_by="worker-a",
    )

    original_flush = db.flush
    def deadlock_on_dirty(*args, **kwargs):
        if db.dirty:
            raise OperationalError("update", {}, Exception(1213, "deadlock"))
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", deadlock_on_dirty)
    with pytest.raises(ProjectionRetryRequired) as raised:
        project_sync_batch(
            db,
            lease=lease,
            source_account_key="tenant-a",
            expected_cursor_value=None,
            records=[],
        )

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    monkeypatch.setattr(db, "flush", original_flush)
    assert db.get(CustomerSyncCursor, lease.cursor_id) is None
