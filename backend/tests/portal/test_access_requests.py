from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.portal import access_request_service
from app.portal.models import Account, PortalAccessRequest
from app.portal.schemas import AccessRequestInput, AccessRequestReview, ActivatePasswordInput


def test_access_request_input_rejects_blank_or_extra_fields():
    with pytest.raises(Exception):
        AccessRequestInput(full_name=" ", phone="123", email="a@example.com")
    with pytest.raises(Exception):
        AccessRequestInput(full_name="A", phone="123", email="a@example.com", password="x")


def test_request_view_never_exposes_password_or_review_binding():
    row = SimpleNamespace(public_id="r", full_name="Buyer", phone="123", email_display="a@example.com",
        status="pending", created_at=SimpleNamespace(isoformat=lambda: "2026-10-19T10:00:00"),
        reviewed_at=None, review_reason="", account_id=7, access_id=8)
    data = access_request_service.view(row)
    assert data["email"] == "a@example.com"
    assert "password" not in data and "account_id" not in data and "access_id" not in data


def test_review_requires_access_for_approval():
    body = AccessRequestReview(decision="approve", reason="核对通过")
    assert body.access_id is None
    rejected = AccessRequestReview(decision="reject", reason="信息不足")
    assert rejected.access_id is None


def test_activation_password_is_secret_and_bounded():
    body = ActivatePasswordInput(challenge_id="11111111-1111-4111-8111-111111111111", code="123456", password="long-enough")
    assert body.password.get_secret_value() == "long-enough"
    with pytest.raises(Exception):
        ActivatePasswordInput(challenge_id="11111111-1111-4111-8111-111111111111", code="123456", password="short")


def test_request_model_status_is_bounded():
    assert PortalAccessRequest.__table__.c.status.type.length == 24
    assert Account.__table__.c.password_hash.comment
