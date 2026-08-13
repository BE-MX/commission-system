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
