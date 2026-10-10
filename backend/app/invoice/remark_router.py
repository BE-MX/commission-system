"""Narrow authenticated remark endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import remark_service

router = APIRouter()


class InvoiceRemarkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remark: str = Field(max_length=5000)
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.patch("/invoices/{invoice_id}/remark", summary="Edit local invoice remark without resending")
def update_remark(invoice_id: int, body: InvoiceRemarkUpdate, db: Session = Depends(get_db),
                  user=Depends(require_permission("invoice:write"))):
    try:
        data = remark_service.update(db, invoice_id, body, user)
        db.commit()
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None
    except Exception:
        db.rollback()
        raise
    return ok(data)
