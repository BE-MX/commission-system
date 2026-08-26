"""Read-only customer/product resolution and external invoice validation."""

from decimal import Decimal, ROUND_HALF_UP
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.integration.schemas import (
    CustomerSubmission,
    InvoiceSubmission,
    ProductResolutionRequest,
)
from app.invoice import accessory_price_service, price_service, product_service
from app.invoice.models import StdPrice


_MONEY = Decimal("0.01")
_PRICE = Decimal("0.0001")
_DECLARED_TOLERANCE = Decimal("0.01")
_MAX_MONEY = Decimal("999999999999.99")


class InvoiceValidationError(Exception):
    def __init__(self, issues: list[dict], warnings: list[dict] | None = None):
        super().__init__("invoice validation failed")
        self.issues = issues
        self.warnings = warnings or []


def _issue(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_MONEY, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal) -> str:
    return format(_money(value), ".2f")


def _price_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(value).quantize(_PRICE, rounding=ROUND_HALF_UP), ".4f")


def _normalize_company_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _normalize_phone(value: str | None) -> str:
    return "".join(re.findall(r"\d", str(value or "")))


def _customer_rows(db: Session) -> list[dict]:
    schema = product_service._schema()
    return [dict(row) for row in db.execute(text(f"""
        SELECT ci.company_id, ci.company_name, ci.country_name
        FROM `{schema}`.customer_info ci
        ORDER BY ci.company_id
    """)).mappings().all()]


def _customer_by_id(db: Session, customer_id: str) -> dict | None:
    schema = product_service._schema()
    row = db.execute(text(f"""
        SELECT ci.company_id, ci.company_name, ci.country_name
        FROM `{schema}`.customer_info ci
        WHERE CAST(ci.company_id AS CHAR) = :company_id
        LIMIT 1
    """), {"company_id": customer_id}).mappings().first()
    return dict(row) if row is not None else None


def _contact_company_ids(db: Session, contact) -> set[str]:
    schema = product_service._schema()
    email = str(contact.email or "").strip().casefold()
    phone = _normalize_phone(contact.phone)
    email_ids: set[str] = set()
    phone_ids: set[str] = set()

    if email:
        rows = db.execute(text(f"""
            SELECT DISTINCT cc.company_id
            FROM `{schema}`.customer_contacts cc
            WHERE LOWER(TRIM(cc.email)) = :email
            ORDER BY cc.company_id
        """), {"email": email}).scalars().all()
        email_ids = {str(company_id) for company_id in rows if company_id is not None}

    if phone:
        # Phone punctuation varies by source. Comparing normalized digits in Python
        # keeps SQLite tests and MySQL production behavior identical.
        rows = db.execute(text(f"""
            SELECT cc.company_id, cc.tel
            FROM `{schema}`.customer_contacts cc
            WHERE cc.tel IS NOT NULL AND TRIM(cc.tel) != ''
            ORDER BY cc.company_id, cc.id
        """)).mappings().all()
        phone_ids = {
            str(row["company_id"])
            for row in rows
            if row["company_id"] is not None and _normalize_phone(row["tel"]) == phone
        }

    if email_ids and phone_ids and email_ids != phone_ids:
        return email_ids | phone_ids
    return email_ids | phone_ids


def _canonical_customer(row: dict, submission: CustomerSubmission) -> dict:
    return {
        "ark_customer_id": str(row["company_id"]),
        "name": str(row["company_name"] or ""),
        "country_name": row.get("country_name"),
        "contact": submission.contact.model_dump(),
    }


def resolve_customer(
    db: Session,
    submission: CustomerSubmission,
    *,
    field: str = "customer",
) -> dict:
    """Resolve at organization scope, matching the existing invoice:write contract.

    The Integration App inherits its bound user's current invoice permission; customer
    private-pool ownership is an optional internal search filter, not an authorization
    boundary. This resolver returns one canonical customer or one stable issue and never
    returns contact candidates or other PII from the customer library.
    """
    if submission.ark_customer_id:
        row = _customer_by_id(db, submission.ark_customer_id)
        if row is None:
            raise InvoiceValidationError([_issue(
                "CUSTOMER_NOT_FOUND",
                field,
                "未找到对应的方舟客户，请先在 OKKI 建档后重试",
            )])
        return _canonical_customer(row, submission)

    contact_ids = _contact_company_ids(db, submission.contact)
    if len(contact_ids) > 1:
        raise InvoiceValidationError([_issue(
            "CUSTOMER_NOT_UNIQUE",
            field,
            "客户联系信息指向多个公司，请先确认方舟客户 ID",
        )])
    if len(contact_ids) == 1:
        row = _customer_by_id(db, next(iter(contact_ids)))
        if row is not None:
            return _canonical_customer(row, submission)

    normalized_name = _normalize_company_name(submission.name)
    matches = [
        row for row in _customer_rows(db)
        if normalized_name and _normalize_company_name(row["company_name"]) == normalized_name
    ]
    company_ids = {str(row["company_id"]) for row in matches}
    if len(company_ids) == 1:
        return _canonical_customer(matches[0], submission)
    if len(company_ids) > 1:
        raise InvoiceValidationError([_issue(
            "CUSTOMER_NOT_UNIQUE",
            field,
            "客户名称匹配到多个公司，请先确认方舟客户 ID",
        )])
    raise InvoiceValidationError([_issue(
        "CUSTOMER_NOT_FOUND",
        field,
        "未找到对应的方舟客户，请先在 OKKI 建档后重试",
    )])


def _canonical_description(item: dict) -> dict:
    product_name = str(item.get("product_name") or "")
    return {
        "product_name": product_name,
        "product_display": str(item.get("product_display") or product_name.split("/", 1)[0].strip()),
        "model": str(item.get("model") or ""),
        "color": str(item.get("color") or ""),
        "length": str(item.get("size") or ""),
        "unit": str(item.get("unit") or ""),
    }


def _catalog_pair(db: Session, product_id: int, sku_id: int) -> dict | None:
    pair = (int(product_id), int(sku_id))
    if pair not in product_service.valid_okki_product_skus(db, {pair}):
        return None

    schema = product_service._schema()
    columns = product_service._table_columns(db, "okki_products")
    name_column = "product_name" if "product_name" in columns else "name"
    product_no = "p.product_no" if "product_no" in columns else "NULL"
    row = db.execute(text(f"""
        SELECT p.product_id, p.`{name_column}` AS product_name,
               {product_no} AS product_no,
               p.model, p.color, p.size, p.unit
        FROM `{schema}`.okki_products p
        WHERE p.product_id = :product_id
        LIMIT 1
    """), {"product_id": product_id}).mappings().first()
    if row is None:
        return None
    item = dict(row)
    item["product_name"] = str(item.get("product_name") or item.get("product_no") or product_id)
    item["product_display"] = item["product_name"].split("/", 1)[0].strip()
    item["sku_id"] = int(sku_id)
    item["sku_count"] = 1
    return item


def resolve_product(
    db: Session,
    submission: ProductResolutionRequest,
    *,
    field: str = "catalog_ref",
) -> dict:
    if submission.catalog_ref is not None:
        if submission.product_kind == "accessory":
            try:
                snapshot = accessory_price_service.validate_active_identity(
                    db,
                    product_id=submission.catalog_ref.product_id,
                    sku_id=submission.catalog_ref.sku_id,
                )
            except (accessory_price_service.AccessoryCatalogUnavailable, ValueError):
                item = None
            else:
                item = {
                    "product_id": submission.catalog_ref.product_id,
                    "sku_id": submission.catalog_ref.sku_id,
                    "product_name": snapshot["accessory_name"],
                    "product_display": snapshot["accessory_name"],
                    "model": snapshot["accessory_model"],
                    "color": snapshot["accessory_color"],
                    "size": "",
                    "unit": "",
                }
        else:
            item = _catalog_pair(
                db,
                submission.catalog_ref.product_id,
                submission.catalog_ref.sku_id,
            )
        if item is None:
            raise InvoiceValidationError([_issue(
                "PRODUCT_NOT_FOUND",
                field,
                "产品与 SKU 不匹配、已停用或不存在，请重新解析产品",
            )])
    else:
        if submission.product_kind == "accessory":
            raise InvoiceValidationError([_issue(
                "PRODUCT_CATALOG_REQUIRED",
                field,
                "配件必须提供已确认的 product_id 和 sku_id",
            )])
        description = submission.description
        dimensions = (description.model, description.color, description.length, description.unit)
        if not all(str(value or "").strip() for value in dimensions):
            raise InvoiceValidationError([_issue(
                "PRODUCT_NOT_FOUND",
                field,
                "无产品 ID 时必须提供 model、color、length、unit 四维精确规格",
            )])
        matched = product_service.match_product(
            db,
            model=str(description.model),
            color=str(description.color),
            size=str(description.length),
            unit=str(description.unit),
        )
        if not matched["matches"]:
            raise InvoiceValidationError([_issue(
                "PRODUCT_NOT_FOUND",
                field,
                "未找到完全匹配的启用产品，请先确认产品规格",
            )])
        item = matched.get("item")
        if (
            not matched.get("is_unique")
            or item is None
            or int(item.get("sku_count") or 0) != 1
            or item.get("sku_id") is None
        ):
            raise InvoiceValidationError([_issue(
                "PRODUCT_NOT_UNIQUE",
                field,
                "产品规格匹配到多条产品或 SKU，请先确认 product_id 和 sku_id",
            )])

    return {
        "product_kind": submission.product_kind,
        "catalog_ref": {
            "product_id": int(item["product_id"]),
            "sku_id": int(item["sku_id"]),
        },
        "description": _canonical_description(item),
    }


def _price_snapshot(
    db: Session,
    *,
    customer_id: str | None,
    currency: str,
    canonical: dict,
) -> dict:
    ref = canonical["catalog_ref"]
    description = canonical["description"]
    if canonical["product_kind"] == "accessory":
        row = db.query(StdPrice).filter(
            StdPrice.product_kind == "accessory",
            StdPrice.product_id == ref["product_id"],
            StdPrice.sku_id == ref["sku_id"],
        ).first()
        if row is None or str(row.currency or "").upper() != currency:
            return {"standard_price": None, "customer_price": None, "price_source": "missing_std"}
        standard = Decimal(row.price)
        rule = price_service.get_customer_rule_row(db, customer_id)
        return {
            "standard_price": standard,
            "customer_price": price_service.apply_rule(standard, rule),
            "price_source": "customer_rule",
        }

    pricing = price_service.resolve_price(
        db,
        customer_id=customer_id,
        product_display=description["product_display"],
        length=description["length"],
        unit=description["unit"],
        color=description["color"],
    )
    if str(pricing.get("currency") or "").upper() != currency:
        return {"standard_price": None, "customer_price": None, "price_source": "missing_std"}
    return {
        "standard_price": pricing["standard_price"],
        "customer_price": pricing["customer_price"],
        "price_source": pricing["price_source"],
    }


def validate_submission(db: Session, submission: InvoiceSubmission) -> dict:
    issues: list[dict] = []
    warnings: list[dict] = []
    try:
        customer = resolve_customer(db, submission.customer)
    except InvoiceValidationError as exc:
        issues.extend(exc.issues)
        customer = None

    canonical_items: list[dict] = []
    product_amount = Decimal("0")
    for index, line in enumerate(submission.items):
        product_field = f"items[{index}].catalog_ref"
        try:
            canonical = resolve_product(db, line, field=product_field)
        except InvoiceValidationError as exc:
            issues.extend(exc.issues)
            continue

        raw_line_total = Decimal(line.quantity) * line.unit_price + line.discount_amount
        if raw_line_total < 0:
            issues.append(_issue(
                "DISCOUNT_EXCEEDS_LINE",
                f"items[{index}].discount_amount",
                "产品行折扣不能超过该行金额",
            ))
            continue
        if raw_line_total > _MAX_MONEY:
            issues.append(_issue(
                "AMOUNT_OUT_OF_RANGE",
                f"items[{index}].total_price",
                "产品行金额超过方舟发票可保存范围",
            ))
            continue
        line_total = _money(raw_line_total)
        product_amount += line_total
        snapshot = _price_snapshot(
            db,
            customer_id=customer["ark_customer_id"] if customer else None,
            currency=submission.currency,
            canonical=canonical,
        )
        expected_price = snapshot["customer_price"]
        price_source = snapshot["price_source"]
        if expected_price is not None and line.unit_price != Decimal(expected_price):
            price_source = "manual"
            warnings.append(_issue(
                "PRICE_DIFFERS_FROM_CURRENT",
                f"items[{index}].unit_price",
                "成交单价与方舟当前客户价不同，已保留外部成交价并返回价格快照",
            ))

        canonical_items.append({
            "external_line_id": line.external_line_id,
            **canonical,
            "quantity": line.quantity,
            "unit_price": _price_text(line.unit_price),
            "discount_amount": _money_text(line.discount_amount),
            "standard_price": _price_text(snapshot["standard_price"]),
            "customer_price": _price_text(snapshot["customer_price"]),
            "price_source": price_source,
            "total_price": _money_text(line_total),
        })

    product_amount = _money(product_amount)
    packaging = _money(submission.fees.packaging_amount)
    shipping = _money(submission.fees.shipping_amount)
    surcharge = _money(submission.fees.surcharge.amount)
    total_amount = _money(product_amount + packaging + shipping + surcharge)
    if product_amount > _MAX_MONEY:
        issues.append(_issue(
            "AMOUNT_OUT_OF_RANGE",
            "totals.product_amount",
            "产品金额合计超过方舟发票可保存范围",
        ))
    if total_amount > _MAX_MONEY:
        issues.append(_issue(
            "AMOUNT_OUT_OF_RANGE",
            "totals.total_amount",
            "发票总金额超过方舟发票可保存范围",
        ))

    if submission.declared_totals is not None:
        declared = submission.declared_totals
        for field_name, actual in (
            ("product_amount", product_amount),
            ("total_amount", total_amount),
        ):
            claimed = Decimal(getattr(declared, field_name))
            if abs(claimed - actual) > _DECLARED_TOLERANCE:
                issues.append(_issue(
                    "DECLARED_TOTAL_MISMATCH",
                    f"declared_totals.{field_name}",
                    "声明金额与方舟服务端重算金额不一致",
                ))

    if issues:
        raise InvoiceValidationError(issues, warnings)

    return {
        "schema_version": submission.schema_version,
        "external_order_id": submission.external_order_id,
        "order_type": submission.order_type,
        "invoice_date": submission.invoice_date.isoformat(),
        "currency": submission.currency,
        "customer": customer,
        "delivery": submission.delivery.model_dump(),
        "fees": {
            "packaging_amount": _money_text(packaging),
            "packaging_quantity": submission.fees.packaging_quantity,
            "shipping_amount": _money_text(shipping),
            "surcharge": {
                "name": submission.fees.surcharge.name,
                "amount": _money_text(surcharge),
            },
        },
        "payment_term": submission.payment_term,
        "remark": submission.remark,
        "items": canonical_items,
        "totals": {
            "product_amount": _money_text(product_amount),
            "total_amount": _money_text(total_amount),
        },
        "warnings": warnings,
    }
