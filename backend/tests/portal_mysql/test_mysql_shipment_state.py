"""Current local shipment state commands on actual JWT/main/owned MySQL."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.settlement_models import ShipmentSettlement
from test_mysql_shipment_create import (shipment_app, body_for, path, snapshot, authorize,
    login, change_user, created)  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


@pytest.fixture
def state_app(shipment_app, monkeypatch):
    # Match the real request SessionLocal contract, including autoflush=False.
    # The explicit False/True test still checks both actual request settings.
    from sqlalchemy.orm import sessionmaker
    from app.core import database
    c = shipment_app
    monkeypatch.setattr(database, 'SessionLocal', sessionmaker(bind=c.ctx.engine, autoflush=False))
    return c


ACTIONS = ('cancel', 'pause', 'resume')


def state_path(c, action):
    return f'/api/shipments/{c.settlement_id}/{action}'


def setup(client, c, action, *, payment=False, quantity=4, freight='20.00'):
    root = login(client, c, c.root_name)
    authorize(client, c, root)
    owner = login(client, c, c.owner_name)
    body = body_for(client, c, owner, payment=payment, quantity=quantity, freight=freight)
    c.settlement_id = created(c, body, client.post(path(c), headers=owner, json=body))
    with Session(c.ctx.engine) as db:
        version = db.get(ShipmentSettlement, c.settlement_id).version
    if action == 'resume':
        response = client.post(state_path(c, 'pause'), headers=owner,
            json={'version': version, 'reason': 'Prepare actual paused settlement'})
        assert response.status_code == 200 and response.json()['data']['state'] == 'paused', response.text
        version = response.json()['data']['version']
    return root, owner, {'version': version, 'reason': 'Current-authority state command'}


@pytest.mark.parametrize('action', ACTIONS)
@pytest.mark.parametrize('revoke', ['disabled', 'roles', 'shipment:write'])
def test_current_revocation_denies_old_token_zero_write(state_app, action, revoke):
    c = state_app
    with c.app.client() as client:
        root, owner, body = setup(client, c, action)
        patch = {'is_active': False} if revoke == 'disabled' else {'role_ids': []} if revoke == 'roles' else {
            'role_ids': [c.roles['invoice:write'], c.roles['write']]}
        change_user(client, c, root, patch)
        before = snapshot(c); c.io.clear()
        response = client.post(state_path(c, action), headers=owner, json=body)
        assert response.status_code == 403, response.text
        assert response.headers.get('cache-control') == 'private, no-store'
        assert snapshot(c) == before and c.io == [] and c.calls == []


@pytest.mark.parametrize('action', ACTIONS)
def test_current_grant_applies_to_old_token_with_only_shipment_action(state_app, action):
    c = state_app
    with c.app.client() as client:
        root, _, body = setup(client, c, action)
        change_user(client, c, root, {'role_ids': []})
        owner = login(client, c, c.owner_name)
        change_user(client, c, root, {'role_ids': [c.roles['shipment:write']]})
        c.io.clear()
        response = client.post(state_path(c, action), headers=owner, json=body)
        assert response.status_code == 200, response.text
        data = response.json()['data']
        assert data['id'] == c.settlement_id and data['version'] == body['version'] + 1
        assert data['state'] == {'cancel': 'cancelled', 'pause': 'paused', 'resume': 'awaiting_payment'}[action]
        assert response.headers.get('cache-control') == 'private, no-store'
        assert c.io == [] and c.calls == []
