"""Fail-closed inventory observation validation; quantities never imply reservation."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.portal.errors import reject


@dataclass(frozen=True)
class InventoryObservation:
    quantity: Decimal
    unit: str
    observed_at: datetime
    source: str


def validate_observation(observation: InventoryObservation | None, *, now: datetime,
                         max_age_seconds: int, quantity: int, inventory_unit: str,
                         conversion_factor: Decimal, safety_buffer: Decimal,
                         minimum: int = 1, step: int = 1, stock_threshold: Decimal = Decimal("0")):
    if observation is None or not observation.observed_at or not observation.source:
        reject("INVENTORY_UNAVAILABLE", "Inventory cannot be confirmed right now.", 503)
    if type(quantity) is not int or quantity < minimum or step <= 0 or quantity % step:
        reject("INVALID_INPUT", "Quantity does not meet the minimum or increment.", 422)
    if not isinstance(observation.quantity, Decimal) or not observation.quantity.is_finite() or observation.quantity < 0:
        reject("INVENTORY_UNAVAILABLE", "Inventory quantity is not reliable.", 503)
    if not conversion_factor.is_finite() or conversion_factor <= 0 or not safety_buffer.is_finite() or safety_buffer < 0:
        reject("INVENTORY_UNAVAILABLE", "The inventory unit is not configured.", 503)
    if observation.unit != inventory_unit or not inventory_unit:
        reject("INVENTORY_UNAVAILABLE", "The inventory unit cannot be verified.", 503)
    age = (now - observation.observed_at).total_seconds()
    if age < 0 or age > max_age_seconds or max_age_seconds <= 0:
        reject("INVENTORY_UNAVAILABLE", "Inventory information needs to be refreshed.", 503)
    if not stock_threshold.is_finite() or stock_threshold < 0:
        reject("INVENTORY_UNAVAILABLE", "The inventory threshold is not configured.", 503)
    if observation.quantity < stock_threshold:
        reject("STOCK_CHANGED", "Available inventory has changed. Review the quantity.")
    available = max(Decimal("0"), observation.quantity - safety_buffer)
    if Decimal(quantity) * conversion_factor > available:
        reject("STOCK_CHANGED", "Available inventory has changed. Review the quantity.")


def item_stock_threshold(item):
    """Family thresholds are in inventory units; ungrouped defaults use sale units."""
    if item.family_id is not None:
        return item.safety_buffer
    name = " ".join(str((item.standard_json or {}).get("product_display") or "").lower().replace("_", " ").replace("-", " ").split())
    units = 5 if "butterfly" in name else 200 if any(value in name for value in ("tape hair", "k tape", "nano tape", "i tape")) else 30
    return Decimal(units) * item.conversion_factor
