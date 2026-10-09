"""Read exact active OKKI identities for import and later order revalidation.

The mirror is read-only. Customer labels and browser-supplied attributes never
participate in this projection. Product kind is an explicit catalog decision;
the source does not guess it from a product name.
"""

import logging
import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.invoice import product_service
from app.portal.domain import content_hash
from app.portal.errors import reject


logger = logging.getLogger(__name__)


def _identity(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        reject("INVALID_INPUT", "Select a valid standard product and SKU.", 422)
    if int(value) > 9223372036854775807:
        reject("INVALID_INPUT", "Select a valid standard product and SKU.", 422)
    return value


def _attribute(value, *, required=True):
    value = str(value or "").strip()
    if (required and not value) or len(value) > 128 or any(
        unicodedata.category(char).startswith("C") or char in "<>" for char in value
    ):
        reject("SKU_UNAVAILABLE", "Standard product attributes need review.", 409)
    return value


def load_snapshot(db, *, namespace, product_id, sku_id, product_kind):
    """Fail closed on a missing source, inactive pair or ambiguous mirror rows."""
    settings = get_settings()
    if not settings.PORTAL_OKKI_NAMESPACE or namespace != settings.PORTAL_OKKI_NAMESPACE:
        reject("SKU_UNAVAILABLE", "The standard product source is not configured.", 503)
    product_id, sku_id = _identity(product_id), _identity(sku_id)
    if product_kind not in {"hair", "accessory"}:
        reject("INVALID_INPUT", "Choose a supported product category.", 422)
    schema = product_service._schema()
    if not re.fullmatch(r"[A-Za-z0-9_]+", schema):
        reject("SKU_UNAVAILABLE", "The standard product source is not configured.", 503)
    try:
        products = product_service._table_columns(db, "okki_products")
        skus = product_service._table_columns(db, "okki_product_skus")
        name = "product_name" if "product_name" in products else "name"
        required = {"product_id", "model", "color", "disable_flag", name}
        if product_kind == "hair":
            required |= {"size", "unit"}
        if not required <= products or not {"product_id", "sku_id", "disable_flag"} <= skus:
            reject("SKU_UNAVAILABLE", "The standard product source is incomplete.", 503)
        size = "p.size" if "size" in products else "NULL"
        unit = "p.unit" if "unit" in products else "NULL"
        rows = db.execute(text(f"""
            SELECT p.`{name}` AS product_name, p.model, p.color,
                   {size} AS size, {unit} AS unit
            FROM `{schema}`.okki_products p
            JOIN `{schema}`.okki_product_skus s ON s.product_id = p.product_id
            WHERE p.product_id = :product_id AND s.sku_id = :sku_id
              AND p.disable_flag = 0 AND s.disable_flag = 0
            LIMIT 2
        """), {"product_id": int(product_id), "sku_id": int(sku_id)}).mappings().all()
    except SQLAlchemyError as exc:
        # Do not expose SQL, connection details or bound values to customers/logs.
        message = f"Portal SKU source unavailable: {type(exc).__name__}"
        logger.warning(message)
        print(message, flush=True)
        reject("SKU_UNAVAILABLE", "The standard product source is unavailable.", 503)
    if len(rows) != 1:
        reject("SKU_UNAVAILABLE", "The standard product is unavailable or ambiguous.", 409)
    row = rows[0]
    name = _attribute(row["product_name"])
    model, color = _attribute(row["model"]), _attribute(row["color"])
    length = _attribute(row["size"], required=product_kind == "hair")
    unit = _attribute(row["unit"], required=product_kind == "hair")
    attributes = {"product_name": name, "model": model, "color": color,
                  "model_key": model, "color_key": color, "length": length,
                  "weight": unit, "price_unit": unit,
                  "product_display": _attribute(name if product_kind == "accessory" else name.split("/", 1)[0])}
    identity = {"source_namespace": namespace, "product_id": product_id,
                "sku_id": sku_id, "product_kind": product_kind}
    return {**identity, "standard_json": attributes,
            "standard_fingerprint": content_hash({**identity, "attributes": attributes})}


def revalidate(db, item):
    """Require explicit reimport when the original standard specification changes."""
    current = load_snapshot(db, namespace=item.source_namespace, product_id=item.product_id,
                            sku_id=item.sku_id, product_kind=item.product_kind)
    if current["standard_fingerprint"] != item.standard_fingerprint or current["standard_json"] != item.standard_json:
        reject("SKU_CHANGED", "The standard specification changed. Refresh the catalog.", 409)
    return current

