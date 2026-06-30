"""微信小程序端 — 业务逻辑层"""

from datetime import datetime, timezone, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.production.models import (
    OrderProductProcessProgress,
    Process,
    UserProcessBinding,
)
from app.production.report_service import verify_qr_data, init_order_product_progress
from app.stock.models import ProductionOrderItem, ProductionOrder

_BJ_TZ = timezone(timedelta(hours=8))


def _bj_now():
    return datetime.now(_BJ_TZ)



def _build_product_display(db: Session, product_id: int) -> str:
    """从 okki_products 组装产品显示字符串，优先 color;size寸;unit;description，逐级 fallback"""
    settings = get_settings()
    biz = settings.BUSINESS_DB_NAME
    sql = text(f"""
        SELECT p.color, p.size, p.unit, p.description, p.product_remark, p.cn_name, p.name
        FROM `{biz}`.okki_products p
        WHERE p.product_id = :pid
        LIMIT 1
    """)
    row = db.execute(sql, {"pid": product_id}).mappings().first()
    print(f"[DEBUG] _build_product_display pid={product_id}, row={dict(row) if row else None}", flush=True)
    if not row:
        return ""
    parts = []
    if row["color"]:
        parts.append(str(row["color"]))
    if row["size"]:
        parts.append(f"{row['size']}寸")
    if row["unit"]:
        parts.append(str(row["unit"]))
    if row["description"]:
        parts.append(str(row["description"]))
    if parts:
        return ";".join(parts)
    if row["product_remark"]:
        return str(row["product_remark"])
    if row["cn_name"]:
        return str(row["cn_name"])
    if row["name"]:
        return str(row["name"])
    return ""


def _batch_product_displays(db: Session, product_ids: list[int]) -> dict[int, str]:
    """批量查询 okki_products 组装显示字符串，返回 {product_id: display_str}"""
    if not product_ids:
        return {}
    settings = get_settings()
    biz = settings.BUSINESS_DB_NAME
    placeholders = ",".join(str(int(pid)) for pid in set(product_ids))
    sql = text(f"""
        SELECT p.product_id, p.color, p.size, p.unit, p.description
        FROM `{biz}`.okki_products p
        WHERE p.product_id IN ({placeholders})
    """)
    rows = db.execute(sql).mappings().all()
    result = {}
    for row in rows:
        parts = []
        if row["color"]:
            parts.append(str(row["color"]))
        if row["size"]:
            parts.append(f"{row['size']}寸")
        if row["unit"]:
            parts.append(str(row["unit"]))
        if row["description"]:
            parts.append(str(row["description"]))
        result[row["product_id"]] = ";".join(parts)
    return result


# ── 认证 ──────────────────────────────────────────────────

def login_by_openid(db: Session, open_id: str) -> dict | None:
    """根据 openId 查找已绑定用户，返回 user dict 或 None"""
    user = db.query(ArkUser).filter(ArkUser.wx_id == open_id).first()
    if not user:
        return None
    return {"id": user.id, "name": user.real_name or user.username, "wx_id": user.wx_id}


def bind_user(db: Session, open_id: str, identifier: str) -> dict:
    """绑定微信 openId 与方舟用户，返回 {success, user, error}"""
    # 按手机号或工号查找
    user = db.query(ArkUser).filter(
        (ArkUser.phone == identifier) | (ArkUser.username == identifier)
    ).first()

    if not user:
        return {"success": False, "error": "USER_NOT_FOUND"}

    # 已绑定其他微信
    if user.wx_id and user.wx_id != open_id:
        return {"success": False, "error": "ALREADY_BOUND"}

    # openId 已绑定其他用户
    existing = db.query(ArkUser).filter(ArkUser.wx_id == open_id, ArkUser.id != user.id).first()
    if existing:
        return {"success": False, "error": "OPEN_ID_TAKEN"}

    # 执行绑定
    user.wx_id = open_id
    db.flush()

    return {"success": True, "user": {"id": user.id, "name": user.real_name or user.username, "wx_id": open_id}}


# ── 扫码 ──────────────────────────────────────────────────

def scan_product(db: Session, order_product_id: int, sign: str, current_user: ArkUser) -> dict:
    """扫码获取产品信息和工序状态"""
    from app.production.report_service import generate_qr_sign
    from app.core.config import get_settings
    settings = get_settings()

    # Step 1: 验证签名
    expected_sign = generate_qr_sign(order_product_id, settings.QR_SIGN_SECRET)
    import hmac as _hmac
    if not _hmac.compare_digest(sign, expected_sign):
        return {"can_submit": False, "block_reason": "SIGN_INVALID", "product": None, "next_process": None}

    # Step 2: 查订单产品
    item = db.query(ProductionOrderItem).get(order_product_id)
    if not item:
        return {"can_submit": False, "block_reason": "ORDER_PRODUCT_NOT_FOUND", "product": None, "next_process": None}

    # 查批次号
    order = db.query(ProductionOrder).get(item.order_id)
    batch_no = order.batch_no if order else None

    product_display = _build_product_display(db, item.product_id) or item.spec_info or item.product_name or ""

    product_info = {
        "id": item.id,
        "order_id": item.order_id,
        "order_no": batch_no,
        "product_name": item.product_name,
        "model": item.model,
        "product_display": product_display,
        "spec_info": item.spec_info,
        "order_qty": item.order_qty,
        "received_qty": item.received_qty,
        "is_urgent": item.is_urgent,
        "expected_delivery_date": str(item.expected_delivery_date) if item.expected_delivery_date else None,
    }

    # Step 3: 获取未完成工序
    pending = (
        db.query(OrderProductProcessProgress)
        .filter(
            OrderProductProcessProgress.order_product_id == order_product_id,
            OrderProductProcessProgress.status == 0,
        )
        .order_by(OrderProductProcessProgress.step_order.asc())
        .first()
    )

    if not pending:
        # 尝试自动初始化
        try:
            init_order_product_progress(db, order_product_id)
            db.flush()
            pending = (
                db.query(OrderProductProcessProgress)
                .filter(
                    OrderProductProcessProgress.order_product_id == order_product_id,
                    OrderProductProcessProgress.status == 0,
                )
                .order_by(OrderProductProcessProgress.step_order.asc())
                .first()
            )
        except (LookupError, ValueError):
            pass

    if not pending:
        # 所有工序已完成
        return {"can_submit": False, "block_reason": "PROCESS_ALREADY_DONE", "product": product_info, "next_process": None}

    # Step 4: 查工序名和总步数
    proc = db.query(Process).get(pending.process_id)
    total = db.query(func.count()).filter(
        OrderProductProcessProgress.order_product_id == order_product_id
    ).scalar()

    next_process_info = {
        "progress_id": pending.id,
        "process_name": proc.name if proc else "未知",
        "step_order": pending.step_order,
        "total_steps": total,
    }

    # Step 4.5: 查所有工序进度（供时间轴展示）
    all_progress_rows = (
        db.query(
            OrderProductProcessProgress.id,
            OrderProductProcessProgress.process_id,
            OrderProductProcessProgress.step_order,
            OrderProductProcessProgress.status,
            OrderProductProcessProgress.completed_at,
            OrderProductProcessProgress.completed_by_user_id,
            Process.name.label("process_name"),
        )
        .join(Process, OrderProductProcessProgress.process_id == Process.id)
        .filter(OrderProductProcessProgress.order_product_id == order_product_id)
        .order_by(OrderProductProcessProgress.step_order.asc())
        .all()
    )
    all_processes = []
    for r in all_progress_rows:
        item = {
            "process_name": r.process_name,
            "step_order": r.step_order,
            "status": r.status,  # 0=待完成, 1=已完成
        }
        if r.status == 1 and r.completed_at:
            item["completed_at"] = r.completed_at.strftime("%m-%d %H:%M")
        if r.status == 1 and r.completed_by_user_id:
            completer = db.query(ArkUser).get(r.completed_by_user_id)
            item["completed_by"] = completer.real_name or completer.username if completer else None
        all_processes.append(item)

    # Step 5: 检查用户工序绑定
    binding = db.query(UserProcessBinding).filter(
        UserProcessBinding.user_id == current_user.id,
        UserProcessBinding.process_id == pending.process_id,
    ).first()

    if not binding:
        return {"can_submit": False, "block_reason": "NOT_ASSIGNED", "product": product_info, "next_process": next_process_info, "all_processes": all_processes}

    # 可以提交
    return {"can_submit": True, "block_reason": None, "product": product_info, "next_process": next_process_info, "all_processes": all_processes}


def submit_report(db: Session, progress_id: int, order_product_id: int, current_user: ArkUser) -> dict:
    """提交报工"""
    # Step 1: 幂等检查
    progress = db.query(OrderProductProcessProgress).get(progress_id)
    if not progress:
        return {"success": False, "message": "工序进度记录不存在"}

    if progress.status == 1:
        # 已完成 — 幂等返回
        proc = db.query(Process).get(progress.process_id)
        return {"success": True, "message": f"「{proc.name if proc else '未知'}」工序已完成", "all_done": False}

    # Step 2: 安全校验
    if progress.order_product_id != order_product_id:
        return {"success": False, "message": "参数不匹配"}

    # Step 3: 权限校验
    binding = db.query(UserProcessBinding).filter(
        UserProcessBinding.user_id == current_user.id,
        UserProcessBinding.process_id == progress.process_id,
    ).first()
    if not binding:
        return {"success": False, "message": "您未被分配此工序"}

    # Step 4: 检查是否是当前应完成的工序
    earliest_pending = (
        db.query(OrderProductProcessProgress)
        .filter(
            OrderProductProcessProgress.order_product_id == order_product_id,
            OrderProductProcessProgress.status == 0,
        )
        .order_by(OrderProductProcessProgress.step_order.asc())
        .first()
    )
    if earliest_pending and earliest_pending.id != progress_id:
        proc = db.query(Process).get(earliest_pending.process_id)
        return {
            "success": False,
            "message": f"当前应完成的是「{proc.name if proc else '未知'}」，请先完成上一道工序",
        }

    # Step 5: 执行报工
    progress.status = 1
    progress.completed_at = _bj_now()
    progress.completed_by_user_id = current_user.id
    progress.completed_by_wx_id = current_user.wx_id
    db.flush()

    # Step 6: 检查全部完成
    remaining = db.query(func.count()).filter(
        OrderProductProcessProgress.order_product_id == order_product_id,
        OrderProductProcessProgress.status == 0,
    ).scalar()

    all_done = remaining == 0
    current_proc = db.query(Process).get(progress.process_id)

    if all_done:
        item = db.query(ProductionOrderItem).get(order_product_id)
        if item:
            item.status = 2
            item.updated_at = _bj_now()
            from app.production.report_service import _sync_order_status
            _sync_order_status(db, item.order_id)

    # 查下一道工序名
    next_proc_name = None
    if not all_done:
        next_pending = (
            db.query(OrderProductProcessProgress)
            .filter(
                OrderProductProcessProgress.order_product_id == order_product_id,
                OrderProductProcessProgress.status == 0,
            )
            .order_by(OrderProductProcessProgress.step_order.asc())
            .first()
        )
        if next_pending:
            np = db.query(Process).get(next_pending.process_id)
            next_proc_name = np.name if np else None

    msg = f"「{current_proc.name if current_proc else '未知'}」工序报工成功"
    if all_done:
        msg += "，该产品所有工序已完成！"

    return {
        "success": True,
        "message": msg,
        "all_done": all_done,
        "next_process": next_proc_name,
    }


def get_today_history(db: Session, user_id: int) -> dict:
    """获取今日报工记录"""
    today_start = _bj_now().replace(hour=0, minute=0, second=0, microsecond=0)

    rows = (
        db.query(
            OrderProductProcessProgress.id.label("progress_id"),
            ProductionOrderItem.id.label("order_product_id"),
            ProductionOrderItem.product_id,
            ProductionOrderItem.product_name,
            ProductionOrderItem.model,
            ProductionOrderItem.order_qty,
            Process.name.label("process_name"),
            OrderProductProcessProgress.step_order,
            OrderProductProcessProgress.completed_at,
            ProductionOrder.batch_no,
        )
        .join(ProductionOrderItem, OrderProductProcessProgress.order_product_id == ProductionOrderItem.id)
        .join(Process, OrderProductProcessProgress.process_id == Process.id)
        .join(ProductionOrder, ProductionOrderItem.order_id == ProductionOrder.id)
        .filter(
            OrderProductProcessProgress.completed_by_user_id == user_id,
            OrderProductProcessProgress.completed_at >= today_start,
        )
        .order_by(OrderProductProcessProgress.completed_at.desc())
        .all()
    )

    product_ids = [r.product_id for r in rows]
    displays = _batch_product_displays(db, product_ids)

    records = []
    for r in rows:
        time_str = r.completed_at.strftime("%H:%M") if r.completed_at else ""
        records.append({
            "progress_id": r.progress_id,
            "order_product_id": r.order_product_id,
            "product_name": r.product_name,
            "model": r.model,
            "product_display": displays.get(r.product_id, ""),
            "order_qty": r.order_qty,
            "process_name": r.process_name,
            "step_order": r.step_order,
            "completed_at": time_str,
            "order_no": r.batch_no,
        })

    return {"today_count": len(records), "records": records}


def get_history(db: Session, user_id: int, page: int = 1, page_size: int = 20,
                date_start: str = None, date_end: str = None,
                keyword: str = None, order_no: str = None) -> dict:
    """分页获取报工历史，支持日期/型号/订单筛选"""
    query = (
        db.query(
            OrderProductProcessProgress.id.label("progress_id"),
            ProductionOrderItem.id.label("order_product_id"),
            ProductionOrderItem.product_id,
            ProductionOrderItem.product_name,
            ProductionOrderItem.model,
            ProductionOrderItem.order_qty,
            Process.name.label("process_name"),
            OrderProductProcessProgress.step_order,
            OrderProductProcessProgress.completed_at,
            ProductionOrder.batch_no.label("order_no"),
        )
        .join(ProductionOrderItem, OrderProductProcessProgress.order_product_id == ProductionOrderItem.id)
        .join(Process, OrderProductProcessProgress.process_id == Process.id)
        .join(ProductionOrder, ProductionOrderItem.order_id == ProductionOrder.id)
        .filter(OrderProductProcessProgress.completed_by_user_id == user_id)
    )

    # 日期范围
    if date_start:
        ds = datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=_BJ_TZ, hour=0, minute=0, second=0)
        query = query.filter(OrderProductProcessProgress.completed_at >= ds)
    if date_end:
        de = datetime.strptime(date_end, "%Y-%m-%d").replace(tzinfo=_BJ_TZ, hour=23, minute=59, second=59)
        query = query.filter(OrderProductProcessProgress.completed_at <= de)

    # 产品型号模糊搜索
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(ProductionOrderItem.model.ilike(kw))

    # 所属订单精确匹配
    if order_no:
        query = query.filter(ProductionOrder.batch_no == order_no)

    query = query.order_by(OrderProductProcessProgress.completed_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    product_ids = [r.product_id for r in rows]
    displays = _batch_product_displays(db, product_ids)

    records = []
    for r in rows:
        time_str = r.completed_at.strftime("%H:%M") if r.completed_at else ""
        date_str = r.completed_at.strftime("%Y-%m-%d") if r.completed_at else ""
        records.append({
            "progress_id": r.progress_id,
            "order_product_id": r.order_product_id,
            "product_name": r.product_name,
            "model": r.model,
            "product_display": displays.get(r.product_id, ""),
            "order_qty": r.order_qty,
            "process_name": r.process_name,
            "step_order": r.step_order,
            "completed_at": time_str,
            "completed_date": date_str,
            "order_no": r.order_no,
        })

    return {"total": total, "page": page, "page_size": page_size, "records": records}


def get_overview(db: Session, date_start: str = None, date_end: str = None) -> dict:
    """获取报工总览：按日期+工序分组，返回所有用户的报工记录（不限制当前用户）"""
    query = (
        db.query(
            OrderProductProcessProgress.id.label("progress_id"),
            ProductionOrderItem.id.label("order_product_id"),
            ProductionOrderItem.product_id,
            ProductionOrderItem.product_name,
            ProductionOrderItem.model,
            ProductionOrderItem.order_qty,
            Process.name.label("process_name"),
            Process.id.label("process_id"),
            OrderProductProcessProgress.step_order,
            OrderProductProcessProgress.completed_at,
            ProductionOrder.batch_no.label("order_no"),
            OrderProductProcessProgress.completed_by_user_id,
            ArkUser.real_name.label("completed_by_name"),
        )
        .join(ProductionOrderItem, OrderProductProcessProgress.order_product_id == ProductionOrderItem.id)
        .join(Process, OrderProductProcessProgress.process_id == Process.id)
        .join(ProductionOrder, ProductionOrderItem.order_id == ProductionOrder.id)
        .outerjoin(ArkUser, OrderProductProcessProgress.completed_by_user_id == ArkUser.id)
        .filter(
            OrderProductProcessProgress.status == 1,
            OrderProductProcessProgress.completed_at.isnot(None),
        )
    )

    if date_start:
        ds = datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=_BJ_TZ, hour=0, minute=0, second=0)
        query = query.filter(OrderProductProcessProgress.completed_at >= ds)
    if date_end:
        de = datetime.strptime(date_end, "%Y-%m-%d").replace(tzinfo=_BJ_TZ, hour=23, minute=59, second=59)
        query = query.filter(OrderProductProcessProgress.completed_at <= de)

    rows = query.order_by(OrderProductProcessProgress.completed_at.desc()).all()

    product_ids = [r.product_id for r in rows]
    displays = _batch_product_displays(db, product_ids)

    # 按 date 分组 → 按 process 分组
    date_map = {}  # key: "YYYY-MM-DD" → { process_id → { info, records } }
    for r in rows:
        date_key = r.completed_at.strftime("%Y-%m-%d") if r.completed_at else "unknown"
        if date_key not in date_map:
            date_map[date_key] = {}

        pid = r.process_id
        if pid not in date_map[date_key]:
            date_map[date_key][pid] = {
                "process_name": r.process_name,
                "process_id": pid,
                "total_qty": 0,
                "latest_time": "",
                "latest_time_raw": None,
                "records": [],
            }

        group = date_map[date_key][pid]
        group["total_qty"] += r.order_qty or 0

        time_str = r.completed_at.strftime("%H:%M") if r.completed_at else ""
        time_raw = r.completed_at

        # 更新最新时间
        if group["latest_time_raw"] is None or time_raw > group["latest_time_raw"]:
            group["latest_time_raw"] = time_raw
            group["latest_time"] = time_str

        group["records"].append({
            "progress_id": r.progress_id,
            "order_product_id": r.order_product_id,
            "product_name": r.product_name,
            "model": r.model,
            "product_display": displays.get(r.product_id, ""),
            "order_qty": r.order_qty,
            "process_name": r.process_name,
            "step_order": r.step_order,
            "completed_at": time_str,
            "completed_date": date_key,
            "order_no": r.order_no,
            "completed_by_name": r.completed_by_name or "未知",
        })

    # 组装结果：日期降序，同日内按 latest_time 降序
    result = []
    for date_key in sorted(date_map.keys(), reverse=True):
        groups = date_map[date_key]
        sorted_groups = sorted(groups.values(), key=lambda g: g["latest_time_raw"] or _bj_now(), reverse=True)
        result.append({
            "date": date_key,
            "groups": [
                {
                    "process_name": g["process_name"],
                    "process_id": g["process_id"],
                    "total_qty": g["total_qty"],
                    "latest_time": g["latest_time"],
                    "record_count": len(g["records"]),
                }
                for g in sorted_groups
            ],
        })

    return {"dates": result}


def get_overview_detail(db: Session, date: str, process_id: int) -> dict:
    """获取指定日期+工序的报工明细列表"""
    day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=_BJ_TZ, hour=0, minute=0, second=0)
    day_end = day_start.replace(hour=23, minute=59, second=59)

    rows = (
        db.query(
            OrderProductProcessProgress.id.label("progress_id"),
            ProductionOrderItem.id.label("order_product_id"),
            ProductionOrderItem.product_id,
            ProductionOrderItem.product_name,
            ProductionOrderItem.model,
            ProductionOrderItem.order_qty,
            Process.name.label("process_name"),
            OrderProductProcessProgress.step_order,
            OrderProductProcessProgress.completed_at,
            ProductionOrder.batch_no.label("order_no"),
            OrderProductProcessProgress.completed_by_user_id,
            ArkUser.real_name.label("completed_by_name"),
        )
        .join(ProductionOrderItem, OrderProductProcessProgress.order_product_id == ProductionOrderItem.id)
        .join(Process, OrderProductProcessProgress.process_id == Process.id)
        .join(ProductionOrder, ProductionOrderItem.order_id == ProductionOrder.id)
        .outerjoin(ArkUser, OrderProductProcessProgress.completed_by_user_id == ArkUser.id)
        .filter(
            OrderProductProcessProgress.process_id == process_id,
            OrderProductProcessProgress.status == 1,
            OrderProductProcessProgress.completed_at >= day_start,
            OrderProductProcessProgress.completed_at <= day_end,
        )
        .order_by(OrderProductProcessProgress.completed_at.desc())
        .all()
    )

    product_ids = [r.product_id for r in rows]
    displays = _batch_product_displays(db, product_ids)

    records = []
    for r in rows:
        time_str = r.completed_at.strftime("%H:%M") if r.completed_at else ""
        records.append({
            "progress_id": r.progress_id,
            "order_product_id": r.order_product_id,
            "product_name": r.product_name,
            "model": r.model,
            "product_display": displays.get(r.product_id, ""),
            "order_qty": r.order_qty,
            "process_name": r.process_name,
            "step_order": r.step_order,
            "completed_at": time_str,
            "completed_date": date,
            "order_no": r.order_no,
            "completed_by_name": r.completed_by_name or "未知",
        })

    return {"date": date, "process_id": process_id, "records": records}


def revoke_report(db: Session, progress_id: int, current_user: ArkUser) -> dict:
    """撤销报工：将已完成的工序恢复为待完成"""
    progress = db.query(OrderProductProcessProgress).get(progress_id)
    if not progress:
        return {"success": False, "message": "工序进度记录不存在"}

    if progress.status != 1:
        return {"success": False, "message": "该工序未完成，无需撤销"}

    # 只能撤销自己的报工
    if progress.completed_by_user_id != current_user.id:
        return {"success": False, "message": "只能撤销自己的报工记录"}

    # 检查：只能撤销最后一道已完成的工序（不能跳过中间工序撤销）
    later_done = (
        db.query(func.count())
        .filter(
            OrderProductProcessProgress.order_product_id == progress.order_product_id,
            OrderProductProcessProgress.step_order > progress.step_order,
            OrderProductProcessProgress.status == 1,
        )
        .scalar()
    )
    if later_done > 0:
        return {"success": False, "message": "已有后续工序完成，无法撤销此工序"}

    # 恢复工序状态
    progress.status = 0
    progress.completed_at = None
    progress.completed_by_user_id = None
    progress.completed_by_wx_id = None
    db.flush()

    # 如果明细之前因为全部完成改为 status=2，需要恢复为进行中
    item = db.query(ProductionOrderItem).get(progress.order_product_id)
    if item and item.status == 2:
        item.status = 0
        item.updated_at = _bj_now()
        from app.production.report_service import _sync_order_status
        _sync_order_status(db, item.order_id)

    proc = db.query(Process).get(progress.process_id)
    return {
        "success": True,
        "message": f"「{proc.name if proc else '未知'}」工序已撤销",
    }
