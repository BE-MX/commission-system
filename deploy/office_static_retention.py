"""Bounded office main-frontend backups; never touches uploads or other components."""

import json
from pathlib import Path
import re
import time

import static_retention as retention
from static_sync import manifest

BACKUP = re.compile(r'office-previous-frontend-(\d+)')
BUILD = re.compile(r'frontend-[0-9a-f]{64}')


def record_backup(state, backup, files):
    match = BACKUP.fullmatch(backup.name)
    if not match or backup.parent != state:
        raise ValueError('Unregistered frontend backup')
    retention.validate_manifest(files)
    path = state / 'office-frontend-history.json'
    history = retention.read_history(path)
    history['releases'][backup.name] = {'files': files,
                                       'retired_at': int(match[1]) / 1_000_000_000}
    retention.atomic_json(path, history)


def legacy_manifest(backup, state):
    """Find the original build, not the cumulative backup directory contents."""
    index = retention.sha(backup / 'index.html')
    matches = []
    for folder in (state / 'builds').iterdir():
        if not BUILD.fullmatch(folder.name):
            continue
        retention.no_links(folder)
        if (folder / 'index.html').is_file() and retention.sha(folder / 'index.html') == index:
            files = manifest(folder)
            retention.validate_manifest(files)
            matches.append(files)
    if not matches or any(files != matches[0] for files in matches[1:]):
        raise ValueError('Cannot reconstruct unique legacy build: ' + backup.name)
    retention.verify(backup, matches[0])
    return matches[0]


def cleanup(live, prepare_only=False):
    live = Path(live).resolve()
    state = live / '.deploy_state'
    current = live / 'frontend/dist'
    retention.no_links(state)
    retention.no_links(current)
    marker_path = state / 'office-frontend.json'
    retention.no_links(marker_path)
    files = json.loads(marker_path.read_text(encoding='utf-8'))['files']
    retention.verify(current, files)
    now = time.time()
    history_path = state / 'office-frontend-history.json'
    history = retention.read_history(history_path)
    rows = history['releases']
    for name, row in rows.items():
        match = BACKUP.fullmatch(name)
        if not match or row['retired_at'] != int(match[1]) / 1_000_000_000:
            raise ValueError('Invalid office retirement history')
    backups = []
    for folder in state.iterdir():
        match = BACKUP.fullmatch(folder.name)
        if not match:
            continue
        retention.no_links(folder)
        if not folder.is_dir():
            raise ValueError('Backup is not a directory')
        backups.append((int(match[1]) / 1_000_000_000, folder))
    backups.sort(reverse=True)
    kept_paths = [folder for _, folder in backups[:retention.ROLLBACK_COUNT]]
    success = state / 'office-success.json'
    if success.exists():
        retention.no_links(success)
        for destination, name in json.loads(success.read_text(encoding='utf-8')).get('backups', []):
            if Path(destination).resolve() != current:
                continue
            folder = Path(name)
            if folder.parent != state or not BACKUP.fullmatch(folder.name) or not folder.is_dir():
                raise ValueError('Office recovery backup escaped state or is missing')
            if folder not in kept_paths:
                kept_paths.append(folder)
    for retired, folder in backups:
        if folder in kept_paths or retired >= now - retention.GRACE_SECONDS:
            if folder.name not in rows:
                rows[folder.name] = {'files': legacy_manifest(folder, state), 'retired_at': retired}
            elif rows[folder.name]['retired_at'] != retired:
                raise ValueError('Backup retirement record differs from directory identity')
    grace = [row['files'] for row in rows.values()
             if row['retired_at'] >= now - retention.GRACE_SECONDS]
    kept = [(current, files)] + [(folder, rows[folder.name]['files']) for folder in kept_paths]
    assets = retention.asset_union([own for _, own in kept] + grace)
    removed = [folder for _, folder in backups if folder not in kept_paths]
    plan = retention.plan_cleanup(kept, removed, assets)
    result = retention.summary(plan) | {'backup_count_before': len(backups),
                                        'backup_count_after': len(kept_paths),
                                        'rollback_artifacts': [retention.artifact_id(own) for _, own in kept[1:]]}
    if not prepare_only:
        retention.atomic_json(history_path, history)
        receipt = state / 'office-frontend-retention.json'
        retention.atomic_json(receipt, {'status': 'cleaning', **result})
        retention.apply_cleanup(plan, [state, current / 'assets'])
        for folder, own in kept:
            retention.verify(folder, own)
        # Grace manifests outlive deleted backups; expired rows no longer grow.
        history['releases'] = {name: row for name, row in rows.items()
                               if state / name in kept_paths
                               or row['retired_at'] >= now - retention.GRACE_SECONDS}
        retention.atomic_json(history_path, history)
        retention.atomic_json(receipt, {'status': 'succeeded', **result})
    return result
