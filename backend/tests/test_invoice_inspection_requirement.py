"""Inspection defaults, explicit choices, persistence and independent print flags."""
import io
from datetime import date

import pytest
from docx import Document
from pydantic import ValidationError

from app.invoice import service
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate
from app.shipping_inspection.print_customer_service import with_customer_order_info
from app.shipping_inspection.word_service import build_outbound_word
from tests.test_shipping_customer_grade import seed


def payload(**changes):
    return dict(customer_id="C1", customer_name="Customer", invoice_date=date(2026, 10, 27),
                okki_new_deal=0, okki_free_shipping=1, okki_first_return=0, items=[]) | changes


@pytest.mark.parametrize("new_deal,choice", [(0, "single"), (1, "detail")])
def test_default_follows_resolved_new_deal(db, new_deal, choice):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(okki_new_deal=new_deal)))
    assert service.serialize_detail(invoice)["inspection_requirement"] == choice


@pytest.mark.parametrize("has_orders,choice", [(False, "detail"), (True, "single")])
def test_default_uses_server_resolved_new_deal(db, monkeypatch, has_orders, choice):
    monkeypatch.setattr(service, "customer_has_xiaoman_orders", lambda *args, **kwargs: has_orders)
    invoice = service.create_invoice(db, InvoiceCreate(**payload(okki_new_deal=None)))
    assert invoice.inspection_requirement == choice


@pytest.mark.parametrize("new_deal,choice", [(1, "single"), (0, "detail")])
def test_explicit_choice_survives_save_reload_and_omitted_update(db, new_deal, choice):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        okki_new_deal=new_deal, inspection_requirement=choice)))
    db.commit()
    db.refresh(invoice)
    assert invoice.inspection_requirement == choice
    service.update_invoice(db, invoice, InvoiceUpdate(**payload(okki_new_deal=1-new_deal)))
    assert invoice.inspection_requirement == choice
    other = "single" if choice == "detail" else "detail"
    service.update_invoice(db, invoice, InvoiceUpdate(**payload(inspection_requirement=other)))
    assert service.serialize_detail(invoice)["inspection_requirement"] == other


@pytest.mark.parametrize("choice", ["", "other", None])
def test_invalid_or_empty_selection_is_rejected(choice):
    with pytest.raises(ValidationError):
        InvoiceCreate(**payload(inspection_requirement=choice))


@pytest.mark.parametrize("new_deal,choice", [(0, "single"), (1, "single"), (0, "detail"), (1, "detail")])
def test_print_flags_follow_actual_linked_order_independently(db, new_deal, choice):
    record = seed(db)
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        okki_new_deal=new_deal, inspection_requirement=choice)))
    invoice.xiaoman_order_id = "O1"
    # Print requirements are local instructions, including saved edits pending OKKI sync.
    invoice.sync_status = "not_synced"
    db.flush()
    result = with_customer_order_info(db, record)
    assert result["is_new_deal"] == bool(new_deal)
    assert result["inspection_requirement"] == choice
    assert "inspection_requirement" not in record
    document = Document(io.BytesIO(build_outbound_word(result, [], "test")))
    runs = [r for p in document.paragraphs for r in p.runs]
    text = "".join(r.text for r in runs)
    assert ("新签" in text) == bool(new_deal)
    assert ("拍摄明细照片" in text) == (choice == "detail")
    for run in runs:
        if "新签" in run.text or "拍摄明细照片" in run.text:
            assert run.bold and run.font.size.pt >= 16


def test_unrelated_customer_does_not_supply_print_flags(db):
    record = seed(db)
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        customer_id="OTHER", okki_new_deal=1, inspection_requirement="detail")))
    invoice.xiaoman_order_id = "O1"
    db.flush()
    result = with_customer_order_info(db, record)
    assert not result["is_new_deal"]
    assert result["inspection_requirement"] == "single"


def test_combined_outbound_keeps_marks_from_separate_linked_orders(db):
    from sqlalchemy import text
    record = seed(db)
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id='O2' WHERE id='IT002'"))
    first = service.create_invoice(db, InvoiceCreate(**payload(
        invoice_no="FIRST", okki_new_deal=1, inspection_requirement="single")))
    second = service.create_invoice(db, InvoiceCreate(**payload(
        invoice_no="SECOND", okki_new_deal=0, inspection_requirement="detail")))
    first.xiaoman_order_id, second.xiaoman_order_id = "O1", "O2"
    db.flush()
    result = with_customer_order_info(db, record)
    assert result["is_new_deal"] is True
    assert result["inspection_requirement"] == "detail"


def test_inspection_change_invalidates_edit_version(db):
    from app.invoice.linked_sync_service import edit_version
    invoice = service.create_invoice(db, InvoiceCreate(**payload()))
    before = edit_version(invoice)
    invoice.inspection_requirement = "detail"
    assert edit_version(invoice) != before


@pytest.mark.parametrize("new_deal", [0, 1])
def test_pre_migration_saved_task_only_accepts_unchanged_migrated_default(db, new_deal):
    from app.invoice.linked_sync_service import edit_version, snapshot, _matches_saved_snapshot
    invoice = service.create_invoice(db, InvoiceCreate(**payload(okki_new_deal=new_deal)))
    saved = snapshot(invoice)
    old_saved = {k: v for k, v in saved.items() if k != "inspection_requirement"}
    old_saved["edit_version"] = edit_version(invoice, include_inspection=False)
    assert _matches_saved_snapshot(invoice, old_saved)
    assert _matches_saved_snapshot(invoice, saved)
    invoice.inspection_requirement = "single" if new_deal else "detail"
    assert not _matches_saved_snapshot(invoice, old_saved)
    assert not _matches_saved_snapshot(invoice, saved)
    invoice.inspection_requirement = "detail" if new_deal else "single"
    invoice.remark = "changed order"
    assert not _matches_saved_snapshot(invoice, old_saved)


def test_legacy_null_new_deal_print_uses_successful_payload_evidence(db):
    import json
    from app.invoice.models import InvoiceSyncLog
    from app.invoice.xiaoman_service import FIELD_NEW_DEAL
    record = seed(db)
    invoice = service.create_invoice(db, InvoiceCreate(**payload()))
    invoice.okki_new_deal, invoice.xiaoman_order_id = None, "O1"
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action="create", success=1,
                          request_digest=json.dumps({FIELD_NEW_DEAL: "是"})))
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action="update", success=0,
                          request_digest=json.dumps({FIELD_NEW_DEAL: "否"})))
    db.flush()
    assert with_customer_order_info(db, record)["is_new_deal"] is True
    invoice.okki_new_deal = 0
    db.flush()
    assert with_customer_order_info(db, record)["is_new_deal"] is False


def test_pre_migration_command_replays_only_identical_original_request(db):
    import hashlib
    from app.invoice import linked_sync_service as linked
    from app.invoice.models import InvoiceLinkedSync
    from app.invoice.router import LinkedSavePayload
    invoice = service.create_invoice(db, InvoiceCreate(**payload()))
    body = LinkedSavePayload(invoice=InvoiceUpdate(**payload()), request_key="legacy-request-key",
                             expected_version="a" * 64)
    old_json = body.model_dump_json(exclude={"invoice": {"inspection_requirement"}})
    old_saved = {k: v for k, v in linked.snapshot(invoice).items() if k != "inspection_requirement"}
    row = InvoiceLinkedSync(id="old-task", invoice_id=invoice.id, created_by=7,
        request_key=body.request_key, request_hash=hashlib.sha256(old_json.encode()).hexdigest(),
        status="manual", before=old_saved, after=old_saved, steps={})
    db.add(row)
    db.flush()
    assert linked.replay(db, invoice, body, 7)[0] is row
    with pytest.raises(ValueError):
        linked.replay(db, invoice, body, 8)
    changed = body.model_copy(update={"invoice": InvoiceUpdate(**payload(remark="different"))})
    with pytest.raises(ValueError):
        linked.replay(db, invoice, changed, 7)
    explicit = body.model_copy(update={"invoice": InvoiceUpdate(**payload(inspection_requirement="single"))})
    with pytest.raises(ValueError):
        linked.replay(db, invoice, explicit, 7)
    # A new task must never accept the legacy digest.
    row.after = linked.snapshot(invoice)
    with pytest.raises(ValueError):
        linked.replay(db, invoice, body, 7)


def test_migration_preserves_orders_and_backfills_only_explicit_new_deals():
    import importlib.util
    from pathlib import Path
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    path = Path(__file__).resolve().parents[1] / "alembic/versions/208_invoice_inspection_photos.py"
    spec = importlib.util.spec_from_file_location("inspection_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY, okki_new_deal INTEGER, remark TEXT)"))
        conn.execute(text("INSERT INTO ark_invoices VALUES (1, 1, 'keep'), (2, 0, 'also keep'), (3, NULL, 'unknown')"))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert conn.execute(text("SELECT id, inspection_requirement, remark FROM ark_invoices ORDER BY id")).all() == [
            (1, "detail", "keep"), (2, "single", "also keep"), (3, "single", "unknown")]
        migration.downgrade()
        assert conn.execute(text("SELECT inspection_requirement FROM ark_invoices WHERE id=1")).scalar() == "detail"
    config = Config()
    config.set_main_option("script_location", str(path.parents[1]))
    assert ScriptDirectory.from_config(config).get_heads() == ["209_invoice_item_groups"]
