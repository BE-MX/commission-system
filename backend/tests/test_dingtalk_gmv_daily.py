"""业务队 GMV 日报：金额守恒、排除边界、配置与投递幂等。"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import (
    ArkPermission,
    ArkRole,
    ArkRolePermission,
    ArkUser,
    ArkUserExternalBinding,
    ArkUserRole,
)
from app.dingtalk.gmv_daily_config import load_config, save_config
from app.dingtalk import gmv_daily_service
from app.dingtalk.gmv_daily_schemas import GmvDailyConfigUpdate
from app.dingtalk.gmv_daily_service import (
    calculate_report,
    load_valid_orders,
    render_admin_markdown,
    render_team_markdown,
    report_date_for_run,
    send_daily_report,
)
from app.dingtalk.models import DingTalkMessageLog
from app.system.models import SysDict
from app.system import service as system_dict_service
from app.system.schemas import DictItemCreate, DictItemUpdate


@pytest.fixture
def gmv_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record):
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS lsordertest")

    for table in (
        ArkUser.__table__, ArkRole.__table__, ArkPermission.__table__,
        ArkUserRole.__table__, ArkRolePermission.__table__,
        ArkUserExternalBinding.__table__, SysDict.__table__, DingTalkMessageLog.__table__,
    ):
        table.create(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE lsordertest.user_basic (
                user_id TEXT PRIMARY KEY, full_name TEXT, nickname TEXT, user_mobile TEXT
            )
        """))
        connection.execute(text("""
            CREATE TABLE lsordertest.okki_orders (
                order_id TEXT PRIMARY KEY, order_no TEXT, amount_usd REAL, user_id TEXT,
                account_date TEXT, status TEXT, status_name TEXT, trail TEXT, departments TEXT
            )
        """))
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _config() -> dict:
    return {
        "teams": [
            {
                "department_id": 1,
                "name": "甲队",
                "captain_okki_user_id": "CAP1",
                "is_active": True,
                "members": [
                    {"okki_user_id": "CAP1", "name": "队长甲", "exclude_from_total": False, "is_active": True},
                    {"okki_user_id": "EX1", "name": "排除人员", "exclude_from_total": True, "is_active": True},
                    {"okki_user_id": "ZERO", "name": "零业绩", "exclude_from_total": False, "is_active": True},
                ],
            },
            {
                "department_id": 2,
                "name": "乙队",
                "captain_okki_user_id": "CAP2",
                "is_active": True,
                "members": [
                    {"okki_user_id": "CAP2", "name": "队长乙", "exclude_from_total": False, "is_active": True},
                ],
            },
        ],
        "admin_recipient_user_ids": [],
    }


def test_split_allocation_zero_member_and_team_scoped_exclusion():
    orders = [
        {
            "order_id": "O1", "order_no": "O1", "amount_usd": Decimal("100.01"),
            "user_id": "EX1", "user_name": "排除人员",
            "departments": '[{"department_id":1,"name":"甲队","rate":50},{"department_id":2,"name":"乙队","rate":50}]',
        },
        {
            "order_id": "O2", "order_no": "O2", "amount_usd": Decimal("-10"),
            "user_id": "CAP1", "user_name": "队长甲",
            "departments": '[{"department_id":1,"name":"甲队","rate":100}]',
        },
    ]
    report = calculate_report(date(2026, 8, 25), _config(), orders)
    first, second = report["teams"]

    assert report["company_raw_gmv"] == Decimal("90.01")
    assert first["raw_gmv"] == Decimal("40.01")
    assert first["excluded_gmv"] == Decimal("50.01")
    assert first["total_gmv"] == Decimal("-10.00")
    assert next(member for member in first["members"] if member["okki_user_id"] == "ZERO")["gmv"] == 0

    # EX1 在甲队的 50% 被排除；分到乙队的 50% 仍正常计入乙队。
    assert second["raw_gmv"] == Decimal("50.00")
    assert second["excluded_gmv"] == 0
    assert second["total_gmv"] == Decimal("50.00")
    assert report["company_excluded_gmv"] == Decimal("50.01")
    assert report["company_total_gmv"] == Decimal("40.00")
    assert report["allocation_gap_gmv"] == 0


def test_invalid_department_rates_are_disclosed_not_silently_normalized():
    orders = [{
        "order_id": "O1", "order_no": "O1", "amount_usd": Decimal("100"),
        "user_id": "CAP1", "user_name": "队长甲",
        "departments": '[{"department_id":1,"name":"甲队","rate":80}]',
    }]
    report = calculate_report(date(2026, 8, 25), _config(), orders)
    assert report["allocated_gmv"] == Decimal("80.00")
    assert report["allocation_gap_gmv"] == Decimal("20.00")
    assert any("不是 100%" in item for item in report["anomalies"])
    assert report["fatal_anomalies"]


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-1"])
def test_non_finite_or_negative_department_rate_is_fatal_but_does_not_crash(rate):
    report = calculate_report(date(2026, 8, 25), _config(), [{
        "order_id": "O1", "order_no": "O1", "amount_usd": Decimal("100"),
        "user_id": "CAP1", "user_name": "队长甲",
        "departments": f'[{ {"department_id": 1, "name": "甲队", "rate": rate} }]'.replace("'", '"'),
    }])
    assert report["fatal_anomalies"]


@pytest.mark.parametrize("amount", [None, "", "bad", "NaN", "Infinity"])
def test_invalid_amount_is_reported_instead_of_silently_becoming_zero(amount):
    report = calculate_report(date(2026, 8, 25), _config(), [{
        "order_id": "O1", "order_no": "O1", "amount_usd": amount,
        "user_id": "CAP1", "user_name": "队长甲",
        "departments": '[{"department_id":1,"name":"甲队","rate":100}]',
    }])
    assert report["company_raw_gmv"] == Decimal("0.00")
    assert any("amount_usd" in item for item in report["fatal_anomalies"])


def test_valid_order_query_uses_confirmed_business_rule(gmv_db):
    db = gmv_db
    db.execute(text("INSERT INTO lsordertest.user_basic (user_id, full_name) VALUES ('CAP1', '队长甲')"))
    rows = [
        ("A", "13972831656", "待回款", None, 100),
        ("B", "13972831654", "已结清", None, 200),
        ("C", "13972831654", "待回款", None, 300),
        ("D", "13972831656", "待回款", "个人订单", 400),
        ("E", "13972831656", "待回款", None, -50),
    ]
    for order_id, status, status_name, trail, amount in rows:
        db.execute(text("""
            INSERT INTO lsordertest.okki_orders
            (order_id, order_no, amount_usd, user_id, account_date, status, status_name, trail, departments)
            VALUES (:id, :id, :amount, 'CAP1', '2026-08-25', :status, :status_name, :trail,
                    :departments)
        """), {
            "id": order_id, "amount": amount, "status": status,
            "status_name": status_name, "trail": trail,
            "departments": '[{"department_id":1,"name":"甲队","rate":100}]',
        })
    db.commit()

    loaded = load_valid_orders(db, date(2026, 8, 25))
    assert {row["order_id"] for row in loaded} == {"A", "B", "E"}
    assert sum(Decimal(str(row["amount_usd"])) for row in loaded) == Decimal("250")


def _user_with_binding(db, *, user_id: int, okki_id: str, name: str) -> ArkUser:
    user = ArkUser(
        id=user_id, username=f"user{user_id}", password_hash="hash", real_name=name,
        dingtalk_id=f"ding-{user_id}", is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(ArkUserExternalBinding(
        ark_user_id=user.id, provider="okki", external_account_id=okki_id,
        external_display_name=name, binding_status="active", is_primary=True,
    ))
    db.commit()
    return user


def _save_test_config(db, admin_user_id: int = 101):
    body = {
        "teams": [{
            "department_id": 1, "name": "甲队", "captain_okki_user_id": "CAP1", "is_active": True,
            "members": [
                {"okki_user_id": "CAP1", "name": "队长甲", "exclude_from_total": False, "is_active": True},
                {"okki_user_id": "ZERO", "name": "零业绩", "exclude_from_total": False, "is_active": True},
            ],
        }],
        "admin_recipient_user_ids": [admin_user_id],
    }
    return save_config(db, GmvDailyConfigUpdate.model_validate(body))


def test_config_reuses_sys_dict_and_round_trips(gmv_db):
    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(db)
    saved = load_config(db)
    assert saved["persisted"] is True
    assert saved["teams"][0]["department_id"] == 1
    assert [member["name"] for member in saved["teams"][0]["members"]] == ["队长甲", "零业绩"]


def test_rejected_save_does_not_pollute_existing_config(gmv_db):
    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(db)
    invalid = GmvDailyConfigUpdate.model_validate({
        "teams": [{
            "department_id": 1, "name": "被拒绝的新名字",
            "captain_okki_user_id": "CAP1", "is_active": True,
            "members": [{"okki_user_id": "CAP1", "name": "队长甲"}],
        }],
        "admin_recipient_user_ids": [999],
    })

    with pytest.raises(ValueError, match="管理员接收人未绑定"):
        save_config(db, invalid)

    persisted = load_config(db)
    assert persisted["teams"][0]["name"] == "甲队"
    assert persisted["admin_recipient_user_ids"] == [101]


def test_gmv_reserved_dict_types_are_hidden_and_reject_generic_crud(gmv_db):
    db = gmv_db
    protected = SysDict(type="dingtalk_gmv_team", code="1", label="甲队", remark="CAP1")
    public = SysDict(type="public_test", code="x", label="公开字典")
    db.add_all([protected, public])
    db.commit()

    assert [item["type"] for item in system_dict_service.list_types(db)] == ["public_test"]
    assert system_dict_service.list_items(db, "dingtalk_gmv_team") == []
    with pytest.raises(system_dict_service.ProtectedDictTypeError):
        system_dict_service.create_item(db, DictItemCreate(
            type="dingtalk_gmv_admin", code="101", label="管理员",
        ))
    with pytest.raises(system_dict_service.ProtectedDictTypeError):
        system_dict_service.update_item(db, protected.id, DictItemUpdate(label="篡改"))
    with pytest.raises(system_dict_service.ProtectedDictTypeError):
        system_dict_service.delete_item(db, protected.id)


def test_malformed_persisted_config_fails_closed(gmv_db):
    gmv_db.add_all([
        SysDict(type="dingtalk_gmv_team", code="1", label="甲队", remark="CAP1"),
        SysDict(type="dingtalk_gmv_member", code="CAP1", label="队长甲", remark="not-json"),
    ])
    gmv_db.commit()

    with pytest.raises(ValueError, match="成员配置损坏"):
        load_config(gmv_db)


def test_first_use_defaults_contain_confirmed_teams_and_scoped_exclusions(gmv_db):
    config = load_config(gmv_db)
    assert config["persisted"] is False
    assert [team["name"] for team in config["teams"]] == [
        "专治不服", "多财多亿", "稻乐偲", "行则将至", "星星之火", "乘风", "无名", "嘉树",
    ]
    excluded = {
        (team["name"], member["name"])
        for team in config["teams"]
        for member in team["members"]
        if member["exclude_from_total"]
    }
    assert excluded == {("行则将至", "罗馨瑜"), ("乘风", "凯丽比努尔·阿伍提")}


def test_saved_config_requires_an_explicit_admin_recipient():
    body = {
        "teams": [{
            "department_id": 1, "name": "甲队", "captain_okki_user_id": "CAP1",
            "members": [{"okki_user_id": "CAP1", "name": "队长甲"}],
        }],
        "admin_recipient_user_ids": [],
    }
    with pytest.raises(ValidationError):
        GmvDailyConfigUpdate.model_validate(body)


@pytest.mark.parametrize(
    "body_patch",
    [
        {"team_name": " "},
        {"captain_id": " "},
        {"member_id": " "},
        {"member_name": " "},
    ],
    ids=["team-name", "captain-id", "member-id", "member-name"],
)
def test_config_rejects_whitespace_only_identity_fields(body_patch):
    body = {
        "teams": [{
            "department_id": 1,
            "name": body_patch.get("team_name", "甲队"),
            "captain_okki_user_id": body_patch.get("captain_id", "CAP1"),
            "is_active": False,
            "members": [{
                "okki_user_id": body_patch.get("member_id", "CAP1"),
                "name": body_patch.get("member_name", "队长甲"),
            }],
        }],
        "admin_recipient_user_ids": [101],
    }
    with pytest.raises(ValidationError, match="at least 1 character"):
        GmvDailyConfigUpdate.model_validate(body)


def test_markdown_displays_zero_and_excluded_member_but_uses_effective_total():
    report = calculate_report(date(2026, 8, 25), _config(), [{
        "order_id": "O1", "order_no": "O1", "amount_usd": Decimal("100"),
        "user_id": "EX1", "user_name": "排除人员",
        "departments": '[{"department_id":1,"name":"甲队","rate":100}]',
    }])
    team_text = render_team_markdown(report, report["teams"][0])
    admin_text = render_admin_markdown(report)
    assert "排除人员：**$100.00**" in team_text
    assert "零业绩：**$0.00**" in team_text
    assert "队伍汇总：**$0.00**" in team_text
    assert "公司原始 GMV：**$100.00**" in admin_text
    assert "公司考核 GMV：**$0.00**" in admin_text


@pytest.mark.asyncio
async def test_send_is_blocked_until_default_config_is_confirmed_and_saved(gmv_db):
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(return_value=True)})()

    with pytest.raises(ValueError, match="请先在 GMV 日报配置页"):
        await send_daily_report(gmv_db, date(2026, 8, 25), "all", notifier)

    notifier.send_to_users.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_is_blocked_when_financial_data_has_fatal_anomaly(gmv_db, monkeypatch):
    _user_with_binding(gmv_db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(gmv_db)
    monkeypatch.setattr(gmv_daily_service, "load_valid_orders", lambda *_args: [{
        "order_id": "O1", "order_no": "O1", "amount_usd": None,
        "user_id": "CAP1", "user_name": "队长甲",
        "departments": '[{"department_id":1,"name":"甲队","rate":100}]',
    }])
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(return_value=True)})()

    with pytest.raises(ValueError, match="阻断异常"):
        await send_daily_report(gmv_db, date(2026, 8, 25), "all", notifier)

    notifier.send_to_users.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_delivery_is_idempotent(gmv_db):
    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(db)
    db.execute(text("INSERT INTO lsordertest.user_basic (user_id, full_name) VALUES ('CAP1', '队长甲')"))
    db.execute(text("""
        INSERT INTO lsordertest.okki_orders
        (order_id, order_no, amount_usd, user_id, account_date, status, status_name, departments)
        VALUES ('O1', 'O1', 100, 'CAP1', '2026-08-25', '13972831656', '待回款',
                :departments)
    """), {"departments": '[{"department_id":1,"name":"甲队","rate":100}]'})
    db.commit()
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(return_value=True)})()

    first = await send_daily_report(db, date(2026, 8, 25), "teams", notifier)
    second = await send_daily_report(db, date(2026, 8, 25), "teams", notifier)

    assert first["deliveries"][0]["status"] == "success"
    assert second["deliveries"][0]["status"] == "skipped"
    assert notifier.send_to_users.await_count == 1
    assert db.query(DingTalkMessageLog).count() == 1


@pytest.mark.asyncio
async def test_failed_retry_reuses_original_snapshot(gmv_db):
    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(db)
    db.execute(text("INSERT INTO lsordertest.user_basic (user_id, full_name) VALUES ('CAP1', '队长甲')"))
    db.execute(text("""
        INSERT INTO lsordertest.okki_orders
        (order_id, order_no, amount_usd, user_id, account_date, status, status_name, departments)
        VALUES ('O1', 'O1', 100, 'CAP1', '2026-08-25', '13972831656', '待回款',
                :departments)
    """), {"departments": '[{"department_id":1,"name":"甲队","rate":100}]'})
    db.commit()
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(side_effect=[False, True])})()

    first = await send_daily_report(db, date(2026, 8, 25), "teams", notifier)
    db.execute(text("UPDATE lsordertest.okki_orders SET amount_usd=999 WHERE order_id='O1'"))
    db.commit()
    retried = await send_daily_report(db, date(2026, 8, 25), "teams", notifier)

    assert first["status"] == "partial_failure"
    assert retried["status"] == "completed"
    assert retried["deliveries"][0]["status"] == "success"
    first_text = notifier.send_to_users.await_args_list[0].kwargs["markdown_text"]
    second_text = notifier.send_to_users.await_args_list[1].kwargs["markdown_text"]
    assert "$100.00" in first_text
    assert second_text == first_text


@pytest.mark.asyncio
async def test_failed_snapshot_retries_even_if_source_order_becomes_fatal(gmv_db):
    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(db)
    db.execute(text("INSERT INTO lsordertest.user_basic (user_id, full_name) VALUES ('CAP1', '队长甲')"))
    db.execute(text("""
        INSERT INTO lsordertest.okki_orders
        (order_id, order_no, amount_usd, user_id, account_date, status, status_name, departments)
        VALUES ('O1', 'O1', 100, 'CAP1', '2026-08-25', '13972831656', '待回款',
                :departments)
    """), {"departments": '[{"department_id":1,"name":"甲队","rate":100}]'})
    db.commit()
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(side_effect=[False, True])})()

    first = await send_daily_report(db, date(2026, 8, 25), "teams", notifier)
    db.execute(text("UPDATE lsordertest.okki_orders SET amount_usd=NULL WHERE order_id='O1'"))
    db.commit()
    retried = await send_daily_report(db, date(2026, 8, 25), "teams", notifier)

    assert first["status"] == "partial_failure"
    assert retried["status"] == "completed"
    assert notifier.send_to_users.await_args_list[1].kwargs["markdown_text"] \
        == notifier.send_to_users.await_args_list[0].kwargs["markdown_text"]


@pytest.mark.asyncio
async def test_long_team_name_keeps_full_body_but_bounds_message_log_title(gmv_db):
    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    long_name = "长" * 128
    save_config(db, GmvDailyConfigUpdate.model_validate({
        "teams": [{
            "department_id": 1, "name": long_name, "captain_okki_user_id": "CAP1",
            "members": [{"okki_user_id": "CAP1", "name": "队长甲"}],
        }],
        "admin_recipient_user_ids": [101],
    }))
    db.execute(text("INSERT INTO lsordertest.user_basic (user_id, full_name) VALUES ('CAP1', '队长甲')"))
    db.commit()
    notifier = type("Notifier", (), {"send_to_users": AsyncMock(return_value=True)})()

    await send_daily_report(db, date(2026, 8, 25), "teams", notifier)

    log = db.query(DingTalkMessageLog).one()
    assert len(log.title) == 128
    assert long_name in log.content


@pytest.mark.asyncio
async def test_whole_batch_snapshot_is_persisted_before_first_external_call(gmv_db):
    class SimulatedProcessCrash(BaseException):
        pass

    db = gmv_db
    _user_with_binding(db, user_id=101, okki_id="CAP1", name="队长甲")
    _save_test_config(db)
    db.execute(text("INSERT INTO lsordertest.user_basic (user_id, full_name) VALUES ('CAP1', '队长甲')"))
    db.execute(text("""
        INSERT INTO lsordertest.okki_orders
        (order_id, order_no, amount_usd, user_id, account_date, status, status_name, departments)
        VALUES ('O1', 'O1', 100, 'CAP1', '2026-08-25', '13972831656', '待回款',
                :departments)
    """), {"departments": '[{"department_id":1,"name":"甲队","rate":100}]'})
    db.commit()
    crashing = type("Notifier", (), {"send_to_users": AsyncMock(side_effect=SimulatedProcessCrash())})()

    with pytest.raises(SimulatedProcessCrash):
        await send_daily_report(db, date(2026, 8, 25), "all", crashing)

    logs = db.query(DingTalkMessageLog).order_by(DingTalkMessageLog.id).all()
    assert len(logs) == 2
    assert all(log.send_status == "pending" and "$100.00" in log.content for log in logs)

    db.execute(text("UPDATE lsordertest.okki_orders SET amount_usd=999 WHERE order_id='O1'"))
    db.commit()
    recovered = type("Notifier", (), {"send_to_users": AsyncMock(return_value=True)})()
    await send_daily_report(db, date(2026, 8, 25), "all", recovered)
    sent_texts = [call.kwargs["markdown_text"] for call in recovered.send_to_users.await_args_list]
    assert len(sent_texts) == 2
    assert all("$100.00" in content and "$999.00" not in content for content in sent_texts)


def test_report_date_uses_beijing_midnight_even_when_instant_is_utc():
    # 16:00 UTC 已是北京时间次日 00:00，日报仍统计刚结束的北京时间前一天。
    instant = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
    assert report_date_for_run(instant) == date(2026, 8, 25)
