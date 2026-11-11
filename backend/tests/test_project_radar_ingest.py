from datetime import timedelta

import pytest

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.core.time import beijing_now
from app.project_radar import ingest
from app.project_radar.dingtalk_inbound import handle_inbound
from app.project_radar.ingest import create_job, process_job, select_candidates
from app.project_radar.models import RadarDialog, RadarSource, RadarSubscription, RadarTarget


@pytest.fixture(autouse=True)
def _public_urls(monkeypatch):
    monkeypatch.setattr("app.mcp.public_web_tools._validate_public_url", lambda url: url)


@pytest.fixture(autouse=True)
def _analysis(monkeypatch):
    def analyze(db, target, text, user_id=None):
        target.one_liner = "AI summary"
        target.ark_modules = []
        return {"analyzed": True}
    monkeypatch.setattr(ingest, "analyze_target", analyze)


class Fetcher:
    def read_target(self, target):
        return {
            "title": target.title, "text": "A useful project readme",
            "facts": {"title": target.title, "version": "v1.2.0", "archived": False},
            "tracked_pages": [],
        }

    def read_clue(self, url):
        return {"title": "Three tools", "text": "Article body", "links": []}


def _user(db, name="ingest-user", *, permission=True, dingtalk_id="dt-ingest"):
    user = ArkUser(username=name, real_name=name, password_hash="x", dingtalk_id=dingtalk_id)
    if permission:
        role = ArkRole(name=f"role-{name}", label="radar")
        permission_row = db.query(ArkPermission).filter_by(code="project_radar:write").first()
        if permission_row is None:
            permission_row = ArkPermission(code="project_radar:write", module="project_radar", action="write", label="write")
        role.permissions = [permission_row]
        user.roles = [role]
    db.add(user)
    db.flush()
    return user


def _process(db, user, raw="https://github.com/a/b #Agent", key="msg-1"):
    job = create_job(db, user.id, raw, channel="dingtalk", request_key=f"dingtalk:{key}")
    db.commit()
    return process_job(db, job, fetcher=Fetcher())


def test_job_and_message_are_idempotent_and_duplicate_only_appends_source(db):
    user = _user(db)
    job = _process(db, user)
    assert job.status == "completed"
    first = db.query(RadarSubscription).one()
    source_count = db.query(RadarSource).count()
    process_job(db, job, fetcher=Fetcher())
    assert db.query(RadarSource).count() == source_count

    duplicate = _process(db, user, key="msg-2")
    assert db.query(RadarSubscription).count() == 1
    assert db.query(RadarSource).count() == source_count + 1
    assert duplicate.result["items"][0]["duplicate"] is True
    assert duplicate.result["items"][0]["subscription_id"] == first.id


def test_multiple_candidates_select_only_requested_and_unconfirmed_never_auto_ingests(db):
    user = _user(db)
    candidates = [
        {"title": "one", "url": "https://github.com/a/one", "confirmed": True},
        {"title": "two", "url": "https://github.com/a/two", "confirmed": True},
        {"title": "three", "url": "https://github.com/a/three", "confirmed": True},
    ]
    job = create_job(db, user.id, "https://mp.weixin.qq.com/s/article", channel="web")
    process_job(db, job, fetcher=Fetcher(), resolver=lambda *args, **kwargs: candidates)
    assert job.status == "awaiting_choice"
    assert db.query(RadarSubscription).count() == 0

    result = select_candidates(db, user.id, "1 3", fetcher=Fetcher())
    assert result["ok"] is True and len(result["items"]) == 2
    assert db.query(RadarSubscription).count() == 2

    other = _user(db, "article-user", dingtalk_id="dt-article")
    article_job = create_job(db, other.id, "https://mp.weixin.qq.com/s/names", channel="web")
    process_job(db, article_job, fetcher=Fetcher(), resolver=lambda *args, **kwargs: [
        {"title": "name only", "url": "", "confirmed": False},
    ])
    assert db.query(RadarSubscription).filter_by(user_id=other.id).count() == 1
    target = db.query(RadarTarget).filter_by(canonical_url="https://mp.weixin.qq.com/s/names").one()
    assert target.kind == "article" and target.scan_enabled is False


def test_selection_context_expires_after_thirty_minutes(db):
    user = _user(db)
    job = create_job(db, user.id, "https://x.com/a/status/123", channel="dingtalk")
    process_job(db, job, fetcher=Fetcher(), resolver=lambda *args, **kwargs: [
        {"title": "one", "url": "https://github.com/a/one", "confirmed": True},
        {"title": "two", "url": "https://github.com/a/two", "confirmed": True},
    ])
    dialog = db.query(RadarDialog).one()
    dialog.expires_at = beijing_now() - timedelta(minutes=1)
    db.commit()
    result = handle_inbound(db, message_id="expired-choice", dingtalk_id=user.dingtalk_id, text="1")
    assert result["reply"] == "上下文已失效，请重新发送链接"
    assert db.query(RadarSubscription).count() == 0


def test_inbound_checks_dingtalk_identity_permission_and_message_id(db):
    denied = _user(db, "no-permission", permission=False, dingtalk_id="dt-denied")
    missing = handle_inbound(db, message_id="m0", dingtalk_id="unknown", text="https://github.com/a/b")
    assert "同步钉钉 ID" in missing["reply"]
    forbidden = handle_inbound(db, message_id="m1", dingtalk_id=denied.dingtalk_id, text="https://github.com/a/b")
    assert "没有项目雷达收录权限" in forbidden["reply"]

    user = _user(db, "allowed", dingtalk_id="dt-allowed")
    accepted = handle_inbound(db, message_id="m2", dingtalk_id=user.dingtalk_id, text="https://github.com/a/b")
    assert accepted["job_id"] and "正在读取" in accepted["reply"]
    repeated = handle_inbound(db, message_id="m2", dingtalk_id=user.dingtalk_id, text="https://github.com/a/b")
    assert repeated["job_id"] == accepted["job_id"] and "无需重复" in repeated["reply"]


def test_reading_job_cannot_be_claimed_twice(db):
    user = _user(db)
    job = create_job(db, user.id, "https://github.com/a/b", channel="web")
    job.status = "reading"
    db.commit()
    process_job(db, job, fetcher=Fetcher())
    assert db.query(RadarSubscription).count() == 0
    assert db.query(RadarSource).count() == 0
