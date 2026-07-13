"""kiosk「返回上一步」修改登记信息：update_customer 服务层测试（2026-07-13）。

核心保障：更新既有客户而非重复建档（线索台一客一档），consent_at 只置不清。
"""

from app.expo import service
from app.expo.models import ExpoCustomer
from app.expo.schemas import CustomerRegister


def _body(**kw):
    data = dict(
        name="陈女士", phone="13800000000", wechat_id="",
        primary_need="volume", style_pref="知性优雅",
        consent=True, expo_code="2026-08-expo",
    )
    data.update(kw)
    return CustomerRegister(**data)


def test_update_customer_edits_in_place_no_duplicate(db):
    customer = service.register_customer(db, _body())
    assert db.query(ExpoCustomer).count() == 1

    updated = service.update_customer(
        db, customer.id, _body(name="王女士", phone="13900000000", primary_need="gray_cover"),
    )
    assert updated.id == customer.id
    assert db.query(ExpoCustomer).count() == 1  # 不重复建档
    assert updated.name == "王女士"
    assert updated.phone == "13900000000"
    assert updated.primary_need == "gray_cover"


def test_update_customer_preserves_consent_timestamp(db):
    customer = service.register_customer(db, _body())
    original = customer.consent_at
    assert original is not None

    service.update_customer(db, customer.id, _body(name="改名不撤授权"))
    db.refresh(customer)
    assert customer.consent_at == original  # 只置不清：改信息不刷新同意时间戳


def test_update_customer_blank_wechat_stored_as_null(db):
    customer = service.register_customer(db, _body(wechat_id="wx_1"))
    service.update_customer(db, customer.id, _body(wechat_id="  "))
    db.refresh(customer)
    assert customer.wechat_id is None


def test_update_customer_missing_returns_none(db):
    assert service.update_customer(db, 99999, _body()) is None
