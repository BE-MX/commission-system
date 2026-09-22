"""内贸客户资金申请：充值/调整先落申请单，审核通过才入账。

申请阶段只做校验与落库（不动余额）；审核通过时调用既有的
balance_service.recharge_customer / customer_service.adjust_customer 执行——
账本幂等键沿用 recharge:/adjust: 前缀口径，重复审批不会重复入账。
"""

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.domestic import balance_service, customer_service
from app.domestic import constants as C
from app.domestic.models import DomesticCustomer, DomesticCustomerRequest
from app.domestic.pricing_service import membership_label
from app.domestic.schemas import CustomerAdjust


def _validate_request_id(request_id: str | None, action: str) -> str:
    value = request_id.strip() if isinstance(request_id, str) else ""
    if not value:
        raise ValueError(f"{action}幂等键不能为空")
    if not 8 <= len(value) <= 64:
        raise ValueError(f"{action}幂等键长度必须为 8 到 64 个字符")
    return value


def _lock_customer(db: Session, customer_id: int, user_id: int, can_operate_all: bool) -> DomesticCustomer:
    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id,
    ).populate_existing().with_for_update().first()
    if not customer or (not can_operate_all and customer.owner_user_id != user_id):
        raise ValueError("客户不存在")
    return customer


def _replay_check(existing: DomesticCustomerRequest, *, customer_id: int, request_type: str,
                  amount: Decimal, change_membership: bool, membership_level: str | None) -> dict:
    """同一 request_id 重复提交：同人同客户同内容返回原申请（replayed），不一致报错。"""
    same = (
        existing.customer_id == customer_id
        and existing.request_type == request_type
        and balance_service.money(existing.amount) == balance_service.money(amount)
        and bool(existing.change_membership) == change_membership
        and (existing.membership_level if change_membership else None) == membership_level
    )
    if not same:
        raise ValueError("该请求号已用于不同申请内容，请刷新后重试")
    return _request_view(existing, replayed=True)


def _add_request_commit_or_replay(db: Session, req: DomesticCustomerRequest,
                                  *, replay_kwargs: dict) -> dict:
    """提交申请行；并发下同 request_id 撞唯一键时回退为幂等重放校验。

    客户行锁只串行化同客户请求；跨客户同键并发仍可能撞 uq_dom_request_request_id，
    撞键后重查并走 _replay_check（内容不一致会被它拒绝）。
    """
    db.add(req)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(DomesticCustomerRequest).filter(
            DomesticCustomerRequest.request_id == req.request_id
        ).first()
        if existing is None:
            raise
        return _replay_check(existing, **replay_kwargs)
    return _request_view(req)


def create_recharge_request(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    voucher_path: str,
    user_id: int,
    remark: str | None = None,
    request_id: str | None = None,
    can_operate_all: bool = False,
) -> dict:
    """充值申请：必须附银行流水/转账截图；审核通过前余额不变。"""
    request_id = _validate_request_id(request_id, "充值")
    amount = balance_service.money(amount)
    if amount <= 0:
        raise ValueError("充值金额必须大于 0")
    if not voucher_path:
        raise ValueError("请上传银行流水或转账截图")
    # 客户行锁先串行化同客户请求，再在锁内查重：双击/弱网重试同键走幂等重放
    customer = _lock_customer(db, customer_id, user_id, can_operate_all)
    existing = db.query(DomesticCustomerRequest).filter(
        DomesticCustomerRequest.request_id == request_id
    ).first()
    if existing:
        return _replay_check(existing, customer_id=customer_id,
                             request_type=C.REQUEST_TYPE_RECHARGE,
                             amount=amount, change_membership=False, membership_level=None)
    req = DomesticCustomerRequest(
        customer_id=customer.id,
        request_type=C.REQUEST_TYPE_RECHARGE,
        amount=amount,
        change_membership=0,
        membership_level=None,
        voucher_path=voucher_path,
        remark=(remark or "").strip() or None,
        status=C.REQUEST_STATUS_PENDING,
        request_id=request_id,
        business_key=f"recharge:{customer.id}:{request_id}",
        created_by=user_id,
    )
    return _add_request_commit_or_replay(db, req, replay_kwargs={
        "customer_id": customer_id, "request_type": C.REQUEST_TYPE_RECHARGE,
        "amount": amount, "change_membership": False, "membership_level": None,
    })


def create_adjust_request(
    db: Session,
    customer_id: int,
    payload: CustomerAdjust,
    user_id: int,
    *,
    can_operate_all: bool = False,
) -> dict:
    """调整申请：余额增减与/或会员等级覆盖，审核通过才生效。"""
    request_id = _validate_request_id(payload.request_id, "调整")
    amount = balance_service.money(payload.amount)
    change_membership = "membership_level" in payload.model_fields_set
    if amount == 0 and not change_membership:
        raise ValueError("没有需要调整的内容：请填余额调整额或选择会员等级")
    customer = _lock_customer(db, customer_id, user_id, can_operate_all)
    existing = db.query(DomesticCustomerRequest).filter(
        DomesticCustomerRequest.request_id == request_id
    ).first()
    if existing:
        return _replay_check(existing, customer_id=customer_id,
                             request_type=C.REQUEST_TYPE_ADJUST,
                             amount=amount, change_membership=change_membership,
                             membership_level=payload.membership_level if change_membership else None)
    req = DomesticCustomerRequest(
        customer_id=customer.id,
        request_type=C.REQUEST_TYPE_ADJUST,
        amount=amount,
        change_membership=1 if change_membership else 0,
        membership_level=payload.membership_level if change_membership else None,
        voucher_path=None,
        remark=payload.remark,
        status=C.REQUEST_STATUS_PENDING,
        request_id=request_id,
        business_key=f"adjust:{customer.id}:{request_id}",
        created_by=user_id,
    )
    return _add_request_commit_or_replay(db, req, replay_kwargs={
        "customer_id": customer_id, "request_type": C.REQUEST_TYPE_ADJUST,
        "amount": amount, "change_membership": change_membership,
        "membership_level": payload.membership_level if change_membership else None,
    })


def _request_view(req: DomesticCustomerRequest, *, replayed: bool = False) -> dict:
    return {
        "id": req.id,
        "customer_id": req.customer_id,
        "request_type": req.request_type,
        "amount": float(req.amount),
        "change_membership": bool(req.change_membership),
        "membership_level": req.membership_level if req.change_membership else None,
        "membership_label": (
            membership_label(req.membership_level) if req.change_membership else None
        ),
        "has_voucher": bool(req.voucher_path),
        "remark": req.remark,
        "status": req.status,
        "created_by": req.created_by,
        "created_at": req.created_at,
        "reviewed_by": req.reviewed_by,
        "reviewed_at": req.reviewed_at,
        "review_remark": req.review_remark,
        "replayed": replayed,
    }


def pending_request_count(db: Session, *, viewer_user_id: int, can_review_all: bool) -> int:
    query = db.query(DomesticCustomerRequest).filter(
        DomesticCustomerRequest.status == C.REQUEST_STATUS_PENDING,
    )
    if not can_review_all:
        query = query.filter(DomesticCustomerRequest.created_by == viewer_user_id)
    return query.count()


def list_requests(
    db: Session,
    *,
    status: str = "",
    request_type: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    viewer_user_id: int,
    can_review_all: bool,
) -> tuple[list[dict], int]:
    q = db.query(DomesticCustomerRequest)
    if status:
        q = q.filter(DomesticCustomerRequest.status == status)
    if request_type:
        q = q.filter(DomesticCustomerRequest.request_type == request_type)
    if keyword:
        q = q.join(DomesticCustomer, DomesticCustomer.id == DomesticCustomerRequest.customer_id).filter(
            DomesticCustomer.shop_name.contains(keyword)
        )
    if not can_review_all:
        q = q.filter(DomesticCustomerRequest.created_by == viewer_user_id)
    total = q.count()
    rows = q.order_by(
        DomesticCustomerRequest.created_at.desc(), DomesticCustomerRequest.id.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    customer_names = dict(db.query(DomesticCustomer.id, DomesticCustomer.shop_name).filter(
        DomesticCustomer.id.in_({row.customer_id for row in rows} or {0})
    ).all())
    user_ids = {row.created_by for row in rows} | {row.reviewed_by for row in rows if row.reviewed_by}
    user_names = dict(db.query(ArkUser.id, ArkUser.real_name).filter(
        ArkUser.id.in_(user_ids or {0})
    ).all())
    items = []
    for row in rows:
        view = _request_view(row)
        view["customer_name"] = customer_names.get(row.customer_id)
        view["created_by_name"] = user_names.get(row.created_by)
        view["reviewed_by_name"] = user_names.get(row.reviewed_by)
        items.append(view)
    return items, total


def _lock_pending_request(db: Session, request_id: int) -> DomesticCustomerRequest:
    req = db.query(DomesticCustomerRequest).filter(
        DomesticCustomerRequest.id == request_id
    ).populate_existing().with_for_update().first()
    if req is None:
        raise ValueError("申请不存在")
    if req.status != C.REQUEST_STATUS_PENDING:
        raise ValueError("该申请已审核过，请刷新查看最新状态")
    return req


def _ensure_reviewer(req: DomesticCustomerRequest, reviewer_id: int, can_admin: bool) -> None:
    # 审自己不成立；domestic:admin / super_admin 兜底（如只有一人在岗）
    if req.created_by == reviewer_id and not can_admin:
        raise ValueError("不能审核自己提交的申请")


def approve_request(
    db: Session,
    request_id: int,
    *,
    reviewer_id: int,
    can_admin: bool,
    remark: str | None = None,
) -> dict:
    """审核通过并立即入账：申请行锁 + 执行（commit=False）+ 状态写库一次提交。

    行锁贯穿到最终 commit，两个审核员并发审批同一张申请只会串行：
    后到者看到状态已变直接报错，不会出现「钱已入账但申请被驳回」的交错。
    账本侧另有 recharge:/adjust: 幂等键兜底，重复执行不重复入账。
    """
    req = _lock_pending_request(db, request_id)
    _ensure_reviewer(req, reviewer_id, can_admin)
    if req.request_type == C.REQUEST_TYPE_RECHARGE:
        result = balance_service.recharge_customer(
            db,
            customer_id=req.customer_id,
            amount=req.amount,
            user_id=req.created_by,
            remark=req.remark,
            request_id=req.request_id,
            can_operate_all=True,
            commit=False,
        )
    else:
        payload_kwargs = {
            "amount": req.amount,
            "remark": req.remark or "审核通过的调整",
            "request_id": req.request_id,
        }
        if req.change_membership:
            payload_kwargs["membership_level"] = req.membership_level
        result = customer_service.adjust_customer(
            db, req.customer_id, CustomerAdjust(**payload_kwargs), req.created_by,
            can_operate_all=True, commit=False,
        )
    req.status = C.REQUEST_STATUS_APPROVED
    req.reviewed_by = reviewer_id
    req.reviewed_at = beijing_now()
    req.review_remark = (remark or "").strip() or None
    db.commit()
    return {"request": _request_view(req), "result": result}


def reject_request(
    db: Session,
    request_id: int,
    *,
    reviewer_id: int,
    can_admin: bool,
    remark: str | None = None,
) -> dict:
    req = _lock_pending_request(db, request_id)
    _ensure_reviewer(req, reviewer_id, can_admin)
    remark = (remark or "").strip()
    if len(remark) < 2:
        raise ValueError("驳回必须填写原因（至少 2 个字）")
    req.status = C.REQUEST_STATUS_REJECTED
    req.reviewed_by = reviewer_id
    req.reviewed_at = beijing_now()
    req.review_remark = remark
    db.commit()
    return _request_view(req)
