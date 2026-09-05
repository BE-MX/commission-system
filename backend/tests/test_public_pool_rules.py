"""Business thresholds, rule snapshots and API authorization on isolated SQLite."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.customer.models import CustomerContactPoint, CustomerConversation, CustomerOrder, CustomerOrderItem, CustomerResearchTask
from app.sales_automation import pool_rule_service, public_pool_service
from app.sales_automation.pool_rule_schema import PoolRules, PoolQuotas, PoolRuleInput, PoolRuleSave, PoolConfiguredBatch
from app.sales_automation.pool_selection import evaluate, matches_commerce
from app.sales_automation.service import ConflictError
from tests.test_customer_workflow import _source_record
from tests.test_public_pool_research import _account, _seed_user
from tests.test_customer_workbench import hub


NOW = datetime(2026, 9, 6, 0, 5)


def seed_candidate(db, code="POOL", *, amount=1001, channel="instagram", days=181, followup_days=31, item_type="bulk", product="Genius Weft"):
    account = _account(db, code)
    account.primary_country_code = "US"
    source = _source_record(db, account, record_id=account.id + 9000)
    order = CustomerOrder(customer_id=account.id, source_system="okki", source_account_key="test", external_order_id=code, account_date=(NOW-timedelta(days=days)).date(), amount_usd=amount, is_valid_business_order=True, source_record_id=source.id, source_hash=f"{account.id:064x}", synced_at=NOW)
    db.add(order)
    db.flush()
    item = CustomerOrderItem(order_id=order.id, product_name=product, item_type=item_type, source_record_id=source.id, item_fingerprint=f"{order.id:064x}")
    point = CustomerContactPoint(customer_id=account.id, point_type="phone" if channel == "phone" else "social", platform=None if channel == "phone" else channel, raw_value=code, normalized_value=code, verification_status="unknown", contactability_status="unknown", is_primary=False, data_classification="public_business", point_fingerprint=f"{account.id:064x}", first_seen_at=NOW, last_seen_at=NOW)
    conversation = CustomerConversation(customer_id=account.id, source_system="email", source_account_key="test", external_conversation_id=code, channel="email", conversation_status="active", last_message_at=None if followup_days is None else NOW-timedelta(days=followup_days))
    db.add_all([item, point, conversation])
    db.flush()
    return account, order, item, point, conversation


def run(db, rules=None, quotas=None):
    return evaluate(db, rules or PoolRules(), quotas or PoolQuotas(), now=NOW)


@pytest.mark.parametrize("amounts,types,expected", [
    ([750,750], ["bulk","bulk"], (False,False)), ([750,751], ["bulk","bulk"], (True,False)),
    ([1000], ["bulk"], (False,False)), ([1000.01], ["bulk"], (True,False)),
    ([10,20], ["sample","sample"], (False,True)), ([10,20], ["sample","unknown"], (False,False)),
    ([], [], (False,False)),
])
def test_strict_money_and_sample_branches(amounts, types, expected):
    orders = [SimpleNamespace(id=i, amount_usd=a) for i,a in enumerate(amounts)]
    items = {i:[SimpleNamespace(item_type=t)] for i,t in enumerate(types)}
    assert matches_commerce(orders, items, PoolRules().commerce) == expected


def test_missing_items_never_sample():
    assert matches_commerce([SimpleNamespace(id=1, amount_usd=10)], {1:[]}, PoolRules().commerce) == (False, False)


def test_default_rules_all_clauses_and_instagram_priority(db):
    phone = seed_candidate(db, "PHONE", channel="phone")
    instagram = seed_candidate(db, "INSTAGRAM")
    recent = seed_candidate(db, "RECENT", days=180)
    missing = seed_candidate(db, "MISSING", followup_days=None)
    low = seed_candidate(db, "LOW", amount=1000)
    wrong = seed_candidate(db, "WRONG", product="Flat Weft")
    sample = seed_candidate(db, "SAMPLE", amount=20, item_type="sample", product="平型")
    selected, summary = run(db, quotas=PoolQuotas(total_limit=1))
    assert [i["account"].id for i in selected] == [instagram[0].id]
    assert summary["eligible_count"] == 3
    excluded = {r["code"]: r["count"] for r in summary["exclusions"]}
    assert excluded["recent_order"] == excluded["followup_missing"] == excluded["commerce"] == excluded["product"] == 1
    assert excluded["quota"] == 2
    assert db.query(CustomerResearchTask).count() == 0


@pytest.mark.parametrize("change,reason", [
    ("country", "country"), ("contact", "contact"), ("date", "order_date_missing"),
    ("followup", "recent_followup"), ("glue", "product"), ("unknown", "commerce"), ("blank_contact", "contact"),
])
def test_exclusions_and_exact_followup_boundary(db, change, reason):
    a,o,i,p,c = seed_candidate(db)
    if change == "country": a.primary_country_code = "CN"
    if change == "contact": p.contactability_status = "opted_out"
    if change == "date": o.account_date = None
    if change == "followup": c.last_message_at = NOW-timedelta(days=30)
    if change == "glue": i.product_name = "贴发胶"
    if change == "unknown": o.amount_usd, i.item_type = 20, "unknown"
    if change == "blank_contact": p.normalized_value = "   "
    db.flush()
    selected, summary = run(db)
    assert not selected
    assert {r["code"]:r["count"] for r in summary["exclusions"]}[reason] == 1


def test_optional_sample_product_and_missing_followup(db):
    seed_candidate(db, amount=10, product="Other", item_type="sample", followup_days=None)
    assert not run(db)[0]
    rule = PoolRules(missing_followup="include")
    rule.commerce.sample_requires_product = False
    assert len(run(db, rule)[0]) == 1


def test_version_conflict_batch_snapshot_and_replay(db, monkeypatch):
    _seed_user(db)
    seed_candidate(db)
    monkeypatch.setattr(public_pool_service, "beijing_now", lambda: NOW)
    initial = pool_rule_service.get_config(db)
    assert initial["version"] == 0 and not initial["active"]
    saved = pool_rule_service.save_config(db, PoolRuleSave(rules=PoolRules(), quotas=PoolQuotas(), expected_version=0), 1)
    with pytest.raises(ConflictError):
        pool_rule_service.save_config(db, PoolRuleSave(rules=PoolRules(), quotas=PoolQuotas(), expected_version=0), 1)
    db.rollback()
    batch, _ = public_pool_service.prepare_batch(db, pool_rule_service.batch_payload(db, expected_version=1), 1)
    rules = PoolRules(countries=["CN"])
    pool_rule_service.save_config(db, PoolRuleSave(rules=rules, quotas=PoolQuotas(), expected_version=1), 1)
    batch_id = batch.id
    db.commit()
    completed = public_pool_service.execute_batch(db, batch_id)
    assert completed.selection_snapshot["selected_count"] == 1
    assert completed.selection_snapshot["policy"]["countries"] == saved["rules"]["countries"]
    db.commit()
    assert public_pool_service.execute_batch(db, batch_id).id == batch_id
    assert db.query(CustomerResearchTask).count() == 1
    with pytest.raises(ConflictError):
        pool_rule_service.create_configured_batch(db, PoolConfiguredBatch(expected_version=1), 1)
    db.rollback()
    new_batch = pool_rule_service.create_configured_batch(db, PoolConfiguredBatch(expected_version=2), 1)
    assert new_batch.selection_snapshot["selected_count"] == 0


def test_rules_api_requires_admin_and_validates_json(db, hub):
    client, identity, *_ = hub
    db.commit()
    assert client.get('/api/customer-hub/public-pool/rules').status_code == 403
    identity['permissions'].append('sales_automation:admin')
    config = client.get('/api/customer-hub/public-pool/rules').json()['data']
    payload = {"rules": config["rules"], "quotas": config["quotas"], "expected_version":0}
    payload['rules']['mystery'] = True
    assert client.put('/api/customer-hub/public-pool/rules', json=payload).status_code == 422
    del payload['rules']['mystery']
    saved = client.put('/api/customer-hub/public-pool/rules', json=payload)
    assert saved.status_code == 200
    assert saved.json()['data']['version'] == 1
    assert client.put('/api/customer-hub/public-pool/rules', json=payload).status_code == 409
    assert client.post('/api/customer-hub/public-pool/rules/preview', json={k:v for k,v in payload.items() if k != 'expected_version'}).status_code == 200


@pytest.mark.parametrize("field", ["product_terms", "product_exclusions"])
def test_normalized_empty_product_rejected(field):
    with pytest.raises(ValidationError):
        PoolRules(**{field: ["- _ -"]})


def move(db, kind, row, old, new):
    from app.customer.models import CustomerObjectOwnership
    db.add(CustomerObjectOwnership(object_type=kind, object_id=row.id, storage_customer_id=old.id,
        current_customer_id=new.id, ownership_version=1, last_change_proposal_id=1,
        last_action_type="split", created_at=NOW, updated_at=NOW))
    db.flush()


def test_orders_contacts_conversations_and_dnc_follow_logical_owner(db):
    from app.customer.models import CustomerAnnotation
    _seed_user(db)
    old, order, _, point, conversation = seed_candidate(db)
    new = _account(db, "NEW")
    new.primary_country_code = "US"
    db.flush()
    for kind, row in [("order", order), ("contact_point", point), ("conversation", conversation)]:
        move(db, kind, row, old, new)
    assert [i["account"].id for i in run(db)[0]] == [new.id]
    annotation = CustomerAnnotation(customer_id=old.id, annotation_type="do_not_contact", status="active",
        content_schema_version="v1", content_json={"text":"stop"}, policy_scope_type="global",
        policy_effective_at=NOW-timedelta(days=1), visibility="customer_team", data_classification="internal_business",
        authored_by=1)
    db.add(annotation)
    db.flush()
    move(db, "annotation", annotation, old, new)
    assert not run(db)[0]
    assert public_pool_service.is_development_denied(db, new.id, "source", "public_pool")
    assert not public_pool_service.is_development_denied(db, old.id, "source", "public_pool")


def test_active_tasks_reuse_current_owner_only(db):
    _seed_user(db)
    old, *_ = seed_candidate(db)
    new = _account(db, "NEW")
    def ensure(account, ref):
        return public_pool_service.ensure_research_task(db, customer_id=account.id, task_type="public_pool",
            source_ref_type="public_pool_batch", source_ref_id=ref, research_policy_version="pool-v1",
            input_snapshot={"customer_id":account.id}, selection_reason=[], tier="T3", created_by=1)
    task, _ = ensure(old, "1")
    move(db, "research_task", task, old, new)
    replacement, created = ensure(old, "2")
    assert created and replacement.id != task.id
    reused, created = ensure(new, "3")
    assert not created and reused.id == task.id
    with pytest.raises(ConflictError, match="已转属"):
        ensure(old, "1")


def test_orchestrator_ends_read_snapshot_and_locks_roots_before_selection(db):
    from sqlalchemy import event
    _seed_user(db)
    seed_candidate(db)
    batch, _ = public_pool_service.prepare_batch(db, {"policy_version":"pool-test", "profile_conditions":PoolRules().model_dump(), "quotas_json":PoolQuotas().model_dump()}, 1)
    batch_id = batch.id
    assert db.in_transaction()  # prepare's refresh opened a read snapshot.
    old_transaction = db.get_transaction()
    reads = []
    def capture(state):
        if state.is_select:
            reads.append((str(state.statement), state.statement._for_update_arg is not None))
    event.listen(db, "do_orm_execute", capture)
    try:
        public_pool_service.generate_batch(db, {"policy_version":"pool-test", "profile_conditions":PoolRules().model_dump(), "quotas_json":PoolQuotas().model_dump()}, 1)
    finally:
        event.remove(db, "do_orm_execute", capture)
    assert not old_transaction.is_active
    locked_index = next(i for i, (sql, lock) in enumerate(reads) if 'ark_sales_public_pool_batches' in sql and lock)
    assert 'ark_customer_accounts' in reads[locked_index + 1][0] and reads[locked_index + 1][1]


def test_execution_rejects_and_preserves_flushed_writes(db):
    _seed_user(db)
    account, *_ = seed_candidate(db)
    batch, _ = public_pool_service.prepare_batch(db, {"policy_version":"pool-test", "profile_conditions":PoolRules().model_dump(), "quotas_json":PoolQuotas().model_dump()}, 1)
    account.display_name = "Keep my edit"
    db.flush()
    assert not db.new and not db.dirty and not db.deleted
    with pytest.raises(ConflictError, match="独立事务"):
        public_pool_service.execute_batch(db, batch.id)
    assert db.in_transaction()
    db.refresh(account)
    assert account.display_name == "Keep my edit"


def test_scheduler_uses_saved_rules(db, monkeypatch):
    from contextlib import nullcontext
    from app.sales_automation import scheduler
    _seed_user(db)
    pool_rule_service.save_config(db, PoolRuleSave(rules=PoolRules(no_order_days=365), quotas=PoolQuotas(total_limit=4), expected_version=0), 1)
    seen = []
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(scheduler, "generate_batch", lambda _db, payload, actor_id: seen.append(payload) or SimpleNamespace(id=1, batch_date=NOW.date(), status="completed", result_counts={}))
    scheduler.generate_public_pool_daily_batch()
    assert seen[0]["profile_conditions"]["no_order_days"] == 365
    assert seen[0]["quotas_json"]["total_limit"] == 4
    assert seen[0]["policy_version"] == "pool-v1"


def test_migration_upgrade_downgrade_and_mysql_ddl():
    import importlib.util
    from pathlib import Path
    from io import StringIO
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'alembic/versions/138_public_pool_rules.py'
    spec = importlib.util.spec_from_file_location('pool_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert {c['name'] for c in inspect(connection).get_columns('ark_public_pool_rule_configs')} == {'id','version','rules_json','quotas_json','updated_by','updated_at'}
        migration.downgrade()
        assert 'ark_public_pool_rule_configs' not in inspect(connection).get_table_names()
    output = StringIO()
    migration.op = Operations(MigrationContext.configure(dialect_name='mysql', opts={'as_sql':True, 'output_buffer':output}))
    migration.upgrade()
    assert 'updated_by INTEGER UNSIGNED' in output.getvalue()
    assert 'FOREIGN KEY(updated_by) REFERENCES ark_users (id)' in output.getvalue()


def test_rule_lock_contention_returns_retryable_conflict(db, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Query
    def busy(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception(1205, "lock timeout"))
    monkeypatch.setattr(Query, "one_or_none", busy)
    with pytest.raises(ConflictError, match="正在被修改"):
        pool_rule_service.save_config(db, PoolRuleSave(rules=PoolRules(), quotas=PoolQuotas(), expected_version=0), 1)
    assert not db.in_transaction()
