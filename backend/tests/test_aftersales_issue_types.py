"""售后问题类型的接口展示与创建契约。"""

from app.aftersales.router import options
from app.aftersales.schemas import CaseCreate


def _case_payload() -> dict:
    return {
        "customer_id": "CUST001",
        "customer_name_snapshot": "客户A",
        "customer_grade": "A",
        "order_id": "ORD001",
        "order_no_snapshot": "NO001",
        "purchase_date": "2026-07-01",
        "feedback_date": "2026-07-10",
        "product_id": 1,
        "product_name_snapshot": "Invisible Weft",
        "color_value": "#2B",
        "length_value": "20 inch",
        "weight_value": "100",
        "weight_unit": "g",
        "quantity": "2",
        "primary_issue_type": "错发退回",
        "problem_description": "客户收到的产品与订单型号不一致，需要安排退回处理。",
        "occurred_stage": "刚收到",
        "care_storage_note": "客户收到后未拆封使用，已保留原包装并等待退回指引。",
        "affects_end_customer": "no",
        "affected_goods_value": "1150",
    }


def test_wrong_item_return_is_exposed_as_issue_type():
    issue_codes = [item["code"] for item in options()["data"]["issue_types"]]

    assert "错发退回" in issue_codes
    assert len(issue_codes) == 12


def test_case_create_accepts_wrong_item_return_issue_type():
    case = CaseCreate.model_validate(_case_payload())

    assert case.primary_issue_type == "错发退回"
