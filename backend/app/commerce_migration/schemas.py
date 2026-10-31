"""Bounded, reviewed inputs; archives cannot be used to post openings."""
import json
from datetime import date
from typing import Any, Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from app.catalog.schemas import ProductCreate, SkuCreate


class CatalogImport(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    external_product_id: str = Field(min_length=1, max_length=64)
    external_sku_id: str = Field(default='', max_length=64)
    product: ProductCreate
    sku: SkuCreate
    product_active: bool = True
    sku_active: bool = True


class ArchiveImport(BaseModel):
    # Evidence keys and values are opaque JSON, not user-entered identifiers.
    # Global stripping would silently collapse distinct source dictionary keys.
    model_config = ConfigDict(extra='forbid')
    object_type: Literal['order', 'payment', 'outbound', 'inspection', 'production', 'material', 'commission']
    external_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    snapshot: dict[str, Any]

    @model_validator(mode='after')
    def bounded_json(self):
        encoded = json.dumps(self.snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(encoded.encode('utf-8')) > 262144:
            raise ValueError('单条历史快照不得超过256KiB')
        return self


class ImportManifest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    catalog: list[CatalogImport] = Field(default_factory=list, max_length=500)
    archives: list[ArchiveImport] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def unique_sources(self):
        if not self.catalog and not self.archives:
            raise ValueError('清单至少包含一条目录或历史归档记录')
        aliases = [(row.external_product_id, row.external_sku_id) for row in self.catalog]
        archives = [(row.object_type, row.external_id) for row in self.archives]
        if len(set(aliases)) != len(aliases) or len(set(archives)) != len(archives):
            raise ValueError('清单含重复来源身份，请先核对差异')
        if len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False, allow_nan=False).encode('utf-8')) > 4194304:
            raise ValueError('整份清单不得超过4MiB，请按来源对象分批导入')
        return self
