from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SpecText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=128)]
Quantity = Annotated[int, Field(strict=True, gt=0, le=1_000_000)]
AliasKind = Literal["process", "color", "grade"]
InheritedField = Literal["order_ref", "grade", "process", "length", "color", "weight", "quantity", "unit"]


class TranscribedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(gt=0, le=500)
    raw: str = Field(min_length=1, max_length=1000)
    order_ref: SpecText | None
    grade: SpecText | None
    process: SpecText | None
    length: SpecText | None
    color: SpecText | None
    weight: SpecText | None
    quantity: Quantity | None
    unit: SpecText | None
    line_type: str = Field(min_length=1, max_length=24)
    inherited: list[InheritedField] = Field(max_length=8)
    doubts: list[SpecText] = Field(max_length=12)


class RecognitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_no: str | None = Field(pattern=r"^[0-9]{1,32}$")
    month: int | None = Field(ge=1, le=12)
    day: int | None = Field(ge=1, le=31)
    lines: list[TranscribedLine] = Field(min_length=1, max_length=150)

    @model_validator(mode="after")
    def validate_rows(self):
        if len({row.row for row in self.lines}) != len(self.lines):
            raise ValueError("Duplicate row numbers")
        return self


class Versioned(BaseModel):
    version: int = Field(ge=1)


class Recognize(Versioned):
    original: bool = False


class ConfirmDelivery(Versioned):
    delivery_no: str = Field(pattern=r"^[0-9]{1,32}$")
    confirmed: Literal[True]


PositiveId = Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]


class PreviewBatch(Versioned):
    model_config = ConfigDict(extra="forbid")

    line_ids: list[PositiveId] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def distinct_lines(self):
        if len(self.line_ids) != len(set(self.line_ids)):
            raise ValueError("到货明细不能重复选择")
        return self


class SkuUnitPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: PositiveId
    sku_id: PositiveId
    unit_price: Annotated[int, Field(strict=True, gt=0, le=9_007_199_254_740_991)]


class ConfirmBatch(PreviewBatch):
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,64}$")
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    unit_prices: list[SkuUnitPrice] = Field(min_length=1, max_length=500)
    confirm_cross: bool = False


class VoidNote(Versioned):
    duplicate: bool = False
    reason: str = Field(min_length=1, max_length=255)


class LineFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_ref_raw: SpecText | None = None
    grade_raw: SpecText | None = None
    process_raw: SpecText | None = None
    length_raw: SpecText | None = None
    color_raw: SpecText | None = None
    weight_raw: SpecText | None = None
    quantity: Quantity | None = None
    quantity_unit: SpecText | None = None
    line_type: str | None = Field(default=None, max_length=24)


class OrderChoice(BaseModel):
    kind: Literal["production_order", "invoice"]
    id: int = Field(gt=0)


class LineChoice(BaseModel):
    sku_id: int | None = Field(default=None, gt=0)
    order: OrderChoice | None = None
    route: Literal["cross", "inbound_only", "reselect", "order"] | None = None
    confirm_conversion: bool = False
    suggest_color_alias: bool = False


class PatchLine(Versioned):
    patch: LineFields | None = None
    select: LineChoice | None = None
    selected: bool | None = None
    writeback_enabled: bool | None = None
    refresh: bool = False

    @model_validator(mode="after")
    def validate_changes(self):
        if self.refresh and (self.patch is not None or self.select is not None):
            raise ValueError("Refresh and edit must be submitted separately")
        return self


class CreateLine(Versioned):
    values: LineFields


class AliasChange(BaseModel):
    factory_term: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    enabled: bool = True


class ReviewSuggestion(BaseModel):
    accept: bool
