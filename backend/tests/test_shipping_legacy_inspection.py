"""历史出库单（验货流程上线前）按已提交展示，但不生成验货单记录。

分界见 app/shipping_inspection/constants.py 的 LEGACY_OUTBOUND_BEFORE：
出库日期早于分界且没有验货单的出库单，出库单打印页展示「已提交」；
验货单列表、照片和已提交统计仍只认真实提交。
"""
import pytest
from sqlalchemy import text

from app.shipping_inspection import board_service, outbound_queue_service as queue, outbound_service
from app.shipping_inspection.models import ShippingInspection
from tests.test_shipping_inspection import _pc_client, _user, _PC_PERMS


@pytest.fixture
def legacy_records(db):
    """分界前一天 / 当天各一张出库单；OB001/OB002 在分界之后（conftest 种子）。"""
    outbound_service._columns_cache.clear()
    db.execute(text("""
        INSERT INTO lsordertest.okki_outbound_records
        (id, outbound_no, outbound_date, customer_name, owner_name)
        VALUES ('LEG001', 'CK-LEG-1', '2026-09-30', '历史客户', '王小二'),
               ('LEG002', 'CK-LEG-2', '2026-10-01', '当日客户', '王小二')
    """))
    db.commit()
    yield
    outbound_service._columns_cache.clear()


@pytest.mark.parametrize("value,expected", [
    ("2025-12-31", True), ("2026-09-30", True), ("2026-09-30 23:59:59", True),
    ("2026-10-01", False), ("2026-10-01 00:00:00", False), (None, False), ("", False),
])
def test_legacy_boundary_is_the_day_before_october_first(value, expected):
    assert outbound_service.is_legacy_outbound(value) is expected


def test_legacy_outbound_shows_submitted_without_creating_inspection(db, legacy_records):
    user = _user(db, "legacy-reader")
    with _pc_client(db, user, _PC_PERMS) as client:
        data = client.get("/api/shipping-inspection/outbound-records", params={"page_size": 50}).json()["data"]
    by_id = {row["outbound_record_id"]: row for row in data["items"]}
    assert by_id["LEG001"]["status"] == "submitted"
    assert by_id["LEG001"]["inspection_legacy"] is True
    assert by_id["LEG001"]["photo_count"] == 0
    # 分界当天及之后仍是未检验；历史展示不写验货单
    assert by_id["LEG002"]["status"] == "none" and by_id["LEG002"]["inspection_legacy"] is False
    assert by_id["OB001"]["status"] == "none" and by_id["OB001"]["inspection_legacy"] is False
    assert db.query(ShippingInspection).filter_by(outbound_record_id="LEG001").count() == 0


def test_inspection_status_filter_matches_legacy_display(db, legacy_records):
    submitted, total = queue.list_outbound_records(db, inspection_status="submitted", page_size=50)
    assert total == 1 and [row["outbound_record_id"] for row in submitted] == ["LEG001"]

    rows, total = queue.list_outbound_records(db, inspection_status="none", page_size=50)
    assert total == 3
    assert {row["outbound_record_id"] for row in rows} == {"OB001", "OB002", "LEG002"}


def test_real_inspection_record_wins_over_legacy_display(db, legacy_records):
    db.add(ShippingInspection(outbound_record_id="LEG001", status="draft"))
    db.commit()
    user = _user(db, "legacy-draft")
    with _pc_client(db, user, _PC_PERMS) as client:
        data = client.get("/api/shipping-inspection/outbound-records", params={"page_size": 50}).json()["data"]
        drafts = client.get("/api/shipping-inspection/outbound-records",
                            params={"inspection_status": "draft"}).json()["data"]
    row = next(item for item in data["items"] if item["outbound_record_id"] == "LEG001")
    assert row["status"] == "draft" and row["inspection_legacy"] is False
    assert [item["outbound_record_id"] for item in drafts["items"]] == ["LEG001"]


def test_legacy_outbound_never_enters_submitted_inspection_list(db, legacy_records):
    user = _user(db, "legacy-list")
    with _pc_client(db, user, _PC_PERMS) as client:
        assert client.get("/api/shipping-inspection/records").json()["data"]["total"] == 0


def test_board_pending_excludes_legacy_outbound(db, legacy_records):
    pending = {row["outbound_record_id"] for row in board_service.build_board(db)["pending"]}
    assert "LEG001" not in pending
    assert {"LEG002", "OB001", "OB002"} <= pending
