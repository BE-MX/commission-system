import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "209_invoice_item_groups.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("invoice_item_groups_209", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_initializes_history_by_invoice_and_line_date_without_touching_business_fields():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    invoices = sa.Table("ark_invoices", metadata, sa.Column("id", sa.Integer, primary_key=True))
    items = sa.Table(
        "ark_invoice_items", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("invoice_id", sa.Integer, nullable=False),
        sa.Column("product_kind", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price_per_piece", sa.Numeric(12, 4)),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(invoices.insert(), [{"id": 1}, {"id": 2}])
        connection.execute(items.insert(), [
            {"id": 1, "invoice_id": 1, "product_kind": "hair", "quantity": 5, "price_per_piece": 20, "created_at": datetime(2026, 10, 1, 9)},
            {"id": 2, "invoice_id": 1, "product_kind": "hair", "quantity": 6, "price_per_piece": 21, "created_at": datetime(2026, 10, 1, 18)},
            {"id": 3, "invoice_id": 1, "product_kind": "hair", "quantity": 7, "price_per_piece": 22, "created_at": datetime(2026, 10, 2, 9)},
            {"id": 4, "invoice_id": 2, "product_kind": "hair", "quantity": 8, "price_per_piece": 23, "created_at": datetime(2026, 10, 1, 9)},
            {"id": 5, "invoice_id": 1, "product_kind": "accessory", "quantity": 9, "price_per_piece": 24, "created_at": datetime(2026, 10, 1, 9)},
        ])
        context = MigrationContext.configure(connection, opts={"render_as_batch": True})
        with Operations.context(context):
            _load_migration().upgrade()

        groups = sa.Table("ark_invoice_item_groups", sa.MetaData(), autoload_with=connection)
        migrated_items = sa.Table("ark_invoice_items", sa.MetaData(), autoload_with=connection)
        group_rows = connection.execute(sa.select(groups).order_by(groups.c.invoice_id, groups.c.sort_order)).all()
        assert [(row.invoice_id, row.name, row.sort_order) for row in group_rows] == [
            (1, "2026-10-01", 1), (1, "2026-10-02", 2), (2, "2026-10-01", 1),
        ]
        assert len({row.key for row in group_rows}) == 3
        group_ids = {(row.invoice_id, row.name): row.id for row in group_rows}
        item_rows = connection.execute(sa.select(migrated_items).order_by(migrated_items.c.id)).all()
        assert [row.group_id for row in item_rows] == [
            group_ids[(1, "2026-10-01")], group_ids[(1, "2026-10-01")], group_ids[(1, "2026-10-02")],
            group_ids[(2, "2026-10-01")], None,
        ]
        assert [(row.quantity, str(row.price_per_piece)) for row in item_rows] == [
            (5, "20.0000"), (6, "21.0000"), (7, "22.0000"), (8, "23.0000"), (9, "24.0000"),
        ]
