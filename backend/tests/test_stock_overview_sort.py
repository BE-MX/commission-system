"""销量备货一览的服务端排序字段契约。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.auth.dependencies import get_current_user
from app.stock import router as stock_router


def _client(monkeypatch):
    received_sorts = []
    app = FastAPI()
    app.include_router(stock_router.router, prefix="/api/stock")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1",
        "permissions": ["stock:read"],
    }
    def fake_query_stock_overview(**kwargs):
        received_sorts.append(kwargs["sort_by"])
        return {"total": 0, "summary": {}, "items": []}

    monkeypatch.setattr(stock_router.service, "query_stock_overview", fake_query_stock_overview)
    return TestClient(app), received_sorts


def test_overview_accepts_every_sortable_table_column(monkeypatch):
    client, received_sorts = _client(monkeypatch)
    sortable_fields = (
        "type", "size", "weight", "status", "safety_stock_source", "suggested_qty", "stock_status",
        "model",
        "color",
        "sales_30d",
        "sales_90d",
        "avg_daily_sales_30d",
        "enable_count",
        "real_count",
        "effective_enable_count",
        "production_in_transit",
        "safety_stock",
    )

    for field in sortable_fields:
        response = client.get("/api/stock/overview", params={"sort": field})
        assert response.status_code == 200, (field, response.json())

    assert received_sorts == list(sortable_fields)


def test_overview_rejects_unknown_sort_field(monkeypatch):
    client, _ = _client(monkeypatch)
    response = client.get(
        "/api/stock/overview", params={"sort": "unsupported"}
    )
    assert response.status_code == 422


def test_name_sort_fields_match_display_fallback_and_missing_segments(db):
    from sqlalchemy import text
    from app.stock import overview_service, safety_service

    connection = db.connection().connection.driver_connection
    def substring_index(value, separator, count):
        if value is None:
            return None
        parts = str(value).split(separator)
        return separator.join(parts[:count] if count > 0 else parts[count:])
    connection.create_function("SUBSTRING_INDEX", 3, substring_index)
    connection.create_function("LOCATE", 2, lambda needle, value: (value or "").find(needle) + 1)
    samples = (
        (1, None, "Alpha/14/#1/50g"),
        (2, "", "Beta/16/#2/100g"),
        (3, "Single", "Ignored/20/#3/80g"),
        (4, "Gamma//", None),
        (5, None, None),
    )
    source = " UNION ALL ".join(f"SELECT :id{i} AS product_id, :name{i} AS name, :cn{i} AS cn_name" for i in range(len(samples)))
    params = {key: value for index, sample in enumerate(samples) for key, value in zip((f"id{index}", f"name{index}", f"cn{index}"), sample)}
    expected = {pid: overview_service._parse_name(name or cn_name or "") for pid, name, cn_name in samples}
    for service in (overview_service, safety_service):
        derived = f"SELECT p.*, {service._DISPLAY_NAME_EXPR} AS _display_name FROM ({source}) p"
        for field in ("type", "size", "weight"):
            expression = service._SORT_MAP[field]
            rows = db.execute(text(f"SELECT p.product_id, {expression} AS value FROM ({derived}) p"), params).mappings().all()
            assert {row["product_id"]: row["value"] or "" for row in rows} == {pid: values[field] for pid, values in expected.items()}
            for direction in ("ASC", "DESC"):
                query = f"SELECT p.product_id, {expression} AS value FROM ({derived}) p ORDER BY ({expression} IS NULL) ASC, {expression} {direction}, p.product_id ASC"
                complete = db.execute(text(query), params).mappings().all()
                pages = [db.execute(text(query + " LIMIT 2 OFFSET :offset"), {**params, "offset": offset}).mappings().all() for offset in range(0, len(samples), 2)]
                assert [row["product_id"] for page in pages for row in page] == [row["product_id"] for row in complete]
                missing = [index for index, row in enumerate(complete) if row["value"] is None]
                assert missing == list(range(len(complete) - len(missing), len(complete)))
