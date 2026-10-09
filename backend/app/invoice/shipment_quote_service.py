"""Current-authorized shipment quote; immutable evidence outside business locks."""
import json
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import set_committed_value
from app.invoice import edit_authority, okki_client, settlement_service as shipments, shipment_create_service as facts
from app.invoice.models import InvoiceItem
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, retry_service


def _authorize(db, identity, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = authority.current_user(db,user,'invoice:read','invoice:write',any_permission=True)
        invoice = edit_authority.lock_document(db,identity,force=True)
        if invoice is None:
            raise HTTPException(404,'订单不存在')
        db.refresh(invoice,with_for_update=True)
        access.ensure_invoice(db,invoice,current)
        items = facts._rows(db,InvoiceItem,InvoiceItem.invoice_id==invoice.id)
        set_committed_value(invoice,'items',facts.business_items(items))
        return invoice,current
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status,'发货报价授权暂不可用') from None


def _release(db):
    transaction = db.get_transaction()
    if transaction is not None and not transaction.is_active:
        db.close()
    else:
        db.rollback()
    db.expire_all()


def unavailable(error):
    retry_service._unavailable(error,message='发货报价暂不能核验，请稍后重新获取报价')


def quote(db, identity, body, user):
    # A dirty caller is rejected before finally; its transaction remains intact.
    authority.fresh_boundary(db)
    try:
        invoice,current = _authorize(db,identity,user)
        expected,target,freight,_ = facts._capture(db,invoice,body,current)
        db.commit()
        try:
            evidence = facts._evidence(db,target,freight)
            db.commit()  # End provider token/cache work before final authority.
        except (ValueError,TypeError,okki_client.OkkiApiError,SQLAlchemyError,OSError,HTTPException) as error:
            unavailable(error)
        finally:
            _release(db)
        invoice,current = _authorize(db,identity,user)
        actual,_,_,_ = facts._capture(db,invoice,body,current)
        if actual != expected:
            raise HTTPException(409,'订单或发货资金在核验期间已变化，请重新获取报价')
        result = shipments.build_quote(db,invoice,body,evidence,current=True)
        # Detach all returned values before releasing the final read locks.
        return json.loads(json.dumps(result))
    except ValueError as error:
        raise HTTPException(409,str(error)) from None
    except SQLAlchemyError as error:
        unavailable(error)
    finally:
        _release(db)
