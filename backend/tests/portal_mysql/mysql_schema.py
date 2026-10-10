"""Execute portal migration DDL on real MySQL, against minimal typed upstream anchors.

This is deliberately NOT a replay of the complete historical Ark migration chain.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.dialects.mysql import INTEGER

from app.core.database import Base
from app.auth.models import ArkUser
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.invoice.models import Invoice
from app.portal import models


@pytest.fixture(scope='session')
def migrated(mysql_engine):
    engine = mysql_engine
    baseline = MetaData()
    for model in (ArkUser, CustomerAccount, CustomerAssignment, CustomerExternalIdentity, Invoice):
        # The historical schema is unsigned even though ArkUser's ORM type is generic.
        # 054_backfill_comments.py explicitly preserves this type at revision 171.
        legacy = (Path(__file__).resolve().parents[2] / 'alembic/versions/054_backfill_comments.py').read_text(encoding='utf-8')
        assert 'ALTER TABLE `ark_users` MODIFY COLUMN `id` int unsigned' in legacy
        id_type = INTEGER(unsigned=True) if model is ArkUser else model.__table__.c.id.type
        columns = [Column('id', id_type, primary_key=True)]
        if model is Invoice: columns.append(Column('invoice_no', model.__table__.c.invoice_no.type))
        Table(model.__tablename__, baseline, *columns)
    baseline.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO ark_invoices (id, invoice_no) VALUES (7, 'PI-LEGACY')"))
    backend = Path(__file__).resolve().parents[2]
    config = Config(); config.set_main_option('script_location', str(backend / 'alembic'))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert '177_portal_pi_header' in {revision.revision for revision in scripts.walk_revisions()}
    for filename in ('176_customer_order_portal.py', '177_portal_pi_header.py'):
        spec = spec_from_file_location('migration_' + filename[:-3], backend / 'alembic/versions' / filename)
        module = module_from_spec(spec); spec.loader.exec_module(module)
        with engine.begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version FROM ark_order_portal_auth_barriers WHERE code='authority'")) == 1
    return engine

