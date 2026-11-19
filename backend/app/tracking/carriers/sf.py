"""顺丰速运 路由查询适配器（丰桥 EXP_RECE_SEARCH_ROUTES + OAuth2）

文档：
- 路由查询 https://qiao.sf-express.com/Api/ApiDetails?level3=397
- 鉴权     https://open.sf-express.com/developSupport/976720?authId=0
- 操作码表 业务文档 → 路由信息操作码

要点：
- 按运单号查询（trackingType=1）只返回「付款月结卡号与 partnerID 绑定」的运单；
  非本月结账号的单需要 checkPhoneNo（收寄任一方手机后四位），当前未接入。
- routes 为空代表 无权限 / 未产生路由 / 超 3 个月，按失败返回让轮询记录原因。
- acceptTime 是北京时间且不带偏移（"YYYY-MM-DD HH:MM:SS"），按北京钟面解析。
- 丰桥限流：单接口 30 次/秒、3000 次/天。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

import httpx

from app.tracking.carriers.base import CarrierAdapter, TrackingEvent, TrackingResult

logger = logging.getLogger("tracking.sf")

SERVICE_CODE = "EXP_RECE_SEARCH_ROUTES"

# 一级状态码（firstStatusCode）→ 统一状态
SF_FIRST_STATUS_MAP = {
    "1": "picked_up",          # 已揽收
    "2": "in_transit",         # 运送中
    "3": "out_for_delivery",   # 派送中
    "4": "delivered",          # 已签收
    "5": "exception",          # 已作废
    "6": "exception",          # 已取消
    "7": "pending",            # 待揽收
    "10": "pending",           # 仓库处理中
    "11": "out_for_delivery",  # 待取件（已到丰巢/驿站/网点，等收件人取）
    "13": "in_transit",        # 待派送（滞留；问题件由 opCode 单独判异常）
}

# 二级状态码优先级高于一级
SF_SECONDARY_STATUS_MAP = {
    "204": "customs_hold",     # 清关中
    "205": "in_transit",       # 已清关
}

# 需要人工关注的操作码
SF_EXCEPTION_OPCODES = {"70", "934"}  # 问题件、外配异常


def map_sf_route_status(route: dict) -> str:
    """单条路由节点 → 统一状态。码表中部分节点状态码为「-」，只能按名称兜底。"""
    op_code = str(route.get("opCode") or "").strip()
    remark = str(route.get("remark") or "")
    names = f"{route.get('firstStatusName') or ''}{route.get('secondaryStatusName') or ''}"

    if "退回" in names:
        return "returned"
    if op_code in SF_EXCEPTION_OPCODES or "遗失" in remark:
        return "exception"

    secondary = str(route.get("secondaryStatusCode") or "").strip()
    if secondary in SF_SECONDARY_STATUS_MAP:
        return SF_SECONDARY_STATUS_MAP[secondary]

    first = str(route.get("firstStatusCode") or "").strip()
    if first in SF_FIRST_STATUS_MAP:
        return SF_FIRST_STATUS_MAP[first]

    # 已转寄 / 未完善节点：仍在流转
    return "in_transit"


def _parse_accept_time(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except (AttributeError, ValueError):
        return None


class SFAdapter(CarrierAdapter):

    PROD_BASE = "https://bspgw.sf-express.com"
    SAND_BASE = "https://sfapi-sbox.sf-express.com"

    def __init__(self, partner_id: str, checkword: str, sandbox: bool = True, timeout: float = 30.0):
        self.partner_id = partner_id
        self.checkword = checkword
        self.base_url = self.SAND_BASE if sandbox else self.PROD_BASE
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expires_at - 60:
            return self._token
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.base_url + "/oauth2/accessToken",
                data={"partnerID": self.partner_id, "secret": self.checkword, "grantType": "password"},
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            )
            resp.raise_for_status()
            body = resp.json()
        if body.get("apiResultCode") != "A1000" or not body.get("accessToken"):
            raise RuntimeError(f"SF OAuth2 {body.get('apiResultCode')}: {body.get('apiErrorMsg')}")
        self._token = body["accessToken"]
        self._token_expires_at = time.time() + int(body.get("expiresIn") or 7200)
        return self._token

    async def _call(self, token: str, msg_data: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.base_url + "/std/service",
                data={
                    "partnerID": self.partner_id,
                    "requestID": str(uuid.uuid4()),
                    "serviceCode": SERVICE_CODE,
                    # 协议时间戳：epoch 毫秒，与时区无关
                    "timestamp": str(int(time.time() * 1000)),
                    "accessToken": token,
                    "msgData": json.dumps(msg_data, ensure_ascii=False),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            )
            resp.raise_for_status()
            return resp.json()

    async def track(self, waybill_no: str) -> TrackingResult:
        msg_data = {"language": "zh-CN", "trackingType": "1", "trackingNumber": [waybill_no], "methodType": "1"}
        try:
            token = await self._get_token()
            body = await self._call(token, msg_data)
            if body.get("apiResultCode") == "A1011":  # token 过期，重取一次
                token = await self._get_token(force=True)
                body = await self._call(token, msg_data)
        except Exception as e:
            logger.warning("SF route query failed %s: %s", waybill_no, e)
            print(f"[tracking.sf] request failed {waybill_no} err={e}", flush=True)
            return TrackingResult(False, waybill_no, "exception", "API请求失败", "", None, [], error=str(e))

        return self.parse_response(waybill_no, body)

    def parse_response(self, waybill_no: str, body: dict) -> TrackingResult:
        def fail(text: str, error: str) -> TrackingResult:
            return TrackingResult(False, waybill_no, "exception", text, "", None, [], error=error)

        api_code = body.get("apiResultCode")
        if api_code != "A1000":
            return fail("API平台错误", f"{api_code}: {body.get('apiErrorMsg')}")

        try:
            data = body.get("apiResultData")
            data = json.loads(data) if isinstance(data, str) else (data or {})
            if not data.get("success"):
                return fail("业务错误", f"{data.get('errorCode')}: {data.get('errorMsg')}")

            resps = (data.get("msgData") or {}).get("routeResps") or []
            resp = next((r for r in resps if r.get("mailNo") == waybill_no), resps[0] if resps else {})
            routes = resp.get("routes") or []
            if not routes:
                reason = "/".join(str(x) for x in (resp.get("reasonRemark") or resp.get("reasonCode") or []) if x)
                return fail(
                    "无路由",
                    f"SF no routes (无权限/未揽收/超3个月){': ' + reason if reason else ''}",
                )

            events: list[TrackingEvent] = []
            for route in routes:
                dt = _parse_accept_time(str(route.get("acceptTime") or ""))
                if dt is None:
                    # 外部时间不可解析时不伪造事件时间
                    continue
                events.append(TrackingEvent(
                    event_time=dt,
                    description=route.get("remark") or "",
                    location=route.get("acceptAddress") or "",
                    status_code=str(route.get("opCode") or ""),
                    raw=route,
                ))
            if not events:
                return fail("解析失败", "SF routes without parsable acceptTime")

            events.sort(key=lambda e: e.event_time, reverse=True)
            latest = events[0]
            return TrackingResult(
                success=True,
                waybill_no=waybill_no,
                current_status=map_sf_route_status(latest.raw),
                current_status_text=latest.description,
                current_location=latest.location,
                last_event_time=latest.event_time,
                events=events,
            )
        except Exception as e:
            logger.warning("SF route parse failed %s: %s", waybill_no, e)
            print(f"[tracking.sf] parse failed {waybill_no} err={e}", flush=True)
            return fail("解析失败", str(e))
