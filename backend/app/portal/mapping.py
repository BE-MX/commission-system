"""Customer aliases are a presentation projection; never mutate standard SKUs."""

import unicodedata

from app.portal.domain import normalize_text
from app.portal.errors import reject


def _label(value, *, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        reject("INVALID_INPUT", "A display label is missing or too long.", 422)
    normalized = normalize_text(value)
    if len(normalized) > maximum:
        reject("INVALID_INPUT", "A display label is missing or too long.", 422)
    # NFKC can turn fullwidth/small brackets into markup. Check the value that
    # is actually published; keep raw control checks before whitespace folding.
    if any(unicodedata.category(c).startswith("C") for c in value) or "<" in normalized or ">" in normalized:
        reject("INVALID_INPUT", "Display labels must be plain text.", 422)
    return normalized


def analyze_mapping(items: list[dict], entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Validate the full effective catalog, not only edited rows.

    Items carry stable public item_id/model_key/color_key and standard dimensions.
    Results contain presentation values only; the caller retains standard records.
    """
    if len(items) > 5000 or len(entries) > 15000:
        reject("INVALID_INPUT", "The customer catalog exceeds the supported size.", 422)
    ids = {str(item["item_id"]) for item in items}
    models = {item["model_key"] for item in items}
    colors = {item["color_key"] for item in items}
    aliases = {}
    for entry in entries:
        kind = entry.get("kind")
        key = entry.get("source_key")
        if kind not in {"sku", "model", "color"} or not isinstance(key, str):
            reject("INVALID_INPUT", "Choose a valid standard mapping key.", 422)
        allowed = ids if kind == "sku" else models if kind == "model" else colors
        if key not in allowed or kind == "sku" and str(entry.get("item_id")) != key:
            reject("RESOURCE_NOT_FOUND", "The mapping source is not available.", 404)
        if (kind, key) in aliases:
            reject("INVALID_INPUT", "A mapping source is listed more than once.", 422)
        aliases[kind, key] = {
            "display_value": _label(entry.get("display_value")),
            "customer_sku": _label(entry["customer_sku"], maximum=64) if entry.get("customer_sku") else None,
        }
        if kind != "sku" and aliases[kind, key]["customer_sku"]:
            reject("INVALID_INPUT", "Customer SKU belongs to an individual SKU mapping.", 422)
    result, specs, customer_skus, color_meanings, conflicts = [], {}, {}, {}, []
    for item in items:
        item_id = str(item["item_id"])
        exact = aliases.get(("sku", item_id), {})
        model = exact.get("display_value") or aliases.get(("model", item["model_key"]), {}).get("display_value") or item["model_name"]
        color = aliases.get(("color", item["color_key"]), {}).get("display_value") or item["color_name"]
        customer_sku = exact.get("customer_sku")
        model_key, color_key = normalize_text(model).casefold(), normalize_text(color).casefold()
        color_scope = (item["product_kind"], model_key, color_key)
        if color_scope in color_meanings and color_meanings[color_scope][0] != item["color_key"]:
            conflicts.append({"code": "COLOR_AMBIGUOUS", "item_ids": [color_meanings[color_scope][1], item_id]})
        color_meanings.setdefault(color_scope, (item["color_key"], item_id))
        spec = (model_key, color_key, str(item["length"]), str(item["weight"]), item["unit"], item["product_kind"])
        if spec in specs and specs[spec] != item_id:
            conflicts.append({"code": "SPEC_AMBIGUOUS", "item_ids": [specs[spec], item_id]})
        specs.setdefault(spec, item_id)
        if customer_sku:
            normalized = normalize_text(customer_sku).casefold()
            if normalized in customer_skus and customer_skus[normalized] != item_id:
                conflicts.append({"code": "CUSTOMER_SKU_DUPLICATE", "item_ids": [customer_skus[normalized], item_id]})
            customer_skus.setdefault(normalized, item_id)
        result.append({"item_id": item_id, "model_name": model, "color_name": color,
                       "customer_sku": customer_sku, "length": item["length"],
                       "weight": item["weight"], "unit": item["unit"]})
    return result, conflicts


def project_mapping(items: list[dict], entries: list[dict]) -> list[dict]:
    """Customer reads and publication always fail closed on any ambiguity."""
    projected, conflicts = analyze_mapping(items, entries)
    if conflicts:
        # Keep scoped internal comparison IDs out of customer-facing errors.
        messages = {"COLOR_AMBIGUOUS": "Two standard shades have the same customer shade name.",
                    "SPEC_AMBIGUOUS": "Two standard SKUs have the same customer specification.",
                    "CUSTOMER_SKU_DUPLICATE": "Customer SKU must be unique within the catalog."}
        reject("MAPPING_CONFLICT", messages[conflicts[0]["code"]])
    return projected
