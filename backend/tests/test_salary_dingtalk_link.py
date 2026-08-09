"""平台账号钉钉绑定 → 薪资档案的传播钩（2026-08-07 缺口修复）。

两条链路各存一份钉钉 id：ark_users.dingtalk_id（用户管理维护）与
ark_salary_employee_profile.dingtalk_userid（薪资考勤取数键）。
只写用户那边，薪资批次页就继续报「未绑定钉钉」。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.admin_router import _propagate_dingtalk_to_salary_profile
from app.auth.models import (
    ArkPermission,
    ArkRole,
    ArkRolePermission,
    ArkUser,
    ArkUserRole,
)
from app.core.database import Base
from app.salary.models import SalaryEmployeeProfile


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # roles 是 lazy="joined"，查 ark_users 会连带 JOIN 角色/权限三表，缺一即炸
    Base.metadata.create_all(
        engine,
        tables=[
            ArkUser.__table__, SalaryEmployeeProfile.__table__,
            ArkRole.__table__, ArkUserRole.__table__,
            ArkPermission.__table__, ArkRolePermission.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, name="王京花", dingtalk_id=None) -> ArkUser:
    u = ArkUser(username=f"u_{name}", password_hash="x", real_name=name,
                dingtalk_id=dingtalk_id, is_active=True)
    db.add(u)
    db.commit()
    return u


def _profile(db, user_id, dingtalk_userid=None) -> SalaryEmployeeProfile:
    p = SalaryEmployeeProfile(emp_no=f"E{user_id}", name="王京花", user_id=user_id,
                              dingtalk_userid=dingtalk_userid, payroll_included=1)
    db.add(p)
    db.commit()
    return p


def test_binding_propagates_to_linked_profile(db):
    u = _user(db, dingtalk_id="ding-123")
    p = _profile(db, u.id)
    _propagate_dingtalk_to_salary_profile(db, u)
    db.commit()
    db.refresh(p)
    assert p.dingtalk_userid == "ding-123"


def test_existing_profile_binding_is_not_overwritten(db):
    """档案里已绑的可能是人工修正过的值，传播只填空缺。"""
    u = _user(db, dingtalk_id="ding-new")
    p = _profile(db, u.id, dingtalk_userid="ding-manual")
    _propagate_dingtalk_to_salary_profile(db, u)
    db.commit()
    db.refresh(p)
    assert p.dingtalk_userid == "ding-manual"


def test_empty_user_binding_is_noop(db):
    u = _user(db, dingtalk_id=None)
    p = _profile(db, u.id)
    _propagate_dingtalk_to_salary_profile(db, u)
    db.commit()
    db.refresh(p)
    assert p.dingtalk_userid is None
