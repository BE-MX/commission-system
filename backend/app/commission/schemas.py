"""Explicit native entitlement changes never follow customer reassignment."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class PolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_snapshot_id: int | None = Field(default=None, gt=0)
    salesperson_id: int = Field(gt=0)
    salesperson_attribute: Literal["develop", "distribute"]
    supervisor_id: int | None = Field(default=None, gt=0)
    supervisor_attribute: Literal["develop", "distribute"] | None = None
    second_supervisor_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class BasisResolve(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    snapshot_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1000)
