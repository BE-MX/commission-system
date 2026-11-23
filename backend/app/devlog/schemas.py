"""采集器上报白名单：只收结构化标识和去敏后的短文本，未知字段与超限整批拒收。"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.time import to_beijing_naive

ItemStatus = Literal["dev", "pending_merge", "pending_push", "pending_release", "released"]
ItemType = Literal["feature", "improve", "bug", "data", "ops", "docs"]
Agent = Literal["codex", "claude", "kimi", "accio", "unknown"]

MigrationId = Annotated[str, Field(max_length=64, pattern=r"^[A-Za-z0-9_]+$")]
ConfigKey = Annotated[str, Field(max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")]
PermissionCode = Annotated[str, Field(max_length=64, pattern=r"^[a-z0-9_]+:[a-z0-9_]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceIn(Strict):
    kind: Literal["branch", "commit", "release", "worktree"]
    ref: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._/@+-]+$")
    at: datetime

    @model_validator(mode="after")
    def validate_identifier(self):
        import re
        if self.kind in ("commit", "release") and not re.fullmatch(r"[0-9a-f]{40}", self.ref):
            raise ValueError("提交和发布证据必须为完整 SHA")
        return self


class Preconditions(Strict):
    migrations: list[MigrationId] = Field(default_factory=list, max_length=20)
    config_keys: list[ConfigKey] = Field(default_factory=list, max_length=20)
    permissions: list[PermissionCode] = Field(default_factory=list, max_length=20)


class ItemIn(Strict):
    key: str = Field(max_length=191, pattern=r"^(branch|merge|commit|batch):[A-Za-z0-9._/@+-]+$")
    title: str = Field(min_length=1, max_length=40)
    type: ItemType
    module: str = Field(default="", max_length=40, pattern=r"^[a-z0-9_]*$")
    agent: Agent = "unknown"
    status: ItemStatus
    status_at: datetime
    last_activity_at: datetime
    stale: bool = False
    unmerged_hotfix: bool = False
    released_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    preconditions: Preconditions = Field(default_factory=Preconditions)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidences: list[EvidenceIn] = Field(default_factory=list, max_length=60)


class SourceState(Strict):
    name: Literal["git", "fetch", "releases"]
    ok: bool
    detail: str = Field(default="", max_length=120)


class IngestIn(Strict):
    started_at: datetime
    finished_at: datetime
    # True 表示 items 是全量；服务端另核对 git/fetch/releases 齐全成功后才隐藏缺席事项
    snapshot: bool = False
    sources: list[SourceState] = Field(max_length=10)
    items: list[ItemIn] = Field(max_length=3000)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("同一次上报里事项键重复")
        names = [source.name for source in self.sources]
        if len(names) != len(set(names)):
            raise ValueError("同一次上报里来源重复")
        if to_beijing_naive(self.finished_at) < to_beijing_naive(self.started_at):
            raise ValueError("采集结束时间早于开始时间")
        return self


class ReleaseIn(Strict):
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    scope: Literal["office-and-cloud", "cloud-only"]
    released_at: datetime


class ReleaseBackfillIn(Strict):
    items: list[ReleaseIn] = Field(max_length=500)
