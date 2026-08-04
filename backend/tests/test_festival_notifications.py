"""采购节钉钉图片、日报内容与恢复链路测试。"""

import json
from datetime import date, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.festival import notification_service
from app.festival.models import FestivalEvent, FestivalState


def test_festival_sender_never_falls_back_to_global_alert_group(monkeypatch):
    settings = notification_service.get_settings()
    monkeypatch.setattr(settings, "FESTIVAL_DINGTALK_WEBHOOK_URL", "")

    assert notification_service._festival_sender() is None


def test_render_event_image_contains_shareable_png(tmp_path, monkeypatch):
    monkeypatch.setattr(notification_service, "_UPLOAD_ROOT", tmp_path)
    event = {
        "level": "L4",
        "label": "公司目标里程碑",
        "subject_type": "company",
        "subject_id": "company",
        "subject_name": "莱莎采购节",
        "detail": "149 新签目标完成 30% · 当前 45/149",
        "amount": None,
        "dedup_key": "company_milestone:30",
        "created_at": datetime(2026, 8, 4, 12, 30),
    }

    output = notification_service.render_event_image(event)

    assert output.is_file()
    with Image.open(output) as image:
        assert image.size == (1200, 675)
        assert image.format == "PNG"


def test_daily_markdown_has_report_and_all_four_screenshots():
    snapshot = {
        "date": "2026-08-04",
        "as_of": "2026-08-04 17:30:00",
        "today_new": 3,
        "today_gmv": 12500,
        "summary": {
            "new_total": 45, "new_target": 149,
            "gmv_total": 780000, "gmv_target": 3260000,
        },
        "sign_top3": [{"name": "张三", "new_points": 8}],
        "first_top2": [{"name": "李四", "first_count": 3}],
        "amount_top2": [{"name": "王五", "re_amount": 9000}],
        "teams_top3": [{"name": "乘风", "avg": 5.5}],
    }
    screenshots = [
        {"title": title, "url": f"https://example.test/{idx}.png"}
        for idx, title in enumerate(("新签榜", "首返复购榜", "团队榜", "阵营榜"), 1)
    ]

    markdown = notification_service.build_daily_markdown(snapshot, screenshots)

    assert "今日新签：**3 个**" in markdown
    assert "今日 GMV：**$12,500**" in markdown
    assert markdown.count("![") == 4
    for shot in screenshots:
        assert shot["url"] in markdown


def test_browser_missing_fails_with_actionable_message(monkeypatch):
    settings = notification_service.get_settings()
    monkeypatch.setattr(settings, "FESTIVAL_BROWSER_EXECUTABLE", "Z:/missing/browser.exe")
    monkeypatch.setattr(notification_service.Path, "is_file", lambda _self: False)

    try:
        notification_service._browser_executable()
    except RuntimeError as exc:
        assert "FESTIVAL_BROWSER_EXECUTABLE" in str(exc)
    else:
        raise AssertionError("缺少浏览器时必须明确失败")


def test_screenshot_preflight_rejects_error_page_without_leaking_key(tmp_path, monkeypatch):
    settings = notification_service.get_settings()
    monkeypatch.setattr(settings, "FESTIVAL_SCREEN_KEYS", "secret-screen-key")
    monkeypatch.setattr(settings, "FESTIVAL_SCREENSHOT_BASE_URL", "http://screen.test")
    monkeypatch.setattr(notification_service, "_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(notification_service, "_browser_executable", lambda: tmp_path / "edge.exe")

    class Response:
        def __init__(self, status_code, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, **_kwargs):
            if "/festival/" in url:
                return Response(403, "access denied")
            return Response(200, payload={"data": {"as_of": "2026-08-04 17:30:00"}})

    monkeypatch.setattr(notification_service.httpx, "Client", Client)

    with pytest.raises(RuntimeError) as caught:
        notification_service.capture_board_screenshots(date(2026, 8, 4))
    assert "预检失败" in str(caught.value)
    assert "secret-screen-key" not in str(caught.value)


def test_screenshot_timeout_does_not_leak_key(tmp_path, monkeypatch):
    settings = notification_service.get_settings()
    monkeypatch.setattr(settings, "FESTIVAL_SCREEN_KEYS", "secret-screen-key")
    monkeypatch.setattr(settings, "FESTIVAL_SCREENSHOT_BASE_URL", "http://screen.test")
    monkeypatch.setattr(notification_service, "_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(notification_service, "_browser_executable", lambda: tmp_path / "edge.exe")

    class Response:
        status_code = 200
        text = "/api/public/festival/"

        @staticmethod
        def json():
            return {"data": {"as_of": "2026-08-04 17:30:00"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def get(*_args, **_kwargs):
            return Response()

    def timeout(cmd, **_kwargs):
        raise notification_service.subprocess.TimeoutExpired(cmd, 40)

    monkeypatch.setattr(notification_service.httpx, "Client", Client)
    monkeypatch.setattr(notification_service.subprocess, "run", timeout)

    with pytest.raises(RuntimeError) as caught:
        notification_service.capture_board_screenshots(date(2026, 8, 4))
    assert "截图进程失败" in str(caught.value)
    assert "secret-screen-key" not in str(caught.value)


def test_stale_daily_claim_can_be_recovered(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)
    target = date(2026, 8, 4)
    with session_factory() as db:
        db.add(FestivalState(
            state_key="delivery:daily:2026-08-04",
            value_json=json.dumps({
                "status": "sending",
                "claimed_at": (datetime.now() - timedelta(minutes=16)).isoformat(),
            }),
        ))
        db.commit()

    assert notification_service._daily_claim(target) is True
    assert notification_service._daily_claim(target) is False


def test_corrupt_daily_claim_can_be_recovered(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)
    with session_factory() as db:
        db.add(FestivalState(
            state_key="delivery:daily:2026-08-05",
            value_json="not-json",
        ))
        db.commit()

    assert notification_service._daily_claim(date(2026, 8, 5)) is True


def test_event_delivery_lease_and_backoff(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)
    with session_factory() as db:
        event = FestivalEvent(
            event_type="daily_combo", level="L3", subject_type="person",
            subject_id="U1", subject_name="张三", detail="×2 连击",
            dedup_key="combo:lease-test",
        )
        db.add(event)
        db.commit()
        event_id = event.id

    assert notification_service._claim_event_delivery(event_id) is True
    assert notification_service._claim_event_delivery(event_id) is False
    notification_service._mark_event_delivery(event_id, "network down")
    assert notification_service._claim_event_delivery(event_id) is False

    with session_factory() as db:
        row = db.get(FestivalEvent, event_id)
        assert row.dingtalk_attempts == 1
        assert row.dingtalk_next_retry_at > datetime.now()
        row.dingtalk_next_retry_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    assert notification_service._claim_event_delivery(event_id) is True


@pytest.mark.asyncio
async def test_daily_recovery_runs_even_when_event_delivery_fails(monkeypatch):
    calls = []

    async def fail_events():
        calls.append("events")
        raise RuntimeError("event failed")

    async def recover_daily(**_kwargs):
        calls.append("daily")
        return {"sent": True}

    monkeypatch.setattr(notification_service, "monitor_festival_events", fail_events)
    monkeypatch.setattr(notification_service, "send_daily_report_if_due", recover_daily)

    with pytest.raises(RuntimeError, match="event failed"):
        await notification_service.monitor_festival_and_recover_daily()
    assert calls == ["events", "daily"]
