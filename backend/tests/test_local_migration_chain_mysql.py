"""Real empty-schema migration and guarded 126 cutover on disposable MySQL.

All approvals and absent worker instances below are synthetic test fixtures.
They do not certify a production maintenance window. No gate is mocked.
"""
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from secrets import token_bytes
from uuid import uuid4
import json
import os
import subprocess
import sys
import re

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, event, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from app.core.time import beijing_now_aware, beijing_today
from app.customer.cutover_service import (
    CUTOVER_EVIDENCE_ROOT, KNOWN_WRITER_CATEGORIES, build_suppression_manifest,
    canonical_json_bytes, load_frozen_customer_physical_contract,
    verify_expected_customer_table_state,
)
from tests.test_inventory_mysql import MySQLTestSettings, isolated_mysql_url
import hashlib

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@pytest.fixture
def chain_database():
    raw = MySQLTestSettings().COMMERCE_TEST_MYSQL_URL
    if not raw:
        pytest.skip("requires isolated loopback COMMERCE_TEST_MYSQL_URL")
    url = isolated_mysql_url(raw)
    if url.port != 33079:
        pytest.fail("full-chain tests require disposable loopback MySQL port 33079 with no database")
    suffix = uuid4().hex[:16]
    schema = "ark_chain_test_" + suffix
    writer = "ark_chain_" + suffix
    control = create_engine(url, hide_parameters=True)
    engine = create_engine(url.set(database=schema), hide_parameters=True)
    task_env = dict(os.environ)
    task_env.update(COMMISSION_DB_HOST=url.host, COMMISSION_DB_PORT=str(url.port),
        COMMISSION_DB_USER=url.username, COMMISSION_DB_PASSWORD=url.password,
        COMMISSION_DB_NAME=schema, SCHEDULER_ENABLED="false", TRANSACTION_MODE="local",
        ARK_TIME_MIGRATION_MAINTENANCE="1")
    logs = ROOT / "tmp/local-migration-chain" / schema
    logs.mkdir(parents=True)

    def run(command, **kwargs):
        result = subprocess.run(command, cwd=BACKEND, env=task_env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180)
        output = result.stdout + result.stderr
        (logs / f"alembic-{len(list(logs.glob('*.log'))):02d}.log").write_text(output, encoding="utf-8")
        if result.returncode:
            pytest.fail(f"Migration failed; retained logs in {logs}\n{output[-4500:]}")
        return result

    try:
        with control.begin() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.exec_driver_sql(f"CREATE USER '{writer}'@'localhost' ACCOUNT LOCK")
            conn.exec_driver_sql(f"GRANT INSERT, UPDATE, DELETE ON `{schema}`.* TO '{writer}'@'localhost'")
            conn.exec_driver_sql(f"REVOKE INSERT, UPDATE, DELETE ON `{schema}`.* FROM '{writer}'@'localhost'")
        yield engine, writer + "@localhost", run, logs
    finally:
        engine.dispose()
        with control.begin() as conn:
            # Both identifiers were generated here; no supplied database/user is removed.
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{schema}`")
            conn.exec_driver_sql(f"DROP USER IF EXISTS '{writer}'@'localhost'")
            assert conn.scalar(text("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=:schema"), {"schema": schema}) == 0
            assert conn.scalar(text("SELECT COUNT(*) FROM mysql.user WHERE User=:user AND Host='localhost'"), {"user": writer}) == 0
        result_path = logs / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_bytes())
            result["schema_dropped_after_test"] = True
            result["writer_dropped_after_test"] = True
            result_path.write_text(json.dumps(result), encoding="utf-8")
        control.dispose()


def evidence(db, script, principal, nonce):
    now = beijing_now_aware()
    report = script.build_preflight_report(db)
    inventory_hash = report["inventory"]["inventory_sha256"]
    bindings = {"inventory_sha256": inventory_hash, "preflight_report_sha256": report["report_sha256"]}
    directory = CUTOVER_EVIDENCE_ROOT / nonce
    directory.mkdir(parents=True)

    def artifact(label, value):
        payload = canonical_json_bytes(value) + b"\n"
        path = directory / f"{label}-{hashlib.sha256(payload).hexdigest()}.json"
        path.write_bytes(payload)
        return path.relative_to(CUTOVER_EVIDENCE_ROOT).as_posix(), hashlib.sha256(payload).hexdigest()

    sources = []
    for kind in ("okki", "alibaba", "provider"):
        path, _ = artifact("source-" + kind, {"schema_version": 1, "source_kind": kind,
            "source_namespace": kind, "source_account_key": "synthetic-empty-" + nonce,
            "exported_at": now.isoformat(), "approved_at": now.isoformat(), "rows": [], "confirmed_empty": True})
        sources.append({"artifact_path": path})
    hmac_key = token_bytes(48)
    suppression = build_suppression_manifest(db, {"sources": sources}, hmac_key, "synthetic-v1", **bindings, now=now).to_dict()
    instance_path, instance_hash = artifact("instances", {
        "schema_version": 1, "artifact_kind": "writer_instance_inventory", **bindings,
        "instances": [{"category": category, "instance_id": "synthetic-absent-" + category,
            "db_principal": principal} for category in KNOWN_WRITER_CATEGORIES],
        "approved_at": now.isoformat(), "approved_by": "isolated-test-fixture",
        "approval_detail": "Synthetic harness owns this random schema; application and workers were never launched",
        "writer_principals": [principal]})
    # Read actual live grants, roles and CURRENT_USER rather than fixture claims.
    from app.customer.cutover_service import _read_mysql_principal_privileges
    live = _read_mysql_principal_privileges(db, [principal])
    privilege = {"schema_version": 1, "artifact_kind": "writer_privilege_revocation", **bindings,
        "migration_principal": live["current_principal"], "writer_principals": [principal],
        "privilege_snapshot": live["privilege_snapshot"], "checked_at": now.isoformat(),
        "instance_inventory_artifact_sha256": instance_hash,
        "evidence_detail": "Synthetic writer DML grants revoked and independently read back on loopback MySQL"}
    privilege["evidence_sha256"] = digest(privilege)
    privilege_path, privilege_hash = artifact("privileges", privilege)
    writer_paths = []
    for category in KNOWN_WRITER_CATEGORIES:
        path, _ = artifact("stop-" + category, {"category": category, "instance_id": "synthetic-absent-" + category,
            "stopped": True, "checked_at": now.isoformat(), **bindings,
            "instance_inventory_artifact_sha256": instance_hash,
            "evidence_detail": "No application or worker launched for this owned isolated schema; live writer grants revoked"})
        writer_paths.append(path)
    db.rollback()
    active = db.scalar(text("SELECT COUNT(*) FROM information_schema.innodb_trx"))
    assert active == 0
    transaction_path, _ = artifact("transactions", {"schema_version": 1,
        "artifact_kind": "active_transaction_snapshot", "count": active, "checked_at": now.isoformat(),
        **bindings, "instance_inventory_artifact_sha256": instance_hash,
        "evidence_detail": "Actual loopback information_schema.innodb_trx enumerated after rollback"})
    fence_path, _ = artifact("fence", {"schema_version": 1, "artifact_kind": "maintenance_fence",
        "token": "synthetic-fence-" + nonce, **bindings, "instance_inventory_artifact_sha256": instance_hash,
        "writer_privilege_revocation_artifact_sha256": privilege_hash,
        "issued_at": now.isoformat(), "expires_at": (now + timedelta(minutes=4)).isoformat(),
        "approval_detail": "Synthetic schema exclusively owned by test; no process or admission can restore revoked writer grants"})
    writer_manifest = {"instance_inventory_artifact": instance_path, "writer_artifacts": writer_paths,
        "active_transaction_artifact": transaction_path, "maintenance_fence_artifact": fence_path,
        "writer_privilege_revocation_artifact": privilege_path}
    policy = {"schema_version": 1, "artifact_type": "target_profile_policy_backfill", "migration_revision": "126",
        "approved_at": now.isoformat(), "confirmed_empty": True, "profiles": []}
    policy["artifact_sha256"] = digest(policy)
    physical = load_frozen_customer_physical_contract()
    resource = json.loads((BACKEND / "alembic/versions/126_unified_customer_domain_schema.json").read_bytes())
    marker = {"approved": True, **bindings, "suppression_manifest_sha256": suppression["manifest_sha256"],
        "writer_manifest_sha256": digest(writer_manifest), "writer_privilege_revocation_artifact_sha256": privilege_hash,
        "physical_schema_contract_sha256": physical["contract_sha256"],
        "target_profile_physical_contract_sha256": resource["target_profile_physical_contract"]["contract_sha256"],
        "target_profile_policy_backfill_sha256": policy["artifact_sha256"], "nonce": nonce,
        "expires_at": (now + timedelta(minutes=4)).isoformat()}
    marker_path, _ = artifact("synthetic-approval", marker)
    return dict(preflight_report=report, suppression_manifest=suppression,
        stopped_writer_manifest=writer_manifest, expected_inventory_sha256=inventory_hash,
        approved_marker_path=CUTOVER_EVIDENCE_ROOT / marker_path,
        suppression_hmac_key=hmac_key, physical_schema_contract=physical,
        target_profile_policy_backfill=policy)


def test_empty_chain_guarded_cutover_and_legacy_invoice_preservation(chain_database):
    engine, principal, run, logs = chain_database
    # The auth and DingTalk tables predate Alembic. Install the repository's
    # original CREATE-only bootstrap, never latest ORM and never seeded users.
    bootstrap = []
    with engine.begin() as conn:
        for filename in ("auth_init.sql", "dingtalk_init.sql"):
            payload = (ROOT / "database" / filename).read_text(encoding="utf-8")
            for match in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+`(\w+)`\s*\(.*?;", payload, re.S):
                conn.exec_driver_sql(match.group(0))
                bootstrap.append(match.group(1))
    assert set(bootstrap) == {"ark_users", "ark_roles", "ark_permissions", "ark_role_permissions",
        "ark_user_roles", "ark_refresh_tokens", "ark_login_logs", "dingtalk_callback_log", "dingtalk_message_log"}
    (logs / "bootstrap.json").write_text(json.dumps(bootstrap), encoding="utf-8")
    run([sys.executable, "-m", "alembic", "upgrade", "125_invoice_integration"])
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "125_invoice_integration"
        legacy = Table("ark_invoices", MetaData(), autoload_with=conn)
        conn.execute(legacy.insert(), {"id": 9001, "invoice_no": "SYNTHETIC-LEGACY-9001",
            "customer_id": "legacy-customer-1", "customer_name": "Synthetic legacy buyer",
            "invoice_date": beijing_today(), "total_amount": 123.45, "status": "synced",
            "xiaoman_order_id": "synthetic-order-1"})
        before = dict(conn.execute(text("SELECT * FROM ark_invoices WHERE id=9001")).mappings().one())
        item = Table("ark_invoice_items", MetaData(), autoload_with=conn)
        conn.execute(item.insert(), {"id": 9002, "invoice_id": 9001, "product_id": 77,
            "product_name": "Synthetic legacy hair", "product_display": "Legacy hair",
            "net_weight_grams": "20", "model": "Legacy Model", "color": "#1",
            "length": "18", "quantity": 3, "price_per_piece": 41.15, "total_price": 123.45})
        before_item = dict(conn.execute(text("SELECT * FROM ark_invoice_items WHERE id=9002")).mappings().one())
        users = Table("ark_users", MetaData(), autoload_with=conn)
        conn.execute(users.insert(), {"id": 9001, "username": "synthetic-legacy-seller",
            "password_hash": "unused", "real_name": "Synthetic legacy seller"})
        cases = Table("ark_aftersales_cases", MetaData(), autoload_with=conn)
        from tests.test_aftersales_workflow import _payload
        legacy_case = _payload().model_dump()
        legacy_case.update(id=9001, case_no="SYNTHETIC-AS-9001", creator_user_id=9001,
            creator_name_snapshot="Synthetic legacy seller", current_status="approved",
            selected_actions_json=[{"code": "return_inspection"}], requires_return=True)
        conn.execute(cases.insert(), {key: value for key, value in legacy_case.items() if key in cases.c})
        media = Table("ark_aftersales_evidence", MetaData(), autoload_with=conn)
        conn.execute(media.insert(), {"id": 9001, "case_id": 9001, "evidence_type": "image",
            "original_filename": "synthetic.jpg", "storage_path": "synthetic/legacy.jpg",
            "mime_type": "image/jpeg", "file_size": 10, "uploaded_by_user_id": 9001})
        legacy_snapshots = {name: dict(conn.execute(text(f"SELECT * FROM {name} WHERE id=9001")).mappings().one())
            for name in ("ark_aftersales_cases", "ark_aftersales_evidence")}
    spec = spec_from_file_location("chain_cutover_script", ROOT / "scripts/customer_domain_cutover.py")
    script = module_from_spec(spec)
    spec.loader.exec_module(script)
    nonce = "synthetic-chain-" + uuid4().hex
    with Session(engine) as db:
        arguments = evidence(db, script, principal, nonce)
        script.apply_reset(db=db, subprocess_runner=run, **arguments)
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "126"
        assert verify_expected_customer_table_state(db, arguments["physical_schema_contract"])
        db.rollback()
        contract = json.loads((CUTOVER_EVIDENCE_ROOT / f"migration-contract-{nonce}.json").read_bytes())
        proof_path = CUTOVER_EVIDENCE_ROOT / contract["ddl_proof_path"]
        receipt_path = CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]
        assert script.verify_after(db=db, preflight_report=arguments["preflight_report"],
            suppression_manifest=arguments["suppression_manifest"], writer_manifest=arguments["stopped_writer_manifest"],
            approved_marker=json.loads(arguments["approved_marker_path"].read_bytes()),
            ddl_proof=json.loads(proof_path.read_bytes()), ddl_proof_path=proof_path,
            execution_receipt=json.loads(receipt_path.read_bytes()), execution_receipt_path=receipt_path,
            physical_schema_contract=arguments["physical_schema_contract"],
            target_profile_policy_backfill=arguments["target_profile_policy_backfill"])
    run([sys.executable, "-m", "alembic", "upgrade", "173_task_center"])
    from app.customer.models import CustomerAccount
    from app.core.time import beijing_now
    with Session(engine) as db:
        customer = CustomerAccount(customer_code="CHAIN-OLD-CUSTOMER", display_name="Synthetic existing customer",
            entity_type="registered_company", identity_status="verified", relationship_stage="active_customer",
            relationship_stage_changed_at=beijing_now(), relationship_stage_reason="synthetic-existing",
            record_status="active", identity_confidence=1, profile_completeness=100, profile_input_seq=1)
        db.add(customer)
        db.commit()
        existing_customer_id = customer.id
        existing_customer = dict(db.execute(text("SELECT * FROM ark_customer_accounts WHERE id=:id"),
            {"id": customer.id}).mappings().one())
        from tests.test_customer_workflow import _source_record
        preserved_source = _source_record(db, customer, record_id=91001)
        db.commit()
        preserved_source_id = preserved_source.id
    with engine.begin() as conn:
        prior_order = Table('ark_customer_orders', MetaData(), autoload_with=conn)
        prior_item = Table('ark_customer_order_items', MetaData(), autoload_with=conn)
        conn.execute(prior_order.insert(), dict(id=91001, customer_id=existing_customer_id, source_system='okki',
            source_account_key='schema-preservation', external_order_id='PRESERVED-CUSTOM-ORDER',
            order_no='Original full number', currency='USD', amount_original='1000', amount_usd='1000',
            is_valid_business_order=False, invalid_reason='synthetic-preserved',
            source_record_id=preserved_source_id, source_hash='e'*64, synced_at=beijing_now(),
            created_at=beijing_now(), updated_at=beijing_now()))
        conn.execute(prior_item.insert(), dict(id=91001, order_id=91001, external_item_id='PRESERVED-CUSTOM-GROUP',
            product_name='Original generic custom', product_family='F'*128, quantity='1', quantity_unit='pcs',
            unit_price='1000', line_amount='1000', item_type='bulk', source_record_id=preserved_source_id,
            item_fingerprint='f'*64, created_at=beijing_now(), updated_at=beijing_now()))
        before_customer_item = dict(conn.execute(text('SELECT * FROM ark_customer_order_items WHERE id=91001')).mappings().one())
    with engine.begin() as conn:
        old_payment = Table('synced_payment', MetaData(), autoload_with=conn)
        conn.execute(old_payment.insert(), dict(id=9001, payment_id='CHAIN-UNSCALED-PRESERVATION',
            order_id='LEGACY-FX-ORDER', customer_id='LEGACY-FX-CUSTOMER', payment_date='1990-01-01',
            payment_amount='123.45', service_fee='1.23', exchange_rate='650.123456', real_amount_rmb='802.59'))
        before_payment = dict(conn.execute(text('SELECT * FROM synced_payment WHERE id=9001')).mappings().one())
    run([sys.executable, "-m", "alembic", "upgrade", "head"])
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == heads[0]
        after = dict(conn.execute(text("SELECT * FROM ark_invoices WHERE id=9001")).mappings().one())
        assert {key: after[key] for key in before} == before
        after_item = dict(conn.execute(text("SELECT * FROM ark_invoice_items WHERE id=9002")).mappings().one())
        assert {key: after_item[key] for key in before_item} == before_item
        assert after_item["local_sku_id"] is None
        # Main's published display grouping and warehouse instructions remain
        # intact alongside the new native commerce fields.
        assert after["inspection_requirement"] == "single"
        assert after_item["group_id"] is not None
        group = conn.execute(text("SELECT invoice_id, name FROM ark_invoice_item_groups WHERE id=:id"),
            {"id": after_item["group_id"]}).mappings().one()
        assert group["invoice_id"] == 9001
        assert group["name"] == str(before_item["created_at"])[:10]
        assert after["transaction_mode"] == "legacy"
        assert after["local_customer_id"] is None
        assert conn.scalar(text("SELECT COUNT(*) FROM ark_stock_ledger")) == 0
        assert conn.scalar(text("SELECT COUNT(*) FROM ark_invoice_commerce_events")) == 0
        for name, snapshot in legacy_snapshots.items():
            migrated = dict(conn.execute(text(f"SELECT * FROM {name} WHERE id=9001")).mappings().one())
            assert {key: migrated[key] for key in snapshot} == snapshot
        assert conn.scalar(text("SELECT local_invoice_item_id FROM ark_aftersales_cases WHERE id=9001")) is None
        migrated_customer = dict(conn.execute(text("SELECT * FROM ark_customer_accounts WHERE id=:id"),
            {"id": existing_customer_id}).mappings().one())
        assert migrated_customer == existing_customer
        after_payment = dict(conn.execute(text('SELECT * FROM synced_payment WHERE id=9001')).mappings().one())
        assert {key: after_payment[key] for key in before_payment} == before_payment
        assert set(after_payment) - set(before_payment) == {"source"}
        assert after_payment["source"] == "okki"
        fx_column = next(row for row in inspect(conn).get_columns('synced_payment') if row['name'] == 'exchange_rate')
        assert fx_column['type'].precision == 18 and fx_column['type'].scale == 8
        assert any(row['column_names'] == ['local_invoice_item_id'] for row in inspect(conn).get_unique_constraints('ark_customer_order_items'))
        assert any(row['constrained_columns'] == ['local_invoice_item_id'] and row['referred_table'] == 'ark_invoice_items'
            for row in inspect(conn).get_foreign_keys('ark_customer_order_items'))
        item_columns = {row['name']: row for row in inspect(conn).get_columns('ark_customer_order_items')}
        assert not item_columns['projection_role']['nullable'] and item_columns['historical_alias_id']['nullable']
        assert any(row['constrained_columns'] == ['historical_alias_id']
            and row['referred_table'] == 'ark_customer_order_items' and row['options']['ondelete'] == 'RESTRICT'
            for row in inspect(conn).get_foreign_keys('ark_customer_order_items'))
        assert any(row['name'] == 'ck_customer_item_projection_role'
            for row in inspect(conn).get_check_constraints('ark_customer_order_items'))
        preserved_item = dict(conn.execute(text('SELECT * FROM ark_customer_order_items WHERE id=91001')).mappings().one())
        assert {key: preserved_item[key] for key in before_customer_item} == before_customer_item
        assert preserved_item['projection_role'] == 'active' and preserved_item['historical_alias_id'] is None
        for table, column in [('ark_customer_order_items', 'product_family'), ('ark_customer_order_batch_map', 'product_family'),
                ('ark_customer_reorder_windows', 'product_family'), ('ark_customer_list_projections', 'primary_product_family')]:
            assert next(row for row in inspect(conn).get_columns(table) if row['name'] == column)['type'].length == 256
        projection_columns = {row['name']: row for row in inspect(conn).get_columns('ark_commission_event_projections')}
        assert all(projection_columns[f'{role}_commission_rmb']['nullable'] for role in ('salesperson', 'supervisor', 'second_supervisor'))
        opening_columns = {row['name']: row for row in inspect(conn).get_columns('ark_commerce_migration_records')}
        opening_unique = inspect(conn).get_unique_constraints('ark_commerce_migration_records')
        opening_fks = inspect(conn).get_foreign_keys('ark_commerce_migration_records')
        for column, target in [('local_invoice_id', 'ark_invoices'), ('local_customer_order_id', 'ark_customer_orders')]:
            assert opening_columns[column]['nullable']
            assert any(row['column_names'] == [column] for row in opening_unique)
            assert any(row['constrained_columns'] == [column] and row['referred_table'] == target
                and row['options']['ondelete'] == 'RESTRICT' for row in opening_fks)
    native_result = native_business_on_migrated_schema(engine)
    import_result = reviewed_import_on_migrated_schema(engine)
    inventory_opening_result = inventory_openings_on_migrated_schema(engine)
    from tests.commerce_finance_mysql_scenarios import verify_finance_opening
    finance_opening_result = verify_finance_opening(engine)
    from tests.commerce_order_mysql_scenarios import verify_order_opening
    order_opening_result = verify_order_opening(engine)
    from tests.commerce_responsibility_mysql_scenarios import verify_responsibilities
    responsibility_result = verify_responsibilities(engine)
    (logs / "result.json").write_text(json.dumps({"head": heads[0], "nonce": nonce,
        "contract": str(CUTOVER_EVIDENCE_ROOT / f"migration-contract-{nonce}.json"),
        "preserved_legacy_invoice": 9001, "preserved_legacy_item": 9002,
        "preserved_legacy_aftersales_case": 9001, "preserved_legacy_aftersales_media": 9001,
        "preserved_existing_customer": existing_customer_id, "native_business": native_result,
        "preserved_legacy_scaled_payment": 9001,
        "reviewed_source_import": import_result,
        "inventory_openings": inventory_opening_result,
        "finance_openings": finance_opening_result,
        "order_openings": order_opening_result,
        "material_and_custom_responsibilities": responsibility_result,
        "schema_dropped_after_test": False}), encoding="utf-8")


def transaction_mirror_guard(schema):
    attempts = []
    pattern = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|TABLE|REFERENCES)\s+"
        r"(?:`?\w+`?\s*\.\s*)?`?okki_[a-z_]+\b|\blsordertest`?\s*\.|(?<!\w)"
        + re.escape(schema) + r"`?\s*\.", re.I)

    def reject(_conn, _cursor, statement, _parameters, _context, _many):
        if pattern.search(statement):
            attempts.append(statement)
            raise AssertionError("Native business attempted a transaction mirror query")

    return reject, attempts


@pytest.mark.parametrize("statement", [
    "SELECT * FROM `other_schema`.`orders`", "SELECT * FROM other_schema.orders",
    "SELECT * FROM okki_orders", "SELECT * FROM okki_receipts",
])
def test_native_query_guard_detects_configured_schema_and_transaction_tables(statement):
    reject, attempts = transaction_mirror_guard("other_schema")
    with pytest.raises(AssertionError, match="transaction mirror"):
        reject(None, None, statement, None, None, False)
    assert attempts == [statement]


def test_native_query_guard_allows_local_external_identity_columns():
    reject, attempts = transaction_mirror_guard("other_schema")
    reject(None, None, "INSERT INTO ark_users (okki_user_id) VALUES (%s)", None, None, False)
    reject(None, None, "SELECT ark_users.okki_user_id FROM ark_users", None, None, False)
    assert attempts == []


def reviewed_import_on_migrated_schema(engine):
    """Actual 188 FKs, RR replay, binary source IDs and CI catalog codes."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import func
    from app.auth.models import ArkUser
    from app.catalog.models import CatalogExternalIdentity
    from app.commerce_migration.models import MigrationBatch, MigrationRecord
    from app.commerce_migration.schemas import ImportManifest
    from app.commerce_migration.service import apply_manifest, preview
    from app.finance.models import FinanceEvent
    from app.inventory.models import StockLedger
    from app.invoice.models import InvoiceCommerceEvent
    from tests.test_commerce_migration import manifest, case_sku_manifest
    from copy import deepcopy
    body = manifest()
    with Session(engine) as db:
        user_id = db.scalar(select(ArkUser.id).where(ArkUser.username == 'chain-native-seller'))
        before = [db.scalar(select(func.count()).select_from(model)) for model in (StockLedger, FinanceEvent, InvoiceCommerceEvent)]
        assert inspect(engine).get_foreign_keys('ark_commerce_migration_records')
    user = {'sub': str(user_id), 'roles': ['super_admin'], 'permissions': []}
    barrier = Barrier(2)
    def import_worker(_):
        with Session(engine) as db:
            db.scalar(select(func.count()).select_from(MigrationRecord))  # Establish old RR view.
            barrier.wait(timeout=10)
            try:
                result = apply_manifest(db, body, user)
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(import_worker, range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MigrationBatch)) == 1
        assert db.scalar(select(func.count()).select_from(MigrationRecord)) == 2
        assert db.scalar(select(func.count()).select_from(CatalogExternalIdentity)) == 1
        after = [db.scalar(select(func.count()).select_from(model)) for model in (StockLedger, FinanceEvent, InvoiceCommerceEvent)]
        assert before == after
        changed = body.model_dump(mode='json')
        changed.update(batch_key='case-distinct', catalog=[], archives=[
            dict(object_type='order', external_id='Order-A', snapshot={'paid': 1, ' amount': ' 100.00 ', 'amount ': '200.00'}),
            dict(object_type='order', external_id='order-a', snapshot={'paid': 2})])
        distinct = ImportManifest.model_validate(changed)
        assert preview(db, distinct)['can_apply']
        distinct_result = apply_manifest(db, distinct, user); db.commit()
        assert len({row['record_id'] for row in distinct_result['archives']}) == 2
        assert db.get(MigrationRecord, distinct_result['archives'][0]['record_id']).snapshot == changed['archives'][0]['snapshot']
        apply_manifest(db, ImportManifest.model_validate({**changed, 'batch_key': 'tenant-case', 'tenant': 'tenant-a'}), user)
        db.commit()
        assert db.scalar(select(func.count()).select_from(MigrationRecord)) == 6
        # Same catalog code under the real MySQL collation must never hide a
        # second specification or bind two source SKUs to the wrong master.
        code_case = case_sku_manifest().model_copy(update={'batch_key': 'sku-case-conflict'})
        assert any(row['code'] == 'manifest_sku_conflict' for row in preview(db, code_case)['conflicts'])
        with pytest.raises(ValueError, match='冲突'):
            apply_manifest(db, code_case, user)
        for include_existing in (False, True):
            changed = body.model_dump(mode='json')
            other = deepcopy(changed['catalog'][0])
            other['external_sku_id'] = 'remote-S2'
            other['product']['code'] = 'M-P2'
            other['sku']['code'] = 'M-S2'
            changed.update(batch_key=f'product-split-{include_existing}', archives=[],
                catalog=([changed['catalog'][0], other] if include_existing else [other]))
            split = ImportManifest.model_validate(changed)
            assert any(row['code'] == 'external_product_conflict' for row in preview(db, split)['conflicts'])
            with pytest.raises(ValueError, match='冲突'):
                apply_manifest(db, split, user)
        assert db.scalar(select(func.count()).select_from(MigrationBatch)) == 3
        assert db.scalar(select(func.count()).select_from(CatalogExternalIdentity)) == 1
        assert before == [db.scalar(select(func.count()).select_from(model)) for model in (StockLedger, FinanceEvent, InvoiceCommerceEvent)]
        collations = dict(db.execute(text("SELECT CONCAT(TABLE_NAME, '.', COLUMN_NAME), COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND ((TABLE_NAME='ark_commerce_migration_records' AND COLUMN_NAME IN ('source','tenant','external_id')) OR (TABLE_NAME='ark_catalog_external_identities' AND COLUMN_NAME IN ('source','tenant','external_product_id','external_sku_id')))")).all())
        assert len(collations) == 7 and set(collations.values()) == {'utf8mb4_bin'}
        db.rollback()
    return {'batch_count': 3, 'source_record_count': 6, 'concurrent_identical_results': True,
            'economic_counts_unchanged': True, 'case_sensitive_sources_preserved': True,
            'case_insensitive_code_conflict_rejected': True, 'cross_batch_product_split_rejected': True}


def inventory_openings_on_migrated_schema(engine):
    """RR races and historical material acknowledgment on real migrated tables."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from decimal import Decimal
    from app.auth.models import ArkUser
    from app.catalog.models import CatalogProduct, CatalogSku
    from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
    from app.commerce_migration import inventory_service as service
    from app.inventory.models import Warehouse, StockBalance, StockLedger
    from app.inventory.schemas import DocumentCreate
    from app.inventory.service import post_document
    from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger
    from sqlalchemy import func
    with Session(engine) as db:
        user_id = db.scalar(select(ArkUser.id).where(ArkUser.username == 'chain-native-seller'))
        assert user_id is not None
        warehouse_id = db.scalar(select(Warehouse.id).order_by(Warehouse.id))
        product = CatalogProduct(code='OPEN-P', name='Opening product', display_name='Opening')
        db.add(product); db.flush()
        sku = CatalogSku(code='OPEN-S', product_id=product.id, color='Black', size='18')
        competing = CatalogSku(code='OPEN-RACE', product_id=product.id, color='Black', size='20')
        master = SemifinishedMaterial(material_code='CHAIN-OPEN-M1', size='18', color_code='Black', color_key='black')
        db.add_all([sku, competing, master]); db.flush()
        db.add(InventoryBalance(material_id=master.id, on_hand_grams=Decimal('899.875'), version=2))
        for key, amount, after in [('chain-old-opening', '1000.000', '1000.000'), ('chain-old-issue', '-100.125', '899.875')]:
            db.add(InventoryLedger(material_id=master.id, movement_type='inbound' if amount[0] != '-' else 'outbound',
                quantity_grams=Decimal(amount), on_hand_after=Decimal(after), reserved_after=0,
                business_type='verified_history', idempotency_key=key, created_by=user_id))
        db.commit()
        sku_id, competing_id, material_id = sku.id, competing.id, master.id
    user = {'sub': str(user_id), 'roles': ['super_admin'], 'permissions': []}
    raw = dict(batch_key='mysql-inventory-opening', source='verified-export', tenant='tenant-A', cutover_date='2026-10-03',
        evidence_sha256='b' * 64, review_reference='Synthetic inventory opening',
        stocks=[dict(external_id='bucket-1', mode='initialize', warehouse_id=warehouse_id,
            local_sku_id=sku_id, quality='sellable', on_hand=10)],
        materials=[dict(external_id='material-1', mode='acknowledge_existing', material_id=material_id, on_hand_grams='899.875')])
    body = InventoryOpeningManifest.model_validate(raw)
    def concurrent_import(bodies):
        barrier = Barrier(2)
        def worker(candidate):
            with Session(engine) as db:
                db.scalar(select(func.count()).select_from(StockBalance))  # Old RR view.
                barrier.wait(timeout=10)
                try:
                    result = service.apply_manifest(db, candidate, user); db.commit()
                    return result
                except ValueError:
                    db.rollback()
                    return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, bodies))
    same = concurrent_import([body, body])
    assert same[0] == same[1] and same[0] != 'rejected'
    with Session(engine) as db:
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.sku_id == sku_id)) == 10
        assert db.scalar(select(func.count()).select_from(StockLedger).where(StockLedger.sku_id == sku_id)) == 1
        assert db.scalar(select(InventoryBalance.on_hand_grams).where(InventoryBalance.material_id == material_id)) == Decimal('899.875')
        assert db.scalar(select(func.count()).select_from(InventoryLedger).where(InventoryLedger.material_id == material_id)) == 2
        post_document(db, DocumentCreate(idempotency_key='chain-later-receipt', kind='receipt', reason='Later local receipt',
            source_type='purchase', source_id='chain-P1', lines=[dict(warehouse_id=warehouse_id, sku_id=sku_id, quantity=2)]), actor_id=user_id)
        db.commit()
        assert service.apply_manifest(db, body, user) == same[0]
        replay = service.apply_manifest(db, body.model_copy(update={'batch_key': 'mysql-inventory-replay'}), user)
        assert replay['stocks'] == same[0]['stocks']
        db.commit()
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.sku_id == sku_id)) == 12
    races = []
    for index, amount in enumerate([4, 7]):
        races.append(InventoryOpeningManifest.model_validate({**raw, 'batch_key': f'mysql-target-race-{index}',
            'source': f'export-{index}', 'materials': [], 'stocks': [dict(external_id=f'bucket-{index}', mode='initialize',
                warehouse_id=warehouse_id, local_sku_id=competing_id, quality='sellable', on_hand=amount)]}))
    results = concurrent_import(races)
    assert results.count('rejected') == 1
    with Session(engine) as db:
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.sku_id == competing_id)) in {4, 7}
        assert db.scalar(select(func.count()).select_from(StockLedger).where(StockLedger.sku_id == competing_id)) == 1
    from tests.commerce_opening_mysql_scenarios import verify_semifinished_opening_races
    ordinary_races = verify_semifinished_opening_races(engine, user_id)
    return dict(concurrent_same_request_once=True, concurrent_same_target_different_sources_rejected=True,
        replay_after_new_activity_keeps_on_hand=12, historical_material_on_hand='899.875', historical_material_ledger_count=2,
        ordinary_receive_adjust_races=ordinary_races)


def native_business_on_migrated_schema(engine):
    """Exercise actual migrated FKs; registered test image is not a storage test."""
    from app.auth.models import ArkUser
    from app.catalog.models import CatalogProduct, CatalogSku
    from app.customer.models import CustomerAccount
    from app.finance.models import BankAccount, Currency
    from app.finance import service as finance_service
    from app.inventory.models import Warehouse, StockBalance, StockLedger
    from app.aftersales.models import AfterSalesExecution
    from app.aftersales.local_execution import receive_return
    from app.core.time import beijing_now
    from tests.test_aftersales_local import shipped_case, command as return_command
    from tests.test_inventory_local import balance

    from app.core.config import get_settings
    reject_transaction_mirrors, mirror_attempts = transaction_mirror_guard(get_settings().BUSINESS_DB_NAME)

    event.listen(engine, "before_cursor_execute", reject_transaction_mirrors)
    try:
        with Session(engine) as db:
            product = CatalogProduct(code="CHAIN-P", name="Synthetic hair", display_name="Synthetic hair", kind="hair")
            customer = CustomerAccount(customer_code="CHAIN-C", display_name="Synthetic buyer",
                entity_type="registered_company", identity_status="verified", relationship_stage="active_customer",
                relationship_stage_changed_at=beijing_now(), relationship_stage_reason="test",
                record_status="active", identity_confidence=1, profile_completeness=100, profile_input_seq=1)
            user_row = ArkUser(username="chain-native-seller", real_name="Synthetic seller", password_hash="unused")
            db.add_all([product, customer, user_row, Currency(code="CNY", name="CNY", rate_to_cny=1),
                Currency(code="USD", name="USD", rate_to_cny=7)])
            db.flush()
            sku = CatalogSku(product_id=product.id, code="CHAIN-S", color="black", size="18", unit="piece")
            warehouses = [Warehouse(code=code, name=code) for code in ("CHAIN-MAIN", "CHAIN-OTHER")]
            bank = BankAccount(code="CHAIN-USD", name="Synthetic bank", currency="USD")
            db.add_all([sku, *warehouses, bank])
            db.flush()
            user = {"sub": str(user_row.id), "roles": ["super_admin"], "permissions": ["invoice:write"]}
            # Real persisted rollout gates, while the synthetic historical
            # order keeps its old route. No force-local global switch.
            from app.commerce_transition import service as transition
            from app.commerce_transition.models import PlatformPolicy
            from app.finance.transition_identity import reconcile_legacy_identity, unmapped_legacy_money
            policy = db.get(PlatformPolicy, 1)
            transition.set_writer_receipt(db, 'synthetic-migrated-schema-fixture', 1, 'compatible',
                {'no_external_process_started_for_owned_schema': True})
            transition.set_policy(db, phase='transition', expected_version=policy.version,
                inventory_evidence={'all_writers': ['synthetic-migrated-schema-fixture']})
            transition.register_resource_scope(db, route='local', resource_kind='sku', resource_key=str(sku.id),
                warehouse_key='*', evidence={'checkpoint': 'synthetic-empty-new-SKU',
                    'old_responsibilities_cleared': True, 'writers_enforced': True})
            historic_bank = BankAccount(code='SYNTHETIC-OLD-ACCOUNT', name='Synthetic historical account', currency='USD')
            db.add(historic_bank)
            db.flush()
            old_domain = transition.register_bank_domain(db, subject_key='leshine', account_key='SYNTHETIC-OLD-ACCOUNT',
                channel='bank_statement', legacy_identity_complete=False, enforced=True, exclusive_route='legacy',
                bank_account_ids=[historic_bank.id],
                evidence={'original_synthetic_fixture_bank_records': True})
            for reference in unmapped_legacy_money(db):
                kind, original_id = reference.split(':')
                reconcile_legacy_identity(db, domain_id=old_domain.id,
                    transaction_id=f'synthetic-statement-{kind}-{original_id}',
                    receipt_id=int(original_id) if kind == 'legacy-receipt' else None,
                    batch_id=int(original_id) if kind == 'legacy-batch' else None,
                    statement_reference='Synthetic original fixture statement; not production evidence', actor_id=user_row.id)
            transition.register_bank_domain(db, subject_key='leshine', account_key=bank.code,
                channel='bank_statement', legacy_identity_complete=True, enforced=True, exclusive_route='local',
                bank_account_ids=[bank.id],
                evidence={'synthetic_empty_local_bank_account': True})
            stock = sku, warehouses
            case, invoice, settlement_item, warehouse, user, _ = shipped_case(db, stock, (customer, user, bank))
            body = return_command(case, settlement_item, warehouse)
            execution = receive_return(db, case.id, body, user)
            assert receive_return(db, case.id, body, user).id == execution.id
            assert db.get(AfterSalesExecution, execution.id).case_id == case.id
            assert balance(db, warehouse, sku).on_hand == 7
            assert balance(db, warehouse, sku).reserved == 0
            quarantine = db.scalar(select(StockBalance).where(StockBalance.sku_id == sku.id, StockBalance.quality == "quarantine"))
            assert quarantine.on_hand == 1 and quarantine.reserved == 0
            assert invoice.commerce_status == "shipped" and invoice.items[0].stock_shipped_quantity == 3
            from app.invoice.settlement_models import ReceiptBatch
            payment = db.scalar(select(ReceiptBatch).where(ReceiptBatch.local_customer_id == customer.id))
            assert payment.allocated_amount == 94
            assert finance_service.describe(db, payment, user)["available_amount"] == "6.00"
            db.flush()
            targets = db.execute(text("SELECT id, kind, amount, paid_amount, adjustment_amount FROM ark_receivables WHERE invoice_id=:id"),
                {"id": invoice.id}).mappings().all()
            assert {(row["kind"], row["amount"], row["paid_amount"], row["adjustment_amount"]) for row in targets} == {
                ("goods", 93, 93, 0), ("freight", 1, 1, 0)}
            receipts = db.execute(text("SELECT id,receivable_id,amount,reversed_amount,bank_charge,reversed_bank_charge,status,collect_status "
                "FROM ark_receipts WHERE invoice_id=:id AND batch_id=:batch"),
                {"id": invoice.id, "batch": payment.id}).mappings().all()
            assert len(receipts) == 2
            assert all(row["status"] == "active" and row["collect_status"] == 1 for row in receipts)
            assert sum(row["amount"] - row["reversed_amount"] for row in receipts) == payment.allocated_amount == 94
            assert sum(row["bank_charge"] - row["reversed_bank_charge"] for row in receipts) == 3
            apps = db.execute(text("SELECT receipt_id,amount,released_amount,bank_charge,released_bank_charge,status "
                "FROM ark_settlement_applications WHERE settlement_id=:id"),
                {"id": settlement_item.settlement_id}).mappings().all()
            assert len(apps) == 2 and all(row["status"] == "applied" for row in apps)
            assert sum(row["amount"] - row["released_amount"] for row in apps) == 94
            assert sum(row["bank_charge"] - row["released_bank_charge"] for row in apps) == 3
            for receipt in receipts:
                used = [app for app in apps if app["receipt_id"] == receipt["id"]]
                assert sum(app["amount"] - app["released_amount"] for app in used) == receipt["amount"] - receipt["reversed_amount"]
                assert sum(app["bank_charge"] - app["released_bank_charge"] for app in used) == receipt["bank_charge"] - receipt["reversed_bank_charge"]
                target = next(row for row in targets if row["id"] == receipt["receivable_id"])
                assert target["paid_amount"] == receipt["amount"] - receipt["reversed_amount"]
            for row in db.scalars(select(StockBalance).where(StockBalance.sku_id == sku.id)):
                ledger = db.scalars(select(StockLedger).where(StockLedger.warehouse_id == row.warehouse_id,
                    StockLedger.sku_id == row.sku_id, StockLedger.quality == row.quality)).all()
                assert sum(entry.on_hand_delta for entry in ledger) == row.on_hand
                assert sum(entry.reserved_delta for entry in ledger) == row.reserved
            db.commit()
            assert mirror_attempts == []
            return {"invoice_id": invoice.id, "case_id": case.id, "return_execution_id": execution.id,
                "shipped_quantity": 3, "sellable_on_hand": 7, "quarantine_on_hand": 1,
                "allocated_amount": "94.00", "available_payment": "6.00", "transaction_mirror_queries": len(mirror_attempts)}
    finally:
        event.remove(engine, "before_cursor_execute", reject_transaction_mirrors)


@pytest.mark.parametrize("raw", [
    "mysql+pymysql://fixture@outside.invalid:33079/",
    "mysql+pymysql://fixture@127.0.0.1:33079/shared_database",
    "mysql+pymysql://fixture@127.0.0.1:33079/?host=outside.invalid",
    "mysql+pymysql://fixture@127.0.0.1:33079/?database=shared_database",
    "mysql+mysqldb://fixture@127.0.0.1:33079/",
])
def test_isolation_rejects_connection_target_overrides_without_connecting(raw):
    with pytest.raises(pytest.fail.Exception, match="loopback"):
        isolated_mysql_url(raw)


@pytest.mark.parametrize('method', ['get', 'post'])
def test_order_http_guard_counts_attempts_even_when_domain_swallows_failure(monkeypatch, method):
    import httpx
    from tests import commerce_order_mysql_scenarios as scenarios
    monkeypatch.setattr(scenarios.event, 'listen', lambda *args: None)
    monkeypatch.setattr(scenarios.event, 'remove', lambda *args: None)
    def swallowed(_engine):
        try:
            getattr(httpx, method)('https://outside.invalid/never-sent')
        except AssertionError:
            return {'swallowed': True}
    monkeypatch.setattr(scenarios, '_verify_order_opening', swallowed)
    with pytest.raises(AssertionError, match='Called 1 times'):
        scenarios.verify_order_opening(object())


@pytest.mark.parametrize("source", ["migration", "orm"])
def test_public_pool_singleton_check_is_enforced_without_auto_increment(chain_database, source):
    engine, _principal, _run, _logs = chain_database
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE ark_users (id INT UNSIGNED PRIMARY KEY)")
        if source == "migration":
            spec = spec_from_file_location("pool_migration", BACKEND / "alembic/versions/138_public_pool_rules.py")
            migration = module_from_spec(spec)
            spec.loader.exec_module(migration)
            # Same current MySQL DDL policy used by env.py; the published
            # revision itself remains byte-identical to the main branch.
            policy_spec = spec_from_file_location('test_singleton_ddl', BACKEND / 'alembic/singleton_ddl.py')
            policy = module_from_spec(policy_spec)
            policy_spec.loader.exec_module(policy)
            policy.install()
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        else:
            from app.sales_automation.models import PublicPoolRuleConfig
            PublicPoolRuleConfig.__table__.create(conn)
        columns = inspect(conn).get_columns("ark_public_pool_rule_configs")
        assert next(column for column in columns if column["name"] == "id")["autoincrement"] is False
        command = text("INSERT INTO ark_public_pool_rule_configs (id,version,rules_json,quotas_json,updated_at) VALUES (:id,1,'{}','{}',:at)")
        conn.execute(command, {"id": 1, "at": beijing_now_aware().replace(tzinfo=None)})
        with pytest.raises(DBAPIError) as failure:
            with conn.begin_nested():
                conn.execute(command, {"id": 2, "at": beijing_now_aware().replace(tzinfo=None)})
        assert failure.value.orig.args[0] == 3819
        assert conn.scalar(text("SELECT COUNT(*) FROM ark_public_pool_rule_configs")) == 1
