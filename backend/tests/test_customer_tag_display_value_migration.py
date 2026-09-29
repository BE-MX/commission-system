"""Customer label migration backfills existing bindings without touching asset links."""

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from tests.test_customer_media_tags import _make_dim, _seed_batch_with_asset


def test_backfills_existing_customer_tag_names_idempotently(db):
    dim, values = _make_dim(db, "customer_colors", "Color names", values=["Ash"])
    _applicant, _designer, _outsider, batch, _asset = _seed_batch_with_asset(db)
    db.execute(text("UPDATE ark_customer_media_customer_tags SET display_value = NULL"))
    db.commit()

    path = Path(__file__).resolve().parents[1] / "alembic/versions/171_customer_tag_display_value.py"
    spec = importlib.util.spec_from_file_location("customer_tag_display_171", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db.connection()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    migration.upgrade()

    rows = connection.execute(text("""
        SELECT customer_id, dimension_id, tag_value_id, display_value
        FROM ark_customer_media_customer_tags
    """)).all()
    assert rows == [(batch.customer_id, dim.id, values[0].id, "Ash")]
