"""Journalled Singapore-only TeamRouter route operations."""
import json
import os
from pathlib import Path
import re

from static_sync import remote_python

HERE = Path(__file__).resolve().parent
TARGET = 'root@119.28.107.92'
ERROR_TYPES = {'RuntimeError', 'ValueError', 'PermissionError', 'FileNotFoundError',
               'TimeoutExpired', 'CalledProcessError', 'OSError', 'JSONDecodeError'}
ERROR_STAGES = {'validation', 'prepare', 'syntax_check', 'save_prepared_state',
                'validate_prepared_state', 'switch_configuration', 'nginx_validate',
                'nginx_reload', 'health_probe', 'restore_previous_configuration'}


def validate_args(args):
    if any(value for key, value in vars(args).items() if key != 'teamrouter_chat_route'):
        raise RuntimeError('TeamRouter route accepts only --teamrouter-chat-route')


def _validate(result):
    if not isinstance(result, dict) or any(
        not isinstance(result.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', result[key])
        for key in ('baseline', 'candidate')
    ):
        raise RuntimeError('Invalid TeamRouter route receipt')


def execute(action):
    import publish

    if action not in {'prepare', 'activate', 'rollback'}:
        raise ValueError('Unknown TeamRouter route action')
    record = publish.STATE / 'teamrouter-chat-route.json'
    journal = json.loads(record.read_text(encoding='utf8')) if record.exists() else None
    previous_prepared = journal if action == 'prepare' and journal and journal.get('status') == 'prepared' else None
    if action == 'prepare':
        # Never replace evidence while the preceding operation may own live routing.
        if journal and not previous_prepared and journal.get('status') != 'rolled_back' and not (
            journal.get('status') in {'prepare_pending', 'prepare_failed'}
            and 'baseline' not in journal and 'candidate' not in journal
        ):
            raise RuntimeError('Existing TeamRouter receipt requires activation or rollback before preparing again')
        verifier = os.environ.get('ARK_TEAMROUTER_CHAT_VERIFIER', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{22}', verifier):
            raise RuntimeError('ARK_TEAMROUTER_CHAT_VERIFIER must contain 22 base64url characters')
        if previous_prepared:
            _validate(previous_prepared)
            if previous_prepared.get('target') != TARGET or previous_prepared.get('verifier') != verifier:
                raise RuntimeError('Repreparation requires the same Singapore target and verifier')
        previous = journal
        journal = {'target': TARGET, 'verifier': verifier, 'status': 'preparing', 'history': []}
        if previous:
            journal['previous'] = previous
        if previous_prepared:
            # A process interruption must retain the owned baseline and prevent
            # a fresh preparation from silently treating this as a new route.
            journal.update({key: previous_prepared[key] for key in ('baseline', 'candidate')})
    else:
        if not journal or journal.get('target') != TARGET:
            raise RuntimeError('A prepared Singapore TeamRouter receipt is required')
        _validate(journal)
        if not isinstance(journal.get('history'), list):
            raise RuntimeError('Invalid TeamRouter operation history')
        if not re.fullmatch(r'[A-Za-z0-9_-]{22}', journal.get('verifier', '')):
            raise RuntimeError('Invalid TeamRouter verifier receipt')
        if action == 'activate' and journal.get('status') not in {'prepared', 'activate_failed'}:
            raise RuntimeError('TeamRouter activation requires a prepared receipt')
    request = {'action': action, 'verifier': journal['verifier'],
               'template': (HERE / 'nginx' / 'teamrouter-chat.conf').read_text(encoding='utf8')}
    if action != 'prepare':
        request.update({key: journal[key] for key in ('baseline', 'candidate')})
    elif previous_prepared:
        request['expected_baseline'] = previous_prepared['baseline']
    journal['status'] = action + '_pending'
    publish.atomic_json(record, journal)
    try:
        response = remote_python(TARGET, HERE / 'teamrouter_chat_remote.py', request, sudo=True)
        if response.returncode:
            try:
                failure = json.loads(response.stdout)
            except (ValueError, AttributeError):
                failure = {}
            if isinstance(failure, dict):
                journal['remote_error'] = {key: failure[key] for key, allowed in (
                    ('error_type', ERROR_TYPES), ('stage', ERROR_STAGES)
                ) if isinstance(failure.get(key), str) and failure[key] in allowed}
            detail = ', '.join(f'{key}={value}' for key, value in journal.get('remote_error', {}).items())
            raise RuntimeError('Remote TeamRouter route operation failed'
                               + (f' ({detail})' if detail else '')
                               + '; inspect protected server evidence')
        result = json.loads(response.stdout)
        _validate(result)
        expected_status = {'prepare': 'prepared', 'activate': 'activated', 'rollback': 'rolled_back'}[action]
        if result.get('status') != expected_status:
            raise RuntimeError('TeamRouter remote operation did not confirm success')
        if previous_prepared and result['baseline'] != previous_prepared['baseline']:
            raise RuntimeError('TeamRouter live baseline differs from the preceding preparation')
        if action != 'prepare' and any(result[key] != journal[key] for key in ('baseline', 'candidate')):
            raise RuntimeError('TeamRouter remote receipt differs from prepared baseline')
        if action == 'prepare':
            journal.update({key: result[key] for key in ('baseline', 'candidate')})
        journal['history'].append({'action': action, 'result': result})
        journal['status'] = expected_status
        publish.atomic_json(record, journal)
    except Exception as exc:
        if previous_prepared:
            previous_prepared['reprepare_error'] = {
                'error_type': type(exc).__name__,
                **journal.get('remote_error', {}),
            }
            publish.atomic_json(record, previous_prepared)
            raise
        journal['status'] = action + '_failed'
        journal['error_type'] = type(exc).__name__
        publish.atomic_json(record, journal)
        raise
    print(json.dumps({'target': TARGET, 'status': journal['status']}), flush=True)
