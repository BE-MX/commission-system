"""Shared order filters for the list and detail export."""

from datetime import date

from sqlalchemy.orm import Session

from app.domestic.models import DomesticCustomer, DomesticOrder


def filtered_order_query(
    db: Session,
    *,
    keyword: str = "",
    status: int | None = None,
    customer_id: int | None = None,
    customer_name: str = "",
    order_kind: str = "",
    order_category: str = "",
    order_type: str = "",
    order_channel: str = "",
    customer_source: str = "",
    owner_user_id: int | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
    creator_id: int | None = None,
    include_all: bool = True,
):
    q = db.query(DomesticOrder).filter(DomesticOrder.deleted_flag == 0)
    if order_kind:
        q = q.filter(DomesticOrder.order_kind == order_kind)
    if not include_all:
        q = q.filter(DomesticOrder.created_by == creator_id)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter((DomesticOrder.order_no.like(kw)) | (DomesticOrder.domestic_no.like(kw)))
    if status is not None:
        q = q.filter(DomesticOrder.status == status)
    if customer_id:
        q = q.filter(DomesticOrder.customer_id == customer_id)
    if customer_name.strip():
        q = q.filter(DomesticOrder.customer_id.in_(
            db.query(DomesticCustomer.id).filter(
                DomesticCustomer.shop_name.contains(customer_name.strip(), autoescape=True)
            )
        ))
    if order_category:
        q = q.filter(DomesticOrder.order_category == order_category)
    if order_type:
        q = q.filter(DomesticOrder.order_type == order_type)
    if order_channel:
        q = q.filter(DomesticOrder.order_channel == order_channel)
    if customer_source:
        q = q.filter(DomesticOrder.customer_id.in_(
            db.query(DomesticCustomer.id).filter(DomesticCustomer.customer_source == customer_source)
        ))
    if owner_user_id:
        q = q.filter(DomesticOrder.customer_id.in_(
            db.query(DomesticCustomer.id).filter(DomesticCustomer.owner_user_id == owner_user_id)
        ))
    if date_start:
        q = q.filter(DomesticOrder.order_date >= date_start)
    if date_end:
        q = q.filter(DomesticOrder.order_date <= date_end)

    return q
