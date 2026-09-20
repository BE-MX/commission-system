"""OS locks release on process death; path leases live as long as their reader."""
from contextlib import contextmanager
import os
from pathlib import Path
from uuid import uuid4
import weakref


def lock(stream, *, blocking=True):
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


@contextmanager
def process_lock(cache):
    with (cache / '.cache.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        lock(stream)
        yield


def _release(stream):
    # Closing is sufficient. Stale marker removal is serialized by process_lock.
    stream.close()


class LeasedPath(type(Path())):
    """Keep this Path alive until processing/response completes; do not stringify."""

    def open(self, *args, **kwargs):
        stream = super().open(*args, **kwargs)
        stream._storage_lease_owner = self
        return stream


def lease(path):
    pinned(path)  # Reap released markers on hot cache hits, not only eviction.
    directory = path.parent / '.leases' / path.name
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / uuid4().hex).open('x+b')
    stream.write(b'0')
    stream.flush()
    lock(stream)
    result = LeasedPath(path)
    result._lease_finalizer = weakref.finalize(result, _release, stream)
    return result


def pinned(path):
    directory = path.parent / '.leases' / path.name
    if not directory.exists():
        return False
    active = False
    for marker in directory.iterdir():
        with marker.open('r+b') as stream:
            try:
                lock(stream, blocking=False)
            except (BlockingIOError, OSError):
                active = True
                continue
        marker.unlink()
    if not active:
        directory.rmdir()
    return active
