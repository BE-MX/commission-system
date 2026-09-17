"""Deploy only the managed outbound worker, without releasing other applications."""
import base64
import hashlib
import json
from pathlib import Path
from static_sync import remote_python


def execute(prepare_only=False):
    root = Path(__file__).resolve().parent
    files = {}
    for name in ['okki_outbound_poller.js', 'okki_outbound_creator.mjs',
                 'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer']:
        path = root / ('systemd' if name.endswith(('.service', '.timer')) else '') / name
        body = path.read_bytes()
        files[name] = {'sha256': hashlib.sha256(body).hexdigest(), 'content': base64.b64encode(body).decode()}
    state = root.parent / '.deploy_state' / 'outbound'
    state.mkdir(parents=True, exist_ok=True)
    result = remote_python('root@119.28.107.92', root / 'okki_outbound_remote.py',
                           {'action': 'prepare' if prepare_only else 'activate', 'files': files})
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Outbound remote deployment failed')
    summary = json.loads(result.stdout)
    (state / 'current.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)
