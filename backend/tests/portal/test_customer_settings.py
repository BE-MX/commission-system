from datetime import datetime
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select
from pydantic import ValidationError
from test_catalog import priced_catalog, catalog, managed, portal_metadata, auth_context
from app.portal import customer_settings_service as service, pricing
from app.portal.models import CatalogGrant, AuthorityBarrier
from app.portal.order_service import next_request_number
from app.portal.schemas import CustomerPricesInput, DeliveryProfileInput
from app.portal.errors import PortalError
from app.invoice.models import CustomerProfile


def prices(item, value="24.0000"):
    return CustomerPricesInput(items=[dict(item_id=item.public_id, unit_price=value)])


def test_prices_default_to_standard_then_override_checkout_fingerprint(priced_catalog):
    ctx, items, _ = priced_catalog
    before = pricing.resolve(ctx.db, ctx.access, items[0], "USD")
    result = service.get_prices(ctx.db, 1, ctx.access.public_id)
    assert result["items"][0]["standard_price"] == "30.0000"
    assert result["items"][0]["unit_price"] is None
    service.update_prices(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, prices(items[0]))
    ctx.db.commit()
    after = pricing.resolve(ctx.db, ctx.access, items[0], "USD")
    assert after.amount == Decimal("24") and after.fingerprint != before.fingerprint
    assert pricing.resolve(ctx.db, ctx.access, items[1], "USD").amount == before.amount
    service.update_prices(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, prices(items[0], None))
    ctx.db.commit()
    assert pricing.resolve(ctx.db, ctx.access, items[0], "USD").amount == before.amount


@pytest.mark.parametrize("actor,version,status", [(2,1,404),(3,1,403),(1,0,409)])
def test_price_write_scope_permission_and_version(priced_catalog, actor, version, status):
    ctx, items, _ = priced_catalog
    with pytest.raises(PortalError) as caught:
        service.update_prices(ctx.db, actor, ctx.access.public_id, version, prices(items[0]))
    assert caught.value.status == status
    ctx.db.rollback()
    assert ctx.db.scalar(select(CatalogGrant.unit_price).where(CatalogGrant.catalog_item_id == items[0].id)) is None


def test_price_batch_rejects_foreign_or_duplicate_before_any_change(priced_catalog):
    ctx, items, _ = priced_catalog
    for ids in ([items[0].public_id, str(uuid4())], [items[0].public_id]*2):
        with pytest.raises(PortalError):
            service.update_prices(ctx.db, 1, ctx.access.public_id, 1,
                CustomerPricesInput(items=[dict(item_id=value, unit_price="20.0000") for value in ids]))
        ctx.db.rollback()
        assert all(row.unit_price is None for row in ctx.db.scalars(select(CatalogGrant)))


@pytest.mark.parametrize("value", ["0.0000", "-1.0000", "NaN", "1.00001", "100000000.0000"])
def test_customer_prices_reject_invalid_money(value):
    with pytest.raises(ValidationError):
        CustomerPricesInput(items=[dict(item_id=uuid4(), unit_price=value)])


def test_shared_address_scoped_admin_readback_and_version(managed):
    ctx = managed
    body = DeliveryProfileInput(delivery=dict(contact_name="Buyer", phone="12345", address_line1="Street", country_code="GB"))
    assert service.get_delivery(ctx.db, 1, ctx.access.public_id)["delivery"] is None
    result = service.update_delivery(ctx.db, 1, ctx.access.public_id, 1, body)
    ctx.db.commit()
    assert result["row_version"] == 2
    assert ctx.db.get(CustomerProfile, "1").delivery_json["country_code"] == "GB"
    with pytest.raises(PortalError) as caught:
        service.update_delivery(ctx.db, 1, ctx.access.public_id, 1, body)
    assert caught.value.code == "VERSION_CONFLICT"
    ctx.db.rollback()
    with pytest.raises(PortalError): service.get_delivery(ctx.db, 2, ctx.access.public_id)


def test_request_number_daily_sequence_and_rollback(auth_context):
    db = auth_context.db
    at = datetime(2026, 10, 28, 23, 59, 59)
    assert next_request_number(db, at) == "POR-20261028-01"
    db.commit()
    assert next_request_number(db, at) == "POR-20261028-02"
    db.rollback()
    assert next_request_number(db, at) == "POR-20261028-02"
    assert next_request_number(db, datetime(2026, 10, 29)) == "POR-20261029-01"
    counter = db.get(AuthorityBarrier, "order-no-20261028")
    counter.version = 99
    assert next_request_number(db, at) == "POR-20261028-100"
