"""Actual pending DDL on owned MySQL with explicit synthetic historical anchors."""
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.core import config as application_config


def test_deployed_186_upgrade_preserves_records(mysql_engine, monkeypatch):
    engine = mysql_engine
    statements = [
        'CREATE TABLE ark_users (id INTEGER UNSIGNED PRIMARY KEY)',
        'CREATE TABLE ark_domestic_customers (id INTEGER PRIMARY KEY)',
        'CREATE TABLE ark_domestic_order_items (id INTEGER PRIMARY KEY)',
        'CREATE TABLE ark_domestic_item_units (id BIGINT PRIMARY KEY)',
        'CREATE TABLE ark_domestic_customer_ledger (id BIGINT PRIMARY KEY)',
        "CREATE TABLE ark_domestic_customer_requests (id BIGINT PRIMARY KEY, request_type VARCHAR(20), CONSTRAINT ck_dom_request_type CHECK (request_type IN ('recharge','adjust')))",
        'CREATE TABLE ark_order_portal_accounts (id BIGINT PRIMARY KEY, password_hash VARCHAR(255))',
        'CREATE TABLE ark_whatsapp_accounts (account_uid VARCHAR(80) PRIMARY KEY, status VARCHAR(20))',
        'CREATE TABLE ark_whatsapp_conversations (id BIGINT PRIMARY KEY, body VARCHAR(80))',
        'CREATE TABLE ark_whatsapp_messages (id BIGINT PRIMARY KEY, body VARCHAR(80))',
        'CREATE TABLE ark_whatsapp_bind_sessions (id BIGINT PRIMARY KEY, qr_code_url TEXT, last_payload JSON)',
        'CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)',
    ]
    with engine.begin() as c:
        for sql in statements:
            c.exec_driver_sql(sql)
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('186_portal_announcement_merge')")
        c.exec_driver_sql("INSERT INTO ark_users VALUES (7)")
        c.exec_driver_sql("INSERT INTO ark_order_portal_accounts VALUES (1,'synthetic-password-hash')")
        c.exec_driver_sql("INSERT INTO ark_domestic_customer_requests VALUES (1,'recharge')")
        c.exec_driver_sql("INSERT INTO ark_whatsapp_accounts VALUES ('wa_synthetic','error')")
        c.exec_driver_sql("INSERT INTO ark_whatsapp_messages VALUES (1,'synthetic retained message')")
        c.exec_driver_sql("INSERT INTO ark_whatsapp_conversations VALUES (1,'synthetic retained conversation')")
        c.exec_driver_sql("INSERT INTO ark_whatsapp_bind_sessions VALUES (1,'ephemeral',JSON_OBJECT('qr','ephemeral','qr_code_url','ephemeral','retained','audit'))")
    monkeypatch.setattr(application_config, 'get_settings', lambda: SimpleNamespace(commission_db_url=engine.url))
    backend = Path(__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    command.upgrade(cfg, 'head')
    with engine.begin() as c:
        assert c.scalar(text('SELECT version_num FROM alembic_version')) == '195_main_portal_merge'
        assert c.scalar(text('SELECT password_hash FROM ark_order_portal_accounts')) == 'synthetic-password-hash'
        assert c.scalar(text('SELECT body FROM ark_whatsapp_messages')) == 'synthetic retained message'
        assert c.execute(text('SELECT provider,consent_state,ai_egress_allowed FROM ark_whatsapp_accounts')).one() == ('whatsapp-web.js','pending',0)
        assert c.scalar(text("SELECT JSON_UNQUOTE(JSON_EXTRACT(last_payload,'$.retained')) FROM ark_whatsapp_bind_sessions")) == 'audit'
        assert c.scalar(text('SELECT qr_code_url FROM ark_whatsapp_bind_sessions')) is None
        c.exec_driver_sql("INSERT INTO ark_domestic_customer_requests (id,request_type) VALUES (2,'receipt')")
    schema = inspect(engine)
    assert set(('ark_domestic_shipments','ark_domestic_shipment_lines','ark_domestic_shipment_units',
                'ark_domestic_receipt_allocations','ark_whatsapp_body_grants','ark_whatsapp_message_sources',
                'ark_whatsapp_assistant_runs','ark_navigation_preferences')).issubset(schema.get_table_names())
    command.upgrade(cfg, 'head')
    with engine.connect() as c:
        assert c.scalar(text('SELECT COUNT(*) FROM ark_domestic_customer_requests')) == 2
