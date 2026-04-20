"""提成计算引擎测试"""

from datetime import date
from decimal import Decimal

from app.models.commission import (
    CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus,
)
from app.models.customer import CustomerCommissionSnapshot
from app.services.commission_calculator import (
    calculate_commission, void_batch, confirm_batch,
)


class TestCommissionCalculator:
    """提成计算测试"""

    def test_dual_develop(self, db, seed_employees, seed_synced_payments,
                          seed_complete_snapshot, seed_draft_batch):
        """业务员=开发，主管=开发，主管≠业务员 → 业务员2%，主管1.5%"""
        result = calculate_commission(db, seed_draft_batch.id)

        # CUST001 有 PAY001(3000) + PAY002(2000)
        details = db.query(CommissionDetail).filter(
            CommissionDetail.customer_id == "CUST001",
        ).all()
        assert len(details) == 2

        d1 = next(d for d in details if d.payment_id == "PAY001")
        assert d1.salesperson_rate == Decimal("0.0200")
        assert d1.salesperson_commission == Decimal("60.00")  # 3000 * 0.02
        assert d1.supervisor_commission == Decimal("45.00")   # 3000 * 0.015
        assert "双开发" in d1.calc_rule_note

    def test_distribute_distribute(self, db, seed_employees, seed_synced_payments,
                                   seed_complete_snapshot, seed_draft_batch):
        """业务员=分配，主管=分配 → 业务员2%，主管1%"""
        result = calculate_commission(db, seed_draft_batch.id)

        d = db.query(CommissionDetail).filter(
            CommissionDetail.customer_id == "CUST002",
        ).first()
        assert d is not None
        assert d.salesperson_commission == Decimal("100.00")  # 5000 * 0.02
        assert d.supervisor_commission == Decimal("50.00")    # 5000 * 0.01
        assert "主管1%" in d.calc_rule_note

    def test_supervisor_equals_salesperson(self, db, seed_employees, seed_synced_payments,
                                           seed_draft_batch):
        """主管=业务员（同一人） → 业务员2%，主管0%"""
        db.add(CustomerCommissionSnapshot(
            customer_id="CUST001",
            salesperson_id="SP001",
            salesperson_attribute="develop",
            salesperson_rate=Decimal("0.0200"),
            supervisor_id="SP001",  # 同一人
            supervisor_attribute="develop",
            supervisor_rate=Decimal("0"),
            is_complete=True, is_current=True, source="manual",
        ))
        db.flush()

        result = calculate_commission(db, seed_draft_batch.id)
        details = db.query(CommissionDetail).filter(
            CommissionDetail.customer_id == "CUST001",
        ).all()

        for d in details:
            assert d.supervisor_commission == Decimal("0")
            assert "仅计业务员提成" in d.calc_rule_note

    def test_skip_incomplete_snapshot(self, db, seed_employees, seed_synced_payments,
                                      seed_draft_batch):
        """归属不完整的客户回款 → 跳过"""
        db.add(CustomerCommissionSnapshot(
            customer_id="CUST001",
            salesperson_id="SP001",
            is_complete=False, is_current=True, source="auto",
        ))
        db.flush()

        result = calculate_commission(db, seed_draft_batch.id)
        assert result.skipped_incomplete == 2  # PAY001, PAY002

    def test_skip_no_snapshot(self, db, seed_employees, seed_synced_payments,
                              seed_draft_batch):
        """无归属快照的客户回款 → 跳过"""
        result = calculate_commission(db, seed_draft_batch.id)
        # CUST001, CUST002 都没有快照
        assert result.skipped_no_snapshot == 3

    def test_no_double_calculation(self, db, seed_employees, seed_synced_payments,
                                   seed_complete_snapshot, seed_draft_batch):
        """同一回款不被两个批次重复计算"""
        calculate_commission(db, seed_draft_batch.id)

        # 创建第二个批次
        batch2 = CommissionBatch(
            batch_name="2026-Q2-v2", period_type="quarterly",
            period_start=date(2026, 4, 1), period_end=date(2026, 6, 30),
            status="draft",
        )
        db.add(batch2)
        db.flush()

        result2 = calculate_commission(db, batch2.id)
        assert result2.total_payments == 0  # 全部已被 batch1 计算

    def test_void_then_recalculate(self, db, seed_employees, seed_synced_payments,
                                   seed_complete_snapshot, seed_draft_batch):
        """批次作废后回款释放，重新计算正确"""
        result1 = calculate_commission(db, seed_draft_batch.id)
        assert result1.total_payments > 0

        void_batch(db, seed_draft_batch.id)

        # 检查回款已释放
        pcs_count = db.query(PaymentCommissionStatus).filter(
            PaymentCommissionStatus.batch_id == seed_draft_batch.id,
        ).count()
        assert pcs_count == 0

        # 新批次可以重新计算
        batch2 = CommissionBatch(
            batch_name="2026-Q2-redo", period_type="quarterly",
            period_start=date(2026, 4, 1), period_end=date(2026, 6, 30),
            status="draft",
        )
        db.add(batch2)
        db.flush()

        result2 = calculate_commission(db, batch2.id)
        assert result2.total_payments == result1.total_payments

    def test_confirm_batch(self, db, seed_employees, seed_synced_payments,
                           seed_complete_snapshot, seed_draft_batch):
        """确认批次：状态变更正确"""
        calculate_commission(db, seed_draft_batch.id)
        confirm_batch(db, seed_draft_batch.id, "admin")

        batch = db.query(CommissionBatch).filter(
            CommissionBatch.id == seed_draft_batch.id,
        ).first()
        assert batch.status == "confirmed"
        assert batch.confirmed_by == "admin"

        details = db.query(CommissionDetail).filter(
            CommissionDetail.batch_id == seed_draft_batch.id,
        ).all()
        for d in details:
            assert d.status == "confirmed"

    def test_calc_result_totals(self, db, seed_employees, seed_synced_payments,
                                seed_complete_snapshot, seed_draft_batch):
        """CalcResult 汇总金额正确"""
        result = calculate_commission(db, seed_draft_batch.id)

        # CUST001: PAY001(3000*0.02=60), PAY002(2000*0.02=40) → sp=100
        # CUST002: PAY003(5000*0.02=100) → sp=100
        assert result.total_salesperson_commission == Decimal("200.00")

        # CUST001: 双开发 3000*0.015=45, 2000*0.015=30 → sv=75
        # CUST002: 主管1% 5000*0.01=50 → sv=50
        assert result.total_supervisor_commission == Decimal("125.00")
