"""Stable local departments and auditable confirmation-time allocations."""
from sqlalchemy import select
from app.system.models import SysDict
from app.trade.models import SalesRoster
from app.trade.schemas import DepartmentShares

DEPARTMENT_TYPE = "sales_department"


def department_options(db):
    return [{"id": row.id, "name": row.label, "code": row.code} for row in db.scalars(
        select(SysDict).where(SysDict.type == DEPARTMENT_TYPE, SysDict.is_active.is_(True)).order_by(SysDict.sort, SysDict.id))]


def resolve_shares(db, entries):
    shares = DepartmentShares(department_allocations=entries).department_allocations
    if not shares:
        return []
    ids = sorted(item.department_id for item in shares)
    rows = {row.id: row for row in db.scalars(select(SysDict).where(SysDict.id.in_(ids)).order_by(SysDict.id)
        .with_for_update().execution_options(populate_existing=True))}
    if any(key not in rows or rows[key].type != DEPARTMENT_TYPE or not rows[key].is_active for key in ids):
        raise ValueError("部门不存在或已停用，请在本地销售部门字典中核对")
    return [{"department_id": item.department_id, "name": rows[item.department_id].label, "rate": str(item.rate)} for item in shares]


def freeze_departments(db, invoice):
    commercial = dict(invoice.local_commercial or {})
    if "departments" in commercial:
        return
    entries = commercial.get("department_allocations", [])
    if not entries:
        roster = db.scalar(select(SalesRoster).where(SalesRoster.ark_user_id == invoice.sales_user_id)
            .with_for_update().execution_options(populate_existing=True))
        if roster and roster.active and roster.department_id:
            entries = [{"department_id": roster.department_id, "rate": "100"}]
    commercial["departments"] = resolve_shares(db, entries)
    invoice.local_commercial = commercial


def assign_departments(db, invoice_id, body, actor):
    from app.invoice.commerce_service import _claim, _get, _version
    if not body.reason.strip() or not body.department_allocations:
        raise ValueError("请填写分摊部门和核验原因")
    with db.begin_nested():
        invoice = _get(db, invoice_id, actor)
        event, fresh = _claim(db, "department_attribution", body, actor, invoice_id)
        if not fresh:
            return invoice
        _version(invoice, body)
        if invoice.commerce_status in {"draft", "opening", "cancelled"}:
            raise ValueError("仅有效确认订单可核验部门归属")
        old = dict(invoice.local_commercial or {})
        values = resolve_shares(db, [item.model_dump(mode="json") for item in body.department_allocations])
        event.payload = {**event.payload, "before_departments": old.get("departments", []), "after_departments": values}
        invoice.local_commercial = {**old, "departments": values}
        invoice.commerce_version += 1
        db.flush()
        return invoice
