"""Validated commands for analysis-owned state."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.domestic_decision.schemas import AnalysisRequest


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewCreate(Command):
    name: str = Field(min_length=1, max_length=80)
    query: AnalysisRequest
    time_mode: Literal["rolling", "fixed"] = "rolling"
    shared: bool = False


class ViewUpdate(ViewCreate):
    expected_version: int = Field(ge=1)


class ActionCreate(Command):
    run_id: str
    customer_id: int = Field(gt=0)
    rule_key: str = Field(min_length=1, max_length=64)
    request_key: str = Field(min_length=8, max_length=64)
    due_date: date


class ActionUpdate(Command):
    expected_version: int = Field(ge=1)
    status: Literal["todo", "in_progress", "done", "dismissed"]
    result: str = Field(default="", max_length=2000)
    result_type: Literal["contacted", "ordered", "recharged", "reconciled", "no_response", "other"] | None = None


class JobCreate(Command):
    run_id: str
    request_key: str = Field(min_length=8, max_length=64)
    focus: Literal["executive", "customer", "product", "finance"] = "executive"
    format: Literal["csv", "json"] = "csv"


class PlanCreate(JobCreate):
    question: str = Field(min_length=3, max_length=500)


class MappingCreate(Command):
    property: Literal["color", "craft", "size"]
    product_type: Literal["", "cap", "piece"] = ""
    raw_value: str = Field(min_length=1, max_length=255)
    standard_value: str = Field(min_length=1, max_length=255)
    expected_version: int | None = Field(default=None, ge=1)


class ConfigUpdate(Command):
    expected_version: int = Field(ge=0)
    value: object
