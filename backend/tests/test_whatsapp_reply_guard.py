"""Retain technical input boundaries after retiring semantic response guards."""
import pytest
from pydantic import ValidationError
from tests.reply_support import request

def test_schema_rejects_extra_identity_and_oversized_context():
    with pytest.raises(ValidationError):
        request(user_id=999)
    with pytest.raises(ValidationError):
        request(messages=[{"role": "customer", "text": "x" * 70000}] * 2)
    with pytest.raises(ValidationError):
        request(messages=[{"role": "customer", "text": "hello"}] * 21)
