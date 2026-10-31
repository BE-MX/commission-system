"""Audited currency/account administration and irreversible period closure."""
from sqlalchemy import select
from app.core.time import beijing_today
from app.finance.models import Currency, BankAccount
from app.finance.service import book, claim, _version


def write_currency(db, body, user):
    with db.begin_nested():
        book(db)
        event, fresh = claim(db, "currency", None, body, user, beijing_today())
        row = db.scalar(select(Currency).where(Currency.code == body.code).with_for_update()
                        .execution_options(populate_existing=True))
        if not fresh:
            return row
        if body.code == "CNY" and body.rate_to_cny != 1:
            raise ValueError("人民币兑人民币汇率必须为1")
        before = None if row is None else {"rate_to_cny": str(row.rate_to_cny), "active": row.active, "name": row.name}
        if row is None:
            row = Currency(code=body.code)
            db.add(row)
        row.name, row.rate_to_cny, row.active = body.name, body.rate_to_cny, int(body.active)
        event.payload = {**event.payload, "before": before}
        db.flush()
        return row


def write_account(db, body, user):
    with db.begin_nested():
        book(db)
        event, fresh = claim(db, "bank_account", None, body, user, beijing_today())
        row = db.scalar(select(BankAccount).where(BankAccount.code == body.code).with_for_update()
                        .execution_options(populate_existing=True))
        if not fresh:
            return row
        currency = db.scalar(select(Currency).where(Currency.code == body.currency).with_for_update())
        if currency is None or not currency.active:
            raise ValueError("请选择已启用的币种")
        if row is not None and row.currency != body.currency:
            raise ValueError("银行账户币种不可修改，请新建账户")
        before = None if row is None else {"name": row.name, "active": row.active}
        if row is None:
            row = BankAccount(code=body.code, currency=body.currency)
            db.add(row)
        row.name, row.active = body.name, int(body.active)
        event.payload = {**event.payload, "before": before}
        db.flush()
        return row


def close_period(db, body, user):
    with db.begin_nested():
        ledger = book(db)
        event, fresh = claim(db, "close_period", 1, body, user, body.business_date)
        if not fresh:
            return ledger
        _version(ledger, body.expected_version)
        if body.business_date >= beijing_today():
            raise ValueError("只能关闭已结束的业务日期")
        if ledger.closed_through and body.business_date <= ledger.closed_through:
            raise ValueError("结账日期只能向后推进")
        event.payload = {**event.payload, "previous_closed_through": str(ledger.closed_through) if ledger.closed_through else None}
        ledger.closed_through = body.business_date
        ledger.version += 1
        db.flush()
        return ledger
