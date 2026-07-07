"""对外库存查询（stock/public_service）单元测试：key 门禁、分层、查询口径与字段白名单。"""

import pytest
from sqlalchemy import text

from app.stock import public_service
from app.stock.public_service import availability_tier, parse_keys, query_public_inventory


def test_availability_tier_boundaries():
    assert availability_tier(-3) == "out_of_stock"
    assert availability_tier(0) == "out_of_stock"
    assert availability_tier(1) == "low_stock"
    assert availability_tier(public_service.LOW_STOCK_THRESHOLD - 1) == "low_stock"
    assert availability_tier(public_service.LOW_STOCK_THRESHOLD) == "in_stock"


def test_parse_keys_trims_and_drops_empty():
    assert parse_keys("a,b , ,c") == {"a", "b", "c"}
    assert parse_keys("") == set()
    assert parse_keys(None) == set()


def test_is_valid_key_and_closed_by_default(monkeypatch):
    class Configured:
        PUBLIC_STOCK_KEYS = "lisla-2026, backup-key"

    monkeypatch.setattr(public_service, "get_settings", lambda: Configured())
    assert public_service.is_valid_key("lisla-2026")
    assert public_service.is_valid_key("backup-key")
    assert not public_service.is_valid_key("wrong")
    assert not public_service.is_valid_key(None)

    class Empty:
        PUBLIC_STOCK_KEYS = ""

    monkeypatch.setattr(public_service, "get_settings", lambda: Empty())
    assert not public_service.is_valid_key("lisla-2026")  # 未配置任何 key = 端点整体关闭


@pytest.fixture
def inventory_db(db, monkeypatch):
    class S:
        PUBLIC_STOCK_KEYS = "k"
        BUSINESS_DB_NAME = "lsordertest"

    monkeypatch.setattr(public_service, "get_settings", lambda: S())
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.okki_products ("
        "product_id TEXT PRIMARY KEY, name TEXT, model TEXT, disable_flag INTEGER DEFAULT 0)"
    ))
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory ("
        "product_id TEXT, enable_count REAL, disable_flag INTEGER DEFAULT 0)"
    ))
    for pid, name, model, flag in [
        ("p1", "Body Wave Bundle 18inch", "BW-18", 0),
        ("p2", "Straight Bundle 20inch", "ST-20", 0),
        ("p3", "Disabled Product", "XX-1", 1),
    ]:
        db.execute(
            text("INSERT INTO lsordertest.okki_products VALUES (:a, :b, :c, :d)"),
            {"a": pid, "b": name, "c": model, "d": flag},
        )
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p1', 55, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p2', 3, 0)"))
    db.commit()
    return db


def test_query_public_inventory_basic(inventory_db):
    result = query_public_inventory(inventory_db, page=1, page_size=10)
    assert result["total"] == 2  # 停用产品不出
    by_id = {i["product_id"]: i for i in result["items"]}
    assert by_id["p1"]["available"] == 55
    assert by_id["p1"]["availability"] == "in_stock"
    assert by_id["p2"]["available"] == 3
    assert by_id["p2"]["availability"] == "low_stock"


def test_query_public_inventory_keyword_and_field_whitelist(inventory_db):
    result = query_public_inventory(inventory_db, keyword="Body")
    assert result["total"] == 1
    item = result["items"][0]
    # 字段白名单：只出产品标识与可用量，销量/安全库存/在产等经营数据不泄漏
    assert set(item.keys()) == {"product_id", "name", "model", "available", "availability"}


def test_query_public_inventory_pagination(inventory_db):
    page1 = query_public_inventory(inventory_db, page=1, page_size=1)
    page2 = query_public_inventory(inventory_db, page=2, page_size=1)
    assert page1["total"] == page2["total"] == 2
    assert page1["items"][0]["product_id"] != page2["items"][0]["product_id"]
