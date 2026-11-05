"""Explicit user intent for a personal Alibaba record link."""
from pydantic import BaseModel, ConfigDict, Field


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(gt=0)
    company_id: int = Field(gt=0)
    expected_mapping_version: int = Field(gt=0)
    client_request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9._:-]+$")
