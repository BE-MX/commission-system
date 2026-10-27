"""Bounded plain-text payloads suitable for old Kindle devices."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class DeviceInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class NoteInput(BaseModel):
    title: Title
    body: str = Field(min_length=1, max_length=2000)


class NoteUpdate(NoteInput):
    version: int = Field(ge=1)


class VersionInput(BaseModel):
    version: int = Field(ge=1)


class MessageInput(BaseModel):
    title: Title
    body: str = Field(min_length=1, max_length=1000)
    priority: Literal["normal", "high"] = "normal"
    request_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,80}$")]


class ReceiptInput(BaseModel):
    ids: list[Annotated[int, Field(gt=0)]] = Field(max_length=20)
    read: bool = False
