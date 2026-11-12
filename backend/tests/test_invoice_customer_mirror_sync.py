"""Manual customer sync must repair the mirror used by owner-scoped readers."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from app.core import time as business_time
from app.invoice import customer_sync_service, customer_picker_service, okki_client, product_service
from app.invoice.customer_sync_models import CustomerSyncLog
from app.invoice.models import InvoiceCustomerOverlay
from tests.test_invoice_customer_sync import (
    OKKI_UID, OTHER_UID, QUERY_URL, _candidate, _client, _info, _mock_okki,
    _seed_mirror_customer, bound_user,
)


def _mirror(db, company_id=88002):
    row = db.execute(text(
        "SELECT company_name, owner_user_ids FROM lsordertest.customer_info WHERE company_id=:id"
    ), {"id": str(company_id)}).mappings().first()
    return dict(row) if row else None


@pytest.mark.parametrize("old_owners", [None, "[]", f"[{OTHER_UID}]", f'["{OTHER_UID}"]'])
def test_sync_repairs_mirror_even_when_overlay_is_already_current(db, bound_user, monkeypatch, old_owners):
    _seed_mirror_customer(db, 88002, "Beta Salon", old_owners)
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})
    # Reproduce a prior successful overlay-only sync, followed by another click.
    overlay = InvoiceCustomerOverlay(company_id="88002", company_name="Beta Salon")
    customer_sync_service._apply_info(overlay, _info(88002, "Beta Salon", [OKKI_UID]))
    db.add(overlay)
    db.commit()

    result = customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)

    assert json.loads(_mirror(db)["owner_user_ids"]) == [OKKI_UID]
    assert "负责人" in result["changed_fields"]
    audit = db.query(CustomerSyncLog).one()
    assert audit.created_by == 5
    assert audit.before_data["owner_user_ids"] == (json.loads(old_owners) if old_owners else None)
    assert audit.after_data["owner_user_ids"] == [OKKI_UID]
    # The selector also works after removing the supplemental projection.
    db.delete(overlay)
    db.flush()
    assert customer_picker_service.search_options(db, keyword="88002", owner_okki_id=OKKI_UID)["total"] == 1
    assert customer_picker_service.search_options(db, keyword="88002", owner_okki_id=OTHER_UID)["total"] == 0


def test_sync_inserts_missing_mirror_customer(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})

    result = customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)

    assert result["created"] is True
    assert _mirror(db)["company_name"] == "Beta Salon"
    assert json.loads(_mirror(db)["owner_user_ids"]) == [OKKI_UID]
    assert db.query(CustomerSyncLog).one().before_data is None


@pytest.mark.parametrize("old_owners", ["[true]", "[1.0]", '["1"]'])
def test_sync_repairs_json_owner_types(db, bound_user, monkeypatch, old_owners):
    _seed_mirror_customer(db, 88002, "Beta Salon", old_owners)
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [1])})
    customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)
    owners = json.loads(_mirror(db)["owner_user_ids"])
    assert owners == [1] and type(owners[0]) is int
    assert db.query(CustomerSyncLog).count() == 1


@pytest.mark.parametrize("timestamp", ["2026-09-03T02:00:00Z", "2026-09-03T03:00:00+01:00",
                                        str(int(datetime(2026, 9, 3, 2, tzinfo=timezone.utc).timestamp()))])
def test_sync_then_select_with_timezone_or_epoch_source_time(db, bound_user, monkeypatch, timestamp):
    _seed_mirror_customer(db, 88002, "Beta Salon", "[]")
    db.execute(text("ALTER TABLE lsordertest.customer_info ADD COLUMN update_time TEXT"))
    db.execute(text("UPDATE lsordertest.customer_info SET update_time='2026-09-03 09:00:00' WHERE company_id='88002'"))
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID], timestamp)})
    customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)
    assert product_service._parse_ts(timestamp) == datetime(2026, 9, 3, 10)
    assert len(product_service.search_customers(db, keyword="88002", owner_okki_id=OKKI_UID)) == 1
    assert customer_picker_service.search_options(db, keyword="88002", owner_okki_id=OKKI_UID)["total"] == 1


def test_unrepresentable_source_time_is_not_a_search_error():
    assert product_service._parse_ts("9999-12-31T23:00:00Z") is None


@pytest.mark.parametrize("owners", [[], [OKKI_UID, str(OKKI_UID), OTHER_UID]])
def test_sync_public_sea_and_multiple_owners_preserve_other_mirror_fields(db, bound_user, monkeypatch, owners):
    _seed_mirror_customer(db, 88002, "Old mirror name", f"[{OTHER_UID}]")
    db.execute(text("ALTER TABLE lsordertest.customer_info ADD COLUMN update_time TEXT"))
    db.execute(text("UPDATE lsordertest.customer_info SET country_name='DE', update_time='2026-09-01 10:00:00' WHERE company_id='88002'"))
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", owners)})

    result = customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)

    expected = [] if not owners else [OKKI_UID, OTHER_UID]
    assert json.loads(_mirror(db)["owner_user_ids"]) == expected
    assert result["is_public_sea"] is (not owners)
    mirror = db.execute(text("SELECT * FROM lsordertest.customer_info WHERE company_id='88002'")).mappings().one()
    assert mirror["company_name"] == "Old mirror name"
    assert mirror["country_name"] == "DE"
    assert mirror["update_time"] == "2026-09-01 10:00:00"


@pytest.mark.parametrize("owner", [None, {}, "owner", [None], [{}], [{"user_id": None}],
                                  [{"user_id": True}], [{"user_id": 0}], [{"user_id": -1}],
                                  [{"user_id": "oops"}], [{"user_id": 1.5}], [{"user_id": "９９"}],
                                  [{"user_id": 2**63}], [{"user_id": OKKI_UID}, {}]])
def test_malformed_owner_never_clears_mirror(db, bound_user, monkeypatch, owner):
    _seed_mirror_customer(db, 88002, "Beta Salon", f"[{OTHER_UID}]")
    info = {**_info(88002, "Beta Salon", []), "owner": owner}
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: info})

    with pytest.raises(customer_sync_service.CustomerSyncError, match="负责人"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)

    assert json.loads(_mirror(db)["owner_user_ids"]) == [OTHER_UID]
    assert db.get(InvoiceCustomerOverlay, "88002") is None
    assert db.query(CustomerSyncLog).count() == 0


@pytest.mark.parametrize("identity", [None, 88003, True])
def test_mismatched_remote_customer_never_writes(db, bound_user, monkeypatch, identity):
    _seed_mirror_customer(db, 88002, "Beta Salon", f"[{OTHER_UID}]")
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {
        88002: {**_info(88002, "Beta Salon", [OKKI_UID]), "company_id": identity},
    })
    with pytest.raises(customer_sync_service.CustomerSyncError, match="身份"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon")
    assert json.loads(_mirror(db)["owner_user_ids"]) == [OTHER_UID]
    assert db.query(CustomerSyncLog).count() == 0


def test_sync_is_idempotent_and_audit_is_persistent(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})
    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        assert client.post(QUERY_URL, json={"company_name": "Beta Salon"}).status_code == 200
        again = client.post(QUERY_URL, json={"company_name": "Beta Salon"})
        assert again.status_code == 200
        assert again.json()["data"]["changed_fields"] == []
        assert client.get("/api/invoice/customers/options", params={"keyword": "88002"}).json()["data"]["total"] == 1
    db.expire_all()
    assert json.loads(_mirror(db)["owner_user_ids"]) == [OKKI_UID]
    assert db.query(CustomerSyncLog).count() == 1


@pytest.mark.parametrize("existing", [True, False])
def test_failed_audit_rolls_back_mirror_and_overlay(db, bound_user, monkeypatch, existing):
    if existing:
        _seed_mirror_customer(db, 88002, "Beta Salon", f"[{OTHER_UID}]")
    db.commit()
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})

    def deny_audit(*args):
        raise OperationalError("test audit", {}, Exception("synthetic failure"))

    event.listen(CustomerSyncLog, "before_insert", deny_audit)
    try:
        with _client(db, sub="5", permissions=["invoice:write"]) as client:
            response = client.post(QUERY_URL, json={"company_name": "Beta Salon"})
    finally:
        event.remove(CustomerSyncLog, "before_insert", deny_audit)
    assert response.status_code == 503
    assert "保存失败" in response.json()["detail"]
    assert "synthetic" not in response.text
    assert (_mirror(db) is not None) is existing
    if existing:
        assert json.loads(_mirror(db)["owner_user_ids"]) == [OTHER_UID]
    assert db.get(InvoiceCustomerOverlay, "88002") is None
    assert db.query(CustomerSyncLog).count() == 0


def test_failed_commit_does_not_report_success(db, bound_user, monkeypatch):
    _seed_mirror_customer(db, 88002, "Beta Salon", "[]")
    db.commit()
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})

    def deny_commit():
        raise OperationalError("test commit", {}, Exception("synthetic failure"))

    monkeypatch.setattr(db, "commit", deny_commit)
    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        response = client.post(QUERY_URL, json={"company_name": "Beta Salon"})
    assert response.status_code == 503
    assert json.loads(_mirror(db)["owner_user_ids"]) == []
    assert db.get(InvoiceCustomerOverlay, "88002") is None
    assert db.query(CustomerSyncLog).count() == 0


@pytest.mark.parametrize("target", ["mirror", "overlay"])
def test_concurrent_update_during_fetch_is_not_overwritten(db, bound_user, monkeypatch, target):
    _seed_mirror_customer(db, 88002, "Beta Salon", "[]")
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {})

    def changed_while_fetching(*args):
        if target == "mirror":
            db.execute(text("UPDATE lsordertest.customer_info SET owner_user_ids=:owners WHERE company_id='88002'"),
                       {"owners": json.dumps([OTHER_UID])})
        else:
            db.add(InvoiceCustomerOverlay(company_id="88002", company_name="Beta Salon", owner_user_ids=[str(OTHER_UID)]))
        db.commit()  # Simulate another completed request before the old response arrives.
        return _info(88002, "Beta Salon", [OKKI_UID])

    monkeypatch.setattr(okki_client, "get_company_info", changed_while_fetching)
    with pytest.raises(customer_sync_service.CustomerSyncError, match="其他同步更新"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)
    db.rollback()
    assert json.loads(_mirror(db)["owner_user_ids"]) == ([OTHER_UID] if target == "mirror" else [])
    assert db.query(CustomerSyncLog).count() == 0


@pytest.mark.parametrize("source", ["mirror", "overlay"])
def test_older_remote_version_is_rejected(db, bound_user, monkeypatch, source):
    _seed_mirror_customer(db, 88002, "Beta Salon", f"[{OTHER_UID}]")
    if source == "mirror":
        db.execute(text("ALTER TABLE lsordertest.customer_info ADD COLUMN update_time TEXT"))
        db.execute(text("UPDATE lsordertest.customer_info SET update_time='2026-09-04 10:00:00' WHERE company_id='88002'"))
    else:
        db.add(InvoiceCustomerOverlay(company_id="88002", company_name="Beta Salon", owner_user_ids=[str(OTHER_UID)],
                                      source_update_time="2026-09-04T02:00:00Z"))
    db.commit()
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})
    with pytest.raises(customer_sync_service.CustomerSyncError, match="早于"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)
    assert json.loads(_mirror(db)["owner_user_ids"]) == [OTHER_UID]
    assert db.query(CustomerSyncLog).count() == 0


@pytest.mark.parametrize("instant, expected", [("2026-11-12T15:59:59+00:00", "2026-11-12 23:59:59"),
                                             ("2026-11-12T16:00:00+00:00", "2026-11-13 00:00:00")])
def test_audit_uses_beijing_midnight_on_non_beijing_server(db, bound_user, monkeypatch, instant, expected):
    fixed = datetime.fromisoformat(instant)

    class ForeignServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz or ZoneInfo("America/Los_Angeles"))

    monkeypatch.setattr(business_time, "datetime", ForeignServerClock)
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})
    customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)
    assert str(db.query(CustomerSyncLog).one().created_at) == expected
