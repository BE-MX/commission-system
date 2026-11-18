from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.product_sales import insight_service, metrics, radar_service
from app.product_sales.insight_models import ProductSalesAiInsight
from app.product_sales.radar_service import ShareScope

TODAY = date(2026, 11, 18)
ME = ShareScope("self", "u1", None, False, "我")
VERSION = (0, 0, None)
KEY = "#1B · 18"


def line(day, kg, color="#1B", size="18", model="B3", user="u1", team="A", confidence="exact", country="US",
         company="c1"):
    return {
        "company_id": company,
        "account_date": day, "kg": Decimal(str(kg)) if kg is not None else None, "quantity": Decimal(10),
        "color": color, "size": size, "model": model, "user_id": user, "user_name": user, "team": team,
        "confidence": confidence, "country": country, "unit_grams": Decimal(20), "product_name": "x",
    }


@pytest.fixture(autouse=True)
def lines(monkeypatch):
    data = []
    radar_service._lines_cache.clear()
    monkeypatch.setattr(metrics, "load_lines", lambda *_: data)
    return data


def test_windows_are_contiguous_and_validated():
    current, previous = radar_service.windows(90, TODAY)
    assert current == (date(2026, 8, 21), TODAY)
    assert previous == (date(2026, 5, 23), date(2026, 8, 20))
    with pytest.raises(HTTPException):
        radar_service.windows(7, TODAY)


def test_radar_movers_share_and_exclusions(lines):
    lines.extend([
        line(date(2026, 10, 1), 5), line(date(2026, 10, 2), 3, user="u2"),
        line(date(2026, 7, 1), 2),
        line(date(2026, 10, 3), 1, color="#613"), line(date(2026, 7, 3), 4, color="#613"),
        line(date(2026, 10, 4), 2, color=metrics.UNKNOWN_LABEL),
        line(date(2026, 10, 5), 9, confidence="assumed", color=metrics.UNKNOWN_LABEL, size=metrics.UNKNOWN_LABEL),
    ])
    result = radar_service.get_radar(None, ME, 90, None, VERSION, TODAY)
    risers, fallers = result["color_size"]["risers"], result["color_size"]["fallers"]
    assert risers[0]["key"] == KEY and risers[0]["kg"] == 8 and risers[0]["delta_kg"] == 6
    assert risers[0]["my_share"] == 0.625
    assert fallers[0]["key"] == "#613 · 18" and fallers[0]["growth"] == -0.75
    assert result["summary"]["color_size_excluded_quantity"] == 20
    assert result["summary"]["kg"] == 20 and result["summary"]["my_kg"] == 17
    assert result["credibility"]["comparable"] is False  # 本期有 assumed 行，确切件数占比 < 90%


def test_unbound_user_gets_company_data_without_share(lines):
    lines.append(line(date(2026, 10, 1), 5))
    result = radar_service.get_radar(None, ShareScope("none", None, None, False, "未绑定"), 90, None, VERSION, TODAY)
    assert result["summary"]["my_kg"] is None and result["summary"]["my_share"] is None
    assert result["color_size"]["top"][0]["my_kg"] == 0


def test_team_share_and_model_filter(lines):
    lines.extend([line(date(2026, 10, 1), 5, team="A"), line(date(2026, 10, 1), 5, team="B", user="u9", model="B1")])
    team = ShareScope("team", None, "A", True, "A 团队")
    result = radar_service.get_radar(None, team, 90, ["B1"], VERSION, TODAY)
    assert result["summary"]["kg"] == 5 and result["summary"]["my_kg"] == 0
    assert result["model_options"] == ["B1", "B3"]


def test_small_risers_skip_top_items_and_slow_growth(lines, monkeypatch):
    monkeypatch.setattr(radar_service, "SMALL_ITEM_TOP_N", 1)
    lines.extend([
        line(date(2026, 7, 1), 100), line(date(2026, 10, 1), 120),                     # 上期第一：不算小款
        line(date(2026, 10, 1), 3, model="Mini"),                                       # 新出现
        line(date(2026, 7, 1), 2, model="Slow"), line(date(2026, 10, 1), 2.5, model="Slow"),  # 只涨 25%
    ])
    picked = radar_service.get_radar(None, ME, 90, None, VERSION, TODAY)["small_risers"]
    assert [row["key"] for row in picked] == ["Mini · #1B · 18"]


def test_share_scope_requires_read_all_for_others():
    with pytest.raises(HTTPException) as denied:
        radar_service.resolve_share_scope(None, {"sub": "1", "permissions": ["product_sales:read"]}, "u2", None)
    assert denied.value.status_code == 403
    scope = radar_service.resolve_share_scope(None, {"sub": "1", "permissions": ["product_sales:read_all"]}, None, "A")
    assert scope.mode == "team" and scope.team == "A"


def test_item_detail_marks_estimate_months_and_404s_unknown(lines):
    lines.extend([
        line(date(2026, 10, 1), 5),
        line(date(2026, 3, 1), 5, confidence="assumed", color="#2", size="16"),
        line(date(2026, 3, 2), 5),
    ])
    detail = radar_service.get_item_detail(None, ME, "color_size", KEY, 90, VERSION, TODAY)
    months = {m["month"]: m for m in detail["monthly"]}
    assert len(detail["monthly"]) == 12 and months["2026-10"]["credible"] is True
    assert months["2026-03"]["credible"] is False and months["2026-03"]["kg"] == 5
    assert detail["top_models"][0] == {"name": "B3", "kg": 5.0, "share": 1.0}
    with pytest.raises(HTTPException) as missing:
        radar_service.get_item_detail(None, ME, "color_size", "#999 · 30", 90, VERSION, TODAY)
    assert missing.value.status_code == 404


def test_lines_cache_is_shared_across_windows_until_version_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(metrics, "load_lines", lambda *_: calls.append(1) or [])
    for window in radar_service.WINDOW_CHOICES:
        radar_service.get_radar(None, ME, window, None, VERSION, TODAY)
    radar_service.cached_lines(None, date(2025, 12, 1), TODAY, VERSION)
    assert len(calls) == 1  # 三个窗口 + 12 个月走势共用一次加载
    radar_service.cached_lines(None, TODAY, TODAY, (1, 0, None))
    assert len(calls) == 2


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ProductSalesAiInsight.__table__.create(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def test_rules_fallback_is_not_cached_but_ai_result_is_reused(db, lines, monkeypatch):
    lines.append(line(date(2026, 10, 1), 5))
    monkeypatch.setattr(radar_service, "beijing_today", lambda: TODAY)
    calls = []
    outcome = {"fail": True}

    def fake_chat(**kwargs):
        calls.append(kwargs)
        if outcome["fail"]:
            raise RuntimeError("provider down")
        return {"content": "现状"}

    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "chat", fake_chat)
    first = insight_service.explain(db, ME, "color_size", KEY, 90, VERSION, (0, None), 7)
    assert first["source"] == "rules" and first["comparable"] is False and "不下趋势结论" in first["content"]
    assert calls[0]["enforce_total_timeout"] is True and calls[0]["timeout_sec"] == 30
    assert KEY in calls[0]["messages"][0]["content"]  # 款的取值运行时注入
    assert db.query(ProductSalesAiInsight).count() == 0  # 降级结果不落表

    outcome["fail"] = False
    second = insight_service.explain(db, ME, "color_size", KEY, 90, VERSION, (0, None), 7)
    third = insight_service.explain(db, ME, "color_size", KEY, 90, (9, 9, None), (0, None), 7)  # 进程计数不同也复用
    assert (second["source"], second["reused"], third["reused"]) == ("ai", False, True)
    assert len(calls) == 2
    insight_service.explain(db, ME, "color_size", KEY, 90, VERSION, (0, None), 7, refresh=True)
    assert len(calls) == 3 and db.query(ProductSalesAiInsight).count() == 1


def test_insight_cache_is_scoped_per_share(db, lines, monkeypatch):
    lines.append(line(date(2026, 10, 1), 5))
    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "chat", lambda **_: {"content": "现状"})
    team = ShareScope("team", None, "A", True, "A 团队")
    insight_service.explain(db, team, "color_size", KEY, 90, VERSION, (0, None), 7)
    mine = insight_service.explain(db, ME, "color_size", KEY, 90, VERSION, (0, None), 8)
    assert mine["reused"] is False


def test_countries_with_few_customers_are_merged_or_hidden(lines):
    lines.extend([line(date(2026, 10, 1), 5, country="US", company=f"c{i}") for i in range(3)])
    lines.append(line(date(2026, 10, 1), 9, country="NZ", company="solo"))
    lines.append(line(date(2026, 10, 1), 7, country="FJ", company=""))
    detail = radar_service.get_item_detail(None, ME, "color_size", KEY, 90, VERSION, TODAY)
    assert {row["name"]: row["kg"] for row in detail["top_countries"]} == {"US": 15.0}  # 「其他」只有 1 个客户，不展示
    lines.extend([line(date(2026, 10, 2), 1, country="NZ", company=f"n{i}") for i in range(2)])
    radar_service._lines_cache.clear()
    detail = radar_service.get_item_detail(None, ME, "color_size", KEY, 90, VERSION, TODAY)
    # NZ 凑够 3 个客户后单独展示；缺客户 ID 的 FJ 进「其他」但其他客户数为 0，不展示
    assert {row["name"]: row["kg"] for row in detail["top_countries"]} == {"US": 15.0, "NZ": 11.0}


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)  # 北京 2026-11-18 00:00
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


def test_insight_uses_beijing_clock_on_utc_server(db, lines, monkeypatch):
    from app.core import time as core_time

    monkeypatch.setattr(core_time, "datetime", _Frozen)
    lines.append(line(date(2026, 11, 18), 5))
    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "chat", lambda **_: {"content": "现状"})
    result = insight_service.explain(db, ME, "color_size", KEY, 30, VERSION, (0, None), 7)
    assert result["source"] == "ai"
    row = db.query(ProductSalesAiInsight).one()
    assert row.as_of_date == date(2026, 11, 18)
    assert row.created_at == datetime(2026, 11, 18, 0, 0) and row.expires_at == datetime(2026, 11, 19, 0, 0)
