"""Native external-order identities and creation on the shared invoice aggregate."""
from app.catalog import query_service
from app.catalog.models import CatalogProduct, CatalogSku
from app.customer.models import CustomerAccount
from app.integration.validation_service import InvoiceValidationError, _issue, _canonical_description


def resolve_customer(db, submission, *, field):
    identity = submission.ark_customer_id or ""
    if not identity.startswith("ark:"):
        raise InvoiceValidationError([_issue("LOCAL_CUSTOMER_ID_REQUIRED", field,
            "本地交易需要已核验的 ark:客户ID，请先在方舟客户目录确认身份")])
    row = db.get(CustomerAccount, int(identity.split(":")[1]))
    if row is None or row.record_status != "active" or row.identity_status == "disputed":
        raise InvoiceValidationError([_issue("CUSTOMER_NOT_FOUND", field, "客户不存在、已停用或存在身份冲突")])
    return {"ark_customer_id": f"ark:{row.id}", "name": row.display_name,
            "country_name": row.primary_country_code, "contact": submission.contact.model_dump()}


def resolve_product(db, submission, *, field):
    ref = submission.catalog_ref
    if ref:
        if not str(ref.product_id).startswith("ark:product:") or not str(ref.sku_id).startswith("ark:sku:"):
            raise InvoiceValidationError([_issue("IDENTITY_SOURCE_MISMATCH", field,
                "本地交易必须使用 ark:product:ID 和 ark:sku:ID，不接受未映射的 OKKI 编号")])
        pair = db.execute(query_service.catalog().where(
            CatalogProduct.id == int(ref.product_id.rsplit(":", 1)[1]),
            CatalogSku.id == int(ref.sku_id.rsplit(":", 1)[1]),
            CatalogProduct.kind == submission.product_kind)).first()
        item = query_service.record(*pair) if pair else None
    else:
        description = submission.description
        if not all(str(value or "").strip() for value in (
                description.model, description.color, description.length, description.unit)):
            raise InvoiceValidationError([_issue("PRODUCT_CATALOG_REQUIRED", field, "请提供商品和SKU标识或完整精确规格")])
        query = query_service.filtered(query_service.catalog(), {
            "model": description.model, "color": description.color,
            "size": description.length, "unit": description.unit})
        pairs = db.execute(query.where(CatalogProduct.kind == submission.product_kind).limit(2)).all()
        if len(pairs) > 1:
            raise InvoiceValidationError([_issue("PRODUCT_NOT_UNIQUE", field, "规格不唯一，请确认本地商品和SKU标识")])
        item = query_service.record(*pairs[0]) if pairs else None
    if item is None:
        raise InvoiceValidationError([_issue("PRODUCT_NOT_FOUND", field, "商品与SKU不匹配、类别不符或已停用")])
    return {"product_kind": submission.product_kind,
            "catalog_ref": {key: item[key] for key in ("product_id", "sku_id")},
            "description": _canonical_description(item)}


def create_invoice(db, canonical, ingest, principal):
    from app.auth.models import ArkUser
    from app.auth.service import get_user_permissions, get_user_roles
    from app.invoice.commerce_schemas import LocalInvoiceDraft, LocalItem
    from app.invoice.commerce_service import create_draft
    actor = db.get(ArkUser, principal.actor_user_id)
    if actor is None or not actor.is_active or actor.deleted_at is not None:
        raise ValueError("接入账号当前不可用")
    fees, customer = canonical["fees"], canonical["customer"]
    body = LocalInvoiceDraft(
        request_key=f"integration:{ingest.public_id}:{ingest.request_sha256}",
        local_customer_id=int(customer["ark_customer_id"].split(":")[1]),
        sales_user_id=principal.sales_user_id, order_type=canonical["order_type"],
        invoice_date=canonical["invoice_date"], currency=canonical["currency"],
        contact_name=customer["contact"]["name"], contact_email=customer["contact"]["email"],
        contact_phone=customer["contact"]["phone"], delivery_address=canonical["delivery"]["address"],
        express_channel=canonical["delivery"]["express_channel"],
        shipping_fee=fees["shipping_amount"], surcharge_name=fees["surcharge"]["name"],
        surcharge_amount=fees["surcharge"]["amount"], packaging_quantity=fees["packaging_quantity"],
        internal_accessory=fees["packaging_amount"], payment_term=canonical["payment_term"],
        remark=canonical["remark"], commercial_source="website",
        items=[LocalItem(local_sku_id=int(item["catalog_ref"]["sku_id"].rsplit(":", 1)[1]),
            quantity=item["quantity"], price_per_piece=item["unit_price"],
            discount_amount=item["discount_amount"]) for item in canonical["items"]])
    invoice = create_draft(db, body, {"sub": str(actor.id), "roles": get_user_roles(actor),
                                    "permissions": get_user_permissions(actor)})
    invoice.source_type, invoice.source_order_id = "external_api", ingest.public_id
    invoice.source_order_name = ingest.external_order_id
    return invoice
