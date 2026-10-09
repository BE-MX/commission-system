"""Actual Ark role-management entry points race with portal approval transactions."""
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import admin_router
from app.auth.admin_schemas import RoleUpdateRequest, UserUpdateRequest
from app.auth.models import ArkPermission, ArkPermissionAudit, ArkRole, ArkRolePermission, ArkUserRole
from app.invoice.models import Invoice
from app.portal import approval_service
from app.portal.authority import lock_authority
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, Conversion, OrderRequest
from test_mysql_services import accepted_request, assert_one_pi, compete, count


@pytest.mark.parametrize('kind', ['role', 'portal_order:write', 'invoice:write'])
@pytest.mark.parametrize('revoke_first', [True, False])
def test_real_rbac_revocation_and_approval_obey_commit_order(trade, kind, revoke_first):
    ctx = trade
    # Isolate this actor's role so removing permission cannot affect another case.
    ArkPermissionAudit.__table__.create(ctx.engine, checkfirst=True)
    with Session(ctx.engine) as db:
        original = db.scalar(select(ArkUserRole.role_id).where(ArkUserRole.user_id == ctx.actor))
        permissions = list(db.scalars(select(ArkRolePermission.permission_id).where(ArkRolePermission.role_id == original)))
        role = ArkRole(name='race-' + uuid4().hex[:12], label='Isolated approval role', is_system=False)
        db.add(role)
        db.flush()
        role_id = role.id
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id == ctx.actor))
        db.add(ArkUserRole(user_id=ctx.actor, role_id=role_id))
        db.add_all([ArkRolePermission(role_id=role_id, permission_id=value) for value in permissions])
        removed_id = None if kind == 'role' else db.scalar(select(ArkPermission.id).where(ArkPermission.code == kind))
        assert kind == 'role' or removed_id in permissions
        db.commit()
    request_id, body = accepted_request(ctx)
    approve = lambda db: approval_service.approve(db, ctx.actor, request_id, 3, body)
    def revoke(db):
        operator = {'sub': str(ctx.admin), 'username': 'mysql-admin'}
        if kind == 'role':
            result = admin_router.update_user(ctx.actor, UserUpdateRequest(role_ids=[]), db, operator)
        else:
            result = admin_router.update_role(role_id,
                RoleUpdateRequest(permission_ids=[value for value in permissions if value != removed_id]), db, operator)
        assert result.code == 200
        return {'revoked': True}
    if revoke_first:
        # Router owns commit. Hold its real barrier until approval's wait is observed,
        # then call the router to mutate and commit without replacing its logic.
        _, result = compete(ctx, lambda db: lock_authority(db, force=True), approve, finalize=revoke)
        assert result['status'] == 403
    else:
        result, revoked = compete(ctx, approve, revoke)
        assert result['current_state'] == 'invoice_created' and revoked == {'revoked': True}
        assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.status == ('ready_for_review' if revoke_first else 'invoice_created')
        assert count(db, Invoice, Invoice.source_order_id == request_id) == int(not revoke_first)
        assert count(db, Conversion, Conversion.request_id == order.id) == int(not revoke_first)
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
            & (AuditEvent.action == 'order.invoice_created')) == int(not revoke_first)
        if kind == 'role':
            assert count(db, ArkUserRole, ArkUserRole.user_id == ctx.actor) == 0
        else:
            assert count(db, ArkRolePermission, (ArkRolePermission.role_id == role_id)
                & (ArkRolePermission.permission_id == removed_id)) == 0
            audits = db.scalars(select(ArkPermissionAudit).where(ArkPermissionAudit.role_id == role_id)).all()
            assert len(audits) == 1 and audits[0].removed_codes == [kind]
            assert audits[0].operator_user_id == ctx.admin
        db.rollback()
        with pytest.raises(PortalError) as caught:
            approve(db)
        assert caught.value.status == 403
        db.rollback()
