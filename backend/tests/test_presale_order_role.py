"""Freight must not appear in any sales metric before or after remote binding."""
import sqlite3

import pytest

from app.invoice.order_role import goods_order_sql


def test_freight_name_reservation_and_verified_id_both_exclude_sales():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE ark_receivables (kind TEXT, remote_order_id TEXT, remote_order_name TEXT, customer_id TEXT)")
    db.execute("CREATE TABLE okki_orders (order_id INTEGER, name TEXT, company_id INTEGER)")
    db.executemany("INSERT INTO okki_orders VALUES (?, ?, ?)", [
        (1, "goods", 10), (2, "shipment-F", 10), (3, "shipment-F", 11),
    ])
    db.execute("INSERT INTO ark_receivables VALUES ('freight', NULL, 'shipment-F', '10')")
    query = f"SELECT o.order_id FROM okki_orders o WHERE {goods_order_sql('o')} ORDER BY o.order_id"
    assert [row[0] for row in db.execute(query)] == [1, 3]

    db.execute("UPDATE ark_receivables SET remote_order_id='2' WHERE remote_order_name='shipment-F'")
    db.execute("UPDATE okki_orders SET name='renamed remotely' WHERE order_id=2")
    assert [row[0] for row in db.execute(query)] == [1, 3]
    db.execute("UPDATE ark_receivables SET remote_order_id='999' WHERE remote_order_name='shipment-F'")
    db.execute("UPDATE okki_orders SET name='shipment-F' WHERE order_id=2")
    assert [row[0] for row in db.execute(query)] == [1, 3]
    db.close()


@pytest.mark.parametrize("alias", ["o;DROP", "o.name", "", "1o"])
def test_order_role_rejects_non_identifier_alias(alias):
    with pytest.raises(ValueError):
        goods_order_sql(alias)
