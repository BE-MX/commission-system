"""Explicit current balances; historical movements are never replayed."""
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StockOpening(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=128)
    mode: Literal['initialize', 'acknowledge_existing']
    warehouse_id: int = Field(gt=0)
    local_sku_id: int = Field(gt=0)
    quality: Literal['sellable', 'quarantine', 'damaged']
    on_hand: int = Field(strict=True, ge=0, le=2147483647)
    reserved: int = Field(default=0, strict=True, ge=0, le=2147483647)

    @model_validator(mode='after')
    def quantities(self):
        if self.reserved > self.on_hand or (self.mode == 'initialize' and self.reserved):
            raise ValueError('实存须覆盖预占；新期初预占必须由已承接销售责任建立')
        if self.quality != 'sellable' and self.reserved:
            raise ValueError('非合格库存不能承接销售预占')
        return self


class MaterialOpening(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=128)
    mode: Literal['initialize', 'acknowledge_existing']
    material_id: int = Field(gt=0)
    on_hand_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reserved_grams: Decimal = Field(default=Decimal('0'), ge=0, max_digits=14, decimal_places=3)

    @model_validator(mode='after')
    def quantities(self):
        if self.reserved_grams > self.on_hand_grams or (self.mode == 'initialize' and self.reserved_grams):
            raise ValueError('实存须覆盖占用；新期初占用必须由已承接物料责任建立')
        return self


class InventoryOpeningManifest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    stocks: list[StockOpening] = Field(default_factory=list, max_length=500)
    materials: list[MaterialOpening] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def identities(self):
        if not self.stocks and not self.materials:
            raise ValueError('至少提供一条库存或物料期初')
        for rows, keys in ((self.stocks, [(r.warehouse_id, r.local_sku_id, r.quality) for r in self.stocks]),
                           (self.materials, [r.material_id for r in self.materials])):
            if len(set(keys)) != len(keys) or len({r.external_id for r in rows}) != len(rows):
                raise ValueError('同一目标余额或来源身份只能在清单中出现一次')
        return self
