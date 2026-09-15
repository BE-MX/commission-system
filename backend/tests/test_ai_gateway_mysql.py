"""Real MySQL current-read, migration and multi-session admission gates.

Enable only against an isolated loopback test server using
AI_GATEWAY_TEST_MYSQL_URL. Creates/removes its own random test schema; never
loads the application's configured database or alters an existing schema.
"""

from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.ai_gateway import admin_service, service
from app.ai_gateway.auth import hash_key
from app.ai_gateway.errors import GatewayError
from app.ai_gateway.models import GatewayApp, GatewayRequest
from app.ai_gateway.schemas import AppPatch
from app.auth.models import ArkUser
from tests.test_ai_gateway import payload, seed


class TestSettings(BaseSettings):
    __test__ = False
    AI_GATEWAY_TEST_MYSQL_URL: str = ''


@pytest.fixture
def mysql_engine():
    raw = TestSettings().AI_GATEWAY_TEST_MYSQL_URL
    if not raw:
        pytest.skip('requires isolated loopback AI_GATEWAY_TEST_MYSQL_URL')
    url = make_url(raw)
    if url.host not in ('127.0.0.1', 'localhost', '::1') or url.database:
        pytest.fail('test URL must be loopback with no database selected')
    schema = 'ark_ai_gateway_test_' + uuid4().hex[:16]
    control = create_engine(url)
    with control.begin() as connection:
        connection.execute(text(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4'))
    engine = create_engine(url.set(database=schema), isolation_level='REPEATABLE READ', pool_size=24, max_overflow=0)
    try:
        with engine.begin() as connection:
            # Production ark_users.id is unsigned (ORM is historically signed).
            connection.execute(text('''CREATE TABLE ark_users (
                id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL, password_hash VARCHAR(128) NOT NULL,
                real_name VARCHAR(50) NOT NULL, email VARCHAR(100), phone VARCHAR(20),
                dingtalk_id VARCHAR(100), wx_id VARCHAR(100), okki_department_id BIGINT,
                okki_department_name VARCHAR(100), avatar_url VARCHAR(500),
                is_active BOOL NOT NULL, must_change_password BOOL NOT NULL,
                last_login_at DATETIME, last_login_ip VARCHAR(45),
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, deleted_at DATETIME
            ) ENGINE=InnoDB'''))
            for table in (AiProvider.__table__, AiPreset.__table__, AiCallLog.__table__):
                table.create(connection)
            migration_path = Path(__file__).parents[1] / 'alembic/versions/146_ai_site_gateway.py'
            spec = spec_from_file_location('gateway_migration', migration_path)
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
        yield engine
    finally:
        engine.dispose()
        # Only the schema generated in this fixture is eligible for removal.
        assert schema.startswith('ark_ai_gateway_test_') and len(schema) == 36
        with control.begin() as connection:
            connection.execute(text(f'DROP DATABASE `{schema}`'))
        control.dispose()


@pytest.fixture
def mysql_site(mysql_engine):
    with Session(mysql_engine) as db:
        return seed(db)


def parallel_admit(engine, site, count=20, request_id=None):
    barrier = Barrier(count)
    def worker(_):
        with Session(engine) as db:
            # Establish an old RR snapshot before competing for the app lock.
            db.execute(select(GatewayApp.id)).all()
            barrier.wait(timeout=10)
            try:
                service.admit(db, hash_key(site[0]['api_key']), request_id or str(uuid4()), payload())
                return 'admitted'
            except GatewayError as exc:
                return exc.error
    with ThreadPoolExecutor(max_workers=count) as executor:
        return list(executor.map(worker, range(count)))


@pytest.mark.parametrize('config,expected,error', [
    ({'daily_limit': 1, 'rpm_limit': 100, 'concurrency_limit': 20}, 1, 'daily_limit_exceeded'),
    ({'daily_limit': 100, 'rpm_limit': 1, 'concurrency_limit': 20}, 1, 'rate_limit_exceeded'),
    ({'daily_limit': 100, 'rpm_limit': 100, 'concurrency_limit': 2}, 2, 'concurrency_limit_exceeded'),
])
def test_current_read_serializes_limits(mysql_engine, mysql_site, config, expected, error):
    with Session(mysql_engine) as db:
        admin_service.update_app(db, mysql_site[0]['id'], AppPatch(**config), mysql_site[1])
    results = parallel_admit(mysql_engine, mysql_site)
    assert results.count('admitted') == expected
    assert results.count(error) == 20 - expected
    with Session(mysql_engine) as db:
        assert db.query(GatewayRequest).count() == expected


def test_duplicate_id_only_admitted_once(mysql_engine, mysql_site):
    results = parallel_admit(mysql_engine, mysql_site, request_id=str(uuid4()))
    assert results.count('admitted') == 1
    assert results.count('duplicate_request') == 19


@pytest.mark.parametrize('operation,error', [('rotate', 'invalid_api_key'), ('disable', 'app_disabled'), ('grant', 'preset_not_allowed'), ('owner', 'app_disabled')])
def test_changes_beat_old_snapshot(mysql_engine, mysql_site, operation, error):
    with Session(mysql_engine) as stale:
        stale.execute(select(GatewayApp.id)).all()
        stale.execute(select(GatewayRequest.id)).all()
        with Session(mysql_engine) as admin:
            if operation == 'rotate':
                admin_service.rotate_key(admin, mysql_site[0]['id'], mysql_site[1])
            elif operation == 'disable':
                admin_service.update_app(admin, mysql_site[0]['id'], AppPatch(is_enabled=False), mysql_site[1])
            elif operation == 'owner':
                admin.execute(text('UPDATE ark_users SET is_active = 0'))
                admin.commit()
            else:
                from app.ai_gateway.models import GatewayAppPreset
                service.lock_app(admin, mysql_site[0]['id'])
                admin.query(GatewayAppPreset).delete()
                admin.commit()
        with pytest.raises(GatewayError) as exc:
            service.admit(stale, hash_key(mysql_site[0]['api_key']), str(uuid4()), payload())
        assert exc.value.error == error


def test_migration_foreign_keys_and_indexes(mysql_engine):
    inspector = inspect(mysql_engine)
    columns = {c['name']: c for c in inspector.get_columns('ark_ai_gateway_apps')}
    assert columns['owner_user_id']['type'].unsigned
    assert len(inspector.get_foreign_keys('ark_ai_gateway_requests')) == 2
    assert {i['name'] for i in inspector.get_indexes('ark_ai_gateway_requests')} >= {
        'idx_ai_gateway_app_created', 'idx_ai_gateway_app_status', 'uq_ai_gateway_request',
    }
