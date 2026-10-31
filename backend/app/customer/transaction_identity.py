"""Resolve current logical owners without rewriting immutable transaction IDs.

Allocated order funds follow the order's reviewed ownership. Unallocated cash
keeps its original payer and follows only explicit account merges.
"""
from sqlalchemy import select
from app.customer.models import CustomerAccount, CustomerOrder, CustomerObjectOwnership


def _one(db, statement, lock):
    return db.scalar(statement.with_for_update().execution_options(populate_existing=True) if lock else statement)


def current_customer(db, identity, *, lock=False):
    visited = set()
    while identity and identity not in visited:
        visited.add(identity)
        account = _one(db, select(CustomerAccount).where(CustomerAccount.id == identity), lock)
        if account is None or account.identity_status == 'disputed':
            break
        if account.record_status == 'active':
            return account.id
        if account.record_status != 'merged':
            break
        identity = account.merged_into_customer_id
    raise ValueError('交易客户无法解析到明确有效客户')


def invoice_customer(db, invoice, *, lock=False):
    order = _one(db, select(CustomerOrder).where(CustomerOrder.local_invoice_id == invoice.id), lock)
    owner = _one(db, select(CustomerObjectOwnership).where(CustomerObjectOwnership.object_type == 'order',
        CustomerObjectOwnership.object_id == order.id), lock) if order else None
    return current_customer(db, owner.current_customer_id if owner else order.customer_id if order else invoice.local_customer_id, lock=lock)


def invoice_key(db, invoice, *, lock=False):
    return f'ark:{invoice_customer(db, invoice, lock=lock)}'
