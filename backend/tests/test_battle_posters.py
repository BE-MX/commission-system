"""Isolated SQLite; never send real webhook messages or read production data."""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.battle_report import pace, poster_delivery, poster_images, poster_renderer, poster_service
from app.battle_report.models import BattleReport, BattleReportDelivery
from app.battle_report.schemas import PosterConfigUpdate
from app.core.config import get_settings
from app.dingtalk.webhook import DingTalkWebhookError
from tests.test_battle_reports import setup, become  # shared real-route, isolated-DB fixture


def campaign(**values):
    return SimpleNamespace(start_date=date(2026, 9, 22), end_date=date(2026, 9, 30), work_dates=None, **values)


@pytest.mark.parametrize("stamp,completed,percent", [
    ("2026-09-21T23:59:59+08:00", 0, 0), ("2026-09-22T15:59:59+08:00", 0, 0),
    ("2026-09-22T16:00:00+08:00", 1, 16.66), ("2026-09-22T08:00:00+00:00", 1, 16.66),
    ("2026-09-22T16:00:00-07:00", 1, 16.66), ("2026-09-23T16:00:00+08:00", 2, 33.32),
    ("2026-09-24T16:00:00+08:00", 3, 49.98), ("2026-09-25T17:30:00+08:00", 3, 49.98),
    ("2026-09-26T17:30:00+08:00", 3, 49.98), ("2026-09-27T17:30:00+08:00", 3, 49.98),
    ("2026-09-28T16:00:00+08:00", 4, 66.64), ("2026-09-29T16:00:00+08:00", 5, 83.30),
    ("2026-09-30T15:59:59+08:00", 5, 83.30), ("2026-09-30T16:00:00+08:00", 6, 100),
    ("2026-10-01T00:00:00+08:00", 6, 100), ("2026-09-22T16:00:00+00:00", 1, 16.66),
])
def test_calendar_boundaries(stamp, completed, percent):
    result = pace.calendar_progress(campaign(), datetime.fromisoformat(stamp))
    assert (result["completed"], result["percent"]) == (completed, percent)


@pytest.mark.parametrize("stamp,slot", [
    ("2026-09-22T13:00:00+08:00", "13:00"),
    ("2026-09-22T13:05:00+08:00", "13:00"),
    ("2026-09-22T17:00:00+08:00", None),
    ("2026-09-22T17:01:00+08:00", "17:01"),
    ("2026-09-22T09:01:00+00:00", "17:01"),
    ("2026-09-22T17:06:00+08:00", "17:01"),
    ("2026-09-22T17:16:00+08:00", "17:01"),
    ("2026-09-22T17:05:00+08:00", None),
])
def test_poster_due_slot_uses_beijing_time(stamp, slot):
    assert poster_delivery.due_slot(datetime.fromisoformat(stamp)) == slot


@pytest.mark.parametrize("gmv,expected", [("1666.01", True), ("1666", False), ("1665.99", False)])
def test_compare_without_rounded_percentage(gmv, expected):
    row = {"gmv": gmv, "target": "10000", "progress_percent": 16.7}
    assert pace.pace_metrics(row, {"percent": 16.66})["ahead_of_time"] is expected


@pytest.fixture
def posters(setup, monkeypatch, tmp_path):
    s = setup
    settings = get_settings()
    monkeypatch.setattr(settings, "BATTLE_REPORT_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send?access_token=test-only")
    monkeypatch.setattr(settings, "BATTLE_REPORT_PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(poster_images, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(poster_images, "UPLOADS_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(poster_delivery, "beijing_now", lambda: datetime(2026, 9, 22, 13))
    monkeypatch.setattr(poster_service, "beijing_now", lambda: datetime(2026, 9, 22, 13))
    report = s.db.get(BattleReport, s.report["id"])
    report.start_date, report.end_date = date(2026, 9, 22), date(2026, 9, 30)
    s.db.commit()
    targets = [{"member_id": m["id"], "version": 1, "target_usd": "100.00"} for m in s.report["members"]]
    assert s.client.put(s.url+"/targets", json={"targets": targets}).status_code == 200
    s.sender = SimpleNamespace(send_markdown=AsyncMock(return_value={"errcode": 0}))
    s.report_obj = report
    return s


def enable(s):
    report = s.db.get(BattleReport, s.report["id"])
    result = s.client.put(s.url+"/poster-config", json={"version": report.version,
        "work_dates": pace.SEPTEMBER_WORK_DATES, "push_enabled": True})
    assert result.status_code == 200, result.text


def _tiny_png():
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), "#420403").save(buf, "PNG")
    return buf.getvalue()


def mock_render(monkeypatch):
    png = _tiny_png()
    monkeypatch.setattr(poster_delivery, "render_posters", lambda snapshot, kinds: {k: png for k in kinds})


def test_admin_preview_same_snapshot_no_delivery(posters, monkeypatch):
    s = posters
    calls = []
    def render(snapshot):
        calls.append(snapshot)
        return {"team": b"a", "personal": b"b"}
    monkeypatch.setattr(poster_renderer, "render_posters", render)
    result = s.client.post(s.url+"/posters/preview")
    assert result.status_code == 200, result.text
    assert len(calls) == 1 and result.json()["data"]["time_progress"]["percent"] == 0
    assert calls[0]["summary"]["gmv"] == "90.90"
    assert [p["rank"] for p in calls[0]["people"]] == [1, 2, 3]
    assert s.db.query(BattleReportDelivery).count() == 0
    become(s, 1)
    assert s.client.post(s.url+"/posters/preview").status_code == 403
    assert s.client.get(s.url+"/poster-config").status_code == 403


def test_calendar_config_validation_and_stale_version(posters):
    s = posters
    config = s.client.get(s.url+"/poster-config").json()["data"]
    assert config["work_dates"] == pace.SEPTEMBER_WORK_DATES
    assert config["send_times"] == ["13:00", "17:01"]
    body = {"version": s.report_obj.version, "work_dates": ["2026-10-01"], "push_enabled": False}
    assert s.client.put(s.url+"/poster-config", json=body).status_code == 422
    body["work_dates"] = ["2026-09-22", "2026-09-22"]
    assert s.client.put(s.url+"/poster-config", json=body).status_code == 422
    body["work_dates"] = pace.SEPTEMBER_WORK_DATES
    assert s.client.put(s.url+"/poster-config", json=body).status_code == 200
    assert s.client.put(s.url+"/poster-config", json=body).status_code == 409


def test_two_images_once_across_retries_and_same_snapshot(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    first = poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert all(v["status"] == "sent" for v in first["deliveries"].values())
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert s.sender.send_markdown.call_count == 2
    assert s.db.query(BattleReportDelivery).count() == 1
    frozen = s.db.query(BattleReportDelivery).one().snapshot
    assert frozen["summary"]["gmv"] == "90.90"


def test_afternoon_release_reuses_old_1700_delivery(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    now = datetime(2026, 9, 22, 17, 1)
    first = poster_delivery.send_slot(s.db, s.report_obj.id, now, s.sender)
    assert all(v["status"] == "sent" for v in first["deliveries"].values())
    row = s.db.query(BattleReportDelivery).one()
    row.slot = "17:00"
    s.db.commit()

    poster_delivery.send_slot(s.db, s.report_obj.id, now.replace(minute=6), s.sender)
    assert s.db.query(BattleReportDelivery).count() == 1
    assert s.db.query(BattleReportDelivery).one().slot == "17:00"
    assert s.sender.send_markdown.call_count == 2


def test_only_definitively_failed_image_retries(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    s.sender.send_markdown.side_effect = [{"errcode": 0}, DingTalkWebhookError(310000, "invalid")]
    first = poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert first["deliveries"]["team"]["status"] == "sent"
    assert first["deliveries"]["personal"]["status"] == "failed"
    s.sender.send_markdown.side_effect = None
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert s.sender.send_markdown.call_count == 3


@pytest.mark.parametrize("error", [httpx.ReadTimeout("secret-url"), DingTalkWebhookError(-1, "系统繁忙")])
def test_uncertain_outcome_never_automatically_resends(posters, monkeypatch, error):
    s = posters; enable(s); mock_render(monkeypatch)
    s.sender.send_markdown.side_effect = error
    result = poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert all(v["status"] == "uncertain" for v in result["deliveries"].values())
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert s.sender.send_markdown.call_count == 2
    assert "secret-url" not in str(result)


def test_interrupted_sending_is_quarantined_and_destination_change_blocks(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    row = s.db.query(BattleReportDelivery).one()
    row.deliveries = {"team": {"status": "sending"}, "personal": {"status": "sent"}}
    s.db.commit()
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert row.deliveries["team"]["status"] == "uncertain"
    assert s.sender.send_markdown.call_count == 2
    monkeypatch.setattr(get_settings(), "BATTLE_REPORT_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send?access_token=different")
    assert poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)["status"] == "blocked"


def test_invalid_slot_and_empty_dedicated_group_never_use_default(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    assert poster_delivery.send_slot(s.db, s.report_obj.id, datetime(2026, 9, 22, 14), s.sender)["status"] == "skipped"
    monkeypatch.setattr(get_settings(), "BATTLE_REPORT_WEBHOOK_URL", "")
    assert poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)["status"] == "skipped"
    assert s.sender.send_markdown.call_count == 0


def test_group_visibility_checked_before_second_image(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    async def send(title, content):
        s.db.get(BattleReport, s.report_obj.id).visibility = "self"
        s.db.commit()
        return {"errcode": 0}
    s.sender.send_markdown.side_effect = send
    result = poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert s.sender.send_markdown.call_count == 1
    assert result["deliveries"]["personal"]["status"] == "pending"


def test_capability_is_expiring_and_kind_bound(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    row = s.db.query(BattleReportDelivery).one()
    expires = poster_images.expiry(row)
    monkeypatch.setattr(poster_images, "beijing_now_aware", lambda: datetime(2026, 9, 22, tzinfo=timezone.utc))
    sig = poster_images.signature(row.id, "team", expires)
    served = poster_images.public_image(s.db, row.id, "team", expires, sig).read_bytes()
    assert served == poster_images.compress_poster(_tiny_png()) and served[:2] == b"\xff\xd8"
    for kind, exp, signature in [("personal", expires, sig), ("team", expires+1, sig), ("../bad", expires, sig)]:
        with pytest.raises(HTTPException):
            poster_images.public_image(s.db, row.id, kind, exp, signature)
    monkeypatch.setattr(poster_images, "beijing_now_aware", lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    with pytest.raises(HTTPException):
        poster_images.public_image(s.db, row.id, "team", expires, sig)


def test_public_image_route_serves_jpeg_and_rebuild_failure_is_503(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    row = s.db.query(BattleReportDelivery).one()
    expires = poster_images.expiry(row)
    sig = poster_images.signature(row.id, "team", expires)
    url = f"/api/battle-reports/poster-images/{row.id}/team.jpg?expires={expires}&signature={sig}"
    response = s.client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.content[:2] == b"\xff\xd8"

    for cached in poster_images.CACHE_ROOT.glob("*.jpg"):
        cached.unlink()
    monkeypatch.setattr(poster_images, "render_posters",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("browser missing")))
    response = s.client.get(url)
    assert response.status_code == 503
    body = response.json()
    assert "海报生成失败" in (body.get("message") or body.get("detail") or "")


def test_compress_poster_jpeg_shrinks_tall_png():
    import os
    from io import BytesIO
    from PIL import Image
    source = BytesIO()
    Image.frombytes("RGB", (1080, 800), os.urandom(1080 * 800 * 3)).save(source, "PNG", compress_level=0)
    raw = source.getvalue()
    jpeg = poster_images.compress_poster(raw)
    assert jpeg[:2] == b"\xff\xd8" and len(jpeg) < len(raw)
    assert Image.open(BytesIO(jpeg)).size == (1080, 800)


def test_image_url_is_cloud_public_uploads_path(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    row = s.db.query(BattleReportDelivery).one()
    url = poster_images.image_url(row, "team")
    assert url.startswith("https://example.test/uploads/festival/battle-report-posters/")
    assert url.endswith(".jpg")
    assert (poster_images.UPLOADS_ROOT / "battle-report-posters").is_dir()
    assert list((poster_images.UPLOADS_ROOT / "battle-report-posters").glob("*.jpg"))


def test_template_escapes_names_and_has_no_external_assets(posters):
    snapshot = poster_service.preview_snapshot(posters.db, posters.report_obj.id, posters.identity)
    snapshot["people"][0]["user_name"] = '<img src="https://evil.test/">'
    html = poster_renderer.render_html(snapshot, "personal")
    assert '&lt;img src=' in html and '<img src="https://evil.test/' not in html
    assert 'class="company-logo"' in html and 'data:image/png;base64,' in html


def test_rest_day_keeps_push_schedule_but_not_pace(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    monkeypatch.setattr(poster_delivery, "beijing_now", lambda: datetime(2026, 9, 26, 13))
    result = poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert all(v["status"] == "sent" for v in result["deliveries"].values())
    assert s.db.query(BattleReportDelivery).one().snapshot["workday_progress"]["percent"] == 49.98


def test_recovery_covers_past_final_retry_without_resending(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    row = s.db.query(BattleReportDelivery).one()
    row.deliveries = {"team": {"status": "sent"}, "personal": {"status": "sending", "attempts": 3}}
    row.updated_at = datetime(2026, 9, 22, 13, 15)
    s.db.commit()
    assert poster_delivery.recover_interrupted(s.db, datetime(2026, 9, 22, 13, 20)) == 0
    with poster_delivery.delivery_lock(s.db, s.report_obj.id):
        assert poster_delivery.recover_interrupted(s.db, datetime(2026, 9, 22, 17, 30)) == 0
    assert poster_delivery.recover_interrupted(s.db, datetime(2026, 9, 22, 17, 30)) == 1
    assert s.db.query(BattleReportDelivery).one().deliveries["personal"]["status"] == "uncertain"
    assert s.sender.send_markdown.call_count == 2


def test_read_transaction_ends_before_every_outgoing_message(posters, monkeypatch):
    s = posters; enable(s); mock_render(monkeypatch)
    boundaries = []
    original = s.db.rollback
    def rollback():
        boundaries.append('rollback')
        original()
    monkeypatch.setattr(s.db, 'rollback', rollback)
    async def send(title, content):
        boundaries.append('send')
        return {"errcode": 0}
    s.sender.send_markdown.side_effect = send
    poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert boundaries == ['rollback', 'send', 'rollback', 'send']


def test_render_failure_is_recorded_without_sending(posters, monkeypatch):
    s = posters; enable(s)
    def fail(*args):
        raise RuntimeError('private path')
    monkeypatch.setattr(poster_delivery, 'render_posters', fail)
    result = poster_delivery.send_slot(s.db, s.report_obj.id, sender=s.sender)
    assert all(v['status']=='failed' for v in result['deliveries'].values())
    assert s.sender.send_markdown.call_count == 0
    assert 'private path' not in str(result)


def test_configured_browser_path_validation(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "BATTLE_REPORT_BROWSER_PATH", "")
    assert poster_renderer.configured_browser_path() is None
    missing = tmp_path / "missing-chrome.exe"
    monkeypatch.setattr(settings, "BATTLE_REPORT_BROWSER_PATH", str(missing))
    with pytest.raises(RuntimeError, match="BATTLE_REPORT_BROWSER_PATH 不存在"):
        poster_renderer.configured_browser_path()
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"stub")
    monkeypatch.setattr(settings, "BATTLE_REPORT_BROWSER_PATH", str(chrome))
    assert poster_renderer.configured_browser_path() == str(chrome)


def test_launch_prefers_configured_then_system_fallback(monkeypatch, tmp_path):
    settings = get_settings()
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"stub")
    monkeypatch.setattr(settings, "BATTLE_REPORT_BROWSER_PATH", str(chrome))
    launched = []

    class Chromium:
        def launch(self, **options):
            launched.append(options)
            return object()

    poster_renderer._launch_chromium(SimpleNamespace(chromium=Chromium()))
    assert launched == [{"headless": True, "executable_path": str(chrome)}]

    monkeypatch.setattr(settings, "BATTLE_REPORT_BROWSER_PATH", "")
    monkeypatch.setattr(poster_renderer, "system_browser_path", lambda: str(chrome))
    launched.clear()

    class DefaultThenFallback:
        def launch(self, **options):
            launched.append(options)
            if "executable_path" not in options:
                raise RuntimeError("Executable doesn't exist at chromium_headless_shell")
            return object()

    assert poster_renderer._launch_chromium(SimpleNamespace(chromium=DefaultThenFallback())) is not None
    assert launched == [{"headless": True}, {"headless": True, "executable_path": str(chrome)}]


def test_launch_error_is_actionable_when_no_browser(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "BATTLE_REPORT_BROWSER_PATH", "")
    monkeypatch.setattr(poster_renderer, "system_browser_path", lambda: None)

    class BrokenChromium:
        def launch(self, **options):
            raise RuntimeError("Executable doesn't exist at missing-shell")

    with pytest.raises(RuntimeError) as excinfo:
        poster_renderer._launch_chromium(SimpleNamespace(chromium=BrokenChromium()))
    message = str(excinfo.value)
    assert "无法启动浏览器生成海报" in message
    assert "playwright install chromium" in message
    assert "BATTLE_REPORT_BROWSER_PATH" in message
    assert "Microsoft YaHei" in message
