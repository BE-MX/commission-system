"""Mixed-schema receipt unions must not inherit incompatible MySQL collations."""
from types import SimpleNamespace

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.invoice.models import Invoice
from app.receipt.models import Receipt
from app.sales_return.receipt_projection import combined


@pytest.mark.parametrize("keyword,order_id", [("", None), ("1030", "105876162862269")])
def test_mysql_receipt_union_normalizes_every_text_projection(keyword, order_id):
    captured = []

    class QueryCaptured(Exception):
        pass

    def capture_count(statement):
        captured.append(statement)
        raise QueryCaptured

    engine = create_engine("sqlite://")
    with Session(engine) as session:
        ordinary = session.query(Receipt, Invoice).join(Invoice, Invoice.id == Receipt.invoice_id)
        db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=mysql.dialect()), scalar=capture_count)
        with pytest.raises(QueryCaptured):
            combined(db, {"roles": ["super_admin"]}, ordinary, 1, 20, keyword, "", "", "",
                     None, None, order_id, "", "", None)
    engine.dispose()
    union = captured[0].get_final_froms()[0].element
    for branch in union.selects:
        for column in branch.selected_columns:
            sql = str(column.compile(dialect=mysql.dialect()))
            if isinstance(column.type, String):
                assert "COLLATE utf8mb4_unicode_ci" in sql, (column.key, sql)
            else:
                assert "COLLATE" not in sql, (column.key, sql)
