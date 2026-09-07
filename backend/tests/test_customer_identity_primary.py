"""Regression for MySQL's active primary slot, absent from SQLite metadata."""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.customer.identity_service import attach_identity_candidate, resolve_business_context
from app.customer.models import CustomerExternalIdentity, CustomerAccount, CustomerResearchTask, SearchResult, CustomerSourceRecord
from app.sales_automation import service
from tests.test_customer_acquisition_workflow import _running_search_job, _candidate, _account


@pytest.fixture
def primary_db(engine):
    with engine.begin() as connection:
        connection.execute(text('''CREATE UNIQUE INDEX test_mysql_primary_identity_slot
            ON ark_customer_external_identities
            (COALESCE(customer_id, -1), COALESCE(contact_id, -1), identifier_type)
            WHERE is_primary = 1 AND status = 'active' '''))
    with Session(engine, autoflush=False) as db:
        yield db


def test_committed_batch_then_changed_score_preserves_primary_and_sources(primary_db):
    db = primary_db
    job, token = _running_search_job(db)
    job_id = job.id
    candidates = [_candidate(external_record_id=f'page-{i}', source_url=f'https://example.com/{i}', score=90)
                  | {'external_context_id': f'company-{i}', 'website': f'https://company-{i}.example'}
                  for i in range(10)]
    receipt = service.ingest_candidates(db, job_id, candidates, 'batch-1', 1, 'search-agent', token)
    db.commit()
    db.expunge_all()
    assert service.ingest_candidates(db, job_id, candidates, 'batch-1', 1, 'search-agent', token) == receipt
    db.commit()
    service.ingest_candidates(db, job_id, [dict(c, score=89) for c in candidates[:5]], 'batch-2', 1, 'search-agent', token)
    db.commit()
    assert db.query(CustomerAccount).count() == 10
    assert db.query(SearchResult).count() == 10
    assert db.query(CustomerResearchTask).count() == 10
    assert db.query(CustomerSourceRecord).count() == 15
    assert db.query(CustomerExternalIdentity).filter_by(is_primary=True, status='active').count() == 10


@pytest.mark.parametrize('account_key,value', [('global', 'second.example'), ('another', 'first.example')])
def test_existing_primary_is_preserved_across_values_and_namespaces(primary_db, account_key, value):
    db = primary_db
    customer = _account(db, 'PRIMARY-1')
    def attach(key, domain):
        return attach_identity_candidate(db, customer_id=customer.id, source_system='public_web',
            source_account_key=key, identifier_type='website_domain', raw_value=domain, is_primary=True)
    first = attach('global', 'first.example')
    second = attach(account_key, value)
    replay = attach(account_key, value)
    assert first.is_primary is True
    assert second.id == replay.id != first.id
    assert second.is_primary is False
    assert db.query(CustomerExternalIdentity).count() == 2


def test_same_weak_domain_does_not_merge_customers(primary_db):
    db = primary_db
    left, right = _account(db, 'LEFT'), _account(db, 'RIGHT')
    rows = [attach_identity_candidate(db, customer_id=c.id, source_system='public_web',
            source_account_key='global', identifier_type='website_domain', raw_value='shared.example',
            is_primary=True) for c in (left, right)]
    assert rows[0].id != rows[1].id
    assert all(row.is_primary for row in rows)


def test_contact_primary_slot_is_also_shared_across_namespaces(primary_db):
    db = primary_db
    resolved = resolve_business_context(db, source_system='alibaba', source_account_key='shop',
        source_entity_type='inquiry', external_context_id='contact-primary', contact_name='Buyer')
    def attach(namespace):
        return attach_identity_candidate(db, contact_id=resolved.contact.id, source_system='okki',
            source_account_key=namespace, identifier_type='contact_id', raw_value='CONTACT-1',
            is_primary=True)
    first = attach('one')
    second = attach('two')
    replay = attach('two')
    assert first.is_primary is True
    assert second.id == replay.id != first.id
    assert second.is_primary is False


def test_reactivating_old_primary_cannot_take_current_primary_slot(primary_db):
    db = primary_db
    customer = _account(db, 'REACTIVATE')
    def attach(domain, **kwargs):
        return attach_identity_candidate(db, customer_id=customer.id, source_system='public_web',
            source_account_key='global', identifier_type='website_domain', raw_value=domain, **kwargs)
    old = attach('old.example', is_primary=True)
    old.status = 'inactive'
    db.flush()
    current = attach('current.example', is_primary=True)
    restored = attach('old.example', verification_status='verified')
    assert restored.id == old.id
    assert restored.status == 'active'
    assert restored.is_primary is False
    assert current.is_primary is True
