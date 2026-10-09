from io import StringIO
import importlib.util
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError

from app.portal.configuration import validate_configuration
from app.portal.schemas import Capabilities, ChallengeInput, Fees, QuoteInput, SubmitInput, VerifyInput


def quote():
    return {"items": [{"item_id": str(uuid4()), "quantity": 3}],
            "delivery": {"contact_name": "Buyer", "phone": "+44 20 0000", "address_line1": "24 Example Street", "country_code": "GB"}}


@pytest.mark.parametrize("field", ["price", "customer_id", "sales_user_id", "amount", "currency", "employee_id"])
def test_customer_cannot_supply_authoritative_fields(field):
    payload = quote()
    payload[field] = "fake"
    with pytest.raises(ValidationError):
        QuoteInput.model_validate(payload)


def test_duplicate_items_and_boolean_quantity_rejected():
    payload = quote()
    payload["items"] *= 2
    with pytest.raises(ValidationError):
        QuoteInput.model_validate(payload)
    payload = quote()
    payload["items"][0]["quantity"] = True
    with pytest.raises(ValidationError):
        QuoteInput.model_validate(payload)


def test_fees_require_decimal_strings_and_named_surcharge():
    with pytest.raises(ValidationError):
        Fees(shipping_amount=45, packaging_amount="0.00", surcharge_amount="0.00")
    with pytest.raises(ValidationError):
        Fees(shipping_amount="45.00", packaging_amount="0.00", surcharge_amount="5.00")
    assert Fees(shipping_amount="45.00", packaging_amount="0.00", surcharge_amount="0.00")


def test_auth_purpose_and_code_are_strict():
    with pytest.raises(ValidationError):
        ChallengeInput(email="buyer@example.com", purpose="activate")
    with pytest.raises(ValidationError):
        VerifyInput(challenge_id=uuid4(), code=123456)
    with pytest.raises(ValidationError):
        Capabilities(can_order=True, can_view_price=False)


def config(**overrides):
    values = dict(PORTAL_NOTIFICATION_ENABLED=False, PORTAL_MAIL_ENABLED=False, PORTAL_EMPLOYEE_ORIGIN="", PORTAL_ENABLED=True, PORTAL_WRITES_ENABLED=True, PORTAL_INVOICE_ENABLED=True,
                  PORTAL_ORIGIN="https://shop.example", APP_ENV="production",
                  PORTAL_CSRF_KEYS={"v1": secrets.token_hex(32)}, PORTAL_CSRF_KEY_VERSION="v1",
                  PORTAL_MAIL_KEYS={"v1": secrets.token_hex(32)}, PORTAL_MAIL_KEY_VERSION="v1",
                  PORTAL_OTP_SECRET=secrets.token_hex(32))
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("origin", ["http://shop.example", "https://shop.example/", "https://name:password@shop.example", "https://shop.example?x=1", ""])
def test_invalid_launch_origin_is_rejected(origin):
    with pytest.raises(ValueError):
        validate_configuration(config(PORTAL_ORIGIN=origin))


def test_launch_fails_closed_without_separate_keys():
    validate_configuration(config())
    with pytest.raises(ValueError):
        validate_configuration(config(PORTAL_OTP_SECRET=""))
    with pytest.raises(ValueError):
        validate_configuration(config(PORTAL_ENABLED=False))
    with pytest.raises(ValueError):
        validate_configuration(config(PORTAL_WRITES_ENABLED=False))
    with pytest.raises(ValueError):
        validate_configuration(config(PORTAL_CSRF_KEYS={"v1": "a"*32}, PORTAL_MAIL_KEYS={"v1": "61"*32}))


def test_migration_emits_mysql_sql_without_connecting():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/176_customer_order_portal.py"
    spec = importlib.util.spec_from_file_location("portal_migration_172", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(url="mysql+pymysql://unused/isolated", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE ark_order_portal_") == 24
    assert sql.count("FOREIGN KEY(") == 76
    assert "ADD COLUMN portal_document_version BIGINT NOT NULL DEFAULT '1'" in sql
    assert "CREATE INDEX ix_op_request_access_submitted" in sql
    assert "DROP TABLE" not in sql
    assert "INSERT INTO ark_order_portal_auth_barriers" in sql
    with pytest.raises(RuntimeError):
        module.downgrade()
