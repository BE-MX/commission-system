"""Catalog maintenance inputs; code and SKU unit are stable identities."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=512)
    display_name: str = Field(min_length=1, max_length=256)
    kind: Literal["hair", "accessory"] = "hair"
    model: str | None = Field(None, max_length=200)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=512)
    display_name: str = Field(min_length=1, max_length=256)
    model: str | None = Field(None, max_length=200)
    active: bool


class SkuCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    color: str = Field(default="", max_length=128)
    size: str = Field(default="", max_length=128)
    curl: str | None = Field(None, max_length=64)
    weight_grams: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=3)


class SkuStatus(BaseModel):
    active: bool
