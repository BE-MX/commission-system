"""Isolated settlement tests; no production database or paid AI calls."""

import json
import random
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.time import BEIJING_TIMEZONE
from app.fx_settlement.engine import calculate_plan
from app.fx_settlement.market_service import parse_boc_quotes, parse_fred_history, trend_summary
from app.fx_settlement.schemas import SettlementInput

NOW = datetime(2026, 9, 24, 18, 0)


def payload(**changes):
    return SettlementInput(**{
        "usd_balance": "100000", "reserved_usd": "20000", "immediate_cny_need": "200000",
        "settle_by": "2026-10-24", "max_loss_cny": "2000", "stress_drop_pct": "2",
        "bank_rate": "6.7", "bank_quote_at": NOW.isoformat(), **changes,
    })


def market():
    return {"checked_at": NOW.isoformat(), "quote": {"rate": 6.7, "as_of": NOW.isoformat(), "usable": True},
            "trend": {"usable": True, "as_of": "2026-09-18", "change_5d_pct": -0.2}, "warnings": [], "history": []}


def test_cash_reserve_loss_budget_and_conservation():
    result = calculate_plan(payload(), market(), NOW)
    assert result["available_usd"] == 80000
    assert result["maximum_later_usd"] == 14925.37
    assert result["minimum_now_usd"] == 65074.63
    for candidate in result["candidates"]:
        assert round(candidate["now_usd"]+candidate["later_usd"]+result["reserved_usd"], 2) == 100000
        assert candidate["now_cny"] >= 200000
        assert candidate["stress_loss_cny"] <= 2000
        assert round(sum(item["usd"] for item in candidate["schedule"]), 2) == candidate["later_usd"]
        assert candidate["scenarios"][0]["total_cny"] <= candidate["scenarios"][2]["total_cny"]


def test_insufficient_cash_reports_gap_without_spending_reserved_dollars():
    result = calculate_plan(payload(immediate_cny_need="600000"), market(), NOW)
    assert result["cash_shortfall_cny"] == 64000
    assert result["reserved_usd"] == 20000
    assert all(c["now_usd"] == 80000 and c["later_usd"] == 0 for c in result["candidates"])


@pytest.mark.parametrize("changes", [
    {"max_loss_cny": "0"}, {"settle_by": "2026-09-24"},
    {"max_loss_cny": "0", "usd_interest_pct": "20", "stress_drop_pct": "0.1"},
])
def test_zero_budget_or_today_means_no_waiting(changes):
    result = calculate_plan(payload(**changes), market(), NOW)
    assert all(row["later_usd"] == 0 for row in result["candidates"])


def test_all_reserved_and_zero_need_is_valid_but_no_available_funds():
    result = calculate_plan(payload(reserved_usd="100000", immediate_cny_need="0"), market(), NOW)
    assert result["available_usd"] == 0
    assert all(row["now_usd"] == 0 for row in result["candidates"])


def test_cash_spent_does_not_earn_interest_and_fees_apply_once():
    result = calculate_plan(payload(usd_balance="100", reserved_usd="0", immediate_cny_need="300", max_loss_cny="1000", fee_bps="100", cny_interest_pct="10", settle_by="2027-09-24"), market(), NOW)
    immediate = result["candidates"][0]
    assert immediate["now_cny"] == 663.3
    assert immediate["scenarios"][1]["total_cny"] == 699.63  # 663.3 + (663.3 - 300) * 10%


@pytest.mark.parametrize("changes", [
    {"reserved_usd": "100001"}, {"usd_balance": "-1"}, {"usd_balance": "NaN"},
    {"usd_balance": "100.001"}, {"stress_drop_pct": "0"}, {"bank_quote_at": None},
    {"fee_bps": "1001"}, {"max_loss_cny": "-1"},
])
def test_invalid_financial_inputs_rejected(changes):
    with pytest.raises(ValidationError):
        payload(**changes)


def test_manual_quote_converts_external_timezone_before_age_check():
    # 23:59 UTC is 07:59 the next day in Beijing; server local zone is irrelevant.
    data = payload(bank_quote_at="2026-09-23T23:59:00Z", settle_by="2026-09-24")
    assert data.bank_quote_at == datetime(2026, 9, 24, 7, 59)
    result = calculate_plan(data, market(), datetime(2026, 9, 24, 8, 0))
    assert result["horizon_days"] == 0
    # Beijing midnight is the date boundary, even for a negative UTC offset input.
    midnight = payload(bank_quote_at="2026-09-23T09:59:00-06:00", settle_by="2026-09-24")
    calculate_plan(midnight, market(), datetime(2026, 9, 24, 0, 1))


@pytest.mark.parametrize("minutes", [-6, 16])
def test_future_and_stale_manual_quotes_rejected(minutes):
    data = payload(bank_quote_at=(NOW-timedelta(minutes=minutes)).isoformat())
    with pytest.raises(ValueError, match="报价"):
        calculate_plan(data, market(), NOW)


def test_stale_public_quote_cannot_be_made_fresh_by_client_flag():
    stale = market()
    stale["quote"]["as_of"] = (NOW-timedelta(minutes=31)).isoformat()
    with pytest.raises(ValueError, match="过期"):
        calculate_plan(payload(bank_rate=None, bank_quote_at=None), stale, NOW)


@pytest.mark.parametrize("day", ["2026-09-23", "2027-09-25"])
def test_invalid_deadline_rejected(day):
    with pytest.raises(ValueError, match="日期"):
        calculate_plan(payload(settle_by=day), market(), NOW)


def test_random_plans_stay_inside_principal_and_stress_budget():
    rng = random.Random(41)
    for _ in range(80):
        balance = rng.randint(1, 10000000)
        reserve = rng.randint(0, balance)
        budget = rng.randint(0, 100000)
        result = calculate_plan(payload(usd_balance=str(balance), reserved_usd=str(reserve), immediate_cny_need="0", max_loss_cny=str(budget)), market(), NOW)
        for row in result["candidates"]:
            assert row["now_usd"] >= 0 and row["later_usd"] >= 0
            assert round(row["now_usd"]+row["later_usd"], 2) == balance-reserve
            assert row["stress_loss_cny"] <= budget


def test_boc_uses_spot_buying_not_selling_or_conversion_rate():
    html = '<table><tr><td>美元</td><td>670.42</td><td>668.00</td><td>673.24</td><td>674</td><td>674.89</td><td>2026/09/24</td><td>17:45:33</td></tr></table>'
    quotes = parse_boc_quotes(html, NOW)
    assert quotes == [{"rate": 6.7042, "as_of": "2026-09-24T17:45:33"}]
    with pytest.raises(ValueError):
        parse_boc_quotes(html.replace("2026/09/24", "2026/09/25"), NOW)
    with pytest.raises(ValueError):
        parse_boc_quotes('<html>temporarily unavailable</html>', NOW)


def test_history_excludes_missing_and_future_quotes_and_marks_lag():
    lines = ["observation_date,DEXCHUS"]
    lines += [f"2026-08-{day:02d},{7-day/100}" for day in range(1, 29)]
    lines += ["2026-08-29,", "2026-08-30,.", "2026-09-25,7.0"]
    history = parse_fred_history("\n".join(lines), NOW.date())
    assert len(history) == 28
    assert not trend_summary(history, NOW)["usable"]
    assert trend_summary(history, NOW)["change_20d_pct"] < 0


def test_ai_success_is_grounded_and_does_not_log_amounts(monkeypatch):
    from app.fx_settlement import service
    monkeypatch.setattr(service, "build_plan", lambda data: calculate_plan(data, market(), NOW))
    reply = {"strategy_id": "immediate", "reason_ids": ["cash_need", "loss_budget"], "watchpoint_ids": ["quote_change"]}
    mock = Mock(return_value={"content": json.dumps(reply)})
    monkeypatch.setattr(service, "chat", mock)
    result = service.generate_advice(Mock(), payload(), "12341")
    assert result["selection_source"] == "ai" and result["selected_id"] == "immediate"
    assert mock.call_args.kwargs["snapshot_mode"] == "metadata"
    assert "allowed_strategy_ids" in mock.call_args.kwargs["messages"][1]["content"]
    evidence = json.loads(mock.call_args.kwargs["messages"][1]["content"])
    assert evidence["analysis_contract"] == service.SYSTEM_PROMPT


@pytest.mark.parametrize("content", [
    'not json',
    '{"strategy_id":"invented","reason_ids":["cash_need"],"watchpoint_ids":["quote_change"]}',
    '{"strategy_id":"balanced","reason_ids":["invented"],"watchpoint_ids":["quote_change"]}',
    '{"strategy_id":"balanced","reason_ids":["cash_need"],"watchpoint_ids":["quote_change"],"summary":"保证上涨，只结汇1美元"}',
])
def test_ai_invalid_output_remains_explicit_rules_result(monkeypatch, content):
    from app.fx_settlement import service
    monkeypatch.setattr(service, "build_plan", lambda data: calculate_plan(data, market(), NOW))
    monkeypatch.setattr(service, "chat", Mock(return_value={"content": content}))
    service._last_call.clear()
    result = service.generate_advice(Mock(), payload(), "12342")
    assert result["ai"] is None and result["selection_source"] == "rules"
    assert result["ai_status"] == "unavailable"


def test_ai_cooldown_prevents_duplicate_call(monkeypatch):
    from app.fx_settlement import service
    from fastapi import HTTPException
    monkeypatch.setattr(service, "build_plan", lambda data: calculate_plan(data, market(), NOW))
    monkeypatch.setattr(service, "chat", Mock(side_effect=RuntimeError("offline")))
    service.generate_advice(Mock(), payload(), "12343")
    with pytest.raises(HTTPException) as exc:
        service.generate_advice(Mock(), payload(), "12343")
    assert exc.value.status_code == 429


def test_http_permissions_and_envelope(monkeypatch):
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.fx_settlement import service
    from app.fx_settlement.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/fx-settlement")
    client = TestClient(app)
    assert client.get("/api/fx-settlement/market").status_code in (401, 403)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "41", "permissions": []}
    assert client.post("/api/fx-settlement/calculate", json=payload().model_dump(mode="json")).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {"sub": "41", "permissions": ["fx_settlement:read"]}
    monkeypatch.setattr(service, "build_plan", lambda data: calculate_plan(data, market(), NOW))
    response = client.post("/api/fx-settlement/calculate", json=payload().model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["data"]["available_usd"] == 80000
    app.dependency_overrides[get_db] = lambda: Mock()
    assert client.post("/api/fx-settlement/advice", json=payload().model_dump(mode="json")).status_code == 403
