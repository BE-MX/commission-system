"""AI 草稿：值域运行时注入、输出逐字段校验、失败降级。"""
import json
from datetime import date

import pytest

from app.task import ai_service, module_service, service
from tests.task_helpers import make_user


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    module_service.sync_nav_manifest(db, {"version": 1, "entries": [
        {"key": "ReceiptList", "title": "回款管理", "group_key": "invoice", "group_title": "订单管理", "route": "/receipts", "sort": 2},
    ]})
    return make_user(db, "ai_owner")


def fake_chat(payload, calls):
    def _chat(**kwargs):
        calls.append(kwargs)
        return {"content": "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"}
    return _chat


def test_draft_injects_domain_and_validates(db, owner, monkeypatch):
    parent = service.create_task(db, owner.id, title="回款管理：生产验证收尾", module_key="ReceiptList")
    calls = []
    monkeypatch.setattr("app.ai.service.chat", fake_chat({
        "title": "回款列表按业务员筛选提速", "priority": "P1", "acceptance": ["P95 < 1s", "走索引"],
        "module_key": "ReceiptList", "parent_id": parent.id, "duplicate_ids": [parent.id, 99999],
        "due_date": "2026-10-01",
    }, calls))
    draft = ai_service.draft_task(db, owner.id, "回款列表按业务员筛选很慢，明天搞定",
                                  module_key="ReceiptList", today=date(2026, 9, 30))
    user_msg = json.loads(calls[0]["messages"][0]["content"])
    assert calls[0]["preset_name"] == "task_draft" and calls[0]["caller_module"] == "task"
    assert {m["key"] for m in user_msg["modules"]} >= {"ReceiptList", "custom.report"}
    assert user_msg["priorities"] == {"P0": "紧急", "P1": "高", "P2": "中", "P3": "低"}
    assert user_msg["today"] == "2026-09-30"
    assert draft["title"] == "回款列表按业务员筛选提速" and draft["priority"] == "P1"
    assert draft["parent_id"] == parent.id and draft["due_date"] == "2026-10-01"
    assert [d["id"] for d in draft["duplicates"]] == [parent.id]   # 不存在的 id 被丢弃
    assert draft["degraded"] is False


def test_draft_rejects_out_of_domain_values(db, owner, monkeypatch):
    other = make_user(db, "ai_other")
    foreign = service.create_task(db, other.id, title="别人的")
    monkeypatch.setattr("app.ai.service.chat", fake_chat({
        "title": "", "priority": "P7", "acceptance": "not-a-list", "module_key": "Hacked",
        "parent_id": foreign.id, "duplicate_ids": [foreign.id], "due_date": "明天",
    }, []))
    draft = ai_service.draft_task(db, owner.id, "随便写一句", module_key="ReceiptList")
    assert draft["title"] == "随便写一句" and draft["priority"] == "P2" and draft["acceptance"] == []
    assert draft["module_key"] == "ReceiptList" and draft["parent_id"] is None
    assert draft["duplicates"] == [] and draft["due_date"] is None


def test_draft_degrades_on_ai_failure(db, owner, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr("app.ai.service.chat", boom)
    draft = ai_service.draft_task(db, owner.id, "  写四季度汇报  ", module_key="custom.report")
    assert draft["degraded"] is True and draft["title"] == "写四季度汇报"
    assert draft["module_key"] == "custom.report" and "AI 暂不可用" in draft["notice"]


def test_draft_rejects_empty_text(db, owner):
    from app.task.errors import TaskInvalid
    with pytest.raises(TaskInvalid):
        ai_service.draft_task(db, owner.id, "   ")


def test_draft_degrades_on_malformed_duplicate_ids(db, owner, monkeypatch):
    monkeypatch.setattr("app.ai.service.chat", fake_chat({"title": "整理清单", "priority": "P1", "duplicate_ids": 42}, []))
    draft = ai_service.draft_task(db, owner.id, "整理清单")
    assert draft["degraded"] is True and draft["title"] == "整理清单"


def test_draft_degrades_on_unhashable_module_key(db, owner, monkeypatch):
    monkeypatch.setattr("app.ai.service.chat", fake_chat({"title": "整理清单", "priority": ["P1"], "module_key": {"key": "ReceiptList"}}, []))
    draft = ai_service.draft_task(db, owner.id, "整理清单")
    assert draft["degraded"] is True
