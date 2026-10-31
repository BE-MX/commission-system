"""Acknowledge original invoice material issues after physical stock is reconciled."""
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HistoricalMaterialAllocation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_binding_record_id: int = Field(gt=0)
    existing_allocation_id: int = Field(gt=0)
    source_material_record_id: int = Field(gt=0)
    material_id: int = Field(gt=0)
    allocated_qty_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)


class MaterialOpeningManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    allocations: list[HistoricalMaterialAllocation] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def identities(self):
        if not self.review_reference.strip() or len({row.existing_allocation_id for row in self.allocations}) != len(self.allocations):
            raise ValueError('原半成品扣量须有核验依据，责任身份不能重复')
        return self
