"""ingest 只接受白名单字段；未知字段、超长文本、非法键整批拒收。机器 token 支持轮换。"""
import hashlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import get_settings
from app.devlog.machine_auth import _require_devlog_machine
from app.devlog.schemas import IngestIn

ITEM = {
    "key": "branch:codex/cross-border-review", "title": "Add 9610 cross-border review", "type": "feature",
    "module": "cross_border", "agent": "codex", "status": "pending_release",
    "status_at": "2026-11-23T09:05:00", "last_activity_at": "2026-11-23T09:05:00",
    "fingerprint": "a" * 64, "evidences": [{"kind": "commit", "ref": "b" * 40, "at": "2026-11-23T09:05:00"}],
}
RUN = {"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
       "sources": [{"name": "git", "ok": True}], "items": [ITEM]}


def test_valid_payload_parses():
    payload = IngestIn.model_validate(RUN)
    assert payload.items[0].preconditions.migrations == []


@pytest.mark.parametrize("patch", [
    {"raw_text": "会话原文"},                       # 未知字段
    {"title": "x" * 41},                            # 超长标题
    {"key": "session:abc"},                         # 非法键前缀
    {"evidences": [{"kind": "session", "ref": "x", "at": "2026-11-23T09:00:00"}]},  # 非法证据类型
    {"evidences": [{"kind": "commit", "ref": "客户张三", "at": "2026-11-23T09:00:00"}]},  # 证据只允许标识字符
])
def test_rejects_non_whitelisted_content(patch):
    with pytest.raises(ValidationError):
        IngestIn.model_validate({**RUN, "items": [{**ITEM, **patch}]})


def test_rejects_duplicate_keys_in_one_payload():
    with pytest.raises(ValidationError):
        IngestIn.model_validate({**RUN, "items": [ITEM, ITEM]})


def test_batch_key_and_snapshot_flag():
    payload = IngestIn.model_validate({**RUN, "snapshot": True, "items": [{**ITEM, "key": "batch:20261123-invoice-codex"}]})
    assert payload.snapshot is True


def test_machine_token_accepts_any_registered_hash(monkeypatch):
    old, new = "o" * 32, "n" * 32
    hashes = ",".join(hashlib.sha256(t.encode()).hexdigest() for t in (old, new))
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashes)
    assert _require_devlog_machine(x_devlog_token=old) is None
    assert _require_devlog_machine(x_devlog_token=new) is None
    with pytest.raises(HTTPException) as err:
        _require_devlog_machine(x_devlog_token="z" * 32)
    assert err.value.status_code == 401


def test_machine_token_rejected_when_unconfigured(monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", "")
    with pytest.raises(HTTPException):
        _require_devlog_machine(x_devlog_token="o" * 32)
