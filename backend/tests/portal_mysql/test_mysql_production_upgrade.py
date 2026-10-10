"""Opt-in protected revision-180 snapshot restore, original Alembic, recovery and replay.

Only the fixture-owned server is contacted. No stamp, baseline invention or live DDL.
Raw backup rows, credentials and restore stderr are never emitted in test diagnostics.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.core import config as application_config
from conftest import ALLOWED
from storage_snapshot import stored_objects_snapshot


def json_value(value):
    if isinstance(value, bytes): return {'bytes': value.hex()}
    if isinstance(value, (Decimal, date, datetime, time, timedelta)): return str(value)
    return value


def business_snapshot(engine):
    result = {}
    schema = inspect(engine)
    with engine.connect() as connection:
        for table in schema.get_table_names():
            if table == 'alembic_version': continue
            columns = [c['name'] for c in schema.get_columns(table)
                if not (table == 'ark_order_portal_accounts' and c['name'] == 'password_hash')]
            names = ','.join('`' + column + '`' for column in columns)
            checksums = []
            for row in connection.execute(text('SELECT ' + names + ' FROM `' + table + '`')):
                encoded = json.dumps([json_value(v) for v in row], ensure_ascii=True, separators=(',', ':')).encode()
                checksums.append(hashlib.sha256(encoded).digest())
            result[table] = {'count': len(checksums), 'digest': hashlib.sha256(b''.join(sorted(checksums))).hexdigest(),
                'columns': columns, 'fks': schema.get_foreign_keys(table), 'unique': schema.get_unique_constraints(table)}
    return result


def test_real_revision_180_restore_upgrade_and_recovery(request, mysql_engine, monkeypatch):
    filename = request.config.getoption('portal_production_backup')
    if not filename:
        import pytest
        pytest.skip('Explicit protected --portal-production-backup required')
    backup = Path(filename).resolve(strict=True)
    receipt = json.loads(backup.with_name('receipt.json').read_text())
    with backup.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == receipt['sha256'], 'Backup digest differs'
    assert receipt['revision'] == '180_settlement_funding_amendment'
    object_manifest = request.config.getoption('portal_production_objects')
    expected_objects = None
    if object_manifest:
        object_manifest = json.loads(Path(object_manifest).read_text(encoding='utf-8'))
        assert object_manifest['database_uuid'] == receipt['database_uuid']
        assert object_manifest['revision'] == receipt['revision']
        expected_objects = object_manifest['objects']
    assert inspect(mysql_engine).get_table_names() == [], 'Restore requires a fresh owned server'
    with mysql_engine.begin() as connection:
        connection.execute(text('SET GLOBAL event_scheduler=OFF'))
    directory = Path(request.config.getoption('portal_mysql_workspace'))
    mysql = Path(request.config.getoption('portal_mysqld')).with_name('mysql.exe').resolve(strict=True)
    options = directory / 'restore-client.cnf'
    options.write_text('[client]\nhost=127.0.0.1\nport=' + str(ALLOWED['port']) + '\nuser=root\npassword=' + ALLOWED['password'] + '\n', encoding='utf-8')
    def restore():
        with backup.open('rb') as data:
            process = subprocess.run([str(mysql), '--defaults-file=' + str(options), '--no-login-paths',
                '--protocol=TCP', '--host=127.0.0.1', '--port=' + str(ALLOWED['port']), '--user=root',
                '--default-character-set=utf8mb4', '--binary-mode', ALLOWED['database']],
                stdin=data, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900)
        assert process.returncode == 0, 'Protected snapshot restore failed; raw database diagnostics withheld'
    def assert_scheduler_off():
        with mysql_engine.connect() as connection:
            assert connection.scalar(text('SELECT @@GLOBAL.event_scheduler')) == 'OFF', 'Owned clone event scheduler must remain off'
    try:
        restore()
        assert_scheduler_off()
        with mysql_engine.connect() as connection:
            stored_objects = stored_objects_snapshot(connection)
        if expected_objects is not None:
            assert stored_objects == expected_objects, 'Restored stored definitions differ from read-only source hashes'
        before = business_snapshot(mysql_engine)
        backend = Path(__file__).resolve().parents[2]
        config = Config(); config.set_main_option('script_location', str(backend / 'alembic'))
        scripts = ScriptDirectory.from_config(config)
        assert scripts.get_heads() == ['181_portal_password_login']
        assert [r.revision for r in scripts.iterate_revisions('head', receipt['revision'])] == ['181_portal_password_login']
        settings = application_config.get_settings().model_copy(update={
            'COMMISSION_DB_HOST':mysql_engine.url.host, 'COMMISSION_DB_PORT':mysql_engine.url.port,
            'COMMISSION_DB_USER':mysql_engine.url.username, 'COMMISSION_DB_PASSWORD':mysql_engine.url.password,
            'COMMISSION_DB_NAME':mysql_engine.url.database, 'BUSINESS_DB_NAME':mysql_engine.url.database})
        monkeypatch.setattr(application_config, 'get_settings', lambda: settings)
        def current():
            with mysql_engine.connect() as connection:
                return connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
        assert current() == [receipt['revision']]
        command.upgrade(config, 'head')
        assert_scheduler_off()
        assert current() == scripts.get_heads()
        assert business_snapshot(mysql_engine) == before, 'Original business rows or constraints changed'
        with mysql_engine.connect() as connection:
            assert stored_objects_snapshot(connection) == stored_objects
        column = next(c for c in inspect(mysql_engine).get_columns('ark_order_portal_accounts') if c['name'] == 'password_hash')
        assert column['nullable'] and column['type'].length == 255
        # Rehearse actual restore after DDL, rather than a destructive downgrade.
        restore()
        assert_scheduler_off()
        assert current() == [receipt['revision']] and business_snapshot(mysql_engine) == before
        with mysql_engine.connect() as connection:
            assert stored_objects_snapshot(connection) == stored_objects
        assert 'password_hash' not in {c['name'] for c in inspect(mysql_engine).get_columns('ark_order_portal_accounts')}
        command.upgrade(config, 'head')
        assert_scheduler_off()
        assert current() == scripts.get_heads() and business_snapshot(mysql_engine) == before
        with mysql_engine.connect() as connection:
            assert stored_objects_snapshot(connection) == stored_objects
        proof = {'database_uuid':receipt['database_uuid'], 'base':receipt['revision'], 'target':scripts.get_heads()[0],
            'backup_sha256':receipt['sha256'], 'migration_sha256':hashlib.sha256((backend/'alembic/versions/181_portal_password_login.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            'business_table_count':len(before), 'business_row_count':sum(t['count'] for t in before.values()),
            'business_rows_and_constraints_unchanged':True, 'restore_after_ddl_verified':True,
            'stored_object_count':len(stored_objects), 'stored_definitions_unchanged':True,
            'source_stored_definitions_verified':expected_objects is not None,
            'event_scheduler_remained_off':True,
            'scope':'Production revision-180 logical snapshot on owned loopback MySQL; no shared writes, stamp or bypass'}
        (directory / 'upgrade-proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    finally:
        options.unlink(missing_ok=True)
