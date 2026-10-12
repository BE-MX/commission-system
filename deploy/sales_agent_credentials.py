"""On-server credential bootstrap for the existing sales principal; no secret output."""
from datetime import timedelta
import json
import os
from pathlib import Path
import pwd
import secrets
import sys

BACKEND = Path('/home/ubuntu/commission-system/backend')
PROFILE = Path('/var/lib/ark-sales/.openclaw-ark-sales')
LABEL = 'openclaw-sales-beijing'
INTENT = Path('/opt/ark-sales/token-issuance.json')


def record_intent():
    if INTENT.exists():
        raise RuntimeError('Credential issuance was already attempted; reconcile its outcome first')
    fd = os.open(INTENT, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps({'label': LABEL, 'user_id': 90, 'status': 'request_started'}))
        stream.flush()
        os.fsync(stream.fileno())
    parent_fd = os.open(INTENT.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def save_private(path, value):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RuntimeError('Unsafe credential destination')
    path.parent.mkdir(mode=0o700, exist_ok=True)
    owner = pwd.getpwnam('ark-sales')
    os.chown(path.parent, owner.pw_uid, owner.pw_gid)
    temp = path.with_name(path.name + '.' + secrets.token_hex(12))
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value.strip() + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(temp, owner.pw_uid, owner.pw_gid)
    os.replace(temp, path)


def main():
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import httpx
    from app.auth.models import ArkUser
    from app.auth.utils import create_access_token, hash_token
    from app.core.database import get_db
    from app.mcp.auth import build_current_user
    from app.mcp.models import MCPToken
    from app.customer.models import CustomerResearchTask, SearchJob

    generator = get_db()
    db = next(generator)
    try:
        sales = db.get(ArkUser, 90)
        if sales is None or sales.username != 'openclaw-sales-01' or not sales.is_active:
            raise RuntimeError('Existing sales principal changed')
        identity = build_current_user(sales)
        if 'sales_automation:invoke' not in identity['permissions'] or 'super_admin' in identity['roles']:
            raise RuntimeError('Existing sales permissions invalid')
        admins = [build_current_user(user) for user in db.query(ArkUser).filter(
            ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).all()]
        operator = next((item for item in admins if 'super_admin' in item['roles']), None)
        if operator is None:
            raise RuntimeError('No active maintenance operator')
        running = db.query(CustomerResearchTask).filter(CustomerResearchTask.claimed_by.like('90:%'),
            CustomerResearchTask.task_status == 'running').count()
        running += db.query(SearchJob).filter(SearchJob.claimed_by.like('90:%'), SearchJob.status == 'running').count()
        if running:
            raise RuntimeError('Wait for old sales research tasks to drain')
        path = PROFILE / 'secrets/ark-agent-token'
        rows = db.query(MCPToken).filter_by(user_id=90, label=LABEL, is_active=True).all()
        if len(rows) > 1:
            raise RuntimeError('Duplicate cloud credentials require reconciliation')
        row = rows[0] if rows else None
        if row is not None and (not path.exists() or hash_token(path.read_text().strip()) != row.token_hash):
            raise RuntimeError('Issued cloud credential has no matching file; inspect before reissuing')
        old_ids = [r.id for r in db.query(MCPToken).filter(MCPToken.user_id == 90,
                   MCPToken.is_active.is_(True), MCPToken.label != LABEL).all()]
        db.rollback()
        auth = create_access_token(operator, expires_delta=timedelta(minutes=5))
        with httpx.Client(base_url='http://127.0.0.1:8001', trust_env=False, timeout=30,
                          headers={'Authorization': 'Bearer ' + auth}) as client:
            if row is None:
                # Exactly one request. Ambiguous outcome is detected by label on the next run.
                record_intent()
                response = client.post('/api/mcp/tokens', json={'user_id': 90, 'label': LABEL})
                if response.status_code != 200:
                    raise RuntimeError(f'Token issuance HTTP {response.status_code}')
                issued = response.json()['data']
                save_private(path, issued['token'])
            token = path.read_text().strip()
            response = client.get('https://leshine.cloud/api/sales-automation/agent/research-tasks/251/context',
                                  headers={'Authorization': 'Bearer ' + token})
            if response.status_code != 200:
                raise RuntimeError(f'Cloud research context HTTP {response.status_code}')
            data = response.json()['data']
            if data.get('execution_contract') != 'external_research_run_v1' or data.get('fact_contract', {}).get('version') != 'registered_research_facts_v1':
                raise RuntimeError('Cloud research contract mismatch')
            for token_id in old_ids:
                response = client.delete('/api/mcp/tokens/' + str(token_id))
                if response.status_code != 200:
                    raise RuntimeError('Old sales credential retirement not confirmed')
        deepseek = json.loads(Path('/root/.openclaw/openclaw.json').read_text())['models']['providers']['deepseek']
        key = deepseek.get('apiKey')
        if isinstance(key, str) and key.strip():
            save_private(PROFILE / 'secrets/deepseek-api-key', key)
        print(json.dumps({'cloud_context': 'verified', 'old_credentials_retired': old_ids,
                          'mimo': 'pending_user_configuration'}))
    finally:
        generator.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # No API response, credential, model configuration, or command is printed.
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)
