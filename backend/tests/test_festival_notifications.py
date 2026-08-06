"""采购节钉钉图片、日报内容与恢复链路测试。"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.dingtalk.webhook import DingTalkWebhookError
from app.festival import notification_service
from app.festival.models import FestivalEvent, FestivalState


def test_only_known_busy_response_is_delivery_uncertain():
    assert DingTalkWebhookError(130101, "系统繁忙").delivery_uncertain is True
    assert DingTalkWebhookError(40035, "系统繁忙").delivery_uncertain is False
    assert DingTalkWebhookError(130101, "签名错误").delivery_uncertain is False


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
        "detail": "143 新签目标完成 30% · 当前 45/143",
        "amount": None,
        "dedup_key": "company_milestone:30",
        "created_at": datetime(2026, 8, 4, 12, 30),
    }

    output = notification_service.render_event_image(event)

    assert output.is_file()
    with Image.open(output) as image:
        assert image.size == (1200, 675)
        assert image.format == "PNG"
        assert image.getpixel((10, 10)) == (253, 217, 86)
        assert image.getpixel((690, 104)) == (8, 3, 3)
        assert image.getpixel((510, 455)) == (8, 3, 3)
        assert image.getpixel((1060, 575)) == (253, 217, 86)


@pytest.mark.parametrize(
    ("subject_type", "subject_id", "subject_name", "asset_path", "color"),
    [
        ("person", "U1", "张三", "avatars/U1.png", (220, 30, 30)),
        ("team", "乘风", "乘风", "team-logos/chengfeng.png", (30, 60, 220)),
    ],
)
def test_render_event_image_includes_person_or_team_image(
        tmp_path, monkeypatch, subject_type, subject_id, subject_name, asset_path, color):
    repo_root = tmp_path / "repo"
    asset = repo_root / "frontend" / "public" / "festival" / "assets" / asset_path
    asset.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (180, 180), color).save(asset)
    monkeypatch.setattr(notification_service, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(notification_service, "_UPLOAD_ROOT", tmp_path / "output")

    output = notification_service.render_event_image({
        "level": "L3",
        "label": "名次上升",
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_name": subject_name,
        "detail": "当前排名上升至第 1 名",
        "dedup_key": f"render-subject:{subject_type}",
    })

    with Image.open(output) as image:
        assert image.getpixel((157, 251)) == color


def test_board_screenshot_is_resized_and_compressed_to_jpeg(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "board.jpg"
    image = Image.effect_noise((1920, 1080), 80).convert("RGB")
    image.save(source, "PNG")

    notification_service._compress_board_screenshot(source, output)

    with Image.open(output) as compressed:
        assert compressed.format == "JPEG"
        assert compressed.size == (1600, 900)
    assert output.stat().st_size < source.stat().st_size


def test_daily_markdown_has_report_and_all_four_screenshots():
    snapshot = {
        "date": "2026-08-04",
        "as_of": "2026-08-04 17:30:00",
        "today_new": 3,
        "today_gmv": 12500,
        "summary": {
            "new_total": 45, "new_target": 143,
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
    assert "公司新签：**45/143**" in markdown
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


def test_browser_executable_uses_chrome_and_ignores_edge_configuration(monkeypatch):
    settings = notification_service.get_settings()
    monkeypatch.setattr(
        settings, "FESTIVAL_BROWSER_EXECUTABLE",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    )
    existing = {"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"}
    monkeypatch.setattr(
        notification_service.Path, "is_file",
        lambda path: str(path) in existing,
    )

    assert notification_service._browser_executable().name == "chrome.exe"


def test_screenshot_command_forces_stable_reduced_motion_frame(tmp_path):
    command = notification_service._screenshot_command(
        tmp_path / "edge.exe",
        str(tmp_path / "profile"),
        tmp_path / "board.png",
        "http://screen.test/festival/xinqian.html?key=secret&stay=1&popup=0",
    )

    assert "--force-prefers-reduced-motion" in command
    assert "--virtual-time-budget=6000" in command


def test_screenshot_command_supports_windows_service_account(tmp_path):
    command = notification_service._screenshot_command(
        tmp_path / "edge.exe",
        str(tmp_path / "service-profile"),
        tmp_path / "board.png",
        "http://127.0.0.1:8002/festival/xinqian.html?key=secret",
    )

    assert "--no-sandbox" not in command
    assert "--disable-crash-reporter" in command
    assert "--disable-extensions" in command


def test_each_board_screenshot_uses_an_independent_browser_profile(tmp_path, monkeypatch):
    settings = notification_service.get_settings()
    monkeypatch.setattr(settings, "FESTIVAL_SCREEN_KEYS", "secret-screen-key")
    monkeypatch.setattr(settings, "FESTIVAL_SCREENSHOT_BASE_URL", "http://screen.test")
    monkeypatch.setattr(notification_service, "_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(notification_service, "_browser_executable", lambda: tmp_path / "edge.exe")
    monkeypatch.setattr(notification_service, "_public_url", lambda path: f"https://files.test/{path.name}")

    class Response:
        status_code = 200
        text = "/api/public/festival/"

        @staticmethod
        def json():
            return {"data": {"as_of": "2026-08-05 17:30:00"}}

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

    profiles = []

    def run(command, **_kwargs):
        profiles.append(next(part for part in command if part.startswith("--user-data-dir=")))
        source = Path(next(part for part in command if part.startswith("--screenshot="))[13:])
        source.write_bytes(b"x" * 10_001)
        return type("Proc", (), {"returncode": 0})()

    def compress(_source, output):
        output.write_bytes(b"x" * 10_001)

    monkeypatch.setattr(notification_service.httpx, "Client", Client)
    monkeypatch.setattr(notification_service.subprocess, "run", run)
    monkeypatch.setattr(notification_service, "_compress_board_screenshot", compress)

    result = notification_service.capture_board_screenshots(date(2026, 8, 5))

    assert len(result) == 4
    assert len(set(profiles)) == 4


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
        assert any("popup=0" in str(part) for part in cmd)
        raise notification_service.subprocess.TimeoutExpired(cmd, 40)

    monkeypatch.setattr(notification_service.httpx, "Client", Client)
    monkeypatch.setattr(notification_service.subprocess, "run", timeout)

    with pytest.raises(RuntimeError) as caught:
        notification_service.capture_board_screenshots(date(2026, 8, 4))
    assert "截图进程失败" in str(caught.value)
    assert "secret-screen-key" not in str(caught.value)


@pytest.mark.parametrize(
    "page",
    ["zhaiyao.html", "xinqian.html", "fugou.html", "zhenying.html", "tuandui.html"],
)
def test_every_festival_board_uses_shared_popup_controller(page):
    festival_root = Path(__file__).resolve().parents[2] / "frontend" / "public" / "festival"
    html = (festival_root / page).read_text(encoding="utf-8")

    assert 'href="assets/festival-popup.css"' in html
    assert 'src="assets/festival-popup.js"' in html
    assert "window.FestivalPopup" in html
    assert "FestivalPopup.scheduleNavigation" in html


def test_shared_popup_acknowledges_only_after_playback_and_can_be_disabled():
    script = (Path(__file__).resolve().parents[2] / "frontend" / "public" / "festival" /
              "assets" / "festival-popup.js").read_text(encoding="utf-8")

    finish_body = script.split("function finish(event)", 1)[1].split("function showLower", 1)[0]
    enqueue_body = script.split("function enqueue(events)", 1)[1].split("function previewExamples", 1)[0]
    assert "acknowledge(event.id)" in finish_body
    assert "acknowledge(" not in enqueue_body
    assert 'qs.get("popup") === "0"' in script
    assert "queuedIds" in enqueue_body


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


def test_daily_target_recovers_yesterday_across_midnight_without_historical_backfill(
        engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)

    # 首次启用只以最近已到 17:30 的 8 月 4 日为基线，不倒灌 8 月 1~3 日。
    assert notification_service._daily_target_date(datetime(2026, 8, 4, 18, 0)) == date(2026, 8, 4)
    # 即使服务直到次日 17:30 后才恢复，也先补昨天，不会直接跳到今天。
    assert notification_service._daily_target_date(datetime(2026, 8, 5, 18, 0)) == date(2026, 8, 4)

    assert notification_service._daily_claim(date(2026, 8, 4)) is True
    notification_service._daily_finish(date(2026, 8, 4), True)
    assert notification_service._daily_target_date(datetime(2026, 8, 5, 18, 0)) == date(2026, 8, 5)


def test_daily_target_waits_until_first_activity_report_is_due(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)

    assert notification_service._daily_target_date(datetime(2026, 8, 1, 17, 29)) is None
    assert notification_service._daily_target_date(datetime(2026, 8, 1, 17, 30)) == date(2026, 8, 1)


def test_daily_target_does_not_backfill_before_first_enablement(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)

    # 8 月 5 日上午首次启用：昨天不是本功能运行期间的欠报，不应倒灌。
    assert notification_service._daily_target_date(datetime(2026, 8, 5, 9, 0)) is None
    assert notification_service._daily_target_date(datetime(2026, 8, 5, 17, 30)) == date(2026, 8, 5)


def test_daily_force_bypasses_time_only_not_activity_window(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)

    assert notification_service._daily_target_date(
        datetime(2026, 8, 5, 9, 0), allow_today=True,
    ) == date(2026, 8, 5)

    with session_factory() as db:
        db.query(FestivalState).delete()
        db.commit()
    assert notification_service._daily_target_date(
        datetime(2026, 10, 2, 9, 0), allow_today=True,
    ) is None


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
async def test_busy_response_marks_daily_report_sent_to_avoid_duplicate(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)

    class BusySender:
        @staticmethod
        async def send_markdown(*_args, **_kwargs):
            raise DingTalkWebhookError(130101, "系统繁忙")

    monkeypatch.setattr(notification_service, "_festival_sender", lambda: BusySender())
    monkeypatch.setattr(notification_service, "_daily_snapshot", lambda _day: {})
    monkeypatch.setattr(notification_service, "capture_board_screenshots", lambda _day: [{}, {}, {}, {}])
    monkeypatch.setattr(notification_service, "build_daily_markdown", lambda *_args: "report")

    result = await notification_service.send_daily_report_if_due(
        force=True, now=datetime(2026, 8, 4, 12, 0),
    )

    assert result == {"sent": True, "screenshots": 4, "delivery_uncertain": True}
    with session_factory() as db:
        row = db.get(FestivalState, "delivery:daily:2026-08-04")
        assert json.loads(row.value_json)["status"] == "sent"


@pytest.mark.asyncio
async def test_busy_response_marks_popup_event_sent_to_avoid_duplicate(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", session_factory)
    with session_factory() as db:
        row = FestivalEvent(
            event_type="daily_combo", level="L3", subject_type="person",
            subject_id="U1", subject_name="张三", detail="×2 连击",
            dedup_key="combo:busy-response",
        )
        db.add(row)
        db.commit()
        event = notification_service._event_dict(row)

    class BusySender:
        @staticmethod
        async def send_markdown(*_args, **_kwargs):
            raise DingTalkWebhookError(130101, "系统繁忙")

    monkeypatch.setattr(notification_service, "_detect_and_load_pending", lambda: [event])
    monkeypatch.setattr(notification_service, "_festival_sender", lambda: BusySender())
    monkeypatch.setattr(notification_service, "render_event_image", lambda _event: None)
    monkeypatch.setattr(notification_service, "_public_url", lambda _path: "https://example.test/event.png")

    result = await notification_service.monitor_festival_events()

    assert result["sent"] == 1
    with session_factory() as db:
        saved = db.get(FestivalEvent, event["id"])
        assert saved.dingtalk_sent_at is not None
        assert saved.dingtalk_next_retry_at is None


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
