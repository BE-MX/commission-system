"""Actual Ark onboarding/catalog pages with a newly UI-created access record."""
import json
from pathlib import Path
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem
from app.portal.models import (Account, AuditEvent, AuthChallenge, CatalogGrant, CatalogItem, Conversion, CustomerAccess,
    Invitation, Membership, OrderRequest, PortalSession, Publication, Quote)
from app.receipt.models import ReceiptIntent
from test_mysql_application_trade import commerce  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_customer_application_browser import ROOT, broker_call, live_application, run_browser


def rows(db, model, condition=None):
    statement = select(*model.__table__.columns).order_by(model.id)
    if condition is not None: statement = statement.where(condition)
    return tuple(tuple(row) for row in db.execute(statement).all())


@pytest.mark.parametrize('commerce', ['other_scope_admin'], indirect=True)
def test_actual_application_onboarding_and_catalog_access(commerce, request):
    c = commerce
    runtime = [request.config.getoption('portal_browser_' + name) for name in ('node', 'module', 'chromium')]
    if not all(runtime): pytest.skip('Explicit owned browser runtimes required')
    node, playwright, chrome = (str(Path(value).resolve(strict=True)) for value in runtime)
    output = Path(request.config.getoption('portal_mysql_workspace')).resolve() / 'onboarding-evidence'
    output.mkdir()
    financial = (Invoice, InvoiceItem, ReceiptIntent, Conversion, Publication, OrderRequest)
    with Session(c.app.ctx.engine) as db:
        assert db.scalar(select(CustomerAccess.id).where(CustomerAccess.customer_id == c.onboard_customer_id)) is None
        old_access = rows(db, CustomerAccess)
        old_grants = rows(db, CatalogGrant)
        old_catalog = rows(db, CatalogItem)
        old_financial = tuple(rows(db, model) for model in financial)
    with live_application(c) as (origin, shell):
        absent, headers, _ = broker_call(origin, '/__owned/invitation/' + str(uuid4()), shell.broker_key)
        assert absent == 404 and headers['cache-control'] == 'no-store'
        summary = run_browser(c, shell, node, ROOT / 'frontend-portal/tests/applicationOnboarding.browser.mjs', origin, playwright, chrome, output)
        (output / 'runner-summary.json').write_text(json.dumps(summary), encoding='utf-8')
        assert not summary['timed_out'] and summary['exit_code'] == 0, 'Owned onboarding browser failed; inspect safe evidence'
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['status'] == 'pass' and report['apiInterceptions'] == 0 and len(report['scenarios']) == 8
        access_id, quote_id = str(UUID(report['accessId'])), str(UUID(report['quoteId']))
        restored_quote_id, login_challenge_id = str(UUID(report['restoredQuoteId'])), str(UUID(report['loginChallengeId']))
        assert len(shell.invitation_landing_snapshots) == 2
        assert shell.invitation_landing_snapshots[0] == shell.invitation_landing_snapshots[1]
        assert shell.invited_account_id is not None and shell.otp_reads[shell.invited_account_id] == 2
        with Session(c.app.ctx.engine) as db:
            accesses = db.scalars(select(CustomerAccess).where(CustomerAccess.customer_id == c.onboard_customer_id)).all()
            assert len(accesses) == 1
            access = accesses[0]
            assert access.public_id == access_id and access.status == 'enabled'
            assert access.can_order and access.can_view_price and access.sales_user_id == c.app.ctx.actor
            assert access.assignment_id == c.onboard_assignment_id and access.external_identity_id == c.onboard_identity_id
            assert access.okki_namespace == 'okki:test' and access.okki_company_id == str(c.onboard_customer_id)
            assert access.catalog_version == report['createdCatalogVersion'] + 2
            assert access.row_version == report['createdRowVersion'] + 3
            assert db.scalar(select(CustomerAccess.id).where(CustomerAccess.customer_id == c.blocked_customer_id)) is None
            grants = db.scalars(select(CatalogGrant).where(CatalogGrant.access_id == access.id)).all()
            item = db.scalar(select(CatalogItem).where(CatalogItem.public_id == c.item_id))
            assert len(grants) == 1 and grants[0].status == 'enabled' and grants[0].catalog_item_id == item.id
            quote = db.scalar(select(Quote).where(Quote.public_id == quote_id))
            assert quote is not None and quote.access_id == access.id and quote.status == 'expired'
            invited = db.get(Account, shell.invited_account_id)
            invitation = db.get(Invitation, shell.invited_invitation_id)
            member = db.get(Membership, invitation.membership_id)
            assert invited.status == 'active' and invited.email_normalized == c.onboard_invited_email and invited.verified_at is not None
            assert invitation.access_id == access.id and invitation.created_by == c.app.ctx.admin and invitation.consumed_at is not None
            assert access.auth_version == invitation.access_version + 2
            assert member.account_id == invited.id and member.access_id == access.id and member.status == 'active'
            sessions = db.scalars(select(PortalSession).where(PortalSession.account_id == invited.id).order_by(PortalSession.id)).all()
            assert len(sessions) == 2
            assert sessions[0].revoked_at is not None and sessions[1].revoked_at is None
            assert sessions[0].access_version == invitation.access_version
            assert sessions[1].access_version == access.auth_version
            assert sessions[0].membership_id == sessions[1].membership_id == member.id
            login_challenge = db.scalar(select(AuthChallenge).where(AuthChallenge.public_id == login_challenge_id))
            assert login_challenge.account_id == invited.id and login_challenge.purpose == 'login'
            assert login_challenge.invitation_id is None and login_challenge.consumed_at is not None
            assert login_challenge.revoked_at is None
            restored_quote = db.scalar(select(Quote).where(Quote.public_id == restored_quote_id))
            assert restored_quote.access_id == access.id and restored_quote.status == 'valid'
            assert restored_quote.authority_versions_json['catalog'] == access.catalog_version
            assert restored_quote.authority_versions_json['access'] == access.auth_version
            assert quote.authority_versions_json['access'] == invitation.access_version
            assert restored_quote.account_id == quote.account_id == invited.id
            assert restored_quote.membership_id == quote.membership_id == member.id
            assert restored_quote.id != quote.id
            types = db.scalars(select(AuditEvent.action).where(AuditEvent.access_id == access.id)).all()
            assert types.count('access_created') == types.count('access_updated') == types.count('invitation_created') == 1
            assert types.count('catalog_access_updated') == 2
            assert rows(db, CustomerAccess, CustomerAccess.id != access.id) == old_access
            assert rows(db, CatalogGrant, CatalogGrant.access_id != access.id) == old_grants
            assert rows(db, CatalogItem) == old_catalog
            assert tuple(rows(db, model) for model in financial) == old_financial
        (output / 'server-evidence.json').write_text(json.dumps({'scope': 'owned actual application onboarding',
            'newAccessCount': 1, 'blockedAccessCount': 0, 'catalogUpdates': 2, 'expiredQuoteCount': 1,
            'revokedNewSessionCount': 1, 'activeRenewedSessionCount': 1, 'freshQuoteCount': 1, 'otherCustomersAndFinancialGraphUnchanged': True}), encoding='utf-8')
    assert c.calls == [] and c.forbidden_writes == []
