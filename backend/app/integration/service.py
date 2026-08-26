"""Integration App credential lifecycle and owner eligibility services."""

from datetime import datetime
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import logging
import secrets

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.auth.utils import hash_token
from app.core.time import beijing_now
from app.integration.models import IntegrationApp, InvoiceIngestRequest
from app.integration.schemas import IntegrationAppCreate, InvoiceSubmission
from app.integration import validation_service
from app.invoice import service as invoice_service
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload


INVOICE_SCOPE = "invoice:write"
_MONEY = Decimal("0.01")
_REVIEW_URL = "https://leshine.work/invoice/manage"
logger = logging.getLogger("commission.integration.service")


def _commit_or_rollback(db: Session, operation: str) -> None:
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("外部发票事务提交失败 operation=%s", operation)
        print(
            f"[integration] commit failed operation={operation} err={type(exc).__name__}",
            flush=True,
        )
        raise


class ExternalOrderChanged(Exception):
    def __init__(self, row: InvoiceIngestRequest):
        self.row = row


class ExternalInvoiceProcessing(Exception):
    def __init__(self, row: InvoiceIngestRequest):
        self.row = row


class ExternalInvoiceRejected(Exception):
    def __init__(self, row: InvoiceIngestRequest, issues: list[dict], warnings: list[dict]):
        self.row = row
        self.issues = issues
        self.warnings = warnings


def user_has_invoice_write(user: ArkUser) -> bool:
    return (
        "super_admin" in set(get_user_roles(user))
        or INVOICE_SCOPE in set(get_user_permissions(user))
    )


def _active_owner(db: Session, user_id: int) -> ArkUser:
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="目标账号不存在")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="目标账号已停用，不能绑定接入应用")
    if not user_has_invoice_write(user):
        raise HTTPException(status_code=400, detail="目标账号当前缺少 invoice:write 权限")
    return user


def _plain_token() -> str:
    return f"ark_live_{secrets.token_urlsafe(32)}"


def _public_id() -> str:
    return f"app_{secrets.token_urlsafe(18)}"


def _request_public_id() -> str:
    return f"req_{secrets.token_urlsafe(18)}"


def _canonical_value(value):
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    return value


def canonical_submission_sha256(submission: InvoiceSubmission) -> str:
    """Hash the complete validated request, independent of JSON representation."""
    canonical = _canonical_value(submission.model_dump(mode="python"))
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _money_text(value) -> str:
    return f"{Decimal(value or 0).quantize(_MONEY, rounding=ROUND_HALF_UP):.2f}"


def _result_payload(row: InvoiceIngestRequest, invoice, *, replayed: bool) -> dict:
    return {
        "request_id": row.public_id,
        "replayed": replayed,
        "external_order_id": row.external_order_id,
        "invoice_id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "status": invoice.status,
        "sync_status": invoice.sync_status,
        "totals": {
            "product_amount": _money_text(invoice.product_amount),
            "total_amount": _money_text(invoice.total_amount),
        },
        "review_url": _REVIEW_URL,
    }


def _integration_app(db: Session, namespace: str) -> IntegrationApp:
    row = db.query(IntegrationApp).filter(IntegrationApp.public_id == namespace).first()
    if row is None:
        raise HTTPException(status_code=401, detail="站点接入应用不存在或已失效")
    return row


def _internal_invoice_payload(
    canonical: dict,
    ingest: InvoiceIngestRequest,
    *,
    sales_user_id: int,
) -> InvoiceCreate:
    customer = canonical["customer"]
    contact = customer["contact"]
    delivery = canonical["delivery"]
    fees = canonical["fees"]
    surcharge = fees["surcharge"]
    return InvoiceCreate(
        sales_user_id=sales_user_id,
        customer_id=customer["ark_customer_id"],
        customer_name=customer["name"],
        order_type=canonical["order_type"],
        contact_name=contact["name"],
        contact_phone=contact["phone"],
        contact_email=contact["email"],
        delivery_address=delivery["address"],
        invoice_date=canonical["invoice_date"],
        currency=canonical["currency"],
        express_channel=delivery["express_channel"],
        shipping_fee=Decimal(fees["shipping_amount"]),
        surcharge_name=surcharge["name"],
        surcharge_amount=Decimal(surcharge["amount"]),
        payment_term=canonical["payment_term"],
        packaging_quantity=fees["packaging_quantity"],
        internal_accessory=Decimal(fees["packaging_amount"]),
        remark=canonical["remark"],
        source_type="external_api",
        source_order_id=ingest.public_id,
        source_order_name=ingest.external_order_id,
        items=[
            InvoiceItemPayload(
                product_kind=item["product_kind"],
                item_type="stock",
                product_id=item["catalog_ref"]["product_id"],
                sku_id=item["catalog_ref"]["sku_id"],
                product_name=item["description"]["product_name"],
                product_display=item["description"]["product_display"],
                net_weight_grams=item["description"]["unit"],
                model=item["description"]["model"],
                color=item["description"]["color"],
                length=item["description"]["length"],
                quantity=item["quantity"],
                price_per_piece=Decimal(item["unit_price"]),
                discount_amount=Decimal(item["discount_amount"]),
                price_source=item["price_source"],
            )
            for item in canonical["items"]
        ],
    )


def _reject(
    db: Session,
    row: InvoiceIngestRequest,
    *,
    issues: list[dict],
    warnings: list[dict],
) -> None:
    row.status = "rejected"
    row.invoice_id = None
    row.error_code = issues[0]["code"] if issues else "INVOICE_CREATE_REJECTED"
    row.error_json = {"issues": issues, "warnings": warnings}
    row.finished_at = beijing_now()
    _commit_or_rollback(db, "reject_invoice_ingest")


def _existing_result(
    db: Session,
    row: InvoiceIngestRequest,
    request_sha256: str,
) -> dict | None:
    if row.status == "created":
        if row.request_sha256 != request_sha256:
            raise ExternalOrderChanged(row)
        invoice = invoice_service.get_invoice(db, row.invoice_id)
        if invoice is None:
            raise RuntimeError("created ingest request references a missing invoice")
        return _result_payload(row, invoice, replayed=True)
    if row.status == "processing":
        raise ExternalInvoiceProcessing(row)
    row.request_sha256 = request_sha256
    row.status = "processing"
    row.attempt_count += 1
    row.invoice_id = None
    row.error_code = None
    row.error_json = None
    row.finished_at = None
    return None


def create_external_invoice(
    db: Session,
    submission: InvoiceSubmission,
    principal,
) -> tuple[dict, bool]:
    request_sha256 = canonical_submission_sha256(submission)
    app = _integration_app(db, principal.idempotency_namespace)
    row = (
        db.query(InvoiceIngestRequest)
        .filter(
            InvoiceIngestRequest.integration_app_id == app.id,
            InvoiceIngestRequest.external_order_id == submission.external_order_id,
        )
        .with_for_update()
        .first()
    )
    if row is not None:
        replay = _existing_result(db, row, request_sha256)
        if replay is not None:
            return replay, True
    else:
        row = InvoiceIngestRequest(
            public_id=_request_public_id(),
            integration_app_id=app.id,
            external_order_id=submission.external_order_id,
            request_sha256=request_sha256,
            status="processing",
            attempt_count=1,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            app = _integration_app(db, principal.idempotency_namespace)
            winner = (
                db.query(InvoiceIngestRequest)
                .filter(
                    InvoiceIngestRequest.integration_app_id == app.id,
                    InvoiceIngestRequest.external_order_id == submission.external_order_id,
                )
                .with_for_update()
                .first()
            )
            if winner is None:
                raise
            replay = _existing_result(db, winner, request_sha256)
            if replay is not None:
                return replay, True
            row = winner

    try:
        canonical = validation_service.validate_submission(db, submission)
    except validation_service.InvoiceValidationError as exc:
        _reject(db, row, issues=exc.issues, warnings=exc.warnings)
        raise ExternalInvoiceRejected(row, exc.issues, exc.warnings) from exc
    except Exception as exc:
        db.rollback()
        logger.exception(
            "外部发票校验发生未预期异常 app_id=%s external_order_id=%s",
            app.id,
            submission.external_order_id,
        )
        print(
            "[integration] unexpected validation error "
            f"app_id={app.id} external_order_id={submission.external_order_id} "
            f"err={type(exc).__name__}",
            flush=True,
        )
        raise

    try:
        payload = _internal_invoice_payload(
            canonical,
            row,
            sales_user_id=principal.sales_user_id,
        )
        with db.begin_nested():
            invoice = invoice_service.create_invoice(
                db,
                payload,
                user_id=principal.actor_user_id,
                allow_external_source=True,
            )
            expected = canonical["totals"]
            if (
                _money_text(invoice.product_amount) != expected["product_amount"]
                or _money_text(invoice.total_amount) != expected["total_amount"]
            ):
                raise ValueError("invoice totals changed between validation and persistence")
    except ValueError as exc:
        issue = {
            "code": "INVOICE_CREATE_REJECTED",
            "field": "invoice",
            "message": "发票创建条件已变化，请刷新客户或产品信息后重试",
        }
        _reject(db, row, issues=[issue], warnings=[])
        raise ExternalInvoiceRejected(row, [issue], []) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    row.status = "created"
    row.invoice_id = invoice.id
    row.error_code = None
    row.error_json = None
    row.finished_at = beijing_now()
    _commit_or_rollback(db, "create_invoice_ingest")
    db.refresh(invoice)
    invoice = invoice_service.get_invoice(db, invoice.id)
    return _result_payload(row, invoice, replayed=False), False


def get_external_invoice_result(
    db: Session,
    external_order_id: str,
    principal,
) -> tuple[str, dict | InvoiceIngestRequest | None]:
    app = _integration_app(db, principal.idempotency_namespace)
    row = db.query(InvoiceIngestRequest).filter(
        InvoiceIngestRequest.integration_app_id == app.id,
        InvoiceIngestRequest.external_order_id == external_order_id,
    ).first()
    if row is None:
        return "not_found", None
    if row.status == "processing":
        return "processing", row
    if row.status == "rejected":
        errors = row.error_json if isinstance(row.error_json, dict) else {}
        return "rejected", {
            "request_id": row.public_id,
            "issues": list(errors.get("issues") or []),
            "warnings": list(errors.get("warnings") or []),
        }
    invoice = invoice_service.get_invoice(db, row.invoice_id)
    if invoice is None:
        raise RuntimeError("created ingest request references a missing invoice")
    return "created", _result_payload(row, invoice, replayed=True)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _app_payload(row: IntegrationApp, owner: ArkUser | None = None) -> dict:
    return {
        "id": row.id,
        "public_id": row.public_id,
        "name": row.name,
        "owner_user_id": row.owner_user_id,
        "owner_username": owner.username if owner is not None else None,
        "owner_real_name": owner.real_name if owner is not None else None,
        "token_suffix": row.token_suffix,
        "scopes": list(row.scopes or []),
        "is_active": bool(row.is_active),
        "expires_at": _iso(row.expires_at),
        "last_used_at": _iso(row.last_used_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def list_user_candidates(db: Session, *, q: str, limit: int) -> list[dict]:
    query = db.query(ArkUser).filter(
        ArkUser.deleted_at.is_(None),
        ArkUser.is_active.is_(True),
    )
    keyword = q.strip()
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(
            ArkUser.username.ilike(pattern),
            ArkUser.real_name.ilike(pattern),
        ))
    users = query.order_by(ArkUser.real_name, ArkUser.username).limit(limit).all()
    return [
        {
            "user_id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "has_invoice_write": user_has_invoice_write(user),
        }
        for user in users
    ]


def list_apps(db: Session) -> list[dict]:
    rows = (
        db.query(IntegrationApp, ArkUser)
        .outerjoin(ArkUser, ArkUser.id == IntegrationApp.owner_user_id)
        .order_by(IntegrationApp.created_at.desc(), IntegrationApp.id.desc())
        .all()
    )
    return [_app_payload(row, owner) for row, owner in rows]


def create_app(
    db: Session,
    request: IntegrationAppCreate,
    *,
    created_by: int,
) -> dict:
    owner = _active_owner(db, request.owner_user_id)
    if request.expires_at is not None and request.expires_at <= beijing_now():
        raise HTTPException(status_code=400, detail="过期时间必须晚于当前北京时间")

    token = _plain_token()
    row = IntegrationApp(
        public_id=_public_id(),
        name=request.name,
        owner_user_id=owner.id,
        token_hash=hash_token(token),
        token_suffix=token[-6:],
        scopes=[INVOICE_SCOPE],
        expires_at=request.expires_at,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        **_app_payload(row, owner),
        "token": token,
        "note": "明文 Token 仅本次返回，关闭后无法再次查看",
    }


def rotate_app_token(db: Session, app_id: int, *, current_token_suffix: str) -> dict:
    row = db.query(IntegrationApp).filter(
        IntegrationApp.id == app_id
    ).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="接入应用不存在")
    if not row.is_active:
        raise HTTPException(status_code=409, detail="接入应用已吊销，不能轮换凭证")
    if row.token_suffix != current_token_suffix:
        raise HTTPException(status_code=409, detail="凭证已被其他请求轮换，请刷新后重试")
    owner = _active_owner(db, row.owner_user_id)

    token = _plain_token()
    row.token_hash = hash_token(token)
    row.token_suffix = token[-6:]
    row.last_used_at = None
    db.commit()
    db.refresh(row)
    return {
        **_app_payload(row, owner),
        "token": token,
        "note": "旧 Token 已立即失效；新明文 Token 仅本次返回",
    }


def revoke_app(db: Session, app_id: int) -> dict:
    row = db.query(IntegrationApp).filter(IntegrationApp.id == app_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="接入应用不存在")
    row.is_active = False
    db.commit()
    return {"id": row.id, "is_active": False}
