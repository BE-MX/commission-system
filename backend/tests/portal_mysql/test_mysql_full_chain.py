"""Opt-in empty-database historical replay; never skips/stamps historical revisions."""
import json
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import inspect, text

from app.core import config as application_config


def test_empty_database_full_alembic_chain(request, monkeypatch):
    if not request.config.getoption('portal_full_chain'):
        pytest.skip('Explicit --portal-full-chain and standalone test selection required')
    engine = request.getfixturevalue('mysql_engine')
    assert inspect(engine).get_table_names() == [], 'Select only this file with a fresh database'
    backend = Path(__file__).resolve().parents[2]
    # Auth and DingTalk predate Alembic and have versioned SQL initializers.
    # Replay their actual table DDL only; do not invent an ORM baseline or seed accounts.
    for filename, expected in [('auth_init.sql', 7), ('dingtalk_init.sql', 2)]:
        source = (backend.parent / 'database' / filename).read_text(encoding='utf-8')
        statements = re.findall(r'^CREATE TABLE IF NOT EXISTS `[^`]+` \([\s\S]*?^\) ENGINE=[^;]+;', source, re.MULTILINE)
        assert len(statements) == expected, 'Review changed historical initializer'
        with engine.begin() as connection:
            for statement in statements: connection.exec_driver_sql(statement)
    config = Config(); config.set_main_option('script_location', str(backend / 'alembic'))
    assert ScriptDirectory.from_config(config).get_heads() == ['176_portal_pi_header']
    settings = application_config.get_settings().model_copy(update={
        'COMMISSION_DB_HOST':engine.url.host, 'COMMISSION_DB_PORT':engine.url.port,
        'COMMISSION_DB_USER':engine.url.username, 'COMMISSION_DB_PASSWORD':engine.url.password,
        'COMMISSION_DB_NAME':engine.url.database, 'BUSINESS_DB_NAME':engine.url.database})
    monkeypatch.setattr(application_config, 'get_settings', lambda: settings)
    output = Path(request.config.getoption('portal_mysql_workspace')) / 'chain-result.json'
    # This owned fresh server has no app/worker writers; satisfy the real 123 maintenance prerequisite.
    monkeypatch.setenv('ARK_TIME_MIGRATION_MAINTENANCE', '1')
    succeeded = False
    try:
        command.upgrade(config, 'head')
        with engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() == ['176_portal_pi_header']
            assert connection.scalar(text("SELECT version FROM ark_order_portal_auth_barriers WHERE code='authority'")) == 1
        succeeded = True
    finally:
        tables = inspect(engine).get_table_names()
        with engine.connect() as connection:
            revisions = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() if 'alembic_version' in tables else []
        output.write_text(json.dumps({'complete':succeeded, 'revisions':revisions, 'tables':tables,
            'scope':'Fresh owned database through unmodified Alembic env; no stamp, downgrade or guard bypass'}, indent=2), encoding='utf-8')
