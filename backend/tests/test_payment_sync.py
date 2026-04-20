"""回款同步服务测试"""

from datetime import date
from unittest.mock import patch

from app.models.commission import SyncedPayment
from app.models.customer import CustomerCommissionSnapshot
from app.services.payment_sync_service import sync_payments


class TestPaymentSync:
    """回款同步测试"""

    def test_new_payment_sync(self, db, seed_employees, seed_business_data):
        """新回款同步：synced_payment 新增记录，字段映射正确"""
        result = sync_payments(db, date(2026, 4, 1), date(2026, 4, 15))

        assert result.total_payments == 4
        assert result.new_synced == 4
        assert result.already_synced == 0

        # 验证字段映射
        sp = db.query(SyncedPayment).filter(SyncedPayment.payment_id == "PAY001").first()
        assert sp is not None
        assert sp.order_id == "ORD001"
        assert sp.customer_id == "CUST001"
        assert sp.payment_date == date(2026, 4, 1)
        assert float(sp.payment_amount) == 3000.00

    def test_idempotent_sync(self, db, seed_employees, seed_business_data):
        """重复同步不产生重复记录"""
        sync_payments(db, date(2026, 4, 1), date(2026, 4, 15))
        result2 = sync_payments(db, date(2026, 4, 1), date(2026, 4, 15))

        assert result2.new_synced == 0
        assert result2.already_synced == 4

        total = db.query(SyncedPayment).count()
        assert total == 4  # 不重复

    def test_customer_with_existing_snapshot(self, db, seed_employees, seed_business_data):
        """客户已有归属快照，跳过不重复生成"""
        # 预先给 CUST001 建快照
        db.add(CustomerCommissionSnapshot(
            customer_id="CUST001",
            salesperson_id="SP001",
            is_complete=True, is_current=True, source="manual",
        ))
        db.flush()

        result = sync_payments(db, date(2026, 4, 1), date(2026, 4, 15))

        # CUST001 的快照应该只有一条
        snaps = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.customer_id == "CUST001",
            CustomerCommissionSnapshot.is_current == True,
        ).count()
        assert snaps == 1

    def test_auto_snapshot_with_matching_order(self, db, seed_employees, seed_business_data):
        """客户无快照，匹配到订单 → 自动生成完整快照"""
        # CUST001 有匹配订单 ORD001 (符合 custom_fields / status / dept 规则)
        # 用 mock 让 build_order_match_query 返回能匹配 SQLite 的 SQL
        with patch("app.services.payment_sync_service.build_order_match_query") as mock_q:
            mock_q.return_value = (
                "SELECT * FROM lsordertest.okki_orders "
                "WHERE company_id = 'CUST001' ORDER BY account_date ASC LIMIT 1"
            )
            result = sync_payments(db, date(2026, 4, 1), date(2026, 4, 5))

        snap = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.customer_id == "CUST001",
            CustomerCommissionSnapshot.is_current == True,
        ).first()
        assert snap is not None
        assert snap.is_complete == True
        assert snap.salesperson_id == "SP001"
        assert snap.source == "auto"
        assert result.snapshots_auto_created >= 1

    def test_incomplete_snapshot_no_matching_order(self, db, seed_employees, seed_business_data):
        """客户无快照，匹配不到订单 → 生成不完整快照"""
        # CUST003 的订单不符合规则
        with patch("app.services.payment_sync_service.build_order_match_query") as mock_q:
            # 返回一定查不到的 SQL
            mock_q.return_value = (
                "SELECT * FROM lsordertest.okki_orders "
                "WHERE company_id = 'CUST003' AND 1=0 LIMIT 1"
            )
            result = sync_payments(db, date(2026, 4, 15), date(2026, 4, 15))

        snap = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.customer_id == "CUST003",
            CustomerCommissionSnapshot.is_current == True,
        ).first()
        assert snap is not None
        assert snap.is_complete == False
        assert snap.salesperson_id == "SP001"  # 从 ORD003 取到 user_id
        assert "CUST003" in result.incomplete_customers
