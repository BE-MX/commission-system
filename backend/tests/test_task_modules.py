"""模块注册表：默认种子、导航清单同步、私有分类、可用性校验。"""
import pytest

from app.task import module_service
from app.task.errors import TaskInvalid
from app.task.models import TaskModule
from tests.task_helpers import make_user

MANIFEST = {
    "version": 1,
    "entries": [
        {"key": "InvoiceManage", "title": "订单发票", "group_key": "invoice", "group_title": "订单管理", "route": "/invoice", "sort": 1},
        {"key": "TaskCenter", "title": "任务中心", "group_key": "task", "group_title": "个人效率", "route": "/task", "sort": 1},
    ],
}


def test_seed_defaults_is_idempotent(db):
    module_service.seed_default_modules(db)
    module_service.seed_default_modules(db)
    keys = {m.key for m in db.query(TaskModule).all()}
    assert {"infra.backend", "infra.deploy", "infra.mini", "infra.docs", "custom.report", "custom.research", "custom.admin"} <= keys


def test_sync_manifest_upserts_and_deactivates_missing(db):
    module_service.sync_nav_manifest(db, MANIFEST)
    smaller = {"version": 1, "entries": [MANIFEST["entries"][0] | {"title": "订单发票管理"}]}
    result = module_service.sync_nav_manifest(db, smaller)
    assert result == {"upserted": 1, "deactivated": 1}
    invoice = db.get(TaskModule, "InvoiceManage")
    assert invoice.title == "订单发票管理" and invoice.is_active
    assert db.get(TaskModule, "TaskCenter").is_active is False


def test_sync_rejects_empty_manifest_and_keeps_registry(db):
    module_service.sync_nav_manifest(db, MANIFEST)
    with pytest.raises(ValueError):
        module_service.sync_nav_manifest(db, {"version": 1, "entries": []})
    assert db.get(TaskModule, "TaskCenter").is_active is True


def test_custom_module_private_to_owner(db):
    module_service.seed_default_modules(db)
    alice, bob = make_user(db, "mod_alice"), make_user(db, "mod_bob")
    key = module_service.add_custom(db, alice.id, "家里的事")
    assert key.startswith(f"custom.u{alice.id}.")
    assert key in {m["key"] for m in module_service.list_modules(db, alice.id)}
    assert key not in {m["key"] for m in module_service.list_modules(db, bob.id)}
    with pytest.raises(TaskInvalid):
        module_service.ensure_usable(db, bob.id, key)


def test_ensure_usable_rejects_inactive(db):
    module_service.sync_nav_manifest(db, MANIFEST)
    module_service.sync_nav_manifest(db, {"version": 1, "entries": [MANIFEST["entries"][0]]})
    owner = make_user(db, "mod_inactive")
    with pytest.raises(TaskInvalid):
        module_service.ensure_usable(db, owner.id, "TaskCenter")
    assert module_service.ensure_usable(db, owner.id, None) is None


def test_deactivate_custom_only_own(db):
    alice, bob = make_user(db, "mod_da"), make_user(db, "mod_db")
    key = module_service.add_custom(db, alice.id, "副业")
    with pytest.raises(TaskInvalid):
        module_service.deactivate_custom(db, bob.id, key)
    module_service.deactivate_custom(db, alice.id, key)
    assert db.get(TaskModule, key).is_active is False
