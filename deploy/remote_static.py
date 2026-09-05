"""Verified, differential static releases; executed on Linux over SSH."""

from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import uuid

ROOTS = {
    "/var/www/ark/dist", "/var/www/ark-dist", "/var/www/pm/dist",
    "/var/www/pm-dist", "/var/www/hair-styles", "/var/www/video.leshine.work",
    "/var/www/video-styles", "/var/www/ark-static/customer-media",
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(name):
    path = PurePosixPath(name)
    if (not name or str(path) != name or path.is_absolute() or ".." in path.parts
            or "\\" in name or any(part.startswith(".") for part in path.parts)
            or name == "release.json"):
        raise ValueError("Unsafe artifact path")
    return path


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or "index.html" not in manifest:
        raise ValueError("Static artifact must include index.html")
    for name, digest in manifest.items():
        safe_relative(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid artifact digest")


def artifact_id(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def no_links(path):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("Unexpected symlink: " + str(item))


def matching(base, name, digest):
    path = base / name
    no_links(path)
    return path.is_file() and sha(path) == digest


def layout(root):
    state = root.parent / ("." + root.name + "-releases")
    no_links(state)
    no_links(state / "versions")
    current = state / "current"
    if current.is_symlink():
        target = Path(os.readlink(current))
        if target.parent != state / "versions" or not re.fullmatch(r"[0-9a-f]{64}", target.name):
            raise ValueError("Release pointer escaped state directory")
        no_links(target)
        if not target.is_dir():
            raise ValueError("Broken release pointer")
    elif current.exists():
        raise ValueError("Current must be a managed symlink")
    else:
        target = root
    if root.is_symlink():
        if os.readlink(root) != str(current) or not current.exists():
            raise ValueError("Root is not a managed release pointer")
    else:
        no_links(root)
    return state, current, target


def plan(root, manifest):
    validate_manifest(manifest)
    _, current, base = layout(root)
    active = current.resolve().name if current.exists() else None
    return {"missing": [n for n, h in manifest.items() if not matching(base, n, h)],
            "artifact": artifact_id(manifest), "active_artifact": active,
            "initialized": root.is_symlink()}


def retain_assets(base, candidate):
    assets = base / "assets"
    no_links(assets)
    if not assets.exists():
        return
    for old in assets.rglob("*"):
        no_links(old)
        if old.is_file():
            destination = candidate / old.relative_to(base)
            no_links(destination)
            if destination.exists():
                if sha(old) != sha(destination):
                    raise ValueError("Asset name reused with different bytes: " + old.name)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, destination)
                destination.chmod(0o644)


def stage(root, manifest, archive):
    validate_manifest(manifest)
    state, _, base = layout(root)
    ident = artifact_id(manifest)
    candidate = state / "versions" / ident
    no_links(candidate)
    if candidate.exists():
        if not all(matching(candidate, n, h) for n, h in manifest.items()):
            raise ValueError("Existing release is corrupt")
        # Also on rollback A->B->A: append B's chunks before serving A again.
        retain_assets(base, candidate)
        return {"artifact": ident}
    candidate.parent.mkdir(parents=True, exist_ok=True)
    state.chmod(0o755)
    candidate.parent.chmod(0o755)
    incoming = state / ("incoming-" + uuid.uuid4().hex)
    incoming.mkdir(mode=0o755)
    seen = set()
    no_links(archive)
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            safe_relative(member.name)
            if not member.isfile() or member.name not in manifest or member.name in seen:
                raise ValueError("Unexpected/duplicate bundle member")
            seen.add(member.name)
            destination = incoming / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out)
            if sha(destination) != manifest[member.name]:
                raise ValueError("Transfer checksum mismatch: " + member.name)
    for name, digest in manifest.items():
        if not matching(incoming, name, digest):
            if not matching(base, name, digest):
                raise ValueError("Missing/corrupt file: " + name)
            (incoming / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / name, incoming / name)
    retain_assets(base, incoming)
    (incoming / "release.json").write_text(json.dumps({"artifact": ident, "files": manifest}, sort_keys=True))
    for path in [incoming, *incoming.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    incoming.rename(candidate)
    return {"artifact": ident}


def pointer(path, target):
    temporary = path.parent / (path.name + ".next-" + uuid.uuid4().hex)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, path)


def exchange(left, right):
    # Linux renameat2 swaps the original directory and prepared symlink atomically.
    libc = ctypes.CDLL(None, use_errno=True)
    operation = libc.renameat2
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    if operation(-100, os.fsencode(left), -100, os.fsencode(right), 2):
        raise OSError(ctypes.get_errno(), "Atomic root exchange failed")


def verify_http(manifest, host):
    if not re.fullmatch(r"(?:[a-z-]+\.)?leshine\.(?:cloud|work)", host):
        raise ValueError("Unregistered verification host")
    content = subprocess.check_output(["curl", "--fail", "--silent", "--show-error",
        "--max-time", "30", "--resolve", host + ":443:127.0.0.1",
        "https://" + host + "/index.html"], timeout=40)
    if hashlib.sha256(content).hexdigest() != manifest["index.html"]:
        raise RuntimeError("Nginx is not serving the selected artifact for " + host)


def activate(root, manifest, expected, host=None):
    validate_manifest(manifest)
    state, current, base = layout(root)
    candidate = state / "versions" / artifact_id(manifest)
    no_links(candidate)
    active = current.resolve().name if current.exists() else None
    if active != expected and active != candidate.name:
        raise ValueError("Another publisher changed this target after preparation")
    if not all(matching(candidate, n, h) for n, h in manifest.items()):
        raise ValueError("Release verification failed before activation")
    if active == candidate.name and root.is_symlink():
        if host:
            verify_http(manifest, host)
        return {"status": "unchanged", "artifact": active}
    retain_assets(base, candidate)
    if active:
        pointer(state / "previous", base)
    pointer(current, candidate)
    legacy = None
    initialized = root.is_symlink()
    if not initialized:
        swap = root.parent / ("." + root.name + "-switch-" + uuid.uuid4().hex)
        swap.symlink_to(current, target_is_directory=True)
        try:
            if root.exists():
                exchange(root, swap)
                legacy = state / ("legacy-" + uuid.uuid4().hex)
                swap.rename(legacy)
            else:
                os.replace(swap, root)
        except Exception:
            if swap.is_symlink():
                swap.unlink()
                if active:
                    pointer(current, base)
                else:
                    current.unlink()
            raise
    try:
        if host:
            verify_http(manifest, host)
    except Exception:
        if active:
            pointer(current, base)
        elif legacy:
            exchange(root, legacy)
            legacy.unlink()
            current.unlink()
        else:
            root.unlink()
            current.unlink()
        raise
    return {"status": "updated", "artifact": candidate.name}


@contextmanager
def locked(root):
    import fcntl
    state, _, _ = layout(root)
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o755)
    lock = state / "publish.lock"
    no_links(lock)
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    request = json.load(sys.stdin)
    root = Path(request["root"])
    if str(root) not in ROOTS:
        raise ValueError("Unregistered static root")
    with locked(root):
        action = request["action"]
        if action == "plan":
            result = plan(root, request["manifest"])
        elif action == "stage":
            archive = Path(request["archive"])
            if not re.fullmatch(r"/tmp/ark-static-[0-9a-f]{64}\.tar\.gz", str(archive)):
                raise ValueError("Unregistered transfer archive")
            result = stage(root, request["manifest"], archive)
        elif action == "activate":
            result = activate(root, request["manifest"], request["expected"], request["host"])
        else:
            raise ValueError("Unknown static action")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
