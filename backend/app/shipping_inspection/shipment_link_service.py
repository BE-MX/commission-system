"""验货单 ↔ 物流单：弹框预填与「上传运单并关联」。

关联本身（版本校验、数据范围、审计）仍由 service.bind_shipment 收口；
这里只负责两件事：
  1. 按验货单 → 出库单 → 订单/客户，推断运单弹框可预填的收件人与国家
  2. 复用物流跟踪的运单入库主流程（upload_service），入库后立即关联本验货单
"""

import logging
from types import SimpleNamespace

from sqlalchemy import func, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.models import ArkUser
from app.core.time import beijing_today
from app.shipping_inspection import outbound_service, service
from app.shipping_inspection.models import ShippingInspection

logger = logging.getLogger("commission")

EDIT_PERMISSIONS = {"shipping_inspection:write", "shipping_inspection:admin"}


class ShipmentLinkError(ValueError):
    """运单已入库物流跟踪，但关联验货单失败；前端据此提示改走「关联已有运单」。"""


def _invoice_contact(db: Session, customer_id: str, order_ids: list[str]) -> str:
    """收件人优先级：本单发票联系人 → 客户共享收货地址联系人 → 该客户最近一张发票联系人。"""
    from app.invoice.models import CustomerProfile, Invoice
    base = db.query(Invoice.contact_name).filter(
        Invoice.customer_id == customer_id, Invoice.contact_name.isnot(None), Invoice.contact_name != "")
    if order_ids:
        name = base.filter(Invoice.xiaoman_order_id.in_(order_ids)).order_by(
            Invoice.created_at.desc(), Invoice.id.desc()).limit(1).scalar()
        if name:
            return name.strip()
    profile = db.get(CustomerProfile, customer_id)
    name = ((profile.delivery_json or {}).get("contact_name") or "") if profile else ""
    if name.strip():
        return name.strip()
    return (base.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(1).scalar() or "").strip()


def _customer_country(db: Session, customer_id: str) -> str:
    """国家：手动同步 overlay（补镜像延迟）→ OKKI 客户镜像。

    客户档案里只有国家代码（US），与物流跟踪里的国家名混用会让同一国家出现两种写法，宁可留空让用户按面单填。
    """
    from app.invoice import product_service
    from app.invoice.models import InvoiceCustomerOverlay
    overlay = db.get(InvoiceCustomerOverlay, customer_id)
    if overlay and (overlay.country_name or "").strip():
        return overlay.country_name.strip()
    country = db.execute(text(
        f"SELECT country_name FROM `{product_service._schema()}`.customer_info WHERE company_id = :cid LIMIT 1"
    ), {"cid": customer_id}).scalar()
    return str(country).strip() if country else ""


def shipment_prefill(db: Session, inspection: ShippingInspection) -> dict:
    """运单弹框预填。业务库不可用时只降级为空字段，不阻断上传（用户可手填）。"""
    # 降级分支会 rollback，ORM 对象随之过期；先取出要用的字段，避免连接已坏时在 except 里再查库
    inspection_id, customer_name = inspection.id, inspection.customer_name or ""
    result = {
        "id": inspection.id,
        "outbound_no": inspection.outbound_no,
        "customer_name": inspection.customer_name,
        "status": inspection.status,
        "edit_version": inspection.edit_version,
        "shipment_version": inspection.shipment_version,
        "shipment": service.shipment_brief(db, inspection),
        "order_id": None,
        "recipient_name": "",
        "recipient_country": "",
        "ship_date": beijing_today().isoformat(),
    }
    record_id = str(inspection.outbound_record_id)
    try:
        order_ids = outbound_service.order_ids_for_records(db, [record_id]).get(record_id, [])
        result["order_id"] = "、".join(order_ids) or None
        record = outbound_service.get_outbound_record(db, record_id, include_deleted=True)
        customer_id = str((record or {}).get("company_id") or "").strip()
        if customer_id:
            result["recipient_name"] = _invoice_contact(db, customer_id, order_ids)
            result["recipient_country"] = _customer_country(db, customer_id)
    except Exception as exc:  # noqa: BLE001 - 预填失败不能挡住上传
        db.rollback()
        logger.warning("验货单 %s 物流单预填降级: %s", inspection_id, exc)
        print(f"inspection {inspection_id} shipment prefill degraded: {type(exc).__name__}", flush=True)
    # 找不到联系人时用客户名兜底：小客户在 OKKI 里常以人名建档，且字段可改
    result["recipient_name"] = result["recipient_name"] or customer_name
    return result


def link_candidate(db: Session, inspection: ShippingInspection, waybill_no: str, carrier: str, user_id: int) -> dict:
    """关联已有运单前的核对信息。

    只在当前用户物流跟踪查看范围内才返回收件人/国家，供与本单客户对比——
    关联后客户门户会展示该运单轨迹，手误串到别的客户的运单就是信息外泄。
    """
    from app.auth.service import get_live_user_authorization
    from app.tracking.models import ShipmentTracking
    from app.tracking.shipment_service import apply_data_scope
    roles, permissions = get_live_user_authorization(db, user_id)
    if "super_admin" not in roles and not {"tracking:read", "tracking:read_all", "tracking:write"} & set(permissions):
        return {"visible": False}
    user = db.get(ArkUser, user_id)
    query = db.query(ShipmentTracking).filter_by(waybill_no=waybill_no, carrier=carrier, deleted_at=None)
    row = apply_data_scope(query, db, {"sub": str(user_id), "username": user.username if user else "",
                                       "roles": roles, "permissions": permissions}).first()
    if row is None:
        return {"visible": False}
    linked = db.query(func.count(ShippingInspection.id)).filter(
        ShippingInspection.shipment_tracking_id == row.id, ShippingInspection.id != inspection.id).scalar() or 0
    return {"visible": True, "recipient_name": row.receiver_name or "",
            "recipient_country": row.receiver_country or "", "linked_inspections": int(linked)}


def _precheck(db: Session, inspection_id: int, body, user_id: int) -> None:
    """入库前先挡掉一定会关联失败的请求，避免白白在物流跟踪里多出一张孤儿运单。"""
    from app.auth.service import get_live_user_authorization
    roles, permissions = get_live_user_authorization(db, user_id)
    if "super_admin" not in roles:
        if not EDIT_PERMISSIONS & set(permissions):
            raise ValueError("没有验货单编辑权限")
        if "tracking:write" not in permissions:
            raise ValueError("没有物流单上传权限")
    inspection = db.get(ShippingInspection, inspection_id)
    if inspection is None or inspection.status != "submitted" or inspection.edit_version != body.edit_version:
        raise ValueError("验货单已变化，请重新打开后操作")
    if inspection.shipment_version != body.shipment_version:
        raise ValueError("物流单关联已变化，请重新打开后核对")
    service.require_shipment_binding_scope(db, inspection, user_id, roles, permissions)


async def create_and_bind(db: Session, inspection_id: int, body, current_user: dict) -> dict:
    """物流跟踪原流程入库（轮询/短链/钉钉推送不变）→ 关联本验货单。

    Raises:
        ValueError: 前置校验失败（尚未入库）
        WaybillConflict: 运单号已存在，应改走关联已有运单
        ShipmentLinkError: 已入库但关联失败
    """
    from app.tracking import upload_service
    from app.tracking.models import ShipmentTracking
    from app.tracking.schemas import WaybillCreate
    user_id = int(current_user["sub"])
    # 预检与关联是同步 DB（关联还要等验货单行锁），放线程池，不卡住事件循环
    await run_in_threadpool(_precheck, db, inspection_id, body, user_id)
    db.rollback()  # 结束预检读事务；入库流程自己提交
    payload = WaybillCreate(**body.model_dump(include=set(WaybillCreate.model_fields)))
    data = await upload_service.create_waybill_with_tracking(db, payload, current_user)
    tracking = db.query(ShipmentTracking).filter_by(
        waybill_no=payload.waybill_no, carrier=payload.carrier, deleted_at=None).first()
    if tracking is None:
        # 运单行已写入但跟踪行没建成：重试会撞重复、关联又找不到跟踪行，用户自己走不出来
        raise ShipmentLinkError("运单已录入，但物流跟踪记录没有建成，暂时无法关联；请把运单号发给系统管理员补建跟踪记录")
    try:
        data["shipment"] = await run_in_threadpool(_bind_and_commit, db, inspection_id, payload, body, user_id)
    except Exception as exc:
        db.rollback()
        logger.warning("验货单 %s 关联新运单 %s 失败: %s", inspection_id, payload.waybill_no, exc)
        print(f"inspection {inspection_id} shipment link failed after waybill created: {type(exc).__name__}", flush=True)
        reason = str(exc) if isinstance(exc, ValueError) else "保存失败"
        raise ShipmentLinkError(f"运单已录入物流跟踪，但关联验货单失败：{reason}") from exc
    return data


def _bind_and_commit(db: Session, inspection_id: int, payload, body, user_id: int) -> dict:
    shipment = service.bind_shipment(db, inspection_id, SimpleNamespace(
        waybill_no=payload.waybill_no, carrier=payload.carrier,
        edit_version=body.edit_version, shipment_version=body.shipment_version), user_id)
    db.commit()
    return shipment
