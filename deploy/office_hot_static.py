"""Static-only publication without removing a live directory or stopping the API."""
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from static_retention import atomic_json, no_links, sha, verify, walk_files


def tree(root):
    return {p.relative_to(root).as_posix(): sha(p) for p, _ in walk_files(root)}


def check_pending(state):
    path = Path(state) / 'office-static-switch.json'
    no_links(path)
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('status') not in {'succeeded', 'rolled_back'}:
        raise RuntimeError('Unfinished static switch requires inspection')


def eligible(changes):
    for _, destination, staged, files in changes:
        verify(staged, files)
        current = tree(destination)
        if 'index.html' not in current:
            return False  # The running application has not mounted this root yet.
        if any(name.endswith('.html') and name not in current for name in files):
            return False
        # Existing non-versioned JS/CSS/config must not change under old pages.
        if any(name in current and current[name] != digest and not name.endswith('.html')
               for name, digest in files.items()):
            return False
        if any(name not in files and not name.startswith('assets/') for name in current):
            return False
    return bool(changes)


def copy_atomic(source, destination):
    no_links(source); no_links(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name('.ark-static-' + uuid.uuid4().hex)
    try:
        shutil.copyfile(source, temporary)
        for attempt in range(10):
            try:
                os.replace(temporary, destination)
                return
            except OSError as error:
                if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 9:
                    raise
                time.sleep(.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def publish(prepared, state, run, marker, wait_ready):
    """Caller owns publish/schema locks. Any uncertain attempt blocks hot retry."""
    state = Path(state)
    check_pending(state)
    journal_path = state / 'office-static-switch.json'
    wait_ready(prepared['port'], prepared['nssm'], ['CommissionSystem'])
    if not eligible(prepared['static']):
        raise RuntimeError('Static hot publication eligibility changed')
    rows = []
    for name, destination, staged, files in prepared['static']:
        old = tree(destination)
        backup = state / ('office-previous-' + name + '-' + str(time.time_ns()))
        shutil.copytree(destination, backup)
        verify(backup, old)
        if tree(destination) != old:
            raise RuntimeError('Live static files changed during backup')
        rows.append(dict(name=name, destination=str(destination), staged=str(staged),
                         backup=str(backup), old=old, files=files, marker=marker('office-' + name)))
    journal = dict(status='applying', revision=prepared['revision'], previous=prepared['previous'], rows=rows)
    old_success = state / 'office-success.json'
    previous_success = json.loads(old_success.read_text(encoding='utf-8')) if old_success.exists() else None
    journal['previous_success'] = previous_success
    atomic_json(journal_path, journal)
    try:
        for row in rows:
            verify(Path(row['staged']), row['files'])
            verify(Path(row['backup']), row['old'])
            if tree(Path(row['destination'])) != row['old']:
                raise RuntimeError('Live static files changed before publication')
        # Prepare resources for every entrypoint before exposing ANY new HTML.
        for html in (False, True):
            for row in rows:
                destination, staged = Path(row['destination']), Path(row['staged'])
                for name, digest in row['files'].items():
                    if name.endswith('.html') == html and row['old'].get(name) != digest:
                        if sha(staged / name) != digest:
                            raise RuntimeError('Staged static content changed')
                        copy_atomic(staged / name, destination / name)
        for row in rows:
            verify(Path(row['destination']), row['files'])
        run(['git', 'merge', '--ff-only', prepared['revision']], cwd=prepared['live'])
        wait_ready(prepared['port'], prepared['nssm'], ['CommissionSystem'])
        for row in rows:
            if row['name'] == 'frontend':
                from office_static_retention import record_backup
                record_backup(state, Path(row['backup']), row['marker']['files'])
            atomic_json(state / ('office-' + row['name'] + '.json'), {'files': row['files']})
        atomic_json(state / 'office-success.json', dict(revision=prepared['revision'],
            previous=prepared['previous'], schema=prepared['schema'], status='static_updated',
            backups=[[row['destination'], row['backup']] for row in rows]))
        journal['status'] = 'succeeded'
        atomic_json(journal_path, journal)
    except Exception:
        # Keep newly served immutable assets for clients that saw the new entry.
        # No directory rename, service stop, or deletion even during rollback.
        for row in rows:
            verify(Path(row['backup']), row['old'])
        for html in (False, True):
            for row in rows:
                for name, digest in row['old'].items():
                    if name.endswith('.html') == html:
                        destination = Path(row['destination']) / name
                        if not destination.exists() or sha(destination) != digest:
                            copy_atomic(Path(row['backup']) / name, destination)
        for row in rows:
            verify(Path(row['destination']), row['old'])
        run(['git', 'reset', '--keep', prepared['previous']], cwd=prepared['live'])
        for row in rows:
            atomic_json(state / ('office-' + row['name'] + '.json'), row['marker'])
        if previous_success is not None:
            atomic_json(old_success, previous_success)
        else:
            old_success.unlink(missing_ok=True)
        journal['status'] = 'rolled_back'
        atomic_json(journal_path, journal)
        raise
    return {'status': 'static_updated', 'revision': prepared['revision']}
