"""发货检验 — 检验单与照片的写侧逻辑

业务库（lsordertest）只读；检验数据全部落 commission_db 自有表。
提交校验规则收口在 submit() 一处：整单（含明细）照片总数 ≥ 1；
若业务要求收紧为"每条明细必拍"，只改这一个函数。
"""

import logging
import hashlib

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from app.core.list_sort import apply_list_sort
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.core.storage import transfers
from app.shipping_inspection import constants as C
from app.shipping_inspection import file_service, outbound_service, audit_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from app.shipping_inspection.print_service import sort_outbound_print_items

logger = logging.getLogger("commission")


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("shipping inspection transaction commit failed", exc_info=True)
        print("shipping inspection transaction commit failed; rolled back", flush=True)
        raise


def _photo_to_dict(photo: ShippingInspectionPhoto, stale_ids=(), local_items=None) -> dict:
    item_id = photo.item_id
    if local_items and item_id is not None:
        item_id = local_items.get(str(item_id), item_id)
    return {"id": photo.id, "item_id": item_id, "file_path": photo.file_path, "sort": photo.sort, "media_type": photo.media_type,
            "storage_state": getattr(photo, '_storage_state', 'local'), "stale": photo.id in stale_ids,
            "created_at": photo.created_at, "created_by_name": getattr(photo, '_uploader_name', None)}


def _display_item_ids(db: Session, outbound_record_id: str) -> dict[str, str]:
    """Resolve evidence bound to a stable remote id onto the current local detail id.

    Photos inherited across a recreated detail are bound to ``okki:<remote>`` while
    the mirror still lags; the station groups by local ids, so resolve on read.
    """
    if not outbound_record_id:
        return {}
    try:
        return {'okki:' + str(row['remote_item_id']): str(row['local_item_id'])
                for row in outbound_service.inspection_item_links(db, outbound_record_id)
                if row.get('remote_item_id') is not None and row.get('local_item_id') is not None}
    except Exception as exc:  # noqa: BLE001 - display-only fallback keeps raw bindings
        logger.warning("验货照片明细ID解析失败 outbound=%s: %s", outbound_record_id, exc)
        print(f"[shipping_inspection] 照片明细ID解析失败 outbound={outbound_record_id}: {exc}", flush=True)
        return {}


def _uploader_names(db: Session, photos: list[ShippingInspectionPhoto]) -> dict[int, str]:
    """批量取上传人姓名：照片墙要按张显示「谁·何时」，逐张 db.get 会变成 N+1。"""
    user_ids = {photo.created_by for photo in photos if photo.created_by}
    if not user_ids:
        return {}
    return {user_id: real_name for user_id, real_name in
            db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(user_ids)).all()}


def list_photos(db: Session, inspection_id: int, media_type: str = "image") -> list[ShippingInspectionPhoto]:
    photos = (
        db.query(ShippingInspectionPhoto)
        .filter(ShippingInspectionPhoto.inspection_id == inspection_id, ShippingInspectionPhoto.media_type == media_type)
        .order_by(ShippingInspectionPhoto.sort.asc(), ShippingInspectionPhoto.id.asc())
        .all()
    )
    if transfers.managed('shipping-inspection') and photos:
        identities = [transfers.transfer_id('shipping-inspection', p.file_path) for p in photos]
        states = {r.id: r.status for r in db.query(transfers.StorageTransfer).filter(transfers.StorageTransfer.id.in_(identities)).all()}
        for photo in photos:
            photo._storage_state = states.get(transfers.transfer_id('shipping-inspection', photo.file_path), 'local')
    uploaders = _uploader_names(db, photos)
    for photo in photos:
        photo._uploader_name = uploaders.get(photo.created_by)
    return photos


def _photo_count(db: Session, inspection_id: int) -> int:
    # 主表行锁后做当前读，不能在 MySQL RR 下沿用权限查询建立的旧快照。
    return len(
        db.query(ShippingInspectionPhoto.id)
        .filter(ShippingInspectionPhoto.inspection_id == inspection_id, ShippingInspectionPhoto.media_type == "image")
        .with_for_update()
        .all()
    )


def _get_by_outbound_id(db: Session, outbound_record_id: str) -> ShippingInspection | None:
    return (
        db.query(ShippingInspection)
        .filter(ShippingInspection.outbound_record_id == outbound_record_id)
        .first()
    )


def _lock_inspection(db: Session, inspection_id: int) -> ShippingInspection | None:
    """对检验单行加写锁（SQLite 下 FOR UPDATE 被忽略，测试不受影响）。

    上传/删除/提交/撤回都要先拿这把锁再判状态、再数照片，
    否则并发下 photo_count 快照与实际照片会长期对不上。
    """
    return (
        db.query(ShippingInspection)
        .filter(ShippingInspection.id == inspection_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def get_or_create_draft(db: Session, outbound_record_id: str, user_id: int) -> ShippingInspection:
    """按出库单 id 取检验单；没有则从业务库取单头快照建 draft。

    唯一键 outbound_record_id 兜底并发：两个请求同建一单时，后到的 IntegrityError
    回退为复用已有行。MySQL REPEATABLE READ 下使用 savepoint 回滚与当前读，
    既看到对方已提交的行，也保留共用手机会话锁与外层审计事务。
    """
    from app.shipping_inspection.outbound_sync_state import ensure_inspection_idle
    ensure_inspection_idle(db, outbound_record_id, user_id)
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
        # Savepoint has rolled back. Current read sees the winner without releasing
        # the caller's station-session lock or discarding its audit transaction.
        print("shipping inspection concurrent draft creation; reusing winner", flush=True)
        inspection = db.query(ShippingInspection).filter_by(outbound_record_id=outbound_record_id).with_for_update().populate_existing().first()
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
    media_type: str = "image",
    edit_version: int = 0,
    commit: bool = True,
    request_id: str | None = None,
) -> ShippingInspectionPhoto:
    """上传一张照片：draft 检验单懒创建；已提交的单拒绝再传。"""
    inspection = get_or_create_draft(db, outbound_record_id, user_id)
    # 行锁串行化 上传/删除/提交：先锁再判状态、再数照片
    inspection = _lock_inspection(db, inspection.id) or inspection
    payload = None
    if request_id:
        with file_service.resolve_path(file_path).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        payload = dict(outbound_record_id=outbound_record_id, item_id=item_id or None,
                       edit_version=edit_version, media_type=media_type, sha256=digest)
        # Inspection row lock serializes retries for the same outbound record.
        prior = db.query(ShippingOperationEvent).filter_by(
            scope=f'mini:{user_id}', request_id=request_id,
        ).populate_existing().with_for_update().first()
        if prior:
            if prior.action != 'upload' or prior.payload != payload:
                raise ValueError('上传请求编号已用于其他内容，请刷新后重新选择文件')
            # A retry may have opened its RR snapshot before the first upload committed.
            photo = db.query(ShippingInspectionPhoto).filter_by(id=prior.media_id).populate_existing().with_for_update().first()
            if photo is None:
                raise ValueError('该文件已被删除，请刷新核对')
            return photo
    if inspection.edit_version != edit_version:
        raise ValueError("验货单已撤回更新，请重新扫码后上传")
    if media_type not in {"image", "video"}:
        raise ValueError("不支持的媒介类型")
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
        media_type=media_type,
        sort=_photo_count(db, inspection.id),
        created_by=user_id,
    )
    db.add(photo)
    transfer = transfers.register(db, 'shipping-inspection', file_path)
    photo._storage_state = transfer.status if transfer else 'local'
    inspection.updated_at = beijing_now()
    inspection.updated_by = user_id
    db.flush()
    if commit:
        audit_service.record(db, 'upload', user_id, outbound_record_id, inspection=inspection, media_id=photo.id,
                             request_id=request_id, payload=payload)
        _commit(db)
        db.refresh(photo)
    return photo


def delete_photo(db: Session, photo_id: int, user_id: int, *, edit_version: int = 0, media_type: str = "image", commit: bool = True):
    """仅 draft 可删；删库行后顺手清落盘文件，清文件失败只记日志（残留文件可人工清理）。"""
    photo = db.get(ShippingInspectionPhoto, photo_id)
    if photo is None or photo.media_type != media_type:
        raise ValueError("照片不存在")
    source = db.get(ShippingInspection, photo.inspection_id)
    if source is None:
        raise ValueError("验货单不存在")
    from app.shipping_inspection.outbound_sync_state import ensure_inspection_idle
    ensure_inspection_idle(db, source.outbound_record_id, user_id)
    from app.shipping_inspection.outbound_sync_state import evidence
    stale_ids, _ = evidence(db, source.outbound_record_id)
    if photo.id in stale_ids:
        raise ValueError('旧版本验货媒体需保留归档，不能删除')
    inspection = _lock_inspection(db, photo.inspection_id)
    if inspection is not None and inspection.edit_version != edit_version:
        raise ValueError("验货单已撤回更新，请重新扫码后删除")
    if inspection is not None and inspection.status == C.STATUS_SUBMITTED:
        raise ValueError("该发货单已提交验货，不能删除照片")
    rel_path = photo.file_path
    transfers.tombstone(db, 'shipping-inspection', rel_path)
    if inspection is not None:
        inspection.updated_at = beijing_now()
        inspection.updated_by = user_id
    db.delete(photo)
    if not commit:
        db.flush()
        return rel_path
    audit_service.record(db, 'delete', user_id, inspection.outbound_record_id, inspection=inspection, media_id=photo_id)
    _commit(db)
    if transfers.managed('shipping-inspection'):
        return
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
    edit_version: int = 0,
    commit: bool = True,
    submitted_ids: list[int] | None = None,
) -> ShippingInspection:
    """提交验货：照片总数 ≥ 1；已提交幂等返回原单（request_id 靠状态幂等，不落库）。"""
    from app.invoice import shipment_inspection_service as completion
    outbound = completion.lock_for_record(db, outbound_record_id)
    inspection = _get_by_outbound_id(db, outbound_record_id)
    from app.shipping_inspection.outbound_sync_state import ensure_submission_ready
    sync_event = ensure_submission_ready(db, outbound_record_id, user_id, inspection) if inspection else None
    if inspection is not None:
        # 行锁挡住并发的上传/删除，保证 photo_count 快照与实际一致
        inspection = _lock_inspection(db, inspection.id)
    if inspection is not None and inspection.edit_version != edit_version:
        raise ValueError("验货单已撤回更新，请重新扫码后提交")
    if inspection is not None and inspection.status == C.STATUS_SUBMITTED:
        completion.sync_record(db, outbound, actor_id=user_id)
        if commit:
            _commit(db)
        return inspection
    count = _photo_count(db, inspection.id) if inspection is not None else 0
    if count < 1:
        raise ValueError("每个发货单至少上传一张照片")
    if sync_event:
        from app.shipping_inspection.outbound_sync_state import persist_recovered_evidence
        persist_recovered_evidence(db, sync_event, user_id, inspection)
    inspection.status = C.STATUS_SUBMITTED
    inspection.photo_count = count
    inspection.submitted_at = beijing_now()
    inspection.submitted_by = user_id
    if remark is not None:
        inspection.remark = remark
    inspection.updated_at = beijing_now()
    inspection.updated_by = user_id
    if sync_event and (sync_event.result or {}).get('required_recheck_ids'):
        sync_event.result = {**sync_event.result, 'required_recheck_ids': [], 'recheck_completed_at': str(beijing_now())}
    completion.sync_record(db, outbound, actor_id=user_id)
    if commit:
        audit_service.record(db, 'submit', user_id, outbound_record_id, inspection=inspection)
        _commit(db)
        db.refresh(inspection)
    else:
        db.flush()
    if submitted_ids is not None:
        submitted_ids.append(inspection.id)
    return inspection


def recall(db: Session, inspection_id: int, user_id: int, edit_version: int) -> ShippingInspection:
    """撤回保留全部媒体/备注，版本令牌阻止旧提交或旧撤回请求越过编辑轮次。"""
    current = db.get(ShippingInspection, inspection_id)
    if current is None:
        raise ValueError("验货单不存在")
    from app.invoice import shipment_inspection_service as completion
    outbound = completion.lock_for_record(db, current.outbound_record_id)
    from app.shipping_inspection.outbound_sync_state import lock, ACTIVE
    sync_event = lock(db, current.outbound_record_id, user_id)
    if sync_event.action in ACTIVE:
        raise ValueError('出库单正在同步或结果待核对，暂不能撤回验货')
    inspection = _lock_inspection(db, inspection_id)
    if inspection is None:
        raise ValueError("验货单不存在")
    if inspection.status == C.STATUS_DRAFT and inspection.edit_version == edit_version + 1:
        return inspection
    if inspection.status != C.STATUS_SUBMITTED or inspection.edit_version != edit_version:
        raise ValueError("验货单状态已变化，请刷新列表后重试")
    inspection.status = C.STATUS_DRAFT
    inspection.edit_version += 1
    inspection.recalled_at = beijing_now()
    inspection.recalled_by = user_id
    inspection.updated_at = inspection.recalled_at
    inspection.updated_by = user_id
    completion.sync_record(db, outbound, actor_id=user_id)
    audit_service.record(db, 'recall', user_id, inspection.outbound_record_id, inspection=inspection,
                         context={'source': 'pc', 'scope': f'pc:{user_id}'})
    _commit(db)
    db.refresh(inspection)
    return inspection


def scan_payload(db: Session, outbound_record_id: str) -> dict:
    """手机与小程序扫码返回；明细顺序与出库单打印一致。"""
    record = outbound_service.get_outbound_record(db, outbound_record_id)
    if record is None:
        raise ValueError("出库单不存在，请核对二维码")
    items = sort_outbound_print_items(outbound_service.list_outbound_items(db, outbound_record_id))
    inspection = _get_by_outbound_id(db, outbound_record_id)
    photos = list_photos(db, inspection.id) if inspection is not None else []
    videos = list_photos(db, inspection.id, "video") if inspection is not None else []
    local_items = _display_item_ids(db, outbound_record_id) if photos or videos else {}
    from app.shipping_inspection.outbound_sync_state import evidence, BLOCKED, requires_recheck_photo
    stale_ids, required_ids = evidence(db, outbound_record_id)
    sync_event = db.query(ShippingOperationEvent).filter_by(scope='outbound-invoice-sync', request_id=str(outbound_record_id)).first()
    return {
        "record": record,
        "items": [{**item, "requires_recheck_photo": requires_recheck_photo(item)} for item in items],
        "inspection": (
            {"id": inspection.id, "status": inspection.status, "photo_count": len(photos),
             "edit_version": inspection.edit_version, "remark": inspection.remark}
            if inspection is not None else None
        ),
        "photos": [_photo_to_dict(p, stale_ids, local_items) for p in photos],
        "videos": [_photo_to_dict(p, stale_ids, local_items) for p in videos],
        "required_recheck_ids": required_ids,
        "outbound_sync_pending": bool(sync_event and sync_event.action in BLOCKED),
    }


def scan_for_user(db, outbound_record_id, user_id, request_id=None):
    db.query(ArkUser.id).filter_by(id=user_id).with_for_update().first()
    payload = scan_payload(db, outbound_record_id)
    from app.shipping_inspection.models import ShippingOperationEvent
    previous = db.query(ShippingOperationEvent).filter_by(scope=f'mini:{user_id}', request_id=request_id).first() if request_id else None
    if previous and previous.outbound_record_id != outbound_record_id:
        raise ValueError('扫码请求编号已用于其他单据')
    if not previous:
        audit_service.record(db, 'scan', user_id, outbound_record_id, request_id=request_id)
        _commit(db)
    return payload


# ── PC 验货单列表 / 详情 ──────────────────────────────────


def list_records(
    db: Session,
    *,
    keyword: str | None = None,
    order_id: str | None = None,
    salesperson_name: str | None = None,
    submitted_by_name: str | None = None,
    date_from=None,
    date_to=None,
    page: int = 1,
    page_size: int = 20,
    okki_user_id: str | None = None,
    sort_field: str = "submitted_at",
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    """已提交验货单分页：keyword 匹配单号/客户，date 按提交时间过滤（含当日）。"""
    from app.shipping_inspection import record_query_service
    query = (
        db.query(ShippingInspection, ArkUser.real_name)
        .outerjoin(ArkUser, ArkUser.id == ShippingInspection.submitted_by)
        .filter(ShippingInspection.status == C.STATUS_SUBMITTED)
    )
    if okki_user_id is not None:
        query = query.filter(ShippingInspection.outbound_record_id.in_(
            outbound_service.scoped_record_ids_query(db, okki_user_id)))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            ShippingInspection.outbound_no.like(like),
            ShippingInspection.customer_name.like(like),
        ))
    if order_id:
        from app.shipping_inspection import record_query_service
        query = query.filter(ShippingInspection.outbound_record_id.in_(
            record_query_service.order_record_ids(db, order_id)))
    if salesperson_name and salesperson_name.strip():
        query = query.filter(ShippingInspection.outbound_record_id.in_(
            record_query_service.salesperson_record_ids(db, salesperson_name)))
    if submitted_by_name:
        query = query.filter(ArkUser.real_name.contains(submitted_by_name.strip(), autoescape=True))
    if date_from:
        query = query.filter(ShippingInspection.submitted_at >= date_from)
    if date_to:
        from datetime import timedelta
        query = query.filter(ShippingInspection.submitted_at < date_to + timedelta(days=1))
    from app.shipping_inspection.list_sort_service import inspection_link_sort_values
    columns = {
        "outbound_no": ShippingInspection.outbound_no,
        "customer_name": ShippingInspection.customer_name,
        "photo_count": ShippingInspection.photo_count,
        "submitted_at": ShippingInspection.submitted_at,
        "remark": ShippingInspection.remark,
        "submitted_by_name": ArkUser.real_name,
        **inspection_link_sort_values(db),
    }
    query = apply_list_sort(query, sort_field, sort_order, columns,
        default=(ShippingInspection.submitted_at.desc(), ShippingInspection.id.desc()),
        tie_breakers=(ShippingInspection.id.asc(),))
    total = query.count()
    rows = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    salespeople = record_query_service.salesperson_names(db, [str(insp.outbound_record_id) for insp, _ in rows])
    order_ids = outbound_service.order_ids_for_records(db, [str(insp.outbound_record_id) for insp, _ in rows])
    items = [{
        "id": insp.id,
        "edit_version": insp.edit_version,
        "outbound_record_id": insp.outbound_record_id,
        "outbound_no": insp.outbound_no,
        "order_id": "、".join(order_ids.get(str(insp.outbound_record_id), [])) or None,
        "customer_name": insp.customer_name,
        "photo_count": insp.photo_count,
        "submitted_at": insp.submitted_at,
        "submitted_by_name": real_name,
        "salesperson_name": salespeople.get(str(insp.outbound_record_id)),
        "remark": insp.remark,
    } for insp, real_name in rows]
    return items, total


def get_record_detail(db: Session, inspection_id: int) -> dict | None:
    """验货单详情：自有表单头 + 照片；明细实时查业务库，业务库不可用时降级为空。"""
    inspection = db.get(ShippingInspection, inspection_id)
    if inspection is None:
        return None
    photos = list_photos(db, inspection.id)
    videos = list_photos(db, inspection.id, "video")
    local_items = _display_item_ids(db, inspection.outbound_record_id) if photos or videos else {}
    from app.shipping_inspection.outbound_sync_state import evidence, BLOCKED, requires_recheck_photo
    stale_ids, required_ids = evidence(db, inspection.outbound_record_id)
    sync_event = db.query(ShippingOperationEvent).filter_by(scope='outbound-invoice-sync', request_id=inspection.outbound_record_id).first()
    try:
        items = outbound_service.list_outbound_items(db, inspection.outbound_record_id)
    except Exception as exc:  # noqa: BLE001 - 历史验货单不该被业务库结构变化卡死
        logger.warning("验货单 %s 明细查询降级为空: %s", inspection_id, exc)
        items = []
    submitter = db.get(ArkUser, inspection.submitted_by) if inspection.submitted_by else None
    return {
        "id": inspection.id,
        "status": inspection.status,
        "shipment": shipment_brief(db, inspection),
        "shipment_version": inspection.shipment_version,
        "edit_version": inspection.edit_version,
        "outbound_record_id": inspection.outbound_record_id,
        "outbound_no": inspection.outbound_no,
        "order_id": "、".join(outbound_service.order_ids_for_records(
            db, [inspection.outbound_record_id]).get(str(inspection.outbound_record_id), [])) or None,
        "customer_name": inspection.customer_name,
        "remark": inspection.remark,
        "submitted_at": inspection.submitted_at,
        "submitted_by_name": submitter.real_name if submitter else None,
        "items": [{**item, "requires_recheck_photo": requires_recheck_photo(item)} for item in items],
        "photos": [_photo_to_dict(p, stale_ids, local_items) for p in photos],
        "videos": [_photo_to_dict(p, stale_ids, local_items) for p in videos],
        "required_recheck_ids": required_ids,
        "outbound_sync_pending": bool(sync_event and sync_event.action in BLOCKED),
    }



def shipment_brief(db, inspection):
    from app.tracking.models import ShipmentTracking
    row = db.get(ShipmentTracking, inspection.shipment_tracking_id) if inspection.shipment_tracking_id else None
    if row is None or row.deleted_at is not None:
        return None
    return dict(waybill_no=row.waybill_no, carrier=row.carrier, shipment_version=inspection.shipment_version)


def require_shipment_binding_scope(db, inspection, user_id, roles, permissions):
    from app.auth.models import ArkUserExternalBinding
    if 'super_admin' in roles or 'shipping_inspection:inspection_read_all' in permissions:
        return
    binding = db.query(ArkUserExternalBinding).filter(
        ArkUserExternalBinding.ark_user_id == user_id,
        ArkUserExternalBinding.provider == 'okki', ArkUserExternalBinding.binding_status == 'active',
        ArkUserExternalBinding.deleted_at.is_(None)).order_by(
            ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id).first()
    okki_id = str(binding.external_account_id).strip() if binding and binding.external_account_id else ''
    if not okki_id or outbound_service.get_outbound_record(db, inspection.outbound_record_id, okki_user_id=okki_id) is None:
        raise ValueError('验货单不存在或不在当前授权范围内')


def bind_shipment(db, inspection_id, body, user_id):
    from app.tracking.models import ShipmentTracking
    from app.auth.service import get_live_user_authorization
    from app.tracking.shipment_service import apply_data_scope
    roles, permissions = get_live_user_authorization(db, user_id)
    if 'super_admin' not in roles:
        if not {'shipping_inspection:write', 'shipping_inspection:admin'} & set(permissions):
            raise ValueError('没有验货单编辑权限')
        if not {'tracking:read', 'tracking:read_all', 'tracking:write'} & set(permissions):
            raise ValueError('没有物流跟踪访问权限')
    inspection = _lock_inspection(db, inspection_id)
    if inspection is None or inspection.status != 'submitted' or inspection.edit_version != body.edit_version:
        raise ValueError('验货单已变化，请重新打开后操作')
    if inspection.shipment_version != body.shipment_version:
        raise ValueError('物流单关联已变化，请重新打开后核对')
    require_shipment_binding_scope(db, inspection, user_id, roles, permissions)
    user = db.get(ArkUser, user_id)
    query = db.query(ShipmentTracking).filter_by(waybill_no=body.waybill_no, carrier=body.carrier)
    shipment = apply_data_scope(query, db, {'sub': str(user_id), 'username': user.username if user else '',
        'roles': roles, 'permissions': permissions}).with_for_update().populate_existing().first()
    if shipment is None or shipment.deleted_at is not None or not shipment.source_image_url:
        raise ValueError('请先在物流跟踪上传并确认该物流单')
    # Explicit employee confirmation establishes the association; never infer it from names.
    if inspection.shipment_tracking_id == shipment.id:
        return shipment_brief(db, inspection)
    inspection.shipment_tracking_id = shipment.id
    inspection.shipment_version += 1
    inspection.updated_by = user_id
    audit_service.record(db, 'shipment_bound', user_id, inspection.outbound_record_id, inspection=inspection,
        context={'source': 'pc'}, payload={'shipment_tracking_id': shipment.id})
    db.flush()
    return shipment_brief(db, inspection)
