"""Deploy only the managed outbound worker, without releasing other applications."""
import base64
import hashlib
import json
from pathlib import Path
from static_sync import remote_python


def artifact(root):
    root = Path(root)
    files = {}
    for name in ['okki_outbound_poller.js', 'okki_outbound_creator.mjs',
                 'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer']:
        path = root / ('systemd' if name.endswith(('.service', '.timer')) else '') / name
        body = path.read_bytes()
        files[name] = {'sha256': hashlib.sha256(body).hexdigest(), 'content': base64.b64encode(body).decode()}
    return files


def invoke(root, action, files, *, coordinated=False, allow_pending=False, revision=None, release_id=None):
    result = remote_python('root@119.28.107.92', Path(root) / 'okki_outbound_remote.py',
                           {'action': action, 'files': files, 'coordinated': coordinated,
                            'allow_pending': allow_pending, 'revision': revision, 'release_id': release_id})
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Outbound remote deployment failed')
    summary = json.loads(result.stdout)
    expected = hashlib.sha256(json.dumps({name: value['sha256'] for name, value in sorted(files.items())}).encode()).hexdigest()
    if summary.get('digest') != expected or summary.get('status') != {
        'prepare': 'prepared', 'freeze': 'frozen', 'activate': 'enabled', 'verify': 'verified',
    }[action]:
        raise RuntimeError('Outbound deployment receipt does not match candidate')
    return summary


def prepare(source, revision, release_id, *, allow_pending=False):
    root = Path(source) / 'deploy'
    files = artifact(root)
    receipt = invoke(root, 'prepare', files, coordinated=True, allow_pending=allow_pending, revision=revision, release_id=release_id)
    return {'root': root, 'files': files, 'receipt': receipt, 'allow_pending': allow_pending,
            'revision': revision, 'release_id': release_id}


def phase(prepared, action):
    return invoke(prepared['root'], action, prepared['files'], coordinated=True,
                  allow_pending=action == 'freeze' and prepared['allow_pending'], revision=prepared['revision'],
                  release_id=prepared['release_id'])


def execute(prepare_only=False):
    root = Path(__file__).resolve().parent
    state = root.parent / '.deploy_state' / 'outbound'
    state.mkdir(parents=True, exist_ok=True)
    summary = invoke(root, 'prepare' if prepare_only else 'activate', artifact(root))
    (state / 'current.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)
