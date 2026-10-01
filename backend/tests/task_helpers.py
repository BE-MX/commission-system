"""任务中心测试工具：建用户、带 JWT 的 TestClient。"""
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db


def make_user(db, username, dingtalk_id=None):
    user = ArkUser(username=username, password_hash="test-hash", real_name=username, dingtalk_id=dingtalk_id)
    db.add(user)
    db.flush()
    return user


@contextmanager
def task_client(db, user, permissions=("task:read", "task:write")):
    from app.task.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/task")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id), "username": user.username, "real_name": user.real_name,
        "roles": [], "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client
