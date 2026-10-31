"""Local shipment commands freeze quantities, warehouse and quote identity."""
from datetime import date
from pydantic import Field
from app.core.time import beijing_today
from app.invoice.settlement_schemas import ShipmentQuote
from app.finance.schemas import Command


class LocalShipmentQuote(ShipmentQuote):
    expected_authority_epoch: int | None = Field(default=None, ge=1)
    business_date: date = Field(default_factory=beijing_today)
    warehouse_id: int = Field(gt=0)


class LocalShipmentCreate(LocalShipmentQuote):
    request_key: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class LocalShipmentAction(Command):
    expected_authority_epoch: int | None = Field(default=None, ge=1)
    business_date: date = Field(default_factory=beijing_today)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    inspection_version: int | None = Field(default=None, ge=0)


class LocalShipmentAudit(LocalShipmentAction):
    settlement_id: int
    operation: str
