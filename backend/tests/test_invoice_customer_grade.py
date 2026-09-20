from datetime import date

import pytest
from pydantic import ValidationError

from app.invoice import service
from app.invoice.customer_profile_service import get_customer_grade, save_customer_grade
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate


def payload(**extra):
    return dict(customer_id="C1", customer_name="Customer", invoice_date=date(2026, 9, 18),
                okki_new_deal=1, okki_free_shipping=1, okki_first_return=0, items=[], **extra)


@pytest.mark.parametrize("grade", ["S", "A", "B", "C", "D", "E", None])
def test_save_and_reuse_grade(db, grade):
    first = service.create_invoice(db, InvoiceCreate(**payload(customer_grade=grade)))
    db.commit()
    assert service.serialize_detail(first)["customer_grade"] == grade
    assert service.get_customer_contact_defaults(db, "C1")["customer_grade"] == grade
    following = service.create_invoice(db, InvoiceCreate(**payload()))
    assert following.customer_grade == grade


def test_edit_updates_customer_but_old_unchanged_snapshot_does_not(db):
    old = service.create_invoice(db, InvoiceCreate(**payload(customer_grade="A")))
    current = service.create_invoice(db, InvoiceCreate(**payload(customer_grade="S")))
    service.update_invoice(db, old, InvoiceUpdate(**payload(customer_grade="A")))
    assert get_customer_grade(db, "C1") == "S"
    service.update_invoice(db, current, InvoiceUpdate(**payload(customer_grade="B")))
    assert get_customer_grade(db, "C1") == "B"
    service.update_invoice(db, current, InvoiceUpdate(**payload(customer_grade=None)))
    assert get_customer_grade(db, "C1") is None
    assert old.customer_grade == "A"


def test_omitted_field_and_customer_change(db):
    save_customer_grade(db, "C1", "A", None)
    save_customer_grade(db, "C2", "D", None)
    invoice = service.create_invoice(db, InvoiceCreate(**payload()))
    service.update_invoice(db, invoice, InvoiceUpdate(**payload(remark="edited")))
    assert invoice.customer_grade == "A"
    data = payload(); data["customer_id"] = "C2"
    service.update_invoice(db, invoice, InvoiceUpdate(**data))
    assert invoice.customer_grade == "D"
    assert get_customer_grade(db, "C1") == "A"


def test_customer_profile_upsert_rolls_back_with_transaction(db):
    save_customer_grade(db, "C1", "A", None)
    db.commit()
    service.create_invoice(db, InvoiceCreate(**payload(customer_grade="S")))
    assert get_customer_grade(db, "C1") == "S"
    db.rollback()
    assert get_customer_grade(db, "C1") == "A"


@pytest.mark.parametrize("grade", ["F", "AA", "a", "", "S\n"])
@pytest.mark.parametrize("schema", [InvoiceCreate, InvoiceUpdate])
def test_reject_invalid_grades(grade, schema):
    with pytest.raises(ValidationError):
        schema(**payload(customer_grade=grade))


def test_migration_adds_nullable_grade_without_changing_existing_data():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text, inspect

    path = Path(__file__).resolve().parents[1] / "alembic/versions/157_invoice_customer_grade.py"
    spec = importlib.util.spec_from_file_location("grade_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY, customer_name TEXT)"))
        connection.execute(text("INSERT INTO ark_invoices VALUES (1, 'Existing customer')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text("SELECT customer_name, customer_grade FROM ark_invoices")).one() == ("Existing customer", None)
        assert "ark_invoice_customer_profiles" in inspect(connection).get_table_names()
        migration.downgrade()
        assert connection.execute(text("SELECT customer_name FROM ark_invoices")).scalar() == "Existing customer"
    config = Config()
    config.set_main_option("script_location", str(path.parents[1]))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert migration.revision in {revision.revision for revision in scripts.walk_revisions()}


def test_edit_to_e_updates_snapshot_customer_defaults_and_next_invoice(db):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(customer_grade="A")))
    service.update_invoice(db, invoice, InvoiceUpdate(**payload(customer_grade="E")))
    db.commit()
    db.expire_all()
    assert service.serialize_detail(invoice)["customer_grade"] == "E"
    assert service.get_customer_contact_defaults(db, "C1")["customer_grade"] == "E"
    following = service.create_invoice(db, InvoiceCreate(**payload()))
    assert following.customer_grade == "E"
