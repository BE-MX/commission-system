"""定时任务 smoke tests

每个 job 测试只验证"能跑完且对的下游被调用",不验证业务正确性。
目的:挡每天 08:30 静默失败 / refactor 把 import 撞坏 / SessionLocal 没注入。

约定:
  - `SessionLocal` 在每个 job 模块顶层 import,monkeypatch 必须 patch 模块导入点
    (e.g., `app.design.scheduler.SessionLocal`),不是 `app.core.database.SessionLocal`
  - insight / stock job 用 `except Exception: logger.exception(...)` 吞异常,
    smoke test 靠 mock call count 判断,不靠 raise
  - stock job 走 `anyio.to_thread.run_sync`,inner sync 在线程跑,
    monkeypatch 进程级生效 OK
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import sessionmaker


# ── 共用 fixture ────────────────────────────────────

@pytest.fixture
def session_factory(engine):
    """返回绑定到 in-memory engine 的 sessionmaker,可作 SessionLocal 替身"""
    return sessionmaker(bind=engine, expire_on_commit=False)


# ── 注册测试 ─────────────────────────────────────────

class TestSchedulerRegistration:
    async def test_start_scheduler_registers_jobs(self, monkeypatch):
        """start_scheduler 应注册 9 个 job 且 id 命名约定一致"""
        from app.core.config import get_settings

        # 强制开启 scheduler
        real_settings = get_settings()
        monkeypatch.setattr(real_settings, "SCHEDULER_ENABLED", True)
        monkeypatch.setattr(real_settings, "SCHEDULER_TIMEZONE", "Asia/Shanghai")
        monkeypatch.setattr(real_settings, "WHATSAPP_AUTO_SYNC_ENABLED", True)

        from app.schedulers.registry import start_scheduler, shutdown_scheduler
        scheduler = start_scheduler()
        try:
            assert scheduler is not None
            ids = {j.id for j in scheduler.get_jobs()}
            assert ids == {
                "design_shoot_reminder",
                "shipping_daily_report",
                "staging_scan",
                "tracking_poll_active",
                "insight_industry_daily",
                "insight_ai_tools",
                "insight_intelligence_overview",
                "stock_daily_report",
                "color_social_extract",
                "color_sales_aggregate",
                "whatsapp_auto_sync",
            }
        finally:
            shutdown_scheduler(scheduler)

    async def test_start_scheduler_disabled_returns_none(self, monkeypatch):
        from app.core.config import get_settings
        real_settings = get_settings()
        monkeypatch.setattr(real_settings, "SCHEDULER_ENABLED", False)

        from app.schedulers.registry import start_scheduler
        assert start_scheduler() is None


# ── 单 job smoke tests ───────────────────────────────

class TestDesignShootReminder:
    async def test_empty_db_skips_silently(self, session_factory, monkeypatch):
        """空 DB 应直接返回,不应调钉钉"""
        monkeypatch.setattr("app.design.scheduler.SessionLocal", session_factory)

        # 即使没人调钉钉,defensive 也 patch 一下以防 import 链断
        mock_notifier = MagicMock(send_to_users=AsyncMock())
        monkeypatch.setattr("app.dingtalk.work_notify.get_work_notifier",
                            lambda: mock_notifier)

        from app.design.scheduler import check_today_shoot_reminders
        await check_today_shoot_reminders()

        mock_notifier.send_to_users.assert_not_called()


class TestShippingDailyReport:
    async def test_empty_db_returns_zero_counts(self, session_factory, monkeypatch):
        """空 DB:无运单 → 无用户 → 早期返回 total=0"""
        monkeypatch.setattr("app.tracking.daily_report_service.SessionLocal",
                            session_factory)

        from app.tracking.daily_report_service import generate_daily_reports
        result = await generate_daily_reports()

        assert result == {"total": 0, "generated": 0, "pushed": 0}


class TestStagingScan:
    async def test_empty_staging_processes_zero(self, db):
        """暂存表空时 scan_staging 应安全跳过"""
        from app.tracking.staging_service import scan_staging
        stats = await scan_staging(db)

        assert stats["processed"] == 0
        assert stats["success"] == 0
        assert stats["duplicate"] == 0
        assert stats["error"] == 0


class TestTrackingPollActive:
    async def test_empty_db_returns_zero_counts(self, db):
        """无活跃运单时 poll_active_shipments 应安全返回零计数"""
        from app.tracking.polling_service import poll_active_shipments
        stats = await poll_active_shipments(db)

        assert stats == {"total": 0, "ok": 0, "error": 0, "skipped": 0}


class TestInsightIndustryDaily:
    async def test_invokes_underlying_generate_function(self, session_factory, monkeypatch):
        """scheduler wrapper 应调 generate_industry_daily_report;失败时吞异常不抛"""
        monkeypatch.setattr("app.insight.scheduler.SessionLocal", session_factory)

        fake_report = MagicMock(id=42, report_date="2026-05-17")
        mock_generate = MagicMock(return_value=fake_report)
        # patch service facade(scheduler 通过 facade 调)
        monkeypatch.setattr("app.insight.service.generate_industry_daily_report",
                            mock_generate)

        from app.insight.scheduler import generate_industry_daily
        await generate_industry_daily()

        mock_generate.assert_called_once()

    async def test_swallows_exception(self, session_factory, monkeypatch):
        """generate_report 抛错时不应让 APScheduler 看到异常"""
        monkeypatch.setattr("app.insight.scheduler.SessionLocal", session_factory)
        monkeypatch.setattr("app.insight.service.generate_industry_daily_report",
                            MagicMock(side_effect=RuntimeError("AI provider down")))

        from app.insight.scheduler import generate_industry_daily
        await generate_industry_daily()  # 不应 raise


class TestInsightAiTools:
    async def test_invokes_underlying_generate_function(self, session_factory, monkeypatch):
        monkeypatch.setattr("app.insight.scheduler.SessionLocal", session_factory)

        fake_report = MagicMock(id=99, report_date="2026-05-17")
        mock_generate = MagicMock(return_value=fake_report)
        monkeypatch.setattr("app.insight.service.generate_ai_tools_report",
                            mock_generate)

        from app.insight.scheduler import generate_ai_tools
        await generate_ai_tools()

        mock_generate.assert_called_once()


class TestStockDailyReport:
    async def test_invokes_sync_generator_in_thread(self, session_factory, monkeypatch):
        """async wrapper → anyio.to_thread → generate_stock_daily_report_sync"""
        monkeypatch.setattr("app.stock.scheduler.SessionLocal", session_factory)

        mock_sync = MagicMock(return_value=None)
        monkeypatch.setattr("app.stock.scheduler.generate_stock_daily_report_sync",
                            mock_sync)

        from app.stock.scheduler import generate_stock_daily_report
        await generate_stock_daily_report()

        mock_sync.assert_called_once()
        # 验证关键 kwargs:push_dingtalk=True(prod 行为)
        _, kwargs = mock_sync.call_args
        assert kwargs.get("push_dingtalk") is True
