"""dws CLI sync: push shipment status to DingTalk AITable"""

import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.tracking import ShipmentTracking
from app.services.short_link import build_short_link

logger = logging.getLogger("tracking.dws_sync")

AITABLE_BASE_ID = "N7dx2rn0Jb65oB3Zh234Ykr2JMGjLRb3"
AITABLE_TABLE_ID = "mozp3qK"

CARRIER_NAME_MAP = {
    "DHL": "DHL",
    "FEDEX": "FEDEX",
    "UPS": "UPS",
    "TNT": "TNT",
}


def _dws_cmd() -> str:
    """找 dws 可执行路径，Windows 优先用 dws.cmd"""
    for candidate in ["dws.cmd", "dws"]:
        path = shutil.which(candidate)
        if path:
            return path
    if sys.platform == "win32":
        # shutil.which 在 uvicorn 子进程里可能读不到用户 PATH，主动探测 npm 全局目录
        import os
        for base in [
            os.environ.get("APPDATA", ""),
            os.path.expanduser("~\\AppData\\Roaming"),
        ]:
            for name in ["dws.cmd", "dws"]:
                full = os.path.join(base, "npm", name)
                if os.path.exists(full):
                    return full
    raise RuntimeError("dws not found in PATH")


_DWS_BIN: str | None = None


def _dws(*args) -> dict:
    global _DWS_BIN
    if _DWS_BIN is None:
        _DWS_BIN = _dws_cmd()
    cmd = [_DWS_BIN] + list(args) + ["--format", "json", "--yes"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"dws non-JSON: {result.stdout} {result.stderr}")
    if data.get("status") != "success":
        raise RuntimeError(f"dws error: {data.get('error')}")
    return data


def _build_cells(shipment: ShipmentTracking) -> dict:
    cells = {}
    cells["EU6A9PM"] = shipment.waybill_no
    if shipment.dingtalk_user_name:
        cells["1cc733E"] = shipment.dingtalk_user_name
    if shipment.receiver_name:
        cells["33cHsWj"] = shipment.receiver_name
    carrier_key = (shipment.carrier or "").upper()
    carrier_display = CARRIER_NAME_MAP.get(carrier_key, shipment.carrier_name)
    if carrier_display:
        cells["kMWLJhM"] = {"name": carrier_display}
    if shipment.waybill_no:
        cells["apv5MKE"] = shipment.waybill_no

    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    if shipment.shipped_at:
        cells["uSS0Ggh"] = fmt(shipment.shipped_at)
    if shipment.delivered_at:
        cells["8LTGmnB"] = fmt(shipment.delivered_at)
    if shipment.last_event_time:
        cells["3jKfHfG"] = fmt(shipment.last_event_time)
    if shipment.current_status_text:
        cells["bv2PXgS"] = shipment.current_status_text
    if shipment.short_code:
        cells["kWV3PAs"] = build_short_link(shipment.short_code)
    return cells


def sync_shipment(db: Session, shipment: ShipmentTracking) -> bool:
    cells = _build_cells(shipment)
    try:
        if not shipment.dingtalk_sheet_row_id:
            data = _dws(
                "aitable", "record", "create",
                "--base-id", AITABLE_BASE_ID,
                "--table-id", AITABLE_TABLE_ID,
                "--records", json.dumps([{"cells": cells}], ensure_ascii=False),
            )
            record_id = data["data"]["newRecordIds"][0]
            shipment.dingtalk_sheet_row_id = record_id
            shipment.last_synced_at = datetime.now()
            db.commit()
            logger.info(f"{shipment.waybill_no}: created row {record_id}")
        else:
            _dws(
                "aitable", "record", "update",
                "--base-id", AITABLE_BASE_ID,
                "--table-id", AITABLE_TABLE_ID,
                "--records", json.dumps(
                    [{"recordId": shipment.dingtalk_sheet_row_id, "cells": cells}],
                    ensure_ascii=False,
                ),
            )
            shipment.last_synced_at = datetime.now()
            db.commit()
            logger.info(f"{shipment.waybill_no}: updated row {shipment.dingtalk_sheet_row_id}")
        return True
    except Exception as e:
        logger.warning(f"{shipment.waybill_no}: sync failed - {e}")
        return False


def sync_all_active(db: Session) -> dict:
    shipments = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.is_active == True)
        .all()
    )
    ok = fail = 0
    for s in shipments:
        if sync_shipment(db, s):
            ok += 1
        else:
            fail += 1
    logger.info(f"dws sync done: ok={ok} fail={fail}")
    return {"ok": ok, "fail": fail, "total": ok + fail}
