"""发货检验 — 检验单与照片的写侧逻辑

业务库（lsordertest）只读；检验数据全部落 commission_db 自有表。
提交校验规则收口在 submit() 一处：整单（含明细）照片总数 ≥ 1；
若业务要求收紧为"每条明细必拍"，只改这一个函数。
"""

import logging

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.shipping_inspection import constants as C
from app.shipping_inspection import file_service, outbound_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto

logger = logging.getLogger("commission")


def _photo_to_dict(photo: ShippingInspectionPhoto) -> dict:
    return {"id": photo.id, "item_id": photo.item_id, "file_path": photo.file_path, "sort": photo.sort}


def list_photos(db: Session, inspection_id: int) -> list[ShippingInspectionPhoto]:
    return (
        db.query(ShippingInspectionPhoto)
        .filter(ShippingInspectionPhoto.inspection_id == inspection_id)
        .order_by(ShippingInspectionPhoto.sort.asc(), ShippingInspectionPhoto.id.asc())
        .all()
    )


def _photo_count(db: Session, inspection_id: int) -> int:
    return (
        db.query(func.count(ShippingInspectionPhoto.id))
        .filter(ShippingInspectionPhoto.inspection_id == inspection_id)
        .scalar()
    ) or 0


def _get_by_outbound_id(db: Session, outbound_record_id: str) -> ShippingInspection | None:
    return (
        db.query(ShippingInspection)
        .filter(ShippingInspection.outbound_record_id == outbound_record_id)
        .first()
    )


def _lock_inspection(db: Session, inspection_id: int) -> ShippingInspection | None:
    """对检验单行加写锁（SQLite 下 FOR UPDATE 被忽略，测试不受影响）。

    上传/删除/提交三个写路径都要先拿这把锁再判状态、再数照片，
    否则并发下 photo_count 快照与实际照片会长期对不上。
    """
    return (
        db.query(ShippingInspection)
        .filter(ShippingInspection.id == inspection_id)
        .with_for_update()
        .first()
    )


def get_or_create_draft(db: Session, outbound_record_id: str, user_id: int) -> ShippingInspection:
    """按出库单 id 取检验单；没有则从业务库取单头快照建 draft。

    唯一键 outbound_record_id 兜底并发：两个请求同建一单时，后到的 IntegrityError
    回退为复用已有行。注意 MySQL REPEATABLE READ 下必须先 rollback 换全新快照再重查，
    否则一致性读仍看不到对方刚提交的行（本函数只在 mini 上传路径被调，调用方未 commit）。
    """
    inspection = _get_by_outbound_id(db, outbound_record_id)
    if inspection is not None:
        return inspection

    record = outbound_service.get_outbound_record(db, outbound_record_id)
    if record is None:
        raise ValueError("出库单不存在，请核对二维码")
    inspection = ShippingInspection(
        outbound_record_id=outbound_record_id,
        outbound_no=record["outbound_no"],
        customer_name=record["customer_name"],
        status=C.STATUS_DRAFT,
        created_by=user_id,
        updated_by=user_id,
    )
    try:
        with db.begin_nested():
            db.add(inspection)
            db.flush()
    except IntegrityError as exc:  # noqa: BLE001 - 并发插入同一出库单：回退为复用
        logger.warning("shipping inspection 并发创建回退为复用 outbound=%s: %s", outbound_record_id, exc)
        db.rollback()  # 换全新事务快照，RR 下才能读到对方已提交的行
        inspection = _get_by_outbound_id(db, outbound_record_id)
        if inspection is None:
            raise
    return inspection


def add_photo(
    db: Session,
    *,
    outbound_record_id: str,
    item_id: str | None,
    file_path: str,
    user_id: int,
) -> ShippingInspectionPhoto:
    """上传一张照片：draft 检验单懒创建；已提交的单拒绝再传。"""
    inspection = get_or_create_draft(db, outbound_record_id, user_id)
    # 行锁串行化 上传/删除/提交：先锁再判状态、再数照片
    inspection = _lock_inspection(db, inspection.id) or inspection
    if inspection.status == C.STATUS_SUBMITTED:
        raise ValueError("该发货单已提交验货，不能再上传照片")
    if item_id:
        valid_ids = {item["item_id"] for item in outbound_service.list_outbound_items(db, outbound_record_id)}
        if item_id not in valid_ids:
            raise ValueError("出库明细不存在，请重新扫码获取明细")
    photo = ShippingInspectionPhoto(
        inspection_id=inspection.id,
        item_id=item_id or None,
        file_path=file_path,
        sort=_photo_count(db, inspection.id),
        created_by=user_id,
    )
    db.add(photo)
    inspection.updated_at = beijing_now()
    inspection.updated_by = user_id
    db.commit()
    db.refresh(photo)
    return photo


def delete_photo(db: Session, photo_id: int, user_id: int) -> None:
    """仅 draft 可删；删库行后顺手清落盘文件，清文件失败只记日志（残留文件可人工清理）。"""
    photo = db.get(ShippingInspectionPhoto, photo_id)
    if photo is None:
        raise ValueError("照片不存在")
    inspection = _lock_inspection(db, photo.inspection_id)
    if inspection is not None and inspection.status == C.STATUS_SUBMITTED:
        raise ValueError("该发货单已提交验货，不能删除照片")
    rel_path = photo.file_path
    if inspection is not None:
        inspection.updated_at = beijing_now()
        inspection.updated_by = user_id
    db.delete(photo)
    db.commit()
    try:
        abs_path = file_service.resolve_path(rel_path)
        if abs_path.is_file():
            abs_path.unlink()
    except Exception as exc:  # noqa: BLE001 - 库行已删，文件残留不影响业务结果
        logger.warning("删除验货照片文件失败 path=%s: %s", rel_path, exc)


def submit(
    db: Session,
    *,
    outbound_record_id: str,
    user_id: int,
    remark: str | None = None,
) -> ShippingInspection:
    """提交验货：照片总数 ≥ 1；已提交幂等返回原单（request_id 靠状态幂等，不落库）。"""
    inspection = _get_by_outbound_id(db, outbound_record_id)
    if inspection is not None:
        # 行锁挡住并发的上传/删除，保证 photo_count 快照与实际一致
        inspection = _lock_inspection(db, inspection.id)
    if inspection is not None and inspection.status == C.STATUS_SUBMITTED:
        return inspection
    count = _photo_count(db, inspection.id) if inspection is not None else 0
    if count < 1:
        raise ValueError("每个发货单至少上传一张照片")
    inspection.status = C.STATUS_SUBMITTED
    inspection.photo_count = count
    inspection.submitted_at = beijing_now()
    inspection.submitted_by = user_id
    if remark:
        inspection.remark = remark
    inspection.updated_at = beijing_now()
    inspection.updated_by = user_id
    db.commit()
    db.refresh(inspection)
    return inspection


def scan_payload(db: Session, outbound_record_id: str) -> dict:
    """小程序扫码返回：单头 + 明细 + 已有照片 + 当前状态。"""
    record = outbound_service.get_outbound_record(db, outbound_record_id)
    if record is None:
        raise ValueError("出库单不存在，请核对二维码")
    items = outbound_service.list_outbound_items(db, outbound_record_id)
    inspection = _get_by_outbound_id(db, outbound_record_id)
    photos = list_photos(db, inspection.id) if inspection is not None else []
    return {
        "record": record,
        "items": items,
        "inspection": (
            {"id": inspection.id, "status": inspection.status, "photo_count": len(photos)}
            if inspection is not None else None
        ),
        "photos": [_photo_to_dict(p) for p in photos],
    }


# ── PC 验货单列表 / 详情 ──────────────────────────────────


def list_records(
    db: Session,
    *,
    keyword: str | None = None,
    date_from=None,
    date_to=None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """已提交验货单分页：keyword 匹配单号/客户，date 按提交时间过滤（含当日）。"""
    query = (
        db.query(ShippingInspection, ArkUser.real_name)
        .outerjoin(ArkUser, ArkUser.id == ShippingInspection.submitted_by)
        .filter(ShippingInspection.status == C.STATUS_SUBMITTED)
    )
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            ShippingInspection.outbound_no.like(like),
            ShippingInspection.customer_name.like(like),
        ))
    if date_from:
        query = query.filter(ShippingInspection.submitted_at >= date_from)
    if date_to:
        from datetime import timedelta
        query = query.filter(ShippingInspection.submitted_at < date_to + timedelta(days=1))
    total = query.count()
    rows = (
        query.order_by(ShippingInspection.submitted_at.desc(), ShippingInspection.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [{
        "id": insp.id,
        "outbound_record_id": insp.outbound_record_id,
        "outbound_no": insp.outbound_no,
        "customer_name": insp.customer_name,
        "photo_count": insp.photo_count,
        "submitted_at": insp.submitted_at,
        "submitted_by_name": real_name,
        "remark": insp.remark,
    } for insp, real_name in rows]
    return items, total


def get_record_detail(db: Session, inspection_id: int) -> dict | None:
    """验货单详情：自有表单头 + 照片；明细实时查业务库，业务库不可用时降级为空。"""
    inspection = db.get(ShippingInspection, inspection_id)
    if inspection is None:
        return None
    photos = list_photos(db, inspection.id)
    try:
        items = outbound_service.list_outbound_items(db, inspection.outbound_record_id)
    except Exception as exc:  # noqa: BLE001 - 历史验货单不该被业务库结构变化卡死
        logger.warning("验货单 %s 明细查询降级为空: %s", inspection_id, exc)
        items = []
    submitter = db.get(ArkUser, inspection.submitted_by) if inspection.submitted_by else None
    return {
        "id": inspection.id,
        "outbound_record_id": inspection.outbound_record_id,
        "outbound_no": inspection.outbound_no,
        "customer_name": inspection.customer_name,
        "remark": inspection.remark,
        "submitted_at": inspection.submitted_at,
        "submitted_by_name": submitter.real_name if submitter else None,
        "items": items,
        "photos": [_photo_to_dict(p) for p in photos],
    }
