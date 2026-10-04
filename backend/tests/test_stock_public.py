"""对外库存查询（stock/public_service）单元测试：名称解析、有货口径、过滤与字段白名单。"""

import pytest
from sqlalchemy import text

from app.stock import public_service
from app.stock.public_service import query_public_inventory


@pytest.fixture
def inventory_db(db, monkeypatch):
    class S:
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
        ("p1", "Body Wave/18inch/#1B/100g", "BW-18", 0),
        ("p2", "Straight/20inch/#1B/99J/120g", "ST-20", 0),
        ("p3", "Disabled/10inch/#2/80g", "XX-1", 1),
        ("p4", "Plain Bundle No Slash", "PB-1", 0),
        ("p5", "Body Wave/22inch/#2/100g", "BW-22", 0),
        ("p6", "Micro Beads/#1", "MB-1", 0),
    ]:
        db.execute(
            text("INSERT INTO lsordertest.okki_products VALUES (:a, :b, :c, :d)"),
            {"a": pid, "b": name, "c": model, "d": flag},
        )
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p1', 55, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p2', 0, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p4', -5, 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('p6', 12, 0)"))
    # p5 无库存记录 → LEFT JOIN NULL → 无货
    db.commit()
    return db


def test_parse_four_segments_and_field_whitelist(inventory_db):
    result = query_public_inventory(inventory_db, keyword="Body Wave/18")
    assert result["total"] == 1
    item = result["items"][0]
    # 字段白名单：只出四要素 + 有货标识，具体库存数量与经营数据不泄漏
    assert set(item.keys()) == {"product_id", "type", "size", "color", "weight", "in_stock"}
    assert item["type"] == "Body Wave"
    assert item["size"] == "18inch"
    assert item["color"] == "#1B"
    assert item["weight"] == "100g"
    assert item["in_stock"] is True


def test_parse_five_segments_merges_color(inventory_db):
    # ≥5 段且倒数第 3 段以 # 开头 → 颜色 = 倒数第 3/2 段拼接（与内部一览同口径）
    result = query_public_inventory(inventory_db, keyword="Straight")
    item = result["items"][0]
    assert item["color"] == "#1B/99J"
    assert item["weight"] == "120g"


def test_unslashed_name_falls_back_to_type(inventory_db):
    # 不规范名整体落入类型列，其余列留空（不重复显示整段名称）
    result = query_public_inventory(inventory_db, keyword="Plain Bundle")
    item = result["items"][0]
    assert item["type"] == "Plain Bundle No Slash"
    assert item["size"] == item["color"] == item["weight"] == ""


def test_two_segments_hash_means_color(inventory_db):
    # 两段名 Micro Beads/#1：第 2 段以 # 开头 → 颜色，尺寸/克重留空（不重复段）
    result = query_public_inventory(inventory_db, keyword="Micro Beads")
    item = result["items"][0]
    assert item["type"] == "Micro Beads"
    assert item["size"] == ""
    assert item["color"] == "#1"
    assert item["weight"] == ""


def test_in_stock_flag_semantics(inventory_db):
    result = query_public_inventory(inventory_db, page=1, page_size=10)
    assert result["total"] == 5  # 停用产品不出
    by_id = {i["product_id"]: i for i in result["items"]}
    assert by_id["p1"]["in_stock"] is True   # 55 > 0
    assert by_id["p2"]["in_stock"] is False  # 0
    assert by_id["p4"]["in_stock"] is False  # 负库存（超卖/数据异常）视为无货
    assert by_id["p5"]["in_stock"] is False  # 无库存记录
    assert by_id["p6"]["in_stock"] is True   # 12 > 0


def test_in_stock_only_filter(inventory_db):
    result = query_public_inventory(inventory_db, in_stock_only=True)
    assert result["total"] == 2
    assert {i["product_id"] for i in result["items"]} == {"p1", "p6"}


def test_keyword_matches_model(inventory_db):
    result = query_public_inventory(inventory_db, keyword="ST-20")
    assert result["total"] == 1
    assert result["items"][0]["product_id"] == "p2"


def test_query_public_inventory_pagination(inventory_db):
    page1 = query_public_inventory(inventory_db, page=1, page_size=1)
    page2 = query_public_inventory(inventory_db, page=2, page_size=1)
    assert page1["total"] == page2["total"] == 5
    assert page1["items"][0]["product_id"] != page2["items"][0]["product_id"]


def test_public_availability_sort_spans_pages_without_quantity_ordering(inventory_db):
    for direction in ("asc", "desc"):
        complete = query_public_inventory(inventory_db, page_size=100, sort_field="in_stock", sort_order=direction)["items"]
        pages = [query_public_inventory(inventory_db, page=number, page_size=2, sort_field="in_stock", sort_order=direction)["items"] for number in (1, 2, 3)]
        assert [row["product_id"] for page in pages for row in page] == [row["product_id"] for row in complete]
        assert [row["in_stock"] for row in complete] == sorted([row["in_stock"] for row in complete], reverse=direction == "desc")
        assert [row["product_id"] for row in complete if row["in_stock"]] == ["p1", "p6"]
        assert all(set(row) == {"product_id", "type", "size", "color", "weight", "in_stock"} for row in complete)


def test_public_private_or_untrusted_sort_restores_default(inventory_db):
    baseline = query_public_inventory(inventory_db, page_size=100)
    for field in ("enable_count", "available", "p.name; DROP TABLE okki_products"):
        assert query_public_inventory(inventory_db, page_size=100, sort_field=field, sort_order="desc") == baseline
    assert query_public_inventory(inventory_db, page_size=100, sort_field="in_stock", sort_order="invalid") == baseline


def test_public_parsed_name_sort_uses_displayed_short_name_fields(inventory_db):
    def substring_index(value, separator, count):
        parts = value.split(separator)
        return separator.join(parts[:count] if count > 0 else parts[count:])
    inventory_db.connection().connection.driver_connection.create_function("SUBSTRING_INDEX", 3, substring_index)
    for field in ("type", "size", "color", "weight"):
        for direction in ("asc", "desc"):
            complete = query_public_inventory(inventory_db, page_size=100, sort_field=field, sort_order=direction)["items"]
            assert [row[field] for row in complete] == sorted([row[field] for row in complete], reverse=direction == "desc")
            paged = [query_public_inventory(inventory_db, page=number, page_size=1, sort_field=field, sort_order=direction)["items"][0] for number in range(1, 6)]
            assert paged == complete
