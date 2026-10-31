"""Workbench projections; supply candidates use the command's invoice scope."""
from fastapi import HTTPException
from sqlalchemy import select, or_

from app.inventory.models import Warehouse, StockDocument
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.service import _visible_invoice_query
from app.invoice.native_visibility import local_invoice_scope
from app.production.models import ProcessRoute
from app.production.local_models import ProductionEvent, ProductionMaterial
from app.receipt.access import user_id
from app.semifinished.models import SemifinishedMaterial, InventoryBalance
from app.stock.models import ProductionOrder, ProductionOrderItem


def list_orders(db, keyword, status, page, page_size):
    from app.production.local_service import describe
    query = db.query(ProductionOrder).filter(ProductionOrder.transaction_mode == 'local', ProductionOrder.deleted_flag == 0)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(or_(ProductionOrder.batch_no.like(like), ProductionOrder.order_no.like(like)))
    if status is not None:
        query = query.filter(ProductionOrder.status == status)
    total = query.count()
    rows = query.order_by(ProductionOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [describe(db, row.id) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


def reference_data(db):
    warehouses = db.scalars(select(Warehouse).where(Warehouse.active.is_(True)).order_by(Warehouse.id)).all()
    routes = db.scalars(select(ProcessRoute).where(ProcessRoute.status == 1).order_by(ProcessRoute.name)).all()
    return {'warehouses': [{'id': row.id, 'name': row.name} for row in warehouses],
            'process_routes': [{'id': row.id, 'name': row.name} for row in routes]}


def supply_options(db, item_id, user, keyword, page, page_size):
    item = db.get(ProductionOrderItem, item_id)
    order = db.get(ProductionOrder, item.order_id) if item else None
    if order is None or order.transaction_mode != 'local' or order.deleted_flag:
        raise HTTPException(404, '本地生产明细不存在')
    viewer = None if 'super_admin' in user.get('roles', []) or 'invoice:read_all' in user.get('permissions', []) else user_id(user)
    remaining = InvoiceItem.quantity - InvoiceItem.stock_reserved_quantity - InvoiceItem.stock_shipped_quantity - InvoiceItem.production_pending_quantity
    query = _visible_invoice_query(db, viewer_user_id=viewer).join(InvoiceItem).filter(
        local_invoice_scope(db, user, read_permissions=('production:write', 'invoice:read_all')),
        Invoice.transaction_mode == 'local', Invoice.commerce_status.in_(['confirmed', 'partially_shipped']),
        InvoiceItem.local_sku_id == item.local_sku_id, remaining > 0)
    if keyword:
        query = query.filter(Invoice.invoice_no.like(f'%{keyword}%'))
    lines = query.with_entities(InvoiceItem.id, Invoice.invoice_no, remaining.label('remaining_quantity'))
    total = lines.count()
    rows = lines.order_by(Invoice.id.desc(), InvoiceItem.id).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [{'invoice_item_id': row.id, 'invoice_no': row.invoice_no,
                      'remaining_quantity': row.remaining_quantity} for row in rows], 'total': total}


def material_options(db, keyword, item_id, page, page_size):
    query = db.query(SemifinishedMaterial).outerjoin(InventoryBalance, InventoryBalance.material_id == SemifinishedMaterial.id)
    usable = SemifinishedMaterial.status == 'active'
    if item_id:
        usable = or_(usable, SemifinishedMaterial.id.in_(select(ProductionMaterial.material_id).where(ProductionMaterial.production_item_id == item_id)))
    query = query.filter(usable)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(or_(SemifinishedMaterial.material_code.like(like), SemifinishedMaterial.color_code.like(like), SemifinishedMaterial.size.like(like)))
    total = query.count()
    rows = query.with_entities(SemifinishedMaterial, InventoryBalance).order_by(SemifinishedMaterial.id).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [{'id': row.id, 'label': f'{row.material_code} · {row.size} · {row.color_code}', 'active': row.status == 'active',
                      'available_grams': str(balance.on_hand_grams - balance.reserved_grams) if balance else '0.000'}
                     for row, balance in rows], 'total': total}


def receipts(db, order_id):
    rows = db.execute(select(ProductionEvent, StockDocument).join(StockDocument, StockDocument.id == ProductionEvent.stock_document_id)
                      .where(ProductionEvent.order_id == order_id, ProductionEvent.action == 'receive').order_by(ProductionEvent.id.desc())).all()
    result = []
    for event, document in rows:
        body = event.payload['body']
        warehouse = db.get(Warehouse, body['warehouse_id'])
        result.append({'event_id': event.id, 'item_id': event.item_id, 'quantity': body['quantity'],
                       'quality': body['quality'], 'warehouse_name': warehouse.name if warehouse else '仓库已不可用',
                       'created_at': event.created_at, 'reason': body['reason'], 'reversed': bool(document.reversed_by_id)})
    return result
