"""Customer-only HTTP boundary; no employee JWT is accepted here."""
from ipaddress import ip_address
import re
from uuid import UUID, uuid4
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.portal import auth_service as service
from app.portal.errors import PortalError, reject
from app.portal.action_receipt_queries import ActionReceiptQuery
from app.portal.schemas import ChallengeInput, PortalInput, VerifyInput, QuoteInput, SubmitInput, ReasonInput, AcceptInput, ReorderInput
from app.portal.security import require_origin


class PortalRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                service.require_enabled()
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    require_origin(request.headers.get("origin"), get_settings().PORTAL_ORIGIN)
                    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        reject("INVALID_INPUT", "A JSON request is required.", 415)
                response = await handler(request)
            except PortalError as error:
                response = JSONResponse(status_code=error.status, content=ok(code=error.status,
                    message=error.message, data={"error_code": error.code, "trace_id": str(uuid4()),
                    "retryable": error.status == 503, "issues": error.issues}))
            except RequestValidationError:
                # ValidationError.errors() includes raw passwords/tokens/PII inputs.
                response = JSONResponse(status_code=422, content=ok(code=422,
                    message="Please check the submitted fields.", data={"error_code": "INVALID_INPUT",
                    "trace_id": str(uuid4()), "retryable": False, "issues": []}))
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        return guarded


router = APIRouter(route_class=PortalRoute)


def _require_portal_proxy(request: Request):
    """Retain the TCP peer: disable Uvicorn proxy headers or strip them at ingress.

    Only an explicitly trusted reverse proxy may supply the overwritten X-Real-IP.
    Never fall back to X-Forwarded-For or accept a client-supplied address directly.
    """
    configured = get_settings().PORTAL_TRUSTED_PROXY_IPS
    try:
        trusted = {ip_address(value) for value in configured}
        peer = ip_address(request.client.host) if request.client else None
        if peer not in trusted:
            reject("ACTION_FORBIDDEN", "This entry point is not available.", 403)
        return str(ip_address(request.headers.get("x-real-ip", "")))
    except ValueError:
        reject("ACTION_FORBIDDEN", "This entry point is not available.", 403)


def cookie_name(kind):
    secure = get_settings().PORTAL_ORIGIN.startswith("https://")
    return ("__Host-" if secure else "dev-") + "portal_" + kind


def set_cookie(response, kind, token, max_age):
    response.set_cookie(cookie_name(kind), token, max_age=max_age, httponly=True,
        secure=get_settings().PORTAL_ORIGIN.startswith("https://"), samesite="lax", path="/")


def clear_cookie(response, kind):
    response.delete_cookie(cookie_name(kind), path="/", httponly=True,
        secure=get_settings().PORTAL_ORIGIN.startswith("https://"), samesite="lax")


def preauth(request, db):
    return service.require_preauth(db, request.cookies.get(cookie_name("preauth")),
                                   request.headers.get("x-portal-csrf"))


def failed_transaction(db, error):
    # Only the rate-limit path can have legitimate previous rate debits to retain.
    if error.status == 429:
        db.commit()
    else:
        db.rollback()


@router.get("/auth/bootstrap")
def bootstrap(client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    try:
        row, token, csrf = service.bootstrap(db, client_ip)
        db.commit()
    except PortalError as error:
        failed_transaction(db, error)
        raise
    response = JSONResponse(ok({"csrf_token": csrf, "expires_in": 600}))
    set_cookie(response, "preauth", token, 600)
    return response


@router.post("/auth/challenges")
def challenge(body: ChallengeInput, request: Request,
              client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    try:
        row = service.challenge(db, preauth(request, db), body, client_ip)
        data = {"challenge_id": row.public_id, "expires_in": get_settings().PORTAL_OTP_MINUTES * 60,
                "resend_after": 60}
        db.commit()
    except PortalError as error:
        failed_transaction(db, error)
        raise
    return JSONResponse(ok(data, code=202), status_code=202)


@router.post("/auth/verify")
def verify(body: VerifyInput, request: Request,
           client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    try:
        result = service.verify(db, preauth(request, db), body, client_ip)
        data = service.session_view(result[0], result[1]) if result else None
        db.commit()  # Persist failed attempt counts BEFORE returning AUTH_FAILED.
    except PortalError as error:
        failed_transaction(db, error)
        raise
    if result is None:
        reject("AUTH_FAILED", "The code is invalid or expired. Please try again.", 401)
    response = JSONResponse(ok(data))
    set_cookie(response, "session", result[2], get_settings().PORTAL_SESSION_HOURS * 3600)
    clear_cookie(response, "preauth")
    return response


@router.get("/catalog")
def catalog(request: Request, keyword: str = Query("", max_length=100),
            category: Literal["hair", "accessory"] | None = None, in_stock_only: bool = False,
            page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
            sort: Literal["curated", "name"] = "curated",
            client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import catalog_service
    principal, _ = service.authenticate(db, request.cookies.get(cookie_name("session")))
    result = catalog_service.list_catalog(db, principal, keyword=keyword, category=category,
        in_stock_only=in_stock_only, page=page, page_size=page_size, sort=sort)
    db.commit()
    return ok(result)


@router.get("/catalog/{item_id}")
def catalog_item(item_id: UUID, request: Request,
                 client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import catalog_service
    principal, _ = service.authenticate(db, request.cookies.get(cookie_name("session")))
    result = catalog_service.detail(db, principal, item_id)
    db.commit()
    return ok(result)


@router.get("/sales-contact")
def sales_contact(request: Request, client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    # Customer-only principal and live assignment; no client-supplied employee ID.
    from app.portal.contact_service import contact_view
    principal, _ = service.authenticate(db, request.cookies.get(cookie_name("session")))
    data = {"contact": contact_view(principal)}
    db.commit()
    return ok(data)


@router.get("/session")
def session(request: Request, client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    principal, row = service.authenticate(db, request.cookies.get(cookie_name("session")))
    data = service.session_view(principal, row)
    db.commit()
    return ok(data)


@router.post("/quotes", status_code=201)
def create_quote(body: QuoteInput, request: Request,
                 client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import quote_service
    try:
        data = quote_service.create(db, request.cookies.get(cookie_name("session")),
                                    request.headers.get("x-portal-csrf"), body)
        db.commit()
    except PortalError:
        db.rollback()
        raise
    return ok(data, code=201)


@router.get("/quotes/{quote_id}")
def quote_detail(quote_id: UUID, request: Request,
                 client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import quote_service
    data = quote_service.detail(db, request.cookies.get(cookie_name("session")), quote_id)
    db.commit()
    return ok(data)


@router.post("/auth/logout")
def logout(body: PortalInput, request: Request,
           client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    try:
        principal, row = service.authenticate(db, request.cookies.get(cookie_name("session")),
            csrf=request.headers.get("x-portal-csrf"), write=True)
        service.logout(db, principal, row)
        db.commit()
    except PortalError as error:
        db.rollback()
        if error.status != 401:
            raise
    response = JSONResponse(ok({"signed_out": True}))
    clear_cookie(response, "session")
    clear_cookie(response, "preauth")
    return response


def submission_key(value: str | None = Header(default=None, alias="Idempotency-Key")):
    if value is None:
        reject("IDEMPOTENCY_KEY_REQUIRED", "A submission key is required.", 428)
    try:
        return UUID(value)
    except ValueError:
        reject("INVALID_INPUT", "The submission key must be a UUID.", 422)


def _submission_key_conflict(error):
    original = error.orig
    args = getattr(original, "args", ())
    if args and args[0] == 1062:
        return "uq_op_request_key" in str(original)
    return str(original) == ("UNIQUE constraint failed: ark_order_portal_requests.access_id, "
        "ark_order_portal_requests.account_id, ark_order_portal_requests.idempotency_key")


@router.post("/orders")
def submit_order(body: SubmitInput, request: Request, key=Depends(submission_key),
                 client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import order_service
    token, csrf = request.cookies.get(cookie_name("session")), request.headers.get("x-portal-csrf")
    try:
        data = order_service.submit(db, token, csrf, key, body)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if not _submission_key_conflict(error):
            raise
        data = order_service.recover_unique_race(db, token, csrf, key, body)
        if data is None:
            db.rollback()
            raise
        db.commit()
    except PortalError:
        db.rollback()
        raise
    status = 200 if data["replayed"] else 201
    return JSONResponse(status_code=status, content=ok(data, code=status))


@router.get("/orders/by-key/{key}")
def order_by_key(key: UUID, request: Request, client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import order_service
    data = order_service.by_key(db, request.cookies.get(cookie_name("session")), key)
    db.commit()
    return ok(data)


OrderStatus = Literal["submitted", "awaiting_customer", "ready_for_review", "invoice_created", "rejected", "cancelled"]


@router.get("/orders")
def order_list(request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               status: OrderStatus | None = None,
               client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import order_queries
    data = order_queries.customer_list(db, request.cookies.get(cookie_name("session")),
                                      page=page, page_size=page_size, status=status)
    db.commit()
    return ok(data)


@router.get("/orders/{request_id}")
def order_detail(request_id: UUID, request: Request,
                 client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import order_queries
    data = order_queries.customer_detail(db, request.cookies.get(cookie_name("session")), request_id)
    db.commit()
    return ok(data)


@router.get("/orders/{request_id}/action-receipt")
def action_receipt(request_id: UUID, request: Request,
                   locator: Annotated[ActionReceiptQuery, Query()],
                   client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    # Dedicated customer principal; employee RBAC is not a portal credential.
    from app.portal import action_receipt_queries, authority
    try:
        data = action_receipt_queries.query(db, request.cookies.get(cookie_name("session")), request_id, locator)
        db.commit()  # Only auth idle renewal; no command or commercial mutation.
    except (PortalError, SQLAlchemyError) as error:
        try:
            db.rollback()
        except SQLAlchemyError as rollback_error:
            authority.unavailable(rollback_error)
        if isinstance(error, SQLAlchemyError):
            authority.unavailable(error)
        raise
    return ok(data)

def command_version(value: str | None = Header(default=None, alias="If-Match")):
    if value is None:
        reject("VERSION_REQUIRED", "Refresh this page before continuing.", 428)
    if not re.fullmatch(r'"[1-9][0-9]{0,18}"', value):
        reject("INVALID_INPUT", "If-Match must contain a quoted record version.", 422)
    return int(value[1:-1])


@router.post("/orders/{request_id}/cancel")
def cancel_order(request_id: UUID, body: ReasonInput, request: Request, expected=Depends(command_version),
                 client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal import order_commands
    try:
        data = order_commands.cancel(db, request.cookies.get(cookie_name("session")),
            request.headers.get("x-portal-csrf"), request_id, expected, body)
        db.commit()
    except PortalError:
        db.rollback()
        raise
    return ok(data)


def _proposal_decision(db, request, request_id, revision_id, expected, body, accept):
    from app.portal import proposal_decisions
    try:
        data = proposal_decisions.decide(db, request.cookies.get(cookie_name("session")),
            request.headers.get("x-portal-csrf"), request_id, revision_id, expected, body, accept=accept)
        db.commit()
    except PortalError:
        db.rollback()
        raise
    return ok(data)


@router.post("/orders/{request_id}/proposals/{revision_id}/accept")
def accept_proposal(request_id: UUID, revision_id: UUID, body: AcceptInput, request: Request,
                    expected=Depends(command_version), client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    return _proposal_decision(db, request, request_id, revision_id, expected, body, True)


@router.post("/orders/{request_id}/proposals/{revision_id}/reject")
def reject_proposal(request_id: UUID, revision_id: UUID, body: ReasonInput, request: Request,
                    expected=Depends(command_version), client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    return _proposal_decision(db, request, request_id, revision_id, expected, body, False)


@router.get("/orders/{request_id}/pi")
def download_pi(request_id: UUID, request: Request, client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal.pi_service import download
    content, filename = download(db, request.cookies.get(cookie_name("session")), request_id)
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition":'attachment; filename="'+filename+'"', "Cache-Control":"no-store"})


@router.post("/orders/{request_id}/reorder-quote", status_code=201)
def reorder_quote(request_id: UUID, body: ReorderInput, request: Request,
                  client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from app.portal.reorder_service import create_quote
    try:
        result = create_quote(db, request.cookies.get(cookie_name("session")),
            request.headers.get("x-portal-csrf"), request_id, body)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(result, code=201)


@router.get("/catalog/{item_id}/image")
def catalog_image(item_id: UUID, request: Request, version: int = Query(..., ge=1),
                  client_ip=Depends(_require_portal_proxy), db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from app.portal.image_service import customer_image
    content = customer_image(db, request.cookies.get(cookie_name("session")), item_id, version)
    return Response(content, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'"})
