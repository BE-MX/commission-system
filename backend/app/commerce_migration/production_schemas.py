"""Full production faces, actual acceptance and remaining sales supplies."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HistoricalSupply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_binding_record_id: int = Field(gt=0)
    source_item_id: str = Field(min_length=1, max_length=64)
    existing_supply_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    received_quantity: int = Field(strict=True, ge=0, le=2147483647)
    released_quantity: int = Field(strict=True, ge=0, le=2147483647)

    @model_validator(mode='after')
    def remaining(self):
        if self.received_quantity + self.released_quantity > self.quantity:
            raise ValueError('原供货已交付与已释放不能超过原计划件数')
        return self


class HistoricalProductionMaterial(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_material_record_id: int = Field(gt=0)
    existing_material_id: int | None = Field(default=None, gt=0)
    material_id: int = Field(gt=0)
    issued_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    returned_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    loss_grams: Decimal = Field(ge=0, max_digits=14, decimal_places=3)

    @model_validator(mode='after')
    def grams(self):
        if self.returned_grams + self.loss_grams > self.issued_grams:
            raise ValueError('原退料与损耗不能超过原实际领料克数')
        return self


class HistoricalProcessProgress(BaseModel):
    model_config = ConfigDict(extra='forbid')
    existing_progress_id: int | None = Field(default=None, gt=0)
    process_id: int = Field(gt=0)
    step_order: int = Field(strict=True, gt=0, le=32767)
    status: Literal[0, 1]
    completed_at: datetime | None
    completed_by_user_id: int | None = Field(gt=0)
    completed_by_wx_id: str | None = Field(max_length=100)

    @model_validator(mode='after')
    def evidence(self):
        if self.status == 1:
            if self.completed_at is None or self.completed_at.tzinfo is not None or not (self.completed_by_user_id or self.completed_by_wx_id):
                raise ValueError('原已完成工序必须保留北京时间及原操作人身份')
        elif self.completed_at or self.completed_by_user_id or self.completed_by_wx_id:
            raise ValueError('原未完成工序不能制造报工人员或完成时间')
        return self


class HistoricalProductionItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_item_id: str = Field(min_length=1, max_length=64)
    existing_item_id: int | None = Field(default=None, gt=0)
    catalog_record_id: int = Field(gt=0)
    local_sku_id: int = Field(gt=0)
    legacy_product_id: int | None = Field(default=None, gt=0)
    product_name: str = Field(min_length=1, max_length=512)
    model: str | None = Field(max_length=200)
    spec_info: str | None = Field(max_length=255)
    process_route_id: int | None = Field(gt=0)
    order_quantity: int = Field(strict=True, gt=0, le=2147483647)
    completed_quantity: int = Field(strict=True, ge=0, le=2147483647)
    received_quantity: int = Field(strict=True, ge=0, le=2147483647)
    source_status: int = Field(strict=True, ge=0, le=2)
    terminated: bool
    is_urgent: bool
    expected_delivery_date: date | None
    remark: str | None = Field(max_length=500)
    supplies: list[HistoricalSupply] = Field(max_length=500)
    materials: list[HistoricalProductionMaterial] = Field(max_length=100)
    progress: list[HistoricalProcessProgress] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def complete_faces(self):
        received = sum(s.received_quantity for s in self.supplies)
        planned = sum(s.quantity - s.released_quantity for s in self.supplies)
        if (not self.received_quantity <= self.completed_quantity <= self.order_quantity
                or received > self.received_quantity or planned > self.order_quantity
                or planned - received > self.order_quantity - self.received_quantity):
            raise ValueError('原生产合同、完工、实际入库与供货件数不守恒')
        if self.terminated and planned > received:
            raise ValueError('已终止生产不能保留未交付销售承诺')
        if self.terminated and self.completed_quantity != self.received_quantity:
            raise ValueError('原已终止生产仍有已完工未验收实物，须先核验处置，不能隐藏在途')
        if (self.source_status == 1) != self.terminated:
            raise ValueError('原终止状态须与核验终止事实一致')
        if (len({(s.order_binding_record_id, s.source_item_id) for s in self.supplies}) != len(self.supplies)
                or len({m.material_id for m in self.materials}) != len(self.materials)):
            raise ValueError('原供货行或原领料物料身份重复')
        if len({p.process_id for p in self.progress}) != len(self.progress) or len({p.step_order for p in self.progress}) != len(self.progress):
            raise ValueError('原工序与顺序只能出现一次')
        if self.progress and self.process_route_id is None:
            raise ValueError('原工序进度缺少核验路线')
        return self


class HistoricalProduction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_production_id: str = Field(min_length=1, max_length=64)
    existing_order_id: int | None = Field(default=None, gt=0)
    order_no: str = Field(min_length=1, max_length=32)
    batch_no: str = Field(min_length=1, max_length=64)
    source_status: int = Field(strict=True, ge=0, le=2)
    remark: str | None = Field(max_length=500)
    items: list[HistoricalProductionItem] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def identities(self):
        for key in ('source_item_id', 'existing_item_id'):
            values = [getattr(item, key) for item in self.items if getattr(item, key) is not None]
            if len(set(values)) != len(values):
                raise ValueError('原生产明细或本地生产明细只能出现一次')
        return self


class ProductionOpeningManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    productions: list[HistoricalProduction] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def identities(self):
        if not self.review_reference.strip():
            raise ValueError('原生产责任须有明确核验依据')
        for key in ('source_production_id', 'existing_order_id', 'order_no', 'batch_no'):
            values = [getattr(row, key) for row in self.productions if getattr(row, key) is not None]
            if len(set(values)) != len(values):
                raise ValueError('原生产身份、批次及单号不能重复')
        if len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode('utf-8')) > 4194304:
            raise ValueError('整份生产责任清单不得超过4MiB')
        return self
