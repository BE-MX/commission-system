"""Stable identity helpers for invoices imported from external OKKI screenshots."""

import hashlib
import re


EXTERNAL_SOURCE_PREFIX = "external:"


def normalize_order_name(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def external_source_key(customer_id, order_name) -> str | None:
    customer = str(customer_id or "").strip()
    normalized_name = normalize_order_name(order_name)
    if not customer or not normalized_name:
        return None
    digest = hashlib.sha256(f"{customer}\0{normalized_name}".encode("utf-8")).hexdigest()
    return f"{EXTERNAL_SOURCE_PREFIX}{digest[:55]}"


def is_external_source_key(value) -> bool:
    return str(value or "").startswith(EXTERNAL_SOURCE_PREFIX)
