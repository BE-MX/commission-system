import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from social_customer_mcp.models import SocialCustomerSearchInput
from social_customer_mcp.query_service import (
    _DETAIL_SQL,
    _FALLBACK_MATCHED_CTES,
    _MATCHED_CTES,
    SocialCustomerQueryService,
    create_db_engine,
)


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows, rows_per_call=None):
        self.rows = rows
        self.rows_per_call = list(rows_per_call or [])
        self.statement = None
        self.statements = []
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.statements.append(self.statement)
        self.params = params
        rows = self.rows_per_call.pop(0) if self.rows_per_call else self.rows
        return _FakeResult(rows)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _FakeEngine:
    def __init__(self, rows, rows_per_call=None):
        self.connection = _FakeConnection(rows, rows_per_call=rows_per_call)

    def connect(self):
        return self.connection


def test_search_maps_owner_fallback_and_pagination():
    rows = [
        {
            "customer_company": "Alpha Hair",
            "customer_name": "Alpha",
            "contact_name": "Alice",
            "customer_email": "sales@example.com",
            "contact_email": "alice@example.com",
            "contact_phone": "+1 202 555 0123",
            "social_platform": "WhatsApp",
            "social_account": "12025550123",
            "owner_user_name": "未进入私海",
            "total_count": 2,
        }
    ]
    engine = _FakeEngine(rows)
    result = SocialCustomerQueryService(engine).search(
        SocialCustomerSearchInput(email="Sales@Example.com", limit=1)
    )

    assert result.total == 2
    assert result.count == 1
    assert result.has_more is True
    assert result.next_offset == 1
    assert result.items[0].owner_user_name == "未进入私海"
    assert engine.connection.params["lookup"] == "sales@example.com"
    assert "Sales@Example.com" not in engine.connection.statement


def test_empty_search_result():
    engine = _FakeEngine([])
    result = SocialCustomerQueryService(engine).search(
        SocialCustomerSearchInput(social_account="not-found")
    )
    assert result.total == 0
    assert result.items == []
    assert result.next_offset is None


def test_out_of_range_page_keeps_real_total_without_dirty_fallback():
    probe = [{
        "customer_company": "Alpha Hair",
        "customer_name": "Alpha",
        "contact_name": "Alice",
        "customer_email": "sales@example.com",
        "contact_email": "alice@example.com",
        "contact_phone": None,
        "social_platform": None,
        "social_account": None,
        "owner_user_name": "未进入私海",
        "total_count": 3,
    }]
    engine = _FakeEngine([], rows_per_call=[[], probe])
    result = SocialCustomerQueryService(engine).search(
        SocialCustomerSearchInput(email="sales@example.com", offset=50)
    )
    assert result.total == 3
    assert result.count == 0
    assert result.has_more is False
    assert len(engine.connection.statements) == 2


def test_query_uses_expected_index_entry_columns():
    cases = [
        (SocialCustomerSearchInput(email="x@example.com"), "ci.email = :lookup"),
        (SocialCustomerSearchInput(social_account="abc"), "ccs.value = :lookup"),
        (SocialCustomerSearchInput(contact_phone="123"), "cc.tel = :lookup"),
    ]
    for params, expected in cases:
        engine = _FakeEngine([])
        SocialCustomerQueryService(engine).search(params)
        assert any(expected in statement for statement in engine.connection.statements)


def test_email_full_scan_compatibility_only_runs_as_fallback():
    assert "FIND_IN_SET" not in _MATCHED_CTES["email"]
    assert "FIND_IN_SET" in _FALLBACK_MATCHED_CTES["email"]


def test_detail_query_deduplicates_before_count_and_has_stable_tiebreakers():
    details_group = _DETAIL_SQL.split("\ndetails AS (", maxsplit=1)[1].split(")\nSELECT", maxsplit=1)[0]
    assert "MIN(_company_id) AS _company_id" in details_group
    assert "MIN(_customer_id) AS _customer_id" in details_group
    assert "MIN(_social_id) AS _social_id" in details_group
    assert "COUNT(*) OVER() AS total_count" in _DETAIL_SQL.split(")\nSELECT", maxsplit=1)[1]
    assert "_company_id,\n    _customer_id,\n    _social_id" in _DETAIL_SQL


def test_engine_hides_query_parameters_from_exceptions_and_logs():
    engine = create_db_engine()
    try:
        assert engine.hide_parameters is True
        secret_lookup = "victim@example.com"
        with pytest.raises(SQLAlchemyError) as exc_info:
            with engine.connect() as conn:
                conn.execute(
                    text("SELECT * FROM missing_table WHERE email = :lookup"),
                    {"lookup": secret_lookup},
                )
        assert secret_lookup not in str(exc_info.value)
        assert "SQL parameters hidden" in str(exc_info.value)
    finally:
        engine.dispose()
