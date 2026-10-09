"""Synthetic upstream columns/data; real migrated portal schema and real auth/services."""
from datetime import timedelta
from ipaddress import IPv4Address
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import secrets

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import Column, MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission, ArkLoginLog, ArkRefreshToken
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity, CustomerObjectOwnership, CustomerSourceRecord, CustomerContactRelationship
from app.invoice.models import Invoice, InvoiceItem, InvoiceDelegateGrant, StdPrice, PriceColorType, CustomerPriceRule
from app.receipt.models import ReceiptIntent
from app.core.time import beijing_now
from app.portal import auth_service as auth, admin_service, authority, quote_service, sku_source, pricing, catalog_service, order_queries, invoice_adapter
from app.portal.access_policy import binding_fingerprint
from app.portal.inventory import InventoryObservation
from app.portal.models import Account, Site, CustomerAccess, Membership, CatalogItem, CatalogGrant, OutboxEvent
from app.portal.schemas import ChallengeInput, VerifyInput, QuoteInput, SubmitInput
from app.portal.security import open_secret


@pytest.fixture(scope='session')
def service_schema(migrated):
    # Add only columns required to execute real domain services. These are upstream
    # fixtures, NOT migrations or proof of the complete upstream schema.
    models = (ArkUser, CustomerAccount, CustomerAssignment, CustomerExternalIdentity, CustomerObjectOwnership, CustomerSourceRecord, CustomerContactRelationship,
        ArkRole, ArkPermission, ArkUserRole, ArkRolePermission, Invoice, InvoiceItem, InvoiceDelegateGrant,
        ReceiptIntent, StdPrice, PriceColorType, CustomerPriceRule, ArkLoginLog, ArkRefreshToken)
    for model in models:
        with migrated.begin() as connection:
            inspector = inspect(connection)
            if inspector.has_table(model.__tablename__):
                existing = {column['name'] for column in inspector.get_columns(model.__tablename__)}
                operations = Operations(MigrationContext.configure(connection))
                for column in model.__table__.columns:
                    if column.name not in existing:
                        operations.add_column(model.__tablename__, Column(column.name, column.type, nullable=True))
            else:
                metadata = MetaData()
                Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
                    nullable=False if c.primary_key else True) for c in model.__table__.columns))
                metadata.create_all(connection)
    with migrated.begin() as connection:
        connection.execute(text('CREATE TABLE okki_products (product_id BIGINT PRIMARY KEY, product_name VARCHAR(255), model VARCHAR(128), color VARCHAR(128), size VARCHAR(32), unit VARCHAR(32), disable_flag INT)'))
        connection.execute(text('CREATE TABLE okki_product_skus (product_id BIGINT, sku_id BIGINT PRIMARY KEY, disable_flag INT)'))
    with Session(migrated) as db:
        root = ArkUser(username='mysql-admin', password_hash='test-only-not-a-login', real_name='Test Admin', is_active=True)
        roles = [ArkRole(name='super_admin', label='Admin'), ArkRole(name='sales', label='Sales')]
        db.add_all([root, *roles]); db.flush()
        db.add(ArkUserRole(user_id=root.id, role_id=roles[0].id))
        for code in ('portal_access:admin', 'portal_order:read', 'portal_order:write', 'invoice:write'):
            module, action = code.split(':')
            permission = ArkPermission(code=code, module=module, action=action, label=code, kind='action', is_legacy=False, sort=1)
            db.add(permission); db.flush()
            db.add(ArkRolePermission(role_id=roles[1].id, permission_id=permission.id))
        db.add(StdPrice(product_kind='hair', series_grade='Standard Straight', length='20', weight_unit='20g', color_type='solid', price=Decimal('30'), currency='USD'))
        root_id, sales_role_id = root.id, roles[1].id
        db.commit()
    return SimpleNamespace(engine=migrated, admin=root_id, sales_role=sales_role_id)


@pytest.fixture
def trade(service_schema, monkeypatch, request):
    # Retain historical business rows, but do not carry a case's live mailbox
    # into later cases which may advance time. Cleanup runs after assertions
    # and after dependent fixtures have joined their workers/child processes.
    with Session(service_schema.engine) as db:
        previous_events = set(db.scalars(select(OutboxEvent.id)).all())
    def cleanup_owned_mailbox():
        from app.portal.mail_worker import close_event
        with Session(service_schema.engine) as db:
            rows = db.scalars(select(OutboxEvent).where(OutboxEvent.id.not_in(previous_events),
                OutboxEvent.status.in_(['pending', 'sending']))).all()
            for row in rows:
                close_event(row, 'cancelled', 'TEST_FIXTURE_CLEANUP')
            db.commit()
    request.addfinalizer(cleanup_owned_mailbox)
    suffix = uuid4().hex[:12]
    settings = SimpleNamespace(PORTAL_ENABLED=True, PORTAL_SITE_CODE='test' + suffix,
        PORTAL_ORIGIN='https://orders.example.test', PORTAL_OTP_SECRET=secrets.token_urlsafe(32),
        PORTAL_CSRF_KEYS={'v1': 'c'*32}, PORTAL_CSRF_KEY_VERSION='v1',
        PORTAL_MAIL_KEYS={'v1': 'ab'*32}, PORTAL_MAIL_KEY_VERSION='v1',
        PORTAL_OTP_MINUTES=5, PORTAL_SESSION_HOURS=12, PORTAL_SESSION_IDLE_MINUTES=30,
        PORTAL_WRITES_ENABLED=True, PORTAL_INVOICE_ENABLED=True, PORTAL_OKKI_NAMESPACE='okki:test',
        PORTAL_INVENTORY_MAX_AGE_SECONDS=120, PORTAL_INVITATION_HOURS=72, PORTAL_LOCK_WAIT_SECONDS=5)
    for module in (auth, admin_service, authority, quote_service, sku_source, pricing, catalog_service, order_queries):
        monkeypatch.setattr(module, 'get_settings', lambda: settings)
    monkeypatch.setattr(sku_source.product_service, '_schema', lambda: 'portal_isolated_test')
    invoices = invoice_adapter.invoices
    monkeypatch.setattr(invoices, 'resolve_okki_flags', lambda *args: {'okki_new_deal':1, 'okki_free_shipping':0, 'okki_first_return':0})
    monkeypatch.setattr(invoices, 'get_customer_grade', lambda *args: None)
    monkeypatch.setattr(invoices, 'suggest_invoice_no', lambda *args: 'PI-TEST-' + uuid4().hex)
    monkeypatch.setattr(invoices.product_service, 'valid_okki_product_skus', lambda db, pairs: pairs)
    engine = service_schema.engine
    with Session(engine) as db:
        user = ArkUser(username='sales-' + suffix, password_hash='test-only-not-a-login', real_name='Test Sales', is_active=True)
        company = CustomerAccount(display_name='Buyer ' + suffix, canonical_company_name='Buyer Company', record_status='active', identity_status='verified')
        account = Account(email_normalized=suffix+'@example.test', email_display=suffix+'@example.test', contact_name='Buyer', status='active', verified_at=beijing_now())
        site = Site(code=settings.PORTAL_SITE_CODE, name='Test Portal', status='enabled', allowed_origin=settings.PORTAL_ORIGIN,
            policy_json={'payment_terms':[{'code':'prepaid', 'display_text':'Payment before shipment', 'deposit_percent':'100.00'}], 'default_payment_term_code':'prepaid'})
        db.add_all([user, company, account, site]); db.flush()
        db.add(ArkUserRole(user_id=user.id, role_id=service_schema.sales_role))
        identity = CustomerExternalIdentity(customer_id=company.id, source_system='okki', source_account_key='okki:test',
            identifier_type='company_id', raw_value=str(company.id), normalized_value=str(company.id), identity_strength='strong',
            cardinality='one_to_one', verification_status='verified', status='active')
        assignment = CustomerAssignment(customer_id=company.id, user_id=user.id, assignment_role='primary', assignment_status='active',
            assignment_source='manual', effective_from=beijing_now()-timedelta(days=1))
        db.add_all([identity, assignment]); db.flush()
        access = CustomerAccess(site_id=site.id, customer_id=company.id, okki_namespace='okki:test', okki_company_id=str(company.id),
            external_identity_id=identity.id, assignment_id=assignment.id, sales_user_id=user.id, status='enabled',
            can_order=True, can_view_price=True, binding_fingerprint=binding_fingerprint(company.id, identity, assignment))
        db.add(access); db.flush()
        member = Membership(site_id=site.id, account_id=account.id, access_id=access.id, status='active')
        db.add(member)
        db.add(CustomerPriceRule(customer_id=str(company.id), adjust_type='percent', adjust_value=Decimal('-10'), enabled=1))
        product_id = 1000 + company.id
        db.execute(text("INSERT INTO okki_products VALUES (:id,'Standard Straight/20','ST','1','20','20g',0)"), {'id': product_id})
        db.execute(text('INSERT INTO okki_product_skus VALUES (:id,:id,0)'), {'id': product_id})
        snapshot = sku_source.load_snapshot(db, namespace='okki:test', product_id=str(product_id), sku_id=str(product_id), product_kind='hair')
        item = CatalogItem(site_id=site.id, product_kind='hair', source_namespace='okki:test', product_id=str(product_id), sku_id=str(product_id),
            standard_json=snapshot['standard_json'], standard_fingerprint=snapshot['standard_fingerprint'], display_name='Standard Straight',
            color_name='Black', status='published', inventory_unit='g', sale_unit='pack', conversion_factor=Decimal('20'))
        db.add(item); db.flush(); db.add(CatalogGrant(access_id=access.id, catalog_item_id=item.id)); db.commit()
        monkeypatch.setattr(catalog_service, 'load_observations', lambda db, rows: {
            item.public_id: InventoryObservation(Decimal('1000'), 'g', beijing_now(), 'synthetic-test-mirror')})
        # Each synthetic buyer originates from a distinct loopback address.
        # Keep the real 30/hour quota; unrelated fixtures must not share its bucket.
        client_ip = str(IPv4Address(0x7f000000 + company.id))
        preauth, token, csrf = auth.bootstrap(db, client_ip); db.commit()
        challenge = auth.challenge(db, auth.require_preauth(db, token, csrf), ChallengeInput(email=account.email_normalized, purpose='login'), client_ip)
        db.commit()
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge.public_id))
        code = open_secret(settings.PORTAL_MAIL_KEYS['v1'], event.secret_envelope, event_key=event.event_key, purpose='login', object_id=challenge.public_id)
        principal, session, session_token = auth.verify(db, auth.require_preauth(db, token, csrf), VerifyInput(challenge_id=challenge.public_id, code=code), client_ip)
        db.commit()
        delivery = {'contact_name':'Buyer', 'phone':'+44 10000000', 'address_line1':'10 Test Street', 'city':'London', 'country_code':'GB'}
        quote_body = QuoteInput(items=[{'item_id':item.public_id, 'quantity':3}], delivery=delivery, customer_po='PO-'+suffix, remark='')
        session_csrf = auth._csrf(session)
        quote = quote_service.create(db, session_token, session_csrf, quote_body); db.commit()
        result = SimpleNamespace(engine=engine, actor=user.id, admin=service_schema.admin, account_id=account.id, account_public_id=account.public_id,
            account_version=account.row_version, token=session_token, csrf=session_csrf, session_id=session.id,
            item_id=item.public_id, access_id=access.id, key=uuid4(), quote_body=quote_body,
            body=SubmitInput(quote_id=quote['quote_id'], quote_content_hash=quote['content_hash'], customer_po=quote_body.customer_po, remark=''))
    return result
