"""Bounded Windows npm snapshots, restored as private candidate files, never links."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import time
import uuid
import zipfile

from static_retention import atomic_json, no_links, sha, walk_files

MAX_BYTES = 2 * 1024**3
MAX_ARCHIVE = 512 * 1024**2
MAX_FILES = 100_000
KEEP = 3
KEY = re.compile(r'[0-9a-f]{64}')


def fingerprint(folder, npm, run):
    """Only registered Windows Vite clients with reviewed lifecycle hooks qualify."""
    if os.name != 'nt' or folder.name not in {'frontend', 'frontend-pm'}:
        return None
    package = json.loads((folder / 'package.json').read_text(encoding='utf-8'))
    lock = json.loads((folder / 'package-lock.json').read_text(encoding='utf-8'))
    if package.get('workspaces') or any(k in package.get('scripts', {}) for k in
            ('preinstall', 'install', 'postinstall', 'prepublish', 'preprepare', 'prepare', 'postprepare')):
        return None
    for name, row in lock.get('packages', {}).items():
        if row.get('link') or str(row.get('resolved', '')).startswith(('file:', 'git', 'workspace:')):
            return None
        if row.get('hasInstallScript') and name not in {'node_modules/esbuild', 'node_modules/fsevents'}:
            return None
    if not lock.get('packages') or lock.get('lockfileVersion') not in {2, 3}:
        return None
    # Effective npm settings include user/global/project configuration and env
    # overrides. Hash them in memory; credentials/config values never enter the
    # cache receipt. Paths naming the candidate/config source are not settings.
    config = json.loads(run([npm, 'config', 'list', '--json'], cwd=folder, capture=True))
    for key in ('local-prefix', 'userconfig', 'globalconfig'):
        config.pop(key, None)
    # install-links=false is npm's normal default; local/link dependencies were
    # already excluded above. Keep its value in the key instead of disabling
    # all ordinary registry-only dependency snapshots.
    if config.get('global'):
        return None
    external = ('ESBUILD_BINARY_PATH', 'NODE_PATH', 'NODE_OPTIONS')
    if any(os.environ.get(key) for key in external):
        return None
    inputs = {'schema': 1, 'package': package, 'lock': lock, 'config': config,
              'node': run(['node', '-p', 'JSON.stringify([process.version,process.platform,process.arch,process.versions.modules])'], capture=True),
              'npm': run([npm, '--version'], capture=True), 'platform': platform.platform(),
              'machine': platform.machine(), 'node_env': os.environ.get('NODE_ENV'),
              'ci': os.environ.get('CI')}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def paths(state, component, key):
    if component not in {'frontend', 'frontend-pm'} or not KEY.fullmatch(key):
        raise ValueError('Unknown dependency cache identity')
    root = state / 'npm-cache' / component
    no_links(root)
    return root, root / (key + '.zip'), root / (key + '.json')


def entry_name(name):
    path = PurePosixPath(name)
    if not name or str(path) != name or path.is_absolute() or any(
            part in {'', '.', '..'} or ':' in part or '\\' in part or part.endswith((' ', '.'))
            or re.fullmatch(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', part)
            for part in path.parts):
        raise ValueError('Unsafe dependency archive path')
    return path


def restore(folder, state, key):
    _, archive, receipt = paths(state, folder.name, key)
    destination = folder / 'node_modules'
    no_links(destination)
    if destination.exists():
        return False
    no_links(archive)
    no_links(receipt)
    if not archive.exists() and not receipt.exists():
        return False
    if not archive.is_file() or not receipt.is_file():
        raise ValueError('Incomplete dependency cache')
    record = json.loads(receipt.read_text(encoding='utf-8'))
    if record.get('key') != key or record.get('schema') != 1 or sha(archive) != record.get('sha256'):
        raise ValueError('Corrupt dependency cache')
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Oversized dependency cache')
    temporary = folder / ('node_modules.restore-' + uuid.uuid4().hex)
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            seen, directories, size = set(), {}, 0
            if len(members) > MAX_FILES:
                raise ValueError('Too many dependency cache files')
            for member in members:
                name = str(entry_name(member.filename)).casefold()
                mode = member.external_attr >> 16
                if name in seen or member.is_dir() or (stat.S_IFMT(mode) not in {0, stat.S_IFREG}):
                    raise ValueError('Duplicate or linked dependency entry')
                seen.add(name)
                for parent in PurePosixPath(member.filename).parents:
                    if str(parent) == '.':
                        continue
                    folded = str(parent).casefold()
                    if folded in directories and directories[folded] != str(parent):
                        raise ValueError('Ambiguous dependency directory case')
                    directories[folded] = str(parent)
                size += member.file_size
            if not seen or size > MAX_BYTES or size != record.get('bytes') or len(seen) != record.get('files'):
                raise ValueError('Dependency cache inventory mismatch')
            if any(str(parent).casefold() in seen for name in seen for parent in PurePosixPath(name).parents if str(parent) != '.'):
                raise ValueError('Dependency archive file/directory collision')
            temporary.mkdir()
            for name in sorted(directories.values(), key=lambda value: (len(PurePosixPath(value).parts), value)):
                (temporary / name).mkdir()
            for member in members:
                target = temporary / member.filename
                with bundle.open(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
        no_links(destination)
        if destination.exists():
            raise ValueError('Dependency destination changed during restore')
        install_tree(temporary, destination)
    finally:
        # Only the newly allocated sibling temp directory is ours to retire.
        if temporary.exists():
            no_links(temporary)
            if temporary.resolve().parent != folder.resolve():
                raise ValueError('Dependency restore escaped candidate')
            shutil.rmtree(temporary)
    return True


def install_tree(temporary, destination):
    # Windows scanners can briefly hold newly extracted files. Retry only after
    # proving rename did not take effect; a changed/ambiguous destination stops.
    for delay in (0.1, 0.2, 0.5, 1, 2, None):
        no_links(temporary)
        no_links(destination)
        if not temporary.is_dir() or destination.exists():
            raise ValueError('Dependency destination changed during restore')
        try:
            temporary.rename(destination)
            return
        except PermissionError:
            if delay is None or not temporary.is_dir() or destination.exists():
                raise
            time.sleep(delay)


def store(folder, state, key):
    root, archive, receipt = paths(state, folder.name, key)
    if archive.exists() or receipt.exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / (key + '.next-' + uuid.uuid4().hex)
    size, count = 0, 0
    installed, committed = False, False
    try:
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for file, length in walk_files(folder / 'node_modules'):
                name = file.relative_to(folder / 'node_modules').as_posix()
                entry_name(name)
                size += length
                count += 1
                if size > MAX_BYTES or count > MAX_FILES:
                    raise ValueError('Dependency snapshot exceeds budget')
                bundle.write(file, name)
        if not count:
            raise ValueError('Empty dependency snapshot')
        if temporary.stat().st_size > MAX_ARCHIVE:
            raise ValueError('Dependency archive exceeds budget')
        digest = sha(temporary)
        temporary.rename(archive)
        installed = True
        atomic_json(receipt, {'schema': 1, 'key': key, 'sha256': digest, 'bytes': size, 'files': count})
        committed = True
        prune(root, key)
    finally:
        temporary.unlink(missing_ok=True)
        if installed and not committed:
            # These paths did not exist on entry and were created under the
            # publisher lock. A failed optional receipt write must not poison
            # every future candidate with an incomplete cache pair.
            for path in (archive, receipt):
                no_links(path)
                if path.resolve().parent != root.resolve():
                    raise ValueError('Dependency cache escaped root')
                path.unlink(missing_ok=True)


def prune(root, current):
    """Only paired, owned cache files; no directories, candidates or business data."""
    rows = []
    for receipt in root.glob('*.json'):
        if not KEY.fullmatch(receipt.stem):
            continue
        archive = receipt.with_suffix('.zip')
        no_links(receipt)
        no_links(archive)
        data = json.loads(receipt.read_text(encoding='utf-8'))
        if data.get('schema') == 1 and data.get('key') == receipt.stem and archive.is_file():
            rows.append((receipt.stat().st_mtime_ns, receipt, archive))
    others = sorted((row for row in rows if row[1].stem != current), reverse=True)
    for _, receipt, archive in others[KEEP - 1:]:
        for path in (archive, receipt):
            no_links(path)
            if path.resolve().parent != root.resolve():
                raise ValueError('Dependency cache escaped root')
            path.unlink()
