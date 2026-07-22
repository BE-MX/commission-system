import pytest
from pydantic import ValidationError

from social_customer_mcp.models import SocialCustomerSearchInput


@pytest.mark.parametrize(
    ("kwargs", "matched_by", "value"),
    [
        ({"email": " Sales@Example.com "}, "email", "Sales@Example.com"),
        ({"social_account": "whatsapp-123"}, "social_account", "whatsapp-123"),
        ({"contact_phone": "+1 202 555 0123"}, "contact_phone", "+1 202 555 0123"),
    ],
)
def test_exactly_one_lookup_happy(kwargs, matched_by, value):
    params = SocialCustomerSearchInput(**kwargs)
    assert params.matched_by == matched_by
    assert params.lookup_value == value


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"email": "a@b.com", "social_account": "abc"},
        {"contact_phone": "123", "social_account": "abc"},
    ],
)
def test_exactly_one_lookup_rejected(kwargs):
    with pytest.raises(ValidationError, match="必须且只能填写一个"):
        SocialCustomerSearchInput(**kwargs)


def test_pagination_limits_are_enforced():
    with pytest.raises(ValidationError):
        SocialCustomerSearchInput(email="a@b.com", limit=51)
    with pytest.raises(ValidationError):
        SocialCustomerSearchInput(email="a@b.com", offset=1001)
