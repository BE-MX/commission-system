"""External native orders retain idempotency without using transaction mirrors."""
import pytest
from sqlalchemy import event
from app.auth.models import ArkRole, ArkUser
from app.catalog.models import CatalogProduct
from app.core.config import get_settings
from app.integration.auth import SubmissionPrincipal
from app.integration.models import IntegrationApp
from app.integration.schemas import InvoiceSubmission, ProductResolutionRequest
from app.integration.service import create_external_invoice, ExternalOrderChanged
from app.integration.validation_service import resolve_product, InvoiceValidationError
from app.invoice import accessory_price_service
from app.invoice.models import Invoice, StdPrice
from app.invoice.schemas import AccessoryPricePayload
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer
from tests.test_integration_api import _submission


def test_native_external_order_identities_persistence_replay_and_prices(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, _ = stock
    customer, claims = buyer
    actor = db.get(ArkUser, int(claims["sub"]))
    role = ArkRole(name="super_admin", label="Admin")
    actor.roles = [role]
    app = IntegrationApp(public_id="native-app", name="Native", owner_user_id=actor.id,
                         token_hash="unused", token_suffix="unused", scopes=["invoice:write"])
    db.add(app)
    product = db.get(CatalogProduct, sku.product_id)
    product.kind, product.model, sku.color = "accessory", "Clip", "Black"
    db.flush()
    ref = {"product_id": f"ark:product:{product.id}", "sku_id": f"ark:sku:{sku.id}"}
    principal = SubmissionPrincipal(actor.id, actor.id, app.public_id, frozenset(["invoice:write"]))
    payload = _submission()
    payload["customer"]["ark_customer_id"] = f"ark:{customer.id}"
    payload["items"][0].update(product_kind="accessory", catalog_ref=ref)
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower() and "okki_products" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        # Colliding external numeric identifiers cannot select or overwrite a native price.
        db.add(StdPrice(product_kind="accessory", product_id=product.id, sku_id=sku.id, price=999, currency="USD"))
        price = accessory_price_service.upsert_price(db, AccessoryPricePayload(**ref, accessory_name="forged",
            accessory_model="forged", accessory_color="forged", price="9", currency="USD"), actor.id)
        db.flush()
        assert price.local_sku_id == sku.id and price.product_id is None
        assert accessory_price_service.search_candidates(db, "Clip")[0]["sku_id"] == ref["sku_id"]
        assert len(accessory_price_service.list_prices(db, active_only=True)) == 1
        with pytest.raises(InvoiceValidationError, match="validation"):
            resolve_product(db, ProductResolutionRequest(product_kind="accessory", catalog_ref={"product_id": product.id, "sku_id": sku.id}))
        body = InvoiceSubmission.model_validate(payload)
        result, replay = create_external_invoice(db, body, principal)
        invoice = db.get(Invoice, result["invoice_id"])
        assert not replay and invoice.transaction_mode == "local" and invoice.commerce_status == "draft"
        assert invoice.local_customer_id == customer.id and invoice.items[0].local_sku_id == sku.id
        assert invoice.total_amount == 20 and invoice.source_type == "external_api"
        repeated, replay = create_external_invoice(db, body, principal)
        assert replay and repeated["invoice_id"] == invoice.id
        with pytest.raises(ExternalOrderChanged):
            create_external_invoice(db, body.model_copy(update={"remark": "changed"}), principal)
        sku.active = False
        db.flush()
        assert accessory_price_service.list_prices(db, active_only=True) == []
        assert len(accessory_price_service.list_prices(db)) == 1
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)
