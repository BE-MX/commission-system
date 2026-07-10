"""小程序绑定登录：identifier 匹配口径 + 绑定必须跨 session 持久化

回归背景（2026-07-10）：bind_user 只 flush、router 层漏 db.commit()，
绑定接口返回 200 但 session 关闭即回滚，wx_id 静默丢失。
service 级测试逮不住这个 bug，必须调 router 函数并跨 session 断言。
"""

import pytest
from sqlalchemy.orm import sessionmaker

from app.auth.models import ArkUser
from app.mini import service
from app.mini.router import mini_bind
from app.mini.schemas import MiniBindRequest


@pytest.fixture
def Session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _create_user(Session, username="worker01", phone="13800000001"):
    db = Session()
    user = ArkUser(
        username=username,
        password_hash="x",
        real_name="测试工人",
        phone=phone,
        is_active=True,
    )
    db.add(user)
    db.commit()
    uid = user.id
    db.close()
    return uid


def test_bind_matches_username(Session):
    _create_user(Session)
    db = Session()
    result = service.bind_user(db, open_id="wxo_by_username", identifier="worker01")
    assert result["success"] is True
    assert result["user"]["wx_id"] == "wxo_by_username"
    db.close()


def test_bind_matches_phone(Session):
    _create_user(Session)
    db = Session()
    result = service.bind_user(db, open_id="wxo_by_phone", identifier="13800000001")
    assert result["success"] is True
    db.close()


def test_bind_unknown_identifier_fails(Session):
    _create_user(Session)
    db = Session()
    result = service.bind_user(db, open_id="wxo_x", identifier="no_such_user")
    assert result["success"] is False
    assert result["error"] == "USER_NOT_FOUND"
    db.close()


async def test_bind_endpoint_persists_across_sessions(Session):
    """router 层必须 commit：换一个全新 session 仍能读到 wx_id"""
    uid = _create_user(Session)

    db = Session()
    resp = await mini_bind(MiniBindRequest(open_id="wxo_persist", identifier="worker01"), db=db)
    assert resp["bound"] is True
    db.close()  # 未 commit 的改动在这里会被回滚

    fresh = Session()
    user = fresh.query(ArkUser).get(uid)
    assert user.wx_id == "wxo_persist", "绑定未持久化——router 层 db.commit() 被移除了？"
    fresh.close()


async def test_rebind_same_user_other_wechat_rejected(Session):
    """一个账号只能绑一个微信：已绑定后换 openId 绑同一账号必须 409 语义"""
    _create_user(Session)
    db = Session()
    await mini_bind(MiniBindRequest(open_id="wxo_first", identifier="worker01"), db=db)
    db.close()

    db2 = Session()
    result = service.bind_user(db2, open_id="wxo_second", identifier="worker01")
    assert result["success"] is False
    assert result["error"] == "ALREADY_BOUND"
    db2.close()
