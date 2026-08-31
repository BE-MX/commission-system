"""内贸订单 service —— 下单、明细维护、发货登记、列表与详情"""

import hashlib
import json
import logging
from datetime import date
from app.core.time import beijing_today

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.domestic import constants as C
from app.domestic import (
    balance_service,
    customer_service,
    product_service,
    progress_service,
    routing_service,
    unit_service,
)
from app.domestic.models import (
    DomesticCustomer,
    DomesticItemAppendRequest,
    DomesticItemProgress,
    DomesticItemUnit,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
    DomesticReportLog,
    DomesticReportUnit,
    DomesticRouteRule,
    DomesticSkipLog,
    DomesticSkipUnit,
)
from app.domestic.schemas import (
    ItemShipRequest,
    OrderCreate,
    OrderItemAppend,
    OrderItemInput,
    OrderItemUpdate,
    OrderUpdate,
)

logger = logging.getLogger("commission")

_TEXT_FIELDS = ("hairstyle", "color", "style_requirement", "remark")
_IMAGE_FIELDS = ("hairstyle_images", "color_images", "style_images", "remark_images")
_PUBLIC_PROGRESS_FIELDS = (
    "step_order",
    "process_name",
    "order_qty",
    "completed_qty",
    "skipped_qty",
    "passed_qty",
    "required_qty",
    "reportable_qty",
    "status",
)


def _public_progress_step(step: dict) -> dict:
    """Serialize the public tracking contract without exposing shop-floor metadata."""
    return {field: step[field] for field in _PUBLIC_PROGRESS_FIELDS}


def _order_request_hash(payload: OrderCreate) -> str:
    """Canonical fingerprint used to reject accidental request-id reuse."""
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude={"request_id"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _item_append_request_hash(payload: OrderItemAppend) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude={"request_id"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _order_create_result(
    db: Session,
    order: DomesticOrder,
    *,
    warnings: list[str] | None = None,
    replayed: bool = False,
) -> dict:
    customer_name = db.query(DomesticCustomer.shop_name).filter(
        DomesticCustomer.id == order.customer_id
    ).scalar()
    item_count = db.query(func.count(DomesticOrderItem.id)).filter(
        DomesticOrderItem.order_id == order.id
    ).scalar() or 0
    return {
        "id": order.id,
        "domestic_no": order.domestic_no,
        "order_no": order.order_no,
        "customer_name": customer_name,
        "item_count": item_count,
        "total_amount": float(order.total_amount or 0),
        "status": order.status,
        "is_draft": order.status == C.ORDER_DRAFT,
        "warnings": warnings or [],
        "replayed": replayed,
    }


def _validate_order_replay(order: DomesticOrder, request_hash: str) -> None:
    if order.request_hash != request_hash:
        raise ValueError("该建单请求号已用于不同订单内容，请刷新页面后重新提交")


def _generate_domestic_no(db: Session) -> str:
    """系统单号 DO{YYYYMMDD}-{NNN}，按天自增。撞号由调用方 savepoint 重试。"""
    prefix = f"DO{beijing_today().strftime('%Y%m%d')}-"
    # 锁定读是必须的：MySQL 默认 RR 下普通读走事务开头的快照，撞号后重试
    # 会一直读到同一个旧最大值，5 次全撞同一个号永远不收敛。
    # 走 ORM 而不是裸 SQL —— with_for_update 会按方言决定是否发 FOR UPDATE，
    # 裸 SQL 写死会让 SQLite（测试库）直接语法错误。
    row = (
        db.query(DomesticOrder.domestic_no)
        .filter(DomesticOrder.domestic_no.like(f"{prefix}%"))
        .order_by(DomesticOrder.domestic_no.desc())
        .limit(1)
        .with_for_update()
        .first()
    )
    seq = 1
    if row:
        try:
            seq = int(row[0].split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}{seq:03d}"


def _build_item(
    db: Session,
    order_id: int,
    line_no: int,
    payload: OrderItemInput,
) -> tuple[DomesticOrderItem, str | None]:
    """建明细行：产品 find-or-create + 路线快照 + 进度展开。返回 (明细, 警告)。"""
    product = product_service.find_or_create_product(db, payload.attrs)
    product.use_count = (product.use_count or 0) + 1

    item = DomesticOrderItem(
        order_id=order_id,
        line_no=line_no,
        product_id=product.id,
        product_name=product.name,
        attrs_snapshot=payload.attrs.model_dump(),
        route_id=product.route_id,
        order_qty=payload.order_qty,
        unit_price=balance_service.money(payload.unit_price),
        status=C.ITEM_PRODUCING,
    )
    for field in _TEXT_FIELDS:
        setattr(item, field, getattr(payload, field, None))
    for field in _IMAGE_FIELDS:
        setattr(item, field, getattr(payload, field, None) or [])
    db.add(item)
    db.flush()
    unit_service.sync_item_units(db, item, item.order_qty)

    warning = None
    if product.route_id:
        steps = progress_service.init_item_progress(db, item)
        if not steps:
            warning = f"「{product.name}」绑定的工艺路线还没配工序，暂时不能开工"
    else:
        warning = f"「{product.name}」的工艺「{product.craft}」还没配工艺路线，暂时不能开工"
    return item, warning


def create_order(db: Session, payload: OrderCreate, user_id: int) -> dict:
    """保存草稿或正式下单；正式单与余额扣款在同一事务完成。"""
    try:
        request_hash = _order_request_hash(payload) if payload.request_id else None
        if payload.request_id:
            existing = db.query(DomesticOrder).filter(
                DomesticOrder.request_id == payload.request_id
            ).first()
            if existing:
                _validate_order_replay(existing, request_hash)
                return _order_create_result(db, existing, replayed=True)

        if payload.customer_id:
            customer = db.query(DomesticCustomer).get(payload.customer_id)
            if not customer:
                raise ValueError("客户不存在")
        else:
            customer = customer_service.find_or_create_by_shop_name(
                db, payload.customer_shop_name, user_id
            )

        # Fast non-locking precheck before the order-number savepoint. The definitive
        # check still happens under the customer lock in sync_order_finance; doing this
        # early also keeps SQLite from retaining a released savepoint after insufficiency.
        estimated_total = balance_service.money(sum(
            balance_service.money(item.unit_price) * item.order_qty
            for item in payload.items
        ))
        available = balance_service.money(customer.balance)
        if not payload.is_draft and available < estimated_total:
            raise ValueError(
                f"客户「{customer.shop_name}」余额不足：当前 ¥{available:.2f}，"
                f"本次需扣 ¥{estimated_total:.2f}"
            )

        order = None
        for _ in range(5):
            savepoint = db.begin_nested()
            candidate = DomesticOrder(
                domestic_no=_generate_domestic_no(db),
                order_no=payload.order_no,
                order_date=payload.order_date,
                customer_id=customer.id,
                order_type=payload.order_type,
                status=C.ORDER_DRAFT if payload.is_draft else C.ORDER_PRODUCING,
                total_amount=0,
                charged_amount=0,
                next_line_no=1,
                item_count=0,
                total_unit_qty=0,
                request_id=payload.request_id,
                request_hash=request_hash,
                remark=payload.remark,
                created_by=user_id,
                deleted_flag=0,
            )
            db.add(candidate)
            try:
                db.flush()
                savepoint.commit()
                order = candidate
                break
            except IntegrityError:
                savepoint.rollback()
                # A concurrent replay may have committed the same request_id while this
                # request was building its graph. Roll back any locally-created customer,
                # then return the first order instead of charging twice.
                if payload.request_id:
                    duplicate = db.query(DomesticOrder).filter(
                        DomesticOrder.request_id == payload.request_id
                    ).with_for_update().first()
                    if duplicate:
                        _validate_order_replay(duplicate, request_hash)
                        duplicate_id = duplicate.id
                        db.rollback()
                        duplicate = db.query(DomesticOrder).filter(
                            DomesticOrder.id == duplicate_id
                        ).one()
                        return _order_create_result(db, duplicate, replayed=True)
                logger.warning("domestic order no collision, retry")
                print("[domestic] 单号撞号，换序号重试", flush=True)
        if order is None:
            raise ValueError("订单号生成冲突，请重试")

        warnings = []
        for line_no, item_payload in enumerate(payload.items, start=1):
            _, warning = _build_item(db, order.id, line_no, item_payload)
            if warning:
                warnings.append(warning)
        order.next_line_no = len(payload.items) + 1
        order.item_count = len(payload.items)
        order.total_unit_qty = sum(item.order_qty for item in payload.items)

        total = balance_service.sync_order_finance(
            db, order, user_id=user_id,
            reason=f"订单 {order.domestic_no} 下单扣款",
        )
        db.commit()
        result = _order_create_result(db, order, warnings=warnings)
        result["total_amount"] = float(total)
        return result
    except Exception:
        db.rollback()
        raise


# ── 列表与详情 ────────────────────────────────────────


def _passage_progress_aggregates(db: Session, item_rows: list) -> dict[int, dict[str, int]]:
    """批量计算列表页每条明细的通行进度，避免逐明细构建完整工序视图。"""
    item_ids = [row.id for row in item_rows]
    if not item_ids:
        return {}

    progress_rows = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.item_id.in_(item_ids))
        .order_by(
            DomesticItemProgress.item_id.asc(),
            DomesticItemProgress.step_order.asc(),
        )
        .all()
    )
    active_unit_rows = db.query(
        DomesticItemUnit.item_id,
        DomesticItemUnit.id,
    ).filter(
        DomesticItemUnit.item_id.in_(item_ids),
        DomesticItemUnit.status == 1,
    ).all()
    reported_rows = (
        db.query(
            DomesticReportLog.item_id,
            DomesticReportUnit.progress_id,
            DomesticReportUnit.unit_id,
        )
        .join(DomesticReportUnit, DomesticReportUnit.log_id == DomesticReportLog.id)
        .filter(
            DomesticReportLog.item_id.in_(item_ids),
            DomesticReportLog.revoked == 0,
        )
        .all()
    )
    skipped_rows = (
        db.query(
            DomesticSkipLog.item_id,
            DomesticSkipUnit.progress_id,
            DomesticSkipUnit.unit_id,
        )
        .join(DomesticSkipUnit, DomesticSkipUnit.skip_log_id == DomesticSkipLog.id)
        .filter(
            DomesticSkipLog.item_id.in_(item_ids),
            DomesticSkipLog.revoked == 0,
        )
        .all()
    )

    route_ids = {row.route_id for row in item_rows if row.route_id}
    rule_rows = db.query(DomesticRouteRule).filter(
        DomesticRouteRule.route_id.in_(route_ids or {0}),
    ).all()

    progress_by_item: dict[int, list[DomesticItemProgress]] = {}
    active_by_item: dict[int, set[int]] = {}
    reported_by_item: dict[int, dict[int, set[int]]] = {}
    skipped_by_item: dict[int, dict[int, set[int]]] = {}
    rules_by_route: dict[int, dict[int, dict]] = {}
    for progress in progress_rows:
        progress_by_item.setdefault(progress.item_id, []).append(progress)
    for item_id, unit_id in active_unit_rows:
        active_by_item.setdefault(item_id, set()).add(unit_id)
    for item_id, progress_id, unit_id in reported_rows:
        reported_by_item.setdefault(item_id, {}).setdefault(progress_id, set()).add(unit_id)
    for item_id, progress_id, unit_id in skipped_rows:
        skipped_by_item.setdefault(item_id, {}).setdefault(progress_id, set()).add(unit_id)
    for rule in rule_rows:
        rules_by_route.setdefault(rule.route_id, {})[rule.process_id] = {
            "process_id": rule.process_id,
            "rule_type": rule.rule_type,
            "config": rule.config_json,
        }

    aggregates: dict[int, dict[str, int]] = {}
    for item in item_rows:
        rows = progress_by_item.get(item.id, [])
        active_unit_ids = active_by_item.get(item.id, set())
        if not active_unit_ids:
            aggregates[item.id] = {
                "done": sum(row.completed_qty for row in rows),
                "capacity": item.order_qty * len(rows),
            }
            continue
        state = routing_service.PassageState(
            reported_by_progress=reported_by_item.get(item.id, {}),
            skipped_by_progress=skipped_by_item.get(item.id, {}),
        )
        _upstream, _skipped, passed = routing_service.effective_passage_maps(
            rows,
            state,
            active_unit_ids,
            rules_by_route.get(item.route_id, {}),
        )
        aggregates[item.id] = {
            "done": sum(len(passed.get(row.id, set())) for row in rows),
            "capacity": item.order_qty * len(rows),
        }
    return aggregates


def list_orders(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    status: int | None = None,
    customer_id: int | None = None,
    order_type: str = "",
    date_start: date | None = None,
    date_end: date | None = None,
    sort_field: str = "",
    sort_order: str = "",
    include_finance: bool = True,
) -> tuple[list[dict], int]:
    q = db.query(DomesticOrder).filter(DomesticOrder.deleted_flag == 0)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter((DomesticOrder.order_no.like(kw)) | (DomesticOrder.domestic_no.like(kw)))
    if status is not None:
        q = q.filter(DomesticOrder.status == status)
    if customer_id:
        q = q.filter(DomesticOrder.customer_id == customer_id)
    if order_type:
        q = q.filter(DomesticOrder.order_type == order_type)
    if date_start:
        q = q.filter(DomesticOrder.order_date >= date_start)
    if date_end:
        q = q.filter(DomesticOrder.order_date <= date_end)

    total = q.count()

    sortable = {
        "order_date": DomesticOrder.order_date,
        "domestic_no": DomesticOrder.domestic_no,
        "status": DomesticOrder.status,
        "created_at": DomesticOrder.created_at,
    }
    col = sortable.get(sort_field, DomesticOrder.created_at)
    q = q.order_by(col.asc() if sort_order == "asc" else col.desc())
    orders = q.offset((page - 1) * page_size).limit(page_size).all()
    if not orders:
        return [], total

    order_ids = [o.id for o in orders]
    customer_names = dict(
        db.query(DomesticCustomer.id, DomesticCustomer.shop_name)
        .filter(DomesticCustomer.id.in_({o.customer_id for o in orders}))
        .all()
    )

    # 明细聚合与进度聚合各一条批量 SQL，避免逐单查询
    item_rows = (
        db.query(
            DomesticOrderItem.id,
            DomesticOrderItem.order_id,
            DomesticOrderItem.order_qty,
            DomesticOrderItem.unit_price,
            DomesticOrderItem.route_id,
        )
        .filter(DomesticOrderItem.order_id.in_(order_ids))
        .all()
    )
    passage_aggregates = _passage_progress_aggregates(db, item_rows)

    agg: dict[int, dict] = {
        oid: {"item_count": 0, "total_qty": 0, "done": 0, "capacity": 0}
        for oid in order_ids
    }
    for row in item_rows:
        bucket = agg[row.order_id]
        bucket["item_count"] += 1
        bucket["total_qty"] += row.order_qty
        bucket["done"] += passage_aggregates.get(row.id, {}).get("done", 0)
        bucket["capacity"] += passage_aggregates.get(row.id, {}).get("capacity", 0)

    items = []
    for o in orders:
        bucket = agg[o.id]
        capacity = bucket["capacity"]
        row = {
            "id": o.id,
            "domestic_no": o.domestic_no,
            "order_no": o.order_no,
            "order_date": o.order_date,
            "customer_id": o.customer_id,
            "customer_name": customer_names.get(o.customer_id),
            "order_type": o.order_type,
            "order_type_label": C.ORDER_TYPES.get(o.order_type, o.order_type),
            "status": o.status,
            "status_label": C.ORDER_STATUS_LABELS.get(o.status, str(o.status)),
            "item_count": bucket["item_count"],
            "total_qty": bucket["total_qty"],
            "total_amount": float(o.total_amount or 0),
            # 进度 = 已完成工序数量 / (数量 × 工序数)，未展开工序的明细计 0
            "progress_pct": round(bucket["done"] / capacity * 100, 1) if capacity else 0.0,
            "remark": o.remark,
            "created_at": o.created_at,
        }
        if include_finance:
            row["charged_amount"] = float(o.charged_amount or 0)
        items.append(row)
    return items, total


def lookup_order(db: Session, code: str, *, include_finance: bool = True) -> dict:
    """订单速查：一个输入框吃三种东西 —— 扫来的二维码、系统单号、客户订单号。

    让系统去认，而不是让车间先选"我要按哪个查"。同一个客户订单号可能对应多张单
    （客户自己的编号不保证唯一），这时返回最近的一张。
    """
    from app.domestic import report_service   # 延迟导入避免与 report_service 循环

    code = (code or "").strip()
    if not code:
        raise ValueError("请输入订单号或扫描流转卡")

    # 1) 扫来的逐件码：验签后经单件定位到订单
    if code.upper().startswith(C.UNIT_QR_PREFIX):
        valid, unit_id = report_service.verify_unit_qr_data(code)
        if not valid:
            raise ValueError("二维码无效，请扫内贸单件标签")
        from app.domestic.models import DomesticItemUnit

        unit = db.query(DomesticItemUnit).get(unit_id)
        item = db.query(DomesticOrderItem).get(unit.item_id) if unit and unit.status == 1 else None
        if not item:
            raise ValueError("找不到这张单件标签对应的订单明细")
        return get_order_detail(db, item.order_id, include_finance=include_finance)

    # 2) 扫来的内贸流转卡：验签后直接定位到它所属的订单
    if code.upper().startswith(C.QR_PREFIX):
        valid, item_id = report_service.verify_qr_data(code)
        if not valid:
            raise ValueError("二维码无效，请扫内贸流转卡")
        item = db.query(DomesticOrderItem).get(item_id)
        if not item:
            raise ValueError("找不到这张卡对应的订单明细")
        return get_order_detail(db, item.order_id, include_finance=include_finance)

    # 3) 系统单号或客户订单号（都按精确匹配，模糊搜索走列表页）
    order = (
        db.query(DomesticOrder)
        .filter(
            DomesticOrder.deleted_flag == 0,
            (DomesticOrder.domestic_no == code) | (DomesticOrder.order_no == code),
        )
        .order_by(DomesticOrder.id.desc())
        .first()
    )
    if not order:
        raise ValueError(f"没找到订单「{code}」，请核对单号")
    return get_order_detail(db, order.id, include_finance=include_finance)


def get_order_detail(
    db: Session,
    order_id: int,
    *,
    public_progress_only: bool = False,
    include_finance: bool = True,
) -> dict:
    order = db.query(DomesticOrder).filter(
        DomesticOrder.id == order_id, DomesticOrder.deleted_flag == 0
    ).first()
    if not order:
        raise ValueError("订单不存在")

    customer = db.query(DomesticCustomer).get(order.customer_id)
    items = (
        db.query(DomesticOrderItem)
        .filter(DomesticOrderItem.order_id == order_id)
        .order_by(DomesticOrderItem.id.asc())
        .all()
    )

    item_views = []
    for item in items:
        unit_service.ensure_item_line_no(db, item)
        full_steps = progress_service.build_progress_view(db, item)
        visible_steps = [step for step in full_steps if step["show_in_domestic_track"]]
        progress_steps = visible_steps if public_progress_only else full_steps
        done = sum(step["passed_qty"] for step in progress_steps)
        steps = (
            [_public_progress_step(step) for step in visible_steps]
            if public_progress_only else full_steps
        )
        capacity = item.order_qty * len(steps)
        current = next((
            step["process_name"]
            for step in steps
            if step["passed_qty"] < item.order_qty
        ), "完成")
        progress_hidden = public_progress_only and bool(full_steps) and not steps
        item_views.append({
            "id": item.id,
            "line_no": item.line_no,
            "line_code": f"A{item.line_no or 1}",
            "product_id": item.product_id,
            "product_name": item.product_name,
            "attrs": item.attrs_snapshot or {},
            "route_id": item.route_id,
            "order_qty": item.order_qty,
            "unit_price": float(item.unit_price or 0),
            "line_amount": float(balance_service.money(item.unit_price) * item.order_qty),
            "status": item.status,
            "status_label": C.ITEM_STATUS_LABELS.get(item.status, str(item.status)),
            "current_process": (
                current if steps else ("工序进度暂不展示" if progress_hidden else "未配工艺路线")
            ),
            "progress_hidden": progress_hidden,
            "progress_pct": round(done / capacity * 100, 1) if capacity else 0.0,
            "steps": steps,
            "hairstyle": item.hairstyle,
            "hairstyle_images": item.hairstyle_images or [],
            "color": item.color,
            "color_images": item.color_images or [],
            "style_requirement": item.style_requirement,
            "style_images": item.style_images or [],
            "remark": item.remark,
            "remark_images": item.remark_images or [],
            "ship_time": item.ship_time,
            "ship_weight": float(item.ship_weight) if item.ship_weight is not None else None,
        })

    detail = {
        "id": order.id,
        "domestic_no": order.domestic_no,
        "order_no": order.order_no,
        "order_date": order.order_date,
        "customer_id": order.customer_id,
        "customer_name": customer.shop_name if customer else None,
        "customer_custom_code": customer.custom_code if customer else None,
        "customer_membership_level": customer.membership_level if customer else None,
        "customer_province": customer.province if customer else None,
        "customer_city": customer.city if customer else None,
        "customer_contact": customer.contact if customer else None,
        "customer_phone": customer.phone if customer else None,
        "customer_address": customer.address if customer else None,
        "order_type": order.order_type,
        "order_type_label": C.ORDER_TYPES.get(order.order_type, order.order_type),
        "status": order.status,
        "status_label": C.ORDER_STATUS_LABELS.get(order.status, str(order.status)),
        "total_amount": float(order.total_amount or 0),
        "remark": order.remark,
        "created_at": order.created_at,
        "items": item_views,
    }
    # 实际扣款和客户余额属于内部财务数据；免登录进度页、普通绑定小程序
    # 都不返回。主站 RBAC 详情才包含这两个字段。
    if include_finance:
        detail["created_by_name"] = db.query(ArkUser.real_name).filter(
            ArkUser.id == order.created_by
        ).scalar()
        detail["charged_amount"] = float(order.charged_amount or 0)
        detail["customer_balance"] = float(customer.balance or 0) if customer else None
    return detail


# ── 编辑 ──────────────────────────────────────────────


def _get_order_or_raise(db: Session, order_id: int, lock: bool = False) -> DomesticOrder:
    q = db.query(DomesticOrder).filter(
        DomesticOrder.id == order_id, DomesticOrder.deleted_flag == 0
    )
    if lock:
        q = q.populate_existing().with_for_update()
    order = q.first()
    if not order:
        raise ValueError("订单不存在")
    return order


def _get_item_or_raise(db: Session, item_id: int, lock: bool = False) -> DomesticOrderItem:
    """lock=True 与报工走同一把明细行锁，防止改量/发货与报工并发时读到旧数量。"""
    q = db.query(DomesticOrderItem).filter(DomesticOrderItem.id == item_id)
    if lock:
        q = q.populate_existing().with_for_update()
    item = q.first()
    if not item:
        raise ValueError("订单明细不存在")
    return item


def update_order(db: Session, order_id: int, payload: OrderUpdate) -> DomesticOrder:
    order = _get_order_or_raise(db, order_id, lock=True)
    if order.status == C.ORDER_TERMINATED:
        raise ValueError("已终止的订单不能编辑")
    data = payload.model_dump(exclude_unset=True)
    if "customer_id" in data:
        if not data["customer_id"]:
            raise ValueError("订单必须有客户")
        if not db.query(DomesticCustomer).get(data["customer_id"]):
            raise ValueError("客户不存在")
        if order.status != C.ORDER_DRAFT and data["customer_id"] != order.customer_id:
            raise ValueError("已提交订单不能更换客户；请终止后重新下单")
    for field, value in data.items():
        setattr(order, field, value)
    db.commit()
    return order


def add_item(
    db: Session,
    order_id: int,
    payload: OrderItemAppend,
    user_id: int | None = None,
) -> dict:
    try:
        order = _get_order_or_raise(db, order_id, lock=True)
        if order.status in (C.ORDER_TERMINATED, C.ORDER_SHIPPED):
            raise ValueError("已终止/已发货的订单不能加明细")
        request_hash = _item_append_request_hash(payload)
        existing = db.query(DomesticItemAppendRequest).filter(
            DomesticItemAppendRequest.order_id == order.id,
            DomesticItemAppendRequest.request_id == payload.request_id,
        ).populate_existing().with_for_update().first()
        if existing:
            if existing.request_hash != request_hash:
                raise ValueError("该追加请求号已用于不同明细内容，请刷新后重新操作")
            if existing.item_id is None:
                raise ValueError("该请求创建的明细已删除，不能用原请求号再次追加")
            return {"id": existing.item_id, "warning": None, "replayed": True}

        if int(order.item_count or 0) >= C.MAX_ORDER_ITEMS:
            raise ValueError(f"单张订单最多允许 {C.MAX_ORDER_ITEMS} 行明细")
        new_total_qty = int(order.total_unit_qty or 0) + payload.order_qty
        if new_total_qty > C.MAX_ORDER_UNITS:
            raise ValueError(f"单张订单合计数量不能超过 {C.MAX_ORDER_UNITS} 件")

        line_no = order.next_line_no or 1
        item, warning = _build_item(db, order.id, line_no, payload)
        order.next_line_no = line_no + 1
        order.item_count = int(order.item_count or 0) + 1
        order.total_unit_qty = new_total_qty
        db.add(DomesticItemAppendRequest(
            order_id=order.id,
            item_id=item.id,
            request_id=payload.request_id,
            request_hash=request_hash,
        ))
        progress_service.sync_order_status(db, order.id)
        balance_service.sync_order_finance(
            db, order, user_id=user_id or order.created_by,
            reason=f"订单 {order.domestic_no} 新增明细差额",
        )
        db.commit()
        return {"id": item.id, "warning": warning, "replayed": False}
    except Exception:
        db.rollback()
        raise


def update_item(
    db: Session,
    item_id: int,
    payload: OrderItemUpdate,
    user_id: int | None = None,
) -> DomesticOrderItem:
    """改明细。数量不能改到低于任一工序已完成的数量 —— 那会让守恒关系失真。"""
    item = _get_item_or_raise(db, item_id, lock=True)
    order = _get_order_or_raise(db, item.order_id, lock=True)
    if order.status in (C.ORDER_TERMINATED, C.ORDER_SHIPPED):
        raise ValueError("已终止/已发货的订单不能修改明细")
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("已发货的明细不能编辑")

    data = payload.model_dump(exclude_unset=True)
    new_qty = data.get("order_qty")
    if new_qty is not None and new_qty != item.order_qty:
        new_total_qty = int(order.total_unit_qty or 0) - item.order_qty + new_qty
        if new_total_qty > C.MAX_ORDER_UNITS:
            raise ValueError(f"单张订单合计数量不能超过 {C.MAX_ORDER_UNITS} 件")
        # 锁定读整组进度行再取最大值：聚合函数配 FOR UPDATE 各库行为不一，
        # 拿到行本身再在内存里比更稳，也顺带锁住了并发报工
        rows = (
            db.query(DomesticItemProgress)
            .filter(DomesticItemProgress.item_id == item.id)
            .with_for_update()
            .all()
        )
        max_done = max((r.completed_qty for r in rows), default=0)
        if new_qty < max_done:
            raise ValueError(f"已有工序完成 {max_done} 件，数量不能改到小于它")
        unit_service.sync_item_units(db, item, new_qty)
        item.order_qty = new_qty
        order.total_unit_qty = new_total_qty
        for row in rows:
            progress_service.sync_progress_row_status(row, new_qty)

    for field in _TEXT_FIELDS:
        if field in data:
            setattr(item, field, data[field])
    if "unit_price" in data and data["unit_price"] is not None:
        item.unit_price = balance_service.money(data["unit_price"])
    for field in _IMAGE_FIELDS:
        if field in data and data[field] is not None:
            setattr(item, field, data[field])

    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    try:
        balance_service.sync_order_finance(
            db, order, user_id=user_id or order.created_by,
            reason=f"订单 {order.domestic_no} 修改明细差额",
        )
        db.commit()
        return item
    except Exception:
        db.rollback()
        raise


def delete_item(db: Session, item_id: int, user_id: int | None = None) -> None:
    """有报工记录的明细不能删 —— 删了车间的工时就凭空消失了。"""
    item = _get_item_or_raise(db, item_id, lock=True)
    reported = db.query(func.count(DomesticReportLog.id)).filter(
        DomesticReportLog.item_id == item_id
    ).scalar()
    if reported:
        raise ValueError(f"该明细已有 {reported} 条报工记录，不能删除；如需作废请终止订单")
    skipped = db.query(func.count(DomesticSkipLog.id)).filter(
        DomesticSkipLog.item_id == item_id
    ).scalar()
    if skipped:
        raise ValueError(f"该明细已有 {skipped} 条跳过记录，不能删除；如需作废请终止订单")
    order_id = item.order_id
    order = _get_order_or_raise(db, order_id, lock=True)
    if order.status in (C.ORDER_TERMINATED, C.ORDER_SHIPPED):
        raise ValueError("已终止/已发货的订单不能删除明细")
    remaining = db.query(func.count(DomesticOrderItem.id)).filter(
        DomesticOrderItem.order_id == order_id
    ).scalar()
    if remaining <= 1:
        raise ValueError("订单至少保留一行明细；如需作废请终止订单")
    order.item_count = max(0, int(order.item_count or 0) - 1)
    order.total_unit_qty = max(0, int(order.total_unit_qty or 0) - item.order_qty)
    # 主动清空幂等记录的 item_id，既不依赖测试库是否启用 FK pragma，也让
    # 重放在锁订单后只读幂等行，不再为“确认明细是否存在”反向锁回明细行。
    db.query(DomesticItemAppendRequest).filter(
        DomesticItemAppendRequest.item_id == item.id
    ).update({DomesticItemAppendRequest.item_id: None}, synchronize_session=False)
    db.delete(item)
    db.flush()
    progress_service.sync_order_status(db, order_id)
    try:
        balance_service.sync_order_finance(
            db, order, user_id=user_id or order.created_by,
            reason=f"订单 {order.domestic_no} 删除明细退款",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def attach_route(db: Session, item_id: int, route_id: int | None = None) -> dict:
    """给缺路线的在制明细补配工艺路线（漏配映射后的补救路径）。"""
    item = _get_item_or_raise(db, item_id, lock=True)
    order = _get_order_or_raise(db, item.order_id, lock=True)
    if order.status in (C.ORDER_TERMINATED, C.ORDER_SHIPPED):
        raise ValueError("已终止/已发货的订单不能重配工艺路线")
    if item.route_id is not None:
        reported = db.query(func.count(DomesticReportLog.id)).filter(
            DomesticReportLog.item_id == item.id
        ).scalar()
        if reported:
            raise ValueError(f"该明细已有 {reported} 条报工记录，不能重建工序进度")
        skipped = db.query(func.count(DomesticSkipLog.id)).filter(
            DomesticSkipLog.item_id == item.id
        ).scalar()
        if skipped:
            raise ValueError(f"该明细已有 {skipped} 条跳过记录，不能重建工序进度")
        raise ValueError("该明细已配置工艺路线，不能重复补配")
    rid = route_id
    if rid is None:
        product = db.query(DomesticProduct).get(item.product_id)
        rid = product.route_id if product else None
        if rid is None and product:
            rid = product_service.resolve_route_id(db, product.product_type, product.craft)
    if rid is None:
        raise ValueError("没有可用的工艺路线，请先在「工艺路线映射」里配好这个工艺")

    steps = progress_service.init_item_progress(db, item, route_id=rid)
    if not steps:
        raise ValueError("该工艺路线还没有配工序")
    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return {"item_id": item.id, "route_id": rid, "step_count": steps}


# ── 发货与终止 ────────────────────────────────────────


def submit_draft(db: Session, order_id: int, user_id: int) -> DomesticOrder:
    """Submit a saved draft and deduct its full amount exactly once."""
    try:
        order = _get_order_or_raise(db, order_id, lock=True)
        if order.status != C.ORDER_DRAFT:
            raise ValueError("只有草稿订单可以提交")
        order.status = C.ORDER_PRODUCING
        balance_service.sync_order_finance(
            db, order, user_id=user_id,
            reason=f"草稿订单 {order.domestic_no} 提交扣款",
        )
        db.commit()
        return order
    except Exception:
        db.rollback()
        raise


def ship_item(db: Session, item_id: int, payload: ItemShipRequest) -> DomesticOrderItem:
    """登记发货。首版要求全工序做齐才允许发货。"""
    item = _get_item_or_raise(db, item_id, lock=True)
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("该明细已发货")
    order = _get_order_or_raise(db, item.order_id, lock=True)
    if order.status == C.ORDER_TERMINATED:
        # 否则会出现「订单已终止但货已发出」的自相矛盾状态，且此后撤销被永久锁死
        raise ValueError("订单已终止，不能登记发货")
    progress_service.recalc_item_status(db, item)
    if item.status != C.ITEM_DONE:
        raise ValueError("该明细还没做完，不能登记发货")

    item.ship_time = payload.ship_time
    item.ship_weight = payload.ship_weight
    item.status = C.ITEM_SHIPPED
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return item


def terminate_order(
    db: Session,
    order_id: int,
    reason: str | None,
    user_id: int | None = None,
) -> DomesticOrder:
    try:
        order = _get_order_or_raise(db, order_id, lock=True)
        if order.status == C.ORDER_TERMINATED:
            raise ValueError("订单已终止")
        if order.status == C.ORDER_SHIPPED:
            raise ValueError("已发货的订单不能终止")
        order.status = C.ORDER_TERMINATED
        if reason:
            # remark 列宽 1000，拼接后截断——超长该是提示不是 500
            order.remark = f"{order.remark or ''}\n[终止] {reason}".strip()[:1000]
        balance_service.refund_order_charge(
            db, order, user_id=user_id or order.created_by,
            reason=f"订单 {order.domestic_no} 终止退款：{reason or '未填写原因'}",
        )
        db.commit()
        return order
    except Exception:
        db.rollback()
        raise


def delete_order(db: Session, order_id: int, user_id: int | None = None) -> None:
    """软删。已有报工记录的订单只能终止，不能删。"""
    order = _get_order_or_raise(db, order_id, lock=True)
    reported = (
        db.query(func.count(DomesticReportLog.id))
        .join(DomesticOrderItem, DomesticOrderItem.id == DomesticReportLog.item_id)
        .filter(DomesticOrderItem.order_id == order_id, DomesticReportLog.revoked == 0)
        .scalar()
    )
    if reported:
        raise ValueError(f"该订单已有 {reported} 条报工记录，不能删除；请改用「终止订单」")
    try:
        balance_service.refund_order_charge(
            db, order, user_id=user_id or order.created_by,
            reason=f"订单 {order.domestic_no} 删除退款",
        )
        order.deleted_flag = 1
        db.commit()
    except Exception:
        db.rollback()
        raise
