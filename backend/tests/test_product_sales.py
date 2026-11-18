from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.product_sales import metrics, service
from app.product_sales.models import ProductSalesNameMapping


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ProductSalesNameMapping.__table__.create(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def raw(name, quantity=10, unit=None, model=None, color=None, size=None, day=date(2026, 8, 1)):
    return {
        "order_id": 1, "company_id": 2, "user_id": 3, "account_date": day, "country": "US",
        "product_name": name, "quantity": quantity,
        "p_model": model, "p_color": color, "p_size": size, "p_unit": unit,
    }


def test_parse_grams_only_accepts_gram_strings():
    assert metrics.parse_grams("20g") == Decimal("20")
    assert metrics.parse_grams(" 2.5 G ") == Decimal("2.5")
    assert metrics.parse_grams("Customized Order") is None
    assert metrics.parse_grams("#1") is None
    assert metrics.parse_grams("0g") is None


def test_exact_line_uses_product_unit_and_dimensions():
    line = metrics.classify_line(raw("B3/18/#8TP8/18/20g", unit="20g", model="B3", size="18"), {}, set())
    assert line["confidence"] == metrics.EXACT
    assert line["kg"] == Decimal("0.2")
    assert line["color"] == "#8TP8/18"


def test_structured_name_is_derived_only_for_known_models():
    known = {metrics.spec_key("Standard Keratin", "18")}
    derived = metrics.classify_line(raw("Standard Keratin/18/#8/1g", quantity=100), {}, known)
    assumed = metrics.classify_line(raw("Odd Hair/18/#8/1g", quantity=100), {}, known)
    assert derived["confidence"] == metrics.DERIVED and derived["kg"] == Decimal("0.1")
    assert assumed["confidence"] == metrics.ASSUMED


def test_history_name_uses_mapping_and_keeps_color_unknown():
    name = "B3新天才发帘（帘宽12“）"
    mapping = ProductSalesNameMapping(
        name_hash=metrics.name_hash(name), product_name=name, model="B3新天才发帘", unit_grams=Decimal("20"),
        status="confirmed", rule_version="v1",
    )
    line = metrics.classify_line(raw(name, quantity=5), {mapping.name_hash: mapping}, set())
    assert line["confidence"] == metrics.ASSUMED
    assert line["model"] == "B3新天才发帘"
    assert line["color"] == metrics.UNKNOWN_LABEL
    assert line["kg"] == Decimal("0.1")


def test_ignored_and_unmapped_names_count_pieces_without_kg():
    name = "8寸色板"
    ignored = ProductSalesNameMapping(
        name_hash=metrics.name_hash(name), product_name=name, model="色板", unit_grams=Decimal("150"),
        status="ignored", rule_version="v1",
    )
    assert metrics.classify_line(raw(name), {ignored.name_hash: ignored}, set())["kg"] is None
    unmapped = metrics.classify_line(raw("Human virgin hair"), {}, set())
    assert unmapped["confidence"] == metrics.UNKNOWN and unmapped["kg"] is None


def test_name_hash_ignores_quote_width_and_spacing():
    assert metrics.name_hash("B3新天才发帘（帘宽12“）") == metrics.name_hash(" b3新天才发帘(帘宽12\")  ")


def test_monthly_coverage_flags_estimate_months_by_pieces():
    lines = [
        {"account_date": date(2026, 7, 3), "quantity": Decimal(95), "confidence": "exact", "kg": Decimal(1)},
        {"account_date": date(2026, 7, 9), "quantity": Decimal(5), "confidence": "unknown", "kg": None},
        {"account_date": date(2026, 3, 9), "quantity": Decimal(50), "confidence": "assumed", "kg": Decimal(1)},
        {"account_date": date(2026, 3, 9), "quantity": Decimal(50), "confidence": "exact", "kg": Decimal(1)},
    ]
    result = {row["month"]: row for row in metrics.monthly_coverage(lines)}
    assert result["2026-07"]["credible"] is True and result["2026-07"]["credible_share"] == 0.95
    assert result["2026-03"]["credible"] is False and result["2026-03"]["kg"] == 2.0


def test_suggest_prefers_current_model_then_category_rule_then_name_grams():
    index = {service._model_key("B3天才发帘（帘宽12″）"): ("B3天才发帘（帘宽12″）", Decimal("20"))}
    assert service.suggest("B3新天才发帘（帘宽12“）", index) == ("B3天才发帘（帘宽12″）", Decimal("20"), "okki_model")
    assert service.suggest("B3 50克天才发帘（帘宽24“）", index) == (None, Decimal("50"), "category_rule")
    assert service.suggest("B3平型", index) == (None, Decimal("1"), "category_rule")
    assert service.suggest("One Donor 100g Human Hair Weft", index) == (None, Decimal("100"), "name_grams")
    assert service.suggest("Human virgin hair", index) == (None, None, None)


def _history_lines(*names_quantities):
    exact = metrics.classify_line(raw("B3/18/#1B/20g", unit="20g", model="天才发帘"), {}, set())
    lines = [exact]
    for name, quantity in names_quantities:
        lines.append(metrics.classify_line(raw(name, quantity=quantity, day=date(2025, 5, 1)), {}, set()))
    return lines


def test_refresh_creates_suggestions_and_never_overwrites_confirmation(db, monkeypatch):
    monkeypatch.setattr(metrics, "load_lines", lambda *_: _history_lines(("天才发帘", 4), ("天才发帘", 6), ("Odd", 1)))
    first = service.refresh_mappings(db, date(2026, 11, 18))
    assert first["created"] == 2 and first["pending"] == 2
    row = db.query(ProductSalesNameMapping).filter_by(product_name="天才发帘").one()
    assert (row.model, row.unit_grams, row.quantity_total, row.line_count) == ("天才发帘", Decimal("20"), Decimal(10), 2)

    service.save_mappings(db, 9, [{"id": row.id, "status": "confirmed", "model": "B3天才", "unit_grams": 25}])
    monkeypatch.setattr(metrics, "load_lines", lambda *_: _history_lines(("天才发帘", 1)))
    second = service.refresh_mappings(db, date(2026, 11, 18))
    db.refresh(row)
    assert second["created"] == 0
    assert (row.status, row.model, row.unit_grams, row.quantity_total) == ("confirmed", "B3天才", Decimal("25"), Decimal(1))
    assert row.confirmed_by_user_id == 9 and row.confirmed_at is not None


def test_confirm_requires_model_and_valid_grams(db):
    row = ProductSalesNameMapping(name_hash="h", product_name="X", status="suggested", rule_version="v1")
    db.add(row)
    db.commit()
    with pytest.raises(HTTPException) as missing:
        service.save_mappings(db, 1, [{"id": row.id, "status": "confirmed", "model": "X", "unit_grams": None}])
    assert missing.value.status_code == 422
    with pytest.raises(HTTPException):
        service.save_mappings(db, 1, [{"id": row.id, "status": "confirmed", "model": "X", "unit_grams": 9000}])
    with pytest.raises(HTTPException) as unknown:
        service.save_mappings(db, 1, [{"id": 999, "status": "ignored"}])
    assert unknown.value.status_code == 404
    service.save_mappings(db, 1, [{"id": row.id, "status": "ignored", "model": None, "unit_grams": None}])
    assert service.list_mappings(db, "ignored", None, 1, 20)["status_counts"]["ignored"] == 1


def test_manual_decision_overrides_structured_name_rules():
    name = "Odd Hair/18/#8/1g"
    confirmed = ProductSalesNameMapping(
        name_hash=metrics.name_hash(name), product_name=name, model="Odd", unit_grams=Decimal("2"),
        status="confirmed", rule_version="v1",
    )
    line = metrics.classify_line(raw(name, quantity=100), {confirmed.name_hash: confirmed}, set())
    assert (line["confidence"], line["model"], line["kg"]) == (metrics.ASSUMED, "Odd", Decimal("0.2"))
    confirmed.status = "ignored"
    assert metrics.classify_line(raw(name, quantity=100), {confirmed.name_hash: confirmed}, set())["kg"] is None
    confirmed.status = "suggested"
    assert metrics.classify_line(raw(name, quantity=100), {confirmed.name_hash: confirmed}, set())["kg"] == Decimal("0.1")


def test_derived_requires_model_and_size_to_match_current_products():
    known = {metrics.spec_key("Standard Keratin", "18")}
    assert metrics.classify_line(raw("Standard Keratin/18/#8/1g"), {}, known)["confidence"] == metrics.DERIVED
    assert metrics.classify_line(raw("Standard Keratin/22/#8/1g"), {}, known)["confidence"] == metrics.ASSUMED


def test_ignore_keeps_model_and_rejects_non_finite_grams(db):
    row = ProductSalesNameMapping(name_hash="h2", product_name="Y", model="B3", status="suggested", rule_version="v1")
    db.add(row)
    db.commit()
    service.save_mappings(db, 1, [{"id": row.id, "status": "ignored", "model": None, "unit_grams": None}])
    assert row.model == "B3"
    with pytest.raises(HTTPException) as nan:
        service.save_mappings(db, 1, [{"id": row.id, "status": "confirmed", "model": "B3", "unit_grams": float("nan")}])
    assert nan.value.status_code == 422


def test_keyword_search_treats_like_wildcards_literally(db):
    db.add_all([
        ProductSalesNameMapping(name_hash="a", product_name="50%幅度天才发帘", status="suggested", rule_version="v1"),
        ProductSalesNameMapping(name_hash="b", product_name="500幅度天才发帘", status="suggested", rule_version="v1"),
    ])
    db.commit()
    names = [item["product_name"] for item in service.list_mappings(db, None, "50%", 1, 20)["items"]]
    assert names == ["50%幅度天才发帘"]


class _FrozenDatetime(__import__("datetime").datetime):
    """服务器时钟停在 UTC 2026-11-17 16:00（= 北京 2026-11-18 00:00）。"""

    @classmethod
    def now(cls, tz=None):
        from datetime import datetime as real, timezone
        instant = real(2026, 11, 17, 16, 0, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


def test_times_use_beijing_clock_on_utc_server_at_midnight(db, monkeypatch):
    from datetime import datetime

    from app.core import time as core_time

    monkeypatch.setattr(core_time, "datetime", _FrozenDatetime)
    seen = {}

    def fake_lines(_db, start, end):
        seen["window"] = (start, end)
        return _history_lines(("天才发帘", 3))

    monkeypatch.setattr(metrics, "load_lines", fake_lines)
    service.refresh_mappings(db)
    assert seen["window"] == (date(2025, 1, 1), date(2026, 11, 18))
    row = db.query(ProductSalesNameMapping).filter_by(product_name="天才发帘").one()
    assert row.last_seen_date == date(2025, 5, 1)
    service.save_mappings(db, 5, [{"id": row.id, "status": "confirmed", "model": "B3", "unit_grams": 20}])
    assert row.confirmed_at == datetime(2026, 11, 18, 0, 0)


def test_coverage_cache_invalidates_after_mapping_save(db, monkeypatch):
    calls = []
    monkeypatch.setattr(metrics, "load_lines", lambda *_: calls.append(1) or [])
    service._coverage_cache.clear()
    service.coverage(db, date(2026, 1, 1), date(2026, 1, 31))
    service.coverage(db, date(2026, 1, 1), date(2026, 1, 31))
    assert len(calls) == 1
    row = ProductSalesNameMapping(name_hash="c", product_name="Z", status="suggested", rule_version="v1")
    db.add(row)
    db.commit()
    service.save_mappings(db, 1, [{"id": row.id, "status": "ignored", "model": None, "unit_grams": None}])
    service.coverage(db, date(2026, 1, 1), date(2026, 1, 31))
    assert len(calls) == 2


def test_tiny_grams_are_rejected_instead_of_rounded_to_zero():
    with pytest.raises(HTTPException):
        service._grams(0.0004)
    assert service._grams(0.0006) == Decimal("0.001")
