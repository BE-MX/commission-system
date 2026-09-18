"""Both scanner clients must receive the same item order as outbound printing."""
import pytest

from app.shipping_inspection import outbound_service
from tests.test_shipping_inspection import _mini_client, _pc_client, _qr, _user
from tests.test_shipping_print_order import EXPECTED, sample_items
from tests.test_shipping_station import people, scan


@pytest.fixture
def unordered_items(monkeypatch):
    items = sample_items()
    for index, item in enumerate(items):
        item.update(qty=index + 1, model=f"MODEL-{index}", color=f"COLOR-{index}")
    monkeypatch.setattr(outbound_service, "list_outbound_items", lambda *args: items)
    return items


def assert_print_order(payload, original):
    assert [item["item_id"] for item in payload["items"]] == EXPECTED
    assert {item["item_id"]: item for item in payload["items"]} == {
        item["item_id"]: item for item in original
    }
    assert [item["item_id"] for item in original] == [
        item["item_id"] for item in sample_items()
    ]


def test_mini_scan_and_refresh_match_print_order(db, unordered_items):
    with _mini_client(db, _user(db)) as client:
        for action in ("scan", "refresh"):
            response = client.post(f"/api/mini/shipping-inspection/{action}", json={"qr_raw": _qr()})
            assert response.status_code == 200
            assert_print_order(response.json(), unordered_items)


def test_phone_scan_and_refresh_match_print_order(db, people, unordered_items):
    login, operator, _ = people
    with _pc_client(db, login, []) as client:
        response = scan(client, operator)
        assert response.status_code == 200
        payload = response.json()["data"]
        assert_print_order(payload, unordered_items)
        response = client.get(f'/api/shipping-inspection/station/sessions/{payload["session_id"]}')
        assert response.status_code == 200
        assert_print_order(response.json()["data"], unordered_items)
