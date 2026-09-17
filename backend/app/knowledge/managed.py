"""Explicit scoped entry into business-managed libraries. Never set by HTTP input."""
from contextlib import contextmanager
from contextvars import ContextVar

_scope = ContextVar('knowledge_managed_scope', default=None)


@contextmanager
def announcement_scope(library_id):
    token = _scope.set(('announcement', library_id))
    try:
        yield
    finally:
        _scope.reset(token)


def in_scope(library_id):
    return _scope.get() == ('announcement', library_id)


def permits(identity, permission):
    if not _scope.get():
        return False
    perms = set(identity.get('permissions', []))
    if permission == 'knowledge:review':
        return 'knowledge:review' in perms or 'announcement:admin' in perms
    mapped = {'knowledge:read': {'announcement:read', 'announcement:write', 'announcement:admin'},
              'knowledge:write': {'announcement:write', 'announcement:admin'},
              'knowledge:admin': {'announcement:admin'}}
    return bool(perms & mapped.get(permission, set()))
