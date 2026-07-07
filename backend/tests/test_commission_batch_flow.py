"""提成批次状态机回归测试

状态流：draft → calculated → confirming → confirmed / voided
直接调用 service 层函数（app/services/commission_calculator.py），绕过 HTTP 层：
- calculate_commission: 仅 draft 可计算
- send_confirm:         仅 calculated 可发送确认（→ confirming）
- revoke_confirm:       仅 confirming 可撤销（→ calculated）
- confirm_batch:        calculated / confirming 可确认（→ confirmed）
- void_batch:           calculated / confirming 可作废（→ voided）
- confirmed / voided 均为终态

API 路由层（app/api/commission.py）只是薄封装 + db.commit()，状态校验全部在
service 层，因此这里覆盖 service 即覆盖状态机核心。
"""

from datetime import date

import pytest

# 注册 ark_users 等表到 Base.metadata，供 send_confirm 内部的 ArkUser 查询使用
import app.auth.models  # noqa: F401

from app.models.commission import (
    CommissionBatch, CommissionDetail, PaymentCommissionStatus,
)
from app.services.commission_calculator import (
    calculate_commission, confirm_batch, revoke_confirm, send_confirm, void_batch,
)


def _make_batch(db, status: str) -> CommissionBatch:
    batch = CommissionBatch(
        batch_name=f"flow-{status}",
        period_type="quarterly",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        status=status,
    )
    db.add(batch)
    db.flush()
    return batch


class TestDraftTransitions:
    """draft 状态：只能 calculate，其余操作全部拒绝"""

    def test_draft_cannot_confirm(self, db):
        batch = _make_batch(db, "draft")
        with pytest.raises(ValueError, match="draft"):
            confirm_batch(db, batch.id, "admin")
        assert batch.status == "draft"

    def test_draft_cannot_send_confirm(self, db):
        batch = _make_batch(db, "draft")
        with pytest.raises(ValueError, match="calculated"):
            send_confirm(db, batch.id)
        assert batch.status == "draft"

    def test_draft_cannot_revoke_confirm(self, db):
        batch = _make_batch(db, "draft")
        with pytest.raises(ValueError, match="confirming"):
            revoke_confirm(db, batch.id)
        assert batch.status == "draft"

    def test_draft_cannot_void(self, db):
        batch = _make_batch(db, "draft")
        with pytest.raises(ValueError, match="draft"):
            void_batch(db, batch.id)
        assert batch.status == "draft"


class TestCalculatedTransitions:
    """calculated：可 send_confirm / confirm / void，不可再 calculate / revoke"""

    def test_calculated_cannot_recalculate(self, db):
        batch = _make_batch(db, "calculated")
        with pytest.raises(ValueError, match="draft"):
            calculate_commission(db, batch.id)
        assert batch.status == "calculated"

    def test_calculated_cannot_revoke_confirm(self, db):
        batch = _make_batch(db, "calculated")
        with pytest.raises(ValueError, match="confirming"):
            revoke_confirm(db, batch.id)
        assert batch.status == "calculated"

    def test_send_confirm_moves_to_confirming(self, db):
        batch = _make_batch(db, "calculated")
        result = send_confirm(db, batch.id)
        assert batch.status == "confirming"
        assert result["batch_name"] == batch.batch_name
        assert result["dingtalk_ids"] == []  # 无明细 → 无通知对象

    def test_calculated_can_confirm_directly(self, db):
        batch = _make_batch(db, "calculated")
        confirm_batch(db, batch.id, "admin")
        assert batch.status == "confirmed"
        assert batch.confirmed_by == "admin"
        assert batch.confirmed_at is not None

    def test_calculated_can_void(self, db):
        batch = _make_batch(db, "calculated")
        void_batch(db, batch.id)
        assert batch.status == "voided"


class TestConfirmingTransitions:
    """confirming：可 revoke（回 calculated）/ confirm / void，不可 calculate / send"""

    def test_revoke_returns_to_calculated(self, db):
        batch = _make_batch(db, "confirming")
        revoke_confirm(db, batch.id)
        assert batch.status == "calculated"

    def test_confirming_can_confirm(self, db):
        batch = _make_batch(db, "confirming")
        confirm_batch(db, batch.id, "boss")
        assert batch.status == "confirmed"

    def test_confirming_can_void(self, db):
        batch = _make_batch(db, "confirming")
        void_batch(db, batch.id)
        assert batch.status == "voided"

    def test_confirming_cannot_recalculate(self, db):
        batch = _make_batch(db, "confirming")
        with pytest.raises(ValueError, match="draft"):
            calculate_commission(db, batch.id)

    def test_confirming_cannot_send_confirm_again(self, db):
        batch = _make_batch(db, "confirming")
        with pytest.raises(ValueError, match="calculated"):
            send_confirm(db, batch.id)
        assert batch.status == "confirming"


class TestConfirmedTerminal:
    """confirmed 为终态：任何迁移都拒绝"""

    def test_confirmed_cannot_recalculate(self, db):
        batch = _make_batch(db, "confirmed")
        with pytest.raises(ValueError, match="draft"):
            calculate_commission(db, batch.id)

    def test_confirmed_cannot_send_confirm(self, db):
        batch = _make_batch(db, "confirmed")
        with pytest.raises(ValueError):
            send_confirm(db, batch.id)
        assert batch.status == "confirmed"

    def test_confirmed_cannot_revoke_confirm(self, db):
        batch = _make_batch(db, "confirmed")
        with pytest.raises(ValueError):
            revoke_confirm(db, batch.id)
        assert batch.status == "confirmed"

    def test_confirmed_cannot_void(self, db):
        batch = _make_batch(db, "confirmed")
        with pytest.raises(ValueError):
            void_batch(db, batch.id)
        assert batch.status == "confirmed"

    def test_confirmed_cannot_confirm_again(self, db):
        batch = _make_batch(db, "confirmed")
        with pytest.raises(ValueError):
            confirm_batch(db, batch.id, "admin")


class TestVoidedTerminal:
    """voided 为终态：任何迁移都拒绝"""

    @pytest.mark.parametrize("op", ["calculate", "send", "revoke", "confirm", "void"])
    def test_voided_rejects_all_transitions(self, db, op):
        batch = _make_batch(db, "voided")
        with pytest.raises(ValueError):
            if op == "calculate":
                calculate_commission(db, batch.id)
            elif op == "send":
                send_confirm(db, batch.id)
            elif op == "revoke":
                revoke_confirm(db, batch.id)
            elif op == "confirm":
                confirm_batch(db, batch.id, "admin")
            else:
                void_batch(db, batch.id)
        assert batch.status == "voided"


class TestMissingBatch:
    """不存在的批次 ID：所有操作都报『不存在』"""

    @pytest.mark.parametrize("fn", [
        lambda db: calculate_commission(db, 999999),
        lambda db: send_confirm(db, 999999),
        lambda db: revoke_confirm(db, 999999),
        lambda db: confirm_batch(db, 999999, "admin"),
        lambda db: void_batch(db, 999999),
    ])
    def test_missing_batch_raises(self, db, fn):
        with pytest.raises(ValueError, match="不存在"):
            fn(db)


class TestFullLifecycle:
    """完整生命周期：draft → calculated → confirming → confirmed（带真实明细）"""

    def test_happy_path(self, db, seed_employees, seed_synced_payments,
                        seed_complete_snapshot, seed_draft_batch):
        batch = seed_draft_batch
        assert batch.status == "draft"

        result = calculate_commission(db, batch.id)
        assert batch.status == "calculated"
        assert result.total_payments == 3

        send_result = send_confirm(db, batch.id)
        assert batch.status == "confirming"
        # ark_users 表为空 → 通知列表为空，但不报错
        assert send_result["dingtalk_ids"] == []

        confirm_batch(db, batch.id, "finance")
        assert batch.status == "confirmed"
        details = db.query(CommissionDetail).filter(
            CommissionDetail.batch_id == batch.id,
        ).all()
        assert details and all(d.status == "confirmed" for d in details)

    def test_void_from_confirming_releases_payments(self, db, seed_employees,
                                                    seed_synced_payments,
                                                    seed_complete_snapshot,
                                                    seed_draft_batch):
        batch = seed_draft_batch
        calculate_commission(db, batch.id)
        send_confirm(db, batch.id)
        assert batch.status == "confirming"

        void_batch(db, batch.id)
        assert batch.status == "voided"
        # 回款释放
        assert db.query(PaymentCommissionStatus).filter(
            PaymentCommissionStatus.batch_id == batch.id,
        ).count() == 0
        # 明细标记 voided
        details = db.query(CommissionDetail).filter(
            CommissionDetail.batch_id == batch.id,
        ).all()
        assert details and all(d.status == "voided" for d in details)
