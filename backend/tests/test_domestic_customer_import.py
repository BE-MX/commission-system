"""内贸客户档案字段 + 《莱莎客户信息录入表》导入测试"""

import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app.auth.models import ArkUser
from app.domestic import customer_import_service, customer_service
from app.domestic.models import DomesticCustomer
from app.domestic.schemas import CustomerCreate, CustomerUpdate
from app.system.models import SysDict

D = Decimal


def _user(db, username, real_name):
    user = ArkUser(username=username, password_hash="x", real_name=real_name)
    db.add(user)
    db.flush()
    return user


def _workbook(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEADER = [
    "客户编号*", "客户正式名称*", "联系人*", "手机号*", "省份*", "城市*",
    "客户来源*", "归属销售*", "客户等级", "首次联系日期*", "首次下单日期",
    "最近下单日期", "累计订单数", "累计销售额", "客户状态", "门店类型*", "备注",
]


def _row(**overrides):
    values = [
        "ls-yh-001", "于姐假发", "于姐", "13488992190", "四川省", "成都市",
        "公司分配", "王语涵", "S级", "2022/09/24", "2022-12-16", "2026-08-30",
        124, 2700000, "活跃", "假发多店及连锁", "备注一",
    ]
    keys = [
        "code", "shop_name", "contact", "phone", "province", "city",
        "source", "owner", "level", "first_contact", "first_order",
        "last_order", "order_count", "sales_amount", "lifecycle", "store_type", "remark",
    ]
    row = dict(zip(keys, values))
    row.update(overrides)
    return [row[k] for k in keys]


def test_parse_skips_template_sheet_and_instruction_rows():
    data = _workbook({
        "模版": [HEADER, _row(code="ls-yh-001")],
        "王语涵": [
            HEADER,
            _row(),
            ["ls-语涵-001，编码规则说明", None],  # 说明行
            ["ls-yh-099"],  # 只有编号的预编号空行 → 静默跳过
            ["ls-yh-100", None, "有内容但没店名"],  # 有内容缺店名 → 记入 skipped
            _row(code="ls-yh-002", shop_name="诗诺雅", owner=None),
        ],
    })
    rows, skipped, warnings = customer_import_service.parse_workbook(data)
    assert [r["custom_code"] for r in rows] == ["ls-yh-001", "ls-yh-002"]
    assert len(skipped) == 2  # 说明行 + 有内容缺店名行
    assert warnings == []
    # 归属销售留空 → 回退到 sheet 名
    assert rows[1]["owner_name"] == "王语涵"


def test_parse_normalizes_region_and_scalar_types():
    data = _workbook({"周笑雨": [
        HEADER,
        _row(code="ls-xy-001", province="内蒙古省", city="呼和浩特", phone=13488992190.0),
        _row(code="ls-xy-002", province="广东省", city="深棕市", order_count=3.0, sales_amount=1234.5),
        _row(code="ls-xy-003", province="上海市", city=None),
        _row(code="ls-xy-004", province="新疆", city="维吾尔自治区"),
    ]})
    rows, skipped, _warnings = customer_import_service.parse_workbook(data)
    assert skipped == []
    assert rows[0]["province"] == "内蒙古自治区"
    assert rows[0]["city"] == "呼和浩特市"
    assert rows[0]["phone"] == "13488992190"
    assert rows[1]["city"] == "深圳市"
    assert rows[1]["total_order_count"] == 3
    assert rows[1]["total_sales_amount"] == D("1234.50")
    assert rows[2]["city"] == "上海市"  # 直辖市补市名
    assert rows[3]["province"] == "新疆维吾尔自治区"
    assert rows[3]["city"] is None  # 省份残片丢弃
    assert rows[0]["first_contact_date"] == date(2022, 9, 24)


def test_parse_bad_date_only_blanks_the_field():
    data = _workbook({"宋洋": [HEADER, _row(code="ls-sy-001", first_contact="不是一个日期")]})
    rows, skipped, warnings = customer_import_service.parse_workbook(data)
    # 单元格级脏数据不丢整条客户：字段置空 + 警告
    assert len(rows) == 1
    assert rows[0]["first_contact_date"] is None
    assert skipped == []
    assert len(warnings) == 1
    assert "日期" in warnings[0]["reason"]


def test_import_creates_then_rerun_updates(db):
    owner = _user(db, "wangyh", "王语涵")
    operator = _user(db, "admin-op", "牟亮亮")
    row = {
        "sheet": "王语涵", "row_no": 3, "custom_code": "ls-yh-001", "shop_name": "于姐假发",
        "contact": "于姐", "phone": "13488992190", "province": "四川省", "city": "成都市",
        "customer_source": "公司分配", "owner_name": "王语涵", "customer_level": "S级",
        "first_contact_date": date(2022, 9, 24), "first_order_date": date(2022, 12, 16),
        "last_order_date": date(2026, 8, 30), "total_order_count": 124,
        "total_sales_amount": D("2700000.00"), "lifecycle_status": "活跃",
        "store_type": "假发多店及连锁", "remark": None,
    }
    result = customer_import_service.import_customers(db, [row], operator.id)
    assert (result["created"], result["updated"], result["merged"]) == (1, 0, 0)
    customer = db.query(DomesticCustomer).filter_by(custom_code="ls-yh-001").one()
    assert customer.owner_user_id == owner.id
    assert customer.customer_level == "S级"
    assert customer.total_sales_amount == D("2700000.00")

    # 重跑：按编码命中 → 覆盖式更新，不新建
    row2 = {**row, "customer_level": "A级"}
    result2 = customer_import_service.import_customers(db, [row2], operator.id)
    assert (result2["created"], result2["updated"]) == (0, 1)
    db.refresh(customer)
    assert customer.customer_level == "A级"
    assert db.query(DomesticCustomer).count() == 1


def test_import_merges_same_shop_name_without_stealing_code_or_owner(db):
    yh = _user(db, "wangyh", "王语涵")
    ch = _user(db, "changh", "常华")
    operator = _user(db, "admin-op", "牟亮亮")
    base = {
        "contact": None, "phone": None, "province": None, "city": None,
        "customer_source": None, "customer_level": None, "lifecycle_status": None,
        "store_type": None, "first_contact_date": None, "first_order_date": None,
        "last_order_date": None, "total_order_count": None, "total_sales_amount": None,
        "remark": None,
    }
    first = {**base, "sheet": "王语涵", "row_no": 3, "custom_code": "ls-yh-174",
             "shop_name": "剪艺人生", "owner_name": "王语涵", "phone": "13000000000"}
    dup = {**base, "sheet": "常华", "row_no": 8, "custom_code": "ls-ch-030",
           "shop_name": "剪艺人生", "owner_name": "常华", "province": "山东省"}
    result = customer_import_service.import_customers(db, [first, dup], operator.id)
    assert (result["created"], result["merged"]) == (1, 1)
    assert len(result["collisions"]) == 1
    customer = db.query(DomesticCustomer).filter_by(shop_name="剪艺人生").one()
    assert customer.custom_code == "ls-yh-174"  # 先来先得
    assert customer.owner_user_id == yh.id  # 归属不被后来者覆盖
    assert customer.province == "山东省"  # 空档被补
    assert customer.phone == "13000000000"  # 非空档不被覆盖


def test_import_rejects_unknown_owner(db):
    operator = _user(db, "admin-op", "牟亮亮")
    row = {
        "sheet": "王语涵", "row_no": 3, "custom_code": "ls-yh-001", "shop_name": "于姐假发",
        "contact": None, "phone": None, "province": None, "city": None,
        "customer_source": None, "owner_name": "不存在的人", "customer_level": None,
        "first_contact_date": None, "first_order_date": None, "last_order_date": None,
        "total_order_count": None, "total_sales_amount": None,
        "lifecycle_status": None, "store_type": None, "remark": None,
    }
    result = customer_import_service.import_customers(db, [row], operator.id)
    assert result["created"] == 0
    assert len(result["errors"]) == 1
    assert "不存在的人" in result["errors"][0]["reason"]


def test_customer_create_update_roundtrip_profile_fields(db):
    owner = _user(db, "zhouxy", "周笑雨")
    operator = _user(db, "admin-op", "牟亮亮")
    payload = CustomerCreate(
        shop_name="南宁假发", custom_code="ls-xy-001",
        province="广西壮族自治区", city="南宁市", contact="卢微", phone="13868714150",
        customer_source="自职业开发", store_type="假发单店", customer_level="C级",
        lifecycle_status="流失", owner_user_id=owner.id,
        first_contact_date=date(2022, 7, 8), last_order_date=date(2024, 12, 31),
        total_order_count=1, total_sales_amount=D("1350.00"), remark="备注",
    )
    customer = customer_service.create_customer(db, payload, operator.id)
    assert customer.owner_user_id == owner.id
    assert customer.customer_source == "自职业开发"
    assert customer.first_contact_date == date(2022, 7, 8)

    update = CustomerUpdate(customer_level="B级", lifecycle_status="活跃", owner_user_id=None)
    customer_service.update_customer(db, customer.id, update)
    db.refresh(customer)
    assert customer.customer_level == "B级"
    assert customer.lifecycle_status == "活跃"
    assert customer.owner_user_id is None  # 显式 null 清空归属

    with pytest.raises(ValueError, match="归属销售用户不存在"):
        customer_service.update_customer(db, customer.id, CustomerUpdate(owner_user_id=999999))


def test_get_customer_options(db):
    _user(db, "wangyh", "王语涵")
    db.add(SysDict(type="domestic_customer_level", code="S级", label="S级", sort=0))
    db.add(SysDict(type="domestic_customer_level", code="A级", label="A级", sort=10))
    db.flush()
    options = customer_service.get_customer_options(db)
    assert options["customer_level"] == [
        {"value": "S级", "label": "S级"}, {"value": "A级", "label": "A级"},
    ]
    assert options["owners"] == [{"value": o["value"], "label": o["label"]} for o in options["owners"]]
    assert any(o["label"] == "王语涵" for o in options["owners"])
    assert options["customer_source"] == []
