"""设计预约提交的客户与登录身份契约。"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.customer_media import service as customer_media_service
from app.design import router as design_router
from app.customer_image.service import list_available_customers
from app.design.models import DesignRequestAttachment, DesignScheduleRequest
from app.design.router import _can_upload_request_attachment
from app.design.schemas import DesignRequestCreate


def _payload(**overrides):
    tomorrow = date.today() + timedelta(days=1)
    payload = {
        "customer_id": 14427527374439,
        "customer_name": "Madeline Camilleri",
        "shoot_type": "Color",
        "expect_start_date": tomorrow.isoformat(),
        "expect_end_date": tomorrow.isoformat(),
    }
    payload.update(overrides)
    return payload


def test_create_contract_accepts_numeric_customer_id_without_client_salesperson_id():
    parsed = DesignRequestCreate.model_validate(_payload())

    assert parsed.customer_id == "14427527374439"
    assert parsed.salesperson_id is None
    assert parsed.salesperson_name == ""


def test_create_contract_does_not_require_client_owned_snapshots():
    parsed = DesignRequestCreate.model_validate(_payload(customer_name=""))

    canonical = parsed.model_copy(update={
        "customer_name": "Canonical Customer",
        "salesperson_id": 7,
        "salesperson_name": "Authenticated User",
    })
    assert canonical.customer_name == "Canonical Customer"
    assert canonical.salesperson_id == 7
    assert canonical.salesperson_name == "Authenticated User"


@pytest.mark.parametrize("customer_id", [
    True, None, "  ", 1.5, {"id": "1"}, "x" * 65,
])
def test_create_contract_rejects_invalid_customer_id(customer_id):
    with pytest.raises(ValidationError):
        DesignRequestCreate.model_validate(_payload(customer_id=customer_id))


def test_customer_search_serializes_driver_numeric_id_as_string():
    class Result:
        @staticmethod
        def all():
            return [SimpleNamespace(
                company_id=14427527374439,
                company_name="Madeline Camilleri",
                country_name="MT",
                origin_name="OKKI",
            )]

    class Db:
        @staticmethod
        def execute(_statement):
            return Result()

    rows = list_available_customers(Db(), ark_user_id=1, is_admin=True, search="Madeline")

    assert rows[0]["id"] == "14427527374439"


def test_validate_customer_access_uses_exact_internal_customer_id(db, monkeypatch):
    db.execute(text(
        "INSERT INTO lsordertest.customer_info "
        "(company_id, company_name, country_name, origin_name) "
        "VALUES ('internal-100', 'Acme Hair', 'US', 'OKKI')"
    ))
    db.flush()
    monkeypatch.setattr(
        customer_media_service,
        "user_identity",
        lambda *_args: (7, "Test User", object()),
    )

    customer = customer_media_service.validate_customer_access(
        db,
        {"roles": ["super_admin"]},
        "internal-100",
    )

    assert customer == {
        "id": "internal-100",
        "name": "Acme Hair",
        "country": "US",
        "origin": "OKKI",
    }


def test_attachment_upload_scope_uses_authenticated_identity():
    own_request = SimpleNamespace(salesperson_id=7)
    another_request = SimpleNamespace(salesperson_id=8)

    assert _can_upload_request_attachment(own_request, 7, {}) is True
    assert _can_upload_request_attachment(another_request, 7, {}) is False
    assert _can_upload_request_attachment(
        another_request, 7, {"permissions": ["design:manage"]},
    ) is True
    assert _can_upload_request_attachment(
        another_request, 7, {"roles": ["super_admin"]},
    ) is True


class _AttachmentDb:
    def __init__(self, attachment, request):
        self.attachment = attachment
        self.request = request
        self.deleted = None
        self.committed = False

    def query(self, model):
        row = self.attachment if model is DesignRequestAttachment else self.request

        class Query:
            def filter(self, *_args):
                return self

            def first(self):
                return row

        return Query()

    def delete(self, row):
        self.deleted = row

    def commit(self):
        self.committed = True


def test_other_salesperson_cannot_delete_attachment_or_file(monkeypatch, tmp_path):
    file_path = tmp_path / "asset.bin"
    file_path.write_bytes(b"content")
    attachment = SimpleNamespace(id=1, request_id=3, file_path=file_path.name)
    request = SimpleNamespace(id=3, salesperson_id=8, deleted_at=None)
    db = _AttachmentDb(attachment, request)
    monkeypatch.setattr(design_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        design_router.customer_media_service, "user_identity",
        lambda *_args: (7, "Other User", object()),
    )

    result = design_router.delete_attachment(1, db=db, _user={})

    assert result["code"] == 403
    assert file_path.is_file()
    assert db.deleted is None
    assert db.committed is False


@pytest.mark.parametrize("user_id,payload", [
    (8, {}),
    (7, {"permissions": ["design:manage"]}),
    (7, {"roles": ["super_admin"]}),
])
def test_owner_or_manager_can_delete_attachment(monkeypatch, tmp_path, user_id, payload):
    file_path = tmp_path / f"asset-{user_id}.bin"
    file_path.write_bytes(b"content")
    attachment = SimpleNamespace(id=1, request_id=3, file_path=file_path.name)
    request = SimpleNamespace(id=3, salesperson_id=8, deleted_at=None)
    db = _AttachmentDb(attachment, request)
    monkeypatch.setattr(design_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        design_router.customer_media_service, "user_identity",
        lambda *_args: (user_id, "User", object()),
    )

    result = design_router.delete_attachment(1, db=db, _user=payload)

    assert result["code"] == 200
    assert not file_path.exists()
    assert db.deleted is attachment
    assert db.committed is True
