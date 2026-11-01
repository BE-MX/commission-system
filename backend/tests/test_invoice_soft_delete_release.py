"""Deleting an unsynced draft archives it but releases its number and screenshot.

The archived row keeps its authority/audit; its unique invoice number is
rewritten to a tagged value and the screenshot provenance is cleared, with
the original values recorded on the immutable authority event.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.commerce_transition.models import AuthorityEvent
from app.invoice import service
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate
from tests.test_invoice_pricing import _custom_item, _seed_okki
from tests.test_invoice_screenshot_import import _resolve, _sample_extraction, _seed_example


def _draft(db, invoice_no, **extra):
    body = InvoiceCreate(customer_id="CUST001", customer_name="客户A", order_type="production",
                         invoice_date=date(2026, 7, 7), invoice_no=invoice_no,
                         items=[_custom_item(price_per_piece=Decimal("10"))], **extra)
    invoice = service.create_invoice(db, body, user_id=1)
    db.flush()
    return invoice


def _deleted_event(db, invoice_id):
    return db.query(AuthorityEvent).filter_by(invoice_id=invoice_id, action="draft_deleted").one()


def test_deleted_draft_releases_its_invoice_number_with_audit(db):
    _seed_okki(db)
    first = _draft(db, "SC-1101")
    service.delete_invoice(db, first, actor_id=1)
    db.flush()
    assert first.status == "deleted"
    assert first.invoice_no == f"SC-1101~DEL~{first.id}"
    assert not service.invoice_no_exists(db, "SC-1101")
    payload = _deleted_event(db, first.id).payload
    assert payload["invoice_no"] == "SC-1101" and payload["released_invoice_no"] == first.invoice_no
    assert payload["actor_id"] == 1

    second = _draft(db, "SC-1101")  # Reusing the released number succeeds.
    assert second.invoice_no == "SC-1101" and second.status != "deleted"


def test_released_number_fits_the_column_for_a_maximum_length_number(db):
    _seed_okki(db)
    long_no = "N" * 64
    first = _draft(db, long_no)
    service.delete_invoice(db, first, actor_id=1)
    db.flush()
    assert len(first.invoice_no) <= Invoice.__table__.c.invoice_no.type.length
    assert first.invoice_no.endswith(f"~DEL~{first.id}")
    assert _deleted_event(db, first.id).payload["invoice_no"] == long_no
    assert _draft(db, long_no).invoice_no == long_no


def test_previous_invoice_number_hint_skips_deleted_drafts(db):
    _seed_okki(db)
    kept = _draft(db, "SC-1102")
    dropped = _draft(db, "SC-1103")
    service.delete_invoice(db, dropped, actor_id=1)
    db.flush()
    assert service.previous_invoice_no(db, 1, "production") == kept.invoice_no


def test_synced_invoice_delete_keeps_the_original_rule(db):
    _seed_okki(db)
    invoice = _draft(db, "SC-1104")
    invoice.sync_status = "synced"
    with pytest.raises(ValueError, match="已同步"):
        service.delete_invoice(db, invoice, actor_id=1)
    assert invoice.invoice_no == "SC-1104" and invoice.status != "deleted"
    assert service.invoice_no_exists(db, "SC-1104")


def test_deleted_screenshot_draft_can_be_imported_again_and_audit_keeps_source(db):
    _seed_example(db)
    preview = _resolve(db, _sample_extraction(order_name="Released Screenshot Order"))
    first = service.create_invoice(db, InvoiceCreate.model_validate({
        **preview["invoice_patch"], "invoice_no": "KATY-KC-1101"}), user_id=27, allow_screenshot_source=True)
    db.commit()
    source_id, source_hash = first.source_order_id, first.source_image_sha256
    assert source_id and source_hash
    service.delete_invoice(db, first, actor_id=27)
    db.commit()
    assert first.source_order_id is None and first.source_image_sha256 is None
    assert first.source_type == "okki_screenshot"
    payload = _deleted_event(db, first.id).payload
    assert payload["source_order_id"] == source_id and payload["source_image_sha256"] == source_hash

    again = _resolve(db, _sample_extraction(order_name="Released Screenshot Order"))
    second = service.create_invoice(db, InvoiceCreate.model_validate({
        **again["invoice_patch"], "invoice_no": "KATY-KC-1101"}), user_id=27, allow_screenshot_source=True)
    db.commit()
    assert (second.source_order_id, second.source_image_sha256) == (source_id, source_hash)
    assert second.invoice_no == "KATY-KC-1101"


def test_default_number_suggestion_ignores_released_deleted_numbers(db):
    _seed_okki(db)
    suggested = service._next_invoice_no(db)
    first = _draft(db, suggested)
    service.delete_invoice(db, first, actor_id=1)
    db.flush()
    assert service._next_invoice_no(db) == suggested  # The released sequence is offered again.
    kept = _draft(db, suggested)
    following = service._next_invoice_no(db)
    assert following != kept.invoice_no and not service.invoice_no_exists(db, following)


def test_portal_delivery_default_ignores_deleted_drafts(db):
    from types import SimpleNamespace
    from app.portal import customer_settings_service
    _seed_okki(db)
    kept = _draft(db, "SC-1105", delivery_address="Kept street 1", contact_name="Kept")
    dropped = _draft(db, "SC-1106", delivery_address="Wrong street 9", contact_name="Wrong")
    service.delete_invoice(db, dropped, actor_id=1)
    db.flush()
    view = customer_settings_service.delivery_view(db, SimpleNamespace(okki_company_id=kept.customer_id))
    assert view["delivery"]["address_line1"] == "Kept street 1"
