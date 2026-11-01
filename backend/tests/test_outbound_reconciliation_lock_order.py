"""Outbound reconciliation may close receipt claims: policy before invoice. SQLite only.

SQLite has no row locks, so the protocol is asserted by call order: the
reconciliation capture must take portal barrier -> commerce policy ->
invoice authorities before the invoice document lock, the same order as
commerce_transition.lock_recovery_scope and legacy_sending.finish.
"""
from types import SimpleNamespace

import pytest

from app.commerce_transition import service as ownership
from app.invoice import outbound_reconciliation_service as reconciliation
from tests.test_presale_runtime import order  # noqa: F401  (fixture reuse)
from tests.test_presale_inspection_completion import batch  # noqa: F401  (fixture reuse)

USER = {"id": 1, "sub": "1", "roles": ["super_admin"], "permissions": []}


class Stop(Exception):
    pass


def test_reconciliation_capture_locks_policy_before_invoice(db, order, batch, monkeypatch):
    row, outbound, inspection = batch
    identity, body = row.id, SimpleNamespace(remote_id=None, version=row.version)
    calls = []
    portal, policy, document = reconciliation.lock_authority, ownership._lock_policy, reconciliation.edit_authority.lock_document
    monkeypatch.setattr(reconciliation, "lock_authority", lambda *a, **k: (calls.append("portal"), portal(*a, **k))[1])
    monkeypatch.setattr(ownership, "_lock_policy", lambda *a, **k: (calls.append("policy"), policy(*a, **k))[1])
    def lock_document(*a, **k):
        calls.append("invoice")
        raise Stop
    monkeypatch.setattr(reconciliation.edit_authority, "lock_document", lock_document)
    db.rollback()
    with pytest.raises(Stop):
        reconciliation._capture(db, identity, body, USER)
    db.rollback()
    assert calls[:3] == ["portal", "policy", "invoice"], calls
