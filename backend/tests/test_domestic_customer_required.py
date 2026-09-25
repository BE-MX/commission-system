"""客户管理手工新增必须提交红框内的完整档案字段。"""

import pytest
from pydantic import ValidationError

from app.domestic.schemas import CustomerCreate, CustomerManagementCreate, CustomerUpdate


VALID_CUSTOMER = {
    "custom_code": "KH-001",
    "shop_name": "马姐假发",
    "contact": "马姐",
    "phone": "13800138000",
    "province": "山东省",
    "city": "青岛市",
    "owner_user_id": 7,
    "customer_source": "老客转介绍",
    "customer_level": "A级",
    "lifecycle_status": "活跃",
    "store_type": "假发门店",
    "first_contact_date": "2026-01-01",
    "first_order_date": "2026-02-01",
    "last_order_date": "2026-03-01",
}


@pytest.mark.parametrize("field", VALID_CUSTOMER)
def test_customer_management_create_requires_each_profile_field(field):
    data = {**VALID_CUSTOMER, field: None}
    with pytest.raises(ValidationError):
        CustomerManagementCreate.model_validate(data)


@pytest.mark.parametrize("field", ["custom_code", "shop_name", "contact", "phone", "province", "city"])
def test_customer_management_create_rejects_whitespace(field):
    with pytest.raises(ValidationError):
        CustomerManagementCreate.model_validate({**VALID_CUSTOMER, field: "   "})


def test_customer_management_create_accepts_complete_profile():
    customer = CustomerManagementCreate.model_validate(VALID_CUSTOMER)
    assert customer.custom_code == "KH-001"
    assert customer.first_order_date.isoformat() == "2026-02-01"
    assert set(VALID_CUSTOMER) <= set(CustomerManagementCreate.model_json_schema()["required"])


def test_other_customer_flows_keep_existing_partial_update_contract():
    assert CustomerCreate(shop_name="下单时就地建档").custom_code is None
    assert CustomerUpdate(contact="新联系人").contact == "新联系人"
