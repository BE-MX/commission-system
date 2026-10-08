"""Deploy only the managed outbound worker, without releasing other applications."""
import base64
import hashlib
import json
import re
from pathlib import Path
from static_sync import remote_python
from timer_writer import registered_writer


def artifact(root):
    root = Path(root)
    files = {}
    for name in ['okki_outbound_poller.js', 'okki_outbound_creator.mjs', 'okki_outbound_mode.mjs',
                 'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer']:
        path = root / ('systemd' if name.endswith(('.service', '.timer')) else '') / name
        body = path.read_bytes()
        files[name] = {'sha256': hashlib.sha256(body).hexdigest(), 'content': base64.b64encode(body).decode()}
    return files


def confirmed_schedule(value):
    return (isinstance(value, dict) and set(value) == {'active', 'enabled'}
            and all(type(item) is bool for item in value.values()))


def invoke(root, action, files, *, coordinated=False, allow_pending=False, revision=None, release_id=None,
           database_fingerprint=None, mode=None, baseline=None):
    writer = registered_writer('ark-okki-outbound-poller', root)
    result = remote_python(writer['host'], Path(root) / 'okki_outbound_remote.py',
                           {'action': action, 'files': files, 'coordinated': coordinated,
                            'allow_pending': allow_pending, 'revision': revision, 'release_id': release_id,
                            'database_fingerprint': database_fingerprint, 'mode': mode, 'baseline': baseline}, sudo=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Outbound remote deployment failed')
    try:
        summary = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError('Outbound deployment receipt cannot be read') from None
    if not isinstance(summary, dict):
        raise RuntimeError('Outbound deployment receipt cannot be read')
    return validate_receipt(summary, action, files, coordinated=coordinated, revision=revision,
                            release_id=release_id, database_fingerprint=database_fingerprint,
                            mode=mode, baseline=baseline)


def validate_receipt(summary, action, files, *, coordinated=False, revision=None, release_id=None,
                     database_fingerprint=None, mode=None, baseline=None):
    if not isinstance(summary, dict):
        raise RuntimeError('Outbound deployment receipt cannot be read')
    expected = hashlib.sha256(json.dumps({name: value['sha256'] for name, value in sorted(files.items())}).encode()).hexdigest()
    if summary.get('digest') != expected or summary.get('status') != {
        'prepare': 'prepared', 'freeze': 'frozen', 'install': 'installed_paused',
        'activate': 'enabled', 'verify': 'verified',
    }[action]:
        raise RuntimeError('Outbound deployment receipt does not match candidate')
    if (not isinstance(summary.get('mode'), str) or summary['mode'] not in {'legacy', 'outbound-worker-v1'}
            or not isinstance(summary.get('database_fingerprint'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', summary['database_fingerprint'])
            or (database_fingerprint is not None and summary['database_fingerprint'] != database_fingerprint)
            or (mode == 'outbound-worker-v1' and summary['mode'] != mode)
            or (coordinated and (summary.get('revision') != revision or summary.get('release_id') != release_id))):
        raise RuntimeError('Outbound mode receipt does not match release')
    if action != 'prepare':
        receipt_baseline = summary.get('baseline')
        if (not isinstance(receipt_baseline, dict) or set(receipt_baseline) != {'active', 'enabled'}
                or any(type(value) is not bool for value in receipt_baseline.values())
                or (baseline is not None and receipt_baseline != baseline)):
            raise RuntimeError('Outbound baseline receipt does not match release')
    if action in {'activate', 'verify'}:
        baseline, schedule = summary.get('baseline'), summary.get('schedule')
        if (not isinstance(baseline, dict) or set(baseline) != {'active', 'enabled'}
                or any(type(value) is not bool for value in baseline.values())
                or not isinstance(schedule, dict) or set(schedule) != {'active', 'enabled'}
                or any(type(value) is not bool for value in schedule.values())
                or schedule != ({'active': False, 'enabled': False} if summary['mode'] == 'outbound-worker-v1' else baseline)
                or not confirmed_schedule(summary.get('target_schedule'))
                or summary['target_schedule'] != schedule or summary.get('release_confirmed') is not True
                or (not coordinated and summary['mode'] != 'legacy')):
            raise RuntimeError('Outbound activation receipt does not match mode target')
    if action == 'freeze':
        pause = summary.get('target_schedule')
        if (not confirmed_schedule(summary.get('schedule')) or summary['schedule'] != summary['baseline'] or not isinstance(pause, dict)
                or set(pause) != {'active', 'enabled'}
                or any(type(value) is not bool or value for value in pause.values())
                or summary.get('release_confirmed') is not False):
            raise RuntimeError('Outbound freeze receipt does not confirm pause')
    if action == 'install':
        schedule = summary.get('schedule')
        if (not coordinated or summary.get('revision') != revision or summary.get('release_id') != release_id
                or not isinstance(schedule, dict) or set(schedule) != {'active', 'enabled'}
                or any(type(value) is not bool or value for value in schedule.values())
                or not confirmed_schedule(summary.get('target_schedule'))
                or summary['target_schedule'] != schedule or summary.get('release_confirmed') is not False):
            raise RuntimeError('Outbound paused installation receipt does not match release')
    return summary


def prepare(source, revision, release_id, *, allow_pending=False):
    root = Path(source) / 'deploy'
    files = artifact(root)
    receipt = invoke(root, 'prepare', files, coordinated=True, allow_pending=allow_pending, revision=revision, release_id=release_id)
    return {'root': root, 'files': files, 'receipt': receipt, 'allow_pending': allow_pending,
            'revision': revision, 'release_id': release_id}


def phase(prepared, action):
    result = invoke(prepared['root'], action, prepared['files'], coordinated=True,
                    allow_pending=action == 'freeze' and prepared['allow_pending'], revision=prepared['revision'],
                    release_id=prepared['release_id'], database_fingerprint=prepared['receipt']['database_fingerprint'],
                    mode=('outbound-worker-v1' if 'outbound-worker-v1' in {prepared['receipt']['mode'],prepared.get('_mode_floor')}
                          else 'legacy'), baseline=prepared.get('_baseline'))
    if action == 'freeze' and '_baseline' not in prepared:
        prepared['_baseline'] = dict(result['baseline'])
    if result['mode'] == 'outbound-worker-v1': prepared['_mode_floor'] = result['mode']
    return result


def execute(prepare_only=False):
    root = Path(__file__).resolve().parent
    state = root.parent / '.deploy_state' / 'outbound'
    state.mkdir(parents=True, exist_ok=True)
    summary = invoke(root, 'prepare' if prepare_only else 'activate', artifact(root))
    (state / 'current.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)


def _verify_completion(prepared, journal):
    """Recheck the bound stage and live target before resuming writers or publishing success."""
    if (not isinstance(prepared, dict) or not isinstance(journal, dict)
            or not re.fullmatch(r'[0-9a-f]{40}', journal.get('revision') or '')
            or not re.fullmatch(r'[0-9a-f]{32}', journal.get('release_id') or '')
            or prepared.get('revision') != journal.get('outbound_artifact_revision', journal['revision'])
            or prepared.get('release_id') != journal['release_id']
            or not confirmed_schedule(prepared.get('_baseline'))):
        raise RuntimeError('Outbound completion context does not match release')
    observation = prepared.get('receipt')
    if (not isinstance(observation, dict) or observation.get('mode') not in {'legacy','outbound-worker-v1'}
            or not isinstance(observation.get('database_fingerprint'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', observation['database_fingerprint'])
            or prepared.get('_mode_floor', observation['mode']) not in {'legacy','outbound-worker-v1'}):
        raise RuntimeError('Outbound completion observation is missing')
    options = dict(coordinated=True, revision=prepared['revision'], release_id=prepared['release_id'],
                   database_fingerprint=observation.get('database_fingerprint'),
                   mode=('outbound-worker-v1' if 'outbound-worker-v1' in {observation['mode'], prepared.get('_mode_floor')}
                         else 'legacy'), baseline=prepared['_baseline'])
    recorded = journal.get('outbound')
    action = {'enabled':'activate','verified':'verify'}.get(recorded.get('status') if isinstance(recorded,dict) else None)
    if action is None:
        raise RuntimeError('Outbound activation receipt is missing for completion')
    validate_receipt(recorded, action, prepared['files'], **options)
    checked = phase(prepared, 'verify')
    validate_receipt(checked, 'verify', prepared['files'], **options)
    return checked


def _completion_context(source, journal):
    """Restore only a previously confirmed candidate identity, then verify the live target."""
    if (not isinstance(journal, dict)
            or not re.fullmatch(r'[0-9a-f]{40}', journal.get('revision') or '')
            or not re.fullmatch(r'[0-9a-f]{32}', journal.get('release_id') or '')):
        raise RuntimeError('Outbound completion context does not match release')
    revision = journal.get('outbound_artifact_revision', journal['revision'])
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('Outbound candidate identity cannot be confirmed')
    recorded = journal.get('outbound')
    action = {'enabled':'activate','verified':'verify'}.get(recorded.get('status') if isinstance(recorded,dict) else None)
    if action is None:
        raise RuntimeError('Outbound activation receipt is missing for completion')
    files = artifact(Path(source)/'deploy')
    validate_receipt(recorded, action, files, coordinated=True, revision=revision,
                     release_id=journal['release_id'])
    prepared = prepare(source, revision, journal['release_id'])
    observed = prepared['receipt']
    if (observed['database_fingerprint'] != recorded['database_fingerprint']
            or (recorded['mode']=='outbound-worker-v1' and observed['mode']!=recorded['mode'])):
        raise RuntimeError('Outbound completion target or mode changed')
    prepared['_baseline']=dict(recorded['baseline'])
    prepared['_mode_floor']='outbound-worker-v1' if 'outbound-worker-v1' in {recorded['mode'],observed['mode']} else 'legacy'
    return prepared


def pause_registered():
    """Pause only the trusted registered timer; no candidate install, mode or provider write."""
    try:
        root=Path(__file__).resolve().parent
        writer=registered_writer('ark-okki-outbound-poller',root)
        result=remote_python(writer['host'],root/'okki_outbound_remote.py',{'action':'pause'},sudo=True)
        if result.returncode:raise ValueError('Remote pause failed')
        receipt=json.loads(result.stdout)
        if (not isinstance(receipt,dict) or receipt.get('status')!='paused'
                or receipt.get('target')!='/root/.openclaw/workspace/okki-sync'
                or not confirmed_schedule(receipt.get('schedule'))
                or receipt['schedule']!={'active':False,'enabled':False}
                or not confirmed_schedule(receipt.get('target_schedule'))
                or receipt['target_schedule']!=receipt['schedule']
                or receipt.get('release_confirmed') is not False
                or receipt.get('service_drain_confirmed') is not False):
            raise ValueError('Invalid pause receipt')
    except Exception:
        raise RuntimeError('Outbound pause cannot be confirmed; inspect the registered timer') from None
    return receipt


def verify_completion(prepared, journal):
    try:return _verify_completion(prepared,journal)
    except Exception:
        pause_registered()
        raise


def completion_context(source, journal):
    try:return _completion_context(source,journal)
    except Exception:
        pause_registered()
        raise
