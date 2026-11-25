from datetime import date, datetime, timedelta, timezone
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
WEFT = "B1天才发帘（帘宽12“）"
ALL = ["spec", "color", "size"]
SPEC = '天才发帘(帘宽12")'


def line(day, kg, color="#1B", size="18", model=WEFT, user="u1", team="A", confidence="exact", country="US",
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
    monkeypatch.setattr(metrics, "load_lines", lambda *_: [dict(row) for row in data])
    return data


def test_split_grade_prefixes():
    assert radar_service.split_grade(WEFT) == ("B1", SPEC)
    assert radar_service.split_grade("B1 天才发帘(帘宽12\")") == ("B1", SPEC)  # 写法不同归为同一规格
    assert radar_service.split_grade("b3 Deep 天才发帘") == ("B3", "Deep 天才发帘")
    assert radar_service.split_grade("50%幅度铁丝") == ("50", "铁丝")
    assert radar_service.split_grade("50％ 幅度铁丝") == ("50", "铁丝")
    assert radar_service.split_grade("B10天才发帘") == (None, "")
    assert radar_service.split_grade("其他费用") == (None, "")
    assert radar_service.split_grade(None) == (None, "")


def test_windows_are_contiguous_and_validated():
    current, previous = radar_service.windows(60, TODAY)
    assert current == (date(2026, 9, 20), TODAY)
    assert previous == (date(2026, 7, 22), date(2026, 9, 19))
    with pytest.raises(HTTPException):
        radar_service.windows(7, TODAY)


def test_grade_tabs_and_sku_ranking(lines):
    lines.extend([
        line(date(2026, 10, 1), 5), line(date(2026, 10, 2), 3, user="u2"),
        line(date(2026, 7, 1), 2),
        line(date(2026, 10, 3), 1, color="#613"), line(date(2026, 7, 3), 4, color="#613"),
        line(date(2026, 10, 4), 2, color=metrics.UNKNOWN_LABEL),
        line(date(2026, 10, 5), 9, confidence="assumed", color=metrics.UNKNOWN_LABEL, size=metrics.UNKNOWN_LABEL),
        line(date(2026, 10, 1), 7, model="B3平型接发"),
        line(date(2026, 10, 1), 6, model="其他费用"),
    ])
    result = radar_service.get_radar(None, ME, "B1", ALL, 90, VERSION, TODAY)
    tabs = {tab["grade"]: tab["kg"] for tab in result["tabs"]}
    assert tabs == {"B1": 20, "B3": 7, "50": 0} and result["unclassified"]["kg"] == 6
    top = result["rows"][0]
    assert top["key"] == f"{SPEC} · #1B · 18" and top["values"]["color"] == "#1B"
    assert (top["kg"], top["delta_kg"], top["my_share"], top["rank"], top["prev_rank"]) == (8, 6, 0.625, 1, 2)
    assert result["movers"]["fallers"][0]["values"]["color"] == "#613"
    assert result["movers"]["fallers"][0]["growth"] == -0.75
    assert result["summary"]["excluded_quantity"] == 20  # 颜色未知 + 估算行
    assert result["summary"]["kg"] == 20 and result["summary"]["my_kg"] == 17
    assert result["credibility"]["comparable"] is False


def test_spec_only_includes_estimated_rows_but_color_does_not(lines):
    lines.extend([
        line(date(2026, 10, 1), 5),
        line(date(2026, 10, 2), 9, confidence="assumed", color=metrics.UNKNOWN_LABEL, size=metrics.UNKNOWN_LABEL),
    ])
    spec = radar_service.get_radar(None, ME, "B1", ["spec"], 90, VERSION, TODAY)
    assert spec["rows"][0]["kg"] == 14 and spec["summary"]["excluded_quantity"] == 0
    color = radar_service.get_radar(None, ME, "B1", ["color"], 90, VERSION, TODAY)
    assert color["rows"][0]["key"] == "#1B" and color["rows"][0]["kg"] == 5
    combo = radar_service.get_radar(None, ME, "B1", ["size", "color"], 90, VERSION, TODAY)
    assert combo["dims"] == ["color", "size"] and combo["rows"][0]["key"] == "#1B · 18"


def test_credibility_counts_rows_outside_any_grade(lines):
    # 上期大类内都是确切行，但还有识别不出型号的历史行：全公司口径不可信，不能判为可比
    lines.extend([line(date(2026, 10, 1), 5), line(date(2026, 7, 1), 5),
                  line(date(2026, 7, 2), None, model=metrics.UNKNOWN_LABEL, confidence="unknown")])
    result = radar_service.get_radar(None, ME, "B1", ["spec"], 90, VERSION, TODAY)
    assert result["credibility"]["current"]["credible"] is True
    assert result["credibility"]["previous"]["credible"] is False and result["credibility"]["comparable"] is False
    assert radar_service.get_grade_evidence(None, "B1", 90, VERSION, TODAY)["comparable"] is False


def test_accessory_estimates_do_not_drag_grades(lines):
    lines.extend([line(date(2026, 10, 1), 5), line(date(2026, 7, 1), 5)])
    lines.extend([line(date(2026, 10, 2), None, model="工具包", confidence="unknown") for _ in range(3)])
    result = radar_service.get_radar(None, ME, "B1", ["spec"], 90, VERSION, TODAY)
    assert result["credibility"]["comparable"] is True


def test_current_month_is_marked_partial(lines):
    lines.extend([line(date(2026, 10, 1), 5), line(date(2026, 11, 2), 1)])
    evidence = radar_service.get_grade_evidence(None, "B1", 90, VERSION, TODAY)
    last = evidence["monthly"][-1]
    assert last["month"] == "2026-11" and last["partial"] is True and last["days_covered"] == 18
    assert evidence["monthly"][-2]["partial"] is False


def test_detail_models_include_previous_window_and_breakdown_skips_estimates(lines):
    lines.extend([
        line(date(2026, 7, 1), 4, color="#613"),
        line(date(2026, 10, 1), 2, model="B1平型接发"),
        line(date(2026, 10, 1), 9, model="B1平型接发", confidence="assumed", color="#99", size="30"),
    ])
    faller = radar_service.get_item_detail(None, ME, "B1", {"color": "#613"}, 90, VERSION, TODAY)
    assert faller["models"] == [WEFT]
    spec = radar_service.get_item_detail(None, ME, "B1", {"spec": "平型接发"}, 90, VERSION, TODAY)
    blocks = {block["dim"]: block["rows"] for block in spec["breakdowns"]}
    assert [row["name"] for row in blocks["color"]] == ["#1B"] and spec["summary"]["kg"] == 11


def test_invalid_grade_and_dims_rejected(lines):
    for grade, dims in (("B2", ALL), ("B1", ["price"])):
        with pytest.raises(HTTPException) as bad:
            radar_service.get_radar(None, ME, grade, dims, 90, VERSION, TODAY)
        assert bad.value.status_code == 422


def test_unbound_user_gets_company_data_without_share(lines):
    lines.append(line(date(2026, 10, 1), 5))
    result = radar_service.get_radar(None, ShareScope("none", None, None, False, "未绑定"), "B1", ALL, 90, VERSION, TODAY)
    assert result["summary"]["my_kg"] is None and result["summary"]["my_share"] is None
    assert result["rows"][0]["my_kg"] == 0


def test_team_share(lines):
    lines.extend([line(date(2026, 10, 1), 5, team="A"), line(date(2026, 10, 1), 5, team="B", user="u9")])
    team = ShareScope("team", None, "A", True, "A 团队")
    result = radar_service.get_radar(None, team, "B1", ["spec"], 90, VERSION, TODAY)
    assert result["summary"]["kg"] == 10 and result["summary"]["my_kg"] == 5


def test_share_scope_requires_read_all_for_others():
    with pytest.raises(HTTPException) as denied:
        radar_service.resolve_share_scope(None, {"sub": "1", "permissions": ["product_sales:read"]}, "u2", None)
    assert denied.value.status_code == 403
    scope = radar_service.resolve_share_scope(None, {"sub": "1", "permissions": ["product_sales:read_all"]}, None, "A")
    assert scope.mode == "team" and scope.team == "A"


def test_item_detail_marks_estimate_months_and_breaks_down_other_dims(lines):
    lines.extend([
        line(date(2026, 10, 1), 5), line(date(2026, 10, 1), 3, size="22"),
        line(date(2026, 3, 1), 5, confidence="assumed", color="#2", size="16"),
        line(date(2026, 3, 2), 5),
    ])
    detail = radar_service.get_item_detail(None, ME, "B1", {"color": "#1B"}, 90, VERSION, TODAY)
    months = {m["month"]: m for m in detail["monthly"]}
    assert len(detail["monthly"]) == 12 and months["2026-10"]["credible"] is True
    assert months["2026-03"]["credible"] is False and months["2026-03"]["kg"] == 5
    breakdowns = {block["dim"]: block["rows"] for block in detail["breakdowns"]}
    assert set(breakdowns) == {"spec", "size"}
    assert breakdowns["size"][0] == {"name": "18", "kg": 5.0, "share": 0.625}
    assert detail["models"] == [WEFT] and detail["summary"]["kg"] == 8
    with pytest.raises(HTTPException) as missing:
        radar_service.get_item_detail(None, ME, "B1", {"color": "#999"}, 90, VERSION, TODAY)
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException):
        radar_service.get_item_detail(None, ME, "B1", {}, 90, VERSION, TODAY)


def test_lines_cache_is_shared_across_windows_until_version_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(metrics, "load_lines", lambda *_: calls.append(1) or [])
    for window in radar_service.WINDOW_CHOICES:
        radar_service.get_radar(None, ME, "B1", ALL, window, VERSION, TODAY)
    radar_service.cached_lines(None, date(2025, 12, 1), TODAY, VERSION)
    assert len(calls) == 1  # 四个窗口 + 12 个月走势共用一次加载
    radar_service.cached_lines(None, TODAY, TODAY, (1, 0, None))
    assert len(calls) == 2


def test_countries_with_few_customers_are_merged_or_hidden(lines):
    lines.extend([line(date(2026, 10, 1), 5, country="US", company=f"c{i}") for i in range(3)])
    lines.append(line(date(2026, 10, 1), 9, country="NZ", company="solo"))
    lines.append(line(date(2026, 10, 1), 7, country="FJ", company=""))
    detail = radar_service.get_item_detail(None, ME, "B1", {"color": "#1B", "size": "18"}, 90, VERSION, TODAY)
    assert {row["name"]: row["kg"] for row in detail["top_countries"]} == {"US": 15.0}
    lines.extend([line(date(2026, 10, 2), 1, country="NZ", company=f"n{i}") for i in range(2)])
    radar_service._lines_cache.clear()
    detail = radar_service.get_item_detail(None, ME, "B1", {"color": "#1B", "size": "18"}, 90, VERSION, TODAY)
    assert {row["name"]: row["kg"] for row in detail["top_countries"]} == {"US": 15.0, "NZ": 11.0}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ProductSalesAiInsight.__table__.create(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def test_grade_evidence_has_each_dimension_and_no_personal_share(lines):
    lines.extend([line(date(2026, 10, 1), 5), line(date(2026, 7, 1), 2, color="#613", user="u2")])
    evidence = radar_service.get_grade_evidence(None, "B1", 90, VERSION, TODAY)
    assert [block["dimension"] for block in evidence["dimensions"]] == ["颜色", "尺寸", "规格", "规格 × 颜色 × 尺寸"]
    assert evidence["dimensions"][0]["fallers"][0]["key"] == "#613"
    assert "my_kg" not in evidence["dimensions"][0]["top"][0]
    assert "u1" not in str(evidence) and "u2" not in str(evidence)
    assert len(evidence["monthly"]) == 12


def test_rules_fallback_is_not_cached_but_ai_result_is_shared(db, lines, monkeypatch):
    lines.append(line(date(2026, 10, 1), 5))
    monkeypatch.setattr(radar_service, "beijing_today", lambda: TODAY)
    calls = []
    outcome = {"fail": True}

    def fake_chat(**kwargs):
        calls.append(kwargs)
        if outcome["fail"]:
            raise RuntimeError("provider down")
        return {"content": "**总体**"}

    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "chat", fake_chat)
    first = insight_service.explain_grade(db, "B1", 90, VERSION, (0, None), 7)
    assert first["source"] == "rules" and first["comparable"] is False and "不下趋势结论" in first["content"]
    assert calls[0]["enforce_total_timeout"] is True and calls[0]["preset_name"] == "product_sales_grade_insight"
    assert "「B1」" in calls[0]["messages"][0]["content"]  # 大类取值运行时注入
    assert db.query(ProductSalesAiInsight).count() == 0  # 降级结果不落表

    outcome["fail"] = False
    second = insight_service.explain_grade(db, "B1", 90, VERSION, (0, None), 7)
    third = insight_service.explain_grade(db, "B1", 90, (9, 9, None), (0, None), 8)  # 换人、进程计数不同也复用
    assert (second["source"], second["reused"], third["reused"]) == ("ai", False, True)
    assert len(calls) == 2
    other = insight_service.explain_grade(db, "B1", 30, VERSION, (0, None), 7)
    assert other["reused"] is False and len(calls) == 3  # 窗口不同各算各的
    cooled = insight_service.explain_grade(db, "B1", 90, VERSION, (0, None), 7, refresh=True)
    assert cooled["reused"] is True and cooled["cooldown_until"] and len(calls) == 3  # 冷却期内不再打模型
    row = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.window_days == 90).one()
    row.created_at = row.created_at - timedelta(minutes=10)
    db.commit()
    outcome["fail"] = True
    kept = insight_service.explain_grade(db, "B1", 90, VERSION, (0, None), 7, refresh=True)
    assert kept["refresh_failed"] is True and kept["source"] == "ai" and kept["content"] == "**总体**"
    outcome["fail"] = False
    insight_service.explain_grade(db, "B1", 90, VERSION, (0, None), 7, refresh=True)
    assert len(calls) == 5 and db.query(ProductSalesAiInsight).count() == 2
    latest = insight_service.latest_grade_insight(db, "B1", 90, TODAY.isoformat(), (0, None))
    assert latest["content"] == "**总体**" and latest["reused"] is True and latest["cooldown_until"]
    row = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.window_days == 90).one()
    row.created_at = row.created_at - timedelta(minutes=10)
    db.commit()
    latest_ready = insight_service.latest_grade_insight(db, "B1", 90, TODAY.isoformat(), (0, None))
    assert latest_ready["cooldown_until"] is None
    assert insight_service.latest_grade_insight(db, "B3", 90, TODAY.isoformat(), (0, None)) is None


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
    result = insight_service.explain_grade(db, "B1", 30, VERSION, (0, None), 7)
    assert result["source"] == "ai"
    row = db.query(ProductSalesAiInsight).one()
    assert row.as_of_date == date(2026, 11, 18) and row.dimension == "grade" and row.item_key == "B1"
    assert row.created_at == datetime(2026, 11, 18, 0, 0) and row.expires_at == datetime(2026, 11, 19, 0, 0)
