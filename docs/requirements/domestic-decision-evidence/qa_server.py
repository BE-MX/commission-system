"""Local acceptance server: synthetic SQLite only, no production connections.

Run from repository root: python docs/requirements/domestic-decision-evidence/qa_server.py
The real decision API serves the built frontend on http://127.0.0.1:8791.
Browser localStorage ark_access_token=qa-full or qa-sales selects synthetic roles.
"""
import json
import sys
from uuid import uuid4
from datetime import timedelta, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
# Reuse isolated SQLite type compilers, never its business database settings.
import conftest  # noqa: E402
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.core.database import Base, get_db
from app.core.time import beijing_today
from app.core.response import ok
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.domestic.models import DomesticCustomer, DomesticProduct, DomesticOrder, DomesticOrderItem, DomesticCustomerLedger, DomesticCustomerRequest
from app.domestic_decision.models import DecisionConfig, DecisionMapping
from app.domestic_decision.router import router
from app.domestic_decision import job_service, scope
from app.system.models import SysDict
from app.ai import service as ai_service


def offline_chat(*args, **kwargs):
    raise RuntimeError("Isolated acceptance disables external AI calls")


ai_service.chat = offline_chat

# Separate connections for concurrent HTTP/background requests, just as in the
# application. A shared in-memory connection lets unrelated rollback/commit
# operations interfere with each other and is unsuitable for browser acceptance.
database_path = ROOT / "tmp" / f"domestic-decision-qa-{uuid4().hex}.sqlite"
database_path.parent.mkdir(exist_ok=True)
engine = create_engine(f"sqlite:///{database_path.as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})
tables = {table for table in Base.metadata.tables.values() if table.name.startswith("ark_domestic_") or table.name in {"ark_users", "ark_roles", "ark_permissions", "ark_user_roles", "ark_role_permissions", SysDict.__tablename__}}
while True:
    extended = tables | {foreign.column.table for table in tables for foreign in table.foreign_keys}
    if extended == tables:
        break
    tables = extended
seen = set()
for table in sorted(tables, key=lambda value: value.name):
    for index in list(table.indexes):
        if index.name in seen:
            table.indexes.remove(index)
        else:
            seen.add(index.name)
Base.metadata.create_all(engine, tables=list(tables))
Session = sessionmaker(bind=engine, expire_on_commit=False)
job_service.SessionLocal = Session


def seed():
    with Session() as db:
        users = [ArkUser(username="qa-full", real_name="隔离验收主管", password_hash="unused"), ArkUser(username="qa-sales", real_name="隔离验收业务员", password_hash="unused")]
        roles = [ArkRole(name="qa-full", label="验收主管"), ArkRole(name="qa-sales", label="验收业务员")]
        db.add_all(users + roles)
        db.flush()
        for user, role in zip(users, roles):
            db.add(ArkUserRole(user_id=user.id, role_id=role.id))
        codes = ["domestic_decision:read", "domestic_decision:read_all", "domestic_decision_finance:read", "domestic_decision_action:write", "domestic_decision_report:write", "domestic_decision:admin"]
        for code in codes:
            permission = ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
            db.add(permission)
            db.flush()
            db.add(ArkRolePermission(role_id=roles[0].id, permission_id=permission.id))
            if code in {"domestic_decision:read", "domestic_decision_action:write", "domestic_decision_report:write"}:
                db.add(ArkRolePermission(role_id=roles[1].id, permission_id=permission.id))
        today = beijing_today()
        db.add_all([DecisionConfig(key="coverage_start", value=(today - timedelta(days=400)).isoformat()), DecisionConfig(key="aftersales_order_types", value=["aftersales"])])
        for property, raw, standard in [("color", "red", "红色"), ("color", "black", "黑色")]:
            db.add(DecisionMapping(property=property, product_type="", raw_value=raw, standard_value=standard, updated_by=users[0].id))
        for kind, values in {"domestic_order_type": [("normal", "常规"), ("aftersales", "售后重做")], "domestic_order_channel": [("wechat", "微信"), ("offline", "门店")], "domestic_customer_lifecycle": [("active", "正常经营"), ("closed", "停止联系")]}.items():
            for index, (code, label) in enumerate(values):
                db.add(SysDict(type=kind, code=code, label=label, sort=index))
        products = [DomesticProduct(attrs_key=f"qa-product-{i}", name="验收头套" if i == 0 else "验收发块", product_type="cap" if i == 0 else "piece", craft="蕾丝" if i == 0 else "U型13*15", length="15厘米") for i in range(2)]
        db.add_all(products)
        db.flush()
        db.add_all([DecisionMapping(property="craft", product_type="piece", raw_value="U型13*15", standard_value="U型", updated_by=users[0].id), DecisionMapping(property="size", product_type="piece", raw_value="U型13*15", standard_value="13*15", updated_by=users[0].id)])
        names = ["杭州青禾", "广州星悦", "成都拾光", "南京若木", "武汉素颜", "西安锦色"]
        for index in range(36):
            owner = users[index % 2]
            customer = DomesticCustomer(shop_name=f"{names[index % 6]}门店{index + 1:02}", owner_user_id=owner.id, created_by=owner.id, province=["浙江", "广东", "四川"][index % 3], city=["杭州", "广州", "成都"][index % 3], store_type="salon", customer_source="exhibition", lifecycle_status="active", status=1, balance=0, settle_mode="credit" if index % 7 == 0 else "prepay", membership_level="silver", total_sales_amount=50000, total_order_count=30, first_order_date=today - timedelta(days=300))
            db.add(customer)
            db.flush()
            balance = 0
            def entry(kind, amount, day, order_id=None):
                nonlocal balance
                db.add(DomesticCustomerLedger(customer_id=customer.id, order_id=order_id, transaction_type=kind, amount=amount, balance_before=balance, balance_after=balance + amount, business_key=f"qa-{customer.id}-{kind}-{day}-{order_id}", created_by=owner.id, created_at=datetime.combine(day, time(10))))
                balance += amount
            if customer.settle_mode == "prepay":
                entry("init", 35000, today - timedelta(days=260))
            offsets = [220, 180, 150, 120, 90, 60, 40, 25, 12, 4]
            if index % 5 == 0:
                offsets = offsets[:7]  # historical-only risk candidates
            for ordinal, offset in enumerate(offsets):
                day = today - timedelta(days=offset + index % 3)
                qty = 1 + (index + ordinal) % 3
                price = 850 + 50 * (ordinal % 4)
                amount = qty * price + 600
                order = DomesticOrder(domestic_no=f"QA{index:02}{ordinal:03}", order_no=f"QA{index:02}{ordinal:03}", customer_id=customer.id, order_date=day, order_category="normal", order_type="normal", order_channel="wechat" if ordinal % 2 else "offline", status=3 if ordinal < 6 else 1, total_amount=amount, charged_amount=amount, created_by=users[1].id)
                db.add(order)
                db.flush()
                for line, product in enumerate(products, 1):
                    attrs = {"product_type": product.product_type, "craft": product.craft, "size": "M", "length": "15厘米", "density": "120", "net_color": "棕网", "hair_style_series": "直发"}
                    db.add(DomesticOrderItem(order_id=order.id, line_no=line, product_id=product.id, product_name=product.name, order_qty=qty if line == 1 else 1, unit_price=price if line == 1 else 600, original_price=price if line == 1 else 600, discount_amount=0, labor_fee=0, pricing_rule="base_price", pricing_version="qa-v1", base_price_version_snapshot=1, membership_level_snapshot="silver", attrs_snapshot=attrs, color="red" if (index + ordinal + line) % 2 else "black"))
                entry("order_charge", -amount, day, order.id)
            if customer.settle_mode == "prepay":
                entry("recharge", 1000, today - timedelta(days=2))
            customer.balance = balance
            if index % 9 == 0:
                db.add(DomesticCustomerRequest(customer_id=customer.id, request_type="recharge", amount=3000, status="pending", request_id=f"qa-request-{index}", business_key=f"qa-request-{index}", created_by=owner.id))
        db.commit()
        return {user.username: user.id for user in users}


USER_IDS = seed()
app = FastAPI(title="Domestic decision isolated acceptance")


def qa_db():
    with Session() as db:
        yield db


def qa_user(request: Request):
    token = request.headers.get("authorization", "Bearer qa-full").removeprefix("Bearer ")
    if token not in USER_IDS:
        raise HTTPException(401, "隔离验收账户不存在")
    return {"sub": str(USER_IDS[token])}


app.dependency_overrides[get_db] = qa_db
app.dependency_overrides[get_current_user] = qa_user
app.include_router(router, prefix="/api/domestic-decision")


@app.get("/api/auth/me")
def me(request: Request):
    with Session() as db:
        actor = scope.live_actor(db, qa_user(request))
        user = db.get(ArkUser, actor["id"])
        return {**actor, "real_name": user.real_name, "username": user.username}


@app.post("/api/auth/refresh")
def refresh():
    return {"access_token": "qa-full"}


@app.get("/api/health")
def health():
    return {"isolation": "Isolated temporary SQLite; synthetic records only", "customers": 36}


@app.get("/api/{path:path}")
def auxiliary(path: str):
    # Shell badges are not part of the domain under test.
    return ok({"items": [], "total": 0, "unread_count": 0, "count": 0})


dist = ROOT / "frontend" / "dist"
if (dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    candidate = (dist / path).resolve()
    if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    # Only this synthetic loopback preview bootstraps a fictional role. The
    # production HTML and authentication code are served unchanged by the app.
    document = (dist / "index.html").read_text(encoding="utf-8")
    bootstrap = "<script>if(!['qa-full','qa-sales'].includes(localStorage.getItem('ark_access_token')))localStorage.setItem('ark_access_token','qa-full');</script>"
    return HTMLResponse(document.replace("<head>", "<head>" + bootstrap, 1))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8791)
