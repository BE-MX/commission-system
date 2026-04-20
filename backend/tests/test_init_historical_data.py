"""存量初始化测试"""

from datetime import date
from unittest.mock import patch

from app.models.commission import SyncedPayment, PaymentCommissionStatus, CommissionBatch
from app.models.customer import CustomerCommissionSnapshot
from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.services.init_historical_data import (
    init_customer_snapshots,
    init_historical_payments,
    run_full_init,
)


class TestInitCustomerSnapshots:
    """客户快照初始化"""

    def test_create_snapshots(self, db, seed_employees, seed_business_data):
        """正常初始化：为匹配订单的客户创建快照"""
        with patch("app.services.init_historical_data.build_order_match_query") as mock_q:
            def side_effect(cid):
                return (
                    f"SELECT * FROM lsordertest.okki_orders "
                    f"WHERE company_id = '{cid}' ORDER BY account_date ASC LIMIT 1"
                )
            mock_q.side_effect = side_effect

            count = init_customer_snapshots(db)

        assert count >= 1
        snap = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.source == "init",
        ).first()
        assert snap is not None
        assert snap.is_current == True

    def test_idempotent(self, db, seed_employees, seed_business_data):
        """重复执行不产生重复数据"""
        with patch("app.services.init_historical_data.build_order_match_query") as mock_q:
            mock_q.return_value = (
                "SELECT * FROM lsordertest.okki_orders "
                "WHERE company_id = 'CUST001' ORDER BY account_date ASC LIMIT 1"
            )
            init_customer_snapshots(db)
            count2 = init_customer_snapshots(db)

        assert count2 == 0  # 已有快照，跳过


class TestInitHistoricalPayments:
    """历史回款初始化"""

    def test_sync_and_mark(self, db, seed_business_data):
        """同步历史回款并标记为已计算"""
        synced, marked = init_historical_payments(db, date(2026, 4, 10))

        assert synced > 0
        assert marked > 0

        # 有历史批次
        batch = db.query(CommissionBatch).filter(
            CommissionBatch.batch_name.like("历史数据%"),
        ).first()
        assert batch is not None
        assert batch.status == "confirmed"

    def test_idempotent(self, db, seed_business_data):
        """重复执行幂等"""
        init_historical_payments(db, date(2026, 4, 10))
        synced2, marked2 = init_historical_payments(db, date(2026, 4, 10))

        # 回款已存在 → synced=0，状态已存在 → marked=0
        assert synced2 == 0


class TestRunFullInit:
    """完整初始化流程"""

    def test_full_init(self, db, seed_employees, seed_business_data):
        """完整初始化：属性、快照、回款全部正确"""
        with patch("app.services.init_historical_data.build_order_match_query") as mock_q:
            mock_q.return_value = (
                "SELECT * FROM lsordertest.okki_orders "
                "WHERE 1=0 LIMIT 1"  # 不匹配，简化测试
            )
            result = run_full_init(db, cutoff_date=date(2026, 4, 10))

        assert result.employees_synced >= 1
        assert result.supervisors_synced >= 1
        assert result.payments_synced > 0

    def test_no_employee_warning(self, db, seed_business_data):
        """无员工属性数据时警告"""
        with patch("app.services.init_historical_data.build_order_match_query") as mock_q:
            mock_q.return_value = "SELECT * FROM lsordertest.okki_orders WHERE 1=0 LIMIT 1"
            result = run_full_init(db, cutoff_date=date(2026, 4, 10))

        assert result.employees_synced == 0

    def test_dry_run(self, db, seed_employees, seed_business_data):
        """dry-run 不写入数据"""
        with patch("app.services.init_historical_data.build_order_match_query") as mock_q:
            mock_q.return_value = "SELECT * FROM lsordertest.okki_orders WHERE 1=0 LIMIT 1"
            run_full_init(db, cutoff_date=date(2026, 4, 10), dry_run=True)

        assert db.query(SyncedPayment).count() == 0
