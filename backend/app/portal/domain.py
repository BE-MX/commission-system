"""Deterministic transaction rules shared by commands and projections."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.portal.errors import reject


CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")
CUSTOMER_WRITES = frozenset({"quote", "submit", "accept", "reject", "cancel", "reorder"})
PRICE_READS = frozenset({"price", "quote_detail", "amount", "pi"})


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def normalize_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or value.count("@") != 1 or any(c.isspace() for c in value):
        reject("INVALID_INPUT", "Enter a valid email address.", 422)
    local, domain = value.rsplit("@", 1)
    if not local or not domain or any(ord(c) < 33 for c in value):
        reject("INVALID_INPUT", "Enter a valid email address.", 422)
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        reject("INVALID_INPUT", "Enter a valid email address.", 422)
    if "." not in domain or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in domain.split(".")):
        reject("INVALID_INPUT", "Enter a valid email address.", 422)
    result = local.casefold() + "@" + domain
    if len(result) > 254:
        reject("INVALID_INPUT", "Enter a valid email address.", 422)
    return result


def decimal_value(value, *, places=2, positive=False, negative=False) -> Decimal:
    if isinstance(value, (float, bool)):
        reject("INVALID_INPUT", "Use a fixed decimal amount.", 422)
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        reject("INVALID_INPUT", "Use a fixed decimal amount.", 422)
    if not result.is_finite() or abs(result) > MAX_AMOUNT:
        reject("INVALID_INPUT", "Amount is outside the supported range.", 422)
    quantum = Decimal(1).scaleb(-places)
    if result != result.quantize(quantum):
        reject("INVALID_INPUT", "Amount has too many decimal places.", 422)
    if positive and result <= 0 or negative and result > 0:
        reject("INVALID_INPUT", "Amount has an invalid sign.", 422)
    return result.quantize(quantum)


def line_amount(quantity: int, unit_price, discount="0.00") -> Decimal:
    if type(quantity) is not int or not 1 <= quantity <= 10000:
        reject("INVALID_INPUT", "Quantity must be an integer from 1 to 10,000.", 422)
    price = decimal_value(unit_price, places=4, positive=True)
    if price > Decimal("99999999.9999"):
        reject("INVALID_INPUT", "Unit price is outside the supported range.", 422)
    reduction = decimal_value(discount, negative=True)
    gross = (Decimal(quantity) * price).quantize(CENT, rounding=ROUND_HALF_UP)
    amount = gross + reduction
    if amount < 0 or amount > MAX_AMOUNT:
        reject("INVALID_INPUT", "The line amount is outside the supported range.", 422)
    return amount


def total_amount(lines, shipping=None, packaging=None, surcharge=None, *, maximum=MAX_AMOUNT):
    amounts = [decimal_value(line) for line in lines]
    if any(amount < 0 for amount in amounts):
        reject("INVALID_INPUT", "Line amounts cannot be negative.", 422)
    products = sum(amounts, Decimal("0.00"))
    if products < 0 or products > maximum:
        reject("INVALID_INPUT", "Order amount exceeds the permitted limit.", 422)
    fees = [decimal_value(value) for value in (shipping, packaging, surcharge) if value is not None]
    if any(value < 0 for value in fees):
        reject("INVALID_INPUT", "Fees cannot be negative.", 422)
    if any(value is None for value in (shipping, packaging, surcharge)):
        return products, None
    total = products + sum(fees, Decimal("0.00"))
    if total > min(maximum, MAX_AMOUNT):
        reject("INVALID_INPUT", "Order amount exceeds the permitted limit.", 422)
    return products, total


def _json_default(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimal cannot be hashed")
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")


def content_hash(payload: dict) -> str:
    envelope = {"hash_schema": 1, "payload": payload}
    wire = json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=_json_default, allow_nan=False)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def require_capability(action, *, can_order: bool, can_view_price: bool):
    if action in CUSTOMER_WRITES and not (can_order and can_view_price):
        reject("ACTION_FORBIDDEN", "Ordering is not enabled for your account.", 403)
    if action in PRICE_READS and not can_view_price:
        reject("ACTION_FORBIDDEN", "Price access is not enabled for your account.", 403)
    if action not in CUSTOMER_WRITES | PRICE_READS | {"catalog", "order_status", "logout"}:
        reject("ACTION_FORBIDDEN", "This action is not available.", 403)


def require_version(actual: int, expected: int | None):
    if expected is None:
        reject("VERSION_REQUIRED", "Refresh this page before continuing.", 428)
    if type(expected) is not int or actual != expected:
        reject("VERSION_CONFLICT", "This record has changed. Refresh and review it.")


def require_fresh(expires_at: datetime, now: datetime, code="PROPOSAL_EXPIRED"):
    if now >= expires_at:
        reject(code, "This offer has expired. Request an updated offer.")


def request_transition(state: str, action: str) -> str:
    transitions = {
        ("submitted", "propose"): "awaiting_customer",
        ("awaiting_customer", "accept"): "ready_for_review",
        ("awaiting_customer", "reject_proposal"): "submitted",
        ("ready_for_review", "propose"): "awaiting_customer",
        ("ready_for_review", "approve"): "invoice_created",
    }
    if action in {"cancel", "reject"} and state in {"submitted", "awaiting_customer", "ready_for_review"}:
        return "cancelled" if action == "cancel" else "rejected"
    result = transitions.get((state, action))
    if result is None:
        reject("INVOICE_ALREADY_CREATED" if state == "invoice_created" else "VERSION_CONFLICT",
               "This action is no longer available.")
    return result


def amendment_transition(state: str, action: str, *, expired=False) -> str:
    if action == "edit" and state in {"current", "withdrawn", "pending_customer", "accepted"}:
        return "withdrawn"
    if action == "propose" and (state == "withdrawn" or expired and state in {"pending_customer", "accepted"}):
        return "pending_customer"
    if (state, action) == ("pending_customer", "accept"):
        return "accepted"
    if (state, action) == ("pending_customer", "reject"):
        return "withdrawn"
    if (state, action) == ("accepted", "publish"):
        return "current"
    reject("PI_REVISION_PENDING", "Review the current invoice revision before continuing.")
