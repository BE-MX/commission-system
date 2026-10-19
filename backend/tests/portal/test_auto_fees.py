from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, func, select

from test_approval_service import (portal_metadata, quoting, priced_catalog, catalog, managed,  # noqa: F401
                                   auth_context)
from test_quotes import body as quote_body
from app.core.time import beijing_now
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.portal import (approval_service, dingtalk_notice, fee_policy, invoice_adapter, order_queries,
                        order_service, quote_service)
from app.portal.errors import PortalError
from app.portal.inventory import InventoryObservation
from app.portal.models import OrderRequest, OutboxEvent, Publication, Quote, Revision
from app.portal.schemas import ApproveInput, CustomerQuoteInput, SitePolicy, SubmitInput

TERMS = [{"code": "bank", "display_text": "Bank transfer before shipment", "deposit_percent": "100.00",
          "method_label": "Bank transfer", "surcharge_percent": "0.00"},
         {"code": "paypal", "display_text": "PayPal before shipment", "deposit_percent": "100.00",
          "method_label": "PayPal", "surcharge_percent": "5.00"}]


def policy(enabled=True):
    return SitePolicy.model_validate({"payment_terms": TERMS, "default_payment_term_code": "bank",
                                      "auto_fees": {"enabled": enabled}})


@pytest.fixture
def fees(quoting):
    ctx = quoting
    ctx.site.policy_json = policy().model_dump(mode="json")
    ctx.db.commit()
    ctx.settings.PORTAL_DINGTALK_WEBHOOK_URL = ""
    return ctx


def quote(ctx, term=None, quantity=3):
    data = quote_body(ctx).model_dump(mode="json")
    data["items"][0]["quantity"] = quantity
    result = quote_service.create(ctx.db, ctx.session_token, ctx.session_csrf,
                                  CustomerQuoteInput.model_validate({**data, "payment_term_code": term}))
    ctx.db.commit()
    return result


def submit(ctx, result):
    receipt = order_service.submit(ctx.db, ctx.session_token, ctx.session_csrf, uuid4(), SubmitInput(
        quote_id=result["quote_id"], quote_content_hash=result["content_hash"], customer_po="PO-1", remark="Please review"))
    ctx.db.commit()
    return receipt


# ── pure fee rules ────────────────────────────────────────────────

@pytest.mark.parametrize("grams,shipping", [("0", "40.00"), ("300", "40.00"), ("300.5", "48.00"), ("1000", "64.00"),
                                            ("1800.01", "96.00"), ("2000", "96.00")])
def test_shipping_tier_upper_bound_is_inclusive(grams, shipping):
    term = policy().payment_terms[0]
    result = fee_policy.estimate(policy(), term, Decimal("100.00"), [Decimal(grams)])
    assert result["status"] == "confirmed" and result["shipping_amount"] == shipping


def test_paypal_surcharge_is_five_percent_of_hair_plus_shipping_rounded_half_up():
    paypal = policy().payment_terms[1]
    result = fee_policy.estimate(policy(), paypal, Decimal("534.20"), [Decimal("250")])
    # (534.20 + 40.00) x 5% = 28.71
    assert (result["surcharge_amount"], result["total_amount"]) == ("28.71", "602.91")
    assert result["surcharge_name"] == "Payment surcharge (PayPal 5%)"
    bank = fee_policy.estimate(policy(), policy().payment_terms[0], Decimal("534.20"), [Decimal("250")])
    assert (bank["surcharge_amount"], bank["surcharge_name"], bank["total_amount"]) == ("0.00", "", "574.20")


def test_heavy_unknown_or_disabled_needs_manual_fees():
    term = policy().payment_terms[0]
    over = fee_policy.estimate(policy(), term, Decimal("10.00"), [Decimal("2000.01")])
    assert (over["status"], over["reason"], over["weight_grams"]) == ("manual", "over_limit", "2000.01")
    unknown = fee_policy.estimate(policy(), term, Decimal("10.00"), [Decimal("20"), None])
    assert (unknown["status"], unknown["reason"]) == ("manual", "unknown_weight")
    assert "shipping_amount" not in over and "total_amount" not in unknown
    assert fee_policy.estimate(policy(enabled=False), term, Decimal("10.00"), [Decimal("20")]) is None


@pytest.mark.parametrize("change", [{"shipping_tiers": [{"max_grams": 600, "fee": "48.00"}, {"max_grams": 300, "fee": "40.00"}]},
                                    {"shipping_tiers": []}, {"shipping_tiers": [{"max_grams": 300, "fee": "40"}]}])
def test_policy_rejects_unordered_or_malformed_tiers(change):
    with pytest.raises(ValidationError):
        SitePolicy.model_validate({"payment_terms": TERMS, "default_payment_term_code": "bank",
                                   "auto_fees": {"enabled": True, **change}})


def test_legacy_policy_json_defaults_to_disabled_auto_fees():
    legacy = SitePolicy.model_validate({"payment_terms": [{"code": "prepaid", "display_text": "Prepaid",
        "deposit_percent": "100.00"}], "default_payment_term_code": "prepaid"})
    assert legacy.auto_fees.enabled is False and legacy.payment_terms[0].surcharge_percent == "0.00"
    assert [tier.max_grams for tier in legacy.auto_fees.shipping_tiers] == [300, 600, 800, 1000, 1300, 1600, 1800, 2000]


# ── quote and submission ─────────────────────────────────────────

def test_quote_carries_customer_chosen_payment_method_and_estimate(fees):
    bank = quote(fees)
    assert bank["payment_terms_snapshot"]["code"] == "bank"
    assert bank["items"][0]["unit_weight_grams"] == "20"
    assert bank["fees_confirmed_on_submit"] is True
    assert {key: bank["fee_estimate"][key] for key in ("weight_grams", "shipping_amount", "surcharge_amount", "total_amount")} \
        == {"weight_grams": "60", "shipping_amount": "40.00", "surcharge_amount": "0.00", "total_amount": "121.00"}
    paypal = quote(fees, "paypal")
    assert paypal["fee_estimate"]["surcharge_amount"] == "6.05" and paypal["fee_estimate"]["total_amount"] == "127.05"
    # The legacy quote contract is unchanged: fees stay pending and total stays unset on the quote itself.
    assert paypal["fees"]["status"] == "pending" and paypal["total_amount"] is None
    with pytest.raises(PortalError) as error:
        quote(fees, "crypto")
    assert error.value.code == "INVALID_INPUT"
    # Evidence covers the estimate: tampering invalidates the stored quote.
    row = fees.db.scalar(select(Quote).order_by(Quote.id.desc()))
    row.fee_estimate_json = {**row.fee_estimate_json, "total_amount": "1.00"}
    with pytest.raises(PortalError):
        quote_service.view(row)
    fees.db.rollback()


def test_disabled_auto_fees_keep_the_original_pending_flow(fees):
    fees.site.policy_json = policy(enabled=False).model_dump(mode="json")
    fees.db.commit()
    result = quote(fees)
    assert result["fee_estimate"] is None and result["fees_confirmed_on_submit"] is False
    receipt = submit(fees, result)
    assert receipt["status"] == "submitted" and receipt["total_amount"] is None
    assert fees.db.scalar(select(Revision)).kind == "submitted"


def test_confirmed_submission_is_accepted_and_waits_for_sales_review(fees):
    receipt = submit(fees, quote(fees, "paypal"))
    assert receipt["status"] == "ready_for_review" and receipt["total_amount"] == "127.05"
    order = fees.db.scalar(select(OrderRequest))
    revision = fees.db.scalar(select(Revision))
    assert order.accepted_revision_id == revision.id == order.active_revision_id
    assert revision.kind == "proposal" and revision.created_by is None and revision.fees_status == "confirmed"
    assert revision.customer_accepted_by == fees.account.id and revision.customer_accepted_at == order.submitted_at
    assert (revision.shipping_amount, revision.surcharge_amount, revision.packaging_amount) == (
        Decimal("40.00"), Decimal("6.05"), Decimal("0.00"))
    assert revision.surcharge_name == "Payment surcharge (PayPal 5%)"
    assert revision.expires_at == order.submitted_at + timedelta(hours=48)
    assert revision.authority_versions_json["sales_user_id"] == fees.access.sales_user_id
    detail = order_queries.detail_view(fees.db, order, show_price=True)
    assert detail["items"][0]["unit_weight_grams"] == "20"
    assert detail["proposal"]["accepted"] is True and detail["fees"]["surcharge_amount"] == "6.05"


def test_heavy_submission_stays_submitted_for_a_manual_shipping_quote(fees):
    fees.observations = {key: InventoryObservation(Decimal("100000"), "g", beijing_now(), "test")
                         for key in fees.observations}
    result = quote(fees, quantity=101)  # 2,020 g
    assert result["fee_estimate"]["status"] == "manual" and result["fee_estimate"]["reason"] == "over_limit"
    receipt = submit(fees, result)
    assert receipt["status"] == "submitted" and receipt["total_amount"] is None
    revision = fees.db.scalar(select(Revision))
    assert revision.kind == "submitted" and revision.fees_status == "pending"
    assert revision.total_amount is None and fees.db.scalar(select(OrderRequest)).accepted_revision_id is None


# ── sales review creates the formal PI ───────────────────────────

@pytest.fixture
def reviewable(fees, portal_metadata, monkeypatch):
    receipt = submit(fees, quote(fees, "paypal"))
    fees.db.execute(portal_metadata.tables["ark_users"].insert(), {"id": 2, "is_active": True})
    metadata = MetaData()
    from app.core.database import Base
    for name in ("ark_user_roles", "ark_roles", "ark_role_permissions", "ark_permissions"):
        source = Base.metadata.tables[name]
        Table(name, metadata, *(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in source.columns))
    Table(InvoiceDelegateGrant.__tablename__, metadata, *(Column(c.name, Integer() if c.primary_key else c.type,
        primary_key=c.primary_key, nullable=c.nullable) for c in InvoiceDelegateGrant.__table__.columns))
    metadata.create_all(fees.db.get_bind())
    fees.settings.PORTAL_INVOICE_ENABLED = True
    invoices = invoice_adapter.invoices
    monkeypatch.setattr(invoices, "resolve_okki_flags", lambda *args: {"okki_new_deal": 1, "okki_free_shipping": 0, "okki_first_return": 0})
    monkeypatch.setattr(invoices, "get_customer_grade", lambda *args: None)
    monkeypatch.setattr(invoices, "suggest_invoice_no", lambda *args: "PI-PORTAL-FEES")
    monkeypatch.setattr(invoices.product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    fees.db.commit()
    return fees, receipt


def test_one_click_sales_review_creates_the_formal_pi_with_weight(reviewable):
    ctx, receipt = reviewable
    order = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.scalar(select(Revision))
    result = approval_service.approve(ctx.db, 1, order.public_id, order.row_version,
                                      ApproveInput(accepted_revision_id=revision.public_id))
    ctx.db.commit()
    assert result["current_state"] == "invoice_created"
    invoice = ctx.db.get(Invoice, order.invoice_id)
    assert (invoice.shipping_fee, invoice.surcharge_amount, invoice.total_amount) == (
        Decimal("40.00"), Decimal("6.05"), Decimal("127.05"))
    assert invoice.surcharge_name == "Payment surcharge (PayPal 5%)"
    publication = ctx.db.scalar(select(Publication))
    assert publication.render_template_version == "portal-pi-v2"
    assert publication.customer_snapshot_json["items"][0]["unit_weight_grams"] == "20"


def test_expired_review_window_requires_a_fresh_proposal(reviewable, monkeypatch):
    ctx, _ = reviewable
    order = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.scalar(select(Revision))
    later = revision.expires_at + timedelta(seconds=1)
    from app.portal import proposal_decisions
    monkeypatch.setattr(proposal_decisions, "beijing_now", lambda: later)
    with pytest.raises(PortalError) as error:
        approval_service.approve(ctx.db, 1, order.public_id, order.row_version,
                                 ApproveInput(accepted_revision_id=revision.public_id))
    assert error.value.code == "PROPOSAL_EXPIRED"
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 0


# ── DingTalk group notices ───────────────────────────────────────

def test_dingtalk_rows_exist_only_when_configured(fees, monkeypatch):
    monkeypatch.setattr(dingtalk_notice, "get_settings", lambda: fees.settings)
    submit(fees, quote(fees))
    assert fees.db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "dingtalk_notice")) == 0
    fees.settings.PORTAL_DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=x"
    submit(fees, quote(fees, "paypal"))
    row = fees.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "dingtalk_notice"))
    assert row.payload_json["source"] == "order_submitted" and row.status == "pending"


class Sender:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or {"errcode": 0}, error, []

    async def send_markdown(self, title, text):
        self.calls.append((title, text))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def notice(fees, monkeypatch):
    fees.settings.PORTAL_DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=x"
    fees.settings.PORTAL_ENABLED = True
    fees.settings.PORTAL_EMPLOYEE_ORIGIN = "https://ark.example.com"
    monkeypatch.setattr(dingtalk_notice, "get_settings", lambda: fees.settings)
    monkeypatch.setattr("app.portal.dingtalk_notice.lock_authority", lambda db, force=False: None)
    monkeypatch.setattr("app.portal.mail_worker.lock_authority", lambda db, force=False: None)
    submit(fees, quote(fees, "paypal"))
    factory = lambda: _Session(fees.db)  # noqa: E731
    return fees, factory


class _Session:
    """Reuse the isolated test session; the worker only needs commit and context management."""
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def test_dingtalk_notice_renders_customer_total_weight_and_ark_link(notice):
    ctx, factory = notice
    sender = Sender()
    assert dingtalk_notice.run_once(factory, sender=sender) == "sent"
    [(title, text)] = sender.calls
    order = ctx.db.scalar(select(OrderRequest))
    assert title == "门户新订单待审核"
    assert "USD 127.05" in text and "60 g" in text and "PayPal" in text and order.public_no in text
    assert f"https://ark.example.com/portal/orders?request={order.public_id}" in text
    assert "一键审核" in text
    assert dingtalk_notice.run_once(factory, sender=sender) == "idle"


def test_dingtalk_uncertain_delivery_is_never_resent(notice):
    from app.dingtalk.webhook import DingTalkWebhookError
    ctx, factory = notice
    sender = Sender(error=DingTalkWebhookError(130101, "系统繁忙"))
    assert dingtalk_notice.run_once(factory, sender=sender) == "uncertain"
    assert dingtalk_notice.run_once(factory, sender=sender) == "idle"
    assert len(sender.calls) == 1


def test_dingtalk_definite_failure_retries_later(notice):
    import httpx
    ctx, factory = notice
    sender = Sender(error=httpx.ConnectError("down"))
    assert dingtalk_notice.run_once(factory, sender=sender) == "pending"
    row = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "dingtalk_notice"))
    assert row.last_error_code == "DINGTALK_SEND_FAILED" and row.next_attempt_at > beijing_now()


def test_customer_markdown_cannot_inject_links():
    assert dingtalk_notice._plain("Evil [click](https://x) @all # heading") == "Evil clickhttps://x all heading"
    assert dingtalk_notice._plain("Line\nbreak\t### title") == "Line break title"


def test_dingtalk_webhook_configuration_is_validated():
    from app.portal.configuration import validate_configuration
    settings = SimpleNamespace(PORTAL_NOTIFICATION_ENABLED=False, PORTAL_ENABLED=False, PORTAL_WRITES_ENABLED=False,
        PORTAL_INVOICE_ENABLED=False, PORTAL_EMPLOYEE_ORIGIN="https://ark.example.com", APP_ENV="production",
        PORTAL_DINGTALK_WEBHOOK_URL="https://evil.example.com/robot/send?access_token=x")
    with pytest.raises(ValueError):
        validate_configuration(settings)
    settings.PORTAL_DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=x"
    validate_configuration(settings)
