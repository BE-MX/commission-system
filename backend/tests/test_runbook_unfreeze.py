"""Rehearse docs/runbook.md's manual unfreeze SQL against the real schema (SQLite).

The statements are read from the runbook itself; only MySQL-only syntax is
adapted (locking reads/transaction keywords dropped, NOW()/JSON_OBJECT/TRUE
mapped to SQLite). A wrong column name or a missing step fails here.
"""
from pathlib import Path
import re

import pytest
from sqlalchemy import text

from app.commerce_transition import service as authority
from app.commerce_transition.models import AuthorityEvent, ClaimEvidence, InvoiceAuthority, SendingClaim
from app.invoice import legacy_sending as gate
from tests.claim_helpers import ended_send_lease  # noqa: F401  (fixture)
from tests.test_commerce_manual_unlock import ready, unknown_claim  # noqa: F401  (fixture reuse)

RUNBOOK = Path(__file__).resolve().parents[2] / 'docs' / 'runbook.md'


@pytest.fixture(autouse=True)
def _ended_send_lease(ended_send_lease):
    """The frozen claim's original request window has long ended."""


def unfreeze_statements():
    body = RUNBOOK.read_text(encoding='utf-8')
    section = body[body.index('### 3. 人工解冻'):]
    block = re.search(r'```sql\n(.*?)```', section, re.S).group(1)
    code = '\n'.join(line.split('--', 1)[0] for line in block.splitlines())
    statements = [part.strip() for part in code.split(';') if part.strip()]
    adapted = []
    for statement in statements:
        upper = statement.upper()
        if upper in {'START TRANSACTION', 'COMMIT'} or upper.endswith('FOR UPDATE'):
            continue  # Locking reads and transaction control are MySQL session details.
        adapted.append(statement.replace('NOW()', 'CURRENT_TIMESTAMP')
                       .replace('JSON_OBJECT', 'json_object').replace('TRUE', '1'))
    return adapted


def frozen_order(db, ready):
    claim = unknown_claim(db, ready)
    authority.confirm_not_sent(db, claim.id, operator_id=1, reason='Checked OKKI: no order exists',
                               remote_evidence={'remote_readback': 'operator_checked'}, source='test')
    db.commit()
    gate.finish(db, 'core-original', 'succeeded', {'late_response': True}, '2001'); db.commit()
    held = db.get(InvoiceAuthority, ready.id)
    assert held.state == 'frozen' and db.get(SendingClaim, claim.id).state == 'unknown'
    return claim.id, held.epoch, held.lock_version


@pytest.mark.parametrize('terminal,external', [('succeeded', '2001'), ('not_sent', None)])
def test_runbook_unfreeze_sql_releases_the_order_for_new_sends(db, ready, terminal, external):
    claim_id, epoch, lock_version = frozen_order(db, ready)
    with pytest.raises(ValueError):  # Frozen: nothing may send.
        gate.start(db, ready, 'after-freeze', 'order_push', {'order_id': '2001'}, {}, 1)
    db.rollback()
    evidence_before = db.query(ClaimEvidence).filter_by(claim_id=claim_id).count()
    params = {'invoice_id': ready.id, 'claim_id': claim_id, 'epoch': epoch, 'lock_version': lock_version,
              'terminal_status': terminal, 'external_id': external, 'ticket_no': 'OPS-1', 'operator_name': 'ops',
              'reason': 'Duplicate checked in OKKI', 'okki_refs': 'okki order 2001'}
    statements = unfreeze_statements()
    assert len(statements) == 4, statements
    for statement in statements:
        result = db.execute(text(statement), {k: v for k, v in params.items() if f':{k}' in statement})
        if statement.upper().startswith('UPDATE'):
            assert result.rowcount == 1, statement
    db.commit()
    db.expire_all()
    claim = db.get(SendingClaim, claim_id)
    assert claim.state == terminal and claim.external_id == external
    assert claim.terminal_at is not None and claim.active_invoice_key is None
    assert db.query(ClaimEvidence).filter_by(claim_id=claim_id).count() == evidence_before + 1
    event = db.query(AuthorityEvent).filter_by(invoice_id=ready.id, action='manual_unfreeze').one()
    assert event.payload['claim_id'] == claim_id and event.payload['claim_terminal_status'] == terminal
    assert db.get(InvoiceAuthority, ready.id).state == 'active'
    gate.start(db, ready, 'after-unfreeze', 'order_push', {'order_id': '2001'}, {}, 1)  # Order is free.
    db.rollback()
