"""Host-local COS activation steps; secrets never leave the host or enter output."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

DOMAINS = ['asset', 'shipping-inspection', 'customer-media', 'design-image',
           'design-attachments', 'domestic', 'receipt-proofs', 'pm', 'training',
           'aftersales', 'ai-chat', 'avatars', 'card', 'expo', 'festival',
           'hair', 'video', 'tag_images', 'knowledge', 'insight', 'colorwork']


class FrozenTransferSession:
    """One lookup while all writers are stopped, avoiding 30k WAN round trips."""
    def __init__(self, db):
        from app.core.storage.models import StorageTransfer
        self.db = db
        self.model = StorageTransfer
        self.known = {row.id: row for row in db.query(StorageTransfer).filter(
            StorageTransfer.domain.in_(['asset', 'shipping-inspection']))}

    def get(self, model, identity):
        return self.known.get(identity) if model is self.model else self.db.get(model, identity)

    def add(self, record):
        self.db.add(record)
        if isinstance(record, self.model):
            self.known[record.id] = record

    def __getattr__(self, name):
        return getattr(self.db, name)


def run(args):
    return subprocess.check_output([str(a) for a in args], text=True, encoding="utf-8", errors="replace", stderr=subprocess.PIPE).strip()


def context(request):
    office = os.name == 'nt'
    root = Path('D:/commission-system' if office else '/home/ubuntu/commission-system')
    if not re.fullmatch('[a-z0-9-]{1,64}', request['attempt']):
        raise ValueError('Invalid attempt')
    if run(['git', '-C', root, 'rev-parse', 'HEAD']) != request['revision']:
        raise RuntimeError('Live code differs from reviewed release')
    os.chdir(root / 'backend')
    sys.path.insert(0, str(root / '.deploy_state/cloud-storage-migration/lib'))
    sys.path.insert(0, str(root / 'backend'))
    state = root / '.deploy_state/storage-cutover' / request['attempt']
    return office, root, state


def controller(office):
    nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
    names = ['CommissionSystem', 'WhatsAppConnector'] if office else ['ark-colorwork', 'ark-backend']
    def status(name):
        value = run([nssm, 'status', name] if office else ['systemctl', 'show', '-p', 'ActiveState', '--value', name])
        states = {'SERVICE_RUNNING': 'running', 'SERVICE_STOPPED': 'stopped', 'active': 'running', 'inactive': 'stopped'}
        if value not in states:
            raise RuntimeError('Service is not stable: ' + name)
        return states[value]
    def control(name, action):
        run([nssm, action, name] if office else ['sudo', '-n', 'systemctl', action, name])
        target = 'running' if action == 'start' else 'stopped'
        if status(name) != target:
            raise RuntimeError('Service failed to reach ' + target)
    return names, status, control


def update_env(path, values):
    content = path.read_text(encoding='utf-8-sig')
    names = set(values)
    lines = [line for line in content.splitlines() if not any(
        re.match(r'^\s*(?:export\s+)?' + re.escape(name) + r'\s*=', line) for name in names)]
    for name, value in values.items():
        encoded = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
        # Lists are JSON for pydantic; scalar JSON quotes are dotenv compatible.
        lines.append(name + '=' + ("'" + encoded + "'" if isinstance(value, list) else encoded))
    # Preserve hard links to managed candidate .env files and the original ACL.
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(lines) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def validate_coverage(data, required_sources):
    if set(required_sources) != set(DOMAINS):
        raise RuntimeError('Every enabled domain needs an audited source matrix')
    actual = {(item['manifest']['domain'], item['manifest']['source_instance']) for item in data}
    expected = {(domain, source) for domain, sources in required_sources.items() for source in sources}
    if any(not sources or len(sources) != len(set(sources)) or
           not set(sources) <= {'office', 'beijing', 'singapore'} for sources in required_sources.values()):
        raise ValueError('Invalid domain source matrix')
    if actual != expected:
        raise RuntimeError('Migration evidence does not cover the reviewed domain/source matrix')


def expected_config(root, office, secrets):
    values = {key: getattr(secrets, key) for key in ['COS_BUCKET', 'COS_REGION', 'COS_KEY_PREFIX',
              'COS_SECRET_ID', 'COS_SECRET_KEY', 'COS_SECURITY_TOKEN']}
    values.update(COS_ENABLED_DOMAINS=DOMAINS, COS_MANAGED_DOMAINS=DOMAINS,
                  COS_INSTANCE_ID='office' if office else 'beijing', COS_LOCAL_OWNER='office',
                  COS_WORKER_ENABLED=True, COS_CACHE_ROOT=str(root / 'backend/data/cos-cache'))
    return values


def validate_runtime(runtime, expected):
    if any(getattr(runtime, key) != value for key, value in expected.items()):
        raise RuntimeError('Runtime storage configuration differs from reviewed destination')


def validate_colorwork(root):
    from dotenv import dotenv_values
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.colorwork.storage_service import secret
    info = json.loads((root / '.deploy_state/colorwork/success.json').read_text())
    folder = Path(info['source']) / 'colorwork-workbench'
    if not folder.resolve().is_relative_to((root / '.deploy_state/checkouts').resolve()):
        raise RuntimeError('Unexpected Colorwork source')
    values = dotenv_values(folder / '.dev.vars')
    if (values.get('ARK_STORAGE_ENDPOINT'), values.get('ARK_STORAGE_SECRET')) != (
            'http://127.0.0.1:8001/api/colorwork/storage', secret()):
        raise RuntimeError('Colorwork storage configuration differs')


def health():
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4) as response:
                result = json.load(response)
            if result.get('status') == 'ok' and result.get('database') == 'connected':
                return
        except Exception:
            if attempt == 29:
                raise RuntimeError('Backend health did not recover') from None
        time.sleep(1)
    raise RuntimeError('Backend health did not recover')


def execute(request):
    office, root, state = context(request)
    names, status, control = controller(office)
    action = request['action']
    from app.core.config import Settings
    from app.core.storage.cos import CosObjectStore
    from sqlalchemy import create_engine, text
    runtime = Settings(_env_file=root / 'backend/.env')
    secrets = Settings(_env_file=root / '.deploy_state/cloud-storage-migration/cos.env')
    if (secrets.COS_BUCKET, secrets.COS_REGION, secrets.COS_KEY_PREFIX) != (
            'leshine-ark-1259007308', 'ap-beijing', 'ark/production'):
        raise RuntimeError('Unexpected storage destination')
    engine = create_engine(runtime.commission_db_url)
    with engine.connect() as connection:
        if list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars()) != ['159_storage_transfers']:
            raise RuntimeError('COS requires deployed schema 159')
    marker = state / 'state.json'
    def save(data):
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if office and not marker.exists():
            account = run(['whoami'])
            run(['icacls', state, '/inheritance:r', '/grant:r',
                 account + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'])
        temporary = marker.with_suffix('.next')
        temporary.write_text(json.dumps(data))
        temporary.replace(marker)
    if action == 'prepare':
        if marker.exists():
            raise RuntimeError('Prior cutover attempt needs inspection')
        CosObjectStore('avatars', settings=secrets).head(request['probe_key'])
        return {'status': 'prepared', 'instance': 'office' if office else 'beijing',
                'services': {name: status(name) for name in names}, 'domains': DOMAINS}
    if action == 'stop':
        ingress = (root / '.deploy_state/storage-maintenance' / request['maintenance_attempt'] / 'office.json') if office else (
            Path('/etc/nginx/.ark-backups/storage-maintenance') / request['maintenance_attempt'] / 'record.json')
        ingress_data = ingress.read_text() if office else run(['sudo', '-n', 'cat', ingress])
        if json.loads(ingress_data)['status'] != 'frozen':
            raise RuntimeError('Ingress must be frozen before stopping writers')
        if marker.exists():
            record = json.loads(marker.read_text())
            if record['revision'] != request['revision'] or record['status'] not in {'stopping', 'stopped'}:
                raise RuntimeError('Prior cutover attempt needs inspection')
        else:
            record = {'status': 'stopping', 'revision': request['revision'], 'before': {name: status(name) for name in names}}
        save(record)
        for name in names:
            if status(name) == 'running':
                control(name, 'stop')
        record['status'] = 'stopped'
        save(record)
        return {'status': 'stopped'}
    record = json.loads(marker.read_text())
    if record['revision'] != request['revision']:
        raise RuntimeError('Cutover release drift')
    if action == 'inspect':
        return {key: record[key] for key in ['status', 'revision', 'receipts_sha256'] if key in record}
    if action in {'configure', 'register', 'assert-stopped'}:
        if any(status(name) != 'stopped' for name in names):
            raise RuntimeError('File writers must remain stopped')
    if action == 'assert-stopped':
        return {'status': 'stopped'}
    if action == 'configure':
        if record['status'] in {'configured', 'registered'}:
            if record.get('receipts_sha256') != request['receipts_sha256'] or runtime.COS_ENABLED_DOMAINS != DOMAINS:
                raise RuntimeError('Configuration or receipt drift')
            validate_runtime(runtime, expected_config(root, office, secrets))
            if not office:
                validate_colorwork(root)
            return {'status': 'configured'}
        if record['status'] not in {'stopped', 'configuring'}:
            raise RuntimeError('Configuration requires fresh stopped baseline')
        env = root / 'backend/.env'
        backup = state / 'backend.env.before'
        if not backup.exists():
            if record['status'] != 'stopped':
                raise RuntimeError('Original environment backup is missing')
            shutil.copy2(env, backup)
        if not office:
            backup.chmod(0o600)
        values = expected_config(root, office, secrets)
        record['status'] = 'configuring'
        if record.get('receipts_sha256', request['receipts_sha256']) != request['receipts_sha256']:
            raise RuntimeError('Receipt identity changed')
        record['receipts_sha256'] = request['receipts_sha256']
        save(record)
        update_env(env, values)
        active = Settings(_env_file=env)
        if active.COS_ENABLED_DOMAINS != DOMAINS or not active.COS_WORKER_ENABLED:
            raise RuntimeError('Written configuration did not validate')
        if not office:
            info = json.loads((root / '.deploy_state/colorwork/success.json').read_text())
            folder = Path(info['source']) / 'colorwork-workbench'
            if not folder.resolve().is_relative_to((root / '.deploy_state/checkouts').resolve()):
                raise RuntimeError('Unexpected Colorwork source')
            target = folder / '.dev.vars'
            if not (state / 'colorwork.vars.before').exists():
                shutil.copy2(target, state / 'colorwork.vars.before')
            (state / 'colorwork.vars.before').chmod(0o600)
            from app.core.config import get_settings
            get_settings.cache_clear()
            from app.colorwork.storage_service import secret
            update_env(target, {'ARK_STORAGE_ENDPOINT': 'http://127.0.0.1:8001/api/colorwork/storage',
                                'ARK_STORAGE_SECRET': secret()})
            target.chmod(0o600)
        record['status'] = 'configured'
        save(record)
        return {'status': 'configured', 'domains': DOMAINS}
    if action == 'register':
        if office and record['status'] == 'registered' and record.get('receipts_sha256') == request['receipts_sha256']:
            return {'status': 'registered', 'idempotent': True}
        if not office or record['status'] != 'configured':
            raise RuntimeError('Only the configured office may commit shared references')
        import hashlib
        bundle = root / '.deploy_state/cloud-storage-migration/cutover-receipts.json'
        if hashlib.sha256(bundle.read_bytes()).hexdigest() != request['receipts_sha256']:
            raise RuntimeError('Verified receipt bundle changed')
        data = json.loads(bundle.read_text(encoding='utf-8'))
        validate_coverage(data, request['required_sources'])
        from app.core.storage.cutover import verified_union, register_ready, migrate_customer_references
        rows = verified_union([(item['manifest'], item['journal']) for item in data],
            bucket=secrets.COS_BUCKET, prefix=secrets.COS_KEY_PREFIX)
        # ORM flush resolves foreign keys for customer-media associations.
        import app.auth.models  # noqa: F401
        import app.design.models  # noqa: F401
        from sqlalchemy.orm import Session
        with engine.connect() as connection:
            if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
                raise RuntimeError('Another deployment owns the database lock')
            connection.commit()
            try:
                with Session(bind=connection) as db:
                    frozen = FrozenTransferSession(db)
                    register_ready(frozen, 'asset', rows['asset'], 'office',
                                   missing_reference_exceptions=request['missing_asset_keys'])
                    register_ready(frozen, 'shipping-inspection', rows['shipping-inspection'], 'office')
                    migrated = migrate_customer_references(db, rows['customer-media'])
                    db.commit()
            finally:
                connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
        record.update(status='registered', receipts_sha256=request['receipts_sha256'])
        save(record)
        return {'status': 'registered', 'customer_assets': migrated,
                'asset_objects': len(rows['asset']), 'inspection_objects': len(rows['shipping-inspection'])}
    if action in {'validate-start', 'start'}:
        if record['status'] not in ({'registered', 'starting', 'started'} if office else {'configured', 'starting', 'started'}):
            raise RuntimeError('Cutover is not ready to start')
        if record.get('receipts_sha256') != request['receipts_sha256'] or runtime.COS_ENABLED_DOMAINS != DOMAINS or runtime.COS_MANAGED_DOMAINS != DOMAINS:
            raise RuntimeError('Startup configuration/receipt identity mismatch')
        validate_runtime(runtime, expected_config(root, office, secrets))
        if not office:
            validate_colorwork(root)
        if action == 'validate-start':
            return {'status': 'ready'}
        record['status'] = 'starting'
        save(record)
        for name in reversed(names) if not office else names:
            if record['before'][name] == 'running' and status(name) == 'stopped':
                control(name, 'start')
            if name in {'CommissionSystem', 'ark-backend'}:
                health()
        if not office:
            with urllib.request.urlopen('http://127.0.0.1:8787/api/colorwork/workbench/api/health', timeout=8) as response:
                if json.load(response) != {'status': 'ok', 'module': 'colorwork'}:
                    raise RuntimeError('Colorwork health failed')
        record['status'] = 'started'
        save(record)
        return {'status': 'started', 'health': 'ok'}
    raise ValueError('Unsupported cutover action')


if __name__ == '__main__':
    try:
        print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        # SDK/DB exceptions may include credentials; preserve only the type.
        print('Cutover host failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
