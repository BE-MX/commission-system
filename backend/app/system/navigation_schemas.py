"""Personal navigation configuration; never accept an owner from the client."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NavigationKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class NavigationPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NavigationKey] = Field(default_factory=list, max_length=200)

    @field_validator("items")
    @classmethod
    def unique_items(cls, items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))
