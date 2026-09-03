"""内贸客户公海规则、客户归属操作与订单数据范围。"""

from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.time import beijing_now, beijing_today
from app.domestic import customer_service
from app.domestic import order_service
from app.domestic.models import DomesticCustomer, DomesticOrder
from app.domestic.router import router
from app.domestic.schemas import CustomerCreate
from app.domestic.schemas import OrderUpdate


def _user(db, username):
    user = ArkUser(username=username, password_hash="x", real_name=username)
    db.add(user)
    db.flush()
    return user


def _customer(db, owner, name, *, province="山东省", city="青岛市", last_order_date=None):
    customer = customer_service.create_customer(
        db,
        CustomerCreate(
            shop_name=name,
            custom_code=f"C-{name}",
            province=province,
            city=city,
        ),
        owner.id,
    )
    customer.last_order_date = last_order_date
    db.flush()
    return customer


def _order(db, customer, creator, domestic_no, order_date):
    order = DomesticOrder(
        domestic_no=domestic_no,
        order_no=f"NO-{domestic_no}",
        order_date=order_date,
        customer_id=customer.id,
        created_by=creator.id,
        status=1,
    )
    db.add(order)
    db.flush()
    return order


def test_customer_filters_and_release_stale_private_customers(db):
    owner = _user(db, "public-sea-owner")
    other = _user(db, "public-sea-other")
    fresh = _customer(db, owner, "新鲜客户", province="山东省", city="青岛市")
    stale = _customer(db, owner, "过期客户", province="广东省", city="深圳市")
    imported_stale = _customer(
        db, other, "导入过期客户", province="广东省", city="广州市",
        last_order_date=beijing_today() - timedelta(days=100),
    )
    prospect = _customer(db, owner, "无下单基准客户", province="山西省", city="太原市")
    public = _customer(db, owner, "已公海客户", province="江苏省", city="南京市")
    public.owner_user_id = None
    _order(db, stale, owner, "DO2026-SEA-001", beijing_today() - timedelta(days=100))
    _order(db, fresh, owner, "DO2026-SEA-002", beijing_today())
    db.flush()
    stale.created_at = beijing_now() - timedelta(days=100)
    imported_stale.created_at = beijing_now() - timedelta(days=100)
    db.flush()

    rows, total = customer_service.list_customers(
        db, owner_scope="private", province="山东省", city="青岛市",
    )
    assert total == 1 and rows[0]["id"] == fresh.id

    rows, total = customer_service.list_customers(db, owner_scope="public")
    assert total == 1 and rows[0]["id"] == public.id

    released = customer_service.release_stale_private_customers(db)
    db.refresh(stale)
    db.refresh(imported_stale)
    db.refresh(fresh)
    assert released == 2
    assert stale.owner_user_id is None
    assert imported_stale.owner_user_id is None
    assert prospect.owner_user_id == owner.id
    assert fresh.owner_user_id == owner.id


def test_create_customer_defaults_owner_to_current_user(db):
    owner = _user(db, "creator-owner")
    customer = customer_service.create_customer(
        db, CustomerCreate(shop_name="默认归属客户"), owner.id,
    )
    assert customer.owner_user_id == owner.id


def _api_client(db, user, *permissions):
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user.id),
        "roles": [],
        "permissions": list(permissions),
    }
    return TestClient(app)


def test_customer_operations_require_current_owner(db):
    owner = _user(db, "customer-owner")
    intruder = _user(db, "customer-intruder")
    customer = _customer(db, owner, "归属控制客户")
    client = _api_client(db, intruder, "domestic:write", "domestic:admin")

    response = client.put(
        f"/api/domestic/customers/{customer.id}", json={"remark": "不应写入"},
    )
    assert response.status_code == 404
    assert customer.remark is None


def test_order_list_and_detail_are_scoped_until_read_all_granted(db):
    owner = _user(db, "order-owner")
    other = _user(db, "order-other")
    customer = _customer(db, owner, "订单范围客户")
    own = _order(db, customer, owner, "DO2026-SCOPE-001", date(2026, 9, 1))
    foreign = _order(db, customer, other, "DO2026-SCOPE-002", date(2026, 9, 2))

    client = _api_client(db, owner, "domestic:read")
    response = client.get("/api/domestic/orders")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [row["id"] for row in items] == [own.id]
    assert items[0]["created_by"] == owner.id

    hidden = client.get(f"/api/domestic/orders/{foreign.id}")
    assert hidden.status_code == 404

    all_client = _api_client(db, owner, "domestic:read", "domestic:read_all")
    response = all_client.get("/api/domestic/orders")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["data"]["items"]} == {own.id, foreign.id}


def test_order_writes_reject_non_creator(db):
    owner = _user(db, "order-write-owner")
    intruder = _user(db, "order-write-intruder")
    customer = _customer(db, owner, "订单写入控制客户")
    order = _order(db, customer, owner, "DO2026-WRITE-001", date(2026, 9, 2))

    with pytest.raises(ValueError, match="只有订单创建人"):
        order_service.update_order(db, order.id, OrderUpdate(), user_id=intruder.id)
