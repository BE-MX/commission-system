from datetime import date

from app.domestic import order_service
from app.domestic.models import DomesticCustomer, DomesticOrder
from tests.test_domestic_order_channel_source import context
from tests.test_domestic_customer_order_controls import _api_client


def test_customer_name_filter_combines_scope_status_and_pagination(db):
    user, customer, _ = context(db, "name-filter")
    customer.shop_name = "青岛莱莎旗舰店"
    customer.customer_source = "referral"
    other = DomesticCustomer(shop_name="莱莎体验店", created_by=user.id)
    db.add(other)
    db.flush()
    for index, (customer_id, status, creator) in enumerate([
        (customer.id, 0, user.id), (customer.id, 0, user.id),
        (customer.id, 1, user.id), (other.id, 0, user.id),
        (customer.id, 0, user.id + 100), (None, 0, user.id),
    ]):
        db.add(DomesticOrder(domestic_no=f"NAME-{index}", order_no=f"PO-{index}",
            order_date=date(2026, 9, 11), customer_id=customer_id,
            order_kind="production" if customer_id is None else "business",
            order_category=None if customer_id is None else "normal",
            status=status, created_by=creator))
    db.flush()
    filters = dict(customer_name="  莱莎旗舰  ", status=0,
        include_all=False, creator_id=user.id, sort_field="domestic_no", sort_order="asc")
    rows, total = order_service.list_orders(db, page_size=1, **filters)
    assert total == 2 and [r["domestic_no"] for r in rows] == ["NAME-0"]
    rows, total = order_service.list_orders(db, page=2, page_size=1, **filters)
    assert total == 2 and [r["domestic_no"] for r in rows] == ["NAME-1"]
    assert order_service.list_orders(db, keyword="PO-1", customer_source="referral", **filters)[1] == 1
    assert order_service.list_orders(db, customer_id=other.id, **filters)[1] == 0
    assert order_service.list_orders(db, customer_name="不存在")[1] == 0
    assert order_service.list_orders(db, customer_name="   ")[1] == 6
    assert order_service.list_orders(db, customer_name="公司备货")[1] == 0


def test_customer_name_treats_wildcards_as_literal_text(db):
    user, customer, payload = context(db, "literal-name")
    customer.shop_name = "50%_旗舰店"
    order_service.create_order(db, payload, user.id)
    assert order_service.list_orders(db, customer_name="%_")[1] == 1
    customer.shop_name = "普通旗舰店"
    db.flush()
    assert order_service.list_orders(db, customer_name="%_")[1] == 0


def test_customer_name_api_passes_filter_and_validates_length(db):
    user, customer, payload = context(db, "name-api")
    customer.shop_name = "莱莎青岛店"
    order_service.create_order(db, payload, user.id)
    client = _api_client(db, user, "domestic:read")
    matching = client.get("/api/domestic/orders", params={"customer_name": "青岛", "status": 0})
    assert matching.status_code == 200 and matching.json()["data"]["total"] == 1
    missing = client.get("/api/domestic/orders", params={"customer_name": "济南"})
    assert missing.status_code == 200 and missing.json()["data"]["total"] == 0
    assert client.get("/api/domestic/orders", params={"customer_name": "名" * 201}).status_code == 422
