"""A native case can close only after its promised executions are evidenced."""
from decimal import Decimal
from sqlalchemy import select
from app.aftersales.models import AfterSalesCase, AfterSalesExecution, AfterSalesReview
from app.finance import service as finance
from app.invoice.models import Invoice, InvoiceItem


def lock_execution_scope(db, case_id):
    seed = db.get(AfterSalesCase, case_id)
    if seed is not None and seed.local_invoice_item_id is not None:
        finance.book(db)
        line = db.get(InvoiceItem, seed.local_invoice_item_id)
        if line is None:
            raise ValueError("本地售后商品身份缺失")
        finance.lock(db, Invoice, line.invoice_id)


def ensure_completed(db, case):
    if case.local_invoice_item_id is None:
        return
    from app.aftersales.local_money import ensure_money_completed
    ensure_money_completed(db, case)
    facts = db.scalars(select(AfterSalesExecution).where(AfterSalesExecution.case_id == case.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    actions = case.selected_actions_json or []
    if case.requires_return or any(a.get("code") == "return_inspection" for a in actions):
        received = sum(f.quantity for f in facts if f.action == "return_receive")
        if received < case.quantity:
            raise ValueError("退货尚未收齐，不能仅凭执行文字结案")
    replacement_actions = [a for a in actions if a.get("code") in {"replacement", "resend"}]
    if replacement_actions:
        review = db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id,
            AfterSalesReview.workflow_round == case.workflow_round, AfterSalesReview.decision == "approve",
            AfterSalesReview.reviewer_role == "director").order_by(AfterSalesReview.id.desc()).limit(1).with_for_update())
        approved = (review.compensation_snapshot_json or {}).get("actions", []) if review else []
        if [a for a in approved if a.get("code") in {"replacement", "resend"}] != replacement_actions:
            raise ValueError("补发方案缺少最终批准凭证")
        for action in replacement_actions:
            dispatched = 0
            for fact in facts:
                if fact.action == action["code"] and fact.payload.get("local_sku_id") == action.get("local_sku_id"):
                    invoice = finance.lock(db, Invoice, fact.related_invoice_id)
                    if invoice and invoice.commerce_status in {"shipped", "completed"}:
                        dispatched += fact.quantity
            if dispatched != Decimal(str(action["quantity"])):
                raise ValueError("补发或重做尚未完成全部检验出库，不能结案")
    if facts and not case.execution_result:
        case.execution_result = "已核对本地执行凭证：" + ", ".join(str(f.id) for f in facts)
