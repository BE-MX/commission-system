"""全平台北京时间契约。"""

import importlib.util
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core import database
from app.core.time import BEIJING_TIMEZONE, beijing_now, beijing_today, to_beijing_naive
from app.agent_runtime.models import AgentEvent, AgentProfile, AgentRun
from app.customer.models import CustomerResearchTask
from app.customer_image.models import CustomerImageGeneration, CustomerImageProduct
from app.design_image.models import DesignImageJob, DesignImageSession
from app.invoice.models import Invoice  # noqa: F401 -- registers semifinal allocation FK target
from app.sales_automation.models import AcquisitionProfile, SearchJob
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.salary.router import _beijing_epoch_ms
from app.tracking.carriers import dhl
from app.tracking.carriers.dhl import DHLAdapter, _parse_event_datetime
from app.tracking.carriers.fedex import FedExAdapter
from app.whatsapp.service import _parse_dt


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions/123_platform_beijing_time.py"
    spec = importlib.util.spec_from_file_location("migration_123_platform_beijing_time", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_beijing_now_does_not_follow_server_local_timezone():
    assert BEIJING_TIMEZONE.key == "Asia/Shanghai"
    original = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/Los_Angeles"
        if hasattr(time, "tzset"):
            time.tzset()
        actual = beijing_now()
        expected = datetime.now(BEIJING_TIMEZONE).replace(tzinfo=None)
        assert actual.tzinfo is None
        assert abs(actual - expected) < timedelta(seconds=1)
        assert beijing_today() == expected.date()
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()


def test_production_order_defaults_write_beijing_clock_time():
    defaults = (
        ProductionOrder.__table__.c.created_at.default.arg,
        ProductionOrder.__table__.c.updated_at.default.arg,
        ProductionOrderItem.__table__.c.created_at.default.arg,
        ProductionOrderItem.__table__.c.updated_at.default.arg,
    )
    for default in defaults:
        assert abs(default(None) - beijing_now()) < timedelta(seconds=1)


def test_ordinary_timestamps_use_beijing_while_leases_remain_explicit_utc():
    business_defaults = (
        CustomerImageProduct.__table__.c.created_at.default.arg,
        CustomerImageGeneration.__table__.c.created_at.default.arg,
        DesignImageSession.__table__.c.created_at.default.arg,
        DesignImageJob.__table__.c.created_at.default.arg,
        AcquisitionProfile.__table__.c.created_at.default.arg,
        SearchJob.__table__.c.created_at.default.arg,
        AgentProfile.__table__.c.created_at.default.arg,
        AgentEvent.__table__.c.created_at.default.arg,
    )
    for default in business_defaults:
        assert abs(default(None) - beijing_now()) < timedelta(seconds=1)
    assert CustomerImageGeneration.__table__.c.lease_expires_at.default is None
    assert DesignImageJob.__table__.c.lease_expires_at.default is None
    assert SearchJob.__table__.c.lease_expires_at.default is None
    assert AgentRun.__table__.c.lease_expires_at.default is None


def test_mysql_connections_are_pinned_to_utc_plus_eight():
    statements = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            statements.append(statement)

    class Connection:
        def cursor(self):
            return Cursor()

    database._set_mysql_session_timezone(Connection(), None)
    assert statements == ["SET time_zone = '+08:00'"]

    alembic_env = (Path(__file__).parents[1] / "alembic/env.py").read_text(encoding="utf-8")
    assert alembic_env.count("SET time_zone = '+08:00'") == 2
    online_setup = alembic_env.split("def run_migrations_online()", 1)[1]
    assert online_setup.index("connection.exec_driver_sql") < online_setup.index("connection.commit()")
    assert online_setup.index("connection.commit()") < online_setup.index("context.configure")


def test_migration_covers_production_and_keeps_invoice_108_excluded():
    migration = _load_migration()
    assert len(migration.TIME_COLUMNS) == 58
    assert sum(len(columns) for columns in migration.TIME_COLUMNS.values()) == 142
    assert migration.TIME_COLUMNS["ark_production_orders"] == ("created_at",)
    assert migration.TIME_COLUMNS["ark_production_order_items"] == ("created_at",)
    assert "ark_production_cart" not in migration.TIME_COLUMNS
    assert "ark_safety_stock" not in migration.TIME_COLUMNS
    assert "product_process_route" not in migration.TIME_COLUMNS
    assert "ark_customer_actions" not in migration.TIME_COLUMNS
    assert "ark_invoices" not in migration.TIME_COLUMNS
    assert "ark_permissions" not in migration.TIME_COLUMNS
    assert "ark_role_permissions" not in migration.TIME_COLUMNS
    assert "ark_users" not in migration.TIME_COLUMNS
    assert "ark_design_image_prompt_templates" not in migration.TIME_COLUMNS
    assert "updated_at" not in migration.TIME_COLUMNS["ark_assets"]
    assert "updated_at" not in migration.TIME_COLUMNS["ark_production_orders"]
    assert "lease_expires_at" not in migration.TIME_COLUMNS["ark_agent_runs"]
    assert "expires_at" not in migration.TIME_COLUMNS["ark_customer_image_invites"]
    assert migration.KEY_COLUMNS["ark_asset_permissions"] == ("asset_id",)
    assert migration.ON_UPDATE_COLUMNS["ark_production_orders"] == ("updated_at",)
    assert migration.ON_UPDATE_COLUMNS["ark_production_order_items"] == ("updated_at",)
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert "时间备份不完整" in source
    assert "missing_keys" in source
    assert "北京时间转换校验失败" in source
    assert "ARK_TIME_MIGRATION_MAINTENANCE" in source
    assert "DATE_ADD(backup.`original_value`, INTERVAL 8 HOUR)" in source
    assert "LEFT JOIN" in source and "DATE_SUB" in source
    assert "rollback_value" in source
    assert "SET target.`{column}` = backup.`original_value`" not in source


def test_migration_requires_maintenance_and_backs_up_all_columns_before_conversion(monkeypatch):
    migration = _load_migration()
    monkeypatch.delenv(migration.MAINTENANCE_ENV, raising=False)
    monkeypatch.setattr(migration.op, "get_context", lambda: type("Ctx", (), {"as_sql": False})())
    with pytest.raises(RuntimeError, match="必须停止所有写实例"):
        migration._require_maintenance_window()

    calls = []
    monkeypatch.setattr(migration, "_require_maintenance_window", lambda: None)
    monkeypatch.setattr(migration, "_create_backup_table", lambda: calls.append(("create", None, None)))
    monkeypatch.setattr(migration, "_backup_verify", lambda table, column: calls.append(("backup", table, column)))
    monkeypatch.setattr(migration, "_convert_verify", lambda table, column: calls.append(("convert", table, column)))
    migration.upgrade()
    last_backup = max(index for index, call in enumerate(calls) if call[0] == "backup")
    first_convert = min(index for index, call in enumerate(calls) if call[0] == "convert")
    assert last_backup < first_convert


def test_migration_backup_keys_ignore_mixed_mysql_collations():
    migration = _load_migration()
    source_key = migration._row_key("source", ("id",))
    condition = migration._binary_key_match("backup.`row_key`", source_key)

    assert condition == (
        "backup.`row_key` = "
        "CAST(CONCAT_WS(':', CAST(source.`id` AS CHAR)) AS BINARY)"
    )
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert "backup.`row_key` = {key}" not in source
    assert "backup.`row_key` = {target_key}" not in source


def test_migration_normalizes_partial_varchar_backup_table(monkeypatch):
    migration = _load_migration()
    existing_type = migration.sa.String(255)
    altered = []

    class Inspector:
        @staticmethod
        def has_table(table):
            return table == migration.BACKUP_TABLE

        @staticmethod
        def get_columns(table):
            assert table == migration.BACKUP_TABLE
            return [{"name": "row_key", "type": existing_type, "nullable": False}]

    monkeypatch.setattr(migration.op, "get_context", lambda: type("Ctx", (), {"as_sql": False})())
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: Inspector())
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: altered.append((args, kwargs)))

    migration._create_backup_table()

    assert altered[0][0] == (migration.BACKUP_TABLE, "row_key")
    assert isinstance(altered[0][1]["type_"], migration.sa.VARBINARY)
    assert altered[0][1]["existing_type"] is existing_type
    assert altered[0][1]["existing_nullable"] is False


def test_external_offset_times_are_converted_to_beijing_without_dropping_offset():
    assert _parse_dt("2026-08-26T12:00:00Z") == datetime(2026, 8, 26, 20)
    assert _parse_dt("2026-08-26T12:00:00-05:00") == datetime(2026, 8, 27, 1)
    assert _parse_dt("2026-08-26T12:00:00") == datetime(2026, 8, 26, 12)
    assert to_beijing_naive(datetime(2026, 8, 26, 12, tzinfo=timezone.utc)) == datetime(2026, 8, 26, 20)

    fedex = FedExAdapter("id", "secret")._parse_response("FX1", {
        "output": {"completeTrackResults": [{"trackResults": [{
            "latestStatusDetail": {"code": "IT", "description": "Transit"},
            "scanEvents": [{
                "date": "2026-08-26T12:00:00-05:00", "eventDescription": "Scan",
                "eventType": "IT", "scanLocation": {"city": "New York", "countryCode": "US"},
            }],
        }]}]},
    })
    assert to_beijing_naive(fedex.events[0].event_time) == datetime(2026, 8, 27, 1)
    dhl_time = _parse_event_datetime({"date": "2026-08-26", "time": "12:00:00", "GMTOffset": "-05:00"})
    assert to_beijing_naive(dhl_time) == datetime(2026, 8, 27, 1)
    with pytest.raises(ValueError, match="missing GMT offset"):
        _parse_event_datetime({"date": "2026-08-26", "time": "12:00:00"})


@pytest.mark.asyncio
async def test_dhl_tracking_explicitly_requests_offset_for_every_event(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"shipments": [{"events": []}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url, **kwargs):
            captured.update(kwargs)
            return Response()

    monkeypatch.setattr(dhl.httpx, "AsyncClient", Client)
    result = await DHLAdapter("user", "password").track("DHL-1")

    assert result.success is True
    assert captured["params"] == {"requestGMTOffsetPerEvent": "true"}


def test_salary_beijing_month_boundary_epoch_ignores_server_timezone():
    original = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/Los_Angeles"
        if hasattr(time, "tzset"):
            time.tzset()
        expected = int(datetime(2026, 8, 1, tzinfo=BEIJING_TIMEZONE).timestamp() * 1000)
        assert _beijing_epoch_ms("2026-08-01 00:00:00") == expected
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()


def test_backend_business_code_and_scripts_have_no_implicit_local_or_deprecated_utc_now():
    backend_root = Path(__file__).parents[1]
    app_root = backend_root / "app"
    forbidden = re.compile(
        r"datetime\.(?:utcnow|today)\s*\(|datetime\.now\s*\(|date\.today\s*\("
    )
    violations = []
    for path in (*app_root.rglob("*.py"), *(backend_root / "scripts").rglob("*.py")):
        if path == app_root / "core/time.py":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line):
                violations.append(f"{path.relative_to(backend_root)}:{line_number}")
    assert violations == []


def test_mixed_utc_and_beijing_domains_use_matching_clock_contracts():
    app_root = Path(__file__).parents[1] / "app"
    agent_gateway = (app_root / "ai/agent_service.py").read_text(encoding="utf-8")
    assert "stale_before = beijing_now()" in agent_gateway
    assert "today = beijing_now().replace(" in agent_gateway
    assert "run.lease_expires_at <= utc_now_naive()" in agent_gateway

    projection = (app_root / "agent_runtime/projection_service.py").read_text(encoding="utf-8")
    assert "action.generated_at = beijing_now()" in projection

    search = (app_root / "sales_automation/service.py").read_text(encoding="utf-8")
    assert "lease_now = beijing_now()" in search
    assert "job.lease_expires_at <= lease_now" in search
    assert "job.lease_expires_at = beijing_now() + timedelta" in search

    research = (app_root / "sales_automation/public_pool_service.py").read_text(
        encoding="utf-8"
    )
    assert "now = beijing_now()" in research
    assert "task.lease_expires_at <= now" in research
    assert "task.lease_expires_at = beijing_now() + timedelta" in research
    assert "DATE_SUB(NOW(), INTERVAL" not in research

    assert "北京时间" in SearchJob.__table__.c.lease_expires_at.comment
    assert "北京时间" in CustomerResearchTask.__table__.c.lease_expires_at.comment


def test_bulk_asset_filename_uses_central_beijing_clock():
    source = (Path(__file__).parents[1] / "app/asset/batch_service.py").read_text(encoding="utf-8")
    assert '__import__("datetime").beijing_now' not in source
    assert "beijing_now().strftime" in source
