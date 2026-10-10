"""Additional proven commission_db writers for the fixed 182-to-183 release."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time
import uuid
import re

from sqlalchemy import create_engine, text

EVENT = 'evt_update_shipment_tracking_dingtalk_user'


def field_hashes(row):
    return {key: hashlib.sha256(json.dumps(value, ensure_ascii=True, default=str).encode()).hexdigest()
        for key, value in row.items()}


def event_snapshot(connection):
    rows = connection.execute(text('SELECT EVENT_NAME, STATUS, DEFINER, EVENT_COMMENT '
        'FROM information_schema.events WHERE EVENT_SCHEMA=DATABASE()')).all()
    if len(rows) != 1 or rows[0][0] != EVENT or rows[0][3]:
        raise RuntimeError('Database events differ from the inspected maintenance scope')
    name, status, definer, _ = rows[0]
    if status not in {'ENABLED', 'DISABLED'}:
        raise RuntimeError('Unreviewed event replication state')
    row = dict(connection.execute(text('SHOW CREATE EVENT `' + EVENT + '`')).mappings().one())
    # This inspected event has no COMMENT and the SHOW CREATE status is adjacent
    # to DO. Do not parse or rewrite arbitrary SQL bodies or quoted literals.
    marker = ' ENABLE DO ' if status == 'ENABLED' else ' DISABLE DO '
    if row['Create Event'].count(marker) != 1:
        raise RuntimeError('Unreviewed event status representation')
    paused = {**row, 'Create Event': row['Create Event'].replace(marker, ' DISABLE DO ', 1)}
    return {'name': name, 'status': status, 'definer': definer,
        'fields_sha256': field_hashes(row), 'paused_fields_sha256': field_hashes(paused),
        'sql_mode': row['sql_mode'], 'time_zone': row['time_zone'],
        'character_set_client': row['character_set_client'], 'collation_connection': row['collation_connection']}


def event_threads_visible(connection):
    if connection.scalar(text('SELECT @@performance_schema')) != 1:
        raise RuntimeError('Performance Schema must prove event worker drain')
    if connection.scalar(text('SELECT COUNT(*) FROM performance_schema.threads WHERE PROCESSLIST_ID=CONNECTION_ID()')) != 1:
        raise RuntimeError('Current connection is absent from event drain monitoring')
    # ENABLED controls INSTRUMENTED, not whether the base thread row exists.
    if connection.scalar(text("SELECT COUNT(*) FROM performance_schema.setup_threads WHERE NAME='thread/sql/event_worker'")) != 1:
        raise RuntimeError('Event worker thread monitoring registration is missing')
    row = connection.execute(text("SHOW GLOBAL STATUS LIKE 'Performance_schema_thread_instances_lost'")).one()
    if int(row[1]) != 0:
        raise RuntimeError('Lost thread instances prevent proven event drain')


@contextmanager
def event_admin(settings, state, expected_uuid, event):
    from dotenv import dotenv_values
    path = state / 'credentials/event-maintenance.env'
    if not path.is_file():
        raise RuntimeError('Protected event-maintenance.env DBA credentials are required before stopping writers')
    values = dotenv_values(path)
    if set(values) != {'COMMISSION_DB_USER', 'COMMISSION_DB_PASSWORD'} or not all(values.values()):
        raise RuntimeError('Event maintenance credential file must contain only DB user/password')
    engine = create_engine(settings.model_copy(update=values).commission_db_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            identity = connection.execute(text('SELECT @@server_uuid, DATABASE(), CURRENT_USER()')).one()
            if identity[:2] != (expected_uuid, 'commission_db'):
                raise RuntimeError('Event maintenance DBA target differs from the inspected database')
            grants = connection.execute(text('SHOW GRANTS')).scalars().all()
            if any(grant.upper().startswith('REVOKE ') for grant in grants):
                raise RuntimeError('Event DBA has partial revokes requiring effective privilege review')
            privileges = set()
            for grant in grants:
                match = re.match(r'GRANT (.+) ON (.+) TO ', grant, re.I)
                if match and match[2].replace('`', '').lower() in {'*.*', 'commission_db.*'}:
                    privileges.update(part.strip().upper() for part in match[1].split(','))
            if not {'EVENT', 'ALL PRIVILEGES'} & privileges:
                raise RuntimeError('Event DBA lacks effective commission_db EVENT permission')
            if identity[2] != event['definer'] and not any(
                    ' ON *.* TO ' in grant and any(privilege in grant for privilege in ('SET_USER_ID', 'SUPER', 'ALL PRIVILEGES'))
                    for grant in grants):
                raise RuntimeError('Event DBA cannot preserve the original definer')
            # Establish visibility before any event/cron/service is paused.
            event_threads_visible(connection)
            yield connection
    finally:
        engine.dispose()


def mirror(action, baseline=None):
    from static_sync import remote_python
    result = remote_python('ubuntu@154.8.205.162', Path(__file__).with_name('portal_mirror_fence_remote.py'),
        {'action': action, **(baseline or {})}, sudo=True, timeout=160)
    if result.returncode:
        raise RuntimeError('Protected mirror maintenance failed; inspect its retained fence state')
    return json.loads(result.stdout)


def check(state, settings, connection):
    database_uuid = connection.scalar(text('SELECT @@server_uuid'))
    event = event_snapshot(connection)
    scheduler = connection.scalar(text('SELECT @@GLOBAL.event_scheduler'))
    # Release SHOW CREATE metadata locks before another connection alters the event.
    connection.commit()
    if scheduler not in {'ON', 'OFF', 'DISABLED'}:
        raise RuntimeError('Unknown production event scheduler state')
    baseline = {'database_uuid': database_uuid, 'event': event, 'scheduler': scheduler,
        'mirror': mirror('check'), 'token': uuid.uuid4().hex}
    with event_admin(settings, state, database_uuid, event) as admin:
        if event_snapshot(admin)['fields_sha256'] != event['fields_sha256']:
            raise RuntimeError('Event DBA cannot verify the original definition')
    return baseline


def alter_event(connection, event, enable):
    user, host = event['definer'].rsplit('@', 1)
    quote = lambda value: '`' + value.replace('`', '``') + '`'
    connection.execute(text('SET SESSION lock_wait_timeout=10'))
    for variable in ('sql_mode', 'time_zone', 'character_set_client', 'collation_connection'):
        connection.execute(text('SET SESSION ' + variable + '=:value'), {'value': event[variable]})
    connection.execute(text('ALTER DEFINER=' + quote(user) + '@' + quote(host)
        + ' EVENT `' + EVENT + '` ' + ('ENABLE' if enable else 'DISABLE')))
    connection.commit()


def freeze(state, settings, connection, baseline, save):
    # Persist intent before each remote/DDL operation; recovery uses observed state.
    save()
    mirror('freeze', {**baseline['mirror'], 'token': baseline['token']})
    baseline['mirror_frozen'] = True; save()
    event = baseline['event']
    if event['status'] == 'ENABLED':
        with event_admin(settings, state, baseline['database_uuid'], event) as admin:
            if event_snapshot(admin)['fields_sha256'] != event['fields_sha256']:
                raise RuntimeError('Production event changed since preflight')
            baseline['event_pause_started'] = True; save()
            alter_event(admin, event, False)
            actual = event_snapshot(admin)
            if actual['fields_sha256'] != event['paused_fields_sha256'] or actual['definer'] != event['definer']:
                raise RuntimeError('Event pause changed its original definition or definer')
            deadline = time.monotonic() + 120
            while True:
                event_threads_visible(admin)
                if not admin.scalar(text("SELECT COUNT(*) FROM performance_schema.threads WHERE NAME='thread/sql/event_worker' "
                        "AND (PROCESSLIST_DB='commission_db' OR PROCESSLIST_DB IS NULL)")):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Database event workers did not drain; no shared migration permitted')
                time.sleep(.2)
            baseline['event_paused'] = True; save()
    verify_frozen(state, settings, connection, baseline)


def verify_frozen(state, settings, connection, baseline):
    mirror('verify-frozen', {**baseline['mirror'], 'token': baseline['token']})
    actual = event_snapshot(connection)
    if connection.scalar(text('SELECT @@GLOBAL.event_scheduler')) != baseline['scheduler']:
        raise RuntimeError('Production event scheduler changed during maintenance')
    connection.commit()
    expected = baseline['event']['paused_fields_sha256'] if baseline.get('event_pause_started') else baseline['event']['fields_sha256']
    if actual['fields_sha256'] != expected:
        raise RuntimeError('Database event maintenance fence changed')
    with event_admin(settings, state, baseline['database_uuid'], baseline['event']) as admin:
        if admin.scalar(text("SELECT COUNT(*) FROM performance_schema.threads WHERE NAME='thread/sql/event_worker' "
                "AND (PROCESSLIST_DB='commission_db' OR PROCESSLIST_DB IS NULL)")):
            raise RuntimeError('Database event workers are still running')


def restore(state, settings, baseline):
    event = baseline['event']
    # Keep the mirror fenced until the original event is restored and verified.
    if baseline.get('event_pause_started'):
        with event_admin(settings, state, baseline['database_uuid'], event) as admin:
            actual = event_snapshot(admin)
            if actual['fields_sha256'] == event['paused_fields_sha256']:
                alter_event(admin, event, True)
            elif actual['fields_sha256'] != event['fields_sha256']:
                raise RuntimeError('Event drift prevents safe baseline restoration')
            if event_snapshot(admin)['fields_sha256'] != event['fields_sha256']:
                raise RuntimeError('Original event definition was not restored')
    # freeze can start the unit then lose its reply; query/restore by persisted token.
    mirror('thaw', {**baseline['mirror'], 'token': baseline['token']})
    baseline['restored'] = True
