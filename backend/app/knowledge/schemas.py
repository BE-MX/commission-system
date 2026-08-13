"""HTTP input schemas for the knowledge base."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LibraryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    category: Literal["company", "department", "personal"]
    description: str | None = Field(default=None, max_length=512)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    role: Literal["viewer", "editor", "reviewer", "admin"]


class MembersReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[MemberInput]


class DocumentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=256)
    node_type: Literal["document", "folder"] = "document"
    parent_id: int | None = Field(default=None, gt=0)
    content: dict | None = None


class DocumentSave(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=256)
    content: dict


class ReviewInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    remark: str | None = Field(default=None, max_length=512)
    confirm_cross_library_sources: bool = False
