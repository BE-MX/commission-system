import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.invoice.models import PriceColorType, StdPrice


def _seed_price(db):
    db.add(PriceColorType(color_code="18p613", color_type="piano"))
    db.add(
        StdPrice(
            product_kind="hair",
            series_grade="Super Double Drawn Genius",
            length="20",
            weight_unit="20g",
            color_type="piano",
            price=Decimal("52.5000"),
            currency="USD",
        )
    )
    db.flush()


def test_standard_price_requires_dedicated_read_permission(db):
    from app.mcp.price_tools import _get_standard_price

    _seed_price(db)
    payload = json.loads(
        _get_standard_price(
            db,
            {"sub": "2", "permissions": ["invoice:read"], "roles": []},
            product_display="Super Double Drawn Genius Weft",
            length="20 inch",
            unit="20g",
            color="#18P613",
        )
    )

    assert payload == {
        "ok": False,
        "error": "权限不足：需要 invoice_price:read 权限，请联系管理员分配",
    }


def test_standard_price_returns_one_reference_cell_without_customer_data(db):
    from app.mcp.price_tools import _get_standard_price

    _seed_price(db)
    payload = json.loads(
        _get_standard_price(
            db,
            {"sub": "2", "permissions": ["invoice_price:read"], "roles": []},
            product_display="Super Double Drawn Genius Weft",
            length="20 inch",
            unit="20g",
            color="#18P613",
        )
    )

    assert payload["ok"] is True
    assert payload["price"] == {
        "product_display": "Super Double Drawn Genius Weft",
        "length": "20",
        "unit": "20g",
        "color": "#18P613",
        "color_type": "piano",
        "color_type_source": "exact",
        "standard_reference_price": "52.5000",
        "currency": "USD",
        "quote_status": "reference_only",
        "requires_quote_confirmation": True,
    }
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "customer_price" not in dumped
    assert "customer_id" not in dumped
    assert "rule" not in dumped


def test_standard_price_super_admin_can_read(db):
    from app.mcp.price_tools import _get_standard_price

    _seed_price(db)
    payload = json.loads(
        _get_standard_price(
            db,
            {"sub": "1", "permissions": [], "roles": ["super_admin"]},
            product_display="Super Double Drawn Genius",
            length="20",
            unit="20G",
            color="18P613",
        )
    )

    assert payload["ok"] is True
    assert payload["price"]["standard_reference_price"] == "52.5000"


def test_standard_price_missing_cell_is_actionable(db):
    from app.mcp.price_tools import _get_standard_price

    payload = json.loads(
        _get_standard_price(
            db,
            {"sub": "2", "permissions": ["invoice_price:read"], "roles": []},
            product_display="Unknown Series",
            length="20",
            unit="20g",
            color="#1B",
        )
    )

    assert payload["ok"] is False
    assert "未匹配到标准价格" in payload["error"]
    assert "核对产品系列、长度、克重和色号" in payload["error"]


def test_standard_price_hides_internal_database_errors(monkeypatch):
    from app.mcp.price_tools import _get_standard_price

    def fail(*args, **kwargs):
        raise RuntimeError("mysql host and table details")

    monkeypatch.setattr("app.mcp.price_tools.price_service.resolve_price", fail)
    payload = json.loads(
        _get_standard_price(
            object(),
            {"sub": "2", "permissions": ["invoice_price:read"], "roles": []},
            product_display="Genius",
            length="20",
            unit="20g",
            color="#1B",
        )
    )

    assert payload == {"ok": False, "error": "标准价格查询失败，请稍后重试"}
    assert "mysql" not in json.dumps(payload)


def test_standard_price_input_forbids_customer_id():
    from app.mcp.price_tools import StandardPriceInput

    with pytest.raises(ValidationError):
        StandardPriceInput.model_validate(
            {
                "product_display": "Super Double Drawn Genius",
                "length": "20",
                "unit": "20g",
                "color": "#1B",
                "customer_id": "secret-customer",
            }
        )


def test_find_product_reuses_structured_catalog_and_permission(monkeypatch):
    from app.mcp.price_tools import _find_product

    captured = {}

    def fake_match(db, *, model, color, size, unit):
        captured.update(model=model, color=color, size=size, unit=unit)
        return {
            "is_unique": True,
            "item": {"product_id": 11, "sku_id": 22, "product_name": "Genius/20/#1B/20g"},
            "matches": [{"product_id": 11, "sku_id": 22, "product_name": "Genius/20/#1B/20g"}],
        }

    monkeypatch.setattr("app.mcp.price_tools.product_service.match_product", fake_match)
    denied = json.loads(
        _find_product(
            object(),
            {"sub": "2", "permissions": ["invoice:read"], "roles": []},
            model="Genius",
            color="#1B",
            size="20",
            unit="20g",
        )
    )
    assert denied["ok"] is False
    assert captured == {}

    allowed = json.loads(
        _find_product(
            object(),
            {"sub": "2", "permissions": ["invoice_price:read"], "roles": []},
            model="Genius",
            color="#1B",
            size="20",
            unit="20g",
        )
    )
    assert allowed["ok"] is True
    assert allowed["is_unique"] is True
    assert allowed["item"]["sku_id"] == 22
    assert captured == {"model": "Genius", "color": "#1B", "size": "20", "unit": "20g"}


@pytest.mark.asyncio
async def test_mcp_server_registers_commerce_lookup_tools():
    from app.mcp.server import mcp

    names = {tool.name for tool in await mcp.list_tools()}
    assert {"get_standard_price", "find_product"} <= names
