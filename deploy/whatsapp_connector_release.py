"""Narrow office connector release; reuse the existing source/schema/rollback gates."""

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import urllib.request


ALLOWED = {
    'services/whatsapp-connector/src/manager.js',
    'services/whatsapp-connector/src/projection.js',
    'services/whatsapp-connector/test/contact-metadata.test.mjs',
    'services/whatsapp-connector/README.md',
    'docs/handoff.md',
    'docs/reports/2026-11-14-whatsapp-contact-metadata.md',
    'docs/requirements/2026-10-13-whatsapp-baileys.md',
    'deploy/publish.py', 'deploy/office_release.py', 'deploy/whatsapp_connector_release.py',
    'deploy/tests/test_whatsapp_connector_release.py', 'deploy/README.md',
}


def validate_args(args):
    allowed = {'whatsapp_connector_only', 'revision', 'live_root', 'no_pull', 'prepare_only'}
    if not args.live_root or not args.no_pull or any(value for key, value in vars(args).items() if key not in allowed):
        raise RuntimeError('Connector-only requires pinned managed source, --live-root and --no-pull; no mixed actions')
    for value in (args.revision, args.whatsapp_connector_only):
        if not value or not re.fullmatch(r'[0-9a-f]{40}', value):
            raise RuntimeError('Connector-only requires full baseline and candidate commit hashes')


def validate_changes(changes):
    if not changes or set(changes) - ALLOWED:
        raise RuntimeError('Connector-only candidate contains changes outside the reviewed metadata repair')
    if not any(name.startswith('services/whatsapp-connector/src/') for name in changes):
        raise RuntimeError('Connector-only candidate has no connector runtime change')


def service_environment(live):
    import winreg
    from dotenv import dotenv_values
    from office_release import connector_environment
    values = {'AppEnvironment': None, 'AppEnvironmentExtra': []}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\WhatsAppConnector\Parameters') as key:
        for name in values:
            try:
                values[name] = winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                pass
    return connector_environment(os.environ, dotenv_values(live / 'services/whatsapp-connector/.env'),
                                 values['AppEnvironment'], values['AppEnvironmentExtra'])


def state_path(live):
    from static_retention import no_links
    env = service_environment(live)
    folder = Path(env.get('WHATSAPP_DATA_DIR') or './data')
    if not folder.is_absolute():
        folder = live / 'services/whatsapp-connector' / folder
    source = folder / 'connector.sqlite'
    no_links(source)
    source = source.resolve()
    if not source.is_file():
        raise RuntimeError('Registered connector state is missing')
    return source


def backup_store(prepared):
    from publish import run, atomic_json
    from static_retention import no_links
    if run([prepared['nssm'], 'status', 'WhatsAppConnector'], capture=True) != 'SERVICE_STOPPED':
        raise RuntimeError('Connector must be stopped before its state backup')
    source = state_path(prepared['live'])
    destination = Path(prepared['connector_only_backup'])
    no_links(destination)
    destination.mkdir(parents=True, exist_ok=False)
    operator = subprocess.check_output(['whoami'], text=True).strip()
    run(['icacls', destination, '/inheritance:r', '/grant:r',
         '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', operator + ':(OI)(CI)F'])
    output = destination / 'connector.sqlite'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(output)) as backup:
        original.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Connector backup integrity check failed')
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    atomic_json(destination / 'backup.json', {'revision': prepared['revision'], 'previous': prepared['previous'],
        'sha256': digest, 'bytes': output.stat().st_size,
        'status': 'verified', 'source': str(source)})


def verify_connector(prepared):
    env = service_environment(prepared['live'])
    host = env.get('WHATSAPP_CONNECTOR_HOST') or '127.0.0.1'
    if host not in {'127.0.0.1', 'localhost'}:
        raise RuntimeError('Connector verification requires the registered loopback listener')
    port = int(env.get('PORT') or 8787)
    request = urllib.request.Request(f'http://127.0.0.1:{port}/health',
                                    headers={'Authorization': 'Bearer ' + env['WHATSAPP_CONNECTOR_API_KEY'].strip()})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 60
    while True:
        try:
            with opener.open(request, timeout=5) as response:
                payload = json.load(response)
            if payload.get('status') == 'ok' and payload.get('provider') == 'baileys':
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Connector health did not recover; rolling back candidate code')
        time.sleep(1)


def execute(source, live, state, revision, baseline, prepare_only):
    import publish
    from source_release import prepare
    if os.name != 'nt':
        raise RuntimeError('Connector-only release must run on the office Windows host')
    def git(*args, root=live):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    if source.resolve() != (state / 'sources' / revision).resolve():
        raise RuntimeError('Connector controller must be its pinned managed source')
    if git('rev-parse', 'HEAD') != baseline or git('rev-parse', 'HEAD', root=source) != revision:
        raise RuntimeError('Connector baseline or candidate changed')
    if git('status', '--porcelain', '--untracked-files=normal', root=source):
        raise RuntimeError('Connector candidate is dirty')
    validate_changes(git('diff', '--no-renames', '--name-only', '-z', baseline, revision, '--').strip('\0').split('\0'))
    journal_path = state / 'whatsapp-connector-release.json'
    if journal_path.exists() and json.loads(journal_path.read_text(encoding='utf8')).get('status') not in {'prepared', 'succeeded'}:
        raise RuntimeError('Previous connector release requires inspection before retry')
    full = state / 'publish-current.json'
    if full.exists() and json.loads(full.read_text(encoding='utf8')).get('status') != 'succeeded':
        raise RuntimeError('Unfinished full release blocks connector-only activation')
    candidate, actual, previous = prepare(live, state, False, pinned_revision=revision)
    if (candidate.resolve(), actual, previous) != (source.resolve(), revision, baseline):
        raise RuntimeError('Prepared source identity changed')
    publish.ROOT = source
    from schema_release import check_recovery
    check_recovery()
    from office_release import prepare as prepare_office, activate
    prepared = prepare_office(live, baseline, revision)
    if prepared['pending'] or prepared['backend_changed'] or not prepared['connector_changed']:
        raise RuntimeError('Connector-only cannot activate backend changes or pending schema')
    command = publish.run([prepared['nssm'], 'get', 'WhatsAppConnector', 'AppParameters'], capture=True)
    if Path(command.strip('"')).resolve() != (live / 'services/whatsapp-connector/src/server.js').resolve():
        raise RuntimeError('Connector service command differs from the verified live checkout')
    if service_environment(live).get('WHATSAPP_RESTORE_ON_START') == 'false':
        raise RuntimeError('Connector startup restore is disabled; no activation attempted')
    prepared['static'] = []
    prepared['connector_only_backup'] = state / 'whatsapp-connector-backups' / revision
    if prepared['connector_only_backup'].exists():
        raise RuntimeError('Existing connector backup requires inspection before another activation')
    state_path(live)
    if publish.run([prepared['nssm'], 'status', 'WhatsAppConnector'], capture=True) != 'SERVICE_RUNNING':
        raise RuntimeError('Connector baseline must be running before scoped release')
    verify_connector(prepared)
    journal = {'revision': revision, 'previous': baseline, 'scope': 'office-whatsapp-connector',
               'schema': prepared['schema'], 'status': 'prepared', 'state_backup': str(prepared['connector_only_backup'])}
    publish.atomic_json(journal_path, journal)
    if prepare_only:
        return journal
    journal['status'] = 'activating'
    publish.atomic_json(journal_path, journal)
    try:
        result = activate(prepared)
    except Exception:
        journal['status'] = 'failed-inspect-required'
        publish.atomic_json(journal_path, journal)
        raise
    journal.update(status='succeeded', activation=result)
    publish.atomic_json(journal_path, journal)
    return journal
