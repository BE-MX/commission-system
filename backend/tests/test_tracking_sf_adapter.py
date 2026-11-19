"""顺丰路由查询适配器：响应解析与状态映射（纯函数，无 DB、无网络）"""

import json
from datetime import datetime

import pytest

from app.tracking.carriers.sf import SFAdapter, map_sf_route_status
from app.tracking.status import normalize_status


def _body(routes, mail_no="SF1011603494291", **resp_extra):
    data = {
        "success": True,
        "errorCode": "S0000",
        "errorMsg": None,
        "msgData": {"routeResps": [{"mailNo": mail_no, "routes": routes, **resp_extra}]},
    }
    return {"apiResultCode": "A1000", "apiErrorMsg": "", "apiResultData": json.dumps(data, ensure_ascii=False)}


# 丰桥文档的成功响应示例
DOC_ROUTES = [
    {"acceptAddress": "深圳市", "acceptTime": "2024-09-02 23:51:27", "remark": "顺丰合作点【名居广场驿站店】已代收",
     "secondaryStatusCode": "701", "firstStatusName": "待揽收", "firstStatusCode": "7",
     "secondaryStatusName": "待揽收", "opCode": "655"},
    {"acceptAddress": "深圳市", "acceptTime": "2024-09-03 07:59:07", "remark": "顺丰速运 已收取快件",
     "secondaryStatusCode": "101", "firstStatusName": "已揽收", "firstStatusCode": "1",
     "secondaryStatusName": "已揽收", "opCode": "54"},
]


@pytest.fixture
def adapter():
    return SFAdapter(partner_id="TEST", checkword="x", sandbox=True)


def test_parse_doc_sample_uses_latest_event(adapter):
    r = adapter.parse_response("SF1011603494291", _body(DOC_ROUTES))
    assert r.success
    assert r.current_status == "picked_up"
    assert r.current_status_text == "顺丰速运 已收取快件"
    assert r.current_location == "深圳市"
    # acceptTime 是北京钟面，按 naive 保留，不做时区平移
    assert r.last_event_time == datetime(2024, 9, 3, 7, 59, 7)
    assert [e.status_code for e in r.events] == ["54", "655"]
    assert normalize_status("SF", r.current_status) == "picked_up"


def test_non_padded_accept_time(adapter):
    routes = [dict(DOC_ROUTES[1], acceptTime="2012-7-30 09:30:00")]
    r = adapter.parse_response("SF1011603494291", _body(routes))
    assert r.last_event_time == datetime(2012, 7, 30, 9, 30, 0)


def test_empty_routes_is_failure_with_reason(adapter):
    r = adapter.parse_response("SF1", _body([], mail_no="SF1", reasonRemark=["无权限"]))
    assert not r.success
    assert "无权限" in r.error


@pytest.mark.parametrize("body,needle", [
    ({"apiResultCode": "A1004", "apiErrorMsg": "无对应服务权限"}, "A1004"),
    ({"apiResultCode": "A1000", "apiResultData": json.dumps({"success": False, "errorCode": "8013", "errorMsg": "未传入查询单号"})}, "8013"),
])
def test_platform_and_business_errors(adapter, body, needle):
    r = adapter.parse_response("SF1", body)
    assert not r.success
    assert needle in r.error


@pytest.mark.parametrize("route,expected", [
    ({"opCode": "80", "firstStatusCode": "4", "secondaryStatusCode": "401"}, "delivered"),
    ({"opCode": "44", "firstStatusCode": "3", "secondaryStatusCode": "301"}, "out_for_delivery"),
    ({"opCode": "125", "firstStatusCode": "11", "secondaryStatusCode": "1101"}, "out_for_delivery"),
    ({"opCode": "30", "firstStatusCode": "2", "secondaryStatusCode": "201"}, "in_transit"),
    ({"opCode": "15", "firstStatusCode": "2", "secondaryStatusCode": "204"}, "customs_hold"),
    ({"opCode": "606", "firstStatusCode": "2", "secondaryStatusCode": "205"}, "in_transit"),
    ({"opCode": "70", "firstStatusCode": "13", "secondaryStatusCode": "1301"}, "exception"),
    ({"opCode": "33", "firstStatusCode": "-", "firstStatusName": "已退回", "secondaryStatusName": "已退回"}, "returned"),
    ({"opCode": "627", "firstStatusCode": "-", "firstStatusName": "已转寄"}, "in_transit"),
    ({"opCode": "8000", "firstStatusCode": "4", "remark": "快件遗失"}, "exception"),
    ({"opCode": "33", "firstStatusCode": "6", "secondaryStatusCode": "601"}, "exception"),
    ({"opCode": "655", "firstStatusCode": "7", "secondaryStatusCode": "701"}, "pending"),
])
def test_route_status_mapping(route, expected):
    assert map_sf_route_status(route) == expected
