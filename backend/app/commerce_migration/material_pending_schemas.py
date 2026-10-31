"""Definitive old operation results; an unknown result is never a release."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaterialResolutionLine(BaseModel):
    model_config = ConfigDict(extra='forbid')
    existing_allocation_id: int = Field(gt=0)
    material_id: int = Field(gt=0)
    allocated_qty_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    pending_delta_grams: Decimal = Field(max_digits=14, decimal_places=3)
    pending_at: datetime
    expected_balance_version: int = Field(strict=True, ge=0)
    on_hand_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reserved_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)

    @model_validator(mode='after')
    def valid_delta(self):
        if (self.pending_at.tzinfo is not None or not self.pending_delta_grams or self.allocated_qty_grams + self.pending_delta_grams < 0
                or self.reserved_grams > self.on_hand_grams):
            raise ValueError('原未决用量、已领量、北京时间或库存组成不守恒')
        return self


class MaterialResolution(BaseModel):
    model_config = ConfigDict(extra='forbid')
    invoice_id: int = Field(gt=0)
    source_order_id: str = Field(min_length=1, max_length=64)
    operation_key: str = Field(min_length=1, max_length=64)
    outcome: Literal['accepted', 'not_accepted']
    evidence_reference: str = Field(min_length=1, max_length=500)
    source_material_record_id: int = Field(gt=0)
    allocations: list[MaterialResolutionLine] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def complete_operation(self):
        if (not self.evidence_reference.strip()
                or len({row.existing_allocation_id for row in self.allocations}) != len(self.allocations)
                or len({row.material_id for row in self.allocations}) != len(self.allocations)):
            raise ValueError('原操作须有明确核验依据、北京时间及完整不重复的物料责任')
        return self


class MaterialResolutionManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    resolutions: list[MaterialResolution] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def reviewed_results(self):
        if (not self.review_reference.strip() or len({row.invoice_id for row in self.resolutions}) != len(self.resolutions)
                or any(line.pending_at.date() > self.cutover_date for row in self.resolutions for line in row.allocations)):
            raise ValueError('未决处置须逐单核验，原操作不能晚于切换日')
        if len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('核验清单超过4MiB')
        return self
