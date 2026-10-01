"""每日简报：确定性排序、AI 选前三（只许从候选里选）、模板降级、同日幂等、钉钉推送。"""
import json
from datetime import date

import pytest

from app.task import brief_service, module_service, service
from app.task.models import TaskBrief
from tests.task_helpers import make_user

TODAY = date(2026, 9, 30)


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    return make_user(db, "brief_owner", dingtalk_id="ding-brief")


def seed(db, owner_id):
    overdue = service.create_task(db, owner_id, title="逾期的", priority="P1", due_date="2026-09-26")
    p0 = service.create_task(db, owner_id, title="紧急的", priority="P0")
    soon = service.create_task(db, owner_id, title="今天到期", priority="P2", due_date="2026-09-30")
    later = service.create_task(db, owner_id, title="不急", priority="P3")
    parent = service.create_task(db, owner_id, title="父任务", priority="P0")
    service.create_task(db, owner_id, title="父的子", priority="P2", parent_id=parent.id)
    done = service.create_task(db, owner_id, title="已完成", priority="P0")
    service.change_status(db, owner_id, done.id, "done")
    return overdue, p0, soon, later


def test_rank_orders_p0_then_overdue_then_due(db, owner):
    seed(db, owner.id)
    titles = [t.title for t in brief_service.rank_candidates(db, owner.id, TODAY)]
    assert titles == ["紧急的", "逾期的", "今天到期", "父的子", "不急"]   # 父任务与已完成不参与


def test_template_brief_reasons(db, owner):
    seed(db, owner.id)
    content = brief_service.build_template(db, owner.id, TODAY)
    reasons = {t["title"]: t["reason"] for t in content["top"]}
    assert reasons == {"紧急的": "P0 紧急", "逾期的": "已逾期 4 天", "今天到期": "今天到期"}
    assert content["overdue"] == 1 and content["pending_confirm"] == 0


def test_ai_brief_only_accepts_candidate_ids(db, owner, monkeypatch):
    overdue, p0, soon, later = seed(db, owner.id)
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return {"content": json.dumps({"top": [
            {"id": later.id, "reason": "顺手做"}, {"id": 999999, "reason": "编的"}, {"id": p0.id, "reason": "卡住别人"},
        ]}, ensure_ascii=False)}
    monkeypatch.setattr("app.ai.service.chat", fake_chat)
    content, source = brief_service.build_content(db, owner.id, TODAY)
    assert source == "ai" and calls[0]["preset_name"] == "task_brief"
    assert [t["id"] for t in content["top"]] == [later.id, p0.id]
    assert content["top"][1]["reason"] == "卡住别人"


def test_ai_failure_falls_back_to_template(db, owner, monkeypatch):
    seed(db, owner.id)
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "not json"})
    content, source = brief_service.build_content(db, owner.id, TODAY)
    assert source == "template" and len(content["top"]) == 3


def test_get_or_create_is_idempotent_per_day(db, owner, monkeypatch):
    seed(db, owner.id)
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "{}"})
    first = brief_service.get_or_create_brief(db, owner.id, TODAY)
    second = brief_service.get_or_create_brief(db, owner.id, TODAY)
    assert first.id == second.id and db.query(TaskBrief).count() == 1


def test_markdown_contains_top_and_counts(db, owner):
    seed(db, owner.id)
    md = brief_service.render_markdown(brief_service.build_template(db, owner.id, TODAY), TODAY)
    assert "09/30" in md and "紧急的" in md and "逾期 1" in md


async def test_prepare_send_mark_pushes_once_per_day(db, owner, monkeypatch):
    seed(db, owner.id)
    make_user(db, "brief_no_ding")   # 没有钉钉 ID、也没有任务的用户不参与
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "{}"})
    sent = []

    class FakeNotifier:
        async def send_to_users(self, user_ids, title, markdown_text):
            sent.append((user_ids, title))
            return True

    monkeypatch.setattr("app.dingtalk.work_notify.get_work_notifier", lambda: FakeNotifier())
    pushes = brief_service.prepare_pushes(db, TODAY)
    assert [p["dingtalk_id"] for p in pushes] == ["ding-brief"]
    ok_ids = await brief_service.send_pushes(pushes)
    brief_service.mark_pushed(db, ok_ids)
    assert sent == [(["ding-brief"], "任务简报 09/30")]
    assert db.query(TaskBrief).one().pushed_at is not None
    assert brief_service.prepare_pushes(db, TODAY) == []   # 同日已推送，不再准备
