"""Owned real main/JWT/admin probe; no provider calls or production database."""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserRole, ArkRole, ArkPermission, ArkRolePermission
from test_mysql_full_application import assembled, boot, owner  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user, snapshot


def assert_current_authorization(c,*,active=True,read=True,all_scope=False):
    with Session(c.ctx.engine) as db:
        user=db.get(ArkUser,c.ctx.actor)
        assert user.is_active is active and user.deleted_at is None
        names=set(db.scalars(select(ArkRole.name).join(ArkUserRole,ArkUserRole.role_id==ArkRole.id).where(ArkUserRole.user_id==c.ctx.actor)))
        codes=set(db.scalars(select(ArkPermission.code).join(ArkRolePermission,ArkRolePermission.permission_id==ArkPermission.id).join(ArkUserRole,ArkUserRole.role_id==ArkRolePermission.role_id).where(ArkUserRole.user_id==c.ctx.actor)))
        assert (('invoice:read' in codes) or ('super_admin' in names)) is read
        assert (('invoice:read_all' in codes) or ('super_admin' in names)) is all_scope


def read_roles(c):
    result = {}
    with Session(c.ctx.engine) as db:
        permissions = {}
        for code in ("invoice:read", "invoice:read_all"):
            permission = db.scalar(select(ArkPermission).where(ArkPermission.code == code))
            if permission is None:
                permission = ArkPermission(code=code, module="invoice", action=code.split(":")[1],
                    label="Owned invoice reader", kind="data" if code.endswith("read_all") else "action",
                    is_legacy=False, sort=1)
                db.add(permission); db.flush()
            permissions[code] = permission.id
        for label, codes in (("private", ["invoice:read"]), ("global", ["invoice:read", "invoice:read_all"])):
            role = ArkRole(name="probe-" + uuid4().hex[:16], label="Owned invoice scope probe")
            db.add(role); db.flush(); result[label] = role.id
            for code in codes:
                db.add(ArkRolePermission(role_id=role.id, permission_id=permissions[code]))
        result["super_admin"] = db.scalar(select(ArkRole.id).where(ArkRole.name == "super_admin"))
        db.commit()
    return result


@pytest.mark.parametrize("change", ["disabled", "roles", "action", "read_all", "super_admin"])
def test_invoice_list_rechecks_committed_employee_authority(receipt_app, change):
    c = receipt_app; roles = read_roles(c)
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        starting = roles["super_admin"] if change == "super_admin" else roles["global"]
        change_user(client, c, root, {"role_ids": [c.sales_role, c.roles["both"], starting]})
        old_token = login(client, c, c.owner_name)
        initial = client.get("/api/invoice/invoices", headers=old_token)
        assert initial.status_code == 200
        assert {c.invoice_id, c.foreign_invoice_id}.issubset({row["id"] for row in initial.json()["data"]["items"]})
        if change == "disabled":
            body = {"is_active": False}
        elif change == "roles":
            body = {"role_ids": []}
        elif change == "action":
            body = {"role_ids": [c.sales_role, c.roles["both"]]}
        else:
            body = {"role_ids": [c.sales_role, c.roles["both"], roles["private"]]}
        change_user(client, c, root, body)
        assert_current_authorization(c,active=change!='disabled',read=change not in {'roles','action'},all_scope=change=='disabled')
        before = snapshot(c)
        response = client.get("/api/invoice/invoices", headers=old_token)
        assert snapshot(c) == before and c.calls == []
        assert response.status_code == (200 if change in {"read_all", "super_admin"} else 403)
        if response.status_code == 200:
            assert {row["id"] for row in response.json()["data"]["items"]} == {c.invoice_id}
        assert snapshot(c) == before and c.calls == []


def test_invoice_list_accepts_current_grant_with_older_identity_token(receipt_app):
    c = receipt_app; roles = read_roles(c)
    with c.app.client() as client:
        root = login(client, c, c.root_name)
        change_user(client, c, root, {"role_ids": [c.sales_role, c.roles["both"]]})
        old_token = login(client, c, c.owner_name)
        assert_current_authorization(c,read=False)
        assert client.get("/api/invoice/invoices", headers=old_token).status_code == 403
        change_user(client, c, root, {"role_ids": [c.sales_role, c.roles["both"], roles["private"]]})
        assert_current_authorization(c)
        before = snapshot(c)
        response = client.get("/api/invoice/invoices", headers=old_token)
        assert snapshot(c) == before and c.calls == []
        assert response.status_code == 200
        assert {row["id"] for row in response.json()["data"]["items"]} == {c.invoice_id}
        assert snapshot(c) == before and c.calls == []
