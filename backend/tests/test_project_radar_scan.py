from contextlib import nullcontext
from datetime import datetime

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.project_radar.models import RadarSnapshot, RadarTrackedPage, RadarUpdate
from app.project_radar import scheduler
from app.project_radar.fetcher import RadarFetcher
from app.project_radar.scan import (
    apply_repo_result, compress_text, initialize_target, scan_all, scan_website_target, text_change_ratio,
)
from app.project_radar.service import subscribe


def _subscription(db):
    user = ArkUser(username="scan-user", real_name="scan", password_hash="x")
    db.add(user)
    db.flush()
    subscription = subscribe(db, user.id, "https://github.com/a/b", validator=lambda url: True)
    target = subscription.target if hasattr(subscription, "target") else __import__("app.project_radar.models", fromlist=["RadarTarget"]).RadarTarget
    target = db.get(target, subscription.target_id)
    target.version = "v1.0.0"
    target.last_updated_at = datetime(2026, 11, 1, 8, 0)
    db.flush()
    return subscription, target


def _classifier(db, **kwargs):
    return {"level": kwargs["level"], "reason": "test", "summary": ["有更新"], "ark_impact": ""}


def test_scheduled_scan_classifies_updates_outside_its_savepoint(db, monkeypatch):
    _, target = _subscription(db)
    ai_session = object()
    used_sessions = []

    def classify(session, **kwargs):
        assert db.in_nested_transaction()
        used_sessions.append(session)
        return _classifier(session, **kwargs)

    def fetch(self, target, *, include_content):
        return {"facts": {"version": "v2.0.0"}, "latest_release": None}

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: nullcontext(ai_session))
    monkeypatch.setattr(scheduler, "classify_update", classify)
    monkeypatch.setattr(RadarFetcher, "read_repo", fetch)

    run = scheduler._run_scan(db)

    assert run.success_count == 1 and run.failed_count == 0
    assert used_sessions == [ai_session]
    assert db.query(RadarUpdate).filter_by(target_id=target.id).one().to_version == "v2.0.0"


def test_commit_and_star_changes_do_not_create_update_or_call_ai(db):
    _, target = _subscription(db)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("AI must not be called")

    update = apply_repo_result(db, target, {
        "unchanged": False, "facts": {
            "version": "v1.0.0", "stars": target.stars + 20 if target.stars else 20,
            "last_updated_at": datetime(2026, 11, 10, 8, 0), "archived": False,
        }, "latest_release": None,
    }, classifier=forbidden)
    assert update is None and calls == []
    assert db.query(RadarUpdate).count() == 0
    assert target.stars == 20


def test_breaking_release_creates_key_update_and_unread_marker(db):
    subscription, target = _subscription(db)
    update = apply_repo_result(db, target, {
        "unchanged": False, "facts": {"version": "v2.0.0", "archived": False},
        "latest_release": {"id": 22, "tag_name": "v2.0.0", "body": "Breaking: removed old Controller API", "html_url": "https://github.com/a/b/releases/v2.0.0"},
    }, classifier=_classifier)
    assert update is not None and update.rule_level == "key"
    assert subscription.unread_update_id == update.id
    assert target.last_update_summary == ["有更新"]

    duplicate = apply_repo_result(db, target, {
        "unchanged": False, "facts": {"version": "v2.0.0", "archived": False},
        "latest_release": {"id": 22, "tag_name": "v2.0.0", "body": "Breaking: removed old Controller API"},
    }, classifier=_classifier)
    assert duplicate is None and db.query(RadarUpdate).count() == 1


def test_archived_repository_is_key_without_release(db):
    _, target = _subscription(db)
    update = apply_repo_result(db, target, {
        "unchanged": False, "facts": {"version": "v1.0.0", "archived": True}, "latest_release": None,
    }, classifier=_classifier)
    assert update is not None and update.event_key == "repository-archived"


def test_website_uses_text_diff_threshold_and_compressed_snapshots(db):
    subscription, target = _subscription(db)
    target.kind = "website"
    initialize_target(db, target, {
        "tracked_pages": [{"url": "https://example.com/changelog", "page_kind": "changelog"}],
    })
    page = db.query(RadarTrackedPage).filter_by(target_id=target.id).one()
    before = "\n".join(f"stable line {i}" for i in range(30))
    db.add(RadarSnapshot(target_id=target.id, tracked_page_id=page.id, captured_at=beijing_now(),
                         clean_text_compressed=compress_text(before), text_hash="old"))
    db.flush()

    class Fetcher:
        def read_page(self, url, *, etag=None):
            return {"unchanged": False, "etag": "new", "text": before + "\nnew team plan and new API parameters\n" + "changed\n" * 20}

    updates = scan_website_target(db, target, fetcher=Fetcher(), classifier=_classifier)
    assert len(updates) == 1 and updates[0].raw_ref["change_ratio"] > 0.08
    assert db.query(RadarSnapshot).filter_by(tracked_page_id=page.id).count() == 2
    assert text_change_ratio(before, before) == 0


def test_website_tracks_complete_urls_with_a_shared_long_prefix(db):
    _, target = _subscription(db)
    target.kind = "website"
    prefix = "https://example.com/" + "a" * (1023 - len("https://example.com/"))
    urls = [prefix + "a", prefix + "A"]
    pages = [{"url": url, "page_kind": "changelog"} for url in [*urls, urls[0]]]

    initialize_target(db, target, {"tracked_pages": pages})
    initialize_target(db, target, {"tracked_pages": pages})

    tracked = db.query(RadarTrackedPage).filter_by(target_id=target.id).all()
    assert {page.url for page in tracked} == set(urls)
    assert len({page.url_hash for page in tracked}) == len(tracked) == 2


def test_scan_failure_is_visible_in_health_and_does_not_silent_pass(db):
    _, target = _subscription(db)

    class FailingFetcher:
        def read_repo(self, target, include_content=False):
            raise RuntimeError("synthetic network failure")

    run = scan_all(db, fetcher=FailingFetcher(), classifier=_classifier)
    assert run.total_count == 1 and run.failed_count == 1 and run.status == "failed"
    assert target.consecutive_failures == 1 and target.read_state == "limited"
    assert target.last_error
