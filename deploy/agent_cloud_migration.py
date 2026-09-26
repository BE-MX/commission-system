"""Explicit, journalled transfer for the inspected 2026-09-26 Agent migration.

Runtime state (including credentials) streams over SSH; it is never a code
artifact or a local file. Activation is a separate, reviewed operation.
"""
import json
import base64
from pathlib import Path
import subprocess

from static_sync import SSH_OPTIONS, remote_python

SOURCE = "root@119.28.107.92"
TARGET = "ubuntu@154.8.205.162"
HERE = Path(__file__).resolve().parent
STATE = HERE.parent / ".deploy_state" / "agent-cloud-migration"
ROOTS = [
    "root/.openclaw", "root/.local/share/pnpm",
    "root/.nvm/versions/node/v22.22.1", "opt/google",
    "opt/social-customer-mcp", "opt/deputy-relay", "usr/local/bin/node",
    "root/.config/systemd/user/openclaw-gateway.service",
    "etc/systemd/system/dingtalk-monitor.service",
    "etc/systemd/system/social-customer-mcp.service",
    "etc/systemd/system/deputy-relay.service",
    "etc/systemd/system/ark-okki-outbound-poller.service",
    "etc/systemd/system/ark-okki-outbound-poller.timer",
]


def invoke(host, action):
    result = remote_python(host, HERE / "agent_cloud_remote.py", {"action": action},
                           sudo=host == TARGET, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or "Remote operation failed")
    print(result.stdout.strip(), flush=True)
    return json.loads(result.stdout)


def direct_transfer(roots, *, final=False):
    """Use a temporary source-IP-bound key restricted to target staging only."""
    shell = ('ssh -i /var/lib/ark-agent-migration/transfer-key -o IdentitiesOnly=yes '
             '-o BatchMode=yes -o StrictHostKeyChecking=yes '
             '-o UserKnownHostsFile=/var/lib/ark-agent-migration/beijing-known-hosts '
             '-o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4')
    import shlex
    commands = []
    if final:
        allowed = {'root/.openclaw', 'root/.mcporter', 'opt/deputy-relay', 'var/lib/ark-agent-migration/source'}
        if set(roots) != allowed:
            raise ValueError('Final mirror must be exactly the inspected state roots')
        for root in roots:
            commands.append(['rsync', '-az', '--delete', '--checksum', '--compress-level=1',
                             '--numeric-ids', '--info=stats2', '-e', shell, '/' + root + '/', TARGET + ':/' + root + '/'])
    else:
        commands.append(['rsync', '-azR', '--compress-level=1', '--numeric-ids', '--info=stats2', '--exclude=root/.local/share/pnpm/store',
                         '-e', shell, *('/' + name for name in roots), TARGET + ':/'])
    for args in commands:
        result = subprocess.run(['ssh', *SSH_OPTIONS, SOURCE, shlex.join(args)],
                                capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise RuntimeError('Direct transfer failed: ' + result.stderr[-1500:])
        print(result.stdout, flush=True)
    return {'status': 'transferred-to-staging', 'final': final, 'transport': 'restricted-ssh-rsync'}


def execute(action):
    STATE.mkdir(parents=True, exist_ok=True)
    if action in {'source-routes-prepare', 'source-routes-activate', 'source-routes-verify'}:
        request = {'action': action.removeprefix('source-routes-'), 'target': SOURCE,
                   'expected_machine_id': '30fcc575adbb45cd938e5d915c7f98c5',
                   'helper_source_b64': base64.b64encode((HERE / 'agent_cloud_nginx.py').read_bytes()).decode()}
        path = STATE / 'source-routes-plan.json'
        if action != 'source-routes-prepare':
            plan = json.loads(path.read_text())
            request.update({key: plan[key] for key in ['plan_id', 'original_sha256']})
        result = remote_python(SOURCE, HERE / 'agent_cloud_source_routes.py', request)
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:])
        print(result.stdout.strip(), flush=True)
        if action == 'source-routes-prepare':
            path.write_text(result.stdout, encoding='utf-8')
    elif action in {'nginx-prepare', 'nginx-activate', 'nginx-verify'}:
        request = {'action': action.removeprefix('nginx-'), 'target': TARGET,
                   'expected_machine_id': 'fd410411419d40079742fdbc36dec028'}
        path = STATE / 'nginx-plan.json'
        if action != 'nginx-prepare':
            plan = json.loads(path.read_text())
            request.update({key: plan[key] for key in ['plan_id', 'original_sha256']})
        result = remote_python(TARGET, HERE / 'agent_cloud_nginx.py', request, sudo=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:])
        print(result.stdout.strip(), flush=True)
        if action == 'nginx-prepare':
            path.write_text(result.stdout, encoding='utf-8')
    elif action == "prepare":
        invoke(TARGET, "prepare-target")
        invoke(SOURCE, "snapshot-source")
        receipt = direct_transfer(ROOTS + ["var/lib/ark-agent-migration/source"])
        (STATE / "prepared.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    elif action == "copy-frozen-state":
        frozen = invoke(SOURCE, "verify-frozen")
        receipt = direct_transfer(["root/.openclaw", "root/.mcporter", "opt/deputy-relay", "var/lib/ark-agent-migration/source"], final=True)
        receipt['freeze_id'] = frozen['freeze_id']
        (STATE / "frozen-copy.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    elif action in {'validate-staged', 'configure-target', 'activate-target', 'verify-target'}:
        if action in {'configure-target', 'activate-target'} and not (STATE / 'frozen-copy.json').exists():
            raise RuntimeError('Final frozen state copy is required before activation')
        if action == 'activate-target':
            frozen = invoke(SOURCE, 'verify-frozen')
            if frozen['freeze_id'] != json.loads((STATE / 'frozen-copy.json').read_text())['freeze_id']:
                raise RuntimeError('Frozen source does not match final state copy')
        result = invoke(TARGET, action)
        (STATE / (action + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    elif action == 'freeze-source':
        if not (STATE / 'validate-staged.json').exists():
            raise RuntimeError('Validate staged runtime before pausing source')
        invoke(SOURCE, action)
    elif action == 'retire-source':
        invoke(TARGET, 'verify-target')
        invoke(SOURCE, action)
    else:
        raise ValueError("Unsupported migration action")
