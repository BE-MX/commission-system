"""内贸客户跟进测试夹具：造用户、客户、发货批次、字典，并起一个只挂本模块路由的 TestClient。"""
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils import create_access_token
from app.core.database import get_db
from app.domestic.models import DomesticCustomer, DomesticCustomerCommission
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentLine
from app.domestic_followup.constants import DICT_SEEDS
from app.system.models import SysDict
from tests.task_helpers import make_user  # noqa: F401  — 统一从这里取

ALL_PERMS = ("domestic_followup:read", "domestic_followup:write")


def seed_dicts(db):
    # 跟进三类值域 + 快速建档要用的客户状态「潜在」（真实库由迁移 133 写入）
    seeds = {**DICT_SEEDS, "domestic_customer_lifecycle": ["潜在"]}
    for dict_type, labels in seeds.items():
        for index, label in enumerate(labels):
            db.add(SysDict(type=dict_type, code=label, label=label, sort=index * 10, is_active=True))
    db.flush()


def make_customer(db, owner, name, *, level="B级", creator=None, commission_users=()):
    customer = DomesticCustomer(
        shop_name=name, owner_user_id=owner.id if owner else None, customer_level=level,
        created_by=(creator or owner).id, balance=0, settle_mode="prepay", status=1,
    )
    db.add(customer)
    db.flush()
    for user in commission_users:
        db.add(DomesticCustomerCommission(customer_id=customer.id, user_id=user.id, rate=Decimal("0.0400")))
    db.flush()
    return customer


def make_shipment(db, customer, creator, ship_time: datetime, *, quantity=2, cancelled=False):
    shipment = DomesticShipment(
        shipment_no=f"FH{uuid4().hex[:10]}", customer_id=customer.id, ship_time=ship_time,
        total_amount=Decimal("100.00"), request_id=uuid4().hex, request_hash=uuid4().hex,
        created_by=creator.id, cancelled_at=ship_time if cancelled else None,
    )
    db.add(shipment)
    db.flush()
    db.add(DomesticShipmentLine(
        shipment_id=shipment.id, item_id=1, order_no="O1", domestic_no="D1", line_code="1",
        product_name="头套", quantity=quantity, unit_price=Decimal("50.00"), amount=Decimal("100.00"),
    ))
    db.flush()
    return shipment


@contextmanager
def followup_client(db, user, permissions=ALL_PERMS, roles=()):
    from app.domestic_followup.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic-followup")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id), "username": user.username, "real_name": user.real_name,
        "roles": list(roles), "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client
