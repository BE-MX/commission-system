"""HTTP contract checks against a separate, in-memory FastAPI app."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.auth.utils import create_access_token
from app.core.database import get_db
from app.inkboard.router import router
from tests.test_inkboard import board  # noqa: F401


def test_complete_http_flow_and_machine_privileges(board):
    db, owner, other, _ = board
    app = FastAPI()
    app.include_router(router, prefix="/api/inkboard")
    app.dependency_overrides[get_db] = lambda: db
    def auth(user):
        token = create_access_token({"sub": str(user), "roles": [], "permissions": ["inkboard:write", "task:read"]})
        return {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        prefix = "/api/inkboard"
        issued = client.post(prefix + "/devices", json={"name": "PW3"}, headers=auth(owner))
        assert issued.status_code == 200 and issued.headers["cache-control"] == "no-store"
        token = issued.json()["data"]["token"]
        device = {"Authorization": f"Bearer {token}"}
        assert "token" not in client.get(prefix + "/devices", headers=auth(owner)).text
        assert client.post(prefix + "/notes", json={"title": "Memo", "body": "Text"}, headers=device).status_code == 401
        assert client.get(prefix + "/device/sync", headers=auth(owner)).status_code == 401
        assert client.get(prefix + "/devices", headers=auth(other)).json()["data"] == []
        note = client.post(prefix + "/notes", json={"title": "Memo", "body": "Text"}, headers=auth(owner)).json()["data"]
        changed = client.put(prefix + f'/notes/{note["id"]}', json={"title": "Memo", "body": "New", "version": 1}, headers=auth(owner))
        assert changed.json()["data"]["version"] == 2
        assert client.put(prefix + f'/notes/{note["id"]}', json={"title": "Memo", "body": "Stale", "version": 1}, headers=auth(owner)).status_code == 409
        payload = {"title": "Message", "body": "Read me", "request_key": "http-retry-1"}
        sent = client.post(prefix + "/messages", json=payload, headers=auth(owner)).json()["data"]
        assert client.post(prefix + "/messages", json=payload, headers=auth(owner)).json()["data"]["id"] == sent["id"]
        assert client.post(prefix + "/messages", json={**payload, "body": "x" * 1001}, headers=auth(owner)).status_code == 422
        snapshot = client.get(prefix + "/device/sync", headers=device)
        assert snapshot.headers["cache-control"] == "no-store"
        assert snapshot.json()["data"]["notes"][0]["body"] == "New"
        assert snapshot.json()["data"]["pending"][0]["id"] == sent["id"]
        assert client.post(prefix + "/device/receipts", json={"ids": [sent["id"]], "read": False}, headers=device).status_code == 200
        listed = client.get(prefix + "/messages", headers=auth(owner)).json()["data"][0]
        assert listed["received_count"] == 1 and listed["read_count"] == 0
        client.post(prefix + f'/messages/{sent["id"]}/withdraw', headers=auth(owner))
        assert client.get(prefix + "/device/sync", headers=device).json()["data"]["active_message_ids"] == []
        client.post(prefix + f'/devices/{issued.json()["data"]["id"]}/revoke', headers=auth(owner))
        assert client.get(prefix + "/device/sync", headers=device).status_code == 401


def test_additive_migration_on_isolated_sqlite_preserves_rows():
    path = Path(__file__).parents[1] / "alembic/versions/207_inkboard.py"
    spec = importlib.util.spec_from_file_location("ink_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)")
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert len([name for name in inspect(connection).get_table_names() if name.startswith("ark_ink_")]) == 4
        assert inspect(connection).get_pk_constraint("ark_ink_receipts")["constrained_columns"] == ["device_id", "message_id"]
        import pytest
        with pytest.raises(RuntimeError, match="preserved"):
            module.downgrade()
