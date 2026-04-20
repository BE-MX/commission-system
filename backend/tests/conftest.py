"""pytest 公共 fixtures：内存 SQLite 数据库 + 预填充数据"""

import pytest
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event, text, BigInteger, Integer
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.models.customer import CustomerCommissionSnapshot
from app.models.commission import (
    SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus,
)


# SQLite 不支持 BIGINT 自增，编译时替换为 INTEGER
from sqlalchemy.ext.compiler import compiles

@compiles(BigInteger, "sqlite")
def _compile_big_int_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def engine():
    """创建内存 SQLite 引擎，附加一个 schema 模拟跨库查询"""
    eng = create_engine("sqlite:///:memory:", echo=False)

    # SQLite 不支持 schema，用 ATTACH 模拟业务库
    @event.listens_for(eng, "connect")
    def _attach(dbapi_conn, _rec):
        dbapi_conn.execute("ATTACH DATABASE ':memory:' AS lsordertest")

    Base.metadata.create_all(eng)

    # 在 lsordertest schema 中创建业务库表
    with eng.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lsordertest.user_basic (
                user_id TEXT PRIMARY KEY,
                full_name TEXT,
                nickname TEXT,
                user_mobile TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lsordertest.customer_info (
                company_id TEXT PRIMARY KEY,
                company_name TEXT,
                country_name TEXT,
                origin_name TEXT,
                archive_type TEXT,
                trail_status_name TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lsordertest.okki_orders (
                order_id TEXT PRIMARY KEY,
                order_no TEXT,
                company_id TEXT,
                amount_usd REAL,
                user_id TEXT,
                custom_fields TEXT,
                account_date TEXT,
                trail TEXT,
                status TEXT,
                status_name TEXT,
                departments TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lsordertest.okki_receipts (
                cash_collection_id TEXT PRIMARY KEY,
                cash_collection_no TEXT,
                collection_date TEXT,
                type TEXT,
                amount_usd REAL,
                order_id TEXT,
                company_id TEXT,
                order_no TEXT,
                company_name TEXT
            )
        """))
        conn.commit()

    return eng


@pytest.fixture
def db(engine):
    """提供事务隔离的 Session，测试结束后回滚"""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def seed_employees(db):
    """预填充：员工属性 + 主管关系"""
    # 业务员 SP001 - 开发
    db.add(EmployeeAttributeHistory(
        employee_id="SP001", attribute_type="develop",
        effective_start=date(2025, 1, 1), is_current=True,
    ))
    # 业务员 SP002 - 分配
    db.add(EmployeeAttributeHistory(
        employee_id="SP002", attribute_type="distribute",
        effective_start=date(2025, 1, 1), is_current=True,
    ))
    # 主管 SV001 - 开发
    db.add(EmployeeAttributeHistory(
        employee_id="SV001", attribute_type="develop",
        effective_start=date(2025, 1, 1), is_current=True,
    ))
    # 主管 SV002 - 分配
    db.add(EmployeeAttributeHistory(
        employee_id="SV002", attribute_type="distribute",
        effective_start=date(2025, 1, 1), is_current=True,
    ))

    # SP001 的主管是 SV001
    db.add(SupervisorRelationHistory(
        salesperson_id="SP001", supervisor_id="SV001",
        effective_start=date(2025, 1, 1), is_current=True,
    ))
    # SP002 的主管是 SV002
    db.add(SupervisorRelationHistory(
        salesperson_id="SP002", supervisor_id="SV002",
        effective_start=date(2025, 1, 1), is_current=True,
    ))
    db.flush()


@pytest.fixture
def seed_business_data(db):
    """预填充：业务库数据（员工、客户、订单、回款）"""
    conn = db.get_bind().raw_connection()
    cur = conn.cursor()

    # 业务库员工
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.user_basic (user_id, full_name)
        VALUES ('SP001', '张三'), ('SP002', '李四'), ('SV001', '王主管'), ('SV002', '赵主管')
    """)

    # 业务库客户
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.customer_info (company_id, company_name)
        VALUES ('CUST001', '客户A'), ('CUST002', '客户B'), ('CUST003', '客户C')
    """)

    # 业务库订单 —— 用 raw cursor 避免 text() 解析 JSON 中的 :24925 为绑定参数
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.okki_orders
        (order_id, order_no, company_id, amount_usd, user_id, account_date, custom_fields, status, status_name, departments)
        VALUES
        ('ORD001', 'NO001', 'CUST001', 10000, 'SP001', '2026-03-15',
         '{"22595163468": "是", "691123983470": "定制品"}', '13972831656', NULL,
         '{"id":24925}'),
        ('ORD002', 'NO002', 'CUST002', 5000, 'SP002', '2026-03-20',
         '{"22595163468": "是", "691123983470": "定制品"}', '13972831654', '已结清',
         '{"id":24926}'),
        ('ORD003', 'NO003', 'CUST003', 8000, 'SP001', '2026-04-01',
         '{}', '999', NULL, '{}')
    """)

    # 业务库回款
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.okki_receipts
        (cash_collection_id, collection_date, amount_usd, order_id, company_id, order_no, company_name)
        VALUES
        ('PAY001', '2026-04-01', 3000.00, 'ORD001', 'CUST001', 'NO001', '客户A'),
        ('PAY002', '2026-04-05', 2000.00, 'ORD001', 'CUST001', 'NO001', '客户A'),
        ('PAY003', '2026-04-10', 5000.00, 'ORD002', 'CUST002', 'NO002', '客户B'),
        ('PAY004', '2026-04-15', 4000.00, 'ORD003', 'CUST003', 'NO003', '客户C')
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def seed_complete_snapshot(db, seed_employees):
    """预填充：CUST001 的完整归属快照（SP001-开发, SV001-开发 → 双开发）"""
    db.add(CustomerCommissionSnapshot(
        customer_id="CUST001",
        first_order_id="ORD001",
        first_order_date=date(2026, 3, 15),
        salesperson_id="SP001",
        salesperson_attribute="develop",
        salesperson_rate=Decimal("0.0200"),
        supervisor_id="SV001",
        supervisor_attribute="develop",
        supervisor_rate=Decimal("0.0150"),
        is_complete=True,
        is_current=True,
        source="auto",
    ))
    # CUST002: SP002-分配, SV002-分配
    db.add(CustomerCommissionSnapshot(
        customer_id="CUST002",
        first_order_id="ORD002",
        salesperson_id="SP002",
        salesperson_attribute="distribute",
        salesperson_rate=Decimal("0.0200"),
        supervisor_id="SV002",
        supervisor_attribute="distribute",
        supervisor_rate=Decimal("0.0100"),
        is_complete=True,
        is_current=True,
        source="auto",
    ))
    db.flush()


@pytest.fixture
def seed_synced_payments(db):
    """预填充：已同步的回款"""
    for pid, oid, cid, pdate, amt in [
        ("PAY001", "ORD001", "CUST001", date(2026, 4, 1), Decimal("3000.00")),
        ("PAY002", "ORD001", "CUST001", date(2026, 4, 5), Decimal("2000.00")),
        ("PAY003", "ORD002", "CUST002", date(2026, 4, 10), Decimal("5000.00")),
    ]:
        db.add(SyncedPayment(
            payment_id=pid, order_id=oid, customer_id=cid,
            payment_date=pdate, payment_amount=amt,
        ))
    db.flush()


@pytest.fixture
def seed_draft_batch(db):
    """预填充：一个 draft 状态的批次"""
    batch = CommissionBatch(
        batch_name="2026-Q2",
        period_type="quarterly",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        status="draft",
    )
    db.add(batch)
    db.flush()
    return batch
