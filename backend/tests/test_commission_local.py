"""Native commission follows frozen entitlement and original-event dependencies."""
from datetime import date, datetime
from decimal import Decimal
import pytest
from sqlalchemy import select

from app.commission.models import CommissionBasis, CommissionEventProjection
from app.commission.service import resolve
from app.finance import service as finance_service
from app.finance.models import FinanceEvent
from app.finance.schemas import AllocationCreate
from app.models.customer import CustomerCommissionSnapshot
from app.models.commission import CommissionBatch, CommissionDetail, SyncedPayment
from app.services.commission_calculator import calculate_commission, confirm_batch, void_batch
from tests.test_finance_local import finance, payment, cmd, order
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock

DAY = date(2026, 10, 3)


def snapshot(db, customer, user, **changes):
    row = CustomerCommissionSnapshot(customer_id=f"ark:{customer.id}", salesperson_id=f"ark:{user['sub']}",
        salesperson_attribute="develop", salesperson_rate=Decimal("0.02"), is_complete=True, is_current=True,
        operated_at=datetime(2026, 10, 3, 9), created_at=datetime(2026, 10, 3, 9), updated_at=datetime(2026, 10, 3, 9), **changes)
    db.add(row)
    db.flush()
    return row


def allocate(db, finance, stock, buyer, amount="1.00"):
    customer, user, bank = finance
    invoice, target = order(db, stock, buyer)
    cash = finance_service.register(db, payment(customer, bank), user)
    finance_service.confirm(db, cash.id, cmd("cash-confirm", 1), user)
    receipt = finance_service.allocate(db, cash.id, AllocationCreate(request_key="allocate", expected_version=2,
        invoice_id=invoice.id, receivable_id=target.id, amount=amount, business_date=DAY), user)
    return receipt, db.scalar(select(CommissionBasis))


def batch(db, name, start=DAY):
    row = CommissionBatch(batch_name=name, period_start=start, period_end=date(2026, 10, 31), status="draft")
    db.add(row)
    db.flush()
    return row


def test_snapshot_drift_and_small_refunds_sum_to_exact_zero(db, finance, stock, buyer):
    customer, user, _ = finance
    source = snapshot(db, customer, user)
    receipt, basis = allocate(db, finance, stock, buyer)
    assert basis.snapshot["salesperson_original_commission"] == "0.02"
    source.salesperson_rate = Decimal("0.5")
    for index, amount in enumerate(["0.33", "0.33", "0.34"]):
        finance_service.reverse_allocation(db, receipt.id, cmd(f"reverse-{index}", receipt.version, amount=amount), user)
    result = calculate_commission(db, batch(db, "all").id)
    assert result.total_payments == 4 and result.total_salesperson_commission == 0
    assert sorted(db.scalars(select(CommissionDetail.salesperson_commission))) == [Decimal("-.01"), Decimal("-.01"), Decimal(0), Decimal(".02")]
    payments = db.scalars(select(SyncedPayment)).all()
    for row in payments:
        event = db.get(FinanceEvent, int(row.payment_id.split(":")[-1]))
        assert row.payment_amount - row.service_fee == event.commission_amount_usd
    assert calculate_commission(db, batch(db, "retry").id).total_payments == 0


def test_snapshot_recorded_after_business_day_requires_explicit_resolution(db, finance, stock, buyer):
    customer, user, _ = finance
    source = snapshot(db, customer, user)
    source.created_at = source.updated_at = datetime(2026, 10, 4, 9)
    receipt, basis = allocate(db, finance, stock, buyer)
    assert basis.snapshot is None and basis.pending_reason
    assert calculate_commission(db, batch(db, 'future-policy').id).total_payments == 0
    resolve(db, basis.id, source.id, 'Reviewed historical entitlement for original allocation date', user)
    assert basis.snapshot['salesperson_original_commission'] == '0.02'


def test_missing_basis_late_resolution_consumes_original_and_refund_together(db, finance, stock, buyer):
    customer, user, _ = finance
    receipt, basis = allocate(db, finance, stock, buyer, "100")
    finance_service.reverse_allocation(db, receipt.id, cmd("reverse", 1, amount=40), user)
    assert calculate_commission(db, batch(db, "pending").id).total_payments == 0
    assert not db.scalars(select(CommissionEventProjection)).all()
    source = snapshot(db, customer, user)
    resolve(db, basis.id, source.id, "Verified allocation-date ownership", user)
    result = calculate_commission(db, batch(db, "late", date(2026, 10, 4)).id)
    assert result.total_payments == 2 and result.total_salesperson_commission == Decimal("1.2")
    with pytest.raises(ValueError, match="冻结"):
        resolve(db, basis.id, source.id, "changed", user)


def test_cross_batch_reversal_waits_until_original_confirmed(db, finance, stock, buyer):
    customer, user, _ = finance
    snapshot(db, customer, user)
    receipt, _ = allocate(db, finance, stock, buyer, "100")
    original_batch = batch(db, "original")
    assert calculate_commission(db, original_batch.id).total_payments == 1
    finance_service.reverse_allocation(db, receipt.id, cmd("reverse", 1), user)
    pending = calculate_commission(db, batch(db, "not-ready").id)
    assert pending.total_payments == 0 and pending.skipped_dependency == 1
    void_batch(db, original_batch.id)
    combined = batch(db, "combined")
    result = calculate_commission(db, combined.id)
    assert result.total_payments == 2 and result.total_salesperson_commission == 0
    confirm_batch(db, combined.id, "admin")
    with pytest.raises(ValueError, match="状态"):
        void_batch(db, combined.id)


def test_policy_api_permissions_stale_writes_and_explicit_pending_resolution(db, finance, stock, buyer):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.commission.router import router
    from tests.authority_helpers import seed_authority
    customer, user, _ = finance
    _, basis = allocate(db, finance, stock, buyer)
    db.commit()
    current = {"sub": user["sub"], "roles": [], "permissions": ["commission:read"]}
    app = FastAPI()
    app.include_router(router, prefix="/api/commission/local")
    app.dependency_overrides[get_current_user] = lambda: current
    def fresh_db():
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = fresh_db
    client = TestClient(app)
    prefix = "/api/commission/local"
    endpoint = prefix + f"/customers/{customer.id}/policies"
    body = {"salesperson_id": int(user["sub"]), "salesperson_attribute": "develop", "reason": "Verified original entitlement"}
    assert client.post(endpoint, json=body).status_code == 403
    assert client.get(prefix + "/pending-bases").status_code == 403
    current["permissions"] = ["customer:write", "commission:write"]
    seed_authority(db, int(user['sub']), *current['permissions'])
    rows = client.get(prefix + "/pending-bases").json()["data"]
    assert [row["id"] for row in rows] == [basis.id]
    response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    snapshot_id = response.json()["data"]["id"]
    assert client.post(endpoint, json=body).status_code == 409
    response = client.post(prefix + f"/bases/{basis.id}/resolve", json={"snapshot_id": snapshot_id, "reason": "Allocation day confirmed"})
    assert response.status_code == 200, response.text
    assert client.get(prefix + "/pending-bases").json()["data"] == []
    assert calculate_commission(db, batch(db, "ready").id).total_payments == 1


@pytest.mark.parametrize('operation', ['resolve_basis', 'write_policy', 'read_pending', 'read_policy'])
def test_revoked_native_commission_permission_cannot_use_stale_token(db, finance, stock, buyer, operation):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.commission.router import router
    from tests.authority_helpers import seed_authority
    customer, user, _ = finance
    _, basis = allocate(db, finance, stock, buyer)
    source = snapshot(db, customer, user)
    actor_id, customer_id, basis_id, source_id = int(user['sub']), customer.id, basis.id, source.id
    seed_authority(db, actor_id, 'commission:read')
    app = FastAPI(); app.include_router(router, prefix='/api/commission/local')
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(actor_id), 'roles': [],
        'permissions': ['commission:write', 'customer:write']}
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    commands = {
        'resolve_basis': ('POST', f'/bases/{basis_id}/resolve', {'snapshot_id': source_id, 'reason': 'Reviewed allocation day'}),
        'write_policy': ('POST', f'/customers/{customer_id}/policies', {'salesperson_id': actor_id,
            'salesperson_attribute': 'develop', 'expected_snapshot_id': source_id, 'reason': 'Reviewed attribution'}),
        'read_pending': ('GET', '/pending-bases', None),
        'read_policy': ('GET', f'/customers/{customer_id}/policies', None),
    }
    method, path, body = commands[operation]
    with TestClient(app) as client:
        result = client.request(method, '/api/commission/local' + path, **({'json': body} if body is not None else {}))
        assert result.status_code == 403, result.text
    assert db.get(CommissionBasis, basis_id).snapshot is None
    assert db.query(CustomerCommissionSnapshot).count() == 1 and db.get(CustomerCommissionSnapshot, source_id).is_current


def test_backdated_snapshot_requires_explicit_evidence(db, finance, stock, buyer):
    from datetime import datetime
    customer, user, _ = finance
    source = snapshot(db, customer, user)
    source.operated_at = datetime(2026, 10, 4)
    _, basis = allocate(db, finance, stock, buyer)
    assert basis.snapshot is None
    assert calculate_commission(db, batch(db, "unproven").id).total_payments == 0


def test_resolve_audit_time_is_beijing_at_utc_day_boundary(db, finance, stock, buyer, monkeypatch):
    from datetime import datetime, timezone
    import app.core.time as clock
    class NonBeijingServer(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 3, 16, 0, 1, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    customer, user, _ = finance
    _, basis = allocate(db, finance, stock, buyer)
    source = snapshot(db, customer, user)
    monkeypatch.setattr(clock, "datetime", NonBeijingServer)
    resolve(db, basis.id, source.id, "Verified evidence", user)
    assert basis.resolved_at == datetime(2026, 10, 4, 0, 0, 1)


def test_explicit_zero_supervisor_rate_is_not_overridden_by_dual_development(db, finance, stock, buyer):
    from app.auth.models import ArkUser
    customer, user, _ = finance
    manager = ArkUser(username="commission-manager", password_hash="test-only", real_name="Manager")
    db.add(manager)
    db.flush()
    source = snapshot(db, customer, user, supervisor_id=f"ark:{manager.id}",
        supervisor_attribute='develop', supervisor_rate=Decimal(0))
    _, basis = allocate(db, finance, stock, buyer, "100")
    assert basis.snapshot["supervisor_rate"] == "0"
    result = calculate_commission(db, batch(db, "explicit-zero").id)
    assert result.total_supervisor_commission == 0


def test_native_personal_details_use_frozen_identity_and_unscaled_fx_without_mirror(db, finance, stock, buyer):
    from sqlalchemy import event
    from app.api.commission import _current_business_context, _query_self_detail_rows, _detail_schema_from_row
    from app.services.commission_calculator import send_confirm
    customer, user, _ = finance
    snapshot(db, customer, user)
    allocate(db, finance, stock, buyer, "100")
    commission_batch = batch(db, "personal")
    calculate_commission(db, commission_batch.id)
    def forbid_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower(), statement
    event.listen(db.bind, "before_cursor_execute", forbid_mirror)
    try:
        _, identities = _current_business_context(db, user)
        assert identities == [f"ark:{user['sub']}"]
        rows = _query_self_detail_rows(db, commission_batch.id, identities)
        assert len(rows) == 1
        detail = _detail_schema_from_row(rows[0])
        assert detail.salesperson_name == rows[0][3] and detail.customer_name == customer.display_name
        assert detail.exchange_rate == 7 and detail.salesperson_commission_rmb == 14
        assert send_confirm(db, commission_batch.id)["batch_name"] == "personal"
    finally:
        event.remove(db.bind, "before_cursor_execute", forbid_mirror)
