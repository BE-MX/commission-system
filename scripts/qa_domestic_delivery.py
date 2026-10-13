"""Local real-component QA server. All database and voucher writes stay in tmp."""
from pathlib import Path
import sys
from decimal import Decimal
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from app.core.database import get_db
from app.core.config import get_settings
from app.auth.dependencies import get_current_user
from app.domestic.router import router
from app.domestic.shipment_router import router as shipment_router
from app.domestic import unit_service, progress_service, balance_service, request_service
from app.domestic.models import DomesticOrder, DomesticOrderItem, DomesticItemProgress, DomesticCustomerRequest
from tests.conftest import engine as test_engine
from tests.test_domestic_conditional_routing import conditional_route, conditional_order
from tests.test_domestic_delivery import complete
from tests.test_domestic_review_flow import _user
from types import SimpleNamespace

# Use separate file connections for concurrent HTTP reads/writes; StaticPool is only
# appropriate for single-session service tests.
import sqlite3
from uuid import uuid4
from sqlalchemy import create_engine
source = test_engine.__wrapped__()
qa_root = ROOT / "tmp/domestic-delivery-evidence"
qa_root.mkdir(parents=True, exist_ok=True)
qa_path = qa_root / f"database-{uuid4().hex}.sqlite"
raw = source.raw_connection()
with sqlite3.connect(qa_path) as target:
    raw.driver_connection.backup(target)
raw.close()
source.dispose()
engine = create_engine(f"sqlite:///{qa_path.as_posix()}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine, autoflush=False)
db = Session()
route = conditional_route.__wrapped__(db)
ctx = conditional_order.__wrapped__(db, route)
customer = db.get(__import__("app.domestic.models", fromlist=["DomesticCustomer"]).DomesticCustomer,
                  db.get(DomesticOrder, ctx.item.order_id).customer_id)
customer.shop_name = "验收客户"
customer.owner_user_id = ctx.worker.id
customer.settle_mode = "credit"
reviewer = _user(db, "delivery-qa-reviewer")
orders = [db.get(DomesticOrder, ctx.item.order_id)]
for i in range(2):
    order = DomesticOrder(domestic_no=f"DO-QA-{i+2}", order_no=f"客户订单{i+2}", order_date=orders[0].order_date,
                          customer_id=customer.id, order_category="normal", created_by=ctx.worker.id,
                          total_unit_qty=300, item_count=30, next_line_no=31)
    db.add(order); db.flush(); orders.append(order)
for i in range(70):
    order = orders[min(i // 25, 2)]
    if i == 0:
        item = ctx.item
        item.order_qty = 10
        unit_service.sync_item_units(db, item, 10)
    else:
        item = DomesticOrderItem(order_id=order.id, line_no=i % 25 + 1, product_id=ctx.item.product_id,
                                product_name=f"头套型号-{i+1:02}", route_id=route.id, order_qty=10,
                                unit_price=Decimal(100), original_price=Decimal(100), discount_amount=0,
                                pricing_rule="legacy_manual", pricing_version="qa", base_price_version_snapshot=0)
        db.add(item); db.flush()
        progress_service.init_item_progress(db, item); unit_service.ensure_item_units(db, item)
    item.unit_price = Decimal(100); item.original_price = Decimal(100)
    item.guest_name = "张女士" if i == 30 else f"顾客{i+1:02}"
    complete(db, SimpleNamespace(item=item, worker=ctx.worker), 6)
for order in orders:
    balance_service.sync_order_finance(db, order, user_id=ctx.worker.id, reason="隔离验收")
db.commit()
settings = get_settings()
settings.DOMESTIC_STORAGE_ROOT = str(ROOT / "tmp/domestic-delivery-evidence/vouchers")
settings.COS_ENABLED_DOMAINS = []
settings.COS_MANAGED_DOMAINS = []
app = FastAPI()
app.include_router(router, prefix="/api/domestic")
app.include_router(shipment_router, prefix="/api/domestic")
def isolated_db():
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
app.dependency_overrides[get_db] = isolated_db
app.dependency_overrides[get_current_user] = lambda: {"sub": str(ctx.worker.id), "roles": ["super_admin"], "permissions": []}

@app.post("/qa/approve-latest")
def approve_latest():
    with Session() as session:
        req = session.query(DomesticCustomerRequest).filter_by(status="pending", request_type="receipt").order_by(DomesticCustomerRequest.id.desc()).first()
        return request_service.approve_request(session, req.id, reviewer_id=reviewer.id, can_admin=False)

@app.get("/qa/readback")
def readback():
    from app.domestic.shipment_models import DomesticShipmentUnit
    from app.domestic.models import DomesticCustomerLedger
    with Session() as session:
        return {"shipped_units": session.query(DomesticShipmentUnit).count(),
                "receipt_ledger_rows": session.query(DomesticCustomerLedger).filter_by(transaction_type="receipt").count()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")
