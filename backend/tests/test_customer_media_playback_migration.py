"""198 客户素材播放版迁移：可续跑的加列行为。"""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/198_customer_media_playback.py"
    spec = importlib.util.spec_from_file_location("customer_media_playback_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install(monkeypatch, module, columns):
    inspector = Mock()
    inspector.get_columns.return_value = [{"name": name} for name in columns]
    monkeypatch.setattr(module.sa, "inspect", lambda bind: inspector)
    operations = Mock()
    monkeypatch.setattr(module, "op", operations)
    return operations


def test_revision_follows_the_single_head():
    module = migration()
    assert module.revision == "198_customer_media_playback"
    assert module.down_revision == "197_battle_awards"


@pytest.mark.parametrize(
    "columns, added",
    [
        (["id", "object_key", "thumbnail_key"], {"playback_key", "playback_size"}),
        (["id", "object_key", "thumbnail_key", "playback_key"], {"playback_size"}),
        (["id", "object_key", "thumbnail_key", "playback_key", "playback_size"], set()),
    ],
)
def test_upgrade_only_adds_missing_columns(monkeypatch, columns, added):
    module = migration()
    operations = _install(monkeypatch, module, columns)
    module.upgrade()
    names = {call.args[1].name for call in operations.add_column.call_args_list}
    assert names == added
    # 列注释是语义变化，不为它重建生产表。
    operations.alter_column.assert_not_called()


def test_downgrade_drops_only_existing_columns(monkeypatch):
    module = migration()
    operations = _install(monkeypatch, module, ["id", "object_key", "playback_key"])
    module.downgrade()
    dropped = [call.args[1] for call in operations.drop_column.call_args_list]
    assert dropped == ["playback_key"]
