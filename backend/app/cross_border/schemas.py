from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

ContentHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ListFilters(BaseModel):
    view: Literal["all", "blocked", "ready", "reminders", "exported", "exceptions"] = "blocked"
    q: str = ""
    shop: str = ""
    logistics: str = ""
    issue: str = ""
    import_id: int | None = Field(None, gt=0)
    bound_date_from: date | None = None
    bound_date_to: date | None = None
    salesperson: str = ""
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)


class ReviewRequest(BaseModel):
    action: Literal["confirm_shipped", "assign_ticket", "exclude", "void"]
    reason: Reason
    target: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def assignment_target(self):
        if (self.action == "assign_ticket") != (self.target is not None):
            raise ValueError("仅指定配对时须提供目标运单")
        return self


class ExportRequest(BaseModel):
    content_hashes: list[ContentHash] = Field(min_length=1, max_length=10000)
    confirm_reexport: bool = False
    confirm_suspected: bool = False
    reason: Reason | None = None

    @model_validator(mode="after")
    def distinct_entries(self):
        if len(self.content_hashes) != len(set(self.content_hashes)):
            raise ValueError("同一条申报不能重复选中")
        return self
