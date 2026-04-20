"""客户归属快照测试"""

import os
import tempfile
from datetime import date
from decimal import Decimal

from openpyxl import Workbook

from app.models.customer import CustomerCommissionSnapshot
from app.services.customer_reset_service import (
    reset_customer_attribution,
    complete_snapshot,
    import_snapshots_from_excel,
)


class TestCompleteSnapshot:
    """补全不完整快照"""

    def test_complete_success(self, db, seed_employees):
        """补全不完整快照 → is_complete=True，比例正确"""
        snap = CustomerCommissionSnapshot(
            customer_id="CUST001",
            salesperson_id="SP001",
            supervisor_id="SV001",
            is_complete=False, is_current=True, source="auto",
        )
        db.add(snap)
        db.flush()

        updated = complete_snapshot(db, snap.id, "develop", "develop", "admin")

        assert updated.is_complete == True
        assert updated.salesperson_attribute == "develop"
        assert updated.salesperson_rate == Decimal("0.0200")
        assert updated.supervisor_attribute == "develop"
        assert updated.supervisor_rate == Decimal("0.0150")  # 双开发
        assert updated.operator == "admin"


class TestResetAttribution:
    """人工重置归属"""

    def test_reset_creates_new_snapshot(self, db, seed_employees):
        """人工重置：旧快照失效，新快照生效"""
        old = CustomerCommissionSnapshot(
            customer_id="CUST001",
            salesperson_id="SP001",
            salesperson_attribute="develop",
            salesperson_rate=Decimal("0.0200"),
            supervisor_id="SV001",
            supervisor_attribute="develop",
            supervisor_rate=Decimal("0.0150"),
            is_complete=True, is_current=True, source="auto",
        )
        db.add(old)
        db.flush()

        new_snap = reset_customer_attribution(
            db,
            customer_id="CUST001",
            new_salesperson_id="SP002",
            new_supervisor_id="SV002",
            salesperson_attribute="distribute",
            supervisor_attribute="distribute",
            reason="客户转移",
            operator="admin",
        )

        # 旧快照失效
        db.refresh(old)
        assert old.is_current == False

        # 新快照
        assert new_snap.is_current == True
        assert new_snap.salesperson_id == "SP002"
        assert new_snap.is_manual_reset == True
        assert new_snap.source == "manual"
        assert new_snap.supervisor_rate == Decimal("0.0100")  # 分配+分配=1%


class TestExcelImport:
    """Excel 导入"""

    def _create_excel(self, rows):
        """创建临时 Excel 文件"""
        wb = Workbook()
        ws = wb.active
        ws.append(["客户ID", "业务员ID", "业务员属性", "业务主管ID", "主管属性"])
        for row in rows:
            ws.append(row)
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(path)
        return path

    def test_import_success(self, db, seed_employees, seed_business_data):
        """批量导入快照，已有的覆盖"""
        path = self._create_excel([
            ["CUST001", "SP001", "开发", "SV001", "开发"],
            ["CUST002", "SP002", "分配", "SV002", "分配"],
        ])
        try:
            result = import_snapshots_from_excel(db, path, "admin")
            assert result.success == 2
            assert result.failed == 0

            snap = db.query(CustomerCommissionSnapshot).filter(
                CustomerCommissionSnapshot.customer_id == "CUST001",
                CustomerCommissionSnapshot.is_current == True,
            ).first()
            assert snap.source == "import"
            assert snap.salesperson_rate == Decimal("0.0200")
        finally:
            os.unlink(path)

    def test_import_invalid_company(self, db, seed_employees, seed_business_data):
        """Excel 中 company_id 不存在 → 该行失败，不影响其他行"""
        path = self._create_excel([
            ["CUST001", "SP001", "开发", "SV001", "开发"],
            ["INVALID_CUST", "SP001", "开发", "SV001", "开发"],
        ])
        try:
            result = import_snapshots_from_excel(db, path, "admin")
            assert result.success == 1
            assert result.failed == 1
            assert "不存在" in result.failures[0]
        finally:
            os.unlink(path)

    def test_import_invalid_user(self, db, seed_employees, seed_business_data):
        """Excel 中 user_id 不存在 → 该行失败"""
        path = self._create_excel([
            ["CUST001", "INVALID_USER", "开发", "SV001", "开发"],
        ])
        try:
            result = import_snapshots_from_excel(db, path, "admin")
            assert result.failed == 1
            assert "不存在" in result.failures[0]
        finally:
            os.unlink(path)

    def test_import_overwrite_existing(self, db, seed_employees, seed_business_data):
        """导入时已有快照被覆盖"""
        db.add(CustomerCommissionSnapshot(
            customer_id="CUST001",
            salesperson_id="SP001",
            is_complete=True, is_current=True, source="auto",
        ))
        db.flush()

        path = self._create_excel([
            ["CUST001", "SP002", "分配", "SV002", "分配"],
        ])
        try:
            import_snapshots_from_excel(db, path, "admin")

            current_snaps = db.query(CustomerCommissionSnapshot).filter(
                CustomerCommissionSnapshot.customer_id == "CUST001",
                CustomerCommissionSnapshot.is_current == True,
            ).all()
            assert len(current_snaps) == 1
            assert current_snaps[0].salesperson_id == "SP002"
        finally:
            os.unlink(path)
