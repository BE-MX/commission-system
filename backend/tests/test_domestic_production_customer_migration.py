import importlib.util
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/142_domestic_prod_customer.py"
    spec = importlib.util.spec_from_file_location("production_customer_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_customer_constraint_upgrade_preserves_rows_and_price_guard():
    module = migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    orders = sa.Table(module.TABLE, metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_kind", sa.String, nullable=False),
        sa.Column("customer_id", sa.Integer),
        sa.Column("order_category", sa.String),
        sa.Column("order_type", sa.String),
        sa.Column("order_channel", sa.String),
        sa.Column("required_ship_date", sa.String),
        sa.Column("total_amount", sa.Numeric, nullable=False),
        sa.Column("charged_amount", sa.Numeric, nullable=False),
        sa.Column("remark", sa.String),
        sa.CheckConstraint(module.OLD_KIND_FIELDS, name=module.CONSTRAINT),
    )
    with engine.begin() as conn:
        metadata.create_all(conn)
        conn.execute(orders.insert(), [
            dict(id=1, order_kind="business", customer_id=7, order_category="normal", total_amount=500, charged_amount=500, remark="keep business"),
            dict(id=2, order_kind="production", customer_id=None, order_category=None, total_amount=0, charged_amount=0, remark="keep production"),
        ])
        before = conn.execute(sa.select(orders).order_by(orders.c.id)).all()
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        assert conn.execute(sa.select(orders).order_by(orders.c.id)).all() == before
        conn.execute(orders.update().where(orders.c.id == 2).values(customer_id=7))
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(orders.update().where(orders.c.id == 2).values(total_amount=1))
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(orders.update().where(orders.c.id == 1).values(customer_id=None))
        with pytest.raises(RuntimeError, match="preserve"):
            module.downgrade()
        assert conn.execute(sa.select(orders.c.customer_id).where(orders.c.id == 2)).scalar_one() == 7
        conn.execute(orders.update().where(orders.c.id == 2).values(customer_id=None))
        module.downgrade()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(orders.update().where(orders.c.id == 2).values(customer_id=7))
    engine.dispose()


def test_mysql_replaces_constraint_in_one_statement():
    module = migration()
    statements = []
    module.op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")),
        execute=lambda sql: statements.append(str(sql)),
    )
    module.upgrade()
    assert len(statements) == 1
    assert "DROP CHECK ck_dom_order_kind_fields, ADD CONSTRAINT" in statements[0]
    assert "charged_amount = 0" in statements[0]
    assert "production' AND customer_id IS NULL" not in statements[0]
