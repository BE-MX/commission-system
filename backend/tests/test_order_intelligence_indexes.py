from contextlib import nullcontext

import pytest

from scripts import ensure_order_intelligence_indexes as indexes


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))


class FakeEngine:
    def __init__(self):
        self.connection = FakeConnection()

    def begin(self):
        return nullcontext(self.connection)


class FakeInspector:
    def __init__(self, existing):
        self.existing = existing

    def get_indexes(self, table_name, schema):
        assert table_name == "okki_orders"
        assert schema == "lsordertest"
        return self.existing


def test_apply_indexes_uses_online_ddl_when_index_is_missing(monkeypatch):
    fake_engine = FakeEngine()
    monkeypatch.setattr(indexes, "inspect", lambda _connection: FakeInspector([]))

    actions = indexes.apply_indexes(fake_engine)

    assert actions == ["ADD lsordertest.okki_orders.idx_order_intel_user_account_date"]
    assert len(fake_engine.connection.statements) == 1
    ddl = fake_engine.connection.statements[0]
    assert "(`user_id`, `account_date`)" in ddl
    assert "ALGORITHM=INPLACE, LOCK=NONE" in ddl


def test_apply_indexes_skips_matching_existing_index(monkeypatch):
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        indexes,
        "inspect",
        lambda _connection: FakeInspector([
            {
                "name": indexes.INDEX_NAME,
                "column_names": ["user_id", "account_date"],
            }
        ]),
    )

    actions = indexes.apply_indexes(fake_engine)

    assert actions == [
        "SKIP lsordertest.okki_orders.idx_order_intel_user_account_date already exists"
    ]
    assert fake_engine.connection.statements == []


def test_apply_indexes_skips_wider_index_with_required_left_prefix(monkeypatch):
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        indexes,
        "inspect",
        lambda _connection: FakeInspector([
            {
                "name": "idx_existing_wider",
                "column_names": ["user_id", "account_date", "status"],
            }
        ]),
    )

    actions = indexes.apply_indexes(fake_engine)

    assert actions == [
        "SKIP lsordertest.okki_orders.idx_existing_wider already covers user_id,account_date"
    ]
    assert fake_engine.connection.statements == []


def test_apply_indexes_rejects_name_collision_with_different_columns(monkeypatch):
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        indexes,
        "inspect",
        lambda _connection: FakeInspector([
            {"name": indexes.INDEX_NAME, "column_names": ["account_date"]}
        ]),
    )

    with pytest.raises(RuntimeError, match="列定义不一致"):
        indexes.apply_indexes(fake_engine)
