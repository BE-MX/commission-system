"""Navigation state machine tests: only explicitly-created in-memory SQLite tables."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.system import navigation_config_service as service
from app.system.navigation_config_models import NavigationConfig, NavigationVersion, NavigationConfigAudit
from app.system.navigation_config_schemas import NavigationDraftSave, NavigationPublish, NavigationPrecondition


def node(key, kind="group", parent="", **extra):
    return dict(id=key, kind=kind, parent=parent, label=key, icon="Menu", order=0, visible=True,
                badge="", badgePlace="text", badgeTone="gold", titleSync=False, **extra)


@pytest.fixture
def context(monkeypatch):
    cat = {"nodes": [node("system", protected=True, builtin=True), node("NavigationManagement", "page", "system", protected=True, builtin=True), node("other", builtin=True)], "icons": ["Menu"], "catalog_hash": "a" * 64}
    monkeypatch.setattr(service, "catalog", lambda: deepcopy(cat))
    engine = create_engine("sqlite:///:memory:")
    for model in (NavigationConfig, NavigationVersion, NavigationConfigAudit):
        model.__table__.create(engine)
    with Session(engine) as db:
        yield db, cat
    engine.dispose()


def pre(draft):
    return {k: draft[k] for k in ("draft_revision", "base_version", "catalog_hash")}


def test_save_publish_restore_and_idempotency(context):
    db, cat = context
    initial = service.get_draft(db)
    nodes = initial["nodes"]
    nodes[2]["label"] = "Changed"
    saved = service.save_draft(db, NavigationDraftSave(**pre(initial), nodes=nodes), 7)
    assert service.effective(db)["version"] == 0
    assert service.effective(db)["nodes"][2]["label"] == "other"
    request = NavigationPublish(**pre(saved), request_id="request-123")
    published = service.publish(db, request, 7)
    assert published["version"] == 1
    assert service.publish(db, request, 7)["id"] == published["id"]
    assert db.query(NavigationVersion).count() == 1
    assert service.effective(db)["nodes"][2]["label"] == "Changed"
    with pytest.raises(HTTPException) as error:
        service.save_draft(db, NavigationDraftSave(**pre(initial), nodes=nodes), 8)
    assert error.value.status_code == 409
    restored = service.restore(db, published["id"], NavigationPrecondition(**pre(service.get_draft(db))), 7)
    assert restored["draft_revision"] == 3
    assert service.effective(db)["version"] == 1
    assert db.query(NavigationConfigAudit).count() == 3
    with pytest.raises(HTTPException):
        service.publish(db, request, 8)


@pytest.mark.parametrize("mutate", [
    lambda n: n.pop(),
    lambda n: n[0].update(visible=False),
    lambda n: n[1].update(parent="other"),
    lambda n: n[2].update(icon="untrusted"),
    lambda n: n[2].update(parent="NavigationManagement"),
    lambda n: n[2].update(label="system"),
    lambda n: n[2].update(rule={"permission": "admin"}),
    lambda n: n[2].update(visible=1),
    lambda n: n[2].update(order=True),
    lambda n: n.append(node("custom-cycle", parent="custom-cycle")),
    lambda n: n.extend([node("custom-a", parent="other"), node("custom-b", parent="custom-a")]),
])
def test_invalid_config_rejected(context, mutate):
    db, cat = context
    nodes = service.defaults(cat)
    mutate(nodes)
    with pytest.raises(HTTPException) as error:
        service.normalize(nodes, cat)
    assert error.value.status_code == 422


def test_hash_cas_and_empty_group_deletion(context):
    db, cat = context
    draft = service.get_draft(db)
    draft["nodes"].append(node("custom-empty"))
    saved = service.save_draft(db, NavigationDraftSave(**pre(draft), nodes=draft["nodes"]), 1)
    saved["nodes"] = [n for n in saved["nodes"] if n["id"] != "custom-empty"]
    service.save_draft(db, NavigationDraftSave(**pre(saved), nodes=saved["nodes"]), 1)
    current = service.get_draft(db)
    with pytest.raises(HTTPException) as error:
        service.save_draft(db, NavigationDraftSave(**{**pre(current), "catalog_hash": "b" * 64}, nodes=current["nodes"]), 1)
    assert error.value.status_code == 409
    assert "rule" not in service.effective(db)["nodes"][0]


def test_audit_uses_beijing_clock_at_boundary(context, monkeypatch):
    db, cat = context
    # UTC date is still Nov 2 while Beijing is Nov 3; host-local time is irrelevant.
    clock = datetime(2026, 11, 2, 16, 1, tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    monkeypatch.setattr(service, "beijing_now", lambda: clock)
    draft = service.get_draft(db)
    service.save_draft(db, NavigationDraftSave(**pre(draft), nodes=draft["nodes"]), 1)
    assert db.get(NavigationConfig, 1).updated_at == datetime(2026, 11, 3, 0, 1)


def test_real_catalog_defaults_are_valid():
    cat = service.catalog()
    nodes = service.normalize(service.defaults(cat), cat)
    assert len(nodes) == len(cat["nodes"])
    assert any(n["id"].startswith("https://") for n in nodes)


def test_two_editors_and_catalog_evolution(context):
    db, cat = context
    original = service.get_draft(db)
    first = deepcopy(original)
    first["nodes"][2]["label"] = "Editor one"
    service.save_draft(db, NavigationDraftSave(**pre(first), nodes=first["nodes"]), 1)
    with Session(db.bind) as other:
        with pytest.raises(HTTPException) as error:
            service.save_draft(other, NavigationDraftSave(**pre(original), nodes=original["nodes"]), 2)
        assert error.value.status_code == 409
    assert service.get_draft(db)["nodes"][2]["label"] == "Editor one"
    cat["nodes"].append(node("new-entry", "page", "other", builtin=True))
    evolved = service.get_draft(db)
    assert evolved["nodes"][-1]["id"] == "new-entry"
    service.normalize(evolved["nodes"], cat)


def test_nonempty_custom_group_cannot_be_deleted_in_same_save(context):
    db, cat = context
    draft = service.get_draft(db)
    draft["nodes"].append(node("custom-parent"))
    draft["nodes"].append(node("custom-child", parent="custom-parent"))
    saved = service.save_draft(db, NavigationDraftSave(**pre(draft), nodes=draft["nodes"]), 1)
    saved["nodes"][-1]["parent"] = ""
    saved["nodes"] = [n for n in saved["nodes"] if n["id"] != "custom-parent"]
    with pytest.raises(HTTPException):
        service.save_draft(db, NavigationDraftSave(**pre(saved), nodes=saved["nodes"]), 1)


def test_beijing_default_ignores_non_beijing_host(context, monkeypatch):
    import app.core.time as time_service
    real_datetime = datetime
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = real_datetime(2026, 11, 2, 16, 1, tzinfo=ZoneInfo("UTC"))
            return instant.astimezone(tz or ZoneInfo("America/Los_Angeles"))
    monkeypatch.setattr(time_service, "datetime", FrozenClock)
    db, cat = context
    draft = service.get_draft(db)
    service.save_draft(db, NavigationDraftSave(**pre(draft), nodes=draft["nodes"]), 1)
    assert db.query(NavigationConfigAudit).one().created_at == datetime(2026, 11, 3, 0, 1)


def test_build_baseline_can_be_restored_after_first_publication(context):
    db, cat = context
    initial = service.get_draft(db)
    initial["nodes"][2]["label"] = "Mistake"
    saved = service.save_draft(db, NavigationDraftSave(**pre(initial), nodes=initial["nodes"]), 1)
    service.publish(db, NavigationPublish(**pre(saved), request_id="first-publish"), 1)
    baseline = service.versions(db)["items"][-1]
    assert baseline["id"] == 0 and baseline["version"] == 0
    assert baseline["nodes"][2]["label"] == "other"
    restored = service.restore(db, 0, NavigationPrecondition(**pre(service.get_draft(db))), 1)
    assert restored["nodes"][2]["label"] == "other"
    assert service.effective(db)["nodes"][2]["label"] == "Mistake"
    with pytest.raises(HTTPException) as error:
        service.restore(db, 0, NavigationPrecondition(**pre(saved)), 1)
    assert error.value.status_code == 409


def test_migration_upgrade_on_isolated_sqlite():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = Path(__file__).resolve().parents[1] / "alembic/versions/248_navigation_config.py"
    spec = importlib.util.spec_from_file_location("navigation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert set(inspect(connection).get_table_names()) == {"ark_navigation_configs", "ark_navigation_versions", "ark_navigation_config_audits"}
            migration.downgrade()
            assert not inspect(connection).get_table_names()
    engine.dispose()


def test_initialization_loser_uses_locking_current_read(context, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    db, cat = context
    service.ensure_state(db, cat)
    db.commit()
    real_get = db.get
    # Simulate a stale REPEATABLE READ snapshot missing the already committed singleton.
    monkeypatch.setattr(db, "get", lambda model, key: None if model is NavigationConfig else real_get(model, key))
    class CompetingInsert:
        def __enter__(self):
            raise IntegrityError("competing insert", {}, Exception("duplicate singleton"))
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(db, "begin_nested", lambda: CompetingInsert())
    statements = []
    real_execute = db.execute
    def capture(statement, *args, **kwargs):
        statements.append(statement)
        return real_execute(statement, *args, **kwargs)
    monkeypatch.setattr(db, "execute", capture)
    winner = service.ensure_state(db, cat)
    assert winner.id == 1
    assert statements[-1]._for_update_arg is not None
    assert statements[-1].get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("icon", [None, [], {}, ["Menu"], 42, True])
def test_invalid_icon_types_are_validation_errors(context, icon):
    db, cat = context
    nodes = service.defaults(cat)
    nodes[2]["icon"] = icon
    with pytest.raises(HTTPException) as error:
        service.normalize(nodes, cat)
    assert error.value.status_code == 422


def test_builtin_group_parent_is_immutable(context):
    db, cat = context
    nodes = service.defaults(cat)
    nodes.append(node("custom-container"))
    nodes[2]["parent"] = "custom-container"
    with pytest.raises(HTTPException) as error:
        service.normalize(nodes, cat)
    assert error.value.status_code == 422
    assert "内置分类不可移动" in error.value.detail
