"""Current DB employee permissions at the first shipment business read."""
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.invoice import settlement_service as shipments
from app.invoice.settlement_models import ShipmentSettlement
from app.invoice.settlement_policy import capabilities
from app.receipt import authority


def read(db, user, *, kind, identity=None):
    # No response-time revocation promise; these ordinary reads authorize once
    # before accessing business data and never commit or call external services.
    permissions = ('invoice:read','invoice:write','receipt:write','shipment:read') if kind=='capabilities' else ('shipment:read','shipment:write')
    try:
        current = authority.read_user(db,user,*permissions)
        if kind=='capabilities':
            return capabilities()
        if kind=='order':
            shipments.get_order(db,identity,current,writable=False)
            rows=db.query(ShipmentSettlement).filter_by(invoice_id=identity).order_by(ShipmentSettlement.sequence.desc()).all()
            return {'items':[shipments.describe(db,row) for row in rows]}
        if kind=='detail':
            return shipments.describe(db,shipments.get(db,identity,current))
        raise ValueError('Unknown shipment read kind')
    except ValueError as error:
        raise HTTPException(409,str(error)) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)
