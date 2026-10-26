"""Bounded process-local JPEG cache. Call only between fresh authorization checks."""
from collections import OrderedDict
from threading import Lock

MAX_CACHE_BYTES = 16 * 1024 * 1024
_cache = OrderedDict()
_bytes = 0
_guard = Lock()
_renders = [Lock() for _ in range(16)]


def rendition(path, ticket, size, generate, *, verified=False):
    # materialize() has already verified cloud bytes. Local immutable-key assets
    # include filesystem identity, so replacements never reuse stale bytes.
    stat = path.stat()
    record = ticket.get('record')
    identity = (record['sha256'], record['file_size']) if record and verified else (
        stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    key = (str(path.resolve()), identity, ticket.get('version_id'), size)
    with _renders[hash(key) % len(_renders)]:
        with _guard:
            cached = _cache.get(key)
            if cached is not None:
                _cache.move_to_end(key)
                return cached
        content = generate()
        global _bytes
        with _guard:
            if len(content) <= MAX_CACHE_BYTES:
                while _cache and _bytes + len(content) > MAX_CACHE_BYTES:
                    _, old = _cache.popitem(last=False)
                    _bytes -= len(old)
                _cache[key] = content
                _bytes += len(content)
        return content
