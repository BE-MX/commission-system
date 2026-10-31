"""Locally maintained sales reporting configuration."""
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RosterWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_version: int = Field(ge=0)
    department_id: int | None = Field(default=None, gt=0)
    english_name: str | None = Field(default=None, max_length=128)
    team: str = Field(default="", max_length=100)
    camp: str = Field(default="", max_length=100)
    new_customer_target: int = Field(default=0, ge=0, le=2147483647)
    amount_target: Decimal = Field(default=Decimal(0), ge=0, max_digits=16, decimal_places=2)
    active: bool = True


class DepartmentShare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    department_id: int = Field(gt=0)
    rate: Decimal = Field(gt=0, le=100, max_digits=7, decimal_places=4)


class DepartmentShares(BaseModel):
    department_allocations: list[DepartmentShare] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def valid_shares(self):
        shares = self.department_allocations
        if shares and (sum(item.rate for item in shares) != Decimal(100) or
                len({item.department_id for item in shares}) != len(shares)):
            raise ValueError("部门分摊须无重复且合计100%")
        return self


class AttributionWrite(DepartmentShares):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_./-]+$")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
