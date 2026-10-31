"""Installed current executor for legacy business mapping/queue regression.

Only HTTP provider responses are simulated. Authority, immutable attempts,
claim commits, result application and queue ownership use the real services.
"""
from app.invoice import okki_client, order_sync_execution
from tests.authority_helpers import seed_authority


def install_transport(db, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'OKKI_OUTBOUND_AUTO_ENABLED', True)
    original = okki_client.push_order
    db.info['isolated_provider_orders'] = {}
    monkeypatch.setattr(okki_client, 'ensure_access_token', lambda *args, **kwargs: 'isolated-order-token')
    def post(path, token, payload, *, context):
        assert path == '/v1/invoices/order/push'
        assert not db.in_transaction(), 'No invoice/authority locks across provider I/O'
        provider = okki_client.push_order
        assert provider is not original, 'Test must supply an explicit provider response'
        result = provider(db, payload, before_send=lambda: None)
        if isinstance(result, dict) and result.get('order_id'):
            db.info['isolated_provider_orders'][str(result['order_id'])] = {
                **payload, **result, 'product_list': result.get('product_list', [])}
        return result
    monkeypatch.setattr(okki_client, '_post_json', post)


def sync_current(db, invoice, operator_id=1):
    identity = invoice.id
    from app.invoice.service import _refresh_invoice_totals
    _refresh_invoice_totals(invoice)  # This ORM fixture represents an already saved editor document.
    from app.auth.models import ArkRole, ArkUserRole
    granted = db.query(ArkUserRole).join(ArkRole, ArkRole.id == ArkUserRole.role_id).filter(
        ArkUserRole.user_id == operator_id, ArkRole.name == 'super_admin').first()
    if granted is None:
        seed_authority(db, operator_id, 'invoice:read', 'invoice:write', 'invoice:sync', 'invoice:read_all',
                       roles=('super_admin',))
    else:
        db.commit()
    # seed_authority commits the test's setup, exactly as saving a document
    # precedes the separate current synchronization request in the UI.
    return order_sync_execution.run(db, identity, {'id': operator_id}, follow_outbound=False)


def current_order_readback(db, invoice):
    from decimal import Decimal
    payload = db.info['isolated_provider_orders'][str(invoice.xiaoman_order_id)]
    amount = sum((Decimal(str(row['cost_amount'])) for row in payload['product_list']), Decimal(0))
    amount += sum((Decimal(str(row['cost'])) for row in payload.get('cost_list', [])), Decimal(0))
    return {**payload, 'amount': amount}
