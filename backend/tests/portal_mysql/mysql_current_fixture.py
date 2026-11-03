"""Current synthetic schema anchors; service evidence, not production DDL-chain proof."""
import pytest
from sqlalchemy import Column, MetaData, Table, UniqueConstraint, inspect
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.fixture(scope='session', autouse=True)
def current_queue_schema(service_schema):
    from app.core.database import Base
    from app.commerce_transition.models import PlatformPolicy
    from app import routers as _registered_models  # noqa: F401
    with service_schema.engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        for table in Base.metadata.tables.values():
            if not table.name.startswith('ark_order_portal_') or not inspect(connection).has_table(table.name):
                continue
            existing = {row['name'] for row in inspect(connection).get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    operations.add_column(table.name, Column(column.name, column.type, nullable=True))
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        if table.schema is None:
            Table(table.name, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
                nullable=c.nullable, default=c.default, server_default=c.server_default) for c in table.columns),
                *(UniqueConstraint(*(c.name for c in constraint.columns), name=constraint.name)
                  for constraint in table.constraints if isinstance(constraint, UniqueConstraint)))
    metadata.create_all(service_schema.engine)
    with Session(service_schema.engine) as db:
        if db.get(PlatformPolicy, 1) is None:
            db.add(PlatformPolicy(id=1, phase='legacy_only', version=1))
        db.commit()
