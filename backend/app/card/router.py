"""名片管家管理路由（/api/card/admin/...，card:read / card:write）。"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.card import service
from app.card.models import CardCustomer, CardEntry, CardInquiry, CardSalesperson
from app.card.schemas import (
    CustomerCreate,
    CustomerUpdate,
    EntryCreate,
    InquiryStatusUpdate,
    SalespersonUpsert,
)
from app.core.database import get_db
from app.core.response import ok

logger = logging.getLogger("commission.card")

router = APIRouter()

# /uploads 静态挂载指向 REPO_ROOT/uploads（bootstrap/static_files.py），与 expo 同锚点
REPO_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_ROOT = REPO_ROOT / "uploads" / "card"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_UPLOAD_MB = 10


# ---------- 业务员档案 ----------

@router.get("/admin/salespersons", summary="业务员档案列表")
def list_salespersons(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:read")),
):
    rows = db.query(CardSalesperson).order_by(CardSalesperson.id).all()
    return ok([
        {
            "id": r.id, "slug": r.slug, "name": r.name, "title": r.title,
            "email": r.email, "whatsapp": r.whatsapp, "intro": r.intro,
            "links_json": r.links_json, "is_active": r.is_active,
        }
        for r in rows
    ])


@router.post("/admin/salespersons", summary="新建/更新业务员档案（slug 幂等 upsert）")
def upsert_salesperson(
    payload: SalespersonUpsert,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:write")),
):
    # exclude_unset：未传字段不改——否则前端表单没带的 links_json 会被静默清空（审查 P2-1）
    data = payload.model_dump(exclude_unset=True)
    data.pop("slug", None)

    def _apply(target: CardSalesperson) -> None:
        for field in ("name", "title", "email", "whatsapp", "intro", "links_json", "is_active"):
            if field in data:
                setattr(target, field, data[field])

    row = db.query(CardSalesperson).filter(CardSalesperson.slug == payload.slug).first()
    if row is None:
        row = CardSalesperson(slug=payload.slug)
        db.add(row)
    _apply(row)
    try:
        db.commit()
    except IntegrityError:  # 并发 upsert 同 slug 撞唯一约束（审查 P3-1）：回滚后按已存在行重放
        db.rollback()
        logger.warning("card salesperson upsert race on slug=%s, retrying as update", payload.slug)
        print(f"[card] upsert race on slug={payload.slug}", flush=True)
        row = db.query(CardSalesperson).filter(CardSalesperson.slug == payload.slug).first()
        if row is None:
            raise
        _apply(row)
        db.commit()
    db.refresh(row)
    return ok({"id": row.id, "slug": row.slug})


# ---------- 客户档案 ----------

@router.get("/admin/customers", summary="客户档案列表")
def list_customers(
    salesperson_id: int | None = Query(None),
    keyword: str = Query("", max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:read")),
):
    q = db.query(CardCustomer)
    if salesperson_id:
        q = q.filter(CardCustomer.salesperson_id == salesperson_id)
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.filter(
            CardCustomer.display_name.like(kw)
            | CardCustomer.email_norm.like(kw)
            | CardCustomer.whatsapp_norm.like(kw)
        )
    total = q.count()
    rows = (
        q.order_by(CardCustomer.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    counts = dict(
        db.query(CardEntry.customer_id, func.count(CardEntry.id))
        .filter(CardEntry.customer_id.in_([r.id for r in rows] or [0]))
        .group_by(CardEntry.customer_id).all()
    )
    return ok({
        "total": total,
        "items": [service.customer_dict(r, counts.get(r.id, 0)) for r in rows],
    })


@router.post("/admin/customers", summary="新建客户档案（绑定口令）")
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("card:write")),
):
    sp = db.query(CardSalesperson).filter(CardSalesperson.id == payload.salesperson_id).first()
    if sp is None:
        raise HTTPException(404, "业务员不存在")
    customer = CardCustomer(
        salesperson_id=sp.id, display_name=payload.display_name.strip(),
        expo_code=payload.expo_code.strip(), remark=payload.remark,
        created_by=int(user.get("sub", 0)) or None,
    )
    try:
        service.apply_customer_contacts(customer, payload.email, payload.whatsapp)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not service.customer_has_passcode(customer):
        raise HTTPException(422, "邮箱和 WhatsApp 至少填一个——它就是客户的口令")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return ok({"id": customer.id})


@router.put("/admin/customers/{customer_id}", summary="更新客户档案")
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:write")),
):
    customer = db.query(CardCustomer).filter(CardCustomer.id == customer_id).first()
    if customer is None:
        raise HTTPException(404, "客户不存在")
    if payload.display_name is not None:
        customer.display_name = payload.display_name.strip()
    if payload.expo_code is not None:
        customer.expo_code = payload.expo_code.strip()
    if payload.remark is not None:
        customer.remark = payload.remark
    try:
        service.apply_customer_contacts(customer, payload.email, payload.whatsapp)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not service.customer_has_passcode(customer):
        raise HTTPException(422, "邮箱和 WhatsApp 至少留一个作口令")
    db.commit()
    return ok()


@router.delete("/admin/customers/{customer_id}", summary="删除客户档案（连带纪要）")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:write")),
):
    customer = db.query(CardCustomer).filter(CardCustomer.id == customer_id).first()
    if customer is None:
        raise HTTPException(404, "客户不存在")
    db.delete(customer)
    db.commit()
    return ok()


# ---------- 沟通纪要 ----------

@router.get("/admin/customers/{customer_id}/entries", summary="客户纪要列表")
def list_entries(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:read")),
):
    rows = (
        db.query(CardEntry).filter(CardEntry.customer_id == customer_id)
        .order_by(CardEntry.created_at, CardEntry.id).all()
    )
    return ok([service.entry_dict(r) for r in rows])


@router.post("/admin/customers/{customer_id}/entries", summary="新增纪要（文字/已传图片路径）")
def create_entry(
    customer_id: int,
    payload: EntryCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("card:write")),
):
    customer = db.query(CardCustomer).filter(CardCustomer.id == customer_id).first()
    if customer is None:
        raise HTTPException(404, "客户不存在")
    if not (payload.content or "").strip() and not payload.attachment_path:
        raise HTTPException(422, "内容和附件至少有一个")
    entry = CardEntry(
        customer_id=customer_id,
        entry_type="image" if payload.attachment_path else "text",
        title=(payload.title or "").strip() or None,
        content=payload.content,
        attachment_path=payload.attachment_path,
        created_by=int(user.get("sub", 0)) or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return ok({"id": entry.id})


@router.delete("/admin/entries/{entry_id}", summary="删除纪要")
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:write")),
):
    entry = db.query(CardEntry).filter(CardEntry.id == entry_id).first()
    if entry is None:
        raise HTTPException(404, "纪要不存在")
    db.delete(entry)
    db.commit()
    return ok()


@router.post("/admin/attachments", summary="上传纪要图片附件")
async def upload_attachment(
    file: UploadFile = File(...),
    _user: dict = Depends(require_permission("card:write")),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMAGE_EXTS:
        raise HTTPException(422, f"只收图片附件（{'/'.join(sorted(_IMAGE_EXTS))}）")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(422, f"附件超过 {_MAX_UPLOAD_MB}MB")
    name = f"{uuid.uuid4().hex}{ext}"
    abs_path = UPLOAD_ROOT / name
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    rel = f"card/{name}"
    return ok({"attachment_path": rel, "url": f"/uploads/{rel}"})


# ---------- 询盘 ----------

@router.get("/admin/inquiries", summary="询盘列表")
def list_inquiries(
    status: str = Query("", pattern=r"^(new|handled)?$"),
    salesperson_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:read")),
):
    q = db.query(CardInquiry)
    if status:
        q = q.filter(CardInquiry.status == status)
    if salesperson_id:
        q = q.filter(CardInquiry.salesperson_id == salesperson_id)
    total = q.count()
    rows = (
        q.order_by(CardInquiry.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    sp_names = dict(db.query(CardSalesperson.id, CardSalesperson.name).all())
    return ok({
        "total": total,
        "items": [
            {
                "id": r.id,
                "salesperson": sp_names.get(r.salesperson_id, "?"),
                "customer_id": r.customer_id,
                "contact": r.contact,
                "message": r.message,
                "status": r.status,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
            }
            for r in rows
        ],
    })


@router.put("/admin/inquiries/{inquiry_id}", summary="更新询盘状态")
def update_inquiry(
    inquiry_id: int,
    payload: InquiryStatusUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("card:write")),
):
    row = db.query(CardInquiry).filter(CardInquiry.id == inquiry_id).first()
    if row is None:
        raise HTTPException(404, "询盘不存在")
    row.status = payload.status
    db.commit()
    return ok()
