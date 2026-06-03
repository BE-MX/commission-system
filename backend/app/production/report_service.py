"""报工核心 service + 进度初始化/查询"""

import hmac
import hashlib
import re
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.production.models import (
    Process, ProcessRoute, ProcessRouteStep,
    ProductProcessRoute, OrderProductProcessProgress,
    UserProcessBinding,
)
from app.auth.models import ArkUser
from app.stock.models import ProductionOrderItem, ProductionOrder

settings = get_settings()


# ── 二维码签名 ────────────────────────────────────────────

def generate_qr_sign(order_product_id: int, secret: str) -> str:
    message = f"ARK-P:{order_product_id}"
    digest = hmac.new(key=secret.encode(), msg=message.encode(), digestmod=hashlib.sha256).hexdigest()
    return digest[:8]


def generate_qr_data(order_product_id: int) -> str:
    sign = generate_qr_sign(order_product_id, settings.QR_SIGN_SECRET)
    return f"ARK-P:{order_product_id}:{sign}"


def verify_qr_data(qr_data: str) -> tuple[bool, int]:
    """Returns (is_valid, order_product_id)"""
    match = re.match(r"^ARK-P:(\d+):([a-f0-9]{8})$", qr_data)
    if not match:
        return False, 0
    op_id = int(match.group(1))
    sign_received = match.group(2)
    sign_expected = generate_qr_sign(op_id, settings.QR_SIGN_SECRET)
    return hmac.compare_digest(sign_received, sign_expected), op_id


# ── 进度初始化 ────────────────────────────────────────────

def init_order_product_progress(db: Session, order_product_id: int, force: bool = False) -> dict:
    """初始化订单产品的工序进度"""
    item = db.query(ProductionOrderItem).get(order_product_id)
    if not item:
        raise LookupError("订单产品不存在")

    binding = db.query(ProductProcessRoute).filter(ProductProcessRoute.product_id == item.product_id).first()
    if not binding:
        raise ValueError("该产品未绑定工序路线，无法初始化进度")

    steps = (
        db.query(ProcessRouteStep)
        .filter(ProcessRouteStep.route_id == binding.route_id)
        .order_by(ProcessRouteStep.step_order)
        .all()
    )
    if not steps:
        raise ValueError("工序路线中没有配置任何工序")

    existing = db.query(OrderProductProcessProgress).filter(
        OrderProductProcessProgress.order_product_id == order_product_id
    ).first()

    if existing and not force:
        raise ValueError("进度记录已存在，请使用 force=true 重新初始化")

    if existing and force:
        db.query(OrderProductProcessProgress).filter(
            OrderProductProcessProgress.order_product_id == order_product_id,
            OrderProductProcessProgress.status == 0,
        ).delete()

    completed_orders = {
        p.step_order
        for p in db.query(OrderProductProcessProgress).filter(
            OrderProductProcessProgress.order_product_id == order_product_id,
            OrderProductProcessProgress.status == 1,
        ).all()
    }

    new_count = 0
    for step in steps:
        if step.step_order not in completed_orders:
            db.add(OrderProductProcessProgress(
                order_product_id=order_product_id,
                process_id=step.process_id,
                route_id=binding.route_id,
                step_order=step.step_order,
                status=0,
            ))
            new_count += 1
    db.flush()

    route = db.query(ProcessRoute).get(binding.route_id)
    return {
        "order_product_id": order_product_id,
        "route_id": binding.route_id,
        "route_name": route.name if route else "",
        "initialized_steps": new_count,
        "message": f"工序进度已初始化，共 {new_count} 个工序",
    }


# ── 进度查询 ──────────────────────────────────────────────

def get_order_product_progress(db: Session, order_product_id: int) -> dict:
    """获取订单产品工序进度"""
    progresses = (
        db.query(OrderProductProcessProgress)
        .filter(OrderProductProcessProgress.order_product_id == order_product_id)
        .order_by(OrderProductProcessProgress.step_order.asc())
        .all()
    )
    if not progresses:
        raise LookupError("该订单产品无进度记录")

    route_id = progresses[0].route_id
    route = db.query(ProcessRoute).get(route_id)

    steps = []
    completed_count = 0
    for p in progresses:
        proc = db.query(Process).get(p.process_id)
        user_name = None
        if p.completed_by_user_id:
            user = db.query(ArkUser).get(p.completed_by_user_id)
            user_name = user.real_name if user else None
        if p.status == 1:
            completed_count += 1
        steps.append({
            "id": p.id,
            "step_order": p.step_order,
            "process_id": p.process_id,
            "process_name": proc.name if proc else "未知",
            "status": p.status,
            "completed_at": p.completed_at,
            "completed_by_user_id": p.completed_by_user_id,
            "completed_by_user_name": user_name,
            "completed_by_wx_id": p.completed_by_wx_id,
        })

    total = len(steps)
    all_completed = completed_count == total
    return {
        "order_product_id": order_product_id,
        "route_id": route_id,
        "route_name": route.name if route else "",
        "total_steps": total,
        "completed_steps": completed_count,
        "completion_rate": round(completed_count / total * 100, 1) if total else 0,
        "all_completed": all_completed,
        "steps": steps,
    }


# ── 核心报工 ──────────────────────────────────────────────

def handle_production_report(db: Session, qr_data: str, wx_id: str) -> dict:
    """核心报工逻辑，返回 {success, message, data}"""

    # Step 1: 解析并校验二维码
    is_valid, order_product_id = verify_qr_data(qr_data)
    if not is_valid:
        return {"success": False, "message": "无效的二维码，请确认扫描的是工艺流转卡上的二维码"}

    # Step 2: 查询订单产品
    item = db.query(ProductionOrderItem).get(order_product_id)
    if not item:
        return {"success": False, "message": "订单产品不存在，请联系管理员"}

    # 检查订单维度是否已完工（通过 order status 判断）
    order = db.query(ProductionOrder).get(item.order_id)
    if item.status == 2:
        return {"success": False, "message": "该产品所有工序已完成，无需再次报工"}

    # Step 3: 通过微信ID匹配用户
    user = db.query(ArkUser).filter(ArkUser.wx_id == wx_id).first()
    if not user:
        return {"success": False, "message": "您的微信账号尚未绑定方舟系统，请联系车间管理员完成绑定"}

    # Step 4: 获取用户绑定的工序ID列表
    bound_process_ids = {
        b.process_id
        for b in db.query(UserProcessBinding).filter(UserProcessBinding.user_id == user.id).all()
    }
    if not bound_process_ids:
        return {"success": False, "message": "您的账号未绑定任何工序，请联系管理员配置工序权限"}

    # Step 5: 获取最小序号的未完成工序（如果进度不存在则自动初始化）
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
        # 进度记录不存在，尝试自动初始化
        try:
            init_result = init_order_product_progress(db, order_product_id)
            db.flush()
            # 重新查询待完成工序
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
        return {"success": False, "message": "该产品所有工序已完成"}

    # Step 6: 判断工序权限
    current_process = db.query(Process).get(pending.process_id)
    if pending.process_id not in bound_process_ids:
        return {
            "success": False,
            "message": f"当前待完成工序为「{current_process.name}」，您未被分配该工序，请联系负责「{current_process.name}」工序的同事扫码",
            "data": {"current_pending_process": current_process.name, "order_product_id": order_product_id},
        }

    # Step 7: 更新进度
    pending.status = 1
    pending.completed_at = datetime.utcnow()
    pending.completed_by_user_id = user.id
    pending.completed_by_wx_id = wx_id
    db.flush()

    # Step 8: 检查是否全部完成
    remaining = (
        db.query(func.count())
        .filter(
            OrderProductProcessProgress.order_product_id == order_product_id,
            OrderProductProcessProgress.status == 0,
        )
        .scalar()
    )
    total = (
        db.query(func.count())
        .filter(OrderProductProcessProgress.order_product_id == order_product_id)
        .scalar()
    )
    all_completed = remaining == 0

    if all_completed:
        item.status = 2  # 已完成
        item.updated_at = datetime.utcnow()
        # 检查是否所有明细都完成，同步订单状态
        _sync_order_status(db, item.order_id)

    db.flush()

    # Step 9: 返回
    if all_completed:
        msg = "所有工序均已完成！🎉"
    else:
        msg = f"「{current_process.name}」工序已记录完成 ✓"

    return {
        "success": True,
        "message": msg,
        "data": {
            "order_product_id": order_product_id,
            "process_id": current_process.id,
            "process_name": current_process.name,
            "step_order": pending.step_order,
            "completed_at": pending.completed_at.isoformat(),
            "remaining_steps": remaining,
            "total_steps": total,
            "all_completed": all_completed,
        },
    }


def _sync_order_status(db: Session, order_id: int) -> None:
    """如果所有明细都是同一完成状态，同步到订单"""
    items = db.query(ProductionOrderItem).filter(
        ProductionOrderItem.order_id == order_id,
    ).all()
    if not items:
        return
    statuses = {i.status for i in items}
    order = db.query(ProductionOrder).get(order_id)
    if not order:
        return
    if statuses == {2}:
        order.status = 2
    elif statuses == {1}:
        order.status = 1


# ── 二维码 / 打印卡数据 ─────────────────────────────────

def get_qrcode(db: Session, order_product_id: int, size: int = 200, box_size: int = 10) -> dict:
    """生成二维码 base64"""
    import qrcode
    from io import BytesIO
    import base64

    qr_data = generate_qr_data(order_product_id)
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "order_product_id": order_product_id,
        "qr_data": qr_data,
        "qr_code": f"data:image/png;base64,{b64}",
    }


def get_print_card_data(db: Session, order_product_id: int) -> dict:
    """获取打印卡片完整数据"""
    item = db.query(ProductionOrderItem).get(order_product_id)
    if not item:
        raise LookupError("订单产品不存在")

    order = db.query(ProductionOrder).get(item.order_id)

    # 查询产品路线绑定
    binding = db.query(ProductProcessRoute).filter(ProductProcessRoute.product_id == item.product_id).first()

    process_steps = []
    if binding:
        from app.production.route_service import get_route_steps
        route_steps = get_route_steps(db, binding.route_id)
        process_steps = [{"step_order": s["step_order"], "process_name": s["process_name"]} for s in route_steps]

    # 生成二维码
    qr_data = get_qrcode(db, order_product_id)

    return {
        "order_product_id": order_product_id,
        "order_no": order.order_no if order else "",
        "product_name": item.product_name,
        "model": item.model,
        "spec_info": item.spec_info,
        "order_qty": item.order_qty,
        "expected_delivery_date": str(item.expected_delivery_date) if item.expected_delivery_date else None,
        "is_urgent": item.is_urgent,
        "remark": item.remark,
        "process_steps": process_steps,
        "qr_code_base64": qr_data["qr_code"],
        "printed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
    }
