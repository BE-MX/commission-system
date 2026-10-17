"""Success-only, bounded retirement of explicitly owned office candidates.

Legacy directories without creation receipts are never adopted automatically.
Epoch seconds are protocol values; durations use the monotonic clock.
"""

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import uuid

from candidate_references import metadata_references, runtime_references
from static_retention import atomic_json, no_links, walk_files

GRACE_SECONDS = 7 * 86400
MAX_REMOVALS = 8
BUDGET_SECONDS = 60
SOURCE = re.compile(r'[0-9a-f]{40}')
STATIC = re.compile(r'office-next-(frontend|frontend-pm|pm-lan)-[0-9]+')
DEPENDENCIES = {'frontend/node_modules', 'frontend-pm/node_modules', 'frontend-portal/node_modules',
                'extensions/whatsapp-translation/node_modules', 'services/whatsapp-connector/node_modules'}


def read(path, default=None):
    no_links(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def registry(state):
    data = read(state / 'candidate-retention/inventory.json', {'schema': 1, 'entries': {}, 'successes': []})
    if data.get('schema') != 1 or not isinstance(data.get('entries'), dict) or not isinstance(data.get('successes'), list):
        raise ValueError('Unknown candidate inventory')
    return data


def candidate_path(state, name, kind):
    if kind == 'source' and SOURCE.fullmatch(name):
        path = state / 'sources' / name
    elif kind == 'static' and STATIC.fullmatch(name):
        path = state / name
    else:
        raise ValueError('Unregistered candidate path')
    no_links(path)
    if path.resolve().parent != (state / 'sources' if kind == 'source' else state).resolve():
        raise ValueError('Candidate escaped its registered parent')
    return path


def record_created(state, path, revision, kind):
    """Called only for a freshly created candidate, never inferred from an old dir."""
    if not SOURCE.fullmatch(revision):
        raise ValueError('Candidate requires a full revision')
    expected = candidate_path(state, path.name, kind)
    if path != expected or not path.is_dir():
        raise ValueError('Candidate creation path mismatch')
    data = registry(state)
    if path.name in data['entries']:
        raise ValueError('Candidate creation receipt already exists')
    data['entries'][path.name] = {'kind': kind, 'revision': revision, 'created_at': time.time()}
    atomic_json(state / 'candidate-retention/inventory.json', data)


def git(live, *args, timeout=30):
    return subprocess.check_output(['git', *args], cwd=live, text=True, encoding='utf-8', timeout=timeout).strip()


def record_settings(state, source, settings):
    data = registry(state)
    row = data['entries'].get(source.name)
    if row and row['kind'] == 'source':
        row['settings'] = settings
        atomic_json(state / 'candidate-retention/inventory.json', data)


def record_success(state, revision, previous):
    """Record installed history before any fallible post-release maintenance."""
    if not SOURCE.fullmatch(revision) or not SOURCE.fullmatch(previous):
        raise ValueError('Installed history requires full revisions')
    data = registry(state)
    data['successes'] = list(dict.fromkeys([revision, previous, *data['successes']]))[:3]
    atomic_json(state / 'candidate-retention/inventory.json', data)


def source_safe(live, path, settings=None):
    records = git(live, 'worktree', 'list', '--porcelain').split('\n\n')
    own = [record.splitlines() for record in records
           if record.splitlines()[0] == 'worktree ' + path.as_posix()]
    if len(own) != 1 or 'detached' not in own[0] or any(line.startswith(('locked', 'prunable')) for line in own[0]):
        raise ValueError('Source is not an unlocked detached registered worktree')
    if 'HEAD ' + path.name not in own[0] or git(path, 'rev-parse', 'HEAD') != path.name:
        raise ValueError('Source identity changed')
    if git(live, 'merge-base', path.name, 'HEAD') != path.name:
        raise ValueError('Source has unmerged history')
    if git(path, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Source has local changes')
    ignored = git(path, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory').splitlines()
    settings = settings or {}
    for name, digest in settings.items():
        if not re.fullmatch(r'(?:frontend|frontend-pm|backend)/\.env(?:[.][a-zA-Z0-9_.-]+)?', name):
            raise ValueError('Invalid copied setting path')
        file = path / name
        no_links(file)
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError('Copied candidate settings changed')
    # Only reproducible dependencies/build output, caches and copied local settings.
    # Unknown ignored data (uploads, runtime state, local scripts) blocks retirement.
    for name in ignored:
        parts = Path(name.rstrip('/')).parts
        allowed = (name.rstrip('/') in DEPENDENCIES
                   or (parts[0] in {'backend', 'deploy', 'scripts'} and parts[-1] in {'__pycache__', '.pytest_cache'})
                   or name.rstrip('/') in {'frontend/dist', 'frontend-pm/dist', 'frontend-pm/dist-lan',
                                            'frontend-portal/dist', 'extensions/whatsapp-translation/dist',
                                            'extensions/whatsapp-translation/release',
                                            'frontend/public/downloads/whatsapp-translation'}
                   or name in settings)
        if not allowed:
            raise ValueError('Unknown ignored source data')
    return dependency_links(path)


def dependency_links(root):
    """Prevalidate the entire tree; only dependency links may be unlinked later."""
    links = []
    for directory, folders, names in os.walk(root, followlinks=False):
        for name in [*folders, *names]:
            path = Path(directory) / name
            observed = path.lstat()
            if stat.S_ISLNK(observed.st_mode) or getattr(observed, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                relative = path.relative_to(root).as_posix()
                if not any(relative == dep or relative.startswith(dep + '/') for dep in DEPENDENCIES):
                    raise ValueError('Unexpected link outside dependencies')
                links.append(path)
                if name in folders:
                    folders.remove(name)
            elif not (stat.S_ISDIR(observed.st_mode) or stat.S_ISREG(observed.st_mode)):
                raise ValueError('Unexpected source file type')
    return links


def unlink_dependencies(root, links):
    for path in links:
        # Check parents without resolving the link target. Native unlink/rmdir
        # removes only the link, never a recursively enumerated destination.
        no_links(path.parent)
        if not path.absolute().is_relative_to(root.absolute()):
            raise ValueError('Dependency link escaped candidate')
        observed = path.lstat()
        if stat.S_ISLNK(observed.st_mode):
            path.unlink()
        elif getattr(observed, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            path.rmdir()
        else:
            raise ValueError('Dependency link changed after validation')


def validate_static(path):
    for _ in walk_files(path):
        pass


def run(live, source, previous, *, now=None, probe=runtime_references, prepare_only=False):
    """Caller owns publish.lock. Refuse interrupted prior deletion until reviewed."""
    live, source = Path(live).absolute(), Path(source).absolute()
    state = live / '.deploy_state'
    no_links(state)
    if read_lock(state) != str(os.getpid()):
        raise RuntimeError('Candidate cleanup requires the owning publish lock')
    current = read(state / 'publish-current.json', {})
    if current.get('status') != 'succeeded' or current.get('scope') != 'office-and-cloud':
        raise RuntimeError('Candidate cleanup requires a successful full release')
    revision = current['revision']
    if git(live, 'rev-parse', 'HEAD') != revision:
        raise RuntimeError('Installed revision differs from successful release')
    root = state / 'candidate-retention'
    old = read(root / 'current.json', {})
    if old.get('status') in {'deleting', 'failed'} and not prepare_only:
        raise RuntimeError('Review interrupted candidate cleanup receipt before retrying')
    started, now = time.monotonic(), time.time() if now is None else now
    data = registry(state)
    # Newest current + two prior installed revisions; repeated publishes do not
    # consume rollback slots. Bootstrap also keeps the pre-feature predecessor.
    successes = [revision, previous, *data['successes']]
    data['successes'] = list(dict.fromkeys(value for value in successes if SOURCE.fullmatch(value)))[:3]
    if not prepare_only:
        atomic_json(root / 'inventory.json', data)
    protected = set(data['successes']) | {revision, source.name, Path(__file__).resolve().parents[1].name}
    eligible, skipped = [], []
    for name, row in data['entries'].items():
        path = candidate_path(state, name, row['kind'])
        if not path.exists():
            continue  # Activated static dirs were renamed into their serving path.
        if not SOURCE.fullmatch(row['revision']) or not isinstance(row['created_at'], (int, float)):
            raise ValueError('Invalid candidate creation receipt')
        if (row['kind'] == 'source' and row['revision'] in protected) or now - row['created_at'] < GRACE_SECONDS:
            continue
        eligible.append((row['created_at'], name, row))
    # Avoid expensive Windows runtime enumeration on the common no-work path.
    if eligible:
        protected |= metadata_references(state) | probe(live)
    receipt = {'schema': 1, 'run_id': uuid.uuid4().hex, 'revision': revision,
               'status': 'inspecting', 'started_at': now, 'removed': [], 'skipped': skipped,
               'planned': [],
               'max_removals': MAX_REMOVALS, 'budget_seconds': BUDGET_SECONDS}
    if not prepare_only:
        atomic_json(root / 'current.json', receipt)
    try:
        for _, name, row in sorted(eligible):
            if len(receipt['removed']) + len(receipt['planned']) >= MAX_REMOVALS or time.monotonic() - started >= BUDGET_SECONDS:
                receipt['budget_exhausted'] = True
                break
            if name in protected or (row['kind'] == 'source' and row['revision'] in protected):
                skipped.append({'name': name, 'reason': 'referenced'})
                continue
            path = candidate_path(state, name, row['kind'])
            try:
                links = []
                if row['kind'] == 'source':
                    links = source_safe(live, path, row.get('settings'))
                else:
                    validate_static(path)
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                skipped.append({'name': name, 'reason': str(error) if isinstance(error, ValueError) else type(error).__name__})
                continue
            # Fresh path/ref check after potentially slow tree validation. A failed
            # inspection stops cleanup; it never becomes an empty reference set.
            fresh = metadata_references(state) | probe(live)
            if name in fresh or (row['kind'] == 'source' and row['revision'] in fresh):
                skipped.append({'name': name, 'reason': 'new-reference'})
                continue
            candidate_path(state, name, row['kind'])
            if prepare_only:
                receipt['planned'].append(name)
                continue
            receipt.update(status='deleting', intent=name)
            atomic_json(root / 'current.json', receipt)
            if row['kind'] == 'source':
                unlink_dependencies(path, links)
                git(live, 'worktree', 'remove', '--force', str(path), timeout=120)
            else:
                shutil.rmtree(path)
            if path.exists():
                raise RuntimeError('Candidate removal not verified')
            if row['kind'] == 'source' and str(path.as_posix()) in git(live, 'worktree', 'list', '--porcelain'):
                raise RuntimeError('Removed worktree is still registered')
            receipt['removed'].append(name)
            receipt.update(status='inspecting', intent=None)
            del data['entries'][name]
            atomic_json(root / 'inventory.json', data)
            atomic_json(root / 'current.json', receipt)
        # Forget consumed stage receipts; preserve unknown legacy dirs and failures.
        data['entries'] = {name: row for name, row in data['entries'].items()
                           if candidate_path(state, name, row['kind']).exists()}
        if not prepare_only:
            atomic_json(root / 'inventory.json', data)
        receipt.update(status='prepared' if prepare_only else 'succeeded', elapsed_seconds=round(time.monotonic() - started, 3),
                       remaining_managed=len(data['entries']), skipped_count=len(skipped))
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__)
        if not prepare_only:
            atomic_json(root / 'current.json', receipt)
        raise
    if not prepare_only:
        atomic_json(root / 'current.json', receipt)
        atomic_json(root / (receipt['run_id'] + '.json'), receipt)
    return receipt


def read_lock(state):
    path = state / 'publish.lock'
    no_links(path)
    return path.read_text(encoding='utf-8').strip() if path.exists() else None


def execute(args, live, source, deployment_lock):
    allowed = {'candidate_retention_only', 'prepare_only', 'revision', 'live_root', 'no_pull'}
    if any(value for key, value in vars(args).items() if key not in allowed):
        raise RuntimeError('Candidate retention only accepts a pinned controller and --prepare-only')
    if args.revision != git(source, 'rev-parse', 'HEAD') or git(source, 'status', '--porcelain'):
        raise RuntimeError('Candidate retention requires a clean pinned controller')
    with deployment_lock():
        from schema_release import check_recovery
        check_recovery(Path(live) / '.deploy_state/schema-writers.json')
        history = registry(Path(live) / '.deploy_state')['successes']
        current = git(live, 'rev-parse', 'HEAD')
        older = history[1:] if history and history[0] == current else history
        previous = older[0] if older else current
        return run(live, source, previous, prepare_only=args.prepare_only)
