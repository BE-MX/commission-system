"""Activate complete reviewed responsibilities as one atomic cutover command."""
from datetime import date
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActivationSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    record_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique_records(self):
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError('同一来源记录不能重复选择')
        return self


class OrderActivation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_binding_record_id: int = Field(gt=0)
    expected_version: int = Field(strict=True, ge=0)


class ProductionItemActivation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    production_item_id: int = Field(gt=0)
    expected_version: int = Field(strict=True, ge=0)


class ProductionActivation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    production_opening_record_id: int = Field(gt=0)
    items: list[ProductionItemActivation] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique_items(self):
        if len({row.production_item_id for row in self.items}) != len(self.items):
            raise ValueError('同一生产明细不能重复启用')
        return self


class ActivationManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    business_date: date
    orders: list[OrderActivation] = Field(default_factory=list, max_length=100)
    productions: list[ProductionActivation] = Field(default_factory=list, max_length=100)
    handover_preparation_id: int | None = Field(default=None, gt=0)
    expected_authority_epochs: dict[int, int] = Field(default_factory=dict)

    @model_validator(mode='after')
    def unique_orders(self):
        if len({row.order_binding_record_id for row in self.orders}) != len(self.orders):
            raise ValueError('同一原订单不能重复启用')
        if not self.orders and not self.productions:
            raise ValueError('至少启用一条已核验订单或备货生产责任')
        if len({row.production_opening_record_id for row in self.productions}) != len(self.productions):
            raise ValueError('同一原生产不能重复启用')
        return self
