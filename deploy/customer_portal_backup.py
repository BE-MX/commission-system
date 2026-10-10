"""Protected commission_db logical snapshot for the additive portal credential release.

Runs only on the installed office host. Secrets stay in a short-lived ACL-restricted
option file; the dump is never a code/static artifact. This does not restore production.
"""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import uuid

BASE = '182_announcement_reads'
TARGET = '183_portal_password_login'
RESTORE_CLIENT_SHA256 = 'c0d0308027906c5116bd4ff6f86923cca04ff969b9cc6c4897aad1ec0da8b618'


def private_directory(path):
    path.mkdir(parents=True, exist_ok=False)
    identity = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh']).decode('ascii', errors='replace')
    sid = next(csv.reader([identity.strip()]))[1]
    result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
        '*' + sid + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Cannot restrict the database backup directory')


def option(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'


def backup_privileges(grants, database):
    scoped, global_privileges = set(), set()
    for grant in grants:
        # SHOW GRANTS may include partial revokes. A flat GRANT union cannot
        # establish effective privileges in that case; refuse before dumping.
        if re.match(r'REVOKE\s', grant, re.I):
            raise RuntimeError('Complete backup privileges include partial revokes; protected DBA review required')
        match = re.match(r'GRANT (.+) ON (.+) TO ', grant, re.I)
        if not match:
            continue
        target = match[2].replace('`', '').lower()
        privileges = {value.strip().upper() for value in match[1].split(',')}
        if target == '*.*':
            global_privileges.update(privileges)
        if target in {'*.*', database.lower() + '.*'}:
            scoped.update(privileges)
    required = {'SELECT', 'SHOW VIEW', 'EVENT', 'TRIGGER'}
    missing = required - scoped if 'ALL PRIVILEGES' not in scoped else set()
    # A filtered routine listing cannot prove that unowned routines are absent.
    if not {'ALL PRIVILEGES', 'SELECT', 'SHOW_ROUTINE'} & global_privileges:
        missing.add('SHOW_ROUTINE (global definition visibility)')
    if missing:
        raise RuntimeError('Complete backup privileges are missing: ' + ', '.join(sorted(missing)))


def snapshot(root, settings, connection):
    if os.name != 'nt' or root.resolve() != Path('D:/commission-system').resolve():
        raise RuntimeError('Database backup must run on the installed office host')
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    identity = connection.execute(text('SELECT @@server_uuid, DATABASE()')).one()
    current = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
    if current != [BASE] or identity[1] != 'commission_db':
        raise RuntimeError('Portal backup requires the actual single revision 182 commission_db')
    engines = connection.execute(text('SELECT DISTINCT engine FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type="BASE TABLE"')).scalars().all()
    if engines != ['InnoDB']:
        raise RuntimeError('Snapshot requires reviewed transactional tables')
    backup_privileges(connection.execute(text('SHOW GRANTS')).scalars().all(), 'commission_db')
    schema = connection.execute(text('SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME '
        'FROM information_schema.schemata WHERE SCHEMA_NAME=DATABASE()')).one()
    tools = root / '.deploy_state/tools/mysql-8.4.6'
    manifest = json.loads((tools / 'manifest.json').read_text())
    binary = tools / 'bin/mysqldump.exe'
    for relative, expected in manifest.items():
        path = (tools / relative).resolve()
        if not path.is_relative_to(tools.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Backup tool differs from its reviewed manifest')
    directory = root / '.deploy_state/customer-portal-backups' / uuid.uuid4().hex
    private_directory(directory)
    credential = directory / 'client.cnf'
    output = directory / 'commission_db.sql'
    url = make_url(settings.commission_db_url)
    credential.write_text('[client]\n' + '\n'.join(key + '=' + option(value) for key, value in {
        'host': url.host, 'port': url.port or 3306, 'user': url.username, 'password': url.password,
        'default-character-set': 'utf8mb4'}.items()) + '\n', encoding='utf-8')
    started = datetime.now(timezone.utc).isoformat()
    try:
        with (directory / 'dump.stderr').open('wb') as errors:
            result = subprocess.run([str(binary), '--defaults-file=' + str(credential), '--no-login-paths',
                '--protocol=TCP', '--host=' + url.host, '--port=' + str(url.port or 3306), '--user=' + url.username,
                '--single-transaction', '--quick', '--routines', '--events', '--triggers', '--hex-blob',
                '--set-gtid-purged=OFF', '--column-statistics=0', '--no-tablespaces',
                '--result-file=' + str(output), 'commission_db'], stderr=errors, stdout=subprocess.DEVNULL, timeout=900)
        if result.returncode:
            raise RuntimeError('Logical backup failed; protected diagnostic retained on office host')
    finally:
        credential.unlink(missing_ok=True)
    if connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() != [BASE]:
        raise RuntimeError('Database revision changed during snapshot')
    with output.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = {'database_uuid': identity[0], 'database': identity[1], 'revision': BASE, 'target': TARGET,
        'schema': {'name': identity[1], 'character_set': schema[0], 'collation': schema[1]},
        'started_at_utc': started, 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'path': str(output), 'sha256': checksum, 'bytes': output.stat().st_size,
        'scope': 'full commission_db logical backup; isolated recovery must be verified separately'}
    (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    return receipt


def validate_proof(state, connection, pending, schema):
    if '183_portal_password_login' not in pending:
        return
    if pending != [TARGET] or schema != TARGET:
        raise RuntimeError('Portal credentials require the separately rehearsed unique 182-to-183 path')
    from sqlalchemy import text
    proof = json.loads((state / 'customer-portal-upgrade-proof.json').read_text())
    migration = Path(__file__).resolve().parents[1] / 'backend/alembic/versions/183_portal_password_login.py'
    if (connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() != [BASE]
            or proof.get('database_uuid') != connection.scalar(text('SELECT @@server_uuid'))
            or proof.get('base') != BASE or proof.get('target') != TARGET
            or proof.get('business_rows_and_constraints_unchanged') is not True or proof.get('restore_after_ddl_verified') is not True
            or proof.get('stored_definitions_unchanged') is not True or proof.get('source_stored_definitions_verified') is not True
            or proof.get('source_schema_verified') is not True or proof.get('event_scheduler_remained_off') is not True
            or proof.get('restore_transport') != 'linux_mysql_ssh_owned_loopback'
            or proof.get('restore_client_sha256') != RESTORE_CLIENT_SHA256
            or proof.get('migration_sha256') != hashlib.sha256(migration.read_bytes().replace(b'\r\n', b'\n')).hexdigest()):
        raise RuntimeError('Actual credential upgrade/recovery proof does not match this database and migration')


def execute(revision):
    import publish
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    import sys
    sys.path.insert(0, str(publish.ROOT / 'backend'))
    from app.core.config import get_settings
    source = Path(__file__).resolve().parent.parent
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=source, text=True)
    if revision != actual or dirty:
        raise RuntimeError('Backup requires the clean pinned candidate')
    values = dotenv_values(publish.STATE / 'credentials/migration.env')
    if set(values) != {'COMMISSION_DB_USER', 'COMMISSION_DB_PASSWORD'} or not all(values.values()):
        raise RuntimeError('Independent protected DBA credential file is invalid')
    runtime = get_settings()
    if values['COMMISSION_DB_USER'] == runtime.COMMISSION_DB_USER:
        raise RuntimeError('Backup requires the independent DBA identity')
    settings = runtime.model_copy(update=values)
    engine = create_engine(settings.commission_db_url, hide_parameters=True)
    stage = 'deployment lock and DBA connection'
    try:
        with publish.deployment_lock(), engine.connect() as connection:
            stage = 'backup preflight or snapshot'
            if connection.scalar(text("SELECT GET_LOCK('leshine-schema-release',0)")) != 1:
                raise RuntimeError('Another schema release owns the maintenance lock')
            try:
                receipt = snapshot(publish.ROOT, settings, connection)
                receipt['candidate_revision'] = revision
                publish.atomic_json(publish.STATE / 'customer-portal-backup.json', receipt)
                print(json.dumps(receipt), flush=True)
            finally:
                connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
    except Exception as error:
        # Never expose driver URLs or SQL parameters from production diagnostics.
        raise RuntimeError(str(error) if isinstance(error, RuntimeError) else 'Protected portal backup failed during ' + stage + ': ' + type(error).__name__) from None
    finally:
        engine.dispose()
