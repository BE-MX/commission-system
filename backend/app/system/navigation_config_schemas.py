"""Strict navigation mutation preconditions."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class NavigationPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    draft_revision: int = Field(ge=0)
    base_version: int = Field(ge=0)
    catalog_hash: str = Field(min_length=64, max_length=64)


class NavigationDraftSave(NavigationPrecondition):
    nodes: list[dict[str, Any]] = Field(max_length=1000)


class NavigationPublish(NavigationPrecondition):
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
