"""kiosk「返回上一步」修改登记信息：update_customer 服务层测试（2026-07-13）。

核心保障：更新既有客户而非重复建档（线索台一客一档），consent_at 只置不清。
2026-08-01 追加手机号 11 位归一/校验（CustomerRegister）。
"""

import pytest
from pydantic import ValidationError

from app.expo import service
from app.expo.models import ExpoCustomer
from app.expo.schemas import CustomerRegister


_RAW = dict(
    name="陈女士", phone="13800000000", wechat_id="",
    primary_need="volume", style_pref="知性优雅",
    consent=True, expo_code="2026-08-expo",
)


def _body(**kw):
    return CustomerRegister(**{**_RAW, **kw})


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


class TestPhoneValidation:
    """展位是客户自己在触屏上填，写法五花八门——能归一的归一，归一不了的才拦。"""

    @pytest.mark.parametrize("raw", [
        "13800138000",              # 纯数字
        " 13800138000 ",            # 首尾空格
        "138 0013 8000",            # 空格分段
        "138-0013-8000",            # 横杠分段
        "+8613800138000",           # 国际区号写法
        "8613800138000",            # 不带加号的区号
        "１３８００１３８０００",       # 中文输入法全角数字
        "手机13800138000",          # 顺手打上的前缀，是噪音不是错误
    ])
    def test_accepted_forms_all_normalise_to_plain_digits(self, raw):
        """归一后必须是同一个落库值——库里混着多种写法会让线索台关键词检索静默漏命中。"""
        assert CustomerRegister(**{**_RAW, "phone": raw}).phone == "13800138000"

    @pytest.mark.parametrize("raw", [
        "1380013800",               # 10 位，少一位
        "138001380000",             # 12 位，多一位
        "0755-12345678",            # 座机，归一后 12 位
        "",                         # 空
        "   ",                      # 纯空白
        "abcdefghijk",              # 11 个字符但一个数字都没有
    ])
    def test_rejected_forms_raise(self, raw):
        with pytest.raises(ValidationError, match="11 位数字"):
            CustomerRegister(**{**_RAW, "phone": raw})

    def test_normalised_value_is_what_lands_in_db(self, db):
        """校验发生在 schema，落库走的就是归一值——service 层无需再处理写法差异。"""
        customer = service.register_customer(db, _body(phone="138-0013-8000"))
        assert customer.phone == "13800138000"
        updated = service.update_customer(db, customer.id, _body(phone="+8613900139000"))
        assert updated.phone == "13900139000"
