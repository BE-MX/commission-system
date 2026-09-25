"""Authenticated settlement support only: no trade execution endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.fx_settlement import service
from app.fx_settlement.market_service import get_market
from app.fx_settlement.schemas import SettlementInput

router = APIRouter()


@router.get("/market")
def market(_user: dict = Depends(require_permission("fx_settlement:read"))):
    return ok(get_market())


@router.post("/calculate")
def calculate(payload: SettlementInput, _user: dict = Depends(require_permission("fx_settlement:read"))):
    try:
        return ok(service.build_plan(payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/advice")
def advice(
    payload: SettlementInput,
    user: dict = Depends(require_permission("fx_settlement:read", "fx_settlement:write")),
    db: Session = Depends(get_db),
):
    try:
        return ok(service.generate_advice(db, payload, str(user["sub"])))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
