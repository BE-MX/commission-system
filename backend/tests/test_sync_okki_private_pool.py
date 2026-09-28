"""Private-pool import keeps the same OKKI owner scope as customer media."""
from datetime import datetime
from types import SimpleNamespace

from scripts import sync_okki_private_pool


def test_owned_customers_accepts_numeric_and_string_owner_ids(monkeypatch):
    monkeypatch.setattr(sync_okki_private_pool, "_business_schema", lambda: "lsordertest")
    calls = []

    class Db:
        def execute(self, statement, params):
            calls.append((str(statement), params))
            return [SimpleNamespace(
                company_id=42, company_name="Example", update_time=datetime(2026, 9, 27),
            )]

    rows = sync_okki_private_pool._owned_customers(Db(), "56046345", 5)

    assert rows == [{
        "company_id": "42", "company_name": "Example", "update_time": datetime(2026, 9, 27),
    }]
    sql, params = calls[0]
    assert "JSON_CONTAINS(owner_user_ids, :numeric_owner)" in sql
    assert "JSON_CONTAINS(owner_user_ids, :string_owner)" in sql
    assert "LIMIT :limit" in sql
    assert params == {
        "numeric_owner": "56046345", "string_owner": '"56046345"', "limit": 5,
    }


def test_order_payload_uses_existing_source_columns_and_full_item_snapshot(monkeypatch):
    monkeypatch.setattr(sync_okki_private_pool, "_business_schema", lambda: "lsordertest")
    statements = []

    class Rows:
        def __init__(self, values):
            self.values = values

        def mappings(self):
            return self

        def all(self):
            return self.values

    class Db:
        def execute(self, statement, params=None):
            sql = str(statement)
            statements.append(sql)
            if sql.startswith("SHOW COLUMNS"):
                return Rows([{"Field": "order_id"}, {"Field": "custom_fields"}])
            if "FROM `lsordertest`.okki_orders o" in sql:
                return Rows([SimpleNamespace(
                    order_id=7, order_no="SO-7", name=None, status="13972831656",
                    status_name="已结束", trail=None, account_date=None, amount_usd=100,
                    user_id=11, source_raw="阿里询盘",
                )])
            return Rows([])

    payloads = sync_okki_private_pool._order_payloads(Db(), "42")

    assert len(payloads) == 1
    assert payloads[0]["source_category"] == "alibaba_inquiry"
    assert payloads[0]["item_snapshot_mode"] == "full"
    assert payloads[0]["order_name"] is None
    assert "NULL AS name" in statements[1]
    assert "source_type" not in statements[1]
    assert "JSON_EXTRACT(o.custom_fields" in statements[1]


def test_research_tasks_receive_only_imported_customer_ids(monkeypatch):
    monkeypatch.setattr(sync_okki_private_pool, "_owned_customers", lambda *_: [
        {"company_id": "42"}, {"company_id": "43"},
    ])
    def sync_one(_db, row, **_kwargs):
        if row["company_id"] == "43":
            raise ValueError("failed import")
        return {"customer_id": 99, "company_id": "42"}
    monkeypatch.setattr(sync_okki_private_pool, "_sync_one_customer", sync_one)
    research_calls = []
    monkeypatch.setattr(
        sync_okki_private_pool.private_research_service,
        "create_private_research_tasks",
        lambda _db, **kwargs: research_calls.append(kwargs) or {},
    )

    class Db:
        def commit(self):
            pass

        def rollback(self):
            pass

    user = SimpleNamespace(id=1, username="sylvia")
    sync_okki_private_pool.sync_owner(
        Db(), owner=user, okki_user_id="11", operator=user, limit=2,
        dry_run=False, with_orders=False, with_profile=False,
        create_research_tasks=True,
    )

    assert research_calls[0]["customer_ids"] == [99]
