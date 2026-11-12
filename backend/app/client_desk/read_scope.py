"""Request-local scope reuse and bounded, process-local read caches.

Only explicitly decorated read paths may reuse ownership across requests.
Source grants, message revisions and suggestion visibility are never cached.
"""

from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps
from threading import RLock
from time import monotonic

_request = ContextVar("client_desk_request", default=None)
_cache = OrderedDict()
_lock = RLock()
_stripes = [RLock() for _ in range(64)]


def scope_request(*, read_only=False, cache_companies=None):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            current = _request.get()
            if current is not None and (read_only or not current["read_only"]):
                return fn(*args, **kwargs)
            token = _request.set({
                "read_only": read_only,
                "cache_companies": read_only if cache_companies is None else cache_companies,
                "values": {},
            })
            try:
                return fn(*args, **kwargs)
            finally:
                _request.reset(token)
        return wrapped
    return decorate


def read_only():
    scope = _request.get()
    return bool(scope and scope["read_only"])


def cache_companies():
    scope = _request.get()
    return bool(scope and scope["cache_companies"])


def forget(key):
    scope = _request.get()
    if scope is not None:
        scope["values"].pop(key, None)


def once(key, load):
    scope = _request.get()
    if scope is None:
        return load()
    if key not in scope["values"]:
        scope["values"][key] = load()
    return scope["values"][key]


def cached(key, seconds, load):
    # Serialize identical misses (e.g. parallel dossier and timeline requests).
    with _stripes[hash(key) % len(_stripes)]:
        with _lock:
            entry = _cache.get(key)
            if entry and entry[0] > monotonic():
                _cache.move_to_end(key)
                return entry[1]
            _cache.pop(key, None)
        value = load()  # Exceptions must never create a successful cache entry.
        with _lock:
            _cache[key] = (monotonic() + seconds, value)
            _cache.move_to_end(key)
            while len(_cache) > 1024:
                _cache.popitem(last=False)
        return value


def invalidate(key):
    with _stripes[hash(key) % len(_stripes)]:
        with _lock:
            _cache.pop(key, None)


def fresh(key, load):
    # A denied live action cannot race with an older read filling the cache.
    with _stripes[hash(key) % len(_stripes)]:
        invalidate(key)
        return load()
